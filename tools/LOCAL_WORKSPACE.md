# Local workspace organization

Double-click `Open_Workspace.cmd` at the project root. It refreshes a local-only
index at `.local/workspace/index.html` and opens it. The index groups saved results,
current runs, canonical models/code, references, and preserved review/diagnostic
evidence. It never starts or resumes a simulation and performs no deletion.

## Stable locations

- `models/`, `scenarios/`, `simulation/`, `transport/`, `tools/`: maintained source,
  canonical models and explicit run definitions. Do not rearrange them casually.
- `docs/`: generated public website. Change its generators, not generated pages.
- `Additional_Simulations/` and `2D_GeGI detector Simulation/`: original workspaces
  retained at their current paths because saved references may depend on them.
- `.local/cs137-1m/` and `.local/cs137-1m-native/`: permanent science, not cache.
  Preserve original archives, compact records, inputs, fields and checkpoints.
- `.local/runs/`: ordinary launcher runs. Opening a result is not a resume action.
- `.local/reference-docs/`: private documents, including `presentations/`.
- Other `.local/` folders: retained development, publication and review evidence.
  An unfamiliar name or failed result is never automatic permission to delete it.

## Deliberately limited physical reorganization

The loose root presentation is moved only after project-code reference checks,
with an exact original/destination/hash record in the current round's
`reference-move.json`. Its bytes and modification time are verified after the move.
No original scientific directory, installed package cache, authentication data,
review history or unfinished run is moved or removed. No desktop/systemwide cleanup
is performed. Local indexing is not an independent backup or proof of cloud sync.

## What stays primary, archived or regenerable

The dashboard leads with direct final response and deposition reports. Its
navigation groups are manually maintained categories, not live worker status.
The historical evidence section is collapsed by default; original paths remain
visible through the inventory and links.

| Class | Exact examples | Treatment |
|---|---|---|
| Permanent science and inputs | `.local/cs137-1m/`, `.local/cs137-1m-native/`, `.local/peak-native-delivery/`, `.local/transport/LBNL/` | Keep original bytes, identities, raw archives, caches and checkpoints |
| Current final derivatives | `.local/native-final-analysis-v3/`, `.local/native-final-report-v2/` | Promote their final results; retain provenance |
| Historical evidence | `.local/native-final-analysis-v1/`, `-v2/`, `.local/native-final-report-v1/`, earlier reviews and failed attempts | Archive in navigation only; do not relocate hash/path-bound evidence |
| Regenerable index | `.local/workspace/index.html`, `.local/workspace/inventory.json` | Rebuild with `Open_Workspace.cmd`; these are not scientific records |
| Unclassified or browser scratch | Other `.local/` entries | Inspect dependencies and unique evidence before any cleanup; no deletion by age/name |

An old failed result may explain a later correction. No scientific dataset has
been declared permanently useless solely to simplify the interface. The owner
still needs a separately verified off-device backup; this index is not one.
