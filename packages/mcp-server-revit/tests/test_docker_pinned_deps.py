"""Docker image installs dependencies from a hash-pinned export of uv.lock (Scorecard Pinned-Dependencies)."""
import shutil
import subprocess
from pathlib import Path

import pytest

PKG = Path(__file__).resolve().parent.parent
ROOT = PKG.parent.parent
REQ = PKG / "requirements-docker.txt"


def test_dockerfile_installs_only_hash_pinned_dependencies():
    text = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    installs = [ln.strip().lstrip("&").strip() for ln in text.splitlines() if "pip install" in ln]
    assert installs == ["RUN pip install --require-hashes -r requirements-docker.txt \\",
                        "pip install --no-deps -e . \\"]


def test_requirements_docker_is_hash_pinned():
    lines = [ln for ln in REQ.read_text(encoding="utf-8").splitlines() if ln and not ln.lstrip().startswith(("#", "--hash"))]
    assert lines and all("==" in ln for ln in lines)
    assert REQ.read_text(encoding="utf-8").count("--hash=sha256:") >= len(lines)


def _body(p):
    return [ln for ln in p.read_text(encoding="utf-8").splitlines() if not ln.startswith("#")]


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv not installed")
def test_requirements_docker_matches_uv_lock(tmp_path):
    out = tmp_path / "req.txt"
    subprocess.run(["uv", "export", "--frozen", "--no-dev", "--no-emit-project", "--format", "requirements-txt",
                    "-q", "-o", str(out)], cwd=PKG, check=True)
    assert _body(out) == _body(REQ), "Run: uv export --frozen --no-dev --no-emit-project --format requirements-txt -o requirements-docker.txt"
