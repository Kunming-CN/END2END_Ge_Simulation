# Saved-charge inspection (M4a) and electronics replay (M4b)

Current routes: the read-only M4a inspector retains its historical status fields
below; these do not describe the separate delivered M4b replay command. Replay
and its opt-in saved-charge checkpoints are documented here and in
[GROUP_CHECKPOINTS.md](GROUP_CHECKPOINTS.md). Bounded new native charge/readout
from checked private AK02/SAP22 inputs is a distinct delivered entry:
[NATIVE_READOUT_INTEGRATION.md](NATIVE_READOUT_INTEGRATION.md). Use the single
[setup & run guide](https://kunming-cn.github.io/END2END_Ge_Simulation/guide.html#local-routes) for prerequisites and route selection.

From PowerShell at the project root:

```powershell
.\Run.cmd charge-check -Name custom-electronics-500-ak02-v1 -Json
.\Run.cmd charge-check -Name NAME -Detector AK02
```

`-Detector both` (default) inspects all detectors recorded in that named run.
Explicit `AK02` or `SAP22` must exist. Only `-Name`, `-Detector`, and `-Json` are
accepted, even if another flag repeats its default. JSON output is one object
on stdout; callers may redirect it to separate evidence. Nothing is written in
the source run. No replay, install, simulation or readiness probe is started.

| Field | Meaning |
|---|---|
| `inspection_status` | `completed`: inspection produced findings; `blocked`: run/lock/parent could not be inspected |
| `storage_complete` | Every native-success group has its complete recorded signed-charge grid, consistent with census, truth, endpoints and bindings. **Not complete physical collection.** Native failures retain null charge. |
| `producer_compatible` | Full recorded child/transport source inventories match current files and supported recorded versions; a file comparison, not a runtime test |
| `runtime_verified` | Always `NOT_CHECKED`; no Julia, WSL, SSD or package probe |
| `replay_supported` | Always `NOT_IMPLEMENTED` at M4a |
| `eligible` / `eligibility_status` | Always `false` / `not_eligible` at M4a; no calculation is authorized |
| `verification_final` | True only after the final input-hash recheck. A failure clears aggregate and detector storage/producer claims; retained diagnostics have `observations_status=nonfinal`. |

Exit **0** means successful inspection, including a rejected, incomplete or
unsupported child. Read the fields/findings; exit 0 never means eligible.
Exit **2** means blocked inspection or Python argument rejection. PowerShell
parameter/interpreter errors are nonzero and may appear only on stderr, before
a JSON report is possible. Strict resume/recover validators are unchanged.

## Interpreter and shared interface

The standard-library API is `tools/charge_check.py:inspect_run(root, name,
detector='both')`. Future interfaces should use this same path. The Python CLI
accepts `--name`, `--detector`, `--json` and needs existing Python 3.10+.
The Windows wrapper selects explicit `SITE_PYTHON` first (an invalid explicit
path fails), otherwise PATH `python.exe` excluding Store aliases, then existing
ParaView 6.1.1 under `%ProgramFiles%`. It never probes versions or installs.

```powershell
$env:SITE_PYTHON = 'D:\Applications\Python\python.exe' # your existing interpreter
.\Run.cmd charge-check -Name NAME -Json
```

For an existing `pvpython.exe`, the wrapper supplies `--no-mpi --disable-registry`.
Python uses `-B`; the helper itself launches no subprocess. It exclusively opens
**an existing** `run.lock` read-only during inspection. Missing, held, inaccessible
or linked locks/paths are refused; locks are never created, removed or recovered.

## Supported scope

Terminal `native_campaign_v1` in `.local/runs/NAME`, bound to its final guarded
`native_response_v1` and `cs137_decay_stream_v1` inputs. Supported AK02/SAP22
settings are deliberately narrow: 77 K override of stored 78 K; +500/+700 V;
contact 1; 16 parcels; native seed 2609261; 2 ns grid; nominal 10 us cap;
diffusion on, self-repulsion/zero-field termination off; 100 us isolated grouping.
CSV policies `all`, `examples`, `none` are judged by actual coverage. An examples
file can contain every group; its label alone does not decide.

Checks cover exact artifact inventory/hashes/sizes, final parent-child binding,
copied input/profile and independently resolved configuration, model catalog and
bytes, input chunks and every primary (including zeros), ordered group/source-row
membership, CSV/JSONL mirrors, endpoint parcels/species/seeds/weights/delays/flags,
and sample IDs/order/count/grid/signed finite values/extrema/final charge.
Truth Edep never normalizes charge. CSV values are **signed induced-equivalent
energy in keV**, not fC: `Q_C = value_keV * 1000 / E_ionisation_eV * 1.602176634e-19`.
Absolute deposition time remains separate from time since group origin.

The full original parent, child and transport source inventories remain in the
report. Parent control/launcher differences are reported separately, without
declaring scientific corruption or rebasing originals. There is no historical
producer whitelist or narrower charge-only dependency approval: all recorded
child/transport sources, including coupled electronics and tests, must match
for producer compatibility. Intact older outputs may therefore be incompatible.
Hashes check consistency, not adversarial authentication. Saved field/runtime
records are provenance: no field cache, installed package source or executable
is independently verified. Raw LH5 bytes are hashed, not decoded.

Custom electronics requires the complete `saved_electronics_execution_v1` mirror.
The input descriptor must bind a schema-1 `electronics_settings_bundle_v1`;
ancestors may be those bundles or schema-2 `native_readout_profile_v1` files.
The checker reconstructs the exact ancestor/source/default copy inventory, checks
every descriptor/hash and each bundle's independently resolved configuration and
physics hash, and binds the selected profile to the parent and child. It uses
only mirrored inputs, never external originals or archived-script execution.
The frozen defaults and source inventory follow the existing ES/EE contracts;
parent control-source differences remain separate from child compatibility.
Physics hashes use the existing Windows PowerShell 5 invariant `R` number format
(15 significant digits when they round-trip, otherwise 17). Inputs are limited
to 128 KiB, 16 ancestor files with cycle rejection, and 256 mirror entries.
Unsupported ancestry formats return a structured refusal. Removing the custom
binding cannot silently fall back to a current canonical profile.

JSON identities/counts require integers, never booleans or float spellings.
Relative grid/delay tolerance is `1e-12` relative plus `1e-9 ns` absolute;
absolute times allow at most two representable float steps and remain bound to
copied original records. Charge tolerance
is `1e-12` relative plus `1e-9 keV` absolute (`1e-8 keV` for endpoint sums;
`1e-25 C` for conversion). Stored integer IDs/counts have no tolerance.

Bounds: 10,000 primaries; 2,000,000 rows/file; 128 MiB/file; 512 MiB distinct
input bytes; 4 MiB JSON documents; 2 MiB lines. Charge rows stream rather than
loading waveform arrays. Watched hashes are rechecked before closing the lock.
Cooperative locking does not prove unrelated writers obey it.

Display-decimated `traces.jsonl` never substitutes for charge CSV. Missing/partial
CSV gives exact missing/truncated findings. `.jls`, checkpoint and other parent
formats return `not_supported` / `compatible_reader_required`; no arbitrary
deserialization, SSD load or recursive archive conversion. Numerical convergence,
calibrated Li CCE and experimental agreement remain out of scope. The inspector
itself never performs M4b replay.

Tests use explicit synthetic storage fixtures, not physics acceptance:

```powershell
python -B tools/test_charge_check.py --evidence .local/charge-reuse-v1/implementation/NEW_TEST_DIRECTORY
```

## Electronics-only derivatives

```powershell
.\Run.cmd replay-readout -Name custom-electronics-500-ak02-v1 -ReplayName NEW -DryRun -Json
.\Run.cmd replay-readout -Name custom-electronics-500-ak02-v1 -ReplayName NEW -Detector AK02 -Json
.\Run.cmd replay-readout -Name SOURCE -ReplayName OTHER -ElectronicsProfile .local/electronics-profiles/PROFILE.json -Json
```

The one-shot mode accepts `-Name`, `-ReplayName`, `-Detector`, `-ElectronicsProfile`,
`-DryRun` and `-Json`; opt-in M5a adds the checkpoint flags documented below.
Default `both` selects the source's recorded detectors.
Omitting a profile preserves each detector's recorded effective profile.
An explicit profile uses the existing settings contract: schema-2 profiles or
current-source-bound schema-1 settings bundles, including checked ancestry.
Old saved bundle provenance is retained and never rebased. The original run's
eleven mirrored inputs are still inspected by M4a independently of any override.

`tools/replay_readout.py:replay_run` is the shared backend. It keeps M4a's existing
exclusive read-only source lock through checks, exact CSV/ledger extraction,
child execution, independent reconciliation and final checksum/size/mtime checks.
Missing or held locks are refused. Every native-success group uses complete
`signals.csv`, with signed induced-equivalent keV and recorded 2.95 eV/2 ns units.
Native failures keep their original null response and exact reason; zero primaries
remain in the census. Endpoint/step-limit flags never change.

Dry-run reports `planned` and `runtime_verified=NOT_CHECKED`. It launches no Julia
or scientific worker, creates no derivative folder, and writes nothing. It checks
storage, producer, configuration and arithmetic limits; it cannot certify runtime
availability. An explicit settings file may invoke the read-only PowerShell parser.

Run requires installed Julia **1.13.0 / JSON 1.9.0** in the unchanged simulation
project/manifest. `JULIA_EXE` selects an existing executable; an invalid explicit
path fails. Otherwise PATH Julia or the existing pinned Juliaup installation is
used. No Juliaup update, package installation or environment modification occurs.
Child-only settings use two Julia threads, one BLAS thread, offline package mode,
the project/stdlib load path and existing compiled modules. Actual loaded JSON,
project/manifest and `ReadoutProfiles.process` source/module identities are checked.
The additive worker includes only `readout_profiles.jl` and its unchanged
`readout.jl`; it never loads SSD/native-response or transport.

The new `.local/replays/NEW` must not exist. Atomic directory creation prevents
repeat/concurrent overwrite; failed folders retain evidence and require a new
name. The driver-owned `run.json` has kind `electronics_replay_v1`, distinct from
native campaigns. The worker's `worker_complete_untrusted` receipt cannot publish
trusted outer completion. `completed` (or `completed_with_native_failures`) is
written only after the child succeeds and every primary/group, flag, signal
identity, trace grid/current/charge, ADC decision and artifact binding reconciles.
Failure invalidates final claims. JSON stdout is a summary; full provenance,
runtime, original receipts, configuration and artifact hashes are in `run.json`.

Electronics uses `ReadoutProfiles.process` with the recorded isolated group origin
and half-open 100 us window, ending at 99998 ns. Calibration is a separate fixed
500 keV delta-charge injection for each effective configuration, shared across
groups; no Edep normalization or event-specific gain. Constant terminal charge
means zero tail current under the original assumption, not completed collection.
Traces are display-decimated outputs and are never generic replay inputs.

Limits include the M4a reader caps, 2,000,000 charge samples, 20,000,000 analog
samples, per-group 500,000 samples, 600 s worker time, 4 MiB joined child output
(60 s/64 KiB runtime probe). Requested settings exceeding injection calibration
bounds fail. One-shot replay has no group recovery; opt-in saved-charge M5a is
documented below. Native-production checkpoints, serialized/large readers,
noise/hardware fitting, waveform ADC acquisition and new physics remain unsupported.

Same-setting acceptance gates are fixed before calculation: analog voltage
`1e-11 V` absolute plus `1e-10` relative, energy `1e-8 keV`, charge `1e-25 C`;
peak times, ADC codes, acceptance/reasons and census/flags are exact. Small analog
roundoff could affect a pulse close to a threshold/LSB boundary; those discrete
gates are never loosened. Agreement verifies software reuse, not experimental CCE.
The acceptance tool then changes only threshold to 1 V: calibration, analog
signals, times and ADC codes must remain identical while all four stored peaks
become rejected and all 500 primaries/496 zeros remain.

```powershell
# Software fixtures explicitly mock runtime/electronics; no numerical acceptance.
pvpython --no-mpi --disable-registry -B tools/test_replay_readout.py --evidence .local/charge-replay-v1/implementation/NEW_TESTS
# Actual existing-Julia acceptance; exactly two NEW electronics derivatives.
pvpython --no-mpi --disable-registry -B tools/test_replay_readout.py --real --evidence .local/charge-replay-v1/implementation/NEW_ACCEPTANCE --same-name NEW_SAME --changed-name NEW_THRESHOLD
```

## Recorded host acceptance and remaining limits

Opt-in M5a checkpoints for **new saved-charge electronics derivatives** now use
the same `replay-readout` entry with `-CheckpointGroups`, `-StopAfterGroups N` and
`-Resume`. Saved-progress `-DryRun` and completed resume launch no Julia and write
nothing. The default one-shot workflow remains unchanged. See
[GROUP_CHECKPOINTS.md](GROUP_CHECKPOINTS.md) for strict flags, immutable group
receipts, conservative interruption boundaries, retained evidence and coordinator
host acceptance. This mode imports saved charge; it does not produce new native
charge. The separate bounded native-readout entry now has its own recovery contract
and host acceptance. M5a passed existing-host cooperative and instrumented process-death
acceptance; see GROUP_CHECKPOINTS.md and `.local/group-checkpoint-v1/COMPLETE.json`.
The following retained acceptance concerns the separate one-shot M4b mode.

The normal existing-host acceptance used the public command for two NEW
same-setting/threshold-only derivatives of the saved AK02 500-primary run.
Same-setting calibration, complete scalar records and saved display traces
reproduced the original under the declared tolerances, with exact clocks,
identities, ADC codes, selection and endpoint flags. Changing only threshold to
0.05 V kept calibration/analog traces/ADC unchanged and accepted events 213/450,
rejecting 220/325. All 500 primaries, 496 zeros and 20,008 charge samples remained.
Complete stored charge still has step-limit flags; it is not complete collection.

Evidence: `.local/charge-replay-v1/coordinator-host-v2/COMPLETE.json` and
`host-verification-v2/`. The independent host acceptance uses 0.05 V; the optional
`--real` test above uses 1 V and is a different predefined check. Its original
writer-side attempt failed before calculation and is not counted as passed.
The host checks are not SAP22/native-failure numerical acceptance or general
serialized-reader, hardware, noise, fresh-machine or GUI validation.

Writer-side Windows sandbox path refusal, a host metadata-type error and the
first worker's quoted-CSV error remain recorded failures. They were resolved for
the host workflow without changing installations, global paths or existing
numerical modules. The failed derivative remains separate from successful ones.
The author's idle process was closed after its frozen handoff; its exit 1 is not
reported as a passed implementation test. Actual host receipts supply the
numerical evidence. Later invalid-gate/profile guards were checked separately
without rebasing those receipts or recomputing their valid numerical results.

A finite peak gate must contain at least two samples on the recorded 2 ns grid.
Limits round inward to that grid; invalid gates fail before Julia or output
reservation. Omitting the profile preserves stored settings; explicitly supplying
an empty profile is rejected, never silently treated as omission.
