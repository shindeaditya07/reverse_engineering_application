# 0005. Characterization tests run in a network-less sandbox

- Status: proposed
- Date: 2026-11-04
- Blocks: build-plan 5.1

## Context

Success criterion: "characterization tests pass against the original application". That requires
building and running the legacy application. The constraints forbid connecting to production and
modifying the legacy code. Legacy build scripts are untrusted and may call the network or deploy.

## Options

- **Run against a client-provided test environment.** Not ours to control; risks touching shared
  systems that are production in all but name. Rejected.
- **Containerised sandbox built from the snapshot**, `--network none`, DB restored from DDL +
  synthetic seed, black-box tests from outside. Chosen.
- **Add gVisor (`runsc`)** to the container for a stronger kernel boundary where the host supports
  it. Chosen as the default when available.

## Decision

`services/sandbox/` is the only code that builds or runs legacy code. Each run: fresh container
from a pinned base image matching the legacy runtime, snapshot mounted read-only, writable scratch
volume, no network, non-root, resource and wall-time limits, destroyed afterwards. Dependencies the
build needs are pre-fetched into the image by the operator from an approved mirror, never fetched
by the legacy build itself.

For the legacy Node.js pilot: base image `node:<version>` pinned to the app's `engines` field or
`.nvmrc`; `node_modules` built by the operator from a pre-filled npm cache with install scripts
reviewed before they run (`--ignore-scripts` by default, specific packages allowed when their
native build needs it); the app started with `NODE_ENV` and config from synthetic values; coverage
via c8 or nyc, with no file edited on disk.

## Consequences

- npm install scripts (`preinstall`, `postinstall`) are arbitrary code from third parties. They
  run only inside the sandbox, and only when allowed per package.

- Some legacy apps will not build without network access or with an old toolchain. Each is a
  recorded blocker, not a reason to open the network. Buildability is a pilot selection criterion.
- External integrations (payment gateway, SMTP, partner APIs) are absent in the sandbox. Tests
  that reach them assert on the attempted call via a stub server inside the sandbox network, and
  that stub is part of the test harness, not the legacy code.
- Tests only prove behaviour under synthetic data. Say so in the test report.
