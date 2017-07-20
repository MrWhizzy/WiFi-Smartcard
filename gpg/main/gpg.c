/* 
 * write some description, sometime
 */
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/event_groups.h"
#include "esp_system.h"
#include "esp_wifi.h"
#include "esp_event_loop.h"
#include "esp_log.h"
#include "esp_partition.h"
#include "nvs_flash.h"
#include "nvs.h"
#include "rom/uart.h"
#include "driver/gpio.h"

#include "lwip/err.h"
#include "lwip/sockets.h"
#include "lwip/sys.h"
#include "lwip/netdb.h"

#include "esp_vfs.h"
#include "esp_vfs_fat.h"

#include "netlist.h"
#include "libAPDU.h"

#define PORT 5511       // The default port of this protocol
#define PRINTAPDU       // If defined, APDU info is printed

// FreeRTOS event group to signal when we are connected & ready to make a request
static EventGroupHandle_t wifi_event_group;

/* The event group allows multiple bits for each event,
 * but we only care about one event - are we connected
 * to the AP with an IP? */
const int CONNECTED_BIT = BIT0;

// Handle of the wear levelling library instance
static wl_handle_t s_wl_handle = WL_INVALID_HANDLE;

// Mount path for the partition
const char *base_path = "/spiflash";

uint8_t toggle = 0;     // Toggle for Wi-Fi status LED
uint8_t proceed = 0;    // When the proceed button is pressed, proceed is set

void proceedHandle(void* arg) {
    proceed = 1;
}

void initGPIO() {
    gpio_set_direction(GPIO_NUM_25, GPIO_MODE_OUTPUT);      // Wi-Fi status LED
    gpio_set_direction(GPIO_NUM_26, GPIO_MODE_OUTPUT);      // Processing status LED

    gpio_set_direction(GPIO_NUM_16, GPIO_MODE_INPUT);       // Proceed button
    gpio_set_intr_type(GPIO_NUM_16, GPIO_INTR_POSEDGE);     // Interrupt on rising edge
    gpio_set_pull_mode(GPIO_NUM_16, GPIO_PULLDOWN_ONLY);    // Enable pull-down (spared a 10k resistor)
    gpio_install_isr_service(0);                            // Install GPIO interrupt service
    gpio_isr_handler_add(GPIO_NUM_16, proceedHandle, (void*) GPIO_NUM_16);   // Hook ISR handler
}

void initNVS() {
    esp_err_t err = nvs_flash_init();
    if (err == ESP_ERR_NVS_NO_FREE_PAGES) {
        // NVS partition was truncated and needs to be erased
        const esp_partition_t* nvs_partition = esp_partition_find_first(
                ESP_PARTITION_TYPE_DATA, ESP_PARTITION_SUBTYPE_DATA_NVS, NULL);
        assert(nvs_partition && "partition table must have an NVS partition");
        ESP_ERROR_CHECK(esp_partition_erase_range(nvs_partition, 0, nvs_partition->size));
        // Retry nvs_flash_init
        err = nvs_flash_init();
    }
    ESP_ERROR_CHECK(err);
}

uint8_t mountFS() {
    static const char *TAG = "mountFS";
    ESP_LOGI(TAG, "Mounting FAT filesystem");
    const esp_vfs_fat_mount_config_t mount_config = {   // Mount the filesystem
            .max_files = 4,
            .format_if_mount_failed = true
    };
    esp_err_t err = esp_vfs_fat_spiflash_mount(base_path, "storage", &mount_config, &s_wl_handle);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "Failed to mount FATFS (0x%x)", err);
        return 0;
    }
    return 1;
}

void unmountFS() {
    static const char *TAG = "unmountFS";
    ESP_LOGI(TAG, "Unmounting FAT filesystem");
    ESP_ERROR_CHECK(esp_vfs_fat_spiflash_unmount(base_path, s_wl_handle));
    ESP_LOGI(TAG, "Done");
}

static esp_err_t event_handler(void *ctx, system_event_t *event) {
    static const char *TAG = "event_handler";

    switch(event->event_id) {
    case SYSTEM_EVENT_STA_START:
        gpio_set_level(GPIO_NUM_26, toggle);    // Not connected to a network
        currNet = nextNet;
        ESP_LOGI(TAG, "Setting WiFi configuration SSID %s...", (*wifiConfig[currNet]).sta.ssid);
        ESP_ERROR_CHECK(esp_wifi_set_config(ESP_IF_WIFI_STA, wifiConfig[currNet]));
        nextNet = (nextNet + 1) % NUMOFNETS;
        ESP_ERROR_CHECK(esp_wifi_connect());
        break;
    case SYSTEM_EVENT_STA_GOT_IP:
        gpio_set_level(GPIO_NUM_26, 1);         // Connected to a network
        xEventGroupSetBits(wifi_event_group, CONNECTED_BIT);
        break;
    case SYSTEM_EVENT_STA_DISCONNECTED:
        xEventGroupClearBits(wifi_event_group, CONNECTED_BIT);
        toggle ^= 1;
        gpio_set_level(GPIO_NUM_26, toggle);    // Not connected to a network
        currNet = nextNet;
        ESP_LOGI(TAG, "Setting WiFi configuration SSID %s...", (*wifiConfig[nextNet]).sta.ssid);
        ESP_ERROR_CHECK(esp_wifi_set_config(ESP_IF_WIFI_STA, wifiConfig[nextNet]));
        nextNet = (nextNet + 1) % NUMOFNETS;
        ESP_ERROR_CHECK(esp_wifi_connect());
        break;
    default:
        break;
    }
    return ESP_OK;
}

static void initWiFi(void) {
    nextNet = 0;        // Attempt to connect to this network next

    tcpip_adapter_init();
    wifi_event_group = xEventGroupCreate();
    ESP_ERROR_CHECK(esp_event_loop_init(event_handler, NULL));

    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&cfg));
    ESP_ERROR_CHECK(esp_wifi_set_storage(WIFI_STORAGE_RAM));
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_start());
    esp_wifi_set_ps(WIFI_PS_NONE);
}

static void taskConnect(void *pvParameters) {
    static const char *TAG = "taskConnect";

    int sockfd, r;
    apdu_t comAPDU;
    outData output;
    char recvBuf[1024];
    struct sockaddr_in serv_addr;

    nvs_handle nvsHandle;       // Open NVS to check if the device has been initialized
    esp_err_t err = nvs_open("storage", NVS_READWRITE, &nvsHandle);
    if (err != ESP_OK) {
        goto exit;
    } else {
        uint8_t initialized = 0;
        err = nvs_get_u8(nvsHandle, "initialized", &initialized);
        nvs_close(nvsHandle);
        gpio_set_level(GPIO_NUM_25, 1);     // Initialize/restore start
        switch (err) {
            case ESP_OK:    // If it has already been initialized, restore the data
                if (restoreState() != 0) {
                    goto exit;
                }
                break;
            case ESP_ERR_NVS_NOT_FOUND:     // If not initialized, then initialize
                if (initialize() != 0) {
                    goto exit;
                }
                break;
            default :
                goto exit;
        }
        gpio_set_level(GPIO_NUM_25, 0);     // Initialize/restore end
    }

    while(1) {
        // Wait for the callback to set the CONNECTED_BIT in the event group.
        xEventGroupWaitBits(wifi_event_group, CONNECTED_BIT, false, true, portMAX_DELAY);
        ESP_LOGI(TAG, "Connected to AP");

        printf("Press the proceed button to connect to: %s\n", IP[currNet]);
        fflush(stdout);
        while (proceed == 0) {
            vTaskDelay(1000/portTICK_PERIOD_MS);
        }
        proceed = 0;

        serv_addr.sin_family = AF_INET;
        serv_addr.sin_port = htons(PORT);
        serv_addr.sin_addr.s_addr = inet_addr(IP[currNet]);

        sockfd = socket(AF_INET, SOCK_STREAM, 0);
        if (sockfd < 0) {
            ESP_LOGE(TAG, "... Failed to allocate socket");
            vTaskDelay(1000/portTICK_PERIOD_MS);
            continue;
        }
        ESP_LOGI(TAG, "... allocated socket\r\n");

        if (connect(sockfd, (struct sockaddr *)&serv_addr, sizeof(serv_addr)) != 0) {
            ESP_LOGE(TAG, "... socket connect failed errno: %d", errno);
            close(sockfd);
            vTaskDelay(1000/portTICK_PERIOD_MS);
            goto exit;
        }
        ESP_LOGI(TAG, "... connected");

        while(1) {
            bzero(recvBuf, sizeof(recvBuf));                // Zero the receive buffer
            r = read(sockfd, recvBuf, sizeof(recvBuf)-1);   // Receive the APDU command
            comAPDU = parseAPDU(recvBuf, r);                // Parse the APDE command

#ifdef PRINTAPDU
            printf("CLA: %02X\tINS: %02X\tP1: %02X\t", comAPDU.CLA, comAPDU.INS, comAPDU.P1);
            printf("P2: %02X\tP1P2: %02X\tLc: %02X\tData: ", comAPDU.P2, comAPDU.P1P2, comAPDU.Lc);
            const uint8_t* tmp = comAPDU.data;
            while(*tmp)
                printf("%02X ", (unsigned int) *tmp++);
            printf("\nLe: %02X\tTotal: %d\n", comAPDU.Le, r);
            fflush(stdout);
#endif

            gpio_set_level(GPIO_NUM_25, 1);     // Start processing a command
            process(comAPDU, &output);          // Perform the appropriate operation
            gpio_set_level(GPIO_NUM_25, 0);     // End of command processing

#ifdef PRINTAPDU
            printf("Output Data: ");
            const uint8_t* tmp2 = output.data;
            while(*tmp2)
                printf("%02X ", (unsigned int) *tmp2++);
            printf("\nLength: %d\n", output.length);
            fflush(stdout);
#endif

            if (write(sockfd, output.data, output.length) < 0) {    // Send the response
                ESP_LOGE(TAG, "... socket send failed");
                close(sockfd);
                vTaskDelay(1000/portTICK_PERIOD_MS);
                goto exit;
            }
            ESP_LOGI(TAG, "... socket send success");
        }
    }

exit:
        for (int countdown = 3; countdown > 0; countdown--) {
            ESP_LOGI(TAG, "Restart in: %d... ", countdown);
            vTaskDelay(1000/portTICK_PERIOD_MS);
        }
        ESP_LOGI(TAG, "Starting again");
        unmountFS();
        esp_restart();
}

void app_main() {
    initGPIO();
    initNVS();
    if (!mountFS()) {
        exit(0);
    }
    initWiFi();
    xTaskCreate(&taskConnect, "taskConnect", 8192, NULL, 5, NULL);
}