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

1. Deliver the updated Control and the four-event comparison through the current PR. After its required review, verify the deployed exhibit and publish the matching stable student package.
2. Evaluate energy ordering on the additional saved left and right source runs. Use the observed rate of reversals and unresolved cases to judge any change to imaging. Keep fit coordinates and source directions conditional while calibration near the strip gaps is incomplete.
3. Use the next matched acquisition to test the instrument fast/slow feature scales and reproduce its selected pixel map. Then compare channel and pixel spectra with matching population, calibration and normalization. The 32-channel simulated spectrum export is ready. An IPB configuration or cumulative N42 spectrum alone cannot supply the reference event list.

Reuse complete saved signals for electronics changes. New transport or drift needs an identified missing physical input. Keep the student download software-only and publish saved studies through the website generator. [Previous development record](https://github.com/Kunming-CN/END2END_Ge_Simulation/blob/9941f0d663e835a225e43923e6271b3b8df17d17/tools/NEXT_DEVELOPMENT_PLAN.md)
