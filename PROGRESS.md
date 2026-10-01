# Project state and next bounded work

Updated: 2026-10-01. This compact handoff governs delivery order.
The full M11b/M11a/M10 handoff is immutable [at 650fe30](https://github.com/Kunming-CN/END2END_Ge_Simulation/blob/650fe30ceef6fe0e78b66778f15fe1486aa77bdc/PROGRESS.md).
Keep detailed receipts and failures local; recover completed artifacts after chat failure.

## M11c: actual gamma charge, injection and electronics accepted

One additive orchestration reuses completed M11b gamma streams and existing field
caches, with no new radiation or field solve. Fixed pre-outcome cohorts AK02
IDs0/4/5 and SAP22 IDs0/2/3 retain whole Ge rows, original IDs and flight/deposition
delays. Each detector retains its complete20-primary truth object ledger; the
other17 responses are explicitly unprocessed/null. Forty truth primaries total.

Exactly4 positive whole-event native calls completed; all4 reached analog shaping,
peak ADC and accepted non-null Erec. Two independent500keV synthetic delta-charge
injections provide fixed per-detector gain, never per-event Edep normalization.
Two selected true zeros bypass native drift; their labeled known-zero electronics
inputs produce ADC0, below-threshold rejection and null Erec, with null native
endpoints. Radiation truth remains distinct from weighted charge and Erec.

| Detector / initial ID | Truth Edep keV | Peak ADC | Erec keV |
|---|---:|---:|---:|
| AK02 / 4 | 188.04479325569585 | 150 | 187.45991067126093 |
| AK02 / 5 | 662.0 | 530 | 660.7806153561722 |
| SAP22 / 2 | 477.65824134837163 | 383 | 477.6802374912197 |
| SAP22 / 3 | 17.97684717135484 | 14 | 18.060921626134775 |

Original78K model snapshots stay exact; existing77K cache override is explicit,
contact1=0V/readout1 and contact2=+500V AK02/+700V SAP22. Native settings remain
16 independent weighted parcels, seed2609261, diffusion,2ns/nominal10us cap,
zero-field termination off, no self-repulsion. AK02 retains39/544 and156/1632
step-limited carrier endpoints; SAP22 has0/512 and0/224. Geometric contacts and
caps remain separate from weighting completion. Near-truth induced charge does
not establish recoverable Li charge, calibrated CCE, depletion/grid convergence,
experimental agreement, physical resolution, efficiency or as-built geometry.
Tiny signed current/shaper excursions, all endpoints and ADC rejection survive.
The analog numerical grid is not waveform-digitizing acquisition; natural10us
shaping tail and isolated event reset remain explicit.

Only expected_primary_count=3 differs in generated resolved electronics; typed
whole-value gates reject rehashed setting/type edits. Default native-failure policy
remains abort; this actual run explicitly chose record before outcomes, limited to
the two existing native-domain ArgumentErrors. Unexpected errors still abort;
unknown failed quantities stay null. This run had no native failures or top-up.

Final26Python fixture tests and54Julia mocked/byte assertions pass; fresh Julia
wrong-kind check refuses before cache loading. A scoped review found the request/
cache consumed-byte seam; canonical model/cache/path/pin checks and bounded same-
buffer hashing before parse/deserialization fix it. Exact inventory excludes only
root receipts; nested matching filenames remain covered. V1 source/tests/reviews
and initial descriptor/sandbox failures are retained, never silently rebaselined.
Successful Python source3734c580/Julia sourcef7959bb1 have separate v2 archives.

First actual launch failed with OSError opening an inherited WindowsApps Julia
alias during the executable-hash read, before output reservation, Julia launch,
cache deserialization or science. Inputs may already have been hashed. Failure
receipts remain exact; a new launcher explicitly selects the already tested Julia
binary for that child only. No fallback, installation or global setting change.

Actual launcher69.573899s; native stage28.462000s includes immediate integrity
hashing and first-call compilation, not independently measured pure SSD drift.
Injection stages0.344000s/electronics2.672000s; cold imports/validation/other worker
overhead and coding/AI-review wall time remain distinct from detector computation.
Existing Julia1.13.0/SSD0.11.8/JSON1.9.0, two Julia threads/one child BLAS thread;
exact executable, loaded source and19 executed-code snapshots are recorded.

Independent root saved-data audit passes303029 general typed/binary64 scalar
comparisons, including truth, response, settings and CSV, not a source-only count.
All10057 signed input samples survive; old2450 records and25 new preservation
records remain exact. Three independent INITIALs, actual reciprocal discussion,
three correction deltas, actual two-peer exchange and three independent actual
FINALs accept. Their final findings/direction exchange is recorded locally. These
are AI reviews, not human certification; reviewers did not rerun physics/tests.
Evidence .local/m11c-gamma-native-v1/; contract tools/GAMMA_NATIVE_EXAMPLE.md.
This source/handoff delivery uses normal Git synchronization; exact terminal
commit parity is recorded locally. Website payloads are not regenerated here.

## Retained delivery and permanent science

M11b at650fe30: two actual20-gamma transport cases, complete40-primary ledger,
1127 physical material rows/248 Ge rows; independent20845 raw scalar comparisons,
measured remage6.832556s. Cold helper failure and corrected source remain exact.
M11a source4d73bd9/publicatione103ad4/handoffdb442ff: four native geometry-only
preparations, v7 input-byte binding and full live458-file check of build689c80cd.
M10 Control.cmd at5861f07 retains its checked Cs137 backend and recovery; it does
not acquire gamma execution from M11c. Seventeen viewable models are not seventeen
executable adapters. Original measured pulse waveforms were not saved.

.local/cs137-1m/ radiation COMPLETE and original archives/HDF5/DONE/COMPLETE are
permanent science. The completed_with_native_failures million native campaign
retains truth, errors and unknown nulls. No rerun or cleanup is authorized here.
Production Li/depletion/grid accuracy remains separate from functional delivery.

## Next bounded work

Skip M8/M9: second-computer newcomer acceptance is deferred and blocks no M11.
Next is the owner's GitHub links/information cleanup: one clear maintained
tools/site_guide.html#local-routes chooser with prerequisites/outcomes/actions,
preserving section IDs, scientific/download URLs and backend eligibility.
Use build_site.py, required publication/link/contact checks, desktop/mobile/
keyboard inspection, scoped AI reviews/NEW strict review and actual discussion,
normal Publish.cmd, full live check and Git parity. Saved science only; no new
framework, precision reduction, manual docs edits or installation experiments.
Future M11 cryostat-preset proof requires independently vetted input/dimensions;
do not invent geometry or label the current nominal asset a new validation.

Current-chat30minute heartbeat ACTIVE creation verified; future execution
unobserved, legacy scheduling unverified. Only ready/no owned lock/no active
workers permits a new supervisor. Acquire lock before writes; keep one writer.
