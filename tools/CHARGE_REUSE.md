# Saved-charge inspection (M4a)

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
calibrated Li CCE, experimental agreement and M4b replay remain out of scope.

Tests use explicit synthetic storage fixtures, not physics acceptance:

```powershell
python -B tools/test_charge_check.py --evidence .local/charge-reuse-v1/implementation/NEW_TEST_DIRECTORY
```
