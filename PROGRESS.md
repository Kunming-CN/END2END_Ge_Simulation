# Project progress

Updated: 2026-09-25 (local)

Current: website/model downloads are live; configurable CPU/CUDA examples and the local Geant4/remage installation are verified. LBNL geometry conversion and radiation-to-charge coupling remain pending.

## Baseline website and migration

Status: published and verified at https://kunming-cn.github.io/END2END_Ge_Simulation/

Verified on the development computer:
- Installed Git 2.55.0.3 and GitHub CLI 2.101.0.
- Repaired old workspace paths in 379 text/configuration/scene files. Originals are in one ignored `.local/migration-originals.zip`.
- All 17 model files match their recorded SHA-256 hashes; referenced baseline files exist where required.
- Replayed the AK01 fixed event with Julia 1.13.0 / SSD 0.11.8: 239 waveform samples, maximum difference from the saved waveform 0.0.
- Loaded and rendered the AK01 and GeGI fixed-event ParaView scenes from the new location.
- Built a public-only website: 17 detectors, approximately 180 MB. Original fields and event binary caches were not recomputed or modified.
- Browser check: 17 homepage detector cards; GeGI has 20 selectable events; changing event/time and selecting all 34 channels works without JavaScript exceptions.
- Added the earlier GeGI notebook results and octagon geometry illustration. Manufacturer PDFs and the photograph remain local.

These are migration and functionality checks, not all-detector convergence tests or experimental validation.

## Remaining work, in order

| Milestone | Deliverable | State |
|---|---|---|
| M0 | Share existing results on GitHub Pages | Published; URL verified |
| M1 | Clean-machine calculation example, pinned environment, portable paths | M1b CPU/CUDA examples verified on Windows; full campaign and other OS checks pending |
| M2 | One Geant4/remage event connected to SSD drift and electrode signal | Planned |
| M3 | Preamp, analog shaping, ADC, independently reconstructed event energy | Planned |
| M4 | Small repeatable spectrum and documented event-level checks | Planned |
| M5 | Physics/readout refinements and comparison with measured data | Planned |

Known portability work: the original GeGI model/cache and one benchmark still reference external local directories; these references currently exist but are not distributed. Some native build scripts also name the installed ParaView/Julia executables. The website does not depend on these paths. Do not describe M1 as complete or upgrade SSD without a separate compatibility check.

## Approved execution settings

The maintainer approved the staged plan and requested Astra High for Work/Codex development tasks on 2026-09-25. The local Codex user config was inspected and already specifies `model = "gpt-6-astra"` and `model_reasoning_effort = "high"`; these existing settings were preserved. The cached model catalog lists High as supported. The preference is recorded in AGENTS.md. No Work/Codex development task was launched by this configuration check.

## Publication maintenance review — 2026-09-25

Plan approved before edits: preserve the existing calculation workspace; stage and validate web exports before replacing docs/; add portable link/privacy/inventory checks; verify the exact deployed build instead of a homepage string; clarify web-only usage. Do not install Geant4 or change scientific inputs. Review, test, and commit this as one publication-maintenance change.

Maintenance implemented: staged export, previous-snapshot protection, read-only generated-folder cleanup, deterministic public manifest, a browser-specific guide, and a portable standard-library validator. Seven guard tests passed, including failed-export preservation. The snapshot has 21 HTML pages and 1,629 checked local links (1,014 content files plus the manifest; approximately 180 MB). A repeat build returned the identical build ID and did not rewrite docs/. Exact live verification passed: the online manifest matches this local snapshot; all 21 HTML pages and representative media/data (41 files total) match their SHA-256 hashes. Build ID: bc8395cf13b9cc9a2d27990ae00edbf7efa688057dd45ada3c6e28ca775cabf0.

The public snapshot is still a results release, not a portable solver. The original calculation inputs and binary outputs were not modified in this maintenance step.

Release marker: `v0.1.0-web` (results website only). GitHub Pages deployment succeeded. An isolated browser loaded the homepage, GeGI explorer (20 event options / 34 channels), and the web guide without JavaScript exceptions. Local interactive control tests are recorded in the initial migration checks; this maintenance verification did not rerun all physical simulations.

Environment note: ParaView's bundled Python lacks SSL. The live validator now reuses installed Node.js HTTPS in that environment; normal Python continues to use its standard SSL implementation. No certificate checks were disabled and no new simulation software was installed.

## M1a plan — original models and a CPU quickstart

Approved scope: publish the 17 exact SSD YAML models with their relative include dependencies; retain source SHA-256 hashes and model/scenario limitations. Add model downloads to detector pages and one shared models/ distribution directory. Preserve the old numerical workspace. Add a separate minimal simulation/ environment and CPU-only from-scratch example, then test in a clean source checkout without field caches. Geometry parsing is not convergence validation. Defer Geant4/remage and full-batch reproduction. Use Astra High for the bounded model-publication coding task; review the diff and verify the deployed build before release.

## M1a implementation: original model distribution — 2026-09-25

Imported 17 original SSD YAMLs byte-for-byte after checking every recorded SHA-256: 12 local models, four reference configs, and the authorized external GeGI model. Nine use the single packaged `ADLChargeDriftModel/drift_velocity_config.yaml` (SHA-256 `642a2bd0df1dabd9da7c71d15950e8b84f491babfd4b4fb63abdb82162f97ce6`); eight are inline. The 20-file `models/` distribution includes portable provenance and unchanged status/assumptions. Scientific originals and caches were not edited.

Added explicit import/validation tooling, strict include and archive guards, deterministic per-detector/all-model ZIP generation, and download links through the existing site builder. Publication reads versioned models only. Site checks retain manifest/staging protection, check exact original hashes and complete downloads, scan archive metadata/text, and select all model downloads for online verification. Git preserves YAML bytes; publication stages only the validated model inventory. The preceding plan remains in place; `simulation/` is reserved for the supervising assistant.

Bounded validation used installed ParaView 6.1.1 Python 3.12.7 (`--no-mpi --disable-registry`): 18 stdlib tests passed, explicit import/re-import and `--validate` passed, and `check_site.py` passed against the unchanged existing docs snapshot (build ID `bc8395cf13b9cc9a2d27990ae00edbf7efa688057dd45ada3c6e28ca775cabf0`). Node syntax check passed. ZIP reproducibility, exact bytes, dependency completeness, unsafe paths, changed hashes, existing-edit protection, and failed-export preservation were tested. Online download selection used an in-memory transport, not a live deployment. No full-site build, publication, commit, numerical simulation, new runtime test, or clean-machine test was performed. Supervisor review/build and post-deployment verification remain pending; this work does not establish numerical convergence or experimental validation.

## M1a verification — original models and a portable CPU example

The bounded model-publication implementation was executed with Codex CLI 0.158.0-alpha.2, model gpt-6-astra, High reasoning, in this project directory using the ChatGPT login and workspace-write sandbox. The resulting changes were reviewed before publication; no subagents or separately billed API were used.

All 17 original YAMLs and the one shared include retain their exact approved SHA-256 values. Every detector page now provides its YAML and a complete ZIP with required includes; the homepage/guide also offer all-models.zip. The 18 publication/model guard tests passed. Site snapshot: 21 HTML pages, 1685 checked local links, 1052 content files plus the manifest. Build ID: 7a12acb489930eeff5ad2d698afbef1ee12dd72adcbf74416b61ffaac2f5ec0b.

The new simulation/ directory has only Project.toml, Manifest.toml, run.jl and README.md. Its pinned Julia 1.13.0 / SSD 0.11.8 environment excludes CUDA, IJulia and Plots as direct or locked packages. The installed SSD source tree was checked against its registry tree hash (c5299531f46a0e394bc957e1623f36c8e4ea5183).

A fresh, initially empty Julia depot was populated from the lockfile. A clean source directory containing only models/ and simulation/ was tested from an unrelated working directory, with no access required to the original study folders or saved field caches. All 17 models constructed successfully. The BEGe_GD32B_reference example independently solved electric and weighting potentials on CPU and generated a 662 keV synthetic-event signal. Both normal and isolated runs produced 146 samples and byte-identical signal.csv and waveform.svg; final signed charge fraction = 1.0000000921981211. Core runs took about 55 and 47 seconds; installation/initial package compilation is additional. Environment manifest SHA-256: 14b1dc8cd127ffa0ec417939ba4abdf6b31fb2258290b6f5d922f4def8ade051.

These tests were performed on this Windows x64 computer, using isolated packages/source files, not on a second physical computer. Linux/macOS and full-campaign reproduction remain untested. This is not Geant4 radiation transport or electronics/ADC reconstruction, and the quickstart grid is not the full website numerical campaign. Original scientific inputs and numerical caches were not modified.

M1a publication verified: GitHub Pages run 36209445007 completed successfully for commit 8285876. The exact online manifest matches build 7a12acb489930eeff5ad2d698afbef1ee12dd72adcbf74416b61ffaac2f5ec0b; 78 live files, including all detector YAML and ZIP downloads, passed SHA-256 verification. Release marker: v0.2.0-models-cpu. Temporary fresh-package/source/browser directories were removed after saving compact verification records and the three final example outputs.


## M1b plan — configurable SSD and optional GPU; transport preparation

Before edits: preserve original model hashes and the CPU environment; add an optional NVIDIA environment and shared CPU/GPU runner, with explicit detector/event settings and bounded CPU/GPU comparisons. GPU scope is potential solves, not a claim that all transport runs on GPU. Audit the installed SSD drift/diffusion/trapping/recombination capabilities. Prepare Geant4/remage through one simple supported installation route before coupling; preserve the pinned jintonic LBNL source and distinguish its text geometry from GDML. Stop for any required Windows reboot or unsupported installation choice. No silent driver upgrades, model changes, deletion of original results, or field-physics claims from a speed test. Codex implementation uses Astra High; supervising session handles system installation and review.

M1b benchmark scope extension, before execution: both small BEGe and Bipolar CPU/CUDA cases passed parity but did not accelerate. Add one GeGI comparison at the centre, using only the catalog readout weighting potential, minimum spacing 0.5 mm and maximum initial spacing 2 mm. Keep all original geometry/physics and parity gates unchanged; no 34-channel campaign. Report performance even if it is slower.

GeGI diagnostic: the first bounded CPU warm-up failed its electric-potential iteration tolerance at the 10000-iteration budget. The failure was retained. Add an explicit per-refinement iteration-budget option (default unchanged) and retry at 50000, without relaxing the 1e-6 tolerance or CPU/GPU parity gates. This is a numerical budget change, not a model or physics change.

GeGI 50000-budget retry also failed the strict CPU gate: last update 0.00090026855 V versus required 0.000879 V, on a 166x166x34 grid. No speed result is claimed. Add explicit Float64 as a numerical diagnostic (Float32 default and all tolerances unchanged). Source review also found that SSD.update_till_convergence! rebuilds point_types; call the existing SSD.mark_bits! helper after the extra electric relaxation, before constructing fields, so depletion/inactive classifications are refreshed. Verify baseline regression after this correction.

## M1b verified — shared CPU/GPU runner and local Geant4/remage

Implemented the shared detector/point/energy/contact/grid/device runner, explicit precision and iteration budgets, optional CUDA project, and a bounded parity benchmark. CPU remains the default. The original CPU lock and all original detector YAML/include hashes remain unchanged. The coding task used Codex Astra High; supervisor tests ran outside the coding sandbox, where Julia runtime tests had been blocked by Windows path access.

Final runner unit tests and all 17 model constructions passed. Both CPU and CUDA standalone BEGe outputs are byte-identical to the retained 146-sample CPU baseline. Three fresh-solve CPU/CUDA benchmarks passed the unchanged potential, field, waveform and endpoint gates: BEGe Float32, Bipolar Float32, and GeGI Float64. Compared potential/field/waveform arrays were identical within each tested backend pair. Each benchmark has one warm-up per backend and two measured repeats; package startup and first compilation are not included in the warm means. These short local tests are not a hardware-maximized or all-model performance study.

| Model / precision | CPU 2-thread warm mean (s) | CUDA warm mean (s) | CPU/CUDA ratio |
|---|---:|---:|---:|
| bege / Float32 | 0.377 | 1.412 | 0.27 |
| bipolar / Float32 | 3.335 | 3.818 | 0.87 |
| gegi64 / Float64 | 81.833 | 20.384 | 4.01 |

The GeGI workload solves one weighting potential, not 34 channels: centre deposit, 0.5 mm minimum grid spacing, 2 mm initial maximum spacing, 50000 maximum iterations per refinement. The two warm speed ratios were about 4.50 and 3.50 (mean-time ratio 4.01). Earlier Float32 attempts failed a strict electric-iteration gate even after increasing the iteration budget; they were not used to claim speed. Float64 passed without relaxing tolerances. The point-type finalization after the extra relaxation was corrected using SSD.mark_bits!, and the baseline regression was rechecked. Original website numerical results were not recomputed or replaced.

Installed WSL 2.7.13 and Ubuntu 24.04 on this computer with normal Windows administrator approval; no restart or Docker was needed. Installed Pixi 0.81.0 inside WSL after verifying its release SHA-256. The transport/pixi.lock environment pins remage 1.1.0 and Geant4 11.3.2; heavy packages live in the managed Linux cache, not the synced project directory. Windows transport/Run.cmd versions and smoke commands were actually tested.

The independent transport smoke test simulated 100 monoenergetic 662 keV photons in a toy Ge box. Overlap checking passed. LH5 inspection found 72 deposited events, 399 recorded steps and 28 zero-deposit primaries; finite data, event identities, bounds and total energy were checked. Output units are keV, metres and ns. This proves installation/output functionality, not the LBNL cryostat or detector response.

The nine pinned jintonic LBNL text-geometry files were fetched locally and checked against Git blob/SHA-256 values. Their provenance is in transport/cryostat-source.json. No standalone license file was found in the pinned tree; original upstream copies remain local rather than being republished. Text-geometry conversion, as-built placement/overlap checks and SSD coupling are pending. The 67.7 mm LBNL end-cap inner diameter does not accommodate the 90 mm GeGI model as a direct replacement.

Charge-physics audit is documented in simulation/README.md: drift-model-specific diffusion coefficients, signal-stage trapping and its time-step constraints, and no identified dedicated SRH/detrapping solver in the pinned source. No new recombination or calibrated diffusion/trapping model is claimed. Installation and GPU parity do not establish experimental accuracy.
