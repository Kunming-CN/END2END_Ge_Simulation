"""Exact legacy finite unknown-current masks for one known recording interval.

Raw failure evidence remains in the acquisition database. This helper retains
active horizon/energy bounds and the merged exclusion intervals needed for live
time accounting. A bound term is removed only when the legacy expression itself
is exactly floating-point zero at the newest horizon and every later query.
"""

from bisect import bisect_right
from hashlib import sha256
import json
import math
from pathlib import Path

import gegi_dual_source as dual


KIND = 'gegi_finite_missing_history_v2'
PRODUCER_SHA256 = sha256(Path(__file__).read_bytes()).hexdigest()
TAIL_SOURCE_SHA256 = sha256(Path(dual.__file__).read_bytes()).hexdigest()


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def native_support_ns(numerics):
    """Requested drift-step ceiling plus SSD's one native signal-support step."""
    dt, cap = numerics.get('drift_dt_ns', 1.), numerics.get('drift_cap_ns', 1000.)
    if not _number(dt) or not _number(cap) or dt <= 0 or cap <= dt:
        raise ValueError('Use finite positive drift spacing and a longer drift cap')
    return (math.ceil(cap/dt)+1)*dt


class HistoryOverflow(RuntimeError):
    """The new failure was not accepted; existing state is preserved for retry."""

    def __init__(self, state):
        super().__init__('Active missing-history bound reached; checkpoint and increase its explicit bound before retrying')
        self.checkpoint_state = state


class MissingHistory:
    def __init__(self, live_time_ns, *, max_active_failures=65536,
                 native_support_ns=dual.NATIVE_DRIFT_CAP_NS+1.):
        if not _number(live_time_ns) or live_time_ns <= 0:
            raise ValueError('Define the finite physical recording interval')
        if type(max_active_failures) is not int or max_active_failures <= 0:
            raise ValueError('Use a positive active missing-history bound')
        if not _number(native_support_ns) or native_support_ns <= 0:
            raise ValueError('Use the configured positive native signal support')
        self.live_time_ns = float(live_time_ns)
        self.max_active_failures = max_active_failures
        self.native_support_ns = float(native_support_ns)
        self._active = []
        self._excluded = []
        self._starts = []
        self._last_onset = None
        self._max_horizon = 0.
        self._failure_count = 0
        self._active_peak = 0

    def add(self, first_ns, last_ns, energy_keV):
        """Admit a chronological unavailable group without discarding any finite tail."""
        if (not all(_number(value) for value in (first_ns, last_ns, energy_keV))
                or not 0 <= first_ns < self.live_time_ns or last_ns < first_ns or energy_keV < 0
                or (self._last_onset is not None and first_ns < self._last_onset)):
            raise ValueError('Add finite unavailable-group times and energy in onset order inside the recording')
        horizon = last_ns+self.native_support_ns
        if not math.isfinite(horizon):
            raise ValueError('The unavailable-current horizon must remain finite')
        maximum = max(self._max_horizon, horizon)
        active = [row for row in self._active if dual._tail_bound_lsb(row[1], maximum-row[0]) != 0.]
        if dual._tail_bound_lsb(energy_keV, maximum-horizon) != 0.:
            active.append((float(horizon), float(energy_keV)))
        if len(active) > self.max_active_failures:
            raise HistoryOverflow(self.checkpoint())
        period = dual.SAMPLE_PERIOD_NS
        lo, hi = math.ceil(maximum/period), math.ceil(self.live_time_ns/period)
        if lo < hi:
            while lo < hi:
                middle = (lo+hi)//2
                total = math.fsum(dual._tail_bound_lsb(energy, middle*period-end) for end, energy in active)
                if total > dual.MAX_UNSEEN_LSB:
                    lo = middle+1
                else:
                    hi = middle
            finish = min(self.live_time_ns, lo*period)
        else:
            finish = self.live_time_ns
        start = max(0., math.floor((first_ns-dual.POST_NS)/period)*period)
        stop = min(self.live_time_ns, math.ceil((finish+dual.PRE_NS)/period)*period)
        # Adding positive unknown current cannot shorten an earlier unknown tail.
        # Legacy clipping at each following onset therefore gives this same union.
        if start < stop:
            if self._excluded and start <= self._excluded[-1][1]:
                self._excluded[-1][1] = max(self._excluded[-1][1], stop)
            else:
                self._excluded.append([start, stop])
                self._starts.append(start)
        self._active, self._max_horizon, self._last_onset = active, maximum, float(first_ns)
        self._failure_count += 1
        self._active_peak = max(self._active_peak, len(active))

    def contains(self, rise_end_ns, *, trigger_time_ns=None):
        """Use the original trigger-rise/interval overlap rule, not a point shortcut."""
        start = rise_end_ns if trigger_time_ns is None else trigger_time_ns
        if not _number(rise_end_ns) or not _number(start) or start > rise_end_ns:
            raise ValueError('Use finite chronological trigger rise bounds')
        if start >= self.live_time_ns or rise_end_ns < 0:
            return False
        if start < min(dual.PRE_NS, self.live_time_ns) and rise_end_ns >= 0:
            return True
        end_margin = max(0., math.floor((self.live_time_ns-dual.POST_NS)/dual.SAMPLE_PERIOD_NS)*dual.SAMPLE_PERIOD_NS)
        if rise_end_ns >= end_margin and start < self.live_time_ns:
            return True
        index = bisect_right(self._starts, rise_end_ns)-1
        return index >= 0 and self._excluded[index][1] > start

    def intervals(self, live_time_ns=None):
        """Return the sample-aligned merged union, including original PRE/POST edges."""
        if live_time_ns is not None and live_time_ns != self.live_time_ns:
            raise ValueError('Use the original physical recording duration')
        period, live = dual.SAMPLE_PERIOD_NS, self.live_time_ns
        result = []
        for left, right in sorted([[0., dual.PRE_NS], *self._excluded, [live-dual.POST_NS, live]]):
            left = max(0., math.floor(left/period)*period)
            right = min(live, math.ceil(right/period)*period)
            if left >= right:
                continue
            if result and left <= result[-1][1]:
                result[-1][1] = max(result[-1][1], right)
            else:
                result.append([left, right])
        return result

    def checkpoint(self):
        return {'kind': KIND, 'producer_sha256': PRODUCER_SHA256, 'tail_source_sha256': TAIL_SOURCE_SHA256,
                'live_time_ns': self.live_time_ns, 'max_active_failures': self.max_active_failures,
                'native_support_ns': self.native_support_ns,
                'active_bounds': [list(row) for row in self._active],
                'excluded_intervals_ns': [list(row) for row in self._excluded],
                'last_onset_ns': self._last_onset, 'max_horizon_ns': self._max_horizon,
                'failure_count': self._failure_count, 'active_bounds_peak': self._active_peak}

    @classmethod
    def restore(cls, state, *, max_active_failures=None, native_support_ns=None):
        if (state.get('kind') != KIND or state.get('producer_sha256') != PRODUCER_SHA256
                or state.get('tail_source_sha256') != TAIL_SOURCE_SHA256):
            raise ValueError('Missing-history checkpoint implementation changed')
        result = cls(state['live_time_ns'], max_active_failures=(
            state['max_active_failures'] if max_active_failures is None else max_active_failures),
            native_support_ns=state['native_support_ns'])
        if native_support_ns is not None and result.native_support_ns != native_support_ns:
            raise ValueError('Missing-history native support changed from its response configuration')
        active, excluded = state['active_bounds'], state['excluded_intervals_ns']
        if (type(active) is not list or type(excluded) is not list or len(active) > result.max_active_failures
                or not _number(state['max_horizon_ns']) or state['max_horizon_ns'] < 0
                or any(type(state[key]) is not int or state[key] < 0 for key in ('failure_count', 'active_bounds_peak'))
                or state['failure_count'] < len(active) or state['active_bounds_peak'] < len(active)
                or (state['last_onset_ns'] is not None and
                    (not _number(state['last_onset_ns']) or not 0 <= state['last_onset_ns'] < result.live_time_ns))):
            raise ValueError('Invalid missing-history checkpoint bounds or counts')
        for row in active:
            if (type(row) is not list or len(row) != 2 or not all(_number(value) for value in row)
                    or not 0 <= row[0] <= state['max_horizon_ns'] or row[1] < 0):
                raise ValueError('Invalid active unavailable-current bound')
        for i, row in enumerate(excluded):
            if (type(row) is not list or len(row) != 2 or not all(_number(value) for value in row)
                    or not 0 <= row[0] < row[1] <= result.live_time_ns
                    or (i and row[0] <= excluded[i-1][1])):
                raise ValueError('Invalid merged missing-history intervals')
        result._active = [tuple(row) for row in active]
        result._excluded = [list(row) for row in excluded]
        result._starts = [row[0] for row in excluded]
        result._last_onset, result._max_horizon = state['last_onset_ns'], state['max_horizon_ns']
        result._failure_count, result._active_peak = state['failure_count'], state['active_bounds_peak']
        return result

    def statistics(self):
        intervals = self.intervals()
        return {'failure_count': self._failure_count, 'active_failure_bounds': len(self._active),
                'active_failure_bounds_peak': self._active_peak, 'merged_excluded_intervals': len(intervals),
                'excluded_time_ns': math.fsum(right-left for left, right in intervals),
                'checkpoint_json_bytes': len(json.dumps(self.checkpoint(), separators=(',', ':'), allow_nan=False).encode())}
