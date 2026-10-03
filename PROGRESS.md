# Current work and delivery order

Updated: 2026-10-03 UTC. Read this handoff before starting a round.
The complete M13 delivery record is immutable
[at db9c864](https://github.com/Kunming-CN/END2END_Ge_Simulation/blob/db9c864fd5718b643a92cb280c5e684c897960b8/PROGRESS.md).
Inspect receipts, source hashes and actual processes before repeating work.

## M14: owner-requested usable software and presentation

The owner now prioritizes a real mouse-operated end-to-end application, then
complete gamma responses, clearer plots/public pages and verified local cleanup.
Control executes checked AK02/SAP22 and both ring configurations through the
shared GUI/CLI workflow. Existing-machine four-detector execution is verified;
portable source preparation is next. Do not claim fresh-clone acceptance yet.

Root is executing M14a under `.local/autonomy/lock`, owner
`product-framework-v1-root`, actual gpt-6.1-sol/ultra in this project.
Do not start a second supervisor or duplicate scientific workers. The bounded
plan and independent planning evidence are in `.local/product-delivery-v1`.
The backend and gamma planners froze their INITIALs before reciprocal discussion;
the newcomer website audit is independent. These are planning reviews, not
implementation acceptance. Each substantive implementation still requires two
scoped independent reviews plus a NEW strict reviewer, frozen before discussion.

Delivery order and acceptance:

1. **M14a — working local application.** One English Control application with
   independent detector/cryostat/source selectors and settings bound to actual
   execution. Reuse the protected local server, existing environment and scientific
   stages. A shared closed configuration resolver serves GUI and CLI. Start uses
   the exact checked configuration; changing a selection invalidates that check.
   First connect actual AK02/SAP22 Cs137 and fresh 662 keV gamma scenarios, then
   bounded single-ring adapters. All four current detectors must be accessible
   before claiming the four-detector application complete. Do not invent a second
   executable cryostat or expose options that the worker ignores. One generated
   `.local/runs/NAME` root; real stage states, receipts, logs, settings and results.
   Stop is cooperative at a stage boundary; uncertain/incomplete work is inspected
   rather than overwritten. A real bounded nonzero end-to-end run is required.
2. **M14b — complete saved gamma example and readable plots.** Retain all40
   original primary IDs and old6 response bytes. The remaining34 are27 known
   zero-input readouts and7 positive native-charge events; no radiation/field
   rerun is needed. Use independent useful time ranges for charge, current,
   preamp collection edge and shaper, with full saved windows available. Existing
   gamma preamp samples need a dense electronics-only derivative to reveal the
   early edge; zoom alone cannot restore missing samples. Preserve exact old peak,
   ADC/Erec/flags, signs, intervals, caps, delays and null numerical failures.
3. **M14c — English public gallery and newcomer navigation.** Put a model image
   and clear detector type on every detector card. Keep provenance in secondary
   details. Fix obsolete ring-pending text, inconsistent return routes, unnecessary
   front-page detail and Chinese UI references. Audit every public HTML page and
   outgoing link, distinguishing actual browser visits/clicks from HTTP checks.
4. **M14d — classified local cleanup.** Remove verified useless duplicate staging
   and reproducible scratch with exact deletion/dependency evidence. Permanent
   science, unique failures and recorded input dependencies remain unchanged.
   Never follow junction targets during deletion. The two original computation
   workspaces still have active dependencies and must not be casually moved.

Build website output only through `tools/build_site.py`; run relevant tests and
`tools/check_site.py` before normal nonforce Git synchronization, then verify the
exact deployed site with `tools/check_site.py --url`. Do not edit `docs/` by hand.
Freeze scientific/export sources before hash-bound export. No new environment,
global PATH/settings, reset credits, separately billed API or million-decay task.

## M14a1 verified application slice

The English local application selects the modular cryostat, AK02/SAP22, nominal
Cs137 (20/500 primaries) or a fixed 662 keV gamma beam (20), and eleven actual
electronics settings. Check is read-only; changing the form invalidates it.
Pipeline captions/settings belong to the selected saved run, independently of
the next-run form. Stages, logs, complete primary identities and four original
signed waveform SVGs are available inside the application. Known zeros retain
zero input and null reconstructed energy; failures retain their original evidence.

Actual mouse acceptance completed SAP22/gamma20 with gain21: all20 primaries,
15 zero-Ge, five accepted responses, no unprocessed/native failure/readout reject.
One independent500keV injection calibrated the selected electronics. Response
stage70.754s (including potential22.646s/native7.881s/electronics1.592s); this is
measured computation, not coding/review wall time. Original complete radiation
was copied losslessly from the preserved cold-entry failure; it was not rerun.
Denied launch01 and failed cold-entry02 remain unchanged. New terminal data are
`.local/runs/m14a-gamma-ui-03`; final source/mouse/review evidence is under
`.local/product-delivery-v1/implementation` and `reviews`. The final source freeze
is `M14a1-LEGACY-GUARD-DISPLAY-SOURCE-FREEZE.json`.
Two independent scoped AI reviewers and a NEW clean-context strict reviewer
accepted this slice after frozen initials, reciprocal discussion and final repairs.
Caption binding, original-SVG access and false legacy prerequisite findings are
resolved. Relevant protocol/projection/browser contracts and unchanged-site
checks passed; the website snapshot itself was not regenerated in this slice.

## M14a2 verified ring application slice

The same English application now executes GeRC02 Li50min and KMRC01_candidate
with Cs137, selected seed,20/500 initial decays and selected electronics. New
fields are solved; original30-minute GeRC02 and KM0/-370V contacts are unchanged.
KM raw signals stay negative; the fixed-1 electronics wiring uses one independent
negative500keV injection. All500 original IDs and signed charge/current/preamp/
shaper plots are selectable; zero input retains null reconstructed energy.
Changing the next-run form leaves saved model/event/group identity unchanged.

Actual mouse acceptance: Ge500 has478 zero-energy events,22 pulse groups,
18 accepted/4 electronics rejects/0 native failures; KM500 has488 zeros,
12 accepted/0 rejects/0 native failures. Ge response283.411s; KM response87.547s,
core52.119s excluding preparation/preflight and separate0.234s calibration.
These are measured computation times, not development/review wall time.
Ge completed response was finalized without recomputation after a derived-sum
1-3ULP validation mismatch; raw identities remain exact. KM continued only
response/results from23 byte-exact prefix files after a receipt-publication
interruption. Its original27 files, pending receipt and failure log remain exact;
unobserved original ledger exit/time remain null. Atomic progress publication
now has unique pending names and finite Windows sharing/access retries; a
secondary receipt failure cannot mask the original exception.

Terminal roots: `.local/runs/m14a2-ge-ui-01` and `m14a2-km-ui-02`; root mouse
acceptance, source freeze and review evidence are under the existing M14 bundle.
The30-source freeze is `M14a2-KM-PUBLICATION-SOURCE-FREEZE.json`.
Relevant semantic/tamper/publication/protocol/browser tests passed. Two scoped
AI reviewers and the NEW independent strict reviewer accepted after frozen
initials, direct reciprocal exchange, fixes and actual mouse-evidence review.
The owned preview and worker processes are closed. Website snapshot unchanged.

Next bounded slice: M14a3 admits a paired portable source/exporter adapter and
explicit existing-environment setup into GUI/CLI. The private candidate and
contract are design evidence only; preserve historical guards and all old science.
Then complete M14b/c/d, reusing the frozen gamma plan, newcomer audit and cleanup
proofs. Focused local waveform ranges remain M14b; current full-window plots are
functional acceptance only. M8/M9 second-computer acceptance remains deferred.

## Completed science and publication: reuse, never redo

M13 is complete and synchronized: HEAD baseline
`db9c864fd5718b643a92cb280c5e684c897960b8`; publication
`0709447d215f8394224ebf2455ba76dfe04f6410`.
Build `677031855afa9c2b80643b0fc3d26b5fc703010979e352d487b7574fffd3aa48`
is979,504,351bytes including its manifest. Exact live checks passed691artifacts;
local checks passed1680files/100HTML/2888links. M13 receipt:
`.local/ring-delivery-v1/COMPLETE.json`. The old preview and workers are closed.

| Case | Initial decays | Zero-Ge | Groups | Accepted | Native failures | Electronics rejects |
|---|---:|---:|---:|---:|---:|---:|
| GeRC02 Li50min | 10000 | 9703 | 297 | 231 | 4 | 62 |
| KMRC01_candidate | 10000 | 9769 | 231 | 230 | 0 | 1 |

GeRC02 is the separate280 C/50-minute Li variant; original30-minute YAML is
unchanged. KM remains the original candidate/-370 V model. Owner-approved
KM-only fixed -1 wiring uses separate negative-charge injection calibration;
raw signed signals and original positive-electronics rejection history remain.
Ge failures560/1519/3230/5212 group0 retain exact error/null output.
KM3239 is near-zero positive, below threshold, not exact zero. Both matching
500-decay pilots passed before10K. Calculations and unique failures are permanent.

Original AK02/SAP22 10K and million-decay radiation/native data are also permanent.
Keep `.local/ring-publication-v1/bundle` (full267files/1.537GB), web-bundle,
all raw/archive/HDF5/configuration/COMPLETE evidence and the14 frozen producer
sources intact unless a new, explicit derivative/source contract is reviewed.
The four-case public entry is
[10K results](https://kunming-cn.github.io/END2END_Ge_Simulation/results/cs137-10k/index.html).
The unified viewer `viewers/events.html` preserves both old deep-link aliases.
These are nominal engineering results, not measured-waveform agreement,
calibrated Li CCE, physical FWHM or experimentally established mounting.

## Postponed items

M8/M9 second-computer acceptance and remage-paper adoption remain TODOs.
Root LICENSE needs the owner's explicit choice/rights scope. Search Console
needs the owner's Google login/ownership/indexing actions. These block only
their own tasks. Unknown experimental dimensions restrict physical assertions,
not the explicitly nominal application framework. Finish the authorized M14
work before expanding scope.
