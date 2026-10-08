# Maintaining the project

The website and the local workflow have different jobs. The public site is a
saved-results browser; `Control.cmd` is the primary local application. The older
generic `Run.cmd` calculation route remains distinct.
The beginner instructions have one authority: `tools/site_guide.html`, published
as `guide.html`. Keep README short and link to that guide rather than adding
another complete installation recipe.

Exact-count campaigns use `tools/batch_execution.py`, `transport/batch_source.py`
and the additive `simulation/batch_native_contract.jl`, `batch_native_response.jl`
and `batch_decay_stream.jl` bridge. The existing workflow CLI and Control delegate
to this shared versioned parent; geometry, native fields and independent calibration
are prepared once, with raw/response artifacts sealed per batch. Count and
recovery contracts remain in `BATCH_PREVIEW.md`. Legacy producers and saved
validators retain their original contracts; generated run-local state stays
under `.local/runs/`.

Student analysis guidance belongs to the existing `local_workflow.html/js`
panel: explain saved file purposes and selected batch/local/global/group joins,
while retaining every original artifact link. Raw LH5 column units and coordinate
transforms are recorded in the stream manifest; they differ from normalized
detector-local fields. Viewing is read-only and download requires an explicit
user action. Do not add a second exporter or mutate scientific records for labels.

## Source ownership

| Area | Edit these sources |
|---|---|
| Home, hubs and navigation | `tools/site_restructure.py`, `site_routes.py`, `site_previews.py`; Results / Detectors / Run locally / Methods share fixed ownership, breadcrumbs and context-aware dataset views. Saved-result anchors `#teaching`, `#gamma`, `#tenk`, `#million` keep different studies distinct. |
| Search descriptions, canonical landing URLs and sitemap | `tools/site_discovery.py` selects indexable formal routes from `site_routes.py`; generated only by `build_site.py` |
| Detector overview/gallery/technical levels | `tools/site_detector_pages.py` |
| Readable GeGI saved-plot derivatives | `tools/saved_plot_repairs.py`; exact original channel/position CSVs produce two SVGs and their checked manifest. `build_site.py` integrates them; original images, coordinates, signed values and uncalibrated position rule remain unchanged. |
| Readable earlier native Li report | `tools/saved_archive_display.py`; one pinned original report keeps all56 SVGs, tables, scripts and settings verbatim. Its display-only lithium wrapper also preserves the strict producer summary and complete scientific body. Only layout, navigation and relative data links change; narrow screens scroll each full-width chart. `site_restructure.py` creates this Methods entry during the saved-site build. |
| Geometry export and validation | `tools/export_ssd_geometry.py`, `geometry_catalog.py`, `ssd_geometry_publication.py` |
| Browser geometry controls | `tools/ssd_geometry_viewer.html` |
| Saved energy-spectrum views | `tools/spectrum_display.py`, `spectrum_plot.py`, `spectrum_controls.js`; see [display semantics](SPECTRUM_DISPLAY.md) |
| Unified GeSignal event reader and old entry aliases | `tools/viewer_navigation.py`, `viewer_navigation.js`, `unified_event_viewer.html`, `unified_event_viewer.js`; see [reader ownership](VIEWER_NAVIGATION.md). Original signed viewers remain frozen. |
| Four-detector 10K hub, report context and saved ring results | `tools/ring_site.py` owns the four directly readable maintained charge/readout reports; frozen original reports stay unchanged. `ring_publication.py`, `ring_scene.cc`; `build_site.py --ring-results` copies completed, checked saved data. The shared spectrum and event readers remain the maintained display route. |
| Ring calculation and signed electronics | `transport/ring_cs137.py`, `simulation/ring_stream.jl`, `ring_response.jl`, `ring_polarity.jl`, `tools/ring_run.py`, `ring_production.py`, `km_ring_run.py`, `ring_model_contract.py`. Use matching clean 500-decay admission before a new 10K; source/configuration checks remain strict. |
| SAP18 Control scenario | Additive tools/sap18_workflow.py, transport/sap18_source.py, simulation/sap18_stream.jl, sap18_polarity.jl and workflow_sap18_response.jl reuse the maintained transport/native/electronics functions and fresh ring run loop. Exact Cs137 nominal20/500 capability is registered after one sealed preselected500 acceptance. Original scenario model, signed −380 V contacts, 0.8 mm readout width and unresolved identity are retained; no historical producer or field cache is replaced. |
| Completed ring campaign verification | `tools/ring_saved_basis.py` has two closed read-only operations for the registered terminal campaigns. It retains original producer hashes and receipts across the exact portable-runtime line change; it cannot start, resume or rewrite science. Its fixed private basis stays local. |
| Windows setup/run guide | `tools/site_guide.html` |
| Contributions, software citation and rights scope | Root `CONTRIBUTING.md`, `CITATION.cff`, `THIRD_PARTY_NOTICES.md`; `.github/PULL_REQUEST_TEMPLATE.md` |
| Catalog inspection in Control | Existing scenario_workflow.catalog() projects models/catalog.json, site_detector_pages.TYPE_LABELS and the capability registry into all seventeen selectable models. local_workflow.js separates viewing from execution; local_ui.saved_model_preview() serves only a known catalog PNG after catalog equality, manifest byte/hash and safe-path checks. Source presets are projected from the single source registry; no general docs file server. Saved rotatable geometry opens the existing public viewer. |
| Shared source presets and anchors | `scenarios/source-presets.json` owns immutable source physics/policy metadata, including the legacy Cs137/gamma display records. `scenarios/placement-anchors.json` owns the reused nominal world, detector frames and source anchor. Additive `transport/decay_source.py`, `tools/decay_workflow.py`, `tools/decay_validation.py`, `simulation/decay_stream.jl` and `workflow_decay_response.jl` compose the same world/detector/source contracts for all five registered connectors. `detector-capabilities.json` source admission changes only after source-specific positive terminal acceptance; preserve old saved receipts and legacy producer contracts. `scenario_workflow.py` source dispatch and `local_workflow.js` metadata projection share Check/import/identity rules. CLI `--bootstrap-source` is the explicit first-acceptance gate, unavailable to GUI requests. |
| Loopback simulation application | `Control.cmd`, `tools/local_ui.ps1`, `local_ui.py`, `local_workflow.html`, `local_workflow.js`, `local_ui_workflow_jobs.py`, `scenario_workflow.py`, `workflow_settings.ps1`, `workflow_inspection.py`, `workflow_recovery.py`, `saved_waveforms.py`, `simulation/scenario_response.jl`, `transport/workflow.sh`; shared checked GUI/CLI configuration, original transport/SSD/readout backends. Retained `local_ui_jobs.py` and `local_ui_gamma_jobs.py` own saved legacy jobs. No public execution service. |
| Exact count, serial batch preview and execution | `tools/workflow_batches.py` owns the retained v2 preview; `tools/batch_execution.py`, `transport/batch_source.py` and additive `simulation/batch_*.jl` own v3 execution/global native seeding. Shared `scenario_workflow.py` CLI and protected `local_ui_workflow_jobs.py`/`local_ui.py` Control routes use the same count, sealed-stage recovery and lazy event-page contract; see [batch contract](BATCH_PREVIEW.md). Old v1 saved validators and fixed20 gamma remain unchanged. Historical WIP/restore receipts are retained, not current blockers. |
| Shared catalog-model calculations | `tools/catalog_workflow.py`, `transport/catalog_geometry.py`, `catalog_source.py`, `catalog_exporter_setup.py`, additive `cryostat_catalog_export.cc` and `catalog_exporter/CMakeLists.txt`; `simulation/catalog_native_model.jl`, `catalog_decay_stream.jl`, `catalog_native_response.jl`. One complete canonical descriptor and shared stage/lease/native/readout route serve the five additional models that fit the unchanged LBNL assembly. New plans have explicit `local_catalog_workflow_v1` authority and protected Check; the original five plans, sources, producers and saved validators retain their legacy contract. Seven larger models expose their actual cryostat-size blockers. `Run.cmd setup -BuildCatalogSourceExporter` explicitly builds the additive source-bound target in the existing locked environment. |
| Scenario eligibility labels | `scenarios/detector-capabilities.json` remains science-bound and unchanged. `scenarios/catalog-presentation.json` is one reviewed public display snapshot from actual common-route eligibility, binding the exact registry, nominal assembly and canonical model hashes. `site_detector_pages.py` validates it for ten supported choices/seven size reasons without private inputs; no backend reads it or admits computation from it. |
| Cryostat source-input inventory | `transport/cryostat-input-ledger.json`, `tools/check_cryostat_inputs.py`, `test_cryostat_inputs.py`; see [input verification contract](CRYOSTAT_INPUTS.md). Curated metadata and opt-in original-byte checks only; no new adapter or native/experimental acceptance. |
| Bounded monolithic native audit | `tools/native_cryostat_audit/`, `cryostat_native_audit.py`, `test_cryostat_native_audit.py`; see [native audit contract](NATIVE_CRYOSTAT_AUDIT.md). Independent structure/source-position diagnostics, no particle transport or adapter promotion. |
| Opt-in source-instance geometry preparation | `transport/scenario_prepare.py`, `scenarios/assets/`, `scenarios/m11a-*.json`, `transport/Prepare.cmd`, `prepare.sh`; see [preparation contract](SCENARIO_PREPARATION.md). This entry prepares geometry and macros only. |
| Finite synthetic gamma transport and raw event stream | `transport/scenario_transport.py`, `test_scenario_transport.py`, `Gamma.cmd`, `gamma.sh`; see [transport contract](SCENARIO_TRANSPORT.md). Separate from the strict Cs137 reader and later charge/readout coupling. |
| Electronics settings and configuration preflight | `tools/electronics_settings.ps1`, `electronics_execution.ps1`, `scenario_cli.ps1`; see [ELECTRONICS_SETTINGS.md](ELECTRONICS_SETTINGS.md) |
| Source-aware bounded gamma charge/calibration/readout | `tools/gamma_native_example.py`, `simulation/gamma_native_example.jl`; see [gamma example contract](GAMMA_NATIVE_EXAMPLE.md). Uses completed gamma truth, existing fields and independently injected calibration. |
| Saved gamma public examples | `tools/gamma_showcase.py` and `gamma_showcase.html` retain the original six responses. `gamma_complete_example.py` and `simulation/gamma_complete_example.jl` own the full40 saved-input completion; `gamma_complete_showcase.py` and `.html` publish its checked bundle. `gamma_publication.py` dispatches the two versions. Do not edit their frozen science/export sources during a presentation-only update. |
| Selected teaching signals | `tools/teaching_examples.py` and `teaching_examples.html` own `spectra/pipeline.html` and its compact JSON. Six exact positive groups from the completed four-case Cs137 10K publications; all original ledgers, source settings and old bare-gamma archives remain intact. Reuse `focused_plots.js`; no physics or analog replay. |
| Focused saved waveform presentation | `tools/focused_plots.js`, `saved_focus_waveforms.py`, `saved_focus_pages.py`, `pipeline_focus.html`; complete saved charge supplies exact original-bin current while sparse analog samples remain sparse. `saved_focus_pages.py` owns receipt-bound display upgrades of the two accepted readers, preserving numerical downloads and original producer/export pins. `simulation/saved_collection_edge.jl` and `saved_control_edge.jl` own explicitly labelled electronics-only display derivatives. Keep full original signed samples, peaks and calibration distinct. |
| Publication check dispatch | `tools/publication_preflight.mjs`, `test_publication_preflight.mjs`, `publish.mjs`; portable fixtures and checked public bundles always run. Private-data regressions skip explicitly only when their recorded roots are absent; present partial/corrupt data fails. |
| Saved-run validation and inspection | `tools/native_run_validation.ps1`, `inspect_native_run.ps1`; see [INSPECT_RUNS.md](INSPECT_RUNS.md) |
| Bounded NEW native-charge group commits | `tools/native_group_checkpoints.py`, `simulation/native_groups.jl`; see [charge-only scope](NATIVE_GROUP_CHECKPOINTS.md). Host acceptance is separate. |
| Local file/result index | `tools/build_local_dashboard.py`, `local_paths.py`, `open_workspace.ps1` |

Shared-source admission uses one source registry and independent detector contracts.
Am241 and Ba133 are promoted through the fixed positive source gate; Co60 remains unavailable
because its terminal 500-primary trial retained one below-threshold rejection.
Every accepted `source_adapters` entry binds the source contract, SAP22/500/seed
26092631 acceptance, positive accepted-group count, zero native failures/readout
rejects/saturation, resolved configuration hash, COMPLETE hash and run reference.
Do not loosen the gate, retune science or rewrite original receipts to enable a
preset. All three case geometries are byte-identical; five-model compatibility is
software factorization, not fifteen actual science acceptances.


The added catalog route brings Control to ten current-cryostat configurations;
seven complete original models require a future larger cryostat. Its five fixed
Cs137/500 public CLI Check/Run/Inspect cases retained all 2,500 original primaries:
2,485 zero-deposit primaries, nine accepted groups, three KL01 native failures
with null unknown charge/readout and three below-threshold readout rejections.
These fixed cases plus the already accepted source contracts are factorized
software support, not thirty actual model/source science acceptances. The current
handoff records exact receipts, actual grids/whole-process RSS, focused review
corrections and publication state. Never rerun physics for this presentation update.

`tools/decay_validation.py` owns the active generic response validation;
`scenario_workflow.py` dispatches to its `response`. The unused
`decay_workflow.response` is retained because its old producer bytes are bound to
accepted evidence; defer cleanup to a future unbound maintenance change. The
Am241 acceptance retained its original native success and failed outer CLI record;
the explicit saved-data completion added no science and preserved FAILED-run.json
and the failure basis. This acceptance repair is not a general GUI finalization
route. Source/world/placement contracts, counts, runtime/producer/model hashes,
raw LH5/ledger IDs, signed native quantities, independent calibration and failure
records remain authoritative. Curated downloads use the existing verified owned-
run artifact route with exact original bytes; HTML viewing retains its derived
navigation. I-001's original INITIAL and closed targeted correction remain retained.
Exact HTTP payload checks do not prove the actual browser destination file. The
promoted-source browser selections passed; current review/synchronization status
is recorded in PROGRESS.md. Own-PC reproduction requires documented runtimes and
pinned upstream inputs; fresh-machine acceptance remains deferred.

The registry's `dataset_lifetime_evidence` annotations describe half-lives. For
example, Np237's 59.54 keV level in the Am241 record has half-life 67.2 ns,
corresponding to mean lifetime about 96.94911 ns. The runtime daughter cap uses the
installed ground-secondary PDG mean lifetime and does not consume this static
annotation. Preserve the already bound registry bytes; clarify this terminology
only in a future versioned metadata change. A 20-primary run is a smoke check that
may produce only zeros; 500 primaries are a bounded example, not convergence or
physical validation.

Never hand-edit generated `docs/` files. Do not alter frozen model files,
scientific results, input identities or calibration to make a display test pass.
The content-addressed geometry assets preserve old published versions.

## Normal publication

From the project root, use `Publish.cmd`. For a source-only navigation update,
the underlying command is `python tools/build_site.py --restructure`: it starts
from the checked saved snapshot rather than rerunning simulations. New saved
geometry exports use the explicit `--ssd-geometry` publication mode.

Normal publication requires the checked `docs/` snapshot. It does not silently
rebuild from private scientific workspaces. A public checkout without `.local`
science skips those saved-data regressions explicitly, while retaining model,
fixture, JavaScript and full public-artifact validation. A present private input
root never excuses missing or corrupt contents.

If generation completed but final publication validation failed, first inspect
and retain the failed stage, source pins and log. `build_site.py --finish-staged`
validates the installed snapshot and the existing fixed `.local/site-build`
stage, then uses the normal atomic replacement. It refuses linked directories
and pending swaps; it never regenerates pages or repeats scientific work.

Before publishing, run the applicable checks:

The complete four-detector snapshot must fit GitHub Pages' 1 GB site limit;
the previous 800 MiB project budget preceded the two ring campaigns. Keep the
95 MiB per-file margin. Ring event chunks use deterministic lossless gzip;
complete response archives retain every original ledger member and exact value.
The checker rejects an oversized snapshot before deployment. Local full bundles
and raw scientific outputs remain permanent and are not constrained by this
website budget.

```powershell
python tools/test_all_detector_pages.py
python tools/test_site_restructure.py
python tools/test_site_hierarchy.py
python tools/test_spectrum_display.py
python tools/test_viewer_navigation.py
python tools/test_site.py
python tools/test_contacts.py
python tools/check_site.py
.\Run.cmd detectors
.\Run.cmd check
```

Use the installed project Python/ParaView Python as appropriate. Original-mesh
comparison additionally needs VTK and the owner's saved geometry; source-only
checks explicitly report that limitation rather than fabricating coverage.
After deployment, verify the actual website with `tools/check_site.py --url`
and the published site address; successful Git push alone is not deployment proof.

## Search discovery

The display name is **GeSignal — HPGe Radiation-to-Readout Simulation**. The
repository slug and Pages address remain `END2END_Ge_Simulation`. GitHub Topics:
`hpge`, `germanium-detector`, `geant4`, `detector-simulation`,
`radiation-detectors`, `nuclear-physics`, `particle-detector`,
`solid-state-detectors`, `ssd-jl`, `remage`.

Normal saved-only publication generates descriptions and self-canonical URLs
for maintained landing pages, plus
[sitemap.xml](https://kunming-cn.github.io/END2END_Ge_Simulation/sitemap.xml).
The map selects current entry pages; archived reports and hash-bound scientific
bundles stay byte-exact and remain reachable through their existing links.
No generated dates or search-ranking claims are added.

For Google Search Console, add a **URL-prefix** property with the exact
`https://kunming-cn.github.io/END2END_Ge_Simulation/` address. Use the owner's
Google account and an offered HTML-tag or HTML-file ownership method. Keep the
actual verification value in a maintained publication source, never hand-edit
`docs/`; retain it after verification. Then submit `sitemap.xml`, inspect the
homepage URL and request indexing. Record the actual result rather than treating
publication as submission. A project-subdirectory `robots.txt` cannot control
the host's crawling policy; this project does not manage the account-root site.
[Google's ownership instructions](https://support.google.com/webmasters/answer/9008080?hl=en)
and [crawl-request guidance](https://developers.google.com/search/docs/crawling-indexing/ask-google-to-recrawl)
explain verification and submission; a request does not guarantee indexing.

## Contributions and default-branch policy

External contributors use [fork, branch and PR](../CONTRIBUTING.md), with owner
review before merge; no collaborator permission is needed. Keep the small PR
template in `.github/`. [CITATION.cff](../CITATION.cff) identifies this software,
not ownership or experimental validation of its upstream tools and inputs.
[THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md) records the rights boundary.
The owner selected MIT on 2026-10-03. The root `LICENSE` covers original project
software and maintained-source documentation; model/data/upstream rights remain
separate. The publisher copies its exact bytes to the site root, admits only that
extensionless path, and checks it during local and live publication validation.

The intended `main` protection requires one approving PR review, dismisses stale
approvals and requires resolved conversations. Force pushes and deletions are
disabled; no unknown CI check, CODEOWNERS requirement or new collaborator is added.
`enforce_admins` remains false: the owner's existing bounded, tested and reviewed
maintenance retains GitHub's default administrator exception. These flags are
not a claim that administrators cannot bypass them. Project policy still forbids
force-pushing or deleting `main`. Inspect actual GitHub settings before changing
this policy; settings are not installed merely by cloning the repository.
The private automation state and lock apply only to automated owner rounds;
a normal clone, CLI example or manual contribution needs neither.
[GitHub's branch-protection documentation](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches)
explains the administrator exception.

## Retention and changes

Use [LOCAL_WORKSPACE.md](LOCAL_WORKSPACE.md) and [DATA_RETENTION.md](DATA_RETENTION.md).
Keep original source workspaces, production archives, checkpoints, unique failures
and exact configurations at stable paths. Collapse historical evidence in the
index; do not move it merely to produce cleaner folder names. The local index
itself is regenerable. A same-disk copy is not an independent backup.

Make one scoped change, test it, inspect the diff, update `PROGRESS.md`, then
commit without force-pushing. Record known limitations instead of either hiding
them or turning unrelated physics research into a gate for interface improvements.
