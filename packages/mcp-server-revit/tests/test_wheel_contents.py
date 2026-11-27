"""Build the wheel and check that the non-Python data files really ship in it.

Regression guard: module manifests (module.json), QA/QC rules and recipes (yaml)
were once missing from the built wheel, so a ``pip``/``uvx`` install silently lacked
every module tool that a source checkout has. A declaration in pyproject.toml is not
proof; only the built artifact is.
"""
from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
SRC_PACKAGE = PACKAGE_ROOT / "src" / "revit_mcp_server"

# Slow (about 57 s each): CI runs these on the primary leg only; the others use -m "not slow".
# One xdist group keeps the module on a single worker, so the wheel is built once (#239).
pytestmark = [pytest.mark.timeout(300), pytest.mark.slow, pytest.mark.xdist_group("wheel-build")]


_BUILD_HINT = "the 'build' package is not installed; run 'uv sync --extra dev' or 'pip install build'"


def _require_build() -> None:
    """Skip locally when `build` is missing; fail when CI is set, so the guard cannot vanish silently."""
    if importlib.util.find_spec("build") is not None:
        return
    if os.environ.get("CI"):
        pytest.fail(_BUILD_HINT, pytrace=False)
    pytest.skip(_BUILD_HINT)


# Everything the build reads: pyproject.toml, the readme, the license-files and the package.
# Only these are copied. The package root also holds files that other xdist workers create
# and delete while the suite runs (`.coverage.*` from pytest-cov, `.hypothesis/`), and
# copying the whole root failed when one vanished mid-copy (#398).
BUILD_INPUTS = ("pyproject.toml", "README.md", "LICENSE", "NOTICE", "LICENSING.md", "LICENSES", "src")
_IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", "*.egg-info")


def _copy_build_inputs(dest: Path, root: Path = PACKAGE_ROOT) -> None:
    """Copy the build inputs of ``root`` into ``dest``, and nothing else from the root."""
    dest.mkdir(parents=True)
    for name in BUILD_INPUTS:
        path = root / name
        if path.is_dir():
            shutil.copytree(path, dest / name, ignore=_IGNORE)
        else:
            shutil.copy2(path, dest / name)


@pytest.fixture(scope="module")
def built_wheel(tmp_path_factory: pytest.TempPathFactory) -> Path:
    _require_build()

    # Build from a copy in this worker's own temp folder, so the source tree never gains
    # build/, dist/ or *.egg-info and parallel builds never share an output folder.
    work = tmp_path_factory.mktemp("wheel-src")
    source = work / "pkg"
    _copy_build_inputs(source)
    outdir = work / "dist"

    command = [sys.executable, "-m", "build", "--wheel", "--outdir", str(outdir), str(source)]
    # Offline and fast when the build backend is already present; otherwise let
    # `build` create its usual isolated environment, with uv installing into it when found.
    if importlib.util.find_spec("setuptools") and importlib.util.find_spec("wheel"):
        command.insert(-1, "--no-isolation")
    elif shutil.which("uv"):
        command[-1:-1] = ["--installer", "uv"]
    proc = subprocess.run(command, capture_output=True, text=True, timeout=280, cwd=work)
    assert proc.returncode == 0, f"wheel build failed:\n{proc.stdout[-2000:]}\n{proc.stderr[-2000:]}"

    wheels = sorted(outdir.glob("*.whl"))
    assert len(wheels) == 1, wheels
    return wheels[0]


def _expected_data_files() -> set[str]:
    expected: set[str] = set()
    for path in (SRC_PACKAGE / "modules").rglob("*"):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        relative = path.relative_to(SRC_PACKAGE.parent).as_posix()
        if (
            path.name == "module.json"
            or (path.suffix == ".yaml" and path.parent.name in {"rules", "recipes"})
            or (path.suffix == ".ipy" and path.parent.name == "scripts")
        ):
            expected.add(relative)
    return expected


def test_wheel_contains_module_manifests_rules_and_recipes(built_wheel: Path) -> None:
    expected = _expected_data_files()
    assert any(p.endswith("/module.json") for p in expected), "no module.json found in the source tree"
    assert any("/rules/" in p for p in expected), "no QA/QC rules found in the source tree"
    assert any("/recipes/" in p for p in expected), "no recipes found in the source tree"
    assert any(p.endswith(".ipy") for p in expected), "no embedded IronPython scripts found in the source tree"

    with zipfile.ZipFile(built_wheel) as wheel:
        shipped = set(wheel.namelist())

    missing = sorted(expected - shipped)
    assert not missing, f"data files missing from {built_wheel.name}: {missing}"


def test_wheel_metadata_keeps_mcp_capped_below_2(built_wheel: Path) -> None:
    with zipfile.ZipFile(built_wheel) as wheel:
        metadata_name = next(n for n in wheel.namelist() if n.endswith(".dist-info/METADATA"))
        metadata = wheel.read(metadata_name).decode("utf-8")
    requires = [
        line.split(":", 1)[1].strip().replace(" ", "")
        for line in metadata.splitlines()
        if line.startswith("Requires-Dist:")
    ]
    assert any(r.startswith("mcp") and "<2" in r for r in requires), requires
    assert any(r.startswith("anthropic") for r in requires), requires


def test_missing_build_fails_in_ci_and_skips_locally(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(importlib.util, "find_spec", lambda name, *a, **k: None if name == "build" else object())
    monkeypatch.setenv("CI", "1")
    with pytest.raises(pytest.fail.Exception, match="uv sync --extra dev"):
        _require_build()
    monkeypatch.delenv("CI")
    with pytest.raises(pytest.skip.Exception, match="uv sync --extra dev"):
        _require_build()


def test_build_copy_takes_only_build_inputs(tmp_path: Path) -> None:
    """Files other workers write into the package root are not copied (#398)."""
    root = tmp_path / "root"
    for name in ("pyproject.toml", "README.md", "LICENSE", "NOTICE", "LICENSING.md"):
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(name)
    (root / "LICENSES").mkdir()
    (root / "LICENSES" / "GPL-3.0-or-later.txt").write_text("gpl")
    (root / "src" / "pkg" / "__pycache__").mkdir(parents=True)
    (root / "src" / "pkg" / "__init__.py").write_text("")
    (root / "src" / "pkg" / "__pycache__" / "__init__.cpython-313.pyc").write_bytes(b"")
    (root / "tests").mkdir()
    (root / "tests" / "test_x.py").write_text("")
    (root / ".hypothesis" / "examples").mkdir(parents=True)
    (root / ".coverage.host.123.456").write_text("coverage data")
    # A coverage file that another worker deleted while this one was copying.
    try:
        (root / ".coverage.host.789.012").symlink_to(root / "gone")
    except OSError:  # pragma: no cover - Windows without symlink rights
        pass

    dest = tmp_path / "copy"
    _copy_build_inputs(dest, root)

    copied = sorted(p.relative_to(dest).as_posix() for p in dest.rglob("*") if p.is_file())
    assert copied == [
        "LICENSE",
        "LICENSES/GPL-3.0-or-later.txt",
        "LICENSING.md",
        "NOTICE",
        "README.md",
        "pyproject.toml",
        "src/pkg/__init__.py",
    ]

