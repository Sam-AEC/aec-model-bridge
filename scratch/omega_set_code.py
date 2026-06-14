import clr, System, System.Reflection as rf
clr.AddReference("Grasshopper")
import Grasshopper as gh

canvas = gh.Instances.ActiveCanvas
gd = canvas.Document
GHPY_GUID = System.Guid("410755b1-224a-4c1e-a407-bf32fb45ea7e")
py_comp = None
for obj in gd.Objects:
    try:
        if hasattr(obj, "ComponentGuid") and obj.ComponentGuid == GHPY_GUID:
            py_comp = obj; break
    except: pass

if py_comp is None:
    print("GhPython component not found in canvas")
    raise SystemExit

# Read the GH-aware tower code from file (IronPython can open() files normally)
code_path = r"C:\Users\sammo\OneDrive\Documenten\GitHub\Autodesk-Revit-MCP-Server\scratch\omega_tower_gh.py"
with open(code_path, "r") as f:
    code = f.read()

print("Read code: %d chars, %d lines" % (len(code), len(code.splitlines())))

# Set via Code property
t = py_comp.GetType()
prop = t.GetProperty("Code", rf.BindingFlags.Public | rf.BindingFlags.Instance)
if prop and prop.CanWrite:
    prop.SetValue(py_comp, code, None)
    print("Code embedded successfully")
    try:
        py_comp.ExpireSolution(False)
    except: pass
else:
    print("Code property not settable")

canvas.Refresh()
print("Done")
