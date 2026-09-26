"""Validate the installation test's event/step output, not detector physics."""
import hashlib
import json
from pathlib import Path
import h5py
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
output = ROOT / '.local' / 'transport' / 'smoke.lh5'
with h5py.File(output, 'r') as data:
    count = int(data['number_of_simulated_events'][()])
    assert count == 100, f'Expected 100 simulated primaries, got {count}'
    steps = data['stp/smoke_ge']
    ids = steps['evtid'][:]
    energy = steps['edep/flattened_data'][:]
    ends = steps['edep/cumulative_length'][:].astype(int)
    assert len(ids) > 0 and len(ids) == len(ends)
    assert np.all(np.diff(ids) > 0) and ids.min() >= 0 and ids.max() < count
    assert np.all(np.isfinite(energy)) and np.all(energy >= 0)
    assert np.all(np.diff(ends) > 0) and ends[-1] == len(energy)
    assert steps['edep/flattened_data'].attrs['units'] == 'keV'
    totals = np.add.reduceat(energy, np.r_[0, ends[:-1]])
    assert np.all(totals <= 662.001), 'Deposited energy exceeds the primary energy'
    for axis in ('xloc', 'yloc', 'zloc'):
        values = steps[axis + '/flattened_data'][:]
        assert steps[axis + '/flattened_data'].attrs['units'] == 'm'
        assert len(values) == len(energy) and np.all(np.isfinite(values))
        assert np.all(np.abs(values) <= 0.025001)
    times = steps['time/flattened_data'][:]
    assert steps['time/flattened_data'].attrs['units'] == 'ns'
    assert len(times) == len(energy) and np.all(np.isfinite(times))
    assert np.all(times >= 0)
    report = {
        'status': 'passed', 'primaries': count, 'events_with_deposits': len(ids),
        'recorded_steps': len(energy), 'zero_deposit_events': count - len(ids),
        'max_event_energy_keV': float(totals.max()),
        'units': {'energy': 'keV', 'position': 'm', 'time': 'ns'},
        'scope': '100 photons in a Ge box; installation only, not the LBNL cryostat',
        'output_sha256': hashlib.sha256(output.read_bytes()).hexdigest(),
        'lock_sha256': hashlib.sha256((ROOT / 'transport/pixi.lock').read_bytes()).hexdigest(),
    }
(ROOT / '.local/transport/smoke-check.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report, indent=2))
