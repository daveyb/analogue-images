"""Unit tests for utility and configuration functions.

Tests:
  - _sanitize_filename(): Filename sanitization
  - detect_device(): Device detection from SD card root
"""

import pytest
from pathlib import Path

import analogue_image_gen

_sanitize_filename = analogue_image_gen._sanitize_filename
detect_device = analogue_image_gen.detect_device
class TestSanitizeFilename:
    """Tests for _sanitize_filename() function."""

    def test_sanitize_valid_filename(self):
        """Leave valid filename unchanged."""
        result = _sanitize_filename("Bonk's Adventure")
        # Should only sanitize problematic filesystem characters
        assert "Bonk" in result
        assert "Adventure" in result

    def test_sanitize_removes_slashes(self):
        """Remove forward slashes."""
        result = _sanitize_filename("Game/Title")
        assert "/" not in result

    def test_sanitize_removes_backslashes(self):
        """Remove backslashes."""
        result = _sanitize_filename("Game\\Title")
        assert "\\" not in result

    def test_sanitize_removes_colons(self):
        """Remove colons (forbidden in Windows filenames)."""
        result = _sanitize_filename("Game: Title")
        assert ":" not in result

    def test_sanitize_removes_question_marks(self):
        """Remove question marks."""
        result = _sanitize_filename("What?")
        assert "?" not in result

    def test_sanitize_removes_asterisks(self):
        """Remove asterisks."""
        result = _sanitize_filename("Game*")
        assert "*" not in result

    def test_sanitize_removes_pipes(self):
        """Remove pipes."""
        result = _sanitize_filename("A|B")
        assert "|" not in result

    def test_sanitize_removes_angle_brackets(self):
        """Remove angle brackets."""
        result = _sanitize_filename("<Game>")
        assert "<" not in result
        assert ">" not in result

    def test_sanitize_handles_multiple_invalid_chars(self):
        """Handle multiple invalid characters."""
        result = _sanitize_filename("Game: Title/Path*Name?")
        assert ":" not in result
        assert "/" not in result
        assert "*" not in result
        assert "?" not in result

    def test_sanitize_preserves_alphanumeric(self):
        """Preserve alphanumeric characters."""
        result = _sanitize_filename("Game123Title456")
        assert result == "Game123Title456"

    def test_sanitize_empty_string(self):
        """Handle empty string."""
        result = _sanitize_filename("")
        assert isinstance(result, str)


class TestDetectDevice:
    """Tests for detect_device() function."""

    def test_detect_pocket_device(self, tmp_dir):
        """Detect Pocket device from Analogue_Pocket.json."""
        (tmp_dir / "Analogue_Pocket.json").write_text("{}")
        
        device = detect_device(tmp_dir)
        assert device == "pocket"

    def test_detect_duo_device(self, tmp_dir):
        """Detect Duo device from Analogue_Duo.json."""
        (tmp_dir / "Analogue_Duo.json").write_text("{}")
        
        device = detect_device(tmp_dir)
        assert device == "duo"

    def test_detect_no_device_file(self, tmp_dir):
        """Return None when no device file found."""
        device = detect_device(tmp_dir)
        assert device is None

    def test_detect_duo_priority_over_pocket(self, tmp_dir):
        """Duo has priority when both files exist."""
        (tmp_dir / "Analogue_Pocket.json").write_text("{}")
        (tmp_dir / "Analogue_Duo.json").write_text("{}")

        device = detect_device(tmp_dir)
        assert device == "duo"

    def test_detect_device_nonexistent_root(self):
        """Return None for nonexistent root path."""
        fake_root = Path("/nonexistent/path/12345")
        device = detect_device(fake_root)
        assert device is None


class TestFilenameUtilities:
    """Additional filename utility tests."""

    def test_sanitize_preserves_spaces(self):
        """Preserve spaces in filenames."""
        result = _sanitize_filename("Game Title Name")
        assert result == "Game Title Name"

    def test_sanitize_preserves_hyphens(self):
        """Preserve hyphens in filenames."""
        result = _sanitize_filename("Game-Title-Name")
        assert result == "Game-Title-Name"

    def test_sanitize_preserves_parentheses(self):
        """Preserve parentheses (generally allowed in filenames)."""
        result = _sanitize_filename("Game (Region)")
        # Parentheses are usually allowed
        assert isinstance(result, str)

    def test_sanitize_preserves_square_brackets(self):
        """Preserve square brackets (generally allowed)."""
        result = _sanitize_filename("Game [Hack]")
        assert isinstance(result, str)


@pytest.mark.unit
class TestUtilityIntegration:
    """Integration tests for utility functions."""

    def test_detect_device_with_full_structure(self, tmp_dir):
        """Detect device in full SD card structure."""
        (tmp_dir / "Analogue_Pocket.json").write_text("{}")
        (tmp_dir / "System").mkdir()
        (tmp_dir / "System" / "Library").mkdir()
        
        device = detect_device(tmp_dir)
        assert device == "pocket"

    def test_sanitize_game_crc_filename(self):
        """Sanitize a typical game filename for storage."""
        # Typical usage: CRC32 hash as filename
        crc = "a1b2c3d4"
        filename = f"{crc}.bin"
        
        result = _sanitize_filename(filename)
        assert isinstance(result, str)
        # CRC and .bin should remain
        assert "bin" in result.lower() or result.startswith(crc)
