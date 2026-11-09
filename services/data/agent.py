"""Data agent (FR-4): tables, relations and SQL lineage, deterministic, no model.

- Schema (`schema.py`): tables, columns, declared foreign keys, and relations a column name
  implies but no foreign key declares (Inferred). The same data is the ER model.
- Statements: every `db.query(...)`-style call whose SQL text can be resolved. The text may be
  a literal, a `+` chain, a template, a constant in the same file, or a parameter whose every
  call site passes a literal (that one step across a function boundary is marked Inferred).
- Lineage: a column written by two or more places (counting the schema default when an INSERT
  leaves the column out), and a schema column no statement refers to.
- Anything it cannot resolve is an Unknown claim (CLM-1.4, CLM-1.7), never an omission.

The patterns were written after the fixture was read, so the fixture score is optimistic.
"""

import re
from dataclasses import dataclass

from tree_sitter import Node

from services.codeanalysis.analyze import (
    _FUNCTIONS,
    Module,
    _ancestors,
    _cap,
    _declared_functions,
    _parse,
    _scan_module,
    _span,
    _string,
    _text,
    _walk,
)
from services.data.pii import pii_findings
from services.data.schema import ErModel, parse_schema
from services.data.sql import DYN, SqlUnreadable, Statement, analyze_sql
from services.discovery.agent import Finding
from services.discovery.inventory import build_inventory
from services.evidence import SnapshotReader

QUERY_METHODS = frozenset({"query", "queryAsync", "execute"})
_LOOKS_LIKE_SQL = re.compile(
    r"^\s*(select|insert|update|delete|replace|with|create|drop|alter)\b", re.I
)
_MAX_VARIANTS = 8
_MAX_DEPTH = 4
_METHODS = (*_FUNCTIONS, "method_definition")
Span = tuple[str, int, int]


@dataclass(frozen=True)
class Variant:
    text: str
    sources: tuple[Span, ...] = ()  # constants the text was read from
    passed_by: tuple[Span, ...] = ()  # call sites that passed a value in (cross-function step)


@dataclass(frozen=True)
class Site:
    finding_id: str
    file: str
    line: int
    statement: Statement
    own: Span  # the SQL argument
    inferred: bool


@dataclass(frozen=True)
class DataAnalysis:
    findings: tuple[Finding, ...]
    er: ErModel
    sites: tuple[Site, ...]
    unread: tuple[tuple[str, str], ...]  # files not read, stated (CLM-1.7)
    plumbing: tuple[Span, ...]  # driver calls whose SQL is a parameter: their callers are analysed


class _Resolver:
    def __init__(self, modules: dict[str, Module]) -> None:
        self.modules = modules
        self._counter = 0

    def _dynamic(self) -> Variant:
        self._counter += 1
        return Variant(f" {DYN}{self._counter}__ ")

    def variants(self, node: Node | None, module: Module, depth: int = 0) -> list[Variant]:
        if node is None or depth > _MAX_DEPTH:
            return [self._dynamic()]
        literal = _string(node)
        if literal is not None:
            return [Variant(literal)]
        if node.type == "parenthesized_expression" and node.named_children:
            return self.variants(node.named_children[0], module, depth)
        if node.type == "binary_expression":
            operator = node.child_by_field_name("operator")
            if operator is None or _text(operator) != "+":
                return [self._dynamic()]
            return self._join(
                [
                    self.variants(node.child_by_field_name("left"), module, depth),
                    self.variants(node.child_by_field_name("right"), module, depth),
                ]
            )
        if node.type == "template_string":
            parts: list[list[Variant]] = []
            for child in node.named_children:
                if child.type == "string_fragment":
                    parts.append([Variant(_text(child))])
                elif child.type == "template_substitution" and child.named_children:
                    parts.append(self.variants(child.named_children[0], module, depth))
            return self._join(parts) if parts else [Variant("")]
        if node.type == "identifier":
            return self._identifier(node, module, depth)
        return [self._dynamic()]

    def _join(self, parts: list[list[Variant]]) -> list[Variant]:
        joined = [Variant("")]
        for options in parts:
            joined = [
                Variant(a.text + b.text, a.sources + b.sources, a.passed_by + b.passed_by)
                for a in joined
                for b in options
            ]
            if len(joined) > _MAX_VARIANTS:
                return [self._dynamic()]
        return joined

    def _identifier(self, node: Node, module: Module, depth: int) -> list[Variant]:
        name = _text(node)
        for fn in _ancestors(node):
            if fn.type not in _METHODS:
                continue
            params = _params(fn)
            if name in params:
                return self._parameter(fn, params.index(name), module, depth)
        declarations = [
            d
            for d in _walk(module.root)
            if d.type == "variable_declarator"
            and d.child_by_field_name("name") is not None
            and _text(d.child_by_field_name("name")) == name  # type: ignore[arg-type]
        ]
        if len(declarations) != 1 or declarations[0].child_by_field_name("value") is None:
            return [self._dynamic()]
        found = self.variants(declarations[0].child_by_field_name("value"), module, depth + 1)
        start, end = _span(declarations[0])
        return [
            Variant(v.text, (*v.sources, (module.path, *_cap(start, end))), v.passed_by)
            for v in found
        ]

    def _parameter(self, fn: Node, index: int, module: Module, depth: int) -> list[Variant]:
        name = _function_name(fn)
        if name is None:
            return [self._dynamic()]
        out: list[Variant] = []
        for caller, call in self._call_sites(module.path, name):
            args = call.child_by_field_name("arguments")
            items = args.named_children if args else []
            if index >= len(items):
                return [self._dynamic()]
            line = _span(call)[0]
            for v in self.variants(items[index], caller, depth + 1):
                out.append(Variant(v.text, v.sources, (*v.passed_by, (caller.path, line, line))))
        if not out or len(out) > _MAX_VARIANTS:
            return [self._dynamic()]
        return out

    def _call_sites(self, path: str, name: str) -> list[tuple[Module, Node]]:
        found: list[tuple[Module, Node]] = []
        for module in self.modules.values():
            for node in _walk(module.root):
                if node.type != "call_expression":
                    continue
                callee = node.child_by_field_name("function")
                if callee is None:
                    continue
                if callee.type == "identifier":
                    here = (module.path == path and _text(callee) == name) or module.named.get(
                        _text(callee)
                    ) == (path, name)
                    if here:
                        found.append((module, node))
                elif callee.type == "member_expression":
                    obj, prop = (
                        callee.child_by_field_name("object"),
                        callee.child_by_field_name("property"),
                    )
                    if (
                        obj is not None
                        and prop is not None
                        and module.imports.get(_text(obj)) == path
                        and _text(prop) == name
                    ):
                        found.append((module, node))
        return found


def _params(fn: Node) -> list[str | None]:
    single = fn.child_by_field_name("parameter")
    if single is not None:
        return [_text(single) if single.type == "identifier" else None]
    params = fn.child_by_field_name("parameters")
    if params is None:
        return []
    return [_text(p) if p.type == "identifier" else None for p in params.named_children]


def _function_name(fn: Node) -> str | None:
    if fn.type == "function_declaration":
        name = fn.child_by_field_name("name")
        return _text(name) if name is not None else None
    holder = fn.parent
    if fn.type in _FUNCTIONS and holder is not None and holder.type == "variable_declarator":
        name = holder.child_by_field_name("name")
        return _text(name) if name is not None else None
    return None  # a method: its callers cannot be found by name


def _is_parameter(node: Node) -> bool:
    return node.type == "identifier" and any(
        fn.type in _METHODS and _text(node) in _params(fn) for fn in _ancestors(node)
    )


def _sites(modules: dict[str, Module]) -> list[tuple[Module, Node, Node, bool]]:
    """(module, call, SQL argument, is a call into a first-party wrapper) for each query call."""
    found: list[tuple[Module, Node, Node, bool]] = []
    for module in modules.values():
        for node in _walk(module.root):
            if node.type != "call_expression":
                continue
            callee = node.child_by_field_name("function")
            if callee is None or callee.type != "member_expression":
                continue
            obj, prop = callee.child_by_field_name("object"), callee.child_by_field_name("property")
            if obj is None or prop is None or _text(prop) not in QUERY_METHODS:
                continue
            args = node.child_by_field_name("arguments")
            if not args or not args.named_children:
                continue
            target = module.imports.get(_text(obj)) if obj.type == "identifier" else None
            if target is not None:
                wrapper = modules.get(target)
                if wrapper is None or _text(prop) not in _declared_functions(wrapper):
                    continue
            found.append((module, node, args.named_children[0], target is not None))
    return found


def _describe(pairs: tuple[tuple[str, str], ...]) -> str:
    return ", ".join(f"all columns of {t}" if c == "*" else f"{t}.{c}" for t, c in pairs)


def _statement_text(
    site_file: str, line: int, s: Statement, dynamic: bool, passed: tuple[Span, ...]
) -> str:
    if s.verb == "select":
        body = f"reads {_describe(s.reads) or 'no column'} from {', '.join(s.tables)}"
    elif s.verb == "insert":
        what = _describe(s.writes).replace("all columns of", "whole rows of")
        body = f"inserts into {', '.join(s.tables)} setting {what}"
    elif s.verb == "update":
        body = f"updates {_describe(s.writes)}"
        if s.reads:
            body += f"; its condition and values read {_describe(s.reads)}"
    else:
        body = f"deletes rows from {', '.join(s.tables)}"
    text = f"{site_file} line {line} {body}."
    if dynamic:
        text += " Part of the statement text is computed at run time and concatenated in."
    if passed:
        where = ", ".join(f"{f} line {a}" for f, a, _ in passed)
        text += f" A value in it is passed in from {where}."
    return text


def analyze(reader: SnapshotReader, paths: list[str]) -> DataAnalysis:
    inventory = build_inventory(reader, paths)
    skip = set(inventory.generated) | set(inventory.vendored)
    er, unread = parse_schema(reader, [p for p in paths if p not in skip])
    all_paths = frozenset(paths)
    modules: dict[str, Module] = {}
    unread_js: list[tuple[str, str]] = []
    for path in inventory.first_party_sources:
        if not path.endswith((".js", ".cjs")):
            continue
        parsed = _parse(reader, path)
        if isinstance(parsed, str):
            unread_js.append((path, parsed))
        else:
            modules[path] = Module(path, parsed)
    for module in modules.values():
        _scan_module(module, all_paths)

    resolver = _Resolver(modules)
    findings: list[Finding] = []
    sites: list[Site] = []
    plumbing: list[Span] = []
    unresolved = False
    for module, _call, arg, wrapper in sorted(
        _sites(modules), key=lambda s: (s[0].path, s[1].start_byte)
    ):
        first, last = _span(arg)
        own: Span = (module.path, *_cap(first, last))
        if not wrapper and _is_parameter(arg):
            plumbing.append((module.path, first, last))
            continue
        for number, variant in enumerate(resolver.variants(arg, module)):
            text = variant.text.strip()
            suffix = f":{number}" if number else ""
            claim_id = f"data:sql:{module.path}:{first}{suffix}"
            evidence = (own, *variant.sources, *variant.passed_by)
            if not _LOOKS_LIKE_SQL.match(text):
                if wrapper:
                    unresolved = True
                    findings.append(
                        Finding(
                            f"data:unresolved:{module.path}:{first}{suffix}",
                            "unresolved",
                            "unknown",
                            f"{module.path} line {first} runs SQL that is computed at run time, "
                            f"so what it reads or writes is not known.",
                            evidence,
                        )
                    )
                continue
            try:
                statement = analyze_sql(text)
            except SqlUnreadable as error:
                unresolved = True
                findings.append(
                    Finding(
                        f"data:unresolved:{module.path}:{first}{suffix}",
                        "unresolved",
                        "unknown",
                        f"{module.path} line {first} runs SQL this analyzer cannot read "
                        f"({error}), so what it reads or writes is not known.",
                        evidence,
                    )
                )
                continue
            if statement.dynamic_table:
                unresolved = True
                findings.append(
                    Finding(
                        f"data:unresolved:{module.path}:{first}{suffix}",
                        "unresolved",
                        "unknown",
                        f"{module.path} line {first} runs SQL whose table name is computed at "
                        f"run time, so the table is not known.",
                        evidence,
                    )
                )
                continue
            inferred = bool(variant.passed_by)
            kind = "sql_read" if statement.verb == "select" else "sql_write"
            findings.append(
                Finding(
                    claim_id,
                    kind,
                    "inferred" if inferred else "confirmed",
                    _statement_text(module.path, first, statement, DYN in text, variant.passed_by),
                    evidence,
                )
            )
            sites.append(Site(claim_id, module.path, first, statement, own, inferred))
    for path, reason in unread:
        unresolved = True
        findings.append(
            Finding(
                f"data:unread:{path}", "unresolved", "unknown", f"{path} was not read: {reason}."
            )
        )
    findings += _schema_findings(er)
    findings += pii_findings(reader, [p for p in paths if p not in skip])
    findings += _lineage(er, sites)
    if not unresolved:
        findings += _unused(er, sites)
    return DataAnalysis(
        tuple(findings), er, tuple(sites), tuple(unread + unread_js), tuple(plumbing)
    )


def _schema_findings(er: ErModel) -> list[Finding]:
    out: list[Finding] = []
    for table in er.tables:
        names = ", ".join(c.name for c in table.columns)
        keys = ", ".join(c.name for c in table.columns if c.primary_key)
        out.append(
            Finding(
                f"data:table:{table.file}:{table.name}",
                "table",
                "confirmed",
                f"{table.file} defines table {table.name} with columns {names}"
                + (f" (primary key {keys})." if keys else " (no primary key)."),
                ((table.file, table.start, table.end),),
            )
        )
    for rel in er.relations:
        pair = (
            f"{rel.table}.{', '.join(rel.columns)} -> {rel.ref_table}.{', '.join(rel.ref_columns)}"
        )
        out.append(
            Finding(
                f"data:relation:{rel.file}:{rel.table}.{'+'.join(rel.columns)}",
                "relation",
                "confirmed" if rel.declared else "inferred",
                f"{rel.file} declares a foreign key {pair}."
                if rel.declared
                else f"{rel.table}.{', '.join(rel.columns)} looks like a reference to "
                f"{rel.ref_table}.{', '.join(rel.ref_columns)} by its name, but no foreign key "
                f"is declared.",
                ((rel.file, rel.line, rel.line),),
            )
        )
    return out


def _lineage(er: ErModel, sites: list[Site]) -> list[Finding]:
    """A column written from two or more places: statements, plus the schema default when an
    INSERT leaves the column out."""
    writers: dict[tuple[str, str], list[Site]] = {}
    defaulted: dict[tuple[str, str], bool] = {}
    for site in sites:
        s = site.statement
        for written_table, written_column in s.writes:
            if written_column != "*":
                writers.setdefault((written_table, written_column), []).append(site)
        if s.verb == "insert" and any(c != "*" for _, c in s.writes):
            for table_name in s.tables:
                declared = er.table(table_name)
                written = {c for t, c in s.writes if t == table_name}
                for candidate in declared.columns if declared else ():
                    if candidate.default is not None and candidate.name not in written:
                        defaulted[(table_name, candidate.name)] = True
    out: list[Finding] = []
    for (table_name, column_name), group in sorted(writers.items()):
        table = er.table(table_name)
        column = table.column(column_name) if table else None
        default = defaulted.get((table_name, column_name), False) and column is not None
        count = len(group) + (1 if default else 0)
        if count < 2:
            continue
        evidence = [site.own for site in group]
        places = [f"{site.file} line {site.line}" for site in group]
        if default and table is not None and column is not None:
            evidence.append((table.file, column.line, column.line))
            places.append(f"the column default {column.default} at {table.file} line {column.line}")
        out.append(
            Finding(
                f"data:lineage:{table_name}.{column_name}",
                "sql_write",
                "inferred",
                f"{table_name}.{column_name} is written from {count} places: {'; '.join(places)}. "
                f"No other statement in the snapshot writes it.",
                tuple(evidence),
            )
        )
    return out


def _unused(er: ErModel, sites: list[Site]) -> list[Finding]:
    used: set[tuple[str, str]] = set()
    touched: set[str] = set()
    for site in sites:
        s = site.statement
        touched.update(s.tables)
        used.update(s.reads)
        used.update(s.writes)
        for name in s.ambiguous:
            used.update((t, name) for t in s.tables)
    out: list[Finding] = []
    for table in er.tables:
        if table.name not in touched:
            continue
        everything = (table.name, "*") in used
        for column in table.columns:
            if everything or (table.name, column.name) in used:
                continue
            out.append(
                Finding(
                    f"data:unused:{table.name}.{column.name}",
                    "column",
                    "inferred",
                    f"{table.name}.{column.name} is defined in {table.file} but no SQL "
                    f"statement in the snapshot reads or writes it.",
                    ((table.file, column.line, column.line),),
                )
            )
    return out
