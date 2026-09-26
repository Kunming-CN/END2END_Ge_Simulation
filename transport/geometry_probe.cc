// Original M2a utility: load the actual generated solid, never reconstruct it.
// No upstream implementation code is copied. Intended for the locked Linux env.
#include "G4GDMLParser.hh"
#include "G4GeometryTolerance.hh"
#include "G4LogicalVolume.hh"
#include "G4LogicalVolumeStore.hh"
#include "G4SystemOfUnits.hh"
#include "G4ThreeVector.hh"
#include "G4Version.hh"
#include "G4VSolid.hh"

#include <cerrno>
#include <cmath>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>
#include <fcntl.h>
#include <unistd.h>

namespace fs = std::filesystem;

fs::path checked_path(const char* argument) {
  const auto base = fs::path(PROJECT_LOCAL).lexically_normal();
  const auto path = fs::absolute(argument).lexically_normal();
  const auto relative = path.lexically_relative(base);
  if (relative.empty() || relative == "." || relative.is_absolute())
    throw std::runtime_error("path must be below project .local");
  for (const auto& part : relative)
    if (part == "..") throw std::runtime_error("path outside project .local");
  auto current = base;
  if (fs::is_symlink(current) || fs::weakly_canonical(base) != base)
    throw std::runtime_error("linked .local root refused");
  for (const auto& part : relative) {
    current /= part;
    if (fs::is_symlink(current)) throw std::runtime_error("symlink path refused");
  }
  return path;
}

void publish_new(const fs::path& output, const std::string& text) {
  const auto partial = output.string() + ".partial";
  if (fs::exists(output) || fs::is_symlink(output))
    throw std::runtime_error("output already exists");
  const int fd = ::open(partial.c_str(), O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW, 0600);
  if (fd < 0) throw std::runtime_error("cannot create new partial output");
  size_t offset = 0;
  while (offset < text.size()) {
    const auto written = ::write(fd, text.data() + offset, text.size() - offset);
    if (written < 0 && errno == EINTR) continue;
    if (written <= 0) {
      ::close(fd);
      throw std::runtime_error("output write failed; partial evidence retained");
    }
    offset += static_cast<size_t>(written);
  }
  const int sync_result = ::fsync(fd);
  const int close_result = ::close(fd);
  if (sync_result != 0 || close_result != 0)
    throw std::runtime_error("output flush failed; partial evidence retained");
  if (::link(partial.c_str(), output.c_str()) != 0)
    throw std::runtime_error("no-clobber publication failed; partial evidence retained");
  if (::unlink(partial.c_str()) != 0)
    throw std::runtime_error("result published, but partial link could not be removed");
}

int main(int argc, char** argv) {
  try {
    if (argc != 4) throw std::runtime_error("usage: geometry_probe geometry.gdml probe-points.txt NEW-result.json");
    const auto gdml = checked_path(argv[1]);
    const auto coordinates = checked_path(argv[2]);
    const auto output = checked_path(argv[3]);
    if (fs::exists(output) || fs::exists(output.string() + ".partial"))
      throw std::runtime_error("output already exists");
    std::ifstream input(coordinates);
    if (!input) throw std::runtime_error("cannot read coordinates");
    std::vector<G4ThreeVector> points;
    std::string line;
    while (std::getline(input, line)) {
      std::istringstream row(line);
      double x, y, z;
      std::string extra;
      if (!(row >> x >> y >> z) || (row >> extra) ||
          !std::isfinite(x) || !std::isfinite(y) || !std::isfinite(z))
        throw std::runtime_error("invalid coordinate row (expected exactly x y z in mm)");
      points.emplace_back(x * mm, y * mm, z * mm);
    }
    if (!input.eof() || points.empty()) throw std::runtime_error("empty/failed coordinate input");
    G4GDMLParser parser;
    parser.SetStripFlag(false);
    parser.Read(gdml.string(), false); // No remote XML schema fetch. G4 constructs the real solid.
    if (!parser.GetWorldVolume()) throw std::runtime_error("GDML world missing");
    G4LogicalVolume* logical = nullptr;
    for (auto* candidate : *G4LogicalVolumeStore::GetInstance()) {
      if (candidate->GetName() != "germanium") continue;
      if (logical) throw std::runtime_error("ambiguous germanium logical volume");
      logical = candidate;
    }
    if (!logical || !logical->GetSolid()) throw std::runtime_error("germanium logical solid missing");
    auto* solid = logical->GetSolid();
    if (solid->GetEntityType() != "G4GenericPolycone")
      throw std::runtime_error("expected original generic polycone solid");
    const double volume = solid->GetCubicVolume() / (mm * mm * mm);
    if (!std::isfinite(volume) || volume <= 0) throw std::runtime_error("invalid G4 solid volume");
    std::ostringstream json;
    json << std::setprecision(17)
         << "{\n  \"schema_version\": 1,\n  \"geant4_version_number\": " << G4VERSION_NUMBER
         << ",\n  \"solid\": \"germanium_solid\",\n  \"coordinate_frame\": \"local_mm\",\n"
         << "  \"volume_mm3\": " << volume << ",\n  \"g4_surface_tolerance_mm\": "
         << G4GeometryTolerance::GetInstance()->GetSurfaceTolerance() / mm
         << ",\n  \"points\": [\n";
    for (size_t i = 0; i < points.size(); ++i) {
      const auto classification = solid->Inside(points[i]);
      const char* label = classification == kInside ? "inside" :
                          classification == kOutside ? "outside" : "surface";
      json << "    {\"index\": " << i << ", \"position_mm\": ["
           << points[i].x() / mm << ", " << points[i].y() / mm << ", " << points[i].z() / mm
           << "], \"classification\": \"" << label << "\"}" << (i + 1 == points.size() ? "\n" : ",\n");
    }
    json << "  ]\n}\n";
    publish_new(output, json.str());
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "geometry_probe: " << error.what() << '\n';
    return 1;
  }
}
