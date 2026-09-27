import ctypes
from ctypes import wintypes

ULONG_PTR = ctypes.c_size_t

class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]

class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]

class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]

class _INPUT_UNION(ctypes.Union):
    _fields_ = [
        ("mi", MOUSEINPUT),
        ("ki", KEYBDINPUT),
        ("hi", HARDWAREINPUT),
    ]

class INPUT(ctypes.Structure):
    _fields_ = [
        ("type", wintypes.DWORD),
        ("_input", _INPUT_UNION),
    ]

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008
KEYEVENTF_UNICODE = 0x0004

MAPVK_VK_TO_VSC = 0

# VK codes that require the E0 extended-key prefix (scan codes for these
# are two-byte scancodes; DirectInput games need KEYEVENTF_EXTENDEDKEY).
_EXTENDED_VKS = {
    0x21, 0x22, 0x23, 0x24,                    # pgup pgdn end home
    0x25, 0x26, 0x27, 0x28,                    # left up right down
    0x5B, 0x5C, 0x5D,                          # win
}

MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_WHEEL = 0x0800

_SetCursorPos = ctypes.windll.user32.SetCursorPos
_SetCursorPos.argtypes = [wintypes.INT, wintypes.INT]
_SetCursorPos.restype = wintypes.BOOL

_SendInput = ctypes.windll.user32.SendInput
_SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
_SendInput.restype = wintypes.UINT

_MapVirtualKeyW = ctypes.windll.user32.MapVirtualKeyW
_MapVirtualKeyW.argtypes = [wintypes.UINT, wintypes.UINT]
_MapVirtualKeyW.restype = wintypes.UINT

_VK = {
    "enter": 0x0D, "esc": 0x1B, "backspace": 0x08, "tab": 0x09,
    "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
    "pgup": 0x21, "pgdn": 0x22, "home": 0x24, "end": 0x23,
    "win": 0x5B, "f5": 0x74, "f12": 0x7B,
    "space": 0x20,
    "shift": 0x10, "ctrl": 0x11, "alt": 0x12,
}

_MOD = {
    "ctrl": 0x11, "alt": 0x12, "shift": 0x10,
}

def _vk(key):
    vk = _VK.get(key)
    if vk:
        return vk
    if key and len(key) == 1:
        return ord(key.upper())
    return 0

def _send(vk=0, scan=0, flags=0):
    ki = KEYBDINPUT(vk, scan, flags, 0, 0)
    inp = INPUT(INPUT_KEYBOARD, _INPUT_UNION(ki=ki))
    _SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))

def _send_scancode(vk, up=False):
    scan = _MapVirtualKeyW(vk, MAPVK_VK_TO_VSC)
    flags = KEYEVENTF_SCANCODE
    if vk in _EXTENDED_VKS:
        flags |= KEYEVENTF_EXTENDEDKEY
    if up:
        flags |= KEYEVENTF_KEYUP
    if not scan:
        flags = KEYEVENTF_KEYUP if up else 0
        _send(vk=vk, flags=flags)
        return
    _send(scan=scan, flags=flags)

def press(key):
    vk = _vk(key)
    if not vk:
        return
    _send_scancode(vk)
    _send_scancode(vk, up=True)

def key_down(key):
    vk = _vk(key)
    if vk:
        _send_scancode(vk)

def key_up(key):
    vk = _vk(key)
    if vk:
        _send_scancode(vk, up=True)

def combo(name):
    parts = name.split("_")
    if len(parts) < 2:
        return
    mods = parts[:-1]
    key = parts[-1]
    mod_vks = []
    for m in mods:
        vk = _MOD.get(m)
        if vk:
            mod_vks.append(vk)
    vk = _VK.get(key) or (ord(key.upper()) if len(key) == 1 and key.isalpha() else None)
    if vk is None:
        return
    for m in mod_vks:
        _send_scancode(m)
    _send_scancode(vk)
    _send_scancode(vk, up=True)
    for m in reversed(mod_vks):
        _send_scancode(m, up=True)

def mouse_event(flags, dx=0, dy=0, data=0):
    mi = MOUSEINPUT(dx, dy, data, flags, 0, 0)
    inp = INPUT(INPUT_MOUSE, _INPUT_UNION(mi=mi))
    _SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))

def mouse_move_to(x, y):
    _SetCursorPos(x, y)

def type_text(text, batch=500):
    """Inject Unicode text via SendInput. Events are batched into arrays —
    one syscall per batch instead of two per character (2000 chars:
    4000 calls -> 4)."""
    for start in range(0, len(text), batch):
        events = []
        for ch in text[start:start + batch]:
            scan = ord(ch)
            events.append(INPUT(INPUT_KEYBOARD,
                                _INPUT_UNION(ki=KEYBDINPUT(0, scan, KEYEVENTF_UNICODE, 0, 0))))
            events.append(INPUT(INPUT_KEYBOARD,
                                _INPUT_UNION(ki=KEYBDINPUT(0, scan, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, 0, 0))))
        arr = (INPUT * len(events))(*events)
        _SendInput(len(events), arr, ctypes.sizeof(INPUT))
