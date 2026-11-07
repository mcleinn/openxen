/*
 * openxen LEDs, firmware glue: IS31FL3733 on I2C1 (PB6 SCL, PB7 SDA, alternate function 4),
 * shutdown pin PC0 (SDB, high = on). Register writes come from the core (openxen_led_core.c)
 * and are sent by a non-blocking state machine: the main loop feeds one byte whenever the
 * I2C peripheral is ready, so LED traffic never stalls key scanning or USB.
 * GPL-3.0-or-later.
 */
#include "openxen_led.h"

#include "hardware/hardware.h"
#include "matrix.h"
#include "openxen_led_map.h"

#include "at32f402_405.h"

/* 7-bit address 0x50 (ADDR1 = ADDR2 = GND), as the 8-bit write address the AT32 expects */
#define IS31_ADDR_W 0xA0u
/* I2C1 kernel clock = PCLK1 = 108 MHz (APB1 = SYSCLK / 2). DIVL 9 -> 92.6 ns ticks;
 * SCLL 16+1 = 1.57 us, SCLH 9+1 = 0.93 us, SDADEL 2, SCLDEL 4 -> ~385 kHz (Fast-mode). */
#define I2C_TIMING 0x90420910u
#define COMPOSE_INTERVAL_MS 2u
#define TRANSFER_TIMEOUT_MS 5u
#define ERROR_BACKOFF_MS 50u

static oxl_t st;
static const oxl_map_t key_map[OXL_KEYS] = OXL_KEY_MAP_INIT;

static enum { I2C_IDLE, I2C_SENDING } i2c_state;
static uint8_t tx[OXL_MAX_WRITE + 1];
static uint8_t tx_len, tx_pos;
static uint32_t tx_started_ms, last_compose_ms, backoff_until_ms;
static bool i2c_error_flag;

static void i2c_hw_init(void) {
  crm_periph_clock_enable(CRM_GPIOB_PERIPH_CLOCK, TRUE);
  crm_periph_clock_enable(CRM_GPIOC_PERIPH_CLOCK, TRUE);
  crm_periph_clock_enable(CRM_I2C1_PERIPH_CLOCK, TRUE);

  gpio_init_type g;
  gpio_default_para_init(&g);
  g.gpio_pins = GPIO_PINS_6 | GPIO_PINS_7;
  g.gpio_mode = GPIO_MODE_MUX;
  g.gpio_out_type = GPIO_OUTPUT_OPEN_DRAIN;  /* 2 k pull-ups on the board */
  g.gpio_pull = GPIO_PULL_NONE;
  g.gpio_drive_strength = GPIO_DRIVE_STRENGTH_STRONGER;
  gpio_init(GPIOB, &g);
  gpio_pin_mux_config(GPIOB, GPIO_PINS_SOURCE6, GPIO_MUX_4);
  gpio_pin_mux_config(GPIOB, GPIO_PINS_SOURCE7, GPIO_MUX_4);

  /* SDB (PC0): drive high to take the driver out of shutdown */
  gpio_default_para_init(&g);
  g.gpio_pins = GPIO_PINS_0;
  g.gpio_mode = GPIO_MODE_OUTPUT;
  g.gpio_out_type = GPIO_OUTPUT_PUSH_PULL;
  g.gpio_pull = GPIO_PULL_NONE;
  gpio_init(GPIOC, &g);
  gpio_bits_set(GPIOC, GPIO_PINS_0);

  i2c_init(I2C1, 0x0F, I2C_TIMING);
  i2c_enable(I2C1, TRUE);
}

static void i2c_restart(void) {
  i2c_enable(I2C1, FALSE);
  i2c_enable(I2C1, TRUE);
}

void openxen_led_init(void) {
  oxl_init(&st, key_map);
  i2c_hw_init();
  i2c_state = I2C_IDLE;
}

void openxen_led_report(const uint8_t *buf, uint16_t len) {
  oxl_handle_report(&st, buf, len, timer_read());
}

uint8_t openxen_led_status(void) {
  uint8_t s = oxl_status(&st, timer_read());
  if (i2c_error_flag) {
    s |= OXL_STATUS_I2C_ERROR;
    i2c_error_flag = false;
  }
  return s;
}

static void fail(uint32_t now) {
  i2c_flag_clear(I2C1, I2C_ACKFAIL_FLAG | I2C_BUSERR_FLAG | I2C_ARLOST_FLAG | I2C_STOPF_FLAG);
  i2c_restart();
  oxl_i2c_failed(&st);
  i2c_error_flag = true;
  backoff_until_ms = now + ERROR_BACKOFF_MS;
  i2c_state = I2C_IDLE;
}

void openxen_led_task(void) {
  const uint32_t now = timer_read();

  if (i2c_state == I2C_SENDING) {
    if (i2c_flag_get(I2C1, I2C_ACKFAIL_FLAG) || i2c_flag_get(I2C1, I2C_BUSERR_FLAG) ||
        i2c_flag_get(I2C1, I2C_ARLOST_FLAG) || (uint32_t)(now - tx_started_ms) > TRANSFER_TIMEOUT_MS) {
      fail(now);
      return;
    }
    if (tx_pos < tx_len && i2c_flag_get(I2C1, I2C_TDIS_FLAG)) {
      i2c_data_send(I2C1, tx[tx_pos++]);
      return;
    }
    if (i2c_flag_get(I2C1, I2C_STOPF_FLAG)) {
      i2c_flag_clear(I2C1, I2C_STOPF_FLAG);
      i2c_state = I2C_IDLE;
    }
    return;
  }

  if ((int32_t)(now - backoff_until_ms) < 0)
    return;
  if ((uint32_t)(now - last_compose_ms) >= COMPOSE_INTERVAL_MS) {
    uint8_t pressed[(OXL_KEYS + 7u) / 8u] = {0};
    for (uint8_t k = 0; k < OXL_KEYS && k < NUM_KEYS; k++)
      if (key_matrix[k].is_pressed)
        pressed[k / 8u] |= (uint8_t)(1u << (k % 8u));
    oxl_compose(&st, key_map, pressed, now);
    last_compose_ms = now;
  }
  oxl_write_t w;
  if (i2c_flag_get(I2C1, I2C_BUSYF_FLAG) || !oxl_next_write(&st, &w))
    return;
  tx[0] = w.reg;
  for (uint8_t i = 0; i < w.len; i++)
    tx[1u + i] = w.data[i];
  tx_len = (uint8_t)(w.len + 1u);
  tx_pos = 0;
  tx_started_ms = now;
  i2c_state = I2C_SENDING;
  i2c_transmit_set(I2C1, IS31_ADDR_W, tx_len, I2C_AUTO_STOP_MODE, I2C_GEN_START_WRITE);
}
