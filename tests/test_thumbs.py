"""Library grid bundles written the way the Pocket firmware reads them."""

import struct
import subprocess
import sys
from pathlib import Path

from PIL import Image

from analogue_image_gen import (
    POCKET_BIN_MAGIC,
    POCKET_THUMB_BYTES,
    POCKET_THUMB_STORED_HEIGHT,
    POCKET_THUMB_STORED_WIDTH,
    POCKET_THUMBS_IMAGE_OFFSET,
    POCKET_THUMBS_MAGIC,
    library_bin_to_thumb,
    sync_pocket_thumbs,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


def _library_bin(width: int, height: int, pixel: bytes) -> bytes:
    return POCKET_BIN_MAGIC + struct.pack("<HH", height, width) + pixel * (width * height)


def test_thumb_of_grid_sized_image_keeps_pixels():
    pixel = bytes([1, 2, 3, 255])
    source = _library_bin(POCKET_THUMB_STORED_WIDTH, POCKET_THUMB_STORED_HEIGHT, pixel)
    thumb = library_bin_to_thumb(source)
    assert thumb is not None
    assert thumb[:4] == POCKET_BIN_MAGIC
    assert struct.unpack_from("<HH", thumb, 4) == (
        POCKET_THUMB_STORED_HEIGHT,
        POCKET_THUMB_STORED_WIDTH,
    )
    assert thumb[8:] == pixel * (
        POCKET_THUMB_STORED_WIDTH * POCKET_THUMB_STORED_HEIGHT
    )
    assert len(thumb) == 52764


def test_sync_writes_sequential_absolute_slots(tmp_path):
    image_dir = tmp_path / "pce"
    image_dir.mkdir()
    pixel = bytes([4, 5, 6, 255])
    (image_dir / "11223344.bin").write_bytes(
        _library_bin(POCKET_THUMB_STORED_WIDTH, POCKET_THUMB_STORED_HEIGHT, pixel)
    )
    (image_dir / "aabbccdd.bin").write_bytes(_library_bin(220, 100, bytes([7, 8, 9, 255])))
    (image_dir / "Bonk's Adventure.bin").write_bytes(_library_bin(20, 20, pixel))
    bundle = tmp_path / "pce_thumbs.bin"

    sync_pocket_thumbs(image_dir, bundle)
    raw = bundle.read_bytes()

    assert raw[:4] == POCKET_THUMBS_MAGIC
    per_image, count = struct.unpack_from("<II", raw, 4)
    assert per_image == POCKET_THUMB_BYTES
    assert count == 2
    first_crc, first_off = struct.unpack_from("<II", raw, 12)
    second_crc, second_off = struct.unpack_from("<II", raw, 20)
    assert first_off == POCKET_THUMBS_IMAGE_OFFSET == 65548
    assert second_off == 65548 + 52764
    assert {first_crc, second_crc} == {0x11223344, 0xAABBCCDD}
    assert raw[first_off : first_off + 4] == POCKET_BIN_MAGIC
    height, width = struct.unpack_from("<HH", raw, first_off + 4)
    assert (height, width) == (121, 109)

    before = bundle.read_bytes()
    sync_pocket_thumbs(image_dir, bundle)
    assert bundle.read_bytes() == before


def test_sync_keeps_pixels_already_in_the_bundle(tmp_path):
    image_dir = tmp_path / "gg"
    image_dir.mkdir()
    (image_dir / "0000000a.bin").write_bytes(_library_bin(40, 50, bytes([1, 0, 0, 255])))
    bundle = tmp_path / "gg_thumbs.bin"
    sync_pocket_thumbs(image_dir, bundle)
    first = bundle.read_bytes()
    offset = struct.unpack_from("<I", first, 16)[0]
    kept = first[offset : offset + POCKET_THUMB_BYTES]

    (image_dir / "0000000b.bin").write_bytes(_library_bin(40, 50, bytes([0, 1, 0, 255])))
    sync_pocket_thumbs(image_dir, bundle)
    second = bundle.read_bytes()
    count = struct.unpack_from("<I", second, 8)[0]
    offset = struct.unpack_from("<I", second, 16)[0]
    assert count == 2
    assert second[offset : offset + POCKET_THUMB_BYTES] == kept


def test_convert_only_writes_the_grid_bundle(tmp_path):
    sd_root = tmp_path / "sd"
    image_dir = sd_root / "System" / "Library" / "Images" / "gba"
    image_dir.mkdir(parents=True)
    (sd_root / "Analogue_Pocket.json").write_text("{}\n", encoding="utf-8")
    (image_dir / "599ead9b.bin").write_bytes(
        _library_bin(80, 90, bytes([2, 3, 4, 255]))
    )
    cache = tmp_path / "cache"
    cache.mkdir()

    dry = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "analogue_image_gen.py"),
            str(sd_root),
            "convert-only",
            "--console",
            "gba",
            "--cache-dir",
            str(cache),
            "--dry-run",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert dry.returncode == 0, dry.stderr
    bundle = sd_root / "System" / "Library" / "Images" / "gba_thumbs.bin"
    assert not bundle.exists()
    assert "would write 1 image" in dry.stdout

    real = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "analogue_image_gen.py"),
            str(sd_root),
            "convert-only",
            "--console",
            "gba",
            "--cache-dir",
            str(cache),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert real.returncode == 0, real.stderr
    raw = bundle.read_bytes()
    assert raw[:4] == bytes([0x02, 0x46, 0x54, 0x41])
    per_image, count = struct.unpack_from("<II", raw, 4)
    assert per_image == 52764
    assert count == 1
    crc, offset = struct.unpack_from("<II", raw, 12)
    assert crc == 0x599EAD9B
    assert offset == 65548

    cleared = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "analogue_image_gen.py"),
            str(sd_root),
            "clear-images",
            "--console",
            "gba",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert cleared.returncode == 0, cleared.stderr
    assert not bundle.exists()
    assert not (image_dir / "599ead9b.bin").exists()


def test_wide_cover_uses_the_center_of_the_library_image():
    width, height = 200, 100
    image = Image.new("RGBA", (width, height), (0, 255, 0, 255))
    for x in range(90, 110):
        for y in range(height):
            image.putpixel((x, y), (255, 0, 0, 255))
    blob = POCKET_BIN_MAGIC + struct.pack("<HH", height, width) + image.tobytes("raw", "BGRA")
    thumb = library_bin_to_thumb(blob)
    assert thumb is not None
    stored = Image.frombytes(
        "RGBA",
        (POCKET_THUMB_STORED_WIDTH, POCKET_THUMB_STORED_HEIGHT),
        thumb[8:],
        "raw",
        "BGRA",
    )
    center = stored.getpixel((POCKET_THUMB_STORED_WIDTH // 2, POCKET_THUMB_STORED_HEIGHT // 2))
    assert center == (255, 0, 0, 255)
