# Current handoff

Updated: 2026-10-17. GeGI-only cryostat and multichannel Compton workflow are
implemented and tested in GeSignal Control. Prior P0-P5 remain delivered; their
handoff is preserved at commit666947fa22d879eae69252d25ec91345d24665cd.

## Current delivery

Root owns .local/autonomy/round.lock as gegi-integration-root. Implementation
workers are finished. No extra AI review agents were used. Release/site closure
is in progress; inspect .local/gegi-integration/delivery.json and actual processes
before continuing. Never repeat completed physics because of a chat interruption.

The dedicated gegi_cryostat_v1 accepts only frozen GeGI_3D. Measured front layers
are1.6mm and0.8mm with8.1mm crystal-to-external-front distance. The owner accepted
explicit nominal side/rear dimensions and gap split; alloys use pure Al. Missing
holders/cold finger and full hardware geometry remain declared approximations.
Private manuals/slides stay private. Canonical92.3K/-879V and0V inputs are unchanged.

The shared lifecycle now handles configurable gamma energy/position, check/run/
stop/resume,34-electrode signed signals, independent readout calibration, channel
plots, strip matching, candidate Compton cones and directional backprojection.
X/Y energies are not double counted. Depth uses an independent simulated central
pixel timing table; no measured per-pixel calibration, range or resolution claim.
Both kinematically valid orders are retained without source-direction selection.

## Actual evidence

.local/runs/gegi-100-pilot-v1:100initial/100zero/0nonzero. Actual stage-boundary
stop/resume reused radiation. Empty results contain no fabricated waveforms.
.local/runs/gegi-5000-imaging-v1:completed,5000initial/4958zero/42nonzero,
874positive Ge steps; seed26101702,662keV isotropic source at[30,0,100]mm.
All42 events retain34 channels;0native failures,2native endpoint flags,38readout
accepted and4readout rejected. Imaging accepts1event(ID2950), rejects41 with
reasons, produces1cone. Image integral is1.0. One cone is not source localization.

The exact existing34-potential Float32 native field cache was reused (hashf75280e7
f21b1a1a06c2a6623aed62873065ca72db02bb1f93a61b9b853b90e8). Fresh-field policy
usesFloat64. Neither a fresh solve nor grid/experimental validation is claimed.
A transient permission error replacing a large progress file was fixed with
bounded atomic-write retries and compact progress.20completed event/checkpoint
hashes and all radiation bytes were reused unchanged. The original failure,
original producer, and explicit storage-only rebind remain in
.local/gegi-integration/storage-failure-original; no new primaries during recovery.

Relevant checks:21shared workflow,6imaging,4protected Control,JS regressions,
5software-package,6saved-publication,33site,15native helper+5model/request and
20checkpoint checks passed. Native overlaps:8volumes/10000samples each passed.
Actual browser verified compatible selection, blocked mismatches, checked source,
empty results, original nonzero IDs,34channel switching and real cone/map display.
CLI-data display used a labelled temporary read-only fixture, not forged UI ownership.

## Current owner extension and remaining closure

The owner added a two-position source-separation test. Running serial bounded
5000primary runs gegi-source-left-v1 and gegi-source-right-v1 at[-40,0,40] and
[40,0,40]mm,662keV,seeds26101703/26101704. Inspect their actual receipts and
.local/gegi-integration/delivery.json; never restart completed radiation.
A real transient-recrossing defect was identified in the old2950Y28charge:
first50%crossing22.24ns,last79.33ns. New native source uses the last upward
crossing for both independent calibration and events;18targeted tests passed.
Old100/5000outputs remain unchanged. Website comparison will use cone vertices
on explicit knownz=40mm plane, plus directional maps; no recovered range claim.


Finish existing website build, required local/live checks, commit/push, build and
verify immutable latest student ZIP from formal source commit. No test data or
publication fixtures go in the student package. Close owned servers and remove
only owned disposable scratch; retain scientific runs and unique failure records.
Update this handoff/delivery/state, release this owned lock and leave ready.

Original campaigns/models are unchanged. Further mechanical fidelity and hardware
calibration require actual dimensions, channel mapping and measured calibration.
No automatic larger campaign, PSD3, phone work, new environment or review rounds.
