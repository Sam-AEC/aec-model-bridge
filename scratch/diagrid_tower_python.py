"""
diagrid_tower_python.py
-----------------------
MCP client: reads rhino_diagrid_tower.py and sends it to the Rhino bridge.

USAGE
  python scratch/diagrid_tower_python.py

The geometry script (rhino_diagrid_tower.py) runs INSIDE Rhino's IronPython
engine — no C# recompile ever needed for geometry changes.

ITERATION WORKFLOW
  - Edit the PARAMETERS block in rhino_diagrid_tower.py
  - Run this file again  →  new tower appears in Rhino within seconds
  - Or open rhino_diagrid_tower.py directly in Rhino's PythonEdit editor
    and press F5 to run without the bridge at all.

BRIDGE SETUP (one-time after C# compile)
  1. Close Rhino
  2. dotnet build -c Release   (in packages/rhino-bridge-addin)
  3. Open Rhino — plugin loads, prints "AEC Model Bridge for Rhino started on port 3004"
  4. Run this script
"""

import os
import sys

try:
    import requests
except ImportError:
    sys.exit("pip install requests")

BRIDGE      = "http://127.0.0.1:3004"
EXECUTE_URL = BRIDGE + "/execute"

# The geometry script lives next to this file
TOWER_SCRIPT = os.path.join(os.path.dirname(__file__), "rhino_diagrid_tower.py")


def load_tower_script() -> str:
    if not os.path.exists(TOWER_SCRIPT):
        sys.exit("Cannot find rhino_diagrid_tower.py next to this file: " + TOWER_SCRIPT)
    with open(TOWER_SCRIPT, encoding="utf-8") as f:
        return f.read()


def check_bridge() -> None:
    try:
        h = requests.get(BRIDGE + "/health", timeout=5).json()
        status = h.get("status", "?")
        bridge = h.get("bridge", "?")
        print("Bridge: {0}  |  status: {1}".format(bridge, status))
    except Exception as e:
        print("")
        print("ERROR: Rhino bridge not reachable at " + BRIDGE)
        print("  Make sure Rhino is open and the RhinoBridge plugin is loaded.")
        print("  Rhino command line should show: 'AEC Model Bridge for Rhino started on port 3004'")
        print("  If not, run: PlugInManager -> drag-drop RhinoBridge.rhp -> restart Rhino")
        print("")
        sys.exit(str(e))


def run_tower() -> None:
    code = load_tower_script()

    print("Sending tower script to Rhino ({0} lines)...".format(len(code.splitlines())))
    print("")

    try:
        r = requests.post(
            EXECUTE_URL,
            json={"command": "run_python", "code": code},
            timeout=300
        )
        r.raise_for_status()
        result = r.json()
    except requests.exceptions.ReadTimeout:
        sys.exit("Timed out — reduce U_DIVS/V_DIVS in rhino_diagrid_tower.py and retry.")
    except Exception as e:
        sys.exit("HTTP error: " + str(e))

    if result.get("success"):
        output = (result.get("output") or "").strip()
        if output:
            print("Rhino output:")
            for line in output.splitlines():
                print("  " + line)
    else:
        err = result.get("error", "unknown error")
        tb  = result.get("stackTrace", "")
        print("ERROR: " + err)
        if tb:
            print(tb)
        sys.exit(1)


if __name__ == "__main__":
    check_bridge()
    run_tower()
