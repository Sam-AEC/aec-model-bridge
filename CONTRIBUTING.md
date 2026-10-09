# Contributing

Thanks for improving AEC Model Bridge.

## Licensing

Open an issue before preparing a code contribution. To preserve the project's
GPL-3.0-or-later, Revit Linking Exception, and commercial dual-licensing model,
code pull requests can only be accepted after the contributor signs a separate
contributor agreement that permits both licensing options.

Do not submit code copied from projects whose licenses are incompatible with
commercial redistribution. Issue reports, design proposals, and documentation
corrections are welcome without a code contribution.

## Focus Areas

Contributions are most useful when they improve one of the following:
- Revit command coverage
- MCP tool reliability and error handling
- installation and configuration documentation
- developer ergonomics for local debugging and testing

## Guidelines

- Keep changes scoped to a single feature, fix, or documentation update.
- Document any Revit version assumptions in the PR description.
- Sanitize local paths, machine names, and credentials from config examples.
- If a change affects UI or commands, include reproduction steps and expected behavior.
- Update examples or docs when behavior changes.

## Building and testing

Build the add-in for one Revit version and run the Python tests:

```powershell
.\scripts\build-addin.ps1 -RevitVersion 2026 -Configuration Release
python -m pytest packages/mcp-server-revit/tests
```

Supported Revit versions are 2024 (net48), 2025 and 2026 (net8.0-windows), and
2027 (net10.0-windows). See
[docs/target-frameworks-and-dependencies.md](docs/target-frameworks-and-dependencies.md).

## Translations

Translated READMEs live in `docs/i18n/` as `README.<language>.md` and are
linked from the language bar at the top of `README.md`. The English
`README.md` is canonical: when a translation differs from it, the English
text wins, and README changes are made in English first. Current translations
are AI-assisted drafts, so native-speaker corrections are especially welcome.

To improve a translation, edit the file in `docs/i18n/` and open a pull
request. Keep code blocks, commands, tool names, environment variable names,
file paths, product names, counts and licence text exactly as in the English
README, and use the standard AEC term for the language (for example parameter,
sheet, view, family, worksharing).

To add a language, copy an existing translation, translate the prose, add the
language to the bar in `README.md` and in every file in `docs/i18n/`, and add
it to the list in `packages/mcp-server-revit/tests/test_i18n_readmes.py`.
That test checks that code blocks match the English README, headings line up,
the language bar is present and relative links resolve. Run it with
`python -m pytest packages/mcp-server-revit/tests/test_i18n_readmes.py`.

## Releases and versions

The project uses Semantic Versioning, and the root `VERSION` file is the
single source of truth. Tags use the form `vX.Y.Z`. Do not bump version numbers
by hand in other files. [docs/versioning.md](docs/versioning.md) describes the
release process, and [CHANGELOG.md](CHANGELOG.md) lists what changed.

## Repository Hygiene & Build Artifacts

- **Build artifacts (`dist/`, `build/`)**: Do not commit compiled files, zip packages, or binary builds. Releases are attached to GitHub Releases.
- **Virtual environments**: Run tests and scripts inside a local `.venv`. Git ignores it.

## Pull Request Checklist

Before opening a PR, confirm that:
- the change has clear reproduction and validation steps
- config examples still work with placeholder values
- README or docs are updated when setup or behavior changes
- any limitations or known gaps are called out explicitly

Accepted contributions are credited in [CONTRIBUTORS.md](CONTRIBUTORS.md).
