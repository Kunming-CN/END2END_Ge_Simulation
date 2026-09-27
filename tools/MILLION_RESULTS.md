# Completed 1M-per-detector transport: saved-data results

This is a Geant4 deposition-truth analysis, not an SSD/readout/ADC spectrum. The same nominal geometry and default uncollimated Cs137 source were retained. Both 1,000,000-decay jobs completed; 200 ten-thousand-decay chunks remain saved. No radiation, field solve, charge transport or electronics was rerun for this analysis.

| Quantity | AK02 | SAP22 |
|---|---:|---:|
| Initial Cs137 decays | 1,000,000 | 1,000,000 |
| Zero Ge deposition | 987,580 | 988,728 |
| Positive Ge deposition | 12,420 | 11,272 |
| Positive Ge fraction | 1.2420% | 1.1272% |
| Isolated positive groups (100 us windows) | 12,420 | 11,273 |
| Emitted RDM photons in 660–663 keV window | 851,505 | 851,318 |
| 650–670 keV deposited-energy band, per initial decay | 808 | 535 |
| Line-photon full-energy candidate roots | 806 | 531 |
| All-photon-family full groups | 2,677 | 2,427 |
| Partial-energy groups | 9,593 | 8,680 |
| Unknown ancestry/classification groups retained | 150 | 166 |

The wide deposited-energy band is not the exact line full-energy count. Full candidates require the saved classifier's common photon ancestry and numerical energy tolerance, not a fitted experimental photopeak. The all-family counts include low-energy photons and must not be called 662-keV events. SAP22 has one decay producing two isolated groups; this is not a duplicated primary. The 316 unknown groups remain in all energy/count ledgers; no classifier exceptions occurred, and unknown classification is not a Geant4 failure.

## Delivered files

`.local/million-analysis/analysis-results/` contains the standalone `report.html`, `summary.json`, exact 1-keV deposition histograms, compressed classifications for every positive group, an all-event typed HDF5 scalar ledger, raw representative event records, provenance and a verified analysis `COMPLETE.json`. Twenty selected representative primaries, comprising 3,364 original raw rows, were matched to the compact source records. The full data pass ran once; including output verification it took about 86 seconds on the development computer.

All 200 compressed archives and decompressed-original SHA-256/byte counts were checked, along with compact event identities, counts and energy sums. The audit found zero original modifications or deletions. The campaign's scientific artifacts occupy about 7.74 GB and remain under `.local/cs137-1m/`; see DATA_RETENTION.md. A small exact-input/source/checkpoint snapshot was also saved. This is not an independent off-device backup.

## Next response stage

Use the saved compact HDF5 and raw archives; do not rerun source transport. Any native-response bridge must preserve detector/chunk/local/global identities, every zero-deposit primary and original row/delay mappings. Before a large SSD batch, use a bounded set of the new actual representative events and the preserved earlier numerical anomaly cases. Keep the 10 us cap/endpoint diagnostics visible and old10k results frozen. No 1M-batch charge/ADC result, physical FWHM, measured fit or absolute experimental efficiency is claimed here. The 23,693 positive groups are the current response workload, not two million nonzero SSD waveforms.
