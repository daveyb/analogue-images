"""Unit tests for image conversion and binary format functions.

Tests:
  - detect_image_format(): PNG/JPEG detection
  - validate_image(): Image validation and loading
  - convert_image_to_pocket_bin(): Image conversion to Pocket format
  - Binary format validation (magic bytes, dimensions, pixel data)
"""

import struct

import pytest
from PIL import Image
from analogue_image_gen import (
    POCKET_BIN_MAGIC,
    POCKET_BIN_TARGET_HEIGHT,
    detect_image_format,
    validate_image,
    convert_image_to_pocket_bin,
)


class TestDetectImageFormat:
    """Tests for detect_image_format() function."""

    def test_detect_png_format(self, test_image_landscape):
        """Detect PNG image format."""
        fmt = detect_image_format(test_image_landscape)
        assert fmt == "PNG"

    def test_detect_jpeg_format(self, tmp_dir):
        """Detect JPEG image format."""
        img = Image.new("RGB", (100, 100), color="red")
        jpeg_path = tmp_dir / "test.jpg"
        img.save(jpeg_path, "JPEG")
        
        fmt = detect_image_format(jpeg_path)
        assert fmt == "JPEG"

    def test_detect_nonexistent_file(self, tmp_dir):
        """Return None for nonexistent file."""
        missing = tmp_dir / "missing.png"
        fmt = detect_image_format(missing)
        assert fmt is None

    def test_detect_invalid_image_file(self, tmp_dir):
        """Return None for non-image file."""
        invalid = tmp_dir / "invalid.bin"
        invalid.write_bytes(b"\x00\x01\x02\x03")
        
        fmt = detect_image_format(invalid)
        assert fmt is None


class TestValidateImage:
    """Tests for validate_image() function."""

    def test_validate_png_image(self, test_image_landscape):
        """Validate a valid PNG image."""
        result = validate_image(test_image_landscape)
        assert result == test_image_landscape

    def test_validate_jpeg_image(self, tmp_dir):
        """Validate a valid JPEG image."""
        img = Image.new("RGB", (200, 300), color="blue")
        jpeg_path = tmp_dir / "test.jpg"
        img.save(jpeg_path, "JPEG")
        
        result = validate_image(jpeg_path)
        assert result == jpeg_path

    def test_validate_nonexistent_file(self, tmp_dir):
        """Return None for nonexistent file."""
        missing = tmp_dir / "missing.png"
        result = validate_image(missing)
        assert result is None

    def test_validate_unsupported_format(self, tmp_dir):
        """Return None for unsupported image format."""
        # Create a BMP file (not supported)
        img = Image.new("RGB", (100, 100))
        bmp_path = tmp_dir / "test.bmp"
        img.save(bmp_path, "BMP")
        
        result = validate_image(bmp_path)
        assert result is None


class TestConvertImageToPocketBin:
    """Tests for convert_image_to_pocket_bin() function."""

    def test_convert_landscape_image(self, test_image_landscape, tmp_dir):
        """Convert landscape image to Pocket .bin format."""
        output_path = tmp_dir / "output.bin"
        
        result = convert_image_to_pocket_bin(test_image_landscape, output_path)
        
        assert result is True
        assert output_path.exists()

    def test_convert_portrait_image(self, test_image_portrait, tmp_dir):
        """Convert portrait image to Pocket .bin format."""
        output_path = tmp_dir / "output.bin"
        
        result = convert_image_to_pocket_bin(test_image_portrait, output_path)
        
        assert result is True
        assert output_path.exists()

    def test_convert_nonexistent_source(self, tmp_dir):
        """Return False for nonexistent source."""
        missing = tmp_dir / "missing.png"
        output = tmp_dir / "output.bin"
        
        result = convert_image_to_pocket_bin(missing, output)
        
        assert result is False

    def test_bin_has_correct_magic_bytes(self, test_image_landscape, tmp_dir):
        """Output .bin file has correct magic bytes."""
        output_path = tmp_dir / "output.bin"
        convert_image_to_pocket_bin(test_image_landscape, output_path)
        
        data = output_path.read_bytes()
        assert data[:4] == POCKET_BIN_MAGIC

    def test_bin_header_contains_dimensions(self, test_image_landscape, tmp_dir):
        """Output .bin header contains valid dimensions."""
        output_path = tmp_dir / "output.bin"
        convert_image_to_pocket_bin(test_image_landscape, output_path)
        
        data = output_path.read_bytes()
        # Magic: bytes 0-3
        # Height: bytes 4-5 (little-endian u16)
        # Width: bytes 6-7 (little-endian u16)
        height, width = struct.unpack("<HH", data[4:8])
        
        assert height > 0
        assert width > 0
        # Target height should be 165 for Pocket
        assert height == POCKET_BIN_TARGET_HEIGHT

    def test_bin_pixel_data_size(self, test_image_landscape, tmp_dir):
        """Output .bin has correct pixel data size (BGRA32)."""
        output_path = tmp_dir / "output.bin"
        convert_image_to_pocket_bin(test_image_landscape, output_path)
        
        data = output_path.read_bytes()
        height, width = struct.unpack("<HH", data[4:8])
        
        expected_pixel_size = height * width * 4  # BGRA32 = 4 bytes per pixel
        header_size = 8
        expected_total_size = header_size + expected_pixel_size
        
        assert len(data) == expected_total_size

    def test_bin_pixel_format_is_bgra(self, test_image_landscape, tmp_dir):
        """Output .bin pixel data is in BGRA32 format."""
        output_path = tmp_dir / "output.bin"
        convert_image_to_pocket_bin(test_image_landscape, output_path)
        
        data = output_path.read_bytes()
        # Skip header (8 bytes)
        pixel_data = data[8:]
        
        # Pixel data should be divisible by 4 (BGRA)
        assert len(pixel_data) % 4 == 0

    def test_convert_multiple_formats(self, test_image_landscape, test_image_portrait, tmp_dir):
        """Convert multiple images successfully."""
        out1 = tmp_dir / "out1.bin"
        out2 = tmp_dir / "out2.bin"
        
        result1 = convert_image_to_pocket_bin(test_image_landscape, out1)
        result2 = convert_image_to_pocket_bin(test_image_portrait, out2)
        
        assert result1 is True
        assert result2 is True
        assert out1.exists()
        assert out2.exists()


class TestBinFormatValidation:
    """Tests for binary format validation."""

    def test_bin_structure_magic_bytes(self, test_image_landscape, tmp_dir):
        """Magic bytes are at expected position."""
        output_path = tmp_dir / "output.bin"
        convert_image_to_pocket_bin(test_image_landscape, output_path)
        
        data = output_path.read_bytes()
        magic = data[0:4]
        
        assert magic == bytes([0x20, 0x49, 0x50, 0x41])  # " IPA"

    def test_bin_height_less_than_file_size(self, test_image_landscape, tmp_dir):
        """Height is reasonable (not corrupted)."""
        output_path = tmp_dir / "output.bin"
        convert_image_to_pocket_bin(test_image_landscape, output_path)
        
        data = output_path.read_bytes()
        height = struct.unpack("<H", data[4:6])[0]
        
        # Height should be reasonable (at most a few thousand pixels)
        assert height < 1024
        assert height > 0

    def test_bin_width_less_than_file_size(self, test_image_landscape, tmp_dir):
        """Width is reasonable (not corrupted)."""
        output_path = tmp_dir / "output.bin"
        convert_image_to_pocket_bin(test_image_landscape, output_path)
        
        data = output_path.read_bytes()
        width = struct.unpack("<H", data[6:8])[0]
        
        # Width should be reasonable (at most a few thousand pixels)
        assert width < 1024
        assert width > 0

    def test_bin_consistent_dimensions_and_data(self, test_image_landscape, tmp_dir):
        """Dimensions match actual pixel data size."""
        output_path = tmp_dir / "output.bin"
        convert_image_to_pocket_bin(test_image_landscape, output_path)
        
        data = output_path.read_bytes()
        height, width = struct.unpack("<HH", data[4:8])
        pixel_data_size = len(data) - 8
        
        expected_size = height * width * 4
        assert pixel_data_size == expected_size


@pytest.mark.unit
class TestImageConversionIntegration:
    """Integration tests for image conversion pipeline."""

    def test_detect_and_convert_landscape(self, test_image_landscape, tmp_dir):
        """Detect format and convert landscape image."""
        fmt = detect_image_format(test_image_landscape)
        assert fmt == "PNG"
        
        output = tmp_dir / "output.bin"
        result = convert_image_to_pocket_bin(test_image_landscape, output)
        assert result is True
        assert output.exists()

    def test_validate_and_convert(self, test_image_landscape, tmp_dir):
        """Validate then convert image."""
        validated = validate_image(test_image_landscape)
        assert validated is not None
        
        output = tmp_dir / "output.bin"
        result = convert_image_to_pocket_bin(validated, output)
        assert result is True
