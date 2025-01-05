import asyncio
import logging
import os

import aiohttp
from urllib.parse import urljoin, urlparse
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
    token = fields.CharField(max_length=255, null=True)

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
    await message.answer(f"Hello, {message.from_user.full_name}!\n\n Use /help to know how to use this bot.")


@dp.message(Command('help'))
async def command_start_handler(message: Message) -> None:
    await message.answer(f"This bot is designed to give you access to Dokploy's basic functionalities easily through "
                         f"Telegram. The only thing you need to do is to set you url and token once, and that's it.\n\n"
                         "To get your token you need to login to your Dokploy's UI interface and follow these steps:\n\n"
                         "1-\n"
                         "Go to Settings -> Scroll down to API/CLI -> Generate Token -> Copy token\n\n"
                         "2-\n"
                         "Then paste your token to this bot:\n`/settoken <token>`\n\n"
                         "3-\n"
                         "Finally set the url to your Dokploy server:\n`/seturl https://your-domain.com`\n\n"
                         "Other Commands:\n"
                         "/start_service: Start a service you choose from the menu\n"
                         "/stop_service: Stop a service you choose from the menu\n"
                         "/reload: Reload a service you choose from the menu\n"
                         "/deploy: Deploy your service you choose from the menu\n"
                         "/redeploy: Redeploy a service you choose from the menu\n",
                         parse_mode="Markdown")


@dp.message(Command('seturl'))
async def set_url(message: types.Message):
    if message.text == '/seturl':
        await message.reply("Invalid! \nUse this command like this:\n\n/seturl https://your-domain.com")
        return None
    url = message.text.split()[1]
    if not urlparse(url).scheme:
        await message.reply("Invalid URL format!\nIt needs to have full scheme, e.g: https://your-domain.com")
        return None
    config = await Config.get(id=message.from_user.id)
    config.url = url
    await config.save()
    await message.reply("URL has been set!")


@dp.message(Command('settoken'))
async def set_token(message: types.Message):
    if message.text == '/settoken':
        await message.reply("Invalid! \nUse this command like this:\n\n/settoken <token>")
        return None
    token = message.text.split()[1]
    config = await Config.get(id=message.from_user.id)
    config.token = token
    await config.save()
    await message.reply("Token has been set!")


async def get_projects(userid: int) -> dict[str, "JSON"]:
    config = await Config.get(id=userid)
    if not config:
        return []

    async with aiohttp.ClientSession() as session:
        async with session.get(urljoin(config.url, "/api/project.all"),
                               headers={"Authorization": f"Bearer {config.token}"}) as resp:
            if resp.status == 200:
                data = await resp.json()
                return data
            else:
                logging.error(f"Error: {resp.text()}")
    return []


class DokItem:
    def __init__(self, index, name, app_name, app_id, project_name, type):
        self.index: int = index
        self.name: str = name
        self.app_name: str = app_name
        self.app_id: str = app_id
        self.project_name: str = project_name
        self.type: str = type

    def get_type(self):
        if self.type == "applications":
            return "application"
        else:
            return self.type


user_items: dict[int, list[DokItem]] = {}


async def create_apps_keyboard(userid: int):
    projects = await get_projects(userid)
    buttons = []
    user_items[userid] = []
    counter = 0
    for project in projects:
        for key in ["applications", "mariadb", "mongo", "mysql", "postgres", "redis", "compose"]:
            for app in project[key]:
                if key == "applications":
                    app_id = app["applicationId"]
                else:
                    app_id = app[f"{key}Id"]
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
                        callback_data=f"app_{counter}"
                    )]
                )
                counter += 1
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    return keyboard


@dp.message(Command('deploy'))
@dp.message(Command('reload'))
@dp.message(Command('redeploy'))
@dp.message(Command('stop_service'))
@dp.message(Command('start_service'))
async def handle_command(message: types.Message):
    config = await Config.get_or_none(id=message.from_user.id)
    if not config.url or not config.token:
        await message.reply(text="URL or token not set yet!\n Use /seturl and /settoken")
        return None
    command = message.text[1:]
    if '_' in command:
        command = command.split('_')[0]
    keyboard = await create_apps_keyboard(userid=message.from_user.id)
    await message.reply(f"Select application to {command}:\n\n [Project]: [Application]", reply_markup=keyboard)


@dp.callback_query(lambda c: c.data.startswith('app_'))
async def process_callback(callback_query: types.CallbackQuery):
    for item in user_items[callback_query.from_user.id]:
        if item.index == int(callback_query.data.split('_')[1]):
            dokitem = item
    command = callback_query.message.text.split()[3].replace(':', '')

    config = await Config.get_or_none(id=callback_query.from_user.id)

    async with aiohttp.ClientSession() as session:
        url = urljoin(config.url, f"/api/{dokitem.get_type()}.{command}")
        headers = {"Authorization": f"Bearer {config.token}"}
        body = {f"{dokitem.get_type()}Id": dokitem.app_id}
        async with session.post(url, headers=headers, data=body) as resp:
            if resp.status == 200:
                await bot.edit_message_text(text=f"Successfully {command}ed {dokitem.app_name}",
                                            chat_id=callback_query.from_user.id,
                                            message_id=callback_query.message.message_id)
            else:
                await bot.edit_message_text(text=f"Failed to {command} {dokitem.app_name}",
                                            chat_id=callback_query.from_user.id,
                                            message_id=callback_query.message.message_id)


async def run() -> None:
    await bot.set_my_commands([
        types.BotCommand(command='/start', description='Start the bot'),
        types.BotCommand(command='/help', description='Show help information'),
        types.BotCommand(command='/seturl', description='Set URL to your Dokploy'),
        types.BotCommand(command='/settoken', description='Set your Dokploy Token'),
        types.BotCommand(command='/start', description='Start Your Dokploy application'),
        types.BotCommand(command='/stop', description='Stop Your Dokploy application'),
        types.BotCommand(command='/reload', description='Reload Your Dokploy application'),
        types.BotCommand(command='/deploy', description='Deploy Your Dokploy application'),
        types.BotCommand(command='/redeploy', description='Redeploy Your Dokploy application')
    ])
    await dp.start_polling(bot)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    logging.info('Initializing...')
    run_async(init_db())
    asyncio.run(run())
