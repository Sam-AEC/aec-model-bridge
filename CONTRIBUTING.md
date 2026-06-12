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

## Repository Hygiene & Build Artifacts

- **Build Artifacts (`dist/`, `build/`)**: Compiled distribution files, zip packages, and binary builds must not be committed to the git repository. All releases are attached directly to GitHub Releases.
- **Local virtual environments**: Always run tests and scripts within local `.venv` environments, which are ignored by git.

## Pull Request Checklist

Before opening a PR, confirm that:
- the change has clear reproduction and validation steps
- config examples still work with placeholder values
- README or docs are updated when setup or behavior changes
- any limitations or known gaps are called out explicitly
