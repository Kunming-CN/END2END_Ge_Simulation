# Project progress

Updated: 2026-09-26 (local)

Current: M3b adds bounded standard scenarios, a one-thread low-load option, census-only run configuration and lossless compact offline examples. The complete AK02/SAP22 engineering workflow remains verified. Production Li/finite-conductivity accuracy, as-built geometry and calibrated hardware response remain unresolved.


## Goal and plan alignment audit — 2026-09-26

Final goal: other students can run a maintainable local Geant4/remage -> SSD -> charge-sensitive preamp -> analog shaping -> peak ADC -> reconstructed-energy/spectrum workflow, with traceable browser examples. Public results are not an online solver. AK02 is primary, SAP22 a nonmatched cross-check; GeGI stays deferred.

Both independent goal audits found a sequencing mismatch: the closing next-task emphasized further weighting/Li diagnostics while M3/M4 were absent. Revised critical path: **M3a causal readout prototype and analytic tests -> one-command full small AK02/SAP22 workflow -> offline event explorer/small diagnostic spectra -> reproducibility hardening**. Advanced finite-conductivity, Li transport convergence, production-cut/step sensitivity, as-built geometry and experiment calibration form a parallel accuracy lane. Their unresolved gates still prohibit physical CCE/efficiency/calibration claims, but do not block a labeled engineering demo. Existing diagnostics are retained, not abandoned.

M3a prospective contract: frozen synthetic finite-feedback CSA, matched pole-zero CR-(RC)^2, independent charge-injection calibration, sampled analog peak and explicitly quantized peak ADC; no per-event truth-based gain, noise/Fano/pileup, or hardware-fit claim. Preserve every selected primary including zeros/flags; record all units, seeds, settings and hashes. Run100 monoenergetic662keV bare-detector primaries per model at explicit77K and canonical biases. The pinned SSD pair energy is2.95eV and will be read from metadata, not replaced by a literature default. New source goes beside existing stage tools; generated data lives under one example root.

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
| M2 | Geant4/remage deposits connected to SSD drift and electrode signal | M2a verified; M2b4 direct SSD analytic checks added; production Li CCE, finite conductivity and cryostat remain gated |
| M3 | Causal preamp, analog shaping, peak ADC, independently reconstructed event energy | M3b scenarios and serial resource controls verified; synthetic full-chain parity retained; hardware calibration pending |
| M4 | Small repeatable workflow and traceable event/spectrum showcase | M3b lossless compact offline explorer and bounded presets verified; production statistics remain later |
| M5 | Physics/readout accuracy, as-built geometry and measured-spectrum comparison | Parallel accuracy lane; unresolved Li/finite-conductivity/calibration gates remain explicit |

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

M2a publication verified: implementation commit 1e7495f was pushed to main; GitHub Pages run 36217261727 completed successfully. The exact live snapshot ee41eb7c32afd0af65c536a5f750b8323170a9e2beffab42daf0bf7a5b45f4e4 matches the local website, with 78 files checked including all model downloads. The initial live check correctly rejected the not-yet-deployed version, then passed after deployment. Release marker: v0.4.0-event-handoff. New source and instructions are published; the original numerical gallery remains precomputed, and M2a raw runs/reviewer logs stay local.

## M2b1 plan — endpoint diagnosis before Li-CCE claims

Confirmed remote device response and clean main at 95112e0 before this task. Bound this step to explaining AK02 unresolved electron endpoints and testing the zero-field diffusion switch, not a calibrated Li-layer or electronics model. Reuse locked SSD0.11.8 and exact AK02/SAP22 models at explicit 77 K. Add one diagnostic entry and its tests under simulation/. No changes to existing replay/solver defaults, source geometry, lifetimes, impurity inputs or package files.

Prospective checks: sample radial depth at detector mid-height, record local field, weighting potential, net/donor concentrations, grid flags and nearest-electrode distances. Compare dt=1,2,4ns and minimum refinement settings0.05/0.025 mm only as sensitivity checks, not certified convergence. Preserve no-contact/step-cap flags. For unchanged drift paths compare original trapping with an explicit no-trapping diagnostic using the analytic Ramo endpoint difference; never renormalize charge. Verify synthetic zero-field ensemble diffusion versus per-axis2Dt, and that the existing zero-field-stop switch prevents diffusion when enabled. Any mobility-specific or boundary diffusion remains a separate gate. Review with the same two specialist roles before publishing status.

M2b1 first bounded run: both AK02 refinement settings and SAP22 at 0.05 mm completed. The SAP22 0.025mm weighting check remained at1.2678171e-6 after four continuation calls (target 1e-6). Preserve this failure and test at most eight existing continuation calls for this diagnostic entry only; do not relax tolerance or change replay/solver defaults. The synthetic zero-field2048-carrier test passed its prospectively fixed moment gates. Cast rational material diffusion coefficients to numeric floats in JSON.

## M2b1 measured diagnostics — physical CCE still blocked

The school computer remained reachable while the maintainer used a phone; a real ping and clean-worktree check succeeded. Work continued on feature/m2b-collection-diagnostics. Two new simulation files provide endpoint/depth diagnostics and lightweight guards; models, package locks and replay sources are unchanged. Review hardening adds only an optional observer to the shared solver, preserving numerical defaults. All inputs are at explicit 77 K and retain original +500/+700 V biases.

Completed 144 synthetic point/time/refinement cases: two detectors, twelve mid-height radial depths, three time steps(1/2/4 ns), and two minimum refinement settings(0.05/0.025 mm). These minima are not uniform cell sizes. A no-trapping calculation on the same paths agrees with the Ramo final weighting-potential difference. For the AK02 depth 1 mm / dt 2 ns/coarse example, the electron stops at exactly zero interpolated field about 0.4545 mm short of the geometric outer contact, with weighting potential 5.44e-9; the hole reaches the point contact. Its near-unit induced signal is therefore internally consistent with the model, but is not proof of metal collection or a measured dead-layer boundary.

**Critical interpretation limit:** AK02 has strong near-surface grid dependence. The maximum change in signed induced fraction between these two refinement settings is 0.99564775; the maximum1/2/4ns time-step range is 0.00099184. Some fine-grid electron paths reach the sample cap in extremely small but nonzero fields. Preserve those flags. Do not threshold small fields to zero or rescale signals to hide this. No quantitative CCE, dead-layer thickness, or convergence claim is released. SAP22 showed much smaller changes for the selected points(grid1.2143e-6, time-step2.7918e-6), but is not a matched-geometry Li-only control.

An independent synthetic zero-field functional test used 2048 carriers per species for 400 ns. With zero-field termination on, all displacements were zero(two stored positions); with it off, the unmodified SSD diffusion algorithm produced per-axis variances consistent with 2Dt using its material De = 0.0239 and Dh = 0.0279 m^2/s. Seed 260926 and prospectively fixed six-standard-error gates were recorded. This tests the fallback branch only, not AK02 mobility-tied diffusion, losses at boundaries, self-repulsion or microscopic recombination.

The first four-check diagnostic run correctly failed the fine SAP22 weighting gate(1.2678171e-6 versus1e-6). The explicit diagnostic-only limit was increased to at most eight continuation calls; all four fresh field cases then met the unchanged gates, with histories retained. Existing replay and solver defaults were not changed. Initial failure evidence is kept; an iteration gate is not a grid-convergence certificate.

Primary method references: SSD charge drift documentation https://juliaphysics.github.io/SolidStateDetectors.jl/stable/man/charge_drift/ and Zhang et al., EPJC86,303(2026), https://doi.org/10.1140/epjc/s10052-026-15508-3. Implementation checks refer to pinned SSD0.11.8 source, especially ChargeDrift/ChargeDrift.jl, SignalGeneration/SignalGeneration.jl and ScalarPotentials/PointTypes.jl. The documented three-region method remains a basis for later calibrated work, not a claim validated by these diagnostics.

Independent M2b1 reviews agreed that diagnostic-only publication is reasonable but physical CCE remains blocked. Implement targeted hardening before release: rename sample-budget status from time_limit to step_limit; verify unchanged models before writing completion; prove the synthetic diffusion cloud cannot reach a boundary and check each full random-walk increment; add an optional observer to the shared solver solely to retain continuation history if a gate fails. The observer default is absent and must leave numerical results/replay defaults unchanged. Rerun source tests, diagnostic suite and CPU baseline after these fixes, then cross-review.

The maximum grid change occurs at the sampled 0.5 mm radial depth(dt = 2 ns): coarse-grid induced fraction 0 versus fine-grid 0.99564775. This is near a sharp no-diffusion transition, not a measured dead-layer thickness and not proof that all bulk event predictions are wrong. Further work must resolve the transition position/shape under grid refinement and diffusion, rather than silently smooth or renormalize it.

M2b1 review closure: two independent Astra High read-only specialists(HPGe/electronics and particle/numerical integrity) cross-read the other report and accepted diagnostic-only release after the focused fixes. The last two wording issues were corrected: current summaries use step_limit and README uses step cap. The severe AK02 near-transition grid sensitivity remains a prominent blocker to physical interpretation.

Final checks: all 144 point-case fraction arrays are unchanged by review hardening; 15 lightweight guards, existing 88 runner checks and 40 replay/schema/geometry checks passed. A known failed four-check solve preserved its full continuation observations. The original 146-sample CPU signal.csv stayed byte-identical. The final diffusion check also verifies full hop length, total duration, and a clearance/excursion bound excluding any boundary interaction. No new electron/hole physics, material fit, cryostat model or electronics stage was introduced.

M2b1 evidence is consolidated in .local/m2b/results(depth-scan.csv and run.json), checks, reviews and validation.json. Initial failure diagnostics and the failed-observer test remain available; superseded duplicate outputs and temporary verification scripts were removed. Original M2a raw events, original CPU baseline and model snapshots are preserved. The fifteen new guards, legacy tests and all18 publication checks passed. Both cross-review sessions completed.

M2b1 publication: implementation2448c57 pushed to main. The existing website snapshot was deliberately unchanged and again matched78 live files; raw diagnostic outputs remain local. Release marker:v0.5.0-collection-diagnostics. This is a diagnostic release, not completion of calibrated M2b or M3.

## M2b2 prospective plan — 2026-09-26

Maintainer requested continued successive rounds with specialist questions/cross-review and primary-literature checks; no per-round confirmation required. Start from clean main e64b57f. Round A: quantify whether the large no-diffusion jump reflects motion of a sharp numerical transition by recording continuous E/W profiles and actual grids across bounded refinements; no manual smoothing, field clipping or gate relaxation. Round B: test the actual AK02 mobility-tied diffusion branch against a controlled constant-coefficient analytical limit, then decide a bounded physical diffusion ensemble only if the prerequisite passes. Keep Li CCE calibration blocked until convergence/uncertainties support it. No canonical model or lockfile changes.

Experimental clarification from the maintainer: Cs137 or Am241 is placed on the aluminum cryostat lid directly above the detector. This is not a collimated side-on source; M2a remains a synthetic side-on interface test. Source active dimensions/encapsulation, top-lid thickness, crystal-to-lid gap and detector orientation are not independently established. Record unknowns rather than inventing them or importing dimensions from another LBNL detector. Read-only searches elsewhere in My Drive remain authorized.

M2b2 exploratory Round A: four profile cases ran. Smaller minimum spacing did not imply a finer electric grid; local radial gaps remained about0.09mm. A fixed-endpoint cross-weighting test shows the zero/near-unit jump at0.5mm is chiefly trajectory/field-front dependent, with much smaller weighting-grid changes on the same endpoints. Exact-positive E is contaminated by tiny nonzero values; reporting1e-6/1/10V/cm crossings is diagnostic only and never clips fields. Before a second run, add max-tick caps0.05/0.025mm to actually refine these cells. Physical FDD/CCE remains unvalidated. The mobility check will use1/2/4ns over400ns and include predeclared mean/variance/cross-covariance guards in homogeneous clones.

M2b2 fine-grid failure preserved: max-tick0.05mm generated312x1x272 electric nodes but the eight continuation updates monotonically decreased0.00669286 to0.00306155V, above the unchanged0.0005V gate. This is not a flat floor or successful solve. Before rerun, allow an explicit bounded64-check budget for this grid diagnostic only (at most3000 iterations/check). Shared default1, replay4 and prior diagnostic8 remain unchanged; all returned updates are retained. No error tolerance, model or field threshold is relaxed. If the finer run still fails, retain the block instead of fitting through it.

M2b2 specialist source audit found no demonstrated calculation defect in the bounded design but required reporting/test hardening: record requested continuation budgets before solving, finalize failed mobility setup state with stage, remove ignored step/dt keyword arguments from the fixed test matrix, and directly test restoration after an injected replacement exception. Implemented these without changing any valid numerical inputs or acceptance tolerance; final exact-source reruns/review remain required.

M2b2 homogeneous-mobility functional test passed all18 species/depth/dt combinations at2048parcels, but the fixed six-SE screens are not precision calibration (largest observed variance deviation about13.14%). Before interpreting numerical precision, add a larger8192-parcel check of the same fixed matrix and same coefficients, with the same six-SE formulas (automatically narrower), preserving all initial results. This is a parcel-count sensitivity check, not a new calibration or a separately measured data set.

M2b2 stricter spacing result: cap50(max tick0.05mm) passed the unchanged solver gates after27 electric and8 weighting continuations, but the1V/cm reporting crossing shifted from0.484–0.486mm(cap100) to0.544–0.546mm(cap50). Thus the numerical front has NOT converged. Cap25(606x1x528 electric grid) failed even the explicit64-check gate: final0.0014441514V >0.0005V after a bounded655.7s six-case run. Preserve failure; do not further raise the budget blindly. The heavy cap25 stress case is now explicitly callable as --phase fine, while --phase fields repeats the five lower-cost diagnostic cases; both are documented and neither represents CCE validation. This is workload separation, not removal of the failed result.

M2b2 final validation plan: regular fields phase now reproduces the five completed configurations on the hardened source; the expensive failed cap25 remains explicit via phase fine and its original failure record is retained. Repeat both2048/8192 mobility matrices on the same final source and require unchanged sample statistics, then rerun old CPU/regression/schema guards. Commit the candidate source on its feature branch before these longer runs so exact tested code is recoverable; merge only after final review.

## M2b2 verified diagnostics — transition grids, actual mobility branch and references

Successive rounds were executed without per-round owner intervention. The two existing independent specialist sessions first proposed tests and asked each other questions, then answered the counterpart's questions, audited the implementation and received final evidence for cross-review. HPGe/electronics used Astra XHigh; particle/numerical integrity used Astra High. These were actual read-only AI sessions, not simulated role dialogue. No parameter fit, package upgrade or original-model edit was performed.

Round A independently records actual electric/weighting ticks, 2-micrometre common-coordinate profiles, 105 synthetic tracked points across five configurations, and a fixed-endpoint cross-weighting matrix. Merely reducing minimum spacing did not refine the relevant electric mesh: min25/min12p5 have the same electric dimensions/ticks, despite changed weighting grids. Maximum-spacing caps do refine it. The model's doping-compensation root remains about0.706800mm; this is not measured FDD/FCCD.

| Case | Electric grid | Weighting grid | First sampled field >1 V/cm bracket (mm) |
|---|---|---|---|
| min50, max2mm | 166x1x142 | 38x1x56 | 0.520–0.522 |
| min25, max2mm | 166x1x144 | 42x1x64 | 0.466–0.468 |
| min12p5, max2mm | 166x1x144 | 46x1x66 | 0.466–0.468 |
| cap100, max0.1mm | 184x1x166 | 170x1x154 | 0.484–0.486 |
| cap50, max0.05mm | 312x1x272 | 316x1x278 | 0.544–0.546 |

**Physical interpretation remains blocked:** the passing cap100/cap50 cases move the reported crossing by about60micrometres. The cap25 stress case failed after64continuations at0.0014441514V against the unchanged0.0005V gate, on606x1x528electric nodes. The original failed report/source hashes are retained. The current `fine` entry exposes this workload separately; it was not rerun after reporting-only hardening and no success is claimed. Regular `fields` deliberately covers the five completed configurations, not the failed stress point. First-exceedance brackets are not continuous physical boundaries; censored zero-threshold brackets and extremely small fields are retained, not clipped.

The fixed-endpoint matrix shows that the zero/near-unit discrepancy at0.5mm is dominated by changes in paths/field turn-on: stopped coincident endpoints give zero under every tested weighting solution, whereas the moving-path endpoints give approximately unit signal across weighting solutions. The latter differences are much smaller, but include weighting-solution/depletion-map changes, not merely interpolation. Hybrid combinations are diagnostics, not self-consistent detector predictions.

Round B exercises the actual InactiveLayerChargeDriftModel mobility-tied diffusion branch in disposable homogeneous-coefficient clones, using coefficients sampled from0.1/0.5/1mm depth. Both species,1/2/4ns time steps and400ns duration give18ensembles per parcel count. All full-hop, duration, boundary-clearance, mean/variance/cross-covariance guards passed for2048 and8192parcels/species. Largest measured relative variance deviations from2Dt were13.1417% and3.0366%, respectively, within predeclared six-SE bounds18.7546% and9.3756%. These are finite-sample functional checks, not claimed physical-model accuracy or near-surface CCE calibration.

Source audit corrections were validated without changing the accepted numerical inputs: requested budgets are available on failures; mobility failures record their stage; ignored keywords were removed; moment dimensions/finite values are checked; a real injected replacement exception verifies detector restoration. The final candidate1d0ce04 rerun reproduced all five-case profile bytes and105signed fractions, both18-ensemble statistics arrays, and the original146-sample CPU baseline CSV. All four numerical-source hashes match those completed reports. Forty-three new guards,88legacy runner checks,40replay checks and15collection checks passed. The larger stress failure is explicitly pre-reporting-hardening evidence, not an unperformed current-version pass.

Both specialist sessions exchanged questions about deposition subdivision and top-source metrology, spatially varying diffusivity and neutral-layer conductivity. They then cross-read the other's audit and checked the focused resolutions. Both accepted diagnostic-only publication once legacy checks finished (now passed); neither certified physical CCE or an as-built apparatus. Constant-D agreement does not choose between laplacian(Dn) and div(D grad n); a large static permittivity is not a measured conductivity. No gradient correction or new lifetime was silently added to SSD.

The shared PHYSICS.md records primary references: Zhang2026 reduced-charge-collection method, Dai2023 mobility/CCE transport, Aguayo2013 real transition-layer pulse examples, Abt2021 measured/simulated superpulses, Riegler2019 finite-conductivity weighting, and temperature-dependent drift measurements. Aguayo Fig6's current is500ns-averaged and display-smoothed; literature plots are not raw AK02 data or transferable electronics constants. The canonical neutral concentration matches an upstream example setting, which is not evidence it was measured for AK02. No new validated AK02/SAP22 waveform data set was identified in the limited read-only source search.

The owner's dissertation baseline-equipment table identifies LBNL Square/BF862 (nominal0.6pF), ORTEC671 shaping, ORTEC927 MCA, DSOX3034A scope and CANBERRA814FP pulser. Exact acquisition settings remain unresolved. Official ORTEC documentation supports an analog-shaper/pulse-height-ADC topology, not an assumed digitize-first waveform chain. transport/experiment.json records source-on-Al-lid placement and separates these documented items from unknown active-source construction, lid thickness, crystal gap and orientation. Laboratory above is not assigned SSD+z. No upstream planar dimensions were substituted as an AK02 survey.

Next bounded autonomous round: independent electrostatic residual/flux verification on a small analytic nonuniform cylindrical problem, without altering the production solver; then a planar two-layer finite-conductivity weighting-response benchmark with explicitly synthetic parameters. Use primary theory and cross-review; do not raise cap25's budget blindly or infer AK02 conductivity. These independent checks can proceed before human metrology is available, but physical CCE and cryostat efficiency remain gated. Successive work is scheduled hourly with a single-owner state/lock, so active rounds are not duplicated. No banked-reset use or separately billed API is permitted.

M2b2 evidence is consolidated under .local/m2b2: results/ contains final fields and both parcel-count mobility reports; checks/ retains all exploratory/failure reports and baseline verification; reviews/ contains reciprocal questions, answers, audits and final cross-reviews; research/ holds the private local copy of the public reference PDF and reference inventory; validation.json is the compact index. Superseded duplicate mobility outputs and temporary verification scripts were removed after exact-array comparisons. Original M2a/M2b data, canonical models, lockfiles, migration backup and cryostat source copies were preserved. No review or numerical worker from this round remains active.

Reference-location check: the current rendered generic charge-drift page omits the numerical example visible in the pinned0.11.8 source; the public TrueCoaxial inactive-layer tutorial explicitly shows5.6769e15cm^-3. The reference map now links that direct example and preserves the distinction from measured AK02 provenance. The same tutorial demonstrates local nonuniform grid refinement; after independent residual checks, reuse this existing grid API rather than blindly tightening every domain cell. No production grid or physical parameter was changed by this documentation clarification.

M2b2 publication verified: implementation candidate1d0ce04 and reviewed documentation0ffa43b were merged and pushed to main; Pages run36223099417 succeeded. The live snapshot d2d6fbe17da0168cf49b512e3519e8efebd18eb7db6e85bbdac8dce353660e10 matches all78 selected live files including model downloads. Eighteen publication/model guard tests passed. Release marker: v0.6.0-transition-verification. Original numerical galleries remain precomputed; only guide/navigation and source documentation changed. Final numerical sources remain those tested at1d0ce04; the later direct-reference correction is documentation only.

## M2b3 prospective plan and spectrum-only clarification — 2026-09-26

Interactive runtime restored real process access. Verified clean synchronized e47573e, no prior terminal/Julia workers, no active owner, and an empty stale automation lock. Preserved prior state before acquiring an owned lock. Do not restart inactive scheduled tasks or imply background execution succeeded. Owner confirms AK02/SAP22 raw measured waveforms were not saved; measured spectrum data were saved. Update experiment.json and move experimental validation to spectrum observables with unresolved run metadata/identifiability, not waveform recovery.

Round A continues the planned independent annulus benchmark: synthetic rho=0, radii5/15mm, potentials0/500V, V=Vb*ln(r/a)/ln(b/a). Independent midpoint finite-volume tridiagonal operator on prescribed nested nonlinear grids17/33/65 nodes. Predeclare normalized algebraic residual<=1e-11, flux spread<=1e-10, exact boundary enforcement, finest relative voltage/face-field errors<=1e-3, and error decrease consistent with second order (fine/coarse<=0.4). Test sign, zero/log-grid limits and intentional perturbations. This verifies an independent diagnostic operator, NOT the AK02 depletion solver or Li CCE.

Round B is prompted by the owner: compare Geant4 Livermore/Penelope/Option4 constructors using the existing bare AK02 interface geometry at monoenergetic59.5/662keV (not full Am241/Cs137 decays). Use identical geometry/cuts/no electronics, record atomic-relaxation flags and actual runtime model banner, distinct seeds and5000 primaries per case, event-level total deposited energy including zero events, unbroadened spectra with count uncertainties. No winner or detector-specific accuracy is inferred from constructor agreement. Published remage documentation confirms these affect radiation interactions, not semiconductor carrier mobility. Keep baseline Livermore unchanged. Review with two independent specialists who exchange questions and findings before release.

EM initial six-case smoke completed; before final validation add one independent-seed Livermore control per energy, source-origin/direction/time checks against raw vertices/particles, exact Geant4-data package versions and independent-binomial difference intervals. Newcombe-Wilson marginal95 intervals are exploratory, not simultaneous/equivalence tests. The final eight-case run uses5000 primaries each. This is validation hardening, not physics or parameter tuning.

Post-review statistical hardening: preserve all eight fixed seeds and original counts. Add structured fluorescence/Auger/PIXE/ignore-cut checks and effective-cut log checks; export Wilson bounds for every spectrum bin including empty bins. A post-hoc family of all six containment contrasts (including both same-Livermore controls) receives two-sided Fisher exact tests and Holm adjustment, explicitly labeled exploratory after observing the original unadjusted intervals. SciPy1.18.1 is already in the locked environment; no dependency upgrade. Do not select/retry random seeds to make the same-constructor control agree.

## M2b3 independent electrostatics and EM comparison — measured checks

The interactive school-computer connection and process tools worked. Prior scheduled
runtime failure was not treated as successful background execution; its inactive
state was left unchanged. An inspected empty stale lock was recovered with the
previous state preserved. All work remains on the focused feature branch until review.

Owner correction is recorded in transport/experiment.json: no original AK02/SAP22
measured waveforms were saved; measured spectra remain available but are not yet
ingested. Future experimental checks target calibrated spectrum observables with
background/live-time/acquisition metadata and parameter degeneracy, not pulse recovery.

The independent charge-free annulus verifier passed its original gates. On nested
17/33/65 nonuniform grids, relative voltage errors were 2.672815e-5, 6.663323e-6,
1.665041e-6; relative midpoint-field errors were 4.067025e-4, 1.017166e-4,
2.543172e-5. Normalized algebraic residuals were below 8.4e-17. Voltage/field
observed orders were approximately two; normalized analytic truncation-residual
orders were 1.80 and 1.91. Forty-three tests include constant/reversed bias,
log-grid nodal limits, nesting, invalid inputs and deliberate perturbations.
This validates the independent diagnostic operator only; it does not resolve
SSD's cap25 depletion failure or establish AK02 CCE/dead-layer thickness.

The existing remage handoff now optionally selects Livermore/Penelope/Option4 and
records the selected constructor in immutable prepared metadata. The original
M2a default Livermore macro was independently checked unchanged. No geometry,
original model, carrier-physics input, dependency lock or solver default was changed.

The final EM comparison executed eight fixed-seed cases, 5000 primary photons each
(40000 total), using bare AK02 and the same synthetic side-on geometry. It is not
the owner's lid-mounted source, full isotope decay, or detector efficiency.

| Mono energy (keV) | Livermore | Penelope | Option4 | Livermore independent-seed control |
|---|---:|---:|---:|---:|
| 59.5 | 0.9816 | 0.9838 | 0.9850 | 0.9878 |
| 662 | 0.0686 | 0.0722 | 0.0678 | 0.0748 |

Entries are full deposited-energy containment fractions per all primaries, with
1e-6 keV numerical energy tolerance, not broadened measured photopeak areas.
Raw energy ledgers, source origin/direction/time, actual constructor banners,
effective cuts, zero-event census and Geant4 data-package versions passed checks.
Actual settings were fluorescence/Auger on, PIXE off, deexcitation ignoring cuts;
package EMLOW was 8.6.1. No electronic/Fano/CCE smearing was applied. Spectral bins
have Wilson intervals, including nonzero upper limits for empty bins.

The four cross-constructor containment difference intervals included zero, but
this is not equivalence. At 59.5 keV, the same-Livermore control differed by
+0.0062, with unadjusted Newcombe95 interval [0.0013834, 0.0111136]. This was not
hidden or rerun with new seeds. A transparently post-hoc family of all six
contrasts gave Fisher p=0.0142607 and Holm-adjusted p=0.0855639 for that control;
no family member crossed 0.05 after Holm adjustment. These exploratory results
do not rank physical accuracy or rule out smaller EM effects. All eight event
energy arrays remained byte-identical after validation/reporting-only fixes.

Review closure: the two reused independent Astra High read-only sessions asked
and answered questions about spectral identifiability, statistical controls and
model activation, then audited code and cross-read the other findings. They accepted
diagnostic-only publication after explicit zero-bias field units, structured atomic
flags, sparse-bin intervals and exploratory multiplicity handling were checked.
Runtime tests were supervisor-run, not human certification or agent-run simulations.
All 43 analytic, 23 handoff, 5 EM, 88 existing-runner and 40 replay checks passed.
The final analytic/source hashes match, and protected model/lock/production-solver
files are unchanged. The handoff change only exposes optional radiation constructors.

Evidence is consolidated under .local/m2b3/electrostatics, em, reviews, checks and
validation.json. The final eight raw transport runs and per-event/spectrum tables
are retained; superseded identical numerical runs were removed after preserving
reports and byte-equality evidence. Earlier milestone data and original baselines
remain untouched. No measured spectrum was fabricated, digitized or ingested here.

Next: apply independent analytic/residual checks to SSD's own simple benchmark
before revisiting local Li-region refinement; separately verify a synthetic planar
finite-conductivity weighting limit. A production-cut sensitivity control at 59.5
keV is useful later, but is not needed to close this diagnostic comparison. Real
spectrum ingestion requires identifying saved files and their calibration/background
metadata; missing pulse records do not block mathematical verification. No current
result authorizes physical Li CCE, dead-layer thickness or as-built efficiency.

M2b3 publication verified: implementation cb333c8 pushed to main; all18 website/model checks passed. The unchanged website snapshot d2d6fbe17da0168cf49b512e3519e8efebd18eb7db6e85bbdac8dce353660e10 again matched78 live files. Release marker: v0.7.0-analytic-em-checks. New source and spectrum-only/physics documentation are public; raw40k-case data and review logs remain local. All current specialist/compute workers finished. This is not an enabled or proven unattended-runtime continuation.

## M2b4 prospective plan — 2026-09-26

Resumed interactively after client-history loss; clean local/origin main 4a35190 verified. No active project computation/review worker or prior owner/lock was present. Acquired one supervisor-owned lock; schedules remain unchanged. First improve all16 two-contact geometry thumbnails/detail images: orange-red contact1, cyan-blue contact2, translucent bulk and exact ID/name/bias legends, preserving original meshes and all field/signal results; GeGI remains unchanged. Separately apply independent analytic/residual checks to SSD's own synthetic source-free annulus, using explicit grids and unchanged production code. Read-only HPGe and numerical/render specialist sessions will exchange questions and cross-review tested evidence. Finite-conductivity weighting and minimal readout prototypes remain subsequent bounded tasks; no fit to measured spectra or fabricated waveforms.

M2b4 planning exchange: both specialists agreed on5.1/34.9mm electrical faces of the unchanged SSD example, explicit17/33/65 annular grids, actual native vector-field checks and separate boundary stencils. Reference-FV residuals are diagnostics unless native coefficient equivalence is established. Before numerical execution, finest voltage/midpoint/interior-field gates are1e-3, refinement ratios0.4, contact1e-10V, constant-bias1e-9V/1e-6V/m; strict bounded iteration gates are frozen in source. Supervisor added active CPU-project/manifest provenance guards before running. The67 new lightweight tests passed.

M2b4 initial actual-SSD harness failed before solving: the explicit zero-width phi axis had been constructed as periodic/open, producing zero angular volume and NaN diagnostic charge densities. Source inspection of SSD.get_φ_SSDInterval/get_extended_ticks shows collapsed phi must use reflecting/closed ends. Corrected this harness API usage to match the shipped configuration, retaining initial failure/source evidence; no package or detector change and no gate relaxation.

M2b4 visual review of all16 first renders found the expanded seven-line title intruded on tall detector images, and enclosing electrodes dimmed back-facing point contacts. Kept exact geometry/cameras but reduced the image header to four ID/name/bias lines (explanations remain in HTML), set bulk/contact1/contact2 opacity to0.15/0.95/0.35, and rerendered before any native application. No mesh enlargement or physical layer thickness was introduced.

## M2b4 verified locally — direct SSD check and two-contact views

The actual pinned SSD 0.11.8 source-free coaxial example was solved on explicit
17/33/65-node annular grids in Float64 on CPU, with the original finite contact
bands and electrical faces at 5.1/34.9 mm. Zero/equal/reversed/common-offset
bias controls also passed. The 80 new lightweight tests and 43 existing reference
tests passed. No production solver, model YAML or locked environment was changed.

Finest-grid voltage error/span was 9.5647e-6, independent midpoint-field error
8.0232e-5, and actual SSD interior radial-field relative error 1.6017e-4 (0.0160%).
Refinement ratios were about 0.25. **Contact-interface errors remain 1.61% and
1.11%**; these are not hidden by the interior result. Independent reconstruction
from the unchanged numerical potential agreed with native radial fields within
2.274e-13 V/m. Reference-FV residual sign is explicitly minus-Laplacian, and
native/FV coefficient equivalence remains unproved. This is synthetic validation,
not a resolution of the production AK02 depletion/Li CCE convergence gate.

All 16 two-contact geometry illustrations now use contact 1 orange-red (opacity
0.95), contact 2 cyan-blue (0.35), and translucent grey-blue bulk (0.15). Exact
contact IDs/names/signed voltages remain in a four-line image header and adjacent
HTML key. Full-size image links clarify tiny physical contacts at 270px thumbnail
width. Colors do not imply doping type or Li-layer thickness. GeGI is unchanged.
The original 78 K annotations remain those of the saved results, not new 77 K
calculations. Native edits were confined to 32 geometry PNG/PVSM files; all other
inventoried native files retained size/time metadata, and selected model/mesh
hashes were checked before and after application. No field/signal cache rerun.

Publication maintenance now has 27 passing contact tests and 18 passing site
checks. Covered cases include deterministic restyling, stale inputs, safe full
palette upgrades, explicit upgrade authorization, same-style restage/reapply,
and caught-failure rollback with an existing ledger. New stage schema 3 records
renderer/exporter/test and previous-ledger hashes; original PNG/PVSM backups and
apply receipts are retained locally. A host crash still needs manual recovery.
The final schema-3 rerender was byte-identical to all 16 reviewed images/states
and was successfully reapplied using the maintained workflow.

Two independent specialist sessions (HPGe/electronics: Astra High; numerical/
rendering: Astra XHigh) exchanged planning questions and reviewed each other's
findings, then reviewed implementation and actual supervisor-run evidence.
Two bounded Astra High coding sessions owned non-overlapping files. Reviews
identified and resolved the residual-sign wording, missing reconstruction
comparison, title overlap and palette-upgrade workflow; they are not human
certification. No resets, paid API switch or scheduling changes were made.

Local browser checks passed at desktop 1440px and mobile 390px: 17 homepage
cards, both AK02/SAP22 contact labels and full-size links, no missing images,
no horizontal overflow in the checked pages and no JavaScript exceptions.
Repeated site build was unchanged: 21 HTML pages, 1702 local links, build ID
cfecdea41177e23d54d3ffd467ba2276fcb72b29b77749be08bd1887a5756c4a.

Next scientific gate: a separate synthetic planar two-layer finite-conductivity
weighting-response benchmark with explicit dielectric/conducting limits, not an
inferred AK02 conductivity. Minimal preamp/shaper/ADC prototypes follow as an
independent gate. No measured-waveform fit is possible from spectra alone.

Final independent numerical/render review closed the palette migration blocker after inspecting current code, matching tool hashes, the successful same-style all16 application receipt, and 27-test evidence. HPGe cross-review closed the residual-sign and numerical-field reconstruction findings. Neither review claims live deployment or production-physics validation.

M2b4 publication verified: implementation commit `5f0d4ea` was pushed to main;
GitHub Pages run `36241549728` completed successfully. The exact live manifest
matches build `cfecdea41177e23d54d3ffd467ba2276fcb72b29b77749be08bd1887a5756c4a`.
The standard 78 live-file checks passed, and all 16 changed geometry PNGs were
separately fetched and matched to staged SHA-256 hashes. A live 390px browser
check loaded AK02 with both exact contact labels, the full-size link, no missing
images and no horizontal overflow. Release marker: `v0.8.0-contact-ssd-checks`.
Superseded un-applied previews and redundant numerical profiles were cleaned;
original grey-geometry backups, final results, failed-harness diagnostics and
review/test receipts are retained together under `.local/m2b4/`. The isolated
test browser/server were closed. No task schedule was enabled or modified.

M3a reviewers exchanged answers and fixed the contract before runtime: impulseCSA/shaper reference error <=1e-9 ofpeak+1e-12V; chargebalance <=1e-12*sum(abs(dQ))+1e-27C; fixed-input electronics1/2/4ns and10/20us tail comparisons <0.25ADC LSB; quantization error <=0.5LSB relative to analog-calibrated energy. Use negativeCSA thenfixedsignshaper, synthetic gain20, Cf0.6pF,50usfeedback,.5usRCpole and500keV-equivalent independent injection. Retain joint driftflags, clipping/threshold statuses and null invalidErec. Numeric timegrid is notwaveformADC.

M3a pre-run checks: eight readout suites passed with exact-source receipts, including impulse/rectangle/RK4, sign reversal, narrow-current display preservation, tail stability, quantization and malformed inputs. The pipeline fixture suite passed29 tests withone Windows symlink-creation test skipped (reparse rejection separately tested). Review caught and corrected flag schema/counting, absent completion status, calibration identity and readout provenance/ADC checks before detector execution. No physical model or original lockfile changed.

## M3a verified workflow and traceable example — 2026-09-26

The optimized flow-first plan has been executed. One driver ran prepared bare
geometry, remage transport, checked event extraction, SSD replay, synthetic CSA,
matched-pole-zero analog shaping and peak ADC for100 AK02 plus100 SAP22 primaries.
The original models/locks/production solver were unchanged. Source was662keV
monoenergetic side-on photons, seed260926, explicit77K and canonical+500/+700V.
This is not a full isotope source, surveyed cryostat or calibrated detector response.

| Model | Primaries | Zero deposit | Readout accepted | Below threshold | Charge-flagged union |
|---|---:|---:|---:|---:|---:|
| AK02 |100|46|52|48|54|
| SAP22 |100|45|55|45|0|

All IDs0–99 per model and every deposition row remain traceable. AK02 has54
stopped-without-contact cases; one also has a step-limit endpoint, so the union
is54, not55. Its two nonzero below-threshold events41/78 remain visible with
null Erec. All52 accepted AK02 readouts retain charge flags; readout acceptance
does not establish completed or validated collection. No event was renormalized
to deposited truth or removed to improve the apparent spectrum.

Synthetic electronics uses Cf0.6pF,50us feedback/matchedPZ,0.5us RC pole and gain20.
An independent500keV-equivalent injection with SSD's recorded2.95eV pair energy
sets the common slope0.000490013623859V/keV. The14-bit0..10V peak ADC uses floor
codes and bin-center energy reconstruction. Half an LSB is0.622790keV; maximum
accepted ADC-versus-analog energy errors were0.610648/0.601932keV. These are
quantization checks, not experimental resolution or Edep agreement. No added
noise/Fano/pileup or event-specific gain was used. Negative cumulative Q is an
explicit conservative unsupported-waveform restriction, not physical trapping.

Eight readout suites passed, including independent impulse/rectangle/RK4 limits,
causal delays, signed reversal, narrow-current display support, tail extension,
ADC boundaries and invalid-input checks. Final receipts contain exact code/config
and environment hashes. The pipeline suite passed29 tests; one Windows test
requiring symlink-creation permission was skipped, while the reparse guard passed.
The existing88 runner,36 replay,27 contact and18 site checks also passed.

All200 completed signals were then checked at1/4ns electronics grids and a
2ns doubled tail, retaining the original calibration slope. All600 comparisons
passed the predeclared0.25LSB peak gate. Maximum differences were0.00044512LSB
(half step),0.00762065LSB(double step), and0(double tail); no ADC code changed.
This verifies fixed-input electronics sampling/window stability, not SSD drift
step convergence or recovery of charge after a stopped trajectory.

A source-only checkout from candidate3a51b4d independently reran all200 primaries
without the original field caches, website or private supervisor state. Both
models reproduced truth-event structures, charge CSV bytes, every readout event
and common calibration exactly. Runs took150.73s and164.87s on the same Windows
computer with existing installed package caches; no second-machine, fresh-depot
or other-OS claim is made.

The self-contained event explorer embeds all200 records and their metadata, with
separate charge/current/preamp/shaped plots, deposition r-z projection, exact
peak/code/Erec, and all-primary Edep versus accepted-only Erec histograms. The
initial nonzero-deposit selection and zero/highest-deposition navigation are
explicit; they do not filter the census. Current segments use original-bin
boundaries, and the short charge window is visible beside the longer electronics
tail. A prominent warning states that52of52 accepted AK02 readouts retain flags.

The final HTML was tested directly via file:// with network disabled: zero HTTP
requests or JavaScript exceptions, both100-ID selectors, zero events, flagged
below-threshold41/78 events, highest-deposition navigation and390px mobile layout.
The example is separate from the original17-model numerical gallery; its images,
model downloads and GeGI content remain unchanged. Website export imports only
a completed hash-verified bundle; it performs no new physics computation.

Both independent Astra High specialist sessions exchanged goal/plan questions,
reviewed implementation and actual artifacts, then cross-read the other findings.
Their closed findings include schema/flag counting, common calibration identity,
provenance/ADC checks, narrow-current display and artifact-specific sampling.
These are AI reviews plus supervisor-run tests, not human certification or
experimental validation. No reset use, paid API switch or schedule changes occurred.

Remaining work stays split: maintain reproducible configurable examples and
presentation on the delivery lane; pursue Li/finite-conductivity convergence,
source/cryostat metrology and calibrated spectrum comparison on the accuracy lane.
No successful engineering run authorizes physical CCE, measured energy resolution
or an as-built efficiency claim.

M3a publication verified: implementation `b297ffc` was pushed to main and GitHub
Pages run `36245299651` succeeded. Exact site build
`7d0662f1c8a392362b8a2357db34e6be95a891eb13f360ed379d9bb0ac3d826f`
passed79 live-file checks; the new pipeline HTML and data JSON were also fetched
separately and matched their local SHA-256 values. The live390px page loaded
both models, all100 selectable IDs per model, the first nonzero example and the
prominent accepted-with-flags warning without errors or horizontal overflow.
Release marker: `v0.9.0-pipeline-demo`.

Large generated example bundles are excluded from textual Git diffs; reviewable
sources remain the small renderer template, orchestration/readout code, tests and
manifest hashes. No result bytes were changed by that Git presentation setting.
Verified duplicate clean-run data and superseded viewer copies were removed,
retaining the source archive, clean-run manifest/comparison, original complete
example, final showcase, sampling report and review/test receipts. The copied
Pixi environment symlink was unlinked before cleanup; shared installed package
caches and the original transport environment were not removed.

## M3b plan — configurable examples and lightweight execution

Continue the flow-first roadmap: make run counts/standard monoenergetic scenarios explicit without editing frozen detector or electronics settings; provide a low-load single-thread option, keep model runs serial, and make the offline example losslessly smaller. Initial host observation: CPU36%,4.66GiB available of15.31GiB; terminal setup278ms, no orphan project computations. This does not establish sustained slowdown. Do not close user apps, reset usage, alter systemwide policies or install software. Cap new runs and use compact progress rather than full signal/log output. Compare complete event/charge/readout records, not only plots, before publishing. Accuracy gates remain unchanged.

M3b prospective gates: full effective readout config may differ from the frozen baseline only in primary census, even after an attacker/test recomputes all hashes; presets retain explicit override intent and reject invalid bounds before work; all stages/models remain serial with child-only resource limits. Compact public JSON must preserve types, signed zero and binary64 values, all event/flag/deposit records and HTML safety, and be under45% of previous pretty payload on the real sample. Closed detail panels should avoid serializing large event/provenance records until opened. Reproduce the default200-event result against M3a, exercise small59.5keV/1-thread cases and check offline/mobile behavior. Timing comparisons are sampled observations, not guaranteed speedups.

Reviewer preflight question resolved: no downstream upper energy bound existed. Added a10,000keV cap to this bounded example (positive finite energies only); this is a resource/workload limit, not a claimed physics-validity range. The59.5/662keV defaults and all canonical numerical inputs remain unchanged.

Independent review found a standalone public consistency gap: an intentionally resealed bundle could contradict its own thread/config declarations even though source-run export was strict. Added a public settings/config/recorded-command cross-check and rehashed-metadata rejection tests. This changes only public validation, not execution or scientific calculations; archived candidate runs remain untouched. The final default sample will be regenerated against the finalized source.

## M3b verified — standard scenarios and lighter examples

The existing driver now offers quick (10 photons/model at 662 keV), gamma-662
(default 100 at 662 keV) and gamma-59 (100 at 59.5 keV). Explicit overrides allow
1..500 events, positive finite energy up to 10,000 keV, a seed, one or both
reviewed models, and 1..4 Julia threads (default 2). These are monoenergetic
engineering scenarios, not full isotope sources or a certified accuracy range.

A single generated readout-config.json is shared by both detectors. Its only
permitted change from the frozen baseline is expected_primary_count; unchanged
feedback, shaping, gain, threshold, ADC and calibration settings are independently
checked even when test mutations recompute every hash. Preset intent and actual
overrides are recorded. Run/showcase schemas are now 2; historical schema-1
artifacts remain preserved and are not silently rewritten by the new driver.

Models/stages run serially. Julia thread limits and BLAS/OMP child-environment
settings do not modify global settings or terminate user applications. Initial
host observations were 36% CPU and 4.66 GiB available memory of 15.31 GiB; one
in-run sample had 45% CPU and 1.16 GiB available, so no overlapping numerical jobs
or test browsers were used. A 278 ms terminal startup measurement is not evidence
of a sustained PowerShell slowdown. No registry/power-plan/WSL global changes,
software installs, reset usage, paid API changes or schedule changes occurred.

The final default run from source 340cb0e processed 200 events in 146.84 s.
Both detectors' complete truth-event structures, charge CSV bytes, readout-event
records and pulser calibrations exactly matched the v0.9 baseline. Original
models, production transport/drift/readout code and environment locks were unchanged.

Candidate source 9bf3000 was also run in a source-only checkout: quick processed
10 events per detector with one Julia thread, preserving all 20 records and the
same numerical pulser coefficients. Its 146.28 s duration is close to the default
because environment startup and field solving dominate; quick is smaller, not a
claim of tenfold speed. The same-machine installed package caches were reused;
no private field cache or other-machine/OS reproducibility is claimed.

The gamma-59 preset with explicit 20 events, AK02 only and one thread completed
in 74.20 s: one zero deposit, 13 readout-accepted, seven rejected and 19 charge-
flagged events. Accepted and flagged populations overlap. The calibration
coefficients remained unchanged. These candidate runs retain their original
9bf3000 provenance; the later public-consistency-only patch does not retroactively
change their producer identity. The final default was rerun after that patch.

The existing independent readout-sampling verifier now recognizes a validated
schema-2 census-only configuration as well as the old schema-1 default. Its
numeric equations were not changed. Twelve configuration tests passed, including
rehashed gain rejection. All 60 fixed-input sampling/window comparisons on the
20-event gamma-59 artifact passed; maximum peak change was 0.00030264 ADC LSB.
This checks electronics discretization, not low-energy detector or Li accuracy.

The expanded pipeline suite passed 45 of 46 tests, with one Windows symlink-
creation test skipped; the reparse-point guard passed separately. Two independent
Astra High reviewers checked configuration/calibration, data identity and public
consistency. Their exchange identified a standalone public metadata gap, fixed
by cross-checking settings, frozen configuration and recorded thread commands.
Current public bundles pass deliberately resealed inconsistent-metadata tests.

Public JSON is now 9,766,838 bytes instead of 24,894,288; standalone HTML is
9,796,506 instead of 24,923,133 bytes (approximately 61% smaller). Compact
serialization preserves every numeric value, type, signed zero, event, deposit,
trace and flag; there was no precision reduction or event filtering. The default
still contains all 200 events, with the same accepted-with-charge-flags warnings.

Heavy event/provenance text is generated only while its panel is open. Offline
browser tests confirmed opening current data, refreshing after event/model
changes, clearing closed panels, and eight mobile event-selection cases without
horizontal overflow. With networking disabled, zero HTTP requests and zero
JavaScript exceptions were observed. Single comparable headless-browser samples
showed DOM ready at 286.9 -> 128.8 ms, ten event changes at 25.6 -> 21.9 ms, and
reported JS heap at 35.1 -> 19.3 MB. These are local observations, not guaranteed
speedups or internet load-time measurements. Closed event-detail text decreased
from 91,901 characters to zero until requested.

Remaining priorities: preserve this runnable delivery path while returning to
bounded AK02 endpoint/depth and finite-conductivity accuracy diagnostics. Do not
remove incomplete-collection flags to improve a plot. True detector efficiency,
Li CCE and hardware response remain unvalidated. Raw data, prior releases and
review evidence remain distinct from the compact public distribution.

M3b publication verified: implementation `616478d` was pushed to main and GitHub
Pages run `36249402601` completed successfully. Build
`4a8c88d5ea48ef9e4ac5cc2c5a9d6a0ac32e62eb2fc5a25c04ff073afe804355`
passed 79 exact live-file checks; both compact example files were separately
fetched and matched to their local hashes and byte counts. The first check while
Pages was deploying correctly rejected the old manifest; success was recorded
only after the new deployment completed. The publisher also passed all 18 site,
27 contact and 46 pipeline tests (one platform-specific skip as noted above).
Release marker: `v0.10.0-scenarios-compact`.

All owned numerical/reviewer tasks finished. The independent quick raw run was
retained under `.local/m3b/quick`; its duplicate source tree was removed only after
unlinking the copied Pixi environment symlink. Shared installed environments were
not deleted. Superseded viewer copies were removed after semantic event comparisons;
raw historical runs, final results, source archive and evidence remain organized.
No user application was closed, no global optimization setting was changed, and
no recurring task was enabled. Further work should focus on bounded AK02 endpoint/
Li-region accuracy diagnostics without disrupting the now-runnable example path.
