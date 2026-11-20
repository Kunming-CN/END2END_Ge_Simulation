# GeSignal development plan

The student workflow runs from detector and source selection through transport, drift, electronics and event analysis. Current development targets what the digital signals in GeGI can establish about interaction position. The [handoff](../PROGRESS.md) records delivered versions, numerical checks and saved inputs.

| GeGI stage | Status and scope |
|---|---|
| 1. Electrode signals | Saved complete signed traces cover 32 strips and two guards, including transient charge on noncollecting neighbors. |
| 2. Fast and slow readout | Control replays a nominal digitized preamplifier signal. The fast branch measures signed area, the slow branch measures pulse energy and collecting-strip timing supplies a depth observable. |
| 3. Single-site position | Four directly calibrated strip pairs, lateral transfer on nine additional pairs, and apparent-depth timing curves across 216 pixels. Control shows evidence and availability per estimate. |
| 4. Two-site reconstruction | New Control runs capture two-strip ADC windows. The portable center-template fit reconstructs allowed Compton cones from these windows. Control opens the energy-resolved maps and reports unresolved trigger weight. Comparison with independent simulated histories covers 46 energy-compatible occurrences. |
| 5. Experimental comparison | The 32-channel simulated spectrum export is available. Matching the instrument selection, pixel map and spectra requires a common acquisition and its metadata. |

## Delivery order

**Current decision: paused by the owner.** Future production is a single mixed-source experiment from particle generation onward. Resume only on a new instruction from the owner.

1. Put Cs-137 at (−40, 0, 40) mm and Co-60 at (+40, 0, 40) mm in one GeGI geometry. Use the commercial reference activities, 185 kBq and 37 kBq. Generate fresh decays on one absolute timeline with a source label and its corresponding position. For constant activities, the combined Poisson rate is 222,000 per second, with source probabilities 5/6 and 1/6. Preserve each decay's emission cascade and delayed daughters. Define pre-exposure activity so the acquisition starts in the intended physical state.
2. Transport that mixed stream in the same detector. Drift charge for its deposits, sum overlapping electrode currents and process them through the same continuous preamplifier, shaper, noise, ADC and trigger. Keep electronics and clocks continuous across computational buffers for **at least 60 seconds**.
3. Image from the common measured data. Report parent decays, recorded triggers, accepted energies, usable cones and excluded cases separately. A 60-second exposure has 13.32 million expected parent decays; the imaging count must be measured. If testing range, fit x, y and z before comparing with the programmed positions. Scale, duration beyond one minute and storage are pending the owner's decision.

The earlier [25-window readout study](../docs/results/gegi-shared-readout/index.html) used archived per-isotope histories in one shared electronics simulation per 250 ms window. It provides a readout comparison, not a completed full-generation run under this plan.

### Next milestone contract (design only; execution remains paused)

The next implementation reuses the existing geometry, fields, carrier transport and readout functions. Its new responsibility is connecting fresh mixed-source generation to continuous detector state. Before any resumed calculation, record these inputs and outputs in the run configuration and checkpoint:

| Boundary | Required record and acceptance |
|---|---|
| Source generation | Both isotope definitions, positions and activities are present before the first decay. Record the acquisition start state, source age or initial daughter populations, pre-acquisition history policy, random seeds and generator version. Do not silently assume an empty detector or secular equilibrium. |
| Identity and time | One immutable acquisition ID and unique parent-decay ID identify the isotope and position. Daughter, emission, transport event and deposit IDs retain their parent relationships and absolute times, including delayed daughters across buffers. A trigger may contain multiple parents; one parent may contribute to multiple triggers. |
| Continuous processing | Carry pending daughters and current tails, preamplifier/shaper/filter state, noise generator state, ADC sample index, trigger state and unfinished readout windows across buffers. A checkpoint also binds configuration/input hashes and the last committed identities so restart neither repeats nor drops records. |
| Bounded acceptance after resumption | Process the same finite fresh-source input continuously, in several buffer sizes and through stop/resume. Compare identities, time ordering, deposited energy, signed charge, ADC codes and trigger/reconstruction records; document any necessary numerical tolerance. Place delayed emissions and overlapping pulses at buffer boundaries. Retain zero/nonzero/failure/unknown counts and close every stage's census before scaling. |
| Production | Only after the bounded path passes, run one uninterrupted acquisition of at least 60 s. Report actual parent decays, deposits, triggers, accepted energies, usable imaging candidates, exclusions and unknowns separately. A completed pipeline alone does not establish instrument accuracy. |

At the specified constant activities, the expected 60 s parent census is
222,000 s⁻¹ × 60 s = **13,320,000 parent decays**, not triggers or imaging events.
Assuming 34 channels, 50 million samples/s, 60 s and two bytes/sample, a complete
uncompressed ADC stream would occupy **204 GB (about 190 GiB)**. This is a storage
estimate under explicit assumptions, not a measured output size. Before production,
choose the new format and full-stream retention policy, measure bounded throughput
and memory, and specify streaming buffers, retained trigger windows, event ledgers,
checkpoints and the information needed to reproduce discarded samples. Existing
scientific originals remain unchanged.

Fix reconstruction selections, interaction-order rules and imaging priors before
independent evaluation. Split by original history or fresh parent-decay identity;
repeated replays of one history are not independent evidence. Use source-position
truth only to score final estimates. Report error with returned/total coverage,
failure rate, energy/position range and uncertainty. Existing AK02/SAP22 measured
spectra support a bounded spectrum comparison; no historical measured waveforms
exist. GeGI comparison needs matched channel mapping, calibration, thresholds,
pixel selection, acquisition time and normalization.

### Earlier saved studies

**Completed imaging baseline.** The four-block ±120/±240 mm comparison and the held-out angular-response check are complete. Students can replay the same measured cones under either plane prior and compare the maps in Control. Uniform solid angle stabilized the pooled peaks on widening, while the 662 keV peak moved farther from the simulated Cs-137 position when the prior changed. Both selectable assumptions and the original event denominators remain in the [published comparison](../docs/results/index.html#gegi-plane-priors).

**Shared-clock evidence.** All 324 measured two-strip rises were recovered from their 34-electrode ADC samples. Their finite ADC, fast and slow supports contained no additional reference Ge onset. The full 3,905-trigger population did include two merged timing assignments with more than one depositing group in one rise. One measured 858.219 keV on one X and two Y strips, and the other had guard collection and no accepted energy. In 24 matched pulse controls, the local ADC window recovered seven second rises. At 600 ns the full clock registered both triggers in all six trials, after the first window had closed.

**Matched component controls.** Replaying the groups from triggers 683 and 598 together reproduced all 1,972 saved ADC codes. Separate replays showed two clean energies on a shared X strip in 683. In 598, only the Co-60 group triggered the guards. Its signals on Y13 and Y14 contributed to the Y strip sum although no carriers ended on those strips. The [handoff](../PROGRESS.md) records the original and isolated outcomes and the retained noise and history.

**Weak strips and pairing.** The [fixed late-step study](gegi_weak_strip_study.py) flagged 2/59 energy-incompatible and 5/265 compatible triggers. All ten flagged strip signals had a [simulated carrier landing](gegi_weak_strip_endpoints.py), including one below the nominal sensitivity floor. All 57 unflagged failures distributed their energy over three or four intersections of the four measured strips. The study is a GitHub Pages exhibit. The student package and the measured pairing rule are unchanged.

**Image contribution from three intersections.** Two triggers in each Co-60 energy window supplied over 41% of the original peak cell on the ±120 mm uniform-area image. Setting them aside moved the peaks 236.0 and 59.5 mm at 1,173 and 1,332 keV. Both cobalt pairs reused a single archived history within their respective window. The solid-angle maxima stayed in their original cells. The [existing imaging exhibit](../docs/results/index.html#gegi-three-intersections) gives the full and retained peak coordinates, the source-position comparison and the leave-two-out denominators.

**Origin of the two cobalt contributions.** In both archived histories one Co-60 photon deposited its full energy in Ge. Four Compton scatters preceded absorption in the 1,173 keV history, and two preceded absorption in the 1,332 keV history. The two-cell readout allowed only the reverse of the dominant first-to-final cell order. The [existing imaging result](../docs/results/index.html#gegi-three-intersections) connects the original photon steps to the measured strip energies and cone directions.

The matched pulse-overlap test supports the existing channel-local quality flags. The 4 keV-per-sample coincidence option recovered 19 of the 45 missed isolated deposits; the original 5 keV setting remains selectable. The 80-point continuous single-pixel calibration transfer, nine additional lateral strip-pair checks, and per-pixel energy-window/spectrum workflow are recorded in the [handoff](../PROGRESS.md). These local development steps proceed independently of stable-release approval and measured-data comparison.

1. Control and the command line now run a configurable simultaneous acquisition from two supplied GeGI source libraries. The [student guide](site_guide.html#gegi-dual-source) covers placement, activity, exposure and the saved count/spectrum receipt. A 0.25 s reference exposure and a 0.05 s changed-activity acquisition are recorded in the handoff.
2. For routine owner-authorized GeSignal updates, synchronize the verified revision using the existing administrator permission. Publish a stable student release when the runtime changes. Update research exhibits on GitHub Pages, remove superseded displays and verify the deployed files.
3. The two edge scans motivated by event 2950 are complete. The wider fast-ratio and timing calibration returned a coordinate at 16/24 independent positions. On those same positions the one-axis RMS error was 1.117 mm, compared with 0.389 mm for the timing-only fit. Keep the current student position calibration and existing photon-order alternatives. The [handoff](../PROGRESS.md) gives the full denominator, measured strip-center fallback and gap-midpoint comparison.
4. Control and the standalone map exporter now read the measured 16 × 16 strip-intersection map from saved dual-source reports. The 0.25 s reference maps 484 of 864 triggers to 176 pixels. The changed-activity case maps 113 of 259 to 80 pixels. Both censuses close when multi-strip energies and triggers without energy are included.
5. Use the next matched experimental acquisition to check the fast/slow feature scales and ImagerPro pixel selection. Compare channel and pixel spectra with matching population, calibration and normalization. The 32-channel simulated spectrum export is ready.

Reuse complete saved signals for electronics changes. New transport or drift needs an identified missing physical input. Keep the student download software-only and publish saved studies through the website generator. [Previous development record](https://github.com/Kunming-CN/END2END_Ge_Simulation/blob/9941f0d663e835a225e43923e6271b3b8df17d17/tools/NEXT_DEVELOPMENT_PLAN.md)

The controlled study uses continuous digital filtering and independently tests trigger separation and pulse-height recovery. These design choices have published precedents in trapezoidal pulse shaping and commercial digital spectroscopy. The GeGI trigger parameters and neighbor-position observable are simulation assumptions. [Jordanov and Knoll (1994)](https://doi.org/10.1016/0168-9002(94)91011-1) · [XIA Pixie-16 User Manual, digital signal processing](https://s3.us-west-1.amazonaws.com/download.xia.com/products/pixie16/documents/manuals/XIA-Pixie16-Users-Manual-3.06-2019-09-13.pdf)
