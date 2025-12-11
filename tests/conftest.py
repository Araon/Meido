"""
Pytest configuration and shared fixtures
"""
import pytest
import sys
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch
import json
import tempfile
import os

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Mock pymongo before any imports that might use it
# This needs to happen before bot.database is imported
if 'pymongo' not in sys.modules:
    # Create a comprehensive mock pymongo module
    pymongo_mock = MagicMock()
    
    # Create mock client with admin.command
    mock_client_instance = MagicMock()
    mock_client_instance.admin = MagicMock()
    mock_client_instance.admin.command.return_value = {'ok': 1}
    
    # Create mock database and collection
    mock_db = MagicMock()
    mock_col = MagicMock()
    mock_client_instance.__getitem__ = lambda x, key: mock_db if key == "animeDatabase" else MagicMock()
    mock_db.__getitem__ = lambda x, key: mock_col if key == "animeDatabase" else MagicMock()
    
    # Setup MongoClient to return our mock
    def mock_mongo_client(*args, **kwargs):
        return mock_client_instance
    
    pymongo_mock.MongoClient = mock_mongo_client
    pymongo_mock.errors = MagicMock()
    pymongo_mock.errors.ConnectionFailure = type('ConnectionFailure', (Exception,), {})
    pymongo_mock.errors.ServerSelectionTimeoutError = type('ServerSelectionTimeoutError', (Exception,), {})
    
    sys.modules['pymongo'] = pymongo_mock
    sys.modules['pymongo.errors'] = pymongo_mock.errors

# Mock telegram module before any imports
if 'telegram' not in sys.modules:
    telegram_mock = MagicMock()
    telegram_mock.Update = MagicMock
    telegram_mock.ext = MagicMock()
    telegram_mock.ext.Application = MagicMock
    telegram_mock.ext.CommandHandler = MagicMock
    telegram_mock.ext.MessageHandler = MagicMock
    telegram_mock.ext.ContextTypes = MagicMock()
    telegram_mock.ext.filters = MagicMock()
    telegram_mock.ext.filters.TEXT = MagicMock()
    telegram_mock.ext.filters.COMMAND = MagicMock()
    telegram_mock.ext.filters.VIDEO = MagicMock()
    
    sys.modules['telegram'] = telegram_mock
    sys.modules['telegram.ext'] = telegram_mock.ext

# Create temporary config files for testing
@pytest.fixture(autouse=True)
def temp_config_dir(tmp_path, monkeypatch):
    """Create temporary config directory with test config files and patch PROJECT_ROOT"""
    # Create the full directory structure matching the project
    bot_config_dir = tmp_path / "bot" / "config"
    bot_config_dir.mkdir(parents=True)
    
    bot_config = {
        "bot_token": "test_bot_token_12345",
        "agent_user_id": 123456789
    }
    
    with open(bot_config_dir / "botConfig.json", "w") as f:
        json.dump(bot_config, f)
    
    # Patch PROJECT_ROOT at module level if bot.bot is already imported
    if 'bot.bot' in sys.modules:
        monkeypatch.setattr(sys.modules['bot.bot'], 'PROJECT_ROOT', tmp_path)
    else:
        # Store for later patching
        monkeypatch.setenv('TEST_PROJECT_ROOT', str(tmp_path))
    
    # Return the project root (tmp_path) so tests can use it
    return tmp_path

@pytest.fixture
def temp_agent_config_dir(tmp_path):
    """Create temporary agent config directory"""
    config_dir = tmp_path / "uploaderService" / "config"
    config_dir.mkdir(parents=True)
    
    agent_config = {
        "entity": "test_session",
        "api_id": "12345",
        "api_hash": "test_api_hash",
        "phone": "+1234567890",
        "bot_name": "@test_bot"
    }
    
    with open(config_dir / "agentConfig.json", "w") as f:
        json.dump(agent_config, f)
    
    return config_dir

@pytest.fixture
def mock_mongo_client():
    """Mock MongoDB client"""
    with patch('bot.database.MongoClient') as mock_client:
        mock_db = MagicMock()
        mock_col = MagicMock()
        mock_client.return_value = MagicMock()
        mock_client.return_value.__getitem__.return_value = mock_db
        mock_db.__getitem__.return_value = mock_col
        yield mock_col

@pytest.fixture
def mock_update():
    """Mock Telegram Update object"""
    update = MagicMock()
    update.message = MagicMock()
    update.message.from_user.id = 123456789
    update.message.text = "/getanime Death Note, 1, 3"
    update.effective_chat.id = 987654321
    update.message.reply_text = MagicMock()
    return update

@pytest.fixture
def mock_context():
    """Mock Telegram Context object"""
    context = MagicMock()
    context.bot = MagicMock()
    context.bot.send_video = MagicMock()
    context.bot.send_message = MagicMock()
    return context

@pytest.fixture
def sample_anime_data():
    """Sample anime data for testing"""
    return {
        "series_key": "death_note",
        "series_name": "Death Note",
        "season_id": 1,
        "episode_id": 3,
        "file_id": "BAACAgIAAxkBAAIB",
        "times_queried": 5,
        "date_added": "2024-01-01T00:00:00"
    }
