# Current Geant4 event readers

`viewers/geant4-assembly.html` retains all 20,000 initial events (10,000/model).
`viewers/ge-positive.html` uses only the saved 121 AK02 / 115 SAP22 Ge-positive
primaries from that earlier campaign. Candidate filters count pulse groups.
These pages use the original canvas renderers, geometry and exact recorded rows.
They do not show full trajectories or perform transport, SSD or electronics work.

Maintain `viewer_navigation.py`, `viewer_navigation.js` and
`viewer_overlay_selection.js`. Build through `build_site.py --restructure`;
never edit generated HTML. The adapter pins both original manifests, verifies
their assets and uses guarded substitutions of the original HTML. Its separate
`viewers/manifest.json` binds every original asset/manifest, original template and
exporter hashes, adapter sources and generated readers. Original templates,
bundles and receipts are never rebased. Sealed publication validators remain
distinct from historical raw-source tests that reject the old campaign launcher.

The reciprocal buttons carry `model`, `event` and optional `group`. IDs are
nonnegative decimal integers; event range is 0–9999, including zero. Model is
AK02 or SAP22. Repeated/unknown parameters and groups without events are rejected.
Successful selection updates the address and outgoing link. Missing primaries,
missing groups and category misses clear selection with an unavailable message;
the return link retains the requested identity. Assembly preserves group solely
as labelled return-navigation context. Event changes clear that group context.
Late model/event success and failure use the original selection gate.

Serve the complete site on localhost HTTP for local offline browsing. Readers
fetch only their original sibling bundles; SHA-256 and native gzip support are
required. Direct `file://` fetch is unsupported. Explicit archive links preserve
historical viewers, whose navigation does not provide current state continuity.
Desktop Edge viewport checks are not native tablet/Safari certification.

Run `test_viewer_navigation.py`, `test_viewer_navigation.mjs` and
`test_viewer_navigation_selection.mjs` (against the generated reader directory), applicable site
and spectrum tests, and `check_site.py`. The browser harness checks actual async
selection and reciprocal navigation against saved data. This display milestone
does not establish group recovery, preamp correctness or cold-machine acceptance.

Normal current-reader validation rejects unknown adapter-source hashes. An older
checked display can be read only when its entire manifest matches an explicit
trusted revision; that pins its HTML and original-data bindings, not merely its
self-declared source inventory. Changing/resealing HTML or the manifest invalidates
this compatibility path. New exports always require the exact current sources.
