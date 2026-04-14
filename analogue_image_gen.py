#!/usr/bin/env python3
"""
Analogue Duo / Pocket — Library Image Generator

Downloads thumbnail images for PC Engine (TurboGrafx-16), PC Engine CD
(TurboGrafx-CD), Game Boy Advance, and Neo Geo Pocket Color games from the
libretro-thumbnails repositories, converts them into Analogue OS's proprietary
library image format, and writes them to an Analogue device's SD card.

By default only generates images for physical cartridge games — games present
in the device's played-games database (list.bin) that do NOT have a
corresponding ROM file in the SD card's Assets directory.  Use --include-roms
to also generate images for ROM/downloaded games.

Supports Analogue Pocket per-game .bin images with CRC32-based filenames
(via No-Intro DAT files or --use-pocket-db) and Analogue Duo thumbnail
generation (WIP).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import shutil
import struct
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
import zipfile
import zlib
from pathlib import Path
from typing import Optional

try:
    from PIL import Image
except ImportError:
    Image = None

try:
    import requests
except ImportError:
    requests = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TOOL_NAME = "analogue-image-gen"
VERSION = "0.4.3"

# libretro-thumbnails repository info
CONSOLE_REPOS = {
    "gg": "Sega_-_Game_Gear",
    "gba": "Nintendo_-_Game_Boy_Advance",
    "ngp": "SNK_-_Neo_Geo_Pocket_Color",
    "pce": "NEC_-_PC_Engine_-_TurboGrafx_16",
    "pcecd": "NEC_-_PC_Engine_CD_-_TurboGrafx-CD",
}

GITHUB_ARCHIVE_URL = (
    "https://github.com/libretro-thumbnails/{repo}/archive/refs/heads/master.zip"
)
GITHUB_RAW_URL = "https://raw.githubusercontent.com/libretro-thumbnails/{repo}/master/{directory}/{filename}"

# Image type → libretro directory mapping
IMAGE_TYPE_DIRS = {
    "boxart": "Named_Boxarts",
    "title": "Named_Titles",
    "snap": "Named_Snaps",
}

# Default cache directory
DEFAULT_CACHE_DIR = Path.home() / ".analogue-image-gen" / "cache"

# Analogue Pocket .bin magic header
POCKET_BIN_MAGIC = bytes([0x20, 0x49, 0x50, 0x41])  # " IPA"
POCKET_BIN_TARGET_HEIGHT = 165

# pce_thumbs.bin format constants (the bundle file the Pocket firmware reads
# for PCE Library list-view thumbnails)
PCE_THUMBS_MAGIC = bytes([0x02, 0x46, 0x54, 0x41])  # "\x02FTA" version 2
PCE_THUMBS_HASH_SLOTS = 8192  # number of entries in the CRC hash table
PCE_THUMBS_HASH_ENTRY_SIZE = 8  # bytes per hash table entry
PCE_THUMBS_HEADER_SIZE = (
    12 + PCE_THUMBS_HASH_SLOTS * PCE_THUMBS_HASH_ENTRY_SIZE
)  # 65548
# Thumbnail height for images embedded in pce_thumbs.bin.
# Hardware testing confirmed that 165 px (= POCKET_BIN_TARGET_HEIGHT) displays
# on the Pocket list view; the previously-tried 121 px did not show anything.
PCE_THUMBS_THUMB_HEIGHT = 165

# Device identification files
DEVICE_FILES = {
    "duo": "Analogue_Duo.json",
    "pocket": "Analogue_Pocket.json",
}

# Per-console SD card output directories for .bin image files.
# Used by both Pocket and Duo devices; entries are keyed by platform_id per the
# Analogue developer docs: https://www.analogue.co/developer/docs/library
# Device-specific notes:
#   gg, gba, ngp  — Pocket only (the Duo does not have cartridge slots for these)
#   pce           — Both Pocket (HuCard) and Duo (HuCard)
#   pcecd         — Duo only (the Pocket has no CD unit)
CONSOLE_IMAGE_DIRS = {
    "gg": Path("System") / "Library" / "Images" / "gg",
    "gba": Path("System") / "Library" / "Images" / "gba",
    "ngp": Path("System") / "Library" / "Images" / "ngp",
    "pce": Path("System") / "Library" / "Images" / "pce",
    "pcecd": Path("System") / "Library" / "Images" / "pcecd",
}

# Duo thumbs file paths per console
DUO_THUMBS_FILES = {
    "pce": Path("System") / "Library" / "Images" / "pce_thumbs.bin",
    "pcecd": Path("System") / "Library" / "Images" / "pcecd_thumbs.bin",
}

# ROM file locations and recognised extensions per console.
# Used to distinguish physical cartridge games (no file on SD card) from
# ROM/downloaded games (file present in Assets/<console>/common/).
CONSOLE_ROM_PATHS: dict[str, tuple[Path, frozenset[str]]] = {
    "gg": (Path("Assets") / "gg" / "common", frozenset({".gg"})),
    "gba": (Path("Assets") / "gba" / "common", frozenset({".gba", ".agb"})),
    "ngp": (Path("Assets") / "ngp" / "common", frozenset({".ngp", ".ngc"})),
    "pce": (Path("Assets") / "pce" / "common", frozenset({".pce", ".sgx"})),
    "pcecd": (Path("Assets") / "pcecd" / "common", frozenset({".cue", ".m3u", ".chd"})),
}

# Pocket played-games database system IDs (upper byte of the ``flags`` field
# in each list.bin entry).  Maps the system byte to a console key used
# throughout this tool.  IDs marked "verified" were confirmed by inspecting
# real list.bin data from a Pocket running firmware 2.5.
POCKET_SYSTEM_IDS = {
    0x01: "gb",  # Game Boy (unverified — placeholder)
    0x02: "gba",  # Game Boy Advance (verified: Advance Wars 2, FE: Sacred Stones)
    0x03: "gg",  # Game Gear (verified: Ax Battler, Shining Force II)
    0x04: "gbc",  # Game Boy Color (unverified — placeholder)
    0x06: "ngp",  # Neo Geo Pocket / Color (verified: Dark Arms, Dive Alert, etc.)
    0x07: "pce",  # PC Engine / TurboGrafx-16 (verified: Ninja Spirit, Military Madness, etc.)
}

# Duo played-games database flags → console key mapping.
# On the Duo the full ``flags`` u16 field encodes the game type, not the
# system ID.  Verified by inspecting a real Duo list.bin (firmware 1.5):
#   0x0000 = HuCard game     → pce
#   0x0100 = CD-ROM² game    → pcecd
DUO_CONSOLE_FLAGS: dict[int, str] = {
    0x0000: "pce",
    0x0100: "pcecd",
}

# Filtering regexes — compiled once
FILTER_ROMHACK = re.compile(r"(\[(Hack|T-)|\([\w\s,]*Hack)", re.IGNORECASE)
FILTER_VIRTUAL_CONSOLE = re.compile(r"Virtual Console", re.IGNORECASE)
FILTER_PIRATE = re.compile(r"\([\w\s,]*Pirate", re.IGNORECASE)

# Characters replaced with _ in libretro-thumbnails filenames
LIBRETRO_SPECIAL_CHARS = re.compile(r'[&*/:`<>?\\|"]')

# PNG magic bytes
PNG_MAGIC = bytes([137, 80, 78, 71, 13, 10, 26, 10])

# JPEG magic bytes (SOI marker)
JPEG_SOI = bytes([0xFF, 0xD8])
JPEG_EOI = bytes([0xFF, 0xD9])

# Maximum file size for a symlink-text file (bytes)
SYMLINK_TEXT_MAX_SIZE = 1024

# Network retry settings
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 2  # seconds

# Valid operating modes (besides default "auto")
VALID_MODES = {"download-only", "convert-only", "list-games", "clear-images"}

# DAT file console identification patterns
# Order matters: check pcecd before pce to avoid partial match on "PC Engine CD"
DAT_CONSOLE_PATTERNS = [
    ("gg", re.compile(r"Game\s*Gear", re.IGNORECASE)),
    ("gba", re.compile(r"Game\s*Boy\s*Advance", re.IGNORECASE)),
    ("ngp", re.compile(r"Neo\s*Geo\s*Pocket", re.IGNORECASE)),
    ("pcecd", re.compile(r"PC\s*Engine\s*CD|TurboGrafx[- ]CD", re.IGNORECASE)),
    ("pce", re.compile(r"PC\s*Engine(?!\s*CD)|TurboGrafx[- ]16", re.IGNORECASE)),
]

# Region tag pattern for fuzzy matching — strips "(USA)", "(Japan)", etc.
REGION_TAG_RE = re.compile(r"\s*\([^)]*\)")

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

logger = logging.getLogger(TOOL_NAME)


def configure_logging(verbosity: int) -> None:
    """Configure logging based on verbosity level (0=WARNING, 1=INFO, 2+=DEBUG)."""
    if verbosity >= 2:
        level = logging.DEBUG
    elif verbosity >= 1:
        level = logging.INFO
    else:
        level = logging.WARNING

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] %(message)s",
            datefmt="%H:%M:%S",
        )
    )
    logger.setLevel(level)
    logger.addHandler(handler)


# ---------------------------------------------------------------------------
# TUI helpers
# ---------------------------------------------------------------------------

_IS_TTY: bool = sys.stdout.isatty()
_BAR_W: int = 20


def _bar(n: int, total: int) -> str:
    """Unicode block progress bar, e.g. '████████░░░░░░░░░░░░'."""
    if total <= 0:
        return "░" * _BAR_W
    filled = int(_BAR_W * min(n, total) / total)
    return "█" * filled + "░" * (_BAR_W - filled)


def _trunc(s: str, n: int) -> str:
    """Truncate *s* to *n* chars, appending '…' if truncated."""
    return s if len(s) <= n else s[: n - 1] + "…"


def _tui_overwrite(text: str) -> None:
    """Overwrite the current terminal line (TTY only)."""
    if _IS_TTY:
        sys.stdout.write(f"\r{text}\033[K")
        sys.stdout.flush()


def _tui_clear() -> None:
    """Clear the current terminal line (TTY only)."""
    if _IS_TTY:
        sys.stdout.write("\r\033[K")
        sys.stdout.flush()


def _tui_match(symbol: str, crc: str, name: str, libretro_stem: str) -> None:
    """Print a match line above the live progress bar.

    Clears the progress bar first so the match line is clean, then prints it
    permanently.  The caller is responsible for redrawing the bar afterwards.
    """
    _tui_clear()
    crc_col = f"{crc}  " if crc else " " * 10
    lr = _trunc(libretro_stem, 46)
    print(f"  {symbol}  {crc_col}{_trunc(name, 40):<40s}  ←  {lr}")


def _dl_progress(label: str, downloaded: int, total: int) -> None:
    """Render a compact download progress line (overwrites current line)."""
    mb_d = downloaded / 1_048_576
    if total:
        b = _bar(downloaded, total)
        pct = int(100 * downloaded / total)
        mb_t = total / 1_048_576
        _tui_overwrite(f"  ↓ {label}  [{b}]  {pct:3d}%  {mb_d:.1f}/{mb_t:.1f} MB")
    else:
        _tui_overwrite(f"  ↓ {label}  {mb_d:.1f} MB…")


def _tui_console_summary(console_key: str, stats: dict, dry_run: bool) -> None:
    """Print a compact one-line per-console summary."""
    parts: list[str] = []
    sym = "?" if dry_run else "✓"
    if stats["converted"]:
        parts.append(f"{stats['converted']} {sym}")
    if stats.get("already_exists"):
        parts.append(f"{stats['already_exists']} ·")
    if stats.get("no_dat_match"):
        parts.append(f"{stats['no_dat_match']} no match")
    if stats["skipped_filter"]:
        parts.append(f"{stats['skipped_filter']} filtered")
    if stats["failed"]:
        parts.append(f"{stats['failed']} ✗")
    if stats.get("removed_stale"):
        parts.append(f"{stats['removed_stale']} stale removed")
    print(f"  {console_key.upper():<6s}  " + "  ".join(parts))


# ---------------------------------------------------------------------------
# Special cases loader
# ---------------------------------------------------------------------------


def load_special_cases(path: Optional[Path] = None) -> dict:
    """Load the special_cases.json file.

    Returns a dict like::

        {
            "pce":   {"skip": [...], "redirect": {...}},
            "pcecd": {"skip": [...], "redirect": {...}},
        }
    """
    if path is None:
        path = Path(__file__).parent / "special_cases.json"
    if not path.is_file():
        logger.debug("No special_cases.json found at %s — using empty defaults", path)
        return {
            "pce": {"skip": [], "redirect": {}},
            "pcecd": {"skip": [], "redirect": {}},
        }
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    logger.debug("Loaded special cases from %s", path)
    return data


# ---------------------------------------------------------------------------
# Device detection
# ---------------------------------------------------------------------------


def detect_device(sd_root: Path) -> Optional[str]:
    """Detect the Analogue device type by looking for identification JSON files.

    Returns ``"duo"``, ``"pocket"``, or ``None`` if neither is found.
    """
    for device, filename in DEVICE_FILES.items():
        candidate = sd_root / filename
        if candidate.is_file():
            try:
                with open(candidate, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                product = data.get("product", "unknown")
                firmware = ""
                fw_section = data.get("firmware", {})
                if isinstance(fw_section, dict):
                    runtime = fw_section.get("runtime", {})
                    if isinstance(runtime, dict):
                        firmware = runtime.get("name", "")
                logger.info(
                    "Detected device: %s (product=%s, firmware=%s)",
                    device,
                    product,
                    firmware,
                )
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Found %s but failed to parse: %s", filename, exc)
            return device
    return None


# ---------------------------------------------------------------------------
# Pocket played-games database helpers
# ---------------------------------------------------------------------------


def parse_pocket_played_games(sd_root: Path) -> list[dict]:
    """Parse ``System/Played Games/list.bin`` from the Pocket SD card.

    Returns a list of game record dicts with keys:

    - ``name``        — Game name string as stored by the firmware
    - ``crc``         — CRC32 hex string (lowercase, 8 digits; matches save-file naming)
    - ``flags``       — Raw flags u16 (upper byte = system ID, lower byte unknown)
    - ``system_id``   — Upper byte of flags (see ``POCKET_SYSTEM_IDS``)
    - ``game_id``     — Firmware-internal game database index
    - ``console_key`` — Console key string (e.g. ``"pce"``) or ``None`` if unrecognised

    Returns an empty list if the file is missing or cannot be parsed.
    """
    list_bin = sd_root / "System" / "Played Games" / "list.bin"
    if not list_bin.is_file():
        logger.warning("Pocket played-games DB not found: %s", list_bin)
        return []

    try:
        with open(list_bin, "rb") as fh:
            data = fh.read()

        # Validate magic bytes (same format as Analogue Duo)
        magic = data[0:4]
        if magic != b"\x01FAT":
            logger.warning(
                "Unexpected magic in list.bin: %s (expected 01464154)",
                magic.hex(),
            )

        entry_count = struct.unpack_from("<I", data, 4)[0]
        # Offset table starts at byte 16 (after 4-byte magic, 4-byte entry
        # count, 4-byte unknown field, 4-byte first-entry offset).
        offsets = [
            struct.unpack_from("<I", data, 16 + i * 4)[0] for i in range(entry_count)
        ]

        games: list[dict] = []
        for off in offsets:
            entry_size = struct.unpack_from("<H", data, off)[0]
            flags = struct.unpack_from("<H", data, off + 2)[0]
            # offset +4: CRC32 of the ROM/asset file — this is what the firmware
            # uses for Library image filename lookup (matches field4, not field8).
            # offset +8: a secondary identifier (role TBD; was incorrectly used
            # as the image-lookup CRC in earlier versions of this tool).
            crc32 = struct.unpack_from("<I", data, off + 4)[0]
            game_id = struct.unpack_from("<I", data, off + 12)[0]
            name_bytes = data[off + 16 : off + entry_size]
            name = name_bytes.split(b"\x00")[0].decode("utf-8", errors="replace")

            system_id = flags >> 8
            console_key = POCKET_SYSTEM_IDS.get(system_id)

            games.append(
                {
                    "name": name,
                    "crc": f"{crc32:08x}",
                    "flags": flags,
                    "system_id": system_id,
                    "game_id": game_id,
                    "console_key": console_key,
                }
            )

        logger.info(
            "Parsed %d games from Pocket played-games DB (%s)",
            len(games),
            list_bin,
        )
        return games

    except (OSError, struct.error) as exc:
        logger.warning("Failed to parse Pocket played-games DB: %s", exc)
        return []


def build_pocket_db_lookup(sd_root: Path, console_key: str) -> dict[str, str]:
    """Build a game-name → CRC32 lookup from the Pocket's played-games database.

    This is an alternative to No-Intro DAT files.  The Pocket records the exact
    CRC32 it computed for each ROM, so filenames derived from this lookup will
    always match what the firmware expects — regardless of ROM region or version
    (e.g. Japanese PCE HuCards whose CRCs differ from the USA No-Intro entries).

    The keys are *libretro-substituted* game names (compatible with
    ``match_game_to_crc()``'s fuzzy matching).  Values are lowercase 8-digit
    CRC32 hex strings.

    Returns an empty dict if no entries for *console_key* are found.
    """
    games = parse_pocket_played_games(sd_root)
    lookup: dict[str, str] = {}
    for game in games:
        if game["console_key"] != console_key:
            continue
        # Apply libretro substitutions so the key is compatible with cached
        # image filenames (e.g. "&" → "_", while "'" and "-" are preserved).
        subst_name = _apply_libretro_substitution(game["name"])
        lookup[subst_name] = game["crc"]
        logger.debug("Pocket DB [%s]: %r → %s", console_key, game["name"], game["crc"])

    logger.info(
        "Built Pocket DB CRC lookup for %s: %d entries", console_key, len(lookup)
    )
    return lookup


def parse_duo_played_games(sd_root: Path) -> list[dict]:
    """Parse ``System/Played Games/list.bin`` from the Duo SD card.

    The binary format is identical to the Pocket's ``list.bin``, but the
    ``flags`` field has a different meaning:

    - Pocket: upper byte of flags = system ID (see ``POCKET_SYSTEM_IDS``)
    - Duo: full flags value = game type (see ``DUO_CONSOLE_FLAGS``)

    Returns a list of game record dicts with keys:

    - ``name``        — Game name string as stored by the firmware
    - ``crc``         — CRC32 hex string (lowercase, 8 digits)
    - ``flags``       — Raw flags u16
    - ``game_id``     — Firmware-internal game database index
    - ``console_key`` — ``"pce"`` or ``"pcecd"`` (or ``None`` if unrecognised flags)

    Returns an empty list if the file is missing or cannot be parsed.
    """
    list_bin = sd_root / "System" / "Played Games" / "list.bin"
    if not list_bin.is_file():
        logger.warning("Duo played-games DB not found: %s", list_bin)
        return []

    try:
        with open(list_bin, "rb") as fh:
            data = fh.read()

        magic = data[0:4]
        if magic != b"\x01FAT":
            logger.warning(
                "Unexpected magic in list.bin: %s (expected 01464154)",
                magic.hex(),
            )

        entry_count = struct.unpack_from("<I", data, 4)[0]
        offsets = [
            struct.unpack_from("<I", data, 16 + i * 4)[0] for i in range(entry_count)
        ]

        games: list[dict] = []
        for off in offsets:
            entry_size = struct.unpack_from("<H", data, off)[0]
            flags = struct.unpack_from("<H", data, off + 2)[0]
            crc32 = struct.unpack_from("<I", data, off + 4)[0]
            game_id = struct.unpack_from("<I", data, off + 12)[0]
            name_bytes = data[off + 16 : off + entry_size]
            name = name_bytes.split(b"\x00")[0].decode("utf-8", errors="replace")

            # Duo: map full flags value to console key
            console_key = DUO_CONSOLE_FLAGS.get(flags)

            games.append(
                {
                    "name": name,
                    "crc": f"{crc32:08x}",
                    "flags": flags,
                    "game_id": game_id,
                    "console_key": console_key,
                }
            )

        logger.info(
            "Parsed %d games from Duo played-games DB (%s)",
            len(games),
            list_bin,
        )
        return games

    except (OSError, struct.error) as exc:
        logger.warning("Failed to parse Duo played-games DB: %s", exc)
        return []


def build_duo_db_lookup(sd_root: Path, console_key: str) -> dict[str, str]:
    """Build a game-name → CRC32 lookup from the Duo's played-games database.

    Identical shape to ``build_pocket_db_lookup`` but uses the Duo's flag
    interpretation (``DUO_CONSOLE_FLAGS``) to identify game console.

    Returns an empty dict if no entries for *console_key* are found.
    """
    games = parse_duo_played_games(sd_root)
    lookup: dict[str, str] = {}
    for game in games:
        if game["console_key"] != console_key:
            continue
        subst_name = _apply_libretro_substitution(game["name"])
        lookup[subst_name] = game["crc"]
        logger.debug("Duo DB [%s]: %r → %s", console_key, game["name"], game["crc"])

    logger.info("Built Duo DB CRC lookup for %s: %d entries", console_key, len(lookup))
    return lookup


def _describe_duo_db_systems(games: list[dict]) -> str:
    """Return a compact summary of console keys present in a Duo played-games list.

    Example output: ``"PCE:8  PCECD:4"``
    """
    seen: dict[str, int] = {}
    for g in games:
        key = g["console_key"] or f"0x{g['flags']:04x}?"
        seen[key] = seen.get(key, 0) + 1
    parts = [f"{k.upper()}:{v}" for k, v in sorted(seen.items())]
    return "  ".join(parts) if parts else "(empty)"


def get_rom_game_names(sd_root: Path, console_key: str) -> set[str]:
    """Return libretro-substituted names of ROM files on the SD card for *console_key*.

    Scans ``Assets/<console>/common/`` for files with known ROM extensions and
    returns their stems after applying ``_apply_libretro_substitution()``, so
    the result is directly comparable with names from the played-games database.

    Returns an empty set if the directory does not exist or no ROM files are
    found (which most likely means the user has no ROMs for that console).
    """
    if console_key not in CONSOLE_ROM_PATHS:
        return set()
    rel_dir, extensions = CONSOLE_ROM_PATHS[console_key]
    rom_dir = sd_root / rel_dir
    if not rom_dir.is_dir():
        logger.debug("No ROM directory found for %s: %s", console_key, rom_dir)
        return set()
    names: set[str] = set()
    for f in rom_dir.iterdir():
        if f.is_file() and f.suffix.lower() in extensions:
            names.add(_apply_libretro_substitution(f.stem))
    logger.debug("Found %d ROM file(s) for %s in %s", len(names), console_key, rom_dir)
    return names


def get_physical_cart_crcs(sd_root: Path, console_key: str) -> "Optional[set[str]]":
    """Return the set of CRC32 values for physical cartridge games.

    A game is considered a physical cart if it appears in the device's
    played-games database (``list.bin``) but does **not** have a corresponding
    ROM file in ``Assets/<console>/common/``.

    Returns ``None`` if ``list.bin`` is unavailable (caller should fall back to
    processing all games and warn the user).  Returns an empty set if
    ``list.bin`` is available but no physical carts are found for the console.
    """
    games = parse_pocket_played_games(sd_root)
    if not games:
        return None  # list.bin missing or unreadable

    rom_names = get_rom_game_names(sd_root, console_key)
    cart_crcs: set[str] = set()
    rom_count = 0
    for game in games:
        if game["console_key"] != console_key:
            continue
        subst_name = _apply_libretro_substitution(game["name"])
        if subst_name in rom_names:
            logger.debug("ROM game (excluded from physical-only): %s", game["name"])
            rom_count += 1
        else:
            cart_crcs.add(game["crc"])
            logger.debug("Physical cart: %s (%s)", game["name"], game["crc"])

    logger.info(
        "Physical carts for %s: %d  (ROM games excluded: %d)",
        console_key.upper(),
        len(cart_crcs),
        rom_count,
    )
    return cart_crcs


def _describe_pocket_db_systems(games: list[dict]) -> str:
    """Return a compact summary of system IDs present in a played-games list.

    Example output: ``"GBA:2  NGP:4  PCE:10"``
    """
    seen: dict[int, int] = {}
    for g in games:
        seen[g["system_id"]] = seen.get(g["system_id"], 0) + 1
    parts = []
    for sid in sorted(seen):
        key = POCKET_SYSTEM_IDS.get(sid, f"0x{sid:02x}?")
        parts.append(f"{key.upper()}:{seen[sid]}")
    return "  ".join(parts) if parts else "(empty)"


# ---------------------------------------------------------------------------
# Network helpers
# ---------------------------------------------------------------------------


def _ensure_requests() -> None:
    """Raise a clear error if the ``requests`` package is not installed."""
    if requests is None:
        logger.error(
            "The 'requests' package is required for downloads. "
            "Install it with: pip install requests"
        )
        sys.exit(1)


def download_with_retry(
    url: str,
    dest: Path,
    *,
    session: requests.Session | None = None,
    timeout: int = 120,
    dl_label: str = "",
) -> bool:
    """Download *url* to *dest* with retry and exponential backoff.

    If *dl_label* is set, a compact progress bar is rendered to stdout while
    downloading (TTY only).

    Returns ``True`` on success, ``False`` on failure.
    """
    _ensure_requests()
    assert requests is not None  # guaranteed by _ensure_requests()
    http = session if session is not None else requests
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            logger.debug("Download attempt %d/%d: %s", attempt, MAX_RETRIES, url)
            resp = http.get(url, stream=True, timeout=timeout)
            resp.raise_for_status()
            dest.parent.mkdir(parents=True, exist_ok=True)

            total_size = int(resp.headers.get("Content-Length", 0))
            downloaded = 0

            # Stream to a temp file in the same directory, then rename for atomicity
            tmp_fd, tmp_path = tempfile.mkstemp(dir=str(dest.parent), suffix=".tmp")
            try:
                with os.fdopen(tmp_fd, "wb") as fh:
                    for chunk in resp.iter_content(chunk_size=256 * 1024):
                        fh.write(chunk)
                        downloaded += len(chunk)
                        if dl_label:
                            _dl_progress(dl_label, downloaded, total_size)
                # Atomic-ish rename (works on same filesystem)
                Path(tmp_path).replace(dest)
            except BaseException:
                # Clean up partial temp file on failure
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise

            logger.debug("Downloaded %s → %s", url, dest)
            return True

        except (requests.RequestException, OSError) as exc:
            wait = RETRY_BACKOFF_BASE**attempt
            logger.warning(
                "Download attempt %d/%d failed (%s); retrying in %ds…",
                attempt,
                MAX_RETRIES,
                exc,
                wait,
            )
            time.sleep(wait)

    logger.error("Failed to download %s after %d attempts", url, MAX_RETRIES)
    return False


# ---------------------------------------------------------------------------
# Archive download & extraction
# ---------------------------------------------------------------------------


def download_and_extract_repo(
    console_key: str,
    cache_dir: Path,
    *,
    session: requests.Session | None = None,
    force: bool = False,
) -> bool:
    """Download the libretro-thumbnails archive for *console_key* and extract
    all three image-type directories (``Named_Boxarts``, ``Named_Titles``,
    ``Named_Snaps``) into *cache_dir*.

    Returns ``True`` on success.
    """
    repo = CONSOLE_REPOS[console_key]
    url = GITHUB_ARCHIVE_URL.format(repo=repo)
    console_cache = cache_dir / repo
    label = console_key.upper()

    # If all three dirs already exist and --force is not set, skip download
    if not force:
        all_present = all(
            (console_cache / d).is_dir() for d in IMAGE_TYPE_DIRS.values()
        )
        if all_present:
            # Quick sanity check: at least one .png in each dir
            has_files = all(
                any((console_cache / d).glob("*.png")) for d in IMAGE_TYPE_DIRS.values()
            )
            if has_files:
                count = sum(
                    len(list((console_cache / d).glob("*.png")))
                    for d in IMAGE_TYPE_DIRS.values()
                )
                print(f"  ↓ {label}  (cached  {count} images)")
                return True

    logger.info("Downloading %s archive for %s…", repo, console_key)
    zip_path = cache_dir / f"{repo}.zip"

    if not download_with_retry(url, zip_path, session=session, dl_label=label):
        _tui_clear()
        return False

    # Extract the three Named_* directories
    _tui_overwrite(f"  ↓ {label}  extracting…")
    try:
        _extract_image_dirs(zip_path, console_cache)
    except (zipfile.BadZipFile, OSError) as exc:
        logger.error("Failed to extract archive %s: %s", zip_path, exc)
        return False
    finally:
        # Remove the zip to save space
        try:
            zip_path.unlink()
            logger.debug("Removed archive %s", zip_path)
        except OSError:
            pass

    count = sum(
        len(list((console_cache / d).glob("*.png"))) for d in IMAGE_TYPE_DIRS.values()
    )
    _tui_clear()
    print(f"  ↓ {label}  {count} images cached")
    return True


def _extract_image_dirs(zip_path: Path, dest: Path) -> None:
    """Extract ``Named_Boxarts/``, ``Named_Titles/``, ``Named_Snaps/`` from
    the archive into *dest*.

    GitHub archives have a top-level directory like ``<repo>-master/``, so we
    strip that prefix.
    """
    target_dirs = set(IMAGE_TYPE_DIRS.values())

    with zipfile.ZipFile(zip_path, "r") as zf:
        # Discover the top-level prefix (e.g. "NEC_-_PC_Engine_...-master/")
        top_prefix = ""
        for name in zf.namelist():
            parts = name.split("/")
            if len(parts) >= 2 and parts[0].endswith("-master"):
                top_prefix = parts[0] + "/"
                break

        extracted_count = 0
        for entry in zf.infolist():
            # Skip directories themselves
            if entry.is_dir():
                continue

            rel = entry.filename
            if top_prefix and rel.startswith(top_prefix):
                rel = rel[len(top_prefix) :]

            # Check if this file belongs to one of the target dirs
            parts = rel.split("/", 1)
            if len(parts) != 2:
                continue
            dir_name, file_name = parts
            if dir_name not in target_dirs:
                continue
            if not file_name:
                continue

            out_path = dest / dir_name / file_name
            out_path.parent.mkdir(parents=True, exist_ok=True)

            try:
                with zf.open(entry) as src, open(out_path, "wb") as dst:
                    while True:
                        chunk = src.read(256 * 1024)
                        if not chunk:
                            break
                        dst.write(chunk)
                extracted_count += 1
            except (OSError, zipfile.BadZipFile) as exc:
                logger.warning("Failed to extract %s: %s", entry.filename, exc)

        logger.info("Extracted %d files for cache", extracted_count)


# ---------------------------------------------------------------------------
# Image validation
# ---------------------------------------------------------------------------


def detect_image_format(file_path: Path) -> Optional[str]:
    """Detect whether *file_path* is a PNG, JPEG, or unknown.

    Returns ``"PNG"``, ``"JPEG"``, or ``None``.
    """
    try:
        with open(file_path, "rb") as fh:
            header = fh.read(8)
    except OSError:
        return None

    if len(header) >= 8 and header[:8] == PNG_MAGIC:
        return "PNG"

    if len(header) >= 2 and header[:2] == JPEG_SOI:
        # Extra validation: check for JPEG EOI at end of file
        try:
            with open(file_path, "rb") as fh:
                fh.seek(-2, 2)
                footer = fh.read(2)
            if footer == JPEG_EOI:
                return "JPEG"
            # Some valid JPEGs have trailing data after EOI, still treat as JPEG
            return "JPEG"
        except OSError:
            return "JPEG"

    return None


def resolve_symlink_text(file_path: Path) -> Optional[Path]:
    """If *file_path* is a small text file containing a relative path (a
    libretro-thumbnails "symlink"), resolve and return the target path.

    Returns ``None`` if the file is not a symlink-text file or the target
    does not exist.
    """
    try:
        size = file_path.stat().st_size
    except OSError:
        return None

    if size == 0 or size > SYMLINK_TEXT_MAX_SIZE:
        return None

    try:
        content = file_path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None

    # Must look like a relative path — no absolute paths, and must contain
    # at least a filename component
    if not content or "\n" in content:
        return None

    # Normalise forward slashes to native
    content = content.replace("/", os.sep)

    target = file_path.parent / content
    if target.is_file():
        return target

    # Also try resolving from the parent of the parent (Named_Boxarts/../)
    target2 = file_path.parent.parent / content
    if target2.is_file():
        return target2

    logger.debug(
        "Symlink-text %s points to %s which does not exist", file_path, content
    )
    return None


def validate_image(file_path: Path) -> Optional[Path]:
    """Validate a cached image file.  Returns the actual path to load (which
    may differ from *file_path* if it was a symlink-text redirect), or
    ``None`` if the image should be skipped.

    Also logs warnings for JPEG-masquerading-as-PNG cases.
    """
    fmt = detect_image_format(file_path)
    if fmt == "PNG":
        return file_path
    if fmt == "JPEG":
        if file_path.suffix.lower() == ".png":
            logger.warning("JPEG masquerading as PNG: %s", file_path.name)
        return file_path

    # Not a recognised image — try symlink-text resolution
    resolved = resolve_symlink_text(file_path)
    if resolved is not None:
        logger.debug("Resolved symlink-text: %s → %s", file_path.name, resolved)
        res_fmt = detect_image_format(resolved)
        if res_fmt in ("PNG", "JPEG"):
            if res_fmt == "JPEG" and resolved.suffix.lower() == ".png":
                logger.warning(
                    "JPEG masquerading as PNG (via symlink): %s", resolved.name
                )
            return resolved
        else:
            logger.warning(
                "Symlink target %s is not a valid image — skipping", resolved
            )
            return None

    logger.warning("Unrecognised image format — skipping: %s", file_path.name)
    return None


# ---------------------------------------------------------------------------
# Filtering rules
# ---------------------------------------------------------------------------


def should_skip_image(
    game_name: str,
    console_key: str,
    special_cases: dict,
) -> tuple[bool, Optional[str]]:
    """Determine whether *game_name* should be skipped.

    Returns ``(should_skip, reason)`` where *reason* is ``None`` if
    the image should NOT be skipped.
    """
    # Check special-case skip list
    skip_list = special_cases.get(console_key, {}).get("skip", [])
    for pattern in skip_list:
        if re.search(pattern, game_name, re.IGNORECASE):
            return True, f"special-case skip: {pattern}"

    # Romhack filter
    if FILTER_ROMHACK.search(game_name):
        return True, "romhack"

    # Virtual Console filter
    if FILTER_VIRTUAL_CONSOLE.search(game_name):
        return True, "Virtual Console"

    # Pirate filter
    if FILTER_PIRATE.search(game_name):
        return True, "pirate"

    return False, None


def get_redirect(
    game_name: str,
    console_key: str,
    special_cases: dict,
) -> Optional[str]:
    """Return the redirect target name if *game_name* has a special-case
    redirect, or ``None``.
    """
    redirects = special_cases.get(console_key, {}).get("redirect", {})
    return redirects.get(game_name)


# ---------------------------------------------------------------------------
# Game enumeration from cache
# ---------------------------------------------------------------------------


def iter_cached_images(
    cache_dir: Path,
    console_key: str,
    image_type: str,
) -> list[Path]:
    """Return a sorted list of ``.png`` files in the cache for the given
    console and image type.
    """
    repo = CONSOLE_REPOS[console_key]
    img_dir = IMAGE_TYPE_DIRS[image_type]
    source = cache_dir / repo / img_dir
    if not source.is_dir():
        logger.warning("Cache directory does not exist: %s", source)
        return []
    files = sorted(source.glob("*.png"))
    logger.debug("Found %d .png files in %s", len(files), source)
    return files


def game_name_from_filename(filename: str) -> str:
    """Strip the ``.png`` extension to get the game name."""
    if filename.lower().endswith(".png"):
        return filename[:-4]
    return filename


# ---------------------------------------------------------------------------
# DAT file parsing & CRC32 lookup
# ---------------------------------------------------------------------------


def parse_dat_file(dat_path: Path) -> tuple[Optional[str], list[dict[str, str]]]:
    """Parse a No-Intro DAT XML file.

    Returns ``(system_name, entries)`` where *system_name* is the header name
    (e.g. ``"NEC - PC Engine - TurboGrafx-16"``) and *entries* is a list of
    dicts with ``"name"`` and ``"crc"`` keys.

    Returns ``(None, [])`` on parse failure.
    """
    try:
        tree = ET.parse(dat_path)
        root = tree.getroot()
    except (ET.ParseError, OSError) as exc:
        logger.error("Failed to parse DAT file %s: %s", dat_path, exc)
        return None, []

    # Extract system name from header
    system_name = None
    header = root.find("header")
    if header is not None:
        name_elem = header.find("name")
        if name_elem is not None and name_elem.text:
            system_name = name_elem.text.strip()

    # Extract game entries
    entries: list[dict[str, str]] = []
    for game in root.iter("game"):
        game_name = game.get("name")
        if not game_name:
            continue

        # Get CRC32 from the first <rom> element
        rom = game.find("rom")
        if rom is None:
            continue
        crc = rom.get("crc")
        if not crc:
            continue

        entries.append({"name": game_name, "crc": crc.upper()})

    logger.info(
        "Parsed DAT file %s: system=%s, %d entries",
        dat_path.name,
        system_name or "(unknown)",
        len(entries),
    )
    return system_name, entries


def _apply_libretro_substitution(name: str) -> str:
    """Apply the libretro-thumbnails character substitution rules to a name.

    Replaces ``& * / : ` < > ? \\ | "`` with ``_``.
    """
    return LIBRETRO_SPECIAL_CHARS.sub("_", name)


def build_dat_lookup(entries: list[dict[str, str]]) -> dict[str, str]:
    """Build a lookup table from DAT entries.

    Returns a dict mapping the libretro-substituted game name to its CRC32
    (uppercase hex).  When multiple ROMs share the same substituted name
    (shouldn't happen in No-Intro, but just in case), the first entry wins.
    """
    lookup: dict[str, str] = {}
    for entry in entries:
        key = _apply_libretro_substitution(entry["name"])
        if key not in lookup:
            lookup[key] = entry["crc"]
    return lookup


def detect_dat_console(system_name: str) -> Optional[str]:
    """Determine which console key a DAT system name maps to.

    Returns ``"pce"``, ``"pcecd"``, or ``None``.
    """
    for console_key, pattern in DAT_CONSOLE_PATTERNS:
        if pattern.search(system_name):
            return console_key
    return None


def load_dat_files(
    dat_paths: list[str],
    consoles: list[str],
) -> dict[str, dict[str, str]]:
    """Load one or more No-Intro DAT files and return per-console lookup tables.

    Returns ``{console_key: {libretro_name: crc32_hex}}`` for each console
    that was successfully matched from the provided DAT files.

    Console identification is automatic (from the DAT header), but if only
    one DAT file is provided and only one console is requested, the DAT is
    assigned to that console regardless of its header.
    """
    lookups: dict[str, dict[str, str]] = {}
    parsed_dats: list[tuple[str, Optional[str], list[dict[str, str]]]] = []

    for raw_path in dat_paths:
        dat_path = Path(raw_path).expanduser().resolve()
        if not dat_path.is_file():
            logger.error("DAT file not found: %s", dat_path)
            continue

        system_name, entries = parse_dat_file(dat_path)
        if not entries:
            logger.warning("DAT file %s contains no game entries", dat_path)
            continue

        parsed_dats.append((str(dat_path), system_name, entries))

    # Map each parsed DAT to a console key
    for dat_path_str, system_name, entries in parsed_dats:
        console_key = None

        # Try auto-detection from header
        if system_name:
            console_key = detect_dat_console(system_name)

        # Fallback: if only one DAT and one console, assume they match
        if console_key is None and len(parsed_dats) == 1 and len(consoles) == 1:
            console_key = consoles[0]
            logger.info(
                "Could not auto-detect console for DAT %s — "
                "assuming %s (only console requested)",
                dat_path_str,
                console_key,
            )

        if console_key is None:
            logger.warning(
                "Could not determine console for DAT file %s (header: %s). Skipping.",
                dat_path_str,
                system_name or "(none)",
            )
            continue

        if console_key not in consoles:
            logger.debug(
                "DAT %s maps to %s which is not in requested consoles %s — skipping",
                dat_path_str,
                console_key,
                consoles,
            )
            continue

        lookup = build_dat_lookup(entries)
        lookups[console_key] = lookup
        logger.info(
            "Loaded %d DAT entries for %s from %s",
            len(lookup),
            console_key.upper(),
            dat_path_str,
        )

    return lookups


def match_game_to_crc(
    game_name: str,
    dat_lookup: dict[str, str],
) -> Optional[str]:
    """Try to match a libretro image name to a CRC32 from the DAT lookup.

    Matching strategies (in order):
      1. Exact match (after libretro character substitution).
      2. Case-insensitive match.
      3. Base-title match (strip region tags and compare).
      4. Subtitle-separator normalisation: replace " - " with "_ " to reconcile
         the difference between Pocket firmware display names ("Game: Subtitle",
         where ":" → "_" via libretro substitution) and No-Intro/libretro
         filenames ("Game - Subtitle").  Tries exact, case-insensitive, and
         base-title variants after normalisation.

    Returns the CRC32 hex string or ``None``.  The caller is responsible
    for lowercasing the value before using it as a filename (Pocket
    firmware convention uses lowercase hex, e.g. ``4ff01515.bin``).
    """
    # Apply libretro substitution — idempotent for image basenames (already
    # substituted), but necessary for redirect targets that use raw DAT names.
    subst_name = _apply_libretro_substitution(game_name)

    # Strategy 1: exact match
    if subst_name in dat_lookup:
        return dat_lookup[subst_name]

    # Strategy 2: case-insensitive match
    subst_lower = subst_name.lower()
    for key, crc in dat_lookup.items():
        if key.lower() == subst_lower:
            logger.debug("Case-insensitive DAT match: %s → %s", game_name, key)
            return crc

    # Strategy 3: strip region tags and compare base titles
    base_name = REGION_TAG_RE.sub("", subst_name).strip()
    if base_name:
        base_lower = base_name.lower()
        for key, crc in dat_lookup.items():
            key_base = REGION_TAG_RE.sub("", key).strip()
            if key_base.lower() == base_lower:
                logger.debug("Fuzzy DAT match (base title): %s → %s", game_name, key)
                return crc

    # Strategy 4: subtitle-separator normalisation.
    # Libretro filenames use " - " as a subtitle separator (e.g. "Game - Sub"),
    # while Pocket firmware stores display names with ": " (e.g. "Game: Sub").
    # After _apply_libretro_substitution, ":" becomes "_", so "Game: Sub"
    # becomes "Game_ Sub".  Replacing " - " with "_ " in the libretro filename
    # makes the two forms comparable.
    if " - " in subst_name:
        norm_name = subst_name.replace(" - ", "_ ")
        if norm_name in dat_lookup:
            logger.debug("Subtitle-normalised DAT match: %s → %s", game_name, norm_name)
            return dat_lookup[norm_name]
        norm_lower = norm_name.lower()
        for key, crc in dat_lookup.items():
            if key.lower() == norm_lower:
                logger.debug(
                    "Subtitle-normalised case-insensitive DAT match: %s → %s",
                    game_name,
                    key,
                )
                return crc
        norm_base = REGION_TAG_RE.sub("", norm_name).strip()
        if norm_base:
            norm_base_lower = norm_base.lower()
            for key, crc in dat_lookup.items():
                key_base = REGION_TAG_RE.sub("", key).strip()
                if key_base.lower() == norm_base_lower:
                    logger.debug(
                        "Subtitle-normalised base-title DAT match: %s → %s",
                        game_name,
                        key,
                    )
                    return crc

    return None


# ---------------------------------------------------------------------------
# Conversion pipeline
# ---------------------------------------------------------------------------


def convert_image_to_pocket_bin(
    source_path: Path,
    dest_path: Path,
    *,
    rotate: bool = True,
) -> bool:
    """Convert a source image to an Analogue ``.bin`` library image file.

    Pipeline:
      1. Load source image (PNG or JPEG).
      2. (Pocket only) Rotate 90° CCW (= -90°) per the Analogue spec.
         The Pocket firmware applies 90° CW when rendering, so this
         pre-rotation results in a correct upright display.
         The Duo firmware displays stored data directly (no rotation), so
         ``rotate=False`` skips this step.
      3. Scale proportionally so height = 165 px.
      4. Convert pixel format to BGRA32.
      5. Write 8-byte header + raw pixel data.

    Header layout differs by device:
      - Pocket (``rotate=True``): firmware rotates 90°CW at render time, so
        the stored image is portrait.  Header = ``(stored_h, stored_w)`` which
        equals ``(display_w, display_h)`` after firmware rotation.
      - Duo   (``rotate=False``): firmware renders stored data as-is, so the
        stored image is in natural orientation.  Header = ``(stored_w, stored_h)``
        so the firmware reads the correct row stride.

    Returns ``True`` on success, ``False`` on failure.
    """
    if Image is None:
        logger.error(
            "Pillow is required for image conversion. "
            "Install it with: pip install Pillow"
        )
        return False

    try:
        img = Image.open(source_path)
        img = img.convert("RGBA")

        if rotate:
            # Pocket: pre-rotate 90° CCW so the firmware's 90° CW render
            # produces a correct upright image.
            # PIL rotate(90) is counter-clockwise with expand=True.
            img = img.rotate(90, expand=True)

        # Scale proportionally so height = 165 px
        orig_w, orig_h = img.size
        if orig_h == 0:
            logger.warning("Image has zero height, skipping: %s", source_path)
            return False
        scale = POCKET_BIN_TARGET_HEIGHT / orig_h
        new_w = max(1, int(orig_w * scale))
        new_h = POCKET_BIN_TARGET_HEIGHT
        img = img.resize((new_w, new_h), Image.LANCZOS)

        # Convert to BGRA32 pixel data
        pixel_data = img.tobytes("raw", "BGRA")

        # Write .bin file
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        with open(dest_path, "wb") as fh:
            fh.write(POCKET_BIN_MAGIC)
            if rotate:
                # Pocket: header encodes display dimensions (post-firmware-rotation).
                # display_w = stored_h (new_h), display_h = stored_w (new_w).
                fh.write(struct.pack("<HH", new_h, new_w))
            else:
                # Duo: header encodes actual stored dimensions so firmware reads
                # the correct row stride without any rotation.
                fh.write(struct.pack("<HH", new_w, new_h))
            fh.write(bytes(pixel_data))

        logger.debug(
            "Converted %s → %s (%dx%d)", source_path.name, dest_path.name, new_w, new_h
        )
        return True

    except Exception as exc:
        logger.warning("Failed to convert %s: %s", source_path.name, exc)
        return False


def _pack_thumbs_bin(entries: list[tuple[int, bytes]]) -> bytes:
    """Pack a list of ``(crc_int, bin_bytes)`` entries into the ``\\x02FTA`` bundle.

    This is the pure serialisation core shared by ``generate_pce_thumbs_bin``
    (reads from a directory) and ``write_duo_thumbs_bin`` (writes from an
    in-memory list).

    Format (all multi-byte integers are little-endian):
      - Bytes   0–3:   magic ``\\x02FTA``
      - Bytes   4–7:   total image-data section size (sum of all image entries)
      - Bytes  8–11:   image count
      - Bytes 12–65547: hash table (8192 × 8-byte entries)
          Entry layout: [crc32 uint32][data-section-offset uint32]
          Slot index = crc32_value % 8192 (linear-probe on collision)
      - Bytes 65548+: image entries (`` IPA`` header + h/w + BGRA32 pixels)
    """
    # Sentinel: slot is empty when CRC field == 0 and offset field == 0.
    # Valid CRC values are never 0, so this is safe.
    hash_table = bytearray(PCE_THUMBS_HASH_SLOTS * PCE_THUMBS_HASH_ENTRY_SIZE)
    image_data = bytearray()

    for crc_val, bin_bytes in entries:
        data_offset = len(image_data)
        image_data.extend(bin_bytes)

        slot = crc_val % PCE_THUMBS_HASH_SLOTS
        for _ in range(PCE_THUMBS_HASH_SLOTS):
            entry_off = slot * PCE_THUMBS_HASH_ENTRY_SIZE
            existing_crc = struct.unpack_from("<I", hash_table, entry_off)[0]
            if existing_crc == 0:
                struct.pack_into("<II", hash_table, entry_off, crc_val, data_offset)
                break
            slot = (slot + 1) % PCE_THUMBS_HASH_SLOTS
        else:
            logger.error(
                "_pack_thumbs_bin: hash table full — cannot insert CRC %08x", crc_val
            )

    return (
        PCE_THUMBS_MAGIC
        + struct.pack("<I", len(image_data))
        + struct.pack("<I", len(entries))
        + bytes(hash_table)
        + bytes(image_data)
    )


def write_duo_thumbs_bin(entries: list[tuple[int, bytes]], output_path: Path) -> bool:
    """Write a ``pce_thumbs.bin`` / ``pcecd_thumbs.bin`` for the Analogue Duo.

    *entries* is a list of ``(crc_int, bin_bytes)`` where *bin_bytes* is a
    fully-formed Pocket ``.bin`` file (`` IPA`` header + BGRA32 pixels).

    Returns ``True`` on success, ``False`` if *entries* is empty or a write
    error occurs.
    """
    if not entries:
        logger.warning("write_duo_thumbs_bin: no entries — skipping %s", output_path)
        return False

    raw = _pack_thumbs_bin(entries)
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(raw)
    except OSError as exc:
        logger.error("write_duo_thumbs_bin: failed to write %s: %s", output_path, exc)
        return False

    logger.info(
        "Wrote %s with %d images (%d bytes total)",
        output_path.name,
        len(entries),
        len(raw),
    )
    return True


def generate_pce_thumbs_bin(source_dir: Path, output_path: Path) -> bool:
    """Build ``pce_thumbs.bin`` from CRC-named ``.bin`` files in *source_dir*.

    The Pocket firmware reads ``System/Library/Images/pce_thumbs.bin`` for the
    PCE Library list-view thumbnails.  It does **not** build this file from the
    source files in ``pce/`` at runtime; it must be generated externally.

    See ``_pack_thumbs_bin`` for the full format specification.

    Images are stored at ``PCE_THUMBS_THUMB_HEIGHT`` px height before embedding.
    Hardware testing confirmed that 165 px (= POCKET_BIN_TARGET_HEIGHT) is
    recognised by the firmware; 121 px was not displayed.

    Only CRC-named files (8 hex chars, e.g. ``6aa69a8b.bin``) are included;
    name-based files are ignored so each CRC appears exactly once.

    Returns ``True`` on success, ``False`` if no valid images were found.
    """
    if Image is None:
        logger.error("generate_pce_thumbs_bin: Pillow is required but not installed")
        return False

    CRC_RE = re.compile(r"^[0-9a-f]{8}$", re.IGNORECASE)

    entries: list[tuple[int, bytes]] = []  # (crc_int, raw_bin_bytes)

    for f in sorted(source_dir.glob("*.bin")):
        if not CRC_RE.match(f.stem):
            continue
        data = f.read_bytes()
        if len(data) < 8 or data[:4] != POCKET_BIN_MAGIC:
            logger.debug("Skipping non-IPA file: %s", f.name)
            continue
        crc_val = int(f.stem, 16)

        # Downscale to thumbnail size before embedding
        orig_h, orig_w = struct.unpack_from("<HH", data, 4)
        scale = PCE_THUMBS_THUMB_HEIGHT / orig_h
        thumb_h = PCE_THUMBS_THUMB_HEIGHT
        thumb_w = max(1, int(orig_w * scale))

        # Reconstruct PIL image from raw BGRA32 pixels in the .bin file.
        # Individual .bin files store images pre-rotated 90° CCW (so the
        # firmware's 90° CW display rotation cancels it out).  Hardware testing
        # showed that pce_thumbs.bin images appear upside-down when stored with
        # the same 90° CCW pre-rotation, meaning the firmware applies an extra
        # 90° CCW on top — producing 180° net.  To compensate we rotate 180°
        # so that firmware-CCW + our-180° = 90° CW stored, and firmware applies
        # 90° CCW → net 0° = correct upright display.
        pixel_bytes = data[8:]
        img = Image.frombytes(
            "RGBA", (orig_w, orig_h), bytes(pixel_bytes), "raw", "BGRA"
        )
        img = img.rotate(180)  # correct for pce_thumbs.bin firmware rotation
        img = img.resize((thumb_w, thumb_h), Image.LANCZOS)
        thumb_pixels = img.tobytes("raw", "BGRA")
        thumb_data = (
            POCKET_BIN_MAGIC + struct.pack("<HH", thumb_h, thumb_w) + thumb_pixels
        )

        entries.append((crc_val, thumb_data))

    if not entries:
        logger.warning(
            "generate_pce_thumbs_bin: no valid CRC .bin files in %s", source_dir
        )
        return False

    raw = _pack_thumbs_bin(entries)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(raw)

    logger.info(
        "Wrote %s with %d images (%d bytes total)",
        output_path.name,
        len(entries),
        len(raw),
    )
    return True


def process_console(
    console_key: str,
    cache_dir: Path,
    image_type: str,
    special_cases: dict,
    sd_root: Optional[Path] = None,
    device: Optional[str] = None,
    dry_run: bool = False,
    force: bool = False,
    dat_lookup: Optional[dict[str, str]] = None,
    crc_to_db_name: Optional[dict[str, str]] = None,
) -> dict:
    """Process all cached images for a single console.

    Applies filtering, validation, and conversion.  When *dat_lookup* is
    provided (Pocket mode), output filenames use CRC32-based naming.
    When *crc_to_db_name* is provided, an additional name-based copy is
    written using the exact game name from the Pocket's played-games database
    (list.bin), covering name-based image lookup by the firmware.

    Returns a stats dict with counts.
    """
    stats = {
        "total": 0,
        "skipped_filter": 0,
        "skipped_invalid": 0,
        "skipped_redirect": 0,
        "converted": 0,
        "failed": 0,
        "already_exists": 0,
        "no_dat_match": 0,
        "removed_stale": 0,
    }

    images = iter_cached_images(cache_dir, console_key, image_type)
    stats["total"] = len(images)

    if not images:
        print(f"\n▶ {console_key.upper()}  no cached images (run download-only first)")
        return stats

    # Duo only supports pce and pcecd — skip unsupported consoles early so we
    # never fall through to the name-based filename fallback.
    if device == "duo" and console_key not in DUO_THUMBS_FILES:
        print(f"\n▶ {console_key.upper()}  skipped (not supported on Duo)")
        return stats

    # Pocket does not have a CD unit — pcecd images are only for the Duo.
    if device == "pocket" and console_key == "pcecd":
        print(f"\n▶ PCECD  skipped (not supported on Pocket — no CD unit)")
        return stats

    if dat_lookup is not None and len(dat_lookup) == 0:
        print(
            f"\n▶ {console_key.upper()}  no targets — no games in DB (launch a game first)"
        )
        return stats

    # Header: show how many CRC targets we're scanning for
    n_targets = len(dat_lookup) if dat_lookup is not None else 0
    target_info = f"  ({n_targets} targets)" if n_targets else ""
    print(f"\n▶ {console_key.upper()}{target_info}")

    # Determine output directory once (used for stale-file cleanup after the loop).
    # Both Pocket and Duo write individual CRC-named .bin files to the same
    # per-console directory; the Duo firmware then builds *_thumbs.bin from them.
    output_dir: Optional[Path] = None
    if sd_root is not None and device in ("pocket", "duo"):
        _img_dir = CONSOLE_IMAGE_DIRS.get(console_key)
        if _img_dir:
            output_dir = sd_root / _img_dir

    # Track every destination path we intend to write so we can remove orphans
    expected_files: set[Path] = set()
    total = len(images)

    for idx, img_path in enumerate(images, 1):
        game_name = game_name_from_filename(img_path.name)

        # Live scanning progress bar
        _tui_overwrite(f"  [{_bar(idx, total)}] {idx}/{total}  {_trunc(game_name, 42)}")

        # --- Filtering ---
        skip, reason = should_skip_image(game_name, console_key, special_cases)
        if skip:
            logger.debug("Skipping %s: %s", game_name, reason)
            stats["skipped_filter"] += 1
            continue

        # Check for redirect
        redirect_name = get_redirect(game_name, console_key, special_cases)
        if redirect_name is not None:
            logger.debug("Redirecting %s → %s", game_name, redirect_name)
            stats["skipped_redirect"] += 1
            game_name = redirect_name

        # --- Validation ---
        resolved = validate_image(img_path)
        if resolved is None:
            stats["skipped_invalid"] += 1
            continue

        # Helper: redraw the progress bar after printing a match line
        def _redraw(i: int = idx, g: str = game_name) -> None:
            _tui_overwrite(f"  [{_bar(i, total)}] {i}/{total}  {_trunc(g, 42)}")

        # --- Conversion — Pocket .bin ---
        if sd_root is not None and device in ("pocket", "duo"):
            if output_dir is None:
                logger.warning("No image directory mapping for %s", console_key)
                stats["failed"] += 1
                continue

            # The firmware may use multiple lookup strategies:
            #   1. CRC-based:      "6aa69a8b.bin"
            #   2. Libretro name:  "Bonk's Adventure (USA).bin"
            #   3. DB name:        "Bonk's Adventure.bin" (exact name from list.bin)
            # We write all available variants so the firmware finds the image
            # regardless of which strategy it uses.
            safe_name = _sanitize_filename(game_name)
            dest_name = output_dir / f"{safe_name}.bin"

            if dat_lookup is not None:
                crc = match_game_to_crc(game_name, dat_lookup)
                if crc is None:
                    logger.debug("No DAT match for: %s", game_name)
                    stats["no_dat_match"] += 1
                    continue
                crc_lower = crc.lower()
                dest_crc = output_dir / f"{crc_lower}.bin"
                expected_files.add(dest_crc)
                expected_files.add(dest_name)

                # Also write a copy using the exact name from list.bin (if available)
                dest_db_name: Optional[Path] = None
                db_name = ""
                if crc_to_db_name is not None:
                    raw_db_name = crc_to_db_name.get(crc_lower)
                    if raw_db_name is not None:
                        db_name = raw_db_name
                        safe_db_name = _sanitize_filename(raw_db_name)
                        if safe_db_name != safe_name:
                            dest_db_name = output_dir / f"{safe_db_name}.bin"
                            expected_files.add(dest_db_name)

                display_name = db_name or game_name

                all_exist = dest_crc.exists() and dest_name.exists()
                if dest_db_name is not None:
                    all_exist = all_exist and dest_db_name.exists()
                if all_exist and not force and not dry_run:
                    stats["already_exists"] += 1
                    _tui_match("·", crc_lower, display_name, game_name)
                    _redraw()
                    continue

                if dry_run:
                    stats["converted"] += 1
                    _tui_match("?", crc_lower, display_name, game_name)
                    _redraw()
                    continue

                ok = convert_image_to_pocket_bin(
                    resolved, dest_crc, rotate=(device != "duo")
                )
                if ok:
                    shutil.copy2(dest_crc, dest_name)
                    if dest_db_name is not None:
                        shutil.copy2(dest_crc, dest_db_name)
                    stats["converted"] += 1
                    _tui_match("✓", crc_lower, display_name, game_name)
                    _redraw()
                else:
                    stats["failed"] += 1
                    _tui_match("✗", crc_lower, display_name, game_name)
                    _redraw()
            else:
                # No DAT — fall back to name-based filename only
                dest = dest_name
                expected_files.add(dest)

                if dest.exists() and not dry_run and not force:
                    stats["already_exists"] += 1
                    _tui_match("·", "", game_name, game_name)
                    _redraw()
                    continue

                if dry_run:
                    stats["converted"] += 1
                    _tui_match("?", "", game_name, game_name)
                    _redraw()
                    continue

                if convert_image_to_pocket_bin(
                    resolved, dest, rotate=(device != "duo")
                ):
                    stats["converted"] += 1
                    _tui_match("✓", "", game_name, game_name)
                    _redraw()
                else:
                    stats["failed"] += 1
                    _tui_match("✗", "", game_name, game_name)
                    _redraw()

        else:
            # No SD card target — just validating
            stats["converted"] += 1

    # Clear the progress bar, print per-console summary
    _tui_clear()

    # Remove stale .bin files that are no longer part of the expected output set
    if output_dir is not None and output_dir.is_dir() and not dry_run:
        for existing in sorted(output_dir.glob("*.bin")):
            if existing not in expected_files:
                logger.debug("Removing stale image: %s", existing.name)
                existing.unlink()
                stats["removed_stale"] += 1

    _tui_console_summary(console_key, stats, dry_run)

    return stats


def _sanitize_filename(name: str) -> str:
    """Remove or replace characters that are unsafe in filenames."""
    # Replace the libretro special chars with underscore (matching their convention)
    safe = LIBRETRO_SPECIAL_CHARS.sub("_", name)
    # Also strip any remaining problematic chars
    safe = re.sub(r'[<>:"/\\|?*]', "_", safe)
    return safe


# ---------------------------------------------------------------------------
# Subcommand handlers
# ---------------------------------------------------------------------------


def cmd_auto(args: argparse.Namespace) -> int:
    """Default mode: download → convert → write to SD card."""
    sd_root = Path(args.sd_card).resolve()
    if not sd_root.is_dir():
        logger.error("SD card root does not exist: %s", sd_root)
        return 1

    # Detect device
    device = args.device or detect_device(sd_root)
    if device is None:
        logger.error(
            "Could not auto-detect device type. "
            "Neither %s nor %s found at %s.\n"
            "Use --device duo or --device pocket to specify manually.",
            DEVICE_FILES["duo"],
            DEVICE_FILES["pocket"],
            sd_root,
        )
        return 1

    logger.info("Device: %s | Image type: %s", device, args.image_type)

    cache_dir = Path(args.cache_dir).expanduser().resolve()
    special_cases = load_special_cases()
    consoles = _resolve_consoles(args.console)

    # Pocket has no CD unit — drop pcecd before any DB lookups or downloads.
    if device == "pocket" and "pcecd" in consoles:
        print("\n▶ PCECD  skipped (not supported on Pocket — no CD unit)")
        consoles = [c for c in consoles if c != "pcecd"]

    # Phase 1: Download
    _ensure_requests()
    assert requests is not None  # guaranteed by _ensure_requests()
    session = requests.Session()
    session.headers["User-Agent"] = f"{TOOL_NAME}/{VERSION}"

    for console_key in consoles:
        ok = download_and_extract_repo(
            console_key, cache_dir, session=session, force=args.force
        )
        if not ok:
            logger.error("Download failed for %s — aborting", console_key)
            return 1

    # Load DAT files for CRC32-based Pocket filenames
    dat_lookups: dict[str, dict[str, str]] = {}
    if args.dat_file:
        dat_lookups = load_dat_files(args.dat_file, consoles)

    # --use-pocket-db: read CRCs directly from the Pocket's played-games DB.
    # This fills in any console not already covered by a --dat-file, so both
    # sources can be combined (DAT file takes precedence where both apply).
    use_pocket_db: bool = getattr(args, "use_pocket_db", True)
    crc_to_db_names: dict[
        str, dict[str, str]
    ] = {}  # console_key → {crc: list.bin name}
    if use_pocket_db and device == "pocket":
        all_games = parse_pocket_played_games(sd_root)
        # TUI: compact single-line DB summary, e.g. "Pocket DB  GBA:2  NGP:7  PCE:11"
        systems_desc = _describe_pocket_db_systems(all_games)
        print(f"\nPocket DB  {systems_desc}")
        for console_key in consoles:
            # Build CRC → list.bin name reverse lookup for this console
            crc_to_db_names[console_key] = {
                g["crc"]: g["name"]
                for g in all_games
                if g["console_key"] == console_key
            }
            if console_key not in dat_lookups:
                pocket_lookup = build_pocket_db_lookup(sd_root, console_key)
                if pocket_lookup:
                    dat_lookups[console_key] = pocket_lookup
                else:
                    logger.warning(
                        "No played-%s games found in Pocket DB — "
                        "ensure you have launched at least one %s game on "
                        "your Pocket before running.",
                        console_key.upper(),
                        console_key.upper(),
                    )
    elif device == "duo":
        all_duo_games = parse_duo_played_games(sd_root)
        systems_desc = _describe_duo_db_systems(all_duo_games)
        print(f"\nDuo DB  {systems_desc}")
        for console_key in consoles:
            crc_to_db_names[console_key] = {
                g["crc"]: g["name"]
                for g in all_duo_games
                if g["console_key"] == console_key
            }
            if console_key not in dat_lookups:
                duo_lookup = build_duo_db_lookup(sd_root, console_key)
                if duo_lookup:
                    dat_lookups[console_key] = duo_lookup
                else:
                    logger.warning(
                        "No played-%s games found in Duo DB — "
                        "ensure you have launched at least one %s game on "
                        "your Duo before running.",
                        console_key.upper(),
                        console_key.upper(),
                    )
    elif device == "pocket" and not args.dat_file:
        logger.warning(
            "No CRC source provided for Pocket filenames. "
            "Without one, output filenames will be game-name-based and will "
            "NOT be recognised by the Pocket firmware.\n"
            "  Option A: --dat-file <nointro.dat>  (No-Intro CRCs; best for USA ROMs)\n"
            "  Option B: omit --no-pocket-db        "
            "(CRCs from the Pocket's played-games DB; works for any region)"
        )

    # --physical-only (default): filter every lookup so only physical
    # cartridge games are included.  A game is considered a physical cart if
    # it is in list.bin but has no corresponding ROM file in Assets/<console>/.
    # The Duo is a cartridge-only device — the filter is always satisfied and
    # does not need to run (get_physical_cart_crcs uses the Pocket parser which
    # would misclassify Duo flags).
    physical_only: bool = getattr(args, "physical_only", True)
    if physical_only and dat_lookups and sd_root is not None and device != "duo":
        for console_key in list(dat_lookups.keys()):
            cart_crcs = get_physical_cart_crcs(sd_root, console_key)
            if cart_crcs is None:
                logger.warning(
                    "Cannot determine physical carts for %s — list.bin not found "
                    "at %s. Processing all %d games in the CRC lookup. "
                    "Use --include-roms to suppress this warning.",
                    console_key.upper(),
                    sd_root / "System" / "Played Games" / "list.bin",
                    len(dat_lookups[console_key]),
                )
            elif not cart_crcs:
                logger.warning(
                    "No physical %s carts found in list.bin. "
                    "Make sure you have launched your physical carts on this "
                    "device at least once so the firmware registers them.",
                    console_key.upper(),
                )
                dat_lookups[console_key] = {}
            else:
                before = len(dat_lookups[console_key])
                dat_lookups[console_key] = {
                    name: crc
                    for name, crc in dat_lookups[console_key].items()
                    if crc.lower() in cart_crcs
                }
                after = len(dat_lookups[console_key])
                logger.info(
                    "Physical-only filter for %s: %d → %d entries "
                    "(%d ROM/downloaded games excluded)",
                    console_key.upper(),
                    before,
                    after,
                    before - after,
                )
    total_stats = {
        "total": 0,
        "skipped_filter": 0,
        "skipped_invalid": 0,
        "converted": 0,
        "failed": 0,
        "already_exists": 0,
        "no_dat_match": 0,
        "removed_stale": 0,
    }

    for console_key in consoles:
        console_dat = dat_lookups.get(console_key)
        stats = process_console(
            console_key,
            cache_dir,
            args.image_type,
            special_cases,
            sd_root=sd_root,
            device=device,
            dry_run=args.dry_run,
            force=args.force,
            dat_lookup=console_dat,
            crc_to_db_name=crc_to_db_names.get(console_key),
        )
        for k in total_stats:
            total_stats[k] += stats.get(k, 0)

    if len(consoles) > 1:
        _print_stats(total_stats, args.dry_run)
    return 0


def cmd_download_only(args: argparse.Namespace) -> int:
    """Download images to local cache without converting."""
    cache_dir = Path(args.cache_dir).expanduser().resolve()
    consoles = _resolve_consoles(args.console)

    _ensure_requests()
    assert requests is not None  # guaranteed by _ensure_requests()
    session = requests.Session()
    session.headers["User-Agent"] = f"{TOOL_NAME}/{VERSION}"

    for console_key in consoles:
        ok = download_and_extract_repo(
            console_key, cache_dir, session=session, force=args.force
        )
        if not ok:
            logger.error("Download failed for %s", console_key)
            return 1

    # Report what's in the cache
    for console_key in consoles:
        for img_type, dir_name in IMAGE_TYPE_DIRS.items():
            repo = CONSOLE_REPOS[console_key]
            d = cache_dir / repo / dir_name
            count = len(list(d.glob("*.png"))) if d.is_dir() else 0
            logger.info(
                "  %s / %s: %d images cached", console_key.upper(), img_type, count
            )

    print("Download complete. Cache directory:", cache_dir)
    return 0


def cmd_convert_only(args: argparse.Namespace) -> int:
    """Convert previously-cached images and write to SD card."""
    sd_root = Path(args.sd_card).resolve()
    if not sd_root.is_dir():
        logger.error("SD card root does not exist: %s", sd_root)
        return 1

    device = args.device or detect_device(sd_root)
    if device is None:
        logger.error(
            "Could not auto-detect device type. Use --device duo or --device pocket."
        )
        return 1

    cache_dir = Path(args.cache_dir).expanduser().resolve()
    special_cases = load_special_cases()
    consoles = _resolve_consoles(args.console)

    # Pocket has no CD unit — drop pcecd before any DB lookups or conversions.
    if device == "pocket" and "pcecd" in consoles:
        print("\n▶ PCECD  skipped (not supported on Pocket — no CD unit)")
        consoles = [c for c in consoles if c != "pcecd"]

    # Load DAT files for CRC32-based Pocket filenames
    dat_lookups: dict[str, dict[str, str]] = {}
    if args.dat_file:
        dat_lookups = load_dat_files(args.dat_file, consoles)

    # --use-pocket-db: read CRCs directly from the Pocket's played-games DB.
    use_pocket_db: bool = getattr(args, "use_pocket_db", True)
    crc_to_db_names: dict[
        str, dict[str, str]
    ] = {}  # console_key → {crc: list.bin name}
    if use_pocket_db and device == "pocket":
        all_games = parse_pocket_played_games(sd_root)
        systems_desc = _describe_pocket_db_systems(all_games)
        print(f"\nPocket DB  {systems_desc}")
        for console_key in consoles:
            # Build CRC → list.bin name reverse lookup for this console
            crc_to_db_names[console_key] = {
                g["crc"]: g["name"]
                for g in all_games
                if g["console_key"] == console_key
            }
            if console_key not in dat_lookups:
                pocket_lookup = build_pocket_db_lookup(sd_root, console_key)
                if pocket_lookup:
                    dat_lookups[console_key] = pocket_lookup
                else:
                    logger.warning(
                        "No played-%s games found in Pocket DB — "
                        "ensure you have launched at least one %s game on "
                        "your Pocket before running.",
                        console_key.upper(),
                        console_key.upper(),
                    )
    elif device == "duo":
        all_duo_games = parse_duo_played_games(sd_root)
        systems_desc = _describe_duo_db_systems(all_duo_games)
        print(f"\nDuo DB  {systems_desc}")
        for console_key in consoles:
            crc_to_db_names[console_key] = {
                g["crc"]: g["name"]
                for g in all_duo_games
                if g["console_key"] == console_key
            }
            if console_key not in dat_lookups:
                duo_lookup = build_duo_db_lookup(sd_root, console_key)
                if duo_lookup:
                    dat_lookups[console_key] = duo_lookup
                else:
                    logger.warning(
                        "No played-%s games found in Duo DB — "
                        "ensure you have launched at least one %s game on "
                        "your Duo before running.",
                        console_key.upper(),
                        console_key.upper(),
                    )
    elif device == "pocket" and not args.dat_file:
        logger.warning(
            "No CRC source provided for Pocket filenames. "
            "Without one, output filenames will be game-name-based and will "
            "NOT be recognised by the Pocket firmware.\n"
            "  Option A: --dat-file <nointro.dat>  (No-Intro CRCs; best for USA ROMs)\n"
            "  Option B: omit --no-pocket-db        "
            "(CRCs from the Pocket's played-games DB; works for any region)"
        )

    # --physical-only (default): filter to physical cart CRCs only.
    # Skipped for the Duo (always a cartridge-only device — no ROM assets).
    physical_only: bool = getattr(args, "physical_only", True)
    if physical_only and dat_lookups and sd_root is not None and device != "duo":
        for console_key in list(dat_lookups.keys()):
            cart_crcs = get_physical_cart_crcs(sd_root, console_key)
            if cart_crcs is None:
                logger.warning(
                    "Cannot determine physical carts for %s — list.bin not found. "
                    "Processing all %d games. Use --include-roms to suppress.",
                    console_key.upper(),
                    len(dat_lookups[console_key]),
                )
            elif not cart_crcs:
                logger.warning(
                    "No physical %s carts found in list.bin.",
                    console_key.upper(),
                )
                dat_lookups[console_key] = {}
            else:
                before = len(dat_lookups[console_key])
                dat_lookups[console_key] = {
                    name: crc
                    for name, crc in dat_lookups[console_key].items()
                    if crc.lower() in cart_crcs
                }
                after = len(dat_lookups[console_key])
                logger.info(
                    "Physical-only filter for %s: %d → %d entries "
                    "(%d ROM/downloaded games excluded)",
                    console_key.upper(),
                    before,
                    after,
                    before - after,
                )

    total_stats = {
        "total": 0,
        "skipped_filter": 0,
        "skipped_invalid": 0,
        "converted": 0,
        "failed": 0,
        "already_exists": 0,
        "no_dat_match": 0,
        "removed_stale": 0,
    }

    for console_key in consoles:
        console_dat = dat_lookups.get(console_key)
        stats = process_console(
            console_key,
            cache_dir,
            args.image_type,
            special_cases,
            sd_root=sd_root,
            device=device,
            dry_run=args.dry_run,
            force=args.force,
            dat_lookup=console_dat,
            crc_to_db_name=crc_to_db_names.get(console_key),
        )
        for k in total_stats:
            total_stats[k] += stats.get(k, 0)

    if len(consoles) > 1:
        _print_stats(total_stats, args.dry_run)
    return 0


def cmd_list_games(args: argparse.Namespace) -> int:
    """List all available game names from cached images."""
    cache_dir = Path(args.cache_dir).expanduser().resolve()
    consoles = _resolve_consoles(args.console)
    image_type = args.image_type
    special_cases = load_special_cases()

    any_found = False
    for console_key in consoles:
        images = iter_cached_images(cache_dir, console_key, image_type)
        if not images:
            print(f"\n[{console_key.upper()}] No cached {image_type} images found.")
            print(f"  Run 'download-only' first, or check --cache-dir ({cache_dir})")
            continue

        any_found = True
        # Apply filtering
        included = []
        skipped = 0
        for img_path in images:
            name = game_name_from_filename(img_path.name)
            skip, reason = should_skip_image(name, console_key, special_cases)
            if skip:
                skipped += 1
                continue
            included.append(name)

        print(
            f"\n[{console_key.upper()}] {len(included)} games ({skipped} filtered out):"
        )
        for name in included:
            print(f"  {name}")

    if not any_found:
        print(
            "\nNo cached images found. Run 'download-only' to populate the cache first."
        )
        return 1
    return 0


def cmd_clear_images(args: argparse.Namespace) -> int:
    """Delete all converted .bin image files from the SD card.

    Removes every ``.bin`` file from each console's image directory on the SD
    card. For Duo devices, also removes any matching ``*_thumbs.bin`` bundle
    files. The played-games database (``System/Played Games/list.bin``) is
    never touched.
    """
    sd_root = Path(args.sd_card).resolve()
    if not sd_root.is_dir():
        logger.error("SD card root does not exist: %s", sd_root)
        return 1

    device = args.device or detect_device(sd_root)
    if device is None:
        logger.error(
            "Could not auto-detect device type. Use --device duo or --device pocket."
        )
        return 1

    dry_run: bool = args.dry_run
    consoles = _resolve_consoles(args.console)

    # Pocket has no CD unit — skip pcecd silently (nothing to clear).
    if device == "pocket" and "pcecd" in consoles:
        consoles = [c for c in consoles if c != "pcecd"]

    # Duo does not support GG/GBA/NGP — skip those silently.
    if device == "duo":
        consoles = [c for c in consoles if c not in ("gg", "gba", "ngp")]

    prefix = "DRY-RUN  " if dry_run else ""
    total_removed = 0
    total_bytes = 0
    had_errors = False

    for console_key in consoles:
        img_dir = CONSOLE_IMAGE_DIRS.get(console_key)
        if img_dir is None:
            continue
        console_dir = sd_root / img_dir

        # Per-console .bin files
        removed = 0
        bytes_freed = 0
        if console_dir.is_dir():
            bin_files = sorted(console_dir.glob("*.bin"))
            for f in bin_files:
                try:
                    size = f.stat().st_size
                    if dry_run:
                        print(f"  {prefix}would remove  {f.relative_to(sd_root)}")
                    else:
                        f.unlink()
                        logger.debug("Removed %s", f)
                    removed += 1
                    bytes_freed += size
                except OSError as e:
                    logger.error("Failed to delete %s: %s", f, e)
                    had_errors = True

        # Duo thumbs bundle (e.g. pce_thumbs.bin / pcecd_thumbs.bin) — only on Duo
        if device == "duo":
            thumbs_rel = DUO_THUMBS_FILES.get(console_key)
            if thumbs_rel is not None:
                thumbs_path = sd_root / thumbs_rel
                if thumbs_path.exists():
                    try:
                        size = thumbs_path.stat().st_size
                        if dry_run:
                            print(
                                f"  {prefix}would remove  {thumbs_path.relative_to(sd_root)}"
                            )
                        else:
                            thumbs_path.unlink()
                            logger.debug("Removed %s", thumbs_path)
                        removed += 1
                        bytes_freed += size
                    except OSError as e:
                        logger.error("Failed to delete %s: %s", thumbs_path, e)
                        had_errors = True

        kb = bytes_freed / 1024
        action = "would remove" if dry_run else "removed"
        print(
            f"\n▶ {console_key.upper()}  {action} {removed} file(s)  "
            f"({kb:.1f} KB freed)"
        )
        total_removed += removed
        total_bytes += bytes_freed

    if len(consoles) > 1:
        kb_total = total_bytes / 1024
        action = "Would remove" if dry_run else "Removed"
        print(
            f"\n  {prefix}TOTAL  {action} {total_removed} file(s)  "
            f"({kb_total:.1f} KB freed)"
        )

    return 1 if had_errors else 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_consoles(console_arg: str) -> list[str]:
    """Turn the ``--console`` argument into a list of console keys.

    ``"all"`` expands to all supported consoles: gg, gba, ngp, pce, and pcecd.
    """
    if console_arg == "all":
        return ["gg", "gba", "ngp", "pce", "pcecd"]
    if console_arg in CONSOLE_REPOS:
        return [console_arg]
    logger.error(
        "Unknown console: %s (expected: gg, gba, ngp, pce, pcecd, all)", console_arg
    )
    sys.exit(1)


def _print_stats(stats: dict, dry_run: bool) -> None:
    """Print a compact aggregate totals line (only useful for multi-console runs)."""
    prefix = "DRY-RUN  " if dry_run else ""
    converted = stats["converted"]
    no_match = stats.get("no_dat_match", 0)
    filtered = stats["skipped_filter"]
    failed = stats["failed"]
    stale = stats.get("removed_stale", 0)
    stale_str = f"  {stale} stale removed" if stale else ""
    print(
        f"\n  {prefix}TOTAL  "
        f"{converted} ✓  {no_match} no match  {filtered} filtered  "
        f"{failed} failed{stale_str}"
    )


# ---------------------------------------------------------------------------
# CLI argument parser
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """Build and return the argument parser."""
    parser = argparse.ArgumentParser(
        prog=TOOL_NAME,
        description=(
            "Download and convert thumbnail images for Game Gear, Game Boy Advance, "
            "Neo Geo Pocket Color, PC Engine, and PC Engine CD — for Analogue Pocket "
            "and Analogue Duo."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Modes:\n"
            "  (default)      Download + convert + write to SD card ('auto')\n"
            "  download-only  Download thumbnail archives to local cache\n"
            "  convert-only   Convert cached images and write to SD card\n"
            "  list-games     List available game names from cache\n"
            "  clear-images   Delete all converted images from SD card\n"
            "\n"
            "Examples:\n"
            "  %(prog)s E:\\                              "
            "# Auto-detect device, download boxart, convert\n"
            "  %(prog)s E:\\ --image-type title            "
            "# Use title screens instead\n"
            "  %(prog)s E:\\ --image-type snap             "
            "# Use in-game snapshots\n"
            "  %(prog)s E:\\ --console pce                 "
            "# Only PC Engine (skip others)\n"
            "  %(prog)s E:\\ --console gg                  "
            "# Only Game Gear\n"
            "  %(prog)s E:\\ --console gba                 "
            "# Only Game Boy Advance\n"
            "  %(prog)s E:\\ --console ngp                 "
            "# Only Neo Geo Pocket Color\n"
            "  %(prog)s download-only --console pce       "
            "# Download to cache only\n"
            "  %(prog)s E:\\ convert-only                  "
            "# Convert from cache (offline)\n"
            "  %(prog)s list-games --console pce          "
            "# List available game names\n"
            "  %(prog)s E:\\ --dry-run                     "
            "# Show what would be done\n"
            "  %(prog)s E:\\ clear-images                  "
            "# Remove all images from SD card\n"
            "  %(prog)s E:\\ clear-images --console pce    "
            "# Remove only PC Engine images\n"
            "  %(prog)s E:\\ clear-images --dry-run        "
            "# Preview which files would be removed\n"
        ),
    )

    # Two optional positional arguments: [sd_card] [mode]
    # Ambiguity (is the first arg a path or a mode?) is resolved in main().
    parser.add_argument(
        "positionals",
        nargs="*",
        metavar="SD_CARD_OR_MODE",
        help=(
            "SD card root path (e.g. E:\\ or /Volumes/DUO/) and/or "
            "operating mode (download-only, convert-only, list-games). "
            "If no mode is given, defaults to 'auto' (download + convert)."
        ),
    )

    _add_common_args(parser)

    return parser


def _add_common_args(parser: argparse.ArgumentParser) -> None:
    """Add option arguments to the parser."""
    parser.add_argument(
        "--image-type",
        choices=["boxart", "title", "snap"],
        default="boxart",
        help="Which image type to use (default: boxart)",
    )
    parser.add_argument(
        "--console",
        choices=["gg", "gba", "ngp", "pce", "pcecd", "all"],
        default="all",
        help=(
            "Which console(s) to process (default: all). "
            "'all' processes gg, gba, ngp, pce, and pcecd."
        ),
    )
    parser.add_argument(
        "--device",
        choices=["duo", "pocket"],
        default=None,
        help="Force device type (default: auto-detect from SD card)",
    )
    parser.add_argument(
        "--dat-file",
        action="append",
        default=None,
        help=(
            "Path to a No-Intro DAT file for CRC32-based Pocket filenames. "
            "Can be specified multiple times for different consoles "
            "(e.g. --dat-file pce.dat --dat-file pcecd.dat). "
            "Console is auto-detected from the DAT header."
        ),
    )
    parser.add_argument(
        "--cache-dir",
        default=str(DEFAULT_CACHE_DIR),
        help=f"Local cache directory (default: {DEFAULT_CACHE_DIR})",
    )
    parser.add_argument(
        "--local-archive",
        default=None,
        help="Path to a previously-downloaded libretro-thumbnails archive or directory",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Show what would be done without writing any files",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="Re-download and re-convert all images even if cached",
    )
    parser.add_argument(
        "--use-pocket-db",
        dest="use_pocket_db",
        action="store_true",
        default=True,
        help=(
            "Read CRC32 values directly from the Pocket's played-games database "
            "(System/Played Games/list.bin). This is the default behaviour and "
            "ensures generated .bin filenames match exactly what the firmware "
            "expects for any ROM region or version. "
            "Can be combined with --dat-file; the DAT file takes precedence for "
            "any console it covers."
        ),
    )
    parser.add_argument(
        "--no-pocket-db",
        dest="use_pocket_db",
        action="store_false",
        help=(
            "Disable automatic CRC lookup from the Pocket's played-games database. "
            "Use with --dat-file to supply CRCs from a No-Intro DAT instead."
        ),
    )
    physical_group = parser.add_mutually_exclusive_group()
    physical_group.add_argument(
        "--physical-only",
        dest="physical_only",
        action="store_true",
        default=True,
        help=(
            "Only generate images for physical cartridge games — games present "
            "in the device's played-games database (list.bin) that do NOT have "
            "a ROM file in Assets/<console>/common/. This is the default behaviour."
        ),
    )
    physical_group.add_argument(
        "--include-roms",
        dest="physical_only",
        action="store_false",
        help=(
            "Generate images for all games in the CRC lookup, including ROM and "
            "downloaded games stored in Assets/<console>/common/. "
            "Overrides the default --physical-only behaviour."
        ),
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="Increase verbosity (-v for INFO, -vv for DEBUG)",
    )


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    # --- Resolve positional arguments: [sd_card] [mode] ---
    positionals = args.positionals or []
    sd_card = None
    mode = "auto"

    if len(positionals) == 1:
        if positionals[0] in VALID_MODES:
            mode = positionals[0]
        else:
            sd_card = positionals[0]
    elif len(positionals) == 2:
        # Support both "sd_card mode" and "mode sd_card" ordering
        if positionals[1] in VALID_MODES:
            sd_card = positionals[0]
            mode = positionals[1]
        elif positionals[0] in VALID_MODES:
            mode = positionals[0]
            sd_card = positionals[1]
        else:
            parser.error(
                f"Unrecognised mode: '{positionals[1]}'. "
                f"Valid modes: {', '.join(sorted(VALID_MODES))}"
            )
    elif len(positionals) > 2:
        parser.error("Too many positional arguments. Expected: [sd_card] [mode]")

    # Attach resolved values so command handlers can access them uniformly
    args.sd_card = sd_card
    args.mode = mode

    # Configure logging from verbosity flag
    verbosity = getattr(args, "verbose", 0) or 0
    configure_logging(verbosity)

    logger.debug("Parsed arguments: %s", args)

    # --- Dispatch to command handler ---
    if mode == "download-only":
        return cmd_download_only(args)
    elif mode == "convert-only":
        if args.sd_card is None:
            parser.error("SD card root is required for convert-only mode.")
        return cmd_convert_only(args)
    elif mode == "list-games":
        return cmd_list_games(args)
    elif mode == "clear-images":
        if args.sd_card is None:
            parser.error("SD card root is required for clear-images mode.")
        return cmd_clear_images(args)
    else:
        # Default auto mode
        if args.sd_card is None:
            parser.error(
                "SD card root is required for the default (auto) mode.\n"
                "Usage: analogue_image_gen.py <sd_card_root> [options]\n"
                "   or: analogue_image_gen.py download-only [options]"
            )
        return cmd_auto(args)


if __name__ == "__main__":
    sys.exit(main())
