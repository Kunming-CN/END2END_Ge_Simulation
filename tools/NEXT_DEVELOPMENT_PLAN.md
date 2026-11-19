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
3. The two edge scans motivated by event 2950 are complete. The wider fast-ratio and timing calibration returned a coordinate at 16/24 independent positions. On those same positions the one-axis RMS error was 1.117 mm, compared with 0.389 mm for the timing-only fit. Keep the current student position calibration and existing photon-order alternatives. The [handoff](../PROGRESS.md) gives the full denominator, measured strip-center fallback and gap-midpoint comparison.
4. Control and the standalone map exporter now read the measured 16 × 16 strip-intersection map from saved dual-source reports. The 0.25 s reference maps 484 of 864 triggers to 176 pixels. The changed-activity case maps 113 of 259 to 80 pixels. Both censuses close when multi-strip energies and triggers without energy are included.
5. Use the next matched experimental acquisition to check the fast/slow feature scales and ImagerPro pixel selection. Compare channel and pixel spectra with matching population, calibration and normalization. The 32-channel simulated spectrum export is ready.

Reuse complete saved signals for electronics changes. New transport or drift needs an identified missing physical input. Keep the student download software-only and publish saved studies through the website generator. [Previous development record](https://github.com/Kunming-CN/END2END_Ge_Simulation/blob/9941f0d663e835a225e43923e6271b3b8df17d17/tools/NEXT_DEVELOPMENT_PLAN.md)

The controlled study uses continuous digital filtering and independently tests trigger separation and pulse-height recovery. These design choices have published precedents in trapezoidal pulse shaping and commercial digital spectroscopy. The GeGI trigger parameters and neighbor-position observable are simulation assumptions. [Jordanov and Knoll (1994)](https://doi.org/10.1016/0168-9002(94)91011-1) · [XIA Pixie-16 User Manual, digital signal processing](https://s3.us-west-1.amazonaws.com/download.xia.com/products/pixie16/documents/manuals/XIA-Pixie16-Users-Manual-3.06-2019-09-13.pdf)
