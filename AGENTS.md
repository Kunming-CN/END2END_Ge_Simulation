# Project working rules

Work only in this project unless a recorded input dependency needs a read-only check.

1. Read README.md and PROGRESS.md first. Complete one milestone-sized task at a time.
2. Keep one project root. Use tools/ for reusable tooling, docs/ for public results, and .local/ for disposable local evidence/backups. Do not scatter copies, timestamped reports or extra environments.
3. Preserve existing numerical data and model hashes. Never silently change bias, impurity, geometry, carrier physics, missing-charge labels or event selection to make a test pass.
4. The public repository initially contains the exported website and maintenance tools only. The full raw computation workspace is deliberately ignored. Add new calculation source deliberately during M1, not with a wholesale force-add.
5. Never publish credentials, private paths, raw field caches, manuals, photographs or slides without a specific reason and review. Do not change permissions or enable a public service unrelated to this project.
6. Geant4/remage provides radiation deposits, positions, creation times and identities. SSD provides semiconductor drift and electrode signals. Readout is a separate stage. A deposition time is not a drift time.
7. Keep all relevant deposits of one event grouped. Keep truth Edep separate from readout-derived Erec. Do not set the energy gain separately for each event.
8. Reuse existing SSD, ParaView and remage functionality. Do not introduce a second frontend framework, Docker, a VM or another solver solely to publish static results.
9. Record exact software versions and random seeds. Distinguish smoke tests, numerical convergence, and agreement with experiment.
10. Before committing: rebuild/validate the relevant outputs, inspect the diff, update PROGRESS.md, and commit a meaningful milestone. Push without force; stop for conflicts.

## Existing tools

- `tools/build_site.py`: deterministic export of the locally generated library into docs/.
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
- Do not silently substitute another model or enable Extra High, Max, Ultra, Fast mode or separately billed API usage.
- Confirm the effective model, reasoning level and project directory when starting a development task. Configuration verification is not a claim that a task has been launched.

## Publication validation

Run tools/test_site.py and tools/check_site.py before publishing. Build only through tools/build_site.py; never hand-edit docs/. Verify the live build with tools/check_site.py --url after deployment, rather than relying on the publisher's basic reachability message. Keep the public manifest and exact-byte Git attributes intact. The original numerical workspace remains out of scope for a publication-only edit.
