# GeSignal — HPGe radiation-to-readout simulation

GeSignal follows gamma-ray energy deposits in high-purity germanium through charge induction and detector readout. Browse saved research or run and analyze your own simulation.

[Explore the website](https://kunming-cn.github.io/END2END_Ge_Simulation/) · [Choose a research study](https://kunming-cn.github.io/END2END_Ge_Simulation/results/index.html) · [Download and run locally](https://kunming-cn.github.io/END2END_Ge_Simulation/guide.html)

## Run a simulation

[Download the student software for Windows and macOS](https://github.com/Kunming-CN/END2END_Ge_Simulation/releases/latest/download/END2END-Ge-Student.zip), extract it and follow the [setup guide](https://kunming-cn.github.io/END2END_Ge_Simulation/guide.html). On Windows open `Control.cmd`; on macOS run `Setup.command` once, then open `Control.command`. Choose a compatible cryostat, detector and source, check the plan, run it and inspect the saved results. The software contains code, models and the guide; research exhibits and saved study data live on the website. GeGI calibration is a separate download.

## Explore saved results

- [Follow one signal](https://kunming-cn.github.io/END2END_Ge_Simulation/learn/signals/index.html) from a saved Cs-137 energy deposit to readout.
- [Browse the research](https://kunming-cn.github.io/END2END_Ge_Simulation/results/index.html): GeGI archived-library shared readout, four independent GeGI acquisitions, and separate Cs-137 10K and 1M studies. Each keeps its own sample, settings and identities.
- Inspect the [17 detector models](https://kunming-cn.github.io/END2END_Ge_Simulation/detectors/index.html) and their [cryostat assemblies](https://kunming-cn.github.io/END2END_Ge_Simulation/assemblies/index.html). Control lists executable combinations.

Geant4/remage provides radiation deposits; SolidStateDetectors.jl calculates fields, drift and electrode charge. LBNL examples use analog shaping and a peak ADC. GeGI studies use nominal digitized strip readout and signal-derived interaction candidates. [Methods and interpretation](https://kunming-cn.github.io/END2END_Ge_Simulation/methods/index.html) distinguish functional software checks, numerical convergence and agreement with experiment.

## Work with the source

`transport/` owns radiation deposits, `simulation/` owns fields, drift and analog electronics, and `tools/gegi_digital_readout.py` implements the GeGI digital branches. The maintained generators in `tools/` build the saved website in `docs/`. [Maintenance guide](tools/MAINTENANCE.md) · [Current handoff](PROGRESS.md) · [Platform test record](https://github.com/Kunming-CN/END2END_Ge_Simulation/pull/1)

[Issues](https://github.com/Kunming-CN/END2END_Ge_Simulation/issues) · [Contributing](CONTRIBUTING.md) · [Citation](CITATION.cff) · [MIT license](LICENSE) · [Third-party and data rights](THIRD_PARTY_NOTICES.md)
