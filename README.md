# GeSignal — HPGe radiation-to-readout simulation

GeSignal follows gamma-ray energy deposits in high-purity germanium through charge induction and detector readout. Browse saved research or run and analyze your own simulation.

[Explore the website](https://kunming-cn.github.io/END2END_Ge_Simulation/) · [Choose a research study](https://kunming-cn.github.io/END2END_Ge_Simulation/results/index.html) · [Download and run locally](https://kunming-cn.github.io/END2END_Ge_Simulation/guide.html)

## Run a simulation

[Download the student software](https://github.com/Kunming-CN/END2END_Ge_Simulation/releases/latest/download/END2END-Ge-Student.zip), extract it, then **open `START_HERE.html` before opening Control**. This opens the included [installation guide](tools/site_guide.html#requirements) in your browser without Python. The ZIP contains source, models and dependency locks; it does not contain installed environments.

| Computer | Install first | Then prepare the project |
|---|---|---|
| Windows x64 | Windows Python 3.10+ (3.13 recommended) with NumPy in that same Python; Juliaup; WSL2 with Ubuntu-24.04; Pixi inside Ubuntu | Follow the [Windows commands](https://kunming-cn.github.io/END2END_Ge_Simulation/guide.html#setup): install Julia 1.13.0 and the locked Julia packages, install the locked WSL transport packages, acquire the cryostat files and build the exporters. Launch `Control.cmd` with the configured Python. |
| macOS 13+ · Apple Silicon or Intel | Juliaup, Pixi 0.81+ and Apple Command Line Tools, using a native Terminal | Follow the [Mac commands](https://kunming-cn.github.io/END2END_Ge_Simulation/guide.html#setup-macos), then run `Setup.command`. It installs the locked Python/transport and Julia packages, fetches cryostat files and builds exporters. Open `Control.command` afterward. |

The transport locks install Python, NumPy, SciPy, h5py, PyYAML, remage 1.1.0, Geant4 11.3.2 and build tools. The Julia manifest installs SolidStateDetectors.jl 0.11.8, JSON 1.9.0, Unitful 1.29.0 and their dependencies. Windows Control uses a separate Windows Python with NumPy: installing packages only inside WSL does not prepare it. Additional modules for direct Windows data analysis are listed in the guide. Git is optional for source development; the student ZIP workflow needs no Git, GPU or ParaView.

The [language, tool and complete package tables](https://kunming-cn.github.io/END2END_Ge_Simulation/guide.html#languages) cover Python, Julia, the Pixi-supplied C++17 compiler/CMake/Ninja, Windows PowerShell/Command Prompt, Bash and browser HTML/CSS/JavaScript, with platform versions and full lock-file links. Student runs need no Node.js or npm; CUDA.jl 6.4.0 belongs only to the separate optional NVIDIA example environment.

The complete commands and checkpoints are in the [public setup guide](https://kunming-cn.github.io/END2END_Ge_Simulation/guide.html#requirements), also included at `tools/site_guide.html`. After setup, follow its [first SAP22/Cs-137 run](https://kunming-cn.github.io/END2END_Ge_Simulation/guide.html#local-control). Research exhibits and saved study data live on the website; GeGI calibration is a separate download.

## Explore saved results

- [Follow one signal](https://kunming-cn.github.io/END2END_Ge_Simulation/learn/signals/index.html) from a saved Cs-137 energy deposit to readout.
- [Browse the research](https://kunming-cn.github.io/END2END_Ge_Simulation/results/index.html): GeGI archived-library shared readout, four independent GeGI acquisitions, and separate Cs-137 10K and 1M studies. Each keeps its own sample, settings and identities.
- Inspect the [17 detector models](https://kunming-cn.github.io/END2END_Ge_Simulation/detectors/index.html) and their [cryostat assemblies](https://kunming-cn.github.io/END2END_Ge_Simulation/assemblies/index.html). Control lists executable combinations.

Geant4/remage provides radiation deposits; SolidStateDetectors.jl calculates fields, drift and electrode charge. LBNL examples use analog shaping and a peak ADC. GeGI studies use nominal digitized strip readout and signal-derived interaction candidates. [Methods and interpretation](https://kunming-cn.github.io/END2END_Ge_Simulation/methods/index.html) distinguish functional software checks, numerical convergence and agreement with experiment.

## Work with the source

`transport/` owns radiation deposits, `simulation/` owns fields, drift and analog electronics, and `tools/gegi_digital_readout.py` implements the GeGI digital branches. The maintained generators in `tools/` build the saved website in `docs/`. [Maintenance guide](https://github.com/Kunming-CN/END2END_Ge_Simulation/blob/main/tools/MAINTENANCE.md) · [Current handoff](https://github.com/Kunming-CN/END2END_Ge_Simulation/blob/main/PROGRESS.md) · [Platform test record](https://github.com/Kunming-CN/END2END_Ge_Simulation/pull/1)

[Issues](https://github.com/Kunming-CN/END2END_Ge_Simulation/issues) · [Contributing](https://github.com/Kunming-CN/END2END_Ge_Simulation/blob/main/CONTRIBUTING.md) · [Citation](CITATION.cff) · [MIT license](LICENSE) · [Third-party and data rights](THIRD_PARTY_NOTICES.md)
