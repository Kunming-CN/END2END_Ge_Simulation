# Geant4/remage: radiation transport, not semiconductor charge transport

This directory keeps one pinned Linux environment for radiation energy deposits.
Windows uses Ubuntu 24.04 under WSL2; SSD remains native Windows Julia.
The Pixi manifest pins remage 1.1.0 and Geant4 11.3.2, selected from the same
conda-forge build family. Keep pixi.toml and pixi.lock together; upgrade on a
branch and rerun the smoke test before merging. Do not use a floating latest image.

## Boundaries

Geant4/remage models radiation interactions and records deposited energy,
position, time and event identity. SSD models electron/hole drift and electrode
signals. Electronics, digitization and reconstructed energy are a later layer.
Installing remage does not improve or validate carrier diffusion, trapping or
recombination. These must be checked against the selected SSD model and data.

## The laboratory cryostat

The user selected jintonic/geant4 at commit
`1ff3371e0afb804115773af0541b3e56bd660f8c`, directory
`detector/Ge/cryostat/LBNL`. See cryostat-source.json for original file hashes.
The original files are retained locally in `.local/transport/LBNL/`; they are
not substituted with a generic cryostat and are not part of the website.
The pinned repository did not expose an explicit license file. This project
records provenance without republishing or relicensing those upstream files.

## Run on the configured Windows computer

From the repository root in PowerShell:

```powershell
.\transport\Run.cmd versions
.\transport\Run.cmd smoke
.\transport\Run.cmd python check_smoke.py
```

`smoke` refuses to overwrite `.local/transport/smoke.lh5`. The supplied Ge box,
100 photons and source macro are installation checks ONLY, not cryostat geometry
or a prediction of experimental efficiency. LH5 output includes metres for
positions, ns for times and keV for energy: conversion to SSD must be explicit.
No-deposit primaries remain represented by the total/vertex data; do not confuse
step rows, deposited events and simulated primaries when building efficiencies.

## Reproduce the Linux environment

Install WSL2/Ubuntu on Windows, then install Pixi inside Linux following its
[official instructions](https://pixi.prefix.dev/latest/installation/).
Native Linux users do not need WSL. Run from `transport/`:

```sh
pixi install --locked
bash run.sh versions
bash run.sh smoke
bash run.sh python check_smoke.py
```

The project-local `.pixi/config.toml` places the large Linux environment in Pixi's
managed Linux cache, not the synced Windows folder. It is a runtime installation,
not a second source checkout. Installation requires several GB for Geant4 data
and dependencies. `Run.cmd` selects Ubuntu-24.04; `run.sh` is the native Linux
entry. Only Linux x86-64 is locked here; macOS is not claimed as tested.

## Before connecting the cryostat to SSD

The upstream is Geant4 `.tg` text geometry, while remage normally reads GDML.
Its `/geometry/source` macro belongs to the original application, not remage.
There are two distinct variants: a monolithic `LBNLcryostat.tg`, and the modular
`planar4wings.tg -> stage.tg -> shield.tg -> chamber.tg` include chain.
Do not merge both variants or silently replace their detector with an SSD model.
The modular detector uses a 10 x 5 x 10 mm bulk and separate handling wings;
its coordinates/orientation must be reconciled with the selected SSD geometry.

Conversion and LBNL overlap/material/placement verification are still pending.
Preserve the distinction between bulk and wings, choose the correct as-built
variant and source placement, then export Geant4 deposit identities/positions/
times without mistaking them for carrier drift times. Preserve zero-deposit
primaries for efficiency and event accounting. Do not cluster deposits before
checking the spatial/time resolution needed by the semiconductor response.

References: [remage installation](https://remage.readthedocs.io/en/stable/manual/install.html),
[remage geometry](https://remage.readthedocs.io/en/stable/manual/geometry.html),
[original LBNL geometry](https://github.com/jintonic/geant4/tree/1ff3371e0afb804115773af0541b3e56bd660f8c/detector/Ge/cryostat/LBNL).

Geometry compatibility warning: the pinned LBNL source sets an end-cap inner
diameter of 67.7 mm, while the distributed GeGI model has a 90 mm body width.
These are not interchangeable hardware setups. Do not automatically place GeGI
inside this cryostat. Start the LBNL coupling with a suitably sized laboratory
prototype and verify the holder/shield clearance and the actual mounting
orientation. Dimensions in these source models are not a substitute for an
as-built survey of the experimental assembly.
