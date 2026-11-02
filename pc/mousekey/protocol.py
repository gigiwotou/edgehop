"""PC 与 Hub 之间的定长帧协议，必须与 firmware/components/mk_proto/include/mk_proto.h 保持一致。"""

FRAME_LEN = 8

MSG_MOUSE_ABS = 0x01
MSG_MOUSE_REL = 0x02
MSG_KEY_REPORT = 0x03
MSG_RELEASE_ALL = 0x04
MSG_SWITCH = 0x05

TARGET_MASTER = 0
TARGET_ALL = 0xFF


def _pad(payload: bytes) -> bytes:
    if len(payload) > FRAME_LEN:
        raise ValueError(f"frame too long: {len(payload)}")
    return payload + b"\x00" * (FRAME_LEN - len(payload))


def frame_mouse_abs(x: int, y: int, buttons: int, wheel: int = 0, pan: int = 0) -> bytes:
    x = max(0, min(32767, int(x)))
    y = max(0, min(32767, int(y)))
    return _pad(
        bytes([MSG_MOUSE_ABS])
        + x.to_bytes(2, "little")
        + y.to_bytes(2, "little")
        + bytes([buttons & 0xFF, wheel & 0xFF, pan & 0xFF])
    )


def frame_key_report(modifier: int, keys) -> bytes:
    keys = list(keys)[:6]
    return _pad(bytes([MSG_KEY_REPORT, modifier & 0xFF]) + bytes(keys))


def frame_release_all() -> bytes:
    return _pad(bytes([MSG_RELEASE_ALL]))


def frame_switch(target: int) -> bytes:
    return _pad(bytes([MSG_SWITCH, target & 0xFF]))
