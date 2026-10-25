#!/usr/bin/env python3
"""Extract the 8x16 bitmap font from kernel/gfx.c into a raw binary file.

Usage: python mkfont.py <path/to/gfx.c> <out.bin>
The font table in gfx.c is a C array of 95 * 16 bytes (ASCII 32..126).
"""

import re
import sys


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        return 1

    src_path, out_path = sys.argv[1], sys.argv[2]
    text = open(src_path, "r", encoding="utf-8", errors="replace").read()

    start = text.index("font8x16_table")
    start = text.index("{", start)
    end = text.index("};", start)
    body = text[start:end]

    # 逐行去掉注释后提取十六进制字节 (逐行处理, 避免跨行注释吞掉数据)
    data = bytearray()
    for line in body.splitlines():
        line = re.sub(r"/\*.*?\*/", "", line)
        line = re.sub(r"//.*", "", line)
        data.extend(int(x, 16) for x in re.findall(r"0x([0-9A-Fa-f]{2})\b", line))
    data = bytes(data)

    expected = 95 * 16
    if len(data) != expected:
        print("warning: got %d bytes, expected %d" % (len(data), expected))

    with open(out_path, "wb") as f:
        f.write(data)
    print("font written: %s (%d bytes)" % (out_path, len(data)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
