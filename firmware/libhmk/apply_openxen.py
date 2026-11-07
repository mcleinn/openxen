#!/usr/bin/env python3
"""Apply openxen's changes to a libhmk work tree (pinned commit, see build_firmware.py).

    python firmware/libhmk/apply_openxen.py <libhmk work tree>

1. copies firmware/libhmk/{src,include} (our own files) into the tree
2. edits libhmk files by exact search/replace; every step must match exactly once, so a
   libhmk update that moves the code fails here instead of producing a wrong firmware.
Line endings of each edited file are preserved.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BS = "\\"

STREAM_REPORT_DESC = """// HID report descriptor for the openxen analog stream (one fixed-size input report)
static const uint8_t desc_stream_report[] = {
    HID_USAGE_PAGE_N(OXS_USAGE_PAGE, 2), HID_USAGE(OXS_USAGE),
    HID_COLLECTION(HID_COLLECTION_APPLICATION),
    HID_USAGE(OXS_USAGE + 1), HID_LOGICAL_MIN(0), HID_LOGICAL_MAX_N(255, 2),
    HID_REPORT_COUNT(OXS_REPORT_SIZE), HID_REPORT_SIZE(8),
    HID_INPUT(HID_DATA | HID_VARIABLE | HID_ABSOLUTE),
    HID_COLLECTION_END};

"""

EDITS: list[tuple[str, str, str]] = [
    # --- TinyUSB: a 4th HID interface; buffer large enough for the 144-byte stream report
    ("include/tusb_config.h", "#define CFG_TUD_HID 3", "#define CFG_TUD_HID 4  // + openxen analog stream"),
    # CFG_TUD_HID_EP_BUFSIZE stays 64 (libhmk asserts RAW_HID_EP_SIZE == it); the 144-byte
    # stream report is sent from its own buffer with usbd_edpt_xfer (openxen_stream.c).
    # --- interface and endpoint numbers (XInput stays the last interface)
    ("include/usb_descriptors.h", "  USB_ITF_RAW_HID,\n",
     "  USB_ITF_RAW_HID,\n  // openxen analog stream (input only), see docs/stream-protocol.md\n  USB_ITF_STREAM,\n"),
    ("include/usb_descriptors.h", "  EP_IN_ADDR_XINPUT,\n};", "  EP_IN_ADDR_XINPUT,\n  EP_IN_ADDR_STREAM,\n};"),
    ("include/usb_descriptors.h", "#define RAW_HID_USAGE 0xAB\n",
     "#define RAW_HID_USAGE 0xAB\n\n"
     "// openxen analog stream: vendor usage page/usage, report size, endpoint packet sizes\n"
     "#define OXS_USAGE_PAGE 0xFFAC\n#define OXS_USAGE 0xAC\n#define OXS_REPORT_SIZE 144\n"
     "#define OXS_EP_SIZE_HS 160\n#define OXS_EP_SIZE_FS 64\n"),
    # --- descriptors
    ("src/usb_descriptors.c", "#define CONFIG_TOTAL_LEN ",
     STREAM_REPORT_DESC + "#define CONFIG_TOTAL_LEN "),
    ("src/usb_descriptors.c", "(TUD_CONFIG_DESC_LEN + 2 * TUD_HID_DESC_LEN + TUD_HID_INOUT_DESC_LEN +",
     "(TUD_CONFIG_DESC_LEN + 3 * TUD_HID_DESC_LEN + TUD_HID_INOUT_DESC_LEN +"),
    ("src/usb_descriptors.c", "static void generate_desc_configuration(uint8_t *dst) {",
     "static void generate_desc_configuration(uint8_t *dst, bool high_speed) {"),
    ("src/usb_descriptors.c",
     "                               EP_IN_ADDR_RAW_HID, RAW_HID_EP_SIZE,\n"
     "                               polling_interval),\n",
     "                               EP_IN_ADDR_RAW_HID, RAW_HID_EP_SIZE,\n"
     "                               polling_interval),\n"
     "      // openxen analog stream: every 125 us microframe at high speed (one report\n"
     "      // per scan), multi-packet reports every 1 ms at full speed\n"
     "      TUD_HID_DESCRIPTOR(USB_ITF_STREAM, 0, HID_ITF_PROTOCOL_NONE,\n"
     "                         sizeof(desc_stream_report), EP_IN_ADDR_STREAM,\n"
     "                         OXS_EP_SIZE_HS, 1),\n"),
    # full-speed variant: the stream endpoint's wMaxPacketSize patched to 64 after the copy
    # (the descriptor macros only accept constants under libhmk's -Wsign-conversion)
    ("src/usb_descriptors.c", "  memcpy(dst, src, sizeof(src));\n",
     "  memcpy(dst, src, sizeof(src));\n\n"
     "  // openxen stream: full-speed interrupt endpoints carry at most 64 bytes per packet\n"
     "  if (!high_speed) {\n"
     "    for (uint16_t i = 0; i + 6u < sizeof(src); i = (uint16_t)(i + dst[i])) {\n"
     "      if (dst[i] == 0)\n        break;\n"
     "      if (dst[i + 1u] == TUSB_DESC_ENDPOINT && dst[i + 2u] == EP_IN_ADDR_STREAM) {\n"
     "        dst[i + 4u] = (uint8_t)(OXS_EP_SIZE_FS & 0xFFu);\n"
     "        dst[i + 5u] = (uint8_t)(OXS_EP_SIZE_FS >> 8);\n"
     "      }\n    }\n  }\n"),
    ("src/usb_descriptors.c", "  case USB_ITF_RAW_HID:\n    return desc_raw_hid_report;\n",
     "  case USB_ITF_RAW_HID:\n    return desc_raw_hid_report;\n\n  case USB_ITF_STREAM:\n    return desc_stream_report;\n"),
    ("src/usb_descriptors.c", "  generate_desc_configuration(desc_configuration);",
     "  generate_desc_configuration(desc_configuration,\n                              tud_speed_get() == TUSB_SPEED_HIGH);"),
    ("src/usb_descriptors.c", "  generate_desc_configuration(desc_other_speed_config);",
     "  // the other speed is full speed when running at high speed (and vice versa)\n"
     "  generate_desc_configuration(desc_other_speed_config,\n                              tud_speed_get() != TUSB_SPEED_HIGH);"),
    # --- scan-complete hook in the AT32 analog driver
    ("src/hardware/at32f405xx/analog.c", "void analog_task(void) {}\n",
     "void analog_task(void) {}\n\n"
     "// Called from the DMA interrupt after the last multiplexer channel of a scan\n"
     "// (openxen analog stream). Weak default: nothing.\n"
     "__attribute__((weak)) void analog_scan_complete_cb(void) {}\n"),
    ("src/hardware/at32f405xx/analog.c", "    adc_initialized |= (current_mux_channel == 0);\n",
     "    adc_initialized |= (current_mux_channel == 0);\n"
     "    if (current_mux_channel == 0)\n      analog_scan_complete_cb();\n"),
    ("include/hardware/analog_api.h", "uint16_t analog_read(uint8_t key);\n",
     "uint16_t analog_read(uint8_t key);\n\n"
     "/**\n * @brief Hook called after every completed scan of all keys (interrupt context)\n *\n"
     " * @return None\n */\nvoid analog_scan_complete_cb(void);\n"),
    # --- main loop
    ("src/main.c", '#include "matrix.h"\n', '#include "matrix.h"\n#include "openxen_stream_api.h"\n'),
    ("src/main.c", "  // Initialize the core modules\n  analog_init();",
     "  // Initialize the core modules\n  openxen_stream_init();\n  analog_init();"),
    ("src/main.c", "    matrix_scan();\n", "    matrix_scan();\n    openxen_stream_task();\n"),
]


def main() -> int:
    tree = Path(sys.argv[1]).resolve()
    for sub in ("src", "include"):
        shutil.copytree(HERE / sub, tree / sub, dirs_exist_ok=True)
    for rel, old, new in EDITS:
        p = tree / rel
        raw = p.read_bytes().decode("utf-8")
        crlf = "\r\n" in raw
        text = raw.replace("\r\n", "\n")
        n = text.count(old)
        if n != 1:
            raise SystemExit(f"apply_openxen: {rel}: expected 1 match, found {n}:\n{old[:200]}")
        text = text.replace(old, new)
        p.write_bytes((text.replace("\n", "\r\n") if crlf else text).encode("utf-8"))
    print(f"apply_openxen: {len(EDITS)} edits applied, own sources copied")
    return 0


if __name__ == "__main__":
    sys.exit(main())
