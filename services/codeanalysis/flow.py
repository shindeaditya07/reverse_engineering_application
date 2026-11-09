"""Flow (FR-3): where control passes from one asynchronous step to the next.

Three shapes, each found from the syntax tree alone and each stated structurally, not by what
the steps mean (that is not in the syntax):
- Nested error-first callbacks: a call whose last argument is a function with an `err`-style
  first parameter, nested two or more deep.
- A promise chain: a call followed by two or more `.then` steps.
- An `async` function that awaits two or more steps; the steps are listed in source order.

All three are Confirmed: they restate the tree. Source order is not run order when a step sits
in a loop or a branch, and the claim says "source order" for that reason.

This is control flow across steps. Value-level data flow (where a request field ends up) is not
built here.
"""

import re
from collections.abc import Iterable, Iterator

from tree_sitter import Node

from services.discovery.agent import Finding
from services.evidence.refs import max_excerpt_lines

_FUNCTIONS = ("function_declaration", "function_expression", "arrow_function")
_LITERALS = ("function_expression", "arrow_function")
_STEPS = ("then", "catch", "finally")
_ERROR_PARAM = re.compile(r"^(err|error|e)\d*$")
MIN_CALLBACK_DEPTH = 2
MIN_THENS = 2
MIN_AWAITS = 2
LISTED = 8  # steps named in a claim; the rest are counted


def _text(node: Node) -> str:
    return (node.text or b"").decode("utf-8")


def _span(node: Node) -> tuple[int, int]:
    return node.start_point.row + 1, node.end_point.row + 1


def _cap(start: int, end: int) -> tuple[int, int]:
    return start, min(end, start + max_excerpt_lines() - 1)


def _walk(node: Node) -> Iterator[Node]:
    stack = [node]
    while stack:
        current = stack.pop()
        yield current
        stack.extend(reversed(current.children))


def _own(node: Node) -> Iterator[Node]:
    """Descendants of a function that are not inside a function nested in it."""
    stack = list(reversed(node.children))
    while stack:
        current = stack.pop()
        yield current
        if current.type not in _FUNCTIONS and current.type != "method_definition":
            stack.extend(reversed(current.children))


def _enclosing(node: Node) -> Node | None:
    parent = node.parent
    while parent is not None:
        if parent.type in (*_FUNCTIONS, "method_definition"):
            return parent
        parent = parent.parent
    return None


def _name(fn: Node | None) -> str:
    if fn is None:
        return "module code"
    named = fn.child_by_field_name("name")
    if named is not None:
        return _text(named)
    parent = fn.parent
    if parent is not None and parent.type == "variable_declarator":
        target = parent.child_by_field_name("name")
        if target is not None:
            return _text(target)
    if parent is not None and parent.type == "pair":
        key = parent.child_by_field_name("key")
        if key is not None:
            return _text(key)
    if parent is not None and parent.type == "assignment_expression":
        left = parent.child_by_field_name("left")
        if left is not None:
            return _text(left)
    return "an anonymous function"


def _callee(call: Node) -> str:
    fn = call.child_by_field_name("function")
    return "".join(_text(fn).split()) if fn is not None else "<expression>"


def _listed(names: list[str]) -> str:
    shown = ", ".join(n if n.startswith("<") else f"{n}()" for n in names[:LISTED])
    return shown + (f" and {len(names) - LISTED} more" if len(names) > LISTED else "")


# -- nested error-first callbacks ------------------------------------------------------------


def _callback(call: Node) -> Node | None:
    """The last argument of the call, if it is a function with an err-style first parameter."""
    args = call.child_by_field_name("arguments")
    last = args.named_children[-1] if args is not None and args.named_children else None
    if last is None or last.type not in _LITERALS:
        return None
    params = last.child_by_field_name("parameters") or last.child_by_field_name("parameter")
    first = None
    if params is not None:
        first = params if params.type == "identifier" else next(iter(params.named_children), None)
    if first is None or first.type != "identifier" or not _ERROR_PARAM.match(_text(first)):
        return None
    return last


def _callback_findings(path: str, root: Node) -> list[Finding]:
    calls = {
        n.id: (n, cb) for n in _walk(root) if n.type == "call_expression" and (cb := _callback(n))
    }
    children: dict[int, list[Node]] = {}
    roots: list[Node] = []
    for call, _ in calls.values():
        parent_id = None
        for up in _ancestors_functions(call):
            owner = up.parent.parent if up.parent is not None else None  # arguments -> call
            if owner is not None and owner.id in calls and calls[owner.id][1].id == up.id:
                parent_id = owner.id
                break
        if parent_id is None:
            roots.append(call)
        else:
            children.setdefault(parent_id, []).append(call)

    def longest(call: Node) -> list[Node]:
        best: list[Node] = []
        for child in children.get(call.id, []):
            candidate = longest(child)
            if len(candidate) > len(best):
                best = candidate
        return [call, *best]

    out: list[Finding] = []
    for call in roots:
        chain = longest(call)
        if len(chain) < MIN_CALLBACK_DEPTH:
            continue
        start, end = _span(call)
        fn = _enclosing(call)
        names = [_callee(c) for c in chain]
        out.append(
            Finding(
                f"ca:callback-chain:{path}:{start}",
                "flow",
                "confirmed",
                f"{_name(fn)} in {path} line {start} nests {len(chain)} error-first callbacks: "
                f"{_listed(names)}. Each step runs inside the callback of the one before.",
                ((path, *_cap(start, end)),),
            )
        )
    return out


def _ancestors_functions(node: Node) -> Iterator[Node]:
    parent = node.parent
    while parent is not None:
        if parent.type in _LITERALS:
            yield parent
        parent = parent.parent


# -- promise chains --------------------------------------------------------------------------


def _step(call: Node) -> str | None:
    fn = call.child_by_field_name("function")
    prop = fn.child_by_field_name("property") if fn is not None else None
    if fn is None or fn.type != "member_expression" or prop is None:
        return None
    return _text(prop) if _text(prop) in _STEPS else None


def _promise_findings(path: str, root: Node) -> list[Finding]:
    out: list[Finding] = []
    for node in _walk(root):
        if node.type != "call_expression" or _step(node) is None:
            continue
        outer = node.parent  # is this the top of its chain?
        if outer is not None and outer.type == "member_expression":
            above = outer.parent
            if above is not None and above.type == "call_expression" and _step(above):
                continue
        steps: list[str] = []
        cursor = node
        while cursor.type == "call_expression" and (kind := _step(cursor)) is not None:
            steps.append(kind)
            fn = cursor.child_by_field_name("function")
            inner = fn.child_by_field_name("object") if fn is not None else None
            if inner is None:
                break
            cursor = inner
        theens = steps.count("then")
        if theens < MIN_THENS:
            continue
        source = (
            _callee(cursor) if cursor.type == "call_expression" else "".join(_text(cursor).split())
        )
        start, end = _span(node)
        steps.reverse()
        out.append(
            Finding(
                f"ca:promise-chain:{path}:{start}",
                "flow",
                "confirmed",
                f"{_name(_enclosing(node))} in {path} line {start} runs a promise chain that "
                f"starts at {source} and continues with {len(steps)} steps, in order: "
                f"{', '.join('.' + s for s in steps)}.",
                ((path, *_cap(start, end)),),
            )
        )
    return out


# -- async functions -------------------------------------------------------------------------


def _is_async(fn: Node) -> bool:
    return any(c.type == "async" for c in fn.children)


def _async_findings(path: str, root: Node) -> list[Finding]:
    out: list[Finding] = []
    for fn in _walk(root):
        if fn.type not in (*_FUNCTIONS, "method_definition") or not _is_async(fn):
            continue
        awaits = [n for n in _own(fn) if n.type == "await_expression"]
        if len(awaits) < MIN_AWAITS:
            continue
        names = []
        for await_node in awaits:
            target = await_node.named_children[0] if await_node.named_children else None
            names.append(
                _callee(target)
                if target is not None and target.type == "call_expression"
                else "<expression>"
            )
        start, end = _span(fn)
        out.append(
            Finding(
                f"ca:async-flow:{path}:{start}",
                "flow",
                "confirmed",
                f"{_name(fn)} in {path} line {start} is async and awaits {len(awaits)} steps, "
                f"in source order: {_listed(names)}.",
                ((path, *_cap(start, end)),),
            )
        )
    return out


def flow_findings(files: Iterable[tuple[str, Node]]) -> list[Finding]:
    out: list[Finding] = []
    for path, root in files:
        out += _callback_findings(path, root)
        out += _promise_findings(path, root)
        out += _async_findings(path, root)
    return out
