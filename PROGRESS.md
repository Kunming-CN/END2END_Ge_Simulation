# Current handoff

## Guard grid defect localized; two local levels completed — 2026-10-20

Owner priority: establish a correct GeGI radiation -> charge ->34-channel signal
-> electronics -> inverse reconstruction chain before larger samples. The forward
response should explain known simulated interactions, then infer unknown events
from signals alone; source positions remain independent image evaluation. Reuse
saved data, keep the frozen holdout independent, and do not tune to source maps.
Use bounded6.1-sol ultra development tasks; no extra AI review agents. Automatic
monitoring stays PAUSED. Latest owner instruction "不需要每次等我审核，你继续就行"
authorizes necessary bounded small repair calculations/development/publication
without per-round approval, superseding the old individual calculation gates.
Large campaigns remain after full-chain validation. Memory is measured only.
Original campaign/v3 science and failure records remain unchanged.

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

Guard34 pilot executed once after the owner removed all artificial memory gates.
Original request83d4e680...f2a5a2/approval remain; request-owner-memory.json
SHA218b4685...f15e19 binds the amendment and unchanged scientific inputs. Runner
SHA8ff17dd8...b023dc;3grid tests and Python/Julia parsers pass. Total77.031s,
peak1.958GB; first grid256x255x88 (5,744,640nodes) solve55.326s returns
max update3.5464764e-6 > fixed1e-6 gate. The pilot stopped, second grid was NOT run.
Keep results/failure.json, solver.json and saved23MB WP34. Native SSD can stop on
small variation of recent updates or iteration cap; the exact reason/count was
not returned. Do not infer that10,000iterations were completed. No memory stop.
Original857MB cache SHA remainsf75280e7...53b90e8; no production fields changed.

One saved-state analysis completed in12.828s, loading only the23MB WP34 and paths;
no new solve/drift. Three original channel34 waveforms reproduce bit-for-bit.
Electron endpoint phi34 original -> first grid: row10191 .91622633->1;
10186 .90592694->.99657255;10185 .90608597->.99510586. Remaining deficits are
0/.342745%/.489414%, versus original8.38-9.41%. Near-end lambda.999->1 samples
change .99999672->1, .99653792->.99657255, .99508107->.99510586 without forced
contact values. These discrete samples and an unconverged local solve do not
validate continuity, grid convergence or production repair. Complete waveforms,
path phi and hashes: validation/boundary-grid-pilot/saved-state-analysis/analysis.json
SHA79f2dacb...f3444a; script SHA69eaf589...6587dd. This supports a local-grid cause
of guard signal error; retain the unvalidated status and original failure receipt.

Owner-approved continuation request374f9bde...37ed7b executed once from the saved
first-level field. Runnercba08545...4a47db at21bb6b4; new outputs stay in
results-continuation, retaining original failure. Total89.531s/solve67.279s,
peak1.943GB. Native stopping1e-7 returns1.1622906e-6, still above unchanged external
1e-6 acceptance. The first level failed again; second level NOT started, no retry.
No production repair. A33line local loop reuses native SSD setup/kernel/update
and painting, records both red/black half maxima every100steps and actual counts/
stop reason, and accepts only full_max<=1e-6 (no std-based early stop).
Request-strict-stop.json SHA8f20c397...6b0910/toolSHAab252653...7bb89 executed once
with owner approval, reusing the latest saved first-level seed. Results-strict-stop
completed in275.984s, peak2.019GB. Level8:300steps/19.241s/max9.23871994e-7;
level16:5000steps/232.813s/max9.53674316e-7. Both accepted unchanged update gate.
COMPLETE SHA46d94c69...e0bcd4; actual workerSHA94ffb394...0d4c. Both fields,
waveforms and native iteration histories hash-verified; prior failures retained.
No new drift, electric-field solve or calibration in this comparison.

Saved Python comparison (0.016s), grid-comparison/summary.json SHA9e16cb99...045:
level16 electron phi34=1 and hole phi34=0 for all3paths, without contact substitution.
Native terminal minus Edep is only+1.33/+2.77/+1.83e-6keV (Float32 scale, not ADC
resolution). Level16-level8 full waveform max/RMS differences in row order
10191/10186/10185: .418079/.163822, .126453/.064184, .292114/.202977keV.
Only WP34 and3local paths were tested; terminal equality is not waveform/global
convergence. Inspect propagation through unchanged readout/timing and common-grid
boundary support for other channels next. Old noncollecting channels still have
spurious terminal signals (up to1.83544keV on channel20 in these3paths); replacing
WP34 alone is not a full34 production repair. Never force charge to truth.

Readout propagation reuses stored500keV calibration, originalelectronics and Y34
wiring:9isolated deposit pulses, no new injection/field/drift. Compute3.253s,
whole process8.969s. Level16-level8 analog-energy differences -.000646/.093451/
.291724keV; maximum t50/t90 changes .309/.527ns (ideal charge, not hardware).
All three ADC codes unchanged75/21/47;1.24558keVLSB hides sub-LSB differences,
not a convergence pass. readout-comparison.json SHA713c9c69...80d45.
Read-only common-grid check confirms all34oldgrids identical and all originalticks
retained; all6endpoints have four interpolation support nodes on the right contact.
multichannel-grid.json SHAa74b1dc8...11678. Fixed17/20 pilot now dispatched under
bounded autonomy: requestae68e935...6491, toolcf977b6d...da4b0, driver18b958d1...8ae0b,
2solves/600s/one thread, samelevel16/1e-6full-updategate, no memory cap or retry.
No new drift or electric-field computation; originals retained. Wait for terminal
receipt in results-channels-17-20 before interpretation or another solve.

Future calibration recording implemented: one native_deposit call requests1:34,
channel_signals preserves native signs/IDs/ns/keV, signals.X/Y and timing unchanged.
New identity/table describes requested coverage; successful response records actual
coverage, excluded/failed records retain nulls. Old selected-only records cannot
resume into the new writer and are unchanged. No missing old responses recovered.
Software-only stub test117checks, oldinventory4tests and package5tests pass; no
physical injection was used. Student release for this change is pending below.

Owner question on past cost is resolved by actual campaign receipts and pinned
source:100/100response.json say new_field_solve=false;5resident loads reuse cache
f75280e7...53b90e8. Loading occurs once per resident initialize, outside event/chunk
loops. Five startup totals28.821-38.342s sum160.649s (includes Julia/package load,
hash/cache reads and possible compilation; no separate deserialize measurement).
100retained chunk timing records sum native_response_and_store75,541.740s=20.984h,
transport_driver11,102.995s=3.084h, verified_archive112.602s. These cross recovered
request generations and are stage sums, not one final calendar runtime. Drift,
34signal generation, electronics and IO were not separately timed; do not invent
shares or call the entire20.984h drift. Actual response helperSHA b249bea matches
current source for all100;5early resident records use an older resident version,
but their receipts/logs also establish cache reuse. Saved reconstruction-v3 took
337.197s without native computation; publication verification called no physics.
Code anchors:simulation/gegi_response.jl:90,144,149,220;
simulation/gegi_campaign_response.jl:76,191,235;tools/gegi_campaign.py:989,1010.

Full34 independent templates and exact hardware transfer remain unresolved; the
15point calibration option is still conditional, not the next calculation.
Ownership retains current/old records; strict-stop worker41096 exited. Automatic
monitoring staysPAUSED. Bounded multichannel repair proceeds under latest autonomy;
no new campaign or reset. Production fields and student package remain unchanged.

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
