#!/usr/bin/env python3
"""Read and display the contents of an Analogue Pocket/Duo list.bin played-games database."""

import argparse
import csv
import struct
import sys
from pathlib import Path

MAGIC = b"\x01FAT"

SYSTEM_NAMES = {
    0x02: "GBA",
    0x06: "NGP",
    0x07: "PCE",
}

CONSOLE_KEYS = {
    0x02: "gba",
    0x06: "ngp",
    0x07: "pce",
}

MEDIA_TYPES = {
    0x00: "HuCard",
    0x01: "CD",
}


def parse_list_bin(path: Path):
    data = path.read_bytes()

    if data[:4] != MAGIC:
        sys.exit(
            f"Error: invalid magic bytes {data[:4]!r}; expected {MAGIC!r}.\n"
            f"Is '{path}' a valid list.bin file?"
        )

    entry_count, _unknown, first_entry_offset = struct.unpack_from("<III", data, 4)

    index_table_offset = 16
    offsets = struct.unpack_from(f"<{entry_count}I", data, index_table_offset)

    entries = []
    for i, offset in enumerate(offsets):
        entry_size, flags = struct.unpack_from("<HH", data, offset)
        hash2, game_id = struct.unpack_from("<II", data, offset + 8)
        crc32 = struct.unpack_from("<I", data, offset + 4)[0]

        name_start = offset + 0x10
        name_end = data.index(b"\x00", name_start)
        name = data[name_start:name_end].decode("utf-8", errors="replace")

        media_type = flags & 0xFF
        system_id = (flags >> 8) & 0xFF

        entries.append({
            "index": i,
            "system_id": system_id,
            "media_type": media_type,
            "flags": flags,
            "hash2": hash2,
            "crc32": crc32,
            "game_id": game_id,
            "name": name,
        })

    return entries


def system_label(entry):
    sid = entry["system_id"]
    name = SYSTEM_NAMES.get(sid, "Unknown")
    return f"0x{sid:02X} ({name})"


def console_key(entry):
    return CONSOLE_KEYS.get(entry["system_id"], f"0x{entry['system_id']:02X}")


def print_table(entries):
    col_widths = {
        "index":   max(5, len("Index")),
        "system":  max(len(system_label(e)) for e in entries) if entries else 12,
        "key":     max(len(console_key(e)) for e in entries) if entries else 11,
        "crc32":   8,
        "game_id": 8,
        "flags":   5,
        "name":    max((len(e["name"]) for e in entries), default=4),
    }
    col_widths["name"] = max(col_widths["name"], len("Name"))
    col_widths["system"] = max(col_widths["system"], len("System"))
    col_widths["key"] = max(col_widths["key"], len("Console Key"))

    header = (
        f"{'Index':<{col_widths['index']}}  "
        f"{'System':<{col_widths['system']}}  "
        f"{'Console Key':<{col_widths['key']}}  "
        f"{'CRC32':<{col_widths['crc32']}}  "
        f"{'Game ID':<{col_widths['game_id']}}  "
        f"{'Flags':<{col_widths['flags']}}  "
        f"Name"
    )
    separator = "-" * len(header)
    print(header)
    print(separator)

    for e in entries:
        print(
            f"{e['index']:<{col_widths['index']}}  "
            f"{system_label(e):<{col_widths['system']}}  "
            f"{console_key(e):<{col_widths['key']}}  "
            f"{e['crc32']:08X}  "
            f"{e['game_id']:08X}  "
            f"{e['flags']:04X}   "
            f"{e['name']}"
        )


def print_csv(entries):
    writer = csv.writer(sys.stdout)
    writer.writerow(["Index", "System", "Console Key", "CRC32", "Game ID", "Flags", "Name"])
    for e in entries:
        writer.writerow([
            e["index"],
            system_label(e),
            console_key(e),
            f"{e['crc32']:08X}",
            f"{e['game_id']:08X}",
            f"{e['flags']:04X}",
            e["name"],
        ])


def print_summary(entries, all_entries):
    print()
    print(f"Total entries shown: {len(entries)}  (of {len(all_entries)} total)")

    counts: dict[int, int] = {}
    for e in all_entries:
        counts[e["system_id"]] = counts.get(e["system_id"], 0) + 1

    print("Breakdown by system (all entries):")
    for sid, count in sorted(counts.items()):
        name = SYSTEM_NAMES.get(sid, "Unknown")
        print(f"  0x{sid:02X} ({name}): {count}")


def main():
    parser = argparse.ArgumentParser(
        description="Read and display an Analogue Pocket/Duo list.bin played-games database."
    )
    parser.add_argument("list_bin_path", type=Path, help="Path to list.bin")
    parser.add_argument(
        "--system",
        metavar="SYSTEM",
        help="Filter by console key (e.g. gba, pce, ngp)",
    )
    parser.add_argument(
        "--format",
        choices=["table", "csv"],
        default="table",
        dest="fmt",
        help="Output format (default: table)",
    )
    args = parser.parse_args()

    all_entries = parse_list_bin(args.list_bin_path)

    if args.system:
        key = args.system.lower()
        filtered = [e for e in all_entries if console_key(e).lower() == key]
    else:
        filtered = all_entries

    if args.fmt == "csv":
        print_csv(filtered)
    else:
        print_table(filtered)

    print_summary(filtered, all_entries)


if __name__ == "__main__":
    main()
