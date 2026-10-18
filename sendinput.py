import ctypes
import time
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
# 绝对坐标归一化到 0..65535。两个标志必须一起用:
#   MOUSEEVENTF_ABSOLUTE   —— dx/dy 是归一化绝对坐标而非相对位移
#   MOUSEEVENTF_VIRTUALDESK—— 映射到**整个虚拟桌面**。少了它,绝对坐标只映射到
#                             主显示器:实测主屏 2560 宽、虚拟桌面 x∈[-1920,2559] 时,
#                             目标 (0,0) 会落到 (1097,0)、(1279,719) 落到 (1828,719),
#                             左侧副屏根本到不了。
MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_VIRTUALDESK = 0x4000

_SetCursorPos = ctypes.windll.user32.SetCursorPos
_SetCursorPos.argtypes = [wintypes.INT, wintypes.INT]
_SetCursorPos.restype = wintypes.BOOL

_GetSystemMetrics = ctypes.windll.user32.GetSystemMetrics
_GetSystemMetrics.argtypes = [ctypes.c_int]
_GetSystemMetrics.restype = ctypes.c_int
SM_CXSCREEN, SM_CYSCREEN = 0, 1
SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN = 76, 77
SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN = 78, 79

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
    # f1..f24:VK_F1=0x70 连续排列。原来只有 f5/f12,键盘行组合器的"输入 f 键"会
    # 对 f1-f4、f6-f11、f13+ 静默失败(服务端 _vk 返回 0,SendInput 什么也不发)。
    **{f"f{i}": 0x6F + i for i in range(1, 25)},
    "space": 0x20,
    "shift": 0x10, "ctrl": 0x11, "alt": 0x12,
    # 命名键里原先缺的几个(键盘行组合器会用到)
    "del": 0x2E, "delete": 0x2E, "ins": 0x2D, "insert": 0x2D,
    "caps": 0x14, "capslock": 0x14, "menu": 0x5D, "apps": 0x5D,
    "prtsc": 0x2C, "printscreen": 0x2C, "pause": 0x13,
}

# 符号 -> VK。**不能靠 ord()**:ord('.')=0x2E 而 0x2E 是 VK_DELETE,句号的 VK 是 0xBE;
# 逗号/减号/斜杠这些同理。只覆盖单字符键,字母数字仍走 ord(upper)。
_VK_CHAR = {
    ".": 0xBE, ",": 0xBC, "-": 0xBD, "=": 0xBB, "/": 0xBF, ";": 0xBA,
    "'": 0xDE, "[": 0xDB, "]": 0xDD, "\\": 0xDC, "`": 0xC0,
    " ": 0x20,
}

_MOD = {
    "ctrl": 0x11, "alt": 0x12, "shift": 0x10,
}

def _vk(key):
    vk = _VK.get(key)
    if vk:
        return vk
    if key and len(key) == 1:
        # 先查符号表,再退回 ord():字母数字 ord() 恰好等于 VK,符号则不然
        sym = _VK_CHAR.get(key)
        if sym:
            return sym
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

# 单发键的保持时长。零时长会被按帧轮询输入的游戏整帧漏掉(与鼠标点击同一个坑,
# 见 mouse_click 的注释)。40ms = 60fps 的 2.4 帧 / 30fps 的 1.2 帧。
# type_text 不走这里,所以不影响打字速度;press 只被 key_press 用。
KEY_TAP_HOLD_MS = 40


def press(key, hold_ms=None):
    vk = _vk(key)
    if not vk:
        return
    hold = KEY_TAP_HOLD_MS if hold_ms is None else int(hold_ms)
    _send_scancode(vk)
    if hold > 0:
        time.sleep(hold / 1000.0)
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
    # 主键也必须有保持时长:否则整组组合键在游戏里等于没按下去(见 KEY_TAP_HOLD_MS)
    time.sleep(KEY_TAP_HOLD_MS / 1000.0)
    _send_scancode(vk, up=True)
    for m in reversed(mod_vks):
        _send_scancode(m, up=True)

def mouse_event(flags, dx=0, dy=0, data=0):
    mi = MOUSEINPUT(dx, dy, data, flags, 0, 0)
    inp = INPUT(INPUT_MOUSE, _INPUT_UNION(mi=mi))
    _SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))

def _virtual_screen():
    """(x, y, w, h) of the virtual desktop, falling back to the primary monitor."""
    w = _GetSystemMetrics(SM_CXVIRTUALSCREEN) or _GetSystemMetrics(SM_CXSCREEN) or 1
    h = _GetSystemMetrics(SM_CYVIRTUALSCREEN) or _GetSystemMetrics(SM_CYSCREEN) or 1
    return (_GetSystemMetrics(SM_XVIRTUALSCREEN), _GetSystemMetrics(SM_YVIRTUALSCREEN),
            w, h)


# ── 点击类:按下与抬起之间必须有保持时长 ──────────────────────────────────
# 同一毫秒内 down+up 的话,按帧轮询输入的游戏可能整帧都没看到"按下"状态 ->
# 单击/双击被吞掉(用户实测:游戏里点画面不认,左键按钮认)。50ms 足够。
CLICK_HOLD_MS = 50
DBL_GAP_MS = 40

LEFTDOWN, LEFTUP = 0x0002, 0x0004
RIGHTDOWN, RIGHTUP = 0x0008, 0x0010
MIDDLEDOWN, MIDDLEUP = 0x0020, 0x0040


def _click(down, up, hold_ms=None):
    hold = CLICK_HOLD_MS if hold_ms is None else int(hold_ms)
    mouse_event(down)
    if hold > 0:
        time.sleep(hold / 1000.0)
    mouse_event(up)


def mouse_click(hold_ms=None):
    _click(LEFTDOWN, LEFTUP, hold_ms)


def mouse_right_click(hold_ms=None):
    _click(RIGHTDOWN, RIGHTUP, hold_ms)


def mouse_middle_click(hold_ms=None):
    _click(MIDDLEDOWN, MIDDLEUP, hold_ms)


def mouse_double_click(hold_ms=None, gap_ms=None):
    gap = DBL_GAP_MS if gap_ms is None else int(gap_ms)
    _click(LEFTDOWN, LEFTUP, hold_ms)
    if gap > 0:
        time.sleep(gap / 1000.0)
    _click(LEFTDOWN, LEFTUP, hold_ms)


def mouse_move_to(x, y):
    """把光标移到 (x, y),并**产生一次真正的鼠标移动事件**。

    **不能只用 SetCursorPos。** 它只把光标搬过去,不产生鼠标输入事件、也不经过
    Raw Input Thread;而 Windows 的菜单(TrackPopupMenu / #32768 窗口)是模态循环
    + 鼠标捕获,靠鼠标消息驱动高亮/选中/取消。只挪光标时菜单收不到移动事件,
    随后 SendInput 的点击又会被投递到持有捕获的菜单窗口 —— 表现就是"点菜单就
    卡死,只有真实鼠标移动(ESP 那种真 USB HID 也一样)才能跳出来"。

    归一化按**虚拟桌面**尺寸算,并带上 MOUSEEVENTF_VIRTUALDESK,这样多显示器也
    落在正确那块屏上(本机是主屏 2560x1440 + 左侧 1920x1080,虚拟桌面
    x∈[-1920,2559];只按主屏归一化会把所有绝对移动挤到主屏)。SetCursorPos 放在
    最后把落点钉到精确像素,它本身在多显示器下也是权威的。
    """
    vx, vy, vw, vh = _virtual_screen()
    cx = max(vx, min(vx + vw - 1, int(x)))
    cy = max(vy, min(vy + vh - 1, int(y)))
    mouse_event(MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK,
                int(round((cx - vx) * 65535 / max(1, vw - 1))),
                int(round((cy - vy) * 65535 / max(1, vh - 1))))
    _SetCursorPos(int(x), int(y))

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
