"""跨屏状态机：本地放行、远程拦截并向 Hub 转发绝对坐标。"""

import ctypes
import time
from ctypes import Structure, byref, c_long

from . import protocol
from .keymap import VK_MODIFIERS, VK_TO_HID

SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79

VK_M = 0x4D
VK_CTRL = (0x11, 0xA2, 0xA3)
VK_ALT = (0x12, 0xA4, 0xA5)

SEND_INTERVAL = 0.004  # 最高 250 帧/秒，避免 ESP-NOW 拥塞

BUTTON_FLAGS = {
    0x0001: (0x01, True),
    0x0002: (0x01, False),
    0x0004: (0x02, True),
    0x0008: (0x02, False),
    0x0010: (0x04, True),
    0x0020: (0x04, False),
    0x0040: (0x08, True),
    0x0080: (0x08, False),
    0x0100: (0x10, True),
    0x0200: (0x10, False),
}

RI_MOUSE_WHEEL = 0x0400
RI_MOUSE_HWHEEL = 0x0800


class RECT(Structure):
    _fields_ = [("left", c_long), ("top", c_long), ("right", c_long), ("bottom", c_long)]


class POINT(Structure):
    _fields_ = [("x", c_long), ("y", c_long)]


_user32 = ctypes.windll.user32


def virtual_screen():
    return (
        _user32.GetSystemMetrics(SM_XVIRTUALSCREEN),
        _user32.GetSystemMetrics(SM_YVIRTUALSCREEN),
        _user32.GetSystemMetrics(SM_CXVIRTUALSCREEN),
        _user32.GetSystemMetrics(SM_CYVIRTUALSCREEN),
    )


def cursor_position():
    point = POINT()
    _user32.GetCursorPos(byref(point))
    return point.x, point.y


def set_cursor_position(x, y):
    _user32.SetCursorPos(int(x), int(y))


def clip_cursor(x, y):
    rect = RECT(int(x), int(y), int(x) + 1, int(y) + 1)
    _user32.ClipCursor(byref(rect))


def unclip_cursor():
    _user32.ClipCursor(None)


class Controller:
    def __init__(self, link, layout, logger=print):
        self.link = link
        self.layout = layout
        self.logger = logger

        self.mode = "local"
        self.target_id = protocol.TARGET_MASTER
        self.vx, self.vy, self.vw, self.vh = virtual_screen()

        self.buttons = 0
        self.mods = 0
        self.keys = []

        self.rx = 0.0
        self.ry = 0.0
        self.exit_side = "left"
        self.last_send = 0.0

        self._ctrl = False
        self._alt = False

        if self.vw <= 0 or self.vh <= 0:
            raise RuntimeError("无法获取主显示器尺寸")

    # ---------- 鼠标 ----------

    def on_mouse(self, dx, dy, flags, wheel, pan):
        changed = self._update_buttons(flags)

        if self.mode == "local":
            if dx or dy:
                x, _ = cursor_position()
                if dx < 0 and x <= self.vx and self.layout.left:
                    self._enter_remote("left", x)
                elif dx > 0 and x >= self.vx + self.vw - 1 and self.layout.right:
                    self._enter_remote("right", x)
            return

        target = self.layout.by_id(self.target_id)
        if target is None or target.width <= 0 or target.height <= 0:
            self._return_to_master()
            return

        self.rx += dx * (target.width / max(1, self.vw))
        self.ry += dy * (target.height / max(1, self.vh))
        self.rx = min(max(self.rx, 0.0), target.width - 1)
        self.ry = min(max(self.ry, 0.0), target.height - 1)

        now = time.monotonic()
        immediate = changed or wheel or pan
        if immediate or now - self.last_send >= SEND_INTERVAL:
            self._send_mouse(target, wheel, pan)

    def _update_buttons(self, flags) -> bool:
        new_buttons = self.buttons
        for flag, (mask, pressed) in BUTTON_FLAGS.items():
            if flags & flag:
                new_buttons = (new_buttons | mask) if pressed else (new_buttons & ~mask)
        changed = new_buttons != self.buttons
        self.buttons = new_buttons
        return changed

    def _send_mouse(self, target, wheel=0, pan=0):
        x16 = int(round(self.rx / max(1, target.width - 1) * 32767))
        y16 = int(round(self.ry / max(1, target.height - 1) * 32767))
        self.link.send(protocol.frame_mouse_abs(x16, y16, self.buttons, wheel, pan))
        self.last_send = time.monotonic()

    # ---------- 键盘 ----------

    def on_key(self, vk, down, extended, injected) -> bool:
        if injected:
            return False

        if vk in VK_CTRL:
            self._ctrl = down
        elif vk in VK_ALT:
            self._alt = down

        # Ctrl+Alt+M：从从机返回主机
        if down and vk == VK_M and self._ctrl and self._alt and self.mode == "remote":
            self._return_to_master()
            return True

        if self.mode == "local":
            return False

        self._apply_key(vk, down)
        return True

    def _apply_key(self, vk, down):
        modifier = VK_MODIFIERS.get(vk)
        if modifier is not None:
            self.mods = (self.mods | modifier) if down else (self.mods & ~modifier)
        else:
            hid = VK_TO_HID.get(vk)
            if hid is None:
                return
            if down:
                if hid not in self.keys:
                    self.keys.append(hid)
            else:
                if hid in self.keys:
                    self.keys.remove(hid)
            self.keys = self.keys[:6]

        self.link.send(protocol.frame_key_report(self.mods, self.keys))

    # ---------- 状态切换 ----------

    def _enter_remote(self, side, cursor_x):
        target = self.layout.left if side == "left" else self.layout.right
        if target is None:
            return

        self.mode = "remote"
        self.target_id = target.id
        self.exit_side = side

        _, y = cursor_position()
        ratio = (y - self.vy) / max(1, self.vh)
        self.ry = min(max(ratio * target.height, 0.0), target.height - 1)
        # 从主机左边缘切出时，进入从机的右边缘，反之亦然
        self.rx = (target.width - 1) if side == "left" else 0.0

        self._clear_keys()
        self.link.send(protocol.frame_switch(target.id))
        self.link.send(protocol.frame_release_all())

        clip_cursor(cursor_x, y)
        self._send_mouse(target)
        self.logger(f"切到 {target.name} (id={target.id})")

    def _return_to_master(self):
        if self.mode == "local":
            return

        self.link.send(protocol.frame_release_all())
        self.link.send(protocol.frame_switch(protocol.TARGET_MASTER))

        self.mode = "local"
        self.target_id = protocol.TARGET_MASTER
        self._clear_keys()
        unclip_cursor()

        # 放回边缘内侧 2px，避免立即再次触发切出
        _, y = cursor_position()
        edge_x = self.vx + (2 if self.exit_side == "left" else self.vw - 3)
        set_cursor_position(edge_x, y)
        self.logger("回到主机")

    def _clear_keys(self):
        self.mods = 0
        self.keys = []

    def shutdown(self):
        if self.mode == "remote":
            self._return_to_master()
