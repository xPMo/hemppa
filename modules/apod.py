import os
import re

import requests
from nio import AsyncClient, UploadError
from nio import UploadResponse

from modules.common.module import BotModule


class Apod:
    def __init__(self, title, explanation, date, hdurl, media_type, url):
        self.hdurl = hdurl
        self.title = title
        self.explanation = explanation
        self.date = date
        self.media_type = media_type
        self.url = url

    @staticmethod
    def create_from_json(json):
        return Apod(json.get("title"), json.get("explanation"), json.get("date"), json.get("hdurl"),
                    json.get("media_type"), json.get("url"))

    def __str__(self):
        return "title: {} || explanation: {} || date: {} || original-url: {}".format(self.title,
                                                                                     self.explanation,
                                                                                     self.date,
                                                                                     self.hdurl)


class MatrixModule(BotModule):

    def __init__(self, name):
        super().__init__(name)
        self.api_key = os.getenv("APOD_API_KEY", "DEMO_KEY")
        self.update_api_urls()
        self.matrix_uri_cache = dict()
        self.APOD_DATE_PATTERN = r"^\d\d\d\d-\d\d-\d\d$"

    def update_api_urls(self):
        self.apod_api_url = f"https://api.nasa.gov/planetary/apod?api_key={self.api_key}&hd=true"
        self.apod_by_date_api_url = self.apod_api_url + "&date="

    async def matrix_message(self, bot, room, event):
        self.logger.debug(f"room: {room.name} sender: {event.sender} wants latest astronomy picture of the day")

        args = event.body.split()

        if len(args) == 1:
            await self.send_apod(bot, room, self.apod_api_url)
        elif len(args) == 2:
            if args[1] == "stats":
                await self.send_stats(bot, room)
            elif args[1] == "clear":
                bot.must_be_admin(room, event)
                await self.clear_uri_cache(bot, room)
            elif args[1] == "help":
                await self.long_help(bot=bot, room=room, event=event)
            else:
                date = args[1]
                if re.match(self.APOD_DATE_PATTERN, date) is not None:
                    uri = self.apod_by_date_api_url + date
                    await self.send_apod(bot, room, uri)
                else:
                    await bot.send_text(room, "invalid date. accpeted: YYYY-MM-DD")
        elif len(args) == 3:
            if args[1] == "apikey":
                await self.update_api_key(bot, room, event, args[2])

    async def send_apod(self, bot, room, uri):
        self.logger.debug(f"send request using uri {uri}")
        response = requests.get(uri)
        if response.status_code == 200:
            apod = Apod.create_from_json(response.json())

            self.logger.debug(apod)
            if apod.media_type == "image":
                await self.upload_and_send_image(room, bot, apod)
            else:
                await self.send_unknown_mediatype(room, bot, apod)
        elif response.status_code == 400:
            self.logger.error("unable to request apod api. status: %d text: %s", response.status_code, response.text)
            await bot.send_text(room, response.json().get("msg"))
        else:
            self.logger.error("unable to request apod api. response: [status: %d text: %s]", response.status_code, response.text)
            await bot.send_text(room, "sorry. something went wrong accessing the api :(")

    async def send_unknown_mediatype(self, room, bot, apod):
        self.logger.debug(f"unknown media_type: {apod.media_type}. sending raw information")
        await bot.send_text(room, f"{apod.title}")
        await bot.send_text(room, f"{apod.explanation} || date: {apod.date} || original-url: {apod.url}")

    async def upload_and_send_image(self, room, bot, apod):
        send_again = True
        await bot.send_text(room, f"{apod.title} ({apod.date})")
        if apod.date in self.matrix_uri_cache:
            matrix_uri = self.matrix_uri_cache.get(apod.date)
            self.logger.debug(f"already uploaded picture {matrix_uri} for date {apod.date}")
        else:
            matrix_uri = await bot.upload_and_send_image(room, apod.hdurl, f"{apod.title}")
            send_again = False

        if matrix_uri is not None:
            self.matrix_uri_cache[apod.date] = matrix_uri
            bot.save_settings()
            if send_again:
                await bot.send_image(room, matrix_uri, f"{apod.title}")
        else:
            await bot.send_text(room, "Sorry. Something went wrong uploading the image to Matrix server :(")
        await bot.send_text(room, f"{apod.explanation}")

    def get_settings(self):
        data = super().get_settings()
        data["matrix_uri_cache"] = self.matrix_uri_cache
        data["api_key"] = self.api_key
        return data

    def set_settings(self, data):
        super().set_settings(data)
        if data.get("matrix_uri_cache"):
            self.matrix_uri_cache = data["matrix_uri_cache"]
        if data.get("api_key"):
            self.api_key = data["api_key"]
            self.update_api_urls()

    def help(self):
        return 'Sends latest Astronomy Picture of the Day to the room. (https://apod.nasa.gov/apod/astropix.html)'

    async def send_stats(self, bot, room):
        msg = f"collected {len(self.matrix_uri_cache)} upload matrix uri's"
        await bot.send_text(room, msg)

    async def clear_uri_cache(self, bot, room):
        self.matrix_uri_cache.clear()
        bot.save_settings()
        await bot.send_text(room, "cleared uri cache")

    async def long_help(self, bot=None, event=None, room=None, **kwargs):
        text = self.help() + (
                '\n- !apod help: show this help'
                '\n- !apod [YYYY-MM-DD]: date of APOD image to retrieve (ex. 2020-03-15)'
                '\n- !apod stats: show information about the uri cache'
                )
        if bot and event and bot.is_admin(event):
            text += ('\n- !apod clear: clear uri cache'
                    )
        if bot and event and bot.is_owner(event):
            text += ('\n- !apod apikey [api-key]: set the api key'
                    )
        await bot.send_text(room, msg)

    async def update_api_key(self, bot, room, event, apikey):
        bot.must_be_owner(event)
        self.api_key = apikey
        self.update_api_urls()
        bot.save_settings()
        await bot.send_text(room, 'Api key set')

