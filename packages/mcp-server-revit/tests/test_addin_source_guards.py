"""Static guards on the C# add-in source.

There is no C# test project yet and CI only compiles the add-in, so a method that calls
itself still builds. These checks read the source text and fail on known-fatal patterns.
"""
import re
from pathlib import Path

ADDIN_SRC = Path(__file__).resolve().parents[3] / "packages" / "revit-bridge-addin" / "src"
FACTORY = ADDIN_SRC / "Bridge" / "BridgeCommandFactory.cs"


def _method_body(source: str, signature_re: str) -> str:
    match = re.search(signature_re, source)
    assert match, f"method not found: {signature_re}"
    start = source.index("{", match.end())
    depth = 0
    for i in range(start, len(source)):
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
            if depth == 0:
                return source[start : i + 1]
    raise AssertionError("unbalanced braces")


def test_create_transaction_builds_a_real_transaction_and_does_not_call_itself():
    body = _method_body(
        FACTORY.read_text(encoding="utf-8"),
        r"public static Transaction CreateTransaction\(Document doc, string name\)",
    )
    assert "BridgeCommandFactory.CreateTransaction(" not in body, "CreateTransaction calls itself"
    assert "CreateTransaction(" not in body, "CreateTransaction calls itself"
    assert "new Transaction(" in body, "CreateTransaction must construct the Revit Transaction"


def test_add_in_constructs_transactions_somewhere():
    hits = [p for p in ADDIN_SRC.rglob("*.cs") if "new Transaction(" in p.read_text(encoding="utf-8")]
    assert hits, "no 'new Transaction(' in the add-in: every model write would fail"


BRAND_DIR = ADDIN_SRC / "UI" / "Resources" / "Brand"
CSPROJ = ADDIN_SRC.parent / "RevitBridge.csproj"


def test_brand_png_resources_are_embedded_and_present():
    csproj = CSPROJ.read_text(encoding="utf-8")
    assert "src\\UI\\Resources\\Brand\\cerberus-*.png" in csproj
    assert "RevitBridge.Brand.%(Filename)%(Extension)" in csproj
    for size in (16, 32, 96, 128):
        png = BRAND_DIR / f"cerberus-{size}.png"
        assert png.is_file(), f"missing brand PNG {png.name}"
        assert png.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n", f"{png.name} is not a PNG"


def test_brand_assets_loader_never_throws_and_matches_embedded_names():
    src = (ADDIN_SRC / "UI" / "BrandAssets.cs").read_text(encoding="utf-8")
    assert '"RevitBridge.Brand.cerberus-"' in src
    body = _method_body(src, r"internal static BitmapSource\? TryLoad\(int size\)")
    assert "catch" in body, "TryLoad must swallow load failures"
    assert "throw" not in body
    assert "Freeze()" in src, "bitmaps must be frozen for cross-thread use"


def test_ribbon_brand_icons_fall_back_to_generated_icons_and_status_glyphs_are_untouched():
    src = (ADDIN_SRC / "UI" / "IconGenerator.cs").read_text(encoding="utf-8")
    assert "BrandAssets.TryLoad(size) ?? CreatePanelGlyphIcon(size)" in src
    assert "BrandAssets.TryLoad(size) ?? CreatePierBrandIcon(size)" in src
    # meaning-bearing status/risk icons must stay generated (green/red/amber badges)
    for name in ("Connect", "Disconnect", "Health", "Pending", "Status"):
        body = _method_body(src, rf"public static BitmapSource Create{name}Icon\(int size = 32\)")
        assert "BrandAssets" not in body, f"Create{name}Icon must not use the brand mark"
