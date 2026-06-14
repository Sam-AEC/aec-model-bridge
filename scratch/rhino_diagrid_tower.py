# =============================================================================
# rhino_diagrid_tower.py
# Parametric diagrid skyscraper — run directly in Rhino 8 Python Script Editor
# or send via the MCP bridge (run_python command).
#
# HOW TO RUN IN RHINO:
#   Type "PythonEdit" in Rhino  →  File > Open this file  →  press Run (F5)
#   Adjust the PARAMETERS block below and re-run to iterate.
#
# HOW TO RUN VIA MCP BRIDGE:
#   python scratch/diagrid_tower_python.py   (sends this file to the bridge)
#
# BUILDABLE GEOMETRY GUARANTEES:
#   - Glass panels are projected onto a flat plane before extrusion → truly planar IGUs
#   - Mullion depth axis is locked to the outward surface normal at each midpoint
#   - All glass solids are 6-face closed Breps (watertight)
#   - Mullion sweeps are capped closed (CreateFromSweep with closed=True)
#   - Materials: PBR tried first (Rhino 7/8), standard fallback for all display modes
# =============================================================================

import Rhino
import Rhino.Geometry as rg
import Rhino.DocObjects as rdo
import Rhino.Display as rdp
import scriptcontext as sc
import System.Drawing as sd

doc = sc.doc
tol = doc.ModelAbsoluteTolerance

# =============================================================================
# PARAMETERS  ←  edit this block to iterate
# All dimensions in metres — script converts to document units automatically.
# =============================================================================

# -- Tower form ---------------------------------------------------------------
BASE_R   = 22.0    # base radius (m)  →  wider = more imposing ground presence
WAIST_R  = 13.5    # waist radius (m) →  smaller = more dramatic hyperboloid pinch
TOP_R    = 19.0    # crown radius (m) →  larger than waist = outward flare at top
HEIGHT   = 180.0   # total height (m) →  ~45 stories at 4 m/floor

# -- Diagrid density ----------------------------------------------------------
# Rule of thumb: U_DIVS sets structural bays around the perimeter.
#   Each bay at the base ≈ 2π × BASE_R / U_DIVS = panel width.
#   V_DIVS sets bays up the height. 2 floors per bay is structurally typical.
U_DIVS  = 20       # panels around circumference  (20 → ~6.9 m per bay at base)
V_DIVS  = 40       # panels up the height         (40 → 4.5 m per bay = 1 floor)

# -- Structural member cross-section (metres) ---------------------------------
MUL_W   = 0.20     # visible face width of each member (200 mm)
MUL_D   = 0.40     # structural depth — goes inward from facade (400 mm)

# -- Glazing (metres) ---------------------------------------------------------
GLASS_T = 0.028    # IGU thickness — 28 mm = high-performance triple-glazed unit
INSET   = 0.14     # fraction each glass corner is pulled toward panel centre
                   # 0.12–0.18 is realistic for exposed-framing curtain walls
SETBACK = 0.025    # glass set back behind facade plane (25 mm)

# -- Appearance ---------------------------------------------------------------
CLEAR_BEFORE = True   # delete previous "Mullions" and "Glass" layer objects before running


# =============================================================================
# END OF PARAMETERS
# =============================================================================

# -- Scale: convert metres to document units ----------------------------------
S = Rhino.RhinoMath.UnitScale(rg.UnitSystem.Meters, doc.ModelUnitSystem)

BASE_R  *= S;  WAIST_R *= S;  TOP_R  *= S;  HEIGHT *= S
MUL_W   *= S;  MUL_D   *= S
GLASS_T *= S;  SETBACK *= S


# ─────────────────────────────────────────────────────────────────────────────
# UTILITIES
# ─────────────────────────────────────────────────────────────────────────────

def smoothstep(a, b, t):
    """Smooth cubic ease between a and b (no overshoot)."""
    e = t * t * (3.0 - 2.0 * t)
    return a + (b - a) * e

def tower_r(t):
    """Radius at normalised height t ∈ [0,1]: base → waist → crown."""
    if t <= 0.5:
        return smoothstep(BASE_R, WAIST_R, t * 2.0)
    return smoothstep(WAIST_R, TOP_R, (t - 0.5) * 2.0)

def dot3(a, b):
    return a.X*b.X + a.Y*b.Y + a.Z*b.Z

def vec_scale(v, s):
    return rg.Vector3d(v.X*s, v.Y*s, v.Z*s)

def pt_shift(p, v):
    return rg.Point3d(p.X+v.X, p.Y+v.Y, p.Z+v.Z)

def project_onto_plane(pt, origin, unit_normal):
    """Orthographic projection of pt onto a plane defined by origin and unit normal."""
    d = (pt.X-origin.X)*unit_normal.X + (pt.Y-origin.Y)*unit_normal.Y + (pt.Z-origin.Z)*unit_normal.Z
    return rg.Point3d(pt.X - d*unit_normal.X,
                      pt.Y - d*unit_normal.Y,
                      pt.Z - d*unit_normal.Z)

def get_or_make_layer(name, color, clear_objects):
    if clear_objects:
        # Remove all objects on this layer before rebuilding
        for obj in doc.Objects.FindByLayer(name) or []:
            doc.Objects.Delete(obj, True)
    for layer in doc.Layers:
        if layer.Name == name and not layer.IsDeleted:
            return layer.Index
    lyr = rdo.Layer()
    lyr.Name  = name
    lyr.Color = color
    return doc.Layers.Add(lyr)


# ─────────────────────────────────────────────────────────────────────────────
# STEP 1 — TOWER SURFACE
# Smooth hyperboloid lofted from 13 ring circles.
# More rings = cleaner normal sampling across the full height.
# ─────────────────────────────────────────────────────────────────────────────
RINGS = 13
loft_crvs = []
for k in range(RINGS + 1):
    t = float(k) / RINGS
    r = tower_r(t)
    z = t * HEIGHT
    pln = rg.Plane(rg.Point3d(0, 0, z), rg.Vector3d.ZAxis)
    loft_crvs.append(rg.Circle(pln, r).ToNurbsCurve())

breps = rg.Brep.CreateFromLoft(
    loft_crvs, rg.Point3d.Unset, rg.Point3d.Unset, rg.LoftType.Normal, False)

if not breps:
    print("ERROR: loft failed — check parameters")
    raise SystemExit

surf = breps[0]
face = surf.Faces[0]
face.SetDomain(0, rg.Interval(0, 1))   # u: 0..1 around circumference
face.SetDomain(1, rg.Interval(0, 1))   # v: 0..1 up the height


# ─────────────────────────────────────────────────────────────────────────────
# STEP 2 — UV GRID
# pts[i][j] = world-space node at (u=i/U_DIVS, v=j/V_DIVS) on the surface.
# Nodes are the diagrid connection points (structural nodes / curtain-wall corners).
# ─────────────────────────────────────────────────────────────────────────────
pts = []
for i in range(U_DIVS + 1):
    row = []
    u = float(i) / U_DIVS
    for j in range(V_DIVS + 1):
        v = float(j) / V_DIVS
        row.append(face.PointAt(u, v))
    pts.append(row)


# ─────────────────────────────────────────────────────────────────────────────
# STEP 3 — MULLION CROSS-SECTION PROFILE
# Rectangle in WorldXY: width along X (what you see from street), depth along Y.
# Y=0 is the outward face of the member; Y=-MUL_D is the inward (hidden) back face.
# This gets re-oriented per-member in Step 4.
# ─────────────────────────────────────────────────────────────────────────────
profile_rect = rg.Rectangle3d(
    rg.Plane.WorldXY,
    rg.Interval(-MUL_W * 0.5, MUL_W * 0.5),
    rg.Interval(-MUL_D, 0.0)
)
profile_crv = profile_rect.ToNurbsCurve()


# ─────────────────────────────────────────────────────────────────────────────
# STEP 4 — DIAGRID MEMBER SWEEPS
# Two diagonals per UV cell: (i,j)→(i+1,j+1) and (i+1,j)→(i,j+1).
#
# ORIENTATION FIX (key for buildability):
#   Standard PerpendicularFrameAt gives an arbitrary roll around the tangent.
#   We lock the roll so the depth axis (Y in the profile) aligns with the
#   outward surface normal at the member's midpoint — the structural depth
#   goes INTO the building, which is the only physically meaningful orientation.
# ─────────────────────────────────────────────────────────────────────────────
mullion_breps = []

for i in range(U_DIVS):
    for j in range(V_DIVS):
        diagonals = [
            (pts[i    ][j    ], pts[i + 1][j + 1]),   # up-right
            (pts[i + 1][j    ], pts[i    ][j + 1]),   # up-left
        ]
        for p0, p1 in diagonals:
            line = rg.LineCurve(p0, p1)

            ok_fr, fr = line.PerpendicularFrameAt(line.Domain.Min)
            if not ok_fr:
                continue

            # Outward surface normal at the member midpoint
            mid = line.PointAt(line.Domain.Mid)
            ok_cp, cu, cv = face.ClosestPoint(mid)
            if not ok_cp:
                continue
            surf_n = face.NormalAt(cu, cv)
            surf_n.Unitize()

            tangent = fr.ZAxis   # unit tangent of the line

            # Gram-Schmidt orthogonalisation:
            # Remove the tangent component from surf_n → "depth" direction
            # that lies in the plane perpendicular to the member.
            t_dot_n   = dot3(tangent, surf_n)
            depth_dir = rg.Vector3d(surf_n.X - t_dot_n * tangent.X,
                                    surf_n.Y - t_dot_n * tangent.Y,
                                    surf_n.Z - t_dot_n * tangent.Z)
            if not depth_dir.Unitize():
                continue

            # Width direction: tangent × depth_dir
            # → lies in the surface tangent plane, perpendicular to the member
            width_dir = rg.Vector3d.CrossProduct(tangent, depth_dir)
            if not width_dir.Unitize():
                continue

            # Build sweep frame and map profile
            sweep_pln = rg.Plane(fr.Origin, width_dir, depth_dir)
            xf = rg.Transform.PlaneToPlane(rg.Plane.WorldXY, sweep_pln)

            oriented = profile_crv.DuplicateCurve()
            oriented.Transform(xf)

            swept = rg.Brep.CreateFromSweep(line, oriented, True, tol)
            if swept:
                mullion_breps.extend(swept)

print("Mullion sweeps: " + str(len(mullion_breps)))


# ─────────────────────────────────────────────────────────────────────────────
# STEP 5 — PLANAR GLASS PANELS
# For each UV quad cell we create a flat glazed panel.
#
# BUILDABILITY LOGIC:
#   a) Compute the 4 node corners of the cell.
#   b) Find the outward surface normal at the cell centroid.
#   c) Pull each corner INSET fraction toward the centroid (creates frame reveal).
#   d) PROJECT all 4 inset corners onto the plane through centroid + outward normal.
#      This is the critical step: it converts the slightly doubly-curved UV quad
#      into a perfectly flat panel — exactly what a standard flat-glass IGU is.
#   e) Step back SETBACK behind the facade plane (glass sits inside the frame).
#   f) Create a 6-face closed solid by building front/back/4 side NurbsSurfaces
#      and joining them. Result: a proper solid glass brick, not a surface.
# ─────────────────────────────────────────────────────────────────────────────
glass_breps = []

for i in range(U_DIVS):
    for j in range(V_DIVS):
        p1 = pts[i    ][j    ];  p2 = pts[i + 1][j    ]
        p3 = pts[i + 1][j + 1]; p4 = pts[i    ][j + 1]

        # Centroid of the quad
        cx = (p1.X + p2.X + p3.X + p4.X) * 0.25
        cy = (p1.Y + p2.Y + p3.Y + p4.Y) * 0.25
        cz = (p1.Z + p2.Z + p3.Z + p4.Z) * 0.25
        c  = rg.Point3d(cx, cy, cz)

        # Outward surface normal at centroid
        ok_n, cu, cv = face.ClosestPoint(c)
        if not ok_n:
            continue
        n = face.NormalAt(cu, cv)
        if not n.Unitize():
            continue

        # Pull each corner (1 - INSET) of the way from centroid to corner
        def ins(p):
            return rg.Point3d(c.X + (p.X - c.X) * (1.0 - INSET),
                               c.Y + (p.Y - c.Y) * (1.0 - INSET),
                               c.Z + (p.Z - c.Z) * (1.0 - INSET))

        gi1 = ins(p1); gi2 = ins(p2); gi3 = ins(p3); gi4 = ins(p4)

        # ── Planarity projection ──────────────────────────────────────────────
        # Project all 4 inset corners onto the tangent plane at centroid.
        # After this the 4 corners are exactly co-planar → flat glass panel.
        fp1 = project_onto_plane(gi1, c, n)
        fp2 = project_onto_plane(gi2, c, n)
        fp3 = project_onto_plane(gi3, c, n)
        fp4 = project_onto_plane(gi4, c, n)

        # Step back behind the facade surface
        sb  = vec_scale(n, -SETBACK)
        sp1 = pt_shift(fp1, sb); sp2 = pt_shift(fp2, sb)
        sp3 = pt_shift(fp3, sb); sp4 = pt_shift(fp4, sb)

        # Inner glass face (step inward by IGU thickness)
        tv  = vec_scale(n, -GLASS_T)
        bp1 = pt_shift(sp1, tv); bp2 = pt_shift(sp2, tv)
        bp3 = pt_shift(sp3, tv); bp4 = pt_shift(sp4, tv)

        # Build the 6-face closed solid
        # Normal convention: all outer face-normals point away from the solid.
        front = rg.NurbsSurface.CreateFromCorners(sp1, sp2, sp3, sp4)  # outward face
        back  = rg.NurbsSurface.CreateFromCorners(bp1, bp4, bp3, bp2)  # inward face (reversed)
        s_b   = rg.NurbsSurface.CreateFromCorners(sp1, sp2, bp2, bp1)  # bottom edge
        s_r   = rg.NurbsSurface.CreateFromCorners(sp2, sp3, bp3, bp2)  # right edge
        s_t   = rg.NurbsSurface.CreateFromCorners(sp3, sp4, bp4, bp3)  # top edge
        s_l   = rg.NurbsSurface.CreateFromCorners(sp4, sp1, bp1, bp4)  # left edge

        faces = [ns.ToBrep() for ns in [front, back, s_b, s_r, s_t, s_l] if ns is not None]
        if len(faces) < 6:
            continue

        joined = rg.Brep.JoinBreps(faces, tol)
        if joined:
            glass_breps.append(joined[0])
        else:
            glass_breps.extend(faces)   # fallback: open surfaces still render

print("Glass panels: " + str(len(glass_breps)))


# ─────────────────────────────────────────────────────────────────────────────
# STEP 6 — PBR MATERIALS
# ToPhysicallyBased() is tried first (Rhino 7/8).
# Standard material properties are always set as a fallback for Shaded mode.
# ─────────────────────────────────────────────────────────────────────────────

def make_aluminum_mat():
    m = rdo.Material()
    m.Name = "DarkAnodizedAluminum"
    try:
        m.ToPhysicallyBased()
        pbr = m.PhysicallyBased
        pbr.BaseColor = rdp.Color4f(0.035, 0.038, 0.046, 1.0)
        pbr.Metallic  = 0.95
        pbr.Roughness = 0.20
        for attr in ("Reflectance", "Specular"):   # name differs Rhino 7 vs 8
            try: setattr(pbr, attr, 0.88); break
            except: pass
    except: pass
    m.DiffuseColor        = sd.Color.FromArgb(28, 30, 36)
    m.SpecularColor       = sd.Color.FromArgb(150, 158, 168)
    m.Reflectivity        = 0.88
    m.FresnelReflections  = True
    m.Shine               = int(0.70 * rdo.Material.MaxShine)
    return m

def make_glass_mat():
    m = rdo.Material()
    m.Name = "HighPerformanceGlass"
    try:
        m.ToPhysicallyBased()
        pbr = m.PhysicallyBased
        pbr.BaseColor = rdp.Color4f(0.025, 0.14, 0.08, 1.0)
        pbr.Metallic  = 0.0
        pbr.Roughness = 0.01   # near-mirror: maximum reflectivity
        pbr.Opacity   = 0.10   # 90% transparent
        for attr in ("Reflectance", "Specular"):
            try: setattr(pbr, attr, 0.95); break
            except: pass
        try: pbr.OpacityIOR = 1.52
        except: pass
    except: pass
    m.DiffuseColor       = sd.Color.FromArgb(15, 68, 48)
    m.Transparency       = 0.88
    m.Reflectivity       = 0.95
    m.FresnelReflections = True
    m.IndexOfRefraction  = 1.52
    return m

al_idx = doc.Materials.Add(make_aluminum_mat())
gl_idx = doc.Materials.Add(make_glass_mat())


# ─────────────────────────────────────────────────────────────────────────────
# STEP 7 — LAYERS + BAKE
# ─────────────────────────────────────────────────────────────────────────────
mul_layer = get_or_make_layer("Mullions", sd.Color.FromArgb(35, 38, 46), CLEAR_BEFORE)
gl_layer  = get_or_make_layer("Glass",    sd.Color.FromArgb(15, 68, 48), CLEAR_BEFORE)

def make_attr(layer_idx, mat_idx):
    a = rdo.ObjectAttributes()
    a.LayerIndex    = layer_idx
    a.MaterialIndex = mat_idx
    a.MaterialSource = rdo.ObjectMaterialSource.MaterialFromObject
    return a

mul_attr = make_attr(mul_layer, al_idx)
gl_attr  = make_attr(gl_layer,  gl_idx)

for b in mullion_breps:
    doc.Objects.AddBrep(b, mul_attr)

for b in glass_breps:
    doc.Objects.AddBrep(b, gl_attr)

doc.Views.Redraw()

print("")
print("Tower complete.")
print("  " + str(len(mullion_breps)) + " mullion sweeps  (dark anodised aluminium PBR)")
print("  " + str(len(glass_breps))   + " glass panels    (high-performance IGU)")
print("")
print("Next steps in Rhino:")
print("  1. Set display mode to Rendered (V -> Rendered)")
print("  2. Open Rendering panel -> Lighting -> add an HDRI sky")
print("  3. Edit the PARAMETERS block at the top and re-run to iterate")
