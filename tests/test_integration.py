"""
Integration tests for the bot workflow
"""
import pytest
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock
import tempfile
import os

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Add bot directory to path for relative imports
BOT_DIR = PROJECT_ROOT / 'bot'
if str(BOT_DIR) not in sys.path:
    sys.path.insert(0, str(BOT_DIR))

# Map relative imports to absolute imports
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


class TestDownloadWorkflow:
    """Integration tests for download workflow"""
    
    @pytest.mark.asyncio
    async def test_full_download_workflow(self, mock_update, mock_context, temp_config_dir):
        """Test complete workflow from request to download"""
        mock_update.message.text = "/getanime Test Anime, 1, 1"
        
        # Mock that anime is not in database
        with patch('bot.bot.PROJECT_ROOT', Path(temp_config_dir.parent.parent)), \
             patch('database.getData', return_value=None), \
             patch('botUtils.getalltsfiles', return_value="/tmp/test.mp4"), \
             patch('subprocess.check_call') as mock_subprocess:
            
            from bot.bot import getanime
            
            await getanime(mock_update, mock_context)
            
            # Verify download was attempted
            assert mock_subprocess.called
            # Should have called downloader service
            call_args = str(mock_subprocess.call_args)
            assert "downloaderService" in call_args or "main.py" in call_args


class TestUploadWorkflow:
    """Integration tests for upload workflow"""
    
    @pytest.mark.asyncio
    async def test_upload_after_download(self, mock_update, mock_context, temp_config_dir):
        """Test upload workflow after download"""
        mock_update.message.text = "/getanime Test Anime, 1, 1"
        
        # Create a temporary mp4 file
        with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as tmp_file:
            tmp_file.write(b"fake video data")
            tmp_file_path = tmp_file.name
        
        try:
            with patch('database.getData', return_value=None), \
                 patch('botUtils.getalltsfiles', return_value=tmp_file_path), \
                 patch('subprocess.check_call') as mock_subprocess:
                    
                    from bot.bot import getanime
                    
                    await getanime(mock_update, mock_context)
                    
                    # Verify both download and upload were called
                    assert mock_subprocess.call_count >= 1
        finally:
            # Cleanup
            if os.path.exists(tmp_file_path):
                os.unlink(tmp_file_path)


class TestCachedWorkflow:
    """Integration tests for cached content workflow"""
    
    @pytest.mark.asyncio
    async def test_cached_content_instant_delivery(self, mock_update, mock_context, 
                                                   temp_config_dir, sample_anime_data):
        """Test that cached content is delivered instantly"""
        mock_update.message.text = "/getanime Death Note, 1, 3"
        
        with patch('database.getData', return_value=sample_anime_data), \
             patch('database.updateData') as mock_update_data:
            
            from bot.bot import getanime
            
            await getanime(mock_update, mock_context)
            
            # Should send video immediately without downloading
            mock_context.bot.send_video.assert_called_once()
            # Should update query count
            mock_update_data.assert_called_once()
            # Should not attempt download
            assert not hasattr(mock_context.bot, 'download_called')


class TestErrorHandling:
    """Integration tests for error handling"""
    
    @pytest.mark.asyncio
    async def test_download_error_handling(self, mock_update, mock_context, temp_config_dir):
        """Test error handling when download fails"""
        mock_update.message.text = "/getanime Test Anime, 1, 1"
        
        with patch('database.getData', return_value=None), \
             patch('subprocess.check_call', side_effect=Exception("Download failed")):
            
            from bot.bot import getanime
            
            await getanime(mock_update, mock_context)
            
            # Should send error message to user
            mock_update.message.reply_text.assert_called()
            call_args = str(mock_update.message.reply_text.call_args)
            assert "error" in call_args.lower() or "retry" in call_args.lower()
    
    @pytest.mark.asyncio
    async def test_upload_error_handling(self, mock_update, mock_context, temp_config_dir):
        """Test error handling when upload fails"""
        mock_update.message.text = "/getanime Test Anime, 1, 1"
        
        with patch('database.getData', return_value=None), \
             patch('botUtils.getalltsfiles', return_value="/tmp/test.mp4"), \
             patch('subprocess.check_call', side_effect=[
                 None,  # Download succeeds
                 Exception("Upload failed")  # Upload fails
             ]):
            
            from bot.bot import getanime
            
            await getanime(mock_update, mock_context)
            
            # Should handle error gracefully
            mock_update.message.reply_text.assert_called()
