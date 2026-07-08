# =============================================================================
# DETAILED FAÇADE SYSTEM — Stick Curtain Wall Generator (Engineered Portfolio)
# AEC Omni-Bridge MCP  |  Run via bridge or Rhino PythonEdit (F5)
# =============================================================================

import math
import Rhino
import Rhino.Geometry as rg
import Rhino.DocObjects as rdo
import Rhino.Display as rdp
import scriptcontext as sc
import System.Drawing as sd

doc = sc.doc
tol = doc.ModelAbsoluteTolerance
S = Rhino.RhinoMath.UnitScale(Rhino.UnitSystem.Meters, doc.ModelUnitSystem)

# =============================================================================
# PARAMETERS (all values in Metres, auto-scaled)
# =============================================================================
NUM_BAYS         = 3       # Number of vertical bays
NUM_FLOORS       = 2       # Number of floors
BAY_WIDTH        = 1.50    # Horizontal bay spacing (m)
FLOOR_HEIGHT     = 3.50    # Floor-to-floor height (m)

# Mullion & Transom Profile Dimensions
MULLION_W        = 0.060   # Sightline width (60 mm - upgraded for 15mm glass bite)
MULLION_D        = 0.150   # Mullion depth (150 mm)
MULLION_T        = 0.003   # Extrusion wall thickness (3 mm)

TRANSOM_W        = 0.060   # Sightline width (60 mm - upgraded for consistency)
TRANSOM_D        = 0.120   # Transom depth (120 mm)
TRANSOM_T        = 0.003   # Extrusion wall thickness (3 mm)

# Double Glazing (IGU) Parameters
GLASS_OUTER_T    = 0.006   # Outer pane thickness (6 mm)
GLASS_INNER_T    = 0.006   # Inner pane thickness (6 mm)
GLASS_GAP_T      = 0.016   # Argon gas spacer gap (16 mm)
GLASS_REVEAL     = 0.015   # Expansion joint gap from gridline (15 mm)
GLASS_SETBACK    = 0.040   # Setback from mullion front face (40 mm)

# Gasket & Pressure Plate Parameters
GASKET_T         = 0.004   # Gasket thickness (4 mm)
GASKET_W         = 0.012   # Gasket width (12 mm)
ISOLATOR_W       = 0.012   # Thermal break width (12 mm)
PRESSURE_PLATE_T = 0.006   # Clamping plate thickness (6 mm)
COVER_CAP_D      = 0.020   # Snap cover cap depth (20 mm)

# Structural Concrete Slab Parameters
SLAB_T           = 0.30    # Concrete slab thickness (300 mm)
SLAB_DEPTH       = 1.50    # Depth of floor slab extension inward (1.5 m)
SLAB_INSET       = 0.010   # Air clearance between slab edge and mullion back (10 mm)

# Slab Anchor Bracket Parameters
BRACKET_W        = 0.080   # Width of bracket flanking the mullion (80 mm)
BRACKET_L1       = 0.150   # Length of bracket leg on concrete slab (150 mm)
BRACKET_L2       = 0.120   # Length of bracket leg on mullion side (120 mm)
BRACKET_T        = 0.008   # Steel bracket thickness (8 mm)

CLEAR_BEFORE     = True

# =============================================================================
# SCALE PARAMETERS TO DOCUMENT UNITS
# =============================================================================
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

# =============================================================================
# MATERIALS & LAYERS
# =============================================================================
def add_mat(name, base_c4f, metallic, roughness, diffuse_rgb, transp=0.0, refl=0.0, shine=0.5, opacity=1.0, ior=1.5):
    existing = doc.Materials.Find(name, True)
    if existing >= 0:
        m = doc.Materials[existing]
    else:
        m = rdo.Material()
        m.Name = name
    try:
        m.ToPhysicallyBased()
        pb = m.PhysicallyBased
        pb.BaseColor = rdp.Color4f(*base_c4f)
        pb.Metallic = metallic
        pb.Roughness = roughness
        try: pb.Opacity = opacity
        except: pass
        try: pb.OpacityIOR = ior
        except: pass
    except: pass
    m.DiffuseColor = sd.Color.FromArgb(*diffuse_rgb)
    m.Transparency = transp
    m.Reflectivity = refl
    m.FresnelReflections = True
    m.Shine = int(shine * rdo.Material.MaxShine)
    if existing >= 0:
        doc.Materials.Modify(m, existing, True)
        return existing
    return doc.Materials.Add(m)

# Create/Get Materials
m_alu      = add_mat("AluAnodized", (0.05, 0.05, 0.06, 1.0), 0.95, 0.18, (35, 38, 46), refl=0.88, shine=0.75)
m_glass_ot = add_mat("GlassOuter",  (0.02, 0.08, 0.12, 1.0), 0.00, 0.01, (15, 68, 90), transp=0.88, refl=0.92, shine=0.98, opacity=0.12, ior=1.52)
m_glass_in = add_mat("GlassInner",  (0.95, 0.95, 0.95, 1.0), 0.00, 0.01, (220, 225, 220), transp=0.92, refl=0.90, shine=0.98, opacity=0.08, ior=1.52)
m_rubber   = add_mat("RubberEPDM",  (0.04, 0.04, 0.04, 1.0), 0.00, 0.82, (20, 20, 20), refl=0.05, shine=0.05)
m_thermal  = add_mat("ThermalBreakStrut", (0.08, 0.08, 0.08, 1.0), 0.00, 0.65, (30, 30, 30), refl=0.06, shine=0.08)
m_steel    = add_mat("GalvanizedSteel", (0.55, 0.55, 0.56, 1.0), 0.85, 0.38, (140, 140, 145), refl=0.55, shine=0.60)
m_concrete = add_mat("SlabConcrete", (0.33, 0.33, 0.31, 1.0), 0.00, 0.85, (120, 120, 115), refl=0.05, shine=0.02)
m_screw    = add_mat("BrightScrew", (0.75, 0.75, 0.75, 1.0), 0.95, 0.10, (190, 190, 195), refl=0.90, shine=0.85)
m_firestop = add_mat("FireStopWool", (0.70, 0.62, 0.38, 1.0), 0.00, 0.92, (180, 160, 100), refl=0.02, shine=0.01)

def get_layer(name, rgb):
    idx = doc.Layers.FindByFullPath(name, -1)
    if idx < 0:
        lyr = rdo.Layer()
        lyr.Name = name
        lyr.Color = sd.Color.FromArgb(*rgb)
        idx = doc.Layers.Add(lyr)
    else:
        doc.Layers[idx].Color = sd.Color.FromArgb(*rgb)
        if CLEAR_BEFORE:
            objs = doc.Objects.FindByLayer(name)
            if objs:
                for o in objs: doc.Objects.Delete(o, True)
    return idx

def make_attr(layer_idx, mat_idx):
    a = rdo.ObjectAttributes()
    a.LayerIndex = layer_idx
    a.MaterialIndex = mat_idx
    a.MaterialSource = rdo.ObjectMaterialSource.MaterialFromObject
    return a

# Sub-layers tree
l_mullion  = get_layer("Facade::Mullions",      (35, 38, 46))
l_transom  = get_layer("Facade::Transoms",      (50, 55, 65))
l_gl_out   = get_layer("Facade::Glazing::GlassOuter", (60, 140, 210))
l_gl_in    = get_layer("Facade::Glazing::GlassInner", (170, 210, 240))
l_spacer   = get_layer("Facade::Glazing::Spacer", (50, 50, 50))
l_sealant  = get_layer("Facade::Glazing::Sealant", (10, 10, 10))
l_gasket   = get_layer("Facade::Gaskets",       (20, 20, 20))
l_thermal  = get_layer("Facade::ThermalIsolator", (30, 30, 30))
l_press    = get_layer("Facade::PressurePlates", (100, 105, 115))
l_caps     = get_layer("Facade::CoverCaps",     (35, 38, 46))
l_fixings  = get_layer("Facade::Fixings",       (190, 190, 195))
l_bracket  = get_layer("Facade::SlabBrackets",  (120, 120, 125))
l_firestop = get_layer("Facade::FireSafing",    (180, 160, 100))
l_slabs    = get_layer("Structure::Slabs",      (140, 136, 126))

a_mullion  = make_attr(l_mullion, m_alu)
a_transom  = make_attr(l_transom, m_alu)
a_gl_out   = make_attr(l_gl_out,  m_glass_ot)
a_gl_in    = make_attr(l_gl_in,   m_glass_in)
a_spacer   = make_attr(l_spacer,  m_alu)
a_sealant  = make_attr(l_sealant, m_rubber)
a_gasket   = make_attr(l_gasket,  m_rubber)
a_thermal  = make_attr(l_thermal, m_thermal)
a_press    = make_attr(l_press,   m_alu)
a_caps     = make_attr(l_caps,    m_alu)
a_fixings  = make_attr(l_fixings, m_screw)
a_bracket  = make_attr(l_bracket, m_steel)
a_firestop = make_attr(l_firestop, m_firestop)
a_slabs    = make_attr(l_slabs,   m_concrete)

# =============================================================================
# PROFILE EXTRUSION HELPERS
# =============================================================================
def make_hollow_tube(plane, w, y_min, y_max, length):
    # Generates a solid bounding profile to minimize CAD computation overhead
    rect = rg.Rectangle3d(rg.Plane.WorldXY, rg.Interval(-w*0.5, w*0.5), rg.Interval(y_min, y_max))
    ext = rg.Extrusion.Create(rect.ToNurbsCurve(), length, True).ToBrep()
    if ext:
        xf = rg.Transform.PlaneToPlane(rg.Plane.WorldXY, plane)
        ext.Transform(xf)
        return ext
    return None

# 1. Grid coordinates
X_grid = [i * BAY_WIDTH for i in range(NUM_BAYS + 1)]

# Define transom elevations (Bottom, intermediate head/sill at slab levels, and top boundaries)
Z_grid = []
Z_grid.append(0.0) # Bottom boundary (Sill)
for f in range(1, NUM_FLOORS):
    fz = f * FLOOR_HEIGHT
    Z_grid.append(fz - 0.15 * S) # Head transom: 150mm below slab level
    Z_grid.append(fz + 0.85 * S) # Sill transom: 850mm above slab level
Z_grid.append(TOTAL_HEIGHT) # Top boundary (Head)

Z_grid = sorted(list(set(Z_grid)))


print("Generating detailed engineered curtain wall façade...")
n_mullions = 0
n_transoms = 0
n_glass = 0

# 2. Vertical Mullions (with structural central noses)
for x in X_grid:
    m_plane = rg.Plane(rg.Point3d(x, 0.0, 0.0), rg.Vector3d.XAxis, rg.Vector3d.YAxis)
    
    # Main structural chamber (Y = -GLASS_SETBACK + GASKET_T to y_mullion_back)
    y_front = -GLASS_SETBACK + GASKET_T
    y_back  = y_front + MULLION_D
    m_brep = make_hollow_tube(m_plane, MULLION_W, y_front, y_back, TOTAL_HEIGHT)
    if m_brep:
        doc.Objects.AddBrep(m_brep, a_mullion)
        n_mullions += 1
    
    # Central nose extrusion (Y = -GLASS_SETBACK - GLASS_INNER_T to -GLASS_SETBACK + GASKET_T)
    nose_w = 0.024 * S
    y_nose_min = -GLASS_SETBACK - GLASS_INNER_T
    y_nose_max = -GLASS_SETBACK + GASKET_T
    m_nose_brep = make_hollow_tube(m_plane, nose_w, y_nose_min, y_nose_max, TOTAL_HEIGHT)
    if m_nose_brep:
        doc.Objects.AddBrep(m_nose_brep, a_mullion)

# 3. Horizontal Transoms (placed at all Z_grid levels)
for k in range(len(Z_grid)):
    z = Z_grid[k]
        
    for i in range(NUM_BAYS):
        x_start = X_grid[i] + MULLION_W*0.5
        x_end   = X_grid[i+1] - MULLION_W*0.5
        length  = x_end - x_start
        if length <= 0: continue
        
        t_plane = rg.Plane(rg.Point3d(x_start, 0.0, z), -rg.Vector3d.ZAxis, rg.Vector3d.YAxis)
        
        # Main transom profile
        y_front = -GLASS_SETBACK + GASKET_T
        y_back  = y_front + TRANSOM_D
        t_brep = make_hollow_tube(t_plane, TRANSOM_W, y_front, y_back, length)
        if t_brep:
            doc.Objects.AddBrep(t_brep, a_transom)
            n_transoms += 1
            
        # Central nose extrusion
        nose_w = 0.024 * S
        y_nose_min = -GLASS_SETBACK - GLASS_INNER_T
        y_nose_max = -GLASS_SETBACK + GASKET_T
        t_nose_brep = make_hollow_tube(t_plane, nose_w, y_nose_min, y_nose_max, length)
        if t_nose_brep:
            doc.Objects.AddBrep(t_nose_brep, a_transom)


# 4. Concrete Floor Slabs & Perimeter Fire Safing
for f in range(1, NUM_FLOORS):
    z_floor = f * FLOOR_HEIGHT
    y_mullion_back = -GLASS_SETBACK + GASKET_T + MULLION_D
    slab_edge_y = y_mullion_back + SLAB_INSET
    
    # Floor slab
    slab = rg.Box(
        rg.Plane.WorldXY,
        rg.Interval(0.0, NUM_BAYS * BAY_WIDTH),
        rg.Interval(slab_edge_y, slab_edge_y + SLAB_DEPTH),
        rg.Interval(z_floor - SLAB_T, z_floor)
    ).ToBrep()
    if slab:
        doc.Objects.AddBrep(slab, a_slabs)
        
    # Perimeter Fire Stop (Mineral wool filling the joint)
    firestop_wool = rg.Box(
        rg.Plane.WorldXY,
        rg.Interval(0.0, NUM_BAYS * BAY_WIDTH),
        rg.Interval(y_mullion_back, slab_edge_y),
        rg.Interval(z_floor - SLAB_T, z_floor)
    ).ToBrep()
    if firestop_wool:
        doc.Objects.AddBrep(firestop_wool, a_firestop)
        
    # Galvanized Smoke Cover Sheet (2mm sheet overlapping the concrete slab by 50mm)
    smoke_sheet = rg.Box(
        rg.Plane.WorldXY,
        rg.Interval(0.0, NUM_BAYS * BAY_WIDTH),
        rg.Interval(y_mullion_back, slab_edge_y + 0.050*S),
        rg.Interval(z_floor, z_floor + 0.002*S)
    ).ToBrep()
    if smoke_sheet:
        doc.Objects.AddBrep(smoke_sheet, a_bracket)

# 5. Slab Anchor Brackets (flanking the mullions inside the spandrel zone, clearing transoms)
for f in range(1, NUM_FLOORS):
    z_floor = f * FLOOR_HEIGHT
    y_mullion_back = -GLASS_SETBACK + GASKET_T + MULLION_D
    slab_edge_y = y_mullion_back + SLAB_INSET
    for x in X_grid:
        # Left flanking bracket legs (attached to slab and side of mullion)
        leg1_l = rg.Box(rg.Plane.WorldXY, rg.Interval(x - MULLION_W*0.5 - BRACKET_T, x - MULLION_W*0.5), rg.Interval(slab_edge_y, slab_edge_y + BRACKET_L1), rg.Interval(z_floor, z_floor + BRACKET_T)).ToBrep()
        leg2_l = rg.Box(rg.Plane.WorldXY, rg.Interval(x - MULLION_W*0.5 - BRACKET_T, x - MULLION_W*0.5), rg.Interval(y_mullion_back - BRACKET_W, slab_edge_y), rg.Interval(z_floor, z_floor + BRACKET_L2)).ToBrep()
        if leg1_l: doc.Objects.AddBrep(leg1_l, a_bracket)
        if leg2_l: doc.Objects.AddBrep(leg2_l, a_bracket)

        # Right flanking bracket legs (attached to slab and side of mullion)
        leg1_r = rg.Box(rg.Plane.WorldXY, rg.Interval(x + MULLION_W*0.5, x + MULLION_W*0.5 + BRACKET_T), rg.Interval(slab_edge_y, slab_edge_y + BRACKET_L1), rg.Interval(z_floor, z_floor + BRACKET_T)).ToBrep()
        leg2_r = rg.Box(rg.Plane.WorldXY, rg.Interval(x + MULLION_W*0.5, x + MULLION_W*0.5 + BRACKET_T), rg.Interval(y_mullion_back - BRACKET_W, slab_edge_y), rg.Interval(z_floor, z_floor + BRACKET_L2)).ToBrep()
        if leg1_r: doc.Objects.AddBrep(leg1_r, a_bracket)
        if leg2_r: doc.Objects.AddBrep(leg2_r, a_bracket)

# 6. EPDM Gaskets, Thermal Breaks, Pressure Plates, Cover Caps, and Fixings
# Centered on Vertical Mullions
g_w_m = MULLION_W * 0.5 - GLASS_REVEAL  # Dynamic gasket width matching mullion shoulders

for x in X_grid:
    # Inner gaskets sized strictly to glass reveal & dynamic gasket width (Y = -GLASS_SETBACK to -GLASS_SETBACK + GASKET_T)
    g_l = rg.Box(rg.Plane.WorldXY, rg.Interval(x - GLASS_REVEAL - g_w_m, x - GLASS_REVEAL), rg.Interval(-GLASS_SETBACK, -GLASS_SETBACK + GASKET_T), rg.Interval(0.0, TOTAL_HEIGHT)).ToBrep()
    g_r = rg.Box(rg.Plane.WorldXY, rg.Interval(x + GLASS_REVEAL, x + GLASS_REVEAL + g_w_m), rg.Interval(-GLASS_SETBACK, -GLASS_SETBACK + GASKET_T), rg.Interval(0.0, TOTAL_HEIGHT)).ToBrep()
    if g_l: doc.Objects.AddBrep(g_l, a_gasket)
    if g_r: doc.Objects.AddBrep(g_r, a_gasket)

    # Outer gaskets flanking the thermal break under the pressure plate
    gy_min = -GLASS_SETBACK - GLASS_INNER_T - GLASS_GAP_T - GLASS_OUTER_T - GASKET_T
    gy_max = gy_min + GASKET_T
    og_l = rg.Box(rg.Plane.WorldXY, rg.Interval(x - GLASS_REVEAL - g_w_m, x - GLASS_REVEAL), rg.Interval(gy_min, gy_max), rg.Interval(0.0, TOTAL_HEIGHT)).ToBrep()
    og_r = rg.Box(rg.Plane.WorldXY, rg.Interval(x + GLASS_REVEAL, x + GLASS_REVEAL + g_w_m), rg.Interval(gy_min, gy_max), rg.Interval(0.0, TOTAL_HEIGHT)).ToBrep()
    if og_l: doc.Objects.AddBrep(og_l, a_gasket)
    if og_r: doc.Objects.AddBrep(og_r, a_gasket)


    # Thermal Break Isolator (filling the central gap between glass edges)
    iy_min = -GLASS_SETBACK - GLASS_INNER_T - GLASS_GAP_T - GLASS_OUTER_T
    iy_max = -GLASS_SETBACK - GLASS_INNER_T
    ti = rg.Box(rg.Plane.WorldXY, rg.Interval(x - ISOLATOR_W*0.5, x + ISOLATOR_W*0.5), rg.Interval(iy_min, iy_max), rg.Interval(0.0, TOTAL_HEIGHT)).ToBrep()
    if ti: doc.Objects.AddBrep(ti, a_thermal)

    # Pressure Plate (clamping the glazing units)
    py_min = -GLASS_SETBACK - GLASS_INNER_T - GLASS_GAP_T - GLASS_OUTER_T - GASKET_T - PRESSURE_PLATE_T
    py_max = py_min + PRESSURE_PLATE_T
    pp = rg.Box(rg.Plane.WorldXY, rg.Interval(x - MULLION_W*0.5, x + MULLION_W*0.5), rg.Interval(py_min, py_max), rg.Interval(0.0, TOTAL_HEIGHT)).ToBrep()
    if pp: doc.Objects.AddBrep(pp, a_press)

    # Snap-on Cover Cap
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
        doc.Objects.AddBrep(ext, a_caps)

    # Screws (90mm long to pass through pressure plate, thermal break, and anchor into structural mullion nose)
    screw_spacing = 0.35 * S
    screw_rad     = 0.004 * S
    screw_len     = 0.090 * S
    cur_z = 0.1 * S
    while cur_z < TOTAL_HEIGHT:
        cyl_plane = rg.Plane(rg.Point3d(x, py_min, cur_z), rg.Vector3d.YAxis)
        cyl = rg.Cylinder(rg.Circle(cyl_plane, screw_rad), screw_len).ToBrep(True, True)
        if cyl: doc.Objects.AddBrep(cyl, a_fixings)
        cur_z += screw_spacing

# Centered on Horizontal Transoms
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

        # Top Gaskets (seal the glass above the transom) - skip if this is the top boundary
        if k < len(Z_grid) - 1:
            g_t = rg.Box(rg.Plane.WorldXY, rg.Interval(x_start, x_end), rg.Interval(-GLASS_SETBACK, -GLASS_SETBACK + GASKET_T), rg.Interval(z + GLASS_REVEAL, z + GLASS_REVEAL + g_w_t)).ToBrep()
            if g_t: doc.Objects.AddBrep(g_t, a_gasket)
            
            og_t = rg.Box(rg.Plane.WorldXY, rg.Interval(x_start, x_end), rg.Interval(gy_min, gy_max), rg.Interval(z + GLASS_REVEAL, z + GLASS_REVEAL + g_w_t)).ToBrep()
            if og_t: doc.Objects.AddBrep(og_t, a_gasket)

        # Bottom Gaskets (seal the glass below the transom) - skip if this is the bottom boundary
        if k > 0:
            g_b = rg.Box(rg.Plane.WorldXY, rg.Interval(x_start, x_end), rg.Interval(-GLASS_SETBACK, -GLASS_SETBACK + GASKET_T), rg.Interval(z - GLASS_REVEAL - g_w_t, z - GLASS_REVEAL)).ToBrep()
            if g_b: doc.Objects.AddBrep(g_b, a_gasket)
            
            og_b = rg.Box(rg.Plane.WorldXY, rg.Interval(x_start, x_end), rg.Interval(gy_min, gy_max), rg.Interval(z - GLASS_REVEAL - g_w_t, z - GLASS_REVEAL)).ToBrep()
            if og_b: doc.Objects.AddBrep(og_b, a_gasket)


        # Thermal break
        iy_min = -GLASS_SETBACK - GLASS_INNER_T - GLASS_GAP_T - GLASS_OUTER_T
        iy_max = -GLASS_SETBACK - GLASS_INNER_T
        ti = rg.Box(rg.Plane.WorldXY, rg.Interval(x_start, x_end), rg.Interval(iy_min, iy_max), rg.Interval(z - ISOLATOR_W*0.5, z + ISOLATOR_W*0.5)).ToBrep()
        if ti: doc.Objects.AddBrep(ti, a_thermal)

        # Pressure plate
        py_min = -GLASS_SETBACK - GLASS_INNER_T - GLASS_GAP_T - GLASS_OUTER_T - GASKET_T - PRESSURE_PLATE_T
        py_max = py_min + PRESSURE_PLATE_T
        pp = rg.Box(rg.Plane.WorldXY, rg.Interval(x_start, x_end), rg.Interval(py_min, py_max), rg.Interval(z - TRANSOM_W*0.5, z + TRANSOM_W*0.5)).ToBrep()
        if pp: doc.Objects.AddBrep(pp, a_press)

        # Snap-on cover cap
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
            doc.Objects.AddBrep(ext, a_caps)

        # Screws (90mm long, penetrating horizontal transom nose)
        screw_spacing = 0.35 * S
        screw_rad     = 0.004 * S
        screw_len     = 0.090 * S
        cur_x = x_start + 0.1 * S
        while cur_x < x_end:
            cyl_plane = rg.Plane(rg.Point3d(cur_x, py_min, z), rg.Vector3d.YAxis)
            cyl = rg.Cylinder(rg.Circle(cyl_plane, screw_rad), screw_len).ToBrep(True, True)
            if cyl: doc.Objects.AddBrep(cyl, a_fixings)
            cur_x += screw_spacing


# 7. Insulated Glass Units (IGUs) - Glass, Spacers, and Sealants
for k in range(len(Z_grid) - 1):
    z_start = Z_grid[k]
    z_end   = Z_grid[k+1]
    
    for i in range(NUM_BAYS):
        x_start = X_grid[i]
        x_end   = X_grid[i+1]
        
        # Glazing coordinates with reveal offsets
        x1 = x_start + GLASS_REVEAL
        x2 = x_end - GLASS_REVEAL
        z1 = z_start + GLASS_REVEAL
        z2 = z_end - GLASS_REVEAL
        
        if x2 - x1 <= 0 or z2 - z1 <= 0: continue
        
        # Inner Glass Pane (Y = -GLASS_SETBACK - GLASS_INNER_T to -GLASS_SETBACK)
        y_in_min = -GLASS_SETBACK - GLASS_INNER_T
        y_in_max = -GLASS_SETBACK
        glass_in = rg.Box(rg.Plane.WorldXY, rg.Interval(x1, x2), rg.Interval(y_in_min, y_in_max), rg.Interval(z1, z2)).ToBrep()
        if glass_in: doc.Objects.AddBrep(glass_in, a_gl_in)

        # Outer Glass Pane (Y = -GLASS_SETBACK - GLASS_INNER_T - GLASS_GAP_T - GLASS_OUTER_T to y_ot_max)
        y_ot_min = -GLASS_SETBACK - GLASS_INNER_T - GLASS_GAP_T - GLASS_OUTER_T
        y_ot_max = y_ot_min + GLASS_OUTER_T
        glass_ot = rg.Box(rg.Plane.WorldXY, rg.Interval(x1, x2), rg.Interval(y_ot_min, y_ot_max), rg.Interval(z1, z2)).ToBrep()
        if glass_ot: doc.Objects.AddBrep(glass_ot, a_gl_out)

        # Spacer Frame (4 individual boxes flanking inner edges)
        sp_offset = 0.015 * S
        sp_width  = 0.012 * S
        sx1 = x1 + sp_offset
        sx2 = x2 - sp_offset
        sz1 = z1 + sp_offset
        sz2 = z2 - sp_offset
        sy_min = y_in_max - GLASS_GAP_T # Wait, y_in_max is -GLASS_SETBACK, but spacer is between inner and outer glass panes.
        # Outer face of inner glass is at y_in_min (-GLASS_SETBACK - GLASS_INNER_T).
        # Inner face of outer glass is at y_ot_max (-GLASS_SETBACK - GLASS_INNER_T - GLASS_GAP_T).
        # So the spacer goes from Y = -GLASS_SETBACK - GLASS_INNER_T - GLASS_GAP_T to Y = -GLASS_SETBACK - GLASS_INNER_T.
        sy_min_spacer = -GLASS_SETBACK - GLASS_INNER_T - GLASS_GAP_T
        sy_max_spacer = -GLASS_SETBACK - GLASS_INNER_T
        
        if sx2 - sx1 > 0 and sz2 - sz1 > 0:
            sp_l = rg.Box(rg.Plane.WorldXY, rg.Interval(sx1, sx1 + sp_width), rg.Interval(sy_min_spacer, sy_max_spacer), rg.Interval(sz1, sz2)).ToBrep()
            sp_r = rg.Box(rg.Plane.WorldXY, rg.Interval(sx2 - sp_width, sx2), rg.Interval(sy_min_spacer, sy_max_spacer), rg.Interval(sz1, sz2)).ToBrep()
            sp_b = rg.Box(rg.Plane.WorldXY, rg.Interval(sx1 + sp_width, sx2 - sp_width), rg.Interval(sy_min_spacer, sy_max_spacer), rg.Interval(sz1, sz1 + sp_width)).ToBrep()
            sp_t = rg.Box(rg.Plane.WorldXY, rg.Interval(sx1 + sp_width, sx2 - sp_width), rg.Interval(sy_min_spacer, sy_max_spacer), rg.Interval(sz2 - sp_width, sz2)).ToBrep()
            for sp in (sp_l, sp_r, sp_b, sp_t):
                if sp: doc.Objects.AddBrep(sp, a_spacer)

            # Secondary Sealant Pocket (4 outer sealant bars filling outer cavity)
            se_l = rg.Box(rg.Plane.WorldXY, rg.Interval(x1, sx1), rg.Interval(sy_min_spacer, sy_max_spacer), rg.Interval(z1, z2)).ToBrep()
            se_r = rg.Box(rg.Plane.WorldXY, rg.Interval(sx2, x2), rg.Interval(sy_min_spacer, sy_max_spacer), rg.Interval(z1, z2)).ToBrep()
            se_b = rg.Box(rg.Plane.WorldXY, rg.Interval(sx1, sx2), rg.Interval(sy_min_spacer, sy_max_spacer), rg.Interval(z1, sz1)).ToBrep()
            se_t = rg.Box(rg.Plane.WorldXY, rg.Interval(sx1, sx2), rg.Interval(sy_min_spacer, sy_max_spacer), rg.Interval(sz2, z2)).ToBrep()
            for se in (se_l, se_r, se_b, se_t):
                if se: doc.Objects.AddBrep(se, a_sealant)
        
        n_glass += 1

doc.Views.Redraw()

print("")
print("=" * 60)
print("STICK CURTAIN WALL SYSTEM - Refined Engineered Edition")
print("  Vertical Mullions   : %d  (continuous profiles + central noses)" % n_mullions)
print("  Horizontal Transoms : %d  (butted profiles + central noses)" % n_transoms)
print("  Glazed Panels (IGUs): %d  (double panes + spacers + sealants)" % n_glass)
print("=" * 60)
print("Visualisation Tip: Set viewport display mode to Rendered / Arctic")
print("============================================================")
