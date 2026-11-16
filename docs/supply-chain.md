# Supply chain: what is signed, what is not

This page says plainly how much you can trust a download from this project, and how to check it yourself.

## What is attested today

The current `Build GitHub Release` workflow builds on GitHub-hosted runners and runs `actions/attest-build-provenance` over `dist/release/*` before publishing. This produces a signed build provenance attestation stored by GitHub, linking each file to the repository, commit and workflow run. Older releases may predate these checks; verify the individual download.

Each release also carries:

- `SHA256SUMS.txt`: a SHA-256 checksum for every other release file, including the SBOM.
- `aec-model-bridge-<version>.cdx.json`: a CycloneDX software bill of materials (SBOM) for the Python distributions actually installed in the shipped bundle, including installation tools such as pip.

## What is not signed

- The Windows installer (`AECModelBridge-Setup-<version>.exe`) and the add-in DLLs are **not Authenticode code signed**. Windows SmartScreen may warn about the installer. The provenance attestation proves where the file was built, but Windows itself does not check it.
- There is no detached signature (`.sig`) or GPG signature next to the release files.
- Builds are not yet reproducible, so you cannot rebuild a file and compare bytes.
- The release SBOM covers installed Python distributions. It does not list .NET dependencies, the VS Code extension, or the Python interpreter and standard library. The wheel and MCP bundle may resolve dependencies differently when a client installs them; the SBOM describes the portable Python shipped in the Revit archives and installer.

## How to verify a download

Download the file and `SHA256SUMS.txt` from the same release page.

Check the checksum (Linux, macOS, Git Bash):

```bash
sha256sum -c --ignore-missing SHA256SUMS.txt
```

On Windows PowerShell:

```powershell
(Get-FileHash .\AECModelBridge-Setup-1.4.0.exe -Algorithm SHA256).Hash.ToLower()
# compare with the matching line in SHA256SUMS.txt
```

Check the build provenance with the GitHub CLI:

```bash
gh attestation verify AECModelBridge-Setup-1.4.0.exe --repo Sam-AEC/aec-model-bridge
```

A checksum only proves the file matches the release page. The attestation is the stronger check, because it proves the file was built by this repository's workflow.

## Where the SBOM is

- **Releases:** `aec-model-bridge-<version>.cdx.json` is a release asset, listed in `SHA256SUMS.txt` and covered by the attestation.
- **Pull requests, `main` and `dev`:** the `sbom` job in `.github/workflows/ci.yml` uploads a separate lock inventory as `sbom-lock-cyclonedx` (kept 14 days). It lists locked runtime requirements, including platform alternatives, rather than an installed release environment.

The bundler exports runtime versions from `uv.lock` with `uv export --frozen --no-dev --no-emit-project` and installs the project without resolving dependencies again. The release workflow runs the pinned SBOM generator outside that environment, validates the inventory against installed distributions and the release version, then refreshes checksums before attesting and publishing. Both inventories use CycloneDX 1.6 JSON.

After building the portable bundle, regenerate its release inventory from the repository root in PowerShell:

```powershell
$bundlePython = (Resolve-Path dist/AECModelBridge/python/python.exe).Path
$version = (Get-Content VERSION -Raw).Trim()
uvx --from cyclonedx-bom==7.2.1 cyclonedx-py environment $bundlePython --pyproject packages/mcp-server-revit/pyproject.toml --sv 1.6 --of JSON --output-reproducible --validate -o "aec-model-bridge-$version.cdx.json"
python scripts/validate_release_sbom.py "aec-model-bridge-$version.cdx.json" --python $bundlePython --version $version
```

To regenerate the separate lock inventory:

```bash
cd packages/mcp-server-revit
python -m pip install "cyclonedx-bom==7.2.1"
uv export --frozen --no-dev --no-hashes --no-emit-project --format requirements-txt -o /tmp/req.txt
cyclonedx-py requirements /tmp/req.txt --pyproject pyproject.toml --sv 1.6 --of JSON -o aec-model-bridge.cdx.json
```

A publishing `workflow_dispatch` rebuild must select the release tag in the workflow's ref selector as well as its `tag` input. The workflow rejects a different checked-out commit so the attestation's source commit matches the build. For a branch experiment, use `dry_run` with the optional `ref` input; it uploads artifacts without publishing or attesting them.
