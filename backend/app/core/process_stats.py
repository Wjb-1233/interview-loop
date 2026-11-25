"""Current API worker resource observations, including Windows (no new dependency)."""
import os
import sys
import time


def current_process_stats() -> dict:
    rss = None
    try:
        if sys.platform == 'win32':
            import ctypes
            from ctypes import wintypes

            class MemoryCounters(ctypes.Structure):
                _fields_ = [('cb', wintypes.DWORD), ('PageFaultCount', wintypes.DWORD)] + [
                    (name, ctypes.c_size_t) for name in ('PeakWorkingSetSize', 'WorkingSetSize',
                    'QuotaPeakPagedPoolUsage', 'QuotaPagedPoolUsage', 'QuotaPeakNonPagedPoolUsage',
                    'QuotaNonPagedPoolUsage', 'PagefileUsage', 'PeakPagefileUsage')]

            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            kernel.GetCurrentProcess.restype = wintypes.HANDLE
            psapi = ctypes.WinDLL('psapi', use_last_error=True)
            psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(MemoryCounters), wintypes.DWORD]
            counters = MemoryCounters()
            counters.cb = ctypes.sizeof(counters)
            if psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
                rss = counters.WorkingSetSize
        elif sys.platform.startswith('linux'):
            from pathlib import Path
            rss = int(Path('/proc/self/statm').read_text().split()[1]) * os.sysconf('SC_PAGE_SIZE')
    except (OSError, ValueError, IndexError):
        pass
    return {'rssBytes': rss, 'cpuSeconds': time.process_time()}
