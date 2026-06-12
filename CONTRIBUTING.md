# Contributing to Clermes

Contributions are welcome. A few ground rules:

1. Open an issue first for non-trivial changes so the design can be discussed before code lands.
2. All tests must pass before a PR is mergeable. Run `make test` locally.
3. Every source file carries an SPDX header: `# SPDX-License-Identifier: AGPL-3.0-or-later` (or the equivalent comment form for the language).
4. Match the voice and style of the surrounding code and prose.
5. By contributing, you agree your contributions are licensed under AGPL-3.0-or-later.

## Local setup

Clone, then `make install` to set up the Python package in editable mode. See `docs/architecture.md` for the lay of the land.

## Reporting bugs

Use the issue templates in `.github/ISSUE_TEMPLATE/`. Include reproduction steps, expected behavior, and observed behavior.

## Security issues

See `SECURITY.md` for the responsible-disclosure process.
