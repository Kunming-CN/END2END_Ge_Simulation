# END2END germanium detector simulation

**[Browse the results website](https://kunming-cn.github.io/END2END_Ge_Simulation/)** · **[Run a supported local case](https://kunming-cn.github.io/END2END_Ge_Simulation/guide.html#setup)** · [Download detector models](https://kunming-cn.github.io/END2END_Ge_Simulation/downloads/all-models.zip)

Explore how radiation deposits become an energy measurement:
**Geant4/remage → SSD charge transport → preamplifier → shaping → peak ADC.**
The website contains saved results, not an online solver.

## Browse first

The [detector library](https://kunming-cn.github.io/END2END_Ge_Simulation/detectors/index.html) has **17 rotatable geometries**, including GeGI's 34 contacts. Each detector has an overview, a detailed saved gallery and technical information.

The featured [Cs137 result](https://kunming-cn.github.io/END2END_Ge_Simulation/results/cs137-1m/index.html) processes one million initial decays **per detector** for AK02 and SAP22. Earlier 10k event viewers and the compact teaching example are labelled separately. Results are engineering simulations, not calibrated experimental predictions.

Current energy spectra use **step histograms**, default **Log**, with **Linear / Log** controls. The display reuses saved bin counts; original reports and numerical data remain preserved.

## Run one local example

Follow the **[Windows setup checklist](https://kunming-cn.github.io/END2END_Ge_Simulation/guide.html#setup)** first. It is the primary installation/run guide. The reviewed LBNL path requires Julia **1.13.0**, the supplied SSD environment, Ubuntu-24.04/WSL, pinned Geant4/remage dependencies and the separately obtained upstream cryostat files.

From the repository root in **PowerShell**, after setup:

```powershell
.\Run.cmd check
.\Run.cmd run -Detector AK02 -Preset demo
```

Use `-Detector SAP22` to switch the crystal without editing YAML; `-Detector both` runs two separate cases serially. The demo uses 500 initial decays per selected model. Double-click `Run.cmd` for the menu.

**Scope:** 17 viewable models do not mean 17 LBNL-ready models. The LBNL adapter currently implements AK02/SAP22. Positive uninstrumented launcher execution and fresh-machine end-to-end reproduction remain unvalidated; first-time setup is explicit, not one-click automatic installation.

```powershell
.\Run.cmd status
.\Run.cmd open -Name RUN_NAME
.\Open_Workspace.cmd
```

The optional workspace index needs an installed Windows Python 3.10+ (standard library only); ParaView is not required for students. Replace `RUN_NAME` with the name printed by the launcher. The workspace entry opens a local-only results/file index; it does not start or resume calculations. Completed stages are reused only after verification. Interrupted native-stage group recovery is not yet part of this beginner launcher.

<details><summary>Source-only checkout instead of downloading the saved media</summary>

Browse saved results online; obtain the calculation sources with Git:

```powershell
git clone --filter=blob:none --sparse https://github.com/Kunming-CN/END2END_Ge_Simulation.git
cd END2END_Ge_Simulation
git sparse-checkout set models simulation transport scenarios tools
```

This omits `docs/` from the checkout. It does not install dependencies or fetch cryostat inputs. A full clone also contains the saved website and media.

</details>

## Project layout

| Location | Purpose |
|---|---|
| `models/`, `scenarios/` | Original detector definitions and reviewed scenario capabilities |
| `simulation/`, `transport/` | SSD/electronics and Geant4/remage implementations with pinned environments |
| `tools/` | Maintained launch, publication and regression utilities |
| `docs/` | Generated public website and saved examples; not the editable source |
| `.local/` | Local runs, permanent science and private evidence; never blanket-delete |

## Methods, validation and maintenance

The [validation record](tools/LAUNCHER_ACCEPTANCE.md) separates instrumented saved-input regression, installation checks and unfinished portability claims. Canonical parameters, zero-deposit events, signed signals and unavailable responses remain explicit. Measured pulse waveforms were not retained; future experimental comparison uses the available spectra.

Use the [maintenance guide](tools/MAINTENANCE.md) for source ownership, publication and checks, and the [local workspace guide](tools/LOCAL_WORKSPACE.md) for file retention. The complete roadmap and current handoff are in [PROGRESS.md](PROGRESS.md).

Advanced component references: [SSD/CPU/GPU](simulation/README.md), [transport and earlier workflows](transport/README.md), [physics references](simulation/PHYSICS.md). These are not competing beginner setup routes.
