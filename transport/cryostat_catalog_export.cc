// Catalog-only derived exporter: cryostat_export.cc af44c9893e4576151511b185989ff1bc88431b36261d2d3b2607640d335e767b
// Same nominal assembly/checks; generic native Geant4 solid gate replaces polycone-only admission.
// Native text importer, nominal assembly, and checks. No upstream parser/copy.
#include "G4tgbVolumeMgr.hh"
#include "G4GDMLParser.hh"
#include "G4LogicalVolume.hh"
#include "G4Material.hh"
#include "G4Element.hh"
#include "G4NistManager.hh"
#include "G4PVPlacement.hh"
#include "G4Tubs.hh"
#include "G4Transform3D.hh"
#include "G4SystemOfUnits.hh"
#include "G4Version.hh"
#include "G4VSolid.hh"
#include "Randomize.hh"
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <vector>
#include <cmath>
namespace fs = std::filesystem;
void require(bool b, const char* s) { if (!b) throw std::runtime_error(s); }
fs::path checked(const char* s) {
  auto p=fs::absolute(s).lexically_normal(), base=fs::path(PROJECT_LOCAL).lexically_normal();
  auto rel=p.lexically_relative(base);
  require(!rel.empty() && rel!="." && !rel.is_absolute(),"path must be below .local");
  for(auto part:rel) require(part!="..","path escapes .local");
  require(fs::weakly_canonical(p)==p,"linked path refused"); return p;
}
struct Node { G4VPhysicalVolume* pv; G4Transform3D global; std::string path, original; };
void walk(G4VPhysicalVolume* pv, const G4Transform3D& parent, const std::string& path,
          std::vector<Node>& out) {
  G4Transform3D here(pv->GetObjectRotationValue(),pv->GetObjectTranslation());
  auto global=parent*here; auto name=std::string(pv->GetName());
  out.push_back({pv,global,path+"/"+name,name});
  auto* lv=pv->GetLogicalVolume();
  for(int i=0;i<lv->GetNoDaughters();++i) walk(lv->GetDaughter(i),global,path+"/"+name,out);
}
void vec(std::ostream& o,const G4ThreeVector& p) { o<<'['<<p.x()/mm<<','<<p.y()/mm<<','<<p.z()/mm<<']'; }
int main(int argc,char** argv) {
 try {
  require(argc==7,"usage: cryostat_export stage.tg canonical.gdml probes.txt parameters.txt NEW.gdml NEW-report.json");
  auto stage=checked(argv[1]), canonical=checked(argv[2]), probes=checked(argv[3]);
  auto parameters=checked(argv[4]), output=checked(argv[5]), report=checked(argv[6]);
  require(!fs::exists(output)&&!fs::exists(report),"output exists");
  // Numeric parameters are generated from the separately hashed nominal JSON.
  std::ifstream in(parameters); double tx,ty,tz,vx,vy,vz,sx,sy,sz,sr,st,cx,cy,cz,cr,ct,cw;
  int samples; std::string extra;
  require(bool(in>>tx>>ty>>tz>>vx>>vy>>vz>>sx>>sy>>sz>>sr>>st>>cx>>cy>>cz>>cr>>ct>>cw>>samples)
          && !(in>>extra),"invalid parameter file");
  require(sr>0&&st>0&&cr>cw&&ct>2*cw&&cw>0&&samples>=1000,"invalid dimensions/check budget");
  G4Random::setTheSeed(26092632);
  G4GDMLParser crystalParser; crystalParser.SetStripFlag(false);
  crystalParser.Read(canonical.string(),false);
  auto* ge=crystalParser.GetVolume("germanium");
  require(ge && ge->GetSolid(),"canonical solid missing");
  const auto solidType=ge->GetSolid()->GetEntityType();
  require(solidType=="G4GenericPolycone" || solidType=="G4Tubs" || solidType=="G4Box"
          || solidType=="G4MultiUnion" || solidType=="G4UnionSolid"
          || solidType=="G4IntersectionSolid" || solidType=="G4SubtractionSolid",
          "unsupported canonical catalog solid");
  // Includes resolve relative to the unchanged upstream directory.
  fs::current_path(stage.parent_path());
  auto* mgr=G4tgbVolumeMgr::GetInstance(); mgr->AddTextFile(stage.filename().string());
  auto* world=mgr->ReadAndConstructDetector(); require(world,"text import failed");
  std::vector<Node> original; walk(world,G4Transform3D(),"",original);
  Node* cavity=nullptr;
  for(auto& n:original) if(n.original=="vacuum") { require(!cavity,"ambiguous cavity"); cavity=&n; }
  require(cavity,"missing cavity");
  require((cavity->global.getTranslation()-G4ThreeVector(vx,vy,vz)*mm).mag()<1e-8*mm,"composed cavity translation mismatch");
  auto rotation=cavity->global.getRotation();
  require((rotation*G4ThreeVector(1,0,0)-G4ThreeVector(1,0,0)).mag()<1e-12 &&
          (rotation*G4ThreeVector(0,1,0)-G4ThreeVector(0,1,0)).mag()<1e-12,"unexpected cavity rotation");
  G4RotationMatrix r; r.rotateX(-90*deg); // local +z -> global +y
  auto desired=G4Transform3D(r,G4ThreeVector(tx,ty,tz)*mm);
  auto relative=cavity->global.inverse()*desired;
  new G4PVPlacement(relative,ge,"germanium",cavity->pv->GetLogicalVolume(),false,1,false);
  auto* bn=G4Material::GetMaterial("boron_nitride"); require(bn,"imported BN missing");
  auto* spacer=new G4LogicalVolume(new G4Tubs("nominal_spacer_solid",0,sr*mm,st*mm/2,0,360*deg),bn,"nominal_spacer");
  new G4PVPlacement(G4Transform3D(r,G4ThreeVector(sx,sy,sz)*mm),spacer,"nominal_spacer",cavity->pv->GetLogicalVolume(),false,1,false);
  auto* nist=G4NistManager::Instance();
  auto* cap=new G4LogicalVolume(new G4Tubs("nominal_capsule_solid",0,cr*mm,ct*mm/2,0,360*deg),nist->FindOrBuildMaterial("G4_Al"),"nominal_capsule");
  new G4PVPlacement(G4Transform3D(r,G4ThreeVector(cx,cy,cz)*mm),cap,"nominal_capsule",world->GetLogicalVolume(),false,1,false);
  auto* fill=new G4LogicalVolume(new G4Tubs("nominal_source_fill_solid",0,(cr-cw)*mm,(ct/2-cw)*mm,0,360*deg),nist->FindOrBuildMaterial("G4_POLYETHYLENE"),"nominal_source_fill");
  new G4PVPlacement(nullptr,{},fill,"nominal_source_fill",cap,false,1,false);
  require(fill->GetSolid()->Inside({})==kInside,"source is not inside fill");
  std::vector<Node> nodes; walk(world,G4Transform3D(),"",nodes);
  size_t sourceMatches=0;
  for(const auto& node:nodes) if(node.original=="nominal_source_fill") {
    const auto inverse=node.global.inverse();
    const auto localSource=inverse.getRotation()*(G4ThreeVector(cx,cy,cz)*mm)+inverse.getTranslation();
    require(node.pv->GetLogicalVolume()->GetSolid()->Inside(localSource)==kInside,
            "global source is not inside composed capsule fill");
    ++sourceMatches;
  }
  require(sourceMatches==1,"source fill hierarchy ambiguous");
  bool overlap=false;
  std::ostringstream json; json<<std::setprecision(17)<<"{\"schema_version\":1,\"geant4_version_number\":"<<G4VERSION_NUMBER
    <<",\"overlap_seed\":26092632,\"overlap_samples\":"<<samples
    <<",\"source_inside_fill\":true,\"crystal_volume_mm3\":"<<ge->GetSolid()->GetCubicVolume()/(mm*mm*mm)
    <<",\"volumes\":[";
  for(size_t i=0;i<nodes.size();++i) {
    auto& n=nodes[i]; auto* lv=n.pv->GetLogicalVolume(); auto* m=lv->GetMaterial();
    bool hit=i!=0 && n.pv->CheckOverlaps(samples,0,true,100); overlap|=hit;
    // Unique names make each material ledger registration unambiguous.
    std::string name=i==0 ? "ledger_0_PV" : n.original=="germanium" ? "germanium" : "ledger_"+std::to_string(i);
    n.pv->SetName(name);
    // GDML reconstructs the root physical volume from its logical-volume name.
    if(i==0) lv->SetName("ledger_0");
    if(i) json<<',';
    json<<"{\"name\":"<<std::quoted(name)<<",\"original_path\":"<<std::quoted(n.path)
      <<",\"copy_number\":"<<n.pv->GetCopyNo()<<",\"material\":"<<std::quoted(std::string(m->GetName()))
      <<",\"density_g_cm3\":"<<m->GetDensity()/(g/cm3)<<",\"elements\":[";
    for(size_t e=0;e<m->GetNumberOfElements();++e) {
      if(e)json<<',';
      json<<"{\"name\":"<<std::quoted(std::string(m->GetElement(e)->GetName()))
          <<",\"mass_fraction\":"<<m->GetFractionVector()[e]<<'}';
    }
    json<<"],\"translation_global_mm\":";
    vec(json,n.global.getTranslation()); json<<",\"rotation_local_to_global\":[";
    auto rr=n.global.getRotation();
    const double matrix[3][3]={{rr.xx(),rr.xy(),rr.xz()},{rr.yx(),rr.yy(),rr.yz()},{rr.zx(),rr.zy(),rr.zz()}};
    for(int a=0;a<3;++a) { if(a)json<<','; json<<'['; for(int b=0;b<3;++b){if(b)json<<','; json<<matrix[a][b];} json<<']'; }
    json<<"],\"overlap\":"<<(hit?"true":"false")<<'}';
  }
  json<<"],\"probes\":[";
  std::ifstream pin(probes); double x,y,z; size_t index=0;
  while(pin>>x>>y>>z) { auto c=ge->GetSolid()->Inside(G4ThreeVector(x,y,z)*mm);
    if(index)json<<','; json<<"{\"index\":"<<index++<<",\"classification\":\""<<(c==kInside?"inside":c==kSurface?"surface":"outside")<<"\"}"; }
  require(pin.eof()&&index>0,"bad probes");
  json<<"],\"overlaps_passed\":"<<(overlap?"false":"true")<<"}\n";
  std::ofstream out(report); require(bool(out),"cannot create report"); out<<json.str(); out.close(); require(bool(out),"report write failed");
  G4GDMLParser exporter; exporter.Write(output.string(),world,false);
  require(!overlap,"recursive overlap checks failed; report and GDML retained");
  return 0;
 } catch(const std::exception& e) {std::cerr<<"cryostat_export: "<<e.what()<<'\n';return 1;}
}
