"""Render Mermaid from extracted claims (OUT-1.1). No model, no guessing.

Inferred claims are drawn dashed and say so; Confirmed ones are solid. Unknown claims are never
drawn. Every node and edge is created through `Builder`, which refuses one with no claim key.
"""

from collections import defaultdict

from services.diagram.extract import Extracted, Flow
from services.diagram.model import Builder, Diagram, ident, label

MAX_ROUTES_SHOWN = 4


def _er(x: Extracted) -> Diagram | None:
    if not x.tables:
        return None
    b = Builder()
    b.raw("erDiagram")
    names = {t.name for t in x.tables}
    for t in sorted(x.tables, key=lambda t: t.name):
        eid = ident(t.name)
        b.node(eid, f"  {eid} {{", [t.key])
        for col in t.columns:
            pk = " PK" if col in t.primary else ""
            b.raw(f"    column {ident(col)}{pk}")
        b.raw("  }")
    for r in sorted(x.relations, key=lambda r: r.key):
        if r.table not in names or r.ref_table not in names:
            continue
        link = "}o--||" if r.declared else "}o..||"
        how = "foreign key" if r.declared else "guessed from the column name"
        b.edge(
            ident(r.table),
            ident(r.ref_table),
            f'  {ident(r.table)} {link} {ident(r.ref_table)} : "{label(r.column)} ({how})"',
            [r.key],
        )
    return Diagram("er", "Tables and relations", "\n".join(b.lines), b.mapping)


def _architecture(x: Extracted) -> Diagram | None:
    if not (x.access or x.outbound or x.routes):
        return None
    b = Builder()
    b.raw("flowchart LR")
    by_file: dict[str, list[str]] = defaultdict(list)
    routes_in: dict[str, list[str]] = defaultdict(list)
    for r in x.routes:
        by_file[r.file].append(r.key)
        routes_in[r.file] += list(r.routes)
    for a in x.access:
        by_file[a.file].append(a.key)
    for o in x.outbound:
        by_file[o.file].append(o.key)
    for path in sorted(by_file):
        shown = routes_in[path][:MAX_ROUTES_SHOWN]
        more = len(routes_in[path]) - len(shown)
        text = "<br/>".join([label(path), *(label(r) for r in shown)])
        if more > 0:
            text += f"<br/>+{more} more routes"
        fid = "f_" + ident(path)
        b.node(fid, f'  {fid}["{text}"]', by_file[path])
    tables = {t for a in x.access for t in a.tables}
    table_keys = {t.name: t.key for t in x.tables}
    for name in sorted(tables):
        tid = "t_" + ident(name)
        keys = [a.key for a in x.access if name in a.tables]
        b.node(tid, f'  {tid}[("{label(name)}")]', keys)
    merged: dict[tuple[str, str, str, str], list[str]] = defaultdict(list)
    for a in sorted(x.access, key=lambda a: a.key):
        for name in a.tables:
            merged[(a.file, name, a.verb, a.status)] += [
                a.key,
                *([table_keys[name]] if name in table_keys else []),
            ]
    for (file, name, verb, status), keys in sorted(merged.items()):
        arrow = "-.->" if status == "inferred" else "-->"
        word = verb + (" (inferred)" if status == "inferred" else "")
        src, dst = "f_" + ident(file), "t_" + ident(name)
        b.edge(src, dst, f'  {src} {arrow}|"{word}"| {dst}', keys)
    for o in sorted(x.outbound, key=lambda o: o.key):
        oid = "x_" + ident(f"{o.file}_{o.line}")
        arrow = "-.->" if o.status == "inferred" else "-->"
        b.node(oid, f'  {oid}(["{label(o.what + " at " + o.file + ":" + str(o.line))}"])', [o.key])
        b.edge("f_" + ident(o.file), oid, f"  f_{ident(o.file)} {arrow} {oid}", [o.key])
    return Diagram("architecture", "Modules, data and outside calls", "\n".join(b.lines), b.mapping)


def _workflow(f: Flow) -> Diagram:
    b = Builder()
    b.raw("flowchart TD")
    kind = {"async": "awaits", "callbacks": "nested callbacks", "promises": "promise steps"}[f.kind]
    arrow = "-.->" if f.status == "inferred" else "-->"
    prev = None
    for n, step in enumerate(f.steps, 1):
        sid = f"s{n}"
        b.node(sid, f'  {sid}["{n}. {label(step)}"]', [f.key])
        if prev:
            b.edge(prev, sid, f"  {prev} {arrow} {sid}", [f.key])
        prev = sid
    title = f"{f.name} ({f.file}:{f.line}), {kind} in source order"
    return Diagram("workflow:" + f.key, label(title, 120), "\n".join(b.lines), b.mapping)


def render(x: Extracted) -> list[Diagram]:
    out = [d for d in (_er(x), _architecture(x)) if d is not None]
    out += [_workflow(f) for f in sorted(x.flows, key=lambda f: f.key) if f.steps]
    return out
