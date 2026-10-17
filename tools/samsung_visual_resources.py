"""Read own process memory only; no user/system process enumeration."""
import ctypes
import os


def peak_working_set():
    if os.name!='nt':
        import resource
        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024
    class Counters(ctypes.Structure):
        _fields_=[('cb',ctypes.c_ulong),('PageFaultCount',ctypes.c_ulong)]+[(k,ctypes.c_size_t) for k in ('PeakWorkingSetSize','WorkingSetSize','QuotaPeakPagedPoolUsage','QuotaPagedPoolUsage','QuotaPeakNonPagedPoolUsage','QuotaNonPagedPoolUsage','PagefileUsage','PeakPagefileUsage')]
    data=Counters();data.cb=ctypes.sizeof(data)
    handle=ctypes.windll.kernel32.GetCurrentProcess
    handle.restype=ctypes.c_void_p
    call=ctypes.windll.psapi.GetProcessMemoryInfo
    call.argtypes=[ctypes.c_void_p,ctypes.POINTER(Counters),ctypes.c_ulong]
    if not call(handle(),ctypes.byref(data),data.cb):raise ctypes.WinError()
    return data.PeakWorkingSetSize
