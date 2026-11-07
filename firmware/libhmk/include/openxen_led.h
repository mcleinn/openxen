/*
 * openxen LEDs: IS31FL3733 matrix driver, host commands, power budget.
 * Protocol: docs/led-protocol.md. GPL-3.0-or-later.
 *
 * Hardware-independent core (openxen_led_core.c, unit-tested on the PC): parses host
 * commands, composes the 192 PWM registers from host colours + press highlight with gamma,
 * computes the global current (GCC) from the power budget, and emits the minimal sequence
 * of register writes (with the chip's page-lock protocol) to bring the chip up to date.
 */
#pragma once

#include <stdbool.h>
#include <stdint.h>

#define OXL_KEYS 56u
#define OXL_PWM_REGS 192u          /* 12 SW x 16 CS */
#define OXL_ONOFF_REGS 24u
#define OXL_REPORT_SIZE 64u
#define OXL_PIXELS_PER_REPORT 20u
#define OXL_MAX_WRITE 16u          /* data bytes per I2C transaction (plus register byte) */

/* host commands (byte 0 of a 64-byte output report) */
#define OXL_CMD_PIXELS 0x10u
#define OXL_CMD_CONFIG 0x11u
#define OXL_CMD_KEEPALIVE 0x12u
#define OXL_PIXELS_SHOW 0x01u      /* flags bit: apply the staged frame */

/* highlight modes */
#define OXL_HL_OFF 0u
#define OXL_HL_REPLACE 1u

/* electrical model (REXT 20k: I_OUT = 840 / REXT * GCC / 256 -> 42 mA peak at GCC 255;
 * 1/12 scan duty; PWM duty p / 256). Average per channel = 3.5 mA * GCC/255 * PWM/256. */
#define OXL_CH_MA_X1000 3500u      /* uA per channel at GCC 255, PWM 256 */
#define OXL_BUDGET_DEFAULT_MA 100u /* until the host raises it (fits a 500 mA port with the sensors) */
#define OXL_BUDGET_MAX_MA 600u     /* hard ceiling: full white is ~590 mA */
#define OXL_TIMEOUT_DEFAULT_MS 2000u

/* status bits (reported in the analog stream report, byte 15) */
#define OXL_STATUS_HOST 0x01u      /* host has sent commands and has not timed out */
#define OXL_STATUS_TIMEOUT 0x02u   /* host stopped: LEDs in fallback (off) */
#define OXL_STATUS_I2C_ERROR 0x04u /* an I2C transfer failed since the last report */

/* IS31FL3733 registers */
#define OXL_REG_UNLOCK 0xFEu
#define OXL_UNLOCK_KEY 0xC5u
#define OXL_REG_PAGE 0xFDu
#define OXL_PAGE_ONOFF 0u
#define OXL_PAGE_PWM 1u
#define OXL_PAGE_FUNC 3u
#define OXL_FUNC_CONFIG 0x00u
#define OXL_FUNC_GCC 0x01u
#define OXL_FUNC_PULLUP 0x0Fu
#define OXL_FUNC_PULLDOWN 0x10u
#define OXL_CONFIG_NORMAL 0x01u    /* SSD = 1 normal operation, no breath, SYNC high-Z */
#define OXL_PULL_DEGHOST 0x07u     /* 32 kOhm SWy pull-up / CSx pull-down during tNOL (bench-tunable) */

/* key -> driver lines, 0-based (CS 0..15, SW 0..11; R, G, B cathodes) */
typedef struct {
  uint8_t cs;
  uint8_t sw[3];
} oxl_map_t;

static inline uint8_t oxl_pwm_reg(uint8_t sw, uint8_t cs) { return (uint8_t)(sw * 16u + cs); }

typedef struct {
  uint8_t reg;
  uint8_t len;                     /* data bytes */
  uint8_t data[OXL_MAX_WRITE];
} oxl_write_t;

typedef struct {
  /* host state */
  uint8_t staged[OXL_KEYS][3];
  uint8_t shown[OXL_KEYS][3];
  uint8_t brightness;
  uint8_t hl_mode;
  uint8_t hl_rgb[3];
  uint16_t timeout_ms;
  uint16_t budget_ma;
  uint32_t last_host_ms;
  bool host_seen;
  bool timed_out;
  uint16_t bad_commands;
  /* desired chip state */
  uint8_t pwm[OXL_PWM_REGS];
  uint8_t gcc;
  uint8_t onoff[OXL_ONOFF_REGS];
  /* what the chip holds */
  uint8_t hw_pwm[OXL_PWM_REGS];
  uint8_t hw_gcc;
  uint8_t hw_page;                 /* 0xFF = unknown */
  uint8_t init_step;               /* 0 = needs (re)initialisation, 0xFF = done */
  bool pending_page_reg;           /* next write must be the page register (after unlock) */
  uint8_t pending_page;
} oxl_t;

void oxl_init(oxl_t *s, const oxl_map_t *map);

/* A 64-byte output report from the host. Returns 0 when accepted, -1 when rejected. */
int oxl_handle_report(oxl_t *s, const uint8_t *buf, uint16_t len, uint32_t now_ms);

/* Recompute the desired PWM/GCC from host colours, highlight (pressed bitmap, bit k = key k)
 * and timeout. */
void oxl_compose(oxl_t *s, const oxl_map_t *map, const uint8_t pressed[(OXL_KEYS + 7u) / 8u], uint32_t now_ms);

/* Next register write needed to bring the chip up to date (handles initialisation and the
 * page-lock protocol). Returns false when the chip is up to date. The write is considered
 * done once returned; call oxl_i2c_failed() if it could not be sent. */
bool oxl_next_write(oxl_t *s, oxl_write_t *w);

/* An I2C transfer failed: forget what the chip holds and re-initialise it. */
void oxl_i2c_failed(oxl_t *s);

uint8_t oxl_status(const oxl_t *s, uint32_t now_ms);

/* Estimated LED supply current (mA) for a PWM image at a given GCC. */
uint32_t oxl_estimate_ma(const uint8_t *pwm, uint8_t gcc);

/* gamma 2.2, 8 bit -> 8 bit */
extern const uint8_t oxl_gamma[256];

/* firmware entry points (openxen_led.c) */
void openxen_led_init(void);
void openxen_led_task(void);
void openxen_led_report(const uint8_t *buf, uint16_t len);
uint8_t openxen_led_status(void);
