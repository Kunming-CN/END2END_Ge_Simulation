# GeSignal development plan

The student workflow runs from detector and source selection through transport, drift, electronics and event analysis. Current development targets what the digital signals in GeGI can establish about interaction position. The [handoff](../PROGRESS.md) records delivered versions, numerical checks and saved inputs.

| GeGI stage | Status and scope |
|---|---|
| 1. Electrode signals | Saved complete signed traces cover 32 strips and two guards, including transient charge on noncollecting neighbors. |
| 2. Fast and slow readout | Control replays a nominal digitized preamplifier signal. The fast branch measures signed area, the slow branch measures pulse energy and collecting-strip timing supplies a depth observable. |
| 3. Single-site position | Nine-slot lateral calibration and a two-face timing estimate tested on independently selected simulated points. Lateral coefficients cover four strips. |
| 4. Two-site reconstruction | Control shows compatible strip pairs, both ideal full-energy scattering orders, and the configured source line. New same-field position fits and checks against the transport history identified a reversed energy-only order even for a fully deposited 662 keV photon. |
| 5. Experimental comparison | The 32-channel simulated spectrum export is available. Matching the instrument selection, pixel map and spectra requires a common acquisition and its metadata. |

## Delivery order

1. The controlled pulse-overlap study is complete. Release its stable student package and verify the deployed exhibit after the required PR review. The software preview and the local exhibit can already be used.
2. The short Cs-137 / Co-60 acquisition clock and the first ten close-window ADC checks are complete. Next use the existing equilibrium clock to measure trigger and slow-energy yields over the full exposure, conserving the native-failure and unresolved-history counts. Use one continuous digital/noise state across processing blocks and compare the isolated and overlapping populations. Retain a reproducible seed and measure cost on this 0.25 s pilot before scaling. A matched activity and date can replace the example activities when available.
3. Keep both photon orders available in analysis. The independent left/right source check found four fully deposited and reference-matched candidates. Energy admitted both orders in all four. A spatial imaging update requires a calibrated response up to the strip gaps and a way to retain unresolved directions, including cases where the energy approximation excludes the simulated first interaction.
4. Use the next matched acquisition to test the instrument fast/slow feature scales and reproduce its selected pixel map. Then compare channel and pixel spectra with matching population, calibration and normalization. The 32-channel simulated spectrum export is ready.

Reuse complete saved signals for electronics changes. New transport or drift needs an identified missing physical input. Keep the student download software-only and publish saved studies through the website generator. [Previous development record](https://github.com/Kunming-CN/END2END_Ge_Simulation/blob/9941f0d663e835a225e43923e6271b3b8df17d17/tools/NEXT_DEVELOPMENT_PLAN.md)

The controlled study uses continuous digital filtering and independently tests trigger separation and pulse-height recovery. These design choices have published precedents in trapezoidal pulse shaping and commercial digital spectroscopy. The GeGI trigger parameters and neighbor-position observable are simulation assumptions. [Jordanov and Knoll (1994)](https://doi.org/10.1016/0168-9002(94)91011-1) · [XIA Pixie-16 User Manual, digital signal processing](https://s3.us-west-1.amazonaws.com/download.xia.com/products/pixie16/documents/manuals/XIA-Pixie16-Users-Manual-3.06-2019-09-13.pdf)
