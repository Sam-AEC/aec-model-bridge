import os
import sys
import requests

BRIDGE = "http://127.0.0.1:3004"
EXECUTE_URL = BRIDGE + "/execute"
SCRIPT_PATH = os.path.join(os.path.dirname(__file__), "detailed_facade.py")

def main():
    if not os.path.exists(SCRIPT_PATH):
        sys.exit("Cannot find detailed_facade.py: " + SCRIPT_PATH)
    
    with open(SCRIPT_PATH, encoding="utf-8") as f:
        code = f.read()

    print("Checking bridge health...")
    try:
        h = requests.get(BRIDGE + "/health", timeout=5).json()
        print("Bridge is active! Status: {0}".format(h.get("status")))
    except Exception as e:
        sys.exit("Bridge is not reachable: " + str(e))

    print("Clearing Rhino scene...")
    try:
        r = requests.post(EXECUTE_URL, json={"command": "clear_scene"}, timeout=10)
        r.raise_for_status()
        print("Scene cleared!")
    except Exception as e:
         print("Warning: failed to clear scene: " + str(e))

    print("Sending detailed_facade.py script to Rhino ({0} lines)...".format(len(code.splitlines())))
    try:
        r = requests.post(
            EXECUTE_URL,
            json={"command": "run_python", "code": code},
            timeout=300
        )
        r.raise_for_status()
        result = r.json()
    except requests.exceptions.ReadTimeout:
        sys.exit("Timed out running detailed_facade.py script inside Rhino.")
    except Exception as e:
        sys.exit("HTTP error: " + str(e))

    if result.get("success"):
        print("Success! Output from Rhino:")
        output = (result.get("output") or "").strip()
        for line in output.splitlines():
            print("  " + line)
    else:
        print("Error from Rhino:")
        print(result.get("error", "Unknown error"))
        print(result.get("stackTrace", ""))

if __name__ == "__main__":
    main()
