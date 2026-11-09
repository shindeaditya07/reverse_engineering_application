// Parse Mermaid files with the real Mermaid parser (no browser). Not run in CI.
//   mkdir /tmp/mm && cd /tmp/mm && npm install mermaid@11.4.1 jsdom@25
//   cp <repo>/scripts/check_mermaid.mjs /tmp/mm/ && node check_mermaid.mjs file.mmd ...
// Exit code 1 if any file fails. Used to check the Diagram agent's output.
import { JSDOM } from 'jsdom';
import fs from 'fs';
const dom = new JSDOM('<!DOCTYPE html><body></body>');
globalThis.window = dom.window; for (const k of ['Element','HTMLElement','Node','DocumentFragment','HTMLTemplateElement','NodeFilter','NamedNodeMap','HTMLFormElement','DOMParser']) globalThis[k] = dom.window[k]; globalThis.document = dom.window.document;
Object.defineProperty(globalThis, 'navigator', {value: dom.window.navigator, configurable: true});
const mermaid = (await import('mermaid')).default;
mermaid.initialize({ startOnLoad: false, securityLevel: 'strict' });
let bad = 0;
for (const f of process.argv.slice(2)) {
  const text = fs.readFileSync(f, 'utf8');
  try { await mermaid.parse(text); console.log('OK  ', f); }
  catch (e) { bad++; console.log('FAIL', f, String(e.message||e).split('\n').slice(0,4).join(' | ')); }
}
process.exit(bad ? 1 : 0);
