---
name: hardware-testing
description: "Hardware test results and procedures for Analogue Pocket and Duo. Use when verifying hardware behavior, debugging image display issues, or running diagnostic scripts."
allowed-tools: shell
---

# Hardware Testing

Tracks hardware test procedures, confirmed results, and open questions for the Analogue Pocket and Duo.

---

## Confirmed Results

### GG (Game Gear) on Analogue Pocket — ✅ FULLY CONFIRMED 2026-04-14

- **Library path:** `System/Library/Images/gg/`
- **Image filename:** CRC32 from `list.bin` offset `+4` (lowercase hex) — same mechanism as PCE/GBA
- **Format:** Same as all Pocket formats — 90°CCW pre-rotated, 165px target height (post-rotation), BGRA32
- **gg_thumbs.bin:** Firmware-managed cache, rebuilt from `.bin` files in `gg/` on boot. Do NOT write it manually.
- **System ID:** `0x03` in Pocket `list.bin` flags (upper byte) — verified with physical cartridges
- **Confirmed on hardware:** Box art displays correctly in Library on Pocket firmware 2.5 with physical cartridges:
  - Ax Battler: A Legend of Golden Axe (`663bcf8a.bin`)
  - Shining Force II: The Sword of Hajya (`a6ca6fa9.bin`)
- **Note:** libretro-thumbnails drops "II" from "Shining Force II: The Sword of Hajya" → matched via `special_cases.json` redirect

### PCE (PC Engine / TurboGrafx-16) — ✅ FULLY CONFIRMED 2026-04-02

- **Library path:** `System/Library/Images/pce/` (= `platform_ids: ["pce"]` from `agg23.PC Engine/core.json`)
- **Image filename:** CRC32 of the ROM file (lowercase hex) — from `list.bin` offset `+4`
  - Example: `Bonk's Adventure (USA).pce` CRC32 = `599ead9b` → file named `599ead9b.bin`
- **Format:** 90°CCW pre-rotated, 165px target height (post-rotation), BGRA32, portrait (width < height)
- **pce_thumbs.bin:** Firmware-managed cache. The firmware rebuilds it from `.bin` files in `pce/` on boot. Do NOT write it manually.
- **Confirmed on hardware:** Box art displays correctly in Library > Game Detail view (Pocket firmware 2.5+, agg23.PCEngine OpenFPGA core)

### PCE + PCECD on Analogue Duo — ✅ FULLY CONFIRMED 2026-04-03

- **Library paths:** Same as Pocket — `System/Library/Images/pce/` and `System/Library/Images/pcecd/`
- **Image filename:** CRC32 from Duo's `list.bin` offset `+4` (may differ from No-Intro CRCs — always use the Duo's own `list.bin`)
- **Format differs from Pocket:** No pre-rotation; header = `(stored_w, stored_h)` not `(stored_h, stored_w)`
  - Duo firmware renders stored data directly (no 90°CW hardware rotation)
- **pce_thumbs.bin / pcecd_thumbs.bin:** Also firmware-managed on the Duo — rebuilt from per-game `.bin` files on boot
- **Confirmed on hardware:** PCE and PCECD box art displays correctly in Library on Duo firmware 1.5

### Historical mistakes (now resolved)
- ❌ Files written to `PC Engine/` — firmware does NOT look there; must use `pce/` (platform_id, not shortname)
- ❌ CRC read from `list.bin[+8]` — wrong field; `list.bin[+4]` is the ROM CRC32
- ❌ Manual `pce_thumbs.bin` generation — not needed; firmware manages this file automatically
- ❌ Pocket-format images written to Duo — causes horizontal stripe garbling due to header `(h, w)` mismatch; Duo needs `(w, h)`

---

## Open Questions / Items to Verify on Hardware

1. **GBA library support** — GBA images at `System/Library/Images/gba/` are implemented but not yet hardware-tested on Pocket. Use `--console gba`. The CRC should come from `list.bin[+4]` (No-Intro ROM CRC32) — same mechanism as PCE.

2. **Neo Geo Pocket Color (NGP)** — NGPC images at `System/Library/Images/ngp/` are implemented but not yet hardware-tested. Use `--console ngp`. System ID `0x06` covers both NGP and NGPC games on the Pocket.

---

## Hardware Test Procedure for New Formats

Step-by-step instructions for testing a new `.bin` format or path:

1. Run `python analogue_image_gen.py "E:\" convert-only --console <console> --use-pocket-db --include-roms --force`
2. Verify files exist: `Get-ChildItem "E:\System\Library\Images\<platform_id>"`
3. Insert SD card into Pocket and open Library
4. Navigate to a game → Game Detail view and observe if box art appears
5. Record result here and update `.github/agents/phase-tracker.md`
