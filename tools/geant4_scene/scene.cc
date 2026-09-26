// Geometry inspection only: no run manager, physics list, fields or beamOn.
#include "G4GDMLParser.hh"
#include "G4Polyhedron.hh"
#include "G4LogicalVolume.hh"
#include "G4VPhysicalVolume.hh"
#include "G4Material.hh"
#include "G4VSolid.hh"
#include "G4Transform3D.hh"
#include "G4SystemOfUnits.hh"
#include "G4Version.hh"
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <cmath>
#include <stdexcept>
#include <vector>
#include <set>
#include <array>
#include <fcntl.h>
#include <unistd.h>
namespace fs = std::filesystem;
void require(bool ok, const char* message) { if (!ok) throw std::runtime_error(message); }
fs::path checked(const char* arg, const fs::path& base) {
  auto p=fs::absolute(arg).lexically_normal();
  auto rel=p.lexically_relative(base);
  require(!rel.empty() && rel!="." && !rel.is_absolute(), "invalid path");
  for (auto part:rel) require(part!="..", "path escapes allowed root");
  require(fs::weakly_canonical(p)==p, "linked path refused");
  return p;
}
void quoted(std::ostream& o, const std::string& s) {
  o << '"';
  for (unsigned char c:s) {
    if (c=='"'||c=='\\') o << '\\' << c;
    else if(c<32) o << "\\u" << std::hex << std::setw(4) << std::setfill('0') << int(c) << std::dec;
    else o << c;
  }
  o << '"';
}
void vec(std::ostream& o, const G4ThreeVector& p) {
  require(std::isfinite(p.x())&&std::isfinite(p.y())&&std::isfinite(p.z()), "nonfinite vertex");
  o << '[' << p.x()/mm << ',' << p.y()/mm << ',' << p.z()/mm << ']';
}
struct Node { G4VPhysicalVolume* pv; G4Transform3D global; int parent; };
void walk(G4VPhysicalVolume* pv,const G4Transform3D& parent,int parentIndex,std::vector<Node>& nodes) {
  require(!pv->IsReplicated() && !pv->GetParameterisation(), "replicas/parameterisation unsupported");
  auto global=parent*G4Transform3D(pv->GetObjectRotationValue(),pv->GetObjectTranslation());
  int index=nodes.size(); nodes.push_back({pv,global,parentIndex});
  auto* lv=pv->GetLogicalVolume();
  for(int i=0;i<lv->GetNoDaughters();++i) walk(lv->GetDaughter(i),global,index,nodes);
}
int main(int argc,char** argv) {
 try {
  require(argc==3,"usage: geant4_scene saved-geometry.gdml NEW-scene-native.json");
  require(G4VERSION_NUMBER==1132,"requires pinned Geant4 11.3.2");
  const fs::path root=fs::path(PROJECT_ROOT);
  auto input=checked(argv[1],root/".local/peak-native-delivery/cs10000-v2");
  auto output=checked(argv[2],root/".local/geometry-events-publication/build");
  require(fs::is_regular_file(input),"missing GDML");
  require(!fs::exists(output),"output already exists");
  G4GDMLParser parser; parser.SetStripFlag(false); parser.Read(input.string(),false);
  G4Polyhedron::SetNumberOfRotationSteps(64);
  std::vector<Node> nodes; walk(parser.GetWorldVolume(),G4Transform3D(),-1,nodes);
  // Atomic exclusive reservation: never overwrite even if another writer races.
  int fd=::open(output.c_str(),O_WRONLY|O_CREAT|O_EXCL,0600);
  require(fd>=0,"cannot exclusively create output"); ::close(fd);
  std::ofstream o(output); require(bool(o),"cannot write output"); o<<std::setprecision(17);
  o<<"{\"schema_version\":1,\"geant4_version_number\":"<<G4VERSION_NUMBER
   <<",\"generator\":\"G4GDMLParser/G4Polyhedron\",\"units\":\"mm\",\"rotation_steps\":64,\"volumes\":[";
  for(size_t k=0;k<nodes.size();++k) {
    const auto& n=nodes[k]; auto* lv=n.pv->GetLogicalVolume(); auto* solid=lv->GetSolid();
    // CreatePolyhedron is native for the actual GDML solid, including booleans.
    auto* poly=solid->CreatePolyhedron(); require(poly!=nullptr,"solid has no native polyhedron");
    if(k) o<<',';
    o<<"{\"name\":"; quoted(o,n.pv->GetName()); o<<",\"parent\":"<<n.parent;
    o<<",\"logical_volume\":"; quoted(o,lv->GetName());
    o<<",\"solid_type\":"; quoted(o,solid->GetEntityType());
    o<<",\"copy_number\":"<<n.pv->GetCopyNo()<<",\"material\":"; quoted(o,lv->GetMaterial()->GetName());
    o<<",\"density_g_cm3\":"<<lv->GetMaterial()->GetDensity()/(g/cm3);
    o<<",\"translation_global_mm\":"; vec(o,n.global.getTranslation());
    auto r=n.global.getRotation();
    o<<",\"rotation_local_to_global\":[["<<r.xx()<<','<<r.xy()<<','<<r.xz()<<"],["<<r.yx()<<','<<r.yy()<<','<<r.yz()<<"],["<<r.zx()<<','<<r.zy()<<','<<r.zz()<<"]]";
    o<<",\"vertices_global_mm\":[";
    for(int i=1;i<=poly->GetNoVertices();++i) {
      if(i>1)o<<','; auto p=poly->GetVertex(i);
      auto q=n.global*G4Point3D(p.x(),p.y(),p.z()); vec(o,G4ThreeVector(q.x(),q.y(),q.z()));
    }
    std::vector<std::array<int,3>> triangles; std::set<std::pair<int,int>> edges;
    for(int i=1;i<=poly->GetNoFacets();++i) {
      int count=0, ids[4], flags[4]; poly->GetFacet(i,count,ids,flags);
      require(count==3||count==4,"unsupported polyhedron facet");
      for(int j=0;j<count;++j) require(ids[j]>0&&ids[j]<=poly->GetNoVertices(),"invalid facet index");
      for(int j=1;j+1<count;++j) triangles.push_back({ids[0]-1,ids[j]-1,ids[j+1]-1});
      for(int j=0;j<count;++j) {
        int a=ids[j]-1,b=ids[(j+1)%count]-1;
        // Facet edges, no artificial triangulation diagonal. Retain tessellation edges.
        edges.emplace(std::min(a,b),std::max(a,b));
      }
    }
    o<<"],\"triangles\":[";
    for(size_t j=0;j<triangles.size();++j) {if(j)o<<',';auto t=triangles[j];o<<'['<<t[0]<<','<<t[1]<<','<<t[2]<<']';}
    o<<"],\"wireframe\":["; bool first=true;
    for(auto e:edges){if(!first)o<<',';first=false;o<<'['<<e.first<<','<<e.second<<']';}
    o<<"]}"; delete poly;
  }
  o<<"]}\n"; o.close(); require(bool(o),"output write failed");
  std::cout<<"Exported "<<nodes.size()<<" native placed volumes; no transport executed.\n";
 } catch(const std::exception& e) {std::cerr<<e.what()<<'\n';return 1;}
}
