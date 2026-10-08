# Exact count, serial batch preview and execution

The versioned v2 preview checks configuration, count arithmetic, seed assignment
and identity only. It launches no remage, Geant4, Julia, SSD or readout worker,
creates no run root/reservation and gives no Start token. Existing v1 Check,
saved imports, producers and terminal-result validators retain their original
Cs13720/500 and gamma20/fixed-seed restrictions. The current Control form uses
the separate executable v3 contract for radioactive sources; gamma retains v1.

## Versioned batch execution (M15b)

The shared `tools/scenario_workflow.py` CLI has explicit `check-batches`,
`run-batches`, `stop-batches`, `resume-batches` and `inspect-batches` actions.
They use the same positive-integer selection fields as the existing local
workflow, with an executable v3 checked contract separate from the v2 preview.
Control uses this same Check/Run contract for its count input. A preview is
never silently upgraded into a runnable plan. Gamma retains its legacy route;
the batch connector covers the admitted radioactive source/model selections.

Use an existing Python executable in the configured project environment:

```text
python tools/scenario_workflow.py check-batches --config selection.json
python tools/scenario_workflow.py run-batches --plan checked-plan.json
python tools/scenario_workflow.py stop-batches --name RUN_NAME
python tools/scenario_workflow.py resume-batches --name RUN_NAME
python tools/scenario_workflow.py inspect-batches --name RUN_NAME
```

Save the JSON returned by Check as `checked-plan.json`; Run consumes that exact
plan. CLI Check accepts either a bare selection or Control's versioned exported
configuration; both reconstruct a fresh checked plan. Check starts no science.
Default transport batches contain at most10000
initial nuclei and execute serially. One run root owns shared geometry, SSD
preparation and independent injection calibration; each batch owns raw transport,
complete event ledger and signed charge/readout. Model/source/operating settings,
runtime and source bytes bind reuse. The parent count includes zero-deposit and
failed primaries, not only detected events.

In Control, enter the total initial nuclei, click Check, then Run. Check shows
the exact serial partition; changing any input invalidates Run. Stop waits for
a sealed boundary. Resume validates that saved job before continuing it.
Saved batch event pages load on demand and retain global/local IDs, zero events,
truth/readout distinctions and raw artifact references. Native signals remain
saved; waveform previews cover only the first 16 groups per batch and show
unavailability explicitly for other groups. No download is triggered by viewing.

Stop is cooperative at a completed stage or batch boundary. Resume verifies
sealed stages and continues pending work. Uncertain unsealed scientific attempts
are retained and refused rather than silently rerun. A terminal receipt takes
precedence over a stale driver status. Existing science and legacy saved
validators are unchanged; this is functional engineering, not physical
convergence, calibrated efficiency or experimental agreement.

One preselected acceptance uses500 initial Cs137 nuclei in two250-nucleus
batches. The smaller cap is an immutable acceptance-only override, not a new
student setting. Ordinary runs retain the10000 cap. Arithmetic boundaries and
injected crash cases require no large physics campaign. Milestone status and
actual acceptance outcomes are recorded in the current `PROGRESS.md` handoff.

## Shared entry and immutable plan

Both the CLI `scenario_workflow.py preview-batches --config REQUEST.json` and the
authenticated loopback POST `/api/workflow/preview-batches` use `preview_request`
and the same `preview` resolver. The POST body is exactly `{"request": REQUEST}`.
The request object is exactly:

```json
{
  "kind": "local_scenario_batch_request_v2",
  "schema_version": 2,
  "selection": {"name": "...", "cryostat": "...", "detector": "...", "source": "...", "pose": "...", "primary_count": 25001, "seed": 26092631, "threads": 2, "electronics": {"...": "all eleven existing settings"}}
}
```

`selection` has the same closed fields and electronics authority as v1. Use the
existing exported v1 selection, then wrap it explicitly in this v2 request and
choose its count. Placeholder values above are explanatory, not an admitted
configuration. Missing/extra/duplicate fields, nonfinite tokens, booleans,
strings, floats and unsafe numeric counts fail rather than being coerced. Pose,
detector, operating variant, electronics and one/two Julia thread restrictions
are retained; ring gamma remains unavailable. V2 gamma may select any admitted
master radiation seed. The effective selection, model/source hashes, lockfiles,
Python/Julia executable hashes, scope and seed/identity rules bind one checked
parent preview with one prospective `.local/runs/NAME` root. Check does not create
that root. Reconstruct a preview with `admit_preview`; rehashing edited rules or
settings does not admit them. The v1 Run and GUI Start refuse the preview kind.

This preview reads pinned source/build/model files and existing executable bytes.
It does **not** probe the current remage/Geant4 runtime or establish worker
readiness, current package compatibility, numerical convergence or experimental
agreement. `batch_preview_scope` states these limits in the checked receipt.

## Count, partition and seed limits

Positive integer JSON counts must be exact within 1..9007199254740991, the shared
numeric safe-integer range. That representability limit is separate from seed
capacity and practical resources. The default radiation batch cap is10000.

| Total initial primaries | Serial batch counts |
|---:|---|
|1|1|
|499|499|
|500|500|
|9999|9999|
|10000|10000|
|10001|10000 + 1|
|25001|10000 + 10000 + 5001|

The plan stores a constant-size descriptor, not an all-batch or all-event array.
`iter_batches` is lazy; `batch_at` resolves any zero-based index. Each batch uses
one stock remage process with `-t 1`; Julia threads never multiply
the radiation count. Transport batching differs from LH5 extraction chunks.

Radiation seed rule `remage_affine_permutation_v1` assigns batch index `i`:

```text
1 + ((master_seed - 1 + i * 104729) mod 2147483646)
```

The project retains its existing conservative positive seed domain
1..2147483646. The installed remage1.1.0 `RMGManager.hh` declares
`SetRandEngineSeed(int seed)`; this domain fits that signed32-bit boundary. This
is a project policy, not a claimed upstream maximum for every random engine.
Since gcd(104729,2147483646)=1, the assignment is a permutation over that domain:
at most2147483646 distinct batch seeds, or21474836460000 total primaries at the
10000 cap. Larger representable totals are explicitly refused. No practical
resource acceptance is inferred for such totals. Distinct numeric seeds do not
prove statistical independence of engine streams. The batch seed depends only
on master seed and batch index, never total N, run name, timestamp or invocation
order; enlarging a partial final batch keeps its seed, without claiming unchanged
transport results. Edited/colliding seed receipts fail before dispatch.

The v3 native connector seeds parcels from the recorded native seed family,
global initial identity, raw row and parcel indices. Raw local IDs are retained.
The fixed legacy native seed and old science remain unchanged.

## Complete identity and independently checked census

Global initial ID is `batch_offset + raw_local_initial_id`, with both zero based.
Raw batch-local `evtid`, file/table/row keys, Track/Vertex identifiers, daughters,
creation/deposition times and values stay intact; mapping adds identity beside a
deep copy of the raw record. Time is not shifted across batches or interpreted
as drift time. Raw files are still necessary; this helper does not certify a
transport trajectory, ancestry, coordinate transform or physical raw schema.

`validate_census` independently compares the one literal active `/run/beamOn`,
raw `number_of_simulated_events` and a streamed complete initial-ID ledger. It
requires every local initial ID exactly once in ordered `0..batch.primary_count-1` coverage.
Zero-deposit primaries and native/readout failures stay in that census. Tracks,
vertices, delayed pulse groups and threshold-selected events never replace its
denominator. A doubled remage count, missing/duplicate/foreign/reordered ID or
additional beamOn command fails. The v3 raw reader/worker and parent receipts
connect these checks to actual saved data. Charge, signed voltage/ADC/Erec and unknown/null accounting remain
the existing science/readout responsibilities.

## Focused acceptance

Run `tools/test_workflow_batches.py` and
`tools/test_local_ui_workflow_protocol.py` with the existing Python runtime, plus
the unchanged workflow/controller tests. They cover boundary arithmetic,
constant-size/lazy large previews, seed stability/collisions, exact raw identity,
independent census, malformed/rehashed imports, GUI/CLI agreement, protected
protocol and refusal before any science/state/lease write. No10001-primary run
is needed to prove an arithmetic boundary. The preselected real two-batch
acceptance used500 total primaries; exact results, corrections and unchanged
original evidence are recorded in PROGRESS.md and the local execution receipt.
