import json
import uuid

# Define slider parameters
SLIDER_SPECS = [
    # A. Grid & Bays
    ("num_bays",         1,   10,    3,   "Integer", "IntegerSlider"),
    ("num_floors",       1,    5,    2,   "Integer", "IntegerSlider"),
    ("bay_width",     0.8,  3.0,  1.50,   "Double",  "DoubleSlider"),
    ("floor_height",  2.5,  5.0,  3.50,   "Double",  "DoubleSlider"),
    # B. Profiles
    ("mullion_w",     0.03, 0.10, 0.060,   "Double",  "DoubleSlider"),
    ("mullion_d",     0.08, 0.25, 0.150,   "Double",  "DoubleSlider"),
    ("mullion_t",     0.002,0.008,0.003,   "Double",  "DoubleSlider"),
    ("transom_w",     0.03, 0.10, 0.060,   "Double",  "DoubleSlider"),
    ("transom_d",     0.06, 0.20, 0.120,   "Double",  "DoubleSlider"),
    ("transom_t",     0.002,0.008,0.003,   "Double",  "DoubleSlider"),
    # C. Glazing
    ("glass_outer_t", 0.004, 0.015, 0.006,  "Double",  "DoubleSlider"),
    ("glass_inner_t", 0.004, 0.015, 0.006,  "Double",  "DoubleSlider"),
    ("glass_gap_t",   0.008, 0.024, 0.016,  "Double",  "DoubleSlider"),
    ("glass_reveal",  0.005, 0.025, 0.015,  "Double",  "DoubleSlider"),
    ("glass_setback", 0.020, 0.080, 0.040,  "Double",  "DoubleSlider"),
    # D. Seals/Plates
    ("gasket_t",         0.002, 0.010, 0.004, "Double",  "DoubleSlider"),
    ("gasket_w",         0.005, 0.020, 0.012, "Double",  "DoubleSlider"),
    ("isolator_w",       0.006, 0.024, 0.012, "Double",  "DoubleSlider"),
    ("pressure_plate_t", 0.004, 0.015, 0.006, "Double",  "DoubleSlider"),
    ("cover_cap_d",      0.010, 0.050, 0.020, "Double",  "DoubleSlider"),
    # E. Slab/Anchors
    ("slab_t",        0.15,  0.50,  0.30,   "Double",  "DoubleSlider"),
    ("slab_depth",    0.50,  2.50,  1.50,   "Double",  "DoubleSlider"),
    ("slab_inset",    0.005, 0.050, 0.010,   "Double",  "DoubleSlider"),
    ("bracket_w",     0.040, 0.150, 0.080,   "Double",  "DoubleSlider"),
    ("bracket_l1",    0.080, 0.300, 0.150,   "Double",  "DoubleSlider"),
    ("bracket_l2",    0.060, 0.250, 0.120,   "Double",  "DoubleSlider"),
    ("bracket_t",     0.004, 0.016, 0.008,   "Double",  "DoubleSlider"),
]

# Slider group mappings
GROUPS_METADATA = [
    {
        "key": "A",
        "title": "A: GRID & BAYS",
        "color": "#2D508737", # transparent blue
        "sliders": ["num_bays", "num_floors", "bay_width", "floor_height"]
    },
    {
        "key": "B",
        "title": "B: STRUCTURAL PROFILES",
        "color": "#87502D37", # transparent purple
        "sliders": ["mullion_w", "mullion_d", "mullion_t", "transom_w", "transom_d", "transom_t"]
    },
    {
        "key": "C",
        "title": "C: INSULATED GLAZING (IGU)",
        "color": "#2D875037", # transparent green
        "sliders": ["glass_outer_t", "glass_inner_t", "glass_gap_t", "glass_reveal", "glass_setback"]
    },
    {
        "key": "D",
        "title": "D: GASKETS & PRESSURE PLATES",
        "color": "#87782837", # transparent orange
        "sliders": ["gasket_t", "gasket_w", "isolator_w", "pressure_plate_t", "cover_cap_d"]
    },
    {
        "key": "E",
        "title": "E: SLAB & ANCHOR BRACKETS",
        "color": "#50505037", # transparent grey
        "sliders": ["slab_t", "slab_depth", "slab_inset", "bracket_w", "bracket_l1", "bracket_l2", "bracket_t"]
    }
]

# Track Y starting offsets for each group
GROUP_Y_STARTS = {
    "A": 0.0,
    "B": 280.0,
    "C": 640.0,
    "D": 1000.0,
    "E": 1360.0
}

# Generate unique IDs for all elements
graph_uuid = str(uuid.uuid4())
python_node_id = str(uuid.uuid4()).replace("-", "")
python_out_port_id = str(uuid.uuid4()).replace("-", "")
code_block_extract_id = str(uuid.uuid4()).replace("-", "")
code_block_colors_id = str(uuid.uuid4()).replace("-", "")

# Build Slider lists and connections
nodes = []
node_views = []
connectors = []
inputs = []

# Port mappings for Python script inputs
py_inputs = []

# Map slider outports to connect to the Performance Calculator
slider_out_ports = {}

# Group nodes collection for annotations
group_nodes = {
    "A": [],
    "B": [],
    "C": [],
    "D": [],
    "E": []
}

# Generate Sliders using grouped Y positions
for idx, (name, mn, mx, val, num_type, concrete_type) in enumerate(SLIDER_SPECS):
    slider_id = str(uuid.uuid4()).replace("-", "")
    out_port_id = str(uuid.uuid4()).replace("-", "")
    slider_out_ports[name] = out_port_id
    
    # Identify group key
    gkey = "A"
    for g in GROUPS_METADATA:
        if name in g["sliders"]:
            gkey = g["key"]
            break
            
    # Append to group nodes
    group_nodes[gkey].append(slider_id)
    
    # Calculate grid position inside group
    g_sliders = next(g["sliders"] for g in GROUPS_METADATA if g["key"] == gkey)
    local_idx = g_sliders.index(name)
    col = local_idx % 2
    row = local_idx // 2
    
    pos_x = -750.0 + col * 230.0
    pos_y = GROUP_Y_STARTS[gkey] + row * 90.0
    
    # Input definition for the root "Inputs" block
    inputs.append({
        "Id": slider_id,
        "Name": name.upper().replace("_", " "),
        "Type": "number",
        "Type2": "number",
        "Value": str(val),
        "MaximumValue": float(mx),
        "MinimumValue": float(mn),
        "StepValue": 1.0 if num_type == "Integer" else 0.001 if name.startswith("bracket") or name.startswith("glass") or name.startswith("mullion") or name.startswith("transom") or name.startswith("gasket") or name.startswith("isolator") or name.startswith("pressure") or name.startswith("cover") else 0.1,
        "NumberType": num_type,
        "Description": "Produces numeric values" if num_type == "Double" else "Produces integer values"
    })
    
    # Node definition (Python booleans used here, serialized dynamically to lowercase in JSON)
    concrete_full_type = "CoreNodeModels.Input.IntegerSlider, CoreNodeModels" if concrete_type == "IntegerSlider" else "CoreNodeModels.Input.DoubleSlider, CoreNodeModels"
    nodes.append({
        "ConcreteType": concrete_full_type,
        "NumberType": num_type,
        "MaximumValue": int(mx) if num_type == "Integer" else float(mx),
        "MinimumValue": int(mn) if num_type == "Integer" else float(mn),
        "StepValue": 1 if num_type == "Integer" else 0.001 if name.startswith("bracket") or name.startswith("glass") or name.startswith("mullion") or name.startswith("transom") or name.startswith("gasket") or name.startswith("isolator") or name.startswith("pressure") or name.startswith("cover") else 0.1,
        "Id": slider_id,
        "NodeType": "NumberInputNode",
        "Inputs": [],
        "Outputs": [
            {
                "Id": out_port_id,
                "Name": "",
                "Description": name.upper().replace("_", " "),
                "UsingDefaultValue": False,
                "Level": 2,
                "UseLevels": False,
                "KeepListStructure": False
            }
        ],
        "Replication": "Disabled",
        "Description": "Produces numeric values" if num_type == "Double" else "Produces integer values",
        "InputValue": int(val) if num_type == "Integer" else float(val)
    })
    
    # Node view position
    node_views.append({
        "Id": slider_id,
        "Name": name.upper().replace("_", " "),
        "IsSetAsInput": True,
        "IsSetAsOutput": False,
        "Excluded": False,
        "ShowGeometry": False,
        "X": pos_x,
        "Y": pos_y
    })
    
    # Python input port definition
    in_port_id = str(uuid.uuid4()).replace("-", "")
    py_inputs.append({
        "Id": in_port_id,
        "Name": "in_{0}".format(idx),
        "Description": "Input #{0}".format(idx),
        "UsingDefaultValue": False,
        "Level": 2,
        "UseLevels": False,
        "KeepListStructure": False
    })
    
    # Connect slider output to python input
    connectors.append({
        "Start": out_port_id,
        "End": in_port_id,
        "Id": str(uuid.uuid4()).replace("-", ""),
        "IsHidden": "False"
    })

# Embedded python geometry code for Dynamo
DYNAMO_PY_CODE = r'''import clr
clr.AddReference('ProtoGeometry')
from Autodesk.DesignScript.Geometry import *
import math

# Map inputs from IN list
num_bays = int(IN[0]) if IN[0] is not None else 3
num_floors = int(IN[1]) if IN[1] is not None else 2
bay_width = float(IN[2]) if IN[2] is not None else 1.50
floor_height = float(IN[3]) if IN[3] is not None else 3.50

mullion_w = float(IN[4]) if IN[4] is not None else 0.060
mullion_d = float(IN[5]) if IN[5] is not None else 0.150
mullion_t = float(IN[6]) if IN[6] is not None else 0.003

transom_w = float(IN[7]) if IN[7] is not None else 0.060
transom_d = float(IN[8]) if IN[8] is not None else 0.120
transom_t = float(IN[9]) if IN[9] is not None else 0.003

glass_outer_t = float(IN[10]) if IN[10] is not None else 0.006
glass_inner_t = float(IN[11]) if IN[11] is not None else 0.006
glass_gap_t = float(IN[12]) if IN[12] is not None else 0.016
glass_reveal = float(IN[13]) if IN[13] is not None else 0.015
glass_setback = float(IN[14]) if IN[14] is not None else 0.040

gasket_t = float(IN[15]) if IN[15] is not None else 0.004
gasket_w = float(IN[16]) if IN[16] is not None else 0.012
isolator_w = float(IN[17]) if IN[17] is not None else 0.012
pressure_plate_t = float(IN[18]) if IN[18] is not None else 0.006
cover_cap_d = float(IN[19]) if IN[19] is not None else 0.020

slab_t = float(IN[20]) if IN[20] is not None else 0.30
slab_depth = float(IN[21]) if IN[21] is not None else 1.50
slab_inset = float(IN[22]) if IN[22] is not None else 0.010

bracket_w = float(IN[23]) if IN[23] is not None else 0.080
bracket_l1 = float(IN[24]) if IN[24] is not None else 0.150
bracket_l2 = float(IN[25]) if IN[25] is not None else 0.120
bracket_t = float(IN[26]) if IN[26] is not None else 0.008

TOTAL_HEIGHT = num_floors * floor_height

def make_box(x_min, x_max, y_min, y_max, z_min, z_max):
    try:
        pt1 = Point.ByCoordinates(x_min, y_min, z_min)
        pt2 = Point.ByCoordinates(x_max, y_max, z_max)
        return Cuboid.ByCorners(pt1, pt2)
    except:
        return None

# Coords grid
X_grid = [i * bay_width for i in range(num_bays + 1)]

# Define transom elevations
Z_grid = []
Z_grid.append(0.0) # Bottom boundary
for f in range(1, num_floors):
    fz = f * floor_height
    Z_grid.append(fz - 0.15) # Head transom
    Z_grid.append(fz + 0.85) # Sill transom
Z_grid.append(TOTAL_HEIGHT) # Top boundary
Z_grid = sorted(list(set(Z_grid)))

m_list = []
t_list = []
go_list = []
gi_list = []
g_list = []
b_list = []
s_list = []
fs_list = []
fx_list = []

# Mullions with Noses
for x in X_grid:
    # Main chamber
    y_front = -glass_setback + gasket_t
    y_back  = y_front + mullion_d
    m_brep = make_box(x - mullion_w*0.5, x + mullion_w*0.5, y_front, y_back, 0.0, TOTAL_HEIGHT)
    if m_brep: m_list.append(m_brep)
    
    # Nose
    nose_w = 0.024
    y_nose_min = -glass_setback - glass_inner_t
    y_nose_max = -glass_setback + gasket_t
    m_nose_brep = make_box(x - nose_w*0.5, x + nose_w*0.5, y_nose_min, y_nose_max, 0.0, TOTAL_HEIGHT)
    if m_nose_brep: m_list.append(m_nose_brep)

# Transoms with Noses (placed at all Z_grid levels)
for k in range(len(Z_grid)):
    z = Z_grid[k]

    for i in range(num_bays):
        x_start = X_grid[i] + mullion_w*0.5
        x_end   = X_grid[i+1] - mullion_w*0.5
        length  = x_end - x_start
        if length <= 0: continue
        
        # Main transom profile
        y_front = -glass_setback + gasket_t
        y_back  = y_front + transom_d
        t_brep = make_box(x_start, x_end, y_front, y_back, z - transom_w*0.5, z + transom_w*0.5)
        if t_brep: t_list.append(t_brep)
        
        # Central nose
        nose_w = 0.024
        y_nose_min = -glass_setback - glass_inner_t
        y_nose_max = -glass_setback + gasket_t
        t_nose_brep = make_box(x_start, x_end, y_nose_min, y_nose_max, z - transom_w*0.5, z + transom_w*0.5)
        if t_nose_brep: t_list.append(t_nose_brep)

# Floor slabs and Fire Stop containment (intermediate slab levels only)
for f in range(1, num_floors):
    z_floor = f * floor_height
    y_mullion_back = -glass_setback + gasket_t + mullion_d
    slab_edge_y = y_mullion_back + slab_inset
    
    # Slab
    slab = make_box(0.0, num_bays * bay_width, slab_edge_y, slab_edge_y + slab_depth, z_floor - slab_t, z_floor)
    if slab: s_list.append(slab)
        
    # Fire wool
    firestop_wool = make_box(0.0, num_bays * bay_width, y_mullion_back, slab_edge_y, z_floor - slab_t, z_floor)
    if firestop_wool: fs_list.append(firestop_wool)
        
    # Galvanized sheet
    smoke_sheet = make_box(0.0, num_bays * bay_width, y_mullion_back, slab_edge_y + 0.050, z_floor, z_floor + 0.002)
    if smoke_sheet: b_list.append(smoke_sheet)

# Slab brackets (intermediate levels only)
for f in range(1, num_floors):
    z_floor = f * floor_height
    y_mullion_back = -glass_setback + gasket_t + mullion_d
    slab_edge_y = y_mullion_back + slab_inset
    for x in X_grid:
        leg1_l = make_box(x - mullion_w*0.5 - bracket_t, x - mullion_w*0.5, slab_edge_y, slab_edge_y + bracket_l1, z_floor, z_floor + bracket_t)
        leg2_l = make_box(x - mullion_w*0.5 - bracket_t, x - mullion_w*0.5, y_mullion_back - bracket_w, slab_edge_y, z_floor, z_floor + bracket_l2)
        if leg1_l: b_list.append(leg1_l)
        if leg2_l: b_list.append(leg2_l)
        leg1_r = make_box(x + mullion_w*0.5, x + mullion_w*0.5 + bracket_t, slab_edge_y, slab_edge_y + bracket_l1, z_floor, z_floor + bracket_t)
        leg2_r = make_box(x + mullion_w*0.5, x + mullion_w*0.5 + bracket_t, y_mullion_back - bracket_w, slab_edge_y, z_floor, z_floor + bracket_l2)
        if leg1_r: b_list.append(leg1_r)
        if leg2_r: b_list.append(leg2_r)

# Gaskets and pressure plates on Mullions
g_w_m = mullion_w * 0.5 - glass_reveal
for x in X_grid:
    g_l = make_box(x - glass_reveal - g_w_m, x - glass_reveal, -glass_setback, -glass_setback + gasket_t, 0.0, TOTAL_HEIGHT)
    g_r = make_box(x + glass_reveal, x + glass_reveal + g_w_m, -glass_setback, -glass_setback + gasket_t, 0.0, TOTAL_HEIGHT)
    if g_l: g_list.append(g_l)
    if g_r: g_list.append(g_r)
    
    gy_min = -glass_setback - glass_inner_t - glass_gap_t - glass_outer_t - gasket_t
    gy_max = gy_min + gasket_t
    og_l = make_box(x - glass_reveal - g_w_m, x - glass_reveal, gy_min, gy_max, 0.0, TOTAL_HEIGHT)
    og_r = make_box(x + glass_reveal, x + glass_reveal + g_w_m, gy_min, gy_max, 0.0, TOTAL_HEIGHT)
    if og_l: g_list.append(og_l)
    if og_r: g_list.append(og_r)
    
    iy_min = -glass_setback - glass_inner_t - glass_gap_t - glass_outer_t
    iy_max = -glass_setback - glass_inner_t
    ti = make_box(x - isolator_w*0.5, x + isolator_w*0.5, iy_min, iy_max, 0.0, TOTAL_HEIGHT)
    if ti: t_list.append(ti)
    
    py_min = -glass_setback - glass_inner_t - glass_gap_t - glass_outer_t - gasket_t - pressure_plate_t
    py_max = py_min + pressure_plate_t
    pp = make_box(x - mullion_w*0.5, x + mullion_w*0.5, py_min, py_max, 0.0, TOTAL_HEIGHT)
    if pp: t_list.append(pp)

    # Detailed Snap-on Cover Cap (chamfered polygon)
    try:
        pts_c = [
            Point.ByCoordinates(x - mullion_w*0.5, py_min, 0.0),
            Point.ByCoordinates(x - mullion_w*0.5, py_min - cover_cap_d + 0.006, 0.0),
            Point.ByCoordinates(x - mullion_w*0.5 + 0.006, py_min - cover_cap_d, 0.0),
            Point.ByCoordinates(x + mullion_w*0.5 - 0.006, py_min - cover_cap_d, 0.0),
            Point.ByCoordinates(x + mullion_w*0.5, py_min - cover_cap_d + 0.006, 0.0),
            Point.ByCoordinates(x + mullion_w*0.5, py_min, 0.0),
            Point.ByCoordinates(x - mullion_w*0.5, py_min, 0.0)
        ]
        cap = PolyCurve.ByPoints(pts_c).ExtrudeAsSolid(Vector.ByCoordinates(0, 0, 1), TOTAL_HEIGHT)
        if cap: t_list.append(cap)
    except:
        # Fallback to simple box representation
        cap = make_box(x - mullion_w*0.5, x + mullion_w*0.5, py_min - cover_cap_d, py_min, 0.0, TOTAL_HEIGHT)
        if cap: t_list.append(cap)

    # Screws as cylinders
    screw_spacing = 0.35; screw_rad = 0.004; screw_len = 0.090
    cur_z = 0.1
    while cur_z < TOTAL_HEIGHT:
        pt1 = Point.ByCoordinates(x, py_min, cur_z)
        pt2 = Point.ByCoordinates(x, py_min + screw_len, cur_z)
        cyl = Cylinder.ByPointsRadius(pt1, pt2, screw_rad)
        if cyl: fx_list.append(cyl)
        cur_z += screw_spacing

# Gaskets and accessories on Transoms
g_w_t = transom_w * 0.5 - glass_reveal
for k in range(len(Z_grid)):
    z = Z_grid[k]

    for i in range(num_bays):
        x_start = X_grid[i] + mullion_w*0.5
        x_end   = X_grid[i+1] - mullion_w*0.5
        length  = x_end - x_start
        if length <= 0: continue
        
        gy_min = -glass_setback - glass_inner_t - glass_gap_t - glass_outer_t - gasket_t
        gy_max = gy_min + gasket_t

        # Top Gaskets - skip if top boundary
        if k < len(Z_grid) - 1:
            g_t = make_box(x_start, x_end, -glass_setback, -glass_setback + gasket_t, z + glass_reveal, z + glass_reveal + g_w_t)
            if g_t: g_list.append(g_t)
            
            og_t = make_box(x_start, x_end, gy_min, gy_max, z + glass_reveal, z + glass_reveal + g_w_t)
            if og_t: g_list.append(og_t)

        # Bottom Gaskets - skip if bottom boundary
        if k > 0:
            g_b = make_box(x_start, x_end, -glass_setback, -glass_setback + gasket_t, z - glass_reveal - g_w_t, z - glass_reveal)
            if g_b: g_list.append(g_b)
            
            og_b = make_box(x_start, x_end, gy_min, gy_max, z - glass_reveal - g_w_t, z - glass_reveal)
            if og_b: g_list.append(og_b)
        
        iy_min = -glass_setback - glass_inner_t - glass_gap_t - glass_outer_t
        iy_max = -glass_setback - glass_inner_t
        ti = make_box(x_start, x_end, iy_min, iy_max, z - isolator_w*0.5, z + isolator_w*0.5)
        if ti: t_list.append(ti)
        
        py_min = -glass_setback - glass_inner_t - glass_gap_t - glass_outer_t - gasket_t - pressure_plate_t
        py_max = py_min + pressure_plate_t
        pp = make_box(x_start, x_end, py_min, py_max, z - transom_w*0.5, z + transom_w*0.5)
        if pp: t_list.append(pp)

        # Snap-on Transom Cover Cap (chamfered polygon in YZ plane extruded along X)
        try:
            pts_c = [
                Point.ByCoordinates(x_start, py_min, z + transom_w*0.5),
                Point.ByCoordinates(x_start, py_min - cover_cap_d + 0.006, z + transom_w*0.5),
                Point.ByCoordinates(x_start, py_min - cover_cap_d, z + transom_w*0.5 - 0.006),
                Point.ByCoordinates(x_start, py_min - cover_cap_d, z - transom_w*0.5 + 0.006),
                Point.ByCoordinates(x_start, py_min - cover_cap_d + 0.006, z - transom_w*0.5),
                Point.ByCoordinates(x_start, py_min, z - transom_w*0.5),
                Point.ByCoordinates(x_start, py_min, z + transom_w*0.5)
            ]
            cap = PolyCurve.ByPoints(pts_c).ExtrudeAsSolid(Vector.ByCoordinates(1, 0, 0), length)
            if cap: t_list.append(cap)
        except:
            # Fallback to simple box representation
            cap = make_box(x_start, x_end, py_min - cover_cap_d, py_min, z - transom_w*0.5, z + transom_w*0.5)
            if cap: t_list.append(cap)

        # Screws
        screw_spacing = 0.35; screw_rad = 0.004; screw_len = 0.090
        cur_x = x_start + 0.1
        while cur_x < x_end:
            pt1 = Point.ByCoordinates(cur_x, py_min, z)
            pt2 = Point.ByCoordinates(cur_x, py_min + screw_len, z)
            cyl = Cylinder.ByPointsRadius(pt1, pt2, screw_rad)
            if cyl: fx_list.append(cyl)
            cur_x += screw_spacing

# IGUs
for k in range(len(Z_grid) - 1):
    z_start = Z_grid[k]
    z_end   = Z_grid[k+1]
    for i in range(num_bays):
        x_start = X_grid[i]; x_end = X_grid[i+1]
        x1 = x_start + glass_reveal; x2 = x_end - glass_reveal
        z1 = z_start + glass_reveal; z2 = z_end - glass_reveal
        if x2 - x1 <= 0 or z2 - z1 <= 0: continue
        
        # Inner Glass
        y_in_min = -glass_setback - glass_inner_t
        y_in_max = -glass_setback
        glass_in = make_box(x1, x2, y_in_min, y_in_max, z1, z2)
        if glass_in: gi_list.append(glass_in)

        # Outer Glass
        y_ot_min = -glass_setback - glass_inner_t - glass_gap_t - glass_outer_t
        y_ot_max = y_ot_min + glass_outer_t
        glass_ot = make_box(x1, x2, y_ot_min, y_ot_max, z1, z2)
        if glass_ot: go_list.append(glass_ot)

        # Spacers and sealant
        sp_offset = 0.015; sp_width = 0.012
        sx1 = x1 + sp_offset; sx2 = x2 - sp_offset
        sz1 = z1 + sp_offset; sz2 = z2 - sp_offset
        sy_min_spacer = -glass_setback - glass_inner_t - glass_gap_t
        sy_max_spacer = -glass_setback - glass_inner_t
        if sx2 - sx1 > 0 and sz2 - sz1 > 0:
            sp_l = make_box(sx1, sx1 + sp_width, sy_min_spacer, sy_max_spacer, sz1, sz2)
            sp_r = make_box(sx2 - sp_width, sx2, sy_min_spacer, sy_max_spacer, sz1, sz2)
            sp_b = make_box(sx1 + sp_width, sx2 - sp_width, sy_min_spacer, sy_max_spacer, sz1, sz1 + sp_width)
            sp_t = make_box(sx1 + sp_width, sx2 - sp_width, sy_min_spacer, sy_max_spacer, sz2 - sp_width, sz2)
            for sp in (sp_l, sp_r, sp_b, sp_t):
                if sp: t_list.append(sp)

            se_l = make_box(x1, sx1, sy_min_spacer, sy_max_spacer, z1, z2)
            se_r = make_box(sx2, x2, sy_min_spacer, sy_max_spacer, z1, z2)
            se_b = make_box(sx1, sx2, sy_min_spacer, sy_max_spacer, z1, sz1)
            se_t = make_box(sx1, sx2, sy_min_spacer, sy_max_spacer, sz2, z2)
            for se in (se_l, se_r, se_b, se_t):
                if se: t_list.append(se)

OUT = [m_list, t_list, go_list, gi_list, g_list, b_list, s_list, fs_list, fx_list]
'''

# 2. Add Python Node
nodes.append({
    "ConcreteType": "PythonNodeModels.PythonNode, PythonNodeModels",
    "Code": DYNAMO_PY_CODE,
    "Engine": "PythonNet3",
    "VariableInputPorts": True,
    "Id": python_node_id,
    "NodeType": "PythonScriptNode",
    "Inputs": py_inputs,
    "Outputs": [
        {
            "Id": python_out_port_id,
            "Name": "OUT",
            "Description": "Engine Output",
            "UsingDefaultValue": False,
            "Level": 2,
            "UseLevels": False,
            "KeepListStructure": False
        }
    ],
    "Replication": "Disabled",
    "Description": "Runs the detailed parametric facade script."
})

node_views.append({
    "Id": python_node_id,
    "Name": "KINETIC CURTAIN WALL ENGINE",
    "IsSetAsInput": False,
    "IsSetAsOutput": False,
    "Excluded": False,
    "ShowGeometry": False,
    "X": 150.0,
    "Y": 350.0
})

# 3. Code Block: EXTRACT CHANNELS
extract_code = """
mullions = data[0];
transoms = data[1];
glass_outer = data[2];
glass_inner = data[3];
gaskets = data[4];
brackets = data[5];
slabs = data[6];
firestops = data[7];
fixings = data[8];
"""

extract_out_ports = []
extract_outputs = []
channel_names = ["mullions", "transoms", "glass_outer", "glass_inner", "gaskets", "brackets", "slabs", "firestops", "fixings"]
for idx, cname in enumerate(channel_names):
    port_id = str(uuid.uuid4()).replace("-", "")
    extract_out_ports.append(port_id)
    extract_outputs.append({
        "Id": port_id,
        "Name": cname,
        "Description": cname,
        "UsingDefaultValue": False,
        "Level": 2,
        "UseLevels": False,
        "KeepListStructure": False
    })

nodes.append({
    "ConcreteType": "Dynamo.Graph.Nodes.CodeBlockNodeModel, DynamoCore",
    "Id": code_block_extract_id,
    "NodeType": "CodeBlockNode",
    "Inputs": [
        {
            "Id": str(uuid.uuid4()).replace("-", ""),
            "Name": "data",
            "Description": "data",
            "UsingDefaultValue": False,
            "Level": 2,
            "UseLevels": False,
            "KeepListStructure": False
        }
    ],
    "Outputs": extract_outputs,
    "Replication": "Disabled",
    "Description": "Extracts the geometry channels.",
    "Code": extract_code.strip()
})

node_views.append({
    "Id": code_block_extract_id,
    "Name": "EXTRACT GEOMETRY CHANNELS",
    "IsSetAsInput": False,
    "IsSetAsOutput": False,
    "Excluded": False,
    "ShowGeometry": False,
    "X": 550.0,
    "Y": 100.0
})

# Wire Python OUT -> Code Block "data" input
connectors.append({
    "Start": python_out_port_id,
    "End": nodes[-1]["Inputs"][0]["Id"],
    "Id": str(uuid.uuid4()).replace("-", ""),
    "IsHidden": "False"
})

# 4. Code Block: COLOR SWATCHES
colors_code = """
c_mullion = DSCore.Color.ByARGB(255, 35, 38, 46);
c_transom = DSCore.Color.ByARGB(255, 50, 55, 65);
c_glass_ot = DSCore.Color.ByARGB(120, 60, 140, 210);
c_glass_in = DSCore.Color.ByARGB(60, 170, 210, 240);
c_gaskets = DSCore.Color.ByARGB(255, 20, 20, 20);
c_brackets = DSCore.Color.ByARGB(255, 120, 120, 125);
c_slabs = DSCore.Color.ByARGB(255, 160, 155, 145);
c_firestops = DSCore.Color.ByARGB(255, 180, 160, 100);
c_fixings = DSCore.Color.ByARGB(255, 220, 220, 225);
"""

colors_out_ports = []
colors_outputs = []
color_names = ["c_mullion", "c_transom", "c_glass_ot", "c_glass_in", "c_gaskets", "c_brackets", "c_slabs", "c_firestops", "c_fixings"]
for idx, cname in enumerate(color_names):
    port_id = str(uuid.uuid4()).replace("-", "")
    colors_out_ports.append(port_id)
    colors_outputs.append({
        "Id": port_id,
        "Name": cname,
        "Description": cname,
        "UsingDefaultValue": False,
        "Level": 2,
        "UseLevels": False,
        "KeepListStructure": False
    })

nodes.append({
    "ConcreteType": "Dynamo.Graph.Nodes.CodeBlockNodeModel, DynamoCore",
    "Id": code_block_colors_id,
    "NodeType": "CodeBlockNode",
    "Inputs": [],
    "Outputs": colors_outputs,
    "Replication": "Disabled",
    "Description": "Defines colors for visual representation.",
    "Code": colors_code.strip()
})

node_views.append({
    "Id": code_block_colors_id,
    "Name": "MATERIAL COLOR SWATCHES",
    "IsSetAsInput": False,
    "IsSetAsOutput": False,
    "Excluded": False,
    "ShowGeometry": False,
    "X": 550.0,
    "Y": 600.0
})

# 5. RENDER PIPELINE: GeometryColor Nodes
render_node_ids = []
for idx, cname in enumerate(channel_names):
    render_id = str(uuid.uuid4()).replace("-", "")
    render_node_ids.append(render_id)
    geom_in_id = str(uuid.uuid4()).replace("-", "")
    color_in_id = str(uuid.uuid4()).replace("-", "")
    render_out_id = str(uuid.uuid4()).replace("-", "")
    
    nodes.append({
        "ConcreteType": "Dynamo.Graph.Nodes.ZeroTouch.DSFunction, DynamoCore",
        "Id": render_id,
        "NodeType": "FunctionNode",
        "Inputs": [
            {
                "Id": geom_in_id,
                "Name": "geometry",
                "Description": "The geometry to apply color to.",
                "UsingDefaultValue": False,
                "Level": 2,
                "UseLevels": False,
                "KeepListStructure": False
            },
            {
                "Id": color_in_id,
                "Name": "color",
                "Description": "The display color.",
                "UsingDefaultValue": False,
                "Level": 2,
                "UseLevels": False,
                "KeepListStructure": False
            }
        ],
        "Outputs": [
            {
                "Id": render_out_id,
                "Name": "GeometryColor",
                "Description": "Display object.",
                "UsingDefaultValue": False,
                "Level": 2,
                "UseLevels": False,
                "KeepListStructure": False
            }
        ],
        "FunctionSignature": "Modifiers.GeometryColor.ByGeometryColor@Autodesk.DesignScript.Geometry.Geometry,DSCore.Color",
        "Replication": "Auto",
        "Description": "Display geometry using a color."
    })
    
    node_views.append({
        "Id": render_id,
        "Name": "RENDER: " + cname.upper(),
        "IsSetAsInput": False,
        "IsSetAsOutput": False,
        "Excluded": False,
        "ShowGeometry": True,
        "X": 1050.0,
        "Y": float(idx * 160)
    })
    
    # Connect Extract CodeBlock channel output -> GeometryColor input geometry
    connectors.append({
        "Start": extract_out_ports[idx],
        "End": geom_in_id,
        "Id": str(uuid.uuid4()).replace("-", ""),
        "IsHidden": "False"
    })
    
    # Connect Color CodeBlock swatch output -> GeometryColor input color
    connectors.append({
        "Start": colors_out_ports[idx],
        "End": color_in_id,
        "Id": str(uuid.uuid4()).replace("-", ""),
        "IsHidden": "False"
    })

# 6. PERFORMANCE CALCULATOR: Native CodeBlock & Watch Nodes
calc_node_id = str(uuid.uuid4()).replace("-", "")
calc_inputs = []
calc_input_names = ["num_bays", "bay_width", "num_floors", "floor_height"]
calc_input_guids = {}
for iname in calc_input_names:
    p_guid = str(uuid.uuid4()).replace("-", "")
    calc_input_guids[iname] = p_guid
    calc_inputs.append({
        "Id": p_guid,
        "Name": iname,
        "Description": iname,
        "UsingDefaultValue": False,
        "Level": 2,
        "UseLevels": False,
        "KeepListStructure": False
    })

calc_outputs = []
calc_output_names = ["area", "cost"]
calc_output_guids = {}
for oname in calc_output_names:
    p_guid = str(uuid.uuid4()).replace("-", "")
    calc_output_guids[oname] = p_guid
    calc_outputs.append({
        "Id": p_guid,
        "Name": oname,
        "Description": oname,
        "UsingDefaultValue": False,
        "Level": 2,
        "UseLevels": False,
        "KeepListStructure": False
    })

nodes.append({
    "ConcreteType": "Dynamo.Graph.Nodes.CodeBlockNodeModel, DynamoCore",
    "Id": calc_node_id,
    "NodeType": "CodeBlockNode",
    "Inputs": calc_inputs,
    "Outputs": calc_outputs,
    "Replication": "Disabled",
    "Description": "Calculates facade area and cost dynamically.",
    "Code": "area = (num_bays * bay_width) * (num_floors * floor_height);\ncost = area * 650.0;"
})

# Connect sliders to calculator inputs
for iname in calc_input_names:
    connectors.append({
        "Start": slider_out_ports[iname],
        "End": calc_input_guids[iname],
        "Id": str(uuid.uuid4()).replace("-", ""),
        "IsHidden": "False"
    })

# Watch nodes
watch_area_id = str(uuid.uuid4()).replace("-", "")
watch_area_in = str(uuid.uuid4()).replace("-", "")
watch_area_out = str(uuid.uuid4()).replace("-", "")
nodes.append({
    "ConcreteType": "CoreNodeModels.Watch, CoreNodeModels",
    "Id": watch_area_id,
    "NodeType": "ExtensionNode",
    "Inputs": [
        {
            "Id": watch_area_in,
            "Name": "",
            "Description": "Incoming data.",
            "UsingDefaultValue": False,
            "Level": 2,
            "UseLevels": False,
            "KeepListStructure": False
        }
    ],
    "Outputs": [
        {
            "Id": watch_area_out,
            "Name": "",
            "Description": "Watch contents.",
            "UsingDefaultValue": False,
            "Level": 2,
            "UseLevels": False,
            "KeepListStructure": False
        }
    ],
    "Replication": "Disabled",
    "Description": "Visualize the output of node."
})

watch_cost_id = str(uuid.uuid4()).replace("-", "")
watch_cost_in = str(uuid.uuid4()).replace("-", "")
watch_cost_out = str(uuid.uuid4()).replace("-", "")
nodes.append({
    "ConcreteType": "CoreNodeModels.Watch, CoreNodeModels",
    "Id": watch_cost_id,
    "NodeType": "ExtensionNode",
    "Inputs": [
        {
            "Id": watch_cost_in,
            "Name": "",
            "Description": "Incoming data.",
            "UsingDefaultValue": False,
            "Level": 2,
            "UseLevels": False,
            "KeepListStructure": False
        }
    ],
    "Outputs": [
        {
            "Id": watch_cost_out,
            "Name": "",
            "Description": "Watch contents.",
            "UsingDefaultValue": False,
            "Level": 2,
            "UseLevels": False,
            "KeepListStructure": False
        }
    ],
    "Replication": "Disabled",
    "Description": "Visualize the output of node."
})

# Wire calculator outputs to Watch nodes
connectors.append({
    "Start": calc_output_guids["area"],
    "End": watch_area_in,
    "Id": str(uuid.uuid4()).replace("-", ""),
    "IsHidden": "False"
})
connectors.append({
    "Start": calc_output_guids["cost"],
    "End": watch_cost_in,
    "Id": str(uuid.uuid4()).replace("-", ""),
    "IsHidden": "False"
})

node_views.append({
    "Id": calc_node_id,
    "Name": "PERFORMANCE CALCULATOR",
    "IsSetAsInput": False,
    "IsSetAsOutput": False,
    "Excluded": False,
    "ShowGeometry": False,
    "X": -750.0,
    "Y": 1720.0
})
node_views.append({
    "Id": watch_area_id,
    "Name": "Watch: TOTAL AREA (m²)",
    "IsSetAsInput": False,
    "IsSetAsOutput": False,
    "Excluded": False,
    "ShowGeometry": False,
    "X": -400.0,
    "Y": 1700.0
})
node_views.append({
    "Id": watch_cost_id,
    "Name": "Watch: ESTIMATED COST ($)",
    "IsSetAsInput": False,
    "IsSetAsOutput": False,
    "Excluded": False,
    "ShowGeometry": False,
    "X": -400.0,
    "Y": 1820.0
})

# 7. VISUAL GROUP ANNOTATIONS
annotations = []
# Slider groups
for g in GROUPS_METADATA:
    gkey = g["key"]
    gtitle = g["title"]
    gcolor = g["color"]
    nodes_in_group = group_nodes[gkey]
    if not nodes_in_group: continue
    
    rows = (len(g["sliders"]) + 1) // 2
    y_start = GROUP_Y_STARTS[gkey]
    height = rows * 90.0 + 60.0
    
    annotations.append({
        "Id": str(uuid.uuid4()).replace("-", ""),
        "Title": gtitle,
        "Nodes": nodes_in_group,
        "Left": -780.0,
        "Top": y_start - 50.0,
        "Width": 490.0,
        "Height": height,
        "Background": gcolor,
        "FontSize": 14.0,
        "InitialTop": y_start - 50.0,
        "InitialLeft": -780.0
    })

# Engine node group
annotations.append({
    "Id": str(uuid.uuid4()).replace("-", ""),
    "Title": "KINETIC CURTAIN WALL ENGINE",
    "Nodes": [python_node_id],
    "Left": 100.0,
    "Top": 300.0,
    "Width": 320.0,
    "Height": 250.0,
    "Background": "#FF333333",
    "FontSize": 14.0,
    "InitialTop": 300.0,
    "InitialLeft": 100.0
})

# Extract channels node group
annotations.append({
    "Id": str(uuid.uuid4()).replace("-", ""),
    "Title": "EXTRACT GEOMETRY CHANNELS",
    "Nodes": [code_block_extract_id],
    "Left": 500.0,
    "Top": 50.0,
    "Width": 380.0,
    "Height": 450.0,
    "Background": "#FF505050",
    "FontSize": 14.0,
    "InitialTop": 50.0,
    "InitialLeft": 500.0
})

# Material Color Swatches node group
annotations.append({
    "Id": str(uuid.uuid4()).replace("-", ""),
    "Title": "MATERIAL COLOR SWATCHES",
    "Nodes": [code_block_colors_id],
    "Left": 500.0,
    "Top": 550.0,
    "Width": 380.0,
    "Height": 450.0,
    "Background": "#FF505050",
    "FontSize": 14.0,
    "InitialTop": 550.0,
    "InitialLeft": 500.0
})

# Render pipeline node group
annotations.append({
    "Id": str(uuid.uuid4()).replace("-", ""),
    "Title": "RENDER PIPELINE",
    "Nodes": render_node_ids,
    "Left": 1000.0,
    "Top": -50.0,
    "Width": 350.0,
    "Height": 9 * 160.0 + 80.0,
    "Background": "#FF4B6C3F",
    "FontSize": 14.0,
    "InitialTop": -50.0,
    "InitialLeft": 1000.0
})

# Performance Calculator node group
annotations.append({
    "Id": str(uuid.uuid4()).replace("-", ""),
    "Title": "PERFORMANCE CALCULATOR (NATIVE GRAPH)",
    "Nodes": [calc_node_id, watch_area_id, watch_cost_id],
    "Left": -780.0,
    "Top": 1670.0,
    "Width": 620.0,
    "Height": 260.0,
    "Background": "#FFA36423",
    "FontSize": 14.0,
    "InitialTop": 1670.0,
    "InitialLeft": -780.0
})

# Formulate complete DYN JSON representation
dyn_data = {
    "Uuid": graph_uuid,
    "IsCustomNode": False,
    "Description": "Detailed Parametric Curtain Wall Façade System. Generated dynamically to match Rhino Grasshopper workflow.",
    "Name": "ParametricCurtainWallFacade",
    "ElementResolver": {
        "ResolutionMap": {
            "DSCore.Color": {
                "Key": "DSCore.Color",
                "Value": "DSCoreNodes.dll"
            }
        }
    },
    "Inputs": inputs,
    "Outputs": [],
    "Nodes": nodes,
    "Connectors": connectors,
    "Dependencies": [],
    "NodeLibraryDependencies": [],
    "EnableLegacyPolyCurveBehavior": False,
    "Thumbnail": "",
    "GraphDocumentationURL": None,
    "ExtensionWorkspaceData": [],
    "Author": "AEC Computational Designer",
    "Linting": {
        "activeLinter": "None",
        "activeLinterId": "7b75fb44-43fd-4631-a878-29f4d5d8399a",
        "warningCount": 0,
        "errorCount": 0
    },
    "Bindings": [],
    "View": {
        "Dynamo": {
            "ScaleFactor": 1.0,
            "HasRunWithoutCrash": True,
            "IsVisibleInDynamoLibrary": True,
            "Version": "4.1.0.4676",
            "RunType": "Automatic",
            "RunPeriod": "1000"
        },
        "Camera": {
            "Name": "_Background Preview",
            "EyeX": 10.0,
            "EyeY": 15.0,
            "EyeZ": -25.0,
            "LookX": 0.0,
            "LookY": -5.0,
            "LookZ": 20.0,
            "UpX": 0.0,
            "UpY": 1.0,
            "UpZ": 0.0
        },
        "ConnectorPins": [],
        "NodeViews": node_views,
        "Annotations": annotations,
        "X": 450.0,
        "Y": 150.0,
        "Zoom": 0.45
    }
}

# Save DYN to scratch
scratch_path = r"c:\Users\sammo\OneDrive\Documenten\GitHub\Autodesk-Revit-MCP-Server\scratch\facade_system.dyn"
with open(scratch_path, "w", encoding="utf-8") as f:
    json.dump(dyn_data, f, indent=2)

# Copy to user Downloads folder for easy load
downloads_path = r"C:\Users\sammo\Downloads\facade_system.dyn"
try:
    with open(downloads_path, "w", encoding="utf-8") as f:
        json.dump(dyn_data, f, indent=2)
    print("Saved Dynamo definition successfully to scratch and Downloads folder!")
except Exception as e:
    print("Warning: failed to save to Downloads: {0}".format(e))
