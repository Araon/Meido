"""
Tests for botUtils module
"""
import pytest
import sys
from pathlib import Path
from unittest.mock import patch, mock_open
import os

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from bot.botUtils import showhelp, parse_search_query, getalltsfiles, normalize_series_name, get_download_path


class TestShowHelp:
    """Tests for showhelp function"""
    
    def test_showhelp_returns_string(self):
        """Test that showhelp returns a string"""
        result = showhelp()
        assert isinstance(result, str)
        assert len(result) > 0
    
    def test_showhelp_contains_commands(self):
        """Test that help text contains expected commands"""
        result = showhelp()
        assert "/getanime" in result.lower()
        assert "/search" in result.lower() or "search" in result.lower()


class TestParseSearchQuery:
    """Tests for parse_search_query function"""
    
    def test_parse_full_query(self):
        """Test parsing a complete query with all fields"""
        query = "Death Note, 1, 3"
        result = parse_search_query(query)
        
        assert result["series_name"] == "Death Note"
        assert result["season_id"] == 1
        assert result["episode_id"] == 3
    
    def test_parse_query_with_extra_spaces(self):
        """Test parsing query with extra whitespace"""
        query = "  Death Note  ,  1  ,  3  "
        result = parse_search_query(query)
        
        assert result["series_name"] == "Death Note"
        assert result["season_id"] == 1
        assert result["episode_id"] == 3
    
    def test_parse_query_missing_episode(self):
        """Test parsing query with missing episode"""
        query = "Death Note, 1"
        result = parse_search_query(query)
        
        assert result["series_name"] == "Death Note"
        assert result["season_id"] == 1
        assert result["episode_id"] == -1
    
    def test_parse_query_only_name(self):
        """Test parsing query with only anime name"""
        query = "Death Note"
        result = parse_search_query(query)
        
        assert result["series_name"] == "Death Note"
        assert result["season_id"] == -1
        assert result["episode_id"] == -1
    
    def test_parse_query_with_text_in_numbers(self):
        """Test parsing query with text mixed in season/episode"""
        query = "Death Note, season 1, episode 3"
        result = parse_search_query(query)
        
        assert result["series_name"] == "Death Note"
        assert result["season_id"] == 1
        assert result["episode_id"] == 3
    
    def test_parse_empty_query(self):
        """Test parsing empty query"""
        query = ""
        result = parse_search_query(query)
        
        assert result["series_name"] == ""
        assert result["season_id"] == -1
        assert result["episode_id"] == -1


class TestGetAllTsFiles:
    """Tests for getalltsfiles function"""
    
    def test_getalltsfiles_no_files(self, tmp_path):
        """Test when no mp4 files exist"""
        with patch('bot.botUtils.PROJECT_ROOT', tmp_path):
            result = getalltsfiles()
            assert result is None
    
    def test_getalltsfiles_finds_mp4(self, tmp_path):
        """Test finding an mp4 file"""
        # Create a test mp4 file
        test_file = tmp_path / "test_video.mp4"
        test_file.write_bytes(b"fake video data")
        
        with patch('bot.botUtils.PROJECT_ROOT', tmp_path):
            result = getalltsfiles()
            assert result is not None
            assert "test_video.mp4" in result
    
    def test_getalltsfiles_finds_nested_mp4(self, tmp_path):
        """Test finding mp4 file in subdirectory"""
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        test_file = subdir / "nested_video.mp4"
        test_file.write_bytes(b"fake video data")
        
        with patch('bot.botUtils.PROJECT_ROOT', tmp_path):
            result = getalltsfiles()
            assert result is not None
            assert "nested_video.mp4" in result
    
    def test_getalltsfiles_ignores_other_extensions(self, tmp_path):
        """Test that other file extensions are ignored"""
        # Create files with different extensions
        (tmp_path / "test.ts").write_bytes(b"data")
        (tmp_path / "test.avi").write_bytes(b"data")
        (tmp_path / "test.mp4").write_bytes(b"data")
        
        with patch('bot.botUtils.PROJECT_ROOT', tmp_path):
            result = getalltsfiles()
            assert result is not None
            assert result.endswith(".mp4")
            assert "test.ts" not in result
            assert "test.avi" not in result
    
    def test_getalltsfiles_case_insensitive(self, tmp_path):
        """Test that file extension matching is case insensitive"""
        test_file = tmp_path / "test.MP4"
        test_file.write_bytes(b"fake video data")
        
        with patch('bot.botUtils.PROJECT_ROOT', tmp_path):
            result = getalltsfiles()
            assert result is not None
            assert "test.MP4" in result or "test.mp4" in result
    
    def test_getalltsfiles_deterministic_path(self, tmp_path):
        """Test getalltsfiles with deterministic path parameters"""
        with patch('bot.botUtils.PROJECT_ROOT', tmp_path):
            # Create the expected directory structure
            download_dir = tmp_path / "downloads" / "death_note" / "S01E03"
            download_dir.mkdir(parents=True)
            test_file = download_dir / "episode.mp4"
            test_file.write_bytes(b"fake video data")
            
            result = getalltsfiles("death_note", 1, 3)
            assert result is not None
            assert "episode.mp4" in result
            assert "S01E03" in result
    
    def test_getalltsfiles_deterministic_path_not_found(self, tmp_path):
        """Test getalltsfiles with deterministic path when file doesn't exist"""
        with patch('bot.botUtils.PROJECT_ROOT', tmp_path):
            result = getalltsfiles("death_note", 1, 3)
            assert result is None


class TestNormalizeSeriesName:
    """Tests for normalize_series_name function"""
    
    def test_normalize_basic(self):
        """Test basic normalization"""
        result = normalize_series_name("Death Note")
        assert result == "death_note"
    
    def test_normalize_with_spaces(self):
        """Test normalization with multiple spaces"""
        result = normalize_series_name("Death  Note   Series")
        assert result == "death_note_series"
    
    def test_normalize_lowercase(self):
        """Test that normalization converts to lowercase"""
        result = normalize_series_name("DEATH NOTE")
        assert result == "death_note"
    
    def test_normalize_special_chars(self):
        """Test normalization removes special characters"""
        result = normalize_series_name("Death Note: The Series!")
        assert result == "death_note_the_series"
    
    def test_normalize_empty(self):
        """Test normalization with empty string"""
        result = normalize_series_name("")
        assert result == ""
    
    def test_normalize_whitespace_only(self):
        """Test normalization with whitespace only"""
        result = normalize_series_name("   ")
        assert result == ""


class TestGetDownloadPath:
    """Tests for get_download_path function"""
    
    def test_get_download_path_basic(self, tmp_path):
        """Test basic download path generation"""
        with patch('bot.botUtils.PROJECT_ROOT', tmp_path):
            download_dir, mp4_file = get_download_path("death_note", 1, 3)
            
            assert download_dir == tmp_path / "downloads" / "death_note" / "S01E03"
            assert mp4_file == download_dir / "episode.mp4"
    
    def test_get_download_path_season_formatting(self, tmp_path):
        """Test that season is formatted with zero padding"""
        with patch('bot.botUtils.PROJECT_ROOT', tmp_path):
            download_dir, mp4_file = get_download_path("test_anime", 10, 5)
            
            assert "S10E05" in str(download_dir)
    
    def test_get_download_path_negative_season(self, tmp_path):
        """Test download path with negative season (defaults to S00)"""
        with patch('bot.botUtils.PROJECT_ROOT', tmp_path):
            download_dir, mp4_file = get_download_path("test_anime", -1, 3)
            
            assert "S00E03" in str(download_dir)
