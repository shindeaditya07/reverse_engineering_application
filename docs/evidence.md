# Evidence resolver

`services/evidence/` turns an evidence reference into the exact bytes it points at in the
pinned snapshot (EVD-1.2). A claim that cannot do this has no evidence.

## References

| Kind | Fields | Points at |
|---|---|---|
| `file_range` | `path`, `start_line`/`end_line` **or** `start_byte`/`end_byte` | Lines (from 1, at most 40) or, for a file that is not UTF-8, bytes (at most 4000, an implementation bound) |
| `log_line` | `path`, `line` | One line of a log file |
| `schema_object` | `path`, `object_name` | `table:t`, `column:t.c`, `index:i`, `constraint:t.c` in a SQL file |
| `config_key` | `path`, `object_name` | A key in a JS, JSON, YAML, env or ini file; a dotted name uses its last part |
| `build_step` | `path`, `object_name` | `npm:script`, `make:target`, `docker:INSTRUCTION`, `step:text` |
| `ticket` | `path`, `object_name` | A ticket id mentioned in a file |

`line` on the last three kinds is optional. Without it, a name that occurs more than once is
`ambiguous`; with it, the name must occur on exactly that line.

## Resolution

`resolve(ref, reader)` returns a `Resolution` and never raises for a bad reference:

- `resolved`: `excerpt` (redacted, SEC-1.3), the span, and `content_hash`.
- `unresolved`: `reason` is `code: detail`. Codes: `not_in_snapshot`, `unreadable`,
  `snapshot_modified`, `undecodable`, `out_of_range`, `not_found`, `ambiguous`,
  `span_too_long`, `bad_object_name`.
- `stale` (only from `check_hash`): the reference resolves but the bytes differ from the hash
  stored with the claim (EVD-1.3). The claim goes back to the review queue.

The hash is SHA-256 of the real, unredacted bytes: the LF-normalised excerpt for lines, the
raw bytes for a byte range. Redaction hides a value from the reader but not from the hash, so
a changed secret still marks the claim stale.

## Line numbers (EVD-1.5)

Decode as UTF-8 (a BOM is dropped), turn CRLF and lone CR into LF, split on LF only. U+2028,
form feed and vertical tab do not start a line. A file with no final newline has the same
lines as one with it. A file that is not UTF-8 cannot be cited by line.

## What it reads

`SnapshotReader` reads only paths in the snapshot's recorded file list, so `..`, absolute
paths and symlinks never resolve. Every file is hashed on first read and compared with its
pinned hash; an edited snapshot resolves nothing.

## Limits to know

- The DDL scanner finds where a name is declared. It handles `CREATE TABLE`, inline columns,
  `CONSTRAINT`, `KEY`/`INDEX`, `CREATE INDEX` and `ALTER TABLE ... ADD CONSTRAINT`, with
  quoted names and comments. It does not parse types, views, triggers or dialect extensions;
  those are `not_found`, never guessed.
- A table longer than 40 lines is `span_too_long`; cite its columns instead.
- Generated and vendored files (EVD-1.6) are not refused here. The verifier decides that.
- The database stores the `line` hint of a located reference, not the span it resolved to.

## Database

Migration `0002` adds `start_byte`/`end_byte` to `evidence` and rewrites `file_range_valid`.
Every branch of the check tests `IS NOT NULL`: a CHECK that evaluates to NULL passes, and the
first version of this constraint let half a range through that way.
`evidence_row_fields` refuses anything that is not `resolved` (EVD-1.2); `ref_from_row`
rebuilds the reference.
