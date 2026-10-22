# GeSignal — HPGe Radiation-to-Readout Simulation

**GeSignal (`END2END_Ge_Simulation`)** follows radiation in high-purity germanium
(HPGe) detectors from energy deposits to signed signals and an energy measurement:
**Geant4/remage → SolidStateDetectors.jl → preamplifier → analog shaper → peak ADC**.

> **[Open the GeSignal website →](https://kunming-cn.github.io/END2END_Ge_Simulation/)**
> Explore saved simulations and detector models online, with no installation.

## Start here

| Your goal | Where to start |
|---|---|
| Learn the signal chain | [Follow one signal](https://kunming-cn.github.io/END2END_Ge_Simulation/spectra/pipeline.html): six saved Cs137 10K examples connect deposits, charge, electronics and original event identities. |
| Explore saved results and geometry | [Browse studies](https://kunming-cn.github.io/END2END_Ge_Simulation/results/index.html), including Cs137 10K, 1M and GeGI; inspect the [detector catalog](https://kunming-cn.github.io/END2END_Ge_Simulation/detectors/index.html) and [cryostat assemblies](https://kunming-cn.github.io/END2END_Ge_Simulation/assemblies/index.html). |
| Run a new simulation on your computer | Follow the [Windows setup and use guide](https://kunming-cn.github.io/END2END_Ge_Simulation/guide.html), then start the local Control interface. |

## Run locally

[Download the student software ZIP](https://github.com/Kunming-CN/END2END_Ge_Simulation/releases/latest/download/END2END-Ge-Student.zip),
extract it and open `tools/site_guide.html`. After preparing the dependencies,
start **Control.cmd** on that computer to choose a compatible cryostat, detector
and source, check the plan, and run, stop or resume a simulation. The guide and
local compatibility checks identify the supported combinations.

The public website displays saved results. New simulations run locally through
Control. The software ZIP contains code, models and the guide; saved website
studies are a separate optional download.

## Source map

```text
END2END_Ge_Simulation/
├── transport/             # Geant4/remage radiation transport and deposit export
├── simulation/            # Julia/SSD fields, carrier drift and electrode signals
│   └── readout.jl         # Preamplifier, analog shaper and peak ADC
├── scenarios/             # Source presets, compatibility and run configurations
├── tools/                 # Local Control, orchestration, website generators and tests
│   └── site_guide.html    # Maintained Windows setup and use guide
├── models/                # Versioned SSD YAMLs, includes and provenance catalog
└── docs/                  # Generated website — edit its maintained sources, not docs/
```

Use the [maintenance guide](tools/MAINTENANCE.md) to find each component's source
owner and [PROGRESS.md](PROGRESS.md) for the current development handoff.

<details>
<summary>Scientific scope</summary>

Saved studies are engineering simulations with their own inputs, event counts
and validation limits. Deposited-energy truth (Edep) and readout-derived energy
(Erec) describe different stages. Model geometry, compatible operating settings,
numerical convergence and agreement with experiment must be assessed separately.
Setup has been checked on the existing Windows/WSL computer; fresh-machine
portability remains unvalidated.

See [Methods](https://kunming-cn.github.io/END2END_Ge_Simulation/methods/index.html)
for stage definitions, calibration, counting rules and study-specific limits.

</details>

## References and contributions

[Report a problem or suggest a change](https://github.com/Kunming-CN/END2END_Ge_Simulation/issues),
or read [Contributing](CONTRIBUTING.md). Cite the software with
[CITATION.cff](CITATION.cff). Original software and maintained-source documentation
use the [MIT License](LICENSE); [third-party and data rights](THIRD_PARTY_NOTICES.md)
remain separate.
