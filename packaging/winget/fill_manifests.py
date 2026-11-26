"""Fill the winget manifest templates for one AEC Model Bridge release.

Writes the three manifests (version, installer, defaultLocale) in the
microsoft/winget-pkgs layout:

    <out>/manifests/s/SamAEC/AECModelBridge/<version>/

The installer SHA-256 comes from the installer file itself: a local copy given
with --installer, or a download of the release asset. Unless --offline is set,
the hash must also match the entry in the release's SHA256SUMS.txt. Any
mismatch stops the script without writing files.

Usage:
    python packaging/winget/fill_manifests.py 1.6.0
    python packaging/winget/fill_manifests.py 1.6.0 --installer dist/release/AECModelBridge-Setup-1.6.0.exe
    python packaging/winget/fill_manifests.py 1.6.0 --installer <path> --offline --out <dir>

Standard library only. See docs/winget.md.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
import tempfile
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
TEMPLATES = HERE / "manifests"
PACKAGE_ID = "SamAEC.AECModelBridge"
REPO_URL = "https://github.com/Sam-AEC/aec-model-bridge"
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
PLACEHOLDER_RE = re.compile(r"__[A-Z0-9_]+__")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class FillError(Exception):
    """A plain-language reason the manifests were not written."""


def installer_name(version: str) -> str:
    return f"AECModelBridge-Setup-{version}.exe"


def release_url(version: str, name: str) -> str:
    return f"{REPO_URL}/releases/download/v{version}/{name}"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download(url: str, dest: Path) -> None:
    if not url.startswith("https://"):
        raise FillError(f"Refusing a non-HTTPS URL: {url}")
    try:
        with urllib.request.urlopen(url, timeout=120) as response, dest.open("wb") as out:  # noqa: S310
            while chunk := response.read(1 << 20):
                out.write(chunk)
    except OSError as exc:
        raise FillError(f"Could not download {url}: {exc}") from exc


def sum_from_checksums(text: str, name: str) -> str:
    """Return the SHA-256 listed for ``name`` in a SHA256SUMS.txt body."""
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].lstrip("*") == name:
            value = parts[0].lower()
            if not SHA256_RE.match(value):
                raise FillError(f"SHA256SUMS.txt has a malformed hash for {name}")
            return value
    raise FillError(f"SHA256SUMS.txt has no entry for {name}")


def fill_text(template: str, values: dict[str, str]) -> str:
    text = template
    for key, value in values.items():
        text = text.replace(f"__{key}__", value)
    left = sorted(set(PLACEHOLDER_RE.findall(text)))
    if left:
        raise FillError(f"Unfilled placeholders: {', '.join(left)}")
    # Drop the template notice so the output is ready to submit.
    lines = [line for line in text.splitlines() if not line.startswith("# Template.")]
    return "\n".join(lines) + "\n"


def fill(version: str, sha256: str, out: Path) -> Path:
    if not VERSION_RE.match(version):
        raise FillError(f"Version '{version}' is not a stable MAJOR.MINOR.PATCH version")
    sha256 = sha256.lower()
    if not SHA256_RE.match(sha256):
        raise FillError("Installer SHA-256 must be 64 hexadecimal characters")
    values = {
        "VERSION": version,
        "INSTALLER_URL": release_url(version, installer_name(version)),
        "INSTALLER_SHA256": sha256.upper(),
        "RELEASE_NOTES_URL": f"{REPO_URL}/releases/tag/v{version}",
    }
    templates = sorted(TEMPLATES.glob(f"{PACKAGE_ID}*.yaml"))
    if len(templates) != 3:
        raise FillError(f"Expected 3 manifest templates in {TEMPLATES}, found {len(templates)}")
    rendered = {t.name: fill_text(t.read_text(encoding="utf-8"), values) for t in templates}
    target = out / "manifests" / "s" / "SamAEC" / "AECModelBridge" / version
    target.mkdir(parents=True, exist_ok=True)
    for name, text in rendered.items():
        (target / name).write_text(text, encoding="utf-8", newline="\n")
    return target


def resolve_sha256(version: str, installer: Path | None, offline: bool) -> str:
    name = installer_name(version)
    with tempfile.TemporaryDirectory() as tmp:
        if installer is None:
            if offline:
                raise FillError("--offline needs --installer, because nothing can be downloaded")
            installer = Path(tmp) / name
            _download(release_url(version, name), installer)
        elif not installer.is_file():
            raise FillError(f"Installer not found: {installer}")
        actual = sha256_file(installer)
        if not offline:
            sums = Path(tmp) / "SHA256SUMS.txt"
            _download(release_url(version, "SHA256SUMS.txt"), sums)
            listed = sum_from_checksums(sums.read_text(encoding="ascii"), name)
            if listed != actual:
                raise FillError(
                    f"Installer SHA-256 {actual} does not match SHA256SUMS.txt ({listed}). Nothing written."
                )
    return actual


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("version", help="Release version without the v, for example 1.6.0")
    parser.add_argument("--installer", type=Path, help="Local copy of the installer to hash")
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Skip the SHA256SUMS.txt check (needs --installer)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT / "dist" / "winget",
        help="Output folder (default: dist/winget, which git ignores)",
    )
    args = parser.parse_args(argv)
    try:
        if not VERSION_RE.match(args.version):
            raise FillError(f"Version '{args.version}' is not a stable MAJOR.MINOR.PATCH version")
        sha256 = resolve_sha256(args.version, args.installer, args.offline)
        target = fill(args.version, sha256, args.out)
    except FillError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"Wrote winget manifests for {args.version} to {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
