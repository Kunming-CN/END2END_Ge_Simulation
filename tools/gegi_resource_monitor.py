"""Measured process memory and owned run bytes; no installed monitoring dependency."""
from __future__ import annotations
from bisect import bisect_left
from contextlib import contextmanager
import ctypes
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time


TIMER_KIND = 'gegi_stage_timing_totals_v1'
TIMER_STAGES = ('transport_cli', 'transport_prepare', 'transport_run', 'transport_extract',
                'transport_verify', 'native_worker_load', 'native_group', 'readout', 'checkpoint', 'export')
TIMER_HISTOGRAM_UPPER_SECONDS = (0.0001, 0.001, 0.01, 0.1, 1., 10., 60., 600.)
NATIVE_OUTCOMES = ('completed', 'failed', 'unavailable')


def _timing_row():
    return {'count': 0, 'total_seconds': 0., 'min_seconds': None, 'max_seconds': None,
            'exception_count': 0, 'unsealed_measurement_count': 0,
            'histogram_counts': [0] * (len(TIMER_HISTOGRAM_UPPER_SECONDS)+1)}


def _nonnegative_number(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


class TimerTotals:
    """Fixed-size measured wall-time summaries, independent of process RSS.

    Use disjoint scopes for cost attribution. Nested different stages are allowed
    and explicitly inclusive; their totals must not be summed as total wall time.
    Operational exceptions and authoritative native outcomes are separate counts.
    A snapshot excludes in-flight intervals and names them; restore marks those
    intervals timing-unsealed instead of inventing elapsed time across downtime.
    """

    def __init__(self, previous=None, *, clock=time.perf_counter):
        self._clock = clock
        self._lock = threading.RLock()
        self._active = {}
        self._stages = {stage: _timing_row() for stage in TIMER_STAGES}
        self._native = {outcome: 0 for outcome in NATIVE_OUTCOMES}
        if previous is not None:
            self._restore(previous)

    @staticmethod
    def _stage(stage):
        if type(stage) is not str or stage not in TIMER_STAGES:
            raise ValueError('Choose a defined stage timing name')
        return stage

    def record(self, stage, elapsed_seconds, *, exception=False):
        """Add one measured interval, including a separately reported CLI interval."""
        stage = self._stage(stage)
        if not _nonnegative_number(elapsed_seconds) or type(exception) is not bool:
            raise ValueError('Use a finite nonnegative measured time and explicit exception flag')
        elapsed = float(elapsed_seconds)
        with self._lock:
            row = self._stages[stage]
            total = row['total_seconds'] + elapsed
            if not math.isfinite(total):
                raise ValueError('Stage timing total exceeds finite seconds')
            row['count'] += 1
            row['total_seconds'] = total
            row['min_seconds'] = elapsed if row['min_seconds'] is None else min(row['min_seconds'], elapsed)
            row['max_seconds'] = elapsed if row['max_seconds'] is None else max(row['max_seconds'], elapsed)
            row['exception_count'] += exception
            row['histogram_counts'][bisect_left(TIMER_HISTOGRAM_UPPER_SECONDS, elapsed)] += 1

    @contextmanager
    def measure(self, stage):
        """Measure a scope and re-raise its original exception after recording time."""
        stage = self._stage(stage)
        with self._lock:
            if stage in self._active:
                raise ValueError('A stage timing scope is already active')
            started = self._clock()
            if not _nonnegative_number(started):
                raise ValueError('The stage clock must return finite nonnegative seconds')
            self._active[stage] = started
        exception = False
        try:
            yield self
        except BaseException:
            exception = True
            raise
        finally:
            ended = self._clock()
            with self._lock:
                del self._active[stage]
                if not _nonnegative_number(ended) or ended < started:
                    raise ValueError('The stage clock must be monotonic finite seconds')
                self.record(stage, ended-started, exception=exception)

    def record_native(self, outcome):
        """Count the checked native result once; never infer it from timing errors."""
        if type(outcome) is not str or outcome not in NATIVE_OUTCOMES:
            raise ValueError('Use native outcome completed, failed or unavailable')
        with self._lock:
            self._native[outcome] += 1

    def snapshot(self):
        """Return independent finite JSON data; active clock readings are not saved."""
        with self._lock:
            return {'kind': TIMER_KIND, 'unit': 'seconds',
                    'scope': 'Measured inclusive wall times; nested stage totals overlap. '
                             'No transport/native/readout production runtime extrapolation.',
                    'histogram_upper_seconds': list(TIMER_HISTOGRAM_UPPER_SECONDS),
                    'histogram_convention': 'Upper-inclusive bins; final bin exceeds the last finite bound.',
                    'stages': {stage: {**row, 'histogram_counts': list(row['histogram_counts'])}
                               for stage, row in self._stages.items()},
                    'native_outcomes': dict(self._native), 'in_flight_stages': list(self._active)}

    def _restore(self, saved):
        if (type(saved) is not dict or saved.get('kind') != TIMER_KIND or saved.get('unit') != 'seconds'
                or saved.get('histogram_upper_seconds') != list(TIMER_HISTOGRAM_UPPER_SECONDS)
                or type(saved.get('stages')) is not dict or set(saved['stages']) != set(TIMER_STAGES)
                or type(saved.get('native_outcomes')) is not dict
                or set(saved['native_outcomes']) != set(NATIVE_OUTCOMES)):
            raise ValueError('Unsupported stage timing checkpoint identity or bins')
        expected_keys = set(_timing_row())
        rows = {}
        for stage, original in saved['stages'].items():
            if (type(original) is not dict or set(original) != expected_keys
                    or type(original.get('histogram_counts')) is not list):
                raise ValueError('Invalid saved stage timing fields')
            row = {**original, 'histogram_counts': list(original['histogram_counts'])}
            counts = [row[key] for key in ('count', 'exception_count', 'unsealed_measurement_count')]
            histogram = row['histogram_counts']
            if (any(type(value) is not int or value < 0 for value in counts)
                    or row['exception_count'] > row['count']
                    or not _nonnegative_number(row['total_seconds'])
                    or len(histogram) != len(TIMER_HISTOGRAM_UPPER_SECONDS)+1
                    or any(type(value) is not int or value < 0 for value in histogram)
                    or sum(histogram) != row['count']):
                raise ValueError('Saved stage timing counts, total or histogram do not close')
            if row['count'] == 0:
                if row['total_seconds'] != 0 or row['min_seconds'] is not None or row['max_seconds'] is not None:
                    raise ValueError('An unmeasured stage must retain null timing bounds')
            elif (not _nonnegative_number(row['min_seconds']) or not _nonnegative_number(row['max_seconds'])
                    or not row['min_seconds'] <= row['max_seconds'] <= row['total_seconds']):
                raise ValueError('Saved stage timing bounds are invalid')
            rows[stage] = row
        if any(type(value) is not int or value < 0 for value in saved['native_outcomes'].values()):
            raise ValueError('Invalid saved native outcome counts')
        in_flight = saved.get('in_flight_stages')
        if (type(in_flight) is not list or any(type(stage) is not str or stage not in TIMER_STAGES for stage in in_flight)
                or len(set(in_flight)) != len(in_flight)):
            raise ValueError('Invalid saved in-flight timing stages')
        for stage in in_flight:
            rows[stage]['unsealed_measurement_count'] += 1
        self._stages, self._native = rows, dict(saved['native_outcomes'])


def memory_bytes(pid):
    if os.name == 'nt':
        from ctypes import wintypes
        class Counters(ctypes.Structure):
            _fields_ = [('cb', wintypes.DWORD), ('PageFaultCount', wintypes.DWORD)] + [
                (name, ctypes.c_size_t) for name in ('PeakWorkingSetSize', 'WorkingSetSize',
                'QuotaPeakPagedPoolUsage', 'QuotaPagedPoolUsage', 'QuotaPeakNonPagedPoolUsage',
                'QuotaNonPagedPoolUsage', 'PagefileUsage', 'PeakPagefileUsage')]
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        process = kernel.OpenProcess(0x1000 | 0x10, False, pid)
        if not process:
            return None
        try:
            data = Counters(); data.cb = ctypes.sizeof(data)
            read = ctypes.WinDLL('psapi').GetProcessMemoryInfo
            read.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
            if read(process, ctypes.byref(data), data.cb):
                return {'resident_bytes': data.WorkingSetSize, 'peak_resident_bytes': data.PeakWorkingSetSize}
            return None
        finally:
            kernel.CloseHandle(process)
    try:
        result = subprocess.run(['ps', '-o', 'rss=', '-p', str(pid)], capture_output=True, text=True, check=False)
        value = int(result.stdout.strip()) * 1024
        return {'resident_bytes': value, 'peak_resident_bytes': value}
    except (ValueError, FileNotFoundError):
        return None


def available_memory():
    if os.name == 'nt':
        class Status(ctypes.Structure):
            _fields_ = [('length', ctypes.c_uint32), ('load', ctypes.c_uint32)] + [
                (key, ctypes.c_uint64) for key in ('total', 'available', 'page_total', 'page_available',
                                                 'virtual_total', 'virtual_available', 'extended')]
        value = Status(); value.length = ctypes.sizeof(value)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(value)):
            return value.available
        return None
    if sys.platform == 'darwin':
        result = subprocess.run(['vm_stat'], capture_output=True, text=True, check=False)
        import re
        page = re.search(r'page size of (\d+) bytes', result.stdout)
        fields = dict(re.findall(r'(Pages (?:free|inactive|speculative)):\s+(\d+)', result.stdout))
        return int(page[1]) * sum(int(v) for v in fields.values()) if page and fields else None
    try:
        fields = dict(line.split(':', 1) for line in Path('/proc/meminfo').read_text().splitlines())
        return int(fields['MemAvailable'].split()[0]) * 1024
    except (OSError, KeyError, ValueError):
        return None


def owned_bytes(root):
    total = 0
    for directory, children, files in os.walk(root, followlinks=False):
        children[:] = [name for name in children if not _linked(Path(directory) / name)]
        for name in files:
            path = Path(directory) / name
            try:
                if not _linked(path):
                    total += path.stat().st_size
            except FileNotFoundError:
                pass  # A committed native spool can retire between samples.
    return total


def _linked(path):
    return path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction())


class Monitor:
    def __init__(self, root, previous=None):
        self.root = Path(root)
        self.pids = {'python': os.getpid()}
        self.data = dict(previous or {})
        self.data.setdefault('process_peak_resident_bytes', {})
        self.data.setdefault('sampled_combined_resident_peak_bytes', 0)
        self.data.setdefault('run_logical_bytes_peak', 0)
        self.data.setdefault('active_elapsed_seconds', 0.)
        self.data['sampling_interval_seconds'] = .5
        self.data['scope'] = 'Python/native process RSS and owned run logical files; transport child peak is reported separately. Peaks between samples may be missed.'
        self.stop = threading.Event()
        self.started = time.perf_counter()
        self.thread = threading.Thread(target=self._loop, name='gegi-resource-monitor', daemon=True)

    def sample(self):
        combined = 0
        for name, pid in tuple(self.pids.items()):
            row = memory_bytes(pid)
            if row is not None:
                combined += row['resident_bytes']
                self.data['process_peak_resident_bytes'][name] = max(
                    self.data['process_peak_resident_bytes'].get(name, 0), row['peak_resident_bytes'])
        self.data['sampled_combined_resident_peak_bytes'] = max(
            combined, self.data['sampled_combined_resident_peak_bytes'])
        self.data['run_logical_bytes_peak'] = max(owned_bytes(self.root), self.data['run_logical_bytes_peak'])
        self.data['disk_free_bytes_last'] = shutil.disk_usage(self.root).free

    def _loop(self):
        while not self.stop.wait(.5):
            self.sample()

    def __enter__(self):
        self.sample(); self.thread.start()
        return self

    def __exit__(self, *args):
        self.stop.set(); self.thread.join()
        self.sample()
        self.data['active_elapsed_seconds'] += time.perf_counter() - self.started
