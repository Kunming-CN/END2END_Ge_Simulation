# Exact count and serial batch preview (M15a)

The versioned v2 preview checks configuration, count arithmetic, seed assignment
and identity only. It launches no remage, Geant4, Julia, SSD or readout worker,
creates no run root/reservation and gives no Start token. Existing v1 Check,
saved imports, producers and terminal-result validators retain their original
Cs13720/500 and gamma20/fixed-seed restrictions. Control's current form remains
the v1 form. Real batch execution is M15b; the count form/event access is M15c.

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
one prospective stock remage process with `-t 1`; Julia threads never multiply
the radiation count. This is an execution requirement for M15b, not execution
already implemented here. Transport batching differs from LH5 extraction chunks.

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

Native parcel/row/group seeding from global identity is explicitly pending M15b.
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
additional beamOn command fails. These checks are pure/injected in M15a; actual
raw reader/worker and parent receipts must connect and independently validate
them in M15b. Charge, signed voltage/ADC/Erec and unknown/null accounting remain
the existing science/readout responsibilities.

## Focused acceptance

Run `tools/test_workflow_batches.py` and
`tools/test_local_ui_workflow_protocol.py` with the existing Python runtime, plus
the unchanged workflow/controller tests. They cover boundary arithmetic,
constant-size/lazy large previews, seed stability/collisions, exact raw identity,
independent census, malformed/rehashed imports, GUI/CLI agreement, protected
protocol and refusal before any science/state/lease write. No10001-primary run
is needed to prove an arithmetic boundary. M15b still requires its one
preselected real two-batch acceptance using at most500 total primaries.
