# Unified event viewer and ring-contact 10K delivery

Owner decisions: 2026-10-02. This is the current delivery plan, not a completed
campaign or numerical validation. M8/M9 remain deferred and do not block it.

## Fixed scope

- Merge the maintained `viewers/ge-positive.html` and
  `viewers/geant4-assembly.html` into one **GeSignal event viewer**, canonical path `viewers/events.html`, with one detector/event/pulse-group
  selection and display controls for assembly context and Ge-positive overlays.
- Reuse the completed AK02 and SAP22 10K data. Add GeRC02 and KMRC01, each with
  **10,000 initial Cs137 decays**, including zero-Ge events. The final current
  presentation covers four detectors and 40,000 initial decays across campaigns;
  this does not mean 40,000 detector pulses or a simultaneous acquisition.
- The owner corrected the Li target: **GeRC02 changes from 280 deg C / 30 min
  to 280 deg C / 50 min** in a separately identified campaign variant.
  KMRC01 retains the current `KMRC01_candidate` model, including its candidate
  qualification. The original GeRC02 30-minute snapshot stays unchanged.
- Keep the current nominal Cs137 source, outer cryostat and synthetic electronics.
  Record and check the ring-detector mounting and coordinate transform explicitly.
  This remains an engineering scenario, not an experimentally surveyed replica.

## Verified starting point

GeRC02 has a PtypePNjunction Li profile at 553.15 K / 30minute, bulk impurity
-1.05e10 cm^-3, 78 K model temperature, ring/readout contact 1 at 0 V and Li contact 2
at +240 V. KMRC01_candidate has constant +2.54e10 cm^-3 impurity, 78 K model
temperature, ADL drift, contact 1 at 0 V and outside contact 2 at -370 V; it has no
Li annealing input. Do not apply GeRC02's Li model to KMRC01.

Both ring models currently have geometry viewing support but
`lbnl_execution_implemented=false` in `scenarios/detector-capabilities.json`.
Existing producer, native consumer, campaign verifier and display contracts
contain AK02/SAP22-specific restrictions. Adding dropdown options alone does
not make the ring models executable.

The two requested live links successfully load AK02/event 213/group 0 and
SAP22/event 5930. They identify different primaries. The all-event reader retains
10,000/model; the Ge-positive overlay contains 121 AK02 and 115 SAP22 primaries.
The old response campaign records one native failed group per model. Retain its
exact data, failure accounting, hashes and historical identity.

## Ordered milestones and acceptance

Current execution (2026-10-02): both original500 pilots have completed their
transport/native/readout stages. GeRC02 Li50min passed with21 groups/19 accepted;
KMRC01_candidate has3 complete negative-charge groups, all rejected by the frozen
positive-peak electronics. The owner has authorized a KM-only fixed linear -1
electronics input wiring plus independent negative injection calibration. KM is
not yet promoted: the additive adapter must pass its saved-500 derivative checks.
Preserve the original pilot and reuse saved native signals for readout analysis.

GeRC02's guarded 10K was actually launched2026-10-02T17:28:41Z and is processing
native charge/readout. Keep its44 computational source pins unchanged while it
runs; prepare the additive KM readout/launcher and public presentation in parallel.
Do not run a second native worker. A saved-only readout correction does not
require repeating the completed KM radiation, field or native500 stages.

Production MUST use `tools/ring_production.py start --directory
.local/ring-cs137-v1 --model GeRC02`. The separately accepted KM case will use
its additive fixed-polarity entry after saved-pilot admission. This
maintained entry itself checks and launches the real500-derived10K. It rejects
known test-only receipts/non-HDF5 placeholders, binds model-specific VERIFIED and
four actual execution stages to the frozen sources/commands and recorded
supervisor exit. The frozen `ring_run.py --phase production` option is internal,
not the maintained production entry. Verify actual workers and any owned lock
before launch; a failed combined supervisor does not invalidate Ge's separately
verified completed stages. No original campaign source/configuration is rewritten.

| Milestone | Work | Completion evidence |
|---|---|---|
| M13a: one maintained viewer | Build one canonical page using the existing canvas/data readers. One selection controls assembly, STEP/deposit layers, Ge-positive overlay, classification and exact-row details. Preserve both old deep links through compatible entry pages, their default display modes and requested identities, including legacy assembly group return-context. | AK02/213/group 0 and SAP22/5930 resolve exactly; event 0, zero-Ge, missing groups, category misses, strict duplicate/unknown-parameter rejection, late async results and Back/Forward behave explicitly. Unavailable selection retains its requested identity without silently selecting another event. Radiation-only/zero/native-failure/no-charge cases remain valid geometry-viewing states. Existing raw bundles unchanged. Desktop/mobile, keyboard and offline-localhost checks pass. Publish and verify live. |
| M13b: model and mounting contracts | Define a GeRC02 Li50min variant binding original bytes plus the exact annealing-time delta and effective model hash. KMRC01 remains unchanged. Prepare checked ring placements/contours/electrodes/units/source geometry and versioned campaign inputs. | Independent checks confirm unchanged geometry, bulk impurity, bias, contacts and all non-time model settings. Native overlap/membership and transform checks pass. New effective-model field/cache bindings prevent reuse of 30min fields as 50min. No unrecorded fitting or layer-thickness substitution. |
| M13c: bounded full-chain integration | Extend the existing transport -> SSD -> preamp -> analog shaper -> peak ADC -> Erec contracts for the two explicit ring cases. Keep one orchestration/output root, streaming truth and serial workers. | Small named runs retain every primary/row/group/time/identity; separate injection calibration passes; signed charge/current/voltage/ADC units and readout polarity are checked. Existing bounded/saved/mock original-model regressions pass without changing inputs or numerical gates; old 10K/1M campaigns are not rerun. Historical source-bound receipts remain verifiable. |
| M13d: 500-decay pilots | Run each new detector serially with 500 initial decays and frozen production settings. Measure potential solve, native response, electronics, orchestration, memory and storage separately. | Full census/energy/geometry/calibration/artifact checks and clean pilot promotion gates pass, including actual positive native integration. Preserve a zero-hit or failed pilot as such; do not retune seeds, invent pulses or loosen acceptance to pass. Report a concrete impediment before a large run if promotion is unavailable. |
| M13e: two 10K campaigns | Run GeRC02 Li50min then unchanged KMRC01_candidate, each 10,000 initial decays, using the matching accepted pilot. Record exact software, seeds, model/config hashes, resource limits and stage receipts. | Complete truth census and every eligible group accounted for; zeros, finite trajectory limits, native failures and electronics rejections remain distinct. Successful groups have the full electronics chain; unknown quantities stay null. Resume reuses only fully hash-verified terminal stages; incomplete transport/native output or uncertain child intent requires inspection, not automatic rerun. Existing v1 has no general native-group resume. |
| M13f: equal public coverage | Export only completed hash-checked results; extend the current results hub, unified viewer, spectrum comparison and per-detector response/data entries to all four cases. Consolidate navigation and common controls; keep campaign/variant differences visible. | A four-detector coverage matrix has no missing current equivalent; full-precision ledgers and downloads match sources, including all zeros/failures. Relevant site/contact/viewer/spectrum checks, desktop/mobile/offline checks, local validation and exact live validation pass. Local commits and GitHub agree. |

M13a needs no new physics and proceeds first. Adapter/configuration work must be
frozen before pilots. A verified 500 pilot with the identical effective inputs is
required before each 10K run. Timings will be estimated from these new pilots,
not copied from the much larger ICPC geometries or tool/review waiting time.

## Page coverage and preserved history

The initial direct 10K inventory is nine HTML pages:

1. `viewers/ge-positive.html` and `viewers/geant4-assembly.html` (current readers).
2. `results/cs137-10k/index.html` (current result entry).
3. `spectra/cs137-10k.html` (current spectrum display).
4. `examples/cs137-10k/comparison.html` (saved original response comparison).
5. `examples/cs137-10k/AK02/response/summary.html` and the SAP22 equivalent.
6. `examples/cs137-10k-geometry/geometry.html` (original all-event display).
7. `examples/cs137-10k-hits/hit_event_view.html` (original positive-event display).

Current equivalents will cover all four models: event assembly/Ge-positive
layers, classification/evidence, truth and reconstructed spectra, individual
response traces/summary, counts/settings/provenance and exact downloads. Common
presentation is merged where useful; new ring response/data leaves still provide
the same functions as the two existing ICPC leaves. Check all inbound result and
detector-page links during implementation. The two historical signed display
bundles and old response bundle retain their bytes; current source adapters give
them clear archive links rather than falsely adding new results to old receipts.

Each model option binds a unique dataset/run/effective-model variant through the
checked manifest. Retain the simple model/event/group address contract; do not
add a competing dataset selector or silently mix campaigns. Show GeRC02's 50min
variant and KMRC01's candidate qualification in the visible model label/settings.
Response-page parity follows the existing first-four trace-example policy plus
complete truth/scalar/endpoint ledgers and downloads. Do not create fabricated
waveforms for zero-deposit or failed groups.

## Numerical and workflow boundaries

- Keep transport energy separate from charge response and Erec. Do not remove Ge
  deposits in radiation to imitate Li loss and then apply SSD loss again.
  Annealing time does not specify a universal millimetre dead-layer thickness;
  report the actual modeled concentration/depletion assumptions and limitations.
- Preserve model 78 K and explicitly recorded runtime 77 K conventions when
  matching the existing native campaign; annealing 553.15 K is a separate input.
  Do not silently modify ADL parametrization, operating bias or net impurity.
- Validate KMRC01's signed response and the existing electronics polarity using
  independent injections and bounded native points. Do not rectify with abs,
  normalize each event to Edep or change the shared electronics to make it pass.
  Report a verified incompatibility if the unchanged profile cannot support it.
- All 10,000 initial identities remain in each ledger even when there is no
  pulse. Delayed daughters retain original timing and finite grouping/windows.
  A threshold changes readout selection, never the initial-event census.
- Keep strict native failure handling for pilots. Any explicit production
  `record` policy retains the existing narrow error allowlist, full truth and
  exact errors, with unknown charge/readout null and separate native-failure
  status; it does not convert processing completion into validated transport.
- A new variant/adapter must be additive or preserve pinned historical
  compatibility. Do not weaken source/hash checks to admit a changed old bundle,
  or rerun old 10K/1M science because current exporter sources changed.
- No noise/Fano/resolution or calibrated Li CCE claims follow from numerical
  parcel sampling. No spectrum fitted to nonexistent measured pulse waveforms.
  Keep unresolved accuracy studies separate from the functional delivery path.

## Deferred recommendations

Owner update2026-10-02: evaluating and adopting additional remage practices is
a TODO. Prioritize the actual two ring-contact full-chain runs and the saved
engineering-example presentation repair. Reuse recorded findings when resumed;
no extra research round or software upgrade precedes these runs.

## Review, synchronization and continuation

Before each new milestone, choose its bounded implementation and acceptance
conditions. After each substantive implementation, two independent Sol6.1 Ultra
AI reviewers examine physics/electronics and transport/data/workflow; a NEW
same-setting third reviewer examines details, direction, complexity and value.
Freeze initial conclusions before exchanging concrete findings. Record real
discussion, fix confirmed blockers and distinguish AI review from certification.

Use existing environments and two Julia threads by default, models/stages serial.
No global installation/settings changes or new frontend/solver. Generated runs,
raw LH5, field caches and review evidence remain classified under `.local/`.
Preserve all old science, failed attempts and receipts permanently.

For each delivered milestone: relevant verification -> diff review -> compact
PROGRESS update -> meaningful non-force commit/push. Website generation is only
through `tools/build_site.py`; never edit `docs/` by hand. Run `tools/test_site.py`
and `tools/check_site.py` before publishing, then `check_site.py --url` against
the deployed result. Local/GitHub synchronization does not imply publishing raw
local science. The current handoff replaces the previous link-clutter priority;
clarity work is incorporated into the unified viewer/result navigation.
