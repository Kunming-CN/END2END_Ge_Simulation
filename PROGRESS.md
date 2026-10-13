# Current handoff

Updated: 2026-10-13. Read this before starting work.
Immutable prior Co60/software delivery and retained earlier history:
[82824413](https://github.com/Kunming-CN/END2END_Ge_Simulation/blob/828244131be24c663eae4f646b181ae0fdf2f619/PROGRESS.md).
Immutable initial software audit:
[28472988](https://github.com/Kunming-CN/END2END_Ge_Simulation/blob/2847298875e6407bd2607f7ba93bf5558af0ea67/PROGRESS.md).

Owner clarification, 2026-10-13: the software and supporting interface are for
desktop computers. Mobile adaptation and phone acceptance are removed from the
active plan. Preserve earlier phone-width audit evidence as history, not a future
improvement requirement or gate. Desktop keyboard/mouse, plot readability and
workflow clarity remain in scope.

## Owner-requested software audit and pulse-shape plan

The owner approved adding staged pulse-shape development, then requested a
strict whole-software audit, a knowledgeable defender and importance-ranked
improvements, explicitly including the interface. This round changes planning
and records only. No radiation, field, drift or electronics calculation,
installation, application implementation, global setting or automation change.
Automatic continuation remains PAUSED.

Three actual new AI agents launched with explicit gpt-6.1-sol/ultra: strict
adversarial auditor, independent software defender, and new independent
goal/detail adjudicator. They first reviewed separately, then exchanged concrete
findings and counterarguments. Launch settings are recorded; the current tools
do not independently expose live model/effort introspection. These are AI reviews,
not human certification or an exhaustive audit of every file/condition.

The maintained tools/NEXT_DEVELOPMENT_PLAN.md now includes PSD1 full saved-waveform
features, PSD2 explicit waveform acquisition and PSD3 a bounded A/E/classifier
comparison. Event census, signed signals, independent calibration, label/split
integrity, sample uncertainty and inconclusive results remain explicit. A small
engineering example is not classifier-performance evidence. Real laboratory
spectrum/I-V/C-V publication remains deferred to November2026 and complete owner
inputs; original AK02/SAP22 measured waveforms were not saved.

Confirmed audit priorities, still unimplemented:

1. STRICT-01/P1: proven pre-worker batch launch failure lacks a safe supported
   reconciliation, blocking later Control and ordinary CLI work across reopen.
   Do not clear unknown workers merely because driver is null.
2. STRICT-02/P2: generic-isotope histogram normalization is incorrectly named
   for660-663keV photons; actual source-specific denominator arithmetic is retained.
   Correct a versioned interpretation/new export without rewriting old science.
3. STRICT-03/P2: unchanged2.5s polling replaces run/recovery controls and loses
   keyboard focus. Root confirmed Show stages BUTTON to BODY in actual Chrome.
4. UI-PRIMARY-CONTRAST/P2: enabled ordinary16px white-on-#008a96 CSS has4.137284:1
   contrast; observed disabled screenshots are exempt, not the claimed failure.
5. UI-ANGLE-READINESS/P3: environment-check label says preview/execution pending
   while the current angular admission note/capability correctly permits Check/Run.

Active interface improvements: clear desktop blocking reasons/next actions,
selected-run/settings context and pulse/status hints in primary selection.
Earlier320/390px plot/form observations are historical only; do not carry them
into the implementation queue or treat them as measured desktop defects.
Root checked public home/results/teaching/guide/geometry/stage-spectra and local
model eligibility, environment/invalid-input prompts, saved zero-event browsing
and keyboard focus. Scoped320/390px pages had no page-level horizontal overflow.
Run/Download/Save As and scientific Stop/Resume were not activated.

Evidence is `.local/software-audit-v1/`: LAUNCH/SOURCE-FREEZE, independent initial
records, strict reproductions/cross-review, defender response, third adjudication,
ui/browser-evidence, ui/routes-evidence, a checked narrow-plot screenshot and a
preserved blank Control capture (not visual acceptance evidence). The initial
socket-restricted browser failure and successful protected loopback retry remain
recorded; no security/browser settings changed. Original science, frozen code,
models and generated public files remain unchanged. No full suite, physics,
fresh-machine or screen-reader acceptance is claimed. Phone acceptance is out of scope.

The new terminal COMPLETE.json must record final documentation checks/source
preservation, normal Git synchronization and owned lease/server closure. Do not
repeat the audit or physics merely to recover an interrupted reply.

## Accepted software baseline and retained limits

Prior Co60/software delivery is completed at82824413 with its terminal receipt in
`.local/co60-software-delivery-v1/COMPLETE.json`. Ten compatible configurations
share Cs137/Am241/Ba133/Co60; forty choices are factorized software coverage, not
forty physical validations. Seventeen models are viewable; seven need a larger
cryostat. Source/capsule angle and the checked student software ZIP are delivered.
Source ZIP excludes docs; ordinary full clone/history still includes website data.
Dependencies and exact upstream setup inputs remain a separate preparation step.

Co60 retains all500 original primaries,491 zero deposits, eight accepted groups
and one audited below-threshold rejection with ADC0/Erec null. Same-contact charge
accuracy, calibrated CCE, physical resolution, experimental agreement and global
numerical convergence remain unvalidated; no retuning or fabricated waveform.
All completed campaigns, caches and unique failed attempts remain permanent under
tools/DATA_RETENTION.md; no further broad cleanup or radiation rerun is authorized.

## Next bounded work

Use the ranked audit in tools/NEXT_DEVELOPMENT_PLAN.md. First implement only the
safe proven-not-launched reconciliation for STRICT-01, with targeted mock/race and
existing sealed-recovery checks. Other confirmed fixes follow by priority; then
PSD1 starts from one full-resolution saved engineering case. This audit authorizes
no new science campaign, classifier training or recurring continuation. Follow
actual student blockers; keep physical accuracy research separate from delivery.
