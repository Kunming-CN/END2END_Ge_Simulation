# Project working rules

Work only in this project unless a recorded input dependency needs a read-only check.

1. Read README.md and PROGRESS.md first. Complete one milestone-sized task at a time.
2. Keep one project root. Use tools/ for reusable tooling, docs/ for public results, and .local/ for disposable local evidence/backups. Do not scatter copies, timestamped reports or extra environments.
3. Preserve existing numerical data and model hashes. Never silently change bias, impurity, geometry, carrier physics, missing-charge labels or event selection to make a test pass.
4. The public repository initially contains the exported website and maintenance tools only. The full raw computation workspace is deliberately ignored. Add new calculation source deliberately during M1, not with a wholesale force-add.
   Intentional M1a addition: `models/` contains exact versioned SSD model snapshots and inspected relative includes. Preserve original YAML bytes and pinned hashes; keep provenance portable and reference/candidate limitations intact. Original model/cache folders remain ignored.
5. Never publish credentials, private paths, raw field caches, manuals, photographs or slides without a specific reason and review. Do not change permissions or enable a public service unrelated to this project.
6. Geant4/remage provides radiation deposits, positions, creation times and identities. SSD provides semiconductor drift and electrode signals. Readout is a separate stage. A deposition time is not a drift time.
7. Keep all relevant deposits of one event grouped. Keep truth Edep separate from readout-derived Erec. Do not set the energy gain separately for each event.
8. Reuse existing SSD, ParaView and remage functionality. Do not introduce a second frontend framework, Docker, a VM or another solver solely to publish static results.
9. Record exact software versions and random seeds. Distinguish smoke tests, numerical convergence, and agreement with experiment.
10. Before committing: rebuild/validate the relevant outputs, inspect the diff, update PROGRESS.md, and commit a meaningful milestone. Push without force; stop for conflicts.

## Existing tools

- `tools/build_site.py`: deterministic export of the locally generated library into docs/.
- `tools/export_models.py`: explicit `--import` of recorded originals; portable `--validate` of versioned snapshots. Site model downloads use `models/` only. Unexpected managed edits must fail, never be overwritten.
- `tools/smoke_test.jl`: bounded AK01 event replay in the existing Julia environment.
- `tools/smoke_scene.py`: existing AK01/GeGI native-state reload and render.
- `tools/migrate_paths.py`: explicit old-root replacement with an originals ZIP; do not rerun blindly.
- `Publish.cmd`: approved publication workflow. Browser authorization may require the owner.

Do not claim that Work/Codex has been started merely because these instructions exist. The execution environment and actual working directory must be verified in that session.

## Work/Codex model preference

The maintainer requested Astra with High reasoning for this project's Work/Codex tasks (2026-09-25).
- Use model `gpt-6-astra` with `model_reasoning_effort = "high"`.
- The development computer's user config already has both values; do not replace the entire config or change unrelated settings.
- When launching Codex programmatically, explicitly select the same model and reasoning level so another profile or task preset cannot silently change them.
- If using Plan mode, set its supported `plan_mode_reasoning_effort` override to `high` for that run as well.
- For Work/Codex graphical sessions, verify Astra and High in the session's model control; a project instruction alone is not a model-setting mechanism.
- Astra High remains default. The maintainer permits supported XHigh or stronger reasoning for difficult bounded reviews; specify and record effective settings. Do not enable separately billed API usage or Fast mode without approval. Never trigger, confirm or consume any banked reset/reset credit; only the owner may do that.
- Confirm the effective model, reasoning level and project directory when starting a development task. Configuration verification is not a claim that a task has been launched.

## Publication validation

Run tools/test_site.py and tools/check_site.py before publishing. Build only through tools/build_site.py; never hand-edit docs/. Verify the live build with tools/check_site.py --url after deployment, rather than relying on the publisher's basic reachability message. Keep the public manifest and exact-byte Git attributes intact. The original numerical workspace remains out of scope for a publication-only edit.

## Portable CPU example

M1a includes only the reviewed simulation/Project.toml, Manifest.toml, run.jl and README.md. Keep this environment separate from the preserved full campaign. Run --check-models and the bounded cache-free example before changing the lockfile or runner; log any differences. Generated files belong under .local/, not models/, simulation/ or docs/. The canonical model snapshots are deliberately frozen by reviewed hashes; do not silently mutate them.

## M1b compute and transport boundaries

Use the shared simulation/run.jl for both CPU and optional CUDA. CPU remains installable without CUDA. Never silently fall back from a requested GPU or force partial charge to unity. Report potential-solve and end-to-end times separately; warm-up is not production timing. Before upgrades run parser/model tests, CPU regression and the explicit parity benchmark. Do not loosen comparison gates to force a pass.

transport/ keeps the Pixi manifest/lock and toy installation checks; large environments belong to Pixi’s detached Linux cache. Preserve cryostat-source.json provenance and locally cached upstream bytes. No LBNL geometry or drift/recombination validation may be inferred from the toy Ge-box smoke test. Keep coupling pending until geometry/units/event mapping are independently checked.

## M2 scope and independent review

AK02 (Anupama ICPC2) is the Li-contact primary case; SAP22 is a non-Li cross-check, not a matched-geometry experimental control. Defer new GeGI work. Preserve original 78 K / +500 V and +700 V snapshots; first reproduce them, with any nominal 77 K override explicit and consistently recorded. No invented experimental holder/source positions or uncalibrated lifetime claims.
Read-only research elsewhere under My Drive is authorized; never edit unrelated files. Keep raw transport energy separate from charge response; no double Li loss. Preserve event IDs, deposition times, transforms, zero-deposit primaries and incomplete-collection flags.
After bounded implementation/testing, use two separate read-only review sessions: (1) HPGe and electronics, (2) particle transport and event integrity. Give both the same tested diff/evidence, then exchange findings for cross-review. Summarize confirmed issues and resolutions in PROGRESS.md. These are AI reviewers, not human certification. Never claim independent agents ran unless launched.

## Successive authorized rounds

The owner requested successive bounded rounds without per-round approval (2026-09-26).
A scheduled continuation checks this project hourly. Before an automated round, inspect
`.local/autonomy/state.json`, its lock directory, the Git worktree and actual
project worker processes. Never run two supervisors/rounds concurrently. Only an
explicit ready state with no prior active supervisor/workers/lock permits a new
round; acquire the lock before writes. Stale or conflicting state requires
inspection, not blind lock deletion. On completion, record tested outcomes and
next bounded work, synchronize Git, release the owned lock and leave ready.
Unknown experimental dimensions block claims that require them, not unrelated
mathematical verification. Notify the owner only for substantive progress or an
issue genuinely requiring their intervention. Usage limits never authorize resets.

The scheduling state/lock governs the owner's automated continuation only. A clean
student clone does not need this private state to run documented CLI examples or
make manual contributions; normal source/test/review rules still apply.
