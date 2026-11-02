"""Raw Input 鼠标 + 低层键盘钩子。

鼠标走 Raw Input 而不是低层钩子：低层钩子在拦截时会丢失相对位移，
而 Raw Input 的 lLastX/lLastY 始终有效，切到从机后本地光标被 ClipCursor
钉在屏幕边缘，位移数据仍然连续。
"""

import ctypes
import time
from ctypes import POINTER, Structure, WINFUNCTYPE, byref, sizeof, wintypes
from ctypes import c_int, c_short, c_size_t, c_ssize_t, c_uint, c_ulong, c_ushort, c_void_p, c_wchar_p

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

WM_INPUT = 0x00FF
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105

WH_KEYBOARD_LL = 13
HC_ACTION = 0
LLKHF_EXTENDED = 0x01
LLKHF_INJECTED = 0x10

RID_INPUT = 0x10000003
RIM_TYPEMOUSE = 0
RIDEV_INPUTSINK = 0x00000100

MOUSE_MOVE_ABSOLUTE = 0x01

RI_MOUSE_LEFT_BUTTON_DOWN = 0x0001
RI_MOUSE_LEFT_BUTTON_UP = 0x0002
RI_MOUSE_RIGHT_BUTTON_DOWN = 0x0004
RI_MOUSE_RIGHT_BUTTON_UP = 0x0008
RI_MOUSE_MIDDLE_BUTTON_DOWN = 0x0010
RI_MOUSE_MIDDLE_BUTTON_UP = 0x0020
RI_MOUSE_BUTTON_4_DOWN = 0x0040
RI_MOUSE_BUTTON_4_UP = 0x0080
RI_MOUSE_BUTTON_5_DOWN = 0x0100
RI_MOUSE_BUTTON_5_UP = 0x0200
RI_MOUSE_WHEEL = 0x0400
RI_MOUSE_HWHEEL = 0x0800

PM_REMOVE = 0x0001

LRESULT = c_ssize_t
WNDPROC = WINFUNCTYPE(LRESULT, c_void_p, c_uint, c_size_t, c_ssize_t)
HOOKPROC = WINFUNCTYPE(LRESULT, c_int, c_size_t, c_ssize_t)


class WNDCLASSW(Structure):
    _fields_ = [
        ("style", c_uint),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", c_int),
        ("cbWndExtra", c_int),
        ("hInstance", c_void_p),
        ("hIcon", c_void_p),
        ("hCursor", c_void_p),
        ("hbrBackground", c_void_p),
        ("lpszMenuName", c_wchar_p),
        ("lpszClassName", c_wchar_p),
    ]


class RAWINPUTDEVICE(Structure):
    _fields_ = [
        ("usUsagePage", c_ushort),
        ("usUsage", c_ushort),
        ("dwFlags", c_ulong),
        ("hwndTarget", c_void_p),
    ]


class RAWINPUTHEADER(Structure):
    _fields_ = [
        ("dwType", c_ulong),
        ("dwSize", c_ulong),
        ("hDevice", c_void_p),
        ("wParam", c_size_t),
    ]


class _ButtonUnion(ctypes.Union):
    _fields_ = [("usButtonFlags", c_ushort), ("usButtonData", c_ushort)]


class RAWMOUSE(Structure):
    _fields_ = [
        ("usFlags", c_ushort),
        ("u", _ButtonUnion),
        ("ulRawButtons", c_ulong),
        ("lLastX", ctypes.c_long),
        ("lLastY", ctypes.c_long),
        ("ulExtraInformation", c_ulong),
    ]


class KBDLLHOOKSTRUCT(Structure):
    _fields_ = [
        ("vkCode", c_ulong),
        ("scanCode", c_ulong),
        ("flags", c_ulong),
        ("time", c_ulong),
        ("dwExtraInfo", c_size_t),
    ]


user32.SetWindowsHookExW.argtypes = [c_int, HOOKPROC, c_void_p, c_uint]
user32.SetWindowsHookExW.restype = c_void_p
user32.CallNextHookEx.argtypes = [c_void_p, c_int, c_size_t, c_ssize_t]
user32.CallNextHookEx.restype = LRESULT
user32.UnhookWindowsHookEx.argtypes = [c_void_p]
user32.RegisterClassW.argtypes = [POINTER(WNDCLASSW)]
user32.CreateWindowExW.argtypes = [
    c_uint, c_wchar_p, c_wchar_p, c_uint,
    c_int, c_int, c_int, c_int,
    c_void_p, c_void_p, c_void_p, c_void_p,
]
user32.CreateWindowExW.restype = c_void_p
user32.DefWindowProcW.argtypes = [c_void_p, c_uint, c_size_t, c_ssize_t]
user32.DefWindowProcW.restype = LRESULT
user32.GetRawInputData.argtypes = [c_void_p, c_uint, c_void_p, POINTER(c_uint), c_uint]
user32.GetRawInputData.restype = c_uint
user32.RegisterRawInputDevices.argtypes = [POINTER(RAWINPUTDEVICE), c_uint, c_uint]
user32.RegisterRawInputDevices.restype = c_int
user32.PeekMessageW.argtypes = [POINTER(wintypes.MSG), c_void_p, c_uint, c_uint, c_uint]
user32.PeekMessageW.restype = c_int
user32.TranslateMessage.argtypes = [POINTER(wintypes.MSG)]
user32.DispatchMessageW.argtypes = [POINTER(wintypes.MSG)]
kernel32.GetModuleHandleW.argtypes = [c_void_p]
kernel32.GetModuleHandleW.restype = c_void_p


class InputCapture:
    def __init__(self, on_mouse, on_key):
        self._on_mouse = on_mouse
        self._on_key = on_key
        self._stop = False
        self._hwnd = None
        self._hook = None
        self._wnd_proc = WNDPROC(self._handle_window_message)
        self._hook_proc = HOOKPROC(self._handle_keyboard)

    def install(self) -> None:
        hinst = kernel32.GetModuleHandleW(None)

        self._class_name = "MouseKeyRawInput"

        wc = WNDCLASSW()
        wc.lpfnWndProc = self._wnd_proc
        wc.hInstance = hinst
        wc.lpszClassName = self._class_name
        if not user32.RegisterClassW(byref(wc)):
            raise OSError("RegisterClassW failed")

        self._hwnd = user32.CreateWindowExW(
            0, self._class_name, "MouseKey", 0,
            0, 0, 0, 0, None, None, hinst, None,
        )
        if not self._hwnd:
            raise OSError("CreateWindowExW failed")

        rid = RAWINPUTDEVICE(1, 2, RIDEV_INPUTSINK, self._hwnd)
        if not user32.RegisterRawInputDevices(byref(rid), 1, sizeof(RAWINPUTDEVICE)):
            raise OSError("RegisterRawInputDevices failed")

        self._hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._hook_proc, hinst, 0)
        if not self._hook:
            raise OSError("SetWindowsHookExW failed")

    def run(self) -> None:
        msg = wintypes.MSG()
        while not self._stop:
            if user32.PeekMessageW(byref(msg), None, 0, 0, PM_REMOVE):
                user32.TranslateMessage(byref(msg))
                user32.DispatchMessageW(byref(msg))
            else:
                time.sleep(0.001)

    def stop(self) -> None:
        self._stop = True
        if self._hook:
            user32.UnhookWindowsHookEx(self._hook)
            self._hook = None

    def _handle_window_message(self, hwnd, msg, wparam, lparam):
        if msg == WM_INPUT:
            self._handle_raw_input(lparam)
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _handle_raw_input(self, lparam) -> None:
        size = c_uint(0)
        user32.GetRawInputData(lparam, RID_INPUT, None, byref(size), sizeof(RAWINPUTHEADER))
        if size.value <= sizeof(RAWINPUTHEADER):
            return

        buffer = ctypes.create_string_buffer(size.value)
        got = user32.GetRawInputData(lparam, RID_INPUT, buffer, byref(size), sizeof(RAWINPUTHEADER))
        if got != size.value:
            return

        header = ctypes.cast(buffer, POINTER(RAWINPUTHEADER)).contents
        if header.dwType != RIM_TYPEMOUSE:
            return

        offset = ctypes.addressof(buffer) + sizeof(RAWINPUTHEADER)
        mouse = ctypes.cast(c_void_p(offset), POINTER(RAWMOUSE)).contents

        flags = mouse.u.usButtonFlags
        wheel = 0
        pan = 0
        if flags & RI_MOUSE_WHEEL:
            wheel = c_short(mouse.u.usButtonData).value
        if flags & RI_MOUSE_HWHEEL:
            pan = c_short(mouse.u.usButtonData).value

        if mouse.usFlags & MOUSE_MOVE_ABSOLUTE:
            # 远程桌面等场景会给出绝对坐标，当前版本忽略其位移
            dx = 0
            dy = 0
        else:
            dx = mouse.lLastX
            dy = mouse.lLastY

        self._on_mouse(dx, dy, flags, wheel, pan)

    def _handle_keyboard(self, n_code, w_param, l_param) -> int:
        if n_code == HC_ACTION:
            kb = ctypes.cast(c_void_p(l_param), POINTER(KBDLLHOOKSTRUCT)).contents
            down = w_param in (WM_KEYDOWN, WM_SYSKEYDOWN)
            injected = bool(kb.flags & LLKHF_INJECTED)
            if self._on_key(kb.vkCode, down, bool(kb.flags & LLKHF_EXTENDED), injected):
                return 1
        return user32.CallNextHookEx(None, n_code, w_param, l_param)
