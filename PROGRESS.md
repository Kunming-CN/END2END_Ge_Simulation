# Current handoff and next development plan

Updated: 2026-10-07 UTC. Read this before starting work.
Prior full handoff/planning is preserved [at bf0ccee](https://github.com/Kunming-CN/END2END_Ge_Simulation/blob/bf0ccee5f2cff06baa781238a1202cc2a8afaaf6/PROGRESS.md).
The complete M13/M14 history remains [at 9b73383](https://github.com/Kunming-CN/END2END_Ge_Simulation/blob/9b733834c245834658151a2d31f092a1b2bd5305/PROGRESS.md).
Inspect terminal receipts, hashes, actual processes and owned lock before repeating work.

## Current state: shared-source milestone accepted

This shared-source milestone began from clean synchronized baseline
`20bd82512c8326cf9a73136a0a4b0b03b8bdfd0e`. Automatic heartbeat remains PAUSED;
M5 is closed and M15a accepted. Real M15b execution/M15c arbitrary-count UI remain
unfinished; M8/M9 fresh-machine acceptance still requires the owner's second PC.

One immutable source registry and one shared nominal world/placement record now
compose source physics with the five existing detector/readout connectors. All
17 models remain inspectable; five have computation connectors. Am241 uses the
existing Cs137 global point [0, 37.073, 0.290] mm. The cryostat geometry, models,
operating variants, signed contacts and source anchor were not retuned. Source
orientation controls remain future work. Cs137/gamma/SAP18 saved contracts and
original source hashes are preserved; no per-combination template was added.

Three preselected SAP22 cases used 500 initial nuclei each, radiation seed
26092631, one thread, +700 V and the frozen model/native/electronics/anchor settings:

| Source | Accepted groups | Zero-deposit primaries | Native failures / readout rejects / saturation | Admission |
|---|---:|---:|---|---|
| Am241 | 9 | 491 | 0 / 0 / 0 | Promoted after unchanged source gate passed |
| Ba133 | 21 | 479 | 0 / 0 / 0 | Promoted after unchanged source gate passed |
| Co60 | 8 | 491 | 0 / 1 / 0 | Completed processing; remains disabled |

Exactly 1500 new initial primaries were run, with no scientific retry, seed/count
change or tuning after outcomes. Co60 event 475 was genuinely below the fixed
readout threshold; the gate is unchanged. The three geometry-file SHA256 values
are identical: `2f865826f961502b4760abf8a036b3ea1a294df2538fdf5d8026f209b510f805`.
These are three actual SAP22 source cases plus factorized software admission for
five detector bindings, not fifteen actual source/detector science acceptances.

Am241's native science succeeded in 49.915 s, but its original CLI returned exit 1
because outer validation expected a status field absent on successful scalar
records. The narrow `tools/decay_validation.py` correction and explicit saved-data
completion retained immutable `FAILED-run.json`, the original science bindings
and failure basis. That completion used science_calls=0; ordinary Inspect passed.
Co60 and Ba133 completed through the normal CLI. Runs are retained under
`.local/runs/source-{am241,co60,ba133}-500-v1/`; no science was regenerated.

Control shows source policy and collapsible identity from the registry; stale
Check/import replies and saved-run identities remain fenced. Real Chrome passed
all ten Am241/Ba133 selections across the five computation connectors and the
four disabled-control protections for view-only AK01. The 17 curated artifact
entries under Explore events → Reproduce or analyze this saved run cover resolved
settings/completion, raw transport/ledger, signed signals and independent
calibration. CLI acceptance roots were not silently imported into Control.

Integrity finding I-001 is closed: Download now returns original artifact bytes
through the same protected route; HTML viewing retains derived navigation links.
The correction passed 39 HTTP/controller tests, JavaScript contracts and an exact
HTTP byte/SHA check of the saved Am241 HTML, independently rechecked. Original
INITIAL and correction evidence are retained. The actual browser download
destination file/checksum remains unconfirmed after the original tool waiter
timeout; the HTTP proof does not establish that destination.

Seven exact-path Git byte rules preserve the acceptance-bound source/configuration
bytes, including the existing mixed-line-ending CMake input. During the Git
byte-protection correction, all 108 frozen source SHA256 values stayed unchanged; raw/clean Git hashes agree, and all 26 staged
production/test files match their original bytes after the recorded CMake index
refresh. No scientific file was rewritten for Git normalization. Evidence is
retained under `.local/source-switch-v1/`, including the original and corrected
staging receipts. The separated Am241 outer validator and I-001 download repair
are necessary acceptance/provenance corrections within this milestone.

The two scoped independent FINAL reviews (physics and integrity) and the NEW
independent third FINAL accept the bounded milestone with no unresolved blockers.
Their recorded peer exchange found no remaining disagreement. These are scoped
AI engineering reviews. The
20-primary option is a smoke check and may yield only zeros; 500 primaries are a
bounded example, not numerical convergence or physical validation. Neither the
runs nor review establish physical detector identity, surveyed source placement,
calibrated CCE, physical resolution or experimental agreement. Students still
need documented installed runtimes and pinned upstream inputs; second-PC/M8/M9
acceptance remains deferred. No installation/PATH/WSL/global change or website
publication occurred; `docs/` remains the existing published snapshot.

Final revision, live-main synchronization and owned-process/lease cleanup are
recorded in `.local/source-switch-v1/COMPLETE.json` and `.local/autonomy/state.json`;
verify those and actual Git before further work. The next bounded task is
the retained M15b real serial execution acceptance: one preselected two-batch case,
<=500 total primaries, with the recorded acceptance-only cap. This round does not
start M15b. Co60 event 475 may be diagnosed from saved data in a separately chosen
step; it is not a prerequisite and does not authorize new computation. M15c,
source angles and the 12 view-only model adapters remain future work. See
[the maintained detailed plan](tools/NEXT_DEVELOPMENT_PLAN.md).

## Preserved preceding milestone: student UI accepted

Owner priority (2026-10-07): make the existing English local browser useful for
Prof. Mei's students. The preserved student UI milestone began at verified main/live origin
ab66a72cf4fae3e3eccc251c912ab0b58118e25a. Automatic heartbeat remains PAUSED. M5 is closed; M15a is
accepted; real M15b execution and M15c arbitrary-count UI remain unfinished.
M8/M9 fresh-machine acceptance stays deferred until a second computer is provided.

All 17 catalog models are selectable for inspection: five registered computation
connectors and 12 view-only models. Contact IDs/signed voltages, model types and
reference/candidate/scenario qualifications come from maintained sources.
Checked saved previews and existing public rotatable geometry are available;
view-only selections disable Check/Run/export. Stale Check/import/preview replies
are fenced, and saved run/results retain their original identities. GeRC02's
preview remains the frozen Ge30min base, separate from its Li50min operating case.

SAP18 was enabled after its first and only preselected 500-decay run sealed
COMPLETE: 15 accepted groups, 485 zero-deposit primaries and zero native failures,
readout rejections or saturation. Original −380 V contacts and 0.8 mm model
readout width remain intact, with stored 78 K/runtime 77 K, own fresh fields and
one independent negative 500 keV injection through fixed −1 wiring. Its physical
identity is unresolved and placement nominal; no experimental dimension,
calibrated CCE, physical resolution or convergence claim is made.
Configuration: 8ffc022282bd289557770187156aa3ceb31ff3c045535b918e7dbb04aa1f20e0.
Sealed run: .local/runs/student-sap18-500-v1/.

Validation: 116 affected Python tests, JavaScript browser contracts and 28 Julia
checks passed. Actual browser acceptance covered all 17 previews/selections,
390×844 mobile layout, GeGI's full 34-contact disclosure, keyboard focus and final
five-connector availability. The actual 500 run used the shared CLI; no GUI500
rerun or fresh-machine/human-student trial is claimed. Ordinary post-promotion
Inspect verified all 56 artifacts unchanged; only exact capability registration
differs from the original accepted source closure. Scientific receipts/hashes
were preserved. Measured solve/replay/readout/export wall time was 48.553 s,
excluding Julia startup and preparation/preflight; full response command 82.992 s.
Calculation, validation, development/tool and review wall times remain separate.

Two scoped independent gpt-6.1-sol/ultra AI reviews and a NEW independent third
review accepted the milestone. One integrity P2 was corrected in the test only:
the SAP18 source check now uses public protected tracked-source hashes instead
of ignored milestone-private history. Its eight tests and unavailable-private-
snapshot proof passed; the integrity reviewer independently closed that finding.
Original INITIAL freezes/reports and the complete private before/after evidence
are retained. These are AI reviews, not experimental certification. Review once
per integrated tested substantive milestone; re-review only verified corrections,
with no new cycle for this final documentation update.

No website build/publication, installation or global environment change occurred.
Source tools/site_guide.html is updated; docs/ remains the existing published
snapshot. Evidence and correction/review receipts: .local/student-ui-v1/.

## Preserved preceding milestone: M15a accepted

The owner explicitly requested verification recovery and continued development on
2026-10-04. This is one manual M15a milestone; automatic continuation remains
PAUSED. Actual root and all four implementation/review launches use gpt-6.1-sol
with ultra effort in this project. No scientific worker was active at launch.
The clean checkout fast-forwarded to the owner's a323b65 upload; original root
`google82c89328d0f5dbe9.html` bytes remain preserved.

Google verification is actually complete for the URL-prefix property
https://kunming-cn.github.io/END2END_Ge_Simulation/.
The referenced chat "解释验证失败原因" and open dialog targeted the GitHub
repository URL instead. The correct property's settings report "You are a
verified owner". Its homepage now reports "URL is on Google" and "Page is indexed"
on 2026-10-04, superseding the earlier pending indexing status. Correct Console
homepage inspection is left open. No repeated verification/index/sitemap request
was submitted. Sitemap report still says "Couldn't fetch"; the current Google
live test confirms Crawl allowed=Yes, Page fetch=Successful, Indexing allowed=Yes.
That unresolved sitemap report is not claimed Success. Private screenshots,
DOM proofs and GOOGLE-RESULT.json are in `.local/product-delivery-v1/m15a/`.

MIT remains adopted for original software/maintained documentation; third-party
model/data/upstream rights remain separate. Website payload, model hashes,
scientific producers/data and environment locks are unchanged. Existing build
785fd3cfe9f2a542b467cf934042304d046a9ee4acafdc0df125da7a8e55b0f0 passed
13 discovery tests, 32 site tests and exact live verification of all 696 selected
artifacts (1686 total files, 104 HTML pages, 3129 links, 982889216 payload bytes).
The bundled Python's initial GBK decoding failure is retained; child-only UTF-8
passed without editing tests/global settings. No website regeneration or physics ran.

## M15a implemented: exact count and serial batch preview

`tools/workflow_batches.py` owns pure count/partition/seed/identity/census rules.
The existing resolver now serves a versioned preview-only CLI action and protected
loopback route; old v1 Check/import/execution/saved validators and the English
Control form keep their original restrictions. [Contract](tools/BATCH_PREVIEW.md).

- Exact positive integer admission rejects booleans, floats, strings, unsafe
  numbers and rehashed rule/config edits. Numeric, seed and resource limits differ.
- Lazy batches are capped at 10000, with exact disjoint zero-based global IDs.
  Versioned radiation seeds depend on master seed and batch index, not total/name/
  time/order. Numeric seed uniqueness does not prove independent engine streams.
- Raw local IDs, file/table/row/Track/Vertex keys, delayed times, zero deposits,
  null failed charge and signed values are preserved. Pure census checks compare
  literal beamOn, raw simulated count and every initial ledger ID.
- Preview creates no run root/reservation/Start token. V1 Run and GUI Start refuse
  it before lease/state/science writes. Remage runtime readiness, actual raw reader,
  native global row/group seeding, execution and resume remain M15b.

61 focused tests passed: 11 batch, 18 legacy workflow, 16 controller, 16 protocol.
Actual CLI preview 25001 produced 10000+10000+5001, seeds
26092631/26197360/26302089, in 1.143432 s, with zero science calls and no run root.
This is configuration-check wall time; detector calculation time this round is 0.
Boundary tests include 1/499/500/9999/10000/10001/25001 and a constant-size capacity
preview; no large radiation task was used to prove partition arithmetic.

Implementation writer exited before source freeze and three independent AI INITIALs.
Physics/electronics and transport/workflow reviewers found no implementation blocker;
a NEW strict reviewer accepted the goal, direction, complexity and bounded value.
Each verified identical frozen hashes and recorded only tests actually executed.
The physics review found one P3 prose denominator error: local census coverage is
0..batch.primary_count-1, not parent batch_count-1. Corrected documentation only;
all executable/test hashes remain unchanged. Actual reciprocal peer findings
exchange is complete; all three FINAL receipts accept the bounded M15a preview.
These are AI reviews, not scientific or experimental certification.

Current round evidence: `.local/product-delivery-v1/m15a/implementation/`,
`reviews/`, Google proofs and completion receipt. Initial failures are retained.
The earlier four 10K Cs137 cases, all40 gamma primaries (29 zeros/11 positive,
0 unprocessed), original six responses, 1M campaigns and existing gallery/viewers
remain preserved; do not repeat science or older completed reviews for recovery.

## Queued computation milestone: M15b

Follow [the detailed plan](tools/NEXT_DEVELOPMENT_PLAN.md): real serial workers,
once-only compatible geometry/fields/independent injection calibration, complete
streamed initial ledger, global native seeds, sealed stage/batch receipts and safe
Stop/Resume. Bind census to the effective native macro and checked actual raw
reader; the M15a helper does not expand arbitrary control/include macros.
One preselected real two-batch acceptance uses at most500 total primaries and a
recorded immutable acceptance-only cap below10000. No count escalation to find a
pulse, source/seed retuning, giant task or new PDE/CCE delivery prerequisite.

Then M15c connects exact count/batch status and complete lazy event access in the
existing English form. M16 enables real source energy/pose, ring gamma and
cryostat/model options individually. No enabled capability without bounded actual
acceptance. M8/M9 remain deferred until a second computer. No new environment,
global configuration, reset credits, separately billed API or million campaign.

Automatic heartbeat remains PAUSED. New manual work must inspect Git, actual
processes, terminal receipts and the lock; this round releases only its owned
`.local/autonomy/round.lock` after normal synchronization; the final local COMPLETE
receipt records exact Git synchronization and lock release. Do not enable automatic
continuation or restart completed transport/SSD/readout to recover a reply.
