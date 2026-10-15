# Current handoff

Updated: 2026-10-14. Read this first, then relevant sources only.
Immutable prior handoff: [P3 desktop results](https://github.com/Kunming-CN/END2END_Ge_Simulation/blob/bdea6a97f1c3f12f80fdfeb0d18a5d96bd4f6300/PROGRESS.md).
It links P2 actual acceptance, P1 packaging and permanent scientific history.

## Owner authority

Corrected heartbeat ACTIVE every30minutes; current student-first plan governs.
No extra AI reviewers/audits/debates. Only directly relevant developer checks.
Desktop only, existing remage/SSD/readout/environments. No installs, global/auth
changes, billed API, resets/banked credits or second-computer gate. Inspect real
Git/state/owned locks/processes/terminal before starting; include pvpython.exe.
Never terminate an owner Control or remove its separate server lock.

## P4 shared gamma options implemented and checked

The existing AK02/SAP22 twenty-primary gamma path now takes positive finite energy
in keV and the existing nominal/+5mm anchors. Beam direction remains global[0,-1,0],
timezero, seed26092631. UI edits invalidate Check; config import/export and saved
energy/placement stay separate from next-run controls. Other models/counts/angles
were not enabled. Canonical source assets, model/bias/temperature and locks remain.

New portable_gamma_source_configuration_v1 binds effective energy/placement to the
frozen662keV canonical preset. Explicit new marker streams and native responses
store only nonzero original IDs, retaining full initial/zero/nonzero counts and
original denominator; signed samples, nonzero failures/rejections and nulls remain.
Allzero stream has no eventfile. Unmarked historical662/+5 retains strict old rules.
No per-event gain or physics kernel changed; independent injection remains separate.

Transport reuses the existing compiled exporter without rebuilding. Only the exact
recorded historical Python producer/source map is admitted for its build receipt;
compile inputs, recipe/runtime/binary still checked. Current execution separately
binds updated gamma reader/shared nonzero policy. Original exporter receipt SHA
c4f62196851efe9f80f5f9996d3cf7fe2b29b76aca49b661c5a4963575aec734 unchanged.
Scenario caller now verifies current source_inventory rather than historical build
PINNED. Student packager statically reads that same21-pin map without Python
execution; changed current gamma/probe/nonzero bytes remain rejected.

Relevant checks passed: workflow21+gamma5Python,19pure Julia assertions; existing
workflow Node with new controls/import/saved identities; transport45unaffected
cases plus corrected/affected3checks (includes mocked sparse/allzero run-export-read).
The first transport case exception mismatch was corrected and targeted rechecked.
Known sandbox hardlink/WSL denials retried unchanged with permission. Two package
source/tamper/static-inventory cases passed; candidate169-member closure passed.
No source test claimed real physics; one exact ignored Julia developer test is
intentionally retained in Git and excluded from runtime ZIP.

## Actual bounded source acceptance

.local/runs/student-sap22-gamma-1000-nominal-v1/transport completed exactly20
initial gamma primaries, SAP22/1000keV/nominal global[0,37.073,0.29]mm, fixedseed.
18zero/2nonzero original IDs7/16; normalized eventfile stores2 rows, raw LH5 retains
all20. Every raw primary energy/momentum/time/position and current source marker,
geometry/overlap and stream bindings verified. Actual gamma-request.json retains
2input events and full20/18/2 descriptor; no fabricated zero input.

Measured remage body3.76150s; full radiation check/I/O stage25.67329s, geometry
preparation28.03798s, saved export20.59734s, native-input verification13.38537s.
Available RAM3.56GiB after owned tests exited; acceptance used transport only.
No SSD field/drift/readout execution, physical accuracy/CCE or experiment claim.
This is a CLI source acceptance, not a Control-owned end-to-end run. It has no
workflow run.json/COMPLETE: transport/run.json is authoritative. Do not launch a
fresh full run into it or repeat completed radiation; preserve this actual data.

The first prepare argument was rejected before any geometry/events for an unsafe
request reference; corrected to the existing project-relative interface. No
scientific retry occurred. One compact .local/gamma-options-p4/COMPLETE.json holds
source/retention/check/package evidence and references the real scientific stages.

## Concrete next desktop fix

Old Gamma job e730045b87b94b4dade4b073d3ec60c5 is terminal but its current-code
verification fails, causing the owner Control peer gate to block independent new
runs. This is not a running scientific worker. Besides P4's gamma reader change,
FOUR untouched producer mismatches already existed at pre-P4 Git bdea6a97:
native_li_example.jl, native_response.jl, readout.jl, charge_check.py.
Do not whitelist those older sources, rebase original maps or rerun old science.
Fix only read-only verification/worker-lifetime separation and its reopen state,
using actual process/terminal evidence; retain blocked unverified old downloads and
original error. This one named issue precedes P5; no broad review or recovery scope.

## Retention, publication and remaining work

P2 actual100 SAP22/Cs137/+30deg remains .local/runs/student-sap22-cs137-100-nonzero-v1,
97zero/IDs24/52/54/3accepted; do not repeat or spend unused400 allowance. P3 files,
lazy saved spectra and conditional advanced panels remain accepted. Old scientific
originals/campaigns/models/cache and exact compile/preset/model pins stay unchanged.

Finalize current P4 formal Git ZIP/immutable student-runtime-<SHA> Release, latest
public download hash/embedded commit and clean Git before ready. Keep one ZIP and
compact receipt in .local/student-runtime-p1; no Actions/auth-scope changes. README
and maintained guide updated; generated docs awaits normal P5 publication.
After the named desktop gate fix, P5 only actual saved-site issues/usable labelled
analysis. No automatic PSD3 demo/ML without independent adequate labels. November
spectra/I-V/C-V require complete owner inputs, blocking only P6.
