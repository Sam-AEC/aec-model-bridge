# AEC Model Bridge — Project Reference

## Architecture

Four independent "switches" (per-platform add-ins) + one Python MCP hub:

| package | language | port | status |
|---------|----------|------|--------|
| `packages/rhino-bridge-addin/` | C# .NET 4.8 | 3004 | built ✓ |
| `packages/navisworks-bridge-addin/` | C# .NET 4.8 | 3002 | routing infra ✓ |
| `packages/powerbi-bridge-tool/` | Python | — | stub |
| `packages/mcp-server-revit/` | Python | — | MCP hub |

MCP providers: `packages/mcp-server-revit/src/revit_mcp_server/providers/`  
Architecture blueprint: `docs/system-blueprint-and-workflows.md`

## Rhino Bridge — Quick Reference

**URL:** `http://127.0.0.1:3004`

**Build (Rhino must be CLOSED):**
```powershell
cd packages/rhino-bridge-addin
dotnet build -c Release
```

**All bridge commands** (POST `/execute`):

| command | key params |
|---------|-----------|
| `get_document_info` | — |
| `get_lines` | — |
| `get_scene` | — → all objects with type/layer/bbox |
| `list_layers` | — |
| `clear_scene` | `layer?` (omit = delete all) |
| `set_view` | `view`: perspective\|top\|front\|right\|rendered\|arctic |
| `create_box` | `min_pt [x,y,z]`, `max_pt [x,y,z]` |
| `create_sphere` | `center [x,y,z]`, `radius` |
| `create_cylinder` | `base [x,y,z]`, `height`, `radius` |
| `boolean_union` | `ids: [guid,...]` |
| `boolean_difference` | `base_id`, `cutter_ids: [guid,...]` |
| `set_material` | `ids`\|`layer`, `color [r,g,b]`, `transparency`, `reflectivity` |
| `transform_objects` | `ids`, `translation`\|`rotation`\|`scale` |
| `run_python` | `code` — IronPython, stdout captured |
| `generate_diagrid_tower` | all dims in metres; auto unit-converted |
| `reflect_get` / `reflect_set` / `invoke_method` | reflection access |

All geometry params in **metres** (C# converts via `RhinoMath.UnitScale`).

## Python Iteration (no recompile)

```python
import requests
code = open("scratch/rhino_diagrid_tower.py").read()
r = requests.post("http://127.0.0.1:3004/execute",
    json={"command": "run_python", "code": code}, timeout=300)
print(r.json().get("output", ""))
```

Edit `scratch/rhino_diagrid_tower.py` → re-run. Rhino updates live.

## RhinoCommon v7 Gotchas

- `mat.ToPhysicallyBased()` → `void` (not `bool`) — never wrap in `if`
- `PythonScript.ExecuteScript(code)` → 1 arg only (not 2)
- `TransparencyColor` property does NOT exist — use `mat.Transparency` (double)
- NuGet: `RhinoCommon 7.16.22067.13001`, target `net48`
- Use reflection for properties that differ between v7/v8

## MCP Provider Pattern

`providers/rhino.py` maps tool name → bridge command:
```python
self._tool_mapping["rhino_foo"] = ("foo_command", lambda args: {"param": args.get("param")})
# Plus matching ProviderTool entry in _capabilities
```

## Commit Rules

- No `Co-Authored-By` trailers — ever
- `docs/ecosystem-strategy-and-monetization.md` is potentially private — check before pushing

## Diagrid Glass Panel Geometry

**Canonical script:** `scratch/glass_diamond.py`

### Critical: loft surface UV axis orientation

`Brep.CreateFromLoft` of horizontal circles produces a surface where:
- **U (first param) = HEIGHT direction** — 0.0 = tower base, 1.0 = roof
- **V (second param) = CIRCUMFERENCE direction** — 0.0/1.0 = seam at angle 0°

In the code, `i` = height index (maps to U), `j` = circumference index (maps to V). The circumferential seam wraps at `j % V_DIVS`. Never wrap `i` — wrapping height jumps from near-top to floor and creates 200m-tall spanning panels.

### gpt / cc conventions

```python
def gpt(i, j):  # grid corner — i=height (no wrap), j=circ (wraps)
    return face.PointAt(float(i) / U_DIVS, float(j % V_DIVS) / V_DIVS)

def cc(i, j):   # cell centre on surface
    return face.PointAt((i + 0.5) / U_DIVS, ((j % V_DIVS) + 0.5) / V_DIVS)
```

### Panel types

All edges lie along half-segments of actual diagonal mullion members:

| type | vertices | covers | loop range |
|------|----------|--------|------------|
| **A** | `cc(i,j)` → `gpt(i+1,j+1)` → `cc(i,j+1)` → `gpt(i,j+1)` | top△(i,j) + bottom△(i,j+1) | i=0..U_DIVS-1, j=0..V_DIVS-1 |
| **B** | `cc(i,j)` → `gpt(i+1,j)` → `cc(i+1,j)` → `gpt(i+1,j+1)` | right△(i,j) + left△(i+1,j) | i=0..U_DIVS-2, j=0..V_DIVS-1 |
| **Bot cap** | `gpt(0,j)` → `gpt(0,j+1)` → `cc(0,j)` | left△ of bottom row | j=0..V_DIVS-1 |
| **Top cap** | `cc(U-1,j)` → `gpt(U,j+1)` → `gpt(U,j)` | right△ of top row | j=0..V_DIVS-1 |

Count at U_DIVS=20, V_DIVS=36: 720 + 684 + 36 + 36 = **1476 panels**, 0 skipped.

## Skill Reference

Use `/rhino-god-mode` for the complete command reference, Python patterns, materials,
Gram-Schmidt mullion orientation, and buildable glass panel code.

## /compact Policy

When compressing context, preserve:
- Which files were modified this session
- Current bridge command set and any new commands added
- Active error messages / fixes in flight
- Build status (compiled / Rhino open or closed)
- Any GUID values still in use
