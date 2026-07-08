# =============================================================================
# DETAILED FAÇADE SYSTEM — Grasshopper Canvas Builder
# AEC Omni-Bridge MCP  |  Runs inside Rhino (Grasshopper must be open)
# =============================================================================

import clr, System, System.Drawing as sd
import System.Reflection as rf
clr.AddReference("Grasshopper")
import Grasshopper as gh
from Grasshopper.Kernel import GH_Document
from Grasshopper.Kernel.Special import GH_NumberSlider, GH_Group, GH_Panel, GH_Scribble

# ── Document ──────────────────────────────────────────────────────────────────
canvas = gh.Instances.ActiveCanvas
if canvas is None:
    print("ERROR: Grasshopper is not open. Run _Grasshopper in Rhino first.")
    raise SystemExit("GH canvas not found")

gd = canvas.Document
if gd is None:
    gd = GH_Document()
    canvas.Document = gd
gd.Objects.Clear()
gd.Enabled = False
print("Canvas ready — cleared previous objects")

# ── Helpers ───────────────────────────────────────────────────────────────────
def sl(name, mn, mx, val, x, y, dec=2):
    s = GH_NumberSlider()
    s.CreateAttributes()
    s.Name = name
    s.NickName = name
    s.Slider.Minimum = System.Decimal(mn)
    s.Slider.Maximum = System.Decimal(mx)
    s.Slider.Value   = System.Decimal(val)
    s.Slider.DecimalPlaces = dec
    s.Attributes.Pivot = sd.PointF(float(x), float(y))
    gd.AddObject(s, False)
    return s

def grp(title, rgba, objs):
    g = GH_Group()
    g.NickName = title
    g.Colour = sd.Color.FromArgb(*rgba)
    for o in objs: 
        g.AddObject(o.InstanceGuid)
    gd.AddObject(g, False)
    return g

def pan(text, x, y):
    p = GH_Panel()
    p.CreateAttributes()
    p.UserText = text
    p.Attributes.Pivot = sd.PointF(float(x), float(y))
    gd.AddObject(p, False)
    return p

def scribble(text, x, y, size=18):
    s = GH_Scribble()
    s.CreateAttributes()
    s.Text = text
    try:
        s.Font = sd.Font("Outfit", float(size), sd.FontStyle.Bold)
    except:
        s.Font = sd.Font("Arial", float(size), sd.FontStyle.Bold)
    s.Attributes.Pivot = sd.PointF(float(x), float(y))
    gd.AddObject(s, False)
    return s

def build_performance_calculator():
    mult_proxy = None
    for proxy in server.ObjectProxies:
        try:
            # Target exact GUIDs of the Math Multiplication component to avoid matching Color Multiplication
            if proxy.Guid == System.Guid("b8963bb1-aa57-476e-a20e-ed6cf635a49c") or proxy.Guid == System.Guid("ce46b74e-00c9-43c4-805a-193b69ea4a11"):
                mult_proxy = proxy
                break
        except: pass

        
    if not mult_proxy:
        print("Warning: Multiplication component proxy not found")
        return
        
    scribble("II. FAÇADE PERFORMANCE CALCULATOR", PX, 680, 12)
    
    mw = mult_proxy.CreateInstance()
    mw.CreateAttributes()
    mw.Attributes.Pivot = sd.PointF(float(PX), float(730))
    gd.AddObject(mw, False)
    mw.Params.Input[0].AddSource(sliders["num_bays"])
    mw.Params.Input[1].AddSource(sliders["bay_width"])
    
    mh = mult_proxy.CreateInstance()
    mh.CreateAttributes()
    mh.Attributes.Pivot = sd.PointF(float(PX), float(810))
    gd.AddObject(mh, False)
    mh.Params.Input[0].AddSource(sliders["num_floors"])
    mh.Params.Input[1].AddSource(sliders["floor_height"])
    
    ma = mult_proxy.CreateInstance()
    ma.CreateAttributes()
    ma.Attributes.Pivot = sd.PointF(float(PX + 120), float(770))
    gd.AddObject(ma, False)
    ma.Params.Input[0].AddSource(mw.Params.Output[0])
    ma.Params.Input[1].AddSource(mh.Params.Output[0])
    
    mc = mult_proxy.CreateInstance()
    mc.CreateAttributes()
    mc.Attributes.Pivot = sd.PointF(float(PX + 240), float(770))
    gd.AddObject(mc, False)
    mc.Params.Input[0].AddSource(ma.Params.Output[0])
    try:
        mc.Params.Input[1].PersistentData.Clear()
        mc.Params.Input[1].PersistentData.Append(gh.Kernel.Types.GH_Number(650.0))
    except: pass
    
    pa = GH_Panel()
    pa.CreateAttributes()
    pa.Attributes.Pivot = sd.PointF(float(PX + 360), float(740))
    gd.AddObject(pa, False)
    pa.AddSource(ma.Params.Output[0])
    
    pc = GH_Panel()
    pc.CreateAttributes()
    pc.Attributes.Pivot = sd.PointF(float(PX + 360), float(810))
    gd.AddObject(pc, False)
    pc.AddSource(mc.Params.Output[0])
    
    scribble("Total Area (m²)", PX + 360, 725, 9)
    scribble("Est. Cost ($)", PX + 360, 795, 9)
    
    grp("PERFORMANCE CALCULATOR (NATIVE GRAPH)", (200, 100, 50, 50), [mw, mh, ma, mc, pa, pc])

# ── Slider layout constants ───────────────────────────────────────────────────
A = 80; B = 290; H = 32; GP = 24
sliders = {}; y = 80

# ── Title Scribbles ───────────────────────────────────────────────────────────
scribble("PARAMETRIC CURTAIN WALL FAÇADE SYSTEM", A, 10, 18)
scribble("AEC Omni-Bridge Model Engine — Refined Façade Engineering Definition", A, 38, 9)

specs = [
    ("A  GRID & BAYS", (45, 80, 135, 55), [
        ("num_bays",       1,   10,    3,   A, 0, 0),
        ("num_floors",     1,    5,    2,   B, 0, 0),
        ("bay_width",     0.8,  3.0,  1.50, A, 1, 2),
        ("floor_height",  2.5,  5.0,  3.50, B, 1, 2),
    ]),
    ("B  STRUCTURAL PROFILES", (135, 80, 45, 55), [
        ("mullion_w",     0.03, 0.10, 0.060, A, 0, 3),
        ("mullion_d",     0.08, 0.25, 0.150, B, 0, 3),
        ("mullion_t",     0.002,0.008,0.003, A, 1, 3),
        ("transom_w",     0.03, 0.10, 0.060, B, 1, 3),
        ("transom_d",     0.06, 0.20, 0.120, A, 2, 3),
        ("transom_t",     0.002,0.008,0.003, B, 2, 3),
    ]),
    ("C  INSULATED GLAZING (IGU)", (45, 135, 80, 55), [
        ("glass_outer_t", 0.004, 0.015, 0.006, A, 0, 3),
        ("glass_inner_t", 0.004, 0.015, 0.006, B, 0, 3),
        ("glass_gap_t",   0.008, 0.024, 0.016, A, 1, 3),
        ("glass_reveal",  0.005, 0.025, 0.010, B, 1, 3),
        ("glass_setback", 0.020, 0.080, 0.040, A, 2, 3),
    ]),
    ("D  GASKETS & PRESSURE PLATES", (135, 120, 40, 55), [
        ("gasket_t",         0.002, 0.010, 0.004, A, 0, 3),
        ("gasket_w",         0.005, 0.020, 0.012, B, 0, 3),
        ("isolator_w",       0.006, 0.024, 0.012, A, 1, 3),
        ("pressure_plate_t", 0.004, 0.015, 0.006, B, 1, 3),
        ("cover_cap_d",      0.010, 0.050, 0.020, A, 2, 3),
    ]),
    ("E  SLAB & ANCHOR BRACKETS", (80, 80, 80, 55), [
        ("slab_t",        0.15,  0.50,  0.30,  A, 0, 2),
        ("slab_depth",    0.50,  2.50,  1.50,  B, 0, 2),
        ("slab_inset",    0.005, 0.050, 0.010, A, 1, 3),
        ("bracket_w",     0.040, 0.150, 0.080, B, 1, 3),
        ("bracket_l1",    0.080, 0.300, 0.150, A, 2, 3),
        ("bracket_l2",    0.060, 0.250, 0.120, B, 2, 3),
        ("bracket_t",     0.004, 0.016, 0.008, A, 3, 3),
    ]),
]

for grp_title, grp_rgba, items in specs:
    scribble(grp_title[3:], A, y - 22, 11)
    g_objs = []
    rows = max(r for _, _, _, _, _, r, _ in items)
    for name, mn, mx, val, col, row, dec in items:
        s = sl(name, mn, mx, val, col, y + row * H, dec)
        g_objs.append(s)
        sliders[name] = s
    grp(grp_title, grp_rgba, g_objs)
    y += (rows + 1) * H + GP + 15

print("Sliders created: %d" % len(sliders))

# ── Python Script component ───────────────────────────────────────────────────
PX = 580; PY_COMP_Y = 60
GHPY_GUID = System.Guid("719467e6-7cf5-4848-99b0-c5dd57e5442c") # New Python 3 Script component

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
            if "python 3" in nm or "ghpython" in nm or "ironpython 2" in nm:
                py_proxy = proxy
                break
        except: pass

if py_proxy:
    py_comp = py_proxy.CreateInstance()
    py_comp.CreateAttributes()
    py_comp.Attributes.Pivot = sd.PointF(float(PX), float(PY_COMP_Y))
    gd.AddObject(py_comp, False)
    print("Python component instantiated: %s" % py_proxy.Desc.Name)

    SLIDER_ORDER = [
        "num_bays", "num_floors", "bay_width", "floor_height",
        "mullion_w", "mullion_d", "mullion_t", "transom_w", "transom_d", "transom_t",
        "glass_outer_t", "glass_inner_t", "glass_gap_t", "glass_reveal", "glass_setback",
        "gasket_t", "gasket_w", "isolator_w", "pressure_plate_t", "cover_cap_d",
        "slab_t", "slab_depth", "slab_inset",
        "bracket_w", "bracket_l1", "bracket_l2", "bracket_t"
    ]

    FACADE_CODE = r'''# =============================================================================
# DETAILED FAÇADE SYSTEM — Grasshopper Python Runtime Engine (Refined & Corrected)
# =============================================================================
import math
import Rhino
import Rhino.Geometry as rg
import scriptcontext as sc
import System
from System.Collections.Generic import List

# Redirect scriptcontext to Rhino Document (so we bake directly into the active Rhino scene if requested)
try:
    ghdoc = sc.doc
    sc.doc = Rhino.RhinoDoc.ActiveDoc
except:
    pass

doc = sc.doc
tol = doc.ModelAbsoluteTolerance
S = Rhino.RhinoMath.UnitScale(Rhino.UnitSystem.Meters, doc.ModelUnitSystem)

# Sliders utility
def _f(v, default):
    try: return float(v) if v is not None else default
    except: return default
def _i(v, default):
    try: return int(v) if v is not None else default
    except: return default

# Map inputs
NUM_BAYS         = _i(num_bays,         3)
NUM_FLOORS       = _i(num_floors,       2)
BAY_WIDTH        = _f(bay_width,        1.50)
FLOOR_HEIGHT     = _f(floor_height,     3.50)

MULLION_W        = _f(mullion_w,        0.060)
MULLION_D        = _f(mullion_d,        0.150)
MULLION_T        = _f(mullion_t,        0.003)

TRANSOM_W        = _f(transom_w,        0.060)
TRANSOM_D        = _f(transom_d,        0.120)
TRANSOM_T        = _f(transom_t,        0.003)

GLASS_OUTER_T    = _f(glass_outer_t,    0.006)
GLASS_INNER_T    = _f(glass_inner_t,    0.006)
GLASS_GAP_T      = _f(glass_gap_t,      0.016)
GLASS_REVEAL     = _f(glass_reveal,     0.015)
GLASS_SETBACK    = _f(glass_setback,    0.040)

GASKET_T         = _f(gasket_t,         0.004)
GASKET_W         = _f(gasket_w,         0.012)
ISOLATOR_W       = _f(isolator_w,       0.012)
PRESSURE_PLATE_T = _f(pressure_plate_t, 0.006)
COVER_CAP_D      = _f(cover_cap_d,      0.020)

SLAB_T           = _f(slab_t,           0.30)
SLAB_DEPTH       = _f(slab_depth,       1.50)
SLAB_INSET       = _f(slab_inset,       0.010)

BRACKET_W        = _f(bracket_w,        0.080)
BRACKET_L1       = _f(bracket_l1,       0.150)
BRACKET_L2       = _f(bracket_l2,       0.120)
BRACKET_T        = _f(bracket_t,        0.008)

# Scale to active units
BAY_WIDTH        *= S; FLOOR_HEIGHT     *= S
MULLION_W        *= S; MULLION_D        *= S; MULLION_T        *= S
TRANSOM_W        *= S; TRANSOM_D        *= S; TRANSOM_T        *= S
GLASS_OUTER_T    *= S; GLASS_INNER_T    *= S; GLASS_GAP_T      *= S
GLASS_REVEAL     *= S; GLASS_SETBACK    *= S
GASKET_T         *= S; GASKET_W         *= S; ISOLATOR_W       *= S
PRESSURE_PLATE_T *= S; COVER_CAP_D      *= S
SLAB_T           *= S; SLAB_DEPTH       *= S; SLAB_INSET       *= S
BRACKET_W        *= S; BRACKET_L1       *= S; BRACKET_L2       *= S; BRACKET_T *= S

TOTAL_HEIGHT = NUM_FLOORS * FLOOR_HEIGHT

def make_hollow_tube(plane, w, y_min, y_max, length):
    rect = rg.Rectangle3d(rg.Plane.WorldXY, rg.Interval(-w*0.5, w*0.5), rg.Interval(y_min, y_max))
    ext = rg.Extrusion.Create(rect.ToNurbsCurve(), length, True).ToBrep()
    if ext:
        xf = rg.Transform.PlaneToPlane(rg.Plane.WorldXY, plane)
        ext.Transform(xf)
        return ext
    return None

# Coords grid
X_grid = [i * BAY_WIDTH for i in range(NUM_BAYS + 1)]

# Define transom elevations
Z_grid = []
Z_grid.append(0.0) # Bottom boundary (Sill)
for f in range(1, NUM_FLOORS):
    fz = f * FLOOR_HEIGHT
    Z_grid.append(fz - 0.15 * S) # Head transom: 150mm below slab level
    Z_grid.append(fz + 0.85 * S) # Sill transom: 850mm above slab level
Z_grid.append(TOTAL_HEIGHT) # Top boundary (Head)
Z_grid = sorted(list(set(Z_grid)))

m_list = List[rg.Brep]()
t_list = List[rg.Brep]()
go_list = List[rg.Brep]()
gi_list = List[rg.Brep]()
g_list = List[rg.Brep]()
b_list = List[rg.Brep]()
fs_list = List[rg.Brep]()
fx_list = List[rg.Brep]()
s_list = List[rg.Brep]()
n_glass = 0

# Mullions with Noses
for x in X_grid:
    m_plane = rg.Plane(rg.Point3d(x, 0.0, 0.0), rg.Vector3d.XAxis, rg.Vector3d.YAxis)
    y_front = -GLASS_SETBACK + GASKET_T
    y_back  = y_front + MULLION_D
    m_brep = make_hollow_tube(m_plane, MULLION_W, y_front, y_back, TOTAL_HEIGHT)
    if m_brep: m_list.Add(m_brep)
    
    nose_w = 0.024 * S
    y_nose_min = -GLASS_SETBACK - GLASS_INNER_T
    y_nose_max = -GLASS_SETBACK + GASKET_T
    m_nose_brep = make_hollow_tube(m_plane, nose_w, y_nose_min, y_nose_max, TOTAL_HEIGHT)
    if m_nose_brep: m_list.Add(m_nose_brep)

# Transoms with Noses (placed at all Z_grid levels)
for k in range(len(Z_grid)):
    z = Z_grid[k]

    for i in range(NUM_BAYS):
        x_start = X_grid[i] + MULLION_W*0.5
        x_end   = X_grid[i+1] - MULLION_W*0.5
        length  = x_end - x_start
        if length <= 0: continue
        
        t_plane = rg.Plane(rg.Point3d(x_start, 0.0, z), -rg.Vector3d.ZAxis, rg.Vector3d.YAxis)
        y_front = -GLASS_SETBACK + GASKET_T
        y_back  = y_front + TRANSOM_D
        t_brep = make_hollow_tube(t_plane, TRANSOM_W, y_front, y_back, length)
        if t_brep: t_list.Add(t_brep)
        
        nose_w = 0.024 * S
        y_nose_min = -GLASS_SETBACK - GLASS_INNER_T
        y_nose_max = -GLASS_SETBACK + GASKET_T
        t_nose_brep = make_hollow_tube(t_plane, nose_w, y_nose_min, y_nose_max, length)
        if t_nose_brep: t_list.Add(t_nose_brep)

# Floor slabs and Fire Stop containment (intermediate levels only)
for f in range(1, NUM_FLOORS):
    z_floor = f * FLOOR_HEIGHT
    y_mullion_back = -GLASS_SETBACK + GASKET_T + MULLION_D
    slab_edge_y = y_mullion_back + SLAB_INSET
    
    # Slab
    slab = rg.Box(rg.Plane.WorldXY, rg.Interval(0.0, NUM_BAYS * BAY_WIDTH), rg.Interval(slab_edge_y, slab_edge_y + SLAB_DEPTH), rg.Interval(z_floor - SLAB_T, z_floor)).ToBrep()
    if slab: s_list.Add(slab)
        
    # Fire wool
    firestop_wool = rg.Box(rg.Plane.WorldXY, rg.Interval(0.0, NUM_BAYS * BAY_WIDTH), rg.Interval(y_mullion_back, slab_edge_y), rg.Interval(z_floor - SLAB_T, z_floor)).ToBrep()
    if firestop_wool: fs_list.Add(firestop_wool)
        
    # Galvanized sheet
    smoke_sheet = rg.Box(rg.Plane.WorldXY, rg.Interval(0.0, NUM_BAYS * BAY_WIDTH), rg.Interval(y_mullion_back, slab_edge_y + 0.050*S), rg.Interval(z_floor, z_floor + 0.002*S)).ToBrep()
    if smoke_sheet: b_list.Add(smoke_sheet)

# Slab brackets (intermediate levels only)
for f in range(1, NUM_FLOORS):
    z_floor = f * FLOOR_HEIGHT
    y_mullion_back = -GLASS_SETBACK + GASKET_T + MULLION_D
    slab_edge_y = y_mullion_back + SLAB_INSET
    for x in X_grid:
        leg1_l = rg.Box(rg.Plane.WorldXY, rg.Interval(x - MULLION_W*0.5 - BRACKET_T, x - MULLION_W*0.5), rg.Interval(slab_edge_y, slab_edge_y + BRACKET_L1), rg.Interval(z_floor, z_floor + BRACKET_T)).ToBrep()
        leg2_l = rg.Box(rg.Plane.WorldXY, rg.Interval(x - MULLION_W*0.5 - BRACKET_T, x - MULLION_W*0.5), rg.Interval(y_mullion_back - BRACKET_W, slab_edge_y), rg.Interval(z_floor, z_floor + BRACKET_L2)).ToBrep()
        if leg1_l: b_list.Add(leg1_l)
        if leg2_l: b_list.Add(leg2_l)
        leg1_r = rg.Box(rg.Plane.WorldXY, rg.Interval(x + MULLION_W*0.5, x + MULLION_W*0.5 + BRACKET_T), rg.Interval(slab_edge_y, slab_edge_y + BRACKET_L1), rg.Interval(z_floor, z_floor + BRACKET_T)).ToBrep()
        leg2_r = rg.Box(rg.Plane.WorldXY, rg.Interval(x + MULLION_W*0.5, x + MULLION_W*0.5 + BRACKET_T), rg.Interval(y_mullion_back - BRACKET_W, slab_edge_y), rg.Interval(z_floor, z_floor + BRACKET_L2)).ToBrep()
        if leg1_r: b_list.Add(leg1_r)
        if leg2_r: b_list.Add(leg2_r)

# Gaskets and pressure plates on Mullions
g_w_m = MULLION_W * 0.5 - GLASS_REVEAL  # Dynamic gasket width matching mullion shoulders

for x in X_grid:
    g_l = rg.Box(rg.Plane.WorldXY, rg.Interval(x - GLASS_REVEAL - g_w_m, x - GLASS_REVEAL), rg.Interval(-GLASS_SETBACK, -GLASS_SETBACK + GASKET_T), rg.Interval(0.0, TOTAL_HEIGHT)).ToBrep()
    g_r = rg.Box(rg.Plane.WorldXY, rg.Interval(x + GLASS_REVEAL, x + GLASS_REVEAL + g_w_m), rg.Interval(-GLASS_SETBACK, -GLASS_SETBACK + GASKET_T), rg.Interval(0.0, TOTAL_HEIGHT)).ToBrep()
    if g_l: g_list.Add(g_l)
    if g_r: g_list.Add(g_r)
    
    gy_min = -GLASS_SETBACK - GLASS_INNER_T - GLASS_GAP_T - GLASS_OUTER_T - GASKET_T
    gy_max = gy_min + GASKET_T
    og_l = rg.Box(rg.Plane.WorldXY, rg.Interval(x - GLASS_REVEAL - g_w_m, x - GLASS_REVEAL), rg.Interval(gy_min, gy_max), rg.Interval(0.0, TOTAL_HEIGHT)).ToBrep()
    og_r = rg.Box(rg.Plane.WorldXY, rg.Interval(x + GLASS_REVEAL, x + GLASS_REVEAL + g_w_m), rg.Interval(gy_min, gy_max), rg.Interval(0.0, TOTAL_HEIGHT)).ToBrep()
    if og_l: g_list.Add(og_l)
    if og_r: g_list.Add(og_r)

    
    iy_min = -GLASS_SETBACK - GLASS_INNER_T - GLASS_GAP_T - GLASS_OUTER_T
    iy_max = -GLASS_SETBACK - GLASS_INNER_T
    ti = rg.Box(rg.Plane.WorldXY, rg.Interval(x - ISOLATOR_W*0.5, x + ISOLATOR_W*0.5), rg.Interval(iy_min, iy_max), rg.Interval(0.0, TOTAL_HEIGHT)).ToBrep()
    if ti: t_list.Add(ti)
    
    py_min = -GLASS_SETBACK - GLASS_INNER_T - GLASS_GAP_T - GLASS_OUTER_T - GASKET_T - PRESSURE_PLATE_T
    py_max = py_min + PRESSURE_PLATE_T
    pp = rg.Box(rg.Plane.WorldXY, rg.Interval(x - MULLION_W*0.5, x + MULLION_W*0.5), rg.Interval(py_min, py_max), rg.Interval(0.0, TOTAL_HEIGHT)).ToBrep()
    if pp: t_list.Add(pp)

    # Caps
    pts_c = [
        rg.Point3d(-MULLION_W*0.5, 0.0, 0.0),
        rg.Point3d(-MULLION_W*0.5, -COVER_CAP_D + 0.006*S, 0.0),
        rg.Point3d(-MULLION_W*0.5 + 0.006*S, -COVER_CAP_D, 0.0),
        rg.Point3d(MULLION_W*0.5 - 0.006*S, -COVER_CAP_D, 0.0),
        rg.Point3d(MULLION_W*0.5, -COVER_CAP_D + 0.006*S, 0.0),
        rg.Point3d(MULLION_W*0.5, 0.0, 0.0),
        rg.Point3d(-MULLION_W*0.5, 0.0, 0.0)
    ]
    pl = rg.Polyline(pts_c).ToNurbsCurve()
    ext = rg.Extrusion.Create(pl, TOTAL_HEIGHT, True).ToBrep()
    if ext:
        ext.Transform(rg.Transform.PlaneToPlane(rg.Plane.WorldXY, rg.Plane(rg.Point3d(x, py_min, 0.0), rg.Vector3d.XAxis, rg.Vector3d.YAxis)))
        t_list.Add(ext)

    # Screws
    screw_spacing = 0.35 * S; screw_rad = 0.004 * S; screw_len = 0.090 * S
    cur_z = 0.1 * S
    while cur_z < TOTAL_HEIGHT:
        cyl_plane = rg.Plane(rg.Point3d(x, py_min, cur_z), rg.Vector3d.YAxis)
        cyl = rg.Cylinder(rg.Circle(cyl_plane, screw_rad), screw_len).ToBrep(True, True)
        if cyl: fx_list.Add(cyl)
        cur_z += screw_spacing

# Gaskets and accessories on Transoms
g_w_t = TRANSOM_W * 0.5 - GLASS_REVEAL  # Dynamic gasket width matching transom shoulders

for k in range(len(Z_grid)):
    z = Z_grid[k]

    for i in range(NUM_BAYS):
        x_start = X_grid[i] + MULLION_W*0.5
        x_end   = X_grid[i+1] - MULLION_W*0.5
        length  = x_end - x_start
        if length <= 0: continue
        
        gy_min = -GLASS_SETBACK - GLASS_INNER_T - GLASS_GAP_T - GLASS_OUTER_T - GASKET_T
        gy_max = gy_min + GASKET_T

        # Top Gaskets (seal the glass above the transom) - skip if top boundary
        if k < len(Z_grid) - 1:
            g_t = rg.Box(rg.Plane.WorldXY, rg.Interval(x_start, x_end), rg.Interval(-GLASS_SETBACK, -GLASS_SETBACK + GASKET_T), rg.Interval(z + GLASS_REVEAL, z + GLASS_REVEAL + g_w_t)).ToBrep()
            if g_t: g_list.Add(g_t)
            
            og_t = rg.Box(rg.Plane.WorldXY, rg.Interval(x_start, x_end), rg.Interval(gy_min, gy_max), rg.Interval(z + GLASS_REVEAL, z + GLASS_REVEAL + g_w_t)).ToBrep()
            if og_t: g_list.Add(og_t)

        # Bottom Gaskets (seal the glass below the transom) - skip if bottom boundary
        if k > 0:
            g_b = rg.Box(rg.Plane.WorldXY, rg.Interval(x_start, x_end), rg.Interval(-GLASS_SETBACK, -GLASS_SETBACK + GASKET_T), rg.Interval(z - GLASS_REVEAL - g_w_t, z - GLASS_REVEAL)).ToBrep()
            if g_b: g_list.Add(g_b)
            
            og_b = rg.Box(rg.Plane.WorldXY, rg.Interval(x_start, x_end), rg.Interval(gy_min, gy_max), rg.Interval(z - GLASS_REVEAL - g_w_t, z - GLASS_REVEAL)).ToBrep()
            if og_b: g_list.Add(og_b)

        
        iy_min = -GLASS_SETBACK - GLASS_INNER_T - GLASS_GAP_T - GLASS_OUTER_T
        iy_max = -GLASS_SETBACK - GLASS_INNER_T
        ti = rg.Box(rg.Plane.WorldXY, rg.Interval(x_start, x_end), rg.Interval(iy_min, iy_max), rg.Interval(z - ISOLATOR_W*0.5, z + ISOLATOR_W*0.5)).ToBrep()
        if ti: t_list.Add(ti)
        
        py_min = -GLASS_SETBACK - GLASS_INNER_T - GLASS_GAP_T - GLASS_OUTER_T - GASKET_T - PRESSURE_PLATE_T
        py_max = py_min + PRESSURE_PLATE_T
        pp = rg.Box(rg.Plane.WorldXY, rg.Interval(x_start, x_end), rg.Interval(py_min, py_max), rg.Interval(z - TRANSOM_W*0.5, z + TRANSOM_W*0.5)).ToBrep()
        if pp: t_list.Add(pp)

        # Transom cap
        pts_c = [
            rg.Point3d(-TRANSOM_W*0.5, 0.0, 0.0),
            rg.Point3d(-TRANSOM_W*0.5, -COVER_CAP_D + 0.006*S, 0.0),
            rg.Point3d(-TRANSOM_W*0.5 + 0.006*S, -COVER_CAP_D, 0.0),
            rg.Point3d(TRANSOM_W*0.5 - 0.006*S, -COVER_CAP_D, 0.0),
            rg.Point3d(TRANSOM_W*0.5, -COVER_CAP_D + 0.006*S, 0.0),
            rg.Point3d(TRANSOM_W*0.5, 0.0, 0.0),
            rg.Point3d(-TRANSOM_W*0.5, 0.0, 0.0)
        ]
        pl = rg.Polyline(pts_c).ToNurbsCurve()
        ext = rg.Extrusion.Create(pl, length, True).ToBrep()
        if ext:
            ext.Transform(rg.Transform.PlaneToPlane(rg.Plane.WorldXY, rg.Plane(rg.Point3d(x_start, py_min, z), -rg.Vector3d.ZAxis, rg.Vector3d.YAxis)))
            t_list.Add(ext)

        # Screws
        screw_spacing = 0.35 * S; screw_rad = 0.004 * S; screw_len = 0.090 * S
        cur_x = x_start + 0.1 * S
        while cur_x < x_end:
            cyl_plane = rg.Plane(rg.Point3d(cur_x, py_min, z), rg.Vector3d.YAxis)
            cyl = rg.Cylinder(rg.Circle(cyl_plane, screw_rad), screw_len).ToBrep(True, True)
            if cyl: fx_list.Add(cyl)
            cur_x += screw_spacing

# IGUs
for k in range(len(Z_grid) - 1):
    z_start = Z_grid[k]
    z_end   = Z_grid[k+1]
    for i in range(NUM_BAYS):
        x_start = X_grid[i]; x_end = X_grid[i+1]
        x1 = x_start + GLASS_REVEAL; x2 = x_end - GLASS_REVEAL
        z1 = z_start + GLASS_REVEAL; z2 = z_end - GLASS_REVEAL
        if x2 - x1 <= 0 or z2 - z1 <= 0: continue
        
        # Inner Glass
        y_in_min = -GLASS_SETBACK - GLASS_INNER_T
        y_in_max = -GLASS_SETBACK
        glass_in = rg.Box(rg.Plane.WorldXY, rg.Interval(x1, x2), rg.Interval(y_in_min, y_in_max), rg.Interval(z1, z2)).ToBrep()
        if glass_in: gi_list.Add(glass_in)

        # Outer Glass
        y_ot_min = -GLASS_SETBACK - GLASS_INNER_T - GLASS_GAP_T - GLASS_OUTER_T
        y_ot_max = y_ot_min + GLASS_OUTER_T
        glass_ot = rg.Box(rg.Plane.WorldXY, rg.Interval(x1, x2), rg.Interval(y_ot_min, y_ot_max), rg.Interval(z1, z2)).ToBrep()
        if glass_ot: go_list.Add(glass_ot)

        # Spacers and sealant
        sp_offset = 0.015 * S; sp_width = 0.012 * S
        sx1 = x1 + sp_offset; sx2 = x2 - sp_offset
        sz1 = z1 + sp_offset; sz2 = z2 - sp_offset
        sy_min_spacer = -GLASS_SETBACK - GLASS_INNER_T - GLASS_GAP_T
        sy_max_spacer = -GLASS_SETBACK - GLASS_INNER_T
        if sx2 - sx1 > 0 and sz2 - sz1 > 0:
            sp_l = rg.Box(rg.Plane.WorldXY, rg.Interval(sx1, sx1 + sp_width), rg.Interval(sy_min_spacer, sy_max_spacer), rg.Interval(sz1, sz2)).ToBrep()
            sp_r = rg.Box(rg.Plane.WorldXY, rg.Interval(sx2 - sp_width, sx2), rg.Interval(sy_min_spacer, sy_max_spacer), rg.Interval(sz1, sz2)).ToBrep()
            sp_b = rg.Box(rg.Plane.WorldXY, rg.Interval(sx1 + sp_width, sx2 - sp_width), rg.Interval(sy_min_spacer, sy_max_spacer), rg.Interval(sz1, sz1 + sp_width)).ToBrep()
            sp_t = rg.Box(rg.Plane.WorldXY, rg.Interval(sx1 + sp_width, sx2 - sp_width), rg.Interval(sy_min_spacer, sy_max_spacer), rg.Interval(sz2 - sp_width, sz2)).ToBrep()
            for sp in (sp_l, sp_r, sp_b, sp_t):
                if sp: t_list.Add(sp)

            se_l = rg.Box(rg.Plane.WorldXY, rg.Interval(x1, sx1), rg.Interval(sy_min_spacer, sy_max_spacer), rg.Interval(z1, z2)).ToBrep()
            se_r = rg.Box(rg.Plane.WorldXY, rg.Interval(sx2, x2), rg.Interval(sy_min_spacer, sy_max_spacer), rg.Interval(z1, z2)).ToBrep()
            se_b = rg.Box(rg.Plane.WorldXY, rg.Interval(sx1, sx2), rg.Interval(sy_min_spacer, sy_max_spacer), rg.Interval(z1, sz1)).ToBrep()
            se_t = rg.Box(rg.Plane.WorldXY, rg.Interval(sx1, sx2), rg.Interval(sy_min_spacer, sy_max_spacer), rg.Interval(sz2, z2)).ToBrep()
            for se in (se_l, se_r, se_b, se_t):
                if se: t_list.Add(se)
        n_glass += 1

mullions = m_list
transoms = t_list
glass_outer = go_list
glass_inner = gi_list
gaskets = g_list
brackets = b_list
firestops = fs_list
fixings = fx_list
slabs = s_list
# Restore Grasshopper scriptcontext
try:
    sc.doc = ghdoc
except:
    pass
'''

    # Try setting code via SetSource (Python 3) or property reflection (GhPython)
    code_set = False
    if hasattr(py_comp, "SetSource"):
        try:
            py_comp.SetSource(FACADE_CODE)
            code_set = True
            print("Code embedded successfully via SetSource (Python 3)")
        except Exception as e:
            print("SetSource attempt failed: %s" % e)
            
    if not code_set:
        for prop_name in ("Code", "ScriptSource", "Expression"):
            try:
                prop = py_comp.GetType().GetProperty(prop_name)
                if prop and prop.CanWrite:
                    prop.SetValue(py_comp, FACADE_CODE, None)
                    code_set = True
                    print("Code embedded successfully via: %s" % prop_name)
                    break
            except: pass

    # Expand inputs dynamically matching slider count
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
            print("  Input parameter expansion failed at %d: %s" % (py_comp.Params.Input.Count, e))
            break
    try:
        py_comp.VariableParameterMaintenance()
        py_comp.Params.OnParametersChanged()
    except: pass
    print("Inputs expanded to: %d (added %d)" % (py_comp.Params.Input.Count, added))

    # Connect/wire each slider to its corresponding input
    n_wired = 0
    for idx, sname in enumerate(SLIDER_ORDER):
        if sname not in sliders: continue
        if idx >= py_comp.Params.Input.Count: break
        try:
            ip = py_comp.Params.Input[idx]
            ip.NickName = sname
            ip.Name = sname
            ip.AddSource(sliders[sname])
            n_wired += 1
        except Exception as wire_err:
            print("  Wiring failure for parameter %s: %s" % (sname, wire_err))

    print("Wired %d / %d inputs to sliders" % (n_wired, target))
    
    # ── Add Custom Outputs to Python Component ────────────────────────────────
    OUTPUT_NAMES = ["mullions", "transoms", "glass_outer", "glass_inner", "gaskets", "brackets", "slabs", "firestops", "fixings"]
    # Unregister default output "a" if it exists at index 1
    while py_comp.Params.Output.Count > 1:
        try:
            py_comp.Params.UnregisterOutputParam(py_comp.Params.Output[1])
        except: break
        
    for name in OUTPUT_NAMES:
        try:
            param = py_comp.CreateParameter(GH_ParameterSide.Output, py_comp.Params.Output.Count)
            param.NickName = name
            param.Name = name
            py_comp.Params.RegisterOutputParam(param)
        except Exception as out_err:
            print("  Output registration failed for %s: %s" % (name, out_err))
            
    try:
        py_comp.VariableParameterMaintenance()
        py_comp.Params.OnParametersChanged()
    except: pass
    print("Outputs expanded to: %d" % py_comp.Params.Output.Count)

    # ── Custom Preview & Swatch pipeline instantiation ────────────────────────
    preview_proxy = None
    swatch_proxy = None
    for proxy in server.ObjectProxies:
        try:
            nm = proxy.Desc.Name.lower()
            if nm == "custom preview":
                preview_proxy = proxy
            elif nm == "colour swatch" or nm == "color swatch":
                swatch_proxy = proxy
        except: pass

    if preview_proxy and swatch_proxy:
        print("Building Custom Preview pipeline...")
        PREVIEW_SPECS = [
            ("mullions",     (35, 38, 46, 255), 0),
            ("transoms",     (50, 55, 65, 255), 1),
            ("glass_outer",  (60, 140, 210, 100), 2),
            ("glass_inner",  (170, 210, 240, 60), 3),
            ("gaskets",      (20, 20, 20, 255), 4),
            ("brackets",     (120, 120, 125, 255), 5),
            ("slabs",        (160, 155, 145, 255), 6),
            ("firestops",    (180, 160, 100, 255), 7),
            ("fixings",      (220, 220, 225, 255), 8),
        ]

        DESCRIPTIONS = {
            "mullions":     "Mullion Profiles\nAlu 6063-T6, Anodized\nSightline 60mm, D=150mm\nUf = 1.6 W/m²K",
            "transoms":     "Transom Profiles & Accessories\nTransom 60x120mm, Cover Caps,\nPressure Plates, Thermal Isolator",
            "glass_outer":  "Outer Glass Pane\n6mm solar-control, tinted\nSolar heat gain g = 0.38\nUg = 1.1 W/m²K",
            "glass_inner":  "Inner Glass Pane\n6mm clear float\nRoom-side glazing surface",
            "gaskets":      "EPDM Weather Gaskets\nContinuous internal & external\nperimeter air/water barrier seals",
            "brackets":     "Anchor Brackets & Sheets\nGalvanized steel flanking legs &\n2mm sheet smoke containment",
            "slabs":        "Concrete Floor Slabs\nC30/37 reinforced structural slab\nThickness = 300mm",
            "firestops":    "Perimeter Fire Safing\n2-hour rated rockwool fire stop\nbetween slab edge & mullion back",
            "fixings":      "Structural Screws & Bolts\nM8 stainless steel screws\nspaced at 350mm centers",
        }
        
        legend_objs = []
        scribble("III. MATERIAL SPECIFICATION LEGEND", PX + 160, PY_COMP_Y - 35, 12)

        for idx, (out_name, rgba, row_idx) in enumerate(PREVIEW_SPECS):
            row_spacing = 70
            # Swatch
            swatch = swatch_proxy.CreateInstance()
            swatch.CreateAttributes()
            sw_x = PX + 160
            sw_y = PY_COMP_Y + row_idx * row_spacing
            swatch.Attributes.Pivot = sd.PointF(float(sw_x), float(sw_y + 15))
            try: swatch.SwatchColour = sd.Color.FromArgb(*rgba)
            except: pass

            gd.AddObject(swatch, False)
            legend_objs.append(swatch)

            # Preview
            preview = preview_proxy.CreateInstance()
            preview.CreateAttributes()
            pr_x = PX + 260
            pr_y = PY_COMP_Y + row_idx * row_spacing
            preview.Attributes.Pivot = sd.PointF(float(pr_x), float(pr_y + 15))
            gd.AddObject(preview, False)
            legend_objs.append(preview)

            # Wire Python output -> Preview input 0 (G)
            py_out = None
            for p in py_comp.Params.Output:
                if p.Name == out_name:
                    py_out = p
                    break
            if py_out and preview.Params.Input.Count > 0:
                preview.Params.Input[0].AddSource(py_out)

            # Wire Swatch -> Preview input 1 (M)
            if preview.Params.Input.Count > 1:
                preview.Params.Input[1].AddSource(swatch)
                
            # Description Panel
            p_desc = GH_Panel()
            p_desc.CreateAttributes()
            p_desc.Attributes.Pivot = sd.PointF(float(PX + 360), float(pr_y))
            p_desc.UserText = DESCRIPTIONS[out_name]
            gd.AddObject(p_desc, False)
            legend_objs.append(p_desc)
            
        grp("MATERIAL LEGEND & SPECIFICATIONS", (100, 100, 100, 100), legend_objs)
        print("Visual previews wired successfully.")
else:
    print("WARNING: Python component could not be resolved programmatically.")

# ── Performance Calculator ──────────────────────────────────────────────────
build_performance_calculator()
 
# ── Info/Annotation Panel ─────────────────────────────────────────────────────
pan(
    "PARAMETRIC FAÇADE SYSTEM — AEC Model Bridge\n"
    "Realistic, high-detail stick curtain wall generator (Audited Edition)\n\n"
    "Sliders control:\n"
    " A  Grid & Bays           Bay counts, floor lines, widths, floor heights\n"
    " B  Structural Profiles   Mullion and transom section dimensions\n"
    " C  Insulated Glazing     IGU double glazing outer/inner panes, spacer and air gap\n"
    " D  Gaskets & Plates      Clamping pressure plate, cover caps, isolator breaks, gaskets\n"
    " E  Slab & Brackets       Flanking concrete anchor brackets, slab thickness, extensions\n\n"
    "Instructions:\n"
    "1. Open Grasshopper and adjust any slider in the left column.\n"
    "2. Viewport automatically updates dynamically via Custom Previews.\n"
    "3. To bake into permanent Rhino objects, right-click the Custom Preview and click Bake.\n"
    "4. Clean visual layout resembles senior facade engineering logic.",
    PX + 620, PY_COMP_Y
)

# ── Re-enable solution solver and save file ───────────────────────────────────
gd.Enabled = True
canvas.Refresh()
print("Grasshopper canvas building complete! Total objects: %d" % gd.ObjectCount)

# Save the Grasshopper document to the scratch folder for easy load
save_path = r"c:\Users\sammo\OneDrive\Documenten\GitHub\Autodesk-Revit-MCP-Server\scratch\facade_system.gh"
try:
    doc_io = gh.Kernel.GH_DocumentIO(gd)
    doc_io.SaveQuiet(save_path)
    print("Saved Grasshopper definition to: %s" % save_path)
except Exception as e:
    print("Warning: failed to save GH file: %s" % e)
