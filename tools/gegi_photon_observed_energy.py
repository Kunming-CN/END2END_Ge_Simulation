"""Convolve conditional photon continuation with an explicit second-site energy response.

The physical photoelectric endpoint is a delta mass. The escaped photon energy
maps to deposited energy as E_intermediate - E_escape, with unit Jacobian.
Each component is convolved on the same observed-keV axis and retains its
integrated path density. See Yoneda et al., doi:10.1016/j.astropartphys.2022.102765,
sections 3.2 and 4.1 for the separate measurement term.
"""

import argparse
import hashlib
import json
import math
from pathlib import Path
import platform
import time

import numpy as np
import scipy
from scipy.special import roots_legendre

import gegi_photon_continuation as photon


def gaussian_density_per_kev(observed_keV, deposited_keV, sigma_keV):
    if not all(math.isfinite(x) for x in (observed_keV, deposited_keV, sigma_keV)) or sigma_keV <= 0:
        raise ValueError('Finite observed/deposited energies and an explicit positive Gaussian width are required')
    z = (observed_keV-deposited_keV)/sigma_keV
    return math.exp(-.5*z*z)/(math.sqrt(2*math.pi)*sigma_keV)


def observed_continuation(crystal, first_mm, second_mm, intermediate_keV, rates, outgoing_total, observed_keV,
                          *, sigma_keV, azimuth_samples=256, energy_order=256):
    """Compare densities per observed keV per path-mm with no observed-energy cut."""
    observed_keV = list(observed_keV)
    gaussian_density_per_kev(0., 0., sigma_keV)
    if type(energy_order) is not int or energy_order < 2:
        raise ValueError('Energy quadrature order must admit a coarser positive rule')
    between = photon.continuation(crystal, first_mm, second_mm, intermediate_keV, rates)
    photo_mass = between['photoelectric_path_density_per_mm']
    compt_mass = between['no_interaction_survival_to_second']*rates.compton_per_mm
    min_outgoing, energy_density = photon.outgoing_energy_model(intermediate_keV)
    max_deposit = intermediate_keV-min_outgoing
    axis = (np.asarray(second_mm) - first_mm)/between['internal_path_mm']
    quadrature = [roots_legendre(n) for n in (energy_order//2,energy_order)]

    def escape_spectrum(deposit):
        outgoing = intermediate_keV-deposit
        # Values come from a quadrature on the known physical interval.
        outgoing = min(intermediate_keV,max(min_outgoing,outgoing))
        cosine = photon._outgoing_cosine(intermediate_keV, outgoing)
        survive = photon.azimuth_survival(crystal, second_mm, axis, cosine, outgoing_total(outgoing), samples=azimuth_samples)
        return compt_mass*energy_density(outgoing)*survive

    def integral(fn, knots=()):
        if not compt_mass:
            return 0.,0.
        stops = [0.,*knots,max_deposit]
        results = []
        for nodes, weights in quadrature:
            terms = []
            for left,right in zip(stops[:-1],stops[1:],strict=True):
                half = (right-left)/2
                values = [fn(left+half*(1+node)) for node in nodes]
                terms.append(half*float(np.dot(values,weights)))
            results.append(math.fsum(terms))
        return results[1],abs(results[1]-results[0])

    escape_mass, mass_error = integral(escape_spectrum)
    if escape_mass > compt_mass + 2*mass_error + 1e-12:
        raise ValueError('Escape continuum mass exceeds the available Compton path mass')
    rows = []
    for observed in observed_keV:
        absorption = photo_mass*gaussian_density_per_kev(observed, intermediate_keV, sigma_keV)
        # Segment near the Gaussian mode to resolve even a narrow explicit width.
        knots = [observed+x*sigma_keV for x in (-8,-4,0,4,8) if 0 < observed+x*sigma_keV < max_deposit]
        escape, error = integral(lambda deposit:escape_spectrum(deposit)*gaussian_density_per_kev(observed,deposit,sigma_keV), knots)
        rows.append(dict(observed_keV=observed, absorption_per_mm_observed_keV=absorption,
                         escape_per_mm_observed_keV=escape, escape_quadrature_difference=error))
    return dict(sigma_keV=sigma_keV, energy_response='unit-normalized Gaussian on the entire real observed-energy axis',
                true_absorption_endpoint_keV=intermediate_keV, true_escape_deposit_support_keV=[0.,max_deposit],
                internal_path_mm=between['internal_path_mm'], no_interaction_survival=between['no_interaction_survival_to_second'],
                photoelectric_endpoint_mass_per_mm=photo_mass, pre_escape_Compton_path_mass_per_mm=compt_mass,
                true_escape_continuum_mass_per_mm=escape_mass, escape_mass_quadrature_difference_per_mm=mass_error,
                observed_integrated_mass_per_mm=dict(absorption=photo_mass,escape=escape_mass),
                observations=rows)


def total_rate_interpolator(rates):
    energies = sorted(rates)
    logs = np.log(energies)
    values = np.log([rates[e].total_per_mm for e in energies])

    def interpolate(energy):
        if not energies[0] <= energy <= energies[-1]:
            raise ValueError('Outgoing energy outside the initialized coefficient table')
        return rates[energy].total_per_mm if energy in rates else float(np.exp(np.interp(math.log(energy),logs,values)))

    return interpolate


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def saved_convolutions(probe, extension, kinetics_path, *, sigma_keV, azimuth_samples, energy_order):
    started = time.perf_counter()
    gaussian_density_per_kev(0.,0.,sigma_keV)
    original = json.loads((probe/'execution.json').read_bytes())
    extended = json.loads((extension/'execution.json').read_bytes())
    saved = json.loads((probe/'saved-controls.json').read_bytes())
    if (original['returncode'] or extended['returncode'] or original['primaries'] or extended['primaries'] or
            extended['original_execution_sha256'] != sha(probe/'execution.json') or
            extended['original_controls_sha256'] != sha(probe/'saved-controls.json') or
            saved['inputs']['exact_kinetics_sha256'] != sha(kinetics_path) or
            original['binary_sha256'] != extended['binary_sha256']):
        raise ValueError('Expected the original and extended zero-event coefficient receipts')
    for name in ('rates.mac','geometry.gdml'):
        if sha(probe/name) != original['inquiry_sha256'][name] or sha(extension/name) != sha(probe/name):
            raise ValueError('Initialized material geometry or physics macro changed')
    original_table, extra_table = probe/'photon-rates.csv', extension/'photon-rates.csv'
    if sha(original_table) != original['photon_rates_sha256'] or sha(extra_table) != extended['artifacts_sha256']['photon-rates.csv']:
        raise ValueError('Coefficient bytes differ from their initialized exports')
    rates = photon.rates_from_csv(original_table)
    extra = photon.rates_from_csv(extra_table)
    if set(rates)&set(extra) or set(rates)|set(extra) != set(rates)|set(extended['nested_query_energies_keV']):
        raise ValueError('The original 17 coefficient queries must be reused')
    complete = rates | extra
    coarse_grid = extended['nested_query_energies_keV'][::4]
    fine_rate = total_rate_interpolator(complete)
    coarse_rate = total_rate_interpolator(rates | {e:complete[e] for e in coarse_grid})
    crystal = photon.ge_halfspaces_from_gdml(probe/'geometry.gdml')
    references = {row['original_trigger_id']:row for row in json.loads(kinetics_path.read_bytes())['rows']}
    controls = []
    for row in saved['trials']:
        reference = references[row['original_trigger_id']]
        combined = reference['substitution_control']
        physical = combined['exact_transfers_keV'][1]
        adc_fit = combined['substitutions_by_incident_energy']['true_incident_at_first_ge_vertex']['substitute_both_signal_quantities']
        energies = adc_fit.get('transfers_or_cell_energies_keV')
        measured = energies[1] if energies is not None else None
        evaluation_points = [physical] if measured is None else [physical,measured]
        E1 = row['intermediate_keV']
        args = (crystal,row['first_mm'],row['second_mm'],E1,rates[E1])
        fine, coarse = [observed_continuation(*args, total, evaluation_points, sigma_keV=sigma_keV,
                                            azimuth_samples=azimuth_samples, energy_order=energy_order)
                        for total in (fine_rate,coarse_rate)]
        controls.append(dict(original_trigger_id=row['original_trigger_id'], sample=row['cohort'], verified_topology=row['topology'],
            second_site_measurement_status=reference['score_status'], measured_second_site_keV=measured,
            exact_photon_transfer_keV=physical, at_exact_transfer=fine['observations'][0],
            at_measured_energy=fine['observations'][1] if measured is not None else None,
            integrated_path_masses={k:v for k,v in fine.items() if k!='observations'},
            coarse_grid_check=dict(escape_mass_difference_per_mm=
                coarse['true_escape_continuum_mass_per_mm']-fine['true_escape_continuum_mass_per_mm'],
                escape_density_differences_per_mm_observed_keV=[a['escape_per_mm_observed_keV']-b['escape_per_mm_observed_keV']
                    for a,b in zip(coarse['observations'],fine['observations'],strict=True)])))
    return dict(kind='gegi_conditional_second_site_observed_energy_v1',
        input_sha256=dict(continuation_receipt=sha(probe/'saved-controls.json'), exact_kinetic_controls=sha(kinetics_path),
                           original_rate_receipt=sha(probe/'execution.json'), extended_rate_receipt=sha(extension/'execution.json'),
                           original_rates=sha(original_table), extension_rates=sha(extra_table)),
        source_sha256={Path(__file__).name:sha(__file__), Path(photon.__file__).name:sha(photon.__file__)},
        software=dict(python=platform.python_version(),numpy=np.__version__,scipy=scipy.__version__),
        calculation=dict(explicit_sigma_keV=sigma_keV, azimuth_samples=azimuth_samples,
            energy_quadrature_nodes_per_segment=[energy_order//2,energy_order],
            coefficient_interpolation='log-linear total inverse-mm; exact initialized points override interpolation',
            new_initialized_energies=len(extra), original_initialized_energies=len(rates),
            comparison_nested_coarse_nodes=len(coarse_grid), nominal_test_width_scope='Analytic acceptance input only. '
            'The saved independent ADC studies characterize fixed pulser gain or conditional waveform fits and synthetic voltage noise. '
            'Their inputs do not calibrate a joint per-site energy response in retained triggers.'),
        scope='Conditional on the exact first outgoing state and original vertices for these validation histories. '
              'The Gaussian spreads second-site energy only. The same observed-energy measure and full retained mass '
              'apply to both branches. First-site uncertainty, secondary containment, charge topology, and trigger selection '
              'remain separate. Densities and mass are not calibrated hypothesis or source weights.',
        controls=controls,elapsed_seconds=time.perf_counter()-started)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('probe','rate-extension','kinetics','output'):
        parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--sigma-kev',type=float,required=True)
    parser.add_argument('--azimuth-samples',type=int,default=256)
    parser.add_argument('--energy-order',type=int,default=256)
    args = parser.parse_args()
    result = saved_convolutions(args.probe,args.rate_extension,args.kinetics,sigma_keV=args.sigma_kev,
                                azimuth_samples=args.azimuth_samples,energy_order=args.energy_order)
    with args.output.open('x',encoding='utf8',newline='\n') as stream:
        json.dump(result,stream,indent=2,allow_nan=False)
        stream.write('\n')
    print(json.dumps(dict(controls=len(result['controls']),seconds=result['elapsed_seconds'])))


if __name__ == '__main__':
    main()
