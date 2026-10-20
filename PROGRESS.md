# Current handoff

## GeGI full34 reference complete; joint-fit development — 2026-10-20

Priority: correct the small radiation -> charge ->34-channel signal -> electronics
-> inverse reconstruction chain before larger campaigns. Truth/known source is
independent evaluation, never a signal correction or image-fitting input.
Latest owner: "不需要每次等我审核，你继续就行" authorizes necessary bounded repair
calculations/development/publication without per-round approval. Memory measured
only. Monitoring PAUSED; no resets or new large campaign. Root owns the existing
gegi-saved-recovery lock; retain old inactive ownership. No science worker running.
Use bounded6.1-sol ultra development tasks, no extra AI reviews. Detailed earlier
guard chronology is retained at Git09eae20:PROGRESS.md and immutable local receipts.

### Completed physical localization — reuse, do not repeat

Saved circuit checks:102channels/3development groups match nominal analog circuit
(<1e-13V, exactADC/gain). Event976317 has positive-transient peak bias: meanADC
12.745keV above terminal charge; X9terminal15.511/transient271.113/analogpeak43.381keV.
Guard event723606 has86geometric contact endpoints yet mean terminal loss45.904keV.
OriginalFloat32 endpoint algebra exactly explains all34terminal signals: native
Cartesian interpolation mixes contact/noncontact nodes near the guard boundary.
Contact membership alone does not establish complete induced charge.

Only3original rows10191/10186/10185 were recaptured,37.343s, retaining full paths
and34signed signals. All102original waveforms replay bit-for-bit. Direct geometric
Dirichlet1/0 replacement is REJECTED: row10186 jumps .905912->1 at the surface.
Original240x240x88 grid has local XY1.17187mm versus Z.0375002mm. No old raw bytes
or production field changed. Capture and diagnostics: validation/boundary-path-pilot.
Original cacheSHA f75280e7...53b90e8; modelSHA4b6c71c1...5c04, SSD0.11.8/Julia1.13.0.

Local WP34 grids preserve originalticks/Z, 256x255x88 and278x277x88. Native-stop
attempts returned3.54648e-6 and1.16229e-6; failures/seeds retained, no inferred
iteration counts. Strict trace uses native SSD CPU kernel/setup/painting, checks
both red/black halves, no std-based stop, unchanged full-update1e-6gate.
results-strict-stop completed275.984s/2.019GB: level8 300steps/19.241s/9.23872e-7;
level16 5000steps/232.813s/9.53674e-7. COMPLETE46d94c69...e0bcd4. Both fields,
waveforms/history verified. Level16 gives electronphi34=1,holephi34=0 on3paths;
terminal error against Edep+1.33/+2.77/+1.83e-6keV (Float32 scale, not resolution).
Level16-level8 max/RMS waveform differences .418079/.163822, .126453/.064184,
.292114/.202977keV. Saved readout:9isolated pulses,3.253s computation/8.969s total;
analog-energy differences -.000646/.093451/.291724keV, max t50/t90 shift .309/.527ns.
Codes75/21/47 unchanged because1.24558keV ADC step hides smaller changes, not a
waveform-convergence pass. Timing is ideal charge, not hardware timing.

Same level16 geometry gives correct4-corner support at all6saved endpoints.
New WP17/20 pilot completed464.234s/2.089GB, no drift/EP/transport/calibration:
WP17 5000steps/224.530s/9.53674e-7; WP20 4900steps/215.493s/9.98378e-7.
All6original baseline waveforms bitexact; both fields/history/output hashes verified.
WP17 terminal now+E within Float32 rounding. WP20 old−1.83544/−.51123/−1.10700keV
terminals become0; nonzero transients remain (positive maxima8.748/2.450/5.227keV).
Requestae68e935...6491, COMPLETEe63430df...01f3, summary204284c9...9b9ad.
Evidence: validation/boundary-grid-pilot/results-channels-17-20 and grid-comparison.
Only3local paths and3of34WP tested; other31WP/electric drift fields unchanged.
This identifies a defect and local remedy, not full-detector production validation.

### Full34 reference and immediate next work

Future pixel calibration now calls native_deposit once with1:34 and saves native
signed channel_signals/IDs/ns/keV; existing signals.X/Y and timing unchanged.
New identity/table records requested coverage, successful rows actual coverage;
excluded/failed rows remainnull. Old selected-only checkpoints stay intact and
cannot resume into the new writer. Source09eae20 pushed; software stub117checks,
oldinventory4tests, package5tests passed without physics. This developer bank
producer is absent from the student manifest; shipped payload unchanged, so keep
student1b88d5e and website4466b8a (no identical-package release).

Fixed15 full34 pilot COMPLETED:3pixels(9,26),(1,26),(3,20), five depths−4.5/−2.5/0/
2.5/4.5mm,500keV; original cache/model/native parameters. All15old X/Y waveforms,
timing/endpoints bitexact;510actual signed waveforms saved. Every channel terminal
matches original endpoint algebra and ideal contact values exactly. Each face
sum−500keV=3.05176e-5keV (Float32 rounding). No correction/normalization applied.
39.093s/2.151GB/2.22MB; startup23.980s, first capture12.293s includes compilation,
other14capture .005-.008s (one .053s); internal native sum10.498s, capture sum12.427s.
Request436a6089...f3da2, toolc99b9b9d...ae506, worker8d2bf5e9...d1274,
COMPLETE5c359317...410e07. Evidence calibration/full34-pilot/results. No new field
or transport; exactly15drifts. Exit/PID37752 recorded complete; do not recalculate.

Full ORIGINAL2991-record bank now COMPLETED,223.531s/2.630GB,481.31MB including
validation evidence. Same K.build and frozen inputs;15pilot points reused in18
checkpoint paths,2973new records/2709new drifts, no field/transport/retry.
K.build162.013s; new injection internal time sum140.127s (not total runtime).
All2991record hashes and old selectedXY/status/timing/endpoints verified exact.
2727full34 records/92718waveforms;264geometry exclusions and176incomplete retained.
All2551complete responses have zero native endpoint and ideal-contact residual;
face-sum roundoff3.05176e-5keV.216available/40unavailable pixels,175diagnostics.
Requestc613a268...7159e; COMPLETEb107d0a1...96821; validationbe5f420f...57ba5.
Evidence calibration/full34-bank/results/{COMPLETE,verification,runtime}.json.
All originals remain unchanged; geometric completeness is not hardware validation.

Joint-fit opt-in all34 implemented; default selected_pair unchanged.18targeted
fit tests and9evaluation tests passed. Frozen200development evaluated19.720s,
95fit calls, all200original spectroscopy values exact. Candidate groups20->33
(13new,20retained,0lost), conditional hypotheses22->55; wrong pairs3/22->24/55,
false splits1/22->6/55. Matched depth medianabs .142586mm(n49)->.504093mm(n124);
site-energy medianabs .352914->.612713keV, max258.035->517.563keV. Sequence
correct/wrong/unknown2/2/40->3/4/242. Different conditional populations are explicit.
Evidence validation/full34-development/{report,evaluation-groups}.json; source
37c133c4...ec4fd. This candidate FAILED development quality; no holdout run or
production promotion. Global energy scaling may hide weak-channel errors: inspect
that concrete mechanism, preserve this failed result, then change only the affected
normalization and test it. Independent template bank is complete and reusable.

### Saved-data and publication baselines — already delivered

Original1M campaign complete100chunks (400kphotons+600kdecays;2400prep excluded).
57,613signal groups,434conditional/837cones; map162groups/393candidates. 1,896
incomplete including426nativefailed. Validated imaging recoveries remain0.
Frozen400=200dev/200holdout across10reasons, event-separated: all oldenergiesexact;
160complete/40unknown each; ADC155/153. Pair errors3/22 vs5/24; false splits1/22
vs2/24; depthmedianabs .143/.100mm(n49/50); sequencecorrect/wrong/unknown2/2/40
vs2/6/40. Conditional selected metrics, not detector efficiency or resolution.
Saved-use-v2 completed104.083s:55,591spectroscopy (55,157only),434conditional,
1,896incomplete,126unresolved; all57,613energiesexact. Guards collection11,206,
transient17,568, adjacent12,680 (overlap). Preserve failed first export as evidence.
Fixed face-sum diagnostic (17signed channels/face before unchanged electronics)
holdout153valid/47unknown; absmean1.837->1.035keV,P905.012->2.052,max18.070->5.360,
median.695->.877worse;55improve/51worsen/47tie. Full waveforms required, not peakADC.
Not production. Do not re-execute old400, electronics, face-sum or map attribution.
1332.492keV layer19groups/58sequences: secondary maximum vanishes3/19LOO;
40iterations not converged. Private18PPT/283slides+4PDF index already researched.
Synthetic electronics still not a measured GeGI transfer; no calibrated diffusion/
noise/crosstalk or detector efficiency inferred. Originalcanonical physics unchanged.

100/100campaign receipts new_field_solve=false.5resident cache loads total160.649s;
fields loaded once per resident, never per event. Retained100chunk stage sums:
native_response_and_store75,541.740s(20.984h), transport_driver11,102.995s(3.084h).
These span recovered generations; not one calendar runtime or pure drift cost.
Saved-v3 reconstruction337.197s, no native calculation. No need rediscover this.

Student release1b88d5e7c2a7 verified public SHA b4407954...e5d9e,892170bytes/187members.
Website4466b8a/buildb13a16e7540c:1727files/985104763bytes,36tests and732live hashes
passed. Do not rebuild unchanged website or runtime for diagnostic-only work.
Detailed receipts/source bindings remain in .local and earlier Git history.

## Prior GeGI saved-data correction — delivered history

Owner authorized full-chain signal/readout/software correction and GitHub display
using existing data, local private GeGI slides and primary literature. No new
Geant4, SSD drift, fields, calibration injections or campaign. Automation remains
PAUSED. Chat01a14bca-3953-7c13-80a1-687a9a571455 / gegi-10m-root owns
.local/autonomy/gegi-diagnosis.lock. Do not launch a competing supervisor.

Numerical work, student release, website publication and live checks are complete.
Actual protected desktop student controls and public pages were verified. Do not
rerun completed processing. Scientific localization limits below remain unresolved;
this delivery does not mark the overall scientific project complete. No automatic
next calculation. Retain the inactive owned diagnosis-lock record and all data.

## Results and limits

Immutable original campaign .local/gegi-10m/campaign completed100chunks/1M;
400k initial photons and600k initial decays are separate denominators; preparation
2400excluded. Four acquisitions occupy only two positions, with two mono662keV
sources and Cs137/Co60. It is not four distinct nuclides or four source positions.
COMPLETE SHA44e40e50dbc3f86517bb144de9a82a920ded30c839201cecca9986b5adfafc29;
plan SHA0ef776b56b699285ffe5ac803bdd759402bca4a15825c2602c7f2ff659ade7d1.
100artifact/archive hashes and quotas verified previously; all scienceworkers exited.
All original fields, requests/spools,3failure/recoverygenerations and quota records
are permanent. Event801/group0 original21rows retain native_failed/null; no replay.

Diagnosis .local/gegi-10m/diagnosis-rejected-v1 is immutable.39,683strict2x2rejects:
30,696one-strip/face,5,819one-face-merged,2,787three-plus-strip,381no-hit.
4,184truth-diagnostic priority candidates are NOT recovered events. Finite-square
per-cone normalization was proved to amplify miss-cone tails into boundary peaks.
Event984042 has two50%crossings; oldlast-crossing depth was wrong. Truth remains
posthoc diagnostic only, never candidate selection, ordering or weight input.

Shared tools/gegi_signal_reconstruction.py fits signed saved waveforms with bounded
sparse X/Y matching, conditional depth templates and sequence hypotheses. No forced
2x2 interaction rule or last-crossing depth fallback. Unknown or incomplete native
responses remain explicit, and missing calibration yields unsupported/null imaging.
The available independent bank saves selected X/Y waveforms, not complete34channel
response bases. Charge sharing, same-pixel multiplicity and cascade ambiguity remain
unresolved; no proprietary GeGI or experimental calibration equivalence is claimed.

Full saved processing .local/gegi-10m/reconstruction-v3/full-signal is COMPLETE:
57,613groups/100chunks in337.197s;1,944,358scalar channels checked;426nativefailed
retained (subset of1,896native_response_incomplete).434conditional groups/837cones,
including284of the original39,683strictrejects. Validated recovered groups=0.
Summary SHAf4d653c8a6a79f2b47a8c8ccbc494fd0dea20e030d585b3ddbeedd9f3ae343ca.
Executed runner preserved under reconstruction-v3/source-bindings; later admission-
only source revision must be explicit, not a silent source rebaseline or rerun.

joint-signal/report.json selects162groups/393candidates using common measured-energy
windows without acquisition labels. Finite-vertex angular likelihood retains
unresolved candidate mass and background, with no finite-square normalization.
Pooled assumedz40mm modes(-42,-2)/(42,2)mm; posthoc evaluation finds2.83mm distance
from known positions, but this is NOT resolution or validated general localization.
The661.657keV layer still misses the right source;1173layer secondary peak reaches
an edge and1332layer has19groups. Weightedmedian angularresidual22.162deg; only33.22%
of total groupmass within15deg. Different162/708populations cannot establish an
accuracy/efficiency improvement. Range/activity remainnull. No true3D or pileupclaim.
Report SHA855fd81aefe107b191f51a826fb5d9d0ecaed446ee9f525a2549425b927b113d;
evaluation SHA8c19858e696ec648329ca0107bb362780fee28c0d393d7386121a0d798f7cb2b.

Independent analytic circuit check of4saved events/136channels passed: peakvoltage
error<9.2e-14V, exactADCcodes and fixedenergygain. This verifies the implemented
nominal circuit, not the real instrument transferfunction. No new native replay.
Sourcekind: Co60-compatible doublet;661.7keV alone ambiguous. Setup56.57mmcenter/
26.4mmcoverclearance is not inferred distance. Full34channel calibration, measured
noise/crosstalk/electronics and calibrated sensitivity remain needed for accuracy.

## Software and publication

New student paths share reconstruction, explicit calibration identity admission,
protected saved-campaign discovery, separate derivatives and chunk stop/resume.
Standalone production must not create old timing-derived maps; absent compatible
independent bank => unsupported depth/map. Preserve exact native result bytes.
No canned science in ZIP. Existing environments unchanged; use maintained guide.
Assembly saved-view bundle .local/gegi-website/assembly-signal-v3 contains214real
positive-energy Ge STEPchords from4original1Mevents, not complete particle tracks.
Old5000science retained privately; old public entries redirect to current results.

New saved publication .local/gegi-10m/reconstruction-v3/publication is complete;
only tools/build_site.py may replace generated docs. Source/test/package commit
47685df9f40a0b05e33d884bae85642a06fe87f3 was pushed and release bytes verified.
Generated snapshot passed both check_site.validate gates in build_site and the
standalone tools/check_site.py command. check_site.py --url verified731public
files byte-for-byte. Actual desktop checks passed: pooled map, energy layers,
historical teaching cone rotation, assembly event switching/cutaway/front view,
and old5000entry redirect. Both pages had no browser warnings/errors. test_site passed35tests
(9.840s including byte-exact GeGI export regression). New/oldpublication tests11/12, signal12,
jointimaging18, assembly16, savedrunner4, standalone8, admission4, controller7 and
studentpackage5 passed; final package dependency closure186members passed. Desktop
student saved-input discovery/calibration selection verified; noRun/Download clicked. No new simulation after delivery; future four-nuclide run requires
owner decision and measured small acceptance/cost evidence before another1M.

Prior detailed handoff is immutable in Git:
https://github.com/kunming-cn/END2END_Ge_Simulation/blob/e58169bdff6e9230da0167de3f1fe85a6b2d285c/PROGRESS.md
Student release authority: .local/student-runtime-p1/COMPLETE.json. Current release
student-runtime-47685df9f40a:186members/889438bytes, SHA256
701628355c56460530712ca408da19b71c36d4465002bce3e35e715003a6d18f. Versioned/latest
public ZIP, receipt bytes and remote tag commit verified; no install.
New public manifest b02b3399a3d8adf05ed1404922fed76691f23caaefc13f7c574f0934b9d7e2ba.
Publication-only old-summary navigation mismatch fixed;11targeted hub tests passed.
Exact predecessor display receipts were matched to committed47685df bytes;6targeted
tamper/original-data binding tests passed. Generic CRLF normalization changed only
one staged event-file terminator; exact original bundle bytes restored through the
publisher, with recovery recorded under publication/build-recovery.json. The
existing stage was validated and installed; no repeated science or source export.
Site build5080f24f65738b52018a675cf4f309a07a643048c9344e077fba627f0b364a2d:
1,726files/985,090,719bytes/109HTMLpages,3,479local links checked. Source and
generated diff inspected; prior scientific datasets unchanged. Website commit
b408c8d3ae242a317a8388050247c52d073e7f5a pushed and Pages built; live verification
completed2026-10-20UTC. Evidence: reconstruction-v3/publication/live-verification.json.
