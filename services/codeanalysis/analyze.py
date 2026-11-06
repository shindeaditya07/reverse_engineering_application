"""Code Analysis (FR-3): parse first-party JavaScript with tree-sitter and state what the syntax
tree shows. Deterministic, no model.

What it produces, and how sure it is:
- `route`: an Express route registration. Confirmed when the receiver is bound to `express()` or
  `express.Router()` in the same file and the whole path is literal (a `forEach` over a literal
  list is expanded). Inferred when a router's mount point cannot be found. Unknown when the path
  is computed at run time.
- `error_handling`: a `catch` block or a `.catch(...)` callback with no statements (Confirmed).
- `dead_code`: an exported function that nothing else in the snapshot references (Inferred: a
  reference through reflection or an unresolvable `require` cannot be excluded).
- `flow`: nested error-first callbacks, a promise chain, or an async function with several awaits
  (Confirmed; see flow.py). Control flow across steps only, not value-level data flow.
- `dependency`, Unknown: a `require` whose path is computed, so the module it loads is not
  known. Code Analysis owns this finding (Discovery does not report it).
- `unresolved`: a file that could not be parsed. Unknown (CLM-1.4, CLM-1.7), never an omission.

The call graph is built from the same pass and returned for later agents. It is not a claim.

Patterns here were written after the fixture was read, so the fixture score is optimistic.
"""

import posixpath
from collections.abc import Iterator
from dataclasses import dataclass, field
from itertools import product

import tree_sitter_javascript
from tree_sitter import Language, Node, Parser

from services.codeanalysis.flow import flow_findings
from services.discovery.agent import Finding
from services.discovery.inventory import build_inventory
from services.evidence import SnapshotReader, Unresolved
from services.evidence.refs import max_excerpt_lines

PARSER_VERSIONS = "tree-sitter 0.26 / tree-sitter-javascript 0.25"
HTTP_METHODS = frozenset("get post put patch delete all head options".split())
_PARSER = Parser(Language(tree_sitter_javascript.language()))
_TEST_DIRS = frozenset({"test", "tests", "__tests__"})
_FUNCTIONS = ("function_declaration", "function_expression", "arrow_function")


@dataclass(frozen=True)
class CallEdge:
    caller: tuple[str, str]  # (file, function name or "<module>")
    callee: tuple[str, str]
    line: int


@dataclass(frozen=True)
class Analysis:
    findings: tuple[Finding, ...]
    calls: tuple[CallEdge, ...]
    unanalyzed: tuple[tuple[str, str], ...]  # (path, reason): stated, never silent (CLM-1.7)


@dataclass
class Module:
    path: str
    root: Node
    imports: dict[str, str] = field(default_factory=dict)  # alias -> resolved file
    named: dict[str, tuple[str, str]] = field(default_factory=dict)  # local -> (file, export)
    express_names: set[str] = field(default_factory=set)
    receivers: dict[str, str] = field(default_factory=dict)  # name -> "app" | "router"
    escapes: bool = False  # the whole module object is used as a value


def _text(node: Node) -> str:
    return (node.text or b"").decode("utf-8")


def _span(node: Node) -> tuple[int, int]:
    return node.start_point.row + 1, node.end_point.row + 1


def _cap(start: int, end: int) -> tuple[int, int]:
    """A cited range is at most the excerpt limit (EVD-1.3): keep the opening lines."""
    return start, min(end, start + max_excerpt_lines() - 1)


def _walk(node: Node) -> Iterator[Node]:
    stack = [node]
    while stack:
        current = stack.pop()
        yield current
        stack.extend(reversed(current.children))


def _ancestors(node: Node) -> Iterator[Node]:
    parent = node.parent
    while parent is not None:
        yield parent
        parent = parent.parent


def _string(node: Node | None) -> str | None:
    """The value of a plain string literal, else None."""
    if node is None or node.type != "string":
        return None
    return "".join(_text(c) for c in node.children if c.type == "string_fragment")


def _is_test(path: str) -> bool:
    parts = path.split("/")
    name = parts[-1]
    return bool(_TEST_DIRS & set(parts[:-1])) or ".test." in name or ".spec." in name


def _resolve(spec: str, origin: str, paths: frozenset[str]) -> str | None:
    """A relative `require` as a file of the snapshot, or None."""
    if not spec.startswith("."):
        return None
    base = posixpath.normpath(posixpath.join(posixpath.dirname(origin), spec))
    for candidate in (base, base + ".js", base + ".cjs", posixpath.join(base, "index.js")):
        if candidate in paths:
            return candidate
    return None


def _require_spec(node: Node | None) -> tuple[bool, str | None]:
    """(is a require call, its literal argument or None when computed)."""
    if node is None or node.type != "call_expression":
        return False, None
    fn = node.child_by_field_name("function")
    if fn is None or fn.type != "identifier" or _text(fn) != "require":
        return False, None
    args = node.child_by_field_name("arguments")
    named = args.named_children if args else []
    return True, _string(named[0]) if len(named) == 1 else None


def _evaluate(node: Node | None, env: dict[str, list[str]]) -> list[str] | None:
    """Every value a path expression can take, or None if any part is computed at run time."""
    if node is None:
        return None
    literal = _string(node)
    if literal is not None:
        return [literal]
    if node.type == "identifier":
        return env.get(_text(node))
    if node.type == "parenthesized_expression" and node.named_children:
        return _evaluate(node.named_children[0], env)
    if node.type == "binary_expression" and node.child_by_field_name("operator") is not None:
        if _text(node.child_by_field_name("operator")) != "+":  # type: ignore[arg-type]
            return None
        left = _evaluate(node.child_by_field_name("left"), env)
        right = _evaluate(node.child_by_field_name("right"), env)
        if left is None or right is None:
            return None
        return [a + b for a, b in product(left, right)]
    if node.type == "template_string":
        parts: list[list[str]] = []
        for child in node.named_children:
            if child.type == "string_fragment":
                parts.append([_text(child)])
            elif child.type == "template_substitution" and child.named_children:
                value = _evaluate(child.named_children[0], env)
                if value is None:
                    return None
                parts.append(value)
        return ["".join(p) for p in product(*parts)] if parts else [""]
    return None


def _parse(reader: SnapshotReader, path: str) -> Node | str:
    """The syntax tree, or the reason there is none."""
    try:
        source = "\n".join(reader.lines(path))
    except Unresolved as error:
        return f"unreadable: {error.args[0]}"
    tree = _PARSER.parse(source.encode("utf-8"))
    if tree.root_node.has_error:
        return "syntax the parser could not read (CommonJS and ES2022 only)"
    return tree.root_node


def _scan_module(module: Module, paths: frozenset[str]) -> None:
    for node in _walk(module.root):
        if node.type != "variable_declarator":
            continue
        is_require, spec = _require_spec(node.child_by_field_name("value"))
        name = node.child_by_field_name("name")
        if not is_require or spec is None or name is None:
            continue
        if spec == "express":
            if name.type == "identifier":
                module.express_names.add(_text(name))
            else:
                module.express_names.update(
                    _text(c)
                    for c in name.named_children
                    if c.type.endswith(("identifier", "identifier_pattern"))
                )
            continue
        target = _resolve(spec, module.path, paths)
        if target is None:
            continue
        if name.type == "identifier":
            module.imports[_text(name)] = target
        elif name.type == "object_pattern":
            for part in name.named_children:
                if part.type == "shorthand_property_identifier_pattern":
                    module.named[_text(part)] = (target, _text(part))
                elif part.type == "pair_pattern":
                    key, value = part.child_by_field_name("key"), part.child_by_field_name("value")
                    if key is not None and value is not None and value.type == "identifier":
                        module.named[_text(value)] = (target, _text(key))
    for node in _walk(module.root):
        if node.type != "variable_declarator":
            continue
        value, name = node.child_by_field_name("value"), node.child_by_field_name("name")
        if value is None or name is None or value.type != "call_expression":
            continue
        fn = value.child_by_field_name("function")
        if fn is None or name.type != "identifier":
            continue
        called = _text(fn)
        if called in module.express_names or called in {
            f"{n}.Router" for n in module.express_names
        }:
            module.receivers[_text(name)] = "router" if called.endswith("Router") else "app"


def _declared_functions(module: Module) -> dict[str, Node]:
    """Top-level functions by name: declarations and `const f = function/arrow`."""
    found: dict[str, Node] = {}
    for node in module.root.named_children:
        if node.type == "function_declaration":
            name = node.child_by_field_name("name")
            if name is not None:
                found[_text(name)] = node
        elif node.type == "lexical_declaration":
            for declarator in node.named_children:
                value = declarator.child_by_field_name("value")
                name = declarator.child_by_field_name("name")
                if value is not None and name is not None and value.type in _FUNCTIONS:
                    found[_text(name)] = declarator
    return found


def _exports(module: Module) -> dict[str, tuple[str, Node]]:
    """Exported name -> (local name, the node that exports it)."""
    out: dict[str, tuple[str, Node]] = {}
    for node in module.root.named_children:
        if node.type != "expression_statement" or not node.named_children:
            continue
        assign = node.named_children[0]
        if assign.type != "assignment_expression":
            continue
        left, right = assign.child_by_field_name("left"), assign.child_by_field_name("right")
        if left is None or right is None:
            continue
        target = _text(left)
        if target == "module.exports" and right.type == "object":
            for part in right.named_children:
                if part.type == "shorthand_property_identifier":
                    out[_text(part)] = (_text(part), node)
                elif part.type == "pair":
                    key, value = part.child_by_field_name("key"), part.child_by_field_name("value")
                    if key is not None and value is not None and value.type == "identifier":
                        out[_text(key)] = (_text(value), node)
        elif target.startswith(("module.exports.", "exports.")) and right.type == "identifier":
            out[target.rsplit(".", 1)[1]] = (_text(right), node)
    return out


def _enclosing_function(node: Node) -> str:
    for parent in _ancestors(node):
        if parent.type == "function_declaration":
            name = parent.child_by_field_name("name")
            return _text(name) if name is not None else "<anonymous>"
        if parent.type in _FUNCTIONS and parent.parent is not None:
            holder = parent.parent
            if holder.type == "variable_declarator":
                name = holder.child_by_field_name("name")
                if name is not None:
                    return _text(name)
    return "<module>"


def _edges(modules: dict[str, Module]) -> list[CallEdge]:
    """Call edges between functions of the snapshot that a call resolves to."""
    edges: list[CallEdge] = []
    for module in modules.values():
        local = set(_declared_functions(module))
        for node in _walk(module.root):
            if node.type != "call_expression" or _require_spec(node)[0]:
                continue
            target = _target(module, node.child_by_field_name("function"), local)
            if target is not None:
                edges.append(
                    CallEdge((module.path, _enclosing_function(node)), target, _span(node)[0])
                )
    return edges


def _uses(
    modules: dict[str, Module], paths: frozenset[str]
) -> tuple[set[tuple[str, str]], set[str]]:
    """(file, name) pairs that these modules use, and files whose whole module object is used as
    a value (so any name in them may be used)."""
    used: set[tuple[str, str]] = set()
    escaped: set[str] = set()
    for module in modules.values():
        for node in _walk(module.root):
            if node.type == "identifier":
                _classify_identifier(module, node, used, escaped)
            elif node.type == "call_expression":
                _classify_require(module, node, paths, used, escaped)
    return used, escaped


def _target(module: Module, fn: Node | None, local: set[str]) -> tuple[str, str] | None:
    if fn is None:
        return None
    if fn.type == "identifier":
        name = _text(fn)
        if name in module.named:
            return module.named[name]
        return (module.path, name) if name in local else None
    if fn.type == "member_expression":
        obj, prop = fn.child_by_field_name("object"), fn.child_by_field_name("property")
        if obj is not None and prop is not None and obj.type == "identifier":
            file = module.imports.get(_text(obj))
            if file is not None:
                return file, _text(prop)
    return None


def _classify_identifier(
    module: Module, node: Node, used: set[tuple[str, str]], escaped: set[str]
) -> None:
    name = _text(node)
    parent = node.parent
    if parent is None:
        return
    if parent.type == "variable_declarator" and parent.child_by_field_name("name") == node:
        return
    if name in module.named:
        target = module.named[name]
        if parent.type not in {"object_pattern", "pair_pattern"}:
            used.add(target)
    if name not in module.imports:
        return
    file = module.imports[name]
    if parent.type == "member_expression" and parent.child_by_field_name("object") == node:
        prop = parent.child_by_field_name("property")
        if prop is not None and prop.type == "property_identifier":
            used.add((file, _text(prop)))
            return
    escaped.add(file)


def _classify_require(
    module: Module,
    node: Node,
    paths: frozenset[str],
    used: set[tuple[str, str]],
    escaped: set[str],
) -> None:
    is_require, spec = _require_spec(node)
    if not is_require or spec is None:
        return
    file = _resolve(spec, module.path, paths)
    parent = node.parent
    if file is None or parent is None:
        return
    if parent.type == "variable_declarator":
        return  # bound to an alias: the alias's uses decide
    if parent.type == "member_expression" and parent.child_by_field_name("object") == node:
        prop = parent.child_by_field_name("property")
        if prop is not None:
            used.add((file, _text(prop)))
            return
    escaped.add(file)


def _local_uses(module: Module, name: str, declaration: Node, export: Node) -> bool:
    """Is `name` used inside its own file, outside its declaration and its export line?"""
    skip = {
        (declaration.start_byte, declaration.end_byte),
        (export.start_byte, export.end_byte),
    }
    for node in _walk(module.root):
        if node.type == "identifier" and _text(node) == name:
            if not any(s <= node.start_byte and node.end_byte <= e for s, e in skip):
                return True
    return False


def _first_param(fn: Node) -> Node | None:
    single = fn.child_by_field_name("parameter")
    if single is not None:
        return single
    params = fn.child_by_field_name("parameters")
    return params.named_children[0] if params is not None and params.named_children else None


def _foreach_of(fn: Node) -> Node | None:
    """The array a function literal iterates, if the function is the callback of `X.forEach`."""
    arguments = fn.parent
    call = arguments.parent if arguments is not None else None
    if arguments is None or arguments.type != "arguments" or call is None:
        return None
    callee = call.child_by_field_name("function")
    if callee is None or callee.type != "member_expression":
        return None
    prop = callee.child_by_field_name("property")
    if prop is None or _text(prop) != "forEach":
        return None
    return callee.child_by_field_name("object")


def _guards(node: Node) -> tuple[list[str], list[str], dict[str, list[str]], bool]:
    """(conditions, enclosing functions, loop variables with their values, unresolved loop)."""
    conditions: list[str] = []
    functions: list[str] = []
    env: dict[str, list[str]] = {}
    unresolved_loop = False
    child = node
    for parent in _ancestors(node):
        if parent.type == "if_statement":
            condition = parent.child_by_field_name("condition")
            alternative = parent.child_by_field_name("alternative")
            negated = alternative is not None and (
                alternative.start_byte <= child.start_byte <= alternative.end_byte
            )
            if condition is not None:
                text = " ".join(_text(condition).split())
                if text.startswith("(") and text.endswith(")"):
                    text = text[1:-1]
                conditions.append(f"not {text}" if negated else text)
        elif parent.type in _FUNCTIONS:
            iterated = _foreach_of(parent)
            if iterated is not None:
                values, param = _loop_values(iterated), _first_param(parent)
                if values is None or param is None or param.type != "identifier":
                    unresolved_loop = True
                else:
                    env[_text(param)] = values
            elif parent.type == "function_declaration":
                name = parent.child_by_field_name("name")
                functions.append(_text(name) if name is not None else "an anonymous function")
        elif parent.type in {"for_statement", "for_in_statement", "while_statement"}:
            unresolved_loop = True
        child = parent
    return conditions, functions, env, unresolved_loop


def _loop_values(node: Node | None) -> list[str] | None:
    if node is None or node.type != "array":
        return None
    values = [_string(c) for c in node.named_children]
    return None if any(v is None for v in values) else [v for v in values if v is not None]


def _mounts(modules: dict[str, Module]) -> dict[str, tuple[str, str, int]]:
    """Router file -> (prefix, mounting file, line), from `app.use('/p', require('./router'))`."""
    mounts: dict[str, tuple[str, str, int]] = {}
    paths = frozenset(modules)
    for module in modules.values():
        for node in _walk(module.root):
            if node.type != "call_expression":
                continue
            fn = node.child_by_field_name("function")
            if fn is None or fn.type != "member_expression":
                continue
            obj, prop = fn.child_by_field_name("object"), fn.child_by_field_name("property")
            if obj is None or prop is None or _text(prop) != "use":
                continue
            if _text(obj) not in module.receivers:
                continue
            args = node.child_by_field_name("arguments")
            items = args.named_children if args else []
            if len(items) != 2:
                continue
            prefix = _evaluate(items[0], {})
            handler = items[1]
            is_require, spec = _require_spec(handler)
            if is_require and spec is not None:
                target = _resolve(spec, module.path, paths)
            elif handler.type == "identifier":
                target = module.imports.get(_text(handler))
            else:
                target = None
            if target is not None and prefix is not None and len(prefix) == 1:
                mounts[target] = (prefix[0], module.path, _span(node)[0])
    return mounts


def _prefix(
    path: str, mounts: dict[str, tuple[str, str, int]], seen: frozenset[str] = frozenset()
) -> tuple[str, list[tuple[str, int]]] | None:
    """(prefix, mount lines as (file, line)) for a router file, or None if it is not mounted."""
    if path not in mounts or path in seen:
        return None
    prefix, parent, line = mounts[path]
    above = _prefix(parent, mounts, seen | {path}) if parent in mounts else ("", [])
    if above is None:
        return None
    return above[0] + prefix, [*above[1], (parent, line)]


def _route_findings(modules: dict[str, Module]) -> list[Finding]:
    mounts = _mounts(modules)
    out: list[Finding] = []
    for module in modules.values():
        for node in _walk(module.root):
            if node.type != "call_expression":
                continue
            fn = node.child_by_field_name("function")
            if fn is None or fn.type != "member_expression":
                continue
            obj, prop = fn.child_by_field_name("object"), fn.child_by_field_name("property")
            if obj is None or prop is None or _text(obj) not in module.receivers:
                continue
            method = _text(prop)
            if method not in HTTP_METHODS:
                continue
            out.append(_route(module, node, method, module.receivers[_text(obj)], mounts))
    return out


def _route(
    module: Module,
    call: Node,
    method: str,
    kind: str,
    mounts: dict[str, tuple[str, str, int]],
) -> Finding:
    path = module.path
    first, last = _span(call)
    claim_id = f"ca:route:{path}:{first}"
    args = call.child_by_field_name("arguments")
    items = args.named_children if args else []
    conditions, functions, env, bad_loop = _guards(call)
    values = None if bad_loop or not items else _evaluate(items[0], env)
    evidence: list[tuple[str, int, int]] = [(path, *_cap(first, last))]
    where = []
    if env:
        where.append("registered in a loop")
    if conditions:
        where.append("only when " + " and ".join(conditions))
    if functions:
        where.append("inside " + ", ".join(functions))
    qualifier = f" ({'; '.join(where)})" if where else ""
    for condition_node in _ancestors(call):
        if condition_node.type == "if_statement":
            line = _span(condition_node)[0]
            if (path, line, line) not in evidence:
                evidence.append((path, line, line))
    if values is None:
        return Finding(
            claim_id,
            "route",
            "unknown",
            f"{path} line {first} registers a {method.upper()} route whose path is computed at "
            f"run time, so its path is not known.",
            tuple(evidence),
        )
    prefix_info = ("", []) if kind == "app" else _prefix(path, mounts)
    if prefix_info is None:
        listed = ", ".join(f"{method.upper()} {v}" for v in values)
        return Finding(
            claim_id,
            "route",
            "inferred",
            f"{path} line {first} registers {listed}{qualifier} on a router; no mount point for "
            f"this router was found, so the full path is not known.",
            tuple(evidence),
        )
    prefix, mount_lines = prefix_info
    for file, line in mount_lines:
        evidence.append((file, line, line))
    full = [prefix + v if v != "/" or not prefix else prefix for v in values]
    listed = ", ".join(f"{method.upper()} {p}" for p in full)
    return Finding(
        claim_id,
        "route",
        "confirmed",
        f"{path} line {first} registers {listed}{qualifier}.",
        tuple(evidence),
    )


def _is_empty_block(node: Node | None) -> bool:
    return (
        node is not None
        and node.type == "statement_block"
        and not [c for c in node.named_children if c.type != "comment"]
    )


def _swallowed(modules: dict[str, Module]) -> list[Finding]:
    out: list[Finding] = []
    for module in modules.values():
        for node in _walk(module.root):
            if node.type == "catch_clause" and _is_empty_block(node.child_by_field_name("body")):
                start, end = _span(node)
                out.append(
                    Finding(
                        f"ca:empty-catch:{module.path}:{start}",
                        "error_handling",
                        "confirmed",
                        f"The catch block at {module.path} line {start} has no statements: an "
                        f"error thrown in its try block is discarded, not logged or rethrown.",
                        ((module.path, *_cap(start, end)),),
                    )
                )
            elif node.type == "call_expression":
                fn = node.child_by_field_name("function")
                prop = fn.child_by_field_name("property") if fn is not None else None
                if fn is None or fn.type != "member_expression" or prop is None:
                    continue
                if _text(prop) != "catch":
                    continue
                args = node.child_by_field_name("arguments")
                callback = args.named_children[0] if args and args.named_children else None
                body = callback.child_by_field_name("body") if callback is not None else None
                if callback is not None and callback.type in _FUNCTIONS and _is_empty_block(body):
                    start, end = _span(node)
                    out.append(
                        Finding(
                            f"ca:empty-catch:{module.path}:{start}",
                            "error_handling",
                            "confirmed",
                            f"The .catch callback at {module.path} line {start} has no "
                            f"statements: a rejection is discarded, not logged or rethrown.",
                            ((module.path, *_cap(start, end)),),
                        )
                    )
    return out


def _computed_requires(modules: dict[str, Module]) -> tuple[list[Finding], set[str], bool]:
    """Unknown claims for `require` with a computed path; the directories they may reach; and
    whether any of them has no literal prefix (then every file may be loaded)."""
    out: list[Finding] = []
    reach: set[str] = set()
    anything = False
    for module in modules.values():
        for node in _walk(module.root):
            is_require, spec = _require_spec(node)
            if not is_require or spec is not None:
                continue
            args = node.child_by_field_name("arguments")
            arg = args.named_children[0] if args and args.named_children else None
            start, end = _span(node)
            prefix = _literal_prefix(arg)
            if prefix and prefix.startswith("."):
                reach.add(
                    posixpath.normpath(posixpath.join(posixpath.dirname(module.path), prefix))
                )
                reach_text = f"modules under {prefix} may be loaded through it"
            else:
                anything = True
                reach_text = "any module may be loaded through it"
            out.append(
                Finding(
                    f"ca:computed-require:{module.path}:{start}",
                    "dependency",
                    "unknown",
                    f"{module.path} line {start} loads a module with a path computed at run "
                    f"time, so calls through it cannot be followed; {reach_text}.",
                    ((module.path, *_cap(start, end)),),
                )
            )
    return out, reach, anything


def _literal_prefix(node: Node | None) -> str | None:
    """The leading string literal of a `'a' + b + c` chain."""
    while node is not None and node.type == "binary_expression":
        node = node.child_by_field_name("left")
    return _string(node)


def _dead_code(
    modules: dict[str, Module],
    used: set[tuple[str, str]],
    escaped: set[str],
    reach: set[str],
    anything: bool,
    main: str | None,
) -> list[Finding]:
    if anything:
        return []
    out: list[Finding] = []
    for module in modules.values():
        path = module.path
        loadable = any(path.startswith(r.rstrip("/") + "/") or path == r for r in reach)
        if path in escaped or path == main or loadable or _is_test(path):
            continue
        functions = _declared_functions(module)
        for exported, (local, export_node) in sorted(_exports(module).items()):
            declaration = functions.get(local)
            if declaration is None:
                continue
            if (path, exported) in used:
                continue
            if _local_uses(module, local, declaration, export_node):
                continue
            start, end = _span(declaration)
            out.append(
                Finding(
                    f"ca:dead:{path}:{exported}",
                    "dead_code",
                    "inferred",
                    f"{exported} is exported from {path} but no other code in the snapshot "
                    f"calls or references it. Use through reflection or a computed require "
                    f"cannot be ruled out.",
                    ((path, *_cap(start, end)), (path, *_span(export_node))),
                )
            )
    return out


def analyze(reader: SnapshotReader, paths: list[str]) -> Analysis:
    inventory = build_inventory(reader, paths)
    all_paths = frozenset(paths)
    modules: dict[str, Module] = {}
    unanalyzed: list[tuple[str, str]] = []
    findings: list[Finding] = []
    for path in inventory.first_party_sources:
        if not path.endswith((".js", ".cjs")):
            unanalyzed.append((path, "only JavaScript (CommonJS) is analysed in v1"))
            continue
        parsed = _parse(reader, path)
        if isinstance(parsed, str):
            unanalyzed.append((path, parsed))
        else:
            modules[path] = Module(path, parsed)
    for module in modules.values():
        _scan_module(module, all_paths)
    # References from test files do not keep application code alive.
    live = {p: m for p, m in modules.items() if not _is_test(p)}
    used, escaped = _uses(live, all_paths)
    findings += _route_findings(modules)
    findings += _swallowed(modules)
    findings += flow_findings((m.path, m.root) for m in modules.values())
    computed, reach, anything = _computed_requires(modules)
    findings += computed
    findings += _dead_code(modules, used, escaped, reach, anything, inventory.main)
    for path, reason in unanalyzed:
        findings.append(
            Finding(
                f"ca:unanalyzed:{path}",
                "unresolved",
                "unknown",
                f"{path} was not analysed: {reason}.",
            )
        )
    return Analysis(tuple(findings), tuple(_edges(modules)), tuple(unanalyzed))
