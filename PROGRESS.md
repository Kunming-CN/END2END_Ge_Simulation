# Current handoff

## Active GeGI 10M campaign — 2026-10-18

The formal full-chain campaign is RUNNING after two explicit native-failure
recoveries in .local/gegi-10m/campaign. Actual progress/process identities prevail.
Current plan SHA256:3e28f5a40f2be830d775dad01994aed694bacffb84408c1bb88acc7c6c7227f6.
Current producer commit:619093442162ecd3904a63bc54935e07c93a87c2.
Supervisor PID36236, creation identity134367559201803262; Julia PID20816,
identity134367559221787871. Both actual identities verified after detached launch.
Current spool from plan.recovery: native-spool-recovery-843b1271056a.

This chat01a14bca-3953-7c13-80a1-687a9a571455 owns .local/autonomy/gegi-10m.lock
as gegi-10m-root. Automation automation is verified ACTIVE every30min targeting
this chat/root and current plan. Read compact state; healthy checks exit quietly.
A sandbox identity unknown is not a dead worker; use authorized process access
when necessary. No competing supervisor, repeated agents, long polling or resets.
Retain this lock/monitor until final delivery, not merely until physics completes.

1000chunks total10M:2M gamma-left,2M gamma-right,3M Cs137-left,3M Co60-right.
Keep photon/initial-decay denominators separate; preparation2400 is excluded.
Coordinates, fixed seeds/cuts and metrics are in NEXT_DEVELOPMENT_PLAN. Mixtures
are independent linear sums without inter-source pileup or a true3D claim.
Five sealed chunks currently account for50,000initial gamma-left photons (0.5%).
At00:13:57UTC the sixth chunk had129stored groups through originalID2656 after
resume; partial response counts are not additional sealed initial completion.

Recovery1: original contact-start failure1188/group0 and original producers remain
in .local/gegi-10m/failure-contact-v1; recovery-contact-v1/application.json binds
its identity migration. All58prior event blobs/2012arrays were preserved. Do not
reapply it. Original plan/source_commit remain historical in the revision chain.
Recovery2: chunk5 failed on Invalid native signed charge at23:50UTC. Preserve
.local/gegi-10m/failure-native-charge-v1, including original error, full21rows,
truth368.52480403127805keV and the single bounded diagnostic. Its original failing
waveform invariant is unobservable. The diagnostic instead hit the existing
outside-crystal endpoint guard; it did not reproduce the exact original error or
fix underlying SSD numerical behavior. Cache reused;38.867s process wall,2.433GB
peak, no new radiation/field solve. No further diagnostic retry is queued.

Recovery2 is applied at .local/gegi-10m/recovery-native-charge-v1/application.json.
Its execution-check.json verifies all5sealed chunks retain exact hashes/mtimes,
all40partial event blobs/1392arrays and17transport files retain original bytes.
Original event801/group0 is imported as native_failed/null, drift_replayed:false;
its original error is retained without another drift attempt. Both readout and
imaging reject it. Future exact Invalid native signed charge ArgumentErrors use
policyv3; other unknown errors still abort. No seeds, cuts, calibration, physical
inputs or original native helper changed. Different source/recipe versions remain
explicit. Existing incomplete-native readout/imaging rejection remains unchanged.
Validation:74targeted Julia assertions and64Python campaign/recovery/adapter/
analysis/publication tests passed. No extra reviewers. The two-generation helper
is bounded to these exact failures/preserved prefix, not arbitrary rebaselining.

Website milestone59f9d008c4ae is live: actual GeGI cryostat3D, preview/section,
correct compatibility and simplified Results/Detectors/Assemblies/Run/Methods
navigation.709live files plus all8assembly assets and desktop rotation/zoom/section
were verified. Historical URLs/science and LBNL flags remain. Earlier33site tests,
8focused checks and1705local files passed; no website artifact changed here.
Current student-runtime-429ebcd78e69 actual tag/latest ZIP bytes are verified:
829262bytes,177members,SHA256
70c990f3f0cfeeb2f49aa38abd1093b16b371d135e62067d7feb61be000fbb37.
No packaged source changed, so this maintainer-only repair needs no new ZIP.

Preparation passed: independent simulated depth table216available/40unavailable,
175fixed diagnostics. Four500pilots:115nonzero,0native failures,2readout rejections,
2imaging. Actual400stop/resume kept the first100sealed unchanged and resumed300;
saved analysis26nonzero/25readout accepted/0imaging is inconclusive. No repeat.
Measured compressed projection76.14GB;1.5x allowance+temporary+20GiB reserve needs
136.08GB. Before latest resume6.35GB physical memory was free; after verification
152.92GB disk was free. Resident measured peak about2.49GB. Rough pilot10days is
not a guarantee; use actual progress. Low disk stops safely, never deletes science.

Final analysis/publication is PENDING and requires COMPLETE. Use frozen
gegi_campaign_analysis.py and gegi_campaign_publication.py (exporter SHA256
f0e8e78163bfaf153ec27e2304457165648b725f726261120acd95a3e43d158b), aggregate exact native error messages
from retained scalar records as well as stage/rejection counts, and report failed
or inconclusive separation honestly. No formal10M figures are yet published.
Freeze relevant writers, export saved data, build_site.py --gegi-campaign-bundle,
run affected checks/live desktop verification, synchronize Git, then disable this
monitor and release only this chat's lock. Do not change frozen sources while the
healthy campaign runs. Re-export affected derivatives rather than rerunning science.

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
