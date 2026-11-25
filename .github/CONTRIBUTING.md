# Contributing

Thanks for improving AEC Model Bridge.

## Licensing

Open an issue before you write code. The project is licensed under
GPL-3.0-or-later with the Revit Linking Exception, and it also has a commercial
licence. To keep both options, the maintainer needs the right to license each
contribution under both.

There is no contributor agreement in force yet. Until there is one, code pull
requests cannot be merged. We are not asking anyone to sign anything now.
[docs/legal/CLA-DRAFT.md](../docs/legal/CLA-DRAFT.md) is a draft of what it might
look like. It is not reviewed by a lawyer and not in force. If you plan a larger
code contribution, say so in your issue and we will settle the terms first.

Issue reports, design proposals and documentation corrections are welcome
without any agreement.

## Dependencies and licences

- Do not vendor or copy GPL-only code into this repository. This includes
  pyRevit, Bonsai (BlenderBIM) and Dynamo samples unless their licence allows
  it. Calling such a tool from outside, without copying its code, is fine, but
  ask in an issue first.
- Do not add proprietary dependencies without discussing them in an issue
  first. Autodesk Revit and Navisworks assemblies are referenced from the
  user's own installation and are never committed or packaged (see
  [TRADEMARKS.md](../docs/legal/TRADEMARKS.md)).
- A new dependency needs a licence that is compatible with GPL-3.0-or-later
  and that does not stop a commercial licence of this project. MIT, BSD, ISC,
  Apache-2.0 and PSF are fine. LGPL needs a discussion. Do not add AGPL, SSPL
  or GPL-only libraries.
- After you change a dependency, regenerate the notices with
  `python scripts/generate_third_party_notices.py` in an environment synced
  from `uv.lock` (`uv sync --frozen`), and commit the result.

## Focus Areas

Contributions help most in these areas:
- Revit command coverage
- MCP tool reliability and error handling
- installation and configuration documentation
- developer ergonomics for local debugging and testing

## Guidelines

- Keep each pull request to one feature, fix or documentation update.
- Name the Revit versions you tested in the PR description.
- Remove local paths, machine names and credentials from config examples.
- If a change affects the UI or commands, give the steps to reproduce it and say what should happen.
- Update examples and docs when behaviour changes.
- Villa recipes under `docs/recipes/` are integration-test evidence. Keep villa-specific work in fixtures and verification records, and group test changes with the reusable tool feature they validate.
- Do not commit session handoffs, local worktree paths, personal file paths or client project/document names. Put durable decisions in an ADR and user-visible changes in `CHANGELOG.md`.

## Building and testing

Build the add-in for one Revit version and run the Python tests:

```powershell
.\scripts\build-addin.ps1 -RevitVersion 2026 -Configuration Release
python -m pytest packages/mcp-server-revit/tests
```

Supported Revit versions are 2024 (net48), 2025 and 2026 (net8.0-windows), and
2027 (net10.0-windows). See
[docs/target-frameworks-and-dependencies.md](../docs/target-frameworks-and-dependencies.md).

## Good first issues

You do not need Revit or Windows for these. The Python tests run in mock mode. The [project board](https://github.com/users/Sam-AEC/projects) has a Contributors view of open community issues by area ([how the board works](../docs/project-board.md)).

To skip local setup, open the repository in its dev container (`.devcontainer/devcontainer.json`, for example with GitHub Codespaces or the VS Code Dev Containers extension). It installs Python 3.13 and uv, runs `uv sync --all-extras` in `packages/mcp-server-revit`, and sets `MCP_REVIT_MODE=mock`.

`examples/mock-tour.ipynb` walks through a read, a snapshot query, a `snapshot_compute` pipeline and a plan in mock mode, and stops where a person would approve.
`examples/ifc-speckle-roundtrip.ipynb` does the same for an IFC and Speckle exchange round trip ([docs/ifc-speckle-roundtrip.md](../docs/ifc-speckle-roundtrip.md)).

### Run the tests

Install the package with its dev extra (`pip install -e "packages/mcp-server-revit[dev]"`), then run:

```bash
cd packages/mcp-server-revit
PYTHONPATH=src python -m pytest tests/test_tools.py tests/test_config.py   # one or two files
PYTHONPATH=src python -m pytest tests                                      # everything
```

On Windows PowerShell, set the variable first: `$env:PYTHONPATH = "src"`.

Optional pre-commit hooks (`.pre-commit-config.yaml`) run `ruff check`, `python scripts/version.py check` and the tool-count test before each commit, with the versions in `uv.lock`. They need uv on PATH. Install them with `pre-commit install`; run them on demand with `pre-commit run --all-files`.

The full run takes about half a minute. A few tests are skipped on purpose: the end-to-end test needs a live Revit, and the proxy tests need a bridge. `test_wheel_contents.py` builds the wheel, so it needs an up-to-date `build` and `setuptools`. If it fails with a licence-metadata error on an old setuptools, upgrade setuptools before you report it.

### Property and mutation tests

`tests/test_property_*.py` use [Hypothesis](https://hypothesis.readthedocs.io/):

- `test_property_gate.py`: a state machine drives the approval gate through random sequences of plan, approve, reject, execute, direct calls, mode switches (look only, ask first, Auto, timed Auto, Dev), expiry, document changes and edits of plan files. A model predicts every approval and every write; any difference fails the test.
- `test_property_safe_paths.py`: generated hostile names and paths (`..`, absolute, drive letters, UNC, NUL, look-alike Unicode, links in the folder) never leave the root.
- `test_property_input_fuzz.py`: random JSON for `plan_actions`, `execute_plan`, direct calls and the validators raises only `BridgeError` or `ValueError`.

The default profile runs a few examples with a fixed seed, so the suite stays fast and repeatable. For a deeper run:

```bash
AEC_HYPOTHESIS_PROFILE=slow uv run pytest -q -p no:cacheprovider tests/test_property_*.py
```

The `slow` profile takes a few minutes. Hypothesis prints a `@reproduce_failure` line for any failure; add a regular test for it before you fix the code.

Mutation testing of `security/` uses mutmut (configured under `[tool.mutmut]` in `packages/mcp-server-revit/pyproject.toml`). It is not a dependency and not run in CI. It needs Linux or macOS:

```bash
cd packages/mcp-server-revit
uv run --with mutmut mutmut run                                       # all of security/ (long)
uv run --with mutmut mutmut run "revit_mcp_server.security.safe_paths*" # one module
uv run --with mutmut mutmut results                                   # surviving mutants
```

A surviving mutant is a change to the code that no test noticed. Add a test that kills it, or note why it is equivalent. A sample run over `security/safe_paths.py` killed 55 of 58 mutants; the 3 survivors are the `startswith` check, which the stricter parent-folder check covers (2 mutants), and the text of one error message.

### Starter tasks

Pick one, say so in an issue, and keep the pull request small.

1. **Review a translation.** The 16 READMEs in [docs/i18n/](../docs/i18n/) are AI-assisted drafts. A native speaker can fix wording. See [Translations](#translations).
2. **Add a language.** Dutch, Swedish and Czech are not there yet. The steps are in [Translations](#translations), and `test_i18n_readmes.py` checks your work.
3. **Add a test for the Power BI provider.** `providers/powerbi.py` has no test that mentions it. A small mock-mode test is a good start.
4. **Try an untested MCP client.** [docs/compatibility.md](../docs/compatibility.md) lists clients marked "not tested". Set one up in mock mode and send a pull request that updates its row, with the steps you used.
5. **Try the server on Linux.** The Linux CI job is experimental because the Windows-only parts (bridge discovery, path mapping) have not been exercised there. Run the tests on Linux and open an issue for each failure you find.
6. **Check the docs for stale statements.** Pick one page from `docs/`, follow it on a clean machine, and fix what is wrong or unclear.
7. **Tidy formatting.** CI reports how many files `ruff format` would change, and does not enforce it. Format a few files in one pull request, with no other changes.
8. **Improve an error message.** Find a tool that returns a vague error in `packages/mcp-server-revit/src/revit_mcp_server/` and make it say what went wrong and what to do. Add a test for it.

## Translations

Translated READMEs live in `docs/i18n/` as `README.<language>.md` and are
linked from the language bar at the top of `README.md`. The English
`README.md` is canonical. If a translation differs from it, the English text
wins, and README changes are made in English first. The current translations
are AI-assisted drafts, so corrections from native speakers are especially
welcome.

To improve a translation, edit the file in `docs/i18n/` and open a pull
request. Keep code blocks, commands, tool names, environment variable names,
file paths, product names, counts and licence text exactly as in the English
README. Use the standard AEC term in your language (for example parameter,
sheet, view, family, worksharing).

To add a language, copy an existing translation and translate the prose. Then
add the language to the bar in `README.md` and in every file in `docs/i18n/`,
and to the list in `packages/mcp-server-revit/tests/test_i18n_readmes.py`.
That test checks that code blocks match the English README, headings line up,
the language bar is present and relative links resolve. Run it with
`python -m pytest packages/mcp-server-revit/tests/test_i18n_readmes.py`.

## Releases and versions

The project uses Semantic Versioning, and the root `VERSION` file is the
single source of truth. Tags look like `vX.Y.Z`. Do not change version numbers
by hand in other files. [docs/versioning.md](../docs/versioning.md) describes the
release process, and [CHANGELOG.md](../CHANGELOG.md) lists what changed.

## Repository Hygiene & Build Artifacts

- **Build artifacts (`dist/`, `build/`)**: Do not commit compiled files, zip packages or binary builds. We attach them to GitHub Releases.
- **Virtual environments**: Run tests and scripts inside a local `.venv`. Git ignores it.

## Pull Request Checklist

Before opening a PR, confirm that:
- the change has clear steps to reproduce and to check it
- config examples still work with placeholder values
- README or docs are updated when setup or behaviour changes
- any limits or known gaps are stated

Accepted contributions are credited in the pull request and in `CHANGELOG.md`.

## Decisions

The project has one maintainer, who decides. Larger design choices are written as numbered notes in `docs/adr/` (ADRs). CI must pass and the maintainer reads every change. Releases follow [docs/versioning.md](../docs/versioning.md); removals follow [docs/deprecation-policy.md](../docs/deprecation-policy.md). Conduct rules are in [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
