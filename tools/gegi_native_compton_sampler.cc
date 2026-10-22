// Direct native-model diagnostic. No geometry, tracking, detector, or readout run.
#include "G4DataVector.hh"
#include "G4DynamicParticle.hh"
#include "G4Electron.hh"
#include "G4Element.hh"
#include "G4EmParameters.hh"
#include "G4Gamma.hh"
#include "G4KleinNishinaCompton.hh"
#include "G4LivermoreComptonModel.hh"
#include "G4LossTableManager.hh"
#include "G4Material.hh"
#include "G4MaterialCutsCouple.hh"
#include "G4NistManager.hh"
#include "G4ParticleChangeForGamma.hh"
#include "G4PhysicalConstants.hh"
#include "G4ProductionCuts.hh"
#include "G4SystemOfUnits.hh"
#include "G4Track.hh"
#include "G4Version.hh"
#include "Randomize.hh"
#include "CLHEP/Random/JamesRandom.h"
#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <memory>
#include <stdexcept>
#include <vector>

int main(int argc, char** argv) {
  try {
    if (argc != 2) throw std::runtime_error("Expected one new output directory");
    if (G4VERSION_NUMBER != 1132) throw std::runtime_error("Requires Geant4 11.3.2");
    const auto start = std::chrono::steady_clock::now();
    const std::filesystem::path out(argv[1]);
    if (!std::filesystem::is_directory(out) || std::filesystem::exists(out/"samples.csv"))
      throw std::runtime_error("Output directory must exist with no previous samples.csv");
    std::ofstream csv(out/"samples.csv");
    csv << std::setprecision(std::numeric_limits<double>::max_digits10);
    csv << "model_id,energy_index,sample_index,seed,E0_keV,Eout_keV,E1_keV,cos_true,cos_free_native_mass,cos_free_project_mass,cos_free_511,angle_error_rad,secondary_ke_keV,local_deposit_keV,closure_keV,secondary_count,secondary_nonfinite_direction_count,track_status,status\n";
    G4Random::setTheEngine(new CLHEP::HepJamesRandom());
    G4Gamma::GammaDefinition();
    G4Electron::ElectronDefinition();
    auto* material = G4NistManager::Instance()->FindOrBuildMaterial("G4_Ge");
    if (!material || material->GetNumberOfElements() != 1 ||
        (*material->GetElementVector())[0]->GetZasInt() != 32)
      throw std::runtime_error("Expected single-element germanium");
    // Atomic relaxation is intentionally absent: native binding energy is local.
    G4EmParameters::Instance()->SetFluo(false);
    G4EmParameters::Instance()->SetAuger(false);
    G4LossTableManager::Instance()->SetAtomDeexcitation(nullptr);
    G4ProductionCuts production_cuts;
    production_cuts.SetProductionCut(0.01*mm);
    G4MaterialCutsCouple couple(material, &production_cuts);
    couple.SetIndex(0);
    // No world/PCT/physics-list is built. Pure-Ge atom selection uses the model's
    // material fallback when no production-cuts element selectors are registered.
    G4DataVector cuts(1, 0.0);
    const std::array<double,3> energies = {662.0,1173.228,1332.492};
    const std::array<std::array<long,3>,2> seeds = {{{261022662,261023173,261023332},
                                                  {261024662,261025173,261025332}}};
    std::ofstream meta(out/"native.json");
    meta << std::setprecision(17)
         << "{\"kind\":\"geant4_native_compton_metadata_v1\",\"geant4_version_number\":"
         << G4VERSION_NUMBER << ",\"geant4_version\":\"" << G4Version
         << "\",\"native_electron_rest_keV\":" << electron_mass_c2/keV
         << ",\"project_electron_rest_keV\":510.99895069,\"material\":\"G4_Ge\",\"Z\":32,\"density_g_cm3\":"
         << material->GetDensity()/(g/cm3)
         << ",\"atomic_deexcitation\":false,\"binding_energy_policy\":\"native local deposit\","
         << "\"registered_geometry_or_transport\":false,\"couple_index\":0,"
         << "\"production_range_cut_mm\":0.01,\"SampleSecondaries_tmin_keV\":0,"
         << "\"model_names\":[\"G4LivermoreComptonModel\",\"G4KleinNishinaCompton\"],"
         << "\"LivermoreDataDir\":\"" << G4EmParameters::Instance()->LivermoreDataDir()
         << "\",\"random_engine\":\"CLHEP::HepJamesRandom\",\"threads\":1}"
         << '\n';
    meta.close();
    std::size_t count = 0;
    for (int model_id=0; model_id<2; ++model_id) {
      G4ParticleChangeForGamma change;
      std::unique_ptr<G4VEmModel> model;
      if (model_id == 0) model = std::make_unique<G4LivermoreComptonModel>();
      else model = std::make_unique<G4KleinNishinaCompton>();
      model->SetParticleChange(&change);
      model->Initialise(G4Gamma::Gamma(), cuts);
      model->SetCurrentCouple(&couple);
      const int samples = model_id == 0 ? 10000 : 1000;
      for (int eindex=0; eindex<3; ++eindex) {
        G4Random::setTheSeed(seeds[model_id][eindex]);
        const double e0 = energies[eindex]*keV;
        for (int i=0; i<samples; ++i) {
          if (count >= 33000 || std::chrono::duration<double>(
              std::chrono::steady_clock::now()-start).count() > 120.)
            throw std::runtime_error("Native sampler exceeded fixed count/time bound");
          G4Track track(new G4DynamicParticle(G4Gamma::Gamma(),G4ThreeVector(0,0,1),e0),
                        0.,G4ThreeVector());
          // Reset energy, status, direction and local deposit for EVERY sample.
          change.InitializeForPostStep(track);
          std::vector<G4DynamicParticle*> secondary;
          model->SampleSecondaries(&secondary,&couple,track.GetDynamicParticle(),0.,e0);
          const double eout = change.GetProposedKineticEnergy();
          const double local = change.GetLocalEnergyDeposit();
          const auto dir = change.GetProposedMomentumDirection();
          double ske = 0.;
          std::size_t nsecondary=0, nonfinite_dir=0;
          for (auto* p : secondary) {
            if (!p) continue;
            ske += p->GetKineticEnergy(); ++nsecondary;
            const auto v=p->GetMomentumDirection();
            if (!std::isfinite(v.x()) || !std::isfinite(v.y()) || !std::isfinite(v.z()))
              ++nonfinite_dir;
            delete p;
          }
          const double closure=(e0-eout-ske-local)/keV;
          const bool energy_ok=std::isfinite(eout) && eout>=0 && eout<=e0 &&
            std::isfinite(ske) && ske>=0 && std::isfinite(local) && local>=0 &&
            std::isfinite(closure) && std::abs(closure)<=1e-9;
          const bool gamma_valid=eout>0 && std::isfinite(dir.z()) &&
            std::abs(dir.mag2()-1.)<=1e-12 && std::abs(dir.z())<=1.;
          const double c=gamma_valid ? 1-electron_mass_c2*(1/eout-1/e0) : 0.;
          const double cp=gamma_valid ? 1-510.99895069*keV*(1/eout-1/e0) : 0.;
          const double cr=gamma_valid ? 1-511.*keV*(1/eout-1/e0) : 0.;
          const bool inverse_valid=gamma_valid && c>=-1 && c<=1;
          const bool control_ok=model_id!=1 || !gamma_valid || std::abs(c-dir.z())<=1e-12;
          const char* status = !energy_ok ? "energy_failure" : !control_ok ? "control_failure" :
            eout==0 ? "absorbed" : !gamma_valid ? "gamma_direction_failure" :
            eout==e0 && nsecondary==0 && local==0 ? "unchanged" : "sampled";
          csv << model_id << ',' << eindex << ',' << i << ',' << seeds[model_id][eindex]
              << ',' << e0/keV << ',' << eout/keV << ',' << (e0-eout)/keV << ',';
          if (gamma_valid) csv << dir.z();
          csv << ','; if (gamma_valid) csv << c;
          csv << ','; if (gamma_valid) csv << cp;
          csv << ','; if (gamma_valid) csv << cr;
          csv << ','; if (inverse_valid) csv << std::acos(c)-std::acos(dir.z());
          csv << ',' << ske/keV << ',' << local/keV << ',' << closure << ',' << nsecondary
              << ',' << nonfinite_dir << ',' << static_cast<int>(change.GetTrackStatus())
              << ',' << status << '\n';
          ++count;
          if (!energy_ok || !control_ok || (eout>0 && !gamma_valid)) {
            csv.flush();
            throw std::runtime_error(std::string("Preserved native sampling failure: ")+status);
          }
        }
        csv.flush();
      }
    }
    if (!csv || count!=33000) throw std::runtime_error("Incomplete native CSV output");
    std::cout << "completed_samples=" << count << '\n';
    return 0;
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 2;
  }
}
