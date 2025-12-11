# Meido

<p align="center">
   <img src="docs/meido.png" width="250" height="250" style="border-radius: 50%;">
</p>

A Telegram bot to send anime directly to your inbox. This bot uses [animdl](https://github.com/justfoolingaround/animdl) for searching and downloading anime files, and stores them in MongoDB for faster subsequent access.

### System Design

![System Design](docs/screenshot.png)

## Features

- 🎬 Download anime episodes on demand
- 💾 Cache downloaded episodes in MongoDB for instant access
- 📱 Send videos directly to Telegram users
- 🔍 Search and download from multiple anime sources via animdl
- ⚡ Fast response times for cached content

## Requirements

- Python 3.9 or higher
- MongoDB (local or remote instance)
- FFmpeg (for video conversion)
- Telegram Bot Token
- Telegram API credentials (api_id, api_hash) from [my.telegram.org](https://my.telegram.org)

## Installation

### 1. Clone the Repository

```bash
git clone https://github.com/yourusername/Meido.git
cd Meido
```

### 2. Install Dependencies

Using pip:

```bash
pip install -r requirements.txt
```

Using pipenv:

```bash
pipenv install
```

### 3. Install FFmpeg

**Ubuntu/Debian:**

```bash
sudo apt-get update
sudo apt-get install ffmpeg
```

**macOS:**

```bash
brew install ffmpeg
```

**Windows:**
Download from [FFmpeg official website](https://ffmpeg.org/download.html) and add to PATH.

### 4. Install animdl

```bash
pip install animdl
```

Or install from source:

```bash
pip install git+https://github.com/justfoolingaround/animdl.git
```

### 5. Setup MongoDB

**Local Installation:**

```bash
# Ubuntu/Debian
sudo apt-get install mongodb

# macOS
brew install mongodb-community

# Start MongoDB service
sudo systemctl start mongod  # Linux
brew services start mongodb-community  # macOS
```

**Docker:**

```bash
docker run -d -p 27017:27017 --name mongodb mongo:latest
```

**Remote MongoDB:**
Set the `MONGO_DB_URL` environment variable:

```bash
export MONGO_DB_URL="mongodb://username:password@host:port/"
```

## Configuration

### 1. Bot Configuration

Create `bot/config/botConfig.json` from the example:

```bash
cp bot/config/exampleConfig.json bot/config/botConfig.json
```

Edit `bot/config/botConfig.json`:

```json
{
    "bot_token": "YOUR_BOT_TOKEN_FROM_BOTFATHER",
    "agent_user_id": YOUR_TELEGRAM_USER_ID
}
```

To get your bot token:

1. Open Telegram and search for [@BotFather](https://t.me/botfather)
2. Send `/newbot` and follow instructions
3. Copy the token provided

To get your user ID:

1. Search for [@userinfobot](https://t.me/userinfobot) on Telegram
2. Start a conversation to get your user ID

### 2. Uploader Service Configuration

Create `uploaderService/config/agentConfig.json` from the example:

```bash
cp uploaderService/config/Example_agentConfig.json uploaderService/config/agentConfig.json
```

Edit `uploaderService/config/agentConfig.json`:

```json
{
  "entity": "session_name",
  "api_id": "YOUR_API_ID",
  "api_hash": "YOUR_API_HASH",
  "phone": "+1234567890",
  "bot_name": "@your_bot_username"
}
```

To get your API credentials:

1. Go to [my.telegram.org](https://my.telegram.org)
2. Log in with your phone number
3. Go to "API development tools"
4. Create a new application and copy `api_id` and `api_hash`

**Important:** The `bot_name` should be your bot's username (e.g., `@myanimebot`)

## Usage

### Starting the Bot

From the project root directory:

```bash
python bot/bot.py
```

Or using pipenv:

```bash
pipenv run python bot/bot.py
```

### Bot Commands

- `/start` - Start the bot and see welcome message
- `/help` - Show help message with available commands
- `/getanime <anime_name>, <season>, <episode>` - Download and send anime episode

**Example:**

```
/getanime Death Note, 1, 3
```

This will:

1. Check if the episode exists in the database
2. If found, send it immediately
3. If not found, download it, convert to MP4, upload to Telegram, and send it to you

## Project Structure

```
Meido/
├── bot/
│   ├── bot.py              # Main bot application
│   ├── botUtils.py         # Utility functions
│   ├── database.py         # MongoDB operations
│   └── config/
│       ├── botConfig.json  # Bot configuration (create from example)
│       └── exampleConfig.json
├── downloaderService/
│   └── main.py             # Anime download service
├── uploaderService/
│   ├── main.py             # Telegram upload service
│   └── config/
│       ├── agentConfig.json # Uploader config (create from example)
│       └── Example_agentConfig.json
├── docs/
│   ├── architechture.md    # Architecture documentation
│   └── databaseSchema.md   # Database schema
├── requirements.txt        # Python dependencies
├── Pipfile                 # Pipenv dependencies
└── README.md              # This file
```

## How It Works

1. **User Request**: User sends `/getanime` command with anime details
2. **Database Check**: Bot checks MongoDB for existing file_id
3. **Cache Hit**: If found, bot sends video immediately using file_id
4. **Cache Miss**: If not found:
   - Downloads anime using animdl
   - Converts .ts to .mp4 using FFmpeg
   - Uploads to Telegram via Telethon (agent account)
   - Bot receives file_id and stores in database
   - Bot sends video to user
5. **Future Requests**: Subsequent requests for the same episode are instant

## Troubleshooting

### Bot won't start

- **Config file not found**: Ensure `botConfig.json` exists in `bot/config/`
- **Invalid token**: Verify your bot token is correct
- **MongoDB connection error**: Check if MongoDB is running and accessible
  ```bash
  # Test MongoDB connection
  mongosh
  ```

### Downloads fail

- **animdl not installed**: Install animdl as shown in installation steps
- **FFmpeg not found**: Ensure FFmpeg is installed and in PATH
  ```bash
  ffmpeg -version  # Should show version info
  ```

### Upload fails

- **Telegram API error**: Verify your API credentials in `agentConfig.json`
- **Session not authorized**: On first run, you'll need to enter the verification code
- **File not found**: Ensure the download completed successfully

### Database issues

- **Connection timeout**: Check MongoDB is running
- **Authentication error**: Verify MongoDB URL if using remote instance
- **Collection not found**: The collection will be created automatically on first use

## Environment Variables

- `MONGO_DB_URL`: MongoDB connection string (default: `mongodb://localhost:27017/`)

Example:

```bash
export MONGO_DB_URL="mongodb://user:pass@localhost:27017/"
```

## Security Notes

- **Never commit** `botConfig.json` or `agentConfig.json` to version control
- These files are in `.gitignore` by default
- Use environment variables for sensitive data in production
- Keep your API credentials secure

## Development

### Code Style

The project follows PEP 8 Python style guidelines. Consider using:

- `black` for code formatting
- `flake8` for linting
- `mypy` for type checking

### Testing

The project includes a comprehensive test suite using pytest. To run tests:

**Install test dependencies:**

```bash
pip install -r requirements.txt
```

**Run all tests:**

```bash
pytest tests/ -v
```

Or use the test runner script:

```bash
./run_tests.sh
```

**Run specific test files:**

```bash
pytest tests/test_botUtils.py -v
pytest tests/test_database.py -v
pytest tests/test_bot_commands.py -v
pytest tests/test_integration.py -v
```

**Run with coverage:**

```bash
pytest tests/ --cov=bot --cov=downloaderService --cov=uploaderService --cov-report=html
```

**Test Structure:**

- `tests/test_botUtils.py` - Tests for utility functions (parsing, file operations)
- `tests/test_database.py` - Tests for MongoDB operations
- `tests/test_bot_commands.py` - Tests for bot commands (/start, /help, /getanime)
- `tests/test_integration.py` - Integration tests for complete workflows

### Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests for new features
5. Ensure all tests pass
6. Submit a pull request

## License

See [LICENSE](LICENSE) file for details.

## Status

✅ Core functionality working
✅ MongoDB integration
✅ Error handling improved
✅ Modern dependencies
🔄 Pre-caching popular anime (planned)
🔄 Subscription feature (planned)
🔄 Watch list (planned)
🔄 Recommendations (planned)

## Support

If you encounter any issues or have questions:

- Open an issue on GitHub
- Check existing issues for solutions
- Review the troubleshooting section above

## Acknowledgments

- [animdl](https://github.com/justfoolingaround/animdl) for anime downloading
- [python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot) for Telegram bot framework
- [Telethon](https://github.com/LonamiWebs/Telethon) for Telegram client library

---

**Note**: This bot is for educational purposes. Ensure you comply with copyright laws and terms of service when using this software.
