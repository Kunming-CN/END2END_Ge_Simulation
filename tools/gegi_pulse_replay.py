"""Replay two saved GeGI responses on one ADC clock. Each trigger includes its
single-pixel readout and an event_energy estimate from the two strip-face sums.
"""
import argparse
import hashlib
import math
from pathlib import Path

import scenario_workflow as W
from gegi_digital_readout import PROFILE_SHA256, terminal_contacts_complete
from gegi_digital_saved import CALIBRATION, load_saved_native
from gegi_event_energy import estimate_event_energy
from gegi_pulse_stream import DEFINITION, acquire, prepare_native, reconstruct
from gegi_substrip import load_calibration


def replay(run, first, second, delay_ns, *, phase_ns=0.0, noise_seed=None):
    if not math.isfinite(delay_ns) or delay_ns < 0:
        raise ValueError('Use a finite, nonnegative second-pulse delay in ns.')
    receipt = W.read(run / 'response/run.json')
    channels = receipt['channels']
    pulses, inputs = [], []
    for event_id, onset in ((first, 0.0), (second, delay_ns)):
        if event_id not in receipt['nonzero_event_ids']:
            raise ValueError(f'Event {event_id} has no saved nonzero response in this run.')
        ref = f'events/{event_id}.json'
        path = run / 'response' / ref
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != receipt['artifacts'][ref]:
            raise ValueError(f'The original native record for event {event_id} changed.')
        event = W.decode_json(data.decode('utf-8-sig'))
        if event['event_id'] != event_id:
            raise ValueError(f'The original event ID differs from {event_id}.')
        saved = load_saved_native(event, channels, run, configuration_sha256=receipt['configuration_sha256'])
        if saved['status'] != 'available':
            raise ValueError(f"Event {event_id}: {saved['reason']}")
        native = prepare_native(saved['native'], channels, terminal_complete=terminal_contacts_complete(event))
        pulses.append((native, onset, 1.0))
        inputs.append({'event_id': event_id, 'injection_ns': onset,
                       'native_sha256': saved['native_signals_sha256']})
    time, codes = acquire(pulses, phase_ns=phase_ns, noise_seed=noise_seed)
    observed = reconstruct(time, codes, channels=channels, calibration=load_calibration(CALIBRATION),
                           source_identity=saved['source'])
    for event in observed['events']:
        event['event_energy'] = estimate_event_energy(event)
    return {'kind': 'gegi_controlled_pulse_replay_v1', 'inputs': inputs,
            'configuration_sha256': receipt['configuration_sha256'], 'field': saved['source'],
            'electronics_profile_sha256': PROFILE_SHA256, 'pulse_definition': DEFINITION,
            'calibration_sha256': W.sha(CALIBRATION),
            'stream_algorithm_sha256': W.sha(Path(__file__).with_name('gegi_pulse_stream.py')),
            'event_energy_algorithm_sha256': W.sha(Path(__file__).with_name('gegi_event_energy.py')),
            'phase_ns': phase_ns, 'noise_seed': noise_seed, 'reconstruction': observed,
            'adc': {'time_ns': time.tolist(), 'contact_ids': [ch['id'] for ch in channels],
                    'signed_codes_by_contact': codes.tolist()}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True, type=Path, help='Completed standalone GeGI run')
    parser.add_argument('--first', required=True, type=int, help='First original nonzero event ID')
    parser.add_argument('--second', required=True, type=int, help='Second original nonzero event ID')
    parser.add_argument('--delay-ns', required=True, type=float)
    parser.add_argument('--phase-ns', type=float, default=0.0, help='ADC clock offset in ns')
    parser.add_argument('--noise-seed', type=int, help='Enable the nominal seeded input noise')
    parser.add_argument('--output', required=True, type=Path, help='New JSON outside the completed run')
    args = parser.parse_args()
    if args.output.resolve().is_relative_to(args.run.resolve()):
        parser.error('Place the replay output outside the sealed run directory.')
    result = replay(args.run, args.first, args.second, args.delay_ns,
                    phase_ns=args.phase_ns, noise_seed=args.noise_seed)
    payload = W.encoded(result) + b'\n'
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('xb') as stream:
        stream.write(payload)
    print(f"{len(result['reconstruction']['events'])} reconstructed triggers. Saved {args.output}")


if __name__ == '__main__':
    main()
