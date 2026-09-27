# Saved Ge-hit overlay and representative candidates

`hit_event_view.py` reads only the exact existing
`.local/geometry-events-publication/bundle` and frozen `cs10000-v2` receipts.
It runs no Geant4, SSD, electronics, HDF5 reader or package installer. Python
standard library only. Canonical geometry, source pose and scientific records
are unchanged. The original viewer remains the complete 20,000-decay census.

The new population is **all 121 AK02 and 115 SAP22 Ge-positive original primary
IDs**, including the radiation records of native-response failures. Every raw
table row belonging to these primaries is preserved: all track graph rows,
vertices, primary particles and steps in every scored material. Lossless column
arrays omit repeated key strings; gzip reduces bytes without rounding, sampling
or changing any numeric value. Empty tables reconstruct using the original
schema. Both complete native scene JSON files are copied byte-for-byte.

## Bounded local commands

From the project root in PowerShell (no installation needed):

```powershell
$pv = 'C:/Program Files/ParaView 6.1.1/bin/pvpython.exe'
& $pv --disable-registry --no-mpi -B tools/hit_event_view.py --check
& $pv --disable-registry --no-mpi -B tools/test_hit_event_view.py
# Finish all four source files and exit any implementation writer BEFORE freezing.
& $pv --disable-registry --no-mpi -B tools/hit_event_view.py --freeze .local/million-transport-dev/viewer-freeze.json
& $pv --disable-registry --no-mpi -B tools/hit_event_view.py --build
& $pv --disable-registry --no-mpi -B tools/hit_event_view.py --validate
```

The sole generated bundle is `.local/million-transport-dev/hit-view`.
Export refuses an existing output, escaped/symlinked paths, changed original
source hashes, changed input pins, or any of the four changed viewer sources.
The manifest is written last. A source-change failure leaves an incomplete
derived bundle as evidence; never repeat physics to repair an export.
`--check` only analyzes in memory. Tests use temporary `viewer-tests-*`
directories under the assigned development root. `--validate` compares the
entire decompressed payload with fresh analysis of the pinned saved rows.

Serve the generated directory over localhost with an existing static server;
open `hit_event_view.html`. The page uses native canvas, SHA-256 and
`DecompressionStream('gzip')`, with no external frontend dependencies. Direct
`file://` fetch is unsupported. Modern browsers on HTTPS or localhost are
required for hash verification. A portable bundle works offline over localhost;
its link to the old viewer works when the complete original bundle is mounted
at sibling `../cs137-10k-geometry/`. The supervisor owns site integration and
browser visual checks. This tool never writes `docs/`.

## Evidence and honest categories

Classification uses original identities, the saved process map and the entire
track hierarchy. All positive Ge deposits in a classified pulse group must have
exactly one common source RadioactiveDecay photon ancestor with a saved ion
parent. Missing, cyclic, duplicate, mixed or non-photon ancestry is unknown.
Grouping matches the frozen preparation: sort positive Ge deposits by original
time/row index, with fixed 100,000 ns intervals starting at each first deposit.
Minute-separated daughter emissions are not one pulse. Original timestamps and
relative delays are both retained. The grouping is an isolated engineering
window, not a validated experimental pileup model.

Full-containment candidates compare Ge Edep **inside one pulse group** with that
photon's actual birth kinetic energy, using `max(1e-5 keV, 1e-8 * Egamma)`.
Root-linked positive non-Ge loss or other-window Ge energy above that tolerance
disqualifies containment. No 650–670 keV band is used, and Cs137 decay energy
is never assumed equal to 662 keV. Low-energy RDM photons are valid distinct
ancestors. This is a numerical radiation-energy candidate, not Erec or CCE.

Compact full-energy SSE **candidates** use maximum pairwise distance between
positive Ge deposit coordinates <= 1 mm. The metric describes saved deposition
points; it is not calibrated pulse-shape discrimination or the exact cloud size.

Observed Compton sites come from child electron creation process `compt` on
the photon ancestry, grouped by exact `(parent photon, time, x, y, z)`.
Multiple recoil/relaxation electrons at the same saved vertex/time share one
site; multiple electron steps never count as multiple scatters. Coincident
interactions and unrecorded subthreshold secondaries remain unresolved. The
one/two-site absorption candidates additionally require all these in-window
sites on the source photon, matched to recorded Ge photon STEP post vertices
within 1e-9 m, and a subsequent (nondecreasing saved time) `phot` electron
creation site on that photon also matched to Ge. Photoelectric relaxation rows
are not automatically separate absorption sites. The evidence retains every
electron ID, creation row, matching Ge row and site, including secondary-photon
sites. The saved STEP columns lack process and pre/post kinetic energy; these
are observed/inferred **candidates**, never exact physical interaction counts.

Partial photon-energy candidates are below that photon energy in the selected
window. Escape and unscored/non-Ge loss remain unresolved unless saved rows
provide specific evidence; recorded non-Ge deposits are listed separately and
do not imply full energy closure. No straight connectors cross missing air paths.

Categories overlap and counts refer to groups. Representative buttons choose
the highest observed photon-energy family within the same numerical tolerance,
then the upper median diameter (compact) or Ge Edep (other categories), ties by
original primary/group ID. This is an illustrative selection rule, not a claim
of statistical typicality. Empty categories get no substitute; buttons display
the actual ancestor energy. In these saved data SAP22's one-site absorption
candidate is a roughly 31.8 keV photon, not the roughly 661.657 keV line.

The default overlay contains all selected primaries' Ge chords/deposits and
relevant photon birth points/chords, including descendants of contributing
source photons. Selected-event highlighting and category filters do not remove
primaries from the background census. Optional full selected-event STEP drawing
caps at 2,000 chords, explicitly reporting drawn/total counts; payloads and raw
panels retain all rows. Raw panels render only when opened, refreshing on every
selection. One generation token rejects stale model, event and category results
and stale errors. Passive shells are hidden initially and can be shown.

Tests cover pinned complete census, exact original record round trips, source
and scene hashes, photon ancestry failures, electron/site distinction, separated
emissions, strict energy/diameter thresholds, nooverwrite/path safety, Node
syntax and actual frontend selection races with a controlled minimal DOM.
These are software/data checks; they do not validate physical detector response
or visual usability. No render-throughput guarantee or measured speedup is made.
