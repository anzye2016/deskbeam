"""Tiny cross-platform shims for the few OS calls the server makes.

Windows keeps the original Win32 behaviour; Linux routes through X11
(Xlib core + XTest extension). All functions are safe to call when no
display is reachable — they degrade to no-ops instead of raising.
"""

import os
import sys

_IS_WIN = sys.platform == "win32"


def session_type():
    """How the graphical session is presented: "windows", "x11", "wayland" or
    "unknown". Wayland matters because the whole Linux capture/input path is
    X11 (x11grab, xrandr, XTest): under a Wayland session XWayland still sets
    DISPLAY, so x11grab runs happily but only ever sees X11 clients - the
    viewer gets a black or partial picture instead of an error."""
    if _IS_WIN:
        return "windows"
    t = os.environ.get("XDG_SESSION_TYPE", "").strip().lower()
    if t:
        return t
    if os.environ.get("WAYLAND_DISPLAY"):
        return "wayland"
    if os.environ.get("DISPLAY"):
        return "x11"
    return "unknown"


def is_wayland():
    """True only when the session certainly is Wayland. "unknown" is not, so a
    process launched without session environment (systemd unit, ssh) never
    gets treated as Wayland."""
    return session_type() == "wayland"


if _IS_WIN:
    import ctypes
    import ctypes.wintypes

    def get_cursor_pos():
        pt = ctypes.wintypes.POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
        return int(pt.x), int(pt.y)

    def set_cursor_pos(x, y):
        ctypes.windll.user32.SetCursorPos(int(x), int(y))

    def screen_size():
        return (int(ctypes.windll.user32.GetSystemMetrics(0)),
                int(ctypes.windll.user32.GetSystemMetrics(1)))

    def set_process_priority():
        """ABOVE_NORMAL + 1ms timer resolution, matching the historical
        server tuning. Failures (old Windows / stripped tokens) ignored."""
        try:
            ctypes.windll.winmm.timeBeginPeriod(1)
            ctypes.windll.kernel32.SetPriorityClass(
                ctypes.windll.kernel32.GetCurrentProcess(), 0x00008000)
        except Exception:
            pass

    # Input-desktop query: the interactive desktop is "Default" normally and
    # "Winlogon" while UAC consent / the lock screen / Ctrl+Alt+Del owns the
    # screen. That is the reliable signature that capture is impossible right
    # now (DXGI desktop duplication loses access on the switch). The export
    # name varies by build - Win11 user32 only has the unsuffixed one - so
    # probe for it and leave it None when absent. argtypes are set explicitly
    # because the desktop handle must not be truncated on 64-bit.
    # use_last_error=True is required here: ctypes.get_last_error() only
    # reports a value for DLLs loaded that way. Via ctypes.windll.user32 the
    # error slot stays 0, which silently defeated the ERROR_ACCESS_DENIED
    # check below (measured: a failing user32 call reports 0 vs 2).
    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _open_input_desktop = None
    for _name in ("OpenInputDesktopW", "OpenInputDesktopA", "OpenInputDesktop"):
        try:
            _open_input_desktop = getattr(_user32, _name)
            break
        except AttributeError:
            continue
    if _open_input_desktop is not None:
        _open_input_desktop.restype = ctypes.wintypes.HANDLE
        _open_input_desktop.argtypes = [ctypes.wintypes.DWORD,
                                        ctypes.wintypes.BOOL,
                                        ctypes.wintypes.DWORD]
        _user32.GetUserObjectInformationW.restype = ctypes.wintypes.BOOL
        _user32.GetUserObjectInformationW.argtypes = [
            ctypes.wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
            ctypes.wintypes.DWORD, ctypes.POINTER(ctypes.wintypes.DWORD)]
        _user32.CloseDesktop.restype = ctypes.wintypes.BOOL
        _user32.CloseDesktop.argtypes = [ctypes.wintypes.HANDLE]

    def _input_desktop_state():
        """(name, last_error) of the session's input desktop. name is None
        when the desktop could not be opened."""
        if _open_input_desktop is None:
            return None, 0
        ctypes.set_last_error(0)
        h = _open_input_desktop(0, False, 0x0001)  # DESKTOP_READOBJECTS
        if not h:
            return None, ctypes.get_last_error()
        try:
            buf = ctypes.create_unicode_buffer(256)
            need = ctypes.wintypes.DWORD()
            ok = _user32.GetUserObjectInformationW(
                h, 2, buf, ctypes.sizeof(buf), ctypes.byref(need))  # UOI_NAME
            if ok:
                return buf.value, 0
            return None, ctypes.get_last_error()
        except Exception:
            return None, 0
        finally:
            _user32.CloseDesktop(h)

    def input_desktop_name():
        return _input_desktop_state()[0]

    def is_secure_desktop():
        """True while UAC / the lock screen / a secure desktop owns the screen.

        Measured on Win11: with the UAC prompt up, OpenInputDesktop failed
        with ERROR_ACCESS_DENIED (5) for every access mask and returned to
        "Default" the moment it was dismissed - a medium-integrity process is
        denied the secure desktop rather than shown its name, so the denial
        itself is the signal. A desktop that does open as something other
        than "Default" counts too. A missing API never reports secure."""
        name, err = _input_desktop_state()
        if name is not None:
            return name != "Default"
        return err == 5  # ERROR_ACCESS_DENIED

else:
    from Xlib import X as _X
    from Xlib import display as _xdisplay
    from Xlib.ext import xtest as _xtest

    _dpy = None

    def _get_dpy():
        """Lazily (re)connect: the server may start before the graphical
        session exists."""
        global _dpy
        if _dpy is None:
            try:
                _dpy = _xdisplay.Display()
            except Exception:
                _dpy = None
        return _dpy

    def get_cursor_pos():
        d = _get_dpy()
        if d is None:
            return 0, 0
        try:
            p = d.screen().root.query_pointer()
            return int(p.root_x), int(p.root_y)
        except Exception:
            return 0, 0

    def set_cursor_pos(x, y):
        d = _get_dpy()
        if d is None:
            return
        try:
            _xtest.fake_input(d, _X.MotionNotify, x=int(x), y=int(y))
            d.sync()
        except Exception:
            pass

    def screen_size():
        d = _get_dpy()
        if d is None:
            return 1920, 1080
        s = d.screen()
        return int(s.width_in_pixels), int(s.height_in_pixels)

    def set_process_priority():
        # BELOW the default nice would need CAP_SYS_NICE; lowering priority
        # is pointless here, and ABOVE_NORMAL niceness is best-effort only.
        try:
            import os
            os.nice(-5)
        except Exception:
            pass

    def input_desktop_name():
        return None

    def is_secure_desktop():
        # X11 has no secure-desktop switch to report; capture loss there is
        # just a normal stall.
        return False


# ── 剪贴板（手动读取，一次）──────────────────────────────────────────────
# 只读**纯文本**。必须先判 CF_HDROP：Windows 复制文件时也会把文件名放进
# CF_UNICODETEXT，先读文本就会把"文件路径"当成文本发出去。
def read_clipboard_text(max_chars=10000):
    """Return (text, why). Windows only; files / 非文本 -> ("", 原因)。"""
    if not _IS_WIN:
        return "", "仅 Windows 支持"
    import ctypes
    import time as _t
    from ctypes import wintypes
    u32 = ctypes.WinDLL("user32", use_last_error=True)
    u32.OpenClipboard.argtypes = [wintypes.HWND]
    u32.OpenClipboard.restype = wintypes.BOOL
    u32.IsClipboardFormatAvailable.argtypes = [wintypes.UINT]
    u32.IsClipboardFormatAvailable.restype = wintypes.BOOL
    u32.GetClipboardData.argtypes = [wintypes.UINT]
    u32.GetClipboardData.restype = wintypes.HANDLE
    u32.CloseClipboard.argtypes = []
    u32.CloseClipboard.restype = wintypes.BOOL
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    k32.GlobalLock.restype = wintypes.LPVOID
    k32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    k32.GlobalUnlock.restype = wintypes.BOOL

    CF_UNICODETEXT, CF_HDROP = 13, 15
    opened = False
    for _ in range(10):                  # 剪贴板常被别的程序短暂占用
        if u32.OpenClipboard(None):
            opened = True
            break
        _t.sleep(0.05)
    if not opened:
        return "", "剪贴板被占用"
    try:
        if u32.IsClipboardFormatAvailable(CF_HDROP):
            return "", "复制的是文件，不处理"
        if not u32.IsClipboardFormatAvailable(CF_UNICODETEXT):
            return "", "剪贴板里没有文本"
        h = u32.GetClipboardData(CF_UNICODETEXT)
        if not h:
            return "", "读取失败"
        p = k32.GlobalLock(h)
        if not p:
            return "", "锁定失败"
        try:
            text = ctypes.wstring_at(p) or ""
        finally:
            k32.GlobalUnlock(h)
        if not text:
            return "", "剪贴板是空的"
        if len(text) > max_chars:
            return text[:max_chars], "已截断到 %d 字符" % max_chars
        return text, ""
    finally:
        u32.CloseClipboard()
