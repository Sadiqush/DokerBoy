import asyncio
import logging
import json
import os

import aiohttp
from aiogram import Bot, Dispatcher, types
from aiogram.client.default import DefaultBotProperties
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from tortoise import Tortoise, run_async
from tortoise import fields
from tortoise.models import Model
from tortoise import Tortoise


TOKEN = os.environ["BOT_TOKEN"]
DB_URL = os.getenv('DB_URL')

dp = Dispatcher()
bot = ...


class Config(Model):
    id = fields.IntField(pk=True)
    url = fields.CharField(max_length=255)
    token = fields.CharField(max_length=255)

    class Meta:
        table = "config"


async def init_db():
    await Tortoise.init(
        db_url=DB_URL,
        modules={'models': ['__main__']}
    )
    await Tortoise.generate_schemas()


@dp.message_handler(commands=['seturl'])
async def set_url(message: types.Message):
    url = message.text.split()[1]
    config = await Config.first()
    if not config:
        await Config.create(url=url, token='')
    else:
        config.url = url
        await config.save()
    await message.reply("URL has been set!")


@dp.message_handler(commands=['settoken'])
async def set_token(message: types.Message):
    token = message.text.split()[1]
    config = await Config.first()
    if not config:
        await Config.create(url='', token=token)
    else:
        config.token = token
        await config.save()
    await message.reply("Token has been set!")


async def get_apps():
    config = await Config.first()
    if not config:
        return []

    async with aiohttp.ClientSession() as session:
        async with session.get(f"{config.url}/api/project.all",
                               headers={"Authorization": f"Bearer {config.token}"}) as resp:
            if resp.status == 200:
                data = await resp.json()
                return data
    return []


async def create_apps_keyboard():
    apps = await get_apps()
    keyboard = InlineKeyboardMarkup()
    for app in apps:
        keyboard.add(InlineKeyboardButton(app['name'], callback_data=f"app_{app['name']}"))
    return keyboard


@dp.message_handler(commands=['deploy', 'reload', 'redeploy', 'stop', 'start'])
async def handle_command(message: types.Message):
    command = message.get_command()[1:]
    keyboard = await create_apps_keyboard()
    await message.reply(f"Select application to {command}:", reply_markup=keyboard)


@dp.callback_query_handler(lambda c: c.data.startswith('app_'))
async def process_callback(callback_query: types.CallbackQuery):
    app_name = callback_query.data.split('_')[1]
    command = callback_query.message.text.split()[3].replace(':', '')

    config = await Config.first()
    if not config:
        await callback_query.answer("URL and token not set!")
        return

    async with aiohttp.ClientSession() as session:
        url = f"{config.url}/api/application.{command}"
        headers = {"Authorization": f"Bearer {config.token}"}

        async with session.post(url, headers=headers) as resp:
            if resp.status == 200:
                await callback_query.answer(f"Successfully {command}ed {app_name}")
            else:
                await callback_query.answer(f"Failed to {command} {app_name}")


async def run() -> None:
    global bot
    bot = Bot(token=TOKEN, default=DefaultBotProperties())
    await dp.start_polling(bot)


if __name__ == "__main__":
    logging.info('Initializing...')
    logging.basicConfig(level=logging.INFO)
    run_async(init_db())
    asyncio.run(run())
