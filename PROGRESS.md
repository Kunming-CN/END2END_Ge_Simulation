# Current handoff

## Active takeover — 2026-10-17

Sole supervisor:01a14bca-3953-7c13-80a1-687a9a571455; ownergegi-10m-root,
.local/autonomy/gegi-10m.lock. Existing automationautomation is ACTIVE every30min
and targets this window; inspect actual workers/state before any continuation.
The current authorization and frozen comparison design are in the active section
of tools/NEXT_DEVELOPMENT_PLAN.md. No extra reviewers, resets or old-science reruns.

Website milestone published at59f9d008c4ae: dedicated native GeGI cryostat3D,
preview/section, correct compatibility and shared simplified navigation. Exact
live check passed709files plus all8assemblyassets; desktop navigation, rotation,
zoom and section verified. No numerical reruns. Student guide releasestudent-runtime-
59f9d008c4ae has177verified members,824958bytes; actual public ZIPsha256
758d9cfda79069fbd785365ca871b7b1b6d532fc71b3ac8faeb6414359d53d90.
Evidence: .local/gegi-website/live-check.json and
.local/student-runtime-p1/COMPLETE.json. Historical result URLs and LBNL
compatibility flags are preserved.

Independent simulated pixel-depth calibration complete:216/256available,40strictly
unavailable;175fixed offset/depth diagnostics, exact existing field cache only.
Protocol-only reply failure was repaired after saved completion; retained valid
calibration was reused. Four500-initial gamma-left/right,Cs137/Co60 pilots complete:
115nonzero,0native failures,2readout rejections,2imaging accepted. Acceptance and
exact replay passed; not experimental validation or a separation demonstration.
Measured compressed projection76.14GB;1.5x allowance+temporary+20GiB reserve
requires136.08GB versus about155GBfree. No formal10M primaries launched yet.
Actual 400-initial stop/resume qualification passed: first 100 sealed/stopped,
remaining 300 resumed; first-chunk hashes and timestamps unchanged. Saved-data
analysis passed (26 nonzero, 25 accepted readouts, 0 imaging; inconclusive).
An explicit analysis-only revision preserves all 38 producer pins after repairing
terminal native-failure handling; no science rerun.
Authoritative evidence:.local/gegi-10m/{preparation,acceptance,lifecycle}.json;
qualification/progress.json and COMPLETE.json take precedence over this text.
Current runtime release: student-runtime-429ebcd78e69, actual ZIP 829262 bytes,
SHA256 70c990f3f0cfeeb2f49aa38abd1093b16b371d135e62067d7feb61be000fbb37.
Next: freeze total 10M and launch detached;
healthy30min monitoring must read compact state and exit immediately. Final maps
and publication remain after formal completion, not a reason to hold workers idle.

## Prior delivered milestone (retained evidence)

Updated: 2026-10-17. GeGI-only cryostat and multichannel Compton workflow are
implemented, tested and published in GeSignal Control. Prior P0-P5 remain delivered; their
handoff is preserved at commit666947fa22d879eae69252d25ec91345d24665cd.

## Current delivery

Functional delivery is complete. Implementation and scientific workers are finished;
no extra AI review agents were used. .local/gegi-integration/delivery.json records
final Git/publication/ownership closure. Inspect it and actual state before any
continuation. Never repeat completed physics because of a chat interruption.

The dedicated gegi_cryostat_v1 accepts only frozen GeGI_3D. Measured front layers
are1.6mm and0.8mm with8.1mm crystal-to-external-front distance. The owner accepted
explicit nominal side/rear dimensions and gap split; alloys use pure Al. Missing
holders/cold finger and full hardware geometry remain declared approximations.
Private manuals/slides stay private. Canonical92.3K/-879V and0V inputs are unchanged.

The shared lifecycle now handles configurable gamma energy/position, check/run/
stop/resume,34-electrode signed signals, independent readout calibration, channel
plots, strip matching, candidate Compton cones and directional backprojection.
X/Y energies are not double counted. Depth uses an independent simulated central
pixel timing table; no measured per-pixel calibration, range or resolution claim.
Both kinematically valid orders are retained without source-direction selection.

## Actual evidence

.local/runs/gegi-100-pilot-v1:100initial/100zero/0nonzero. Actual stage-boundary
stop/resume reused radiation. Empty results contain no fabricated waveforms.
.local/runs/gegi-5000-imaging-v1:completed,5000initial/4958zero/42nonzero,
874positive Ge steps; seed26101702,662keV isotropic source at[30,0,100]mm.
All42 events retain34 channels;0native failures,2native endpoint flags,38readout
accepted and4readout rejected. Imaging accepts1event(ID2950), rejects41 with
reasons, produces1cone. Image integral is1.0. One cone is not source localization.

The exact existing34-potential Float32 native field cache was reused (hashf75280e7
f21b1a1a06c2a6623aed62873065ca72db02bb1f93a61b9b853b90e8). Fresh-field policy
usesFloat64. Neither a fresh solve nor grid/experimental validation is claimed.
A transient permission error replacing a large progress file was fixed with
bounded atomic-write retries and compact progress.20completed event/checkpoint
hashes and all radiation bytes were reused unchanged. The original failure,
original producer, and explicit storage-only rebind remain in
.local/gegi-integration/storage-failure-original; no new primaries during recovery.

Relevant checks:21shared workflow,6imaging,4protected Control,JS regressions,
5software-package,8saved-publication,33site,18native helper+5model/request and
20checkpoint checks passed. Native overlaps:8volumes/10000samples each passed.
Actual browser verified compatible selection, blocked mismatches, checked source,
empty results, original nonzero IDs,34channel switching and real cone/map display.
CLI-data display used a labelled temporary read-only fixture, not forged UI ownership.

## Two-position acceptance and publication

The two-position source-separation test completed serially with 5000 primaries
each at [-40,0,40] and [40,0,40] mm, 662 keV, seeds 26101703/26101704.
gegi-source-left-v1: 4747 zero / 253 nonzero / 1 imaging accepted (ambiguous).
gegi-source-right-v1: 4769 zero / 231 nonzero / 4 imaging accepted (3 ambiguous).
Both have zero native failures; native endpoint flags are 7 and 4 respectively.
Native response took 158.139 s and 119.436 s; response plus imaging took 203.039 s
and 161.989 s. These are computation times, not development/publication wall time.
Only 5 accepted events cannot establish reliable spatial separation. Do not extend
the campaign or change seeds to manufacture success. Exact receipts, full sparse
records and original radiation remain in these roots and delivery.json.
A real transient-recrossing defect was identified in the old2950Y28charge:
first50%crossing22.24ns,last79.33ns. New native source uses the last upward
crossing for both independent calibration and events;18targeted tests passed.
Old100/5000outputs remain unchanged. Website comparison uses cone vertices
on explicit assumed z=40mm plane, plus directional maps; no recovered range claim.
The mixed plane integral is5.0 from9weighted candidate cones. All484nonzero IDs
are qualified by source run; all10000initial primaries remain the denominator.


The generated website passed local validation, actual browser display and exact
live verification of706files. Its
1691 earlier files remain byte-identical; only guide/GeGI entry changed and four
GeGI result files were added. Build b8767e91ba1538756293c4c7cee3f63521d9c215f5a57604829e98a2c55a756d.
Student release student-runtime-6040230dc3ff is latest, built from formal commit
6040230dc3ffe68e06ae2e46151e4d68d4c6771a. Its actual downloaded824755-byte ZIP
matches SHA256 2b4263461810ec83a06583801ae353fc1f34355ecc0d9db3fed3d834d3d1e09e
and PACKAGE.json source identity. It contains176source files, no saved test data,
publication tools or field caches. Keep only the current ZIP/compact receipt.
The GeGI page is https://kunming-cn.github.io/END2END_Ge_Simulation/examples/gegi/index.html.
Owned temporary servers and browser tabs are closed; disposable reference renders,
browser fixtures and publication candidates were removed. Scientific data and
unique failures remain protected by tools/DATA_RETENTION.md.

Original campaigns/models are unchanged. Further mechanical fidelity and hardware
calibration require actual dimensions, channel mapping and measured calibration.
No independent executable work remains. Leave autonomy ready and skip unchanged
wakeups. No automatic larger campaign, PSD3, phone work, new environment or reviews.
