# Saved gamma native/electronics engineering example

`gamma_native_example.py` composes the existing native SSD and synthetic
electronics numerical primitives. It reads completed M11b gamma streams and
existing field caches; it launches no radiation or field solve. Frozen Cs137
producer, stream/session and electronics-only runtime contracts stay unchanged.
Use the existing pinned simulation Julia environment. No installation is attempted.

From the project root, run `python tools/gamma_native_example.py check`, then
`python tools/gamma_native_example.py run`. The default new output is
`.local/m11c-gamma-native-v1/example`, default two Julia threads; `--threads 1`
is supported. Models run serially. Existing destinations are refused.
`--native-failure-policy abort` is the default. Explicit `record` isolates only
the existing two native-domain ArgumentErrors; all other failures abort and retain
failure evidence. A failed run is never automatically retried. To inspect saved
results without physics, use `python tools/gamma_native_example.py verify OUTPUT`.
The check and verify modes launch no Julia process.

Each detector keeps the whole20 initial-gamma truth census and all material/raw
scalar rows. The fixed pre-outcome first-zero/first-two-positive cohort is
AK02 IDs0/4/5 and SAP22 IDs0/2/3; the other17 are explicitly unprocessed with null
response. Complete selected Ge rows, including zero-energy rows, retain original
initial IDs, raw indexes, birth ancestry, source positions and flight/deposition
times. The primary origin is0ns. A deposition delay is not a carrier drift time.
No gamma is relabeled with a decay ID or activity normalization.

The original78K model snapshots stay frozen. Existing77K caches are an explicit
override, contact1=0V/readout1, contact2=+500V AK02/+700V SAP22. Native positive
events use16 independently seeded equal-energy parcels, diffusion,2ns, nominal
10us drift cap, zero-field termination off, no self-repulsion. No outcome filtering,
seed tuning, signal rectification or forced full collection is performed.
Selected true zeros bypass native drift; a labeled known zero-charge input is
processed by electronics without fabricated native endpoints/waveforms.

One separate500keV delta-charge injection per detector supplies its fixed gain.
Event truth energy never enters that calibration. Only expected_primary_count=3
differs from the frozen resolved profile; whole parsed configuration equality is
checked independently of hashes. The unchanged gamma readout uses its natural
charge duration plus the configured analog tail. Signed charge/current/voltage,
endpoint/cap flags, analog window, threshold/ADC rejection and null Erec survive.
The analog time grid is not a waveform-digitizing acquisition system.

The root contains `run.json` and, only after complete validation, `COMPLETE.json`
with exact artifact/source inventory. Each model contains:

- `request.json`: complete20 original source objects, source manifest/preparation,
  fixed selection, exact input/code/cache/model pins and frozen settings.
- `report.json` and `event-ID.json`: the three selected responses, independent
  calibration, truthful loaded runtime, signed native products and endpoint flags.
- `truth-ledger.jsonl`:20 `{initial_primary_id,selected,processing_status,source_truth,response}`
  records. `source_truth` is the whole unchanged original JSONL object.
  Unprocessed response is null; documented native failures retain exact errors
  and unknown charge/endpoints/readout null. A true zero is its own status.
- `signals.csv`: every known signed charge input sample, keyed initial gamma ID;
  native failures have no fabricated rows. `calibration.json` binds the separately
  injected calibration and effective configuration. `child.json`/`worker.log`
  preserve the actual invocation and import/worker wall time.

Native-stage, calibration, electronics and startup/orchestration times are separate.
`native_seconds` includes the immediate input/source integrity hashing inside the
timed native wrapper, as well as the unchanged native helper; it is not measured
pure SSD drift time. Request parse/report SHA use one bounded consumed byte buffer.
Canonical per-model cache paths/model hashes/cache hashes must match their request
pins before loading; deserialization consumes the same bounded cache buffer whose
canonical SHA was verified. The inventory excludes only the two root receipt paths.
All nested products, including matching receipt basenames, are retained and hashed;
field_solve_seconds=0. This is a low-statistics functional engineering example,
not calibrated Li CCE, experimental spectra/waveform agreement, physical parcel
noise/resolution, efficiency, as-built geometry or grid/PDE convergence. Raw
recorded-material energy is distinct from readout-derived Erec; missing world/
escape energy and activity remain unknown. STEP chords and Track births are not
complete trajectories across unscored material. Old science and failed trials
remain permanent evidence.

## Public saved-data showcase

`tools/gamma_showcase.py` reads only the specifically pinned completed M11c
example, its archived 19 execution sources and existing M11b JSON streams.
It imports no producer, loads no cache/LH5 and launches no Julia, radiation,
charge, calibration or readout work. All 40 original truth objects, six original
responses, 34 unprocessed/null responses and 10057 signed input samples survive.
AK02 retains 195 capped endpoints even where peak ADC accepted a response.

The saved readout traces already contain only 599/600 display points; their
`original_sample_count` values are larger. Full original analog arrays were not
saved. No missing bin is reconstructed. These are numerical analog samples,
not waveform acquisitions. The exact CSV bytes and canonical public JSON retain
binary64 values, numeric types and negative zero. UI detail formatting is a view;
the download is the exact exported data.

First wait for both implementation writers to exit. Record
`.local/m11d-gamma-showcase-v1/WRITER-EXIT.json` with `status="exited"` and
`science_calls=0`, then `SOURCE-FREEZE.json` with
`status="frozen_after_writer_exit"`, the exact `writer_exit_sha256`, and `files`
containing every `gamma_showcase.SOURCE_FILES` path with `{sha256,bytes}`.
The frozen source binding excludes mutable handoff/review records. Run
`python tools/gamma_showcase.py export`; the only accepted new output is
`.local/m11d-gamma-showcase-v1/bundle`. Existing or partial outputs are refused,
and failures require inspected exporter recovery, never a science rerun.

`python tools/gamma_showcase.py validate BUNDLE` checks a completed public bundle
without original private data. A reviewed fixed typed scientific digest rejects
scientific edits even after public manifests are rehashed; configuration/census,
exact CSV bytes, privacy, frozen source/template and embedded HTML bindings are
checked separately. Hashes establish reproducibility/integrity, not authorship
signatures, physical validation or human certification. Only identified runtime
path fields change to portable roles; scientific fields and LH5-internal `/stp/`
dataset addresses remain exact. Raw caches, upstream geometry inputs and private
evidence stay local.

All eleven implementation sources are checked at the first export/freeze, and
their hashes remain historical generation provenance. Later changes to generic
navigation/checkers/tests/publishing/documentation or a compatible exporter do
not invalidate an already checked bundle. The gamma HTML template remains an
active exact rendering dependency: an intentional template/schema change needs
a reviewed saved-data-only export, without scientific reruns. Preserve the
previous completed bundle and reconcile a presentation upgrade explicitly.

Use `python tools/build_site.py --gamma-showcase BUNDLE` to copy this checked
bundle onto the current checked website snapshot. The optional Results card
links to `examples/gamma-native/gamma.html`; old example URLs remain available.
Normal `Publish.cmd` / `--restructure` preserves these hash-bound bytes and does
not export or compute the example. Validate the full public prefix locally and
with `check_site.py --url` after deployment. M8/M9 acceptance on a second computer
remains deferred.
