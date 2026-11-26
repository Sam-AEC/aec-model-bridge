# Supply chain: what is signed, what is not

This page says plainly how much you can trust a download from this project, and how to check it yourself.

## What is attested today

The current `Build GitHub Release` workflow builds on GitHub-hosted runners and runs `actions/attest-build-provenance` over `dist/release/*` before publishing. This produces a signed build provenance attestation stored by GitHub, linking each file to the repository, commit and workflow run. The attestation bundle is also attached to the release as `aec-model-bridge-<version>.intoto.jsonl`; check a download offline with `gh attestation verify <file> --bundle <bundle> --repo Sam-AEC/aec-model-bridge`. Older releases may predate these checks; verify the individual download.

Each release also carries:

- `SHA256SUMS.txt`: a SHA-256 checksum for every other release file, including the SBOM.
- `aec-model-bridge-<version>.cdx.json`: a CycloneDX software bill of materials (SBOM) for the Python distributions actually installed in the shipped bundle, including installation tools such as pip.

The release files attested this way include the `.mcpb` bundle, the per-year add-in zips (`aec-model-bridge-revit-<year>-<version>.zip`), the installer, the SBOM and `SHA256SUMS.txt`.

The PyPI package is built from the stable tag by `.github/workflows/publish-pypi.yml` and uploaded with Trusted Publishing, so no PyPI token is stored in the repository. The `build` job of that workflow also runs `actions/attest-build-provenance` over the wheel and sdist before they are uploaded. The attestation permissions (`id-token: write`, `attestations: write`) are set on the job that attests, not on the whole workflow. Both workflows pin the action by full commit SHA. `pypa/gh-action-pypi-publish` uploads digital attestations (PEP 740) by default with Trusted Publishing; this is UNVERIFIED until the first upload. `.github/workflows/scorecard.yml` runs the OpenSSF Scorecard weekly and publishes the result shown by the README badge.

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

The same command works for the `.mcpb` bundle, the add-in zips and the wheel or sdist downloaded from PyPI:

```bash
gh attestation verify aec-model-bridge-1.6.0.mcpb --repo Sam-AEC/aec-model-bridge
gh attestation verify aec-model-bridge-revit-2026-1.6.0.zip --repo Sam-AEC/aec-model-bridge
pip download aec-model-bridge==1.6.0 --no-deps -d dl
gh attestation verify dl/aec_model_bridge-1.6.0-py3-none-any.whl --repo Sam-AEC/aec-model-bridge
```

Attestations for the wheel and sdist exist only for releases built after this step was added. A release made before then reports no attestation; that is expected and does not mean the file was changed.

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
