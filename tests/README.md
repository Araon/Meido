# Test Suite for Meido Bot

This directory contains comprehensive tests for the Meido Telegram bot.

## Test Structure

- `test_botUtils.py` - Tests for utility functions (parsing, file operations)
- `test_database.py` - Tests for MongoDB operations
- `test_bot_commands.py` - Tests for bot commands (/start, /help, /getanime)
- `test_integration.py` - Integration tests for complete workflows
- `conftest.py` - Shared fixtures and test configuration

## Running Tests

### Run all tests:

```bash
pytest tests/ -v
```

### Run specific test file:

```bash
pytest tests/test_botUtils.py -v
pytest tests/test_database.py -v
```

### Run specific test:

```bash
pytest tests/test_botUtils.py::TestParseSearchQuery::test_parse_full_query -v
```

### Run with coverage:

```bash
pytest tests/ --cov=bot --cov=downloaderService --cov=uploaderService --cov-report=html
```

## Test Coverage

The test suite covers:

1. **Utility Functions** (test_botUtils.py)

   - Help text generation
   - Query parsing with various formats
   - File discovery operations

2. **Database Operations** (test_database.py)

   - Data insertion (postData)
   - Data retrieval (getData)
   - Data updates (updateData)
   - Error handling

3. **Bot Commands** (test_bot_commands.py)

   - /start command
   - /help command
   - /getanime command (cached and uncached scenarios)
   - Video upload handling

4. **Integration Tests** (test_integration.py)
   - Complete download workflow
   - Upload workflow
   - Cached content delivery
   - Error handling scenarios

## Notes

- Tests use mocks for external dependencies (Telegram API, MongoDB, animdl)
- Config files are created automatically in temporary directories
- All async functions are tested using pytest-asyncio
