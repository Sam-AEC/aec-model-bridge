"""Atheris harness: the panel body parser returns a dict or raises ValueError, nothing else.

Run: python fuzz/fuzz_panel_body.py -max_total_time=60   (needs `atheris`, Linux or macOS)
"""
from __future__ import annotations

import sys

import atheris

with atheris.instrument_imports():
    from revit_mcp_server.panel_server import parse_json_object


def test_one_input(data: bytes) -> None:
    try:
        body = parse_json_object(data)
    except ValueError:
        return
    assert isinstance(body, dict)


if __name__ == "__main__":
    atheris.Setup(sys.argv, test_one_input)
    atheris.Fuzz()
