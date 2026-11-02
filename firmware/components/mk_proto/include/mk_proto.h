#pragma once

#include <stdint.h>
#include <stddef.h>
#include <string.h>

#ifdef __cplusplus
extern "C" {
#endif

/*
 * PC <-> Hub <-> Dongle 共用协议。
 *
 * 所有报文固定 8 字节，第 0 字节为类型，便于 CDC 断包后重新对齐。
 *
 * MOUSE_ABS  [0]=0x01 [1..2]=x(0..32767) [3..4]=y(0..32767)
 *            [5]=buttons(bit0 左 / bit1 右 / bit2 中 / bit3 侧1 / bit4 侧2)
 *            [6]=wheel(int8) [7]=pan(int8)
 * KEY_REPORT [0]=0x03 [1]=modifier [2..7]=HID 键码(最多 6 个)
 * RELEASE_ALL[0]=0x04 其余补 0
 * SWITCH     [0]=0x05 [1]=目标设备 id(0 表示回到主机)
 *
 * 无线载荷 = [目标 id][8 字节报文]
 */

#define MK_FRAME_LEN        8
#define MK_TARGET_MASTER    0
#define MK_TARGET_ALL       0xFF

#define MK_MSG_MOUSE_ABS    0x01
#define MK_MSG_MOUSE_REL    0x02
#define MK_MSG_KEY_REPORT   0x03
#define MK_MSG_RELEASE_ALL  0x04
#define MK_MSG_SWITCH       0x05

#define MK_RADIO_PAYLOAD_MAX (MK_FRAME_LEN + 1)

static inline void mk_frame_switch(uint8_t *f, uint8_t target)
{
    memset(f, 0, MK_FRAME_LEN);
    f[0] = MK_MSG_SWITCH;
    f[1] = target;
}

static inline void mk_frame_mouse_abs(uint8_t *f, uint16_t x, uint16_t y,
                                      uint8_t buttons, int8_t wheel)
{
    memset(f, 0, MK_FRAME_LEN);
    f[0] = MK_MSG_MOUSE_ABS;
    f[1] = (uint8_t)(x & 0xFF);
    f[2] = (uint8_t)(x >> 8);
    f[3] = (uint8_t)(y & 0xFF);
    f[4] = (uint8_t)(y >> 8);
    f[5] = buttons;
    f[6] = (uint8_t)wheel;
}

static inline uint8_t mk_frame_type(const uint8_t *f)
{
    return f[0];
}

#ifdef __cplusplus
}
#endif
