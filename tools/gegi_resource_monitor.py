"""Measured process memory and owned run bytes; no installed monitoring dependency."""
from __future__ import annotations
import ctypes
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time


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
