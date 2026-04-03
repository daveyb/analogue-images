---
name: binary-formats
description: "Binary format specs for .bin image files, list.bin played-games database, and pce_thumbs.bin. Use when working on binary parsing, file format bugs, or reading raw device data."
---

# Binary Formats

Reference for all binary format specifications used by the Analogue Pocket and Duo.

---

## Analogue Pocket `.bin` Format (Fully Documented)

Source: https://www.analogue.co/developer/docs/library

### Header (8 bytes)
| Offset | Size | Value / Description |
|--------|------|---------------------|
| 0x00   | 4 B  | Magic: `0x20 0x49 0x50 0x41` (= `0x41504920` LE = RGB32 format) |
| 0x04   | u16 LE | **Display width** in pixels (= height of the stored/rotated image data) |
| 0x06   | u16 LE | **Display height** in pixels (= width of the stored/rotated image data) |

> ⚠️ Earlier docs had this backwards (height then width). Confirmed via Analogue developer docs sample code: width (bytes 4-5) then height (bytes 6-7), where width/height describe the **final display** image dimensions.

### Pixel Data
- Format: **BGRA32** — 4 bytes per pixel in Blue, Green, Red, Alpha order
- Layout: row-major, **stored 90°CCW rotated** from display orientation
- Alpha must be `0xFF` (fully opaque)

### Rotation & Scaling

**Pre-rotation is required.** The Pocket firmware applies 90°CW when rendering library images; pre-rotating -90°CCW (= PIL `rotate(90)`) produces correct upright display.

- Scale to **165 px** target height (post-rotation) before writing
- Output must be **portrait** (stored width < stored height) — firmware rejects landscape

### Conversion Pipeline
```
Load image → Rotate 90°CCW (PIL rotate(90)) → Scale to 165px height (post-rotation) → Convert to BGRA32 → Write header + pixel data
```

### Confirmed working (hardware 2026-04-02)
PC Engine HuCard games via agg23.PCEngine OpenFPGA core display box art correctly using this format.

---

## Analogue Duo `.bin` Format

The Duo uses the **same magic bytes and pixel format** as the Pocket but with two key differences:

| | Pocket | Duo |
|---|---|---|
| Pre-rotation | 90°CCW (`rotate=True`) | None (`rotate=False`) |
| Header bytes 0x04–0x05 | `stored_h` (display width) | `stored_w` (actual pixel columns) |
| Header bytes 0x06–0x07 | `stored_w` (display height) | `stored_h` (actual pixel rows) |

**Confirmed working (hardware 2026-04-03, firmware 1.5).**

---

## `pce_thumbs.bin` Format

Both Pocket and Duo use this format for firmware-managed thumbnail caches.

### Header (12 bytes)
| Offset | Size | Value / Description |
|--------|------|---------------------|
| 0x00   | 4 B  | Magic: `0x02 0x46 0x54 0x41` (`\x02FTA`) |
| 0x04   | u32 LE | Total size of image data section in bytes |
| 0x08   | u32 LE | Number of images in the file |

### Hash Table (65,536 bytes, 8,192 entries of 8 bytes each)
Starts at offset 0x0C (= `PCE_THUMBS_HEADER_SIZE`).

Each 8-byte slot:
| Offset | Size | Description |
|--------|------|-------------|
| +0     | u32 LE | CRC32 of the game (0 = empty slot) |
| +4     | u32 LE | Byte offset into image data section |

Slot selection: `crc32 % 8192` with linear probing for collisions.

### Image Data Section
Starts immediately after the hash table. Each entry is a full Pocket-format `.bin` image (header + pixel data), but scaled to a smaller thumbnail:
- Target height: **40 px** (post-rotation for Pocket; as-is for Duo)
- Width: proportional to source

> **Do not write this file manually.** Both the Pocket and Duo firmware manage and rebuild these files automatically from the per-game `.bin` files on boot.

---

## `list.bin` Format (Pocket and Duo — same format)

### Magic
`0x01` + `"FAT"` (= `\x01FAT`)

### Header (16 bytes)
| Offset | Size | Value / Description |
|--------|------|---------------------|
| 0x00   | 4 B  | Magic (`0x01 FAT`) |
| 0x04   | u32 LE | Entry count |
| 0x08   | u32 LE | Unknown (observed: 16 = `0x10`) |
| 0x0C   | u32 LE | Byte offset to first entry |

### Index Table
Array of `entry_count` × u32 LE values, each a byte offset pointing to an entry.

### Entry Format
| Offset | Size | Description |
|--------|------|-------------|
| 0x00   | u16 LE | Entry size (including this field) |
| 0x02   | u16 LE | Flags: `0x0000` = HuCard, `0x0100` = CD; upper byte = system ID on Pocket |
| **0x04** | **u32 LE** | **ROM file CRC32 ← THIS IS THE IMAGE FILENAME** (e.g. `599ead9b`) |
| 0x08   | u32 LE | Secondary identifier — unknown purpose; NOT used for image lookup |
| 0x0C   | u32 LE | `game_id` (firmware database index) |
| 0x10   | variable | NUL-terminated UTF-8 game name, padded to 4-byte alignment |

> ⚠️ CRITICAL: The image filename is derived from **offset `+4`** (ROM file CRC32), NOT offset `+8`. Earlier code read offset `+8` which caused all filenames to be wrong and no images to appear. Confirmed via CRC32 of `Bonk's Adventure (USA).pce` = `599ead9b` = `list.bin[+4]`.

### Pocket System IDs (verified firmware 2.5)
| ID   | System |
|------|--------|
| 0x02 | GBA |
| 0x06 | NGP |
| 0x07 | PCE |

### Duo Flags Interpretation
The Duo uses the full u16 `flags` field as a game type indicator (not a system ID):
| Flags | Type |
|-------|------|
| `0x0000` | HuCard (PCE) |
| `0x0100` | CD-ROM (PCECD) |

Use `parse_duo_played_games()` for Duo SD cards — `parse_pocket_played_games()` misclassifies Duo entries.

### File Locations
- **Pocket:** `System/Played Games/list.bin`
- **Duo:** `System/Played Games/list.bin`

---

## CRITICAL: Pocket Image Filename Source

The Pocket's library `.bin` filename = **CRC32 of the ROM file** = `list.bin` offset `+4`.

| System | Status |
|--------|--------|
| PCE / PCECD | ✅ Confirmed on hardware (2026-04-02) — `list.bin[+4]` = ROM file CRC32 |
| GBA | ✅ Fixed — `list.bin[+4]` = No-Intro ROM CRC32; use `--use-pocket-db` |
| NGP / NGPC | 🔲 Not yet hardware-tested — system ID `0x06`; images go to `System/Library/Images/ngp/` |

### Verification (Bonk's Adventure)
- ROM: `Bonk's Adventure (USA).pce` (384 KB)
- `crc32(rom file)` = `599ead9b` = `list.bin[+4]` ✅
- Image filename: `599ead9b.bin`
- `list.bin[+8]` = `6aa69a8b` ← this is NOT the image filename
