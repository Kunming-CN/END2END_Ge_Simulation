# END2END germanium detector simulation

Explore how radiation deposits become an energy measurement:
**Geant4/remage → SSD charge transport → preamplifier → shaping → peak ADC.**
The website contains saved results, not an online solver.

## Choose your task

| Task | Start here |
|---|---|
| Browse saved results | [Results](https://kunming-cn.github.io/END2END_Ge_Simulation/results/index.html) — spectra, event viewers and teaching examples |
| Explore detector models | [Detector Library](https://kunming-cn.github.io/END2END_Ge_Simulation/detectors/index.html) — 17 rotatable geometries, including GeGI's 34 contacts; overviews, detailed saved galleries and technical information |
| Set up or run a local case | [Setup & run guide](https://kunming-cn.github.io/END2END_Ge_Simulation/guide.html) — the single Windows installation/run authority |
| Maintain this project | [Maintenance guide](tools/MAINTENANCE.md) — source ownership, publication and checks |

## Run one local example

Use the guide to choose a workflow. For a generic new LBNL run, follow its Windows setup checklist first. First-time setup is explicit, not one-click automatic installation.

On the existing prepared computer, double-click `Control.cmd` for the local mouse interface: check, run, stop/continue and download the bounded AK02/SAP22 native example.

From the repository root in **PowerShell**, after setup:

```powershell
.\Run.cmd check
.\Run.cmd run -Detector AK02 -Preset demo
```

Use `-Detector SAP22` to switch the crystal without editing YAML; `-Detector both` runs two separate cases serially. The demo uses 500 initial decays per selected model. Double-click `Run.cmd` for the menu.

**Scope:** 17 viewable models do not mean 17 LBNL-ready models. The LBNL adapter currently implements AK02/SAP22. One custom AK02 500-decay uninstrumented run is recorded; broader positive replacement acceptance and fresh-machine end-to-end reproduction remain unvalidated.

The guide also covers status, inspection and generic resume, the optional local workspace index, and a source-only checkout. ParaView is not a student runtime prerequisite.

Advanced existing-input routes are distinct: saved-charge electronics replay and bounded new native-readout use compatible private local inputs, not public report HTML or a fresh checkout. Generic resume still lacks interrupted native-stage group recovery. Metadata-only recovery reconciles a completed child with its parent; it never starts missing calculations or adopts partial responses.

## Project layout

| Location | Purpose |
|---|---|
| `models/`, `scenarios/` | Original detector definitions and reviewed scenario capabilities |
| `simulation/`, `transport/` | SSD/electronics and Geant4/remage implementations with pinned environments |
| `tools/` | Maintained launch, publication and regression utilities |
| `docs/` | Generated public website and saved examples; not the editable source |
| `.local/` | Local runs, permanent science and private evidence; never blanket-delete |

<details>
<summary>Reference links: saved examples, local workflows and developer notes</summary>

### Saved examples and downloads

The featured [Cs137 result](https://kunming-cn.github.io/END2END_Ge_Simulation/results/cs137-1m/index.html) processes one million initial decays **per detector** for AK02 and SAP22. Earlier 10k event viewers and the compact teaching example are labelled separately. Results are engineering simulations, not calibrated experimental predictions.

Current energy spectra use **step histograms**, default **Log**, with **Linear / Log** controls. The display reuses saved bin counts; original reports and numerical data remain preserved. [Download detector models](https://kunming-cn.github.io/END2END_Ge_Simulation/downloads/all-models.zip).

### Local workflow shortcuts

| Task | Guide section |
|---|---|
| Choose a workflow | [Local routes](https://kunming-cn.github.io/END2END_Ge_Simulation/guide.html#local-routes) |
| Prepare a generic new LBNL run | [Windows setup checklist](https://kunming-cn.github.io/END2END_Ge_Simulation/guide.html#setup) — follow this first |
| Use `Control.cmd` on the existing prepared computer | [Local mouse interface](https://kunming-cn.github.io/END2END_Ge_Simulation/guide.html#local-control) |
| Inspect or continue a run | [Status, inspection and generic resume](https://kunming-cn.github.io/END2END_Ge_Simulation/guide.html#results) — interrupted native-stage group recovery remains unavailable |
| Browse local files | [Optional local workspace index](https://kunming-cn.github.io/END2END_Ge_Simulation/guide.html#workspace) |

### Existing-input advanced routes

Both [saved-charge electronics replay](https://kunming-cn.github.io/END2END_Ge_Simulation/guide.html#replay) and [bounded new native-readout](https://kunming-cn.github.io/END2END_Ge_Simulation/guide.html#native-readout) require compatible private local inputs, not public report HTML or a fresh checkout. [Metadata-only recovery](tools/RECOVERY.md) reconciles a completed child with its parent; it never starts missing calculations or adopts partial responses.

### Developer and validation notes

The [validation record](tools/LAUNCHER_ACCEPTANCE.md) separates instrumented saved-input regression, installation checks and unfinished portability claims. Canonical parameters, zero-deposit events, signed signals and unavailable responses remain explicit. Measured pulse waveforms were not retained; future experimental comparison uses the available spectra.

Use the [local workspace guide](tools/LOCAL_WORKSPACE.md) for file retention. The complete roadmap and current handoff are in [PROGRESS.md](PROGRESS.md).

Advanced component references: [SSD/CPU/GPU](simulation/README.md), [transport and earlier workflows](transport/README.md), [physics references](simulation/PHYSICS.md). These are not competing beginner setup routes.

</details>
