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
| Detector overview/gallery/technical levels | `tools/site_detector_pages.py` |
| Geometry export and validation | `tools/export_ssd_geometry.py`, `geometry_catalog.py`, `ssd_geometry_publication.py` |
| Browser geometry controls | `tools/ssd_geometry_viewer.html` |
| Saved energy-spectrum views | `tools/spectrum_display.py`, `spectrum_plot.py`, `spectrum_controls.js`; see [display semantics](SPECTRUM_DISPLAY.md) |
| Windows setup/run guide | `tools/site_guide.html` |
| Scenario eligibility labels | `scenarios/detector-capabilities.json`; backend restrictions remain independently enforced |
| Saved-run validation and inspection | `tools/native_run_validation.ps1`, `inspect_native_run.ps1`; see [INSPECT_RUNS.md](INSPECT_RUNS.md) |
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

## Retention and changes

Use [LOCAL_WORKSPACE.md](LOCAL_WORKSPACE.md) and [DATA_RETENTION.md](DATA_RETENTION.md).
Keep original source workspaces, production archives, checkpoints, unique failures
and exact configurations at stable paths. Collapse historical evidence in the
index; do not move it merely to produce cleaner folder names. The local index
itself is regenerable. A same-disk copy is not an independent backup.

Make one scoped change, test it, inspect the diff, update `PROGRESS.md`, then
commit without force-pushing. Record known limitations instead of either hiding
them or turning unrelated physics research into a gate for interface improvements.
