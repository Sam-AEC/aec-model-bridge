# Versioning and releases

AEC Model Bridge follows [Semantic Versioning 2.0.0](https://semver.org). The version is `MAJOR.MINOR.PATCH`, and release tags are the same number with a `v` in front: `v1.3.0`.

One file decides the version: [`VERSION`](../VERSION) in the repository root. Everything else is generated from it, so the Revit add-in, the MCP server, the installer and the registry listing can never disagree.

## What each number means

| Bump | Use it when | Example |
|---|---|---|
| **MAJOR** | A tool is removed or renamed, a tool's arguments change in a way that breaks existing prompts or recipes, or a supported Revit version is dropped. | `1.3.0` to `2.0.0` |
| **MINOR** | You add tools, workflows, UI, a new Revit version, or a new provider. Existing behaviour keeps working. | `1.2.1` to `1.3.0` |
| **PATCH** | Bug fixes, CI fixes, documentation and security patches with no new features. | `1.3.0` to `1.3.1` |

Pre-releases use a hyphen suffix: `1.4.0-rc.1`, `1.4.0-beta.2`. GitHub marks them as pre-releases automatically. The Python wheel is named with the PEP 440 form (`1.4.0rc1`); `build-release.ps1` converts it for you.

## Where the version lives

`scripts/version.py` keeps these in sync:

| File | Field |
|---|---|
| `VERSION` | the source of truth |
| `packages/mcp-server-revit/pyproject.toml` | `version` |
| `packages/mcp-server-revit/manifest.json` | `version` (MCP bundle) |
| `server.json` | `version`, package `version`, release download URL |
| `packages/revit-bridge-addin/RevitBridge.csproj` | `Version`, `AssemblyVersion`, `FileVersion`, `InformationalVersion` |
| `packages/navisworks-bridge-addin/`, `rhino-bridge-addin/`, `powerbi-bridge-tool/` | `Version` in each `.csproj` |
| `scripts/installer/AECModelBridge.iss` | `AppVersion` |

`AssemblyVersion` and `FileVersion` are four-part numbers, so `1.3.0` becomes `1.3.0.0` and any pre-release suffix is dropped there.

`server.json` also carries a `fileSha256` for the `.mcpb` bundle. That hash only exists once the release is built, so the publish workflow refreshes it. Do not edit it by hand.

## Cutting a release

1. Make sure `CHANGELOG.md` has your notes under `## Unreleased`.
2. Pick the bump and let the script do the edits:

   ```powershell
   python scripts/version.py bump minor      # or: major | patch
   python scripts/version.py set 1.4.0-rc.1  # or set an exact version
   ```

   This rewrites every file above and renames `## Unreleased` to `## 1.4.0 - <today>`.
3. Check, commit, tag and push:

   ```powershell
   python scripts/version.py check
   git commit -am "chore(release): 1.4.0"
   git tag v1.4.0
   git push --follow-tags
   ```

4. The **Build GitHub Release** workflow starts on the tag. It confirms the tag, `VERSION`, every manifest and the changelog agree, runs the Python tests, builds the add-in and installer bundle, and publishes the GitHub release with the changelog section as its notes.
5. Publishing the release starts **Publish MCP Server**, which fills in the bundle hash for the registry.

If the tag and `VERSION` disagree, or the changelog has no section for that version, the release stops before building anything.

To rebuild an existing release, run **Build GitHub Release** by hand and enter the tag (for example `v1.4.0`). It re-uploads the files and replaces the notes.

## Checks that run automatically

- **Every push and pull request:** CI runs `python scripts/version.py check`. If someone edits one manifest by hand, the build fails and prints what is out of step and the command that fixes it.
- **Every tag:** the release workflow runs the same check with `--tag`, so a mistyped tag cannot ship.

## Command reference

```text
python scripts/version.py show               print the current version
python scripts/version.py check [--tag vX]   fail on drift (and on tag/changelog mismatch)
python scripts/version.py set X.Y.Z          set an exact version, roll the changelog
python scripts/version.py bump minor         increment major, minor or patch
python scripts/version.py notes [X.Y.Z]      print one changelog section (used for release notes)
```

Add `--no-changelog` to `set` or `bump` if you do not want the changelog touched.

## Choosing the Revit year for a release

The release workflow packages one Revit year, `2027` by default. When you run it by hand you can choose another year in the `revit_version` input. For local testing of a single year, build it directly:

```powershell
./scripts/build-addin.ps1 -RevitVersion 2026 -Configuration Release
```
