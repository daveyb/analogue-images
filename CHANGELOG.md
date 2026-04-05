# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/daveyb/analogue-images/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/daveyb/analogue-images/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/daveyb/analogue-images/releases/tag/v0.2.0
```

Now let me bump the version in the script and commit everything: