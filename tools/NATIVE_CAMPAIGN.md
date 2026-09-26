# Native Cs137 campaign

Run from the repository root on the configured Windows computer. This uses the
existing pinned WSL Geant4/remage and Windows Julia environments. No dependency
installation, canonical-model change, or existing-output overwrite is performed.

## Commands

The native cryostat adapter must exist and match the current source. The verified
configured-computer build is `.local/m2a/cs137-build-v1/cryostat_export`. Its binary
hash is recorded; a different project-local build can be selected with `-Exporter`.

```powershell
.\transport\Run.cmd cmake -S . -B ../.local/m2a/cs137-build-v1 -G Ninja
.\transport\Run.cmd cmake --build ../.local/m2a/cs137-build-v1 --target cryostat_export --parallel 2

.\tools\run_native_campaign.ps1 -Output .local/my-cs500 -Events 500
.\tools\run_native_campaign.ps1 -Output .local/my-cs10000 -Events 10000 -Pilot .local/my-cs500
node tools/native_campaign_report.mjs .local/my-cs10000
```

The upstream LBNL cache must already match `transport/cryostat-source.json`.
Upstream originals are not bundled or modified. Use fresh output paths. The two
detectors run serially, using two Julia threads and one reused field solution
per detector/configuration. The runner generates real Cs137 decays, extracts
complete chunks, validates the stream and applies native SSD plus peak readout.

A completed positive 500-decay-per-detector pilot is mandatory before 10k.
The guard rechecks actual response artifacts, raw LH5, chunk and model hashes,
all recorded producer/consumer source dependencies, current profile and binary.
Source or configuration changes require appropriate fresh evidence; failed or
incomplete pilots never pass. Launcher-only validation revisions preserve and
record the previous launcher hash rather than rewriting historical receipts.

## Results and limits

Open `comparison.html` in the campaign directory after running the exporter.
It verifies the completed artifacts and scalar/histogram accounting first; it
does not run simulations. Each detector also has `response/summary.html` with
charge, current, preamp and shaper traces. Complete scalar, endpoint and truth
ledgers remain separate from the bounded display traces. Original raw radiation
transport is retained in `transport/truth.lh5`.

The cryostat, capsule, spacer and crystal pose are explicitly nominal, not an
as-built survey. Every initial decay remains represented, including zero-Ge
events. Emitted-line photons, decays and accepted pulses are different denominators.
Finite groups reset electronics and retain boundary, tail and recovery flags;
this is not continuous acquisition, a rate prediction or an absolute experimental
efficiency. Synthetic electronics and numerical parcel variation are not measured
energy resolution. Signed charge, partial collection and trajectory caps remain
visible. Global Li/grid research is a separate accuracy task, not a delivery gate.

`node --test tools/test_native_campaign_report.mjs` exercises lossless accounting,
deliberately rehashed corruption and no-overwrite behavior using synthetic fixtures.

## Native anomalies are not repaired or hidden

The campaign selects the explicit `record` failure policy. The native entry itself
still defaults to `abort`. Record mode isolates only the two documented strict
native-domain errors; other exceptions stop the run. Failed groups retain original
truth, identifiers, delays, settings and exact errors in `native-failures.jsonl`.
Unavailable response values are null, not zero. There are no fabricated endpoint,
charge, current or ADC records for those groups. `completed_with_native_failures`
is distinct from a clean completion, and native failures are counted separately
from threshold/ADC rejections. Native/analog histograms include successful native
groups only; deposited truth retains every decay/group. The report exposes the
missing-response count. A clean500 pilot remains mandatory before10k.

## Publish an existing completed 10k campaign (no calculation)

From the project root, use the existing site Python runtime or Python 3.10+:

```powershell
node tools/native_campaign_report.mjs .local/peak-native-delivery/cs10000-v2 --verify-only
& 'C:\Program Files\ParaView 6.1.1\bin\pvpython.exe' tools/build_site.py --native-campaign .local/peak-native-delivery/cs10000-v2
& 'C:\Program Files\ParaView 6.1.1\bin\pvpython.exe' tools/check_site.py
```

The explicit mode adds `docs/examples/cs137-10k/` to the validated existing
website snapshot. It does not regenerate historical galleries or rerun old
examples against newer code. Original campaign dependencies must still match.
All scalar, histogram and selected-charge CSV bytes remain unchanged. Each
model's `response/ledgers.zip` contains all 18 original response files, including
complete truth/deposit and endpoint ledgers; original line endings are preserved.
Original `run.json` and `source-comparison.json` remain historical receipts.
`publication.json` separately binds adapted public pages and the complete archive
inventory. No raw LH5, field cache or upstream geometry file is republished.

After GitHub Pages deployment, run `tools/check_site.py --url` with the site URL.
It checks every published campaign file, including both ZIP archives, not just
page availability. Unit tests: `tools/test_native_publication.py` and
`node --test tools/test_native_campaign_report.mjs`. None invokes a simulation.
