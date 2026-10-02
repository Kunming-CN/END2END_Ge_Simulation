# Maintaining the project

The website and the local workflow have different jobs. The public site is a
saved-results browser; `Run.cmd` is the supported local calculation entry.
The beginner instructions have one authority: `tools/site_guide.html`, published
as `guide.html`. Keep README short and link to that guide rather than adding
another complete installation recipe.

## Source ownership

| Area | Edit these sources |
|---|---|
| Home, hubs and navigation | `tools/site_restructure.py`, `site_previews.py` |
| Search descriptions, canonical landing URLs and sitemap | `tools/site_discovery.py`; generated only by `build_site.py` |
| Detector overview/gallery/technical levels | `tools/site_detector_pages.py` |
| Geometry export and validation | `tools/export_ssd_geometry.py`, `geometry_catalog.py`, `ssd_geometry_publication.py` |
| Browser geometry controls | `tools/ssd_geometry_viewer.html` |
| Saved energy-spectrum views | `tools/spectrum_display.py`, `spectrum_plot.py`, `spectrum_controls.js`; see [display semantics](SPECTRUM_DISPLAY.md) |
| Current reciprocal Geant4 readers | `tools/viewer_navigation.py`, `viewer_navigation.js`, `viewer_overlay_selection.js`; see [reader ownership](VIEWER_NAVIGATION.md). Original signed viewers remain frozen. |
| Windows setup/run guide | `tools/site_guide.html` |
| Contributions, software citation and rights scope | Root `CONTRIBUTING.md`, `CITATION.cff`, `THIRD_PARTY_NOTICES.md`; `.github/PULL_REQUEST_TEMPLATE.md` |
| Loopback bounded-native control | `Control.cmd`, `tools/local_ui.ps1`, `local_ui.py`, `local_ui_jobs.py`, `local_ui.html`, `local_ui.js`; same native backend, no public execution service |
| Scenario eligibility labels | `scenarios/detector-capabilities.json`; backend restrictions remain independently enforced |
| Cryostat source-input inventory | `transport/cryostat-input-ledger.json`, `tools/check_cryostat_inputs.py`, `test_cryostat_inputs.py`; see [input verification contract](CRYOSTAT_INPUTS.md). Curated metadata and opt-in original-byte checks only; no new adapter or native/experimental acceptance. |
| Bounded monolithic native audit | `tools/native_cryostat_audit/`, `cryostat_native_audit.py`, `test_cryostat_native_audit.py`; see [native audit contract](NATIVE_CRYOSTAT_AUDIT.md). Independent structure/source-position diagnostics, no particle transport or adapter promotion. |
| Opt-in source-instance geometry preparation | `transport/scenario_prepare.py`, `scenarios/assets/`, `scenarios/m11a-*.json`, `transport/Prepare.cmd`, `prepare.sh`; see [preparation contract](SCENARIO_PREPARATION.md). This entry prepares geometry and macros only. |
| Finite synthetic gamma transport and raw event stream | `transport/scenario_transport.py`, `test_scenario_transport.py`, `Gamma.cmd`, `gamma.sh`; see [transport contract](SCENARIO_TRANSPORT.md). Separate from the strict Cs137 reader and later charge/readout coupling. |
| Electronics settings and configuration preflight | `tools/electronics_settings.ps1`, `electronics_execution.ps1`, `scenario_cli.ps1`; see [ELECTRONICS_SETTINGS.md](ELECTRONICS_SETTINGS.md) |
| Source-aware bounded gamma charge/calibration/readout | `tools/gamma_native_example.py`, `simulation/gamma_native_example.jl`; see [gamma example contract](GAMMA_NATIVE_EXAMPLE.md). Uses completed gamma truth, existing fields and independently injected calibration. |
| Saved gamma public example | `tools/gamma_showcase.py`, `gamma_showcase.html`, `test_gamma_showcase.py`; explicit `build_site.py --gamma-showcase` copies a frozen completed bundle. No calculation or private inputs are published. |
| Saved-run validation and inspection | `tools/native_run_validation.ps1`, `inspect_native_run.ps1`; see [INSPECT_RUNS.md](INSPECT_RUNS.md) |
| Bounded NEW native-charge group commits | `tools/native_group_checkpoints.py`, `simulation/native_groups.jl`; see [charge-only scope](NATIVE_GROUP_CHECKPOINTS.md). Host acceptance is separate. |
| Local file/result index | `tools/build_local_dashboard.py`, `local_paths.py`, `open_workspace.ps1` |

Never hand-edit generated `docs/` files. Do not alter frozen model files,
scientific results, input identities or calibration to make a display test pass.
The content-addressed geometry assets preserve old published versions.

## Normal publication

From the project root, use `Publish.cmd`. For a source-only navigation update,
the underlying command is `python tools/build_site.py --restructure`: it starts
from the checked saved snapshot rather than rerunning simulations. New saved
geometry exports use the explicit `--ssd-geometry` publication mode.

Before publishing, run the applicable checks:

```powershell
python tools/test_all_detector_pages.py
python tools/test_site_restructure.py
python tools/test_site_hierarchy.py
python tools/test_spectrum_display.py
python tools/test_viewer_navigation.py
python tools/test_site.py
python tools/test_contacts.py
python tools/check_site.py
.\Run.cmd detectors
.\Run.cmd check
```

Use the installed project Python/ParaView Python as appropriate. Original-mesh
comparison additionally needs VTK and the owner's saved geometry; source-only
checks explicitly report that limitation rather than fabricating coverage.
After deployment, verify the actual website with `tools/check_site.py --url`
and the published site address; successful Git push alone is not deployment proof.

## Search discovery

The display name is **GeSignal — HPGe Radiation-to-Readout Simulation**. The
repository slug and Pages address remain `END2END_Ge_Simulation`. GitHub Topics:
`hpge`, `germanium-detector`, `geant4`, `detector-simulation`,
`radiation-detectors`, `nuclear-physics`, `particle-detector`,
`solid-state-detectors`, `ssd-jl`, `remage`.

Normal saved-only publication generates descriptions and self-canonical URLs
for maintained landing pages, plus
[sitemap.xml](https://kunming-cn.github.io/END2END_Ge_Simulation/sitemap.xml).
The map selects current entry pages; archived reports and hash-bound scientific
bundles stay byte-exact and remain reachable through their existing links.
No generated dates or search-ranking claims are added.

For Google Search Console, add a **URL-prefix** property with the exact
`https://kunming-cn.github.io/END2END_Ge_Simulation/` address. Use the owner's
Google account and an offered HTML-tag or HTML-file ownership method. Keep the
actual verification value in a maintained publication source, never hand-edit
`docs/`; retain it after verification. Then submit `sitemap.xml`, inspect the
homepage URL and request indexing. Record the actual result rather than treating
publication as submission. A project-subdirectory `robots.txt` cannot control
the host's crawling policy; this project does not manage the account-root site.
[Google's ownership instructions](https://support.google.com/webmasters/answer/9008080?hl=en)
and [crawl-request guidance](https://developers.google.com/search/docs/crawling-indexing/ask-google-to-recrawl)
explain verification and submission; a request does not guarantee indexing.

## Contributions and default-branch policy

External contributors use [fork, branch and PR](../CONTRIBUTING.md), with owner
review before merge; no collaborator permission is needed. Keep the small PR
template in `.github/`. [CITATION.cff](../CITATION.cff) identifies this software,
not ownership or experimental validation of its upstream tools and inputs.
[THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md) records the rights boundary.
The software license remains pending the owner's explicit choice; adopt a root
`LICENSE` and its exact publisher allowlist entry only after that choice.

The intended `main` protection requires one approving PR review, dismisses stale
approvals and requires resolved conversations. Force pushes and deletions are
disabled; no unknown CI check, CODEOWNERS requirement or new collaborator is added.
`enforce_admins` remains false: the owner's existing bounded, tested and reviewed
maintenance retains GitHub's default administrator exception. These flags are
not a claim that administrators cannot bypass them. Project policy still forbids
force-pushing or deleting `main`. Inspect actual GitHub settings before changing
this policy; settings are not installed merely by cloning the repository.
The private automation state and lock apply only to automated owner rounds;
a normal clone, CLI example or manual contribution needs neither.
[GitHub's branch-protection documentation](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches)
explains the administrator exception.

## Retention and changes

Use [LOCAL_WORKSPACE.md](LOCAL_WORKSPACE.md) and [DATA_RETENTION.md](DATA_RETENTION.md).
Keep original source workspaces, production archives, checkpoints, unique failures
and exact configurations at stable paths. Collapse historical evidence in the
index; do not move it merely to produce cleaner folder names. The local index
itself is regenerable. A same-disk copy is not an independent backup.

Make one scoped change, test it, inspect the diff, update `PROGRESS.md`, then
commit without force-pushing. Record known limitations instead of either hiding
them or turning unrelated physics research into a gate for interface improvements.
