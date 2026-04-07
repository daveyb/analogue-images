# Copilot Instructions — analogue-images

## Repository Overview

Single-file Python CLI tool (`analogue_image_gen.py`) that downloads box art from
[libretro-thumbnails](https://github.com/libretro-thumbnails/libretro-thumbnails),
converts the images into the Analogue Pocket/Duo proprietary `.bin` format, and writes
them to an Analogue SD card's `System/Library/Images/<console>/` directory.

**Supported consoles / devices:**

| Console key | libretro repo | Pocket | Duo |
|-------------|--------------|--------|-----|
| `pce`   | `NEC_-_PC_Engine_-_TurboGrafx_16` | ✅ | ✅ |
| `pcecd` | `NEC_-_PC_Engine_CD_-_TurboGrafx-CD` | ❌ | ✅ |
| `gba`   | `Nintendo_-_Game_Boy_Advance` | ✅ | ❌ |
| `ngp`   | `SNK_-_Neo_Geo_Pocket_Color` | ✅ | ❌ |

---

## Repository Structure

```
analogue_image_gen.py   # Entire application — ~2 700 lines
requirements.txt        # Pillow>=10, requests>=2.28
special_cases.json      # Per-console skip/redirect overrides (repo root)
scripts/
  test_image_conversion.py   # 48-56 unit tests (run without SD card)
  read_list_bin.py            # Diagnostic: dump list.bin contents
  generate_test_bins.py       # Generate reference .bin files for hardware testing
CHANGELOG.md            # Keep-a-changelog format; drives auto-release
.github/
  workflows/release.yml       # Auto-creates GitHub releases on push to main
  scripts/create_release.py   # CHANGELOG parser + gh CLI release logic
  skills/                     # Specialist agent skill files (see below)
```

---

## Skills (use these before coding)

Load a skill when working in its area — each file contains precise specs and
confirmed hardware data that supersedes guesswork.

| Skill name | When to use |
|------------|-------------|
| `workflow` | Setup, CLI options, test runner, TUI output |
| `binary-formats` | `.bin` header layout, `list.bin` format, `pce_thumbs.bin` |
| `device-formats` | Pocket vs Duo conversion pipeline, SD card directory structure |
| `game-matching` | CRC32 lookup, fuzzy matching, `special_cases.json`, physical-cart filter |
| `hardware-testing` | Hardware test results and reproduction procedures |

---

## Setup & Tests

```bash
pip install -r requirements.txt
# Run all unit tests (no SD card required)
python scripts/test_image_conversion.py
```

48 tests always pass; 8 more run only when SD card PCE files are present. Do
**not** delete or weaken any existing test.

---

## Key Architecture Points

### Single-file layout

All logic lives in `analogue_image_gen.py`. The file is large (~2700 lines);
use section comments (e.g. `# ---- Image conversion ----`) to navigate.

### Image conversion pipeline

**Pocket:**
```
Load PNG/JPEG → rotate(90°CCW, PIL rotate(90)) → scale to h=165px (post-rotation)
→ BGRA32 pixel data → header(stored_h, stored_w) + pixel bytes
```
**Duo:**
```
Load PNG/JPEG → scale to h=165px (no rotation)
→ BGRA32 pixel data → header(stored_w, stored_h) + pixel bytes
```

The Pocket header bytes `0x04–0x05` = display width = `stored_h`.
The Pocket header bytes `0x06–0x07` = display height = `stored_w`.
The Duo reverses these. See `device-formats` skill for full details.

### Output filename = CRC32 from `list.bin` offset `+4`

⚠️ **Critical bug trap**: image filenames are the ROM file CRC32 from
`list.bin` at byte offset `+4`, NOT offset `+8`. Using `+8` (a secondary hash)
produces wrong filenames and no images appear on the device. This was fixed in
an earlier session; do not revert it.

### Device detection

Auto-detected from the SD card root by the presence of
`Analogue_Pocket.json` or `Analogue_Duo.json`. Override with `--device pocket`
or `--device duo`.

### `list.bin` flags differ between devices

- **Pocket**: `flags >> 8` = system ID (`0x02`=GBA, `0x06`=NGP, `0x07`=PCE)
- **Duo**: full `flags` u16 = game type (`0x0000`=PCE HuCard, `0x0100`=PCECD)

Use `parse_pocket_played_games()` for Pocket, `parse_duo_played_games()` for
Duo. Mixing them silently misclassifies games.

### Fuzzy name matching — four strategies

`match_game_to_crc()` tries these in order:
1. Exact match (after libretro char substitution: `& * / : \` < > ? \ | "` → `_`)
2. Case-insensitive
3. Strip region tags `(USA)`, `(Japan)`, etc.
4. Subtitle separator normalisation (`: ` in firmware name → `_`; ` - ` in
   libretro name → `_ `)

### Physical-cart filter (default behaviour)

By default the script only generates images for physical cartridge games — games
in `list.bin` that have **no** matching ROM file in `Assets/<console>/common/`.
Use `--include-roms` to process all games.

### `special_cases.json`

Located at the repo root. Keyed by console (`pce`, `pcecd`, `gba`, `ngp`).

```json
{
  "pce": {
    "skip": ["regex pattern"],
    "redirect": { "Libretro Name In Cache": "Actual Libretro Name" }
  }
}
```

`skip` patterns are matched case-insensitively against the libretro filename
stem. `redirect` maps a wrong name to the correct one before lookup.

---

## Release Workflow

Pushes to `main` trigger `.github/workflows/release.yml`, which calls
`.github/scripts/create_release.py`:

- **Versioned release**: if the topmost dated `CHANGELOG.md` section (e.g.
  `## [0.4.0] - 2026-04-05`) has no matching GitHub tag, a published release is
  created and any drafts for that version are deleted.
- **Draft release**: if `## [Unreleased]` has content, a draft tagged
  `v<inferred-version>-draft-<YYYYMMDD-HHmm>` is created; prior drafts for that
  inferred version are replaced.

SemVer is inferred from the highest-priority change type under `[Unreleased]`:
`Removed` → major, `Added`/`Deprecated` → minor, everything else → patch.

**Always update `CHANGELOG.md`** under `## [Unreleased]` when making
user-visible changes.

---

## Common Pitfalls & Errors Encountered

| Pitfall | Details |
|---------|---------|
| Wrong CRC offset in `list.bin` | Use offset `+4` (ROM CRC), not `+8`. Using `+8` produces wrong filenames silently. |
| Writing `pce_thumbs.bin` manually | Don't. Both Pocket and Duo firmware rebuild it from the individual `.bin` files on boot. Writing it manually either has no effect or corrupts the cache. |
| Pocket format written to Duo | Without pre-rotation the header says `(h, w)` but stored data is `(w, h)`. Firmware renders as thin horizontal stripes. |
| Landscape output (no pre-rotation) | Pocket firmware rejects landscape `.bin` files and shows `Image: —` in Game Detail view. |
| Wrong output directory name | Directory must be `platform_id` (e.g. `pce`), not the display name (`PC Engine`). Case-insensitive on FAT32 but use lowercase. |
| `pcecd` on Pocket | The Pocket has no CD unit; `pcecd` is Duo-only. The script skips PCECD processing with an explicit message when targeting a Pocket. |
| GitHub archive timeout | Large repos (GBA ≈6 000 images) can exceed GitHub's 20-minute download limit. Use `convert-only` once the cache is partially populated, or follow `create-local-archive.md` for a git-bundle workaround. |
| JPEG masquerading as PNG | Some libretro-thumbnails entries are JPEGs with a `.png` extension. `validate_image()` handles these; a warning is logged but the file is still used. |
| Symlink-text files | Some `.png` entries in libretro-thumbnails are small text files containing a relative path (not OS symlinks). `validate_image()` detects and resolves these transparently. |

---

## Duo CRC32 Note

Duo CRC32 values in `list.bin` may differ from No-Intro database CRCs.
Always read CRCs from the Duo's own `list.bin` via `build_duo_db_lookup()`;
do not rely on a No-Intro DAT file for Duo targets.

| Game | Duo CRC32 | No-Intro CRC32 |
|------|-----------|----------------|
| Ninja Spirit | `de8af1c1` | `6c2052d5` |
| Military Madness | `93f316f7` | `52c7ce6e` |

---

## Verified CRC32 Sanity-Check Values

| Console | Game | CRC32 |
|---------|------|-------|
| PCE | Bonk's Adventure (USA) | `599ead9b` |
| PCE | Ninja Spirit (Pocket) | `6c2052d5` |
| GBA | Advance Wars 2 | `5ad0e571` |
| GBA | Fire Emblem: Sacred Stones | `a47246ae` |
