# End-to-end germanium detector simulation

**[Open the detector results website](https://kunming-cn.github.io/END2END_Ge_Simulation/)** · [GeGI strip explorer](https://kunming-cn.github.io/END2END_Ge_Simulation/detectors/GeGI_3D/strip_explorer.html) · [Development progress](PROGRESS.md)

## Current release

A static library of 17 detector models: geometry/field views, drift movies, pulse comparisons, and signal tables. GeGI includes 20 selectable events, 34 signed channels, and a separate supplementary notebook study. Read the [website guide](https://kunming-cn.github.io/END2END_Ge_Simulation/guide.html) before interpreting the results.

These are precomputed SSD results, **not an online solver or a standalone calculation package**. Movies are pre-rendered 3D views; full scene rotation still requires the original desktop ParaView workspace. Synthetic deposits are not a Geant4 source simulation or a Compton reconstruction.

To browse a downloaded repository, open `docs/index.html`. No Julia, ParaView, Node.js, or Python installation is needed for viewing. The development computer's full local entry remains `Additional_Simulations/Visualization_3D/Open_Library.cmd`.

## One project root

| Path | Purpose | In this repository? |
|---|---|---|
| `Additional_Simulations/` | Existing models, calculation code, original numerical data and full desktop library | Not yet; portability is M1 |
| `2D_GeGI detector Simulation/` | Earlier GeGI study and source reference material | No |
| `docs/` | Generated, validated public website | Yes |
| `tools/` | Export, publication checks, tests and maintenance utilities | Yes |
| `.local/` | Ignored migration backup and bounded test/build scratch space | No |
| `PROGRESS.md`, `AGENTS.md` | Milestones, evidence, and development rules | Yes |

Only `docs/` is served by GitHub Pages. Raw caches, native scenes, manuals, photographs, slides, and private machine paths are excluded. The source calculation folders are deliberately preserved rather than reorganized during the publication milestone.

## Updating results on the development computer

Change the scientific source or its presentation generator, then test it and update `PROGRESS.md`. Do not edit generated files in `docs/` by hand. Double-click `Publish.cmd` to rebuild, validate, commit the approved publication files and push to `main`; GitHub Pages publishes `main:/docs`. No force-push is used.

The exporter first builds in `.local/site-build`, checks links, privacy, file sizes and SHA-256 inventory, then replaces `docs/`. Unchanged snapshots are not rewritten. A failed validation leaves the previous published folder intact. Generated staging/previous folders are cleaned; Windows read-only attributes are handled only within those generated folders. ACLs are not changed.

A failed network push leaves the local commit available for retry. Do not force-push to solve conflicts. The helper's basic reachability check is not an exact-version check: run the independent verification below after deployment.

## Checks that work from a clean repository clone

Python 3.10+ and its standard library are sufficient for these checks. No simulation data outside the repository is needed:

```sh
python tools/test_site.py
python tools/check_site.py
python tools/check_site.py --url https://kunming-cn.github.io/END2END_Ge_Simulation/
```

The live check compares the exact snapshot manifest, every HTML page, and representative image, video and data files. A not-yet-deployed version fails rather than being reported as current. The manifest contains per-file hashes and a deterministic build ID; Git is configured to preserve the exact website bytes across operating systems.

Building new exports is different: `tools/build_site.py` requires the original local results and GeGI source notebook. The publication helper currently uses the installed Git, GitHub CLI, Node.js and ParaView Python on the development computer; `SITE_PYTHON` overrides its Python executable. Portable calculation/build setup is explicitly the next milestone, not a feature of this snapshot.

## Maintenance boundaries

`tools/site_guide.html` is the editable web-guide template. The existing library generators remain the authority for galleries and scientific displays. `tools/check_site.py` and `tools/test_site.py` guard the public deliverable. `tools/migrate_paths.py`, `tools/smoke_scene.py` and `tools/smoke_test.jl` serve the original workspace and are not standalone simulation entry points.

For subsequent substantial development, use one focused branch, record the purpose and tests, then review before merging to `main`. Keep model changes separate from presentation changes. Never silently alter original model parameters or discard incomplete-collection events. The staged development plan and Astra/High preference are in `PROGRESS.md` and `AGENTS.md`.
