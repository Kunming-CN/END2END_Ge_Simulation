# New-student usability and scenario extensibility plan

Current owner disposition,2026-10-07: the second-computer M8/M9 acceptance task
is removed from the delivery backlog. Develop usable shared workflows and improve
setup/use from actual student feedback. This does not certify an untested fresh
installation, and does not authorize installs/new environments on this computer.
The [original plan and history](https://github.com/Kunming-CN/END2END_Ge_Simulation/blob/cb285557f9d1458a0314da4e7e02da93700ae677/tools/ONBOARDING_EXTENSIBILITY_PLAN.md)
remain preserved. M3 preamplifier/noise and deeper physical validation stay separate.

M4/bounded M5 and M10 local Control are delivered with recorded limits. M6 retained
the installed readers; unavailable reboost/simflow remains deferred. The current
cryostat admits ten configurations and Cs137/Am241/Ba133 through shared backends,
with exact counts, serial batches, boundary Stop/Resume and saved analysis access.
Gamma remains fixed20; Co60 admission and seven larger models remain unchanged.
See PROGRESS.md for actual scope and receipts. Further M11 extensions are bounded
one at a time, without model/source configuration copies or mandatory research gates.

Use existing engines/environment, keep one working project, and synchronize tracked
source/configuration/lockfiles with GitHub. Development and substantive integrated
reviews use actual gpt-6.1-sol/ultra settings; follow AGENTS.md for review frequency.

## Delivery order and terms

Do not reopen completed M4 or bounded M5. Current priority is usable Control,
accurate public entry and one useful extension at a time. Actual student feedback
starts concrete fixes; it is not a future-device delivery prerequisite. Preserve
failed/partial evidence and report only validation actually performed.

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
computer using saved inputs; it does not claim fresh-installation acceptance.

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

## Student feedback and no-source-edit use

The owner removed the planned second-computer trials. Keep one maintained guide
for Browse / Setup / Run / Analyze and fix concrete student-reported blockers
through existing components. Useful reports identify OS, project revision, selected
detector/source/count, failing step and exact error or run name. Do not ask students
to publish private paths, credentials or large raw inputs. Missing installation
evidence stays unperformed; never replace it with a simulated success claim.

Ordinary supported settings should use Control without source/config-file editing.
Preserve explicit dependency checks, units/defaults, progress, safe boundary
Stop/Resume and saved results. Unsupported combinations must be explained before
computation. Reproduce a reported issue with the smallest necessary case, retain
its failure, and stop after a verified useful fix. No new feedback platform is needed.

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
