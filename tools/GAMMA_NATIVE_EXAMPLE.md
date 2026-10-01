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
