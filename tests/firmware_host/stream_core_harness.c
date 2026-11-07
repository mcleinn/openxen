/*
 * Host harness for firmware/libhmk/src/openxen_stream_core.c (compiled with zig cc by
 * tests/test_stream_protocol.py). Runs scenarios and prints every packed report as one hex
 * line; the Python side decodes them with host/oxs.py and checks the results.
 *
 *   harness basic     14 scans pushed and popped one by one (one full calibration rotation)
 *   harness overflow  12 scans pushed before any pop (ring of 8: 4 lost), then 3 more
 *   harness clock     microsecond clock across a 32-bit cycle counter wrap
 */
#include "openxen_stream.h"

#include <stdio.h>
#include <string.h>

#define NKEYS 56

static void get_cal(uint8_t key, oxs_cal_t *cal) {
  cal->rest = (uint16_t)(1000 + key);
  cal->bottom_out = (uint16_t)(3000 + key);
}

static void emit(const oxs_report_t *r) {
  const uint8_t *b = (const uint8_t *)r;
  for (size_t i = 0; i < sizeof(*r); i++)
    printf("%02x", b[i]);
  printf("\n");
}

static void scan_values(uint16_t *v, uint32_t scan) {
  for (int k = 0; k < NKEYS; k++)
    v[k] = (uint16_t)((scan * 100u + (uint32_t)k) & 0x0FFFu);   /* 12-bit pattern */
}

int main(int argc, char **argv) {
  static oxs_ring_t ring;
  oxs_report_t rep;
  uint16_t v[NKEYS];
  const char *mode = argc > 1 ? argv[1] : "basic";
  oxs_ring_init(&ring);

  if (strcmp(mode, "basic") == 0) {
    for (uint32_t s = 0; s < 14; s++) {
      scan_values(v, s);
      if (!oxs_ring_push(&ring, 1000u + s * 250u, v, NKEYS))
        return 2;
      if (!oxs_ring_pop_report(&ring, &rep, NKEYS, OXS_FLAG_INVERTED, 12, get_cal))
        return 3;
      emit(&rep);
    }
    if (oxs_ring_pop_report(&ring, &rep, NKEYS, 0, 12, get_cal))
      return 4;                                     /* nothing left */
  } else if (strcmp(mode, "overflow") == 0) {
    uint32_t s = 0;
    for (; s < 12; s++) {
      scan_values(v, s);
      oxs_ring_push(&ring, 0xFFFFF000u + s * 250u, v, NKEYS);   /* also wraps the time */
    }
    while (oxs_ring_pop_report(&ring, &rep, NKEYS, 0, 12, get_cal))
      emit(&rep);
    for (; s < 15; s++) {
      scan_values(v, s);
      oxs_ring_push(&ring, 0xFFFFF000u + s * 250u, v, NKEYS);
      if (oxs_ring_pop_report(&ring, &rep, NKEYS, 0, 12, get_cal))
        emit(&rep);
    }
  } else if (strcmp(mode, "clock") == 0) {
    oxs_clock_t c;
    const uint32_t cpu = 216u;                     /* cycles per microsecond at 216 MHz */
    uint32_t cyc = 0xFFFFFFFFu - 216u * 500u;      /* 500 us before the counter wraps */
    oxs_clock_init(&c, cyc, cpu);
    for (int i = 0; i < 6; i++) {
      cyc += 216u * 250u + 7u;                     /* 250 us + 7 cycles per scan */
      printf("%u\n", oxs_clock_update(&c, cyc));
    }
  } else {
    return 1;
  }
  return 0;
}
