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
    PCE_THUMBS_HASH_ENTRY_SIZE,
    PCE_THUMBS_HASH_SLOTS,
    PCE_THUMBS_HEADER_SIZE,
    PCE_THUMBS_MAGIC,
    PCE_THUMBS_THUMB_HEIGHT,
    POCKET_BIN_MAGIC,
    POCKET_BIN_TARGET_HEIGHT,
    convert_image_to_pocket_bin,
    generate_pce_thumbs_bin,
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
# pce_thumbs.bin tests
# ---------------------------------------------------------------------------

BONK_CRC = 0x599EAD9B


def _make_fake_bin(crc: int, h: int, w: int) -> bytes:
    pixel_data = bytes([0x00, 0x00, 0xFF, 0xFF]) * (h * w)
    return POCKET_BIN_MAGIC + struct.pack("<HH", h, w) + pixel_data


def _thumb_dims(orig_h: int, orig_w: int) -> tuple[int, int]:
    scale = PCE_THUMBS_THUMB_HEIGHT / orig_h
    return PCE_THUMBS_THUMB_HEIGHT, max(1, int(orig_w * scale))


def _thumb_size(orig_h: int, orig_w: int) -> int:
    th, tw = _thumb_dims(orig_h, orig_w)
    return 8 + th * tw * 4


def _hash_slot(crc: int) -> int:
    return crc % PCE_THUMBS_HASH_SLOTS


def test_pce_thumbs_structure(tmp_dir: Path) -> None:
    print("\n[Test] pce_thumbs.bin structure")
    src = tmp_dir / "thumbs_src"
    src.mkdir()
    out = tmp_dir / "pce_thumbs.bin"
    src_dims = [(200, 160), (180, 140)]
    crcs = [0x11223344, 0xAABBCCDD]
    expected_data_size = 0
    for c, (sh, sw) in zip(crcs, src_dims):
        data = _make_fake_bin(c, sh, sw)
        (src / f"{c:08x}.bin").write_bytes(data)
        expected_data_size += _thumb_size(sh, sw)
    ok = generate_pce_thumbs_bin(src, out)
    _check("generate_pce_thumbs_bin returned True", ok)
    raw = out.read_bytes()
    _check("File exists and is non-empty", len(raw) > PCE_THUMBS_HEADER_SIZE)
    _check("Magic == 02 46 54 41", raw[:4] == PCE_THUMBS_MAGIC, raw[:4].hex())
    data_size = struct.unpack_from("<I", raw, 4)[0]
    _check("data_size == sum of thumbnail entry sizes", data_size == expected_data_size, f"data_size={data_size}, expected={expected_data_size}")
    img_count = struct.unpack_from("<I", raw, 8)[0]
    _check("image count == 2", img_count == 2, f"got {img_count}")
    _check("file size == header + data_size", len(raw) == PCE_THUMBS_HEADER_SIZE + data_size, f"file={len(raw)}, expected={PCE_THUMBS_HEADER_SIZE + data_size}")


def test_pce_thumbs_hash_table(tmp_dir: Path) -> None:
    print("\n[Test] pce_thumbs.bin hash table correctness")
    src = tmp_dir / "thumbs_hash_src"
    src.mkdir()
    out = tmp_dir / "pce_thumbs_hash.bin"
    crcs = [0x6AA69A8B, 0x12345678, 0xDEADBEEF]
    src_h, src_w = 200, 160
    thumb_sz = _thumb_size(src_h, src_w)
    data_map: dict[int, bytes] = {}
    for c in crcs:
        data = _make_fake_bin(c, src_h, src_w)
        (src / f"{c:08x}.bin").write_bytes(data)
        data_map[c] = data
    generate_pce_thumbs_bin(src, out)
    raw = out.read_bytes()
    sorted_crcs = sorted(data_map.keys(), key=lambda c: f"{c:08x}")
    expected_offsets: dict[int, int] = {}
    offset = 0
    for c in sorted_crcs:
        expected_offsets[c] = offset
        offset += thumb_sz
    for c in crcs:
        slot = _hash_slot(c)
        found_slot = None
        for probe in range(PCE_THUMBS_HASH_SLOTS):
            s = (slot + probe) % PCE_THUMBS_HASH_SLOTS
            off = 12 + s * PCE_THUMBS_HASH_ENTRY_SIZE
            if struct.unpack_from("<I", raw, off)[0] == c:
                found_slot = s
                break
        _check(f"CRC {c:08x} found in hash table", found_slot is not None, f"expected near slot {slot}")
        if found_slot is not None:
            off = 12 + found_slot * PCE_THUMBS_HASH_ENTRY_SIZE
            data_off = struct.unpack_from("<I", raw, off + 4)[0]
            _check(f"CRC {c:08x} data_offset correct", data_off == expected_offsets[c], f"got {data_off}, expected {expected_offsets[c]}")


def test_pce_thumbs_image_data(tmp_dir: Path) -> None:
    print("\n[Test] pce_thumbs.bin image data integrity")
    src = tmp_dir / "thumbs_img_src"
    src.mkdir()
    out = tmp_dir / "pce_thumbs_img.bin"
    src_h, src_w = 200, 160
    th, tw = _thumb_dims(src_h, src_w)
    crcs = [0xAABBCCDD, 0x11223344]
    for c in crcs:
        (src / f"{c:08x}.bin").write_bytes(_make_fake_bin(c, src_h, src_w))
    generate_pce_thumbs_bin(src, out)
    raw = out.read_bytes()
    for c in crcs:
        slot = _hash_slot(c)
        for probe in range(PCE_THUMBS_HASH_SLOTS):
            s = (slot + probe) % PCE_THUMBS_HASH_SLOTS
            off = 12 + s * PCE_THUMBS_HASH_ENTRY_SIZE
            if struct.unpack_from("<I", raw, off)[0] == c:
                data_off = struct.unpack_from("<I", raw, off + 4)[0]
                img_start = PCE_THUMBS_HEADER_SIZE + data_off
                img_magic = raw[img_start: img_start + 4]
                _check(f"CRC {c:08x} image magic == ' IPA'", img_magic == POCKET_BIN_MAGIC, img_magic.hex())
                stored_h = struct.unpack_from("<H", raw, img_start + 4)[0]
                stored_w = struct.unpack_from("<H", raw, img_start + 6)[0]
                _check(f"CRC {c:08x} thumbnail height == {PCE_THUMBS_THUMB_HEIGHT}", stored_h == PCE_THUMBS_THUMB_HEIGHT, f"h={stored_h}")
                _check(f"CRC {c:08x} thumbnail width == {tw}", stored_w == tw, f"w={stored_w}")
                break


def test_pce_thumbs_no_dir_variants(tmp_dir: Path) -> None:
    print("\n[Test] pce_thumbs.bin ignores non-CRC filenames")
    src = tmp_dir / "thumbs_nodir_src"
    src.mkdir()
    out = tmp_dir / "pce_thumbs_nodir.bin"
    crc = 0xCAFEBABE
    (src / f"{crc:08x}.bin").write_bytes(_make_fake_bin(crc, 10, 8))
    (src / "Bonk's Adventure.bin").write_bytes(_make_fake_bin(0, 10, 8))
    (src / "some_name.bin").write_bytes(_make_fake_bin(0, 10, 8))
    generate_pce_thumbs_bin(src, out)
    raw = out.read_bytes()
    img_count = struct.unpack_from("<I", raw, 8)[0]
    _check("Only 1 image included (CRC-named only)", img_count == 1, f"got {img_count}")


def test_pce_thumbs_bonk_on_sd(sd_thumbs_path: Path | None) -> None:
    print("\n[Test] SD card pce_thumbs.bin structure")
    if sd_thumbs_path is None or not sd_thumbs_path.exists():
        print("  [SKIP] pce_thumbs.bin not on SD card")
        return
    raw = sd_thumbs_path.read_bytes()
    _check("Magic == 02 46 54 41", raw[:4] == PCE_THUMBS_MAGIC, raw[:4].hex())
    data_size = struct.unpack_from("<I", raw, 4)[0]
    img_count = struct.unpack_from("<I", raw, 8)[0]
    _check("Image count > 0", img_count > 0, f"count={img_count}")
    _check("File size == header + data_size", len(raw) == PCE_THUMBS_HEADER_SIZE + data_size, f"file={len(raw)}, expected={PCE_THUMBS_HEADER_SIZE + data_size}")
    bonk_slot = _hash_slot(BONK_CRC)
    bonk_found = False
    for probe in range(PCE_THUMBS_HASH_SLOTS):
        s = (bonk_slot + probe) % PCE_THUMBS_HASH_SLOTS
        off = 12 + s * PCE_THUMBS_HASH_ENTRY_SIZE
        if struct.unpack_from("<I", raw, off)[0] == BONK_CRC:
            bonk_found = True
            data_off = struct.unpack_from("<I", raw, off + 4)[0]
            img_start = PCE_THUMBS_HEADER_SIZE + data_off
            img_magic = raw[img_start: img_start + 4]
            _check("Bonk image magic == ' IPA'", img_magic == POCKET_BIN_MAGIC, img_magic.hex())
            h = struct.unpack_from("<H", raw, img_start + 4)[0]
            w = struct.unpack_from("<H", raw, img_start + 6)[0]
            _check("Bonk image has valid dimensions", h > 0 and w > 0, f"h={h}, w={w}")
            _check(f"Bonk image height == {PCE_THUMBS_THUMB_HEIGHT}", h == PCE_THUMBS_THUMB_HEIGHT, f"h={h}")
            _check("Bonk image pixel data size == w*h*4", len(raw) >= img_start + 8 + w * h * 4, f"w={w}, h={h}")
            break
    _check("Bonk's Adventure (CRC 599ead9b) in hash table", bonk_found)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    print("=" * 60)
    print("Analogue Pocket .bin conversion tests")
    print("=" * 60)

    sd_pce_dir = Path(r"E:\System\Library\Images\pce")
    sd_bonks = sd_pce_dir / "599ead9b.bin"
    sd_bonks_name = sd_pce_dir / "Bonk's Adventure (USA).bin"
    sd_bonks_db_name = sd_pce_dir / "Bonk's Adventure.bin"
    sd_thumbs = sd_pce_dir / "pce_thumbs.bin"

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
            test_pce_thumbs_structure(tmp_dir)
            test_pce_thumbs_hash_table(tmp_dir)
            test_pce_thumbs_image_data(tmp_dir)
            test_pce_thumbs_no_dir_variants(tmp_dir)
            test_pce_thumbs_bonk_on_sd(sd_thumbs)
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
