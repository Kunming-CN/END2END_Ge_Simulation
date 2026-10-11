# GeSignal — HPGe Radiation-to-Readout Simulation

The END2END germanium detector project; its repository and website addresses stay unchanged.

Explore how radiation deposits become an energy measurement:
**Geant4/remage → SSD charge transport → preamplifier → shaping → peak ADC.**
The website contains saved results, not an online solver.

## Start here

- [Selected signals](https://kunming-cn.github.io/END2END_Ge_Simulation/spectra/pipeline.html) — six representative saved Cs137 examples, from deposits to peak ADC.
- [Saved results](https://kunming-cn.github.io/END2END_Ge_Simulation/results/index.html) — complete datasets, detector views and analysis files.
- [Run locally](https://kunming-cn.github.io/END2END_Ge_Simulation/guide.html) — the maintained Windows preparation and Control guide.
- [Download software only (ZIP)](https://github.com/Kunming-CN/END2END_Ge_Simulation/archive/refs/heads/main.zip) — source, detector models and pinned configuration; saved website data are excluded.
- [Contributing](CONTRIBUTING.md) — propose changes or report a problem.

## Run one local example

For a student run, download the software ZIP and extract it. Browse the saved
results on the website; they are not required to calculate your own events.
Developers should use the guide's sparse, blobless Git checkout. A normal full
clone still includes the website and repository history. An offline website
copy is a separate optional download through the documented Git route.

After following the guide, double-click `Control.cmd`. Choose one of ten
configurations available in the current cryostat. Cs137, Am241, Ba133 and Co60 share
the same selection and run workflow: enter an exact positive initial-nucleus
count, then review the checked serial batches of at most 10,000 nuclei each. The fixed
662 keV gamma beam retains its 20-primary AK02/SAP22 route. Co60 admission uses
its saved 500-decay trial: eight accepted pulses and one verified below-threshold
rejection. Rejected events remain in the ledger with no reconstructed energy;
the detector, charge model, electronics threshold and calibration are unchanged.

**Check environment** inspects installed files. **Check plan** verifies the selected
source, build, runtime and settings before **Run simulation**. Changing the form
invalidates its check. The five additional models—AK01, SAP16, SAP17,
Bipolar_reference_3D and KL01_3D—completed fixed 500-decay Cs137 cases on the
existing Windows/WSL computer. Native failures, readout rejections and zero events
remain visible; these are engineering checks, not experimental qualification.

Use **Stop at next boundary** and **Resume saved settings** for a checked decay
run. Completed batches stay available in **Explore events**. Open
**Reproduce or analyze this saved run** for files grouped by purpose and the
selected batch, primary and pulse-group filters. See the
[saved-result guide](https://kunming-cn.github.io/END2END_Ge_Simulation/guide.html#saved-analysis).

All 17 models remain browsable. Seven require a future larger cryostat; Control
shows their specific dimension limits. Setup has been checked on the existing
Windows/WSL computer; fresh-machine portability remains unvalidated.
[Student feedback](https://github.com/Kunming-CN/END2END_Ge_Simulation/issues)
will guide further fixes; include your OS/revision, detector/source/count and
the failing step or exact error. ParaView is not a student runtime prerequisite.

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

The website's [Results](https://kunming-cn.github.io/END2END_Ge_Simulation/results/index.html) page owns saved-study selection. The [local guide](https://kunming-cn.github.io/END2END_Ge_Simulation/guide.html) owns preparation, Control, analysis and advanced existing-input routes. Public reports are engineering examples; private-input replay requires compatible local data.

### Developer and validation notes

The [validation record](tools/LAUNCHER_ACCEPTANCE.md) separates instrumented saved-input regression, installation checks and unfinished portability claims. Canonical parameters, zero-deposit events, signed signals and unavailable responses remain explicit. Measured pulse waveforms were not retained; future experimental comparison uses the available spectra.

Use the [local workspace guide](tools/LOCAL_WORKSPACE.md) for file retention. The complete roadmap and current handoff are in [PROGRESS.md](PROGRESS.md).
Use the [maintenance guide](tools/MAINTENANCE.md) for source ownership and publication.

Advanced component references: [SSD/CPU/GPU](simulation/README.md), [transport and earlier workflows](transport/README.md), [physics references](simulation/PHYSICS.md). These are not competing beginner setup routes.

</details>

To propose a change, see [Contributing](CONTRIBUTING.md). Cite the software with
[CITATION.cff](CITATION.cff). Original project software and maintained-source
documentation use the [MIT License](LICENSE);
[third-party and data rights](THIRD_PARTY_NOTICES.md) remain separate.
