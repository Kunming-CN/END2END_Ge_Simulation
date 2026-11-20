"""Incremental all-electrode ADC/readout with explicit bounded history and resume.

Inputs must be pushed in onset order before advancing their source watermark.
No acquisition boundary is introduced by advance() or checkpoint(); finalize()
alone closes the physical recording and qualifies truncated final gates.
"""

import base64
from hashlib import sha256
import math
from pathlib import Path

import numpy as np

import gegi_digital_readout as digital
import gegi_exposure_stream as legacy
from gegi_imaging import MIN_COLLECTED_KEV
import gegi_pulse_stream as pulse


KIND = 'gegi_incremental_readout_checkpoint_v1'
PRODUCER_SHA256 = sha256(Path(__file__).read_bytes()).hexdigest()
DIGEST_KIND = 'gegi_fixed_adc_block_chain_v1'
DIGEST_BLOCK_FRAMES = 1024
_CHANNELS = len(digital.CONTACT_IDS)
_DT = legacy.SAMPLE_PERIOD_NS
_TAUS = legacy._TAUS


class WindowOverflow(RuntimeError):
    """Processing stopped with all received data retained in checkpoint_state."""

    def __init__(self, message, checkpoint_state):
        super().__init__(message)
        self.checkpoint_state = checkpoint_state


def _pack(array, dtype):
    return base64.b64encode(np.asarray(array, dtype=dtype, order='C').tobytes()).decode('ascii')


def _unpack(body, dtype, shape):
    raw = base64.b64decode(body, validate=True)
    if len(raw) != math.prod(shape) * np.dtype(dtype).itemsize:
        raise ValueError('Checkpoint array shape or bytes changed')
    return np.frombuffer(raw, dtype=dtype).reshape(shape).copy()


class StreamingReadout:
    """Keep active native pulses, one analog carry and local ADC/activity history.

    max_context_samples is an explicit operational bound, never a selection cut.
    Overflow retains at most one extra processing block and raises WindowOverflow
    with a restartable checkpoint. Restore with a larger bound to continue.
    The caller supplies a chronological input watermark, including delayed groups.
    """

    def __init__(self, *, noise_seed=None, phase_ns=0., block_samples=32768,
                 max_context_samples=4096, max_active_components=4096,
                 live_time_ns=None, trigger_profile='standard', on_readout_context=None,
                 on_adc_block=None):
        if not math.isfinite(phase_ns) or not 0 <= phase_ns < _DT:
            raise ValueError('ADC phase must be in one nominal sample period')
        if noise_seed is not None and (type(noise_seed) is not int or not 0 <= noise_seed < 2**64):
            raise ValueError('Use a noise seed smaller than 2**64')
        if any(type(v) is not int or v <= 0 for v in (block_samples, max_context_samples, max_active_components)):
            raise ValueError('ADC block, context and active-component bounds must be positive integers')
        if live_time_ns is not None and (not math.isfinite(live_time_ns) or live_time_ns <= phase_ns):
            raise ValueError('A recording must contain at least one ADC sample')
        self.phase_ns = float(phase_ns)
        self.noise_seed = noise_seed
        self.block_samples = block_samples
        self.max_context_samples = max_context_samples
        self.max_active_components = max_active_components
        self.live_time_ns = live_time_ns
        self.trigger_profile = trigger_profile
        self._threshold = pulse.trigger_threshold(trigger_profile)
        self.on_readout_context = on_readout_context
        self.on_adc_block = on_adc_block
        self._rngs = [] if noise_seed is None else [np.random.Generator(np.random.PCG64([noise_seed, cid]))
                                                  for cid in digital.CONTACT_IDS]
        self._pulses = []
        self._sequence = 0
        self._last_onset = -math.inf
        self._carry = np.zeros((2, _CHANNELS))
        self._carry_time = 0.
        self._carry_valid = False
        self._next_index = 0
        self._input_watermark_ns = 0.
        self._groups = []
        self._emitted_through = -legacy.PREAMBLE_SAMPLES-1
        self._accounted_through = -legacy.PREAMBLE_SAMPLES-1
        self._trigger_count = 0
        self._accepted_count = 0
        self._rejected_count = 0
        self._activity_count = 0
        self._unconfirmed_count = 0
        self._maximum_context = 0
        self._rail_counts = np.zeros(_CHANNELS, dtype=np.int64)
        self._active_peak = 0
        self._buffer_peak = 0
        self._activities_peak = 0
        self._digest_chain = bytes(32)
        self._digest_blocks = 0
        self._digest_pending = bytearray()
        self._digest_frames = 0
        self._finalized = False
        self._reason_end = None
        preamble = self._digitize(np.zeros((_CHANNELS, legacy.PREAMBLE_SAMPLES)))
        self._baseline = (preamble * digital._LSB_V).mean(axis=1)
        self._face_baseline = np.array([self._baseline[face].sum() for face in pulse._FACES])[:, None]
        self._previous_face = legacy._face_voltages(preamble[:, -pulse._FAST_SAMPLES:]) - self._face_baseline
        self._buffer_lo = -legacy.PREAMBLE_SAMPLES
        self._buffer = preamble
        self._note_codes(self._buffer_lo, preamble)

    def _digitize(self, voltage):
        for values, rng in zip(voltage, self._rngs):
            values += rng.normal(0., digital._PROFILE['optional_noise_rms_V'], values.size)
        return digital._digitize(voltage)[0].astype(np.int16)

    def _chain_block(self, raw):
        frames = len(raw) // (_CHANNELS * 2)
        body = (self._digest_chain + self._digest_blocks.to_bytes(8, 'little')
                + frames.to_bytes(4, 'little') + raw)
        self._digest_chain = sha256(body).digest()
        self._digest_blocks += 1

    def _note_codes(self, first, code):
        self._rail_counts += legacy._rail(code).sum(axis=1, dtype=np.int64)
        self._digest_pending.extend(np.asarray(code.T, dtype='<i2', order='C').tobytes())
        self._digest_frames += code.shape[1]
        size = DIGEST_BLOCK_FRAMES * _CHANNELS * 2
        while len(self._digest_pending) >= size:
            self._chain_block(bytes(self._digest_pending[:size]))
            del self._digest_pending[:size]
        self._buffer_peak = max(self._buffer_peak, self._buffer.shape[1])
        if self.on_adc_block is not None:
            self.on_adc_block(first, code)

    def _overflow(self, message):
        self._reason_end = 'operational_bound_reached'
        raise WindowOverflow(message, self.checkpoint())

    def push(self, native, onset_ns, scale=1.):
        """Push a complete prepared native pulse before advancing past its onset."""
        if self._finalized:
            raise ValueError('The recording is finalized')
        if (not isinstance(native, pulse.NativePulse) or not math.isfinite(onset_ns)
                or onset_ns < self._input_watermark_ns or onset_ns < self._last_onset
                or not math.isfinite(scale) or scale <= 0):
            raise ValueError('Push prepared pulses in onset order before their source watermark')
        if self.live_time_ns is not None and onset_ns >= self.live_time_ns:
            raise ValueError('A new pulse onset must lie inside the physical recording')
        if len(self._pulses) >= self.max_active_components:
            self._overflow('Active/pending pulse bound reached; advance the watermark or restore with a larger bound')
        if (native.time_ns.ndim != 1 or not len(native.time_ns) or native.time_ns[0] != 0
                or native.drive_V.shape != (2, _CHANNELS, len(native.time_ns))
                or native.knot_V.shape != native.drive_V.shape):
            raise ValueError('Use an all-electrode NativePulse from prepare_native')
        self._pulses.append((self._sequence, native, float(onset_ns), float(scale)))
        self._sequence += 1
        self._last_onset = float(onset_ns)
        self._active_peak = max(self._active_peak, len(self._pulses))
        self._reason_end = None

    def _analog(self, times):
        """Same endpoint-ordered two-pole arithmetic as ADCExposure, only locally."""
        voltage = np.zeros((_CHANNELS, len(times)))
        ended = sorted((row for row in self._pulses if row[2]+row[1].time_ns[-1] <= times[-1]),
                       key=lambda row: (row[2]+row[1].time_ns[-1], row[0]))
        cursor = 0

        def tail(lo, hi):
            if self._carry_valid and lo < hi:
                decay = np.exp(-(times[lo:hi] - self._carry_time) / _TAUS)
                voltage[:, lo:hi] = legacy._POLE_GAIN * (
                    self._carry[0, :, None] * decay[0] - self._carry[1, :, None] * decay[1])

        for _, native, onset, scale in ended:
            end = onset + native.time_ns[-1]
            stop = int(times.searchsorted(end))
            tail(cursor, stop)
            self._carry = self._carry * np.exp(-(end-self._carry_time) / _TAUS) + scale*native.knot_V[..., -1]
            self._carry_time, self._carry_valid, cursor = float(end), True, stop
        tail(cursor, len(times))
        for _, native, onset, scale in self._pulses:
            end = onset + native.time_ns[-1]
            if onset <= times[-1] and end > times[0]:
                lo, hi = times.searchsorted([onset, end])
                voltage[:, lo:hi] += scale * pulse._sample_pulse(native, times[lo:hi]-onset)
        self._pulses = [row for row in self._pulses if row[2]+row[1].time_ns[-1] > times[-1]]
        return voltage

    def _closed(self, index, *, final=False):
        return final or index < len(self._groups)-1 or self._next_index-1-self._groups[index][1] > pulse._QUIET_SAMPLES

    def _account_groups(self, *, final=False):
        for i, (start, _, coincidence) in enumerate(self._groups):
            if start > self._accounted_through and self._closed(i, final=final):
                self._unconfirmed_count += not coincidence
                self._accounted_through = start

    def _emit_ready(self, *, final=False):
        live = (math.ceil((self.live_time_ns-self.phase_ns)/_DT) if self.live_time_ns is not None
                else self._next_index if final else self._next_index+self.max_context_samples+self.block_samples+1)
        clock = legacy._SavedClock(live, self.phase_ns)
        contexts = {context.pivot: context for context in legacy._contexts(clock, self._groups)}
        for i, (start, _, coincidence) in enumerate(self._groups):
            if not coincidence or start <= self._emitted_through:
                continue
            if not self._closed(i, final=final):
                break
            edge = start + pulse._SLOW_NS[1] // _DT
            if not final and self._next_index < edge+2:
                break
            context = contexts[i]
            if not final and any(not self._closed(j) for j in context.neighboring):
                break
            if context.hi-context.lo > self.max_context_samples:
                self._overflow('Readout window exceeds its explicit sample bound; no candidate was truncated')
            if context.hi > self._next_index:
                break
            if context.lo < self._buffer_lo:
                raise RuntimeError('Required ADC history was released before its readout context')
            context.codes = self._buffer[:, context.lo-self._buffer_lo:context.hi-self._buffer_lo]
            event = legacy._context_readout(context, clock, self._groups, self._baseline)
            steps = event['face_step_keV']
            reason = ('no_persistent_coincident_charge_step'
                      if steps is not None and min(steps) < MIN_COLLECTED_KEV else None)
            if self.on_readout_context is not None:
                # Unknown future recording length is represented by this prefix
                # watermark. The exact context and settling support are complete.
                saved_clock = clock if self.live_time_ns is not None or final else legacy._SavedClock(self._next_index, self.phase_ns)
                saved = legacy.readout_context(context, saved_clock, self._groups, self._baseline,
                                               trigger_id=self._trigger_count+1, rejection_reason=reason)
                saved['streaming_producer_sha256'] = PRODUCER_SHA256
                saved['recording_length_scope'] = 'final' if self.live_time_ns is not None or final else 'received_prefix'
                self.on_readout_context(event, saved)
            self._trigger_count += 1
            self._accepted_count += reason is None
            self._rejected_count += reason is not None
            self._emitted_through = start
            self._maximum_context = max(self._maximum_context, context.hi-context.lo)

    def _prune_history(self):
        pending = [start for start, _, coincidence in self._groups
                   if coincidence and start > self._emitted_through]
        if self._groups and not self._closed(len(self._groups)-1):
            pending.append(self._groups[-1][0])
        anchor = min([self._next_index-1, *pending])
        threshold = anchor + pulse._SLOW_NS[0]//_DT - pulse._SLOW_LOOKBACK - 1 - 2*pulse._QUIET_SAMPLES
        self._groups = [row for row in self._groups if row[1] >= threshold]
        lo = anchor + pulse._SLOW_NS[0]//_DT - pulse._SLOW_LOOKBACK - 1
        if self._groups:
            lo = min(lo, self._groups[0][0]-(pulse._QUIET_SAMPLES+pulse._FAST_SAMPLES+2))
        lo = max(-legacy.PREAMBLE_SAMPLES, lo)
        if lo > self._buffer_lo:
            self._buffer = self._buffer[:, lo-self._buffer_lo:].copy()
            self._buffer_lo = lo
        if self._buffer.shape[1] > self.max_context_samples:
            self._overflow('Pending readout history exceeds its explicit sample bound; received data are retained')

    def advance(self, until_ns):
        """Process ADC samples before until_ns after all earlier onsets were pushed."""
        if self._finalized:
            raise ValueError('The recording is finalized')
        if (not math.isfinite(until_ns) or until_ns < self._input_watermark_ns
                or (self.live_time_ns is not None and until_ns > self.live_time_ns)):
            raise ValueError('Advance one nondecreasing physical source watermark inside the recording')
        target = max(0, math.ceil((until_ns-self.phase_ns)/_DT))
        while self._next_index < target:
            first, stop = self._next_index, min(target, self._next_index+self.block_samples)
            times = np.arange(first, stop)*_DT + self.phase_ns
            code = self._digitize(self._analog(times))
            self._buffer = np.concatenate((self._buffer, code), axis=1)
            face = np.concatenate((self._previous_face, legacy._face_voltages(code)-self._face_baseline), axis=1)
            self._previous_face = face[:, -pulse._FAST_SAMPLES:]
            increments = face[:, 1:] - legacy._ALPHA*face[:, :-1]
            change = (increments[:, 1:]+increments[:, :-1]) / (pulse._FAST_SAMPLES*pulse._SLOW_GAIN)
            before = len(self._groups)
            legacy._register_groups(self._groups, first, change, self._threshold)
            self._activity_count += len(self._groups)-before
            self._activities_peak = max(self._activities_peak, len(self._groups))
            self._next_index = stop
            # At overflow a checkpoint still admits new onsets after the last
            # processed sample; input supplied ahead remains in _pulses.
            self._input_watermark_ns = min(float(until_ns), float(times[-1]+np.finfo(float).eps*max(1., abs(times[-1]))))
            self._note_codes(first, code)
            self._account_groups()
            self._emit_ready()
            self._prune_history()
        self._input_watermark_ns = float(until_ns)
        self._reason_end = None
        return self.statistics()

    def finalize(self, live_time_ns):
        """End the physical acquisition once; preserve truncated final-gate flags."""
        if self.live_time_ns is not None and live_time_ns != self.live_time_ns:
            raise ValueError('Finalize the originally declared physical recording interval')
        if not math.isfinite(live_time_ns) or live_time_ns <= self.phase_ns:
            raise ValueError('A recording must contain at least one ADC sample')
        if any(onset >= live_time_ns for _, _, onset, _ in self._pulses):
            raise ValueError('Pushed future inputs lie beyond this recording; do not silently censor them')
        self.advance(live_time_ns)
        self.live_time_ns = float(live_time_ns)
        self._account_groups(final=True)
        self._emit_ready(final=True)
        if self._digest_pending:
            self._chain_block(bytes(self._digest_pending))
            self._digest_pending.clear()
        self._finalized = True
        self._reason_end = 'acquisition_completed'
        return self.statistics()

    def statistics(self):
        flags = []
        if self._rail_counts.any():
            flags.append('adc_saturation')
        if not self._accepted_count:
            flags.append('no_coincident_trigger')
        return {'kind': KIND, 'producer_sha256': PRODUCER_SHA256,
                'status': 'completed' if self._finalized else 'open', 'reason_end': self._reason_end,
                'sample_frames_processed': self._next_index,
                'preamble_samples_per_channel': legacy.PREAMBLE_SAMPLES,
                'active_components_peak': self._active_peak, 'active_components': len(self._pulses),
                'buffered_samples_peak': self._buffer_peak, 'buffered_samples': self._buffer.shape[1],
                'activities_peak': self._activities_peak, 'retained_activities': len(self._groups),
                'activity_count': self._activity_count, 'unconfirmed_activity_count': self._unconfirmed_count,
                'coincident_rises': self._trigger_count, 'accepted_trigger_count': self._accepted_count,
                'rejected_rise_count': self._rejected_count, 'maximum_context_samples': self._maximum_context,
                'saturated_adc_codes': int(self._rail_counts.sum()),
                'saturated_contact_ids': [cid for cid, n in zip(digital.CONTACT_IDS, self._rail_counts) if n],
                'flags': flags, 'adc_digest': {'kind': DIGEST_KIND, 'block_frames': DIGEST_BLOCK_FRAMES,
                    'frames_including_preamble': self._digest_frames, 'blocks': self._digest_blocks,
                    'chain_sha256': self._digest_chain.hex(), 'pending_frames': len(self._digest_pending)//(_CHANNELS*2)}}

    def checkpoint(self):
        """Return JSON-safe exact state, without callbacks or global acquisition lists."""
        return {'kind': KIND, 'producer_sha256': PRODUCER_SHA256,
                'readout_source_sha256': legacy._CONTEXT_SOURCES,
                'settings': {'noise_seed': self.noise_seed, 'phase_ns': self.phase_ns,
                    'block_samples': self.block_samples, 'max_context_samples': self.max_context_samples,
                    'max_active_components': self.max_active_components, 'live_time_ns': self.live_time_ns,
                    'trigger_profile': self.trigger_profile},
                'pulses': [{'sequence': seq, 'onset_ns': onset, 'scale': scale, 'samples': len(native.time_ns),
                    'time_f64': _pack(native.time_ns, '<f8'), 'drive_f64': _pack(native.drive_V, '<f8'),
                    'knot_f64': _pack(native.knot_V, '<f8')} for seq, native, onset, scale in self._pulses],
                'rng_states': [rng.bit_generator.state for rng in self._rngs],
                'carry_f64': _pack(self._carry, '<f8'), 'carry_time_ns': self._carry_time,
                'carry_valid': self._carry_valid, 'next_sample_index': self._next_index,
                'input_watermark_ns': self._input_watermark_ns,
                'last_onset_ns': None if not math.isfinite(self._last_onset) else self._last_onset,
                'sequence': self._sequence, 'groups': [list(row) for row in self._groups],
                'emitted_through': self._emitted_through, 'accounted_through': self._accounted_through,
                'trigger_count': self._trigger_count, 'accepted_count': self._accepted_count,
                'rejected_count': self._rejected_count, 'activity_count': self._activity_count,
                'unconfirmed_count': self._unconfirmed_count, 'maximum_context': self._maximum_context,
                'rail_counts': self._rail_counts.tolist(), 'active_peak': self._active_peak,
                'buffer_peak': self._buffer_peak, 'activities_peak': self._activities_peak,
                'baseline_v': self._baseline.tolist(), 'previous_face_v': self._previous_face.tolist(),
                'buffer_first_index': self._buffer_lo, 'buffer_samples': self._buffer.shape[1],
                'buffer_i16': _pack(self._buffer, '<i2'), 'digest_chain_sha256': self._digest_chain.hex(),
                'digest_blocks': self._digest_blocks, 'digest_frames': self._digest_frames,
                'digest_pending_i16': base64.b64encode(self._digest_pending).decode('ascii'),
                'finalized': self._finalized, 'reason_end': self._reason_end}

    @classmethod
    def restore(cls, saved, *, on_readout_context=None, on_adc_block=None,
                block_samples=None, max_context_samples=None, max_active_components=None):
        """Restore exact state; processing-block/buffer bounds may increase or change."""
        if (saved.get('kind') != KIND or saved.get('producer_sha256') != PRODUCER_SHA256
                or saved.get('readout_source_sha256') != legacy._CONTEXT_SOURCES):
            raise ValueError('Checkpoint producer or readout implementation changed')
        settings = dict(saved['settings'])
        for key, value in (('block_samples', block_samples), ('max_context_samples', max_context_samples),
                           ('max_active_components', max_active_components)):
            if value is not None:
                settings[key] = value
        # The ordinary initializer validates settings and establishes objects;
        # discard its deterministic preamble before restoring exact state.
        obj = cls(**settings)
        obj.on_readout_context, obj.on_adc_block = on_readout_context, on_adc_block
        obj._pulses = [(row['sequence'], pulse.NativePulse(
            _unpack(row['time_f64'], '<f8', (row['samples'],)),
            _unpack(row['drive_f64'], '<f8', (2, _CHANNELS, row['samples'])),
            _unpack(row['knot_f64'], '<f8', (2, _CHANNELS, row['samples']))), row['onset_ns'], row['scale'])
            for row in saved['pulses']]
        if len(obj._pulses) > obj.max_active_components:
            raise ValueError('Restored pulses exceed the selected active-component bound')
        for rng, state in zip(obj._rngs, saved['rng_states'], strict=True):
            rng.bit_generator.state = state
        obj._carry = _unpack(saved['carry_f64'], '<f8', (2, _CHANNELS))
        obj._carry_time, obj._carry_valid = saved['carry_time_ns'], saved['carry_valid']
        obj._next_index, obj._input_watermark_ns = saved['next_sample_index'], saved['input_watermark_ns']
        obj._last_onset = -math.inf if saved['last_onset_ns'] is None else saved['last_onset_ns']
        obj._sequence, obj._groups = saved['sequence'], [tuple(row) for row in saved['groups']]
        for attr, key in (('_emitted_through', 'emitted_through'), ('_accounted_through', 'accounted_through'),
                          ('_trigger_count', 'trigger_count'), ('_accepted_count', 'accepted_count'),
                          ('_rejected_count', 'rejected_count'), ('_activity_count', 'activity_count'),
                          ('_unconfirmed_count', 'unconfirmed_count'), ('_maximum_context', 'maximum_context'),
                          ('_active_peak', 'active_peak'), ('_buffer_peak', 'buffer_peak'),
                          ('_activities_peak', 'activities_peak'), ('_digest_blocks', 'digest_blocks'),
                          ('_digest_frames', 'digest_frames'), ('_finalized', 'finalized'), ('_reason_end', 'reason_end')):
            setattr(obj, attr, saved[key])
        obj._rail_counts = np.asarray(saved['rail_counts'], dtype=np.int64)
        obj._baseline = np.asarray(saved['baseline_v'], dtype=float)
        obj._face_baseline = np.array([obj._baseline[face].sum() for face in pulse._FACES])[:, None]
        obj._previous_face = np.asarray(saved['previous_face_v'], dtype=float)
        obj._buffer_lo = saved['buffer_first_index']
        obj._buffer = _unpack(saved['buffer_i16'], '<i2', (_CHANNELS, saved['buffer_samples']))
        obj._digest_chain = bytes.fromhex(saved['digest_chain_sha256'])
        obj._digest_pending = bytearray(base64.b64decode(saved['digest_pending_i16'], validate=True))
        if (obj._buffer_lo+obj._buffer.shape[1] != obj._next_index
                or obj._previous_face.shape != (2, pulse._FAST_SAMPLES)
                or obj._baseline.shape != (_CHANNELS,) or not np.isfinite(obj._baseline).all()
                or len(obj._digest_chain) != 32
                or len(obj._digest_pending) % (_CHANNELS*2)
                or len(obj._digest_pending) >= DIGEST_BLOCK_FRAMES*_CHANNELS*2):
            raise ValueError('Checkpoint ADC bounds or filter/digest state changed')
        return obj
