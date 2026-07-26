"""Unit tests for played-games database parsing and Duo thumbs bin packing.

Tests:
  - parse_pocket_played_games() and parse_duo_played_games()
  - build_pocket_db_lookup() and build_duo_db_lookup()
  - _pack_thumbs_bin(), write_duo_thumbs_bin(), and generate_pce_thumbs_bin()
  - get_physical_cart_crcs() and get_rom_game_names()
  - cmd_clear_images()
"""

import struct
from pathlib import Path
import pytest

from analogue_image_gen import (
    parse_pocket_played_games,
    parse_duo_played_games,
    build_pocket_db_lookup,
    build_duo_db_lookup,
    _pack_thumbs_bin,
    write_duo_thumbs_bin,
    generate_pce_thumbs_bin,
    get_physical_cart_crcs,
    get_rom_game_names,
    cmd_clear_images,
    build_parser,
    POCKET_BIN_MAGIC,
    PCE_THUMBS_MAGIC,
    PCE_THUMBS_HEADER_SIZE,
)


def _create_mock_list_bin(tmp_dir: Path, entries: list[tuple[int, int, str]]) -> Path:
    """Helper to create a synthetic list.bin binary file.
    
    entries is a list of (flags, crc32, name).
    """
    played_dir = tmp_dir / "System" / "Played Games"
    played_dir.mkdir(parents=True, exist_ok=True)
    list_bin_path = played_dir / "list.bin"

    entry_count = len(entries)
    header_size = 16 + entry_count * 4
    
    entry_bytes_list = []
    offsets = []
    current_off = header_size

    for game_id, (flags, crc32, name) in enumerate(entries):
        offsets.append(current_off)
        name_bytes = name.encode("utf-8") + b"\x00"
        # 16 bytes fixed entry header + name_bytes
        entry_size = 16 + len(name_bytes)
        entry_data = struct.pack("<HHIII", entry_size, flags, crc32, 0, game_id) + name_bytes
        entry_bytes_list.append(entry_data)
        current_off += len(entry_data)

    header = b"\x01FAT" + struct.pack("<III", entry_count, 0, offsets[0] if offsets else header_size)
    offset_table = b"".join(struct.pack("<I", off) for off in offsets)
    
    full_data = header + offset_table + b"".join(entry_bytes_list)
    list_bin_path.write_bytes(full_data)
    return list_bin_path


class TestParsePlayedGames:
    """Tests for parse_pocket_played_games and parse_duo_played_games."""

    def test_parse_pocket_played_games(self, tmp_dir):
        """Parse Pocket list.bin with system IDs in upper byte of flags."""
        entries = [
            (0x0200, 0x12345678, "Advance Wars"),  # GBA system_id = 0x02
            (0x0700, 0xABCDEF00, "Bonk's Adventure"),  # PCE system_id = 0x07
        ]
        _create_mock_list_bin(tmp_dir, entries)

        games = parse_pocket_played_games(tmp_dir)
        assert len(games) == 2
        assert games[0]["name"] == "Advance Wars"
        assert games[0]["crc"] == "12345678"
        assert games[0]["console_key"] == "gba"
        assert games[1]["console_key"] == "pce"

    def test_parse_duo_played_games(self, tmp_dir):
        """Parse Duo list.bin with console flags."""
        entries = [
            (0x0000, 0x11112222, "Ninja Spirit"),  # HuCard -> pce
            (0x0100, 0x33334444, "Rondo of Blood"),  # CD-ROM -> pcecd
        ]
        _create_mock_list_bin(tmp_dir, entries)

        games = parse_duo_played_games(tmp_dir)
        assert len(games) == 2
        assert games[0]["console_key"] == "pce"
        assert games[1]["console_key"] == "pcecd"

    def test_parse_played_games_missing_file(self, tmp_dir):
        """Missing list.bin returns empty list."""
        assert parse_pocket_played_games(tmp_dir) == []
        assert parse_duo_played_games(tmp_dir) == []

    def test_build_db_lookups(self, tmp_dir):
        """Test build_pocket_db_lookup and build_duo_db_lookup."""
        entries = [
            (0x0700, 0xA1B2C3D4, "Alien Crush"),
            (0x0000, 0xE5F6A7B8, "Devil's Crush"),
        ]
        _create_mock_list_bin(tmp_dir, entries)

        pocket_lookup = build_pocket_db_lookup(tmp_dir, "pce")
        assert pocket_lookup.get("Alien Crush") == "a1b2c3d4"

        duo_lookup = build_duo_db_lookup(tmp_dir, "pce")
        assert duo_lookup.get("Devil's Crush") == "e5f6a7b8"


class TestThumbsBinPacking:
    """Tests for _pack_thumbs_bin, write_duo_thumbs_bin, and generate_pce_thumbs_bin."""

    def test_pack_thumbs_bin(self):
        """Pack synthetic bin entries into FTA bundle."""
        mock_bin_data = POCKET_BIN_MAGIC + struct.pack("<HH", 165, 100) + b"\x00" * (165 * 100 * 4)
        entries = [(0x12345678, mock_bin_data)]

        packed = _pack_thumbs_bin(entries)
        assert packed[:4] == PCE_THUMBS_MAGIC
        total_img_size, img_count = struct.unpack_from("<II", packed, 4)
        assert img_count == 1
        assert total_img_size == len(mock_bin_data)
        assert len(packed) == PCE_THUMBS_HEADER_SIZE + len(mock_bin_data)

    def test_write_duo_thumbs_bin(self, tmp_dir):
        """Write duo thumbs bin file to disk."""
        out_path = tmp_dir / "System" / "Library" / "Images" / "pce_thumbs.bin"
        mock_bin_data = POCKET_BIN_MAGIC + struct.pack("<HH", 165, 100) + b"\x00" * (165 * 100 * 4)
        
        ok = write_duo_thumbs_bin([(0xABCDEF00, mock_bin_data)], out_path)
        assert ok is True
        assert out_path.is_file()

    def test_generate_pce_thumbs_bin_empty_dir(self, tmp_dir):
        """generate_pce_thumbs_bin returns False when no CRC bins present."""
        src_dir = tmp_dir / "pce_source"
        src_dir.mkdir()
        out_path = tmp_dir / "pce_thumbs.bin"

        assert generate_pce_thumbs_bin(src_dir, out_path) is False


class TestPhysicalCartAndRomFiltering:
    """Tests for get_rom_game_names and get_physical_cart_crcs."""

    def test_get_rom_game_names(self, tmp_dir):
        """Find ROM files in Assets/pce/common/."""
        rom_dir = tmp_dir / "Assets" / "pce" / "common"
        rom_dir.mkdir(parents=True)
        (rom_dir / "Game1.pce").write_bytes(b"dummy")
        (rom_dir / "Game2.sgx").write_bytes(b"dummy")
        (rom_dir / "readme.txt").write_bytes(b"dummy")

        rom_names = get_rom_game_names(tmp_dir, "pce")
        assert "Game1" in rom_names
        assert "Game2" in rom_names
        assert "readme" not in rom_names

    def test_get_physical_cart_crcs(self, tmp_dir):
        """Distinguish physical carts (in list.bin, no ROM) from ROM games."""
        entries = [
            (0x0700, 0x11111111, "CartGame"),
            (0x0700, 0x22222222, "RomGame"),
        ]
        _create_mock_list_bin(tmp_dir, entries)

        rom_dir = tmp_dir / "Assets" / "pce" / "common"
        rom_dir.mkdir(parents=True)
        (rom_dir / "RomGame.pce").write_bytes(b"dummy")

        cart_crcs = get_physical_cart_crcs(tmp_dir, "pce")
        assert cart_crcs is not None
        assert "11111111" in cart_crcs
        assert "22222222" not in cart_crcs


class TestClearImagesCommand:
    """Tests for cmd_clear_images handler."""

    def test_clear_images_deletes_bin_files(self, tmp_dir):
        """Delete converted bin files from SD card structure."""
        (tmp_dir / "Analogue_Pocket.json").write_text("{}")
        img_dir = tmp_dir / "System" / "Library" / "Images" / "pce"
        img_dir.mkdir(parents=True)
        img_file = img_dir / "12345678.bin"
        img_file.write_bytes(b"dummy")

        parser = build_parser()
        args = parser.parse_args([str(tmp_dir), "clear-images", "--console", "pce"])
        args.sd_card = str(tmp_dir)
        args.mode = "clear-images"

        ret = cmd_clear_images(args)
        assert ret == 0
        assert not img_file.exists()
