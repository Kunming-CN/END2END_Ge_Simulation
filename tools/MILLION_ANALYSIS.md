# Saved million-decay analysis

`analyze_million.py` reads the completed `.local/cs137-1m` campaign, serially by
detector and chunk. It never runs Geant4, Julia, SSD, readout or package installers.
Only a new `.local/million-analysis/analysis-*` output is allowed; existing output
is refused. Original raw, compact, archive and receipt files are read-only inputs.
Supervisor state and locks are not accessed or changed.

Use the existing ParaView Python on Windows (not the Microsoft Store alias):

```powershell
& 'C:/Program Files/ParaView 6.1.1/bin/pvpython.exe' --disable-registry --no-mpi -B tools/test_analyze_million.py
& 'C:/Program Files/ParaView 6.1.1/bin/pvpython.exe' --disable-registry --no-mpi -B tools/analyze_million.py freeze
& 'C:/Program Files/ParaView 6.1.1/bin/pvpython.exe' --disable-registry --no-mpi -B tools/analyze_million.py run
& 'C:/Program Files/ParaView 6.1.1/bin/pvpython.exe' --disable-registry --no-mpi -B tools/analyze_million.py verify
```

Finish all implementation and tests before freezing. Do not edit any frozen source
during analysis. `verify` reads generated results only; it does not repeat analysis.
Freeze/run outputs deliberately cannot be reused or overwritten. A failed bundle
is incomplete evidence, not a reason to rerun physics. Commands, exit statuses and
runtime receipts belong in the assigned local evidence directory.

## Verification boundaries

Config and COMPLETE hashes bind the run. Existing simulation source hashes and
saved input templates must still match. DONE plans, contiguous global ranges,
model identities, chunk counts, seed derivation, recorded command and compact,
transport and archive-receipt hashes are checked. Metadata must equal the saved
template except primary count and seed. All chunk counts must agree with DONE
and COMPLETE. Raw archive size/hash receipts are cross-bound here; the supervisor
independently audits all 200 compressed archives. This script does **not** claim
to compare every compact value with the full archived raw file.

Compact schema checks include local/global ID uniqueness, exact primary census,
raw row-map order/uniqueness, units, nonnegative finite deposition, positive-event
photon emission counts from retained tracks, material/scalar agreement for positive
events, and all-Ge detail/scalar sums. Rehashed semantic mutations are rejected.
Stored all-primary emission scalars for zero-Ge events require the separate raw
archive audit because their track detail was not retained in compact form.

Only Ge-positive events enter the unchanged `hit_event_view.classify(event,
processes,100000)`. Groups use first-row anchored half-open 100 us windows. Every
positive event remains. Mixed/missing/cyclic ancestry is unknown. An exception
or dropped group from the classifier becomes an explicit failed/unknown record
with all positive rows and the exception retained. Integrity failures in the
compact input abort rather than silently replacing data.

## Outputs and denominators

- `positive-groups.csv.gz`: one row per positive isolated group, exact numeric
  values, detector/chunk/global offset/local ID/global ID/seed, categories and
  full classification JSON including original raw row maps. Local event IDs are
  never merged across chunks. Global IDs are detector-local; use `(model,global)`.
- `all-event-scalars.h5`: lossless typed, compressed scalar arrays including zeros,
  all material energies, photon counts, original IDs, chunk indices and seeds.
- `histograms.csv` and `histograms.json`: exact integer counts for Edep per initial
  decay, positive initial decay and isolated group. One-keV bins from 0 to 1400,
  with exact zero in its own disjoint bin. Other intervals are `[lo,hi)` excluding
  exact zero; underflow `<0`, overflow `>=1400` explicitly recorded. No clipping,
  normalization, fitting, random noise or smoothing of stored counts.
- `summary.json`: raw totals, independent census invariants, inclusive 650–670 keV
  deposition-band counts (not exact photopeak), family/category counts and explicit
  numerator/denominator fractions. Initial decays, RDM photon births, 660–663 keV
  emitted line photons, positive-Ge decays and isolated groups remain distinct.
  Full-energy roots are deduplicated by `(global_decay_id,source_track_id)` within
  a detector. Full per group and full per emitted photon are different quantities.
- `provenance.json`: exact source hashes, templates, runtime, seeds, all chunk
  hashes, simulation receipts and retained raw-column schemas/units.
- `representative-events.json`: up to two actual candidates per category/detector,
  with all retained original raw event tables, processes, identity, seed, ancestry
  and exact classifier evidence. Prefer 661.657 keV within the existing tolerance,
  then closest actual photon energy, global ID and group ID. No invented category
  if none exists. The same event may demonstrate multiple overlapping categories.
- `report.html`: a small standalone offline page with inline SVG plots, stage
  definitions, old 10k descriptive counts and actual photon-family tables. It
  embeds no event archive and requests no external resources.
- `COMPLETE.json`: only written after source recheck and output hash/census checks.

Photon-family anchors group source energies only within the existing classifier
tolerance `max(1e-5,1e-8*energy)`; exact observed minima/maxima are retained. Group
CSV and representatives retain exact actual photon energy. In particular,
31.8-keV-family full events must never be presented as 662-keV line events.
Category counts overlap: compact and observed 1/2-Compton are subsets of full.
Full/partial/unknown alone partition groups. Observed Compton creation sites are
not certified physical interaction counts or PSD labels.

## Interpretation

These are **deposition truth spectra, not ADC or reconstructed-energy spectra**.
No charge transport/readout/noise has run for the million-decay campaign. No fitted
FWHM, physical resolution, experimental agreement or calibrated efficiency is
claimed. Scoring coordinates are global metres, despite the `xloc` field name.
Material energy is recorded-only; world air and escaping energy prevent energy
closure. STEP chords and track births are not full trajectories through unscored
material. The nominal geometry/source and independent-group reset assumptions
remain. Old 10k comparisons are descriptive simulation sampling, not matched
experimental controls. The report is shareable in size but is not published by
this tool; full event data and archives remain local.

## Bounded tests

The suite loads one actual 10k compact fixture and creates derivative test copies
only under `analysis-tests-*`. It tests multi-chunk collisions, zero census, exact
histogram edges/tails, photon/group normalization, unknown/failing classifiers,
duplicate track ancestry, deliberately rehashed ID/row-map/energy/unit/seed/source
mutations, non-overwrite, freeze enforcement and old saved-count comparison.
No million-event analysis or physics calculation is part of the test suite.
