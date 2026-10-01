# Saved electronics settings

Current workflow selection belongs to the maintained [setup & run guide](https://kunming-cn.github.io/END2END_Ge_Simulation/guide.html#local-routes).
Settings checks remain read-only. A custom generic run starts its normal upstream
calculation; compatible saved-charge replay is a separate delivered command in
[CHARGE_REUSE.md](CHARGE_REUSE.md). Bounded private-input native-readout has its
own fixed profile and does not accept electronics overrides.

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
NEW execution additionally checks sample/window feasibility before runtime work.
This arithmetic check is not a propagator or successful injection-calibration test.

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

Saved custom electronics are implemented for NEW AK02/SAP22 LBNL runs:

```powershell
.\Run.cmd run -Name custom-smoke -Preset smoke -Detector AK02 -ElectronicsProfile .local/electronics-profiles/my-electronics.json
.\Run.cmd run -Name custom-pilot -Preset demo -ElectronicsProfile .local/electronics-profiles/my-electronics.json
.\Run.cmd run -Name custom-larger -Preset larger -Pilot .local/runs/custom-pilot -ElectronicsProfile .local/electronics-profiles/my-electronics.json
.\Run.cmd inspect -Name custom-pilot -Json
.\Run.cmd resume -Name custom-pilot -DryRun
.\Run.cmd resume -Name custom-pilot
```

These commands perform the normal upstream radiation, field, native charge and
electronics calculation. They do not automatically reuse old fields or charge.
The named presets retain 20/500/10000 initial decays per selected detector.
Omitting `-ElectronicsProfile` preserves the canonical child defaults.
`-DryRun` creates neither a run nor a profile; a NEW dry run still probes installed
runtime readiness after read-only configuration and pilot validation.

The shared `electronics_execution.ps1` validates the saved bundle with the strict
`Get-ESInput` ancestry contract before runtime probes or writes. Only a NEW run
creates `electronics/profile.json`, a standalone schema-2 profile passed by its
exact project-relative path to the actual `native_response_guarded.jl --profile`
argument. `electronics/inputs/` mirrors the small set of exact bundle/ancestor/
default/settings-source bytes at their original relative names. Original bundle
provenance is retained without rewriting it; copied scripts are data, never loaded.
The parent receipt binds the input identity, exact copy inventory, profile bytes,
settings-source hashes, full effective configuration, configuration hash and
arithmetic feasibility. Campaign source inventories distinguish custom/canonical.

Inspection/resume independently reconstruct from those copies and compare the
standalone profile, parent configuration, child receipt, child profile copies,
resolved configuration and event census. Child configuration may differ from the
selected effective configuration only in `expected_primary_count`. Hash-only
resealing cannot bypass the independent parameter comparison. Original saved
bundles/ancestors are no longer needed after successful copying; current compatible
project sources, models and ordinary recorded transport dependencies remain required.
Missing/corrupt copies block reuse; the launcher never reconstructs them from current
UI selection. Source-incompatible historical receipts remain untouched. This revision
changes settings-source hashes, so older saves may fail compatibility checks; do not
edit/rebase their provenance to bypass that check.

A 10000/model request requires a completed clean 500/model pilot with positive
native integration for every requested detector. The verifier first validates the
pilot's own saved binding and child artifacts, then compares the full effective
electronics to the request and checks compute dependencies. Display names and copy
paths do not define physics equality. A canonical pilot cannot authorize changed
electronics. Historical orchestration revisions remain recorded; supported legacy
unguarded pilot validation stays explicitly labelled.
Legacy unguarded verification does not authorize a NEW guarded campaign request;
that request requires a guarded pilot with the current compute dependencies.

Evidence is bounded, source-only, mocked public-CLI/driver execution, not
uninstrumented full-chain acceptance. The test clone intercepts runtime readiness,
child processes and disk-capacity reporting; it runs the actual dispatch, argument
construction, snapshot, receipt and validation code. The fixture's synthetic receipts
are not scientific results. No production simulation or electronics rerun is part of
this implementation milestone; numerical injection acceptance is a separate check.

Resume uses recorded configuration and rejects explicit preset, detector, seed,
pilot, scenario and electronics-profile overrides, including explicit defaults.
The underlying driver also rejects explicit resume configuration overrides and
loads the recorded values itself. No old receipt
is changed by settings comparison.
The interactive main menu also rejects these command-line overrides; choose
its prompted values or use an explicit `run` command.

Comparison always separates three claims:

- **Dependency-based theoretical reuse:** electronics-only changes do not require
  new radiation, fields or charge, provided compatible complete charge waveforms,
  identities, timing, units and producer settings are available.
- **Artifact-verified supported reuse:** `NOT_CHECKED` by settings comparison.
  `Run.cmd inspect` checks terminal saved campaigns using their recorded canonical
  or custom binding. Configuration equality alone verifies no scientific artifacts.
- **Automatic electronics replay in settings comparison/coupled run:** the
  comparison retains its `NOT_IMPLEMENTED` status. The coupled response driver
  does not automatically reuse charge. A comparison never starts either
  configuration. The separate `replay-readout` command supports compatible
  saved-charge derivatives under [CHARGE_REUSE.md](CHARGE_REUSE.md).

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
valid settings, but NEW execution rejects them before runtime work or allocation.
Execution fixes DT=2 ns and the half-open 100000 ns window (last sample 99998 ns).
A finite gate needs at least two grid points. Injection calibration requires
`n = ceil(20000 * shaping_tau_us / 2) + 1`, with `3 <= n <= 500000` and
`(n-1)*2 <= max_window_ns`. This does not guarantee numerical conditioning or
successful calibration; the unchanged native child performs the actual independent
injection calibration, with one gain across events.

## Bounded uninstrumented acceptance

One new custom-profile AK02 demo ran through the real Run.cmd path without child
stubs or field-cache injection:500 initial Cs137 decays, 4 groups,
4 accepted, 0 electronics rejects and 0 native failures.
The actual child --profile path, snapshot bytes and all effective parameters were
independently verified. This establishes that selected configuration on the existing
computer only; it is not all-model or fresh-machine reproduction, experimental
validation, or electronics-only replay. The preserved original campaigns were not
recomputed. Exact local evidence is in .local/electronics-execution-v1/.
