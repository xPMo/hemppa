from modules.common.module import BotModule
from nio import RoomMessageText

import pypandoc as pandoc

class MatrixModule(BotModule):
    def __init__(self, name):
        super().__init__(name)
        self.enabled = False

        self.lines = 5
        self.chars = 500
        self.default_output = 'txt'
        self.input_formats = []

        self.commands = {
                **dict.fromkeys(['set', 'default'], self.set_behavior),
                **dict.fromkeys(['get', 'show'], self.get_behavior),
                **dict.fromkeys(['add'], self.add_behavior),
                **dict.fromkeys(['rm', 'remove'], self.remove_behavior),
        }

    def set_settings(self, data):
        super().set_settings(data)
        if data.get('lines'):
            self.lines = data['lines']
        if data.get('chars'):
            self.chars = data['chars']
        if data.get('default_output'):
            self.default_output = data['default_output']
        if data.get('input_formats'):
            self.input_formats = data['input_formats']

    def get_settings(self):
        data = super().get_settings()
        data['lines'] = self.lines
        data['chars'] = self.chars
        data['default_output'] = self.default_output
        data['input_formats'] = self.input_formats
        return data

    def matrix_start(self, bot):
        super().matrix_start(bot)
        self.bot = bot
        bot.client.add_event_callback(self.message_cb, RoomMessageText)
        langs = [*self.aliases.keys(), *self.langmap.keys()]
        self.add_module_aliases(bot, langs + [f'eval{key}' for key in langs])

    def matrix_stop(self, bot):
        super().matrix_stop(bot)
        bot.remove_callback(self.message_cb)

    async def handle_file_event(self, bot, room, event, formats=[]):
        if not formats:
            formats = [self.default_output]
        self.logger.debug(f'RX file - MXC {event.url} - from {event.sender}')
        https_url = await self.bot.client.mxc_to_http(event.url)
        self.logger.debug(f'HTTPS URL {https_url}')
        filename = await download_file(https_url)
        self.logger.debug(f'RX filename {filename}')
        output = pandoc.convert_file(filename, try_format)

    # Credit: https://medium.com/swlh/how-to-boost-your-python-apps-using-httpx-and-asynchronous-calls-9cfe6f63d6ad
    async def download_file(url: str, filename: Optional[str] = None) -> str:
        filename = filename or url.split("/")[-1]
        filename = f"/tmp/{filename}"
        client = httpx.AsyncClient()
        async with client.stream("GET", url) as resp:
            resp.raise_for_status()
            async with aiofiles.open(filename, "wb") as f:
                async for data in resp.aiter_bytes():
                    if data:
                        await f.write(data)
        await client.aclose()
        return filename

    async def file_cb(self, room, event):
        """
        Calls handle_file_event with [default_output]
        """
        if self.bot.should_ignore_event(event):
            return
        try:
            mimetype = event.source['content']['info']['mimetype']
            if any([mimetype in format for format in self.input_formats]):
                return await self.handle_file_event(bot, room, event)
        except KeyError:
            return
        except Exception as e:
            self.logger.warning(f'got unexpected exception: {repr(e)}')

    async def message_cb(self, room, event):
        """
        Calls handle_file_event with args + [default_output]
        """
        if self.bot.should_ignore_event(event):
            return

        content = event.source.get('content')
        if not content:
            return

        # Don't re-run edited messages
        if "m.new_content" in content:
            return

        try:
            target_event = content['m.relates_to']['m.in_reply_to']
            for line in event.body.split('\n'):
                if line.startswith('!pandoc'):
                    break
            else:
                return
            try_outputs = line.split()[1:]
            target_event = self.get_event(target_event) # TODO
            return await handle_file_event(bot, room, target_event, outputs=try_outputs) # TODO
        except KeyError:
            return
        except Exception as e:
            # No formatted body
            self.logger.warning(f'unexpected exception in callback: {repr(e)}')

    async def matrix_message(self, bot, room, event):
        try:
            cmd, event.body = event.body.split(None, 1)      # [!cmd] [(!)subcmd body]
            if cmd in ['!' + self.name, self.name]:
                cmd, event.body = event.body.split(None, 1)  # [!subcmd] [body]
        except (ValueError, IndexError):
            # couldn't split, not enough arguments in body
            cmd = event.body.strip()
            event.body = ''
        cmd = cmd.lstrip('!')
        op = self.commands.get(cmd)
        if op:
            await op(bot, room, event, cmd)

    def help(self):
        return 'Convert a file with pandoc'

    def long_help(self, bot=None, event=None, **kwargs):
        text = self.help() + (
                '\n- !pandoc (list|ls|get|show): show the current settings'
                '\n- [m.file event]: if m.file has a mimetype matching [input_formats], convert to [default_output]'
                '\n- !pandoc ([formats ...]) (in reply to a file): convert a format in [formats], or the [default_output]'
                )
        if bot and event and bot.is_owner(event):
            text += ('\nBot owner commands:'
                     '\n- !pandoc set [prop] [value ...]'
                     )
        return text
