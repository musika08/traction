"""The record number of Windows' newest wake event, for the reapply loop.

On Modern Standby (the Ally's sleep) the wall and monotonic clocks keep running, so the clock check in
reapply_core never sees a sleep, yet the controller still forgets its settings. Windows logs every wake in the
System log: Kernel-Power 507 (leaving Modern Standby) and Power-Troubleshooter 1 (waking from S3/S4). A record
number that changed since the last poll means the PC woke. One read takes about 2 ms.
"""
import re
from typing import Optional

QUERY = ("*[System[(Provider[@Name='Microsoft-Windows-Kernel-Power'] and EventID=507)"
         " or (Provider[@Name='Microsoft-Windows-Power-Troubleshooter'] and EventID=1)]]")
_QUERY_CHANNEL_PATH, _QUERY_REVERSE = 0x1, 0x200
_RENDER_EVENT_XML = 1
_api = None


def _wevtapi():
    global _api
    if _api is None:
        import ctypes
        from ctypes import wintypes
        w = ctypes.WinDLL("wevtapi")
        w.EvtQuery.restype = ctypes.c_void_p
        w.EvtQuery.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD]
        w.EvtNext.argtypes = [ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p), wintypes.DWORD,
                              wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
        w.EvtRender.argtypes = [ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                                ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD)]
        w.EvtClose.argtypes = [ctypes.c_void_p]
        _api = w
    return _api


def last_wake_id() -> Optional[int]:
    """The EventRecordID of the newest wake event, None when there is none or the log can't be read."""
    try:
        import ctypes
        from ctypes import wintypes
        w = _wevtapi()
        query = w.EvtQuery(None, "System", QUERY, _QUERY_CHANNEL_PATH | _QUERY_REVERSE)
        if not query:
            return None
        try:
            event, got = ctypes.c_void_p(), wintypes.DWORD()
            if not w.EvtNext(query, 1, ctypes.byref(event), 0, 0, ctypes.byref(got)):
                return None
            try:
                buf, used, props = ctypes.create_unicode_buffer(8192), wintypes.DWORD(), wintypes.DWORD()
                if not w.EvtRender(None, event, _RENDER_EVENT_XML, ctypes.sizeof(buf), buf, ctypes.byref(used),
                                   ctypes.byref(props)):
                    return None
                m = re.search(r"<EventRecordID>(\d+)</EventRecordID>", buf.value)
                return int(m.group(1)) if m else None
            finally:
                w.EvtClose(event)
        finally:
            w.EvtClose(query)
    except Exception:
        return None
