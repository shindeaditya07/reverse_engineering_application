"""Reconstruct tables, columns, keys and relations from `CREATE TABLE` statements (FR-4), and
produce the ER data that the Diagram agent will draw. Deterministic, no model.

Parsing is sqlglot with the MySQL dialect (ADR 0002). Line numbers come from the parser's own
identifier positions, counted from 1 after LF normalisation like every other citation.
"""

from dataclasses import dataclass
from typing import Any

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

from services.evidence import SnapshotReader, Unresolved
from services.evidence.refs import max_excerpt_lines


@dataclass(frozen=True)
class Column:
    name: str
    type: str
    nullable: bool
    primary_key: bool
    unique: bool
    auto_increment: bool
    default: str | None
    line: int


@dataclass(frozen=True)
class Table:
    name: str
    file: str
    start: int
    end: int
    columns: tuple[Column, ...]

    def column(self, name: str) -> Column | None:
        return next((c for c in self.columns if c.name == name), None)


@dataclass(frozen=True)
class Relation:
    table: str
    columns: tuple[str, ...]
    ref_table: str
    ref_columns: tuple[str, ...]
    file: str
    line: int
    declared: bool  # False: inferred from the column name, no foreign key exists


@dataclass(frozen=True)
class ErModel:
    tables: tuple[Table, ...]
    relations: tuple[Relation, ...]

    def table(self, name: str) -> Table | None:
        return next((t for t in self.tables if t.name == name), None)

    def as_dict(self) -> dict[str, Any]:
        """Plain data for the Diagram agent: no objects, stable order."""
        return {
            "tables": [
                {
                    "name": t.name,
                    "file": t.file,
                    "lines": [t.start, t.end],
                    "columns": [
                        {
                            "name": c.name,
                            "type": c.type,
                            "nullable": c.nullable,
                            "primary_key": c.primary_key,
                            "unique": c.unique,
                            "default": c.default,
                            "line": c.line,
                        }
                        for c in t.columns
                    ],
                }
                for t in self.tables
            ],
            "relations": [
                {
                    "from": r.table,
                    "columns": list(r.columns),
                    "to": r.ref_table,
                    "to_columns": list(r.ref_columns),
                    "declared": r.declared,
                    "line": r.line,
                }
                for r in self.relations
            ],
        }


def _line(node: exp.Expression) -> int:
    """First line of the node, from the identifiers inside it."""
    lines = [i.meta["line"] for i in node.find_all(exp.Identifier) if "line" in i.meta]
    return min(lines) if lines else 1


def _column(definition: exp.ColumnDef) -> tuple[Column, list[tuple[str, tuple[str, ...]]]]:
    primary = unique = auto = False
    nullable = True
    default: str | None = None
    refs: list[tuple[str, tuple[str, ...]]] = []
    for constraint in definition.args.get("constraints") or []:
        kind = constraint.args.get("kind")
        if isinstance(kind, exp.PrimaryKeyColumnConstraint):
            primary, nullable = True, False
        elif isinstance(kind, exp.NotNullColumnConstraint):
            nullable = False
        elif isinstance(kind, exp.UniqueColumnConstraint):
            unique = True
        elif isinstance(kind, exp.AutoIncrementColumnConstraint):
            auto = True
        elif isinstance(kind, exp.DefaultColumnConstraint):
            default = kind.this.sql(dialect="mysql")
        elif isinstance(kind, exp.Reference):
            target = kind.this
            if isinstance(target, exp.Schema) and isinstance(target.this, exp.Table):
                refs.append((target.this.name, tuple(e.name for e in target.expressions)))
    kind_sql = definition.args["kind"].sql(dialect="mysql") if definition.args.get("kind") else ""
    return (
        Column(
            definition.name, kind_sql, nullable, primary, unique, auto, default, _line(definition)
        ),
        refs,
    )


def _end_line(lines: list[str], last_item: int) -> int:
    for number in range(last_item, len(lines) + 1):
        if lines[number - 1].lstrip().startswith(")"):
            return number
    return last_item


def parse_schema(reader: SnapshotReader, paths: list[str]) -> tuple[ErModel, list[tuple[str, str]]]:
    """(the model, the files it could not read with the reason, stated and never silent)."""
    tables: list[Table] = []
    relations: list[Relation] = []
    unread: list[tuple[str, str]] = []
    for path in sorted(p for p in paths if p.endswith(".sql")):
        try:
            text = "\n".join(reader.lines(path))
        except Unresolved as error:
            unread.append((path, f"unreadable: {error.args[0]}"))
            continue
        try:
            statements = sqlglot.parse(text, read="mysql")
        except SqlglotError:
            unread.append((path, "SQL the parser could not read"))
            continue
        lines = text.split("\n")
        for statement in statements:
            if (
                not isinstance(statement, exp.Create)
                or str(statement.args.get("kind")).upper() != "TABLE"
            ):
                continue
            schema = statement.this
            if not isinstance(schema, exp.Schema) or not isinstance(schema.this, exp.Table):
                continue
            name = schema.this.name
            columns: list[Column] = []
            for item in schema.expressions:
                if isinstance(item, exp.ColumnDef):
                    column, refs = _column(item)
                    columns.append(column)
                    relations += [
                        Relation(name, (column.name,), t, c, path, column.line, True)
                        for t, c in refs
                    ]
                elif isinstance(item, exp.ForeignKey):
                    reference = item.args.get("reference")
                    target = reference.this if isinstance(reference, exp.Reference) else None
                    if isinstance(target, exp.Schema) and isinstance(target.this, exp.Table):
                        relations.append(
                            Relation(
                                name,
                                tuple(e.name for e in item.expressions),
                                target.this.name,
                                tuple(e.name for e in target.expressions),
                                path,
                                _line(item),
                                True,
                            )
                        )
            items = [i for i in schema.expressions if i is not None]
            start = _line(schema.this)
            last = max((_line(i) for i in items), default=start)
            end = _end_line(lines, last)
            tables.append(
                Table(name, path, start, min(end, start + max_excerpt_lines() - 1), tuple(columns))
            )
    model = ErModel(tuple(tables), tuple(relations))
    return ErModel(model.tables, model.relations + _inferred(model)), unread


def _inferred(model: ErModel) -> tuple[Relation, ...]:
    """`customer_id` with no foreign key, next to a `customers` table that has an `id`."""
    declared = {(r.table, c) for r in model.relations for c in r.columns}
    found: list[Relation] = []
    for table in model.tables:
        for column in table.columns:
            if not column.name.endswith("_id") or (table.name, column.name) in declared:
                continue
            stem = column.name[: -len("_id")]
            target = model.table(stem) or model.table(stem + "s")
            if target is not None and target.name != table.name and target.column("id"):
                found.append(
                    Relation(
                        table.name,
                        (column.name,),
                        target.name,
                        ("id",),
                        table.file,
                        column.line,
                        False,
                    )
                )
    return tuple(found)
