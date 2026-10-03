# GeSignal — HPGe Radiation-to-Readout Simulation

The END2END germanium detector project; its repository and website addresses stay unchanged.

Explore how radiation deposits become an energy measurement:
**Geant4/remage → SSD charge transport → preamplifier → shaping → peak ADC.**
The website contains saved results, not an online solver.

## Browse, setup or use

| Task | Start here |
|---|---|
| Browse | [Four-case Cs137 10K results](https://kunming-cn.github.io/END2END_Ge_Simulation/results/cs137-10k/index.html) — events, spectra, charge/readout and complete ledgers; [17 detector models](https://kunming-cn.github.io/END2END_Ge_Simulation/detectors/index.html) — shapes, types and saved galleries |
| Setup | [Windows setup](https://kunming-cn.github.io/END2END_Ge_Simulation/guide.html#setup) — the single installation authority, including the explicit source-bound exporter build |
| Use | [Control instructions](https://kunming-cn.github.io/END2END_Ge_Simulation/guide.html#local-control) — check a setup, run a supported case and explore its saved result |

## Run one local example

After following the guide, double-click `Control.cmd`. Choose AK02, SAP22,
GeRC02 Li50min or KMRC01 candidate. Cs137 supports 20/500 initial decays; the
fixed 662 keV gamma beam supports 20 primaries for AK02/SAP22. Electronics
settings belong to the checked run; changing the form invalidates its check.

**Check environment** inspects installed files. **Check plan** verifies the selected
source, build, runtime and settings before **Run simulation**. The four Control
connectors and source-bound preparation have been verified on the existing
Windows/WSL computer. Fresh-clone and second-computer setup remain unvalidated.
Seventeen viewable models do not mean seventeen executable models. ParaView is
not a student runtime prerequisite.

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

The featured [four-case 10K result](https://kunming-cn.github.io/END2END_Ge_Simulation/results/cs137-10k/index.html) retains all initial decays for AK02, SAP22, GeRC02 Li50min and KMRC01 candidate. The [separate 1M campaign](https://kunming-cn.github.io/END2END_Ge_Simulation/results/cs137-1m/index.html) covers AK02/SAP22. The saved gamma example now processes all 40 original primaries with useful collection-edge and full-window views. These are engineering simulations, not calibrated experimental predictions.

Current energy spectra use **step histograms**, default **Log**, with **Linear / Log** controls. The display reuses saved bin counts; original reports and numerical data remain preserved. [Download detector models](https://kunming-cn.github.io/END2END_Ge_Simulation/downloads/all-models.zip).

### Local workflow shortcuts

| Task | Guide section |
|---|---|
| Choose a workflow | [Local routes](https://kunming-cn.github.io/END2END_Ge_Simulation/guide.html#local-routes) |
| Prepare a supported Control case | [Windows setup checklist](https://kunming-cn.github.io/END2END_Ge_Simulation/guide.html#setup) — follow this first |
| Use `Control.cmd` on a prepared computer | [Local simulation application](https://kunming-cn.github.io/END2END_Ge_Simulation/guide.html#local-control) |
| Inspect or continue a run | [Status, inspection and generic resume](https://kunming-cn.github.io/END2END_Ge_Simulation/guide.html#results) — interrupted native-stage group recovery remains unavailable |
| Browse local files | [Optional local workspace index](https://kunming-cn.github.io/END2END_Ge_Simulation/guide.html#workspace) |

### Existing-input advanced routes

Both [saved-charge electronics replay](https://kunming-cn.github.io/END2END_Ge_Simulation/guide.html#replay) and [bounded new native-readout](https://kunming-cn.github.io/END2END_Ge_Simulation/guide.html#native-readout) require compatible private local inputs, not public report HTML or a fresh checkout. [Metadata-only recovery](tools/RECOVERY.md) reconciles a completed child with its parent; it never starts missing calculations or adopts partial responses.

The older generic `Run.cmd` adapter supports AK02/SAP22. Its `check` validates
the legacy exporter, not Control's portable exporter; use the guide's explicit
`Run.cmd setup -BuildPortableSourceExporter` preparation and Control **Check plan**.

### Developer and validation notes

The [validation record](tools/LAUNCHER_ACCEPTANCE.md) separates instrumented saved-input regression, installation checks and unfinished portability claims. Canonical parameters, zero-deposit events, signed signals and unavailable responses remain explicit. Measured pulse waveforms were not retained; future experimental comparison uses the available spectra.

Use the [local workspace guide](tools/LOCAL_WORKSPACE.md) for file retention. The complete roadmap and current handoff are in [PROGRESS.md](PROGRESS.md).
Use the [maintenance guide](tools/MAINTENANCE.md) for source ownership and publication.

Advanced component references: [SSD/CPU/GPU](simulation/README.md), [transport and earlier workflows](transport/README.md), [physics references](simulation/PHYSICS.md). These are not competing beginner setup routes.

</details>

To propose a change, see [Contributing](CONTRIBUTING.md). Cite the software with
[CITATION.cff](CITATION.cff). The project software license is pending;
[third-party and data rights](THIRD_PARTY_NOTICES.md) remain separate.
