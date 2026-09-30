# EXPERIMENTAL tiny NEW native-charge group checkpoints (M5b slice)

This EXPERIMENTAL fixed-cohort, private-input maintainer CLI generates
**new SSD native signed charge**, with durable
group commits. It uses existing immutable radiation deposits and checked field
cache bytes. It does not import previously calculated charge. Electronics,
calibration and full end-to-end M5b integration remain pending. Actual SSD host
acceptance and coordinator reviews are required after the implementation freeze.
Existing public/legacy one-shot and M5a commands are unchanged.

From the project root on the owner's existing Windows computer:

```powershell
$pv = 'C:\Program Files\ParaView 6.1.1\bin\pvpython.exe'
& $pv --no-mpi --disable-registry -B tools/native_group_checkpoints.py --name=tiny-native-v1 --dry-run
& $pv --no-mpi --disable-registry -B tools/native_group_checkpoints.py --name=tiny-native-v1 --stop-after-new-groups=1
& $pv --no-mpi --disable-registry -B tools/native_group_checkpoints.py --name=tiny-native-v1 --resume --dry-run
& $pv --no-mpi --disable-registry -B tools/native_group_checkpoints.py --name=tiny-native-v1 --resume
```

If the terminal's Julia alias does not start the pinned runtime, `JULIA_EXE`
may select the **already-installed pinned Julia 1.13.0 executable** for the
current terminal and its children only. Use the coordinator's recorded runtime
path, then restore the prior terminal value after the command. Do not change
PATH, global package settings or installed environments. The selected runtime
still must pass the existing probe, hashes and resume equality gates.

The declared AK02 cohort is original primaries **0, 2594, 3950**: three selected
primaries, one true zero, two nonzero groups and 91 retained deposition rows.
This is a deliberately selected engineering example from the million-decay
radiation population, not its complete response, spectrum or efficiency. Inputs
are the checked `.local/native-bridge-pilot/contracts-v3/AK02.json` export and
`.local/cs137-1m-native/config.json` cache provenance. No old native result or
campaign is adopted. Original raw rows, particle/track identities, coordinate
transforms and deposition clocks remain intact.
Validation hashes the existing radiation contract's **entire dependency
inventory**, including other selected-model/SAP22 and historical 10k inputs
unused by these three AK02 records. Those private prerequisites remain required.

New outputs are restricted to
`.local/native-group-checkpoint-v1/implementation/outputs/NAME`; names use 1..32
letters, digits, underscores or hyphens and must fit the Windows path bound.
New names must not exist. Resume requires the same name. Stop counts 1..4 newly
committed groups in that command; this fixed cohort has two groups total.

Default native failure policy is strict `abort`. A new command can explicitly
use `--native-failure-policy=record`; resume reuses its immutable recorded policy
and forbids every policy override. Recording isolates only the existing helper's
two exact native-domain ArgumentErrors and the pinned boundary guard's explicit
stall error. Unexpected exceptions abort. Failed groups retain exact errors and
the complete truth ledger; unknown native charge, endpoints/flags and readout are
null. There is no fabricated zero waveform, positive rectification or truth gain.

The existing pinned Julia 1.13.0 / SSD 0.11.8 environment runs one serial native
worker per invocation, plus a separate runtime probe before work. Threads=2,
BLAS=1 and offline package settings apply only to children. The adapter reuses
`NativeCheckpointBatch`'s loaded validators and native helpers without changing
their numerical modules. It deserializes the checked AK02 field cache once per
worker; there are no field solves. Cached 77 K / +500 V, contact 1, actual field
grid/fingerprint, 16 parcels, seed family 2609261, original event/row seed mapping,
2 ns drift grid and nominal 10 us cap are explicit. Diffusion is on, zero-field
termination off, self-repulsion off and geometry checking on, as in the existing
native helper. Native calculation seconds are distinct from process wall time.

`manifest.json` and `INITIAL.json` bind the **full selected primary and expected
group ledger before work**, including zeros, raw provenance, physics/settings,
cache/model/contact/grid, source and runtime hashes. Exact source input snapshots
are under `inputs/`. Resume reconstructs the same full ledger from original input
pins and validates all previous commits before runtime probing or new numerical
work. Disk contents never define expected work. Dry-run creates no output or lease,
looks up no Julia and launches no process. Saved dry-run validates progress under
the existing output lease. Completed resume validates the complete bundle without
Julia lookup/probe or writes, including with an invalid `JULIA_EXE` override.
Initialized outputs require structurally valid, manifest-bound `run.json`
progress with both completed group keys and their matching count. Every reported
key must still have a reopened valid commit and witness before any probe or work.
Missing/incomplete progress conservatively refuses. A valid commit newer than
progress is retained and reused; it is not generated again. Existing accepted
bundles are not migrated or rebased under changed source.

Full signed times/signal and all native step/parcel endpoint/contact/limit flags
are stored in `charge/KEY/charge.json`, separately from any electronic result.
Successful `readout` remains null because this slice has no electronics stage.
The original cumulative signal unit is induced-equivalent-energy keV; it is not
truth Edep or reconstructed energy. Finite support and endpoint flags do not prove
physical collection completion, calibrated Li CCE or experimental resolution.

The driver reuses M5a's staging, fsync, receipt and independent witness convention.
It independently validates and reopens each commit before ACK, and owns the final
selected census and `COMPLETE.json`. A missing/corrupt committed folder, receipt
or witness is refused. Canonical orphan data, incomplete initialization and
terminal driver data without COMPLETE are conservatively refused. Uncommitted
attempts, partial files, logs and failed derivatives remain evidence; they are
never deleted or silently adopted. A persistent exclusive `run.lock` prevents
cooperating writers; failures release the handle without deleting the lease file.
This does not claim every power-loss, cloud-sync or unrelated-writer crash case.
Transient filesystem rename failures can require later inspection/resume; there
is no automatic retry or permission change.

Bounded limits: at most eight selected primaries, four groups, 100 raw rows,
500,000 full charge samples/group, 4 MiB JSON, 600 s worker and 4 MiB child output.
The experimental interface exposes only the stated cohort, not arbitrary selection,
physics or cache overrides. It needs existing private inputs; this is not a
fresh-machine setup route. No new environment, daemon, database, GUI or website
export is added.
Ordinary orchestration entry, readout and calibration integration remain the NEXT
M5b task; this lifecycle fix does not add them.

Source-only fixture tests explicitly mock native physics. The separate opt-in
host harness generates one new tiny uninterrupted reference and one new driver-
death/resumed output, with identical seeds/backend. It compares every signed
native numeric value, support, identity, flag and error/null exactly, excluding
only native runtime seconds. It also checks immutable-file hash/size/mtime reuse,
one actual group-ready event per group/output and completed no-write behavior.
Death injection belongs only to the test harness; product code has no validation
bypass. See the local implementation `HANDOFF.md` for frozen commands and status.
The host test harness defaults to the immutable original `FREEZE.json`. A
distinct corrected candidate can use `--source-freeze=PROJECT_RELATIVE_JSON`
under the implementation evidence root; the complete source inventory and every
hash must match before host work. Previous freezes and failed attempts remain.
