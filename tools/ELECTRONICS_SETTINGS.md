# Saved electronics settings

From Windows PowerShell in the repository root:

```powershell
.\Run.cmd settings
.\Run.cmd settings -View advanced
.\Run.cmd settings show
.\Run.cmd settings show -View advanced -Json
.\Run.cmd settings check
.\Run.cmd settings save -SaveName my-electronics
.\Run.cmd settings show -SettingsFile .local/electronics-profiles/my-electronics.json
.\Run.cmd settings check -SettingsFile .local/electronics-profiles/my-electronics.json
.\Run.cmd settings compare -SettingsFile simulation/native_readout_profile.json -CompareTo .local/electronics-profiles/my-electronics.json -Json
```

`settings` prompts for simple/advanced view, then values and a new save name.
Press Enter to retain a value; a blank save name cancels. Values use JSON syntax:
numbers, `null` for an optional gate, and quoted strings for the peak policy.
Simple edits preserve every advanced and inherited value. The main menu also
offers electronics settings. No settings command launches a calculation.

For noninteractive edits, `-SetJson` is a partial object containing exact setting
names. `save` and `check` accept it; `check` validates the proposed edits without
saving. Because CMD and Windows PowerShell 5 have different native argument
quoting rules, pass JSON directly to the PowerShell script when editing:

```powershell
& .\tools\scenario_cli.ps1 settings check -SetJson '{"shaping_tau_us":0.8,"gain":10}' -Json
& .\tools\scenario_cli.ps1 settings save -SaveName slower -SetJson '{"shaping_tau_us":0.8,"gain":10}'
& .\tools\scenario_cli.ps1 settings save -SaveName gated -View advanced -SetJson '{"peak_gate_start_ns":0,"peak_gate_end_ns":90000}'
```

Script execution must be allowed for direct script invocation. The `Run.cmd`
wrapper already uses a process-local execution-policy bypass; it is suitable
for interactive editing and all examples above without inline JSON. No machine
policy change or package installation is required by this feature.

## Settings and units

| Setting | Default | Meaning |
| --- | --- | --- |
| `shaping_tau_us` | 0.5 µs | Analog shaping time constant |
| `gain` | 20 V/V | Shaper voltage gain |
| `threshold_V` | 0.001 V | Inclusive peak acceptance threshold |
| `adc_bits` | 14 bits | Peak ADC, integer 2–24 |
| `adc_full_scale_V` | 10 V | Upper ADC range; saturation at or above this value |
| `feedback_capacitance_pF` | 0.6 pF | Preamplifier feedback capacitance |
| `feedback_tau_us` | 50 µs | Preamplifier decay time constant |
| `pole_zero_tau_us` | 50 µs | Pole-zero compensation time constant |
| `peak_policy` | `signed_input_positive_peak` | Or `legacy_reject_negative_input`; signals are never rectified |
| `peak_gate_start_ns` | `null` | Optional gate start, relative to the readout trace origin |
| `peak_gate_end_ns` | `null` | Optional gate end, relative to the readout trace origin |

The first five settings form the simple view; advanced exposes all eleven and
prints the complete resolved configuration. Feedback and pole-zero settings are
independent: changing one does not silently retune the other. Both gate bounds
must be null, or finite with `0 <= start < end <= 99998 ns`. This last limit is
the existing launcher's conservative isolated-window constraint (100000 ns,
2 ns analog numerical grid); the generic Julia schema also supports other
window contexts. The numerical grid is **not waveform ADC sampling**. There is
no sampling-frequency control.

Gate times are measured from the **readout trace origin**. In the LBNL Cs137
chain this is each pulse group's `origin_time_ns`, not necessarily the initial
radioactive primary's time. The one-primary legacy examples use their own primary
origin. This label changes no recorded deposition times or numerical clocks.

Capacitance, time constants, gain and range must be finite and positive;
`0 < threshold < adc_full_scale_V`. Booleans are not numbers, and ADC bits must
be a JSON integer, not `14.0`. Unknown/missing keys, duplicate or case-aliased
keys, arrays, unexpected types/kinds, NaN/infinity, unsafe paths and reparse paths
are rejected. Paths must be project-relative, with simple components and no
spaces, traversal, device names, alternate streams or wildcards.
Symbolic links and junctions in any path component are rejected. Ordinary NTFS
hard links (also used transiently by sync software) are read and hash-checked;
the editor never modifies an input or replaces a saved output name.

All commands use the same PowerShell validation path, including the existing
saved-run profile validator. Checks are configuration preflight, not execution
readiness: no propagator, injection calibration or pulse simulation is run.
Runtime window/sample limits and numerical conditioning still need testing with
the actual child configuration before execution can be supported.

## Saved bundle and provenance

`save` creates `.local/electronics-profiles/NAME.json`, never overwriting an
existing name. It contains a complete schema-2 `profile`, independently resolved
`configuration`, deterministic `physics_sha256`, and schema/revision-1 save
metadata. The outer object is a settings bundle, **not a direct Julia profile
argument**. The configuration contains the frozen defaults, all profile overrides,
schema 2, and a null expected census; schema 2 removes `max_total_samples`.
No run census is invented. Inherited limits, trace settings and the independent
500 keV injection calibration setting are visible but not editable here.
The saved profile name is the new save name; the original input identity remains
in provenance. Renaming does not change the physics hash.

Provenance records input path/hash/schema/kind, default path/hash/schema and
source hashes. Default profile and configuration hashes are pinned. Checking a
save checks these bindings and independently reconstructs its configuration;
changing only the stored resolved configuration and recomputing its physics hash
cannot bypass this check. Hashes detect inconsistency, not malicious forgery.
Keep the recorded input available and unchanged. Source changes can make a save
incompatible; they do not justify editing an old receipt. Each save has a new
name and revision 1; editing from a save records that save as its input.

The physics hash includes the full effective configuration, excluding display
name and save metadata. Equivalent numeric spellings and repeated saves produce
the same hash; changing an effective setting changes it. It is a configuration
identity, not a simulation result or calibration certificate.

`show`, `check` and `compare` use PowerShell file reads only: no Julia, WSL,
installation, locks, output folders, or receipt edits. `save` validates first,
then stages one file and atomically publishes it without replacement. An IO
failure can leave a `.pending-*` evidence file. Invalid configuration creates no
output. JSON mode returns one object; validation failures are nonzero (normally
2; PowerShell parameter-binding failures may return 1).

## Execution, pilots and reuse boundary

This milestone supports editing, persistence and preflight. Custom-profile run
selection is deliberately unavailable. `-ElectronicsProfile` is rejected before
runtime checks or writes, including on resume/dry-run. The campaign driver still
uses its original canonical profile and original source inventories. A canonical
pilot cannot authorize different electronics. Custom execution requires a later
change binding the selected profile, child argument, copied inputs, independent
configuration checks, run receipts and matching pilot. No new-run or positive
custom-profile execution is claimed here.

Resume uses recorded configuration and rejects explicit preset, detector, seed,
pilot and scenario overrides, rather than silently ignoring them. No old receipt
is changed by settings comparison.
The interactive main menu also rejects these command-line overrides; choose
its prompted values or use an explicit `run` command.

Comparison always separates three claims:

- **Dependency-based theoretical reuse:** electronics-only changes do not require
  new radiation, fields or charge, provided compatible complete charge waveforms,
  identities, timing, units and producer settings are available.
- **Artifact-verified supported reuse:** `NOT_CHECKED` by settings comparison.
  `Run.cmd inspect` can check terminal saved campaigns for unchanged canonical
  settings. Configuration equality alone verifies no scientific artifacts.
- **Electronics-only replay:** `NOT_IMPLEMENTED`. The coupled response driver does
  not automatically reuse charge. A comparison never starts either configuration.

Threshold changes affect acceptance, never the event census. Every independently
executed electronics configuration requires injection calibration, not an
event-by-event gain fitted to truth energy. Synthetic electronics are not an
experimental resolution or charge-collection validation.

## Additional preflight limits

Unknown command-line flags and excess positional arguments are rejected before
settings or run dispatch. A misspelled `-SettingsFile` must never check the default
profile silently. Every saved ancestor is checked recursively against its own
profile, resolved configuration, source and input bindings. Changed or missing
ancestors invalidate derived saves. Cycles are rejected; a chain may contain at
most 16 input files, counting the current save and original raw profile. Saving
beyond that bound fails without creating a file. All read ancestor hashes are
checked again before save or comparison returns. Original receipts are not rebased.

Structural validity is not numerical readiness. For example, a 0--1 ns peak gate
contains only one point on the 2 ns grid, and 50 us shaping requests 500001
calibration samples against the inherited 500000 limit. These are structurally
valid settings, but are not executable-ready configurations. Runtime calibration,
sample/window feasibility and numerical conditioning remain a later execution gate.
