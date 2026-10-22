# Current handoff

## Current milestone — 2026-10-22

Finish publication of actual Compton cone intersections, angular density and the
saved conditional map. Root owns direction; ordinary implementation is gpt-6.1-sol
ultra. No additional AI reviews, resets, large campaigns or repeated broad checks.
The owner explicitly stopped further two-bright-spot investigation: the current
1332.492 keV layer has 18 groups. State limited statistics and move on.

The same manual supervisor owns `.local/autonomy/gegi-saved-recovery.lock` as
`gegi-saved-recovery-20261020`; previous ownership and pause records are retained.
Automatic monitoring stays PAUSED. Bounded repair development/calculations and
publication are authorized without repeated permission. Check actual processes,
receipts and `.local/autonomy/state.json` before resuming; do not duplicate workers.
All original science, failed attempts and identities remain permanent.

Detailed preceding evidence is preserved at
[2bf8b5e5fabb](https://github.com/Kunming-CN/END2END_Ge_Simulation/blob/2bf8b5e5fabb610e330109c0c20a9c0cb5f2327d/PROGRESS.md).
Paths below are relative to `.local/gegi-10m/signal-recovery-v1/` unless specified.
Use the receipt hashes and existing tests; do not rerun completed physics to recover
context. `tools/NEXT_DEVELOPMENT_PLAN.md` retains the stage/evidence map.

## Tested software and current publication

Student release `student-runtime-2bf8b5e5fabb` is public and verified: 896158 bytes,
187 members, ZIP SHA256
`4b2790f41a6be34b65a6431a063ec154e44c7ae8f3e6359c46eeb5e1bd773038`.
It contains single-pass readout, optional post-reconstruction two-site selection,
and repaired order weights. Five package tests passed; versioned/latest public
bytes, embedded source commit, receipt and guide link agree. No installation test.
Receipt: `.local/student-runtime-p1/COMPLETE.json`, SHA
`f9c413b38da08d13ac4bc4092867628d5c8f07f454098f725ead758302138b7b`.
Do not rebuild this runtime for website-only edits.

Website publication is in progress using `tools/gegi_saved_publication.py` and
`tools/build_site.py`. Four selectable layers show actual cone-plane curves,
saved angular backprojection and saved conditional image; default1332 has18groups/
36candidate orders. Plane z=40mm, XY units mm. Root inspected the three default
PNGs. No smoothing, new fits, physics or source-truth overlay. Old snapshots remain.
The initial build failed at the historical teaching loader interface; docs were
not replaced. The exporter now uses the existing exact mount/deferred loader.
Intermediate bundles/build failures are retained. Final generator uses the existing
section/nav/anchor layout; the pinned historical site tools remain unchanged.
Final bundle: `validation/order-prior-preservation/publication/final/`.
21 exporter tests and36 final-source site tests passed, plus the affected complete
page transformation and six control-switch checks. Browser/CDP timed out; real
browser control/viewport acceptance is not claimed. Final build/local/live checks
are pending. Failures and exact checks are in publication/validation.json.
Root owns final commit/push/live verification; no hand edits to docs.

## Latest saved-data repair

The approximate free-electron kinematic screen previously redistributed all mass
to surviving site orders. Equal engineering priors are now assigned before that
screen; unsupported orders retain unresolved mass. This is not a calibrated
posterior or additional signal recovery. All18 reconstruction tests pass.

Fixed200development+200holdout and153map checks preserve IDs, energies, candidates
and all nonweight fields. The545group union contains280 original missing-mass
records, still missing. Result:
`validation/order-prior-preservation/evaluation/result.json`, SHA
`27e7788afa17712cfc5d2ff51ce3aa11f13710e237516dde1e4666620de0ceab`.
The initial wrong-directory failure scanned0groups and remains recorded.

The repair has been applied to all434candidate groups/837candidates in a sparse
new derivative. 212groups/323candidate weights decrease; total candidate mass
338.583333 ->262.149306, unresolved95.416667 ->171.850694. All nonweight values
match; all545validated subset records match. Original57613group census retained.
Application plus one changed map took7.054s; map+checks1.581s. Current two-site map
uses153groups/287orders:661/1173/1332layers113/22/18groups. The1332layer is exactly
unchanged. Maps retain the fixed40iteration budget; no convergence claim or more
peak/plane/leave-one-out work. Population result SHA
`e0e6bc42b165e47537dd2a739a828630ca9209b7b64bfdbb3359974dc7433878`,
map SHA`181e261b6e978cc4b1cfb0d7e7859665122c69dae2c7c187871be8bfbb8b9162`,
in `validation/order-prior-preservation/population/`.

Publication evaluation reuses the153group saved posthoc labels/geometry with exact
new candidate keys/weights; no raw truth reads. Strict36correct/39wrong/212unknown
candidate alternatives remain unchanged; these are not hard-choice error rates.
Weighted median charge-centroid3D/absZ/absE errors1.439274mm/0.149247mm/0.373420keV.
Photon-vertex error is separately1.432634mm on80sites. Original unweighted metrics
remain exact. Angular errors are null because the old angle-array order cannot be
proven; do not guess the mapping. Only6development+2holdout groups overlap the153;
145 supplemental groups are posthoc, not a new holdout. Evaluation SHA
`ce0d6d1ff3558250e71ca2b90c5e5a24d75448c128c57a7d6c836e23f61cec4a`.
No additional validated imaging recoveries.

## Reusable full-chain evidence

- Native Geant4 model test:11.3.2/G4EMLOW8.6.1,30000Livermore plus3000Klein–Nishina
  controls, fixed seeds. Free-electron-domain failures125/106/74of10000 at662/
  1173.228/1332.492keV; controls0. Energy closure <=1.04e-13keV. Compile3.227s,
  sample process1.233s. Atomic relaxation off, binding energy local: model diagnostic,
  not detector transport or original event replay. COMPLETE SHA
  `ce02d38a16b9c19f28f0520549c6a776e9af595b345aaa203f0320825096c5ee`,
  `validation/bound-electron-response/native-sampler/`. Do not widen cuts from this.
- Transport-only >2gamma-anchor prefilter rejected: it would remove14743of57613
  groups, including228of414current two-site candidate groups. Seven tests; saved
  scan40.475s. Keep zero-only skipping. Post-reconstruction `--two-site-only` has
  seven passing tests and preserves excluded ambiguity/denominators.
- Fixed400baseline pairing errors3/22development,5/24holdout; optional two-site
  selection0/15,0/16 with false splits1/15,0/16. These are conditional hypotheses,
  not validated hardware recovery. Source truth never enters the inverse.
-153map posthoc:306matched charge cells, unweighted median3D/absZ/absE errors
  1.412926mm/0.135299mm/0.366593keV;80photon vertices in40groups median1.424950mm.
  Parent ancestry gives152single-gamma-lineage groups. First-child attribution
  resolves82groups to two dominant interactions:2correct-only/75both/5wrong-only,
  71unknown;1/5keV sensitivity unchanged.407direct-root deposits remain unassigned,
  max per-group energy0.51656keV. `validation/root-gamma-interaction/evaluation/`.
- Native cell bank:378training points and80independent validation cases. Single-site
  inverse80/80pixels; median/max3D0.010570/0.023088mm. Eight fixed ideal two-site
  mixtures8/8nominal pairings, but cases3/7 nearly degenerate. Raw ideal charge,
  sparse domain, no hardware discrimination claim. All relevant tests already pass.
- Region bank5148records:378imports+4770new drifts,145s, no fields/transport/failures.
  `calibration/native-region-bank/`. Fixed development720929 K1024 refinement:
  2032new+16reused,69.181s; RMS2.754360 ->0.267866keV, correct pairing, centroid
  errors0.0073225/0.0515993mm; opposite pairing93.1220keV. One development case,
  not validated recovery/global optimum. `validation/native-region-720929-k1024/`.
- Full34 original-grid bank:2991points =2551complete+176incomplete+264exclusions;
  original selected-pair parity passes. Original calibration lacked other channels;
  it could not supply them by export. Failed full34 inverse v1/v2/v3 remain retained.
- Guard diagnosis identifies coarse weighting-grid interpolation on3saved paths.
  WP17/20/34 local refinements pass unchanged1e-6update gates. These3potentials do
  not establish all34/global convergence; do not splice them into production or
  force endpoint1/0. Original paths, waveforms and failed solves remain preserved.
- Existing fields are reused per native worker, not solved per event. Five resident
  loads160.649s. SSD0.11.8/Julia1.13Float32,92.3K,-879/0V,-5e9cm^-3,ADL/Bruyneel,
  1ns/max1000steps, no diffusion/self-repulsion. Preserve canonical hashes.
- Single-pass electronics repair:68electronics+74failure-policy assertions and
  6calibration tests pass. Saved benchmark3groups×2:6.990 ->6.410s, exact outputs;
  electronics-only8.30%, not campaign speedup. Nominal circuit tests do not identify
  actual GeGI filtering, noise, ADC, timing or guard observability.

## Original campaign and experimental correspondence

`.local/gegi-10m/campaign` is complete and permanent:1Mprimaries/100chunks,
400kgammas+600kdecays;942395zero,57605nonzero primaries ->57613pulse groups.
The old `.local/gegi-10m/reconstruction-v3` baseline has434conditional groups/
837cones,162mapgroups/393orders. Its original1332layer19/58 is historical.
55591spectroscopy groups,1896incomplete including426native failures,126unresolved.
Keep original nulls/failures, all identities, seeds and denominators. These counts
are not validated detector efficiency. The fixed development/holdout split remains.

Owner-provided Juergen/Noomen emails establish that ImagerPro exports single-site
and two-site .bin events, not multisite or waveforms. N42 FullDetector/AllEvents,
256pixel/PixelTotal and32channel spectra are cumulative: no individualXYZ/dE.
Their selected binary events reportedly reproduce the pixel map; exact population
rules still awaitPHDS. Experimental reconstructed positions are not independent
truth. Do not assume all spectral totals and binary events have one denominator.
BEGe3820waveforms are not needed. Reply draft was delivered; no email was sent.

Read-only local My Drive search found0.n42 and1736.bin files, all simulation/software
artifacts, in4.416s. Two inaccessible paths are project test folders. This is not
cloud-wide absence; prior G:Ge-STAR search was reused. Receipt
`reference-index.experimental-data-search.json`, SHA
`f8ea3f7a23c5034f316fe52b52efc407fd5706f8e173ee307a71f7a0c3181748`.
Private PPT/manual index is `reference-index.json`; do not publish its source files
or private paths. The manual duplicates DataStream type1 and omits GlobalTime units:
no guessed binary parser. Need matched.bin/N42, format/version, acquisition/source
settings and selections. Reproduce the experimental pixel map before comparing
matching spectra; no event-by-event pairing to unrelated simulated events.

The nominal readout bridge is now complete on the fixed8two-site cases. It uses16
original full-duration34-channel records, each with complete carrier endpoints,
existing causal summation/Julia channel_response and the saved global calibration.
No truncated inverse prediction enters readout. Full support90–155ns plus the
existing20shaping-constant/10000ns electronics tail; no new injection or physics.
All272channels and IDs retained:32expected collectors accepted, ADC energy minus
250keV expectation -0.261049 to+0.984532keV. Of240noncollectors,18also have positive
peaks above threshold (up to7.096972keV equivalent), while none passes terminal-
charge collection classification;222below-threshold energies stay null. All current
balances pass, no saturation/window limit. Peak times319–1764ns are separate from
ideal charge t50 times13.269–119.460ns. Terminal charge/t50 are native diagnostics,
not established .bin observables. Positive peak ADC alone cannot identify collection.
Three targeted tests pass; one Julia1thread/BLAS1 execution,15.931s total, exit0.
No inverse fits or production change. `validation/native-pair-readout/result.json`,
SHA`300991905ca16f5a2c69e5a0dd058bd8eea0e9fc55925dfc1c08d9ae66f2be70`;
COMPLETE SHA`b84a29cd13c08fb9b13df7a63975214814a4c658b31533945b7ba448de883c98`.

Next: finish website deployment and exact live verification. The next experimental
milestone is a matched.bin/N42 acquisition with format/settings: reproduce its
selected pixel map and compare matching spectra. Preserve the demonstrated peak/
collection ambiguity; do not invent hardware timing, use native terminal charge as
measured input, or expand the inverse/campaign before defining the actual observable
contract. No more two-bright-spot work and no large campaign yet.
