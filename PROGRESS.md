# Current handoff

## Guard-path diagnosis complete; local grid pilot approved — 2026-10-20

Owner priority: establish a correct GeGI radiation -> charge ->34-channel signal
-> electronics -> inverse reconstruction chain before larger samples. The forward
response should explain known simulated interactions, then infer unknown events
from signals alone; source positions remain independent image evaluation. Reuse
saved data, keep the frozen holdout independent, and do not tune to source maps.
Use bounded6.1-sol ultra development tasks; no extra AI review agents. Automatic
monitoring stays PAUSED. No new transport or calibration is approved. Owner approved
3fixed original-deposit drift captures (complete), then the bounded2levelWP34
grid pilot below. Original campaign/v3 science and failure records remain unchanged.

Frozen400 evaluation COMPLETE in17.234s:200development/200holdout, stratified by
10reasons, original-event-separated. All400 reproduce original spectroscopy
exactly. Each split has160complete endpoint references/40unknown. Development/
holdout pairing errors3/22 and5/24hypotheses; false splits1/22 and2/24; depth median
absolute errors0.143/0.100mm on49/50matched cell-hypothesis pairs. Sequence correct/
wrong/unknown2/2/40 and2/6/40. These selected conditional metrics are neither detector
efficiency nor spatial resolution. Validated imaging recoveries remain0.

Saved readout diagnosis:102channels from3development groups match the analytic
nominal circuit (peak error<1e-13V, exactADC/gain). Event976317: positive transient
peak raises mean ADC energy12.745keV over terminal charge; X9ends15.511keV but
transient reaches271.113keV and the shaped analog peak corresponds to43.381keV. Event30057 is mainly quantization.
Guard event723606: all86endpoints marked contact but mean terminal charge is45.904keV
below deposited energy. Saved-field query establishes contact-boundary interpolation: continuous guard
endpoints mix contact/noncontact grid nodes, yielding own-electrode values below1.
All86contact identities are correct; originalFloat32 algebra reproduces all34
saved terminal charges exactly (max error0.0keV). Query18.05s,1.679GBpeak memory;
no new drift/solve/injection in that endpoint query. Waveform correction remains unvalidated.
Never force its charge toEdep or treat contact flags as charge-conservation proof.

Approved capture c514ed87e5b0 completed exactly3original rows10191/10186/10185 in
37.343s, one process/thread, no retry. Results are under
validation/boundary-path-pilot/results; COMPLETE SHA50ead54a...832c50. Endpoint
positions, sample counts, contact IDs and all34terminal signals exactly reproduce
the original records. Full native paths and every34-channel sample are retained.
The separate same-path diagnostic took24.615s, peak1.605GB; no new drift or solve.
All102original waveforms reproduce bit-for-bit. Setting geometric-contact samples
to exact Dirichlet1/0 restores terminal charge but fails spatial continuity:
row10186 electron guard34 changes from0.905912 just outside to1 at the contact.
Maximum waveform changes are7.980/2.718/5.944keV for the3rows. This candidate is
rejected for production. Diagnostic report SHA9e887c96...adbf9 and source
gegi_saved_path_boundary.jl SHAf4f8c3af...da0af. Native guard grids are240x240x88;
local XY spacing1.17187mm versus Z0.0375002mm motivates a bounded XY mesh test,
not a claim that refinement is already a validated repair.

Fixed face-sum readout diagnostic COMPLETE: all17signed channels per face, including
guard, summed before the unchanged linear electronics/fixed500keV gain. Development
12.228s and single holdout11.896s;5targeted tests passed. Holdout keeps153/200valid
and47unknown, the same as the original. Paired absolute error mean1.837->1.035keV,
P905.012->2.052, max18.070->5.360; median0.695->0.877worsens.55improve/51worsen/47tie.
Face difference P909.840->0keV. This isolates positive-strip-transient bias but does
not fix upstream guard loss or remaining ballistic deficit; no production change.
It requires complete waveform access, unavailable from per-channel peak ADC alone.
Evidence validation/face-sum-readout/report.json SHA d7eb4c76...72c669; executed and
current tool SHA fee590c4...aa15e1. Do not tune thresholds against this holdout.

Saved signal-use derivative COMPLETE: signal-recovery-v1/signal-use-v2,104.083s,
57,613original groups.55,591existing spectroscopy groups (55,157spectroscopy-only),
434unchanged conditional candidate groups,1,896incomplete (including426nativefailed),
126unresolved complete signals.11,206guard collection,17,568guard transient,
12,680adjacent-strip groups; flags overlap.55,170spectroscopy groups meet the existing
face-compatibility screen. Every original readout summary matched exactly. No fits,
new cones or new energy reconstructions. Keep failed first derivative signal-use/
and log: GoogleDrive denied replacing progress.json after44chunks; second export
writes completion artifacts once and reports progress tostdout.

Runtime changes in this milestone: shared signal-use reporting, separate energy and
imaging explanations in Control, no adjacent-strip merging, preserved null failures.
The identical readout_summary function moved from campaign orchestration into the
existing imaging helper so the student package does not pull campaign/recovery
runners. AST equivalence and all57,613original energy values checked. Relevant tests:
signal-use7, shared signal12, campaign response9, saved reconstruction4, standalone8,
package5, saved-use exporter2; browser contract script passed. Original400evaluation
used pre-relocation source hashes; exact producer math is unchanged. Export source
snapshots live in signal-use-v2/source-bindings. Publication integration passes18exporter tests plus36site tests. Historical
installed-artifact validation is separate from strict current candidate admission;
explicit replacement binds the installed manifest. Source1b88d5e is committed/pushed. Student release student-runtime-1b88d5e7c2a7
is public and its892,170bytes/SHA b4407954...e5d9e were independently downloaded
and verified against the exact committed package. .local/student-runtime-p1/COMPLETE.json
is current. Websitepublication-v3 built successfully; build b13a16e7540c,
1,727files/985,104,763bytes. Required36site tests and final local check pass.
Website commit4466b8a deployed;732live files match exact lengths/hashes. The same
commit includes the separate tested face-sum diagnostic; student runtime remains
the exact1b88d5e package because production code did not change afterward.

Existing completed evidence: calibration/inventory.json confirms2,727selectedX/Y
signal checkpoints +264excluded records; full34responses were not computed and drift
paths were not saved. Peak-diagnostic confirms the19-group1332keV layer's second
maximum disappears locally in3/19leave-one-out cases; existing40iterations had not
converged. Keep these results; no repeat analysis. reference-index.json records private
18PPTs/283slides and4targetedPDFs. Current electronics is synthetic-signed-14bit-v1,
not a matched GeGI hardware transfer; distinguish10mmGeGI-4 from11mmcurrent models.

Next scientific step: execute the approved guard34 weighting-potential comparison on two
locally refined XY grids, preserving Z, model and original cache. New field solves
were separately approved; the3-drift approval is fully consumed. Fixed
request validation/boundary-grid-pilot/request.json SHA83d4e680...f2a5a2 is frozen;
the explicit owner reply is retained alongside it in approval.json.
Grids256x255x88/278x277x88 contain5,744,640/6,776,528nodes. Tool264lines,
SHAf776c878...547e20;3pure grid tests and Python/embedded Julia parser checks pass,
without evaluating Julia science code. CPU solve cost remains unmeasured.
Limits: one CPUthread/process, two solves,300s total,7M nodes per level, no retries;
startup free memory3.5GB, stop below768MiB free or above3GB worker working set.
At22:02UTC the repeated preflight has2,599,731,200B free, below3.5GB;0workers and
0field solves launched. Retain approval and await memory; do not loosen the gate
or close unrelated user programs. Source/diagnostic tooling is pushed atafa79b5.
No new transport, drift or calibration. Reuse these same paths for endpoint,
waveform and spatial-continuity comparisons; retain timeout/nonconvergence as failures.
Earlier memory-blocked capture preflights remain preserved. Missing full34
independent templates and exact hardware transfer remain explicit. The15pointfull34
injection proposal is conditional only; present necessity/scale/cost for owner decision
before any new drift/calibration. Keep one compact handoff.

Ownership: current manual owner gegi-saved-recovery-20261020 uses
.local/autonomy/gegi-saved-recovery.lock/owner.json. Old diagnosis ownership is retained
inactive, never deleted. Current manual ownership is retained inactive while
waiting for memory; state.json records approved_WP34_waiting_memory. No science
worker was launched. Automatic monitoring staysPAUSED.

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
