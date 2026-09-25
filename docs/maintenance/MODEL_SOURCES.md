# Model sources and assumptions

All original models are read-only inputs. Twelve existing dissertation entries are retained, including previously labelled candidates, scenarios and references. New large models are publicly dimensioned examples, not verified as-built LEGEND-200 replicas.

## SAP16

Category: thesis. Status: geometry and material match.

Source YAML: `[external local input]`



- Outer bias set to 340 V; readout 0 V.
- Explicit SSD 0.11 impurity format with units prevents automatic legacy conversion from multiplying density by 1e9.

- Authoritative dissertation model_manifest.json

## SAP17

Category: thesis. Status: geometry and material match.

Source YAML: `[external local input]`



- Outer bias set to 400 V; readout 0 V.

- Authoritative dissertation model_manifest.json

## SAP22

Category: thesis. Status: geometry and material match.

Source YAML: `[external local input]`



- Outer bias set to 700 V; readout 0 V.

- Authoritative dissertation model_manifest.json

## AK01

Category: thesis. Status: geometry and material match.

Source YAML: `[external local input]`



- Outer bias set to 700 V; readout 0 V.

- Authoritative dissertation model_manifest.json

## AK02

Category: thesis. Status: geometry and material match.

Source YAML: `[external local input]`



- Outer bias set to 500 V; readout 0 V.

- Authoritative dissertation model_manifest.json

## GeRC02

Category: thesis. Status: geometry and material match.

Source YAML: `[external local input]`



- Outer bias set to 240 V; readout 0 V.

- Authoritative dissertation model_manifest.json

## KMRC01_candidate

Category: thesis. Status: candidate; ring-width match.

Source YAML: `[external local input]`



- Outer bias set to -370 V; readout 0 V.
- Explicit SSD 0.11 impurity format with units prevents automatic legacy conversion from multiplying density by 1e9.

- Authoritative dissertation model_manifest.json

## SAP18_ring08_scenario

Category: thesis. Status: scenario; identity unresolved.

Source YAML: `[external local input]`



- Outer bias set to -380 V; readout 0 V.
- Hypothesis only: 0.8-mm ring substituted into the 2-mm GeRC geometry; other dimensions not independently identified for SAP18.
- Explicit SSD 0.11 impurity format with units prevents automatic legacy conversion from multiplying density by 1e9.

- Authoritative dissertation model_manifest.json

## KL01_3D

Category: thesis. Status: geometry and material match.

Source YAML: `[external local input]`



- Outer bias set to 1600 V; readout 0 V.
- Rectangular union geometry retained; replaced invalid phi=0 cylindrical approximation by Cartesian 3D.
- Explicit SSD 0.11 impurity format with units prevents automatic legacy conversion from multiplying density by 1e9.

- Authoritative dissertation model_manifest.json

## BEGe_reference

Category: thesis_reference. Status: illustrative model; no serial-number match.

Source YAML: `[external local input]`



- Original geometry, impurity and bias retained. Used as a reference, not a validated LEGEND device.
- Explicit SSD 0.11 impurity format with units prevents automatic legacy conversion from multiplying density by 1e9.

- Authoritative dissertation model_manifest.json

## ICPC_large_reference

Category: thesis_reference. Status: illustrative model; no serial-number match.

Source YAML: `[external local input]`



- Original geometry, impurity and bias retained. Used as a reference, not a validated LEGEND device.

- Authoritative dissertation model_manifest.json

## Bipolar_reference_3D

Category: thesis_reference. Status: reconstructed ideal planar scenario; exact fabrication details not identified.

Source YAML: `[external local input]`



- 9.21 x 11.69 x 9.50 mm rectangular slab from thesis; ideal full-face contacts; +2000 V assumed operating scenario; N_eff=-3.14e10 cm^-3 assumed from nearby-boule KL01, not an independent reference measurement.
- Explicit SSD 0.11 impurity format with units prevents automatic legacy conversion from multiplying density by 1e9.

- Authoritative dissertation model_manifest.json

## COAX_ANG2_reference

Category: commercial_reference. Status: dimension-based illustrative model; not a calibrated replica.

Source YAML: `[external local input]`

ANG2: diameter 80 mm, height 107 mm, operating bias 3500 V; Table 4.2.

- Bore radius 5 mm, closed-end thickness 10 mm, bottom passivated annulus 3 mm are estimates.
- 78 K and a uniform net impurity are illustrative inputs; no measured impurity profile is claimed.
- Ideal contacts; no explicit dead/transition layer. No experiment-matched electronics.

- https://www.mpi-hd.mpg.de/gerda/public/2015/phd2015_giovanniBenato.pdf

## PPC_PONaMa1_reference

Category: commercial_reference. Status: dimension-based illustrative model; not a calibrated replica.

Source YAML: `[external local input]`

PONaMa-1: diameter 68.9 mm, height 52 mm, contact diameter 3.2 mm and depth 2 mm, passivated diameter 60 mm; Table 1. Bias 1050 V in section 2.2.

- A cylindrical recess approximates the curved point-contact dimple; a 45-degree 4.45 mm corner chamfer is inferred from the passivated radius.
- 78 K and a uniform net impurity are illustrative inputs; no measured impurity profile is claimed.
- Ideal contacts; no explicit dead/transition layer. No experiment-matched electronics.

- https://pmc.ncbi.nlm.nih.gov/articles/PMC8921096/

## BEGe_GD32B_reference

Category: commercial_reference. Status: dimension-based illustrative model; not a calibrated replica.

Source YAML: `[external local input]`

GD32B: diameter 71.89 mm, height 32.16 mm (Table 1); groove diameters 15/21 mm and depth about 2 mm reported for the production.

- Readout fills the central 15 mm diameter disk; microscopic contact details are idealized.
- 4000 V is reported for GD32B in Benato thesis Table 4.2: https://www.mpi-hd.mpg.de/gerda/public/2015/phd2015_giovanniBenato.pdf
- 78 K and a uniform net impurity are illustrative inputs; no measured impurity profile is claimed.
- Ideal contacts; no explicit dead/transition layer. No experiment-matched electronics.

- https://pmc.ncbi.nlm.nih.gov/articles/PMC6892349/

## ICPC_48A_reference

Category: commercial_reference. Status: dimension-based illustrative model; not a calibrated replica.

Source YAML: `[external local input]`

IC detector 48A: diameter 74.6 mm, height 80.4 mm, well depth 47.4 mm, well diameter 10.5 mm; Table 1.

- Groove diameters 15/21 mm, depth 2 mm and a disk readout are estimated.
- 4000 V is an illustrative bias, not a verified operating voltage for serial 48A.
- 78 K and a uniform net impurity are illustrative inputs; no measured impurity profile is claimed.
- Ideal contacts; no explicit dead/transition layer. No experiment-matched electronics.

- https://pmc.ncbi.nlm.nih.gov/articles/PMC8549949/

## GeGI_3D

Category: strip. Status: existing user model; measured and assumed inputs retained.

Source YAML: `[external local input]`



- Uses the existing 34-contact model without changing geometry, bias, temperature, impurity or orientation.
- Only missing weighting potentials will be solved; the original field cache is read-only.

- [external local input]
- [external local input]

## GeGI retained source assumptions

The existing source model has a 90 mm across-flats octagonal crystal, thickness 11 mm, 16 strips per face and two guard contacts. X-side contacts are at -879 V and Y-side contacts at 0 V; temperature is 92.3 K. The existing source assumes net p-type impurity -5e9 cm^-3, a 0.25 mm strip gap and 45-degree crystal-axis orientation. These are inherited inputs, not new measurements. The source README distinguishes drawing dimensions, instrument-photo inputs and modeling assumptions. Four centre-strip weighting potentials were already available; the remaining 30 were solved on the existing electric grid with per-contact update checks.
