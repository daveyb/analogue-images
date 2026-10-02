"""Tests for the Analogue Pocket .bin image conversion pipeline.

Verifies:
  - Correct magic bytes in output header
  - Portrait orientation (height > width) for typical landscape boxart sources
  - Header dimensions match actual pixel data size
  - Rotation: -90° CCW (PIL rotate(90)) applied before scaling
  - Pixel data is BGRA32 (4 bytes per pixel)
  - Scale target: height = 165 px

Run with: python scripts/test_image_conversion.py
"""

import struct
import sys
import tempfile
import traceback
from pathlib import Path

# Resolve repo root so this script works from any cwd
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

try:
    from PIL import Image, ImageDraw
except ImportError:
    sys.exit("Pillow is required: pip install Pillow")

from analogue_image_gen import (
    POCKET_BIN_MAGIC,
    POCKET_BIN_TARGET_HEIGHT,
    POCKET_THUMB_BYTES,
    POCKET_THUMB_STORED_HEIGHT,
    POCKET_THUMB_STORED_WIDTH,
    POCKET_THUMBS_IMAGE_OFFSET,
    POCKET_THUMBS_MAGIC,
    convert_image_to_pocket_bin,
    sync_pocket_thumbs,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"

_results: list[tuple[str, bool, str]] = []


def _check(name: str, condition: bool, detail: str = "") -> bool:
    label = PASS if condition else FAIL
    msg = f"  [{label}] {name}"
    if detail:
        msg += f" — {detail}"
    print(msg)
    _results.append((name, condition, detail))
    return condition


def _make_test_image(width: int, height: int) -> Image.Image:
    """Create a synthetic RGBA test image with a distinct arrow pattern."""
    img = Image.new("RGBA", (width, height), (200, 50, 50, 255))
    draw = ImageDraw.Draw(img)
    cx, cy = width // 2, height // 2
    draw.rectangle([cx - 5, cy, cx + 5, cy + height // 4], fill=(255, 255, 0, 255))
    tip_y = cy - height // 4
    draw.polygon(
        [(cx, tip_y), (cx - 20, cy), (cx + 20, cy)],
        fill=(255, 255, 0, 255),
    )
    return img


def _read_bin(path: Path) -> tuple[int, int, bytes]:
    """Return (width, height, pixel_bytes) from an Analogue .bin file."""
    data = path.read_bytes()
    h, w = struct.unpack("<HH", data[4:8])
    return w, h, data[8:]


# ---------------------------------------------------------------------------
# Individual test cases
# ---------------------------------------------------------------------------


def test_magic_bytes(tmp_dir: Path) -> None:
    print("\n[Test] Magic bytes")
    src = tmp_dir / "src_magic.png"
    dst = tmp_dir / "out_magic.bin"
    _make_test_image(300, 400).save(src)
    ok = convert_image_to_pocket_bin(src, dst)
    _check("convert returned True", ok)
    raw = dst.read_bytes()
    _check("Magic == 0x20 0x49 0x50 0x41", raw[:4] == POCKET_BIN_MAGIC, f"got {raw[:4].hex()}")


def test_portrait_output_from_landscape_source(tmp_dir: Path) -> None:
    print("\n[Test] Portrait output from landscape source")
    src = tmp_dir / "src_landscape.png"
    dst = tmp_dir / "out_landscape.bin"
    _make_test_image(600, 594).save(src)
    convert_image_to_pocket_bin(src, dst)
    w, h, _ = _read_bin(dst)
    _check("height == 165", h == POCKET_BIN_TARGET_HEIGHT, f"h={h}")
    _check("portrait: width < height", w < h, f"w={w}, h={h}")
    _check("width ≈ 163", 160 <= w <= 165, f"w={w}")


def test_portrait_output_from_portrait_source(tmp_dir: Path) -> None:
    print("\n[Test] Scale target from portrait source")
    src = tmp_dir / "src_portrait.png"
    dst = tmp_dir / "out_portrait.bin"
    _make_test_image(500, 700).save(src)
    convert_image_to_pocket_bin(src, dst)
    w, h, _ = _read_bin(dst)
    _check("height == 165", h == POCKET_BIN_TARGET_HEIGHT, f"h={h}")
    _check("width proportional to rotated source", 225 <= w <= 235, f"w={w}")


def test_header_dimensions_match_pixel_data(tmp_dir: Path) -> None:
    print("\n[Test] Header dimensions match pixel data size")
    for label, src_w, src_h in [
        ("landscape 600x594", 600, 594),
        ("portrait 400x600", 400, 600),
        ("square 512x512", 512, 512),
    ]:
        src = tmp_dir / f"src_{label.split()[0]}.png"
        dst = tmp_dir / f"out_{label.split()[0]}.bin"
        _make_test_image(src_w, src_h).save(src)
        convert_image_to_pocket_bin(src, dst)
        w, h, pixels = _read_bin(dst)
        expected = w * h * 4
        _check(f"{label}: pixel bytes == w*h*4", len(pixels) == expected, f"expected {expected}, got {len(pixels)}")


def test_rotation_90ccw(tmp_dir: Path) -> None:
    print("\n[Test] Rotation correctness (-90° / 90°CCW)")
    src_w, src_h = 100, 120
    src = tmp_dir / "src_rotation.png"
    dst = tmp_dir / "out_rotation.bin"
    img = Image.new("RGBA", (src_w, src_h), (128, 128, 128, 255))
    for x in range(10):
        for y in range(10):
            img.putpixel((x, y), (0, 255, 0, 255))
    img.save(src)
    convert_image_to_pocket_bin(src, dst)
    out_w, out_h, pixels = _read_bin(dst)

    def get_pixel_rgba(pixels: bytes, x: int, y: int, w: int) -> tuple:
        idx = (y * w + x) * 4
        b, g, r, a = pixels[idx], pixels[idx + 1], pixels[idx + 2], pixels[idx + 3]
        return (r, g, b, a)

    pixel = get_pixel_rgba(pixels, 1, out_h - 2, out_w)
    _check("Bottom-left of output is green (top-left of source after 90°CCW)", pixel[1] > 200 and pixel[0] < 100, f"RGBA{pixel}")
    pixel2 = get_pixel_rgba(pixels, 1, 1, out_w)
    _check("Top-left of output is NOT green (gray background after 90°CCW)", pixel2[1] < 200, f"RGBA{pixel2}")


def test_bgra32_pixel_format(tmp_dir: Path) -> None:
    print("\n[Test] BGRA32 pixel format")
    src = tmp_dir / "src_bgra.png"
    dst = tmp_dir / "out_bgra.bin"
    img = Image.new("RGBA", (100, 80), (255, 0, 0, 255))
    img.save(src)
    convert_image_to_pocket_bin(src, dst)
    _, _, pixels = _read_bin(dst)
    b, g, r, a = pixels[0], pixels[1], pixels[2], pixels[3]
    _check("First pixel B=0 (pure red source)", b == 0, f"B={b}")
    _check("First pixel G=0 (pure red source)", g == 0, f"G={g}")
    _check("First pixel R=255 (pure red source)", r == 255, f"R={r}")
    _check("First pixel A=255 (pure red source)", a == 255, f"A={a}")


def test_bonks_adventure_bin(bonks_path: Path | None, tmp_dir: Path) -> None:
    print("\n[Test] Bonk's Adventure bin on SD card (599ead9b.bin)")
    if bonks_path is None or not bonks_path.exists():
        print("  [SKIP] 599ead9b.bin not found — SD card not mounted or file missing")
        return
    raw = bonks_path.read_bytes()
    w, h, pixels = _read_bin(bonks_path)
    _check("Magic bytes correct", raw[:4] == POCKET_BIN_MAGIC, raw[:4].hex())
    _check("Height == 165", h == POCKET_BIN_TARGET_HEIGHT, f"h={h}")
    _check("Portrait orientation (w < h)", w < h, f"w={w}, h={h}")
    expected_px = w * h * 4
    _check("Pixel data size == w*h*4", len(pixels) == expected_px, f"expected {expected_px}, got {len(pixels)}")
    _check("Width ≈ 163", 160 <= w <= 165, f"w={w}")


def test_bonks_adventure_name_file(name_path: Path | None) -> None:
    print("\n[Test] Bonk's Adventure name-based file on SD card")
    crc_path = name_path.parent / "599ead9b.bin" if name_path else None
    if name_path is None or not name_path.exists():
        print("  [SKIP] Bonk's Adventure (USA).bin not found — SD card not mounted or file missing")
        return
    if crc_path is None or not crc_path.exists():
        print("  [SKIP] 599ead9b.bin not found — cannot compare")
        return
    name_raw = name_path.read_bytes()
    crc_raw = crc_path.read_bytes()
    w, h, pixels = _read_bin(name_path)
    _check("Magic bytes correct", name_raw[:4] == POCKET_BIN_MAGIC, name_raw[:4].hex())
    _check("Height == 165", h == POCKET_BIN_TARGET_HEIGHT, f"h={h}")
    _check("Portrait orientation (w < h)", w < h, f"w={w}, h={h}")
    _check("Name file identical to CRC file", name_raw == crc_raw, f"name={len(name_raw)}B, crc={len(crc_raw)}B")


# ---------------------------------------------------------------------------
# Library grid bundle tests
# ---------------------------------------------------------------------------

BONK_CRC = 0x599EAD9B


def _solid_library_bin(width: int, height: int, pixel: bytes) -> bytes:
    return POCKET_BIN_MAGIC + struct.pack("<HH", height, width) + pixel * (width * height)


def test_grid_bundle_layout(tmp_dir: Path) -> None:
    print("\n[Test] library grid bundle layout")
    src = tmp_dir / "grid_src"
    src.mkdir()
    out = tmp_dir / "pce_thumbs.bin"
    pixel = bytes([1, 2, 3, 255])
    (src / "11223344.bin").write_bytes(
        _solid_library_bin(POCKET_THUMB_STORED_WIDTH, POCKET_THUMB_STORED_HEIGHT, pixel)
    )
    (src / "aabbccdd.bin").write_bytes(_solid_library_bin(200, 80, pixel))
    stats = sync_pocket_thumbs(src, out)
    _check("sync wrote the bundle", stats["wrote"] is True and stats["images"] == 2)
    raw = out.read_bytes()
    _check("Magic == 02 46 54 41", raw[:4] == POCKET_THUMBS_MAGIC, raw[:4].hex())
    per_image, count = struct.unpack_from("<II", raw, 4)
    _check("per-image size == 52764", per_image == POCKET_THUMB_BYTES, str(per_image))
    _check("image count == 2", count == 2, str(count))
    first_crc, first_off = struct.unpack_from("<II", raw, 12)
    second_crc, second_off = struct.unpack_from("<II", raw, 20)
    _check("first slot offset == 65548", first_off == POCKET_THUMBS_IMAGE_OFFSET, str(first_off))
    _check(
        "second slot follows the first image",
        second_off == POCKET_THUMBS_IMAGE_OFFSET + POCKET_THUMB_BYTES,
        str(second_off),
    )
    _check("slots are sequential, not hashed", {first_crc, second_crc} == {0x11223344, 0xAABBCCDD})
    stored_h, stored_w = struct.unpack_from("<HH", raw, first_off + 4)
    _check(
        "stored size is 121 by 109",
        (stored_h, stored_w) == (POCKET_THUMB_STORED_HEIGHT, POCKET_THUMB_STORED_WIDTH),
        f"{stored_h}x{stored_w}",
    )
    again = sync_pocket_thumbs(src, out)
    _check("second sync does not rewrite", again["wrote"] is False and out.read_bytes() == raw)


def test_grid_ignores_name_files(tmp_dir: Path) -> None:
    print("\n[Test] library grid ignores name-based files")
    src = tmp_dir / "grid_names"
    src.mkdir()
    out = tmp_dir / "ngp_thumbs.bin"
    (src / "cafebabe.bin").write_bytes(_solid_library_bin(40, 60, bytes([9, 9, 9, 255])))
    (src / "Bonk's Adventure.bin").write_bytes(_solid_library_bin(40, 60, bytes([9, 9, 9, 255])))
    sync_pocket_thumbs(src, out)
    count = struct.unpack_from("<I", out.read_bytes(), 8)[0]
    _check("only the CRC file is in the bundle", count == 1, str(count))


def test_grid_keeps_existing_pixels(tmp_dir: Path) -> None:
    print("\n[Test] library grid keeps pixels already in the bundle")
    src = tmp_dir / "grid_keep"
    src.mkdir()
    out = tmp_dir / "gg_thumbs.bin"
    red = bytes([0, 0, 255, 255])
    (src / "00000001.bin").write_bytes(_solid_library_bin(30, 40, red))
    sync_pocket_thumbs(src, out)
    first = out.read_bytes()
    per = struct.unpack_from("<I", first, 4)[0]
    off = struct.unpack_from("<I", first, 16)[0]
    kept = first[off : off + per]
    (src / "00000002.bin").write_bytes(_solid_library_bin(30, 40, bytes([255, 0, 0, 255])))
    sync_pocket_thumbs(src, out)
    second = out.read_bytes()
    count = struct.unpack_from("<I", second, 8)[0]
    off2 = struct.unpack_from("<I", second, 16)[0]
    _check("count grew to 2", count == 2, str(count))
    _check("first image bytes are unchanged", second[off2 : off2 + per] == kept)


def test_sd_grid_bundle(sd_thumbs_path: Path | None) -> None:
    print("\n[Test] SD card pce_thumbs.bin structure")
    if sd_thumbs_path is None or not sd_thumbs_path.exists():
        print("  [SKIP] pce_thumbs.bin not on SD card")
        return
    raw = sd_thumbs_path.read_bytes()
    _check("Magic == 02 46 54 41", raw[:4] == POCKET_THUMBS_MAGIC, raw[:4].hex())
    per_image, count = struct.unpack_from("<II", raw, 4)
    _check("per-image size == 52764", per_image == POCKET_THUMB_BYTES, str(per_image))
    _check("image count > 0", count > 0, str(count))
    found = False
    for index in range(count):
        crc, offset = struct.unpack_from("<II", raw, 12 + index * 8)
        if crc == BONK_CRC:
            found = True
            _check("Bonk offset points at an IPA image", raw[offset : offset + 4] == POCKET_BIN_MAGIC)
            h, w = struct.unpack_from("<HH", raw, offset + 4)
            _check(
                "Bonk grid image is 121 by 109",
                (h, w) == (POCKET_THUMB_STORED_HEIGHT, POCKET_THUMB_STORED_WIDTH),
                f"{h}x{w}",
            )
            break
    _check("Bonk's Adventure (CRC 599ead9b) is in the grid", found)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    print("=" * 60)
    print("Analogue Pocket .bin conversion tests")
    print("=" * 60)

    sd_images = None
    for root in (Path("D:/"), Path("E:/")):
        candidate = root / "System" / "Library" / "Images"
        if (candidate / "pce").is_dir():
            sd_images = candidate
            break
    sd_pce_dir = (sd_images / "pce") if sd_images else Path("missing")
    sd_bonks = sd_pce_dir / "599ead9b.bin"
    sd_bonks_name = sd_pce_dir / "Bonk's Adventure (USA).bin"
    sd_bonks_db_name = sd_pce_dir / "Bonk's Adventure.bin"
    sd_thumbs = (sd_images / "pce_thumbs.bin") if sd_images else None

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        try:
            test_magic_bytes(tmp_dir)
            test_portrait_output_from_landscape_source(tmp_dir)
            test_portrait_output_from_portrait_source(tmp_dir)
            test_header_dimensions_match_pixel_data(tmp_dir)
            test_rotation_90ccw(tmp_dir)
            test_bgra32_pixel_format(tmp_dir)
            test_bonks_adventure_bin(sd_bonks, tmp_dir)
            test_bonks_adventure_name_file(sd_bonks_name)
            test_bonks_adventure_name_file(sd_bonks_db_name)
            test_grid_bundle_layout(tmp_dir)
            test_grid_ignores_name_files(tmp_dir)
            test_grid_keeps_existing_pixels(tmp_dir)
            test_sd_grid_bundle(sd_thumbs)
        except Exception:
            traceback.print_exc()
            return 1

    print("\n" + "=" * 60)
    passed = sum(1 for _, ok, _ in _results if ok)
    failed = sum(1 for _, ok, _ in _results if not ok)
    print(f"Results: {passed} passed, {failed} failed")
    if failed:
        print("\nFailed tests:")
        for name, ok, detail in _results:
            if not ok:
                print(f"  - {name}: {detail}")
    print("=" * 60)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
