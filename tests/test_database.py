"""
Tests for database module
"""
import pytest
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, Mock
from datetime import datetime

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Import after pymongo is mocked in conftest
# The conftest.py should have mocked pymongo before this import
from bot.database import postData, getData, updateData, col


class TestPostData:
    """Tests for postData function"""
    
    def test_post_data_success(self):
        """Test successful data insertion"""
        # Mock the collection's insert_one method
        with patch.object(col, 'insert_one') as mock_insert:
            mock_insert.return_value.inserted_id = "test_id_123"
            
            test_data = {
                "series_key": "death_note",
                "series_name": "Death Note",
                "season_id": 1,
                "episode_id": 3,
                "file_id": "BAACAgIAAxkBAAIB"
            }
            
            result = postData(test_data)
            
            assert result == "test_id_123"
            mock_insert.assert_called_once_with(test_data)
    
    def test_post_data_error_handling(self):
        """Test error handling in postData"""
        with patch.object(col, 'insert_one', side_effect=Exception("Database error")):
            test_data = {"series_name": "Test"}
            result = postData(test_data)
            
            assert result is None


class TestGetData:
    """Tests for getData function"""
    
    def test_get_data_found(self, sample_anime_data):
        """Test retrieving existing data"""
        with patch.object(col, 'find_one', return_value=sample_anime_data) as mock_find:
            query = {
                "series_key": "death_note",
                "season_id": 1,
                "episode_id": 3
            }
            
            result = getData(query)
            
            assert result == sample_anime_data
            mock_find.assert_called_once_with(filter=query)
    
    def test_get_data_not_found(self):
        """Test retrieving non-existent data"""
        with patch.object(col, 'find_one', return_value=None):
            query = {"series_name": "Non-existent"}
            result = getData(query)
            
            assert result is None
    
    def test_get_data_error_handling(self):
        """Test error handling in getData"""
        with patch.object(col, 'find_one', side_effect=Exception("Database error")):
            query = {"series_name": "Test"}
            result = getData(query)
            
            assert result is None


class TestUpdateData:
    """Tests for updateData function"""
    
    def test_update_data_success(self):
        """Test successful data update"""
        mock_result = MagicMock()
        mock_result.matched_count = 1
        mock_result.modified_count = 1
        
        with patch.object(col, 'update_one', return_value=mock_result) as mock_update:
            test_data = {
                "series_key": "death_note",
                "series_name": "Death Note",
                "season_id": 1,
                "episode_id": 3,
                "times_queried": 5
            }
            
            result = updateData(test_data)
            
            assert result is not None
            assert result.matched_count == 1
            mock_update.assert_called_once()
            
            # Check that the update uses $inc operator
            call_args = mock_update.call_args
            # call_args[0] is positional args tuple, call_args[1] is kwargs dict
            update_dict = call_args[1] if len(call_args) > 1 and call_args[1] else call_args[0][1] if len(call_args[0]) > 1 else {}
            assert "$inc" in str(update_dict) or "$inc" in update_dict
            if "$inc" in update_dict:
                assert update_dict["$inc"]["times_queried"] == 1
    
    def test_update_data_not_found(self):
        """Test updating non-existent data"""
        mock_result = MagicMock()
        mock_result.matched_count = 0
        
        with patch.object(col, 'update_one', return_value=mock_result):
            test_data = {
                "series_key": "non_existent",
                "series_name": "Non-existent",
                "season_id": 1,
                "episode_id": 999
            }
            
            result = updateData(test_data)
            
            assert result is not None
            assert result.matched_count == 0
    
    def test_update_data_error_handling(self):
        """Test error handling in updateData"""
        with patch.object(col, 'update_one', side_effect=Exception("Database error")):
            test_data = {"series_name": "Test"}
            result = updateData(test_data)
            
            assert result is None
