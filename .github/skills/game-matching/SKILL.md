---
name: game-matching
description: "Game identification and thumbnail matching logic. Use when debugging missing thumbnails, working on CRC32 lookups, fuzzy name matching, the physical-cart filter, or special_cases.json redirects."
---

# Game Matching & Image Identification

## Output Filename = CRC32 ⚠️ CRITICAL

On the Analogue Pocket, each library image file is named `<crc32>.bin` where the CRC32 is sourced from `System/Played Games/list.bin` offset `+4` for that game. This is the ROM file CRC32 for most consoles.

**Do not** use offset `+8` (secondary hash — earlier versions of this tool had this bug).

---

## `list.bin` Entry Layout

Each entry in `System/Played Games/list.bin`:

| Offset | Field | Description |
|--------|-------|-------------|
| `+0` | u16 LE | Entry size (including this field) |
| `+2` | u16 LE | Flags — upper byte = system ID |
| `+4` | u32 LE | **ROM file CRC32** ← used as image filename |
| `+8` | u32 LE | Secondary hash (unknown purpose — NOT used for image lookup) |
| `+12` | u32 LE | Game database index |
| `+16` | NUL-terminated UTF-8 | Game name as displayed in the Library |

Full format specification: `.github/skills/binary-formats/SKILL.md`.

### Verification Example (Bonk's Adventure, PCE)

| Field | Value |
|---|---|
| ROM file | `Bonk's Adventure (USA).pce` (384 KB) |
| CRC32 of ROM | `599ead9b` |
| `list.bin` offset `+4` | `599ead9b` ✅ matches |
| Image filename | `599ead9b.bin` |
| `list.bin` offset `+8` | `6aa69a8b` ← NOT used |

### GBA Note

For GBA, `list.bin` offset `+4` = No-Intro ROM CRC32 (e.g. Advance Wars 2 = `5ad0e571`). Use `--use-pocket-db` (default) rather than GoodGBA CRC32 values — they differ.

---

## Pocket System IDs (from firmware 2.5)

| System ID byte | Console | Key |
|---|---|---|
| `0x02` | Game Boy Advance | `gba` |
| `0x06` | Neo Geo Pocket / Color | `ngp` |
| `0x07` | PC Engine / TurboGrafx-16 | `pce` |
| `0x08` | PC Engine CD | `pcecd` (unverified placeholder) |

---

## Fuzzy Matching (`match_game_to_crc()`)

The libretro thumbnail filename must be matched to an entry in the CRC lookup. Four strategies are tried in order, applied after `_apply_libretro_substitution()` on both sides:

**Strategy 1 — Exact match**
Normalize both game name and DAT/lookup key with libretro character substitution, compare exactly.

**Strategy 2 — Case-insensitive match**
Same as strategy 1 but case-folded.

**Strategy 3 — Strip region tags**
Remove `(USA)`, `(Japan)`, `(Europe)`, `(World)`, etc. from the libretro stem and compare base names.

**Strategy 4 — Subtitle separator normalization**
The Pocket firmware stores names with `: ` as the subtitle separator (e.g. `"Advance Wars 2: Black Hole Rising"`). After libretro substitution, `:` → `_`. But libretro filenames use ` - ` (e.g. `"Advance Wars 2 - Black Hole Rising (USA)"`). Strategy 4 normalizes ` - ` → `_ ` in the libretro key before comparing, with exact, case-insensitive, and base-title variants.

---

## Libretro Character Substitution

Characters in game names that are replaced with `_` to match libretro-thumbnails filenames:

```
& * / : ` < > ? \ | "  →  _
```

Applied by `_apply_libretro_substitution()` in the code.

---

## Filtering Rules

Games matching these patterns are skipped before any match attempt:

| Pattern | Match | Reason |
|---|---|---|
| Romhacks | `\[(Hack|T-)` or `(Hack)` in name | Modified ROMs have no DAT entry |
| Pirate | `(Pirate)` in name | Unlicensed copies |
| Virtual Console | `Virtual Console` substring | Re-releases, not original hardware |

Additional per-console skip patterns are loaded from `special_cases.json`.

---

## `special_cases.json`

Located at the repo root. Keyed by console (`pce`, `pcecd`, `gba`, `ngp`). Each entry:

```json
{
  "pce": {
    "skip": ["regex pattern to skip"],
    "redirect": {
      "Old Libretro Name": "Correct Libretro Name"
    }
  }
}
```

- **`skip`** — Regex patterns; matching game names are excluded entirely.
- **`redirect`** — Remap a libretro thumbnail filename to a different one before lookup. Use for entries that have been renamed or use a non-standard title.

---

## Physical-Cart-Only Mode

By default the script generates images only for **physical cartridges** — games present in `list.bin` that have no matching ROM file in `Assets/<console>/common/`.

**How it works:**
1. `get_rom_game_names(sd_root, console_key)` — scans `Assets/<console>/common/` for ROM files:
   - PCE: `.pce`, `.sgx`
   - PCECD: `.cue`, `.m3u`, `.chd`
   - GBA: `.gba`
   - NGP: `.ngp`, `.ngc`
2. `get_physical_cart_crcs(sd_root, console_key)` — returns CRC32s from `list.bin` whose game names do **not** match any ROM file
3. The CRC lookup is filtered to only those CRCs before `process_console()` runs

If `list.bin` is missing, the script warns and processes all games (equivalent to `--include-roms`).

---

## Symlink-Text Files

Some `.png` entries in libretro-thumbnails are plain text files containing a relative path to the actual image (not real OS symlinks). `validate_image()` detects these (file < 1 KB, content is a relative path) and resolves them transparently.

---

## CRC Source: Pocket DB vs DAT File

| Source | Flag | Best for |
|---|---|---|
| Pocket `list.bin` (default) | *(default — no flag needed)* | Any region, any console — exact filenames the firmware expects |
| No-Intro DAT file | `--dat-file <path>` | Batch processing without SD card access |

When both are specified, DAT file takes precedence for consoles it covers; Pocket DB fills the rest.

**Known limitation:** Game names in `list.bin` use `: ` as subtitle separator and omit region tags. Strategy 4 fuzzy matching handles most cases, but edge cases can be added to `special_cases.json` redirects.
