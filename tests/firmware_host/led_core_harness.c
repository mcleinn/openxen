/*
 * Host harness for firmware/libhmk/src/openxen_led_core.c (compiled with zig cc by
 * tests/test_led.py). Reads commands on stdin, one per line:
 *   cmd <ms> <hex>       host output report (oxl_handle_report); prints "ACK 0|-1"
 *   press <hex7>         pressed-key bitmap (7 bytes, bit k = key k)
 *   step <ms>            compose and drain all register writes; prints
 *                        "W <reg hex> <data hex>" per write, then "GCC <n>" and "END"
 *   write1 <ms>          compose and emit at most one write (for ordering tests)
 *   fail                 oxl_i2c_failed()
 *   status <ms>          prints "STATUS <n>"
 */
#include "openxen_led_map.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static oxl_t st;
static const oxl_map_t map[OXL_KEYS] = OXL_KEY_MAP_INIT;
static uint8_t pressed[(OXL_KEYS + 7u) / 8u];

static int hexbytes(const char *h, uint8_t *out, int max) {
  int n = 0;
  while (h[0] && h[1] && n < max) {
    unsigned v;
    if (sscanf(h, "%2x", &v) != 1)
      break;
    out[n++] = (uint8_t)v;
    h += 2;
  }
  return n;
}

static void emit(const oxl_write_t *w) {
  printf("W %02x ", w->reg);
  for (uint8_t i = 0; i < w->len; i++)
    printf("%02x", w->data[i]);
  printf("\n");
}

int main(void) {
  oxl_init(&st, map);
  char line[512], hex[400];
  unsigned long ms;
  while (fgets(line, sizeof line, stdin)) {
    if (sscanf(line, "cmd %lu %399s", &ms, hex) == 2) {
      uint8_t buf[OXL_REPORT_SIZE] = {0};
      int n = hexbytes(hex, buf, (int)sizeof buf);
      printf("ACK %d\n", oxl_handle_report(&st, buf, (uint16_t)n, (uint32_t)ms));
    } else if (sscanf(line, "press %399s", hex) == 1) {
      memset(pressed, 0, sizeof pressed);
      hexbytes(hex, pressed, (int)sizeof pressed);
    } else if (sscanf(line, "step %lu", &ms) == 1) {
      oxl_compose(&st, map, pressed, (uint32_t)ms);
      oxl_write_t w;
      int guard = 0;
      while (oxl_next_write(&st, &w) && guard++ < 1000)
        emit(&w);
      printf("GCC %u\nEND\n", st.gcc);
    } else if (sscanf(line, "write1 %lu", &ms) == 1) {
      oxl_compose(&st, map, pressed, (uint32_t)ms);
      oxl_write_t w;
      if (oxl_next_write(&st, &w))
        emit(&w);
      printf("END\n");
    } else if (strncmp(line, "fail", 4) == 0) {
      oxl_i2c_failed(&st);
    } else if (sscanf(line, "status %lu", &ms) == 1) {
      printf("STATUS %u\n", oxl_status(&st, (uint32_t)ms));
    }
    fflush(stdout);
  }
  return 0;
}
