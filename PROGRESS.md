# Project state and next bounded work

Updated: 2026-10-02 UTC. This compact handoff governs delivery order.
Full preceding history is immutable
[at 6fa7bf3](https://github.com/Kunming-CN/END2END_Ge_Simulation/blob/6fa7bf35097a5c51b7f81f77a3d81183034f1f04/PROGRESS.md).
Inspect terminal receipts, hashes and actual processes before repeating work.

Owner resumed after the application update. Actual root launch is Sol 6.1 Ultra
in this project; outer owner `km-polarity-v1-root`, host39260, heartbeat
`automation` ACTIVE. State is running and the owned lock prevents duplicate
rounds. Both ring 10K workers have exited and terminal verification passed.
Current bounded work is M13f: synchronize the accepted four-detector saved
website and perform exact live validation. Local checks and all three independent
AI reviews with reciprocal concrete discussion have passed.
No radiation, SSD, calibration or pilot rerun is needed for this publication.

## M13 science completed; four-detector local website accepted

The delivery authority is [tools/RING_10K_PLAN.md](tools/RING_10K_PLAN.md).
M13a unified reader is already delivered at `viewers/events.html`; both old
entry URLs remain strict aliases preserving model, primary and pulse-group IDs.
Original AK02/SAP22 10K and million-decay data remain exact and permanent.

M13b-e terminal cases under `.local/ring-cs137-v1`:

| Case | Initial decays | Zero-Ge | Groups | Accepted | Native failures | Electronics rejects |
|---|---:|---:|---:|---:|---:|---:|
| GeRC02 Li50min | 10000 | 9703 | 297 | 231 | 4 | 62 |
| KMRC01_candidate | 10000 | 9769 | 231 | 230 | 0 | 1 |

GeRC02 is an independent 280 C / 50-minute annealing variant; original 30-minute
YAML bytes stay unchanged. Only annealing time changes, never a direct minutes-to-
thickness conversion. Unchanged KM retains its candidate qualification and
-370 V bias. Nominal ring mounting, units, transforms, overlap/membership and
separate 500 keV injection checks passed. Model 78 K and explicit runtime 77 K
remain distinct. These are functional engineering checks, not calibrated Li CCE,
physical FWHM, experimental mounting or measured-waveform agreement.

Each matching 500-decay pilot passed cleanly before its own 10K admission.
Ge pilot:479 zeros/21 groups/19 accepted/0 native failures. Original KM pilot
preserves497 zeros/3 negative groups/3 electronics rejects. Owner-authorized
KM-only fixed -1 electronics wiring plus independent negative-charge injection
then accepted all3, without repeating radiation, field or drift. Raw signed
samples, original flags, calibration and rejection history remain retained.
Three independent Sol6.1 Ultra AI INITIALs froze before real peer exchange;
all FINALs accepted admission. Their receipts are in `.local/ring-delivery-v1`.

Ge terminal `production-GeRC02-COMPLETE.json`, finished18:05:09Z: native drift
2048.070s, field26.215s, electronics7.019s, remage6.461s, supervisor2196.642s;
peak RSS1,474,600,960bytes. Its4 failed groups are560/1519/3230/5212, each group0,
exact ArgumentError "Noncontact endpoint outside crystal". Unknown charge,
endpoint and readout stay null. Status completed_with_native_failures.

KM terminal `km-production-COMPLETE.json`, finished21:59:25Z: native159.058s,
field22.554s, original electronics6.221s, fixed-wiring derivative10.363s,
negative injection0.325s, remage6.289s, supervisor328.431s;
peak RSS1,358,864,384bytes. Status completed; original positive electronics
still records0 accepted/231 rejects. The current230 accepted groups use one
independent slope, never Edep-derived eventwise gain or abs/rectification.
Calculation times are separate from coding, review, tools and publication.

Original44/51 source pins and31 execution receipts were verified before the
portable runtime change. The exact old runner and fixed private basis remain
under `.local/ring-cs137-v1/source-basis-v1`. Current runner changes only its
owner-specific Julia path to Path.home(); `ring_saved_basis.py` exposes two
closed read-only verifications for the registered completed campaigns. It
cannot launch, resume, write receipts or execute archived code. Current new-run
admission still checks current sources strictly. Actual14 boundary tests pass;
old receipts and full scientific outputs are unchanged.

Both full saved exports completed without science: unchanged HDF5 raw reader
used the existing locked remage environment after updated Windows Python lacked
h5py; no installation. Native geometry inspection used existing Geant4 only.
FULL bundle `.local/ring-publication-v1/bundle`, manifest e9ff0c6c1272d258dcfdd109055b8642587caf3ad1cde5fed2cb3334a03503d6,
has267files/1,536,656,831bytes and is permanent. Initial failed exports, source
freezes and error logs remain. Zero-energy Ge rows are preserved in native truth
and excluded only from positive pulse groups; exact raw-row/sign checks pass.

Real source-reader regression passes all764 groups and40000 primary IDs,
including39236 zero-Ge primaries,39016357 Object.is scalar checks,83156 signed
zero checks, all14897 KM saved raw samples and4 null Ge failures. Ten binding
mutants, six stale races and three overlay failures pass. This is a minimal-DOM
reader check, not browser/layout or physics acceptance. Evidence:
`.local/ring-delivery-v1/reader-real/SOURCE-01-SUMMARY.json`.

M13f saved web derivative is complete at `.local/ring-publication-v1/web-bundle`,
manifest773e9529ad19b5ff0c48113957248e15d0754429026d7f09d4774332632b6860:
225payload files/211,149,029bytes. All200 raw-event gzip chunks decode to the
exact originals; selected overlays and every complete ZIP ledger member remain
byte-exact. No precision, identity, sign, failure or null is dropped. Direct signed
signals/JSONL scalars/JSON histograms remain; large redundant downloads honestly
open complete ZIPs. The permanent1.537GB full bundle and unique failed derivatives
remain local. Both web package and existing site fit the1GB hosting limit and
95MiB/file margin without repeating radiation, SSD or calibration.

`build_site.py` generated the four-case hub/home/model entries, shared20-stage
spectra and four-model unified reader. Final JSONL guard failure preserved a
complete frozen stage; after the narrow guard fix, `--finish-staged` fully
validated and atomically installed that exact generated payload without copying
or rendering again. All1680 payloads match the frozen stage,14 producer sources
remain frozen. Local build677031855afa9c2b80643b0fc3d26b5fc703010979e352d487b7574fffd3aa48
has979,165,418payload bytes,100HTML pages and2888checked local links. Manifest
SHAf5b8c78e562abde89615171aac2425ae67c688dc63bc83a96eec70deae0f1b71.
The recovery CLI now also refuses junction/linked ancestors and prints its
summary. Subsequent budget review now includes manifest bytes and always budgets
the exact generated serialization when re-sealing an existing compact manifest;
32publication tests pass. The complete installed deployment is979,504,351bytes,
including338,933manifest bytes, within1,000,000,000. The real `check_site.py` passed;
the post-deployment invocation will also exercise this final narrow budget fix.

Generated reader regression passes764groups/40000primaries/39236zero-Ge,
39,016,621exact scalar and83,156signed-zero checks. Four null photon identities,
all14897KM raw samples,4Ge native-null failures,10binding mutants,6stale races,
3overlay failures and2full-gzip-unavailable cases are retained/tested. An initial
fault-test assumption treated all raw chunks as uncompressed; its failed log is
preserved and the updated harness separately checks overlay decoding and absence
of all decoding. Production viewer/data needed no fix.9navigation/6ring-reader/
4ring-site/26spectrum/27contact/12package/14saved-boundary checks also pass.
Actual IAB checks cover four-model selection, zero/failure identities, both old
deep links, native raw/adapted traces,20spectra and homepage/card/download links.
390x844viewport checks pass for event/hub/spectrum without horizontal overflow;
this is not physical-phone, Safari or second-machine acceptance.

Common frozen AI review packet is `.local/ring-delivery-v1/PUBLIC-REVIEW-PACKET-01.json`
(d60bfd261d13f9787617ae31e60508e28d636d7caf64e908d99b06788d1465a6).
All three independent INITIALs froze before reciprocal concrete discussion.
Physics/electronics, integrity and the NEW strict FINALs accept publication with
zero verified blockers. Physics/integrity addenda and the strict review confirm
the final narrow manifest re-sealing budget fix and its32 passing tests.
Discussion distinguishes41removed archive-only files from56total ZIP members,
exact zero-Ge census from the[0,5)keV bin, and true Object.is negative zeros from
a byte-substring count. KM3239 is near-zero positive(+7.001380755584819e-17keV),
below-threshold rejected;19tiny positive transient samples retain their original
sign along with14647negative/231zero raw samples. No waveform is rectified.
The exact Git tree export passes saved validation using published14producer
sources with no private.local/raw/cache/basis, in the existing Python runtime.
This is not second-computer setup or scientific reproduction acceptance.
Nonforce Git synchronization and exact live validation remain release steps.
Retain all failure evidence; do not repeat completed science for release.

## Retained website and postponed work

The pre-M13f public build8bff93f is byte-exact against the saved baseline. Prior
M13a and gamma presentation checks/publication are recorded in the immutable
handoff and `.local/m13a-unified-viewer-v1`, `.local/remage-adoption-v1`.
The gamma example honestly retains40 truth IDs, six selected responses,
four positive/two zeros and34 unprocessed/null responses; no fitted prediction.

M12 discovery/Topics, contributions, CITATION and branch-policy work are
recorded in the prior handoff. Root LICENSE still requires the owner's explicit
choice and rights scope. Search Console requires the owner's Google login and
ownership/indexing actions; no account action is fabricated. These block only
their own tasks. Remage-paper adoption is a deferred TODO after ring delivery;
reuse existing findings rather than starting another research round.

M8/M9 second-computer newcomer acceptance stays deferred. All old10K/1M raw
archives, HDF5, inputs, field caches, DONE/COMPLETE and unique failures are
permanent. No new million-decay task, global settings/environment install,
reset credits or separately billed API is authorized. Unknown experimental
dimensions limit physical claims, not this explicitly nominal engineering flow.
Finish the authorized four-detector delivery before expanding scope.
