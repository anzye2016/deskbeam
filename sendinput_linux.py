"""Linux input injection via X11 XTest — drop-in for sendinput.py (Windows).

Same public API: press / combo / type_text / mouse_event / mouse_move_to /
key_down / key_up. The wire protocol speaks Windows Virtual-Key codes, so
this module maps VK -> X keysym -> keycode per keystroke.

Known limitation (documented in docs/DEV-NOTES.md（Linux 移植）): XTest has no
hardware-scan-code mode, so DirectInput-style full-screen games that read
raw scancodes may ignore injected keys.
"""

import sys

from Xlib import display as _xdisplay
from Xlib import X as _X
from Xlib import XK as _XK
from Xlib.ext import xtest as _xtest

# -- Windows MOUSEEVENTF_* flag values (the protocol sends these numbers) --
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_WHEEL = 0x0800

_BTN = {
    MOUSEEVENTF_LEFTDOWN: (_X.ButtonPress, 1),
    MOUSEEVENTF_LEFTUP: (_X.ButtonRelease, 1),
    MOUSEEVENTF_MIDDLEDOWN: (_X.ButtonPress, 2),
    MOUSEEVENTF_MIDDLEUP: (_X.ButtonRelease, 2),
    MOUSEEVENTF_RIGHTDOWN: (_X.ButtonPress, 3),
    MOUSEEVENTF_RIGHTUP: (_X.ButtonRelease, 3),
}

# VK code -> keysym name (superset of sendinput._VK; extras are free).
_VK_KEYSYM = {
    0x08: "BackSpace", 0x09: "Tab", 0x0D: "Return", 0x13: "Pause",
    0x14: "Caps_Lock", 0x1B: "Escape", 0x20: "space",
    0x21: "Prior", 0x22: "Next", 0x23: "End", 0x24: "Home",
    0x25: "Left", 0x26: "Up", 0x27: "Right", 0x28: "Down",
    0x2C: "Print", 0x2D: "Insert", 0x2E: "Delete",
    0x5B: "Super_L", 0x5C: "Super_R", 0x5D: "Menu",
    0x60: "KP_0", 0x61: "KP_1", 0x62: "KP_2", 0x63: "KP_3", 0x64: "KP_4",
    0x65: "KP_5", 0x66: "KP_6", 0x67: "KP_7", 0x68: "KP_8", 0x69: "KP_9",
    0x6A: "KP_Multiply", 0x6B: "KP_Add", 0x6D: "KP_Subtract",
    0x6E: "KP_Decimal", 0x6F: "KP_Divide",
    0x90: "Num_Lock", 0x91: "Scroll_Lock",
    0x10: "Shift_L", 0x11: "Control_L", 0x12: "Alt_L",
    0xA0: "Shift_L", 0xA1: "Shift_R", 0xA2: "Control_L", 0xA3: "Control_R",
    0xA4: "Alt_L", 0xA5: "Alt_R",
    0xBA: "semicolon", 0xBB: "equal", 0xBC: "comma", 0xBD: "minus",
    0xBE: "period", 0xBF: "slash", 0xC0: "grave", 0xDB: "bracketleft",
    0xDC: "backslash", 0xDD: "bracketright", 0xDE: "apostrophe",
}
for _i in range(10):
    _VK_KEYSYM[0x30 + _i] = str(_i)               # 0-9
for _i in range(26):
    _VK_KEYSYM[0x41 + _i] = chr(ord("a") + _i)    # A-Z -> lowercase keysyms
for _i in range(12):
    _VK_KEYSYM[0x70 + _i] = f"F{_i + 1}"          # F1-F12
_VK_KEYSYM[0x7C] = "F13"

_VK = {
    "enter": 0x0D, "esc": 0x1B, "backspace": 0x08, "tab": 0x09,
    "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
    "pgup": 0x21, "pgdn": 0x22, "home": 0x24, "end": 0x23,
    "win": 0x5B, "f5": 0x74, "f12": 0x7B,
    "space": 0x20,
    "shift": 0x10, "ctrl": 0x11, "alt": 0x12,
}

_MOD = {"ctrl": 0xA2, "alt": 0xA4, "shift": 0xA0}   # left variants

_dpy = None


def _get_dpy():
    global _dpy
    if _dpy is None:
        try:
            _dpy = _xdisplay.Display()
        except Exception:
            _dpy = None
        if _dpy is None:
            raise RuntimeError("no X11 display (DISPLAY unset or unreachable)")
    return _dpy


def _keysym_for_vk(vk):
    name = _VK_KEYSYM.get(vk)
    if name is None:
        return 0
    return _XK.string_to_keysym(name)


def _keycode(keysym):
    """Return (keycode, needs_shift); (0, False) when unmapped."""
    d = _get_dpy()
    for kc, col in d.keysym_to_keycodes(keysym):
        if col == 0:
            return kc, False
    for kc, col in d.keysym_to_keycodes(keysym):
        if col == 1:
            return kc, True
    return 0, False


def _vk_keycode(vk):
    ks = _keysym_for_vk(vk)
    if not ks:
        return 0, False
    return _keycode(ks)


def _key_raw(keycode, up=False):
    d = _get_dpy()
    _xtest.fake_input(d, _X.KeyRelease if up else _X.KeyPress, keycode)


def _vk(key):
    vk = _VK.get(key)
    if vk:
        return vk
    if key and len(key) == 1:
        return ord(key.upper())
    return 0


def press(key):
    vk = _vk(key)
    kc, sh = _vk_keycode(vk)
    if not kc:
        return
    if sh:
        kcs, _ = _vk_keycode(_MOD["shift"])
        _key_raw(kcs)
    _key_raw(kc)
    _key_raw(kc, up=True)
    if sh:
        _key_raw(kcs, up=True)
    _get_dpy().sync()


def key_down(key):
    vk = _vk(key)
    kc, sh = _vk_keycode(vk)
    if not kc:
        return
    if sh:
        kcs, _ = _vk_keycode(_MOD["shift"])
        _key_raw(kcs)
    _key_raw(kc)
    _get_dpy().sync()


def key_up(key):
    vk = _vk(key)
    kc, sh = _vk_keycode(vk)
    if not kc:
        return
    _key_raw(kc, up=True)
    if sh:
        kcs, _ = _vk_keycode(_MOD["shift"])
        _key_raw(kcs, up=True)
    _get_dpy().sync()


def combo(name):
    parts = name.split("_")
    if len(parts) < 2:
        return
    mod_vks = [_MOD[m] for m in parts[:-1] if m in _MOD]
    key = parts[-1]
    vk = _VK.get(key) or (ord(key.upper()) if len(key) == 1 and key.isalpha() else None)
    if vk is None:
        return
    d = _get_dpy()
    mod_kcs = []
    for m in mod_vks:
        kc, _ = _vk_keycode(m)
        if kc:
            _key_raw(kc)
            mod_kcs.append(kc)
    kc, sh = _vk_keycode(vk)
    if kc:
        if sh:
            kcs, _ = _vk_keycode(_MOD["shift"])
            _key_raw(kcs)
            mod_kcs.insert(0, kcs)
        _key_raw(kc)
        _key_raw(kc, up=True)
    for kc in reversed(mod_kcs):
        _key_raw(kc, up=True)
    d.sync()


def mouse_move_to(x, y):
    d = _get_dpy()
    root = d.screen().root
    root.warp_pointer(int(x), int(y))
    d.sync()


def mouse_event(flags, dx=0, dy=0, data=0):
    d = _get_dpy()
    if flags == MOUSEEVENTF_MOVE:
        # relative motion: XTest motion is absolute, so read-then-warp
        p = d.screen().root.query_pointer()
        nx, ny = int(p.root_x) + int(dx), int(p.root_y) + int(dy)
        _xtest.fake_input(d, _X.MotionNotify, x=nx, y=ny)
    elif flags == MOUSEEVENTF_WHEEL:
        _xtest.fake_input(d, _X.ButtonPress, 4 if data > 0 else 5)
        _xtest.fake_input(d, _X.ButtonRelease, 4 if data > 0 else 5)
    elif flags in _BTN:
        ev, btn = _BTN[flags]
        _xtest.fake_input(d, ev, btn)
    d.sync()


_SPECIAL_CHARS = {" ": "space", "\t": "Tab", "\n": "Return", "\r": "Return"}


def _char_keysym(ch):
    name = _SPECIAL_CHARS.get(ch)
    if name:
        return _XK.string_to_keysym(name)
    cp = ord(ch)
    if 0 < cp < 0x10000000:
        # Latin-1 chars map to their own keysyms; anything beyond uses the
        # Unicode keysym range 0x01000000 + ucs (works when the keymap or
        # XKB option covers it; otherwise skipped by _keycode()).
        return cp if cp <= 0xFFFF else 0x01000000 | cp
    return 0


def type_text(text, batch=500):
    """Type Unicode text. Chars whose keysym has no keycode in the current
    layout are skipped (Windows injects raw UNICODE events instead)."""
    d = _get_dpy()
    pending = 0
    for ch in text:
        ks = _char_keysym(ch)
        kc, sh = _keycode(ks) if ks else (0, False)
        if not kc:
            continue
        shift_kc = None
        if sh:
            shift_kc, _ = _vk_keycode(_MOD["shift"])
            _key_raw(shift_kc)
        _key_raw(kc)
        _key_raw(kc, up=True)
        if shift_kc:
            _key_raw(shift_kc, up=True)
        pending += 1
        if pending >= batch:
            d.sync()
            pending = 0
    d.sync()
