# 0002. Parse with tree-sitter, resolve names per language

- Status: proposed
- Date: 2026-11-04
- Blocks: build-plan 2.3

## Context

The use case requires static analysis on an AST, not text. We need positions for every fact,
tolerance for broken or old syntax, and a path to more than one language.

## Options

- **tree-sitter** for all languages: one API, error-tolerant, exact byte and line positions, many
  grammars. Does **not** resolve types, imports or overloads.
- **Language-native compilers/analyzers** (JavaParser + symbol solver, Roslyn, PHP-Parser,
  Python `ast` + jedi): accurate resolution, different API per language, often need the
  project's dependencies on the classpath.
- **Heavy platforms** (CodeQL, Joern, SCIP indexers): powerful, but CodeQL's licence restricts use
  on non-open-source code, and the others add a large dependency we must learn and secure.
  [Likely; re-check CodeQL licence terms if it is reconsidered.]

## Decision

tree-sitter is the parsing layer for every language. Each language adapter adds name resolution,
starting with our own resolver over the symbol index, and adds a native resolver sidecar for the
pilot language only if fixture evals show the Confirmed-edge share is too low.

For the pilot (legacy Node.js, decided 2026-11-04): `tree-sitter-javascript`, our own CommonJS
`require` resolver following Node's module resolution algorithm, and an Express adapter. The
candidate sidecar is the TypeScript compiler API run over the JS sources with `allowJs`, in a Node
process inside the platform (not the sandbox; it reads source, never executes it).

**JavaScript makes static resolution weaker than in a typed language.** [Likely] Computed member
calls, `require` with a variable, `call`/`apply`, prototype patching and callbacks passed through
several layers are common in legacy Node code. Expect a large share of call edges to be Inferred
until characterization tests confirm them (TST-7.5). Measure that share on the fixture first and
report it; do not hide it.

## Consequences

- One parse model, one position model, across languages.
- Our own resolver will miss cases a compiler would catch; those edges become Inferred or Unknown,
  which is honest but costs reviewer time.
- A sidecar (for example a JVM process) is a second runtime to package and sandbox.
