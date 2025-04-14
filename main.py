import asyncio
import logging
import os
from urllib.parse import urljoin, urlparse

import aiohttp
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command, CommandStart
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message
from tortoise import run_async
from tortoise import fields
from tortoise.models import Model
from tortoise import Tortoise

TOKEN = os.environ["BOT_TOKEN"]
DB_URL = os.getenv('DB_URL')

bot = Bot(token=TOKEN)
dp = Dispatcher()

# Global dictionaries to store user session data
user_projects: dict[int, list] = {}  # Maps user id to list of project JSONs
user_project_services: dict[int, dict[int, list]] = {}  # Maps user id -> {project_index: [DokItem, ...]}


class Config(Model):
    id = fields.CharField(20, pk=True, unique=True)
    url = fields.CharField(max_length=255, null=True)
    api_key = fields.CharField(max_length=255, null=True)

    class Meta:
        table = "config"


async def init_db():
    await Tortoise.init(
        db_url=DB_URL,
        modules={'models': ['__main__']}
    )
    await Tortoise.generate_schemas()


@dp.message(CommandStart())
async def command_start_handler(message: Message) -> None:
    if not await Config.get_or_none(id=message.from_user.id):
        await Config.create(id=message.from_user.id)
    await message.answer(
        f"Hello, {message.from_user.full_name}!\n\nUse /help to know how to use this bot."
    )


@dp.message(Command('help'))
async def command_start_handler(message: Message) -> None:
    await message.answer(f"This bot is designed to give you access to Dokploy's basic functionalities easily through "
                         f"Telegram. The only thing you need to do is to set you url and API Key once, and that's it.\n\n"
                         "To get your API Key you need to login to your Dokploy's UI interface and follow these steps:\n\n"
                         "1-\n"
                         "(IMPORTANT: in version 0.19 Dokploy changed how authorization works, it used Bearer Token but now it uses API Key. If you haven't updated your Dokploy instance, you need to do that first.)\n"
                         "From side panel go to Settings/Profile -> Scroll down to API/CLI -> Generate New Key -> Generate and copy\n\n"
                         "2-\n"
                         "Then paste your API Key to this bot:\n`/setapikey <key>`\n\n"
                         "3-\n"
                         "Finally set the url to your Dokploy server:\n`/seturl https://your-domain.com`\n\n"
                         "Other Commands:\n"
                         "/start\\_service: Start a service you choose from the menu\n"
                         "/stop\\_service: Stop a service you choose from the menu\n"
                         "/reload: Reload a service you choose from the menu\n"
                         "/deploy: Deploy your service you choose from the menu\n"
                         "/redeploy: Redeploy a service you choose from the menu\n",
                         parse_mode="Markdown")


@dp.message(Command('seturl'))
async def set_url(message: types.Message):
    if message.text.strip() == '/seturl':
        await message.reply("Invalid!\nUsage: /seturl https://your-domain.com")
        return
    url = message.text.split()[1]
    if not urlparse(url).scheme:
        await message.reply("Invalid URL format!\nIt must include the full scheme (e.g., https://your-domain.com)")
        return
    config = await Config.get(id=message.from_user.id)
    config.url = url
    await config.save()
    await message.reply("URL has been set!")


@dp.message(Command('setapikey'))
async def set_apikey(message: types.Message):
    if message.text == '/setapikey':
        await message.reply("Invalid! \nUse this command like this:\n\n/setapikey <key>")
        return None
    key = message.text.split()[1]
    config = await Config.get(id=message.from_user.id)
    config.api_key = key
    await config.save()
    await message.reply("API Key has been set!")


async def get_projects(userid: int) -> list:
    """Call Dokploy API to fetch projects."""
    config = await Config.get(id=userid)
    if not config:
        return []
    async with aiohttp.ClientSession() as session:
        async with session.get(
            urljoin(config.url, "/api/project.all"),
            headers={"x-api-key": config.api_key}
        ) as resp:
            if resp.status == 200:
                data = await resp.json()
                return data
            else:
                logging.error(f"Error fetching projects: {await resp.text()}")
    return []


class DokItem:
    def __init__(self, index, name, app_name, app_id, project_name, type):
        self.index: int = index  # Service index within the project
        self.name: str = name
        self.app_name: str = app_name
        self.app_id: str = app_id
        self.project_name: str = project_name
        self.type: str = type

    def get_type(self):
        return "application" if self.type == "applications" else self.type


# Command to list projects
@dp.message(Command('services'))
async def services_handler(message: Message) -> None:
    config = await Config.get_or_none(id=message.from_user.id)
    if not config or not config.url or not config.api_key:
        await message.reply("URL or API Key not set!\nPlease use /seturl and /setapikey.")
        return
    projects = await get_projects(message.from_user.id)
    if not projects:
        await message.reply("No projects found.")
        return
    user_projects[message.from_user.id] = projects
    buttons = []
    for idx, project in enumerate(projects):
        buttons.append(
            [InlineKeyboardButton(text=project["name"], callback_data=f"project_{idx}")]
        )
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await message.reply("Select a project:", reply_markup=keyboard)


# Callback when a project button is pressed.
@dp.callback_query(lambda c: c.data.startswith('project_'))
async def process_project_selection(callback_query: types.CallbackQuery):
    """Get all services (applications) in this project."""
    user_id = callback_query.from_user.id
    try:
        project_index = int(callback_query.data.split("_")[1])
        project: [DokItem] = user_projects[user_id][project_index]
    except (IndexError, ValueError):
        await callback_query.answer("Invalid project selection!")
        return

    # Build the list of services for the selected project.
    services = []
    counter = 0
    # Loop over different keys where services might be stored.
    for key in ["applications", "mariadb", "mongo", "mysql", "postgres", "redis", "compose"]:
        for app in project.get(key, []):
            if key == "applications":
                app_id = app.get("applicationId")
            else:
                app_id = app.get(f"{key}Id")
            app_name = app.get("appName")
            dokitem = DokItem(
                counter,
                name=app.get("name"),
                app_name=app_name,
                app_id=app_id,
                project_name=project["name"],
                type=key
            )
            services.append(dokitem)
            counter += 1

    if user_id not in user_project_services:
        user_project_services[user_id] = {}
    user_project_services[user_id][project_index] = services

    if not services:
        await bot.edit_message_text(
            text=f"Project: {project['name']}\n\nNo services found for this project.",
            chat_id=user_id,
            message_id=callback_query.message.message_id
        )
        return

    # Build a keyboard of services.
    buttons = []
    for dokitem in services:
        buttons.append(
            [InlineKeyboardButton(text=dokitem.name, callback_data=f"service_{project_index}_{dokitem.index}")]
        )
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    text = f"Project: {project['name']}\nSelect a service:"
    await bot.edit_message_text(
        text=text,
        chat_id=user_id,
        message_id=callback_query.message.message_id,
        reply_markup=keyboard
    )
    await callback_query.answer()


# Callback when a service is selected.
@dp.callback_query(lambda c: c.data.startswith('service_'))
async def process_service_selection(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    try:
        # Expected format: service_{project_index}_{service_index}
        _, project_idx, service_idx = callback_query.data.split('_')
        project_idx = int(project_idx)
        service_idx = int(service_idx)
        dokitem = user_project_services[user_id][project_idx][service_idx]
    except (IndexError, ValueError):
        await callback_query.answer("Invalid service selection!")
        return

    # Create an inline keyboard with action buttons.
    actions = ["start", "stop", "restart", "reload", "deploy", "redeploy"]
    action_buttons = [
        [InlineKeyboardButton(text=action.capitalize(), callback_data=f"action_{action}_{project_idx}_{service_idx}")]
        for action in actions
    ]
    keyboard = InlineKeyboardMarkup(inline_keyboard=action_buttons)
    text = (f"Project: {dokitem.project_name}\n"
            f"Service: {dokitem.name}\n\n"
            "Choose an action:")
    await bot.edit_message_text(
        text=text,
        chat_id=user_id,
        message_id=callback_query.message.message_id,
        reply_markup=keyboard
    )
    await callback_query.answer()


# Callback to process the selected action.
@dp.callback_query(lambda c: c.data.startswith('action_'))
async def process_action(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    try:
        # Expected format: action_{action}_{project_idx}_{service_idx}
        _, action, project_idx, service_idx = callback_query.data.split('_')
        project_idx = int(project_idx)
        service_idx = int(service_idx)
        dokitem = user_project_services[user_id][project_idx][service_idx]
    except (IndexError, ValueError):
        await callback_query.answer("Invalid action!")
        return

    config = await Config.get(id=callback_query.from_user.id)
    url = urljoin(str(config.url), f"/api/{dokitem.get_type()}.{action}")
    headers = {"x-api-key": config.api_key}
    body = {f"{dokitem.get_type()}Id": dokitem.app_id}

    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=headers, data=body) as resp:
            if resp.status == 200:
                result_text = f"Successfully {action}ed {dokitem.app_name}"
            else:
                result_text = f"Failed to {action} {dokitem.app_name}"
    await bot.edit_message_text(
        text=result_text,
        chat_id=user_id,
        message_id=callback_query.message.message_id
    )
    await callback_query.answer()


async def run() -> None:
    await bot.set_my_commands([
        types.BotCommand(command='/start', description='Start the bot'),
        types.BotCommand(command='/help', description='Show help information'),
        types.BotCommand(command='/seturl', description='Set URL to your Dokploy'),
        types.BotCommand(command='/setapikey', description='Set your Dokploy API Key'),
        types.BotCommand(command='/services', description='List all services'),
    ])
    await dp.start_polling(bot)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    logging.info('Initializing...')
    run_async(init_db())
    asyncio.run(run())
