"""Check a CycloneDX inventory against the Python environment actually shipped."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path


def canonical_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def package_version(version: str) -> str:
    # VERSION uses SemVer; wheel metadata uses PEP 440 for prereleases.
    return re.sub(r"-(alpha|a|beta|b|rc)\.?(\d+)$",
                  lambda m: {"alpha": "a", "beta": "b"}.get(m[1], m[1]) + m[2], version)


def validate(bom: dict, installed: list[dict], version: str) -> None:
    expected: dict[str, str] = {}
    for dist in installed:
        name = canonical_name(dist["name"])
        if name in expected and expected[name] != dist["version"]:
            raise ValueError(f"Multiple installed versions of {name}")
        expected[name] = dist["version"]
    if expected.get("aec-model-bridge") != package_version(version):
        raise ValueError("Bundled aec-model-bridge version does not match the release")
    root = bom.get("metadata", {}).get("component", {})
    if (canonical_name(root.get("name", "")) != "aec-model-bridge"
            or package_version(root.get("version", "")) != package_version(version)):
        raise ValueError("SBOM root component does not match the release")
    # CycloneDX may represent the installed project only as the root component,
    # or repeat it in components (for example for an editable installation).
    actual: dict[str, str] = {canonical_name(root["name"]): package_version(root["version"])}
    for component in bom.get("components", []):
        name = canonical_name(component["name"])
        if name in actual and actual[name] != component.get("version"):
            raise ValueError(f"Multiple SBOM versions of {name}")
        actual[name] = component.get("version", "")
    if actual != expected:
        differences = sorted(name for name in actual.keys() | expected.keys()
                             if actual.get(name) != expected.get(name))
        raise ValueError("SBOM differs from the shipped environment: " + ", ".join(differences))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sbom", type=Path)
    parser.add_argument("--python", required=True, help="Bundled Python interpreter")
    parser.add_argument("--version", required=True)
    args = parser.parse_args()
    code = (
        "import importlib.metadata as m, json; "
        "print(json.dumps([{'name':d.metadata['Name'], 'version':d.version} "
        "for d in m.distributions()]))"
    )
    result = subprocess.run([args.python, "-I", "-c", code], check=True,
                            capture_output=True, text=True)
    installed = json.loads(result.stdout)
    validate(json.loads(args.sbom.read_text(encoding="utf-8")), installed, args.version)
    print(f"SBOM matches {len(installed)} installed distributions in the shipped Python environment")


if __name__ == "__main__":
    main()
