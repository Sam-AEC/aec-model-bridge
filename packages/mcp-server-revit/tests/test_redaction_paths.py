"""Path redaction must cover every path style that shows up in AEC projects."""
import pytest

from revit_mcp_server.security.audit import redact_data


@pytest.mark.parametrize(
    "text, leaked",
    [
        (r"opening C:\Projects\Tower\central.rvt now", "central.rvt"),
        (r"opening \\fileserver\BIM\Tower\central.rvt now", "fileserver"),
        (r"\\10.0.0.5\share\model.ifc", "model.ifc"),
        (r"mapped to \tmp\pytest-0\test.rvt", "test.rvt"),
        ("saved to /home/user/projects/model.rvt", "model.rvt"),
    ],
)
def test_paths_are_redacted(text, leaked):
    redacted = redact_data({"message": text})["message"]
    assert leaked not in redacted
    assert "<redacted-path>" in redacted


@pytest.mark.parametrize("text", ["a\\b", "regex \\d+ and \\w", "plain sentence with no paths", "ratio 3/4"])
def test_ordinary_text_is_left_alone(text):
    assert redact_data({"message": text})["message"] == text
