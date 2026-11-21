// Initialization-only exporter for the original remage material and photon processes.
#include "G4EmCalculator.hh"
#include "G4Gamma.hh"
#include "G4GenericMessenger.hh"
#include "G4LogicalVolumeStore.hh"
#include "G4Material.hh"
#include "G4RunManager.hh"
#include "G4SystemOfUnits.hh"
#include "RMGDefaultCli.hh"

#include <cmath>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <stdexcept>

namespace {
class PhotonRates {
public:
  void Save(const std::string& filename) {
    auto* manager = G4RunManager::GetRunManager();
    auto* crystal = G4LogicalVolumeStore::GetInstance()->GetVolume("germanium");
    if (!crystal || crystal->GetMaterial()->GetName() != "G4_Ge") {
      throw std::runtime_error("Expected the initialized GeGI germanium volume");
    }
    // Geant4's fake run prepares material-cuts and cross-section tables with zero events.
    manager->BeamOn(0);
    auto* material = crystal->GetMaterial();
    G4EmCalculator calculator;
    std::ifstream energies("energies-keV.txt");
    std::ofstream output(filename);
    if (!energies || !output) throw std::runtime_error("Open the energy input and rate output");
    output << "energy_keV,density_g_cm3,photoelectric_per_mm,compton_per_mm,rayleigh_per_mm,pair_per_mm\n"
           << std::setprecision(17);
    double energy;
    while (energies >> energy) {
      const auto rate = [&](const char* name) {
        return calculator.GetCrossSectionPerVolume(energy*keV, G4Gamma::Gamma(), name, material, crystal->GetRegion())*mm;
      };
      const double photo = rate("phot"), compton = rate("compt");
      if (!(photo > 0 && compton > 0 && std::isfinite(photo) && std::isfinite(compton))) {
        throw std::runtime_error("Initialized germanium photoelectric and Compton rates are unavailable");
      }
      output << energy << ',' << material->GetDensity()/(g/cm3) << ',' << photo << ',' << compton
             << ',' << rate("Rayl") << ',' << rate("conv") << '\n';
    }
    if (!energies.eof() || !output) throw std::runtime_error("Malformed energy input or rate output error");
  }
};
}

int main(int argc, char** argv) {
  try {
    PhotonRates rates;
    G4GenericMessenger messenger(&rates, "/GeSignal/PhotonRates/", "Initialized photon interaction rates");
    messenger.DeclareMethod("Save", &PhotonRates::Save).SetStates(G4State_Idle);
    RMGDefaultCli app;
    app.ParseCliArgs(argc, argv);
    app.SetupLoggingAndIpc();
    return app.RunSimulation(argc, argv);
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
