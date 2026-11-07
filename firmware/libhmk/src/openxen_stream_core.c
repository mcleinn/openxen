/*
 * openxen analog stream, hardware-independent core: frame ring and report packing.
 * Compiled into the firmware and into the host unit tests (tests/firmware_host/).
 * GPL-3.0-or-later.
 */
#include "openxen_stream.h"

#include <string.h>

#if defined(__arm__)
#define OXS_BARRIER() __asm volatile("dmb" ::: "memory")
#else
#define OXS_BARRIER() __atomic_thread_fence(__ATOMIC_SEQ_CST)
#endif

void oxs_ring_init(oxs_ring_t *ring) {
  memset(ring, 0, sizeof(*ring));
}

bool oxs_ring_push(oxs_ring_t *ring, uint32_t timestamp_us, const uint16_t *values, uint8_t num_keys) {
  const uint16_t seq = ring->next_sequence++;
  const uint32_t head = ring->head;
  if (head - ring->tail >= OXS_RING_SIZE) {
    ring->lost++;
    return false;
  }
  oxs_frame_t *f = &ring->frames[head % OXS_RING_SIZE];
  f->sequence = seq;
  f->timestamp_us = timestamp_us;
  if (num_keys > OXS_MAX_KEYS)
    num_keys = OXS_MAX_KEYS;
  memcpy(f->values, values, (size_t)num_keys * sizeof(uint16_t));
  OXS_BARRIER();                    /* frame contents visible before the index moves */
  ring->head = head + 1u;
  return true;
}

bool oxs_ring_pop_report(oxs_ring_t *ring, oxs_report_t *out, uint8_t num_keys, uint8_t flags,
                         uint8_t adc_bits, void (*get_cal)(uint8_t key, oxs_cal_t *cal)) {
  const uint32_t tail = ring->tail;
  if (ring->head == tail)
    return false;
  OXS_BARRIER();
  if (num_keys > OXS_MAX_KEYS)
    num_keys = OXS_MAX_KEYS;
  const oxs_frame_t *f = &ring->frames[tail % OXS_RING_SIZE];

  memset(out, 0, sizeof(*out));
  out->magic = OXS_MAGIC;
  out->version = (uint8_t)OXS_PROTOCOL_VERSION;
  out->flags = flags;
  out->sequence = f->sequence;
  /* frames lost since the previous report: the producer's lost counter, taken and reset */
  uint32_t lost = ring->lost;
  ring->lost = 0;                   /* benign race: a loss counted right now shows up as a sequence gap anyway */
  out->dropped = (uint16_t)(lost > 0xFFFFu ? 0xFFFFu : lost);
  out->timestamp_us = f->timestamp_us;
  out->num_keys = num_keys;
  out->adc_bits = adc_bits;
  memcpy(out->values, f->values, (size_t)num_keys * sizeof(uint16_t));
  if (num_keys > 0 && get_cal != NULL) {
    out->cal_first_key = ring->cal_cursor;
    for (uint8_t i = 0; i < OXS_CAL_PER_REPORT; i++)
      get_cal((uint8_t)((ring->cal_cursor + i) % num_keys), &out->cal[i]);
    ring->cal_cursor = (uint8_t)((ring->cal_cursor + OXS_CAL_PER_REPORT) % num_keys);
  }
  OXS_BARRIER();                    /* done reading the frame before releasing the slot */
  ring->tail = tail + 1u;
  return true;
}

void oxs_clock_init(oxs_clock_t *clk, uint32_t cycles_now, uint32_t cycles_per_us) {
  clk->last_cycles = cycles_now;
  clk->rem_cycles = 0;
  clk->us = 0;
  clk->cycles_per_us = cycles_per_us ? cycles_per_us : 1u;
}

uint32_t oxs_clock_update(oxs_clock_t *clk, uint32_t cycles_now) {
  uint32_t delta = cycles_now - clk->last_cycles;  /* modular: handles counter wrap */
  clk->last_cycles = cycles_now;
  delta += clk->rem_cycles;
  clk->us += delta / clk->cycles_per_us;
  clk->rem_cycles = delta % clk->cycles_per_us;
  return clk->us;
}
