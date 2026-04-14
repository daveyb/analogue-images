# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Game Gear (`gg`) support on Analogue Pocket: downloads box art from the
  `Sega_-_Game_Gear` libretro-thumbnails repository and writes per-game `.bin`
  images to `System/Library/Images/gg/`. Validated on hardware with physical
  cartridges (Ax Battler, Shining Force II). Pocket system ID `0x03` confirmed
  as Game Gear (previously labelled as an unverified GBC placeholder).

## [0.4.3] - 2026-04-07

### Added

- Comprehensive pytest-based unit test suite with 76 tests covering:
  - DAT file parsing and game matching logic
  - Image format detection and Pocket `.bin` conversion
  - Utility functions for filename sanitization and device detection
  - Configuration loading from `special_cases.json`
- GitHub Actions workflow (`.github/workflows/test.yml`) that:
  - Runs tests on all pull requests and pushes to `main`/`develop`
  - Tests against Python 3.9, 3.10, 3.11, and 3.12
  - Generates and uploads coverage reports to Codecov
  - Can be required before merge via branch protection rules
- `pytest.ini` configuration for test discovery and reporting
- `TESTING.md` quick reference guide for running and maintaining tests
- `TEST_SUITE.md` comprehensive documentation of test coverage and architecture

## [0.4.2] - 2026-04-07

### Added

- `clear-images` mode: removes all converted `.bin` image files from the SD
  card without modifying the played-games database (`list.bin`). Respects
  `--console` to target a single console and `--dry-run` to preview deletions.
  Also removes matching `*_thumbs.bin` bundle files when present.

## [0.4.1] - 2026-04-05

### Fixed

- README examples incorrectly included `auto` as a positional argument;
  `auto` is the default mode and should not be passed explicitly.
- README supported-devices table incorrectly listed PC Engine CD (`pcecd`)
  as confirmed on the Analogue Pocket; PCECD is Duo-only.

## [0.4.0] - 2026-04-05

### Added

- GitHub Actions release workflow (`.github/workflows/release.yml`) that
  triggers on merge to `main`, parses `CHANGELOG.md`, and automatically
  manages GitHub releases:
  - Creates a **draft release** (tagged `v<version>-draft-<YYYYMMDD-HHmm>`)
    when the `[Unreleased]` section has content, inferring the next SemVer
    from change-type headings (`Removed` → major, `Added`/`Deprecated` →
    minor, all others → patch). Each new merge replaces the previous draft.
  - Creates a **published release** (tagged `v<version>`) when a new dated
    version heading is found in `CHANGELOG.md` with no corresponding GitHub
    release yet; cleans up any draft releases for that version.
- Release helper script (`.github/scripts/create_release.py`) containing all
  CHANGELOG parsing and `gh` CLI release management logic.

## [0.3.0] - 2026-04-05

### Changed

- Renamed `POCKET_IMAGE_DIRS` to `CONSOLE_IMAGE_DIRS` to reflect that the
  mapping covers both Pocket and Duo output directories.

### Removed

- PC Engine CD (`pcecd`) support on the Pocket. The Pocket has no CD unit, so
  `pcecd` images are Duo-only. Processing is now skipped with an explicit
  message when `--console pcecd` (or `--console all`) is used with a Pocket SD
  card.
- `0x08 (pcecd)` entry from `POCKET_SYSTEM_IDS`; the Pocket firmware does not
  expose a PC Engine CD system ID.

## [0.2.0] - 2026-04-03

### Added

- Initial public release with support for GBA, NGP, PCE, and PCECD image
  generation for the Analogue Pocket and Duo.

[Unreleased]: https://github.com/daveyb/analogue-images/compare/v0.4.3...HEAD
[0.4.3]: https://github.com/daveyb/analogue-images/compare/v0.4.2...v0.4.3
[0.4.2]: https://github.com/daveyb/analogue-images/compare/v0.4.1...v0.4.2
[0.4.1]: https://github.com/daveyb/analogue-images/compare/v0.4.0...v0.4.1
[0.4.0]: https://github.com/daveyb/analogue-images/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/daveyb/analogue-images/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/daveyb/analogue-images/releases/tag/v0.2.0
