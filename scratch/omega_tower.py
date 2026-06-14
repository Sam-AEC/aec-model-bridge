# =============================================================================
# OMEGA TOWER — Adaptive Performative Facade System
# AEC Omni-Bridge MCP Showcase  |  Run via bridge or Rhino PythonEdit (F5)
#
# Systems:
#   A  Squircle-twisted NURBS tower (variable profile, 72° rotation)
#   B  Diagrid frame — tapered sections, heavier at base
#   C  Facade zone 1: solid weathering steel cladding (base 0-22%)
#   D  Facade zone 2: high-performance glass IGU (22-80%)
#   E  Facade zone 3: open structural crown (80-100%)
#   F  Solar fin system — louvers oriented by sun vector at each node
#   G  Floor plates — squircle profile slabs at every 4.3 m
#   H  Branching ground columns — recursive binary tree, 3 levels
#   I  Crown spire — tapered steel needle
#   J  5 PBR materials + 7 layers
# =============================================================================

import math
import Rhino
import Rhino.Geometry as rg
import Rhino.DocObjects as rdo
import Rhino.Display as rdp
import scriptcontext as sc
import System.Drawing as sd

sc.doc = Rhino.RhinoDoc.ActiveDoc
doc = sc.doc
tol = doc.ModelAbsoluteTolerance
S = Rhino.RhinoMath.UnitScale(Rhino.UnitSystem.Meters, doc.ModelUnitSystem)

# =============================================================================
# MASTER PARAMETERS  ←  These map 1-to-1 with GH sliders
# =============================================================================

# A. Tower form
BASE_R       = 26.0   # base radius (m)
WAIST_R      = 14.5   # waist radius at ~40% height (m)
TOP_R        = 21.0   # crown radius (m)
HEIGHT       = 272.0  # total height (~63 floors at 4.3 m)
WAIST_T      = 0.42   # fractional height of waist (0.3–0.6)
SQUIRCLE_N   = 3.5    # 2.0 = circle  |  4.0 = rounded-square  |  8.0 = near-square
TWIST_DEG    = 72.0   # total profile rotation from base to crown (degrees)
PROFILE_PTS  = 64     # points per ring cross-section (smoothness)
LOFT_RINGS   = 22     # loft guide rings (accuracy)

# B. Diagrid
U_DIVS       = 52     # height rows      (U = HEIGHT on the loft surface)
V_DIVS       = 24     # circumference columns (V = CIRCUMFERENCE)
MUL_W_BASE   = 0.30  # face width at base (m)
MUL_W_TOP    = 0.12  # face width at crown (m)
MUL_D_BASE   = 0.52  # structural depth at base (m)
MUL_D_TOP    = 0.20  # structural depth at crown (m)

# C/D/E. Facade zones  (fractions of total height)
ZONE_SOLID   = 0.22   # solid cladding below this
ZONE_GLASS   = 0.80   # glass panels between solid and this; open crown above

# D. Glass panels
GLASS_T      = 0.028  # IGU depth (m)
GLASS_SB     = 0.030  # setback behind facade plane (m)
GLASS_INSET  = 0.09   # corner reveal fraction (0 = full panel, 0.15 = exposed frame)

# F. Solar fins
FIN_ON       = True
SUN_AZ       = 195.0  # azimuth degrees from North (SW orientation)
SUN_ALT      = 40.0   # solar altitude (degrees above horizon)
FIN_LEN      = 1.10   # projection length (m)
FIN_THICK    = 0.055  # fin thickness (m)
FIN_STEP     = 2      # place fin at every Nth height division

# G. Floor plates
FLOOR_H      = 4.3    # floor-to-floor height (m)
SLAB_T       = 0.30   # concrete slab thickness (m)
SLAB_IN      = 0.14   # inset from facade (m)


# I. Crown spire
SPIRE_H      = 38.0   # spire extension above roof (m)
SPIRE_BASE_R = 1.80   # spire base radius (m)
SPIRE_TIP_R  = 0.08   # spire tip radius (m)

CLEAR_BEFORE = True

# =============================================================================
# UTILITIES
# =============================================================================

def smoothstep(a, b, t):
    t = max(0.0, min(1.0, t))
    t = t * t * (3.0 - 2.0 * t)
    return a + (b - a) * t

def tower_r(t):
    """Radius at normalised height t ∈ [0,1]. Non-symmetric waist."""
    if t <= WAIST_T:
        return smoothstep(BASE_R, WAIST_R, t / WAIST_T)
    return smoothstep(WAIST_R, TOP_R, (t - WAIST_T) / (1.0 - WAIST_T))

def copysign_py(mag, sgn):
    return abs(mag) if sgn >= 0 else -abs(mag)

def squircle_xy(angle, r, n):
    """Superellipse point at given angle, radius r, exponent n."""
    c = math.cos(angle)
    s = math.sin(angle)
    x = r * copysign_py(abs(c) ** (2.0 / n), c)
    y = r * copysign_py(abs(s) ** (2.0 / n), s)
    return x, y

def make_layer(name, rgb, clear=CLEAR_BEFORE):
    idx = doc.Layers.FindByFullPath(name, -1)
    if idx < 0:
        lyr = rdo.Layer()
        lyr.Name = name
        lyr.Color = sd.Color.FromArgb(*rgb)
        idx = doc.Layers.Add(lyr)
    else:
        doc.Layers[idx].Color = sd.Color.FromArgb(*rgb)
        if clear:
            objs = doc.Objects.FindByLayer(name)
            if objs:
                for o in objs:
                    doc.Objects.Delete(o, True)
    return idx

def make_attr(layer_idx, mat_idx):
    a = rdo.ObjectAttributes()
    a.LayerIndex = layer_idx
    a.MaterialIndex = mat_idx
    a.MaterialSource = rdo.ObjectMaterialSource.MaterialFromObject
    return a

def dot3(a, b):
    return a.X*b.X + a.Y*b.Y + a.Z*b.Z

def project_to_plane(pt, origin, unit_n):
    d = (pt.X-origin.X)*unit_n.X + (pt.Y-origin.Y)*unit_n.Y + (pt.Z-origin.Z)*unit_n.Z
    return rg.Point3d(pt.X - d*unit_n.X, pt.Y - d*unit_n.Y, pt.Z - d*unit_n.Z)

# =============================================================================
# MATERIALS  (PBR first, standard fallback)
# =============================================================================

def _purge_layer(name):
    """Delete all objects on a named layer (idempotent)."""
    idx = doc.Layers.FindByFullPath(name, -1)
    if idx < 0: return
    objs = doc.Objects.FindByLayer(name)
    if objs:
        for o in objs:
            doc.Objects.Delete(o, True)

# Purge stale layers left by older script versions
_purge_layer("Columns")

def add_mat(name, base_c4f, metallic, roughness, diffuse_rgb,
            transp=0.0, refl=0.0, shine=0.5, opacity=1.0, ior=1.5):
    # Reuse existing material so colours don't accumulate across re-runs
    existing = doc.Materials.Find(name, True)
    if existing >= 0:
        m = doc.Materials[existing]
    else:
        m = rdo.Material()
        m.Name = name
    try:
        m.ToPhysicallyBased()
        pb = m.PhysicallyBased
        pb.BaseColor  = rdp.Color4f(*base_c4f)
        pb.Metallic   = metallic
        pb.Roughness  = roughness
        try: pb.Opacity = opacity
        except: pass
        try: pb.OpacityIOR = ior
        except: pass
    except: pass
    m.DiffuseColor      = sd.Color.FromArgb(*diffuse_rgb)
    m.Transparency      = transp
    m.Reflectivity      = refl
    m.FresnelReflections = True
    m.Shine             = int(shine * rdo.Material.MaxShine)
    if existing >= 0:
        doc.Materials.Modify(m, existing, True)
        return existing
    return doc.Materials.Add(m)

mat_frame  = add_mat("DarkAluminium",
    (0.038, 0.040, 0.048, 1.0), 0.94, 0.17, (30, 32, 38),
    refl=0.87, shine=0.74)

mat_glass  = add_mat("PerfGlass_IGU",
    (0.68, 0.84, 0.94, 1.0),  0.00, 0.02, (170, 210, 240),
    transp=0.92, refl=0.86, shine=0.98, opacity=0.08, ior=1.52)

mat_corten = add_mat("CortenSteelBase",
    (0.16, 0.055, 0.018, 1.0), 0.80, 0.48, (105, 48, 18),
    refl=0.42, shine=0.30)

mat_fin    = add_mat("AluminiumFin",
    (0.52, 0.48, 0.40, 1.0),   0.65, 0.22, (155, 142, 115),
    refl=0.60, shine=0.55)

mat_slab   = add_mat("ExposedConcrete",
    (0.26, 0.26, 0.24, 1.0),   0.00, 0.82, (132, 130, 122),
    refl=0.06, shine=0.04)


mat_spire  = add_mat("BrightStainless",
    (0.78, 0.76, 0.74, 1.0),   0.96, 0.08, (200, 195, 188),
    refl=0.92, shine=0.90)

# =============================================================================
# LAYERS
# =============================================================================

l_frame  = make_layer("Diagrid",      (35, 38, 46))
l_glass  = make_layer("Glass",        (60, 140, 210))
l_clad   = make_layer("Cladding",     (105, 50, 20))
l_fins   = make_layer("SolarFins",    (158, 144, 112))
l_slabs  = make_layer("FloorSlabs",   (140, 136, 126))
l_spire  = make_layer("Spire",        (195, 190, 182))

a_frame = make_attr(l_frame, mat_frame)
a_glass = make_attr(l_glass, mat_glass)
a_clad  = make_attr(l_clad,  mat_corten)
a_fins  = make_attr(l_fins,  mat_fin)
a_slab  = make_attr(l_slabs, mat_slab)
a_spire = make_attr(l_spire, mat_spire)

# =============================================================================
# A — TOWER SURFACE  (squircle twisted loft)
# =============================================================================
print("A: Building tower surface...")

loft_crvs = []
for k in range(LOFT_RINGS + 1):
    t = float(k) / LOFT_RINGS
    r = tower_r(t)
    twist = math.radians(TWIST_DEG * t)
    z = t * HEIGHT * S

    ring = []
    for p in range(PROFILE_PTS):
        angle = 2.0 * math.pi * p / PROFILE_PTS + twist
        x, y = squircle_xy(angle, r * S, SQUIRCLE_N)
        ring.append(rg.Point3d(x, y, z))

    crv = rg.NurbsCurve.CreateInterpolatedCurve(
        ring, 3, rg.CurveKnotStyle.ChordPeriodic)
    if crv:
        loft_crvs.append(crv)
    else:
        # Fallback: degree-3 through points (close manually)
        ring.append(ring[0])
        crv2 = rg.NurbsCurve.CreateInterpolatedCurve(ring, 3)
        if crv2: loft_crvs.append(crv2)

breps = rg.Brep.CreateFromLoft(loft_crvs, rg.Point3d.Unset, rg.Point3d.Unset,
                                 rg.LoftType.Normal, False)
if not breps:
    print("ERROR: loft failed"); raise SystemExit

face = breps[0].Faces[0]
face.SetDomain(0, rg.Interval(0, 1))
face.SetDomain(1, rg.Interval(0, 1))

# Build UV grid (diagrid node positions)
pts = []
for i in range(U_DIVS + 1):
    row = []
    u = float(i) / U_DIVS
    for j in range(V_DIVS + 1):
        v = float(j) / V_DIVS
        row.append(face.PointAt(u, v))
    pts.append(row)

print("   Squircle n=%.1f  twist=%.0f deg  rings=%d" % (SQUIRCLE_N, TWIST_DEG, LOFT_RINGS))

# Diamond-panel helpers — U=HEIGHT (i), V=CIRCUMFERENCE (j wraps)
# Use pts array directly so shapes are geometrically correct regardless of
# surface parameterisation uniformity (squircle curves are chord-length spaced).
def gpt(hi, ci):
    return pts[hi][ci % V_DIVS]

def cc_pt(hi, ci):
    """Geometric centroid of the four surrounding grid corners."""
    j0 = ci % V_DIVS; j1 = (ci + 1) % V_DIVS
    p0=pts[hi][j0]; p1=pts[hi][j1]; p2=pts[hi+1][j0]; p3=pts[hi+1][j1]
    return rg.Point3d((p0.X+p1.X+p2.X+p3.X)*0.25,
                      (p0.Y+p1.Y+p2.Y+p3.Y)*0.25,
                      (p0.Z+p1.Z+p2.Z+p3.Z)*0.25)

# =============================================================================
# B — DIAGRID FRAME  (variable section: deeper + wider at base)
# =============================================================================
print("B: Building diagrid frame...")

n_mul = 0
for i in range(U_DIVS):
    for j in range(V_DIVS):
        t_h = (float(i) + 0.5) / U_DIVS       # normalised height at cell centre
        mw = (MUL_W_BASE + (MUL_W_TOP - MUL_W_BASE) * t_h) * S
        md = (MUL_D_BASE + (MUL_D_TOP - MUL_D_BASE) * t_h) * S

        # Heavier section in solid base zone
        if t_h < ZONE_SOLID:
            mw *= 1.35; md *= 1.55

        diags = [
            (pts[i    ][j    ], pts[i + 1][j + 1]),
            (pts[i + 1][j    ], pts[i    ][j + 1]),
        ]
        for p0, p1 in diags:
            line = rg.LineCurve(p0, p1)
            ok, fr = line.PerpendicularFrameAt(line.Domain.Min)
            if not ok: continue

            mid = line.PointAt(line.Domain.Mid)
            ok2, cu, cv = face.ClosestPoint(mid)
            if not ok2: continue
            sn = face.NormalAt(cu, cv)
            sn.Unitize()

            tang = fr.ZAxis
            t_n = dot3(tang, sn)
            depth = rg.Vector3d(sn.X - t_n*tang.X, sn.Y - t_n*tang.Y, sn.Z - t_n*tang.Z)
            if not depth.Unitize(): continue
            width = rg.Vector3d.CrossProduct(tang, depth)
            if not width.Unitize(): continue

            rect = rg.Rectangle3d(rg.Plane.WorldXY,
                                   rg.Interval(-mw*0.5, mw*0.5),
                                   rg.Interval(-md, 0.0))
            prof = rect.ToNurbsCurve()
            sweep_pln = rg.Plane(fr.Origin, width, depth)
            xf = rg.Transform.PlaneToPlane(rg.Plane.WorldXY, sweep_pln)
            prof.Transform(xf)

            swept = rg.Brep.CreateFromSweep(line, prof, True, tol)
            if swept:
                for b in swept: doc.Objects.AddBrep(b, a_frame)
                n_mul += 1

print("   Mullion sweeps: %d" % n_mul)

# =============================================================================
# C/D — FACADE PANELS
#   Solid base  (UV quad corten)         : 0 → ZONE_SOLID
#   Glass zone  (diamond panels)         : ZONE_SOLID → ZONE_GLASS
#   Crown       (open structural frame)  : ZONE_GLASS → 1.0
#
# Diamond topology identical to diagrid_tower_glass.py:
#   Type A  : cc(i,j)→gpt(i+1,j+1)→cc(i,j+1)→gpt(i,j+1)
#   Type B  : cc(i,j)→gpt(i+1,j)→cc(i+1,j)→gpt(i+1,j+1)
#   Bot cap : gpt(i0,j)→gpt(i0,j+1)→cc(i0,j)
#   Top cap : cc(ie-1,j)→gpt(ie,j+1)→gpt(ie,j)
# =============================================================================
print("C/D: Building facade panels...")

def _surf_cn(pts_list):
    """Surface normal + centroid for a list of surface points."""
    cx = sum(p.X for p in pts_list) / len(pts_list)
    cy = sum(p.Y for p in pts_list) / len(pts_list)
    cz = sum(p.Z for p in pts_list) / len(pts_list)
    c = rg.Point3d(cx, cy, cz)
    ok, cu, cv = face.ClosestPoint(c)
    if not ok: return None, None
    n = face.NormalAt(cu, cv)
    return (c, n) if n.Unitize() else (None, None)

def _solid_6face(verts_f, verts_b, attr):
    """Build and bake a 6-face closed solid from front and back quad vertices."""
    f, b = verts_f, verts_b
    surfs = [
        rg.NurbsSurface.CreateFromCorners(f[0],f[1],f[2],f[3]),
        rg.NurbsSurface.CreateFromCorners(b[0],b[3],b[2],b[1]),
        rg.NurbsSurface.CreateFromCorners(f[0],f[1],b[1],b[0]),
        rg.NurbsSurface.CreateFromCorners(f[1],f[2],b[2],b[1]),
        rg.NurbsSurface.CreateFromCorners(f[2],f[3],b[3],b[2]),
        rg.NurbsSurface.CreateFromCorners(f[3],f[0],b[0],b[3]),
    ]
    faces_b = [s.ToBrep() for s in surfs if s]
    if len(faces_b) < 6: return False
    j2 = rg.Brep.JoinBreps(faces_b, tol)
    if j2: doc.Objects.AddBrep(j2[0], attr)
    return bool(j2)

def _solid_5face(verts_f, verts_b, attr):
    """Build and bake a 5-face closed solid from front and back triangle vertices."""
    f, b = verts_f, verts_b
    surfs = [
        rg.NurbsSurface.CreateFromCorners(f[0],f[1],f[2]),
        rg.NurbsSurface.CreateFromCorners(b[0],b[2],b[1]),
        rg.NurbsSurface.CreateFromCorners(f[0],f[1],b[1],b[0]),
        rg.NurbsSurface.CreateFromCorners(f[1],f[2],b[2],b[1]),
        rg.NurbsSurface.CreateFromCorners(f[2],f[0],b[0],b[2]),
    ]
    faces_b = [s.ToBrep() for s in surfs if s]
    if len(faces_b) < 5: return False
    j2 = rg.Brep.JoinBreps(faces_b, tol)
    if j2: doc.Objects.AddBrep(j2[0], attr)
    return bool(j2)

def diamond_quad(A, B, C, D, thick, setback, attr):
    """Diamond glass panel: vertices ARE the structural nodes (no corner inset)."""
    c, n = _surf_cn([A, B, C, D])
    if c is None: return False
    off = n * (-setback); tv = n * (-thick)
    fv = [p + off for p in [A, B, C, D]]
    bv = [p + tv  for p in fv]
    return _solid_6face(fv, bv, attr)

def diamond_tri(A, B, C, thick, setback, attr):
    """Triangular glass cap panel."""
    c, n = _surf_cn([A, B, C])
    if c is None: return False
    off = n * (-setback); tv = n * (-thick)
    fv = [p + off for p in [A, B, C]]
    bv = [p + tv  for p in fv]
    return _solid_5face(fv, bv, attr)

def rect_corten(p1, p2, p3, p4, thick, setback, inset, attr):
    """UV-quad solid cladding panel with corner inset."""
    c, n = _surf_cn([p1, p2, p3, p4])
    if c is None: return False
    k = 1.0 - inset
    gi = [rg.Point3d(c.X+(p.X-c.X)*k, c.Y+(p.Y-c.Y)*k, c.Z+(p.Z-c.Z)*k)
          for p in [p1, p2, p3, p4]]
    fp = [project_to_plane(g, c, n) for g in gi]
    off = n * (-setback); tv = n * (-thick)
    fv = [rg.Point3d(f.X+off.X, f.Y+off.Y, f.Z+off.Z) for f in fp]
    bv = [rg.Point3d(f.X+tv.X,  f.Y+tv.Y,  f.Z+tv.Z ) for f in fv]
    return _solid_6face(fv, bv, attr)

# ── Solid corten base (UV quads) ──────────────────────────────────────────────
n_clad = 0
for i in range(U_DIVS):
    if (float(i) + 0.5) / U_DIVS >= ZONE_SOLID: break
    for j in range(V_DIVS):
        p1=pts[i][j]; p2=pts[i+1][j]; p3=pts[i+1][j+1]; p4=pts[i][j+1]
        if rect_corten(p1,p2,p3,p4, 0.055*S, 0.018*S, 0.03, a_clad):
            n_clad += 1

# ── Diamond glass panels ──────────────────────────────────────────────────────
i_solid = int(round(ZONE_SOLID * U_DIVS))
i_glass = min(int(round(ZONE_GLASS * U_DIVS)), U_DIVS)
n_glass = 0

# Bottom-zone transition caps (left-triangle of first glass row)
for j in range(V_DIVS):
    if diamond_tri(gpt(i_solid,j), gpt(i_solid,j+1), cc_pt(i_solid,j),
                   GLASS_T*S, GLASS_SB*S, a_glass):
        n_glass += 1

# Type A: top-tri(i,j) + bottom-tri(i,j+1) merged as rhombus
for i in range(i_solid, i_glass):
    for j in range(V_DIVS):
        if diamond_quad(cc_pt(i,j), gpt(i+1,j+1), cc_pt(i,j+1), gpt(i,j+1),
                        GLASS_T*S, GLASS_SB*S, a_glass):
            n_glass += 1

# Type B: right-tri(i,j) + left-tri(i+1,j) merged as rhombus
for i in range(i_solid, i_glass - 1):
    for j in range(V_DIVS):
        if diamond_quad(cc_pt(i,j), gpt(i+1,j), cc_pt(i+1,j), gpt(i+1,j+1),
                        GLASS_T*S, GLASS_SB*S, a_glass):
            n_glass += 1

# Top-zone transition caps (right-triangle of last glass row)
for j in range(V_DIVS):
    if diamond_tri(cc_pt(i_glass-1,j), gpt(i_glass,j+1), gpt(i_glass,j),
                   GLASS_T*S, GLASS_SB*S, a_glass):
        n_glass += 1

print("   Corten panels: %d   Diamond glass: %d" % (n_clad, n_glass))

# =============================================================================
# F — SOLAR FIN SYSTEM  (louvers oriented perpendicular to projected sun ray)
# =============================================================================
if FIN_ON:
    print("F: Building solar fins...")

    az_r  = math.radians(SUN_AZ)
    alt_r = math.radians(SUN_ALT)
    sun_v = rg.Vector3d(math.sin(az_r)*math.cos(alt_r),
                        math.cos(az_r)*math.cos(alt_r),
                        math.sin(alt_r))
    sun_v.Unitize()

    n_fins = 0
    for i in range(U_DIVS):
        for j in range(0, V_DIVS, FIN_STEP):
            t_h = float(j) / V_DIVS
            if t_h < ZONE_SOLID or t_h > ZONE_GLASS:
                continue

            node = pts[i][j]
            ok_cp, cu, cv = face.ClosestPoint(node)
            if not ok_cp: continue
            sn = face.NormalAt(cu, cv)
            if not sn.Unitize(): continue

            # Project sun vector onto surface tangent plane
            d_sn = dot3(sun_v, sn)
            proj = rg.Vector3d(sun_v.X - d_sn*sn.X,
                               sun_v.Y - d_sn*sn.Y,
                               sun_v.Z - d_sn*sn.Z)
            if proj.Length < 0.01:
                proj = rg.Vector3d(0, 0, 1)
            proj.Unitize()

            # Fin faces the sun: width direction is cross(sn, proj_sun)
            fw = rg.Vector3d.CrossProduct(sn, proj)
            if not fw.Unitize(): continue

            fl = FIN_LEN * S
            ft = FIN_THICK * S
            base_off = sn * (0.02 * S)   # tiny lift off facade

            c1 = rg.Point3d(node.X + base_off.X - fw.X*ft*0.5,
                            node.Y + base_off.Y - fw.Y*ft*0.5,
                            node.Z + base_off.Z)
            c2 = rg.Point3d(c1.X + fw.X*ft, c1.Y + fw.Y*ft, c1.Z)
            c3 = rg.Point3d(c2.X + sn.X*fl, c2.Y + sn.Y*fl, c2.Z + sn.Z*fl)
            c4 = rg.Point3d(c1.X + sn.X*fl, c1.Y + sn.Y*fl, c1.Z + sn.Z*fl)

            fin_s = rg.NurbsSurface.CreateFromCorners(c1, c2, c3, c4)
            if fin_s:
                doc.Objects.AddSurface(fin_s, a_fins)
                n_fins += 1

    print("   Solar fins: %d  (sun az=%.0f° alt=%.0f°)" % (n_fins, SUN_AZ, SUN_ALT))

# =============================================================================
# G — FLOOR PLATES  (squircle profile follows tower twist + taper)
# =============================================================================
print("G: Building floor plates...")

n_floors_actual = int(HEIGHT / FLOOR_H)
n_slabs = 0

for fl_idx in range(1, n_floors_actual + 1):
    z_frac = float(fl_idx) * FLOOR_H / HEIGHT
    if z_frac >= 1.0: break
    z = z_frac * HEIGHT * S

    twist = math.radians(TWIST_DEG * z_frac)
    r = tower_r(z_frac) - SLAB_IN

    slab_ring = []
    for p in range(PROFILE_PTS):
        angle = 2.0 * math.pi * p / PROFILE_PTS + twist
        x, y = squircle_xy(angle, r * S, SQUIRCLE_N)
        slab_ring.append(rg.Point3d(x, y, z))

    slab_crv = rg.NurbsCurve.CreateInterpolatedCurve(
        slab_ring, 3, rg.CurveKnotStyle.ChordPeriodic)
    if not slab_crv:
        slab_ring.append(slab_ring[0])
        slab_crv = rg.NurbsCurve.CreateInterpolatedCurve(slab_ring, 3)
    if not slab_crv: continue

    try:
        extrusion = rg.Extrusion.Create(slab_crv, SLAB_T * S, True)
        if extrusion:
            doc.Objects.AddExtrusion(extrusion, a_slab)
            n_slabs += 1
            continue
    except: pass
    # fallback: planar cap only
    flat = rg.Brep.CreatePlanarBreps(slab_crv, tol)
    if flat:
        for fb in flat:
            doc.Objects.AddBrep(fb, a_slab)
        n_slabs += 1

print("   Floor slabs: %d" % n_slabs)

# =============================================================================
# I — CROWN SPIRE  (tapered stainless needle)
# =============================================================================
print("I: Building crown spire...")

spire_rings = []
for k in range(6):
    t = float(k) / 5.0
    r_s = (SPIRE_BASE_R + (SPIRE_TIP_R - SPIRE_BASE_R) * (t*t)) * S
    z_s = (HEIGHT + SPIRE_H * t) * S
    spire_rings.append(rg.Circle(
        rg.Plane(rg.Point3d(0, 0, z_s), rg.Vector3d.ZAxis), r_s
    ).ToNurbsCurve())

sp_brep = rg.Brep.CreateFromLoft(spire_rings, rg.Point3d.Unset, rg.Point3d.Unset,
                                   rg.LoftType.Normal, False)
if sp_brep:
    for b in sp_brep:
        b2 = rg.Brep.CapPlanarHoles(b, tol)
        doc.Objects.AddBrep(b2 if b2 else b, a_spire)
    print("   Spire: OK")

# =============================================================================
# DONE
# =============================================================================
doc.Views.Redraw()

print("")
print("=" * 58)
print("OMEGA TOWER  — Complete")
print("  Diagrid members   : %d" % n_mul)
print("  Corten cladding   : %d  (zone 0 – %.0f%%)" % (n_clad, ZONE_SOLID*100))
print("  Glass IGU panels  : %d  (zone %.0f%% – %.0f%%)" % (n_glass, ZONE_SOLID*100, ZONE_GLASS*100))
if FIN_ON:
    print("  Solar fins        : %d" % n_fins)
print("  Floor slabs       : %d  (@ %.1f m)" % (n_slabs, FLOOR_H))
print("  Crown spire       : 1")
print("=" * 58)
print("Next: Rendered display mode + HDRI sky for final image")

# Restore GH scriptcontext if running inside a Grasshopper component
try:
    sc.doc = ghdoc
except NameError:
    pass
