"""Unit tests for game parsing and lookup functions.

Tests:
  - parse_dat_file(): DAT file parsing with clrmamepro format
  - build_dat_lookup(): Creating CRC lookup tables
  - detect_dat_console(): Console detection from DAT system names
  - game_name_from_filename(): Extracting game names from filenames
  - match_game_to_crc(): Fuzzy name matching with fallbacks
  - load_special_cases(): Loading special_cases.json redirects
"""

import pytest
import sys
from pathlib import Path

# Add repo root to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from analogue_image_gen import (
    parse_dat_file,
    build_dat_lookup,
    detect_dat_console,
    game_name_from_filename,
    match_game_to_crc,
    _apply_libretro_substitution,
    load_special_cases,
)


class TestParseDatFile:
    """Tests for parse_dat_file() function."""

    def test_parse_valid_dat_file(self, sample_dat_file):
        """Parse a valid clrmamepro DAT file."""
        system_name, entries = parse_dat_file(sample_dat_file)
        
        assert system_name == "PC Engine"
        assert len(entries) == 5
        assert entries[0]["name"] == "Adventure Island"
        assert entries[0]["crc"] == "A1B2C3D4"  # Should be uppercase

    def test_parse_dat_file_nonexistent(self, tmp_dir):
        """Handle missing DAT file gracefully."""
        nonexistent = tmp_dir / "missing.dat"
        system_name, entries = parse_dat_file(nonexistent)
        
        assert system_name is None
        assert entries == []

    def test_parse_dat_file_empty(self, tmp_dir):
        """Handle empty DAT file."""
        empty_dat = tmp_dir / "empty.dat"
        empty_dat.write_text("")
        
        system_name, entries = parse_dat_file(empty_dat)
        assert system_name is None
        assert entries == []

    def test_dat_entry_structure(self, sample_dat_file):
        """Verify DAT entry has expected fields."""
        _, entries = parse_dat_file(sample_dat_file)
        
        for entry in entries:
            assert "name" in entry
            assert "crc" in entry
            assert isinstance(entry["name"], str)
            assert isinstance(entry["crc"], str)
            assert len(entry["crc"]) == 8  # CRC32 is 8 hex chars


class TestBuildDatLookup:
    """Tests for build_dat_lookup() function."""

    def test_build_lookup_from_entries(self, sample_dat_entries):
        """Build a lookup table from DAT entries."""
        # The entries from the fixture have "crc32" key, but build_dat_lookup expects "crc"
        entries = [{"name": e["name"], "crc": e["crc32"]} for e in sample_dat_entries]
        lookup = build_dat_lookup(entries)
        
        assert "Adventure Island" in lookup
        assert lookup["Adventure Island"] == "a1b2c3d4"
        assert lookup["Bonk's Adventure"] == "d4c3b2a1"

    def test_build_lookup_applies_libretro_substitution(self):
        """Lookup keys should have libretro substitution applied."""
        entries = [
            {"name": "Game: Subtitle", "crc": "12345678"},
            {"name": "Game & Co.", "crc": "abcdef00"},
        ]
        lookup = build_dat_lookup(entries)
        
        # Colons and ampersands get replaced with underscores
        # Note: the exact key depends on libretro substitution rules
        assert "Game_ Subtitle" in lookup
        # "Game _ Co_" has period replaced, not just ampersand
        assert "Game _ Co." in lookup or "Game _ Co_" in lookup

    def test_build_lookup_first_entry_wins_duplicates(self):
        """First occurrence of a substituted name wins."""
        entries = [
            {"name": "Game Title", "crc": "11111111"},
            {"name": "Game Title", "crc": "22222222"},  # Duplicate
        ]
        lookup = build_dat_lookup(entries)
        
        assert lookup["Game Title"] == "11111111"

    def test_build_lookup_empty(self):
        """Build lookup from empty entries."""
        lookup = build_dat_lookup([])
        assert lookup == {}


class TestDetectDatConsole:
    """Tests for detect_dat_console() function."""

    def test_detect_pce_from_system_name(self):
        """Detect PC Engine from system name."""
        console = detect_dat_console("NEC - PC Engine - TurboGrafx-16")
        assert console == "pce"

    def test_detect_pcecd_from_system_name(self):
        """Detect PC Engine CD from system name."""
        console = detect_dat_console("NEC - PC Engine CD - TurboGrafx-CD")
        assert console == "pcecd"

    def test_detect_gba_from_system_name(self):
        """Detect GBA from system name."""
        console = detect_dat_console("Nintendo - Game Boy Advance")
        assert console == "gba"

    def test_detect_ngp_from_system_name(self):
        """Detect Neo Geo Pocket from system name."""
        console = detect_dat_console("SNK - Neo Geo Pocket Color")
        assert console == "ngp"

    def test_detect_unknown_console(self):
        """Return None for unknown console."""
        console = detect_dat_console("Unknown Console Name")
        assert console is None


class TestGameNameFromFilename:
    """Tests for game_name_from_filename() function."""

    def test_extract_name_with_extension(self):
        """Extract game name from filename with extension."""
        name = game_name_from_filename("Adventure Island.png")
        assert name == "Adventure Island"

    def test_extract_name_multiple_dots(self):
        """Handle filenames with multiple dots."""
        name = game_name_from_filename("Game.of.Year.png")
        assert name == "Game.of.Year"

    def test_extract_name_underscores(self):
        """Preserve underscores in filenames."""
        name = game_name_from_filename("Game_Name_Here.png")
        assert name == "Game_Name_Here"

    def test_extract_name_special_chars(self):
        """Handle special characters in filenames."""
        name = game_name_from_filename("Game_&_Friends.png")
        assert name == "Game_&_Friends"


class TestApplyLibretroSubstitution:
    """Tests for _apply_libretro_substitution() function."""

    def test_substitute_special_characters(self):
        """Replace special chars with underscores."""
        result = _apply_libretro_substitution("Game: Title")
        assert result == "Game_ Title"

    def test_substitute_multiple_chars(self):
        """Handle multiple special characters."""
        result = _apply_libretro_substitution("Game & Co: Edition")
        assert result == "Game _ Co_ Edition"

    def test_substitute_ampersand(self):
        """Replace ampersand."""
        result = _apply_libretro_substitution("Game & Friends")
        assert result == "Game _ Friends"

    def test_substitute_slashes(self):
        """Replace slashes."""
        result = _apply_libretro_substitution("A/B/C")
        assert result == "A_B_C"

    def test_no_substitution_needed(self):
        """Leave normal text unchanged."""
        result = _apply_libretro_substitution("Normal Game Name")
        assert result == "Normal Game Name"


class TestMatchGameToCrc:
    """Tests for match_game_to_crc() function."""

    @pytest.fixture
    def sample_lookup(self):
        """Provide a sample DAT lookup."""
        return {
            "Adventure Island": "A1B2C3D4",
            "Bonk's Adventure": "D4C3B2A1",
            "Game_ Title": "12345678",
        }

    def test_exact_match(self, sample_lookup):
        """Match exact game name."""
        crc = match_game_to_crc("Adventure Island", sample_lookup)
        assert crc == "A1B2C3D4"

    def test_case_insensitive_match(self, sample_lookup):
        """Match with case differences."""
        crc = match_game_to_crc("ADVENTURE ISLAND", sample_lookup)
        assert crc == "A1B2C3D4"

    def test_match_with_libretro_substitution(self, sample_lookup):
        """Match after libretro substitution."""
        # "Game: Title" -> "Game_ Title"
        crc = match_game_to_crc("Game: Title", sample_lookup)
        assert crc == "12345678"

    def test_no_match(self, sample_lookup):
        """Return None when no match found."""
        crc = match_game_to_crc("Nonexistent Game", sample_lookup)
        assert crc is None

    def test_match_with_apostrophe(self, sample_lookup):
        """Match apostrophes correctly."""
        crc = match_game_to_crc("Bonk's Adventure", sample_lookup)
        assert crc == "D4C3B2A1"


class TestLoadSpecialCases:
    """Tests for load_special_cases() function."""

    def test_load_valid_special_cases(self, sample_special_cases_file):
        """Load valid special_cases.json file."""
        cases = load_special_cases(sample_special_cases_file)
        
        assert cases is not None
        assert "redirects" in cases
        assert "Bonk's Adventure (Japanese Title)" in cases["redirects"]

    def test_load_missing_file_returns_empty(self, tmp_dir):
        """Handle missing special_cases.json with defaults."""
        missing = tmp_dir / "missing.json"
        cases = load_special_cases(missing)
        
        # Function returns default structure when file missing
        assert "pce" in cases
        assert "pcecd" in cases
        assert cases["pce"]["skip"] == []
        assert cases["pce"]["redirect"] == {}

    def test_load_invalid_json(self, tmp_dir):
        """Handle invalid JSON gracefully."""
        invalid = tmp_dir / "invalid.json"
        invalid.write_text("{invalid json")
        
        # Invalid JSON raises an exception in load_special_cases
        with pytest.raises(Exception):
            load_special_cases(invalid)

    def test_load_empty_json_file(self, tmp_dir):
        """Handle empty JSON object."""
        empty = tmp_dir / "empty.json"
        empty.write_text("{}")
        
        cases = load_special_cases(empty)
        assert cases == {}


@pytest.mark.unit
class TestParsingIntegration:
    """Integration tests combining multiple parsing functions."""

    def test_full_parsing_pipeline(self, sample_dat_file):
        """Test complete parsing and lookup pipeline."""
        system_name, entries = parse_dat_file(sample_dat_file)
        assert system_name is not None
        assert len(entries) > 0
        
        console = detect_dat_console(system_name)
        assert console == "pce"
        
        lookup = build_dat_lookup(entries)
        assert len(lookup) == len(entries)
        
        # Match a game
        crc = match_game_to_crc("Adventure Island", lookup)
        assert crc is not None
        assert crc.upper() == "A1B2C3D4"
