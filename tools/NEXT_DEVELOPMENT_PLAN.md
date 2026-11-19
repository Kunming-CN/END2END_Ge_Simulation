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

1. Control and the command line now run a configurable simultaneous acquisition from two supplied GeGI source libraries. The [student guide](site_guide.html#gegi-dual-source) covers placement, activity, exposure and the saved count/spectrum receipt. A 0.25 s reference exposure and a 0.05 s changed-activity acquisition are recorded in the handoff.
2. Release the matching stable student package and verify the deployed guide and digital exhibit after the required PR review. The software preview and local exhibit are available during review.
3. The next position question is whether collecting and neighboring strip responses retain usable sub-strip information near an electrode gap. Use the cells from saved event 2950, where the simulated deposition centroids fell outside the ±0.4-pitch calibration on one axis. Reuse the field and available reference signals. If edge positions are missing, run a small edge scan and evaluate held-out positions against the existing calibration, keeping charge sharing and incomplete collection visible. The result determines whether to expand the position calibration. Keep alternative photon orders available. Energy admitted both orders in all four fully deposited, reference-matched candidates from the independent left/right check.
4. Use the next matched acquisition to test the instrument fast/slow feature scales and reproduce its selected pixel map. Then compare channel and pixel spectra with matching population, calibration and normalization. The 32-channel simulated spectrum export is ready.

Reuse complete saved signals for electronics changes. New transport or drift needs an identified missing physical input. Keep the student download software-only and publish saved studies through the website generator. [Previous development record](https://github.com/Kunming-CN/END2END_Ge_Simulation/blob/9941f0d663e835a225e43923e6271b3b8df17d17/tools/NEXT_DEVELOPMENT_PLAN.md)

The controlled study uses continuous digital filtering and independently tests trigger separation and pulse-height recovery. These design choices have published precedents in trapezoidal pulse shaping and commercial digital spectroscopy. The GeGI trigger parameters and neighbor-position observable are simulation assumptions. [Jordanov and Knoll (1994)](https://doi.org/10.1016/0168-9002(94)91011-1) · [XIA Pixie-16 User Manual, digital signal processing](https://s3.us-west-1.amazonaws.com/download.xia.com/products/pixie16/documents/manuals/XIA-Pixie16-Users-Manual-3.06-2019-09-13.pdf)
