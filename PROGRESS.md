# Current handoff

## Full-chain evidence/planning milestone complete — 2026-10-20

Owner resumed work with full-chain correctness first and strict token discipline.
The evidence/implementation/gap/acceptance table and ordered next task are now in
tools/NEXT_DEVELOPMENT_PLAN.md. One 6.1-sol read-only source-mapping task was used;
no new Astra agents, physical calculations, calibration or reconstruction fits.
Automatic monitoring stays PAUSED. Original campaign/v3 delivery remains unchanged.

Main finding: current electronics is synthetic-signed-14bit-v1, not an identified
GeGI hardware transfer. Its existing 4-group/136-channel numerical circuit check
passed; reuse it. Need align full-detector/pixel spectra, signal/timing/trigger
observables and model generation before interpreting acceptance or source maps.
Carrier model uses deterministic point charges without diffusion; full 34-channel campaign
signals exist but the independent calibration saved only X/Y and no drift paths.
These are established model gaps, not proof of a single cause for all bad events.

Private reference-index.json under .local/gegi-10m/signal-recovery-v1 records
18 PPTs / 283 slides and 4 targeted PDFs. July 14 plots and IAEA p16 were visually checked.
Older GeGI-4 (10 mm), current manufacturer (11 mm), other strip/ring/PAGe/GIPR systems must
remain distinct. Full GeGI manual and matched hardware configuration still missing.

Next bounded task: finish existing frozen 400-event evaluation (200 development,
200 holdout); quantify stage energy, position, pairing, splitting and sequence errors
without changing cuts or rerunning fits. Then choose the earliest concrete repair.
15 full 34-channel injections are a conditional proposal only; no approval or execution yet.

Previous recovery WIP remains uncommitted and incompletely integrated: signal-use
classification/shared-entry wiring and dedicated inventory/peak/evaluation tools.
Six signal-use and twelve existing signal tests passed previously; do not repeat
unaffected tests. Peak attribution is complete; 400-event evaluation is not. No new
student release or website publication. Retain failed inventory-write evidence.
Old diagnosis ownership remains intact; current manual ownership record is
.local/autonomy/gegi-saved-recovery.lock/owner.json. Check its state/processes
before further execution; do not start automatic monitoring.

## GeGI saved-data correction — authorized delivery complete

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
