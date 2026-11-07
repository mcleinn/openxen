/*
 * openxen analog stream, firmware glue (AT32F405 / libhmk / TinyUSB).
 * The scan interrupt captures every completed scan with a microsecond timestamp; the main
 * loop sends one HID input report per scan on the stream interface (USB_ITF_STREAM).
 * GPL-3.0-or-later.
 */
#include "openxen_stream.h"

#include "hardware/hardware.h"
#include "matrix.h"
#include "tusb.h"
#include "device/usbd_pvt.h"
#include "usb_descriptors.h"

static oxs_ring_t ring;
static oxs_clock_t clock_us;
static volatile bool stream_ready;
/* transfer buffer: must stay untouched until the IN transfer completes (busy check) */
static oxs_report_t report __attribute__((aligned(4)));

void openxen_stream_init(void) {
  /* time base: the DWT cycle counter, enabled by libhmk's board_init() */
  oxs_ring_init(&ring);
  oxs_clock_init(&clock_us, board_cycle_count(), (uint32_t)(F_CPU / 1000000u));
  stream_ready = true;
}

/* Called by the analog driver (DMA interrupt) after the last mux channel of a scan. */
void analog_scan_complete_cb(void) {
  if (!stream_ready)
    return;
  const uint32_t now = oxs_clock_update(&clock_us, board_cycle_count());
  uint16_t values[NUM_KEYS];
  for (uint8_t i = 0; i < NUM_KEYS; i++) {
#if defined(MATRIX_INVERT_ADC_VALUES)
    values[i] = (uint16_t)(ADC_MAX_VALUE - analog_read(i));
#else
    values[i] = analog_read(i);
#endif
  }
  oxs_ring_push(&ring, now, values, (uint8_t)NUM_KEYS);
}

static void get_cal(uint8_t key, oxs_cal_t *cal) {
  cal->rest = key_matrix[key].adc_rest_value;
  cal->bottom_out = key_matrix[key].adc_bottom_out_value;
}

void openxen_stream_task(void) {
  /* The report (144 B) is larger than TinyUSB's shared HID buffer (64 B, which libhmk's raw
   * HID needs), so it goes out from our own buffer on the HID interface's IN endpoint.
   * TinyUSB releases the endpoint claim when the transfer completes. */
  if (!tud_mounted() || tud_suspended() || usbd_edpt_busy(BOARD_TUD_RHPORT, EP_IN_ADDR_STREAM))
    return;
  uint8_t flags = 0;
#if defined(MATRIX_INVERT_ADC_VALUES)
  flags |= OXS_FLAG_INVERTED;
#endif
  if (!usbd_edpt_claim(BOARD_TUD_RHPORT, EP_IN_ADDR_STREAM))
    return;
  if (!oxs_ring_pop_report(&ring, &report, (uint8_t)NUM_KEYS, flags, (uint8_t)ADC_RESOLUTION, get_cal)) {
    usbd_edpt_release(BOARD_TUD_RHPORT, EP_IN_ADDR_STREAM);
    return;
  }
  if (!usbd_edpt_xfer(BOARD_TUD_RHPORT, EP_IN_ADDR_STREAM, (uint8_t *)&report, (uint16_t)sizeof(report)))
    usbd_edpt_release(BOARD_TUD_RHPORT, EP_IN_ADDR_STREAM);
}
