// Command-only regression: inspect GPS state without geometry or event generation.
#include "G4GeneralParticleSource.hh"
#include "G4RunManager.hh"
#include "G4SPSPosDistribution.hh"
#include "G4SingleParticleSource.hh"
#include "G4SystemOfUnits.hh"
#include "G4UImanager.hh"
#include "G4VUserPhysicsList.hh"
#include "G4Version.hh"

#include <algorithm>
#include <array>
#include <cmath>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <string>

static_assert(G4VERSION_NUMBER == 1132, "Use the pinned Geant4 11.3.2 runtime");

namespace {
constexpr double position_atol_mm = 1e-10;

// Registration makes the particle table ready for GPS construction. Neither
// processes nor geometry are initialized, and no event loop is entered.
class CommandOnlyPhysics final : public G4VUserPhysicsList {
  void ConstructParticle() override {}
  void ConstructProcess() override {}
  void SetCuts() override {}
};

void apply(G4UImanager* ui, const std::string& command) {
  const auto status = ui->ApplyCommand(command);
  if (status != 0) {
    throw std::runtime_error("GPS command refused (" + std::to_string(status) + "): " + command);
  }
}

void vector_json(std::ostream& out, const std::array<double, 3>& values) {
  out << '[' << values[0] << ',' << values[1] << ',' << values[2] << ']';
}
}  // namespace

int main(int argc, char** argv) {
  try {
    if (argc != 4 || (std::string(argv[1]) != "default" && std::string(argv[1]) != "precise")) {
      throw std::runtime_error("Usage: test_gps_precision default|precise cases.tsv result.json");
    }
    const bool precise = std::string(argv[1]) == "precise";
    std::ifstream input(argv[2]);
    if (!input) throw std::runtime_error("Cannot read cases");
    std::ifstream existing(argv[3]);
    if (existing) throw std::runtime_error("Preserve the existing result");
    std::ofstream output(argv[3]);
    if (!output) throw std::runtime_error("Cannot write result");
    output << std::setprecision(17) << std::boolalpha;

    G4RunManager run_manager;
    run_manager.SetUserInitialization(new CommandOnlyPhysics);
    auto* ui = G4UImanager::GetUIpointer();
    const bool initial_double_precision = G4UImanager::DoublePrecisionStr();
    if (initial_double_precision) throw std::runtime_error("Expected the native default precision flag to be false");
    if (precise) apply(ui, "/control/useDoublePrecision true");
    G4GeneralParticleSource gps;
    apply(ui, "/gps/pos/type Point");

    output << "{\"kind\":\"native_gps_command_precision_v1\",\"geant4_version_number\":"
           << G4VERSION_NUMBER << ",\"mode\":\"" << argv[1]
           << "\",\"initial_double_precision\":" << initial_double_precision
           << ",\"effective_double_precision\":" << G4UImanager::DoublePrecisionStr()
           << ",\"events_generated\":0,\"position_atol_mm\":" << position_atol_mm
           << ",\"cases\":[";

    bool first = true, all_precise = true, reproduced_recorded_failure = false;
    std::size_t count = 0;
    std::string line;
    while (std::getline(input, line)) {
      if (line.empty()) continue;
      std::istringstream fields(line);
      double angle;
      std::array<std::string, 3> tokens;
      if (!(fields >> angle >> tokens[0] >> tokens[1] >> tokens[2])) {
        throw std::runtime_error("Invalid case row");
      }
      std::string extra;
      if (fields >> extra) throw std::runtime_error("Unexpected case columns");
      std::array<double, 3> expected, actual, delta;
      for (std::size_t i = 0; i < 3; ++i) {
        std::size_t parsed = 0;
        expected[i] = std::stod(tokens[i], &parsed);
        if (parsed != tokens[i].size() || !std::isfinite(expected[i])) {
          throw std::runtime_error("Invalid position value");
        }
      }
      const auto command = "/gps/pos/centre " + tokens[0] + ' ' + tokens[1] + ' ' + tokens[2] + " mm";
      apply(ui, command);
      const auto& centre = gps.GetCurrentSource()->GetPosDist()->GetCentreCoords();
      double max_error = 0;
      for (std::size_t i = 0; i < 3; ++i) {
        actual[i] = centre[i] / mm;
        delta[i] = actual[i] - expected[i];
        max_error = std::max(max_error, std::abs(delta[i]));
      }
      const bool within_tolerance = max_error <= position_atol_mm;
      all_precise = all_precise && within_tolerance;
      if (angle == 30 && expected[1] == 32.303504374726018 &&
          actual[1] == 32.3035 && !within_tolerance) {
        reproduced_recorded_failure = true;
      }
      if (!first) output << ',';
      first = false;
      output << "{\"angle_deg\":" << angle << ",\"position_command\":\"" << command
             << "\",\"command_status\":0,\"expected_global_mm\":";
      vector_json(output, expected);
      output << ",\"effective_global_mm\":";
      vector_json(output, actual);
      output << ",\"delta_mm\":";
      vector_json(output, delta);
      output << ",\"max_abs_delta_mm\":" << max_error
             << ",\"within_unchanged_tolerance\":" << within_tolerance << '}';
      ++count;
    }
    if (count == 0 || !input.eof()) throw std::runtime_error("No cases or unreadable input");
    const bool passed = precise ? all_precise : reproduced_recorded_failure;
    output << "],\"case_count\":" << count << ",\"all_within_unchanged_tolerance\":" << all_precise
           << ",\"reproduced_recorded_default_failure\":" << reproduced_recorded_failure
           << ",\"regression_passed\":" << passed << "}\n";
    output.close();
    if (!output) throw std::runtime_error("Result write failed");
    std::cout << "mode=" << argv[1] << " cases=" << count << " regression_passed=" << std::boolalpha
              << passed << " events_generated=0\n";
    return passed ? 0 : 1;
  } catch (const std::exception& error) {
    std::cerr << "test_gps_precision: " << error.what() << '\n';
    return 2;
  }
}
