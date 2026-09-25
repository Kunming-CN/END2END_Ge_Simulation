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
