# Germanium detector 3D visualization library

Open `Open_Library.cmd` or `index.html`. Each detector has its own gallery and ParaView launchers under `detectors/<id>/`. AK02 uses the same layout as every other detector.

To open any event, double-click `Open_Events.cmd` at the library root or in a detector folder. Select the detector/event, then click **Open in ParaView**. `Open_Animation.cmd` is a shortcut to the first event only. Native scene-file links have been removed from the galleries. Use the event selector; each gallery also provides copyable Windows folder paths. `Open_Presentation.cmd` and `Open_Comparisons.cmd` open the actual media folders under the current run.

The library covers all 12 entries in the existing dissertation model manifest, the existing 34-contact GeGI model, and four new dimension-based large references. Candidate, scenario and reference labels are preserved. The large references are representative published devices from GERDA and point-contact detector research; they are not claimed to be as-built LEGEND-200 serial models.

## Contents

- Rotatable detector and contact geometry, electric-field lines, weighting-potential sections and isosurfaces.
- A fixed event, four spatially varied random single-site examples, five two-site and three three-site examples, and finite-cloud/diffusion/self-repulsion controls.
- Carrier motion synchronized to electron, hole and total induced signals on a shared physical-time clock.
- Four MP4 clips, corresponding WebM browser previews and one GIF per detector, figures in PNG/SVG, numerical CSV files and native ParaView states.
- Drift-step sensitivity, cloud-seed/packet sensitivity, exact seed replay and scene reload checks.
- GeGI: all 34 weighting potentials/signals, neighbour induction, gap sharing, depth examples and an illustrative X/Y strip position estimate.

## Layout

```
Visualization_3D/
  index.html, Open_Library.cmd, README.md
  catalog.json, CURRENT.json
  detectors/<id>/
    config/                 source provenance, event settings; new reference YAML only
    CURRENT.json, index.html, Open_*.cmd
    runs/20260922_suite_v3/
      fields.vtr, crystal.vtp, contact_*.vtp, field_seeds.vtp
      01_geometry.pvsm, 02_static_fields.pvsm
      events/<event>/      raw SSD event, JSON, signal CSV, scene, preview, launcher
      comparisons/         PNG, SVG, measurements CSV
      presentation/        MP4, GIF, codec/size verification
      validation*.json, run.json
  src/                      Julia export and reproducible build tools
  paraview/                 shared geometry, animation and validation code
  maintenance/              sources, limitations, checks, cleanup records
```

Canonical dissertation YAML and baseline fields stay in `../models/` and `../results/`. The GeGI model and baseline stay in the existing `SSDmodel/GeGI_model` project. The visualization project reads those inputs and verifies their hashes; it does not rewrite them. Source locations are recorded in every `config/source.json`.

Run folders retain authoritative event data and expensive new field solutions. PNG movie frames, old per-frame animation meshes, duplicate legacy outputs and temporary caches are disposable after validation. Native animation uses an in-memory time source backed by event JSON, so thousands of VTP frame files are unnecessary.

## ParaView use

Use `Open_Geometry.cmd`, `Open_Static_Fields.cmd` or `Open_Animation.cmd` in a detector folder. Rotate with the mouse; the time slider and Play control event motion. Each event folder has `Open_in_ParaView.cmd`. Field lines show electric-field direction; carrier tracks come from SSD drift calculations. They are different objects.

For GeGI, use `Open_Strip_Channels.cmd`. The paired views show X09 and Y09 weighting fields with linked cameras. To inspect another weighting field, update the section threshold Scalars and Coloring, the contour Contour By and Coloring, and show the corresponding electrode mesh. All 34 `WP_*` arrays are retained. Select a signal table and enable channels in Series Parameters. All channel CSV values retain their sign. Two-contact overview curves may use a single fixed polarity multiplier, with the original signed signal retained in event JSON.

GeGI also has `Open_Strip_Explorer.cmd`: an offline browser dashboard for all 20 events, two numbered faces, a physical-time slider, signed signal colours and selectable channel waveforms. Its data and geometry are embedded; no server or internet connection is required. All GeGI event scenes now show 3D drift, both labelled faces and synchronized multi-channel signals. Electrode colour represents instantaneous signed charge on a fixed -1 to +1 scale, while carrier markers retain blue/electron and red/hole colours. Face panels use common global x-y coordinates, without mirroring the lower face. Geometry-only colours identify X/Y faces; the selected electrode in the weighting-potential scene has a separate meaning.

The saved states reference this workspace and the shared animation module. If moving the whole project, follow `maintenance/MAINTENANCE.md` to regenerate states and launchers. Do not move a single run away from its supporting files.

See `maintenance/MODEL_SOURCES.md` for measured versus assumed parameters and `maintenance/VALIDATION.md` for practical limits. Compton reconstruction and Geant4 integration are deliberately outside scope.

## Event library revision 3

Each detector now has four retained random single-site examples, five two-site examples and three three-site examples. Multi-site deposits are simultaneous, total 662 keV, and vary separation, depth and energy sharing. They are synthetic deposits, not a Compton or radiation-transport simulation. The original twelve random candidates remain as raw reference data; unselected candidates are excluded from the gallery and event selector. The selection and exact recipes are recorded in `config/event_library.json`.

Every active event includes a final display interval equal to 20% of its recorded duration (at least 10 ns). Original signals and trajectories are unchanged. Incomplete collection is explicitly labelled; a flat display extension is not evidence of collection. Full recorded late tails remain available, with nonuniform playback to keep the early pulse visible. A fourth presentation movie shows a three-site event.

GeGI static fields now compare the electric field with X09 and Y09 weighting potentials, using a cutaway shell, perpendicular sections and matched isosurfaces. The channel scene compares those two orientations above gap-sharing and three-site waveforms. Both weighting colour scales are fixed to 0–1.

## Plot layout revision 4

Pulse plots now use an activity-based horizontal range. If the original record is much longer than the pulse, the upper chart shows pulse detail and a smaller lower chart retains the complete history and final display hold. This changes the viewport, not the signal or simulated timestamps. All event legends sit to the right, outside the plotting area. Vertical limits include the full electron/hole/total or strip-channel extrema with a margin; very small responses are labelled.

Comparison-figure legends sit below their axes. Near-zero random responses do not determine the common pulse-detail range. GeGI multi-site comparisons show the summed signed X-face response rather than one possibly inactive reference strip. In the strip browser, the channel legend wraps below the canvas and the vertical range follows the event amplitude.

Close old ParaView scenes and reopen them using the launchers to load the new layout. Refresh open browser galleries. Validation and chart contact sheets are retained under `maintenance/plot_layout_revision4.json` and `maintenance/visual_review_v4/`.
