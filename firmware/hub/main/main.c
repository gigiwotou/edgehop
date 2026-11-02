#include <string.h>

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "esp_event.h"
#include "esp_wifi.h"
#include "esp_now.h"
#include "nvs_flash.h"
#include "tinyusb.h"
#include "tusb_cdc_acm.h"

#include "mk_proto.h"

static const char *TAG = "mk_hub";

/* 0 = 主机本地使用，不无线转发；1..254 = 当前激活的从机 id */
static uint8_t s_target = MK_TARGET_MASTER;

static const uint8_t s_broadcast[ESP_NOW_ETH_ALEN] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};

static void radio_init(void)
{
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());

    wifi_init_config_t wifi_cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&wifi_cfg));
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_start());
    ESP_ERROR_CHECK(esp_wifi_set_ps(WIFI_PS_NONE));   /* 关闭省电，稳定时延 */
    ESP_ERROR_CHECK(esp_wifi_set_channel(CONFIG_MK_CHANNEL, WIFI_SECOND_CHAN_NONE));

    ESP_ERROR_CHECK(esp_now_init());

    esp_now_peer_info_t peer = {0};
    memcpy(peer.peer_addr, s_broadcast, ESP_NOW_ETH_ALEN);
    peer.channel = CONFIG_MK_CHANNEL;
    peer.ifidx = WIFI_IF_STA;
    peer.encrypt = false;
    ESP_ERROR_CHECK(esp_now_add_peer(&peer));

    ESP_LOGI(TAG, "ESP-NOW ready, channel %d", CONFIG_MK_CHANNEL);
}

static void usb_init(void)
{
    tinyusb_config_t tusb_cfg = {0};
    ESP_ERROR_CHECK(tinyusb_driver_install(&tusb_cfg));

    tinyusb_config_cdcacm_t acm_cfg = {0};
    acm_cfg.usb_dev = TINYUSB_USBDEV_0;
    acm_cfg.cdc_port = TINYUSB_CDC_ACM_0;
    acm_cfg.rx_unread_buf_sz = 64;
    ESP_ERROR_CHECK(tusb_cdcacm_init(&acm_cfg));
}

static void forward_frame(const uint8_t *frame)
{
    if (s_target == MK_TARGET_MASTER) {
        return;
    }

    uint8_t payload[MK_RADIO_PAYLOAD_MAX];
    payload[0] = s_target;
    memcpy(&payload[1], frame, MK_FRAME_LEN);

    esp_err_t err = esp_now_send(s_broadcast, payload, sizeof(payload));
    if (err != ESP_OK) {
        ESP_LOGW(TAG, "esp_now_send failed: 0x%x", err);
    }
}

static void handle_frame(const uint8_t *frame)
{
    switch (mk_frame_type(frame)) {
    case MK_MSG_SWITCH:
        s_target = frame[1];
        ESP_LOGI(TAG, "active target -> %u", s_target);
        break;
    case MK_MSG_MOUSE_ABS:
    case MK_MSG_KEY_REPORT:
    case MK_MSG_RELEASE_ALL:
        forward_frame(frame);
        break;
    default:
        break;
    }
}

static void cdc_task(void *arg)
{
    (void)arg;

    uint8_t chunk[32];
    uint8_t frame[MK_FRAME_LEN];
    size_t fill = 0;

    for (;;) {
        size_t rx = 0;
        if (tusb_cdcacm_read(TINYUSB_CDC_ACM_0, chunk, sizeof(chunk), &rx) == ESP_OK && rx > 0) {
            for (size_t i = 0; i < rx; i++) {
                frame[fill++] = chunk[i];
                if (fill == MK_FRAME_LEN) {
                    fill = 0;
                    handle_frame(frame);
                }
            }
        }
        vTaskDelay(pdMS_TO_TICKS(1));
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

    radio_init();
    usb_init();

    xTaskCreate(cdc_task, "mk_cdc", 4096, NULL, 10, NULL);
    ESP_LOGI(TAG, "hub started, waiting for PC frames on USB CDC");
}
