"""Findings Discovery can state without parsing code. Every one is a line-level pattern or a
file property, so each is Inferred (CLM-1.2, CLM-1.3), except the two read from bytes, which
are exact: a file that is not UTF-8 and a file with CRLF line ends.

Generated and vendored files are classified first and never scanned for findings: citing them
is allowed only for claims about them (EVD-1.6). Discovery does not find routes, call graphs or
data flow; that is Code Analysis (FR-3), and a loop or a condition needs a parser.

The patterns were written after the fixture was read, so the score they get on the fixture is
optimistic. Treat it as a floor on what the approach needs, not a measure of it on other apps.
"""

import hashlib
import re
from dataclasses import dataclass

from services.discovery.inventory import Inventory, build_inventory
from services.evidence import SnapshotReader, Unresolved, parse_ref, resolve
from services.evidence.refs import max_excerpt_lines
from services.verifier import ClaimInput, EvidenceInput

# Reused so the line cited is the one the classifier actually matched.
from services.verifier.flags import _GENERATED_HEADER, _HEADER_LINES, _VENDORED_HEADER

NODE_BUILTINS = frozenset(
    (
        "assert async_hooks buffer child_process cluster console constants crypto dgram "
        "diagnostics_channel dns domain events fs http http2 https inspector module net os path "
        "perf_hooks process punycode querystring readline repl stream string_decoder timers tls "
        "trace_events tty url util v8 vm wasi worker_threads zlib"
    ).split()
)
_REQUIRE = re.compile(r"""\brequire\(\s*(['"])([^'"]+)\1\s*\)""")
_DYNAMIC_REQUIRE = re.compile(r"""\brequire\(\s*(?!['"][^'"]*['"]\s*\))[^)\s]""")
_TIMER = re.compile(r"\bsetInterval\s*\(|\bcron\.schedule\s*\(|\bnode-cron\b")
_HTTP_OUT = re.compile(r"\b(?:https?\.(?:request|get)|axios\.\w+|fetch)\s*\(")
_SOCKET_OUT = re.compile(r"\bnet\.(?:connect|createConnection)\s*\(")
PATTERNS = (_REQUIRE, _DYNAMIC_REQUIRE, _TIMER, _HTTP_OUT, _SOCKET_OUT)


def patterns_sha256() -> str:
    """Fingerprint of every pattern, in order. A change must be re-run and re-committed."""
    digest = hashlib.sha256()
    for pattern in PATTERNS:
        digest.update(f"{pattern.pattern}\0{pattern.flags}\n".encode())
    return digest.hexdigest()


@dataclass(frozen=True)
class Finding:
    claim_id: str
    kind: str  # an answer-key kind: dependency, job, integration, provenance, encoding
    status: str  # "confirmed" or "inferred"
    text: str
    evidence: tuple[tuple[str, int, int], ...] = ()  # (path, first line, last line)
    byte_evidence: tuple[tuple[str, int, int], ...] = ()  # (path, start byte, end byte)
    subject_paths: frozenset[str] = frozenset()


@dataclass(frozen=True)
class Discovery:
    inventory: Inventory
    findings: tuple[Finding, ...]
    unscanned: tuple[tuple[str, str], ...]  # (path, reason): stated, never silent (CLM-1.7)


def _package_name(spec: str) -> str | None:
    if spec.startswith((".", "/")) or spec.startswith("node:"):
        return None
    parts = spec.split("/")
    name = "/".join(parts[:2]) if spec.startswith("@") else parts[0]
    return None if name in NODE_BUILTINS else name


def _declared_block(reader: SnapshotReader) -> tuple[int, int] | None:
    """Line range of the "dependencies" object in package.json, if it has one."""
    lines = reader.lines("package.json")
    for number, line in enumerate(lines, 1):
        if re.match(r'\s*"dependencies"\s*:', line):
            for end in range(number, len(lines) + 1):
                if lines[end - 1].strip().startswith("}"):
                    return number, end
    return None


def _scan_lines(
    path: str, lines: list[str], declared: set[str], block: tuple[int, int] | None
) -> list[Finding]:
    out: list[Finding] = []
    for number, line in enumerate(lines, 1):
        for match in _REQUIRE.finditer(line):
            package = _package_name(match.group(2))
            if package and package not in declared and block is not None:
                out.append(
                    Finding(
                        f"disc:undeclared:{path}:{number}",
                        "dependency",
                        "inferred",
                        f"{path} requires {package}, which package.json does not declare.",
                        ((path, number, number), ("package.json", *block)),
                    )
                )
        if _DYNAMIC_REQUIRE.search(line):
            out.append(
                Finding(
                    f"disc:dynamic-require:{path}:{number}",
                    "dependency",
                    "inferred",
                    f"{path} line {number} loads a module with a computed path.",
                    ((path, number, number),),
                )
            )
        if _TIMER.search(line):
            out.append(
                Finding(
                    f"disc:timer:{path}:{number}",
                    "job",
                    "inferred",
                    f"{path} line {number} starts a recurring timer.",
                    ((path, number, number),),
                )
            )
        if _HTTP_OUT.search(line):
            out.append(
                Finding(
                    f"disc:http:{path}:{number}",
                    "integration",
                    "inferred",
                    f"{path} line {number} makes an outbound HTTP call.",
                    ((path, number, number),),
                )
            )
        if _SOCKET_OUT.search(line):
            out.append(
                Finding(
                    f"disc:socket:{path}:{number}",
                    "integration",
                    "inferred",
                    f"{path} line {number} opens an outbound network connection.",
                    ((path, number, number),),
                )
            )
    return out


def _marker_line(reader: SnapshotReader, path: str, kind: str) -> int:
    """The header line that says generated or vendored, or line 1 when the file was classified
    by its folder alone. A claim cites the line that carries its evidence."""
    pattern = _GENERATED_HEADER if kind == "generated" else _VENDORED_HEADER
    try:
        head = reader.lines(path)[:_HEADER_LINES]
    except Unresolved:
        return 1
    return next((n for n, line in enumerate(head, 1) if pattern.search(line)), 1)


def _provenance(reader: SnapshotReader, path: str, kind: str) -> Finding:
    line = _marker_line(reader, path, kind)
    return Finding(
        f"disc:{kind}:{path}",
        "provenance",
        "inferred",
        f"{path} is {kind} code, by its location or its header.",
        ((path, line, line),),
        subject_paths=frozenset({path}),
    )


def _bytes_findings(reader: SnapshotReader, path: str) -> tuple[list[Finding], bool]:
    """Exact findings read from the bytes. The bool says whether the file decodes as UTF-8."""
    data = reader.raw(path)
    try:
        data.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        return (
            [
                Finding(
                    f"disc:not-utf8:{path}",
                    "encoding",
                    "confirmed",
                    f"{path} is not valid UTF-8.",
                    byte_evidence=((path, error.start, error.end),),
                )
            ],
            False,
        )
    return [], True


def _crlf(reader: SnapshotReader, path: str) -> Finding | None:
    if b"\r\n" not in reader.raw(path):
        return None
    raw_lines = reader.raw(path).decode("utf-8-sig").split("\n")
    marked = [n for n, line in enumerate(raw_lines, 1) if line.endswith("\r")]
    if not marked:
        return None
    last = min(marked[0] + max_excerpt_lines() - 1, len(reader.lines(path)))
    return Finding(
        f"disc:crlf:{path}",
        "encoding",
        "confirmed",
        f"{path} uses CRLF line endings; line numbers here count after LF normalisation.",
        ((path, marked[0], last),),
    )


def discover(reader: SnapshotReader, paths: list[str]) -> Discovery:
    inventory = build_inventory(reader, paths)
    declared = set(inventory.declared) | set(inventory.declared_dev)
    block = _declared_block(reader) if "package.json" in paths else None
    findings: list[Finding] = [_provenance(reader, p, "generated") for p in inventory.generated]
    findings += [_provenance(reader, p, "vendored") for p in inventory.vendored]
    unscanned: list[tuple[str, str]] = []
    for path in sorted(paths):
        found, decodes = _bytes_findings(reader, path)
        findings += found
        if not decodes:
            unscanned.append((path, "undecodable"))
            continue
        crlf = _crlf(reader, path)
        if crlf:
            findings.append(crlf)
    for path in inventory.first_party_sources:
        try:
            findings += _scan_lines(path, reader.lines(path), declared, block)
        except Unresolved as error:
            if error.reason != "undecodable":
                raise
    return Discovery(inventory, tuple(findings), tuple(unscanned))


def _ref(path: str, start: int, end: int, *, unit: str) -> dict[str, object]:
    if unit == "byte":
        return {"kind": "file_range", "path": path, "start_byte": start, "end_byte": end}
    return {"kind": "file_range", "path": path, "start_line": start, "end_line": end}


def to_claim_inputs(finding: Finding, reader: SnapshotReader) -> ClaimInput:
    """The finding as the verifier takes it, with each excerpt hashed as the pipeline stores it."""
    refs = [_ref(p, s, e, unit="line") for p, s, e in finding.evidence]
    refs += [_ref(p, s, e, unit="byte") for p, s, e in finding.byte_evidence]
    evidence = []
    for ref in refs:
        found = resolve(parse_ref(ref), reader)
        evidence.append(EvidenceInput(ref, found.content_hash))
    return ClaimInput(
        finding.claim_id,
        finding.text,
        finding.status,
        "deterministic",
        tuple(evidence),
        subject_paths=finding.subject_paths,
    )
