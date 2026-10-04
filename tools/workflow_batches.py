"""Pure versioned serial-batch arithmetic and radiation identity checks.

No process, filesystem writer, scheduler, or simulation is owned here. The v2
contract is a preview until the separately reviewed execution milestone.
"""
from __future__ import annotations
import copy
import math
from pathlib import PurePosixPath
import re

from local_ui_jobs import ControlError

KIND = 'local_scenario_batch_preview_v2'
REQUEST_KIND = 'local_scenario_batch_request_v2'
MAX_SAFE_INTEGER = 9007199254740991
BATCH_CAP = 10000
SEED_MAX = 2147483646
SEED_STRIDE = 104729
MAX_SEEDED_PRIMARIES = SEED_MAX * BATCH_CAP
SEED_RULE = 'remage_affine_permutation_v1'
IDENTITY_RULE = 'zero_based_batch_offset_v1'


def require(ok, message):
    if not ok:
        raise ControlError(message, 'batch_preview_refused')


def exact_integer(value, minimum, maximum, label):
    require(type(value) is int and minimum <= value <= maximum,
            f'{label} must be an exact integer between {minimum} and {maximum}; no rounding or coercion is allowed.')
    return value


def primary_count(value):
    return exact_integer(value, 1, MAX_SAFE_INTEGER, 'Primary count')


def partition(count, seed):
    count = primary_count(count)
    exact_integer(seed, 1, SEED_MAX, 'Radiation seed')
    batches = (count + BATCH_CAP - 1) // BATCH_CAP
    require(batches <= SEED_MAX,
            f'The unique radiation-seed limit is {SEED_MAX} batches ({MAX_SEEDED_PRIMARIES} primaries), separate from numeric representability and the {BATCH_CAP} per-batch cap.')
    require(math.gcd(SEED_STRIDE, SEED_MAX) == 1, 'Seed rule is not collision-free.')
    return {'schema_version': 2, 'batch_cap': BATCH_CAP, 'primary_count': count,
            'batch_count': batches, 'last_batch_count': count - (batches-1)*BATCH_CAP,
            'models_serial': True, 'batches_serial': True, 'remage_processes_per_batch': 1,
            'radiation_threads': 1, 'seed_rule': SEED_RULE, 'master_seed': seed,
            'seed_min': 1, 'seed_max': SEED_MAX, 'seed_stride': SEED_STRIDE,
            'identity_rule': IDENTITY_RULE, 'initial_primary_id_range': [0, count-1],
            'limits': {'maximum_exact_primary_count': MAX_SAFE_INTEGER,
                       'maximum_unique_seed_batches': SEED_MAX,
                       'maximum_seeded_primary_count': MAX_SEEDED_PRIMARIES,
                       'resource_acceptance': 'not_established_by_preview'}}


def validate_partition(value):
    require(type(value) is dict, 'Batch descriptor must be an object.')
    expected = partition(value.get('primary_count'), value.get('master_seed'))
    # Dict equality alone would coerce bools and integral floats. The recursive
    # typed equality also checks every fixed rule/limit, including rehashed edits.
    require(typed_equal(value, expected), 'Batch descriptor differs from the versioned count/seed rules.')
    return expected


def typed_equal(a, b):
    if type(a) is not type(b):
        return False
    if type(a) is dict:
        return a.keys() == b.keys() and all(typed_equal(a[k], b[k]) for k in a)
    if type(a) is list:
        return len(a) == len(b) and all(typed_equal(x, y) for x, y in zip(a, b))
    return a == b


def batch_at(descriptor, index):
    value = validate_partition(descriptor)
    exact_integer(index, 0, value['batch_count']-1, 'Batch index')
    offset = index * BATCH_CAP
    count = min(BATCH_CAP, value['primary_count']-offset)
    return {'batch_index': index, 'global_initial_offset': offset,
            'primary_count': count, 'local_initial_primary_id_range': [0, count-1],
            'global_initial_primary_id_range': [offset, offset+count-1],
            'radiation_seed': 1 + (value['master_seed']-1 + index*SEED_STRIDE) % SEED_MAX}


def iter_batches(descriptor):
    """Keep memory independent of N. No all-batch or all-event array."""
    value = validate_partition(descriptor)
    for index in range(value['batch_count']):
        yield batch_at(value, index)


def validate_batch(descriptor, batch):
    require(type(batch) is dict, 'Batch must be an object.')
    expected = batch_at(descriptor, batch.get('batch_index'))
    require(typed_equal(batch, expected), 'Batch count, offset, identity or seed changed; seed collisions are refused.')
    return expected


def validate_seed_receipts(descriptor, records):
    """Check an injected/recorded serial sequence before scientific dispatch."""
    value = validate_partition(descriptor)
    count = 0
    for record in records:
        require(count < value['batch_count'], 'Extra radiation batch receipt.')
        require(typed_equal(record, batch_at(value, count)),
                'Missing, reordered or changed batch/seed receipt; a seed collision is refused.')
        count += 1
    require(count == value['batch_count'], 'Incomplete radiation batch receipt census.')
    return {'batch_count': count, 'unique_radiation_seeds': count, 'seed_rule': SEED_RULE}


def global_initial_id(descriptor, batch, local_id):
    batch = validate_batch(descriptor, batch)
    exact_integer(local_id, 0, batch['primary_count']-1, 'Raw local initial primary ID')
    return batch['global_initial_offset'] + local_id


def map_raw_record(descriptor, batch, raw, *, file, table):
    """Add identity without modifying raw evtid/row/Track/Vertex/time/values."""
    require(type(raw) is dict, 'Raw record must be an object.')
    for name, value in (('file', file), ('table', table)):
        require(type(value) is str and value and '\\' not in value and ':' not in value and
                not value.startswith('/') and all(p not in ('', '.', '..') for p in value.split('/')) and
                str(PurePosixPath(value)) == value, 'Raw '+name+' identity must be a relative canonical key.')
    row = exact_integer(raw.get('raw_row_index'), 0, MAX_SAFE_INTEGER, 'Raw row index')
    global_id = global_initial_id(descriptor, batch, raw.get('evtid'))
    return {'global_initial_primary_id': global_id, 'batch_index': batch['batch_index'],
            'raw_identity': {'file': file, 'table': table, 'raw_row_index': row,
                             'local_initial_primary_id': raw['evtid']},
            'raw': copy.deepcopy(raw)}


def validate_census(descriptor, batch, *, macro_text, number_of_simulated_events, initial_ids):
    """Independently compare active beamOn, remage count and complete ledger.

    The ledger contains every initial ID once, including zero deposits and failed
    charge responses. Descendant Track/Vertex rows and pulse groups are not this
    initial-primary census. Readers supply their checked raw count/ID stream.
    """
    batch = validate_batch(descriptor, batch)
    require(type(macro_text) is str, 'Native macro must be text.')
    active = [line.split('#', 1)[0].strip() for line in macro_text.splitlines()]
    commands = [line for line in active if line and line.split()[0] == '/run/beamOn']
    require(len(commands) == 1 and re.fullmatch(r'/run/beamOn\s+[1-9][0-9]*', commands[0]),
            'Native macro requires exactly one literal positive beamOn count.')
    beam_on = int(commands[0].split()[1])
    raw_count = exact_integer(number_of_simulated_events, 1, BATCH_CAP, 'Raw number_of_simulated_events')
    require(beam_on == raw_count == batch['primary_count'],
            'beamOn, raw number_of_simulated_events and planned batch count disagree; radiation threads cannot multiply the count.')
    count = 0
    for local_id in initial_ids:
        require(count < raw_count, 'Extra initial primary ledger row.')
        exact_integer(local_id, 0, raw_count-1, 'Ledger local initial primary ID')
        require(local_id == count, 'Initial ledger has a missing, repeated, reordered or foreign ID.')
        count += 1
    require(count == raw_count, 'Initial ledger is incomplete; zeros and failures must remain present.')
    return {'batch_index': batch['batch_index'], 'beam_on': beam_on,
            'number_of_simulated_events': raw_count, 'initial_ledger_count': count,
            'global_initial_primary_id_range': batch['global_initial_primary_id_range']}
