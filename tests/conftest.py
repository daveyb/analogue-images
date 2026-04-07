"""Shared pytest fixtures for the test suite.

Provides:
  - Temporary directories for file operations
  - Sample DAT files with game entries
  - Mock images (synthetic PNG/BIN files)
  - Common test data (CRCs, game names, paths)
"""

import json
import struct
import tempfile
from pathlib import Path

import pytest
from PIL import Image, ImageDraw


# =============================================================================
# Temporary directories
# =============================================================================


@pytest.fixture
def tmp_dir():
    """Create and provide a temporary directory for tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


# =============================================================================
# Sample DAT files
# =============================================================================


@pytest.fixture
def sample_dat_entries():
    """Return sample DAT file entries for PC Engine games."""
    return [
        {
            "name": "Adventure Island",
            "crc32": "a1b2c3d4",
            "status": "good",
        },
        {
            "name": "Bonk's Adventure",
            "crc32": "d4c3b2a1",
            "status": "good",
        },
        {
            "name": "Castlevania: Rondo of Blood",
            "crc32": "12345678",
            "status": "good",
        },
        {
            "name": "Military Madness",
            "crc32": "abcdef00",
            "status": "good",
        },
        {
            "name": "Ninja Spirit",
            "crc32": "fedcba00",
            "status": "good",
        },
    ]


@pytest.fixture
def sample_dat_file(tmp_dir, sample_dat_entries):
    """Create a sample DAT file (XML format) and return path."""
    dat_content = """<?xml version="1.0"?>
<datafile>
	<header>
		<name>PC Engine</name>
		<description>NEC - PC Engine - TurboGrafx-16</description>
	</header>
	<game name="Adventure Island">
		<rom name="Adventure Island.pce" crc="a1b2c3d4" />
	</game>
	<game name="Bonk's Adventure">
		<rom name="Bonks Adventure.pce" crc="d4c3b2a1" />
	</game>
	<game name="Castlevania: Rondo of Blood">
		<rom name="Castlevania - Rondo of Blood.cue" crc="12345678" />
	</game>
	<game name="Military Madness">
		<rom name="Military Madness.pce" crc="abcdef00" />
	</game>
	<game name="Ninja Spirit">
		<rom name="Ninja Spirit.pce" crc="fedcba00" />
	</game>
</datafile>
"""
    dat_path = tmp_dir / "test.dat"
    dat_path.write_text(dat_content)
    return dat_path


# =============================================================================
# Sample special cases configuration
# =============================================================================


@pytest.fixture
def sample_special_cases():
    """Return sample special_cases.json data."""
    return {
        "redirects": {
            "Bonk's Adventure (Japanese Title)": "Bonk's Adventure",
            "Military Madness (Alt)": "Military Madness",
        },
        "skip_patterns": ["Virtual Console", "[Hack]", "[Homebrew]"],
    }


@pytest.fixture
def sample_special_cases_file(tmp_dir, sample_special_cases):
    """Create a sample special_cases.json file and return path."""
    config_path = tmp_dir / "special_cases.json"
    config_path.write_text(json.dumps(sample_special_cases, indent=2))
    return config_path


# =============================================================================
# Test images
# =============================================================================


@pytest.fixture
def test_image_landscape(tmp_dir):
    """Create a test landscape image (300x200) and return path."""
    img = Image.new("RGBA", (300, 200), (100, 150, 200, 255))
    draw = ImageDraw.Draw(img)
    # Draw a simple pattern for testing
    draw.rectangle([50, 50, 250, 150], outline=(255, 255, 0, 255), width=2)
    path = tmp_dir / "landscape.png"
    img.save(path)
    return path


@pytest.fixture
def test_image_portrait(tmp_dir):
    """Create a test portrait image (200x300) and return path."""
    img = Image.new("RGBA", (200, 300), (200, 100, 150, 255))
    draw = ImageDraw.Draw(img)
    # Draw a simple pattern for testing
    draw.rectangle([30, 50, 170, 250], outline=(0, 255, 255, 255), width=2)
    path = tmp_dir / "portrait.png"
    img.save(path)
    return path


@pytest.fixture
def test_image_square(tmp_dir):
    """Create a test square image (256x256) and return path."""
    img = Image.new("RGBA", (256, 256), (150, 200, 100, 255))
    draw = ImageDraw.Draw(img)
    # Draw a simple pattern for testing
    draw.ellipse([50, 50, 206, 206], outline=(255, 0, 255, 255), width=2)
    path = tmp_dir / "square.png"
    img.save(path)
    return path


# =============================================================================
# Test data constants
# =============================================================================


@pytest.fixture
def test_data():
    """Provide common test data constants."""
    return {
        "game_names": [
            "Adventure Island",
            "Bonk's Adventure",
            "Castlevania: Rondo of Blood",
            "Military Madness",
            "Ninja Spirit",
        ],
        "crcs": {
            "Adventure Island": "a1b2c3d4",
            "Bonk's Adventure": "d4c3b2a1",
            "Castlevania: Rondo of Blood": "12345678",
            "Military Madness": "abcdef00",
            "Ninja Spirit": "fedcba00",
        },
        "sd_root_structure": {
            "System": {
                "Played Games": ["list.bin"],
                "Library": {
                    "Images": {
                        "pce": [],
                        "gba": [],
                        "ngp": [],
                    }
                },
            },
            "Assets": {
                "pce": {"common": []},
                "gba": {"common": []},
                "ngp": {"common": []},
            },
        },
    }
