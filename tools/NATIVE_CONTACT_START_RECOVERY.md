# Native batch contact-start recovery

The native response worker stopped after 13,841 committed groups because SAP22
event 128042 / group 0 contains positive-energy deposits that Geant4 retained
inside Ge but the SSD model classifies inside contact 1 (the point contact).
The first failing row is 2248 at about r=0.585 mm, z=9.9998 mm.

A complete saved-input scan found **zero affected AK02 groups** and exactly
**five SAP22 events / five groups / 38 positive rows** in SSD contact 1:
128042, 185628, 189671, 585848 and 628484. This is an input-domain
compatibility condition, not evidence that the Geant4 deposit is wrong and not
a supported immediate-collection model.
The recovery therefore fails closed. `native_contact_start_resilience.jl`
keeps outside-semiconductor deposits fatal, but moves contact-start handling to
the pulse-group boundary before drift. An affected whole group is committed as
`native_failed` with failure class `input_domain_compatibility`. Its complete
truth, coordinates, delays and contact rows remain; native charge and readout
are null. No coordinate is moved, no contact energy is subtracted, and no ADC
is fabricated. Unaffected groups delegate to the unchanged response function.

The adapter is process-local and verifies the exact frozen checkpoint-runner
hash. It composes with the existing unwritten-boundary guard and display-I/O
resilience; the numerical runner, cached fields, models and prepared config
remain byte-identical.
Validation: 19 Julia assertions passed. Two existing physics/integrity agents
reviewed the policy and then the actual implementation/evidence. A max_new=0
run recovered all 13,841 old checkpoints and paused with exit 0. A max_new=1
run added only SAP22 event 128042/group0 as an explicit input-domain failure.

A full post-run audit rehashed every pre-existing DONE and JLS file and compared
size and modification time: all 13,841 prior groups were unchanged. The new
group preserves the full 34.333136 keV truth; the 6.130806 keV subtotal inside
contact 1 is diagnostic only. The response remains unknown.

During the running campaign the legacy `numerical_failures` progress counter is an
aggregate native-failure count. Final analysis must split contact-start input
compatibility failures, boundary numerical failures, and electronics rejects.
Use the updated local Resume.cmd for this interrupted campaign; never rerun
Geant4 or rebuild the already prepared native input.
