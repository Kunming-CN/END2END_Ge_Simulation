"""Data-bound Ba137m inventory at the start of a steady Cs137 point source.

Only inventory mathematics and record adaptation live here; no transport starts.
An initial Poisson population followed by independent exponential deaths is a
nonhomogeneous Poisson decay stream after averaging over the initial population.
Its conditional lazy implementation stores a population count, not its nuclei.
"""
from __future__ import annotations
import copy
from functools import lru_cache
import hashlib
import json
import math
import os
from pathlib import Path

import numpy as np

POLICY = 'secular_equilibrium_poisson_daughters_v1'
KIND = 'gegi_initial_Ba137m_inventory_v1'
SOURCE_ID = 'cs137_point_decay_v1'
DAUGHTER_SOURCE_ID = 'ba137m_initial_inventory_v1'
DATA = {
    'cs137_decay': ('G4RADIOACTIVEDATA', 'z55.a137', 'RadioactiveDecay6.1.2',
                   '350002c36260fdfc7f1c0951709d0e8bc615f1ecd164827055b29980ab12b95f'),
    'ba137_decay': ('G4RADIOACTIVEDATA', 'z56.a137', 'RadioactiveDecay6.1.2',
                   '0bd88f7a664b604dfbcbd12b01eaa1a54093b4faff60ca91b911b2af13cd773a'),
    'ba137_levels': ('G4LEVELGAMMADATA', 'z56.a137', 'PhotonEvaporation6.1',
                    '8876f2971f53cb0a8989ef57147ded17bb6a6f41bc3dc73718f6ae13facaca4c'),
    'ensdf_states': ('G4ENSDFSTATEDATA', 'ENSDFSTATE.dat', 'ENSDFSTATE3.0',
                    '12b2b4a608b445914fa29a39600dd1ec324fffd5cae20ad09b26bbe9ff0a224c'),
}
REFERENCES = {
    'branch_normalization_and_lifetime': 'https://github.com/Geant4/geant4/blob/v11.3.2/source/processes/hadronic/models/radioactive_decay/src/G4VRadioactiveDecay.cc',
    'gps_excitation_keV': 'https://github.com/Geant4/geant4/blob/v11.3.2/source/event/src/G4GeneralParticleSourceMessenger.cc',
    'ion_excitation_and_pdg': 'https://github.com/Geant4/geant4/blob/v11.3.2/source/particles/management/src/G4IonTable.cc',
    'initial_decay_reset': 'https://github.com/legend-exp/remage/blob/v1.1.0/src/RMGTrackingAction.cc',
}


def require(condition, message):
    if not condition: raise ValueError(message)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _records(text):
    return [line.split() for line in text.splitlines() if line.strip() and not line.lstrip().startswith('#')]


def parameters_from_texts(texts, bindings):
    """Read native BetaMinus normalization, matched state and PDG mean lifetime."""
    cs = _records(texts['cs137_decay'])
    feeding = [{'excitation_keV': float(row[1]), 'raw_intensity': float(row[3])}
               for row in cs if len(row) >= 5 and row[0] == 'BetaMinus' and row[2] == '-']
    require(feeding and all(row['raw_intensity'] >= 0 for row in feeding), 'Missing physical Cs137 beta branches')
    mode = [row for row in cs if len(row) == 3 and row[0] == 'BetaMinus']
    require(len(mode) == 1 and float(mode[0][2]) == 1., 'Unsupported Cs137 decay-mode branching')
    states = [{'energy_keV': float(row[2]), 'mean_lifetime_ns': float(row[4])}
              for row in _records(texts['ensdf_states']) if row[:2] == ['56', '137']]
    rdm = {float(row[1]): float(row[3]) for row in _records(texts['ba137_decay']) if row[0] == 'P'}
    candidates = [(branch, state) for branch in feeding for state in states
                  if branch['excitation_keV'] == state['energy_keV'] > 0 and state['mean_lifetime_ns'] > 0
                  and state['energy_keV'] in rdm]
    require(len(candidates) == 1, 'Cs feeding does not identify one matched Ba137 metastable state')
    branch, state = candidates[0]; energy = state['energy_keV']; mean_ns = state['mean_lifetime_ns']
    levels = [row for row in _records(texts['ba137_levels']) if len(row) == 6 and row[1] == '-'
              and float(row[2]) == energy]
    require(len(levels) == 1 and float(levels[0][3]) == rdm[energy] > 0,
            'RDM/PhotonEvaporation metastable half-lives differ')
    # This is the first excited ENSDF state for Ba137. Actual source registration
    # must still check Geant4 GetExcitationEnergy/PDG, rather than using ionLvl.
    rank = sorted(row['energy_keV'] for row in states if row['energy_keV'] > 0).index(energy)+1
    require(rank == 1, 'Pinned Ba137m isomer ordering changed')
    total = math.fsum(row['raw_intensity'] for row in feeding)
    probability = branch['raw_intensity']/total
    require(abs(mean_ns*1e-9*math.log(2)/rdm[energy]-1) < 1e-6,
            'ENSDF native lifetime and tabulated half-life are inconsistent')
    return {'kind': 'gegi_Ba137m_nuclear_parameters_v1', 'Z': 56, 'A': 137,
            'excitation_keV': energy, 'expected_isomer_level': rank, 'expected_pdg': 1000561370+rank,
            'mean_lifetime_ns': mean_ns, 'lambda_per_ns': 1./mean_ns,
            'tabulated_half_life_s': rdm[energy], 'feeding_probability': probability,
            'raw_beta_branch_intensity_sum': total, 'cs137_beta_branches': feeding,
            'feeding_policy': 'Geant4 per-mode normalized intensity; not gamma emission probability.',
            'lifetime_policy': 'ENSDF native PDG mean lifetime, matching G4VRadioactiveDecay; rounded RDM/PhotonEvaporation half-life retained separately.',
            'data': bindings, 'references': REFERENCES,
            'native_registration_status': 'Data/API-derived; initial Ba137m ion transport acceptance still required.'}


@lru_cache(maxsize=1)
def installed_parameters():
    import gegi_source as S
    runtime = S.runtime_snapshot(); prefix = Path(runtime['prefix']).resolve()
    texts, bindings = {}, {}
    for key, (variable, name, version, expected) in DATA.items():
        directory = Path(os.environ.get(variable, '/missing')).resolve(); path = directory/name
        require(directory.is_relative_to(prefix) and directory.name == version, 'Use pinned installed nuclear datasets')
        body = path.read_bytes(); actual = hashlib.sha256(body).hexdigest()
        require(actual == expected, 'Installed inventory nuclear data changed: '+key)
        texts[key] = body.decode('utf-8')
        bindings[key] = {'dataset': version, 'filename': name, 'sha256': actual}
    result = parameters_from_texts(texts, bindings)
    result['software'] = {key: runtime['packages'][key]['version'] for key in
                          ('remage', 'geant4', 'geant4-data-radioactivedecay',
                           'geant4-data-photonevaporation', 'geant4-data-ensdfstate')}
    return result


def contract(parameters, activity_bq=185000., position_mm=(-40., 0., 40.)):
    require(type(activity_bq) in (int, float) and math.isfinite(activity_bq) and activity_bq > 0,
            'Initial inventory requires positive Cs137 parent activity')
    require(len(position_mm) == 3 and all(type(x) in (int, float) and math.isfinite(x) for x in position_mm),
            'Define the initial daughter source position in mm')
    rate_per_s = activity_bq*parameters['feeding_probability']
    return {'kind': KIND, 'policy': POLICY, 'parameters': parameters,
            'parameters_sha256': digest(parameters), 'cs137_activity_Bq': activity_bq,
            'source_id': SOURCE_ID, 'position_global_mm': list(position_mm),
            'mean_initial_nuclei': rate_per_s*parameters['mean_lifetime_ns']*1e-9,
            'initial_mean_decay_rate_per_s': rate_per_s,
            'source_age_assumption': 'Stationary parent activity before t=0; secular daughter equilibrium.',
            'new_parent_policy': 'New Cs137 physical daughter cascades remain in native transport; never added again by this initial-inventory process.',
            'electronics_initial_state': 'Existing explicit quiet zero; no electronic warm-up implied.'}


def contract_from_installed(activity_bq=185000., position_mm=(-40., 0., 40.)):
    return contract(installed_parameters(), activity_bq, position_mm)


def expected_initial_decays(contract_value, stop_ns):
    require(math.isfinite(stop_ns) and stop_ns >= 0, 'Use a finite nonnegative time')
    return contract_value['mean_initial_nuclei']*(-math.expm1(-stop_ns*contract_value['parameters']['lambda_per_ns']))


def initialize(contract_value, seed, acquisition_id):
    require(type(seed) is int and 0 <= seed < 2**64 and type(acquisition_id) is str and acquisition_id,
            'Define an independent inventory RNG seed and acquisition identity')
    require(contract_value['parameters_sha256'] == digest(contract_value['parameters']), 'Inventory parameters changed')
    rng = np.random.Generator(np.random.PCG64(seed))
    initial = int(rng.poisson(contract_value['mean_initial_nuclei']))
    return {'kind': KIND, 'contract': contract_value, 'contract_sha256': digest(contract_value),
            'acquisition_id': acquisition_id, 'inventory_seed': seed, 'numpy_version': np.__version__,
            'rng_kind': 'numpy.random.PCG64', 'rng_state': copy.deepcopy(rng.bit_generator.state),
            'initial_nuclei': initial, 'remaining_nuclei': initial,
            'generated_initial_daughter_decays': 0, 'last_decay_time_ns': 0., 'pending_decay': None}


def next_decay(state):
    """Return one scheduled initial-daughter decay with no fabricated parent.

    Given n remaining independent nuclei, the next death has rate n*lambda.
    Starting n~Poisson(mean) is exactly the requested unconditional NHPP law.
    The count and clocks therefore remain consistent, unlike independent draws
    of an initial count and an unrelated NHPP event stream.
    """
    # The contract is immutable/hash-bound; only top-level state is advanced.
    result = dict(state); value = result['contract']
    require(result['kind'] == KIND and result['contract_sha256'] == digest(value), 'Inventory checkpoint changed')
    require(result['rng_kind'] == 'numpy.random.PCG64' and result['numpy_version'] == np.__version__,
            'Resume with the recorded inventory RNG implementation')
    if result['pending_decay'] is not None:
        row = result['pending_decay']; result['pending_decay'] = None
        return row, result
    if result['remaining_nuclei'] == 0: return None, result
    rng = np.random.Generator(np.random.PCG64(0)); rng.bit_generator.state = result['rng_state']
    rate_per_ns = result['remaining_nuclei']*value['parameters']['lambda_per_ns']
    clock = result['last_decay_time_ns']+float(rng.exponential(1./rate_per_ns))
    ordinal = result['generated_initial_daughter_decays']
    row = {'origin': 'initial_daughter_inventory', 'source_id': SOURCE_ID, 'isotope': 'Ba137m',
           'parent_decay_id': None, 'new_parent_decay_id': None, 'initial_daughter_id': ordinal,
           'prehistory_identity': [result['acquisition_id'], 'initial_Ba137m', ordinal],
           'acquisition_id': result['acquisition_id'], 'source_pdg': value['parameters']['expected_pdg'],
           'source_excitation_keV': value['parameters']['excitation_keV'],
           'source_position_global_mm': value['position_global_mm'],
           'absolute_parent_time_ns': clock, 'absolute_decay_time_ns': clock}
    result.update(rng_state=copy.deepcopy(rng.bit_generator.state), remaining_nuclei=result['remaining_nuclei']-1,
                  generated_initial_daughter_decays=ordinal+1, last_decay_time_ns=clock)
    return row, result


def next_block(state, stop_ns, max_decays=500):
    require(type(max_decays) is int and max_decays > 0 and math.isfinite(stop_ns) and stop_ns >= 0,
            'Use a positive block size and explicit [0,T) duration')
    rows = []; result = state
    for _ in range(max_decays):
        row, result = next_decay(result)
        if row is None: break
        if row['absolute_decay_time_ns'] >= stop_ns:
            result['pending_decay'] = row; break
        rows.append(row)
    return rows, result


def gps_registration(parameters):
    return ['/gps/particle ion', '/gps/ion 56 137 0 '+format(parameters['excitation_keV'], '.17g')]


def daughter_contract(parameters, position_mm):
    """Per-root reader contract; physical source_id remains the Cs point source."""
    return {'id': DAUGHTER_SOURCE_ID, 'particle': 'ion', 'pdg': parameters['expected_pdg'],
            'Z': 56, 'A': 137, 'primary_excitation_keV': parameters['excitation_keV'],
            'position_global_mm': list(position_mm), 'diagnostic_lines': [{'name': 'Ba137_661.7', 'window_keV': [660., 663.]}],
            'grouping_policy': {'horizon_ns': 100000}, 'daughter_lifetime_limit_ns': -1}


def validate_initial_tracks(rows, names, meta, parameters):
    """Validate a native ion root and its full IT family, preserving all rows."""
    import gegi_source as S
    vertices, particles, tracks = rows['vtx'], rows['particles'], rows['tracks']
    require(len(vertices) == len(particles) == 1 and vertices[0]['n_part'] == 1 and particles[0]['vertexid'] == 0,
            'Initial daughter requires one native primary vertex and particle')
    require(vertices[0]['time'] == meta['primary_vertex_time_ns'], 'Initial daughter scheduled clock changed')
    position = meta['source_position_global_mm']
    require(np.allclose([1000*vertices[0][a] for a in ('xloc', 'yloc', 'zloc')], position, rtol=0, atol=1e-9),
            'Initial daughter source position changed')
    primary = particles[0]
    require(primary['particle'] == parameters['expected_pdg'] and primary['ekin'] == 0 and
            all(primary[a] == 0 for a in ('px', 'py', 'pz')), 'Initial daughter must be the defined at-rest Ba137m ion')
    by_id = {track['trackid']: track for track in tracks}
    require(len(by_id) == len(tracks) and all(type(tid) is int and tid > 0 for tid in by_id), 'Invalid daughter track identities')
    roots = [t for t in tracks if t['parent_trackid'] == 0]
    require(len(roots) == 1 and roots[0]['particle'] == parameters['expected_pdg'] and roots[0]['ekin'] == 0,
            'Missing/foreign initial Ba137m root')
    root = roots[0]; children = [t for t in tracks if t['parent_trackid'] == root['trackid']]
    require(np.allclose([1000*root[a] for a in ('xloc', 'yloc', 'zloc')], position, rtol=0, atol=1e-9)
            and all(root[a] == 0 for a in ('px', 'py', 'pz')), 'Initial daughter root position/momentum changed')
    require(children and all(t['time'] == 0 for t in children), 'Initial Ba137m decay children were not reset to zero')
    require(any(t['particle'] == 1000561370 for t in tracks), 'Missing stable Ba137 daughter')
    for track in tracks:
        require(track['time'] >= 0 and track['ekin'] >= 0 and
                (track['parent_trackid'] == 0 or track['procid'] in names), 'Invalid native daughter time/energy/process')
        parent = track['parent_trackid']; visited = {track['trackid']}
        while parent:
            require(parent in by_id and parent not in visited, 'Missing/cyclic initial daughter ancestry')
            visited.add(parent); parent = by_id[parent]['parent_trackid']
        parent = track['parent_trackid']
        require(parent in (0, root['trackid']) or track['time'] >= by_id[parent]['time'], 'Daughter birth precedes its parent')
        if abs(track['particle']) >= 1000000000:
            require(track['particle']//10 == 100056137 or S.decay.is_gamma_conversion_target_recoil(
                    track, by_id, names, S.conversion_target_material(track, rows, meta)), 'Unexpected initial daughter nuclear family')
    return by_id
