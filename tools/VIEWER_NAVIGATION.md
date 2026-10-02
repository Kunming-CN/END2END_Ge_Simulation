# Current Geant4 event reader

`viewers/events.html` is the maintained GeSignal event viewer. One model,
primary ID and optional pulse-group selection controls one canvas: assembly,
recorded STEP chords and creation vertices, Ge deposits and saved Ge-positive
classification/evidence. It retains all 20,000 initial events (10,000/model).
The positive layer contains the saved 121 AK02 / 115 SAP22 primaries; candidate
filters count pulse groups. It does not calculate charge or readout responses.

## Source and saved-data ownership

Maintain `viewer_navigation.py`, `viewer_navigation.js`,
`unified_event_viewer.html` and `unified_event_viewer.js`. Build only through
`build_site.py --restructure`; never edit generated HTML. The original
`geometry_events.html`, `hit_event_view.html`, sealed examples and numerical
payloads remain frozen. The unified canvas reuses their native-mesh, projection,
chunk-loading and saved group/evidence functions.

The separate `viewers/manifest.json` binds every original asset/manifest,
original template/exporter hash, maintained source and all three generated
entry pages. Current validation reconstructs exact HTML and rejects changed
sources or extra files. A historical display is accepted only by its complete
explicitly trusted manifest and unchanged HTML/asset bindings. Self-declared
source hashes cannot authorize a changed old bundle; new exports require the
current frozen sources.

## Selection and compatibility

Canonical queries accept only `model`, `event`, `group` and `view`. Models are
AK02 or SAP22; `view` is `assembly` or `positive`. IDs are nonnegative decimal
integers, event range is 0–9999, including zero. Repeated/unknown parameters,
invalid values and groups without events are rejected. Requested identity is
separate from verified rendering; an unavailable primary/group/category never
silently selects another primary.

`viewers/geant4-assembly.html` and `viewers/ge-positive.html` are compatibility
entries. They accept only the original three query keys and transfer a valid
request to the canonical page with the original assembly/positive preset.
Assembly keeps an optional group as labelled return-navigation context; it
neither invents that group nor blocks geometry if the group is unavailable.
Choosing a different primary clears its old group context. Switching to positive
attempts the requested group; an unavailable group clears only group evidence.

User selections update the address without duplicate history entries.
Back/Forward restores the requested identity and view. Late load success and
failure are ignored after a newer selection. A positive-layer failure clears
that layer while retaining independently verified assembly records. Open detail
folds clear on selection changes and show only current verified rows/evidence.

## Scope and checks

Creation times are not SSD drift times. STEP chords join only the endpoints of
recorded scored steps; track birth records are not complete trajectories. Zeros,
unknown native response and readout rejection do not remove a radiation primary.
Draw-only detail limits never cap the raw event ledger or numeric precision.

Serve the complete site on localhost HTTP for offline browsing. The viewer
fetches its original sibling bundles with SHA-256 checking and native gzip;
direct `file://` fetch is unsupported. Explicit archive links preserve the
historical viewers. Existing-host desktop/mobile checks are not second-computer
installation or native Safari/tablet acceptance.

Run `test_viewer_navigation.py`, `test_viewer_navigation.mjs` and
`test_viewer_navigation_selection.mjs` against the generated reader directory,
applicable site/spectrum/contact checks, and `check_site.py`. The saved-payload
script harness checks selection/async/history behavior; actual browser checks
cover layout, keyboard and both old deep links. Publication performs no science.
