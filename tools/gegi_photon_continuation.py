"""Photon continuation after a first Ge interaction, conditional on its outgoing ray.

Transport factors follow Yoneda et al., doi:10.1016/j.astropartphys.2022.102765,
equations 16--21. Photoelectric interaction has a path density in mm^-1;
resolved scatter and escape has a joint path/exit-energy density in mm^-1 keV^-1.
The nominal full-absorption hypothesis places a delta mass at complete local
energy loss at the final vertex, conditional on secondary containment.
Comparing these branches in measured space needs the energy/charge/readout response.
"""

from dataclasses import dataclass
import math
from pathlib import Path
import xml.etree.ElementTree as ET

import numpy as np
from scipy.integrate import quad

from gegi_imaging import ELECTRON_REST_KEV


# Reference totals for an independently labeled survival check only.
# https://physics.nist.gov/PhysRefData/XrayMassCoef/ElemTab/z32.html
GE_REFERENCE_KEV = (100., 150., 200., 300., 400., 500., 600., 800., 1000., 1250., 1500.)
GE_REFERENCE_TOTAL_CM2_G = (.555, .2491, .1661, .1131, .09327, .08212, .07452, .06426, .05727, .05101, .04657)
GE_G4_DENSITY_G_CM3 = 5.323  # Geant4 v11.3.2 G4NistMaterialBuilder, G4_Ge


def ge_reference_total_per_mm(energy_keV):
    if not GE_REFERENCE_KEV[0] <= energy_keV <= GE_REFERENCE_KEV[-1]:
        raise ValueError('Energy outside the admitted NIST reference table')
    return float(GE_G4_DENSITY_G_CM3/10 * np.exp(np.interp(math.log(energy_keV), np.log(GE_REFERENCE_KEV),
                                                       np.log(GE_REFERENCE_TOTAL_CM2_G))))


def ge_halfspaces_from_gdml(path):
    """Read the existing unrotated-placement Ge intersection of two rotated boxes."""
    root = ET.parse(Path(path)).getroot()
    volumes = {value.attrib['name']:value for value in root.findall('structure/volume')}
    solids = {value.attrib['name']:value for value in root.find('solids')}
    ge = volumes['germanium']
    if ge.find('materialref').attrib['ref'] != 'G4_Ge':
        raise ValueError('Expected saved GeGI G4_Ge crystal')

    def xyz(node, units):
        if node is None:  # Omitted GDML placement is the zero translation/rotation.
            return np.zeros(3)
        if node.attrib['unit'] != units:
            raise ValueError(f'Expected GDML {units} units')
        return np.array([float(node.attrib[a]) for a in 'xyz'])

    def placement(name):
        found = [value for volume in volumes.values() for value in volume.findall('physvol')
                 if value.find('volumeref').attrib['ref'] == name]
        value, = found
        if np.any(xyz(value.find('rotation'), 'deg')):
            raise ValueError('Expected unrotated saved GeGI enclosure and crystal placements')
        return xyz(value.find('position'), 'mm')

    center = placement('cryostat_vacuum')+placement('germanium')
    intersection = solids[ge.find('solidref').attrib['ref']]
    if (intersection.tag != 'intersection' or np.any(xyz(intersection.find('position'), 'mm')) or
            np.any(xyz(intersection.find('rotation'), 'deg'))):
        raise ValueError('Expected the saved centered GeGI box intersection')
    normals, offsets = [], []
    for ref in ('first', 'second'):
        wrapper = solids[intersection.find(ref).attrib['ref']]
        node, = wrapper.findall('multiUnionNode')
        box = solids[node.find('solid').attrib['ref']]
        rx, ry, rz = xyz(node.find('rotation'), 'deg')
        if box.tag != 'box' or box.attrib['lunit'] != 'mm' or rx or ry:
            raise ValueError('Expected millimeter crystal boxes with a z-only relative rotation')
        x, y = math.cos(math.radians(rz)), math.sin(math.radians(rz))
        axes = np.array([[x,y,0],[-y,x,0],[0,0,1]])
        half = np.array([float(box.attrib[a])/2 for a in 'xyz'])
        box_center = center+xyz(node.find('position'), 'mm')
        normals.extend(np.vstack((axes, -axes)))
        offsets.extend(np.r_[half+axes@box_center, half-axes@box_center])
    return np.array(normals), np.array(offsets)


def exit_distance_mm(crystal, origin_mm, directions):
    """First intersection of an interior-origin unit ray with the convex crystal."""
    normals, offsets = crystal
    origin = np.asarray(origin_mm, dtype=float)
    rays = np.asarray(directions, dtype=float)
    distance_to_faces = offsets - normals@origin
    if (origin.shape != (3,) or not np.isfinite(origin).all() or distance_to_faces.min() < -1e-9 or
            rays.shape[-1] != 3 or not np.allclose(np.linalg.norm(rays, axis=-1), 1., atol=1e-10, rtol=0.)):
        raise ValueError('Crystal exit requires an interior point and unit rays')
    outward = rays@normals.T
    distance = np.full(outward.shape, np.inf)
    np.divide(np.maximum(0., distance_to_faces), outward, out=distance, where=outward > 0.)
    return np.min(distance, axis=-1)


def _angle_model(incident_keV):
    if not math.isfinite(incident_keV) or incident_keV <= 0:
        raise ValueError('Klein–Nishina requires positive incident energy')
    x = incident_keV/ELECTRON_REST_KEV

    def shape(u):
        k = 1/(1 + x*(1-u))
        return k*k*(k + 1/k - (1-u*u))

    normalizer = quad(shape, -1., 1., epsabs=1e-12, epsrel=1e-11)[0]

    def density(cosine):
        if not -1 <= cosine <= 1:
            raise ValueError('Klein–Nishina requires a physical cosine')
        return shape(cosine)/normalizer

    return density


def cosine_density(incident_keV, cosine):
    """Unpolarized free stationary-electron Klein–Nishina density in d(cos theta)."""
    return _angle_model(incident_keV)(cosine)


def solid_angle_density_per_sr(incident_keV, cosine):
    return cosine_density(incident_keV, cosine)/(2*math.pi)


def _outgoing_cosine(incident_keV, outgoing_keV):
    # Used only within the physical endpoint range. Clip roundoff at backscatter.
    return max(-1., 1-ELECTRON_REST_KEV*(1/outgoing_keV-1/incident_keV))


def outgoing_energy_model(incident_keV):
    """Prepare one normalized KN energy density for repeated use at fixed energy."""
    angle_density = _angle_model(incident_keV)
    minimum = incident_keV/(1+2*incident_keV/ELECTRON_REST_KEV)

    def density(outgoing_keV):
        if not math.isfinite(outgoing_keV):
            raise ValueError('Outgoing photon energy must be finite')
        if not minimum <= outgoing_keV <= incident_keV:
            return 0.
        return angle_density(_outgoing_cosine(incident_keV, outgoing_keV))*ELECTRON_REST_KEV/outgoing_keV**2

    return minimum, density


def outgoing_density_per_keV(incident_keV, outgoing_keV):
    """Transform the normalized cosine density with |d cos(theta)/d E_out|."""
    _, density = outgoing_energy_model(incident_keV)
    return density(outgoing_keV)


def azimuth_survival(crystal, second_mm, incoming_direction, cosine, total_outgoing_per_mm, *, samples):
    """Average the zero-interaction Ge exit survival at fixed final scatter angle."""
    u = np.asarray(incoming_direction, dtype=float)
    if (u.shape != (3,) or not np.isclose(np.linalg.norm(u), 1., atol=1e-10, rtol=0.) or not -1 <= cosine <= 1 or
            not math.isfinite(total_outgoing_per_mm) or total_outgoing_per_mm < 0 or type(samples) is not int or samples < 1):
        raise ValueError('Invalid outgoing cone, attenuation or quadrature count')
    transverse = np.cross(u, np.eye(3)[np.argmin(np.abs(u))])
    transverse /= np.linalg.norm(transverse)
    phase = np.arange(samples)*2*math.pi/samples
    rays = cosine*u + math.sqrt(1-cosine*cosine)*(np.cos(phase)[:,None]*transverse + np.sin(phase)[:,None]*np.cross(u, transverse))
    lengths = exit_distance_mm(crystal, second_mm, rays)
    return float(np.mean(np.exp(-total_outgoing_per_mm*lengths)))


@dataclass(frozen=True)
class PhotonRates:
    total_per_mm: float
    photoelectric_per_mm: float
    compton_per_mm: float

    def __post_init__(self):
        if (not all(math.isfinite(rate) and rate >= 0 for rate in (self.total_per_mm, self.photoelectric_per_mm, self.compton_per_mm)) or
                self.photoelectric_per_mm+self.compton_per_mm > self.total_per_mm):
            raise ValueError('Invalid explicitly supplied material rate decomposition')


def rates_from_csv(path):
    """Read the scoped initialization-only Geant4 export in keV and inverse mm."""
    import csv

    rates = {}
    with Path(path).open(newline='') as stream:
        for row in csv.DictReader(stream):
            photo, compt, coherent, pair = [float(row[field+'_per_mm']) for field in ('photoelectric', 'compton', 'rayleigh', 'pair')]
            if not math.isclose(float(row['density_g_cm3']), GE_G4_DENSITY_G_CM3, rel_tol=1e-14):
                raise ValueError('Initialized Ge density differs from the saved material')
            energy = float(row['energy_keV'])
            if not math.isfinite(energy) or energy <= 0 or energy in rates or any(
                    not math.isfinite(rate) or rate < 0 for rate in (coherent, pair)):
                raise ValueError('Invalid rate table energy or coefficient')
            rates[energy] = PhotonRates(math.fsum((photo, compt, coherent, pair)), photo, compt)
    return rates


def continuation(crystal, first_mm, second_mm, intermediate_keV, rates, *, outgoing_keV=None,
                 outgoing_total_per_mm=None, azimuth_samples=256):
    """Point continuation conditional on the outgoing state at the first scatter.

    The axial path measure is d(length). Converting a fixed first-scatter
    angular density and this path measure to dV2 additionally requires 1/L^2.
    """
    second = np.asarray(second_mm, dtype=float)
    delta = second - np.asarray(first_mm, dtype=float)
    length = float(np.linalg.norm(delta))
    if not math.isfinite(length) or length <= 0 or not math.isfinite(intermediate_keV) or intermediate_keV <= 0:
        raise ValueError('Two distinct vertices and positive intermediate photon energy required')
    axis = delta/length
    exit_distance_mm(crystal, second, axis)
    if exit_distance_mm(crystal, first_mm, axis) < length-1e-9:
        raise ValueError('The conditional Ge path crosses a boundary before the second vertex')
    between = math.exp(-rates.total_per_mm*length)
    result = dict(internal_path_mm=length, no_interaction_survival_to_second=between,
                  photoelectric_path_density_per_mm=between*rates.photoelectric_per_mm,
                  resolved_escape_density_per_mm_keV=None)
    if outgoing_keV is not None:
        energy_density = outgoing_density_per_keV(intermediate_keV, outgoing_keV)
        if not energy_density:
            return dict(result, resolved_escape_density_per_mm_keV=0., status='free_electron_kinematics_inadmissible')
        cosine = _outgoing_cosine(intermediate_keV, outgoing_keV)
        average = azimuth_survival(crystal, second, axis, cosine, outgoing_total_per_mm, samples=azimuth_samples)
        result.update(escape_azimuth_survival=average, normalized_kn_outgoing_density_per_keV=energy_density,
                      resolved_escape_density_per_mm_keV=between*rates.compton_per_mm*energy_density*average)
    return dict(result, status='conditional_ge_continuation')


def saved_controls(probe, kinetics_path, observer_root):
    """Check exact history energies and actual Ge exits against the analytic paths."""
    import hashlib
    import json
    import sys

    transport_dir = Path(__file__).resolve().parents[1] / 'transport'
    sys.path.insert(0, str(transport_dir))
    from gegi_photon_steps import photon_steps

    def digest(path):
        with path.open('rb') as stream:
            return hashlib.file_digest(stream, 'sha256').hexdigest()

    execution = json.loads((probe/'execution.json').read_bytes())
    if (execution['returncode'] or execution['primaries'] or
            any(digest(probe/name) != expected for name, expected in execution['inquiry_sha256'].items()) or
            execution['photon_rates_sha256'] != digest(probe/'photon-rates.csv')):
        raise ValueError('Expected the initialized zero-event rate export')
    crystal = ge_halfspaces_from_gdml(probe/'geometry.gdml')
    rate_at = rates_from_csv(probe/'photon-rates.csv')
    actual = json.loads(kinetics_path.read_bytes())
    trials = []
    labels = {'compton_then_absorption': 'phot', 'two_compton_then_escape': 'compt'}
    for row in actual['rows']:
        topology = row['topology']
        if topology not in labels:
            continue
        tid = row['original_trigger_id']
        evidence = row['observer_provenance']
        observed = observer_root/f'b{evidence["block"]:06d}'
        verification_path = observed/'observer-verification.json'
        if (digest(verification_path) != evidence['verification_sha256'] or
                digest(observed/'photon-steps.csv') != evidence['sidecar_sha256'] or
                digest(observed/'geometry.gdml') != execution['inquiry_sha256']['geometry.gdml']):
            raise ValueError(f'Saved exact geometry or photon sidecar differs for {tid}')
        verification = json.loads(verification_path.read_bytes())
        target = next(value for value in verification['targets'] if value['original_trigger_id'] == tid)
        track = row['photon_kinetics']['depositing_photon_track_id']
        expected = row['photon_kinetics']['exact_ge_photon_interactions']
        history = {step['step_number']:step for step in photon_steps(observed/'photon-steps.csv')
                   if step['event_id'] == target['local_geant4_event_id'] and step['track_id'] == track}
        first, second = [history[step['observed_step_number']] for step in expected]
        if ([first['process'], second['process']] != ['compt', labels[topology]] or
                first['post']['kinetic_keV'] != second['pre']['kinetic_keV'] or
                first['post']['position_mm'] != second['pre']['position_mm'] or
                any(step['pre'] != old['pre'] or step['post'] != old['post']
                    for step, old in zip((first, second), expected, strict=True))):
            raise ValueError(f'Photon energy and vertex chronology differ for {tid}')
        r1, r2 = first['post']['position_mm'], second['post']['position_mm']
        energy = second['pre']['kinetic_keV']
        rates = rate_at[energy]
        measured = dict(original_trigger_id=tid, cohort=row['sample'], topology=topology,
            original_transport_event_id=target['original_driver_id'], photon_track_id=track,
            first_mm=r1, second_mm=r2, intermediate_keV=energy,
            intermediate_rates_per_mm=vars(rates), nist_reference_intermediate_total_per_mm=ge_reference_total_per_mm(energy))
        if topology == 'compton_then_absorption':
            if second['post']['kinetic_keV'] != 0:
                raise ValueError('Expected a terminal photon photoelectric interaction')
            measured['conditional_factors'] = continuation(crystal, r1, r2, energy, rates)
        else:
            outgoing = second['post']['kinetic_keV']
            path = history[second['step_number']+1]
            if (path['process'] != 'Transportation' or path['pre']['position_mm'] != r2 or
                    path['pre']['kinetic_keV'] != outgoing or path['post']['kinetic_keV'] != outgoing or
                    path['pre']['physical_volume'] != 'germanium' or path['post']['physical_volume'] == 'germanium'):
                raise ValueError(f'Expected an unchanged-energy Ge exit segment for {tid}')
            direction = second['post']['direction']
            true_distance = math.dist(r2,path['post']['position_mm'])
            distance = float(exit_distance_mm(crystal, r2, direction))
            if abs(distance-true_distance) > 1e-9:
                raise ValueError(f'Analytic exit disagrees with the observed Geant4 exit for {tid}')
            total_out = rate_at[outgoing].total_per_mm
            results = {samples:continuation(crystal, r1, r2, energy, rates, outgoing_keV=outgoing,
                outgoing_total_per_mm=total_out, azimuth_samples=samples) for samples in (256,1024)}
            measured.update(escaping_keV=outgoing, outgoing_total_per_mm=total_out, recorded_exit_mm=true_distance,
                analytic_exit_mm=distance, recorded_ray_survival=math.exp(-total_out*distance),
                conditional_factors=results[1024], azimuth_samples=1024,
                azimuth_256_minus_1024=results[256]['escape_azimuth_survival']-results[1024]['escape_azimuth_survival'])
        trials.append(measured)
    return dict(kind='gegi_photon_continuation_saved_controls_v1', source_sha256=digest(Path(__file__)),
        inputs=dict(execution_sha256=digest(probe/'execution.json'), exact_kinetics_sha256=digest(kinetics_path),
                    photon_reader_sha256=digest(transport_dir/'gegi_photon_steps.py'), rates_sha256=execution['photon_rates_sha256'],
                    scoped_geometry_sha256=execution['inquiry_sha256']['geometry.gdml']),
        domain='Bulk germanium only, conditional on the first outgoing photon state. Path lengths are millimeters and energies keV.',
        model='Partial and total Ge attenuation use the initialized Livermore application. The normalized last-scatter energy density '
              'and unobserved-azimuth average use free stationary, unpolarized electrons. The retained Geant4 histories use bound-electron transport.',
        next_input='A complete measured likelihood additionally needs entrance and passive-volume transport, secondary-energy containment, '
                   'a joint measured energy/position response, and probability of retained acquisition and topology selection.',
        trials=trials)


def main():
    import argparse
    import json

    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('probe', 'kinetics', 'observer-root', 'output'):
        parser.add_argument('--'+name, type=Path, required=True)
    args = parser.parse_args()
    result = saved_controls(args.probe, args.kinetics, args.observer_root)
    with args.output.open('x', encoding='utf8', newline='\n') as stream:
        json.dump(result, stream, indent=2, allow_nan=False)
        stream.write('\n')
    print(json.dumps(dict(controls=len(result['trials']))))


if __name__ == '__main__':
    main()
