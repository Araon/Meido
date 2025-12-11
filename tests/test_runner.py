"""
Helper script to set up imports for testing bot commands
This ensures relative imports work correctly
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
BOT_DIR = PROJECT_ROOT / 'bot'

# Add bot directory to path for relative imports
if str(BOT_DIR) not in sys.path:
    sys.path.insert(0, str(BOT_DIR))

# Map relative imports to absolute imports
import bot.botUtils as botUtils_module
import bot.database as database_module

sys.modules['botUtils'] = botUtils_module
sys.modules['database'] = database_module
