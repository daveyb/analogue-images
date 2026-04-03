---
name: workflow
description: "Development workflow for analogue-image-gen. Use when setting up the project, running the script, understanding CLI options, debugging test failures, or interpreting TUI output."
allowed-tools: shell
---

# Development Workflow

## Setup

```powershell
pip install -r requirements.txt
```

---

## Running Tests

```powershell
$env:PYTHONIOENCODING="utf-8"; python scripts/test_image_conversion.py
# 48 tests pass normally; up to 56 when SD card pce/ files and firmware-generated pce_thumbs.bin are present
```

The test suite is safe to run without an SD card — SD card tests skip gracefully.

---

## Standard Workflows

```powershell
# Auto mode (download + convert) for all consoles
python analogue_image_gen.py "E:\"

# Convert-only from cache (most common during development)
python analogue_image_gen.py "E:\" convert-only --console pce

# Force re-convert all (e.g. after a code change)
python analogue_image_gen.py "E:\" convert-only --console pce --force

# All consoles at once
python analogue_image_gen.py "E:\" convert-only --console all

# Download to cache only (no SD card required)
python analogue_image_gen.py download-only --console gba

# List all available game names from cache
python analogue_image_gen.py list-games --console pce

# Dry run — show what would be written without writing
python analogue_image_gen.py "E:\" convert-only --dry-run
```

> ⚠️ **Before each hardware test**, confirm SD card state:
> ```powershell
> Get-ChildItem "E:\System\Library\Images\pce"   # should contain CRC-named .bin files
> ```

The script is **idempotent** — running it twice produces the same result. Already-converted files are skipped unless `--force` is used.

---

## CLI Arguments

| Argument | Default | Description |
|---|---|---|
| `sd_card` (positional) | — | Path to the Analogue SD card root (required for auto/convert-only) |
| `--console` | `all` | Console(s): `pce`, `pcecd`, `gba`, `ngp`, or `all` |
| `--image-type` | `boxart` | Image type: `boxart`, `title`, or `snap` |
| `--device` | auto-detect | Force device type: `pocket` or `duo` |
| `--dat-file` | none | Path to No-Intro DAT file for CRC32 name matching |
| `--no-pocket-db` | — | Disable reading CRCs from the Pocket's `list.bin` (Pocket DB is on by default) |
| `--include-roms` | — | Process ROM-backed games in addition to physical carts |
| `--cache-dir` | `~/.analogue-image-gen/cache/` | Local cache directory |
| `--force` | false | Re-download and re-convert even if files are cached/present |
| `--dry-run` | false | Show what would be done without writing any files |
| `-v` / `-vv` | WARNING | Increase verbosity to INFO / DEBUG |

### Pocket DB default

`--use-pocket-db` is the default. The Pocket's `list.bin` is always read to source CRC32 identifiers (exact filenames the firmware expects). Use `--no-pocket-db` to disable this and fall back to name-based filenames (not recognised by firmware without a `--dat-file`).

### Physical-cart vs ROM mode

By default the script generates images only for **physical cartridge games**: games that appear in `list.bin` but have no matching ROM file in `Assets/<console>/common/`. Use `--include-roms` to generate images for all games in the CRC lookup.

---

## Logging Levels

| Level | Flag | Output |
|---|---|---|
| WARNING | (default) | Errors, skipped files, important warnings |
| INFO | `-v` | Progress updates, download/conversion counts |
| DEBUG | `-vv` | Per-file details, HTTP requests, binary format details |

---

## TUI Output

When stdout is a TTY the script renders compact, overwrite-in-place progress output:

```
Pocket DB  GBA:2  NGP:7  PCE:11

▶ PCE  (11 targets)
  ✓  599ead9b  Bonk's Adventure                        ←  Bonk's Adventure (USA)
  ·  52c7ce6e  Military Madness                        ←  Military Madness (USA)
  [████████████████████] 541/541  Ys Book I & II
  PCE     11 ✓  530 no match  158 filtered

  TOTAL  13 ✓  5682 no match  422 filtered
```

| Symbol | Meaning |
|---|---|
| `✓` | Newly converted |
| `·` | Already up-to-date (skipped) |
| `?` | Dry-run (would be written) |
| `✗` | Conversion failed |

Progress bars and match lines are no-ops when piped (non-TTY), so the output is clean in CI/log files.

---

## Error Handling

- **Network errors** — Retry up to 3 times with exponential backoff (2 s, 4 s, 8 s).
- **Individual image failures** — Log and continue; do not abort the batch.
- **Missing/corrupt images** — Skip with a warning.
- **SD card not writable** — Fail early with a clear error.
- **Unknown device** — Require `--device pocket` or `--device duo`.

---

## Caching

Downloaded archives are extracted to `~/.analogue-image-gen/cache/` (override with `--cache-dir`):

```
cache/
  {repo_name}/
    Named_Boxarts/
    Named_Titles/
    Named_Snaps/
```

All three image types are cached from a single ZIP download. Subsequent runs with a different `--image-type` hit the cache without re-downloading.

GitHub ZIP archives for large repos (GBA ~6000 images) can exceed GitHub's 20-minute timeout. See `create-local-archive.md` for the git-bundle workaround.
