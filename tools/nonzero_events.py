"""Shared nonzero-deposit storage policy for new student outputs.

An omitted zero-deposit event still belongs to the initial-primary census and
its efficiency denominator. Historical unmarked files keep their dense schema.
"""
from __future__ import annotations
import math

from local_ui_jobs import ControlError
from workflow_batches import MAX_SAFE_INTEGER, typed_equal

KIND = 'nonzero_deposit_v1'
FIELDS = {'kind', 'initial_primaries', 'zero_deposit_primaries',
          'nonzero_primaries', 'efficiency_denominator'}


def require(ok, message):
    if not ok:
        raise ControlError(message, 'nonzero_storage_refused')


def count(value, label):
    require(type(value) is int and 0 <= value <= MAX_SAFE_INTEGER,
            label + ' must be a nonnegative exact integer.')
    return value


def descriptor(initial_primaries, zero_deposit_primaries):
    initial = count(initial_primaries, 'Initial primaries')
    zero = count(zero_deposit_primaries, 'Zero-deposit primaries')
    require(zero <= initial, 'Zero-deposit count exceeds the initial census.')
    return {'kind': KIND, 'initial_primaries': initial,
            'zero_deposit_primaries': zero, 'nonzero_primaries': initial-zero,
            'efficiency_denominator': initial}


def validate_storage(value, counts=None, *, initial_primaries=None):
    require(type(value) is dict and set(value) == FIELDS,
            'Unsupported event-storage descriptor.')
    expected = descriptor(value.get('initial_primaries'), value.get('zero_deposit_primaries'))
    require(typed_equal(value, expected), 'Event storage changed its census or efficiency denominator.')
    if initial_primaries is not None:
        require(type(initial_primaries) is int and initial_primaries == expected['initial_primaries'],
                'Event storage differs from the requested initial-primary count.')
    if counts is not None:
        require(type(counts) is dict and all(type(counts.get(key)) is int and counts[key] == expected[key]
                for key in ('initial_primaries', 'zero_deposit_primaries', 'nonzero_primaries')),
                'Event storage differs from the independently checked census.')
    return expected


def storage(document, counts=None, *, initial_primaries=None):
    """Absence is the historical dense contract; an invalid marker never falls back."""
    require(type(document) is dict, 'Stored event metadata must be an object.')
    if 'event_storage' not in document:
        return None
    return validate_storage(document['event_storage'], counts, initial_primaries=initial_primaries)


def has_nonzero_deposit(event):
    """Use original deposit truth, without selecting by charge/readout acceptance."""
    require(type(event) is dict and type(event.get('steps')) is list,
            'Deposit selection requires original event steps.')
    nonzero = False
    for step in event['steps']:
        require(type(step) is dict and type(step.get('energy_keV')) in (int, float)
                and math.isfinite(step['energy_keV']) and step['energy_keV'] >= 0,
                'Invalid original deposited energy.')
        nonzero = nonzero or step['energy_keV'] != 0
    return nonzero


def nonzero_events(events):
    for event in events:
        if has_nonzero_deposit(event):
            yield event


def initial_summary(manifest):
    """Full census from a marked source manifest, verified against its raw LH5 upstream."""
    policy = storage(manifest, initial_primaries=manifest.get('primary_count'))
    require(policy is not None, 'Sparse source requires explicit event storage.')
    summary = manifest.get('initial_summary')
    required = {'initial_primaries', 'initial_decays', 'zero_deposit_primaries',
                'nonzero_primaries', 'line_photons', 'decay_photons'}
    require(type(summary) is dict and required <= set(summary)
            and set(summary) <= required | {'line_photon_counts'}, 'Sparse source has no complete initial summary.')
    for key in required:
        count(summary[key], key)
    validate_storage(policy, summary)
    require(summary['initial_decays'] == summary['initial_primaries'],
            'Sparse decay source changed its initial-decay census.')
    if 'line_photon_counts' in summary:
        named = summary['line_photon_counts']
        require(type(named) is dict and all(type(key) is str and key for key in named),
                'Invalid named photon census.')
        for key, value in named.items():
            count(value, key)
        require(sum(named.values()) == summary['line_photons'], 'Named photon census differs from its total.')
    return summary


def source_sequence(events, policy, initial_primaries):
    """Check original ordered IDs; sparse row count is never the primary count."""
    count(initial_primaries, 'Requested initial primaries')
    previous = -1
    stored = 0
    for event in events:
        eid = event.get('event_id') if type(event) is dict else None
        require(type(eid) is int and type(event.get('global_decay_id')) is int
                and eid == event['global_decay_id'] and previous < eid < initial_primaries,
                'Source event identities are missing, repeated, reordered or out of range.')
        if policy is None:
            require(eid == stored, 'Historical source primary census is not complete and ordered.')
        else:
            require(has_nonzero_deposit(event), 'Sparse source retained a zero-deposit event.')
        previous = eid
        stored += 1
        yield event
    expected = initial_primaries if policy is None else policy['nonzero_primaries']
    require(stored == expected, 'Source event count differs from its complete initial/nonzero census.')
