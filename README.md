# GeSignal — HPGe radiation-to-readout simulation

GeSignal simulates energy deposits in high-purity germanium with Geant4/remage and follows the drifting charge with SolidStateDetectors.jl. The readout depends on the detector. The LBNL examples use a preamplifier, analog shaper and peak ADC. For GeGI, Control can replay saved strip signals through a nominal digitized preamplifier, use the fast response on neighboring strips for position, and measure energy on the slow branch. The GeGI electronics settings and position calibration describe the simulation.

## Run a simulation

[Download the student software for Windows and macOS](https://github.com/Kunming-CN/END2END_Ge_Simulation/releases/latest/download/END2END-Ge-Student.zip) and extract it. Open `tools/site_guide.html` for prerequisites. On Windows open `Control.cmd`. On macOS run `Setup.command` once, then open `Control.command`. In Control, choose a cryostat, detector and source, check the plan, run it and open its results. The package includes the code, models and guide. [Setup and use guide](https://kunming-cn.github.io/END2END_Ge_Simulation/guide.html)

## Explore saved results

- [Follow one signal](https://kunming-cn.github.io/END2END_Ge_Simulation/spectra/pipeline.html) from a Cs137 energy deposit to a measured pulse in a simulation.
- [Browse the results](https://kunming-cn.github.io/END2END_Ge_Simulation/results/index.html) for Cs137 and GeGI studies, including event counts, settings and downloadable data. [Methods](https://kunming-cn.github.io/END2END_Ge_Simulation/methods/index.html)
- Inspect the [17 detector models](https://kunming-cn.github.io/END2END_Ge_Simulation/detectors/index.html) and their [cryostat assemblies](https://kunming-cn.github.io/END2END_Ge_Simulation/assemblies/index.html). Control lists executable combinations.

## Work with the source

`transport/` owns radiation deposits, `simulation/` owns fields, drift and analog electronics, and `tools/gegi_digital_readout.py` implements the GeGI digital branches. The maintained generators in `tools/` build the saved website in `docs/`. [Maintenance guide](tools/MAINTENANCE.md) · [Current handoff](PROGRESS.md) · [Platform test record](https://github.com/Kunming-CN/END2END_Ge_Simulation/pull/1)

[Issues](https://github.com/Kunming-CN/END2END_Ge_Simulation/issues) · [Contributing](CONTRIBUTING.md) · [Citation](CITATION.cff) · [MIT license](LICENSE) · [Third-party and data rights](THIRD_PARTY_NOTICES.md)
