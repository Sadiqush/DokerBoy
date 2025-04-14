# DokerBoy

This project is a Telegram bot designed to provide easy access to Dokploy's basic functionalities. Users can manage their Dokploy applications directly through Telegram by setting up their URL and API Key.

## Features

- List available applications for management
- Start and stop services and applications
- Supports applications, composes and databases

## Requirements

- Python 3.7+
- `aiohttp`
- `aiogram`
- `tortoise-orm`

## Installation

1. Clone the repository:

   ```bash
   git clone https://github.com/yourusername/dokploy-telegram-bot.git
   cd dokploy-telegram-bot
   ```

2. Install the required packages:

   ```bash
   pip install -r requirements.txt
   ```

3. Set up your environment variables:

   ```bash
   export BOT_TOKEN='your_telegram_bot_token'
   export DB_URL='your_database_url'
   ```

## Usage

1. Run the bot:

   ```bash
   python main.py
   ```

2. Start a chat with your bot on Telegram and use the following commands:

   - `/start`: Start the bot and initialize settings
   - `/help`: Get information on how to use the bot
   - `/seturl <url>`: Set the URL for your Dokploy server
   - `/settoken <token>`: Set your Dokploy API token
   - `/services`: Manage your Dokploy applications

## Database Setup

This bot uses Tortoise ORM for database interactions. Ensure that your database is properly configured and accessible via the `DB_URL`.

### Database description

**Table Name:** config

#### Fields:

* **id:** (CharField, 20 chars) - Primary key, unique

* **url:** (CharField, 255 chars) - Optional (nullable)

* **api_key:** (CharField, 255 chars) - Optional (nullable)

## Contributing

Feel free to fork the repository, make changes, and submit pull requests. Any contributions to improve the bot are welcome!

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.