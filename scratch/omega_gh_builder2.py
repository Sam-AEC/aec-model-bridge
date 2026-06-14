import clr, System, System.Drawing as sd
import System.Reflection as rf
clr.AddReference("Grasshopper")
import Grasshopper as gh
from Grasshopper.Kernel import GH_Document
from Grasshopper.Kernel.Special import GH_NumberSlider, GH_Group, GH_Panel

# ── Document ──────────────────────────────────────────────────────────────────
canvas = gh.Instances.ActiveCanvas
gd = canvas.Document
if gd is None:
    gd = GH_Document()
    canvas.Document = gd
gd.Objects.Clear()
gd.Enabled = False
print("Canvas ready — cleared")

# ── Helpers ───────────────────────────────────────────────────────────────────
def sl(name, mn, mx, val, x, y, dec=2):
    s = GH_NumberSlider()
    s.CreateAttributes()
    s.Name = name; s.NickName = name
    s.Slider.Minimum = System.Decimal(mn)
    s.Slider.Maximum = System.Decimal(mx)
    s.Slider.Value   = System.Decimal(val)
    s.Slider.DecimalPlaces = dec
    s.Attributes.Pivot = sd.PointF(float(x), float(y))
    gd.AddObject(s, False)
    return s

def grp(title, rgba, objs):
    g = GH_Group(); g.NickName = title
    g.Colour = sd.Color.FromArgb(*rgba)
    for o in objs: g.AddObject(o.InstanceGuid)
    gd.AddObject(g, False)
    return g

def pan(text, x, y):
    p = GH_Panel(); p.CreateAttributes()
    p.UserText = text
    p.Attributes.Pivot = sd.PointF(float(x), float(y))
    gd.AddObject(p, False)
    return p

# ── Slider layout (6 groups, 28 sliders) ─────────────────────────────────────
A = 80; B = 290; H = 32; GP = 24
sliders = {}; y = 60

specs = [
    # (group_title, rgba, [ (name, min, max, val, col, rel_row, dec), ... ])
    ("A  TOWER FORM", (45, 80, 135, 55), [
        ("base_r",       5.,  60.,  26.,  A, 0, 1),
        ("waist_r",      3.,  50.,  14.5, B, 0, 1),
        ("top_r",        5.,  55.,  21.,  A, 1, 1),
        ("height",      50., 600., 272.,  B, 1, 1),
        ("squircle_n",   2.,   8.,   3.5, A, 2, 2),
        ("twist_deg",    0., 180.,  72.,  B, 2, 1),
    ]),
    ("B  DIAGRID SYSTEM", (135, 80, 45, 55), [
        ("u_divs",      20,  80,  52,   A, 0, 0),
        ("v_divs",      12,  48,  24,   B, 0, 0),
        ("mul_w_base",  0.1, 0.8, 0.30, A, 1, 3),
        ("mul_w_top",   0.05,0.4, 0.12, B, 1, 3),
        ("mul_d_base",  0.15,1.2, 0.52, A, 2, 3),
        ("mul_d_top",   0.08,0.6, 0.20, B, 2, 3),
    ]),
    ("C/D  FACADE ZONES", (45, 135, 80, 55), [
        ("zone_solid",  0.,  0.5, 0.22, A, 0, 3),
        ("zone_glass",  0.5, 1.0, 0.80, B, 0, 3),
        ("glass_t",     0.01,0.06,0.028,A, 1, 3),
        ("glass_inset", 0.02,0.2, 0.09, B, 1, 3),
    ]),
    ("F  SOLAR FINS", (135, 120, 40, 55), [
        ("sun_azimuth",  0., 360., 195., A, 0, 1),
        ("sun_altitude", 5.,  85.,  40., B, 0, 1),
        ("fin_len",      0.2, 3.0,  1.1, A, 1, 2),
        ("fin_thick",    0.02,0.2,  0.055,B,1, 3),
        ("fin_step",     1,   6,    2,   A, 2, 0),
    ]),
    ("G  FLOOR PLATES", (80, 80, 80, 55), [
        ("floor_h",  2.5, 6.5, 4.3,  A, 0, 2),
        ("slab_t",   0.15,0.6, 0.30, B, 0, 3),
        ("slab_in",  0.05,0.4, 0.14, A, 1, 3),
    ]),
]

for grp_title, grp_rgba, items in specs:
    g_objs = []
    rows = max(r for _, _, _, _, _, r, _ in items)
    for name, mn, mx, val, col, row, dec in items:
        s = sl(name, mn, mx, val, col, y + row * H, dec)
        g_objs.append(s); sliders[name] = s
    grp(grp_title, grp_rgba, g_objs)
    y += (rows + 1) * H + GP

print("Sliders: %d" % len(sliders))

# ── Python Script component ───────────────────────────────────────────────────
PX = 580; PY_COMP_Y = 60
GHPY_GUID = System.Guid("410755b1-224a-4c1e-a407-bf32fb45ea7e")

server = gh.Instances.ComponentServer
py_proxy = None
for proxy in server.ObjectProxies:
    try:
        if proxy.Guid == GHPY_GUID:
            py_proxy = proxy
            break
    except: pass
if py_proxy is None:
    for proxy in server.ObjectProxies:
        try:
            nm = proxy.Desc.Name.lower()
            if "ghpython" in nm or "ironpython 2" in nm:
                py_proxy = proxy
                break
        except: pass

if py_proxy:
    py_comp = py_proxy.CreateInstance()
    py_comp.CreateAttributes()
    py_comp.Attributes.Pivot = sd.PointF(float(PX), float(PY_COMP_Y))
    gd.AddObject(py_comp, False)
    print("Python component: %s" % py_proxy.Desc.Name)

    # Wire available inputs (typically 2 default: x, y)
    SLIDER_ORDER = [
        "base_r","waist_r","top_r","height","squircle_n","twist_deg",
        "u_divs","v_divs","mul_w_base","mul_w_top","mul_d_base","mul_d_top",
        "zone_solid","zone_glass","glass_t","glass_inset",
        "sun_azimuth","sun_altitude","fin_len","fin_thick","fin_step",
        "floor_h","slab_t","slab_in",
    ]

    # ── Add inputs until we have enough ──────────────────────────────────────
    from Grasshopper.Kernel import GH_ParameterSide
    target = len(SLIDER_ORDER)
    added = 0
    while py_comp.Params.Input.Count < target:
        try:
            idx_new = py_comp.Params.Input.Count
            param = py_comp.CreateParameter(GH_ParameterSide.Input, idx_new)
            py_comp.Params.RegisterInputParam(param)
            added += 1
        except Exception as e:
            print("  add input failed at %d: %s" % (py_comp.Params.Input.Count, e))
            break
    try:
        py_comp.VariableParameterMaintenance()
        py_comp.Params.OnParametersChanged()
    except: pass
    print("Inputs after expansion: %d (added %d)" % (py_comp.Params.Input.Count, added))

    # ── Wire sliders → inputs ─────────────────────────────────────────────────
    # GH_NumberSlider IS an IGH_Param itself — AddSource takes it directly
    wired = 0
    for idx, sname in enumerate(SLIDER_ORDER):
        if sname not in sliders: continue
        if idx >= py_comp.Params.Input.Count: break
        try:
            ip = py_comp.Params.Input[idx]
            ip.NickName = sname; ip.Name = sname
            ip.AddSource(sliders[sname])
            wired += 1
        except Exception as e:
            print("  wire[%d] %s: %s" % (idx, sname, e))

    print("Wired: %d / %d" % (wired, target))
else:
    print("WARNING: GhPython component not found — add manually from GH toolbar")

# ── Info panel ────────────────────────────────────────────────────────────────
pan(
    "OMEGA TOWER  |  AEC Omni-Bridge MCP\n"
    "Squircle-twisted performative skyscraper\n\n"
    "Geometry baked in Rhino (run omega_tower.py):\n"
    "  2496  diagrid members   tapered section base→crown\n"
    "   260  corten cladding   solid base 0-22%\n"
    "  1508  diamond glass     IGU mid zone 22-80%\n"
    "   360  solar fins        sun az=195 alt=40\n"
    "    61  floor slabs       squircle profile\n"
    "     1  crown spire\n\n"
    "TO USE GH SLIDERS:\n"
    "1. Open Python component (double-click)\n"
    "2. Paste code from omega_tower.py\n"
    "3. Click the + (ZUI) to add 24 inputs\n"
    "4. Name them matching the slider NickNames\n"
    "5. Drag wires slider > input\n"
    "6. Press TAB to update geometry",
    PX + 260, PY_COMP_Y
),

# ── Re-enable ─────────────────────────────────────────────────────────────────
gd.Enabled = True
canvas.Refresh()
print("GH definition complete  (objects: %d)" % gd.ObjectCount)
