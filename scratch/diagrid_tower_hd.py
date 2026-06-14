"""
High-fidelity diagrid skyscraper generator via Rhino MCP bridge.

Sends a single command to http://127.0.0.1:3004/execute which triggers:
  - Smooth hyperboloid tower surface (waisted profile, 11 loft rings)
  - Properly-oriented 150x300mm rectangular mullion sweeps (depth axis = surface normal)
  - Volumetric glass panel solids inset within the frame grid
  - PBR materials: dark anodised aluminium + highly-reflective tinted green glass

Switch to Rendered Mode in Rhino after running to see the photorealistic result.
"""

import json
import sys

try:
    import requests
except ImportError:
    sys.exit("Install requests first: pip install requests")

BRIDGE  = "http://127.0.0.1:3004"
EXECUTE = f"{BRIDGE}/execute"
HEALTH  = f"{BRIDGE}/health"


def post(payload: dict) -> dict:
    r = requests.post(EXECUTE, json=payload, timeout=300)  # generous timeout for heavy geometry
    r.raise_for_status()
    return r.json()


def main() -> None:
    # ── Health check ────────────────────────────────────────────────────────────
    try:
        health = requests.get(HEALTH, timeout=5).json()
        print(f"Bridge: {health.get('bridge', '?')}  |  status: {health.get('status', '?')}")
    except Exception as e:
        sys.exit(f"Rhino bridge not reachable at {BRIDGE} — is the addin running?\n{e}")

    print()

    # ── Tower parameters ────────────────────────────────────────────────────────
    #   Sizes are in metres; the C# handler converts to the document unit automatically.
    #
    #   Topology tip: u_divs controls the diagrid panel count around the perimeter;
    #   v_divs controls the vertical rhythm. 16×28 gives elegant ~8×6m panels on a
    #   180m tower — increase both for a denser facade on a faster machine.

    command = {
        "command": "generate_diagrid_tower",

        # Form — waisted hyperboloid
        "base_radius":  22.0,   # m — ground-floor footprint radius
        "waist_radius": 14.0,   # m — narrowest point at mid-height
        "top_radius":   19.0,   # m — crown radius (slightly flared)
        "height":      180.0,   # m — total tower height

        # Diagrid density
        "u_divs": 16,           # panels around circumference
        "v_divs": 28,           # panels up the height

        # Mullion cross-section (metres)
        "mullion_width": 0.15,  # 150 mm — visible face width
        "mullion_depth": 0.30,  # 300 mm — structural depth (aligns to surface normal)

        # Glass panel (metres)
        "glass_thickness": 0.024,  # 24 mm — IGU depth (realistic double-glazing unit)
        "inset_ratio":     0.12,   # 12 % — pull each glass corner in toward cell centroid
    }

    # ── Execute ─────────────────────────────────────────────────────────────────
    print("Generating high-fidelity diagrid tower…")
    print(f"  {command['u_divs']} × {command['v_divs']} cell grid  |  "
          f"{command['u_divs'] * command['v_divs'] * 2} mullion members  |  "
          f"{command['u_divs'] * command['v_divs']} glass panels")
    print()

    try:
        result = post(command)
    except requests.exceptions.ReadTimeout:
        sys.exit("Request timed out — the geometry is heavy; try reducing u_divs/v_divs and retry.")
    except Exception as e:
        sys.exit(f"HTTP error: {e}")

    # ── Result ──────────────────────────────────────────────────────────────────
    print(json.dumps(result, indent=2))

    if result.get("success"):
        data = result.get("data", {})
        print()
        print(f"  Mullion sweeps : {data.get('mullionCount', '?')}")
        print(f"  Glass solids   : {data.get('glassCount',   '?')}")
        print()
        print("Done.  Switch Rhino to Rendered Mode (V → Rendered) to see the PBR result.")
        print("Apply a HDRI sky in Rhino's Rendering panel for maximum realism.")
    else:
        err = result.get("error", "unknown error")
        tb  = result.get("stackTrace", "")
        print(f"\nERROR: {err}")
        if tb:
            print(f"\nStack trace:\n{tb}")
        sys.exit(1)


if __name__ == "__main__":
    main()
