import requests

BRIDGE = "http://127.0.0.1:3004"
EXECUTE_URL = BRIDGE + "/execute"

code = """
import scriptcontext as sc, Rhino
doc = sc.doc
S = Rhino.RhinoMath.UnitScale(Rhino.UnitSystem.Meters, doc.ModelUnitSystem)
print("S = {0}".format(S))
print("UnitSystem = {0}".format(doc.ModelUnitSystem))
"""

try:
    r = requests.post(EXECUTE_URL, json={"command": "run_python", "code": code}, timeout=10)
    print(r.json())
except Exception as e:
    print("Error:", e)
