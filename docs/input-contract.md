# Strata: Input Contract

**Version:** 0.1 (2026-11-04), **draft**
**Spec reference:** `spec.md` v0.1 §5, §11, FR-1

ReplyDesk's `data-contract.md` defined what the order store must provide, so the grounding rules
could cite only fields that exist. This is the equivalent: what an input bundle must contain, so
the evidence rules in `policies.md` can resolve every reference.

## Bundle layout

A bundle is a directory or archive supplied by the client's team. The platform never reaches out
to fetch anything (SAF-3.2).

```
bundle/
├── manifest.json        required
├── source/              required: the repository tree (git bundle, or files)
├── schema/              required: DDL (.sql), schema-only dump
├── config/              optional but expected: config files as used by the app
├── build/               optional: build and deploy scripts if outside source/
├── logs/                optional: runtime logs, sanitized by the supplier
├── tickets/             optional: CSV or JSON export
└── docs/                optional: existing partial documentation
```

## manifest.json

| Field | Required | Meaning |
|---|---|---|
| `name` | yes | Application name |
| `language` | yes | `javascript` in v1 |
| `runtime` | yes | e.g. `node:12` (from `engines` or `.nvmrc` if known) |
| `sql_dialect` | yes | e.g. `mysql`, `postgres` |
| `commit` | if git | Commit SHA the tree was exported at |
| `sanitized` | yes | `true` only if the supplier attests logs and data are sanitized (SAF-3.3) |
| `contact` | yes | Person who can answer review-queue questions about the application |
| `notes` | no | Anything the supplier knows that the code does not show |

## Rules

1. **Schema is DDL or a schema-only dump.** Data dumps are refused unless `sanitized` is true and
   the PII scan finds nothing above `pii_refusal_threshold` (SAF-3.3).
2. **Symlinks must stay inside the bundle.** A symlink pointing out is rejected (AGENTS §7).
3. **Size limits** are settings, not code: maximum archive size, file count, file size, line
   length. A bundle over a limit is rejected with the limit named.
4. **Encoding** is detected per file and recorded (spec §20). Files that cannot be decoded are
   listed as unsupported in the inventory.
5. **Nothing in the bundle is executed** outside the sandbox (SAF-3.4, SAF-3.5).
6. **The snapshot ID** is the SHA-256 of the sorted list of `(path, sha256, bytes)` for every file
   plus the manifest, so the same bundle always gets the same ID (FR-1).

## What the platform emits, for reference

Each input file becomes a `snapshot_files` row with its kind (`source`, `schema`, `config`,
`build`, `log`, `ticket`, `doc`), hash and detected encoding. Evidence references (EVD-1.2) can
point only at rows that exist.
