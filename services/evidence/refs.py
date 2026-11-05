"""The six evidence kinds as typed references (EVD-1.2, EVD-1.4, EVD-1.5).

A reference says where to look, never what is there. Whether it points at real bytes is
decided by `resolve`.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from services.rules_constants import rule_constants

# Implementation bound, not a rule: a byte range is only for files that cannot be decoded, and
# a long run of bytes is not reviewable. Moves into rules_constants.yaml if the rules adopt it.
MAX_EXCERPT_BYTES = 4000


def max_excerpt_lines() -> int:
    return int(rule_constants("EVD-1.4")["max_excerpt_lines"])


class _Ref(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    path: str = Field(min_length=1)


class FileRange(_Ref):
    """Lines (from 1, LF-normalised, inclusive) or, for undecodable files, a byte range."""

    kind: Literal["file_range"] = "file_range"
    start_line: int | None = None
    end_line: int | None = None
    start_byte: int | None = None
    end_byte: int | None = None

    @model_validator(mode="after")
    def _one_form(self) -> "FileRange":
        by_line = self.start_line is not None or self.end_line is not None
        by_byte = self.start_byte is not None or self.end_byte is not None
        if by_line == by_byte:
            raise ValueError("give either lines or a byte range, not both and not neither")
        if by_line:
            start, end = self.start_line, self.end_line
            if start is None or end is None or start < 1 or end < start:
                raise ValueError("lines count from 1 and need start_line <= end_line")
            if end - start + 1 > max_excerpt_lines():
                raise ValueError(f"at most {max_excerpt_lines()} lines per range (EVD-1.4)")
        else:
            first, last = self.start_byte, self.end_byte
            if first is None or last is None or first < 0 or last <= first:
                raise ValueError("a byte range needs 0 <= start_byte < end_byte")
            if last - first > MAX_EXCERPT_BYTES:
                raise ValueError(f"at most {MAX_EXCERPT_BYTES} bytes per range")
        return self


class LogLine(_Ref):
    kind: Literal["log_line"] = "log_line"
    line: int = Field(ge=1)


class _Located(_Ref):
    """Names an object inside a file. `line` picks one when the name occurs more than once."""

    object_name: str = Field(min_length=1)
    line: int | None = Field(default=None, ge=1)


class SchemaObject(_Located):
    """table:<t>, column:<t>.<c>, index:<i> or constraint:<t>.<c> in a SQL DDL file."""

    kind: Literal["schema_object"] = "schema_object"


class ConfigKey(_Located):
    """A key in a config file (JS, JSON, YAML, env, ini). A dotted name uses its last part."""

    kind: Literal["config_key"] = "config_key"


class BuildStep(_Located):
    """npm:<script>, make:<target>, docker:<INSTRUCTION> or step:<text>."""

    kind: Literal["build_step"] = "build_step"


class Ticket(_Located):
    """A ticket id such as ORD-123 mentioned in a file."""

    kind: Literal["ticket"] = "ticket"


EvidenceRef = Annotated[
    FileRange | LogLine | SchemaObject | ConfigKey | BuildStep | Ticket,
    Field(discriminator="kind"),
]
_ADAPTER: TypeAdapter[EvidenceRef] = TypeAdapter(EvidenceRef)


def parse_ref(data: dict[str, object]) -> EvidenceRef:
    """Validate a dict (for example from JSON) into the right reference type."""
    return _ADAPTER.validate_python(data)
