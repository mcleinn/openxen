/*
 * openxen analog stream: one HID input report per complete key scan.
 * Protocol: docs/stream-protocol.md. GPL-3.0-or-later (openxen, built into libhmk).
 *
 * This header is shared by the firmware and the host-side unit tests; it has no
 * hardware dependencies.
 */
#pragma once

#include <stdbool.h>
#include <stdint.h>

#define OXS_PROTOCOL_VERSION 1u
#define OXS_MAGIC 0x584Fu           /* "OX" little endian: 'O' 'X' */
#define OXS_MAX_KEYS 56u
#define OXS_CAL_PER_REPORT 4u
#define OXS_RING_SIZE 8u            /* frames buffered between scan interrupt and USB */

/* flags */
#define OXS_FLAG_INVERTED 0x01u     /* values were inverted (ADC_MAX - raw) like libhmk's matrix */
#define OXS_FLAG_CALIBRATING 0x02u  /* libhmk is still in its start-up calibration */

typedef struct __attribute__((packed)) {
  uint16_t rest;                    /* libhmk adc_rest_value (same domain as values) */
  uint16_t bottom_out;              /* libhmk adc_bottom_out_value */
} oxs_cal_t;

typedef struct __attribute__((packed)) {
  uint16_t magic;                   /* OXS_MAGIC */
  uint8_t version;                  /* OXS_PROTOCOL_VERSION */
  uint8_t flags;                    /* OXS_FLAG_* */
  uint16_t sequence;                /* +1 per completed scan, wraps; gaps = lost scans */
  uint16_t dropped;                 /* scans lost in the firmware since the previous report (saturates) */
  uint32_t timestamp_us;            /* device time of the scan's end, microseconds, wraps after 71.6 min */
  uint8_t num_keys;                 /* keys carried in values[] */
  uint8_t cal_first_key;            /* cal[i] belongs to key cal_first_key + i (mod num_keys) */
  uint8_t adc_bits;                 /* ADC resolution, 12 on the AT32F405 */
  uint8_t led_status;               /* OXL_STATUS_* (openxen_led.h); 0 = no LED information */
  uint16_t values[OXS_MAX_KEYS];    /* per key, libhmk key order (Lumatone .ltn index) */
  oxs_cal_t cal[OXS_CAL_PER_REPORT];
} oxs_report_t;

_Static_assert(sizeof(oxs_report_t) == 144, "oxs_report_t layout changed: update docs/stream-protocol.md");
_Static_assert(__builtin_offsetof(oxs_report_t, values) == 16, "header must be 16 bytes");

/* One scan as captured in the scan interrupt. */
typedef struct {
  uint16_t sequence;
  uint32_t timestamp_us;
  uint16_t values[OXS_MAX_KEYS];
} oxs_frame_t;

/* Single-producer (scan interrupt) / single-consumer (main loop) frame ring. */
typedef struct {
  oxs_frame_t frames[OXS_RING_SIZE];
  volatile uint32_t head;           /* written by the producer only */
  volatile uint32_t tail;           /* written by the consumer only */
  volatile uint32_t lost;           /* frames the producer could not store (ring full) */
  uint16_t next_sequence;           /* producer side */
  uint8_t cal_cursor;               /* consumer side */
} oxs_ring_t;

void oxs_ring_init(oxs_ring_t *ring);

/* Producer: store one scan. Returns false (and counts it as lost) when the ring is full. */
bool oxs_ring_push(oxs_ring_t *ring, uint32_t timestamp_us, const uint16_t *values, uint8_t num_keys);

/* Consumer: build the next report from the oldest frame. Returns false when no frame is
 * pending. get_cal(key, &cal) supplies the calibration of one key. */
bool oxs_ring_pop_report(oxs_ring_t *ring, oxs_report_t *out, uint8_t num_keys, uint8_t flags,
                         uint8_t adc_bits, void (*get_cal)(uint8_t key, oxs_cal_t *cal));

/* Microsecond clock from a free-running cycle counter (e.g. DWT->CYCCNT). Call at least
 * once per counter wrap (every ~19 s at 216 MHz); every scan does. */
typedef struct {
  uint32_t last_cycles;
  uint32_t rem_cycles;
  uint32_t us;
  uint32_t cycles_per_us;
} oxs_clock_t;

void oxs_clock_init(oxs_clock_t *clk, uint32_t cycles_now, uint32_t cycles_per_us);
uint32_t oxs_clock_update(oxs_clock_t *clk, uint32_t cycles_now);
