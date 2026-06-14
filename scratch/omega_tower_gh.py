# =============================================================================
# OMEGA TOWER — Grasshopper-aware version
# All parameters read from GH input ports; defaults used when standalone.
# Paste this into the GhPython Script component that omega_gh_builder2.py created.
# =============================================================================

import math
import Rhino, Rhino.Geometry as rg, Rhino.DocObjects as rdo
import Rhino.Display as rdp, scriptcontext as sc, System.Drawing as sd

# ── GH input helpers ─────────────────────────────────────────────────────────
def _f(v, d):
    try: return float(v) if v is not None else d
    except: return d
def _i(v, d):
    try: return int(float(v)) if v is not None else d
    except: return d

# ── Parameters (read from wired sliders, fallback to defaults) ───────────────
BASE_R      = _f(base_r,      26.0)
WAIST_R     = _f(waist_r,     14.5)
TOP_R       = _f(top_r,       21.0)
HEIGHT      = _f(height,      272.0)
SQUIRCLE_N  = _f(squircle_n,  3.5)
TWIST_DEG   = _f(twist_deg,   72.0)
U_DIVS      = _i(u_divs,      24)
V_DIVS      = _i(v_divs,      52)
MUL_W_BASE  = _f(mul_w_base,  0.30)
MUL_W_TOP   = _f(mul_w_top,   0.12)
MUL_D_BASE  = _f(mul_d_base,  0.52)
MUL_D_TOP   = _f(mul_d_top,   0.20)
ZONE_SOLID  = _f(zone_solid,  0.22)
ZONE_GLASS  = _f(zone_glass,  0.80)
GLASS_T     = _f(glass_t,     0.028)
GLASS_INSET = _f(glass_inset, 0.09)
SUN_AZ      = _f(sun_azimuth, 195.0)
SUN_ALT     = _f(sun_altitude,40.0)
FIN_LEN     = _f(fin_len,     1.10)
FIN_THICK   = _f(fin_thick,   0.055)
FIN_STEP    = _i(fin_step,    2)
FLOOR_H     = _f(floor_h,     4.3)
SLAB_T      = _f(slab_t,      0.30)
SLAB_IN     = _f(slab_in,     0.14)
COL_N       = _i(col_n,       8)
COL_DEPTH   = _i(col_depth,   3)
COL_ANGLE   = _f(col_angle,   26.0)
COL_H       = _f(col_h,       15.0)

WAIST_T    = 0.42
PROFILE_PTS = 64
LOFT_RINGS  = 22
SPIRE_H = 38.0; SPIRE_BASE_R = 1.80; SPIRE_TIP_R = 0.08
FIN_ON = True; CLEAR_BEFORE = True

doc = sc.doc; tol = doc.ModelAbsoluteTolerance
S = Rhino.RhinoMath.UnitScale(Rhino.UnitSystem.Meters, doc.ModelUnitSystem)

# ── Utilities ─────────────────────────────────────────────────────────────────
def smoothstep(a,b,t):
    t=max(0.0,min(1.0,t)); t=t*t*(3.0-2.0*t); return a+(b-a)*t
def tower_r(t):
    if t<=WAIST_T: return smoothstep(BASE_R,WAIST_R,t/WAIST_T)
    return smoothstep(WAIST_R,TOP_R,(t-WAIST_T)/(1.0-WAIST_T))
def cs(m,s): return abs(m) if s>=0 else -abs(m)
def sqxy(ang,r,n):
    c=math.cos(ang); s=math.sin(ang)
    return r*cs(abs(c)**(2.0/n),c), r*cs(abs(s)**(2.0/n),s)
def mk_layer(name,rgb):
    idx=doc.Layers.FindByFullPath(name,-1)
    if idx<0:
        lyr=rdo.Layer(); lyr.Name=name; lyr.Color=sd.Color.FromArgb(*rgb)
        idx=doc.Layers.Add(lyr)
    elif CLEAR_BEFORE:
        objs=doc.Objects.FindByLayer(name)
        if objs:
            for o in objs: doc.Objects.Delete(o,True)
    return idx
def mk_attr(li,mi):
    a=rdo.ObjectAttributes(); a.LayerIndex=li; a.MaterialIndex=mi
    a.MaterialSource=rdo.ObjectMaterialSource.MaterialFromObject; return a
def d3(a,b): return a.X*b.X+a.Y*b.Y+a.Z*b.Z
def prj(pt,o,n):
    d=(pt.X-o.X)*n.X+(pt.Y-o.Y)*n.Y+(pt.Z-o.Z)*n.Z
    return rg.Point3d(pt.X-d*n.X,pt.Y-d*n.Y,pt.Z-d*n.Z)
def add_m(nm,bc,me,ro,dif,tr=0.0,re=0.0,sh=0.5,op=1.0):
    m=rdo.Material(); m.Name=nm
    try:
        m.ToPhysicallyBased(); pb=m.PhysicallyBased
        pb.BaseColor=rdp.Color4f(*bc); pb.Metallic=me; pb.Roughness=ro
        try: pb.Opacity=op
        except: pass
    except: pass
    m.DiffuseColor=sd.Color.FromArgb(*dif); m.Transparency=tr
    m.Reflectivity=re; m.FresnelReflections=True
    m.Shine=int(sh*rdo.Material.MaxShine); return doc.Materials.Add(m)

# ── Materials ─────────────────────────────────────────────────────────────────
mf =add_m("Frame",  (0.038,0.040,0.048,1.0),0.94,0.17,(30,32,38), re=0.87,sh=0.74)
mg =add_m("Glass",  (0.025,0.14,0.09,1.0), 0.00,0.01,(10,58,40),  tr=0.88,re=0.94,sh=0.96,op=0.10)
mc =add_m("Corten", (0.16,0.055,0.018,1.0),0.80,0.48,(105,48,18), re=0.42,sh=0.30)
mfi=add_m("Fin",    (0.52,0.48,0.40,1.0), 0.65,0.22,(155,142,115),re=0.60,sh=0.55)
ms =add_m("Slab",   (0.26,0.26,0.24,1.0), 0.00,0.82,(132,130,122),re=0.06,sh=0.04)
mco=add_m("Col",    (0.20,0.07,0.022,1.0),0.82,0.44,(118,55,22),  re=0.40,sh=0.28)
msp=add_m("Spire",  (0.78,0.76,0.74,1.0), 0.96,0.08,(200,195,188),re=0.92,sh=0.90)

# ── Layers ────────────────────────────────────────────────────────────────────
lf =mk_layer("Diagrid",(35,38,46));   lg =mk_layer("Glass",(12,65,45))
lc =mk_layer("Cladding",(105,50,20)); lfn=mk_layer("SolarFins",(158,144,112))
lsl=mk_layer("FloorSlabs",(140,136,126)); lco=mk_layer("Columns",(112,52,20))
lsp=mk_layer("Spire",(195,190,182))
af=mk_attr(lf,mf); ag=mk_attr(lg,mg); ac=mk_attr(lc,mc)
afn=mk_attr(lfn,mfi); asl=mk_attr(lsl,ms); aco=mk_attr(lco,mco); asp=mk_attr(lsp,msp)

# ── A: Tower surface ──────────────────────────────────────────────────────────
loft=[]
for k in range(LOFT_RINGS+1):
    t=float(k)/LOFT_RINGS; r=tower_r(t)
    twist=math.radians(TWIST_DEG*t); z=t*HEIGHT*S
    ring=[rg.Point3d(sqxy(2.0*math.pi*p/PROFILE_PTS+twist,r*S,SQUIRCLE_N)[0],
                     sqxy(2.0*math.pi*p/PROFILE_PTS+twist,r*S,SQUIRCLE_N)[1],z)
          for p in range(PROFILE_PTS)]
    crv=rg.NurbsCurve.CreateInterpolatedCurve(ring,3,rg.CurveKnotStyle.ChordPeriodic)
    if not crv: ring.append(ring[0]); crv=rg.NurbsCurve.CreateInterpolatedCurve(ring,3)
    if crv: loft.append(crv)
breps=rg.Brep.CreateFromLoft(loft,rg.Point3d.Unset,rg.Point3d.Unset,rg.LoftType.Normal,False)
if not breps: print("Loft failed"); raise SystemExit
face=breps[0].Faces[0]
face.SetDomain(0,rg.Interval(0,1)); face.SetDomain(1,rg.Interval(0,1))
pts=[[face.PointAt(float(i)/U_DIVS,float(j)/V_DIVS) for j in range(V_DIVS+1)] for i in range(U_DIVS+1)]

# ── B: Diagrid frame ──────────────────────────────────────────────────────────
nm=0
for i in range(U_DIVS):
  for j in range(V_DIVS):
    th=(float(j)+0.5)/V_DIVS
    mw=(MUL_W_BASE+(MUL_W_TOP-MUL_W_BASE)*th)*S
    md=(MUL_D_BASE+(MUL_D_TOP-MUL_D_BASE)*th)*S
    if th<ZONE_SOLID: mw*=1.35; md*=1.55
    for p0,p1 in [(pts[i][j],pts[i+1][j+1]),(pts[i+1][j],pts[i][j+1])]:
      line=rg.LineCurve(p0,p1); ok,fr=line.PerpendicularFrameAt(line.Domain.Min)
      if not ok: continue
      mid=line.PointAt(line.Domain.Mid); ok2,cu,cv=face.ClosestPoint(mid)
      if not ok2: continue
      sn=face.NormalAt(cu,cv); sn.Unitize(); tang=fr.ZAxis
      tn=d3(tang,sn); dep=rg.Vector3d(sn.X-tn*tang.X,sn.Y-tn*tang.Y,sn.Z-tn*tang.Z)
      if not dep.Unitize(): continue
      wid=rg.Vector3d.CrossProduct(tang,dep)
      if not wid.Unitize(): continue
      rect=rg.Rectangle3d(rg.Plane.WorldXY,rg.Interval(-mw*0.5,mw*0.5),rg.Interval(-md,0.0))
      prof=rect.ToNurbsCurve()
      spln=rg.Plane(fr.Origin,wid,dep); xf=rg.Transform.PlaneToPlane(rg.Plane.WorldXY,spln)
      prof.Transform(xf)
      sw=rg.Brep.CreateFromSweep(line,prof,True,tol)
      if sw:
        for b in sw: doc.Objects.AddBrep(b,af)
        nm+=1

# ── C/D: Facade panels (zone-aware) ──────────────────────────────────────────
def panel(p1,p2,p3,p4,t,sb,ins,c,n,attr):
    k=1.0-ins
    gi=[rg.Point3d(c.X+(p.X-c.X)*k,c.Y+(p.Y-c.Y)*k,c.Z+(p.Z-c.Z)*k) for p in[p1,p2,p3,p4]]
    fp=[prj(g,c,n) for g in gi]; off=n*(-sb)
    sp=[rg.Point3d(f.X+off.X,f.Y+off.Y,f.Z+off.Z) for f in fp]; tv=n*(-t)
    bp=[rg.Point3d(s.X+tv.X,s.Y+tv.Y,s.Z+tv.Z) for s in sp]
    ss=[rg.NurbsSurface.CreateFromCorners(sp[0],sp[1],sp[2],sp[3]),
        rg.NurbsSurface.CreateFromCorners(bp[0],bp[3],bp[2],bp[1]),
        rg.NurbsSurface.CreateFromCorners(sp[0],sp[1],bp[1],bp[0]),
        rg.NurbsSurface.CreateFromCorners(sp[1],sp[2],bp[2],bp[1]),
        rg.NurbsSurface.CreateFromCorners(sp[2],sp[3],bp[3],bp[2]),
        rg.NurbsSurface.CreateFromCorners(sp[3],sp[0],bp[0],bp[3])]
    fb=[s.ToBrep() for s in ss if s]
    if len(fb)<6: return
    j2=rg.Brep.JoinBreps(fb,tol)
    if j2: doc.Objects.AddBrep(j2[0],attr)

for i in range(U_DIVS):
  for j in range(V_DIVS):
    th=(float(j)+0.5)/V_DIVS
    if th>ZONE_GLASS: continue
    p1=pts[i][j];p2=pts[i+1][j];p3=pts[i+1][j+1];p4=pts[i][j+1]
    cx=(p1.X+p2.X+p3.X+p4.X)*0.25;cy=(p1.Y+p2.Y+p3.Y+p4.Y)*0.25;cz=(p1.Z+p2.Z+p3.Z+p4.Z)*0.25
    c=rg.Point3d(cx,cy,cz); ok,cu,cv=face.ClosestPoint(c)
    if not ok: continue
    n=face.NormalAt(cu,cv)
    if not n.Unitize(): continue
    if th<ZONE_SOLID: panel(p1,p2,p3,p4,0.055*S,0.018*S,0.03,c,n,ac)
    else: panel(p1,p2,p3,p4,GLASS_T*S,0.030*S,GLASS_INSET,c,n,ag)

# ── F: Solar fins ─────────────────────────────────────────────────────────────
if FIN_ON:
    az=math.radians(SUN_AZ); alt=math.radians(SUN_ALT)
    sv=rg.Vector3d(math.sin(az)*math.cos(alt),math.cos(az)*math.cos(alt),math.sin(alt)); sv.Unitize()
    for i in range(U_DIVS):
      for j in range(0,V_DIVS,FIN_STEP):
        th=float(j)/V_DIVS
        if th<ZONE_SOLID or th>ZONE_GLASS: continue
        nd=pts[i][j]; ok,cu,cv=face.ClosestPoint(nd)
        if not ok: continue
        sn=face.NormalAt(cu,cv)
        if not sn.Unitize(): continue
        dsn=d3(sv,sn); pj=rg.Vector3d(sv.X-dsn*sn.X,sv.Y-dsn*sn.Y,sv.Z-dsn*sn.Z)
        if pj.Length<0.01: pj=rg.Vector3d(0,0,1)
        pj.Unitize(); fw=rg.Vector3d.CrossProduct(sn,pj)
        if not fw.Unitize(): continue
        fl=FIN_LEN*S; ft=FIN_THICK*S; bo=sn*(0.02*S)
        c1=rg.Point3d(nd.X+bo.X-fw.X*ft*0.5,nd.Y+bo.Y-fw.Y*ft*0.5,nd.Z+bo.Z)
        c2=rg.Point3d(c1.X+fw.X*ft,c1.Y+fw.Y*ft,c1.Z)
        c3=rg.Point3d(c2.X+sn.X*fl,c2.Y+sn.Y*fl,c2.Z+sn.Z*fl)
        c4=rg.Point3d(c1.X+sn.X*fl,c1.Y+sn.Y*fl,c1.Z+sn.Z*fl)
        fs=rg.NurbsSurface.CreateFromCorners(c1,c2,c3,c4)
        if fs: doc.Objects.AddSurface(fs,afn)

# ── G: Floor slabs ────────────────────────────────────────────────────────────
nfl=int(HEIGHT/FLOOR_H)
for fi in range(1,nfl+1):
    zf=float(fi)*FLOOR_H/HEIGHT
    if zf>=1.0: break
    z=zf*HEIGHT*S; tw=math.radians(TWIST_DEG*zf); r=tower_r(zf)-SLAB_IN
    if r<=0.5: continue
    sr=[rg.Point3d(sqxy(2.0*math.pi*p/PROFILE_PTS+tw,r*S,SQUIRCLE_N)[0],
                   sqxy(2.0*math.pi*p/PROFILE_PTS+tw,r*S,SQUIRCLE_N)[1],z)
        for p in range(PROFILE_PTS)]
    sc2=rg.NurbsCurve.CreateInterpolatedCurve(sr,3,rg.CurveKnotStyle.ChordPeriodic)
    if not sc2: sr.append(sr[0]); sc2=rg.NurbsCurve.CreateInterpolatedCurve(sr,3)
    if not sc2: continue
    try:
        ex=rg.Extrusion.Create(sc2,SLAB_T*S,True)
        if ex: doc.Objects.AddExtrusion(ex,asl); continue
    except: pass
    flat=rg.Brep.CreatePlanarBreps(sc2,tol)
    if flat:
        for fb in flat: doc.Objects.AddBrep(fb,asl)

# ── H: Branching columns ──────────────────────────────────────────────────────
def grow(st,dr,ln,rad,dep,out):
    en=rg.Point3d(st.X+dr.X*ln,st.Y+dr.Y*ln,st.Z+dr.Z*ln)
    pp=rg.Brep.CreatePipe(rg.LineCurve(st,en),rad,True,rg.PipeCapMode.Flat,False,tol,tol)
    if pp: out.extend(pp)
    if dep<COL_DEPTH:
        ar=math.radians(COL_ANGLE); pe=rg.Vector3d(-dr.Y,dr.X,0.0)
        if pe.Length<1e-6: pe=rg.Vector3d(1,0,0)
        pe.Unitize()
        for sg in [1,-1]:
            rt=rg.Transform.Rotation(sg*ar,pe,en); nd2=rg.Vector3d(dr); nd2.Transform(rt); nd2.Unitize()
            grow(en,nd2,ln*0.60,rad*0.62,dep+1,out)

cb=[]
for k in range(COL_N):
    ang=2.0*math.pi*k/COL_N
    xb,yb=sqxy(ang,BASE_R*0.85*S,SQUIRCLE_N)
    grow(rg.Point3d(xb,yb,0.0),rg.Vector3d(0,0,1),COL_H*S,0.44*S,0,cb)
for b in cb: doc.Objects.AddBrep(b,aco)

# ── I: Crown spire ────────────────────────────────────────────────────────────
sr2=[]
for k in range(6):
    t=float(k)/5.0; rs=(SPIRE_BASE_R+(SPIRE_TIP_R-SPIRE_BASE_R)*(t*t))*S
    zs=(HEIGHT+SPIRE_H*t)*S
    sr2.append(rg.Circle(rg.Plane(rg.Point3d(0,0,zs),rg.Vector3d.ZAxis),rs).ToNurbsCurve())
spb=rg.Brep.CreateFromLoft(sr2,rg.Point3d.Unset,rg.Point3d.Unset,rg.LoftType.Normal,False)
if spb:
    for b in spb:
        b2=rg.Brep.CapPlanarHoles(b,tol)
        doc.Objects.AddBrep(b2 if b2 else b,asp)

doc.Views.Redraw()
print("Omega Tower: %d diagrid | BASE_R=%.1f TWIST=%.0f SQUIRCLE=%.1f" % (nm,BASE_R,TWIST_DEG,SQUIRCLE_N))
