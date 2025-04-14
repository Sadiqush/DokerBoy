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
    await message.answer(f"Hello, {message.from_user.full_name}!\n\n"
                         "Use /help to know how to use this bot.")


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
        await message.reply("Invalid! \nUse this command like this:\n\n/seturl https://your-domain.com")
        return
    url = message.text.split()[1]
    if not urlparse(url).scheme:
        await message.reply("Invalid URL format!\nIt must include the scheme, e.g., https://your-domain.com")
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


# Keep a cache of services by user id to reference them in callback queries.
# Each service is represented as a DokItem instance.
user_items: dict[int, list["DokItem"]] = {}


# Helper class to store Dokploy service information.
class DokItem:
    def __init__(self, index, name, app_name, app_id, project_name, type):
        self.index: int = index
        self.name: str = name
        self.app_name: str = app_name
        self.app_id: str = app_id
        self.project_name: str = project_name
        self.type: str = type

    def get_type(self):
        return "application" if self.type == "applications" else self.type


async def get_projects(userid: int) -> list:
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


# Creates the initial keyboard listing all services.
async def create_apps_keyboard(userid: int) -> InlineKeyboardMarkup:
    projects = await get_projects(userid)
    buttons = []
    user_items[userid] = []
    counter = 0
    for project in projects:
        # Looping through potential service types.
        for key in ["applications", "mariadb", "mongo", "mysql", "postgres", "redis", "compose"]:
            for app in project.get(key, []):
                app_id = app.get("applicationId") if key == "applications" else app.get(f"{key}Id")
                app_name = app["appName"]
                dokitem = DokItem(
                    counter,
                    name=app['name'],
                    app_name=app_name,
                    app_id=app_id,
                    project_name=project["name"],
                    type=key
                )
                user_items[userid].append(dokitem)
                buttons.append(
                    [InlineKeyboardButton(
                        text=f"{project['name']}: {app['name']}",
                        callback_data=f"service_{counter}"
                    )]
                )
                counter += 1
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    return keyboard


# New command to list all services.
@dp.message(Command('services'))
async def services_handler(message: Message) -> None:
    config = await Config.get_or_none(id=message.from_user.id)
    if not config or not config.url or not config.api_key:
        await message.reply("URL or API Key not set yet!\nPlease use /seturl and /setapikey.")
        return
    keyboard = await create_apps_keyboard(userid=message.from_user.id)
    await message.reply("Select a service:", reply_markup=keyboard)


# Callback when a user selects a service from the list.
@dp.callback_query(lambda c: c.data.startswith('service_'))
async def process_service_selection(callback_query: types.CallbackQuery):
    try:
        index = int(callback_query.data.split('_')[1])
        service_item = user_items[callback_query.from_user.id][index]
    except (IndexError, ValueError):
        await callback_query.answer("Invalid service selected.")
        return

    # Create an inline keyboard with action buttons
    actions = ["start", "stop", "restart", "reload", "deploy", "redeploy"]
    action_buttons = [
        [InlineKeyboardButton(text=action.capitalize(), callback_data=f"action_{action}_{index}")]
        for action in actions
    ]
    keyboard = InlineKeyboardMarkup(inline_keyboard=action_buttons)
    text = (f"Service: {service_item.name}\n"
            f"Project: {service_item.project_name}\n\n"
            "Choose an action:")
    await bot.edit_message_text(
        text=text,
        chat_id=callback_query.from_user.id,
        message_id=callback_query.message.message_id,
        reply_markup=keyboard
    )
    await callback_query.answer()  # Acknowledge callback


# Callback when an action is chosen.
@dp.callback_query(lambda c: c.data.startswith('action_'))
async def process_action(callback_query: types.CallbackQuery):
    try:
        _, action, index_str = callback_query.data.split('_')
        index = int(index_str)
        service_item = user_items[callback_query.from_user.id][index]
    except (IndexError, ValueError):
        await callback_query.answer("Invalid action!")
        return

    config = await Config.get(id=callback_query.from_user.id)
    url = urljoin(str(config.url), f"/api/{service_item.get_type()}.{action}")
    headers = {"x-api-key": config.api_key}
    body = {f"{service_item.get_type()}Id": service_item.app_id}

    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=headers, data=body) as resp:
            if resp.status == 200:
                result_text = f"Successfully {action}ed {service_item.app_name}"
            else:
                result_text = f"Failed to {action} {service_item.app_name}"
    await bot.edit_message_text(
        text=result_text,
        chat_id=callback_query.from_user.id,
        message_id=callback_query.message.message_id
    )
    await callback_query.answer()  # Acknowledge callback


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
