# Changelog fragments

Each pull request adds one file here instead of editing `CHANGELOG.md`, so changelogs never conflict.

- Name: `changes/<issue-or-branch>.md`, for example `changes/issue-187.md`.
- Content: one or more lines starting with `- `, written like a changelog line (what changed, `Fixes #N`, UNVERIFIED where it applies). An indented line continues the bullet above.
- A change that adds or removes tools also states the new total in its fragment, for example `Tool count is now 325.` Then run `python scripts/sync_counts.py` and `python scripts/make_llms_full.py`.
- `python scripts/changelog.py check` validates the files. CI runs it.
- At release, `python scripts/changelog.py build --version X.Y.Z` moves all fragments into a new section at the top of `CHANGELOG.md` and deletes them. Lines still under `## Unreleased` are folded in too.
