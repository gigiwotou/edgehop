#include <string.h>

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/queue.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "esp_event.h"
#include "esp_wifi.h"
#include "esp_now.h"
#include "nvs_flash.h"
#include "tinyusb.h"
#include "tusb.h"

#include "mk_proto.h"

static const char *TAG = "mk_dongle";

static const uint8_t s_broadcast[ESP_NOW_ETH_ALEN] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};

typedef struct {
    uint8_t data[MK_FRAME_LEN];
} hid_msg_t;

static QueueHandle_t s_queue;

/* 报告 ID 1：绝对坐标鼠标；报告 ID 2：标准 boot 键盘 */
static const uint8_t s_hid_report_desc[] = {
    0x05, 0x01,        /* Usage Page (Generic Desktop) */
    0x09, 0x02,        /* Usage (Mouse) */
    0xA1, 0x01,        /* Collection (Application) */
    0x85, 0x01,        /*   Report ID (1) */
    0x09, 0x01,        /*   Usage (Pointer) */
    0xA1, 0x00,        /*   Collection (Physical) */
    0x05, 0x09,        /*     Usage Page (Button) */
    0x19, 0x01,        /*     Usage Minimum (1) */
    0x29, 0x05,        /*     Usage Maximum (5) */
    0x15, 0x00,        /*     Logical Minimum (0) */
    0x25, 0x01,        /*     Logical Maximum (1) */
    0x95, 0x05,        /*     Report Count (5) */
    0x75, 0x01,        /*     Report Size (1) */
    0x81, 0x02,        /*     Input (Data,Var,Abs) */
    0x95, 0x01,        /*     Report Count (1) */
    0x75, 0x03,        /*     Report Size (3) */
    0x81, 0x01,        /*     Input (Const) */
    0x05, 0x01,        /*     Usage Page (Generic Desktop) */
    0x09, 0x30,        /*     Usage (X) */
    0x09, 0x31,        /*     Usage (Y) */
    0x16, 0x00, 0x00,  /*     Logical Minimum (0) */
    0x26, 0xFF, 0x7F,  /*     Logical Maximum (32767) */
    0x75, 0x10,        /*     Report Size (16) */
    0x95, 0x02,        /*     Report Count (2) */
    0x81, 0x02,        /*     Input (Data,Var,Abs) */
    0x09, 0x38,        /*     Usage (Wheel) */
    0x15, 0x81,        /*     Logical Minimum (-127) */
    0x25, 0x7F,        /*     Logical Maximum (127) */
    0x75, 0x08,        /*     Report Size (8) */
    0x95, 0x01,        /*     Report Count (1) */
    0x81, 0x06,        /*     Input (Data,Var,Rel) */
    0xC0,              /*   End Collection */
    0xC0,              /* End Collection */

    0x05, 0x01,        /* Usage Page (Generic Desktop) */
    0x09, 0x06,        /* Usage (Keyboard) */
    0xA1, 0x01,        /* Collection (Application) */
    0x85, 0x02,        /*   Report ID (2) */
    0x05, 0x07,        /*   Usage Page (Keyboard) */
    0x19, 0xE0,        /*   Usage Minimum (Left Control) */
    0x29, 0xE7,        /*   Usage Maximum (Right GUI) */
    0x15, 0x00,        /*   Logical Minimum (0) */
    0x25, 0x01,        /*   Logical Maximum (1) */
    0x75, 0x01,        /*   Report Size (1) */
    0x95, 0x08,        /*   Report Count (8) */
    0x81, 0x02,        /*   Input (Data,Var,Abs) */
    0x95, 0x01,        /*   Report Count (1) */
    0x75, 0x08,        /*   Report Size (8) */
    0x81, 0x01,        /*   Input (Const) */
    0x95, 0x06,        /*   Report Count (6) */
    0x75, 0x08,        /*   Report Size (8) */
    0x15, 0x00,        /*   Logical Minimum (0) */
    0x25, 0x65,        /*   Logical Maximum (101) */
    0x05, 0x07,        /*   Usage Page (Keyboard) */
    0x19, 0x00,        /*   Usage Minimum (0) */
    0x29, 0x65,        /*   Usage Maximum (101) */
    0x81, 0x00,        /*   Input (Data,Array,Abs) */
    0xC0               /* End Collection */
};

uint8_t const *tud_hid_descriptor_report_cb(uint8_t instance)
{
    (void)instance;
    return s_hid_report_desc;
}

uint16_t tud_hid_get_report_cb(uint8_t instance, uint8_t report_id,
                               hid_report_type_t report_type, uint8_t *buffer,
                               uint16_t reqlen)
{
    (void)instance;
    (void)report_id;
    (void)report_type;
    (void)buffer;
    (void)reqlen;
    return 0;
}

void tud_hid_set_report_cb(uint8_t instance, uint8_t report_id,
                           hid_report_type_t report_type,
                           uint8_t const *buffer, uint16_t bufsize)
{
    (void)instance;
    (void)report_id;
    (void)report_type;
    (void)buffer;
    (void)bufsize;
}

static void radio_recv_cb(const esp_now_recv_info_t *info, const uint8_t *data, int len)
{
    (void)info;

    if (len != MK_RADIO_PAYLOAD_MAX) {
        return;
    }

    uint8_t target = data[0];
    if (target != CONFIG_MK_DEVICE_ID && target != MK_TARGET_ALL) {
        return;
    }

    hid_msg_t msg;
    memcpy(msg.data, &data[1], MK_FRAME_LEN);
    xQueueSend(s_queue, &msg, 0);
}

static void radio_init(void)
{
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());

    wifi_init_config_t wifi_cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&wifi_cfg));
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_start());
    ESP_ERROR_CHECK(esp_wifi_set_ps(WIFI_PS_NONE));
    ESP_ERROR_CHECK(esp_wifi_set_channel(CONFIG_MK_CHANNEL, WIFI_SECOND_CHAN_NONE));

    ESP_ERROR_CHECK(esp_now_init());

    esp_now_peer_info_t peer = {0};
    memcpy(peer.peer_addr, s_broadcast, ESP_NOW_ETH_ALEN);
    peer.channel = CONFIG_MK_CHANNEL;
    peer.ifidx = WIFI_IF_STA;
    peer.encrypt = false;
    ESP_ERROR_CHECK(esp_now_add_peer(&peer));

    ESP_ERROR_CHECK(esp_now_register_recv_cb(radio_recv_cb));
    ESP_LOGI(TAG, "device id %d, channel %d", CONFIG_MK_DEVICE_ID, CONFIG_MK_CHANNEL);
}

static void usb_init(void)
{
    tinyusb_config_t tusb_cfg = {0};
    ESP_ERROR_CHECK(tinyusb_driver_install(&tusb_cfg));
}

static void send_mouse(uint8_t buttons, uint16_t x, uint16_t y, int8_t wheel)
{
    uint8_t report[6] = {
        buttons,
        (uint8_t)(x & 0xFF),
        (uint8_t)(x >> 8),
        (uint8_t)(y & 0xFF),
        (uint8_t)(y >> 8),
        (uint8_t)wheel,
    };
    tud_hid_report(1, report, sizeof(report));
}

static void send_keyboard(uint8_t modifier, const uint8_t *keys)
{
    uint8_t report[8] = {modifier, 0, 0, 0, 0, 0, 0, 0};
    memcpy(&report[2], keys, 6);
    tud_hid_report(2, report, sizeof(report));
}

static void hid_task(void *arg)
{
    (void)arg;
    hid_msg_t msg;

    for (;;) {
        if (xQueueReceive(s_queue, &msg, portMAX_DELAY) != pdTRUE) {
            continue;
        }
        if (!tud_mounted() || !tud_hid_ready()) {
            continue;
        }

        switch (msg.data[0]) {
        case MK_MSG_MOUSE_ABS: {
            uint16_t x = (uint16_t)(msg.data[1] | (msg.data[2] << 8));
            uint16_t y = (uint16_t)(msg.data[3] | (msg.data[4] << 8));
            send_mouse(msg.data[5], x, y, (int8_t)msg.data[6]);
            break;
        }
        case MK_MSG_KEY_REPORT:
            send_keyboard(msg.data[1], &msg.data[2]);
            break;
        case MK_MSG_RELEASE_ALL:
            send_keyboard(0, (const uint8_t[6]){0});
            send_mouse(0, 0, 0, 0);
            break;
        default:
            break;
        }
    }
}

void app_main(void)
{
    esp_err_t err = nvs_flash_init();
    if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        err = nvs_flash_init();
    }
    ESP_ERROR_CHECK(err);

    s_queue = xQueueCreate(16, sizeof(hid_msg_t));

    radio_init();
    usb_init();

    xTaskCreate(hid_task, "mk_hid", 4096, NULL, 10, NULL);
    ESP_LOGI(TAG, "dongle ready");
}
