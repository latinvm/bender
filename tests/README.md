# Testing Guide

This directory contains the test suite for the Bender Trading Bot. The tests are written using pytest and cover all major components of the system.

## 📋 Test Structure

```
tests/
├── __init__.py
├── test_main.py       # Tests for core application functionality
├── test_strategies.py # Tests for trading strategies
├── test_market.py     # Tests for market operations
├── test_database.py   # Tests for database operations
└── test_config.py     # Tests for configuration management
```

## 🚀 Getting Started

### Prerequisites

Install the development dependencies:
```bash
pip install -r requirements-dev.txt
```

This will install:
- pytest (testing framework)
- pytest-cov (coverage reporting)
- black (code formatting)
- flake8 (linting)
- mypy (type checking)

### Running Tests

Basic test execution:
```bash
# Run all tests
pytest tests/

# Run tests with verbose output
pytest -v tests/

# Run a specific test file
pytest tests/test_strategies.py
```

### Coverage Reports

Generate test coverage reports:
```bash
# Generate coverage report in terminal
pytest --cov=src.trader tests/

# Generate detailed HTML coverage report
pytest --cov=src.trader --cov-report=html tests/
```

The HTML report will be available in the `htmlcov` directory.

## 🧪 Test Categories

### Core Application Tests (test_main.py)
- Application initialization
- Market selection logic
- Market information display
- Error handling

### Trading Strategy Tests (test_strategies.py)
- Moving average calculations
- Buy/sell signal generation
- Position management
- Trade execution logic
- Volume analysis

### Market Operations Tests (test_market.py)
- API interactions
- Order placement (market and limit orders)
- Market data retrieval
- Error handling
- Minimum order requirements

### Database Tests (test_database.py)
- Trade recording
- Position tracking
- Profit/Loss calculations
- Database schema validation
- Uses temporary test database

### Configuration Tests (test_config.py)
- Environment variable handling
- Path resolution
- Default values
- Data directory creation

## 🔧 Test Environment

The test suite is designed to run without requiring:
- Real API credentials
- Active internet connection
- Actual database setup

This is achieved through:
- Mock objects for API calls
- Temporary file handling for database tests
- Environment variable management

## 💡 Writing New Tests

When adding new tests:
1. Use appropriate fixtures from existing test files
2. Follow the existing pattern of arrange/act/assert
3. Include both success and error cases
4. Use meaningful test names that describe the scenario
5. Add proper docstrings to test functions

Example:
```python
def test_meaningful_name(required_fixture):
    """Test description explaining what is being tested and why"""
    # Arrange
    expected_result = ...
    
    # Act
    actual_result = function_under_test()
    
    # Assert
    assert actual_result == expected_result
```

## 🐛 Debugging Tests

For detailed test output:
```bash
# Show print statements and detailed errors
pytest -v --capture=no tests/

# Stop on first failure
pytest -x tests/

# Start debugger on failures
pytest --pdb tests/
```

## 📊 Test Quality Metrics

Maintain test quality by running:
```bash
# Check code formatting
black tests/

# Run linting
flake8 tests/

# Run type checking
mypy tests/
```

Remember to run the full test suite before submitting any changes to ensure all tests pass and no regressions are introduced.