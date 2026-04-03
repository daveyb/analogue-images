---
name: device-formats
description: "Analogue Pocket and Duo SD card structures and image format specs. Use when working on image conversion, output directory names, Pocket vs Duo format differences, or list.bin parsing."
---

# Device Formats & SD Card Structures

## Device Detection

The script auto-detects the device type from the SD card root:

| File | Device |
|---|---|
| `Analogue_Pocket.json` | Analogue Pocket |
| `Analogue_Duo.json` | Analogue Duo |

If neither is found, `--device pocket` or `--device duo` is required.

---

## Analogue Pocket `.bin` Image Format

### Header (8 bytes)

| Offset | Size | Value |
|--------|------|-------|
| `0x00` | 4 B | Magic: `0x20 0x49 0x50 0x41` (`" IPA"`, LE = `0x41504920`) |
| `0x04` | u16 LE | Display width (= height of stored/rotated image) |
| `0x06` | u16 LE | Display height (= width of stored/rotated image) |

### Pixel Data

- Format: **BGRA32** — 4 bytes per pixel (Blue, Green, Red, Alpha)
- Layout: row-major; stored **90°CCW pre-rotated** from display orientation

### Conversion Pipeline

```
Load image → Rotate 90°CCW (PIL rotate(90)) → Scale to 165px height (post-rotation) → BGRA32 → Write header + pixel data
```

**Why pre-rotation:** The Pocket firmware applies 90°CW when rendering library images. Pre-rotating −90°CCW results in correct upright display. The output must be portrait-oriented (width < height) — the firmware rejects landscape files, showing `Image: —` in Game Detail view.

| Source | After rotate(90) | After scale to h=165 | Result |
|---|---|---|---|
| Landscape boxart 600×594 | 594×600 | 163×165 | ✅ Portrait |
| No pre-rotation | 600×594 | 165×163 | ❌ Landscape — rejected |

### `pce_thumbs.bin` — firmware-managed cache

`System/Library/Images/pce_thumbs.bin` is rebuilt by the Pocket firmware on boot by scanning the individual `.bin` files in `System/Library/Images/pce/`. **Do not write or modify it manually.**

If it is 65,548 bytes (empty) after a Pocket boot, the firmware found no valid `.bin` files in `pce/`. Confirm files are in `pce/` (not `PC Engine/` or another directory).

---

## `list.bin` Format (Pocket and Duo — same format)

Magic: `0x01 0x46 0x41 0x54` (`\x01FAT`).

### File Header

| Offset | Size | Description |
|---|---|---|
| `0x00` | 4 B | Magic: `\x01FAT` |
| `0x04` | u32 LE | Entry count |
| `0x08` | u32 LE | Unknown (observed: 16 = `0x10`) |
| `0x0C` | u32 LE | Offset to first entry |

An array of `entry_count` u32 LE values follows (byte offsets to each entry).

### Entry Format

| Offset | Size | Description |
|---|---|---|
| `+0` | u16 LE | Entry size (including this field) |
| `+2` | u16 LE | Flags: upper byte = system ID (`0x00`=HuCard, `0x01`=CD) |
| `+4` | u32 LE | **ROM file CRC32** — used as image filename |
| `+8` | u32 LE | Secondary hash (unknown purpose) |
| `+12` | u32 LE | Game database index |
| `+16` | variable | NUL-terminated UTF-8 game name |

Entries are padded to 4-byte alignment. Full spec: `.github/skills/binary-formats/SKILL.md`.

---

## Analogue Pocket — SD Card Structure

```
/Assets/<console>/common/           ← ROM files
/System/Library/Images/<platform_id>/  ← Per-game library images
/System/Played Games/list.bin       ← Played games database
```

### Console Platform ID Mappings

| Console | `platform_id` | Asset Path | Image Path |
|---|---|---|---|
| PC Engine | `pce` | `Assets/pce/common/` | `System/Library/Images/pce/` |
| PC Engine CD | `pcecd` | `Assets/pcecd/common/` | `System/Library/Images/pcecd/` |
| Game Boy Advance | `gba` | `Assets/gba/common/` | `System/Library/Images/gba/` |
| Neo Geo Pocket Color | `ngp` | `Assets/ngp/common/` | `System/Library/Images/ngp/` |

> **IMPORTANT:** Directory name = `platform_ids` from `core.json`, NOT the display shortname. On FAT32/exFAT case is insensitive but the convention is lowercase.

### Per-Game Image File Naming

Each game gets one or more `.bin` files:
- `{crc32}.bin` — primary file, named after the ROM CRC32 from `list.bin` offset `+4`
- `{libretro game name}.bin` — copy using the sanitized libretro thumbnail filename
- `{list.bin game name}.bin` — copy using the exact name from `list.bin` (if different)

All three copies are identical in content; the firmware may use any of these lookup strategies.

---

## Analogue Duo — SD Card Structure

```
/System/Library/Images/pce/             ← Per-game PCE images (same as Pocket)
/System/Library/Images/pcecd/           ← Per-game PCECD images (same as Pocket)
/System/Library/Images/pce_thumbs.bin   ← Firmware-managed consolidated cache
/System/Library/Images/pcecd_thumbs.bin ← Firmware-managed consolidated cache
/System/Played Games/list.bin           ← Played games database
```

The Duo uses **the same per-game `.bin` file approach as the Pocket**: individual CRC-named files in `pce/` and `pcecd/` subdirectories. The firmware rebuilds `pce_thumbs.bin` and `pcecd_thumbs.bin` from those files on boot. Do NOT write the consolidated files manually.

> **Confirmed on hardware (2026-04-03, firmware 1.5):** PCE and PCECD box art displays correctly in the Duo Library.

---

## Analogue Duo — Image Format Differences

The Duo uses the same `.bin` file format as the Pocket **except**:

| | Pocket | Duo |
|---|---|---|
| Pre-rotation | 90°CCW (`rotate=True`) | None (`rotate=False`) |
| Header `0x04` | `stored_h` (= display width after CW rotation) | `stored_w` (= actual pixel columns) |
| Header `0x06` | `stored_w` (= display height after CW rotation) | `stored_h` (= actual pixel rows) |
| Firmware render | Applies 90°CW at render time | Renders stored data as-is |

**Why the difference matters:** If you write a Pocket-format image to the Duo (header `(h, w)` with pre-rotation), the firmware reads the first header field as the row width. A 2px mismatch between the header value and the actual stored row width causes a cumulative row-offset error — visible as thin horizontal stripes across the image. The garbled image has the right colors but wrong geometry.

### Conversion Pipeline

```
Pocket: Load → rotate(90°CCW) → scale h=165 → BGRA32 → header(stored_h, stored_w)
Duo:    Load →                   scale h=165 → BGRA32 → header(stored_w, stored_h)
```

---

## Analogue Duo `list.bin` — Flags Interpretation

The Duo uses the **same `list.bin` binary format** as the Pocket but interprets the `flags` field differently:

| Device | Flags field (`+2`, u16 LE) | Meaning |
|---|---|---|
| Pocket | Upper byte = system ID | `0x0700` = PCE, `0x0200` = GBA, etc. |
| Duo | Full u16 = game type | `0x0000` = HuCard (PCE), `0x0100` = CD-ROM (PCECD) |

`parse_pocket_played_games()` **cannot** be used on a Duo SD card — it misclassifies HuCard (flags=`0x0000`, system_id=0x00) and CD (flags=`0x0100`, system_id=0x01). Use `parse_duo_played_games()` instead.

### Duo CRC32 Note

Duo CRC32 values may differ from No-Intro CRCs. Always read CRCs from the Duo's own `list.bin` via `build_duo_db_lookup()`.

Examples:
| Game | Duo CRC32 | No-Intro CRC32 |
|---|---|---|
| Ninja Spirit | `de8af1c1` | `6c2052d5` |
| Military Madness | `93f316f7` | `52c7ce6e` |

---

## Verified CRC32 Examples

| Console | Game | CRC32 | Source |
|---|---|---|---|
| PCE | Bonk's Adventure (USA) | `599ead9b` | ROM file + `list.bin` +4 ✅ |
| PCE | Ninja Spirit | `6c2052d5` | ROM file + `list.bin` +4 ✅ |
| GBA | Advance Wars 2 | `5ad0e571` | No-Intro ROM CRC + `list.bin` +4 ✅ |
| GBA | Fire Emblem: Sacred Stones | `a47246ae` | No-Intro ROM CRC + `list.bin` +4 ✅ |
