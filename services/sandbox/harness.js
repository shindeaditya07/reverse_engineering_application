'use strict';
// Runs inside the sandbox. Reads one job on stdin: {module, function, inputs}. Calls the function
// with each input twice, on fresh copies, and prints ONE line of JSON on stdout:
// {"observations":[{"outcome":"value|throws|unserializable|async|nondeterministic", ...}]}.
// Anything the legacy module prints is sent to stderr, so stdout holds only this line.
// This file is ours and trusted; it makes no claim about the legacy code beyond what it observed.

const path = require('path');
const out = process.stdout.write.bind(process.stdout);
process.stdout.write = (chunk, ...rest) => process.stderr.write(chunk, ...rest);

function fail(code) {
  out(JSON.stringify({ error: code }) + '\n', () => process.exit(0));
}

let input = '';
process.stdin.setEncoding('utf8');
process.stdin.on('data', (d) => { input += d; });
process.stdin.on('end', () => {
  let job;
  try { job = JSON.parse(input); } catch (e) { return fail('bad_job'); }
  const root = path.resolve('/app');
  const file = path.resolve(root, String(job.module));
  if (!file.startsWith(root + path.sep)) return fail('bad_path');
  if (!/^[A-Za-z_$][A-Za-z0-9_$]*$/.test(String(job.function))) return fail('bad_function');
  if (!Array.isArray(job.inputs) || job.inputs.length > 50) return fail('bad_job');

  let mod;
  try { mod = require(file); } catch (e) { return fail('load_failed'); }
  const fn = mod && mod[job.function];
  if (typeof fn !== 'function') return fail('not_a_function');

  function once(args) {
    let result;
    try { result = fn.apply(undefined, JSON.parse(JSON.stringify(args))); }
    catch (e) {
      const name = e && e.constructor && /^[A-Za-z_$][A-Za-z0-9_$]*$/.test(e.constructor.name) ? e.constructor.name : 'Error';
      return { outcome: 'throws', error: name };
    }
    if (result && typeof result.then === 'function') {
      result.then(() => {}, () => {});
      return { outcome: 'async' };
    }
    let text;
    try {
      text = JSON.stringify(result, (k, v) => {
        if (typeof v === 'number' && !Number.isFinite(v)) throw new Error('x');
        if (typeof v === 'bigint' || typeof v === 'function' || typeof v === 'symbol') throw new Error('x');
        return v;
      });
    } catch (e) { return { outcome: 'unserializable' }; }
    if (text === undefined) return { outcome: 'unserializable' };
    return { outcome: 'value', value: JSON.parse(text) };
  }

  const observations = job.inputs.map((args) => {
    const first = once(args);
    const second = once(args);
    if (JSON.stringify(first) !== JSON.stringify(second)) return { outcome: 'nondeterministic' };
    return first;
  });
  // Exit as soon as the line is flushed: a legacy timer must not keep the container alive.
  out(JSON.stringify({ observations }) + '\n', () => process.exit(0));
});
