import scriptcontext as sc
import Rhino, Rhino.Geometry as rg, Rhino.DocObjects as rdo, System.Drawing as sd

# ── Tower params (must match mullion generation) ─────────────────────────────
BASE_R=22.0; WAIST_R=13.5; TOP_R=19.0; HEIGHT=200.0
U_DIVS=20    # divisions in i-direction (= surface U = HEIGHT direction on this loft)
V_DIVS=36    # divisions in j-direction (= surface V = CIRCUMFERENTIAL direction)
THICKNESS=0.028; SETBACK=0.06

scale = Rhino.RhinoMath.UnitScale(Rhino.UnitSystem.Meters, sc.doc.ModelUnitSystem)

# ── Rebuild tower loft ────────────────────────────────────────────────────────
def smooth_r(a,b,c,t):
    if t<=0.5: s=t*2.0; return a+(b-a)*(s*s*(3-2*s))
    s=(t-0.5)*2.0; return b+(c-b)*(s*s*(3-2*s))

crvs=[]
for k in range(12):
    t=float(k)/11; r=smooth_r(BASE_R,WAIST_R,TOP_R,t)*scale; z=t*HEIGHT*scale
    crvs.append(rg.Circle(rg.Plane(rg.Point3d(0,0,z),rg.Vector3d.ZAxis),r).ToNurbsCurve())
breps=rg.Brep.CreateFromLoft(crvs,rg.Point3d.Unset,rg.Point3d.Unset,rg.LoftType.Normal,False)
face=breps[0].Faces[0]
face.SetDomain(0,rg.Interval(0,1)); face.SetDomain(1,rg.Interval(0,1))

# Confirmed: surface U = HEIGHT (i direction), surface V = CIRCUMFERENCE (j direction)
# The circumferential seam is at V=0/V=1 (j=0/j=V_DIVS).
# i goes from 0 (bottom) to U_DIVS (top) — NO wrap needed for i.
# j wraps: j % V_DIVS keeps us inside the closed circumferential range.

def gpt(i, j):
    """Grid corner: i=height index (0..U_DIVS), j=circumference index (wraps)."""
    u = float(i) / U_DIVS
    v = float(j % V_DIVS) / V_DIVS
    return face.PointAt(u, v)

def cc(i, j):
    """Cell centre on surface: i=height cell (0..U_DIVS-1), j=circ cell (wraps)."""
    u = (i + 0.5) / U_DIVS
    v = ((j % V_DIVS) + 0.5) / V_DIVS
    return face.PointAt(u, v)

# ── Layer + material ──────────────────────────────────────────────────────────
def get_layer(name, rgb, clear=False):
    idx = sc.doc.Layers.FindByFullPath(name,-1)
    if idx < 0:
        lay=rdo.Layer(); lay.Name=name
        lay.Color=sd.Color.FromArgb(*rgb)
        idx=sc.doc.Layers.Add(lay)
    elif clear:
        for o in list(sc.doc.Objects):
            if o.Attributes.LayerIndex==idx:
                sc.doc.Objects.Delete(o.Id,True)
    return idx

glass_layer = get_layer("Glass",(18,75,52),clear=True)
mat=rdo.Material(); mat.Name="ArchGlass"
mat.DiffuseColor=sd.Color.FromArgb(35,155,105)
mat.Transparency=0.55; mat.Reflectivity=0.95
mat.FresnelReflections=True; mat.IndexOfRefraction=1.52
mat.Shine=int(0.92*rdo.Material.MaxShine)
try:
    mat.ToPhysicallyBased()
    pbr=mat.PhysicallyBased
    pbr.BaseColor=Rhino.Display.Color4f(0.04,0.28,0.16,1.0)
    pbr.Metallic=0.0; pbr.Roughness=0.02; pbr.Opacity=0.48
except:
    pass
glass_mat=sc.doc.Materials.Add(mat)

attr=rdo.ObjectAttributes()
attr.LayerIndex=glass_layer; attr.MaterialIndex=glass_mat
attr.MaterialSource=rdo.ObjectMaterialSource.MaterialFromObject

tol=sc.doc.ModelAbsoluteTolerance
# Reject any panel whose bbox diagonal exceeds 2 cell widths (catches spanning artifacts)
MAX_DIAG = 15000.0 * scale
added=0; skipped=0

# ── Quad panel (6-face solid) ─────────────────────────────────────────────────
def make_panel(A, B, C, D):
    bb = rg.BoundingBox([A,B,C,D])
    if bb.Diagonal.Length > MAX_DIAG:
        return False
    cpt=rg.Point3d((A.X+B.X+C.X+D.X)/4.,(A.Y+B.Y+C.Y+D.Y)/4.,(A.Z+B.Z+C.Z+D.Z)/4.)
    ok,cu,cv=face.ClosestPoint(cpt)
    if not ok: return False
    n=face.NormalAt(cu,cv)
    if not n.Unitize(): return False
    push=n*(-SETBACK*scale); thick=n*(-THICKNESS*scale)
    fA=A+push; fB=B+push; fC=C+push; fD=D+push
    bA=fA+thick; bB=fB+thick; bC=fC+thick; bD=fD+thick
    front=rg.NurbsSurface.CreateFromCorners(fA,fB,fC,fD)
    back =rg.NurbsSurface.CreateFromCorners(bA,bD,bC,bB)
    s1=rg.NurbsSurface.CreateFromCorners(fA,fB,bB,bA)
    s2=rg.NurbsSurface.CreateFromCorners(fB,fC,bC,bB)
    s3=rg.NurbsSurface.CreateFromCorners(fC,fD,bD,bC)
    s4=rg.NurbsSurface.CreateFromCorners(fD,fA,bA,bD)
    faces=[x.ToBrep() for x in [front,back,s1,s2,s3,s4] if x]
    if len(faces)<6: return False
    joined=rg.Brep.JoinBreps(faces,tol)
    if joined and len(joined)>0: sc.doc.Objects.AddBrep(joined[0],attr)
    else: [sc.doc.Objects.AddBrep(f,attr) for f in faces]
    return True

# ── Triangular panel (5-face solid, for top/bottom caps) ─────────────────────
def make_tri(A, B, C):
    bb = rg.BoundingBox([A,B,C])
    if bb.Diagonal.Length > MAX_DIAG:
        return False
    cpt=rg.Point3d((A.X+B.X+C.X)/3.,(A.Y+B.Y+C.Y)/3.,(A.Z+B.Z+C.Z)/3.)
    ok,cu,cv=face.ClosestPoint(cpt)
    if not ok: return False
    n=face.NormalAt(cu,cv)
    if not n.Unitize(): return False
    push=n*(-SETBACK*scale); thick=n*(-THICKNESS*scale)
    fA=A+push; fB=B+push; fC=C+push
    bA=fA+thick; bB=fB+thick; bC=fC+thick
    front=rg.NurbsSurface.CreateFromCorners(fA,fB,fC)
    back =rg.NurbsSurface.CreateFromCorners(bA,bC,bB)
    s1=rg.NurbsSurface.CreateFromCorners(fA,fB,bB,bA)
    s2=rg.NurbsSurface.CreateFromCorners(fB,fC,bC,bB)
    s3=rg.NurbsSurface.CreateFromCorners(fC,fA,bA,bC)
    faces=[x.ToBrep() for x in [front,back,s1,s2,s3] if x]
    if len(faces)<5: return False
    joined=rg.Brep.JoinBreps(faces,tol)
    if joined and len(joined)>0: sc.doc.Objects.AddBrep(joined[0],attr)
    else: [sc.doc.Objects.AddBrep(f,attr) for f in faces]
    return True

# ── Type A: TOP triangle of cell(i,j) + BOTTOM triangle of cell(i,j+1) ──────
# Vertices: cc(i,j), gpt(i+1,j+1), cc(i,j+1), gpt(i,j+1)
# i spans full height range, j wraps circumferentially via gpt/cc % V_DIVS
for i in range(U_DIVS):
    for j in range(V_DIVS):
        r = make_panel(cc(i,j), gpt(i+1,j+1), cc(i,j+1), gpt(i,j+1))
        if r: added+=1
        else: skipped+=1

# ── Type B: RIGHT triangle of cell(i,j) + LEFT triangle of cell(i+1,j) ──────
# Vertices: cc(i,j), gpt(i+1,j), cc(i+1,j), gpt(i+1,j+1)
# i goes 0..U_DIVS-2 (height cells that have a valid i+1 cell above them, NO wrap)
for i in range(U_DIVS - 1):
    for j in range(V_DIVS):
        r = make_panel(cc(i,j), gpt(i+1,j), cc(i+1,j), gpt(i+1,j+1))
        if r: added+=1
        else: skipped+=1

# ── Bottom caps: LEFT triangle of cell(i=0, j) ───────────────────────────────
# LEFT(0,j): gpt(0,j), gpt(0,j+1), cc(0,j)  (all at height i=0 = tower base)
for j in range(V_DIVS):
    r = make_tri(gpt(0,j), gpt(0,j+1), cc(0,j))
    if r: added+=1
    else: skipped+=1

# ── Top caps: RIGHT triangle of cell(i=U_DIVS-1, j) ──────────────────────────
# RIGHT(U_DIVS-1,j): cc(U_DIVS-1,j), gpt(U_DIVS,j+1), gpt(U_DIVS,j)
for j in range(V_DIVS):
    r = make_tri(cc(U_DIVS-1,j), gpt(U_DIVS,j+1), gpt(U_DIVS,j))
    if r: added+=1
    else: skipped+=1

sc.doc.Views.Redraw()
print("Panels added: %d  skipped: %d" % (added, skipped))
