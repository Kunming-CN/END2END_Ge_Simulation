// Exact visual octagon for the frozen GeGI intersection. Geant4 11.3.2's
// one-child MultiUnion cannot form a display polyhedron, and its Boolean
// processor perturbs coincident faces. Derive the octagon from the UNCHANGED
// native solid's bounds and diagonal distance, then check native occupancy.
// No transport solid, GDML input, material or placement is changed.
#include "G4IntersectionSolid.hh"
#include "G4PolyhedronArbitrary.hh"

G4Polyhedron* gegi_polyhedron(G4VSolid* solid) {
  if (!dynamic_cast<G4IntersectionSolid*>(solid)) return solid->CreatePolyhedron();
  G4ThreeVector low,high; solid->BoundingLimits(low,high);
  require((low+high).mag()<1e-8*mm,"GeGI crystal must be centered");
  require(std::abs(high.x()-45*mm)<1e-8*mm&&std::abs(high.y()-45*mm)<1e-8*mm&&
          std::abs(high.z()-5.5*mm)<1e-8*mm,"only the frozen GeGI octagon is supported");
  G4ThreeVector origin(0,0,0),diagonal(1/std::sqrt(2.),1/std::sqrt(2.),0);
  double r=high.x(),h=high.z(),d=solid->DistanceToOut(origin,diagonal);
  require(std::abs(d-45*mm)<1e-8*mm,"native diagonal crystal radius differs");
  double k=d*std::sqrt(2.)-r;
  std::vector<G4ThreeVector> rim={{r,k,0},{k,r,0},{-k,r,0},{-r,k,0},
                                {-r,-k,0},{-k,-r,0},{k,-r,0},{r,-k,0}};
  auto* poly=new G4PolyhedronArbitrary(16,20);
  for(double z:{-h,h})for(auto p:rim) {
    p.setZ(z);
    require(solid->Inside(p)==kSurface,"derived vertex is not on native GeGI boundary");
    poly->AddVertex(p);
  }
  for(int i=0;i<8;++i) {int j=(i+1)%8;poly->AddFacet(i+1,j+1,j+9,i+9);}
  for(int i=1;i<7;++i) {poly->AddFacet(1,i+2,i+1);poly->AddFacet(9,i+9,i+10);}
  poly->SetReferences();
  // Native face centers must also lie on the exact original boundary.
  for(int i=1;i<=poly->GetNoFacets();++i) {
    int count=0,ids[4],flags[4];poly->GetFacet(i,count,ids,flags);G4ThreeVector p;
    for(int j=0;j<count;++j){auto q=poly->GetVertex(ids[j]);p+=G4ThreeVector(q.x(),q.y(),q.z());}
    p/=count;require(solid->Inside(p)==kSurface,"derived facet is not on native GeGI boundary");
  }
  int checked=0;
  for(int ix=-10;ix<=10;++ix)for(int iy=-10;iy<=10;++iy)for(int iz=-4;iz<=4;++iz) {
    G4ThreeVector p(ix*5.1*mm,iy*5.1*mm,iz*2.1*mm);
    bool expected=std::abs(p.x())<r&&std::abs(p.y())<r&&std::abs(p.z())<h&&
                  std::abs(p.x())+std::abs(p.y())<r+k;
    require((solid->Inside(p)!=kOutside)==expected,"native GeGI crystal occupancy differs");
    ++checked;
  }
  std::cout<<"Exact GeGI octagon: 16 vertices and 20 face centers on native boundary; "
           <<checked<<" deterministic native occupancy points matched.\n";
  return poly;
}
