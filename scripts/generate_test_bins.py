#!/usr/bin/env python3
"""Generate solid-color test .bin image files in Analogue Pocket format."""

import argparse
import struct
import sys
from pathlib import Path

MAGIC = bytes([0x20, 0x49, 0x50, 0x41])  # " IPA"

DEFAULT_COLORS = [
    ("blue",    "0000FF"),
    ("magenta", "FF00FF"),
    ("orange",  "FF8000"),
    ("green",   "00FF00"),
    ("yellow",  "FFFF00"),
]


def parse_color(hex_str: str) -> tuple[int, int, int]:
    hex_str = hex_str.lstrip("#")
    if len(hex_str) != 6:
        raise ValueError(f"Invalid color hex '{hex_str}'; expected RRGGBB")
    r = int(hex_str[0:2], 16)
    g = int(hex_str[2:4], 16)
    b = int(hex_str[4:6], 16)
    return r, g, b


def build_bin(width: int, height: int, r: int, g: int, b: int) -> bytes:
    pixel = bytes([b, g, r, 255])  # BGRA32, alpha=255
    pixel_data = pixel * (width * height)
    header = MAGIC + struct.pack("<HH", height, width)
    return header + pixel_data


def main():
    parser = argparse.ArgumentParser(
        description="Generate solid-color test .bin files in Analogue Pocket format."
    )
    parser.add_argument("output_dir", type=Path, help="Directory to write .bin files into")
    parser.add_argument("--width", type=int, default=120, help="Image width in pixels (default: 120)")
    parser.add_argument("--height", type=int, default=165, help="Image height in pixels (default: 165)")
    parser.add_argument(
        "--colors",
        metavar="name:RRGGBB,...",
        help="Comma-separated list of name:RRGGBB color specs (default: 5 built-in test colors)",
    )
    parser.add_argument(
        "--names",
        metavar="NAME,...",
        help="Comma-separated output filenames (without .bin) matching the order of --colors",
    )
    args = parser.parse_args()

    if args.colors:
        raw_pairs = [item.strip() for item in args.colors.split(",") if item.strip()]
        try:
            color_specs = []
            for pair in raw_pairs:
                if ":" not in pair:
                    sys.exit(f"Error: color spec '{pair}' must be in name:RRGGBB format")
                name, hex_val = pair.split(":", 1)
                color_specs.append((name.strip(), hex_val.strip()))
        except ValueError as exc:
            sys.exit(f"Error parsing --colors: {exc}")
    else:
        color_specs = list(DEFAULT_COLORS)

    if args.names:
        names = [n.strip() for n in args.names.split(",") if n.strip()]
        if len(names) != len(color_specs):
            sys.exit(
                f"Error: --names has {len(names)} entries but --colors has {len(color_specs)} entries"
            )
        color_specs = [(names[i], hex_val) for i, (_, hex_val) in enumerate(color_specs)]

    args.output_dir.mkdir(parents=True, exist_ok=True)

    for name, hex_val in color_specs:
        try:
            r, g, b = parse_color(hex_val)
        except ValueError as exc:
            sys.exit(f"Error: {exc}")

        data = build_bin(args.width, args.height, r, g, b)
        out_path = args.output_dir / f"{name}.bin"
        out_path.write_bytes(data)
        print(f"Written: {out_path}  ({args.width}x{args.height}, #{hex_val.upper()})")

    print(f"\nGenerated {len(color_specs)} file(s) in '{args.output_dir}'")


if __name__ == "__main__":
    main()
