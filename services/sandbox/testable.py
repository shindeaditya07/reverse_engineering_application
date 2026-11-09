"""Which modules can be tested at all (TST-1.2, TST-1.6, SEC-1.2). Deterministic, no model.

A module is testable when it and every file it requires through relative paths load nothing but
other snapshot files and a short list of pure Node built-ins. A module that needs a package cannot
be tested: dependencies come from a lockfile only (TST-1.6), and many packages (a database
driver, an HTTP client) would reach a system the sandbox forbids (SEC-1.2). A module that reaches
files, the network, processes or the clock through a built-in is also not testable. The reason is
a fixed sentence, stated as an Unknown claim (CLM-1.7), never dropped silently.
"""

import re
from dataclasses import dataclass

from tree_sitter import Node

from services.codeanalysis.analyze import (
    Module,
    _declared_functions,
    _exports,
    _is_test,
    _parse,
    _require_spec,
    _resolve,
    _text,
    _walk,
)
from services.discovery.agent import Finding
from services.discovery.inventory import build_inventory
from services.evidence import SnapshotReader

# Built-ins that only compute. Anything else (fs, net, child_process, os, ...) is refused.
PURE_BUILTINS = frozenset("assert buffer events path querystring string_decoder url util".split())
LOCKFILES = ("package-lock.json", "npm-shrinkwrap.json", "yarn.lock", "pnpm-lock.yaml")
_NAME = re.compile(r"^[A-Za-z_$][A-Za-z0-9_$]*$")
_PACKAGE = re.compile(r"^(@[a-z0-9._-]+/)?[a-z0-9._-]+$")


@dataclass(frozen=True)
class FunctionTarget:
    path: str
    name: str
    params: tuple[str, ...]
    start: int
    end: int
    source: str  # the function's own lines, for the proposal prompt (SEC-2.2: untrusted)


@dataclass(frozen=True)
class Assessment:
    targets: tuple[FunctionTarget, ...]
    untestable: tuple[tuple[str, str], ...]  # (path, reason)
    skipped_functions: int  # exported functions with async, default or destructured parameters
    findings: tuple[Finding, ...]  # Unknown claims (CLM-1.7)


def _own_reasons(module: Module, paths: frozenset[str]) -> tuple[list[str], list[str]]:
    """(reasons this file alone is untestable, relative files it requires)."""
    reasons: list[str] = []
    relative: list[str] = []
    for node in _walk(module.root):
        if node.type == "import_statement":
            reasons.append("it uses ES module syntax, and only CommonJS is supported in v1")
        is_require, spec = _require_spec(node)
        if not is_require:
            continue
        if spec is None:
            reasons.append("it loads a module with a path computed at run time")
        elif spec.startswith("."):
            target = _resolve(spec, module.path, paths)
            if target is None:
                reasons.append("it requires a file that is not in the snapshot")
            else:
                relative.append(target)
        else:
            name = spec[5:] if spec.startswith("node:") else spec
            top = "/".join(name.split("/")[: 2 if name.startswith("@") else 1])
            if name in PURE_BUILTINS:
                continue
            if spec.startswith("node:") or top in _ALL_BUILTINS:
                shown = top if _NAME.match(top) else "a built-in"
                reasons.append(
                    f"it uses the Node built-in {shown}, which reaches files, the network, "
                    "processes or the clock"
                )
            else:
                shown = top if _PACKAGE.match(top) else "a package"
                reasons.append(
                    f"it needs the package {shown}, and dependencies are fetched from a "
                    "lockfile only (TST-1.6)"
                )
    return sorted(set(reasons)), sorted(set(relative))


_ALL_BUILTINS = frozenset(
    (
        "assert async_hooks buffer child_process cluster console constants crypto dgram "
        "diagnostics_channel dns domain events fs http http2 https inspector module net os path "
        "perf_hooks process punycode querystring readline repl stream string_decoder sys timers "
        "tls trace_events tty url util v8 vm wasi worker_threads zlib"
    ).split()
)


def _simple_params(fn: Node) -> tuple[str, ...] | None:
    """Plain identifier parameters, or None (defaults, rest, destructuring, async)."""
    if fn.children and fn.children[0].type == "async":
        return None
    params = fn.child_by_field_name("parameters")
    if params is None:
        single = fn.child_by_field_name("parameter")
        nodes = [single] if single is not None else []
    else:
        nodes = list(params.named_children)
    if any(n.type != "identifier" for n in nodes):
        return None
    names = tuple(_text(n) for n in nodes)
    return names if all(_NAME.match(n) for n in names) else None


def assess(reader: SnapshotReader, paths: list[str]) -> Assessment:
    inventory = build_inventory(reader, paths)
    all_paths = frozenset(paths)
    modules: dict[str, Module] = {}
    unparsed: list[tuple[str, str]] = []
    for path in inventory.first_party_sources:
        if _is_test(path) or not path.endswith((".js", ".cjs")):
            continue
        parsed = _parse(reader, path)
        if isinstance(parsed, str):
            unparsed.append((path, "it could not be parsed"))
        else:
            modules[path] = Module(path, parsed)
    own = {p: _own_reasons(m, all_paths) for p, m in modules.items()}

    def closure(path: str) -> tuple[str, str] | None:
        """(file, reason) of the first obstacle in the module or what it requires."""
        seen: set[str] = set()
        stack = [path]
        while stack:
            here = stack.pop()
            if here in seen:
                continue
            seen.add(here)
            if here not in own:
                return here, "it requires a file that cannot be read as plain JavaScript"
            reasons, relative = own[here]
            if reasons:
                return here, reasons[0]
            stack.extend(relative)
        return None

    targets: list[FunctionTarget] = []
    untestable: list[tuple[str, str]] = list(unparsed)
    skipped = 0
    for path, module in sorted(modules.items()):
        exported = _exports(module)
        declared = _declared_functions(module)
        functions = [
            (n, declared[local]) for n, (local, _) in sorted(exported.items()) if local in declared
        ]
        if not functions:
            continue
        obstacle = closure(path)
        if obstacle is not None:
            where, why = obstacle
            via = "" if where == path else f" (through {where})"
            untestable.append((path, f"{why}{via}"))
            continue
        lines = reader.lines(path)
        for name, node in functions:
            fn = node.child_by_field_name("value") if node.type == "variable_declarator" else node
            params = _simple_params(fn) if fn is not None else None
            if fn is None or params is None or not _NAME.match(name):
                skipped += 1
                continue
            start, end = node.start_point[0] + 1, node.end_point[0] + 1
            if end - start + 1 > 40:
                skipped += 1
                continue
            targets.append(
                FunctionTarget(path, name, params, start, end, "\n".join(lines[start - 1 : end]))
            )
    findings = [
        Finding(
            f"sb:untestable:{path}",
            "unresolved",
            "unknown",
            f"{path} was not tested in the sandbox: {why}.",
        )
        for path, why in untestable
    ]
    needs_package = any("it needs the package" in why for _, why in untestable)
    if needs_package and "package.json" in all_paths and not any(f in all_paths for f in LOCKFILES):
        findings.append(
            Finding(
                "sb:app:no-lockfile",
                "unresolved",
                "unknown",
                "package.json is present but the snapshot has no lockfile, so no dependency can "
                "be fetched for testing (TST-1.6); modules that need a package are not tested.",
            )
        )
    return Assessment(tuple(targets), tuple(untestable), skipped, tuple(findings))
