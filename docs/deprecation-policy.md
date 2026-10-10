# Deprecation policy

This page says how features, tools and supported versions are retired. It builds on [versioning.md](versioning.md), which sets the meaning of each version number. Where the two disagree, `versioning.md` wins.

AEC Model Bridge is maintained by one person ([GOVERNANCE.md](../GOVERNANCE.md)). The notice periods below are what the project aims for. They are not a contract.

## Supported versions

### Revit

| Revit | Add-in target | Built in CI | Status |
|---|---|---|---|
| 2024 | net48 | Yes | Supported |
| 2025 | net8.0-windows | Yes | Supported |
| 2026 | net8.0-windows | Yes | Supported |
| 2027 | net10.0-windows | Yes | Supported |
| 2023 and earlier | none | No | Not supported |

Every release ships one package per supported Revit year. Sources: [target-frameworks-and-dependencies.md](target-frameworks-and-dependencies.md), [versioning.md](versioning.md) and the `addin` job in `.github/workflows/ci.yml`.

### Python

| Python | CI | Status |
|---|---|---|
| 3.11 | Windows | Supported |
| 3.12 | Windows | Supported |
| 3.13 | Windows | Supported |
| 3.12 | Linux | Experimental. Failures do not block CI. |
| 3.10 and earlier | none | Not supported (`requires-python = ">=3.11"`) |

Python 3.14 and later are not tested. They may work, but nobody has checked.

### Project versions

| Version | Receives fixes |
|---|---|
| Latest 1.x release (see [`VERSION`](../VERSION)) | Yes |
| Older 1.x releases | Not separately. Upgrade to the latest 1.x. |
| Earlier than 1.0 | No |

The same table is in [SECURITY.md](../SECURITY.md#supported-versions). The repository does not describe backports to older minor lines, so none are promised.

## What counts as a breaking change

[versioning.md](versioning.md) calls for a MAJOR bump when any of these happen:

- a tool is removed or renamed
- a tool's arguments change in a way that breaks existing prompts or recipes
- a supported Revit version is dropped

Removals of this kind happen only in a major release.

## How a deprecation works

1. **Announce.** The feature is marked deprecated in a minor release. The note goes in [CHANGELOG.md](../CHANGELOG.md) and in the docs or tool description. Where it is practical, the tool also returns a warning.
2. **Keep working.** A deprecated feature keeps its behaviour. Fixes for serious bugs and security problems still apply.
3. **Remove.** The feature is removed in a later major release. The changelog says so and names the replacement.

The aim is to keep a deprecated feature for at least one minor release before the major release that removes it.

## Dropping a Revit or Python version

- **Adding a Revit year** is a minor release.
- **Dropping a Revit year** is a major release, as `versioning.md` says. It is announced in the changelog before the release that removes it.
- **Dropping a Python version** raises `requires-python`. Treat it as a breaking change and announce it the same way.

## Security exceptions

A security fix may break compatibility without the usual notice if there is no safe way to keep the old behaviour. The release notes will say what changed and why.

## Experimental and in-progress features

Features marked "in progress" or "experimental" in the docs may change or go away in any release. Navisworks and Power BI in [compatibility.md](compatibility.md) are examples. They are outside this policy.
