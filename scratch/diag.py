import scriptcontext as sc, Rhino, Rhino.Geometry as rg

BASE_R=22.0; WAIST_R=13.5; TOP_R=19.0; HEIGHT=200.0
U_DIVS=20; V_DIVS=36
scale = Rhino.RhinoMath.UnitScale(Rhino.UnitSystem.Meters, sc.doc.ModelUnitSystem)

def smooth_r(a,b,c,t):
    if t<=0.5: s=t*2.0; return a+(b-a)*(s*s*(3-2*s))
    s=(t-0.5)*2.0; return b+(c-b)*(s*s*(3-2*s))

crvs=[]
for i in range(12):
    t=float(i)/11; r=smooth_r(BASE_R,WAIST_R,TOP_R,t)*scale; z=t*HEIGHT*scale
    crvs.append(rg.Circle(rg.Plane(rg.Point3d(0,0,z),rg.Vector3d.ZAxis),r).ToNurbsCurve())
breps=rg.Brep.CreateFromLoft(crvs,rg.Point3d.Unset,rg.Point3d.Unset,rg.LoftType.Normal,False)
face=breps[0].Faces[0]
face.SetDomain(0,rg.Interval(0,1)); face.SetDomain(1,rg.Interval(0,1))

print("Brep faces:", breps[0].Faces.Count)
p0=face.PointAt(0.0, 0.5)
p1=face.PointAt(1.0, 0.5)
print("PointAt(0,0.5): %.3f %.3f %.3f" % (p0.X, p0.Y, p0.Z))
print("PointAt(1,0.5): %.3f %.3f %.3f" % (p1.X, p1.Y, p1.Z))
print("U seam distance: %.4f" % p0.DistanceTo(p1))
print("IsClosed U:", face.IsClosed(0))
print("IsPeriodic U:", face.IsPeriodic(0))

def gpt(i,j): return face.PointAt(float(i%U_DIVS)/U_DIVS, float(j)/V_DIVS)
def cc(i,j): return face.PointAt(((i+0.5)/float(U_DIVS))%1.0, (j+0.5)/float(V_DIVS))

import math
cell_w = 2*math.pi*22*scale/U_DIVS
print("Expected cell width ~: %.2f" % cell_w)

# Check bounding box of each seam panel type
print("--- TypeB seam panels (i=19) ---")
for j in [0,17,35]:
    A=cc(19,j); B=gpt(20,j); C=cc(0,j); D=gpt(20,j+1)
    bb=rg.BoundingBox([A,B,C,D])
    print("  j=%d diag=%.2f" % (j, bb.Diagonal.Length))

print("--- TypeA seam panels (i=19) ---")
for j in [0,17,34]:
    A=cc(19,j); B=gpt(20,j+1); C=cc(19,j+1); D=gpt(19,j+1)
    bb=rg.BoundingBox([A,B,C,D])
    print("  j=%d diag=%.2f" % (j, bb.Diagonal.Length))

print("--- Normal TypeB (i=10) ---")
A=cc(10,18); B=gpt(11,18); C=cc(11,18); D=gpt(11,19)
bb=rg.BoundingBox([A,B,C,D])
print("  diag=%.2f" % bb.Diagonal.Length)
