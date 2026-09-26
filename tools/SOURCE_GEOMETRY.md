# Saved Cs137 source placement and low Ge-deposition fraction

This is an audit of the existing `cs10000-v2` run, not a new simulation or an
as-built survey. Original radiation, native-response and readout outputs remain frozen.

## What was actually simulated

The point source is at global **(0, 37.073, 0.290) mm**. Both crystals use
`x_global = R*x_local + (0, 1.450, 0.290) mm`, with local +z mapped to global +y.
The source is centered above the crystal axis. Its nominal 1 mm-thick capsule
rests tangentially on the **curved cylindrical outer wall**, whose uppermost
surface is y = 36.573 mm. It is **not** on the cylinder's flat axial end face.
The geometry orientation is an explicit engineering assumption, not a verified
identification of the laboratory lid. A real source on the axial flat end face
would require a different scenario; do not silently reinterpret these results.

| Quantity | AK02 | SAP22 |
|---|---:|---:|
| Crystal outer radius (mm) | 12.65 | 12.75 |
| Crystal overall height (mm) | 9.4 | 10.0 |
| Source to highest Ge surface (mm) | 26.223 | 25.623 |
| Initial Cs137 decays | 10000 | 10000 |
| Decays with positive Ge deposition | 121 | 115 |
| Positive-Ge-deposition fraction | 1.21% | 1.15% |
| Mean Edep among positive-Ge decays (keV) | 236.5174 | 213.6233 |
| Edep in the explicit 650–670 keV band (decays) | 11 | 7 |

The last row is only a broad deposited-energy count, not a fitted photopeak,
physical FWHM or an ADC acceptance count. Most initial decays have no Ge deposit.
A positive deposit need not contain the complete energy of the incident photon.

## A bounded sanity estimate, not a calibrated prediction

For an isotropic point emitter a distance d above a disk of radius R,
`Omega/(4*pi) = [1 - d/sqrt(d*d+R*R)]/2`. The highest-plane disk covering each
crystal subtends about 4.97% / 5.24% of the full sphere. This envelope disk
ignores the bore/groove-dependent material path lengths.

Using NIST total attenuation data interpolated between 0.6 and 0.8 MeV,
`mu_Ge` near 661.657 keV is about 0.38 cm^-1. The volume/projected-area mean
crystal thickness gives an interaction probability of only roughly 23–27%.
The nominal central-ray aluminum thickness (0.1 mm capsule + 1.25 mm curved
wall + 1.27 mm inner shield roof) transmits about 95% without interaction.
These central thicknesses are inferred from the actual saved solids and poses;
this estimate does not integrate the full angular material distribution.
The 0.40 mm polyethylene fill on the central path is omitted from this quick
attenuation estimate; volume/area is not the source-weighted mean chord.

Multiplying the actual emitted-line-photon yield by solid angle, approximate
aluminum transmission and mean-thickness interaction probability gives roughly
1.06% / 0.95% per initial decay. The observed 1.21% / 1.15% is therefore not an
obvious order-of-magnitude inconsistency. The estimate is not precise enough to
validate the simulation, source survey or efficiency. Total attenuation includes
coherent scattering; it is not the mass energy-absorption coefficient or a
full-energy-peak probability. Non-line radiation and scattered-in photons are
also omitted from this simple estimate.

Primary coefficient tables: [NIST Ge](https://physics.nist.gov/PhysRefData/XrayMassCoef/ElemTab/z32.html)
and [NIST Al](https://physics.nist.gov/PhysRefData/XrayMassCoef/ElemTab/z13.html).
`source_efficiency_audit.mjs` records the inputs, interpolation, hashes and exact
saved counts. It never invokes Geant4 transport, SSD or readout.
