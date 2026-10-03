# Contributing to GeSignal

GeSignal — HPGe Radiation-to-Readout Simulation welcomes focused fixes,
documentation improvements and reproducible scientific reports.
The repository remains `Kunming-CN/END2END_Ge_Simulation`; its addresses stay unchanged.

## Fork, branch, pull request

1. Read [README](README.md), [PROGRESS](PROGRESS.md) and the relevant
   [source ownership entry](tools/MAINTENANCE.md) before changing a component.
2. Fork the repository to your own GitHub account and work in your fork;
   no collaborator grant on the owner's repository is needed.
3. Create a descriptive branch in your fork and make one bounded change.
4. Open a pull request to the project's default branch. Explain the problem,
   resulting behavior, checks actually run and remaining limitations.
5. The owner reviews the change, requests fixes if needed, and decides whether
   to merge. Keep discussion and proposed changes in the pull request.

Use the existing setup guide; this document is not another installation route.
External contributions use the PR and owner-review route above; they do not need
write access to this repository. The owner retains the configured administrator
exception for the existing tested, reviewed maintenance workflow. This exception
is not a promise that protection flags constrain every administrator action;
project policy forbids force-pushing or deleting the default branch.
Required checks must correspond to checks the project actually runs.
A normal clone, documented CLI example or manual contribution does not need the
owner's private automation state or supervisor lock.

## Edit the maintained source

- Follow [tools/MAINTENANCE.md](tools/MAINTENANCE.md). Never hand-edit `docs/`;
  website output is generated through `tools/build_site.py`.
- Keep the single Windows setup authority in `tools/site_guide.html`.
- Preserve model bytes, hashes, relative includes, catalog status and assumptions.
  Propose model or physics changes deliberately with provenance and owner review;
  never silently change bias, impurity, geometry or carrier physics to pass a test.
- Keep raw computation, private caches, machine paths and unique failure evidence
  local. Never submit credentials. Manuals, photographs, slides or raw inputs
  require a specific reason and prior owner review.
  Follow [retention rules](tools/DATA_RETENTION.md); completed science is permanent.

## Choose relevant checks

Use the documented existing runtime and record exact commands and results.
Documentation-only edits do not require physics reruns or unchanged exports.

| Change | Relevant checks |
|---|---|
| Website sources | Matching generator tests; `python tools/test_site.py` and `python tools/check_site.py` before publication; `tools/test_contacts.py` for contact views |
| Canonical model handling | `python tools/export_models.py --validate`; reviewed byte/provenance changes require explicit review |
| Local control | Matching `tools/test_local_ui*.py` tests and `node tools/test_local_workflow.js` for frontend behavior |
| SSD runner/parser | The two lightweight validation commands in [simulation/README.md](simulation/README.md): parser tests and `--check-models` in the pinned project |
| Transport/readout | Matching component tests and a bounded regression appropriate to the changed stage |

Report unavailable dependencies, skipped checks and unperformed browser checks.
Mocks, static review and smoke tests are not numerical convergence or agreement
with experiment. Keep these claims separate; 17 viewable models are not 17
LBNL-executable models. Do not install new environments just to extend a PR's scope.

## Report a physics or data issue

Include the commit, exact software versions and environment/input hashes,
command, detector/source configuration, random seeds, units and actual timings.
Record the truth, selected, zero-deposit, incomplete and null-response census.
Keep all deposits of an event together and retain event IDs, creation times,
signed signals and endpoint/cap/rejection flags. Edep truth and Erec readout are
distinct; calibration must be independent, not adjusted separately per event.
State expected versus observed behavior and a bounded reproduction. Share only
reviewed public evidence; explain private dependencies without uploading them.

## License, citation and credit

The project software license is pending the owner's choice; this guide grants no
license. Consult the root `LICENSE` once adopted and the existing
[software/model/source rights notice](THIRD_PARTY_NOTICES.md). A software license
does not automatically cover model snapshots, data or third-party inputs.
Preserve file-specific provenance and notices.

State who authored your contribution and any existing third-party terms; submit
only work you may lawfully share. Opening or merging a PR does not give the owner
authority to apply a future license to your work. Agree any such grant with its
rights holder before accepting the contribution; no new CLA or DCO is required.
Pinned LBNL cryostat inputs have no recorded explicit upstream license; originals
stay local under the [recorded policy](transport/cryostat-source.json).
Use [CITATION.cff](CITATION.cff) for this software, and cite the upstream tools and
model sources actually used. Record the exact commit; do not invent a DOI, ORCID
or release.
GitHub contributor attribution depends on commit identity and merge rules;
a merged PR alone does not guarantee appearance in its contributor listing.
