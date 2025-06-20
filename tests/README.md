# Testing with pytest

This project uses pytest for testing. Here's how to run the tests:

## Running Tests

### Basic Commands

```bash
# Run all tests
uv run pytest

# Run tests with verbose output
uv run pytest -v

# Run tests in a specific file
uv run pytest tests/test_throttling.py

# Run tests matching a pattern
uv run pytest -k "test_throttling"
```

### Advanced Options

```bash
# Show test durations
uv run pytest --durations=10

# Run only integration tests
uv run pytest -m integration

# Run tests with short traceback format
uv run pytest --tb=short

# Collect tests without running them
uv run pytest --collect-only
```

## Test Structure

- [`tests/conftest.py`](conftest.py) - Shared fixtures and configuration
- [`tests/test_throttling.py`](test_throttling.py) - Tests for throttling mechanism
- [`tests/test_spotify_client.py`](test_spotify_client.py) - Tests for Spotify client

## Key Features Used

### Pytest Features

- **Fixtures**: Reusable test setup code
- **Parametrization**: Running tests with different inputs
- **Markers**: Categorizing tests (e.g., `@pytest.mark.integration`)
- **Mocking**: Using `unittest.mock` for isolating tests
- **Assert statements**: Simple, readable assertions

### Test Organization

- **Classes**: Grouping related tests
- **Descriptive names**: Clear test and function names
- **Docstrings**: Explaining what each test does

### Configuration

- **pyproject.toml**: Test configuration in [`pyproject.toml`](../pyproject.toml)
- **Markers**: Custom test markers for integration vs unit tests
- **Test paths**: Automatic test discovery in `tests/` directory

## Migrated from unittest

This project was migrated from unittest to pytest, providing:

- Simpler assertions (no `self.assertEqual`)
- Better fixture management
- More readable test output
- Powerful command-line options
- Better plugin ecosystem
