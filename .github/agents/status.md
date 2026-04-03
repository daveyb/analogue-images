# Development Status & Open Questions

## Phase Status

| Phase | Status |
|---|---|
| Phase 1: Core infrastructure & download | ✅ Complete |
| Phase 2: Pocket image conversion | ✅ Complete — PCE **confirmed working on hardware** (2026-04-02) |
| Phase 3: Duo support | ✅ Complete — PCE + PCECD **confirmed working on hardware** (2026-04-03) |
| Phase 4: Polish (dry-run, progress, force, README) | 🟡 Partial — `--force` done; TUI output done; `--dry-run` not yet implemented |
| GBA console support | ✅ Complete — files written to SD card; hardware test pending |
| NGP console support | ✅ Complete — files written to SD card; hardware test pending |

---

## Development Plan

### Phase 1: Core Infrastructure ✅
- [x] `argparse` CLI with positional `sd_card` argument
- [x] Device auto-detection (`Analogue_Duo.json` / `Analogue_Pocket.json`)
- [x] libretro-thumbnails archive download and extraction
- [x] `--image-type` flag
- [x] Local image caching (all three types)
- [x] Image validation (symlink resolution, format detection)
- [x] Filtering rules (romhacks, pirate, Virtual Console)

### Phase 2: Pocket Image Conversion ✅
- [x] Pocket `.bin` conversion (rotate, scale, BGRA32, header)
- [x] No-Intro DAT file parser for CRC32 ↔ game name mapping
- [x] Per-game `.bin` files written to `System/Library/Images/<platform_id>/`
- [x] Fuzzy matching (4 strategies including subtitle normalization)
- [x] Physical-cart-only filtering (`--include-roms` to opt out)
- [x] `--use-pocket-db` (reads `list.bin` directly) — now the default behavior
- [x] `--no-pocket-db` to opt out of Pocket DB
- [x] GBA support added (fully promoted — removed "not recommended" caveat)
- [x] NGP/NGPC support added (new console)
- [x] TUI output: per-game match lines, live progress bar, download progress, per-console summary

### Phase 3: Duo Support ❌
- [ ] Reverse-engineer `_thumbs.bin` format using test patterns on real hardware
- [ ] Implement `_thumbs.bin` generation
- [ ] Test with actual Analogue Duo hardware

### Phase 4: Polish 🟡
- [ ] `--dry-run` mode (wired up in pipeline but not fully implemented)
- [ ] Populate `special_cases.json` with discovered edge cases
- [ ] Update `README.md` with full documentation

---

## Open Questions / Hardware Testing Needed

1. **GBA library images on Pocket** — Files written to `System/Library/Images/gba/`. Do they display in the Library? Hardware test pending (firmware 2.5 expected to support it).

2. **NGP library images on Pocket** — Files written to `System/Library/Images/ngp/`. Same question as GBA. Hardware test pending.

3. **Pocket PCECD system ID** — `0x08` is an unverified placeholder. Needs hardware confirmation.

4. **Duo `_thumbs.bin` internal format** — Pixel format, image dimensions, indexing, compression all unknown. Needs a populated file (after a game is played on the Duo and thumbnails are generated) for reverse-engineering.

5. **Duo game ID mapping** — `list.bin` offset `+12` = game database index (e.g. Columns=65, Ninja Spirit=238). Likely an index into thumbnail positions within `_thumbs.bin`. Critical for Duo support.

6. **Duo `_thumbs.bin` header at offset 0x04** — Value `0x0000CE1C` (52764) present in both empty thumbs files. Meaning unknown (checksum? max entry count? reserved?).

7. **Duo firmware updates** — Future Duo firmware (currently v1.5) may change the `_thumbs.bin` format or add per-game `.bin` support similar to the Pocket.

8. **Maximum thumbnail dimensions on Duo** — The Duo outputs to a TV. Library thumbnails may need a different resolution than the Pocket's 165px-height images.

---

## Helper Scripts

| Script | Purpose |
|---|---|
| `scripts/test_image_conversion.py` | Unit + SD card tests: `.bin` pipeline, `pce_thumbs.bin` format (48+ tests) |
| `scripts/read_list_bin.py` | Parse and display `list.bin` contents (game names, CRC32s, system IDs) |
| `scripts/generate_test_bins.py` | Generate solid-color test `.bin` files for hardware verification |

---

## Reference Files

| File | Contents |
|---|---|
| `.github/copilot/binary-formats.md` | Complete binary format specs: Pocket `.bin`, Duo `_thumbs.bin`, `list.bin` |
| `.github/copilot/hardware-testing.md` | Hardware test results, verified values, open questions |
| `.github/copilot/phase-tracker.md` | Per-task checkbox status; instructions for updating |
