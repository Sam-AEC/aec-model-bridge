"""scripts/changelog.py: per-change fragments in changes/ are folded into CHANGELOG.md at release."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]


@pytest.fixture
def cl():
    spec = importlib.util.spec_from_file_location("changelog_script", REPO / "scripts" / "changelog.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_repo(tmp_path: Path, unreleased: str = "", fragments: dict[str, str] | None = None) -> Path:
    (tmp_path / "changes").mkdir()
    (tmp_path / "CHANGELOG.md").write_text(
        f"# Changelog\n\n## Unreleased\n\n{unreleased}## 1.0.0 - 2026-01-01\n\n- Old entry.\n", encoding="utf-8"
    )
    for name, body in (fragments or {}).items():
        (tmp_path / "changes" / name).write_text(body, encoding="utf-8")
    return tmp_path


def test_build_moves_fragments_and_unreleased_into_a_new_section(cl, tmp_path):
    root = make_repo(tmp_path, "- Existing line.\n\n", {"b-two.md": "- Two.\n", "a-one.md": "- One.\n- One more.\n"})
    cl.build(root, "1.1.0", "2026-02-03")
    text = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    assert text.startswith(
        "# Changelog\n\n## Unreleased\n\n## 1.1.0 - 2026-02-03\n\n- Existing line.\n- One.\n- One more.\n- Two.\n\n## 1.0.0"
    )
    assert "- Old entry." in text
    assert cl.fragment_files(root) == []


def test_build_ignores_readme_in_changes(cl, tmp_path):
    root = make_repo(tmp_path, "", {"x.md": "- X.\n", "README.md": "How fragments work.\n"})
    cl.build(root, "1.1.0", "2026-02-03")
    assert (root / "changes" / "README.md").exists()
    assert "How fragments work" not in (root / "CHANGELOG.md").read_text(encoding="utf-8")


def test_build_refuses_when_nothing_to_release(cl, tmp_path):
    root = make_repo(tmp_path)
    with pytest.raises(cl.ChangelogError, match="nothing to release"):
        cl.build(root, "1.1.0", "2026-02-03")


def test_build_refuses_existing_version(cl, tmp_path):
    root = make_repo(tmp_path, "", {"x.md": "- X.\n"})
    with pytest.raises(cl.ChangelogError, match="1.0.0"):
        cl.build(root, "1.0.0", "2026-02-03")
    assert (root / "changes" / "x.md").exists()


def test_build_refuses_bad_version(cl, tmp_path):
    root = make_repo(tmp_path, "", {"x.md": "- X.\n"})
    with pytest.raises(cl.ChangelogError, match="version"):
        cl.build(root, "v1", "2026-02-03")


def test_build_refuses_malformed_fragment_and_changes_nothing(cl, tmp_path):
    root = make_repo(tmp_path, "", {"x.md": "## Heading\n- X.\n"})
    before = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    with pytest.raises(cl.ChangelogError):
        cl.build(root, "1.1.0", "2026-02-03")
    assert (root / "CHANGELOG.md").read_text(encoding="utf-8") == before
    assert (root / "changes" / "x.md").exists()


def test_build_keeps_indented_continuation_lines(cl, tmp_path):
    root = make_repo(tmp_path, "", {"x.md": "- First line\n  continued.\n"})
    cl.build(root, "1.1.0", "2026-02-03")
    assert "- First line\n  continued.\n" in (root / "CHANGELOG.md").read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "body, expected",
    [
        ("- ok\n", []),
        ("- ok\n- also ok\n", []),
        ("", ["empty"]),
        ("\n\n", ["empty"]),
        ("plain text\n", ["start with"]),
        ("## Heading\n", ["start with"]),
        ("- ok\nstray\n", ["start with"]),
        ("-no space\n", ["start with"]),
    ],
)
def test_fragment_problems(cl, body, expected):
    problems = cl.fragment_problems("x.md", body)
    assert len(problems) == len(expected)
    for needle, problem in zip(expected, problems):
        assert needle in problem and "x.md" in problem


def test_check_rejects_bad_file_name(cl, tmp_path):
    root = make_repo(tmp_path, "", {"Bad Name.txt": "- X.\n"})
    assert any("Bad Name.txt" in p for p in cl.check(root))


def test_check_passes_for_good_fragments_and_empty_dir(cl, tmp_path):
    root = make_repo(tmp_path, "", {"issue-12.md": "- X.\n"})
    assert cl.check(root) == []
    (root / "changes" / "issue-12.md").unlink()
    assert cl.check(root) == []


def test_main_check_exit_codes_and_message(cl, tmp_path, capsys, monkeypatch):
    root = make_repo(tmp_path, "", {"x.md": "nope\n"})
    monkeypatch.setattr(cl, "ROOT", root)
    assert cl.main(["check"]) == 1
    assert "changes/<name>.md" in capsys.readouterr().err
    (root / "changes" / "x.md").write_text("- ok\n", encoding="utf-8")
    assert cl.main(["check"]) == 0


def test_main_build(cl, tmp_path, monkeypatch):
    root = make_repo(tmp_path, "", {"x.md": "- X.\n"})
    monkeypatch.setattr(cl, "ROOT", root)
    assert cl.main(["build", "--version", "2.0.0"]) == 0
    assert "## 2.0.0 - " in (root / "CHANGELOG.md").read_text(encoding="utf-8")


def test_repo_fragments_are_well_formed(cl):
    assert cl.check(REPO) == []
