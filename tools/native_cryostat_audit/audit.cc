// Read-only native text geometry and GPS POSITION audit. No particle/event API.
#include "G4tgbVolumeMgr.hh"
#include "G4LogicalVolume.hh"
#include "G4LogicalVolumeStore.hh"
#include "G4PhysicalVolumeStore.hh"
#include "G4SolidStore.hh"
#include "G4Material.hh"
#include "G4Element.hh"
#include "G4Box.hh"
#include "G4Tubs.hh"
#include "G4BooleanSolid.hh"
#include "G4DisplacedSolid.hh"
#include "G4Transform3D.hh"
#include "G4SPSPosDistribution.hh"
#include "G4SPSRandomGenerator.hh"
#include "G4TransportationManager.hh"
#include "G4Navigator.hh"
#include "G4TouchableHistory.hh"
#include "G4GeometryManager.hh"
#include "G4SystemOfUnits.hh"
#include "G4Version.hh"
#include "Randomize.hh"
#include <filesystem>
#include <chrono>
#include <cmath>
#include <cerrno>
#include <cstring>
#include <iomanip>
#include <iostream>
#include <limits>
#include <locale>
#include <memory>
#include <sstream>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <vector>
#include <fcntl.h>
#include <unistd.h>

#if G4VERSION_NUMBER != 1132
#error "This bounded audit requires the recorded Geant4 11.3.2 runtime"
#endif

namespace fs = std::filesystem;
using Clock = std::chrono::steady_clock;
using Fields = std::vector<std::pair<std::string, std::string>>;
using Rows = std::vector<std::string>;

void require(bool condition, const std::string& message) {
  if (!condition) throw std::runtime_error(message);
}
double seconds(Clock::time_point since) {
  return std::chrono::duration<double>(Clock::now() - since).count();
}
std::string jsonString(const std::string& value) {
  std::ostringstream out;
  out << '"';
  for (unsigned char c : value) {
    switch (c) {
      case '"': out << "\\\""; break;
      case '\\': out << "\\\\"; break;
      case '\b': out << "\\b"; break;
      case '\f': out << "\\f"; break;
      case '\n': out << "\\n"; break;
      case '\r': out << "\\r"; break;
      case '\t': out << "\\t"; break;
      default:
        if (c < 0x20) out << "\\u00" << std::hex << std::setw(2)
                          << std::setfill('0') << static_cast<unsigned>(c) << std::dec;
        else out << static_cast<char>(c);
    }
  }
  out << '"';
  return out.str();
}
std::string number(double value) {
  if (!std::isfinite(value)) return "null";
  if (value == 0 && std::signbit(value)) return "-0.0";
  std::ostringstream out;
  out.imbue(std::locale::classic());
  out << std::setprecision(std::numeric_limits<double>::max_digits10) << value;
  return out.str();
}
std::string boolean(bool value) { return value ? "true" : "false"; }
std::string object(const Fields& fields) {
  std::string out = "{";
  for (std::size_t i = 0; i < fields.size(); ++i) {
    if (i) out += ',';
    out += jsonString(fields[i].first) + ':' + fields[i].second;
  }
  return out + '}';
}
std::string array(const Rows& rows) {
  std::string out = "[";
  for (std::size_t i = 0; i < rows.size(); ++i) {
    if (i) out += ',';
    out += rows[i];
  }
  return out + ']';
}
std::string vector(const G4ThreeVector& v, double unit = mm) {
  return array({number(v.x()/unit), number(v.y()/unit), number(v.z()/unit)});
}
bool finite(const G4ThreeVector& v) {
  return std::isfinite(v.x()) && std::isfinite(v.y()) && std::isfinite(v.z());
}
std::string matrix(const G4RotationMatrix& r) {
  return array({array({number(r.xx()),number(r.xy()),number(r.xz())}),
                array({number(r.yx()),number(r.yy()),number(r.yz())}),
                array({number(r.zx()),number(r.zy()),number(r.zz())})});
}
std::string chain(const std::vector<int>& copies) {
  Rows rows;
  for (int copy : copies) rows.push_back(std::to_string(copy));
  return array(rows);
}
std::string inside(EInside value) {
  return value == kInside ? "inside" : value == kSurface ? "surface" : "outside";
}

// Exact output names and exclusive file creation make partial checkpoints durable.
void checkpoint(const fs::path& dir, const char* name, const std::string& json) {
  const auto path = dir/name;
  int flags = O_WRONLY|O_CREAT|O_EXCL;
#ifdef O_NOFOLLOW
  flags |= O_NOFOLLOW;
#endif
  int fd = ::open(path.c_str(), flags, 0600);
  require(fd >= 0, "checkpoint creation failed: " + path.string() + ": " + std::strerror(errno));
  const std::string bytes = json + '\n';
  std::size_t written = 0;
  while (written < bytes.size()) {
    const auto count = ::write(fd, bytes.data()+written, bytes.size()-written);
    if (count < 0 && errno == EINTR) continue;
    if (count <= 0) { ::close(fd); throw std::runtime_error("checkpoint write failed: " + path.string()); }
    written += static_cast<std::size_t>(count);
  }
  const int synced = ::fsync(fd);
  const int closed = ::close(fd);
  require(synced == 0 && closed == 0, "checkpoint sync/close failed: " + path.string());
  int parent = ::open(dir.c_str(), O_RDONLY|O_DIRECTORY);
  require(parent >= 0, "checkpoint directory open failed");
  const int parentSynced = ::fsync(parent);
  const int parentClosed = ::close(parent);
  require(parentSynced == 0 && parentClosed == 0, "checkpoint directory sync failed");
  std::cout << "checkpoint " << name << " flushed\n" << std::flush;
}
fs::path exactPath(const char* argument, const fs::path& expected) {
  const auto path = fs::absolute(argument).lexically_normal();
  require(path == expected.lexically_normal(), "unexpected audit input/output path");
  require(fs::weakly_canonical(path) == path, "linked audit path refused");
  return path;
}
Fields common(const char* kind, const std::string& status, const std::string& error,
              Clock::time_point start, const Fields& times) {
  return {{"schema_version","1"},{"kind",jsonString(kind)},{"status",jsonString(status)},
          {"error",error.empty() ? "null" : jsonString(error)},
          {"geant4_version_number",std::to_string(G4VERSION_NUMBER)},
          {"runtime",object({{"geant4_version_number",std::to_string(G4VERSION_NUMBER)},
                              {"geant4_version",jsonString(G4Version)},
                              {"compiler",jsonString(__VERSION__)},
                              {"rng_engine",jsonString(G4Random::getTheEngine()->name())},
                              {"cplusplus",std::to_string(__cplusplus)}})},
          {"elapsed_seconds",number(seconds(start))},{"stage_wall_seconds",object(times)}};
}
struct Node {
  G4VPhysicalVolume* pv;
  G4Transform3D global;
  std::string path, motherPath;
  std::vector<int> copies;
};
void walk(G4VPhysicalVolume* pv, const G4Transform3D& parent, const std::string& mother,
          std::vector<int> copies, std::vector<Node>& out,
          std::unordered_set<G4VPhysicalVolume*>& ancestry) {
  require(pv && ancestry.insert(pv).second, "null volume or cyclic geometry hierarchy");
  require(!pv->IsReplicated() && !pv->IsParameterised(), "unexpected replica/parameterised volume");
  const auto path = mother + '/' + std::string(pv->GetName());
  copies.push_back(pv->GetCopyNo());
  const auto global = parent*G4Transform3D(pv->GetObjectRotationValue(),pv->GetObjectTranslation());
  out.push_back({pv,global,path,mother,copies});
  auto* logical = pv->GetLogicalVolume();
  require(logical && logical->GetSolid() && logical->GetMaterial(), "incomplete native logical volume");
  for (int i = 0; i < logical->GetNoDaughters(); ++i)
    walk(logical->GetDaughter(i),global,path,copies,out,ancestry);
  ancestry.erase(pv);
}
std::string nodeRow(const Node& n) {
  auto* frame = n.pv->GetFrameRotation();
  return object({{"name",jsonString(n.pv->GetName())},
                 {"logical_name",jsonString(n.pv->GetLogicalVolume()->GetName())},
                 {"path",jsonString(n.path)},{"copy_chain",chain(n.copies)},
                 {"copy_number",std::to_string(n.pv->GetCopyNo())},
                 {"mother_path",n.motherPath.empty() ? "null" : jsonString(n.motherPath)},
                 {"translation_parent_mm",vector(n.pv->GetObjectTranslation())},
                 {"rotation_object_to_parent",matrix(n.pv->GetObjectRotationValue())},
                 {"rotation_frame",matrix(frame ? *frame : G4RotationMatrix())},
                 // Physical-volume frame translation is -t, not -R^-1*t.
                 {"translation_frame_mm",vector(n.pv->GetFrameTranslation())},
                 {"translation_global_mm",vector(n.global.getTranslation())},
                 {"rotation_object_to_global",matrix(n.global.getRotation())}});
}
using SolidIDs = std::unordered_map<const G4VSolid*,std::size_t>;
std::string solidID(const SolidIDs& ids, const G4VSolid* solid) {
  const auto found = ids.find(solid);
  require(found != ids.end(), "native constituent is absent from full solid store");
  return std::to_string(found->second);
}
Fields solidFields(G4VSolid* solid, const SolidIDs& ids) {
  Rows constituents;
  if (auto* booleanSolid = dynamic_cast<G4BooleanSolid*>(solid)) {
    constituents.push_back(solidID(ids,booleanSolid->GetConstituentSolid(0)));
    constituents.push_back(solidID(ids,booleanSolid->GetConstituentSolid(1)));
  }
  auto* moved = dynamic_cast<G4DisplacedSolid*>(solid);
  return {{"id",solidID(ids,solid)},{"name",jsonString(solid->GetName())},
          {"entity_type",jsonString(solid->GetEntityType())},{"constituents",array(constituents)},
          {"moved_solid_id",moved ? solidID(ids,moved->GetConstituentMovedSolid()) : "null"},
          {"moved_rotation_object",moved ? matrix(moved->GetObjectRotation()) : "null"},
          {"moved_rotation_frame",moved ? matrix(moved->GetFrameRotation()) : "null"},
          {"moved_translation_object_mm",moved ? vector(moved->GetObjectTranslation()) : "null"},
          // Displaced-solid frame translation uses its inverse affine transform.
          {"moved_translation_frame_mm",moved ? vector(moved->GetFrameTranslation()) : "null"}};
}
std::string logicalRow(G4LogicalVolume* logical, const SolidIDs& ids) {
  auto* material = logical->GetMaterial();
  require(material && logical->GetSolid(), "native logical material/solid missing");
  Rows elements;
  const auto* fractions = material->GetFractionVector();
  require(fractions, "native material mass-fraction vector missing");
  for (std::size_t e = 0; e < material->GetNumberOfElements(); ++e) {
    auto* element = material->GetElement(e);
    elements.push_back(object({{"name",jsonString(element->GetName())},
                               {"symbol",jsonString(element->GetSymbol())},
                               {"z",number(element->GetZ())},
                               {"a_g_mole",number(element->GetA()/(g/mole))},
                               {"mass_fraction",number(fractions[e])}}));
  }
  return object({{"name",jsonString(logical->GetName())},{"material",jsonString(material->GetName())},
                 {"solid_name",jsonString(logical->GetSolid()->GetName())},
                 {"solid_id",solidID(ids,logical->GetSolid())},
                 {"density_g_cm3",number(material->GetDensity()/(g/cm3))},
                 {"elements",array(elements)}});
}
std::string navigatorIdentity(G4Navigator* navigator, G4VPhysicalVolume* located) {
  if (!located) return "null";
  std::unique_ptr<G4TouchableHistory> history(navigator->CreateTouchableHistory());
  require(bool(history), "native navigator touchable missing");
  std::string path;
  std::vector<int> copies;
  for (int depth = history->GetHistoryDepth(); depth >= 0; --depth) {
    auto* pv = history->GetVolume(depth);
    require(pv, "native navigator ancestry missing");
    path += '/' + std::string(pv->GetName());
    copies.push_back(history->GetCopyNumber(depth));
  }
  return object({{"name",jsonString(located->GetName())},
                 {"logical_name",jsonString(located->GetLogicalVolume()->GetName())},
                 {"path",jsonString(path)},{"copy_chain",chain(copies)},
                 {"copy_number",std::to_string(history->GetCopyNumber())}});
}
std::string originalSettings() {
  return object({{"particle",jsonString("gamma")},{"energy_keV",number(59.5)},
                 {"type",jsonString("Volume")},{"shape",jsonString("Cylinder")},
                 {"centre_mm",vector(G4ThreeVector(37.077,0,0)*mm)},
                 {"rot1",vector(G4ThreeVector(0,1,0),1)},
                 {"rot2",vector(G4ThreeVector(0,0,1),1)},
                 {"half_length_mm",number(.002)},{"radius_mm",number(1.62)},
                 {"confine",jsonString("Active")}});
}

int main(int argc, char** argv) {
  const auto started = Clock::now();
  fs::path output;
  std::string stage;
  auto tick = started;
  std::string timingKey;
  Fields times;
  Rows logicalRows, physicalRows, importSolids, geometrySolids, overlaps, probes, positions;
  std::string getters = "null";
  bool geometryFailed = false, structuralFailed = false, gpsFailed = false;
  auto writeImport = [&](const std::string& status, const std::string& error) {
    auto fields = common("cryostat_native_import_v1",status,error,started,times);
    fields.insert(fields.end(),{{"logical_volumes",array(logicalRows)},
                               {"physical_volumes",array(physicalRows)},
                               {"solids",array(importSolids)}});
    checkpoint(output,"import.json",object(fields));
  };
  auto writeGeometry = [&](const std::string& status, const std::string& error) {
    auto fields = common("cryostat_native_geometry_v1",status,error,started,times);
    fields.insert(fields.end(),{{"overlap_seed","26092632"},{"overlap_samples","10000"},
                               {"solids",array(geometrySolids)},{"overlaps",array(overlaps)},
                               {"probes",array(probes)}});
    checkpoint(output,"geometry.json",object(fields));
  };
  auto writeGPS = [&](const std::string& status, const std::string& error) {
    auto fields = common("cryostat_native_gps_v1",status,error,started,times);
    fields.insert(fields.end(),{{"original_settings",originalSettings()},{"native_getters",getters},
                               {"seed","26100161"},{"requested_positions","1000"},
                               {"positions",array(positions)},
                               {"raw_internal_rejection_count_unknown","null"}});
    checkpoint(output,"gps.json",object(fields));
  };
  try {
    require(argc == 3, "usage: cryostat_native_audit EXACT-LBNLcryostat.tg FRESH-native-directory");
    require(G4VERSION_NUMBER == 1132, "unexpected Geant4 runtime version");
    const fs::path root(AUDIT_PROJECT_ROOT);
    const auto input = exactPath(argv[1],root/".local/transport/LBNL/LBNLcryostat.tg");
    output = exactPath(argv[2],root/".local/m11f-cryostat-native-v1/native");
    require(fs::is_regular_file(input), "exact original input absent");
    require(!fs::exists(output), "native output root already exists; no overwrite allowed");
    require(fs::is_directory(output.parent_path()), "native evidence parent absent");
    require(fs::create_directory(output), "fresh native output root creation failed");
    stage = "import";
    std::cout << "stage native_import start; gamma/59.5keV are metadata only\n" << std::flush;
    tick = Clock::now();
    timingKey = "native_import";
    fs::current_path(input.parent_path());
    auto* manager = G4tgbVolumeMgr::GetInstance();
    manager->AddTextFile(input.filename().string());
    auto* world = manager->ReadAndConstructDetector();
    require(world, "native text import returned null world");
    times.push_back({"native_import",number(seconds(tick))});
    tick = Clock::now();
    timingKey = "census_materials_transforms";
    auto* store = G4SolidStore::GetInstance();
    SolidIDs ids;
    for (std::size_t i = 0; i < store->size(); ++i) {
      require((*store)[i] && ids.emplace((*store)[i],i).second, "null/duplicate native solid store object");
    }
    for (auto* solid : *store) importSolids.push_back(object(solidFields(solid,ids)));
    for (auto* logical : *G4LogicalVolumeStore::GetInstance()) logicalRows.push_back(logicalRow(logical,ids));
    std::vector<Node> nodes;
    std::unordered_set<G4VPhysicalVolume*> ancestry;
    walk(world,G4Transform3D(),"",{},nodes,ancestry);
    std::unordered_set<G4VPhysicalVolume*> visited;
    for (const auto& node : nodes) {
      require(visited.insert(node.pv).second, "unexpected reused placement object");
      physicalRows.push_back(nodeRow(node));
    }
    require(visited.size() == G4PhysicalVolumeStore::GetInstance()->size(), "unwalked native physical store object");
    times.push_back({"census_materials_transforms",number(seconds(tick))});
    writeImport("completed",""); // No unsafe bounds, overlap or GPS call precedes this flush.

    const Node* active = nullptr;
    for (const auto& node : nodes) if (node.pv->GetName() == "Active") {
      require(!active, "ambiguous native Active physical volume");
      active = &node;
    }
    require(active, "native Active physical volume absent");
    stage = "geometry";
    times.clear();
    tick = Clock::now();
    timingKey = "solid_diagnostics";
    std::cout << "stage solid_diagnostics start; Boolean cubic volumes not_run\n" << std::flush;
    for (auto* solid : *store) {
      std::cout << "solid bounds id=" << ids.at(solid) << " name=" << solid->GetName() << '\n' << std::flush;
      auto fields = solidFields(solid,ids);
      G4ThreeVector lower, upper;
      solid->BoundingLimits(lower,upper);
      const bool boundsFinite = finite(lower) && finite(upper);
      const bool boundsOrdered = boundsFinite && lower.x()<upper.x() && lower.y()<upper.y() && lower.z()<upper.z();
      Fields parameters;
      std::string valid = "null", volume = "null", method = "not_applicable";
      if (auto* box = dynamic_cast<G4Box*>(solid)) {
        const G4ThreeVector half(box->GetXHalfLength(),box->GetYHalfLength(),box->GetZHalfLength());
        const auto cubic = box->GetCubicVolume()/(mm*mm*mm);
        const bool good = finite(half) && half.x()>0 && half.y()>0 && half.z()>0 && std::isfinite(cubic) && cubic>0;
        parameters = {{"half_lengths_mm",vector(half)}};
        valid = boolean(good); volume = number(cubic); method = "analytic_primitive";
        geometryFailed |= !good;
      } else if (auto* tubs = dynamic_cast<G4Tubs*>(solid)) {
        const auto r0 = tubs->GetInnerRadius(), r = tubs->GetOuterRadius(), z = tubs->GetZHalfLength();
        const auto phi = tubs->GetStartPhiAngle(), delta = tubs->GetDeltaPhiAngle();
        const auto cubic = tubs->GetCubicVolume()/(mm*mm*mm);
        const bool good = std::isfinite(r0) && std::isfinite(r) && std::isfinite(z) && std::isfinite(phi) && std::isfinite(delta)
                          && r0>=0 && r>r0 && z>0 && delta>0 && std::isfinite(cubic) && cubic>0;
        parameters = {{"inner_radius_mm",number(r0/mm)},{"outer_radius_mm",number(r/mm)},
                      {"half_length_mm",number(z/mm)},{"start_angle_rad",number(phi/rad)},
                      {"delta_angle_rad",number(delta/rad)}};
        valid = boolean(good); volume = number(cubic); method = "analytic_primitive";
        geometryFailed |= !good;
      } else if (dynamic_cast<G4BooleanSolid*>(solid)) method = "not_run_stochastic_boolean";
      geometryFailed |= !boundsOrdered;
      fields.insert(fields.end(),{{"bounding_min_mm",vector(lower)},{"bounding_max_mm",vector(upper)},
                                 {"bounds_finite",boolean(boundsFinite)},{"bounds_ordered",boolean(boundsOrdered)},
                                 {"primitive_parameters",object(parameters)},{"primitive_parameters_valid",valid},
                                 {"volume_mm3",volume},{"volume_method",jsonString(method)}});
      geometrySolids.push_back(object(fields));
    }
    struct Probe { const char* name; G4ThreeVector local; EInside expected; };
    const std::vector<Probe> selected = {{"centre",{},kInside}, {"radial_inside",{1.60,0,0},kInside},
      {"axial_inside",{0,0,.0009},kInside}, {"radial_outside",{1.615,0,0},kOutside},
      {"axial_outside",{0,0,.0015},kOutside}, {"envelope_edge",{1.62,0,.002},kOutside}};
    for (const auto& probe : selected) {
      const auto local = probe.local*mm;
      const auto classification = active->pv->GetLogicalVolume()->GetSolid()->Inside(local);
      const auto global = active->global.getRotation()*local + active->global.getTranslation();
      geometryFailed |= classification != probe.expected;
      probes.push_back(object({{"name",jsonString(probe.name)},{"source_local_mm",vector(local)},
                               {"global_mm",vector(global)},{"source_inside",jsonString(inside(classification))},
                               {"expected_source_inside",jsonString(inside(probe.expected))}}));
    }
    times.push_back({"solid_diagnostics",number(seconds(tick))});
    // Unsafe continuation is refused when even structural/primitive bounds fail.
    if (!geometryFailed) {
      tick = Clock::now();
      timingKey = "overlaps";
      G4Random::setTheSeed(26092632);
      for (std::size_t i = 1; i < nodes.size(); ++i) {
        const auto& node = nodes[i];
        std::cout << "overlap path=" << node.path << " copies=" << chain(node.copies) << '\n' << std::flush;
        const bool hit = node.pv->CheckOverlaps(10000,0,true,100);
        geometryFailed |= hit;
        overlaps.push_back(object({{"path",jsonString(node.path)},{"copy_chain",chain(node.copies)},
                                  {"reported_overlap",boolean(hit)}}));
      }
      times.push_back({"overlaps",number(seconds(tick))});
    } else times.push_back({"overlaps","null"});
    structuralFailed = geometrySolids.size()!=store->size() || probes.size()!=selected.size()
                       || overlaps.empty();
    writeGeometry(geometryFailed ? "completed_with_geometry_failures" : "completed","");

    stage = "gps";
    times.clear();
    if (structuralFailed) {
      times.push_back({"gps_position_confinement","null"});
      writeGPS("incomplete","GPS not executed after invalid structural/primitive diagnostics");
      return 2;
    }
    tick = Clock::now();
    timingKey = "gps_position_confinement";
    std::cout << "stage gps_position_confinement start; no primaries or tracking\n" << std::flush;
    auto* navigator = G4TransportationManager::GetTransportationManager()->GetNavigatorForTracking();
    require(navigator, "native tracking navigator absent");
    navigator->SetWorldVolume(world);
    require(G4GeometryManager::GetInstance()->CloseGeometry(true,false,world), "native CloseGeometry failed");
    G4SPSRandomGenerator bias;
    G4SPSPosDistribution distribution;
    distribution.SetBiasRndm(&bias);
    distribution.SetPosDisType("Volume");
    distribution.SetPosDisShape("Cylinder");
    distribution.SetCentreCoords(G4ThreeVector(37.077,0,0)*mm);
    distribution.SetPosRot1(G4ThreeVector(0,1,0));
    distribution.SetPosRot2(G4ThreeVector(0,0,1));
    distribution.SetHalfZ(.002*mm);
    distribution.SetRadius(1.62*mm);
    distribution.ConfineSourceToVolume("Active");
    getters = object({{"type",jsonString(distribution.GetPosDisType())},{"shape",jsonString(distribution.GetPosDisShape())},
                       {"centre_mm",vector(distribution.GetCentreCoords())},
                       {"half_length_mm",number(distribution.GetHalfZ()/mm)},
                       {"radius_mm",number(distribution.GetRadius()/mm)},
                       {"inner_radius_mm",number(distribution.GetRadius0()/mm)},
                       {"basis_x",vector(distribution.GetRotx(),1)},
                       {"basis_y",vector(distribution.GetRoty(),1)},
                       {"basis_z",vector(distribution.GetRotz(),1)},
                       {"confined",boolean(distribution.GetConfined())},
                       {"confine",jsonString(distribution.GetConfineVolume())}});
    require(distribution.GetConfined() && distribution.GetConfineVolume()=="Active", "native GPS confinement is inactive/wrong");
    G4Random::setTheSeed(26100161); // Independent phase; overlap RNG consumption cannot retime this seed.
    const auto inverse = active->global.inverse();
    for (int i = 0; i < 1000; ++i) {
      const auto global = distribution.GenerateOne();
      const auto local = inverse.getRotation()*global + inverse.getTranslation();
      const auto classification = active->pv->GetLogicalVolume()->GetSolid()->Inside(local);
      auto* located = navigator->LocateGlobalPointAndSetup(global,nullptr,false,true);
      const auto identity = navigatorIdentity(navigator,located);
      gpsFailed |= !finite(global) || !finite(local) || classification != kInside || located != active->pv;
      positions.push_back(object({{"index",std::to_string(i)},{"global_mm",vector(global)},
                                  {"source_local_mm",vector(local)},{"source_inside",jsonString(inside(classification))},
                                  {"native_navigator_identity",identity}}));
    }
    times.push_back({"gps_position_confinement",number(seconds(tick))});
    writeGPS(gpsFailed ? "failed" : "completed",gpsFailed ? "one or more native GPS positions failed strict Active checks" : "");
    return geometryFailed || gpsFailed ? 2 : 0;
  } catch (const std::exception& error) {
    std::cerr << "cryostat_native_audit stage=" << stage << ": " << error.what() << '\n' << std::flush;
    bool timeAlreadyRecorded = false;
    for (const auto& time : times) timeAlreadyRecorded |= time.first==timingKey;
    if (!timingKey.empty() && !timeAlreadyRecorded) times.push_back({timingKey,number(seconds(tick))});
    try {
      if (!output.empty() && fs::is_directory(output)) {
        if (stage == "import" && !fs::exists(output/"import.json")) writeImport("incomplete",error.what());
        else if (stage == "geometry" && !fs::exists(output/"geometry.json")) writeGeometry("incomplete",error.what());
        else if (stage == "gps" && !fs::exists(output/"gps.json")) writeGPS("incomplete",error.what());
      }
    } catch (const std::exception& receiptError) {
      std::cerr << "partial checkpoint failure: " << receiptError.what() << '\n' << std::flush;
    }
    return 1;
  }
}
