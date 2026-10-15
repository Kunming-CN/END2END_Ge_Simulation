# Next development plan

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
Later explicit decisions: seven oversized detectors await a real larger cryostat;
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

Concrete next desktop fix before P5: an old completed Gamma verification compares
its recorded producers with changed live source files, and the owner Control
gate can block an independent new run despite no scientific worker. Four source
mismatches already predate P4. Preserve old hashes/artifacts and keep unverified
old downloads blocked; separate a read-only verification failure from actual
worker lifetime. No broad historical audit, old-source admission or physics rerun.

Keep the shared current cryostat, detector and source anchors; no duplicated files
for every combination. The accepted source-angle function is already implemented,
so do not rebuild it. Add genuinely requested missing monoenergetic gamma energy/
position options through the same configuration/backend, with units and saved resolved
placement. Check geometry/overlap and one bounded case only where transport changes.
Do not expose sliders that the actual backend ignores or admit oversize detectors.

The seven larger models wait for the larger cryostat's real dimensions/materials/
mounting data. Reuse remage's existing interfaces; adopting paper advice is not a
new framework/solver/upgrade project. Stop each option when it actually works and
is documented, without an extra direction-review round.

### P5 — Maintain useful website presentation and later pulse analysis

The website remains saved-results presentation, separate from student runtime files.
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

After each useful change:one related developer verification, concise PROGRESS update,
normal commit/push, close owned idle tools and release the owned lease. No extra
reviewers or new evidence directories. Do not manufacture work when the usable
requested outcome is complete. Do not call software/data presentation validated
physical detector response. Report implemented, tested and input-dependent items
separately; retain scientific identities, signs, nulls, units and independent gain.
