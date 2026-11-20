"""Stream exact Compton-candidate ADC contexts, scalar features and rejection counts.

Every ADC sample still participates in triggering and readout. Only selected
readout contexts are saved, once, as compressed signed int16 preamp samples for
all 34 electrodes. Fast/slow waveforms are deterministic derivatives; their
measured scalar values, nulls and flags are retained with the context instead of
two redundant arrays. Original scientific inputs and legacy archives are unchanged.
"""

from collections import Counter
from contextlib import closing, contextmanager
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import zlib

import numpy as np

from gegi_event_store import encoded
import gegi_exposure_stream as stream


KIND = 'gegi_compton_candidate_context_store_v1'
ARCHIVE_NAME = 'compton-candidates.sqlite'
CHECKPOINT_KIND = 'gegi_compton_candidate_checkpoint_v1'
MAX_CHECKPOINT_BYTES = 32 * 1024 * 1024
POLICY = {
    'kind': 'gegi_conservative_readout_candidate_selection_v1',
    'multistrip': 'Keep at least two measured strips on either face, including charge sharing and unmatched faces.',
    'ambiguity': 'Keep incomplete, contaminated or unavailable classifications and all energy pairing/order alternatives.',
    'rejection': 'Reject only a clean measured one-strip pair, guard-only collection, or an explicit unusable/excluded rise.',
    'scope': 'Readout selection, not transport truth, photon identity or a validated hardware imaging efficiency.',
}
_CENSUS_UNCERTAIN = {'step_window_truncated', 'step_adc_saturation'}


def candidate_decision(card, *, rejection_reason=None):
    """Return (keep, reason) without requiring a unique pairing or photon order."""
    if rejection_reason is not None:
        if not isinstance(rejection_reason, str) or not rejection_reason:
            raise ValueError('A rejected rise needs its explicit selection reason')
        return False, rejection_reason
    xs, ys = card.get('x_collecting_strips'), card.get('y_collecting_strips')
    flags = set(card.get('flags') or []) | set(card.get('event_energy_flags') or [])
    if xs is None or ys is None or flags & _CENSUS_UNCERTAIN:
        return True, 'uncertain_strip_census'
    if len(xs) >= 2 or len(ys) >= 2:
        return True, 'multistrip_imaging_candidate'
    guards = card.get('guard_contact_ids') or []
    guard_flags = {'guard_collection', 'missing_face_strip_census', 'unresolved_strip_multiplicity'}
    if not xs and not ys and guards and flags <= guard_flags:
        return False, 'guard_only_collection'
    if (len(xs) == len(ys) == 1 and not guards and not flags
            and card.get('single_pixel_energy_keV') is not None):
        return False, 'qualified_single_strip_pair'
    return True, 'uncertain_imaging_candidate'


def _digest(value):
    return sha256(value).hexdigest()


def _record_digest(record, adc_sha):
    return _digest(encoded({'record': record, 'adc_sha256': adc_sha}))


def _json_object(value, label):
    if not isinstance(value, dict):
        raise ValueError(f'{label} must be a JSON object')
    try:
        body = encoded(value)
        if json.loads(body) != value:
            raise ValueError('Use string object keys and JSON arrays')
    except (TypeError, ValueError) as exc:
        raise ValueError(f'{label} must contain finite standard JSON values') from exc
    if len(body) > MAX_CHECKPOINT_BYTES:
        raise ValueError(f'{label} exceeds the {MAX_CHECKPOINT_BYTES}-byte serialized limit')
    return body


def _metadata(identity):
    return {'kind': KIND, 'selection_policy': POLICY, 'identity': identity,
            'context_kind': stream.CONTEXT_KIND,
            'record_encoding': 'zlib-compressed canonical UTF-8 JSON',
            'adc_encoding': 'zlib-compressed channel-major little-endian signed int16',
            'filter_state': 'Saved acquisition baseline and exact finite-support context origin; '
                            'the common pole-zero accumulator offset cancels in every gate.',
            'signal_scope': 'One all-channel preamp context; exact fast/slow scalar values and flags. '
                            'Reconstruct derived waveforms with the recorded implementation.'}


class CandidateStore:
    """Bounded candidate records with optional atomic acquisition-block checkpoints.

    Creation is exclusive. ``resume=True`` reopens an incomplete acquisition only
    with matching immutable metadata and a checkpoint covering its last trigger.
    Legacy stores remain readable; legacy rows without a checkpoint cannot resume.

    Use ``with store.transaction():`` for a complete source/readout block, including
    writes to orchestration-owned tables on ``store.db``, then call
    ``store.save_checkpoint(state)`` last. Rows and checkpoint commit together.
    Standalone ``observe`` retains its original one-trigger transaction behavior.
    """

    def __init__(self, path, identity, *, resume=False):
        identity = json.loads(_json_object(identity, 'Acquisition identity'))
        self.path = Path(path)
        self._finished = False
        self._transaction_active = False
        self._checkpoint_saved = False
        self._identity_sha256 = _digest(encoded(identity))
        self._metadata_body = encoded(_metadata(identity))
        if resume:
            if not self.path.is_file():
                raise FileNotFoundError(self.path)
            self.db = sqlite3.connect(self.path.resolve().as_uri() + '?mode=rw', uri=True)
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open('xb'):
                pass
            self.db = sqlite3.connect(self.path)
        try:
            self.db.execute('PRAGMA synchronous=FULL')
            if resume:
                if self.db.execute('SELECT 1 FROM completion WHERE singleton=1').fetchone():
                    raise ValueError('Candidate acquisition is already complete; open it read-only')
                row = self.db.execute('SELECT body FROM metadata WHERE singleton=1').fetchone()
                if row is None or encoded(json.loads(row[0])) != self._metadata_body:
                    raise ValueError('Candidate acquisition metadata or identity differs')
                has_checkpoint = self.db.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='checkpoint'").fetchone()
                if has_checkpoint:
                    checkpoint = self.load_checkpoint()
                else:
                    checkpoint = None
                if checkpoint is None and self.last_trigger_id:
                    raise ValueError('Observed triggers have no resumable checkpoint')
            else:
                self.db.executescript('''
                    CREATE TABLE metadata (singleton INTEGER PRIMARY KEY CHECK(singleton=1), body BLOB NOT NULL);
                    CREATE TABLE triggers (trigger_id INTEGER PRIMARY KEY, trigger_time_ns REAL NOT NULL,
                        decision TEXT NOT NULL, reason TEXT NOT NULL, record BLOB NOT NULL,
                        adc_codes BLOB, adc_sha256 TEXT, record_sha256 TEXT NOT NULL);
                    CREATE TABLE completion (singleton INTEGER PRIMARY KEY CHECK(singleton=1), body BLOB NOT NULL);
                ''')
                with self.db:
                    self.db.execute('INSERT INTO metadata VALUES (1,?)', (self._metadata_body,))
            self.db.executescript('''
                CREATE TABLE IF NOT EXISTS checkpoint (
                    singleton INTEGER PRIMARY KEY CHECK(singleton=1), identity_sha256 TEXT NOT NULL,
                    last_trigger_id INTEGER NOT NULL, last_candidate_trigger_id INTEGER NOT NULL,
                    last_record_sha256 TEXT, state BLOB NOT NULL, checkpoint_sha256 TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS trigger_decision_id ON triggers(decision,trigger_id);
            ''')
            self.metadata = json.loads(self._metadata_body)
        except BaseException:
            self.db.close()
            raise

    @property
    def last_trigger_id(self):
        row = self.db.execute('SELECT trigger_id FROM triggers ORDER BY trigger_id DESC LIMIT 1').fetchone()
        return row[0] if row else 0

    def _boundary(self):
        row = self.db.execute(
            'SELECT trigger_id,record_sha256 FROM triggers ORDER BY trigger_id DESC LIMIT 1').fetchone()
        candidate = self.db.execute(
            "SELECT trigger_id FROM triggers WHERE decision='candidate' ORDER BY trigger_id DESC LIMIT 1").fetchone()
        return (row[0], candidate[0] if candidate else 0, row[1]) if row else (0, 0, None)

    def _checkpoint_digest(self, boundary, body):
        last_id, last_candidate_id, last_record_sha = boundary
        return _digest(encoded({'kind': CHECKPOINT_KIND, 'identity_sha256': self._identity_sha256,
                                'last_trigger_id': last_id, 'last_candidate_trigger_id': last_candidate_id,
                                'last_record_sha256': last_record_sha, 'state_sha256': _digest(body)}))

    def load_checkpoint(self):
        """Return the detached JSON state, checking identity and the committed row boundary."""
        size = self.db.execute('SELECT length(state) FROM checkpoint WHERE singleton=1').fetchone()
        if size is None:
            return None
        if size[0] > MAX_CHECKPOINT_BYTES:
            raise ValueError('Stored acquisition checkpoint exceeds the serialized limit')
        identity_sha, last_id, last_candidate_id, last_record_sha, body, digest = self.db.execute(
            'SELECT identity_sha256,last_trigger_id,last_candidate_trigger_id,last_record_sha256,state,'
            'checkpoint_sha256 FROM checkpoint WHERE singleton=1').fetchone()
        boundary = (last_id, last_candidate_id, last_record_sha)
        if (identity_sha != self._identity_sha256 or boundary != self._boundary()
                or self._checkpoint_digest(boundary, body) != digest):
            raise ValueError('Acquisition checkpoint identity, trigger boundary or state changed')
        state = json.loads(body)
        if not isinstance(state, dict):
            raise ValueError('Stored acquisition checkpoint must be a JSON object')
        return state

    @contextmanager
    def transaction(self):
        """Commit a block and its final checkpoint together, or roll back all its writes."""
        if self._finished:
            raise ValueError('Candidate acquisition is already complete')
        if self._transaction_active or self.db.in_transaction:
            raise ValueError('Begin acquisition blocks outside any existing transaction')
        self.db.execute('BEGIN IMMEDIATE')
        self._transaction_active = True
        self._checkpoint_saved = False
        try:
            yield self
            if not self._checkpoint_saved:
                raise ValueError('An acquisition block needs a checkpoint after its last trigger')
            self.load_checkpoint()
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise
        finally:
            self._transaction_active = False
            self._checkpoint_saved = False

    @contextmanager
    def _write(self):
        if self._transaction_active:
            yield
        else:
            with self.db:
                yield

    def save_checkpoint(self, state):
        """Save at most 32 MiB of finite JSON, atomically with the current block's rows."""
        if self._finished:
            raise ValueError('Candidate acquisition is already complete')
        body = _json_object(state, 'Acquisition checkpoint')
        boundary = self._boundary()
        with self._write():
            self.db.execute('INSERT OR REPLACE INTO checkpoint VALUES (1,?,?,?,?,?,?)',
                            (self._identity_sha256, *boundary, body, self._checkpoint_digest(boundary, body)))
        if self._transaction_active:
            self._checkpoint_saved = True

    def observe(self, card, context, *, event=None, trigger_id=None, identities=None, rejection_reason=None):
        """Retain a candidate, or only a compact ID/reason ledger row for a rejection.

        `context` is borrowed from on_readout_context. `event` is the original
        full scalar readout (all electrodes), not a waveform array. Source joins
        belong in `identities`; measured triggers need not have a unique parent.
        """
        if self._finished:
            raise ValueError('Candidate acquisition is already complete')
        trigger_id = context['readout_trigger_id'] if trigger_id is None else trigger_id
        if type(trigger_id) is not int or trigger_id <= 0:
            raise ValueError('Retain the original positive readout trigger ID')
        previous = self.db.execute('SELECT max(trigger_id) FROM triggers').fetchone()[0]
        if previous is not None and trigger_id <= previous:
            raise ValueError('Observe original trigger IDs once in acquisition order')
        reason = rejection_reason or context.get('readout_rejection_reason')
        keep, reason = candidate_decision(card, rejection_reason=reason)
        record = {'trigger_id': trigger_id, 'trigger_time_ns': card['trigger_time_ns'],
                  'decision': 'candidate' if keep else 'rejected', 'reason': reason,
                  'identities': identities if identities is not None else []}
        blob, adc_sha = None, None
        if keep:
            if event is None:
                raise ValueError('A saved candidate requires its original all-channel scalar readout')
            codes = np.asarray(context['adc_codes'])
            if codes.dtype != np.dtype('int16') or codes.shape != (
                    len(stream.digital.CONTACT_IDS), context['stop_sample_index']-context['first_sample_index']):
                raise ValueError('Candidate context requires the exact signed all-channel ADC samples')
            raw = np.asarray(codes, dtype='<i2', order='C').tobytes()
            adc_sha, blob = _digest(raw), zlib.compress(raw)
            record.update(card=card, readout=event,
                          context={key: value for key, value in context.items() if key != 'adc_codes'})
        else:
            record['summary'] = {key: card.get(key) for key in (
                'x_collecting_strips', 'y_collecting_strips', 'guard_contact_ids',
                'energy_keV', 'flags', 'event_energy_flags')}
        with self._write():
            self.db.execute('INSERT INTO triggers VALUES (?,?,?,?,?,?,?,?)',
                            (trigger_id, card['trigger_time_ns'], record['decision'], reason,
                             zlib.compress(encoded(record)), blob, adc_sha, _record_digest(record, adc_sha)))
        if self._transaction_active:
            self._checkpoint_saved = False
        return {'trigger_id': trigger_id, 'decision': record['decision'], 'reason': reason}

    def statistics(self):
        counts = Counter()
        reasons = Counter()
        for decision, reason, count in self.db.execute(
                'SELECT decision,reason,count(*) FROM triggers GROUP BY decision,reason'):
            counts[decision] += count
            reasons[reason] += count
        return {'observed_coincident_rises': sum(counts.values()),
                'saved_candidates': counts['candidate'], 'rejected_rises': counts['rejected'],
                'selection_reason_counts': dict(sorted(reasons.items()))}

    def finalize(self, *, acquisition_statistics, report_sha256=None):
        """Seal full acquisition denominators supplied by the orchestration layer."""
        if self._finished:
            raise ValueError('Candidate acquisition is already complete')
        if self._transaction_active:
            raise ValueError('Finalize after the acquisition block commits')
        self.load_checkpoint()
        digest = sha256()
        for (value,) in self.db.execute('SELECT record_sha256 FROM triggers ORDER BY trigger_id'):
            digest.update(bytes.fromhex(value))
        completion = {'kind': KIND, 'status': 'completed', **self.statistics(),
                      'acquisition_statistics': acquisition_statistics, 'report_sha256': report_sha256,
                      'metadata_sha256': _digest(self._metadata_body), 'records_sha256': digest.hexdigest()}
        with self.db:
            self.db.execute('INSERT INTO completion VALUES (1,?)', (encoded(completion),))
        self._finished = True
        return completion

    def close(self):
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def _open_readonly(path):
    return sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)


def load_candidate(path, trigger_id):
    """Load and verify one candidate; rejected triggers have no fabricated waveform."""
    with closing(_open_readonly(path)) as db:
        metadata = json.loads(db.execute('SELECT body FROM metadata WHERE singleton=1').fetchone()[0])
        if metadata.get('kind') != KIND:
            raise ValueError('Select a candidate acquisition store')
        row = db.execute('SELECT record,adc_codes,adc_sha256,record_sha256 FROM triggers WHERE trigger_id=?',
                         (trigger_id,)).fetchone()
    if row is None:
        raise KeyError(trigger_id)
    body, blob, adc_sha, record_sha = row
    record = json.loads(zlib.decompress(body))
    if _record_digest(record, adc_sha) != record_sha:
        raise ValueError('Candidate scalar/context record changed')
    if record['decision'] != 'candidate':
        if blob is not None or adc_sha is not None:
            raise ValueError('Rejected trigger unexpectedly contains a waveform')
        return record
    context = record['context']
    count = context['stop_sample_index'] - context['first_sample_index']
    size = len(stream.digital.CONTACT_IDS) * count * 2
    if count <= 0:
        raise ValueError('Invalid candidate context sample count')
    inflater = zlib.decompressobj()
    raw = inflater.decompress(blob, size+1)
    if len(raw) != size or not inflater.eof or inflater.unused_data or _digest(raw) != adc_sha:
        raise ValueError('Candidate ADC samples changed or are truncated')
    context['adc_codes'] = np.frombuffer(raw, dtype='<i2').reshape(len(stream.digital.CONTACT_IDS), count)
    return record


def store_summary(path):
    """Read small storage/completion metadata without loading saved ADC samples."""
    with closing(_open_readonly(path)) as db:
        metadata = json.loads(db.execute('SELECT body FROM metadata WHERE singleton=1').fetchone()[0])
        if metadata.get('kind') != KIND:
            raise ValueError('Select a candidate acquisition store')
        row = db.execute('SELECT body FROM completion WHERE singleton=1').fetchone()
        completion = json.loads(row[0]) if row else None
        counts = dict(db.execute('SELECT decision,count(*) FROM triggers GROUP BY decision'))
    if completion is not None:
        if (completion['metadata_sha256'] != _digest(encoded(metadata))
                or completion['saved_candidates'] != counts.get('candidate', 0)
                or completion['rejected_rises'] != counts.get('rejected', 0)):
            raise ValueError('Candidate acquisition completion or denominators changed')
    return {'metadata': metadata, 'completion': completion,
            'status': 'completed' if completion else 'interrupted_or_running',
            'saved_candidates': counts.get('candidate', 0), 'rejected_rises': counts.get('rejected', 0)}


def list_candidates(path, *, limit=50, offset=0):
    """Page scalar candidate cards by original trigger ID, without inflating ADC arrays."""
    if type(limit) is not int or type(offset) is not int or not 1 <= limit <= 1000 or offset < 0:
        raise ValueError('Use a positive candidate page size at most 1000 and a nonnegative offset')
    with closing(_open_readonly(path)) as db:
        rows = db.execute('SELECT record,adc_sha256,record_sha256 FROM triggers WHERE decision=? '
                          'ORDER BY trigger_id LIMIT ? OFFSET ?', ('candidate', limit, offset)).fetchall()
    result = []
    for body, adc_sha, record_sha in rows:
        record = json.loads(zlib.decompress(body))
        if _record_digest(record, adc_sha) != record_sha:
            raise ValueError('Candidate scalar/context record changed')
        result.append({key: value for key, value in record.items() if key != 'context'})
    return result


def replay_candidate(path, trigger_id):
    """Independently recompute the saved trigger's fast, slow and timing readout."""
    record = load_candidate(path, trigger_id)
    if record['decision'] != 'candidate':
        raise ValueError('Rejected trigger has no saved ADC context')
    reproduced = stream.replay_readout_context(record['context'])
    if record.get('readout') is not None and reproduced != record['readout']:
        raise ValueError('Reconstructed fast/slow readout differs from the saved scalar values')
    return reproduced
