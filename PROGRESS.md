# Project progress

Updated: 2026-09-25 (local)

Current: website/model downloads and CPU/CUDA examples are available; M2a bare AK02/SAP22 radiation-to-charge replay is verified. Calibrated Li response, LBNL placement and electronics remain pending.

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
| M2 | Geant4/remage deposits connected to SSD drift and electrode signal | M2a bare AK02/SAP22 handoff verified; Li-response and cryostat gates remain |
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

M1b release verification: implementation commit 1943a28 was pushed to main; GitHub Pages run 36212446961 completed successfully. The exact online build 29914625da03f0998c972117da43d98dd4a7b01e3cf6649d05ac76ba81a65ea0 matched the local snapshot, with 78 live files checked (including model downloads). Release marker: v0.3.0-gpu-transport. Superseded trial output folders were removed after retaining final CPU/CUDA reports and combined Float32 GeGI diagnostics under .local/m1b-final. Original baseline, scientific inputs, migration backup and pinned cryostat sources are preserved.

## M2a execution plan — 2026-09-25 local

Remote connectivity restored; clean main at edd0a36 verified before creating feature/m2a-ak02-events. First implement bare AK02/SAP22 transport geometry and a versioned lossless-enough deposit handoff, then a bounded time-aware SSD replay. Preserve original model bytes, lockfiles and existing results. Use nominal stored 78 K baselines initially; explicit 77 K conditions later, never silently change snapshots. AK02 +500 V is corroborated by the private manuscript; SAP22 +700 V is the stored model setting and still needs latest experimental confirmation.

Acceptance: canonical polycone equivalence (volume and sampled point membership against Geant4 and SSD); raw LH5 with track/parent IDs, both endpoints, global positions, keV/m/ns, preclustering off; zero-deposit census; explicit rigid transform; reassembly by event ID; causal delayed-signal sum without per-event normalization. Use remage already installed, not a replacement engine. Start with coarse 100-photon coupling tests, not a Li-layer efficiency prediction. Keep all Li-volume deposited energy in transport; record model-level charge losses only once. No new recombination claim. LBNL placement and M3 electronics remain separate gates.

Use one focused Astra High implementation task, independent supervisor runtime checks, then two read-only specialist agents and cross-review before release. No permission/auth reset changes, no banked resets, no unrelated writes. Project sources stay in transport/simulation; compact evidence in .local/m2a.

M2a numerical diagnostic: AK02 Float64 at 0.05 mm minimum spacing failed the strict 0.0005 V electric update gate with default SOR both at 10000 and 50000 budgets (0.0012436695 V). Pinned SSD may stop on an update plateau before meeting tolerance in depletion switching. In-memory SOR tests gave 0.0005917673 V at 1.2–1.4 and 0.0004786505 V at 1.0; a stricter 5e-5 V target was NOT reached. Add an explicit optional relaxation parameter, default unchanged, for the new baseline replay. Fresh full solves and reviewers must validate it; this is not a grid-convergence claim.

Fresh AK02 replay with explicit SOR=1 still stopped at the same electric plateau. The earlier in-memory result required successive relaxations and does not establish a SOR-only fix. Add a bounded maximum of four extra relaxation calls in replay, preserving the same update gate and recording every returned update. The shared runner default remains one check. A failed sequence remains failed; no tolerance relaxation.

SAP22 first replay reached an analogous weighting-potential plateau (1.3052206e-6 vs 1e-6 target). Apply the same explicitly bounded four-check policy to both potentials, recording both histories; keep shared-runner default one check. AK02 electric history reached the original gate on check four. A CartesianPoint iteration assertion bug was fixed to compare explicit x/y/z coordinates; failed trial evidence is retained.

## M2a verified — bare AK02/SAP22 radiation-to-charge handoff

The native remote connection was restored, main edd0a36 was checked clean, and work stayed on feature/m2a-ak02-events. A bounded Astra High implementation task wrote only the transport adapter/probe/tests. The supervising session implemented causal SSD replay and independently ran all numerical and environment tests. No original model bytes, field caches or pinned dependency locks were changed. GeGI new development is deferred.

The adapter exports the canonical r-z contour as GDML genericPolycone, not a z-plane polycone. Actual Geant4 volume/membership and SSD contour/membership were compared. Each detector passed 34 G4 probe points including bore/groove/surface offsets; SSD passed the same closed-solid membership checks. Volumes: AK02 4082.209056019479 mm^3; SAP22 3491.724725628703 mm^3, matching independent cylinder-subtraction formulas. Runtime placement is identity only; nontrivial transform tests are synthetic, not an as-built assembly.

| Transport case | Primaries | Stored step rows | Positive-energy steps | Events with deposits | Zero-deposit primaries |
|---|---:|---:|---:|---:|---:|
| AK02 | 100 | 1283 | 1138 | 58 | 42 |
| SAP22 | 100 | 1167 | 1024 | 58 | 42 |

These are 662 keV monoenergetic side-on photons in bare crystals, not experimental source efficiency. The raw flat LH5 retains global positions/time, track/parent IDs, endpoints and zero-energy records. Primary gamma PDG, MeV energy/momentum and census are now checked from the raw particles table, with a per-event energy bound. The JSON schema keeps all primary IDs and separates local mm from raw global metres. Both 100-event records were unchanged after review-only validation fixes.

Causal replay processed primary IDs 0–9, including four zero-deposit events, at both original 78 K and explicit 77 K. AK02 +500 V and SAP22 +700 V were retained. All selected raw deposits were preserved with source row IDs and creation delays; no per-event normalization or double Li loss was applied. AK02 retains stopped_without_contact electron flags even where induced charge is near unity. SAP22 selected tracks reach geometric contacts. Neither outcome proves calibrated CCE. All raw positive-deposit positions were validated against SSD before any field solve.

Current-code fresh 78/77 K runs passed their strict electric/weighting update gates using explicit SOR=1 and bounded retries; each update history is saved. The original BEGe CPU signal.csv remains byte-identical to the 146-sample baseline. The 23 transport tests include malformed primary kinematics and source energy; causal/schema/geometry tests include a changed-but-internally-consistent transform rejected against prepared geometry. A real SSD simultaneous 10-deposit check versus the independent component sum differed by at most 7.105427357601002e-15 keV. This is linearity validation with noninteracting clouds, not experimental validation.

The two independent read-only AI reviewers (HPGe/electronics: Astra XHigh; particle/event integrity: Astra High) found no release-blocking bug in the stated interface scope. Their concrete follow-ups were implemented: bind the replay transform to prepared identity geometry, check actual primary-particle kinematics, and explicitly report SAP22 ADL's lack of temperature scaling. A fixed-field test confirms its original 77/78 K velocities are equal; AK02 mobility temperature is updated consistently. The same two review sessions then read each other's findings and the focused fixes. Both cross-reviews accepted the resolutions and recommended release within the stated bare-detector interface scope, with no remaining concrete release blocker. These are independent AI source reviews; runtime tests were executed by the supervising session, not by human certifiers.

Final M2a acceptance: 23 Python handoff tests, 40 Julia causal/schema/temperature/actual-geometry checks, two additional actual SSD linearity assertions, and the existing runner tests passed. All four 78/77 K response reports hash the current run.jl/replay.jl files; the original 146-sample CPU CSV regression passed. Raw energy/position/time records remain unchanged by review fixes. The read-only reviewer sessions and implementation task have completed; no further agents are left running. M2b Li-depth/zero-field diffusion diagnostics, grid/time/cloud convergence, measured parameter calibration, LBNL placement and M3 electronics remain pending.

Local evidence is consolidated under .local/m2a: AK02/ and SAP22/ each retain immutable raw truth/inputs, geometry-check.json and response-77K/response-78K; reviews/ retains both agent sessions and cross-reviews; checks/ and validation.json retain test evidence, original trial diagnostics and baseline regression. Superseded duplicate raw/response folders, temporary scripts and reproducible C++ build intermediates were removed only after preserving verification records. Original .local/quickstart, migration backups and LBNL source files were preserved.
