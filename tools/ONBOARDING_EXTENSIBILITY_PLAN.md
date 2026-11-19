# Student workflow and scenario contracts

Students install from the common Windows/macOS ZIP, choose compatible hardware and a source in Control, then run and inspect their own data. Pages serves the saved studies. The [setup guide](site_guide.html) owns the student instructions, the [maintenance guide](MAINTENANCE.md) locates the source, and the [development plan](NEXT_DEVELOPMENT_PLAN.md) owns the work queue.

## Add a scenario

Register detector, cryostat and source assets in the shared catalog. The detector owns crystal geometry, contacts, bias and impurity. The cryostat owns its materials and internal placements. The source owns its radiation and normalization. The placed instance supplies units, frame and pose. Control, CLI, transport geometry and provenance use the resolved inputs. Moving or rotating a source moves its capsule and fill together. Preserve the exact zero-angle world for existing configurations.

The current catalog has ten detectors admitted in the LBNL cryostat and GeGI in its dedicated cryostat. Six other models can be viewed. Enable new combinations through the common capability resolver and a checked physical placement. Keep run-local resolved settings and the original identifiers.

## Reuse saved work

| Changed input | Earliest stage to revisit |
|---|---|
| Layout or illustration | Regenerate the display from the saved result. |
| Electronics or position calibration | Replay complete signed electrode signals with sufficient duration. |
| Grouping or acquisition window | Recheck event membership and available time coverage. |
| Bias, impurity or carrier model | Recompute the affected fields and charge response. |
| Geometry, material, source placement or radiation | Recompute transport for that configuration. |

Keep creation times, drift times and readout times in their own stages. Carry initial, zero, nonzero and failed counts, rejection flags and original event identities through the chain. Use independent energy calibration. Stop/resume follows sealed stage outputs and the exact input settings. For detailed historical design decisions see the [previous contract](https://github.com/Kunming-CN/END2END_Ge_Simulation/blob/9941f0d663e835a225e43923e6271b3b8df17d17/tools/ONBOARDING_EXTENSIBILITY_PLAN.md).
