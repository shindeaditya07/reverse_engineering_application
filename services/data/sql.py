"""What one SQL statement reads and writes. sqlglot with the MySQL dialect (ADR 0002).

The text may hold `__dynN__` tokens where the code computed part of the statement at run time.
A token in a value position is harmless; a token where a table or a clause belongs is reported,
not guessed.
"""

from dataclasses import dataclass
from typing import cast

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

DYN = "__dyn"


class SqlUnreadable(Exception):
    """The statement cannot be parsed, or is a kind this analyzer does not read."""


@dataclass(frozen=True)
class Statement:
    verb: str  # select, insert, update, delete
    tables: tuple[str, ...]
    reads: tuple[tuple[str, str], ...]  # (table, column); "*" is every column
    writes: tuple[tuple[str, str], ...]  # (table, column); "*" is a whole row (delete, bare insert)
    ambiguous: tuple[str, ...]  # unqualified columns in a join, not attributable to one table

    @property
    def dynamic_table(self) -> bool:
        return any(t.startswith(DYN) for t in self.tables)


def _aliases(root: exp.Expression) -> dict[str, str]:
    return {t.alias_or_name: t.name for t in root.find_all(exp.Table)}


def analyze_sql(text: str) -> Statement:
    # `??` is the mysql driver's identifier placeholder (a column or table name supplied at run
    # time). sqlglot cannot parse it, so it becomes a dynamic name, like a template hole.
    text = text.replace("??", f" {DYN}ident__ ")
    try:
        root = sqlglot.parse_one(text, read="mysql")
    except SqlglotError as error:
        raise SqlUnreadable(type(error).__name__) from error
    if isinstance(root, exp.Insert):
        return _insert(root)
    if isinstance(root, exp.Update):
        return _update(root)
    if isinstance(root, exp.Delete):
        return _delete(root)
    if isinstance(root, exp.Query):
        return _select(cast(exp.Expression, root))
    raise SqlUnreadable(f"unsupported statement {type(root).__name__}")


def _attribute(
    columns: list[exp.Column],
    aliases: dict[str, str],
    skip: set[int] = frozenset(),  # type: ignore[assignment]
) -> tuple[list[tuple[str, str]], list[str]]:
    found: list[tuple[str, str]] = []
    ambiguous: list[str] = []
    tables = sorted(set(aliases.values()))
    for column in columns:
        if id(column) in skip or column.name.startswith(DYN):
            continue
        if isinstance(column.this, exp.Star):
            owners = [aliases[column.table]] if column.table in aliases else tables
            found += [(t, "*") for t in owners]
        elif column.table and column.table in aliases:
            found.append((aliases[column.table], column.name))
        elif len(tables) == 1:
            found.append((tables[0], column.name))
        else:
            ambiguous.append(column.name)
    return found, ambiguous


def _result(
    verb: str,
    root: exp.Expression,
    reads: list[tuple[str, str]],
    writes: list[tuple[str, str]],
    ambiguous: list[str],
) -> Statement:
    tables = sorted({t.name for t in root.find_all(exp.Table)})
    return Statement(
        verb,
        tuple(tables),
        tuple(sorted(set(reads))),
        tuple(sorted(set(writes))),
        tuple(sorted(set(ambiguous))),
    )


def _select(root: exp.Expression) -> Statement:
    aliases = _aliases(root)
    reads, ambiguous = _attribute(list(root.find_all(exp.Column)), aliases)
    for select in root.find_all(exp.Select):
        if any(isinstance(e, exp.Star) for e in select.expressions):
            reads += [(t.name, "*") for t in select.find_all(exp.Table)]
    return _result("select", root, reads, [], ambiguous)


def _update(root: exp.Update) -> Statement:
    aliases = _aliases(root)
    target_nodes: list[exp.Column] = []
    for assignment in root.expressions:
        if isinstance(assignment, exp.EQ) and isinstance(assignment.this, exp.Column):
            target_nodes.append(assignment.this)
    skip = {id(c) for c in target_nodes}
    reads, ambiguous = _attribute(list(root.find_all(exp.Column)), aliases, skip)
    writes, ambiguous_writes = _attribute(target_nodes, aliases)
    return _result("update", root, reads, writes, ambiguous + ambiguous_writes)


def _insert(root: exp.Insert) -> Statement:
    target = root.this
    columns: list[str] | None = None
    if isinstance(target, exp.Schema):
        columns = [e.name for e in target.expressions]
        target = target.this
    table = target.name if isinstance(target, exp.Table) else ""
    source = root.args.get("expression")
    reads: list[tuple[str, str]] = []
    ambiguous: list[str] = []
    if source is not None:
        aliases = _aliases(source)
        reads, ambiguous = _attribute(list(source.find_all(exp.Column)), aliases)
    writes = [(table, c) for c in columns] if columns is not None else [(table, "*")]
    statement = _result("insert", root, reads, writes, ambiguous)
    return Statement(
        "insert",
        tuple(sorted({table, *statement.tables})),
        statement.reads,
        statement.writes,
        ambiguous=statement.ambiguous,
    )


def _delete(root: exp.Delete) -> Statement:
    aliases = _aliases(root)
    reads, ambiguous = _attribute(list(root.find_all(exp.Column)), aliases)
    table = root.this.name if isinstance(root.this, exp.Table) else ""
    return _result("delete", root, reads, [(table, "*")], ambiguous)
