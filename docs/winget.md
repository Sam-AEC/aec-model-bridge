# winget package

The Windows installer `AECModelBridge-Setup-<version>.exe` from each stable GitHub release can be listed in the Windows Package Manager (winget) as `SamAEC.AECModelBridge`. Nothing is submitted automatically. The package is not in `microsoft/winget-pkgs` yet.

## Files

- `packaging/winget/manifests/`: templates for the three manifests (version, installer, defaultLocale), schema 1.10.0. Placeholders look like `__VERSION__`.
- `packaging/winget/fill_manifests.py`: fills version, installer URL, installer SHA-256 and release notes URL for one release. Standard library only.
- `packages/mcp-server-revit/tests/test_winget_manifests.py`: checks the templates against `scripts/installer/AECModelBridge.iss` and tests the script.

Installer facts the manifests depend on, all from `AECModelBridge.iss`:

- Inno Setup, `PrivilegesRequired=lowest`, so `Scope: user`. Files still go to the fixed folder `C:\ProgramData\AECModelBridge`.
- x64 only, Windows 10 or later.
- `ProductCode` is the Inno `AppId` plus `_is1`. Change both together.
- winget's default Inno switches (`/SP- /VERYSILENT /SUPPRESSMSGBOXES /NORESTART`) are the base switches `scripts/test-installer.ps1` runs. That test also passes `/COMPONENTS` and `/SKIPWEBVIEW2=1`; which Revit years a plain `winget install` selects is UNVERIFIED.

If any of these change in the `.iss` file, update the installer template; the test fails until they agree.

## Fill the manifests for a release

Run after the release is published, from the repository root:

```bash
python packaging/winget/fill_manifests.py 1.6.0
```

The script downloads the installer and `SHA256SUMS.txt` from the `v1.6.0` release, hashes the installer, and refuses to write anything if the hash differs from `SHA256SUMS.txt`. Output goes to `dist/winget/manifests/s/SamAEC/AECModelBridge/1.6.0/`, the `microsoft/winget-pkgs` layout.

With a local installer: `--installer dist/release/AECModelBridge-Setup-1.6.0.exe`. Add `--offline` to skip the `SHA256SUMS.txt` check (for a dry run only; a submission must point at the published asset).

Check the result on Windows:

```powershell
winget validate --manifest dist\winget\manifests\s\SamAEC\AECModelBridge\1.6.0
winget install --manifest dist\winget\manifests\s\SamAEC\AECModelBridge\1.6.0
```

`winget install --manifest` needs `winget settings --enable LocalManifestFiles` once, from an elevated shell.

## Submit to microsoft/winget-pkgs

Submission is a pull request to `microsoft/winget-pkgs` from a fork, made by the maintainer. `wingetcreate` (Windows Package Manager Manifest Creator) opens it.

First version:

```powershell
winget install Microsoft.WingetCreate
wingetcreate submit --token <github-pat> dist\winget\manifests\s\SamAEC\AECModelBridge\1.6.0
```

Later versions, once the package exists in `winget-pkgs`, can skip the templates:

```powershell
wingetcreate update SamAEC.AECModelBridge --version 1.7.0 `
  --urls https://github.com/Sam-AEC/aec-model-bridge/releases/download/v1.7.0/AECModelBridge-Setup-1.7.0.exe `
  --submit --token <github-pat>
```

The token needs the `public_repo` scope; `wingetcreate` forks `winget-pkgs` under that account. Do not store the token in this repository.

The `winget-pkgs` pipeline validates the manifests, installs the package in a sandbox and scans it. The installer is not Authenticode signed (see [supply-chain.md](supply-chain.md)); the pipeline accepts unsigned installers, but reviewers may ask about SmartScreen warnings. Pre-releases are not submitted.
