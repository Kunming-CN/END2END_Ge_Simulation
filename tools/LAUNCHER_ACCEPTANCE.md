# Bounded launcher acceptance and remaining scope

Current follow-up: the saved-run inventory/settings checks and read-only inspector
are documented in [INSPECT_RUNS.md](INSPECT_RUNS.md). The account below preserves
the earlier acceptance round; its then-next Pages work has since been delivered.

Date: 2026-09-28. This is engineering regression evidence, not experimental validation.
The complete owner-approved roadmap remains in `../PROGRESS.md`; these tests do not
replace the pending GitHub Pages first-visitor, detector-subpage and guide work.

## Saved positive native-response regression

`simulation/test_guarded_saved_input.jl` reads the preserved `cs500-v4` streams and
calls `GuardedNativeResponse.main` with actual CLI arguments. Each model retains
500 primaries: 496 zero-deposit records plus four positive groups. Original IDs,
row indices and timestamps remain unchanged. Radiation seed is 26092631; native
seed family is 2609261, with 16 parcels, 2 ns drift steps and a 10 us cap.

An explicit **test-process-only** replacement supplies hash-pinned saved fields;
it never calls the field solver. Cache bytes and baseline receipts are pinned.
The test retains freshly parsed detector/configuration, independently copies an
allowlist of solved-state fields and checks runtime/project, model/includes,
settings, bias, source hashes and field fingerprints before response execution.
Comparisons cover all scalar/truth/endpoint/trace records, histograms, independent
injection calibration and byte-exact signed signal CSV. Preservation checks run
in `finally`, including on a failed test; previous results are never overwritten.

This does **not** validate uninstrumented `Run.cmd` positive orchestration, a cold
field solve, a public arbitrary-cache import interface or clean-machine reproduction.
The serialized caches are fixed maintainer fixtures, not redistributed artifacts.
Missing or incompatible fixtures abort; there is no fallback to new simulation.

## Source-only same-machine clone preflight

`tools/test_clone_preflight.py` creates a real local Git clone without hardlinks,
checks out source directories and overlays an explicitly hashed set of candidate
runtime files. It runs the Windows launcher from another working directory through
a path containing spaces. No owner data, upstream geometry or field caches are copied.

The executed check inherited installed Julia/package caches and Ubuntu-24.04, but
reported the clone's locked transport environment, LBNL originals and exporter as
missing. `Run.cmd check` correctly returned **2** with preparation guidance;
`run ... -DryRun` also rejected the incomplete setup. No run directory, upstream
fetch or exporter build was produced. Runtime source hashes stayed unchanged.
This is **successful missing-prerequisite detection**, not successful installation
or an independently ready computer. The exact base revision and candidate source
hashes are recorded in the local acceptance receipt.

The transport version probe now uses `pixi run --locked --no-install`, preventing
implicit environment installation or lockfile changes. Check/setup return nonzero
when readiness is incomplete; installing dependencies remains an explicit action.

## Commands and evidence

Maintainer-only positive regression (requires the pinned private saved fixtures):
`julia --startup-file=no --threads=2 --project=simulation simulation/test_guarded_saved_input.jl .local/NEW_positive_acceptance`

Windows clone/preflight regression:
`python tools/test_clone_preflight.py --output .local/NEW_clone_acceptance`

## Recorded outcomes

Evidence root: `.local/launcher-acceptance-v1/` (private maintainer evidence).
The initial `positive-v1` passed 59 assertions and preserved 112 files. One bounded
review-hardening repeat, `positive-v2`, passed **64 assertions** and preserved
**149 files** byte-for-byte with unchanged sizes and modification times. Each
run handled the same eight positive groups and retained all 1,000 initial records;
these are two regression executions, not 1,000 newly generated decays. Final
signed signal CSVs are byte-exact against the frozen baseline for both models.
No Geant4 transport or field solving ran. Original production checkpoints were
neither resumed nor rewritten. The v1 executed source remains in local evidence.

`clone-v1/acceptance.json` records the source-only negative preflight. The original
workspace also passed the modified no-install check (`main-check.json`: exit 0,
ready true), while the clone's check correctly returned 2. The focused PowerShell
scenario tests and pinned transport version check both returned 0.

## Deliberately unfinished capabilities

Positive uninstrumented `Run.cmd` orchestration, fresh-machine installation and
full reproduction, and public saved-transport/cache import remain unvalidated or
unimplemented. Strengthening mandatory response artifact/source inventories and
explicit native seed/parcel/field checks belongs to the next low-code hardening
work, with rehashed-mutation fixtures. Do not misdescribe these as completed.

The next saved-data-only Pages milestone is independent: remove duplicated
detector navigation, add lightweight saved previews and concise detector/gallery/
technical levels, label earlier 10k event links, preserve old fragments and update
the maintained guide. No website redesign was published by this acceptance round.

## Scoped reciprocal review

The original site-UX and workflow reviewer threads were resumed, not replaced.
Three bounded rounds exchanged their findings: acceptance/Pages gaps, the scope
of test-only cache regression versus a new public import feature, and inspection
of executed final evidence. Both final read-only reviews closed this milestone
with no remaining blocker. These are AI source/evidence reviews, not independent
experimental certification or re-execution of the controller's tests.
Local review results and numeric exit receipts are under the evidence root as
`site-ux-r1/r2/r3-*` and `workflow-r1/r2/r3-*`. No reset credits or separately billed
API fallback were used. The complete Pages deliverable remains explicitly next.
