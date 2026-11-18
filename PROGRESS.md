# GeSignal handoff

## Current stage · GeGI two-site reconstruction

Students can select a detector/source in Control and run radiation transport, charge drift and readout. The GeGI extension has reached stage 4 of 5. Its nominal digital chain and single-site position estimates are available in the shared Windows/macOS student runtime. The [development plan](tools/NEXT_DEVELOPMENT_PLAN.md) is the current work queue.

| Saved check | Result |
|---|---|
| Standalone GeGI run | 5,000 primaries, 4,958 zero-deposit and 42 nonzero. Digital replay found 25 conditional single-pixel candidates and four events with a unique two-face energy pairing. Overlapping neighbor signals limit what can be inferred from those pairs. |
| Neighbor response | In event 45, X03 measures 154.98 keV on the slow branch. X02 and X04 reach 13.06 and 27.41 keV-equivalent induced charge during drift and return to zero at the end. |
| Single-site position | 396 simulated 500 keV injections trained the position calibration on X11, X12, Y07 and Y09. A separate 80-point native-grid check found all 80 strip pairs and returned calibrated positions on both axes for 40. Using strip center for each unavailable axis, radial XY RMS error fell from 1.821 to 1.266 mm over all 80. Depth RMS error was 0.278 mm. |
| Two-site readout | Eight fixed 250 + 250 keV mixtures gave 32/32 expected collecting-strip hits and 0/240 spurious energy hits with the digital slow branch. Energy alone admits both X/Y pairings in all eight. |
| Two-site pairing | On those same eight, combining signed fast areas with relative timing on the four collecting strips ranked the known pair first in 8/8. Only the known pair fell inside the empirical reference range in six. Both pairs fit in two. Neither the fits nor that range use the eight truth labels. |
| Independent pairing check | Sixteen further mixtures used 32 distinct positions excluded from the training, reference-error and original eight sets. With the method frozen, fast area alone put only the known pairing inside the reference range in 12/16, and both inside in 4/16. Adding timing gave 8/16 and 8/16 respectively. Both methods ranked the wrong pairing first twice. Control keeps the compatible alternatives. |

The pairing study uses 396 reference injections and a separate 40-mixture set to measure prediction residuals. A strip can sense carriers moving through its weighting field even when they eventually reach other electrodes. A related experimental germanium strip camera used neighboring transients for position interpolation. [Johnson et al. (2011)](https://doi.org/10.1088/0031-9155/56/18/007)

The simulation processes a band-limited preamplifier signal sampled at a nominal 50 MS/s. A fixed pulser calibration sets the energy scale. The actual instrument's fast-feature definition, electronics settings and calibration still need matched evidence. The four energy-unique events in the standalone sample (1412, 1575, 2950 and 3472) use strip combinations outside the study. The published Compton map uses its original reconstruction.

## Software, studies and reproducibility

- [Student release](https://github.com/Kunming-CN/END2END_Ge_Simulation/releases/tag/student-runtime-50f47a917c93) at `50f47a9`, 1,034,459 bytes. Public download matched the local SHA-256 recorded in `.local/student-runtime-p1/COMPLETE.json`. The earlier cloud CPU acceptance ran SAP22/Cs137 with 100 primaries on each of two Mac architectures. [Platform record](https://github.com/Kunming-CN/END2END_Ge_Simulation/pull/1)
- [Results hub](https://kunming-cn.github.io/END2END_Ge_Simulation/results/index.html) serves the existing saved studies. The new neighboring-strip exhibit is in [PR #2](https://github.com/Kunming-CN/END2END_Ge_Simulation/pull/2). The last checked live manifest has 1,872 files, the checked exhibit snapshot 1,874. The PR awaits required review.
- Reproduce the pairing study with `tools/gegi_digital_pairing_study.py` and `tools/gegi_digital_pairing_holdout.py`, each with `--output <new-file.json>`, NumPy, SciPy and the original local records. The two frozen results are `two-site-pairing-study.json` and `two-site-pairing-holdout.json` under `.local/gegi-digital-v1/`. Original inputs live under `.local/gegi-10m/signal-recovery-v1/`. The original million-primary GeGI campaign is sealed under `.local/gegi-10m/campaign/COMPLETE.json` and the Cs137 campaigns under `.local/cs137-1m/`.
- Stage 5 has a 32-channel simulated spectrum exporter. The experimental comparison needs event and spectrum files from the same acquisition plus channel mapping, calibration and selection settings. Compare cumulative spectra only after reproducing the selected experimental pixel map.

[Previous handoff and full milestone history](https://github.com/Kunming-CN/END2END_Ge_Simulation/blob/9941f0d663e835a225e43923e6271b3b8df17d17/PROGRESS.md)
