# Next development plan

## Active owner campaign — GeGI website and 1M (owner reduction2026-10-17)

This window (01a14bca-3953-7c13-80a1-687a9a571455) is the sole supervisor.
The owner reduced the campaign from10,000,000 to1,000,000 TOTAL formal initial
events and requested continued execution. Preserve all completed science; apply
an explicit proportional quota amendment after a safe completed-chunk stop.
This supersedes earlier10M allocation text. Preparation2400 is separately counted.
No extra AI reviews, new environment, global changes, paid API or resets.

1. First synchronize website generators with delivered GeGI capabilities: dedicated
   cryostat geometry/section/native 3D at Assemblies, home/catalog/Results/guide links,
   exact LBNL versus GeGI compatibility. Simplify normal routes and demote historical
   duplication without deleting unique science or breaking retained URLs. Build only
   with build_site.py, test/check, publish and verify live desktop navigation/3D.
2. Prepare source-blind reconstruction: collection/induction, strip pairing, timing
   depth and ordering. Quantify central-pixel calibration bias with existing evidence
   and independent model injections only as needed. Record omissions (charge sharing,
   cross talk/noise) and limit conclusions. Never select candidates with source truth.
3. Integrate the existing true isotope decay source into GeGI, then implement shared
   batch arithmetic, streaming nonzero response, one losslessly stored copy of signals,
   atomic completion and exact resume. Preserve old runs/fields/failures unchanged.
4. Measure representative pilots, including initial/source denominator, nonzero and
   imaging rates, wall time, peak memory, compressed bytes. Verify stop/resume and that
   sealed radiation/response chunks do not rerun. Freeze configuration, code/model
   hashes, seed schedule, cuts and metrics BEFORE production starts.
5. Launch a detached, bounded full-chain worker. The existing automation ID automation
   is migrated to this window every 30 minutes. Healthy monitoring reads compact state
   and exits immediately; faults resume only affected unfinished stages. Do not run
   competing supervisors or restart healthy workers on one unchanged observation.
6. Analyze all formal groups, publish spectra/real multichannel signals/directional
   and explicit assumed-plane images through existing generators, verify necessary
   student ZIP updates, synchronize Git, then disable monitoring and release own lock.

### Owner-reduced allocation — original campaign launched2026-10-17

Coordinates are mm from crystal center; +z is front; theta is from +z and phi
from +x toward +y. All points are 56.568542 mm away. Isotropic emission, no
collimator or inferred source activity. Existing geometry assumptions are retained.

| Group | Source and denominator | Position mm | phi / theta | Formal quota | Master seed | Purpose |
|---|---|---|---|---:|---:|---|
| gamma-left | 662 keV mono gamma; initial photons | (-40,0,40) | 180 / 45 deg | 200,000 | 261017101 | Equal-energy spatial control |
| gamma-right | 662 keV mono gamma; initial photons | (40,0,40) | 0 / 45 deg | 200,000 | 261017102 | Paired equal-energy control |
| cs137-left | Existing pinned Cs137 decay model; initial decays | (-40,0,40) | 180 / 45 deg | 300,000 | 261017103 | True-decay spectrum and isotope mixture |
| co60-right | Existing pinned Co60 decay model; initial decays | (40,0,40) | 0 / 45 deg | 300,000 | 261017104 | Distinct-energy cascade and spatial mixture |

Each group uses workflow_batches partition/seed rules (at most 10,000 initial
primaries per transport batch); validate cross-group seed uniqueness before freeze.
Group-resolved photon/decay denominators remain distinct in mixtures; 1M is their
administrative total, not a common photon efficiency denominator. Mixtures are
linear sums of independent acquisitions, without inter-source pile-up. Preserve
within-decay cascade/delayed timing and finite electronics-window semantics.
Both isotope groups use the identical union of661.657/1173.228/1332.492keV
windows (half-width max(5keV,2%)); source labels cannot discard cross-isotope
continuum contributions. Both gamma control groups use662keV.
Fixed analysis:5deg directional bins/kernel, assumedz40mm plane with2mm bins
over[-120,120]mm; blind top-two peaks at least20deg/20mm apart with connecting
valley at most0.8 of the lower peak. Evaluate truth matching only afterward, with
predeclared15deg/15mm engineering tolerances. Require20accepted groups/component
for a separation conclusion, never as a pilot launch gate. Optional200primary-
cluster Poisson resamples use seed261017201 and require a measured cost budget.

Acceptance is computational completion with exact full census, nonzero failures,
rejections, signed units, fixed source-blind reconstruction and reproducible hashes.
Before production freeze the scientific report definitions: image peak angular and
assumed z=40 mm plane bias, fixed energy windows, acceptance/rejection rates,
uncertainty/resampling rule and an objective two-peak/valley separation criterion.
A failure to separate is a valid scientific result; do not change seeds/cuts after
seeing maps. Direction and imposed-plane projection do not establish source range
or genuine 3D localization. No measured detector validation is claimed.

Measured recovery resources: about 155 GB free disk, 3.46 GB Windows physical memory
free at initial check; WSL 6.92 GB available after start. Re-measure before workers.
The old JSON format is not admitted for this campaign. No production start until measured
compressed storage + bounded temporary space + reserve fit available disk and
memory. The website milestone is delivered; current work is formal campaign
recovery and completion, then saved-data analysis/publication.

Owner quota amendment applied: .local/gegi-10m/quota-1m-v1/application.json.
The same .local/gegi-10m/campaign directory retains all17sealed chunks/170k,
old native failures, cache and identities. Exactly20/20/30/30effective chunks use
unchanged per-group seed/local-ID prefixes; no science rerun or Store rebind.
Current plan SHA2563539fab2594dd848ae9989490ed9fa80d8c74400abd9c8a2cb7a74c78ded8ae5;
quota producer90a82eda5b24262b3cfc7b843a8a8b5ed21d102d.69targeted tests passed.
Detached execution resumed with same request/spool; actual identities are in
PROGRESS/launcher records. Same-chat30min automation targets1M. Owner confirmed
the independent-acquisition/linear-mixture model; complex simultaneous-source and
pileup work is deferred. Final acceptance requires1M/100chunks and publication.
Effective remaining disk budget at170k is32.26GB including reserve, versus153.78GB
free before resume; original10M resource projection below is historical.

Historical preparation and original10M recovery evidence (retained unchanged):

Preparation evidence: source-blind reconstruction changes
pass14 targeted tests and retain original accepted IDs2714 /3170,3998,4046,4468.
All kinematically valid pair/order candidates remain; pixel calibration is strict
with no fallback to central truth. Fixed independent pixel/offset calibration
is completed:256pixels,216available/40unavailable,175diagnostic injections. Native
cache reused, no field solve. Protocol-only type failure occurred after saved
completion; exact failed producer/request are retained and the reply is repaired.
All11pilot checkpoints were reused, then2980new evaluations completed in158.298s,
peak native RSS2453430272bytes (startup36.505s separate). The table hash is
61f59e2fcdd43aa0f04d6a49a6e59c448bc6059057207a8bcd80d46074d29694.
Of175fixed diagnostics,124pixel and106central estimates are supported;51remain
outside support. On the same106points, median|residual| is0.132588mm pixel versus
0.168900mm central; maxima0.485043/0.566306mm. Remaining intrapixel bias and strict
no-extrapolation limits persist; this is not measured resolution or a global bound. Saved single-cloud
diagnostics (108 in-envelope cases) span -1.369..+1.133mm central-table residual;
this selected diagnostic is not a resolution or global error bound. Basis:
[Amman & Luke2000](https://escholarship.org/uc/item/1x55j4h9),
[Sleator et al.2019](https://arxiv.org/html/1911.02992v1), and
[Rogers et al.2026](https://arxiv.org/html/2602.02442v1).
Actual GeGI timing is still ideal-charge crossing, not those instruments' hardware.
The proposed transactional store retains one exact full native input and every
electronics scalar, hashes deterministic display traces for replay, and preserves
unknown failures. A12-existing-event bitwise round trip occupies843776bytes;
exact all34-channel electronics replay passed on a saved nonzero event without
drift. Four500-initial-event pilots with seeds261017301..304 completed, separate
from formal10M: nonzero counts26/28/20/41, native failures0, readout rejections0/1/0/1,
imaging accepted0/0/1/1 in table order. All34-channel electronics replay matches
exactly in each group. Measured native/store seconds27.705/14.134/35.287/73.355;
transport-driver seconds44.570/45.739/42.395/45.271; resident startup35.687s separate,
peak working set2,489,167,872bytes. Direct small-sample scaling is roughly10days,
not a production completion-time guarantee; revise from actual chunk timings.
Measured lossless storage projection76,135,237,900bytes; selected1.5x allowance,
temporary overlap and20GiB reserve require136,080,158,804bytes versus about155GB
free. The2x budget correctly fails and is not admitted. Gzip round trips preserve
all pilot originals. Four100-initial-event stop/resume qualification groups use
fixed seeds261017401..404. All400 completed after a stop at100 and resume;
the first sealed chunk retained exact hashes/timestamps. Actual saved-data analysis
passed with26nonzero/25readout accepted/0imaging, inconclusive. No formal primaries
are part of qualification. An explicit analysis-only producer/reader version record
allows the terminal-native-failure reporting correction without science reruns.
Preparation authority: .local/gegi-10m/preparation.json. Original formal campaign
was launched in .local/gegi-10m/campaign:1000chunks,total10M before owner reduction. First10k transport completed;
contact-domain event1188/group0 then stopped native processing after58saved groups.
The exact failure is retained with27rows/truth379.37764922113564keV and unknown
response null, without coordinate adjustment. Explicit versioned recovery is
complete in .local/gegi-10m/recovery-contact-v1: all58event blobs/2012arrays and
17transport file hashes/timestamps remained unchanged. Actual resumed processing
passed the failed event and reached131saved groups at23:23UTC. This is a partial
native count, not a completed formal chunk. Source commit96a814057ea40a57079116de8efd5da75bffc3fa;
first-recovery plan SHA25669c7a222025747be46c9585fd6200f201f33aa501c0f655fbb47d6d3ad9f783e.
The original frozen plan3cfcf66a... and producer9cd3f6c... remain in the recovery
archive. Only explicit failure recording/source identity changed; criteria,
allocations, seeds, physical inputs and calibration remain fixed.48Julia assertions
and58targeted recovery/response/analysis/publication tests passed. Existing student
release remains current because no packaged source changed. Read compact progress
and actual process identities; healthy monitors exit immediately. At23:50UTC a
second failure (Invalid native signed charge) stopped chunk5 after five sealed
chunks/50,000initial photons. Preserve that prefix and the40groups/1392arrays in
the partial sixth chunk. The original failure is retained in
.local/gegi-10m/failure-native-charge-v1. One bounded replay of the failed group
reached an already recognized outside-crystal endpoint error; it did not reproduce
the exact charge error or establish which original waveform invariant failed.
The original response is unknown. The second explicit recovery records only
this exact ArgumentError as native_failed/null, retaining all rows and all prior
source versions; underlying SSD numerical behavior is not claimed fixed.
No physical source, seed, cut, calibration or completed scientific data changed.
Recovery2 is applied in .local/gegi-10m/recovery-native-charge-v1; its execution
check preserves all5sealed chunks,40prior group blobs,1392arrays and17transport
files. Event801/group0 is imported from original failure evidence without drift
replay. Actual resumed partial count129groups through originalID2656 at00:13:57UTC
is not sealed initial completion. Pre-quota second-recovery plan SHA256:
3e28f5a40f2be830d775dad01994aed694bacffb84408c1bb88acc7c6c7227f6;
producer619093442162ecd3904a63bc54935e07c93a87c2.74Julia assertions and64targeted
Python tests passed. Same-chat30min automation is verified ACTIVE; healthy checks
exit quietly. Current process identities are in PROGRESS and launcher records.
Final analysis,
figures and final publication remain pending; do not declare the effective1M task complete.

## Delivered owner extension — GeGI (2026-10-17)

Owner extension during delivery: test two equal-energy point sources at different
positions for spatial separation. Completed bounded acceptance:5000primaries each at
[-40,0,40] and[40,0,40]mm,662keV,seeds26101703/26101704,serial CPU with reused
fields. Use source-independent cone reconstruction with corrected last-rising
charge timing; compare individual and mixed maps. For this near-field case,
backproject each cone from its actual vertex onto an explicitly imposedz=40mm
plane. Keep this assumed plane distinct from measured range or3Dlocalization.
Do not increase statistics solely to manufacture separation. The left source
yielded253nonzero/1imaging event; the right231nonzero/4imaging events. Four of the
five accepted events have ordering ambiguity. Spatial separation is inconclusive,
not demonstrated; this bounded test is complete and does not authorize more runs.

Steps1–6 are delivered. Software release student-runtime-6040230dc3ff is latest;
the actual downloaded ZIP/commit/hash and706live website files were verified.
The current compact receipt is .local/gegi-integration/delivery.json. No further
GeGI simulation, reviewer round or publication expansion is automatically queued.
Actual acceptance:100initial zero-only pilot with stop/resume, then5000initial
photons,42nonzero events and1signal-derived cone, plus the two-position test above.
This verifies the software workflow, not experimental accuracy or source localization.

P0-P5 below remain delivered. The owner now requests a GeGI-only cryostat and
multichannel Compton workflow in the existing desktop software. This section is
the completed delivery scope; no old audit/PSD/demo work is reopened.

1. Establish the dimension/material/coordinate/channel contract from supplied
   GeGI schematics/manual and relevant Ge-STAR presentations, checking primary
   online references. Preserve frozen GeGI YAML. Identify explicit nominal
   mechanical/electronics assumptions and any truly blocking missing input.
2. Add a separate cryostat asset restricted to GeGI; reuse Geant4/remage, geometry
   exports and the current lifecycle. Check native overlaps and identity/units,
   then one small transport pilot with recorded seed and bounded resources.
3. Reuse SSD for actual grouped deposits and all relevant electrodes; preserve
   signed induced signals, independent electronics calibration and channel IDs.
   Reuse applicable fields, checkpoint completed work and retain nonzero failures.
4. Reconstruct candidate interactions from channels with explicit pairing/depth/
   ordering ambiguities. Export valid Compton cones and a directional sky map;
   distinguish simulated response reconstruction from truth-assisted diagnostics.
   No fabricated depth, unknown range, laboratory calibration or precision claim.
5. Integrate compatible selection, check/run/stop/resume, actual channel plots,
   cones/map and file access in existing Control. Check changed paths only.
   Publish useful pilot plots on the website, never as student package fixtures.
6. Freeze producers, validate derived outputs, update this plan/PROGRESS, commit
   and push normally; build and verify the immutable student release, and use the
   existing generated-site publication checks. Remove only owned useless scratch.

Done when a user can select GeGI cryostat + GeGI, configure a source, run the
recorded chain, inspect real channel/cone/map outputs and resume completed stages;
incompatible detectors are refused independently by the backend. Scientific
limitations and event/selection census remain visible. Larger event counts follow
measured pilot cost and useful imaging statistics, not an unbounded campaign.

Owner correction: 2026-10-14. This is the current plan, replacing the automatic
PSD3/reviewer-heavy queue. Earlier history is preserved in Git at be145f9210d22e2449e6d66f03d9108dc9a3851d;
do not recreate a pile of historical planning files.

## User outcome and working rules

A student downloads the software, configures the documented existing environment,
opens Control, selects the current cryostat, a compatible detector and source,
enters the primary count, runs/stops/resumes, and finds each stage's real data.
The public website separately presents selected saved simulation and later measured
results. All product UI and beginner-facing text remain English. Desktop only.

No extra AI reviews, independent physics/workflow/third-party review agents, peer
debates, direction committees or repeated broad audits. The owner revoked those
requirements on 2026-10-14. Necessary developer checks are bounded to the change:
run the directly relevant existing tests or one meaningful operation, inspect the
diff, report actual failures, commit and push. Tiny documentation changes do not
rerun physics or a broad test suite. Once the useful outcome works, stop that item.

Use the existing remage/SSD/readout engines, shared model/source/scene definitions,
Control and pinned environments. No per-combination adapters, second frontend,
new installations, system PATH/WSL/global package changes, billed API or resets.
Reuse completed radiation/fields/charge and prior applicable acceptance. New physics
only when a changed physical input requires it, with a small stated case; never
rerun a campaign because a chat failed or a review could be repeated.

## Chat reconciliation and accepted work

Six owner chats belonging to this project were retrieved through all pages, including
older chats outside the recent sidebar list. User and assistant messages were read;
repeated scheduled prompts are historical automation content, superseded here.
Internal execution/subagent sessions are not separate owner requests. Original chat
histories remain in the app; no transcript copies were saved into the project.

The consistent owner requests were: student use first; a clean extensible common
workflow; configurable compatible detector/source/cryostat; arbitrary exact primary
count with batches up to10000; reliable stop/resume and data access; newest useful
representative teaching signals; readable plots and simple navigation; software
separate from saved showcase data; remove useless generated files and repeated audits.
Later explicit decisions: six oversized detectors await a real larger cryostat;
no phone work or second-computer prerequisite; keep current preamp unchanged;
November measurements require complete owner data; newest instruction removes extra
reviews and zero-input clutter from new product outputs.

Do not list accepted work as new development:10 compatible catalog models in the
existing cryostat, four isotope sources(Cs137/Am241/Ba133/Co60), legacy662keV gamma
route, shared scene/source assembly, batch counts and stop/resume, file provenance,
source/capsule angles within the accepted range, four-model10K display, AK02+SAP22
million-transport display, and the concrete recovery/normalization/focus/contrast
fixes already delivered. Availability is not experimental accuracy or proof that
all detector/source combinations have been physically rerun.

The added feature/acquisition code is retained as reusable advanced code, not the
next primary product delivery. Its two all-ineligible500-event demo exports were
removed during cleanup; no four-pulse classifier claim or new demo campaign follows.
Existing original scientific inputs and completed results remain unchanged.

## Ordered work

### P0 — Correct process and remove proven waste (completed at 33fdb05)

Remove old AI-review requirements from AGENTS and the saved continuation prompt.
Delete only confirmed assistant-generated review text, browser fixtures/screenshots,
synthetic acceptance scratch, duplicate-purpose source ZIP/unpacked copies and the
two all-ineligible feature/acquisition demo bundles. Keep one compact deletion manifest
under .local/autonomy/cleanup.json, not separate reports for each category.

Keep canonical models/includes, software environments/lockfiles, raw radiation/native/
readout outputs, original ledgers, fields/checkpoints, unique physical failures and
owner inputs. Keep app chat histories, credentials and browser account data. Check
absolute deletion paths and do not follow junctions. File name alone is not enough.

Done when confirmed candidates are removed, the retained original roots remain,
only one current plan/handoff governs development, and the process launches no extra
reviewers. The owner subsequently authorized continuation and an updated active
scheduled task on2026-10-14; use only this corrected queue. No new physics or
environment was needed for cleanup.

### P1 — Deliver a genuine student software package

Implementation and bounded package acceptance completed in the current P1 milestone.
The final committed/public ZIP receipt is .local/student-runtime-p1/COMPLETE.json;
only its terminal publication check permits automatic handoff to P2. Do not repeat
P1 packaging work when that receipt and source pins are complete.

The developer GitHub source ZIP excludes docs but still includes development material;
it remains distinct from the new student runtime release. Maintain one packaging
manifest from actual runtime dependencies:launchers, required Python/Julia code,
models and relative includes, scenario/source definitions, lockfiles, licenses and
one setup/use guide. Exclude saved results, developer tests/reports, browser fixtures,
publication tooling, unused canned demos and local caches.

P1 removed the unnecessary new-run dependency between production provenance and
developer test files, preserving historical v1 interpretation and runtime-only v2
inventories. Shared model labels and saved-waveform helpers also removed Control
imports of website generation code. Keep useful tests in developer source and
historical validators, outside the student ZIP. Runtime modules named example are
still real dependencies; do not delete them by filename.

Change the student download to this package and maintain the existing setup route.
Check package member paths and required-file/import completeness in the current
configured environment; do not create a new novice installation. Stop when the
package contains the real running dependencies and no showcase/test/report baggage.
A full developer clone may retain website/source/history; it is a distinct route.

### P2 — Implement zero-input storage and selection policy

Completed in the current P2 milestone: one actual100-primary SAP22/Cs137/+30deg
run completed with97zero/3nonzero, IDs24/52/54,3accepted groups. New truth/scalars
and normalized/analysis records are nonzero-only; full counts/denominator and raw
LH5 remain. Actual new and historical pages/feature export passed. Current
.local/nonzero-storage-p2/COMPLETE.json governs final source/asset evidence.
Do not rerun the100 case or spend the unused400-primary allowance automatically.
Next is P3 after P2 Git/public asset closure.

For NEW analysis/result exports store nonzero-deposit event records and their actual
signals; do not create a per-zero-event JSON/CSV/waveform payload. Preserve total
initial primaries, zero/nonzero/failed/rejected counts, exposure/denominator, original
nonzero IDs, batch offsets, seeds and exact settings. A missing or failed signal is
null with a reason, never a fabricated zero waveform. Nonzero readout-rejected and
native-failed events are retained, not confused with zero deposition.

Use one common filter/storage contract in writer, exporter and Control. Default
browsing selects a real saved nonzero signal, with concise count summaries. Historical
raw scientific archives remain unchanged and readable; do not destroy them to make
new output small. Teaching pages keep a few representative signals from newer
completed data rather than giant zero-event lists. Check a saved small mixed case
for nonzero IDs, zero count, failure/null/negative-sign behavior and unchanged energy
and efficiency denominator. Owner update2026-10-14 also permits one actual small
end-to-end software acceptance: start100 initial events, cap total new primaries
at500, one detector/source combination, reuse existing geometry/fields when
applicable, record settings/seed and preserve failures. This is a bounded software
check, not new physical validation or a reason to expand a campaign.

### P3 — Close the actual student desktop workflow

Implemented and checked in the current P3 milestone. Saved stage files are visible
below the existing signal plots; saved raw-count spectra distinguish a full run
from a selected sealed batch. Empty advanced exports stay hidden and exact hashes
remain optional details. Current .local/desktop-workflow-p3/COMPLETE.json governs
Git/package/public asset closure before P4. Existing control/recovery/plot acceptance
is reused; no new radiation/SSD calculation was needed. An already open old Control
backend must be reopened to load new routes; its process and lock were preserved.

Keep a single main route:select scene/detector/source -> enter count/settings ->
check -> run -> inspect results. Remove unused fixed-example controls and empty/demo
result panels from the normal route; retain advanced analysis only where it can
operate on the student's own run. Display only useful stage state, progress and
blocking reason; move hashes/full logs/old jobs to optional details.

Check actual selected settings drive the backend; edits invalidate old checks;
current setup differs clearly from the selected saved run. Reopen/stop/resume reuses
finished stages, shared fields and independent calibration. Results lead with the
nonzero event, four readable signal plots, spectrum and stage-specific original-file
links with units/identity mapping. All UI stays English, mouse/keyboard desktop use.

Use existing applicable acceptance and one targeted operation for changed paths;
no repeat10-model/all-source simulation matrix, broad UI audit or synthetic demo
passed off as ordinary student use. Stop at the usable documented path; subsequent
student feedback supplies concrete fixes.

### P4 — Add only the remaining useful configuration options

Implemented in the current P4 milestone: positive finite gamma energy in keV and
the existing nominal/+5mm anchors on the same AK02/SAP22 twenty-primary route.
The original662keV preset stays frozen; new effective-source markers bind actual
energy/placement and new marked streams/responses omit zero-input rows while
keeping full census/denominator. One actual1000keV/nominal SAP22 transport check
completed20 primaries:18zero/2nonzero, original IDs7/16. Geometry, raw radiation,
sparse export and actual native-request binding passed; SSD/fields/readout were
not rerun. Current .local/gamma-options-p4/COMPLETE.json governs publication.

Named desktop follow-up completed: saved Gamma current-source verification is
separate from known ended scientific workers, including failed verification and
reopening. Active/unknown/uncertain workers still block; unverified old downloads
stay refused and strict source checks remain. One exact historical local metadata
repair used original successful run/verification logs, bound terminal artifacts
and actual idle process/lease evidence. The real old verification still fails;
a fresh configuration Check succeeds without science. All22 original files and
old log prefix remain unchanged. See .local/gamma-history-gate/COMPLETE.json.
No broad historical audit, old-source admission or physics rerun was performed.

Keep the shared current cryostat, detector and source anchors; no duplicated files
for every combination. The accepted source-angle function is already implemented,
so do not rebuild it. Add genuinely requested missing monoenergetic gamma energy/
position options through the same configuration/backend, with units and saved resolved
placement. Check geometry/overlap and one bounded case only where transport changes.
Do not expose sliders that the actual backend ignores or admit oversize detectors.

The six larger models wait for the larger cryostat's real dimensions/materials/
mounting data. Reuse remage's existing interfaces; adopting paper advice is not a
new framework/solver/upgrade project. Stop each option when it actually works and
is documented, without an extra direction-review round.

### P5 — Maintain useful website presentation and later pulse analysis

The website remains saved-results presentation, separate from student runtime files.
P5 publication milestone synchronizes the maintained student download/setup/
configuration guide through the normal saved-snapshot build. Only the guide and
three exact historical display-source receipts change; all1531 saved data/media
artifacts and scientific HTML remain exact. Current .local/autonomy/public-guide-p5.json
is authoritative for local/live publication completion. Once its status is completed,
this executable item is delivered; no new whole-site audit or redesign follows.
Fix named actual broken plots/links/selection issues from the existing supplied
navigation plan; do not restart a whole-site redesign. Keep dataset-first navigation,
both AK02/SAP22 million results and all four10K models, current representative signals,
readable axes and source identities. Current preamp model/display stays unchanged.
Use maintained generators; test/check only affected publication scope through the
existing build path when publishing. No phone acceptance or physics rerun for layout.

The PPT-inspired A/E/rise/acquisition/classifier direction remains a later application
on usable independently labelled data, after P1-P3. Do not automatically start PSD3
on the removed0-selected-group demo. Define population/labels/event-grouped splits/
minimum sample adequacy before a small comparison; report insufficient data honestly.
No A/E-derived training label called independent validation, invented metrics,
missing measured waveforms or growing ML environment as a delivery prerequisite.

### P6 — November real measurement publication (external input)

When the owner supplies complete releasable energy spectra,I-V,C-V and metadata,
add one detector's actual measurement using the existing detector/result structure:
conditions, units, acquisition/calibration/background information, uncertainty,
original files and simulation/measurement distinction. Then reuse that template.
No forced simulation overlay, parameter fit or waveform accuracy claim; original
AK02/SAP22 measured pulse waveforms were not saved. Missing input blocks only this
item, not software packaging/storage/desktop delivery.

## Completion and stop

After the P5 public-guide receipt reaches completed, all currently independent
executable P0-P5 work is delivered. Leave input-dependent P5 pulse classification,
P6 measurements and larger-cryostat geometry pending, without inventing new work.
Unchanged scheduled wakeups remain quiet; do not repeat accepted checks or rebuild
identical student ZIPs. New concrete owner feedback/input can reopen its own item.

After each useful change:one related developer verification, concise PROGRESS update,
normal commit/push, close owned idle tools and release the owned lease. No extra
reviewers or new evidence directories. Do not manufacture work when the usable
requested outcome is complete. Do not call software/data presentation validated
physical detector response. Report implemented, tested and input-dependent items
separately; retain scientific identities, signs, nulls, units and independent gain.
