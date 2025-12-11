"""
Tests for bot commands
"""
import pytest
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock, mock_open
import json

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Add bot directory to path for relative imports
BOT_DIR = PROJECT_ROOT / 'bot'
if str(BOT_DIR) not in sys.path:
    sys.path.insert(0, str(BOT_DIR))

# Map relative imports to absolute imports
# Don't import bot.bot here - it will be imported in tests after config is set up
import bot.botUtils as botUtils_module
import bot.database as database_module
sys.modules['botUtils'] = botUtils_module
sys.modules['database'] = database_module

# Mock telegram imports before importing bot
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


class TestStartCommand:
    """Tests for /start command"""
    
    @pytest.mark.asyncio
    async def test_start_command(self, mock_update, mock_context, temp_config_dir, monkeypatch):
        """Test /start command response"""
        # Mock config file before importing bot
        config_path = temp_config_dir / 'bot' / 'config' / 'botConfig.json'
        with patch('builtins.open', mock_open(read_data=json.dumps({
            "bot_token": "test_token",
            "agent_user_id": 123456789
        }))), \
        patch('bot.bot.config_path', config_path), \
        patch('bot.bot.PROJECT_ROOT', temp_config_dir):
            # Import after patching
            import importlib
            if 'bot.bot' in sys.modules:
                importlib.reload(sys.modules['bot.bot'])
            from bot.bot import start
            
            await start(mock_update, mock_context)
            
            mock_update.message.reply_text.assert_called_once()
            call_args = mock_update.message.reply_text.call_args[0][0]
            assert "Araon Bot" in call_args or "Thanks for using" in call_args


class TestHelpCommand:
    """Tests for /help command"""
    
    @pytest.mark.asyncio
    async def test_help_command(self, mock_update, mock_context, temp_config_dir):
        """Test /help command response"""
        from bot.bot import help_command
        
        await help_command(mock_update, mock_context)
        
        mock_update.message.reply_text.assert_called_once()
        call_args = mock_update.message.reply_text.call_args[0][0]
        assert "/getanime" in call_args.lower() or "getanime" in call_args.lower()


class TestGetAnimeCommand:
    """Tests for /getanime command"""
    
    @pytest.mark.asyncio
    async def test_getanime_with_valid_query(self, mock_update, mock_context, temp_config_dir, 
                                            sample_anime_data):
        """Test /getanime with valid query and cached data"""
        mock_update.message.text = "/getanime Death Note, 1, 3"
        
        with patch('bot.bot.PROJECT_ROOT', Path(temp_config_dir.parent.parent)), \
             patch('database.getData', return_value=sample_anime_data), \
             patch('database.updateData') as mock_update_data, \
             patch('bot.botUtils.normalize_series_name', return_value="death_note"):
            
            from bot.bot import getanime
            
            await getanime(mock_update, mock_context)
            
            # Should send video from cache
            mock_context.bot.send_video.assert_called_once()
            mock_update_data.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_getanime_not_in_cache(self, mock_update, mock_context, temp_config_dir):
        """Test /getanime when anime is not in cache"""
        mock_update.message.text = "/getanime New Anime, 1, 1"
        
        with patch('bot.bot.PROJECT_ROOT', Path(temp_config_dir.parent.parent)), \
             patch('database.getData', return_value=None), \
             patch('botUtils.getalltsfiles', return_value=None), \
             patch('subprocess.check_call') as mock_subprocess:
            
            from bot.bot import getanime
            
            await getanime(mock_update, mock_context)
            
            # Should attempt to download
            assert mock_subprocess.called
    
    @pytest.mark.asyncio
    async def test_getanime_empty_query(self, mock_update, mock_context, temp_config_dir):
        """Test /getanime with empty query"""
        mock_update.message.text = "/getanime"
        
        from bot.bot import getanime
        
        await getanime(mock_update, mock_context)
        
        # Should show help message
        mock_update.message.reply_text.assert_called()
        call_args = mock_update.message.reply_text.call_args[0][0]
        assert "help" in call_args.lower() or "/help" in call_args.lower()
    
    @pytest.mark.asyncio
    async def test_getanime_missing_file_id(self, mock_update, mock_context, temp_config_dir):
        """Test /getanime when data exists but file_id is missing"""
        mock_update.message.text = "/getanime Death Note, 1, 3"
        data_without_file_id = {
            "series_key": "death_note",
            "series_name": "Death Note",
            "season_id": 1,
            "episode_id": 3,
            "file_id": None
        }
        
        with patch('bot.bot.PROJECT_ROOT', Path(temp_config_dir.parent.parent)), \
             patch('database.getData', return_value=data_without_file_id), \
             patch('bot.botUtils.normalize_series_name', return_value="death_note"):
            
            from bot.bot import getanime
            
            await getanime(mock_update, mock_context)
            
            # Should send error message
            mock_update.message.reply_text.assert_called()
            call_args = str(mock_update.message.reply_text.call_args)
            assert "file_id" in call_args.lower() or "missing" in call_args.lower()


class TestCheckDocument:
    """Tests for check_document function (handles video uploads)"""
    
    @pytest.mark.asyncio
    async def test_check_document_valid_video(self, mock_update, mock_context, temp_config_dir):
        """Test check_document with valid video from agent"""
        # Set up mock video message with new object_id format
        mock_video = MagicMock()
        mock_video.file_id = "BAACAgIAAxkBAAIB"
        mock_update.message.video = mock_video
        mock_update.message.caption = "987654321:death_note-s1-e3"
        mock_update.message.from_user.id = 123456789  # agent_user_id
        
        with patch('database.postData') as mock_post, \
             patch('database.getData', return_value=None):
            
            from bot.bot import check_document
            
            await check_document(mock_update, mock_context)
            
            # Should post to database and send video
            mock_post.assert_called_once()
            mock_context.bot.send_video.assert_called_once()
            
            # Verify the data posted includes series_key, season_id, episode_id
            posted_data = mock_post.call_args[0][0]
            assert posted_data.get("series_key") == "death_note"
            assert posted_data.get("season_id") == 1
            assert posted_data.get("episode_id") == 3
    
    @pytest.mark.asyncio
    async def test_check_document_wrong_user(self, mock_update, mock_context, temp_config_dir):
        """Test check_document with video from non-agent user"""
        mock_update.message.from_user.id = 999999999  # Not agent
        
        with patch('bot.bot.PROJECT_ROOT', temp_config_dir):
            from bot.bot import check_document
            
            await check_document(mock_update, mock_context)
            
            # Should not process
            mock_context.bot.send_video.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_check_document_invalid_caption(self, mock_update, mock_context, temp_config_dir):
        """Test check_document with invalid caption format"""
        mock_video = MagicMock()
        mock_video.file_id = "BAACAgIAAxkBAAIB"
        mock_update.message.video = mock_video
        mock_update.message.caption = "invalid_format"
        mock_update.message.from_user.id = 123456789
        
        with patch('bot.bot.PROJECT_ROOT', temp_config_dir):
            from bot.bot import check_document
            
            await check_document(mock_update, mock_context)
            
            # Should not process
            mock_context.bot.send_video.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_check_document_object_id_with_season(self, mock_update, mock_context, temp_config_dir):
        """Test check_document parses new object_id format with season correctly"""
        mock_video = MagicMock()
        mock_video.file_id = "BAACAgIAAxkBAAIB"
        mock_update.message.video = mock_video
        mock_update.message.caption = "987654321:test_anime-s2-e5"
        mock_update.message.from_user.id = 123456789
        
        with patch('database.postData') as mock_post, \
             patch('database.getData', return_value=None):
            
            from bot.bot import check_document
            
            await check_document(mock_update, mock_context)
            
            # Verify correct parsing
            posted_data = mock_post.call_args[0][0]
            assert posted_data.get("series_key") == "test_anime"
            assert posted_data.get("season_id") == 2
            assert posted_data.get("episode_id") == 5
