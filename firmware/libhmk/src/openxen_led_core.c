/*
 * openxen LEDs, hardware-independent core (see openxen_led.h). Compiled into the firmware
 * and into the host tests (tests/firmware_host/led_core_harness.c). GPL-3.0-or-later.
 */
#include "openxen_led.h"

#include <string.h>

/* gamma 2.2 (non-zero inputs map to at least 1 so dim colours stay visible) */
const uint8_t oxl_gamma[256] = {
      0,   1,   1,   1,   1,   1,   1,   1,   1,   1,   1,   1,   1,   1,   1,   1,
      1,   1,   1,   1,   1,   1,   1,   1,   1,   2,   2,   2,   2,   2,   2,   2,
      3,   3,   3,   3,   3,   4,   4,   4,   4,   5,   5,   5,   5,   6,   6,   6,
      6,   7,   7,   7,   8,   8,   8,   9,   9,   9,  10,  10,  11,  11,  11,  12,
     12,  13,  13,  13,  14,  14,  15,  15,  16,  16,  17,  17,  18,  18,  19,  19,
     20,  20,  21,  22,  22,  23,  23,  24,  25,  25,  26,  26,  27,  28,  28,  29,
     30,  30,  31,  32,  33,  33,  34,  35,  35,  36,  37,  38,  39,  39,  40,  41,
     42,  43,  43,  44,  45,  46,  47,  48,  49,  49,  50,  51,  52,  53,  54,  55,
     56,  57,  58,  59,  60,  61,  62,  63,  64,  65,  66,  67,  68,  69,  70,  71,
     73,  74,  75,  76,  77,  78,  79,  81,  82,  83,  84,  85,  87,  88,  89,  90,
     91,  93,  94,  95,  97,  98,  99, 100, 102, 103, 105, 106, 107, 109, 110, 111,
    113, 114, 116, 117, 119, 120, 121, 123, 124, 126, 127, 129, 130, 132, 133, 135,
    137, 138, 140, 141, 143, 145, 146, 148, 149, 151, 153, 154, 156, 158, 159, 161,
    163, 165, 166, 168, 170, 172, 173, 175, 177, 179, 181, 182, 184, 186, 188, 190,
    192, 194, 196, 197, 199, 201, 203, 205, 207, 209, 211, 213, 215, 217, 219, 221,
    223, 225, 227, 229, 231, 234, 236, 238, 240, 242, 244, 246, 248, 251, 253, 255};

#define DONE 0xFFu
#define PAGE_UNKNOWN 0xFFu

void oxl_init(oxl_t *s, const oxl_map_t *map) {
  memset(s, 0, sizeof(*s));
  s->brightness = 255;
  s->hl_mode = OXL_HL_OFF;
  s->hl_rgb[0] = s->hl_rgb[1] = s->hl_rgb[2] = 255;
  s->timeout_ms = OXL_TIMEOUT_DEFAULT_MS;
  s->budget_ma = OXL_BUDGET_DEFAULT_MA;
  s->hw_page = PAGE_UNKNOWN;
  s->init_step = 0;
  /* enable exactly the channels that have an LED */
  for (uint8_t k = 0; k < OXL_KEYS; k++)
    for (uint8_t c = 0; c < 3; c++) {
      const uint8_t sw = map[k].sw[c], cs = map[k].cs;
      s->onoff[sw * 2u + cs / 8u] |= (uint8_t)(1u << (cs % 8u));
    }
}

static uint16_t u16le(const uint8_t *b) { return (uint16_t)(b[0] | (b[1] << 8)); }

int oxl_handle_report(oxl_t *s, const uint8_t *buf, uint16_t len, uint32_t now_ms) {
  if (len < 1)
    return -1;
  switch (buf[0]) {
  case OXL_CMD_PIXELS: {
    if (len < 4)
      goto bad;
    const uint8_t flags = buf[1], first = buf[2], count = buf[3];
    if (count > OXL_PIXELS_PER_REPORT || first >= OXL_KEYS || (uint16_t)first + count > OXL_KEYS ||
        4u + 3u * count > len)
      goto bad;
    memcpy(s->staged[first], &buf[4], 3u * count);
    if (flags & OXL_PIXELS_SHOW)
      memcpy(s->shown, s->staged, sizeof(s->shown));
    break;
  }
  case OXL_CMD_CONFIG: {
    if (len < 10 || buf[2] > OXL_HL_REPLACE)
      goto bad;
    s->brightness = buf[1];
    s->hl_mode = buf[2];
    memcpy(s->hl_rgb, &buf[3], 3);
    s->timeout_ms = u16le(&buf[6]);
    const uint16_t budget = u16le(&buf[8]);
    s->budget_ma = budget > OXL_BUDGET_MAX_MA ? OXL_BUDGET_MAX_MA : budget;
    break;
  }
  case OXL_CMD_KEEPALIVE:
    break;
  default:
    goto bad;
  }
  s->last_host_ms = now_ms;
  s->host_seen = true;
  s->timed_out = false;
  return 0;
bad:
  if (s->bad_commands < 0xFFFFu)
    s->bad_commands++;
  return -1;
}

uint32_t oxl_estimate_ma(const uint8_t *pwm, uint8_t gcc) {
  uint32_t sum = 0;
  for (uint32_t i = 0; i < OXL_PWM_REGS; i++)
    sum += pwm[i];
  return (uint32_t)(((uint64_t)OXL_CH_MA_X1000 * gcc * sum) / (255u * 256u * 1000u));
}

void oxl_compose(oxl_t *s, const oxl_map_t *map, const uint8_t pressed[(OXL_KEYS + 7u) / 8u], uint32_t now_ms) {
  if (s->host_seen && s->timeout_ms && (uint32_t)(now_ms - s->last_host_ms) > s->timeout_ms)
    s->timed_out = true;
  const bool active = s->host_seen && !s->timed_out;
  memset(s->pwm, 0, sizeof(s->pwm));
  uint32_t sum = 0;
  if (active) {
    for (uint8_t k = 0; k < OXL_KEYS; k++) {
      const uint8_t *rgb = s->shown[k];
      if (s->hl_mode == OXL_HL_REPLACE && pressed && (pressed[k / 8u] & (1u << (k % 8u))))
        rgb = s->hl_rgb;
      for (uint8_t c = 0; c < 3; c++) {
        const uint8_t v = oxl_gamma[rgb[c]];
        s->pwm[oxl_pwm_reg(map[k].sw[c], map[k].cs)] = v;
        sum += v;
      }
    }
  }
  uint32_t gcc = active ? s->brightness : 0u;
  if (sum > 0) {
    /* 3500 uA * gcc/255 * sum/256 <= budget -> gcc <= budget * 1000 * 255 * 256 / (3500 * sum) */
    const uint64_t cap = ((uint64_t)s->budget_ma * 1000u * 255u * 256u) / ((uint64_t)OXL_CH_MA_X1000 * sum);
    if (cap < gcc)
      gcc = (uint32_t)cap;
  }
  s->gcc = (uint8_t)gcc;
}

/* Emit the unlock / page-select pair needed before writing `page`. */
static bool select_page(oxl_t *s, uint8_t page, oxl_write_t *w) {
  if (s->hw_page == page && !s->pending_page_reg)
    return false;
  if (!s->pending_page_reg) {
    w->reg = OXL_REG_UNLOCK;
    w->len = 1;
    w->data[0] = OXL_UNLOCK_KEY;
    s->pending_page_reg = true;
    return true;
  }
  w->reg = OXL_REG_PAGE;
  w->len = 1;
  w->data[0] = page;
  s->pending_page_reg = false;
  s->hw_page = page;
  return true;
}

static void reg_write(oxl_write_t *w, uint8_t reg, const uint8_t *data, uint8_t len) {
  w->reg = reg;
  w->len = len;
  memcpy(w->data, data, len);
}

/* PWM run starting at the first difference: up to 16 bytes, ending at the last difference */
static bool pwm_diff(oxl_t *s, oxl_write_t *w) {
  uint32_t i = 0;
  while (i < OXL_PWM_REGS && s->pwm[i] == s->hw_pwm[i])
    i++;
  if (i == OXL_PWM_REGS)
    return false;
  uint32_t end = i + 1;
  for (uint32_t j = i; j < OXL_PWM_REGS && j < i + OXL_MAX_WRITE; j++)
    if (s->pwm[j] != s->hw_pwm[j])
      end = j + 1;
  if (select_page(s, OXL_PAGE_PWM, w))
    return true;
  reg_write(w, (uint8_t)i, &s->pwm[i], (uint8_t)(end - i));
  memcpy(&s->hw_pwm[i], &s->pwm[i], end - i);
  return true;
}

static bool gcc_diff(oxl_t *s, oxl_write_t *w) {
  if (s->gcc == s->hw_gcc)
    return false;
  if (select_page(s, OXL_PAGE_FUNC, w))
    return true;
  reg_write(w, OXL_FUNC_GCC, &s->gcc, 1);
  s->hw_gcc = s->gcc;
  return true;
}

bool oxl_next_write(oxl_t *s, oxl_write_t *w) {
  if (s->init_step != DONE) {
    /* 0..3: function page; 4..5: on/off page; 6..17: PWM page (all 192 registers) */
    const uint8_t step = s->init_step;
    if (step <= 3) {
      if (select_page(s, OXL_PAGE_FUNC, w))
        return true;
      static const uint8_t regs[4] = {OXL_FUNC_CONFIG, OXL_FUNC_GCC, OXL_FUNC_PULLUP, OXL_FUNC_PULLDOWN};
      const uint8_t vals[4] = {OXL_CONFIG_NORMAL, 0u, OXL_PULL_DEGHOST, OXL_PULL_DEGHOST};
      reg_write(w, regs[step], &vals[step], 1);
      if (step == 1)
        s->hw_gcc = 0;
    } else if (step <= 5) {
      if (select_page(s, OXL_PAGE_ONOFF, w))
        return true;
      const uint8_t first = step == 4 ? 0u : 16u;
      reg_write(w, first, &s->onoff[first], step == 4 ? 16u : 8u);
    } else {
      if (select_page(s, OXL_PAGE_PWM, w))
        return true;
      const uint8_t first = (uint8_t)((step - 6u) * 16u);
      reg_write(w, first, &s->pwm[first], 16);
      memcpy(&s->hw_pwm[first], &s->pwm[first], 16);
    }
    s->init_step = (uint8_t)(step == 17u ? DONE : (uint8_t)(step + 1u));
    return true;
  }
  /* never exceed the budget in between: lower the current before raising PWM, raise it after */
  if (s->gcc < s->hw_gcc)
    return gcc_diff(s, w);
  if (pwm_diff(s, w))
    return true;
  return gcc_diff(s, w);
}

void oxl_i2c_failed(oxl_t *s) {
  s->init_step = 0;
  s->hw_page = PAGE_UNKNOWN;
  s->pending_page_reg = false;
}

uint8_t oxl_status(const oxl_t *s, uint32_t now_ms) {
  (void)now_ms;
  uint8_t st = 0;
  if (s->host_seen && !s->timed_out)
    st |= OXL_STATUS_HOST;
  if (s->timed_out)
    st |= OXL_STATUS_TIMEOUT;
  return st;
}
