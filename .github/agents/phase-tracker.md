# Agent Skill: Phase Tracker

## Purpose

Use this skill to:
- Understand the current state of the development plan
- Know which phase is active and which tasks remain
- Know how to correctly mark tasks done, in-progress, or blocked

## Phase Status Format

Checkboxes follow this convention:
- `[x]` — Complete
- `[ ]` — Not started
- `[~]` — In-progress or blocked

## Current Development Plan

### Phase 1: Core Infrastructure & Download
- [x] Set up `argparse` CLI with positional `sd_card` argument and options (including `--image-type`)
- [x] Implement device auto-detection (read `Analogue_Duo.json` / `Analogue_Pocket.json`)
- [x] Implement libretro-thumbnails archive download and extraction (extract all three image type directories to cache)
- [x] Implement `--image-type` flag to select which cached directory (`Named_Boxarts`, `Named_Titles`, `Named_Snaps`) feeds the conversion pipeline
- [x] Implement local caching of downloaded images (all types cached independently)
- [x] Implement image validation (symlink resolution, format detection)
- [x] Implement filtering rules (romhacks, pirate, Virtual Console)

### Phase 2: Pocket Image Conversion — ✅ CONFIRMED WORKING ON HARDWARE (2026-04-02)
- [x] Implement Analogue Pocket `.bin` conversion (rotate -90°CCW, scale to 165px, BGRA32, header)
- [x] Implement DAT file parser for CRC32 ↔ game name mapping
- [x] Write per-game `.bin` files to `System/Library/Images/<platform_id>/` (e.g. `pce/`, `gba/`)
- [x] Implement fuzzy matching for DAT lookups
- [x] Support multiple `--dat-file` flags with per-console auto-detection
- [x] Physical-cart-only filtering — `--physical-only` (default); scans `Assets/<console>/common/` for ROM files, filters CRC lookup to carts only; `--include-roms` to opt out
- [x] Fixed `cmd_convert_only` to support `--use-pocket-db` and `--physical-only`
- [x] Fixed `list.bin` CRC field: read from offset `+4` (ROM CRC32), NOT `+8`
- [x] Fixed directory name: use `platform_ids[]` from `core.json` (e.g. `pce/`), NOT display shortname (e.g. `PC Engine/`)
- [x] Confirmed working: PCE box art displays in Library on Analogue Pocket hardware

### Phase 3: Duo Support — ✅ CONFIRMED WORKING ON HARDWARE (2026-04-03)
- [x] Implement `list.bin` parser for Duo (`parse_duo_played_games`, `build_duo_db_lookup`)
- [x] Discover that Duo uses same per-game `.bin` file approach as Pocket (not a single `_thumbs.bin`)
- [x] Implement correct Duo output: individual CRC-named `.bin` files in `pce/` and `pcecd/`
- [x] Determine Duo image format difference: **no pre-rotation**, header `(stored_w, stored_h)` vs Pocket's `(stored_h, stored_w)`
- [x] Fix `physical_only` filter for Duo (Duo has no ROM assets, always physical)
- [x] Add early-exit guard for unsupported consoles on Duo (GBA/NGP skip cleanly)
- [x] Confirmed working: PCE and PCECD box art displays correctly in Library on Duo hardware (firmware 1.5)

### Phase 4: Polish
- [x] Implement `--force` re-convert
- [x] TUI output: per-game match lines, live progress bar, download progress, per-console summary
- [ ] Implement `--dry-run` mode
- [ ] Populate `special_cases.json` with discovered edge cases
- [x] Update `.gitignore` for Python artifacts (`__pycache__/`, `.pyc`, cache dirs)

## How to Update This File

When a task is completed or its status changes, update the checkbox in **this file** (`phase-tracker.md`) and the matching entry in **`status.md`** (Phase Status table).
