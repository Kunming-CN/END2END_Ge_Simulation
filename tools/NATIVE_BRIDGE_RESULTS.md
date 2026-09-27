# Saved HDF5 to native response: representative pilot

The bridge and bounded pilot are implemented. This is NOT a completed million-event
SSD response or a calibrated spectrum. No Geant4 transport was rerun and no original
million-decay data, old baseline, model or existing native helper was modified.

## Actual execution

Final input: `.local/native-bridge-pilot/contracts-v3/`. Final native result:
`.local/native-bridge-pilot/pilot-v2/`. The independent process observer recorded
exit 0. Field solve, native drift, electronics and export took 133.134 seconds,
excluding module startup/preflight. One field solve per detector was reused.
The field fingerprints, injection calibration and profile match the preserved
10k baseline exactly. Settings remain 77 K, +500/+700 V, 16 parcels, 2 ns,
10 us drift cap, diffusion on, zero-field termination off, and 100 us readout windows.

| New million-sample selection | AK02 | SAP22 |
|---|---:|---:|
| Selected initial primaries | 10 | 13 |
| Selected zero-Ge primaries | 1 | 1 |
| Positive pulse groups | 9 | 13 |
| Native response succeeded | 9 | 13 |
| Peak ADC accepted | 9 | 13 |
| Native failures / electronics rejects | 0 / 0 | 0 / 0 |
| Groups with at least one capped trajectory | 9 | 0 |
| Groups with a stopped-without-contact flag | 0 | 1 |

SAP22 primary 965630 retains two separate groups. All 20 saved representative
primaries, two actual zeros and this extra two-group primary are accounted for.
The two old diagnostic cases below are additional, explicitly separate namespaces.
Nonselected response is unknown, not zero. The full population/zero ledger remains intact.

## Response limitations and historical controls

ADC acceptance is not full charge collection. For example, new AK02 primary2594
has 661.657283 keV deposited, 661.604092 keV induced-equivalent charge and a
662.026196 keV ADC result. Primary3950 has the same deposited energy but only
59.169117 keV induced-equivalent charge and 47.954861 keV reconstructed energy.
Those are preserved provisional outputs, not measured accuracy or an identified
physical mechanism. The caps and negative/endpoint flags have not been cleared.

Old AK02 primary8432 reproduces its noncontact-exterior native failure. Old SAP22
primary8413 instead returned a finite response in the mixed selected pilot:
26.067190 keV induced-equivalent charge, accepted ADC, and 251 stopped-without-contact
endpoint reports. In a separate fresh process, the SAME isolated SAP22 case was
then repeated three times; all three reproduced the original exterior-endpoint
ArgumentError. Exact saved rows, group origins, seed identities, field hashes,
profile/calibration and recorded environment match. The discrepancy is therefore
unresolved cross-context reproducibility, NOT a repair or permission to delete the
old failure. No root cause has been established. Evidence: sap22-repeat-v1/report.json
and repeat-exit.json under the local pilot root. No global Li scan was launched.

## Verified delivery and next boundary

13 Python bridge tests, 87 Julia assertions (including output reservation),
3 rehashed units/metadata cases, 4 artifact/failure-ledger mutation tests and
4 renderer tests passed. An early output-directory ordering failure occurred
before any field solve, was preserved, and was fixed in the new adapter only.
The temporary PowerShell wrapper's null exit-code receipt was not treated as
success: a live process observer retained the handle and independently recorded
numeric exit0. The permanent Python launcher has numeric return-code/terminal
checks and tested failure/stall handling; use it rather than that old local wrapper.

The local report is `.local/native-bridge-pilot/report-v2/comparison.html`.
It shows all selected pulse results and expandable charge/current/preamp/shaper
plots. Full signed charge CSVs and endpoint/failure records remain in pilot-v2;
old source and intermediate diagnostic evidence are retained. The source tools
and this summary are versioned; this pilot report is local, not a replacement
for the published million-event deposition spectrum.

Final preservation audit rechecked 1,400 campaign files, 20 original computation
sources and nine saved-analysis artifacts: zero original modifications/deletions.
Same-computer preservation is not an off-device backup.

Before a long native batch, isolate the concrete SAP22 execution-context discrepancy
and quantify the representative AK02 low-collection/cap effect with bounded tests.
Then add resumable native processing using retained inputs and exact cached field
state. Do not regenerate radiation, redo all prior analyses, or make global Li/PDE
convergence an unrelated feature gate. No full-million native job is running.

Two focused read-only reviewers completed reciprocal closure after inspecting the
fixes and final receipts. They accepted this limited engineering milestone while
explicitly retaining the SAP22 cross-context reproducibility limitation; neither
review is experimental certification or authorization of full native production.
