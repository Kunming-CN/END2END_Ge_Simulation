# Original SSD model snapshots

These 17 versioned YAML snapshots preserve the original source bytes, including
line endings. `catalog.json` preserves original model hashes, status, assumptions,
and portable provenance. Candidate, scenario and reference names are intentional;
dimension-based reference models are not calibrated replicas.

Nine models require `ADLChargeDriftModel/drift_velocity_config.yaml`, packaged
once here at its original relative path. Keep it alongside the model YAMLs.
The other eight models contain their configuration inline. A per-detector ZIP
contains its YAML, all required includes, this README and its catalog metadata;
the all-model ZIP contains this complete distribution.

These are SSD constructive geometry, material, bias and carrier configurations,
not CAD/STL files, numerical field caches, event data, or readout electronics.
They do not establish numerical convergence or agreement with experiment.
The GeGI source comment refers to its original private README; that source
document is not included. Public provenance and limitations are in the catalog.

Validate from the repository with `python tools/export_models.py --validate`.
Maintainers may explicitly import the recorded local sources with
`python tools/export_models.py --import`. Import checks original hashes first,
copies only models and discovered includes, and refuses differing existing files.
Source files and caches are never changed. Python 3.10+ stdlib is sufficient.
