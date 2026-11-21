#include "RMGDefaultCli.hh"
#include "RMGManager.hh"
#include "RMGUserInit.hh"

#include "G4Event.hh"
#include "G4GenericMessenger.hh"
#include "G4ParticleDefinition.hh"
#include "G4Run.hh"
#include "G4RunManager.hh"
#include "G4Step.hh"
#include "G4StepPoint.hh"
#include "G4SystemOfUnits.hh"
#include "G4Track.hh"
#include "G4UserSteppingAction.hh"
#include "G4VPhysicalVolume.hh"
#include "G4VProcess.hh"
#include "Randomize.hh"

#include <charconv>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <locale>
#include <memory>
#include <mutex>
#include <stdexcept>
#include <string>
#include <string_view>
#include <unordered_set>
#include <utility>

namespace {

struct StateWriter {
  void Save(const std::string& name) { CLHEP::HepRandom::saveEngineStatus(name.c_str()); }
};

std::unordered_set<int> event_ids(std::string_view text) {
  std::unordered_set<int> ids;
  if (text.empty()) return ids;
  for (;;) {
    const auto comma = text.find(',');
    const auto token = text.substr(0, comma);
    int id = -1;
    const auto result = std::from_chars(token.data(), token.data() + token.size(), id);
    if (result.ec != std::errc{} || result.ptr != token.data() + token.size() || id < 0) {
      throw std::invalid_argument("GEGI_PHOTON_STEP_EVENTS expects comma-separated nonnegative event IDs");
    }
    ids.insert(id);
    if (comma == std::string_view::npos) return ids;
    text.remove_prefix(comma + 1);
  }
}

void csv_text(std::ostream& out, std::string_view value) {
  out << '"';
  for (const char c : value) {
    if (c == '"') out << '"';
    out << c;
  }
  out << '"';
}

void point(std::ostream& out, const G4StepPoint& value) {
  const auto& position = value.GetPosition();
  const auto& direction = value.GetMomentumDirection();
  const auto* volume = value.GetPhysicalVolume();
  out << ',' << value.GetKineticEnergy() / keV
      << ',' << position.x() / mm << ',' << position.y() / mm << ',' << position.z() / mm
      << ',' << direction.x() << ',' << direction.y() << ',' << direction.z()
      << ',' << value.GetGlobalTime() / ns << ',' << value.GetLocalTime() / ns << ',';
  csv_text(out, volume == nullptr ? "" : volume->GetName());
  out << ',' << (volume == nullptr ? -1 : volume->GetCopyNo()) << ','
      << static_cast<int>(value.GetStepStatus());
}

class PhotonSteps {
public:
  PhotonSteps(const std::filesystem::path& output, std::unordered_set<int> selected)
      : selected_(std::move(selected)) {
    if (std::filesystem::exists(output)) throw std::runtime_error("Photon-step sidecar already exists");
    out_.exceptions(std::ios::badbit | std::ios::failbit);
    out_.open(output, std::ios::out | std::ios::binary);
    out_.imbue(std::locale::classic());
    out_ << std::setprecision(std::numeric_limits<double>::max_digits10)
         << "# gegi_photon_step_sidecar_v1\n"
         << "run_id,event_id,track_id,parent_track_id,step_number,"
            "process,process_type,process_subtype,creator_process,track_status,"
            "step_edep_keV,step_nonionizing_edep_keV,"
            "pre_kinetic_keV,pre_x_mm,pre_y_mm,pre_z_mm,pre_dx,pre_dy,pre_dz,"
            "pre_global_ns,pre_local_ns,pre_volume,pre_copy,pre_status,"
            "post_kinetic_keV,post_x_mm,post_y_mm,post_z_mm,post_dx,post_dy,post_dz,"
            "post_global_ns,post_local_ns,post_volume,post_copy,post_status\n";
  }

  bool includes(int id) const { return selected_.empty() || selected_.count(id) != 0; }

  void write(int run_id, int event_id, const G4Step& step) {
    const auto* track = step.GetTrack();
    const auto* pre = step.GetPreStepPoint();
    const auto* post = step.GetPostStepPoint();
    const auto* process = post->GetProcessDefinedStep();
    const auto* creator = track->GetCreatorProcess();
    const std::lock_guard<std::mutex> guard(mutex_);
    out_ << run_id << ',' << event_id << ',' << track->GetTrackID() << ',' << track->GetParentID()
         << ',' << track->GetCurrentStepNumber() << ',';
    csv_text(out_, process == nullptr ? "" : process->GetProcessName());
    out_ << ',' << (process == nullptr ? -1 : static_cast<int>(process->GetProcessType()))
         << ',' << (process == nullptr ? -1 : process->GetProcessSubType()) << ',';
    csv_text(out_, creator == nullptr ? "" : creator->GetProcessName());
    out_ << ',' << static_cast<int>(track->GetTrackStatus())
         << ',' << step.GetTotalEnergyDeposit() / keV << ','
         << step.GetNonIonizingEnergyDeposit() / keV;
    point(out_, *pre);
    point(out_, *post);
    out_ << '\n';
  }

  void close() { out_.close(); }

private:
  std::unordered_set<int> selected_;
  std::ofstream out_;
  std::mutex mutex_;
};

class PhotonStepAction final : public G4UserSteppingAction {
public:
  explicit PhotonStepAction(std::shared_ptr<PhotonSteps> output) : output_(std::move(output)) {}

  void UserSteppingAction(const G4Step* step) override {
    const auto* track = step->GetTrack();
    if (track->GetDefinition()->GetPDGEncoding() != 22) return;
    const auto* manager = G4RunManager::GetRunManager();
    const auto event_id = manager->GetCurrentEvent()->GetEventID();
    if (!output_->includes(event_id)) return;
    output_->write(manager->GetCurrentRun()->GetRunID(), event_id, *step);
  }

private:
  std::shared_ptr<PhotonSteps> output_;
};

class ObservedCli final : public RMGDefaultCli {
public:
  explicit ObservedCli(std::shared_ptr<PhotonSteps> output) : output_(std::move(output)) {}

  void SetupRuntime(RMGManager& manager) override {
    RMGDefaultCli::SetupRuntime(manager);
    if (output_) manager.GetUserInit()->AddSteppingAction<PhotonStepAction>(output_);
  }

private:
  std::shared_ptr<PhotonSteps> output_;
};

}  // namespace

int main(int argc, char** argv) {
  try {
    StateWriter writer;
    G4GenericMessenger messenger(&writer, "/GeSignal/RNG/", "Exact current serial CLHEP state");
    messenger.DeclareMethod("Save", &StateWriter::Save).SetStates(G4State_Idle);
    std::shared_ptr<PhotonSteps> output;
    if (const auto* path = std::getenv("GEGI_PHOTON_STEP_OUTPUT")) {
      const auto* selected = std::getenv("GEGI_PHOTON_STEP_EVENTS");
      output = std::make_shared<PhotonSteps>(path, event_ids(selected == nullptr ? "" : selected));
    }
    ObservedCli app(output);
    app.ParseCliArgs(argc, argv);
    app.SetupLoggingAndIpc();
    const int status = app.RunSimulation(argc, argv);
    if (output) output->close();
    return status;
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
