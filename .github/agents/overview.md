# Project Overview

## Purpose

This Python tool downloads thumbnail images for PC Engine, PC Engine CD, Game Boy Advance, and Neo Geo Pocket Color games from [libretro-thumbnails](https://github.com/libretro-thumbnails), converts them to the Analogue OS proprietary library image format, and writes them to an Analogue device's SD card.

The script accepts the SD card root path as its primary argument, auto-detects the device type (Analogue Pocket or Analogue Duo), and places converted images in the correct location for each device.

---

## Goals

1. **Download all console thumbnails** from libretro-thumbnails (bulk download, three image types).
2. **Convert images to the correct Analogue OS library format** for the detected device.
3. **Auto-detect device type** from the SD card root (Duo vs Pocket).
4. **Cross-platform** — works on Windows, macOS, and Linux.
5. **Idempotent** — re-running skips images already converted and up-to-date.

---

## Supported Consoles

| Console | `--console` Key | libretro-thumbnails Repo | SD Card Path (Pocket) |
|---|---|---|---|
| PC Engine / TurboGrafx-16 | `pce` | `NEC_-_PC_Engine_-_TurboGrafx_16` | `System/Library/Images/pce/` |
| PC Engine CD / TurboGrafx-CD | `pcecd` | `NEC_-_PC_Engine_CD_-_TurboGrafx-CD` | `System/Library/Images/pcecd/` |
| Game Boy Advance | `gba` | `Nintendo_-_Game_Boy_Advance` | `System/Library/Images/gba/` |
| Neo Geo Pocket Color | `ngp` | `SNK_-_Neo_Geo_Pocket_Color` | `System/Library/Images/ngp/` |

> **SD card path = `platform_ids[]` from `core.json`** (per [Analogue developer docs](https://www.analogue.co/developer/docs/library)). Use the `platform_ids` value (e.g. `pce`), NOT the display shortname (e.g. "PC Engine"). On Windows FAT32/exFAT these are case-insensitive but the firmware expects the lowercase `platform_id`.

---

## Architecture

```
analogue_image_gen.py  (all core logic)
        │
        ┌───────────────┼──────────────────┐
        ▼               ▼                  ▼
        Download          DAT Parsing /      Image Conversion
  (GitHub ZIP archive)   list.bin parse    (PIL → Analogue .bin)
              │               │                  │
              ▼               ▼                  ▼
  ~/.analogue-image-gen/  game → CRC32      Pocket: rotate −90°CCW, header(h,w)
  cache/{repo}/{type}/    lookup dict      Duo:    no rotation,   header(w,h)
                                            Both: scale 165px height, BGRA32
```

**Download phase:** Fetches a ZIP archive from GitHub. All three image type directories (`Named_Boxarts/`, `Named_Titles/`, `Named_Snaps/`) are extracted to the local cache.

**Device detection:** Reads `Analogue_Pocket.json` or `Analogue_Duo.json` from the SD card root.

**Per-image pipeline:**
1. `validate_image()` — detect PNG/JPEG/libretro symlink-text; resolve symlink-text paths
2. `should_skip_image()` — filter romhacks, pirates, Virtual Console titles
3. `get_redirect()` — apply name redirects from `special_cases.json`
4. `match_game_to_crc()` — 4-tier fuzzy match (see `.github/skills/game-matching/SKILL.md`)
5. `convert_image_to_pocket_bin()` — scale to 165px, convert to BGRA32, write
   - **Pocket** (`rotate=True`): pre-rotate 90°CCW; header = `(stored_h, stored_w)`
   - **Duo** (`rotate=False`): no rotation; header = `(stored_w, stored_h)`

**Output:** `System/Library/Images/{platform_id}/{crc32}.bin` + `{game name}.bin`

---

## Entry Point

```
python analogue_image_gen.py <sd_card_root> [mode] [options]
```

| Mode | Description |
|---|---|
| `auto` (default) | Download → convert → write to SD card |
| `download-only` | Download all three image types to cache, no conversion |
| `convert-only` | Convert from cache to SD card (offline) |
| `list-games` | List available game names from libretro-thumbnails |

### Image Types (`--image-type`)

| Value | libretro Directory | Description |
|---|---|---|
| `boxart` (default) | `Named_Boxarts/` | Front box art / cover art |
| `title` | `Named_Titles/` | Title screen screenshot |
| `snap` | `Named_Snaps/` | In-game screenshot |

---

## Dependencies

| Package | Purpose |
|---|---|
| **Pillow (`PIL`)** | Image loading, rotation, resizing, pixel format conversion |
| **requests** | HTTP downloads from GitHub / libretro-thumbnails |
| **argparse** | CLI argument parsing (stdlib) |
| **struct** | Binary packing for `.bin` headers (stdlib) |
| **pathlib** | Path manipulation (stdlib) |
| **zipfile** | Archive extraction (stdlib) |
| **logging** | Structured logging (stdlib) |
| **zlib** | CRC32 computation (stdlib) |

Install: `pip install -r requirements.txt`

---

## Repository Structure

```
analogue_image_gen.py                 ← Main script (all core logic)
requirements.txt                      ← Python dependencies
special_cases.json                    ← Per-console skip/redirect rules
.github/
├── agents/
│   ├── overview.md                   ← This file
│   ├── status.md                     ← Dev status, open questions
│   └── phase-tracker.md              ← Per-task checkbox status
└── skills/
    ├── workflow/SKILL.md             ← Setup, testing, CLI reference
    ├── game-matching/SKILL.md        ← CRC identification, fuzzy matching
    ├── device-formats/SKILL.md       ← Binary formats, SD card structures
    ├── hardware-testing/SKILL.md     ← Hardware test results and procedures
    └── binary-formats/SKILL.md       ← Detailed binary format specs
scripts/
├── test_image_conversion.py          ← Test suite (48+ tests)
├── read_list_bin.py                  ← Parse and display list.bin contents
└── generate_test_bins.py             ← Generate test .bin files for hardware
```
