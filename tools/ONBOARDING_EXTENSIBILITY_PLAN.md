# New-student usability and scenario extensibility plan

Owner request, 2026-09-29 local. **Planned, not implemented or accepted.**
This adds M8-M11 after the current M4-M7 roadmap. It does not reopen the deferred
M3 preamplifier, hardware-filter, noise or optimum-resolution work.

Two existing Astra reviewers independently discussed this plan and exchanged
findings. They are planning advisers, NOT the two future project-naive testers.
The future tests require new threads without this project's history.

## Current owner disposition (2026-09-30)

Current follow-up (2026-10-01): M7a's bounded SAP22 native-readout and checkpoint
recovery is delivered alongside the retained AK02 route; see
[its checked private-input scope](NATIVE_READOUT_INTEGRATION.md).
The separate saved-site organization milestone below is implemented, locally
tested and accepted after independent AI reviews and actual peer discussion;
publication and exact live verification are pending. Neither change reopens
fresh-machine trials or changes the later M8-M11 delivery order.

M8 and M9 are DEFERRED until a second computer is available and the owner reopens
them. Fresh-machine installation aspects of M7 are also not attempted on this
working computer. No new-student clones, environment installs or global settings
changes are authorized by the current development request. M10/M11 remain later
planned backend/UI/extension work, without claiming deferred novice acceptance.
M4 and bounded engineering M5 are delivered; their accepted limits remain.
M6's installed-interface assessment retains the existing readers; the unavailable
reboost/simflow operation is deferred, not accepted. See
[the M6 decision](M6_INTERFACE_ASSESSMENT.md). The requested useful M7 adapter
is delivered within its recorded engineering scope.
Preserve one working
project and synchronize its tracked source/configuration/lockfiles with GitHub.
The two regular agents now use GPT-6.1-Sol Ultra. Each completed milestone also
receives a fresh third-party Sol Ultra detail AND goal/direction review.

## Delivery order and terms

Do not reopen completed M4 or bounded M5. The optional M6 assessment has a
recorded keep-current decision; proceed to one useful M7 physically checked
adapter. Fresh-machine reproduction waits for the second computer. Report
blocked optional items and their disposition explicitly; never call a deferred
item complete or let an unbounded research topic silently replace the roadmap.
Then execute M8 discovery trials, M9 no-source-edit improvements, M10 mouse-driven
control, and M11 extension proofs. Freeze one release per acceptance milestone.

- **No source code required:** a student can install documented prerequisites,
  select a supported preset, enter settings through prompts, run and inspect
  using documented commands/menu, without editing Python, Julia, C++, YAML/JSON
  or diagnosing internal source code. Dependency installation is separate.
- **Mouse-driven routine use:** after setup, start through a visible launcher,
  select fields/files and run through the interface without a terminal.
- **Extensible:** supported assets and placements change through configuration;
  genuinely new unsupported geometry/physics may need a documented developer
  adapter once. This does not promise arbitrary uploaded geometry will work.

## Website links and information organization

Owner addition, 2026-09-30: the public pages are cleaner, but links and information
still feel scattered. Plan a separate saved-display milestone using existing
generators and the single maintained Windows guide. It can proceed on this
computer; it is not the deferred fresh-user or installation acceptance.

- Keep a clear main route from the homepage to detector overview or current
  results, then event/geometry details. Consolidate competing or repeated links
  and give return links a predictable destination.
- Label current million-decay results, earlier 10k examples and archives clearly;
  retain original URLs/fragments, scientific downloads and immutable evidence.
- Correct stale capability/status text, including the guide's electronics-replay
  NOT_IMPLEMENTED label and historical M5a/charge-only status. Link delivered
  replay/checkpoints and bounded native-readout without implying generic launcher
  recovery, arbitrary-input support or fresh-machine validation.
- Keep 17 viewable models distinct from checked executable detector/scenario
  combinations. Put setup in the maintained guide and detailed history behind
  methods/advanced links; do not add another beginner tutorial or framework.

Before implementation, inventory the reachable current links and define one
bounded change with explicit entry/destination rules. Accept it only after local
link/fragment and applicable navigation/publication checks plus desktop/mobile/
keyboard review, a strict independent direction review and peer discussion.
Build with `tools/build_site.py`, publish through the approved workflow, verify
the live build, and synchronize tracked local/GitHub sources. Read saved data;
no physics rerun, precision reduction or rebaseline is part of this task.

## M8 - Two genuinely new-student trials (DEFERRED)

When reopened, create two NEW sessions using the then-authorized model policy, and separate source-only checkout
and output roots. Give a neutral task and public GitHub URL/user guide only.
Launch from a neutral authorized working directory and check automatic instruction
injection, so project AGENTS/history cannot silently provide the solution.
Do not supply maintainer hints, internal handoffs, prior reviews, private .local
results, field caches or answers. Exclude those from the permitted trial inputs.
One trial can follow the documented download route; the other the documented
Git route. The novice should not need Git if a download route is advertised.

Before starting, fix supported OS/runtime expectations, event/disk/time ceilings,
permitted installation actions, pass conditions and assistance policy. Inventory
preinstalled runtimes. A clean checkout on the owner's configured computer is
NOT fresh-machine installation evidence; test that separately in an authorized
independent environment. Do not create VMs or install system tools implicitly.

Each tester must discover the project purpose, locate setup, prepare permitted
prerequisites, configure a small supported run, execute it, find/interpret output,
and exercise documented inspect/stop/resume behavior. Missing capabilities stay
missing. Record commands/clicks, screenshots, errors, elapsed setup/run/interaction
time separately, source/dependency identities, result receipts and help requests.
Writing source, undocumented repairs, borrowed private data or covert help means
that attempted workflow failed the no-code criterion; retain the evidence.

Also critique the GitHub landing page, menus and reachable pages: purpose and
first action, duplicate/outdated instructions, clutter/history, failed links,
example-vs-calculation distinction, supported-vs-viewable models and limitations.

Deliver two independent reports with reproducible blocker/major/minor findings,
then exchange them. Neither self-reported success nor an exit0 is sufficient:
verify the run's actual stage/census completion and correct output identity.
Developers fix outside the frozen trial. A now-informed tester's retry is regression
evidence; a new discovery test needs another new thread. These are AI usability
proxies, not claims of human-student testing or universal OS support.

## M9 - No-source-edit workflow and clear public entry (DEFERRED)

Repair observed M8 blockers through the existing backend/menu and one maintained
user guide. Keep README short: Browse results / Install / Run / Inspect; separate
one-time setup from everyday use. Keep engineering history and detailed caveats
reachable but out of the beginner's main path; retain original evidence/archive
links instead of deleting unique results. Do not create competing tutorials.

Provide supported presets with named units, defaults, plain error messages,
configuration save/load, preflight, progress, safe stop/resume and result opening.
A student should not edit a schema file to select ordinary supported settings.
Unsupported combinations must be disabled or explained before computation.

Acceptance: a supported small example and one saved-configuration variation run
using only the guide/menu, with no source/config-file hand editing or hidden inputs.
The student can find results and explain what completed, failed or remains assumed.
Tests include spaces/non-ASCII checkout paths where supported, missing dependencies,
invalid settings, interruption and repeat output-name refusal. Report unsupported
platform/path cases honestly. Keep failure evidence and measured interaction counts.

## M10 - Mouse-driven local execution interface

Start with a dependency check and a small prototype, not a new frontend framework.
A desktop launcher may open a local browser interface. It must call the SAME
backend/configuration/preflight as the CLI, not a second implementation.
GitHub Pages remains a static saved-results viewer, not a hosted simulation service.

Proposed flow: choose example/custom -> cryostat -> detector -> source/type/pose ->
geometry preview -> events/numerics/electronics -> preflight/reuse plan -> explicit
Run -> progress/log/status -> results. Hide advanced controls by default but save
all resolved values. Show unsupported choices and why; 17 viewable geometries do
not imply 17 executable models. Never silently replace a user's selection.

The backend owns queued/preflight/running/stop-requested/stopped/failed/completed
states and allowed transitions. COMPLETE requires committed stage/group results
and census validation, not merely a successful process exit. Stop preserves partial
evidence; resume verifies provenance. Show actual known progress, not invented ETA.

Acceptance: default run and a supported configuration variation completed with
mouse-only routine interaction; equivalent CLI/GUI configurations and results;
invalid input, double launch, stop/resume and reopen-after-disconnect tests;
visible files/results, accessible keyboard/focus and readable screen layouts.
No silent administrative install, overwritten output or background computation.
Bind only to loopback; protect control requests with session token/origin/CSRF
checks, structured arguments (no shell eval), safe file roots and no executable
uploads. Retain one-writer locks and event/disk/resource limits.

## M11 - Demonstrate bounded scenario extensibility

Keep versioned ASSETS separate from placed INSTANCES and backend adapters.
Cryostat assets supply dimensions/materials/placements or vetted GDML plus metadata.
Detector assets supply geometry, contacts, impurity and bias; instances define pose
and the Geant4-sensitive-volume/SSD/readout mapping. Source definitions distinguish
mono-particle generation from isotope decay, including spectrum, spatial distribution,
position/orientation, time policy, weights and initial-event normalization.

One validated scenario drives both transport and SSD mappings. Require explicit
units and coordinate frames, rotations/transforms, supported shapes/materials,
containment/overlap checks, readout-contact mapping and capability/version checks.
Do not infer a source is outside the housing or a detector fits merely from a
preview image. Unsupported physics/geometry requires a reviewed adapter, not
arbitrary source-code execution from an imported configuration.

Three minimum extension demonstrations:
1. Change a supported source type/isotope and allowed position through configuration;
   verify physical placement, emission/decay identity and event normalization.
2. Swap a second validated compatible detector without editing the runner; verify
   dimensions, voltage/contact/field inputs and a bounded positive full-chain result.
3. Register ONE independently vetted cryostat preset/adapter with documented data
   and extension hooks; run geometry/mapping tests then a bounded positive example.
These prove those combinations, not arbitrary geometry compatibility. Keep a
capability matrix and public example bundles so outside contributors can add one
asset/adapter with tests, without rewriting the pipeline or GUI.

## Shared contracts to preserve from M4 onward

Record these design constraints now; do not build a schema overhaul or GUI early.
The future scenario separates geometry assets, placements/transforms, sources,
electronics, numerical controls and versions/capabilities. Existing saved formats
remain readable through explicitly supported adapters; no provenance rebasing.
The effective configuration, input/model/source hashes, original event/group IDs,
zero-primary ledger, null failures and termination flags remain traceable.

| Change | Reuse boundary to validate |
|---|---|
| Plot colors/axes/navigation | Saved display only |
| Electronics settings within existing time support | Eligible complete charge only; new independent calibration/result |
| Grouping/time horizon | Re-evaluate support and group membership; not automatically readout-only |
| Bias/impurity/charge-transport settings | New relevant fields/native response; transport reuse requires matching material/geometry |
| Physical cryostat/detector/source geometry or radiation definition | New transport for the new setup; keep old run immutable |

Preflight returns structured supported/unsupported reasons, dependencies, planned
stages, reuse decisions and resource bounds. A display/model label never authorizes
execution. Capabilities should use stable IDs and versions rather than scattered
hardcoded GUI options. Every physical response correction has one owner to avoid
double dead-layer loss, charge loss, noise or resolution broadening.

Planning evidence: `.local/charge-reuse-v1/` contains two original reviewers'
independent planning and reciprocal discussion. No fresh-student trial, GUI,
extension acceptance or new hardware calibration is claimed by this document.
