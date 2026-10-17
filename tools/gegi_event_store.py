"""Transactional, lossless GeGI native inputs and scalar response per batch.

One copy of each exact Float64 array is stored with byte-shuffle + zlib. Full
electronics display traces are deterministic derivatives: their hashes, all
scalar outputs and the frozen readout recipe are retained, not duplicate arrays.
No original scientific run is modified by this new explicit storage contract.
"""
from __future__ import annotations
import csv
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import struct
import zlib

KIND = 'gegi_native_scalar_store_v1'


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def require(ok, message):
    if not ok:
        raise ValueError(message)


def trace_hash(trace):
    """Canonical scalar/array representation for a later independent replay."""
    return sha(encoded(trace))


def pack_array(values):
    require(isinstance(values, list) and len(values) <= 200000,
            'Native array exceeds bounded event support')
    require(all(type(v) in (int, float) and math.isfinite(v) for v in values),
            'Nonfinite or nonnumeric native signal')
    raw = struct.pack('<' + 'd' * len(values), *values)
    shuffled = b''.join(raw[i::8] for i in range(8))
    return sha(raw), len(values), zlib.compress(shuffled, 6)


def unpack_array(digest, count, blob):
    require(type(count) is int and 0 <= count <= 200000, 'Invalid native array size')
    inflater = zlib.decompressobj()
    shuffled = inflater.decompress(blob, count * 8 + 1)
    require(len(shuffled) == count * 8 and inflater.eof and not inflater.unused_data,
            'Truncated or oversized compressed array')
    raw = bytearray(count * 8)
    for i in range(8):
        raw[i::8] = shuffled[i * count:(i + 1) * count]
    require(sha(raw) == digest, 'Native array hash changed')
    return list(struct.unpack('<' + 'd' * count, raw))


def native_csv(path, channels):
    """Read existing native worker output once; fixed wiring is checked, not stored twice."""
    wiring = {c['contact_id']: c['wiring_factor'] for c in channels}
    result = {i: {'time_ns': [], 'signed_induced_keV': []} for i in wiring}
    with Path(path).open(encoding='utf-8', newline='') as stream:
        reader = csv.DictReader(stream)
        require(reader.fieldnames == ['contact_id', 'time_ns', 'signed_induced_keV', 'wired_induced_keV'],
                'Unexpected native signal columns')
        for row in reader:
            i = int(row['contact_id'])
            require(i in wiring and wiring[i] in (-1, 1), 'Unknown channel or wiring')
            t, q, wired = (float(row[k]) for k in ('time_ns', 'signed_induced_keV', 'wired_induced_keV'))
            require(all(math.isfinite(v) for v in (t, q, wired)) and wired == wiring[i] * q,
                    'Native fixed-wiring identity changed')
            require(not result[i]['time_ns'] or t > result[i]['time_ns'][-1], 'Native time is not increasing')
            result[i]['time_ns'].append(t)
            result[i]['signed_induced_keV'].append(q)
    require(all(len(v['time_ns']) >= 2 for v in result.values()), 'Missing native signal channel')
    return result


class Store:
    def __init__(self, path, identity, *, create=False):
        self.path = Path(path)
        require(type(identity) is dict, 'Missing frozen store identity')
        if create:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            # Exclusive reservation; existing interrupted or completed science is retained.
            with self.path.open('xb'):
                pass
        require(self.path.is_file() and not self.path.is_symlink(), 'Missing or linked event store')
        self.db = sqlite3.connect(self.path)
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.execute('PRAGMA synchronous=FULL')
        if create:
            with self.db:
                self.db.executescript('''
                    CREATE TABLE identity (singleton INTEGER PRIMARY KEY CHECK(singleton=1), body BLOB NOT NULL);
                    CREATE TABLE arrays (digest TEXT PRIMARY KEY, count INTEGER NOT NULL, value BLOB NOT NULL);
                    CREATE TABLE events (primary_id INTEGER NOT NULL, group_id INTEGER NOT NULL,
                      input_sha256 TEXT NOT NULL, metadata BLOB NOT NULL, metadata_sha256 TEXT NOT NULL,
                      PRIMARY KEY(primary_id, group_id));
                    CREATE TABLE completion (singleton INTEGER PRIMARY KEY CHECK(singleton=1), body BLOB NOT NULL);
                ''')
                self.db.execute('INSERT INTO identity VALUES (1,?)', (encoded({'kind': KIND, 'identity': identity}),))
        actual = self.db.execute('SELECT body FROM identity WHERE singleton=1').fetchone()
        if actual is None or actual[0] != encoded({'kind': KIND, 'identity': identity}):
            self.db.close()
            raise ValueError('Store configuration/source/model identity changed')

    def close(self):
        self.db.close()

    def has(self, primary_id, group_id, input_sha256):
        row = self.db.execute('SELECT input_sha256 FROM events WHERE primary_id=? AND group_id=?',
                              (primary_id, group_id)).fetchone()
        if row is not None:
            require(row[0] == input_sha256, 'Completed event input changed')
        return row is not None

    def append(self, primary_id, group_id, event, signals, input_sha256):
        require(type(primary_id) is int and primary_id >= 0 and type(group_id) is int and group_id >= 0,
                'Invalid original primary/group identity')
        require(not self.db.execute('SELECT 1 FROM completion').fetchone(), 'Completed batch is immutable')
        require(not self.has(primary_id, group_id, input_sha256), 'Completed event must not be reprocessed')
        require(event['event_id'] == primary_id, 'Original primary ID changed')
        metadata = json.loads(encoded(event))
        metadata['storage'] = {'kind': KIND, 'native_dtype': '<f8', 'native_units': {'time': 'ns', 'charge': 'keV'},
            'electronics_trace_policy': 'Regenerate from exact native inputs and frozen readout; verify per-channel canonical trace SHA256.'}
        references = {}
        pending = {}
        channels = metadata.get('channels')
        if channels is None:
            require(event['status'] == 'native_failed' and signals is None, 'Unknown signals must remain null')
        else:
            require(set(signals) == {c['contact_id'] for c in channels}, 'Signal/channel census mismatch')
            for c in channels:
                c['derived_trace_sha256'] = trace_hash(c.pop('trace'))
            for contact, native in signals.items():
                require(set(native) == {'time_ns', 'signed_induced_keV'}, 'Unexpected native signal fields')
                require(len(native['time_ns']) == len(native['signed_induced_keV']), 'Signal length mismatch')
                references[str(contact)] = {}
                for key, values in native.items():
                    digest, count, blob = pack_array(values)
                    pending[digest] = (count, blob)
                    references[str(contact)][key] = {'sha256': digest, 'count': count}
        metadata['native_signals'] = references if signals is not None else None
        metadata.pop('signals_ref', None)
        metadata.pop('signals_sha256', None)
        body = encoded(metadata)
        # Native arrays and metadata commit together. Interrupted groups leave no
        # partial completed row, while prior groups remain durable and reusable.
        with self.db:
            for digest, (count, blob) in pending.items():
                self.db.execute('INSERT OR IGNORE INTO arrays VALUES (?,?,?)', (digest, count, blob))
            self.db.execute('INSERT INTO events VALUES (?,?,?,?,?)',
                            (primary_id, group_id, input_sha256, zlib.compress(body, 6), sha(body)))

    def read(self, primary_id, group_id, *, with_signals=False):
        row = self.db.execute('SELECT metadata,metadata_sha256 FROM events WHERE primary_id=? AND group_id=?',
                              (primary_id, group_id)).fetchone()
        require(row is not None, 'Unknown saved event group')
        body = zlib.decompress(row[0])
        require(sha(body) == row[1], 'Event metadata hash changed')
        event = json.loads(body)
        signals = None
        if with_signals and event['native_signals'] is not None:
            signals = {}
            for contact, fields in event['native_signals'].items():
                signals[int(contact)] = {}
                for name, ref in fields.items():
                    row = self.db.execute('SELECT count,value FROM arrays WHERE digest=?', (ref['sha256'],)).fetchone()
                    require(row is not None and row[0] == ref['count'], 'Native array missing or count changed')
                    signals[int(contact)][name] = unpack_array(ref['sha256'], row[0], row[1])
        return event, signals

    def keys(self):
        yield from self.db.execute('SELECT primary_id,group_id FROM events ORDER BY primary_id,group_id')

    def seal(self, completion):
        require(not self.db.execute('SELECT 1 FROM completion').fetchone(), 'Batch already sealed')
        require(self.db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok', 'SQLite integrity failure')
        for key in self.keys():
            self.read(*key, with_signals=True)
        with self.db:
            self.db.execute('INSERT INTO completion VALUES (1,?)', (encoded(completion),))
