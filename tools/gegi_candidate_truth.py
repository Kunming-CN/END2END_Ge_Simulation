"""Stage and export compact source/transport/native truth for diagnostic scoring."""

from contextlib import closing
import gzip
from hashlib import sha256
import json
from pathlib import Path
import zlib

from gegi_candidate_storage import _open_readonly, _record_digest
from gegi_dual_source import _publish_artifact
from gegi_event_store import encoded


KIND = 'gegi_candidate_truth_v1'
PHOTON_KIND = 'gegi_candidate_photon_truth_v1'
SCRATCH = 'candidate-truth-scratch.sqlite'
ARTIFACT = 'candidate-truth.jsonl.gz'


def attach(db, path):
    """Share the main store's rollback-journal transaction and checkpoint."""
    path = Path(path)
    if not path.is_file() and db.execute('SELECT 1 FROM input_groups LIMIT 1').fetchone():
        raise ValueError('The committed acquisition is missing its candidate truth scratch')
    if db.execute('PRAGMA main.journal_mode').fetchone()[0] != 'delete':
        raise ValueError('Candidate truth and the acquisition require a shared durable rollback-journal transaction')
    db.execute('ATTACH DATABASE ? AS candidate_truth', (str(path),))
    db.execute('PRAGMA candidate_truth.journal_mode=DELETE')
    db.execute('PRAGMA candidate_truth.synchronous=FULL')
    db.executescript('''
        CREATE TABLE IF NOT EXISTS candidate_truth.events (
          driver INTEGER PRIMARY KEY, block_index INTEGER NOT NULL, body BLOB NOT NULL, digest TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS candidate_truth.responses (
          ordinal INTEGER PRIMARY KEY, body BLOB NOT NULL, digest TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS candidate_truth.links (
          trigger INTEGER NOT NULL, link_index INTEGER NOT NULL, ordinal INTEGER NOT NULL, PRIMARY KEY(trigger,link_index));
        CREATE INDEX IF NOT EXISTS candidate_truth.links_for_ordinal ON links(ordinal);
        CREATE INDEX IF NOT EXISTS candidate_truth.events_for_block ON events(block_index);
    ''')


def store_event(db, event, manifest, manifest_hash):
    photon_truth = event['candidate_photon_truth']
    descriptor = manifest.get('photon_step_observation')
    observation = {'status': 'unavailable_not_recorded'}
    chords = photon_truth['ge_gamma_steps']
    if descriptor is not None:
        if (descriptor['kind'] != 'gegi_photon_step_sidecar_v1'
                or photon_truth.get('photon_step_observation_status') != 'observed_exact'):
            raise ValueError('Observed Ge photon kinematics are missing from the declared source block')
        for row in chords:
            step = row.get('observed_transport_step')
            if step is None or (step['event_id'], step['track_id'], step['parent_track_id']) != (
                    event['transport_event_id'], row['track_id'], row['parent_track_id']):
                raise ValueError('Observed Ge photon step differs from its original event and ancestry identities')
        observation = {'status': 'observed_exact', **descriptor}
    elif any('observed_transport_step' in row for row in chords):
        raise ValueError('Observed Ge photon kinematics must be bound to the source manifest')
    abstart = event['absolute_parent_time_ns']
    photons = [dict(step, absolute_time_ns=abstart+step['time_ns']) for step in chords]
    births = [dict(track, absolute_birth_time_ns=abstart+track['birth_time_ns']) for track in photon_truth['track_births']]
    deposits = [{key: step[key] for key in ('raw_row_index', 'deposit_id', 'energy_keV', 'position_mm',
                'pre_position_mm', 'post_position_mm', 'absolute_time_ns', 'parent_relative_time_ns',
                'track_id', 'parent_track_id', 'pdg')} for step in event['steps']]
    driver = event['event_id']
    block_index = manifest['block_index']
    if block_index != event['block_index']:
        raise ValueError('Candidate truth transport block does not match its source manifest')
    body = encoded(dict(record='transport_event', driver_id=driver, block_index=block_index,
        transport_event_id=event['transport_event_id'], acquisition_id=event['acquisition_id'],
        source_id=event['source_id'], parent_decay_id=event['parent_decay_id'],
        new_parent_decay_id=event.get('new_parent_decay_id'), initial_daughter_id=event.get('initial_daughter_id'),
        source_position_global_mm=event['source_position_global_mm'], absolute_parent_time_ns=abstart,
        source_lh5_sha256=manifest['source_lh5_sha256'], source_manifest_sha256=manifest_hash,
        source_events_sha256=manifest['events_sha256'], decay_photons=event['decay_photons'],
        ge_gamma_steps=photons, positive_ge_deposits=deposits, track_births=births,
        photon_step_observation=observation))
    db.execute('INSERT INTO candidate_truth.events VALUES (?,?,?,?)',
               (driver, block_index, zlib.compress(body), sha256(body).hexdigest()))


def store_response(db, ordinal, group, event, phase):
    if (event['event_id'], event['group_id']) != (group['event_id'], group['group_id']):
        raise ValueError('Candidate truth response has a different group identity')
    outcomes = event['steps'] if event['status'] != 'native_failed' else None
    if outcomes is not None and [row['raw_row_index'] for row in outcomes] != [row['raw_row_index'] for row in group['steps']]:
        raise ValueError('Candidate truth endpoint rows differ from the original positive Ge deposit rows')
    body = encoded(dict(driver_id=group['event_id'], input_group_ordinal=ordinal, group_id=group['group_id'],
        group_origin_time_ns=group['group_origin_time_ns'], status=event['status'], native_processing_phase=phase,
        raw_row_indices=[row['raw_row_index'] for row in group['steps']], native_steps=outcomes,
        input_event_sha256=event['input_event_sha256'], signals_sha256=event.get('signals_sha256'),
        native_domain_error=event.get('native_domain_error')))
    db.execute('INSERT INTO candidate_truth.responses VALUES (?,?,?)',
               (ordinal, zlib.compress(body), sha256(body).hexdigest()))


def link_candidate(db, trigger, ordinals):
    db.executemany('INSERT INTO candidate_truth.links VALUES (?,?,?)',
                   ((trigger, index, ordinal) for index, ordinal in enumerate(ordinals)))


def _decode(packed, expected):
    plain = zlib.decompress(packed)
    if sha256(plain).hexdigest() != expected:
        raise ValueError('Staged candidate truth record changed')
    return json.loads(plain)


def _rows(db, identity):
    yield dict(record='schema', kind=KIND, acquisition_identity_sha256=sha256(encoded(identity)).hexdigest(),
        transport_schema=PHOTON_KIND, clocks='Transport step and birth raw ns are parent-relative. Native outcome time is relative to group onset.',
        coordinates='Detector/world XYZ in mm as written by the attested GeGI transport transform.',
        gamma_step_process='The observer records the Geant4 step-defining process when present. Older scored Ge chords have unavailable step processes. Track births are separate.',
        photon_step_observation='Matched original Ge gamma rows optionally carry observer step IDs, pre/post keV and direction, volume and Geant4 event-clock time. The sidecar is bound at the source block.',
        association='A trigger links to every available original group in its recorded context. The links do not identify the photon, deposit or group causing that trigger.')
    if db.execute('''SELECT 1 FROM candidate_truth.links l LEFT JOIN triggers t ON t.trigger_id=l.trigger
                     WHERE t.trigger_id IS NULL OR t.decision<>'candidate' LIMIT 1''').fetchone():
        raise ValueError('Staged truth links contain a trigger outside the saved candidate population')
    for trigger, body, adc_sha, record_sha in db.execute(
            "SELECT trigger_id,record,adc_sha256,record_sha256 FROM triggers WHERE decision='candidate' ORDER BY trigger_id"):
        saved = json.loads(zlib.decompress(body))
        links = [ordinal for (ordinal,) in db.execute(
            'SELECT ordinal FROM candidate_truth.links WHERE trigger=? ORDER BY link_index', (trigger,))]
        if saved['trigger_id'] != trigger or saved['identities'] != links or _record_digest(saved, adc_sha) != record_sha:
            raise ValueError('Candidate truth trigger links differ from the verified waveform record')
        yield dict(record='trigger_context', original_trigger_id=trigger, input_group_ordinals=links,
                   candidate_record_sha256=record_sha)
    transport = '''SELECT DISTINCT g.parent FROM candidate_truth.links l
                   JOIN input_groups g ON g.ordinal=l.ordinal'''
    for driver, packed, digest in db.execute(f'''SELECT p.parent,e.body,e.digest FROM ({transport}) p
            LEFT JOIN candidate_truth.events e ON e.driver=p.parent ORDER BY p.parent'''):
        if packed is None:
            raise ValueError(f'Missing staged photon truth for driver {driver}')
        result = _decode(packed, digest)
        if result['driver_id'] != driver:
            raise ValueError(f'Staged transport truth differs from driver {driver}')
        yield result
    groups = 'SELECT DISTINCT ordinal FROM candidate_truth.links'
    for ordinal, driver, group_id, onset, status, meta, packed, digest in db.execute(f'''
            SELECT l.ordinal,g.parent,g.group_id,g.onset_ns,g.status,g.metadata,r.body,r.digest FROM ({groups}) l
            LEFT JOIN input_groups g ON g.ordinal=l.ordinal
            LEFT JOIN candidate_truth.responses r ON r.ordinal=l.ordinal ORDER BY l.ordinal'''):
        if status is None:
            raise ValueError(f'Candidate truth references missing input group {ordinal}')
        if packed is None:
            if status != 'daughter_deposits_after_acquisition':
                raise ValueError(f'Missing staged native response for processed input group {ordinal}')
            result = dict(driver_id=driver, group_id=group_id, input_group_ordinal=ordinal, group_origin_time_ns=onset,
                          status=status, raw_row_indices=json.loads(meta)['raw_row_indices'], native_steps=None)
        else:
            result = _decode(packed, digest)
            if (result['driver_id'], result['group_id'], result['input_group_ordinal'], result['status']) != (driver, group_id, ordinal, status):
                raise ValueError(f'Staged response identity differs from input group {ordinal}')
        yield {'record': 'input_group_response', **result}


def publish(database, scratch, target, identity):
    """Export exclusively candidate-linked rows and verify exact round-trip bytes."""
    with closing(_open_readonly(database)) as db:
        db.execute('ATTACH DATABASE ? AS candidate_truth', (Path(scratch).resolve().as_uri()+'?mode=ro',))
        def write(out):
            with gzip.GzipFile(fileobj=out, mode='wb', filename='', mtime=0) as compressed:
                for row in _rows(db, identity):
                    compressed.write(encoded(row)+b'\n')
        if not target.exists():
            _publish_artifact(target, write)
        counts = {'trigger_context': 0, 'transport_event': 0, 'input_group_response': 0}
        coverage = {'observed_exact': 0, 'unavailable_not_recorded': 0}
        with gzip.open(target, 'rb') as stream:
            for row in _rows(db, identity):
                if stream.readline() != encoded(row)+b'\n':
                    raise ValueError('Published candidate truth differs from its verified staging records')
                if row['record'] in counts:
                    counts[row['record']] += 1
                if row['record'] == 'transport_event':
                    coverage[row.get('photon_step_observation', {}).get('status', 'unavailable_not_recorded')] += 1
            if stream.read(1):
                raise ValueError('Unexpected trailing data in the candidate truth export')
    return dict(kind=KIND, status='verified_exact', file=target.name, counts=counts, photon_step_observation=coverage)
