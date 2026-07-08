import os
import sys
import requests

BRIDGE = "http://127.0.0.1:3004"
EXECUTE_URL = BRIDGE + "/execute"
SCRIPT_PATH = os.path.join(os.path.dirname(__file__), "detailed_facade.py")
ARTIFACT_DIR = r"C:\Users\sammo\.gemini\antigravity-ide\brain\fa30a343-026e-4366-b14d-56a8c1f3112f"

def capture_viewport(filename):
    path = os.path.join(ARTIFACT_DIR, filename)
    print("Capturing viewport to: {0}...".format(path))
    # Python code to execute inside Rhino
    cap_code = r'''
import Rhino
import System
import os
import scriptcontext as sc

doc = sc.doc
view = doc.Views.ActiveView
if view:
    # Zoom extends to frame the model
    view.ActiveViewport.ZoomExtents()
    # Redraw
    view.Redraw()
    # Capture bitmap
    bmp = view.CaptureToBitmap(System.Drawing.Size(1200, 800))
    if bmp:
        path = r"{path}"
        bmp.Save(path, System.Drawing.Imaging.ImageFormat.Png)
        bmp.Dispose()
        print("Captured successfully!")
    else:
        print("Error: bitmap capture failed")
else:
    print("Error: active view not found")
'''.replace("{path}", path)

    try:
        # Set view mode to rendered first
        requests.post(EXECUTE_URL, json={"command": "set_view", "view": "rendered"}, timeout=15)
        # Run capture
        r = requests.post(EXECUTE_URL, json={"command": "run_python", "code": cap_code}, timeout=15)
        r.raise_for_status()
        print("Capture complete: {0}".format(r.json().get("output", "").strip()))
    except Exception as e:
        print("Error capturing viewport: " + str(e))

def run_facade(params=None):
    with open(SCRIPT_PATH, encoding="utf-8") as f:
        code = f.read()

    # Modify parameters if provided
    if params:
        lines = code.splitlines()
        for i, line in enumerate(lines):
            # Check for matches and replace
            for param, val in params.items():
                if line.startswith(param + " "):
                    # Find equals and replace rest
                    parts = line.split("=")
                    lines[i] = parts[0] + "= " + str(val) + "    # dynamically updated"
        code = "\n".join(lines)

    # Clean active scene
    try:
        requests.post(EXECUTE_URL, json={"command": "clear_scene"}, timeout=15)
    except Exception as e:
        print("Warning: failed to clear scene: " + str(e))

    # Send script
    try:
        r = requests.post(
            EXECUTE_URL,
            json={"command": "run_python", "code": code},
            timeout=180
        )
        r.raise_for_status()
        print("Bake successful!")
    except Exception as e:
        print("Bake failed: " + str(e))

def main():
    if not os.path.exists(SCRIPT_PATH):
        sys.exit("Cannot find detailed_facade.py: " + SCRIPT_PATH)

    print("Checking bridge health...")
    try:
        h = requests.get(BRIDGE + "/health", timeout=5).json()
        print("Bridge is active! Status: {0}".format(h.get("status")))
    except Exception as e:
        sys.exit("Bridge is not reachable: " + str(e))

    # 1. RUN DEFAULT VARIATION
    print("\n--- Running Default Façade (3 Bays, 2 Floors) ---")
    run_facade()
    capture_viewport("facade_default.png")

    # 2. RUN HIGH DENSITY VARIATION (5 Bays, 3 Floors, deep profiles)
    print("\n--- Running Variation 1: High Density (5 Bays, 3 Floors) ---")
    var1_params = {
        "NUM_BAYS": 5,
        "NUM_FLOORS": 3,
        "BAY_WIDTH": 1.20,
        "FLOOR_HEIGHT": 3.60,
        "MULLION_D": 0.180,
        "TRANSOM_D": 0.140,
        "GLASS_REVEAL": 0.008,  # Wider glass panels
    }
    run_facade(var1_params)
    capture_viewport("facade_high_density.png")

    # 3. RUN LOW DENSITY VARIATION (2 Bays, 1 Floor, wide spans, shallow profiles)
    print("\n--- Running Variation 2: Low Density (2 Bays, 1 Floor, wide span) ---")
    var2_params = {
        "NUM_BAYS": 2,
        "NUM_FLOORS": 1,
        "BAY_WIDTH": 2.20,
        "FLOOR_HEIGHT": 4.00,
        "MULLION_D": 0.120,
        "TRANSOM_D": 0.100,
        "GLASS_REVEAL": 0.015,  # Narrower glass panels
    }
    run_facade(var2_params)
    capture_viewport("facade_low_density.png")

    # 4. RESTORE DEFAULT CONFIGURATION
    print("\n--- Restoring Default Façade ---")
    run_facade()
    print("Done generating variations!")

if __name__ == "__main__":
    main()
