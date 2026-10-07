# Current handoff

Updated: 2026-10-07 UTC. Read this before starting work.
The complete prior source, UI and planning history is preserved
[at verified f274f96](https://github.com/Kunming-CN/END2END_Ge_Simulation/blob/f274f96a5c5449cf0183ef783118805c1b8c8e96/PROGRESS.md).

## Accepted ten-model engineering milestone

Ten detector configurations now use the existing LBNL cryostat through Control:
the original AK02, SAP22, GeRC02 Li50min, KMRC01 candidate and SAP18 ring scenario,
plus AK01, SAP16, SAP17, Bipolar_reference_3D and KL01_3D through one common route.
All 17 original models remain browsable. BEGe_GD32B_reference, BEGe_reference,
COAX_ANG2_reference, ICPC_48A_reference, ICPC_large_reference, PPC_PONaMa1_reference
and GeGI_3D require a future larger cryostat because of their actual dimensions;
GeGI also intersects the fixed support. Their canonical inputs are complete.
No replacement world, model geometry, temperature, contact or bias was introduced.

Cs137, Am241 and Ba133 share the existing source-selection workflow at the nominal
anchor, with 20/500 initial nuclei. Gamma retains its original fixed-20 AK02/SAP22
contract. Co60 remains held by its unchanged source gate. Source/model software
factorization does not mean thirty actual source/model physics acceptances.

This manual round starts from f274f96a5c5449cf0183ef783118805c1b8c8e96 under the
owned coordinator lock `student-batches-v1-root`. Five new fixed science cases
completed; physics/electronics, integrity and the new independent third AI FINAL
reviews accept the integrated engineering milestone. The saved-site guide and
navigation refresh passed its local build and complete check.
Final Git/live-publication/process/lock outcomes are authoritative only in
`.local/student-detector-coverage-v1/COMPLETE.json`, `.local/autonomy/state.json`
and actual Git/process state. The root writes terminal COMPLETE after those
operations actually finish; this handoff does not infer their completion.
Do not repeat completed science.

## Five completed fixed cases

The preselected normal public CLI Check → Run → Inspect route completed five
distinct Cs137 cases, each with 500 initial nuclei, sequentially with two Julia
threads and one remage thread. Each had one independent 500 keV injection.
There was no scientific retry, seed/count change, outcome tuning or source-input
change. Each case retains original IDs 0–499, exact raw truth and every zero event.

| Model | Accepted groups | Zero-deposit primaries | Native failures | Readout rejects | Public Run wall time (s) |
|---|---:|---:|---:|---:|---:|
| AK01 | 3 | 496 | 0 | 1 | 219.231 |
| SAP16 | 1 | 497 | 0 | 2 | 176.966 |
| SAP17 | 1 | 499 | 0 | 0 | 153.829 |
| Bipolar_reference_3D | 2 | 498 | 0 | 0 | 149.596 |
| KL01_3D | 2 | 495 | 3 | 0 | 146.576 |

Total: 2,500 initial primaries, 2,485 zero-deposit primaries and 15 pulse groups:
9 accepted, 3 native-failed and 3 readout-rejected; no saturation. KL01's
NativeBoundaryStall events 124, 236 and 367 retain error/raw truth and null unknown
charge/readout. AK01 event480 and SAP16 events151/311 remain below-threshold
readout rejections. KL01 is `completed_with_native_failures`, not a clean result.

Measured totals are 90.661 s potential solves, 213.163 s native stages,
846.197 s public Run and 1,102.779 s public Check/Run/Inspect. The five added paths
use explicit Float64 initial-grid parameters 0.25/2 mm; original five paths remain
unchanged. The earlier spacing extrapolation was disproved as an upper bound:
AK01's actual electric grid is 162×1×124. Maximum measured whole-process peak RSS
is 1,209,978,880 bytes; this is not field-only memory or parallel-solve headroom.
These small engineering cases establish neither grid/PDE/CCE convergence nor
physical resolution, detector efficiency, surveyed placement or experimental agreement.

## Verification and evidence

Recorded software checks passed: core48, native-model164, native-request15,
UI-controller20, protected-HTTP24, setup2 and JavaScript contracts. All five actual
Geant4/SSD geometry checks passed. Legacy saved inspections preserve prior counts.
Real Chrome selected all five added models with Am241 and displayed all seven
dimension blockers. After the existing saved-only Gamma Verify action, AK01/Ba133
Check enabled Run; changing to Cs137 invalidated it. No UI Run, Download or Export
was clicked. UI-BROWSER-CHECKS.json records this selection/Check acceptance; the
owned browser tab and server were closed. The root records publication closure.

Acceptance, exact per-case identities/hashes, timing, failure records and source
preservation: `.local/student-batches-v1/model-coverage/acceptance-v1/COMPLETE.json`
(SHA256 `4c47b8b2ea9f8e2fb4947ec46335549f67fa1ef45e4c471ba782df15413770a5`).
UI/setup freeze: `.local/student-batches-v1/ui/SOURCE-FREEZE.json`.
Current integrated AI reviews: `.local/student-detector-coverage-v1/reviews/`.
Physics/electronics and integrity FINAL accept the integrated milestone with
I-001's exact saved-response settings binding and P-R001's resource-wording
correction closed. The independent third FINAL also accepts the validated
presentation snapshot, final guide/source freeze and focused tests. Local build
and publication are separate delivery checks. Original sources, science and
unique failures remain preserved.
AI engineering review is not human student or experimental certification.

## Delivery order and retained state

`tools/site_guide.html` remains the single setup authority, including both explicit
exporter builds in the existing pinned environment. README stays a short entry.
Public guide/navigation refresh uses `build_site.py --restructure`, saved-only
checks and a live `check_site.py --url` after deployment; generated docs are never
edited by hand. One tracked `scenarios/catalog-presentation.json` snapshot
validates exact canonical-model, nominal-assembly and unchanged science-bound
registry hashes for public display; the backend independently checks runtime
admission. Focused publication checks passed 75 tests plus the final guide check.
`docs/` was refreshed once through `--restructure` and the full local checker
passed. `.local/student-batches-v1/docs/SAVED-PUBLICATION-BUILD.json` binds its
manifest/guide hashes; live publication and Git/lock closure use the terminal
authorities above.

M5 remains closed; M15a preview remains accepted. M15b/M15c unfinished batch WIP is
preserved in `.local/student-batches-v1/wip/` and paused, not a model-coverage
prerequisite. Its exact four-file baseline restore is recorded in RESTORED.json.
M8/M9 fresh-machine/student setup acceptance remains deferred until the owner's
second computer. Automatic heartbeat remains PAUSED. Future larger cryostat,
source angles and extra models are outside this milestone. Next work follows
the owner's priority; no new science, installation experiment or full review
cycle is justified by these documentation changes.
