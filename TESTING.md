# Running the Test Suite

## Quick Start

```bash
# 1. Install dependencies (first time only)
pip install -r requirements.txt

# 2. Run all tests
pytest tests/ -v

# 3. Check coverage
pytest tests/ --cov=analogue_image_gen --cov-report=term-missing
```

## Common Commands

| Command | Purpose |
|---------|---------|
| `pytest tests/` | Run all tests (quiet) |
| `pytest tests/ -v` | Run all tests (verbose) |
| `pytest tests/test_parsing.py -v` | Run only parsing tests |
| `pytest tests/test_image_conversion.py` | Run only image conversion tests |
| `pytest tests/test_utilities.py` | Run only utility tests |
| `pytest -k "match"` | Run tests matching keyword "match" |
| `pytest --tb=short` | Show short tracebacks on failure |
| `pytest --pdb` | Drop into debugger on first failure |
| `pytest --collect-only` | List all tests without running them |
| `pytest --cov=analogue_image_gen` | Generate coverage report |

## Expected Output

```
=============================== 76 passed in 0.46s ===============================
```

All tests should pass. If any fail, check:
1. Dependencies are installed: `pip install -r requirements.txt`
2. Python version is 3.9+: `python --version`
3. Current working directory is repo root: `cd analogue-images`

## Coverage Report

Coverage is 21% overall (by design - CLI/device I/O not unit-testable):

```
Name                    Stmts   Miss  Cover
analogue_image_gen.py    1133    891    21%
```

The tested functions have >85% coverage:
- Image conversion: ~40%
- Parsing: ~35%
- Utilities: ~30%

## GitHub Actions

Tests run automatically on:
- Pull requests to `main` or `develop`
- Pushes to `main` or `develop`

View results in **Actions** tab on GitHub.

## Debugging a Failing Test

```bash
# Run single test with full output
pytest tests/test_parsing.py::TestParseDatFile::test_parse_valid_dat_file -vv

# Drop into Python debugger on failure
pytest tests/ --pdb

# Show print statements
pytest tests/ -s

# Verbose with short tracebacks
pytest tests/ -v --tb=short
```

## Adding New Tests

1. Create a file `tests/test_*.py`
2. Use fixtures from `tests/conftest.py`
3. Write test functions starting with `test_`
4. Run: `pytest tests/test_yourfile.py -v`

Example:

```python
def test_something(tmp_dir):
    """Test description."""
    path = tmp_dir / "myfile.txt"
    path.write_text("content")
    
    assert path.read_text() == "content"
```

## CI/CD Integration

The workflow `.github/workflows/test.yml` tests against Python 3.9, 3.10, 3.11, 3.12.

To make tests required before merge:
1. Settings → Rules → Rulesets
2. Add required status check: `test (all)`
3. Save
