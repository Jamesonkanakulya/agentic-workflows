# Tool Tests

This directory contains test files for all workflow tools.

## Setup

Install test dependencies:

```bash
pip install pytest python-dotenv
```

Ensure your `.env` file is configured with necessary API keys.

## Running Tests

Run all tests:

```bash
pytest tools/tests/ -v
```

Run specific test file:

```bash
pytest tools/tests/test_research_trends.py -v
```

Run tests with coverage:

```bash
pytest tools/tests/ --cov=tools --cov-report=html
```

## Test Structure

- `conftest.py` - Shared fixtures and configuration
- `test_*.py` - Individual test files for each tool
- Tests are skipped if required API keys are not configured

## Writing New Tests

When adding a new tool, create a corresponding test file:

1. Create `test_<tool_name>.py`
2. Import the tool functions
3. Write test cases for core functionality
4. Use fixtures from `conftest.py` for sample data
5. Skip tests when API keys are not available

Example:

```python
import pytest
import os

def test_my_tool():
    if not os.getenv('MY_API_KEY'):
        pytest.skip("MY_API_KEY not configured")

    # Your test code here
    pass
```

## Test Coverage Goals

- All core functions should have tests
- API error handling should be tested
- File I/O operations should be tested
- Invalid input should be handled gracefully
