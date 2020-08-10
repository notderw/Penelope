import os
import re
import typing
import random
import unicodedata

from datetime import datetime
from typing import List, Dict, NoReturn

import discord
from discord.ext import commands, tasks

from mcstatus import MinecraftServer

from .utils import cache
from .utils.config import CogConfig


GUILD_ID = 216389071457615872

class MinecraftConfig(CogConfig):
    name = 'minecraft'

    enabled: bool = False
    message: discord.Message
    servers: List = []

    class Server:
        __slots__ = ('name', 'ip', 'port')

        def __init__(self, doc):
            print(doc)
            self.name = doc["name"]
            self.ip = doc["ip"]
            self.port = doc["port"]

    def from_doc(self, doc: Dict) -> NoReturn:
        super().from_doc(doc)

        self.servers: List[MinecraftConfig.Server] = [self.Server(s) for s in self.servers]

    @property
    def check(self):
        return self.enabled \
            and self.message_id is not None


class Dew(commands.Cog):
    """thiccc bot for dew's server"""

    def __init__(self, bot):
        self.bot = bot

        self.minecraft.start()

    def cog_unload(self):
        self.minecraft.cancel()

    def cog_check(self, ctx):
        return ctx.guild and ctx.guild.id == GUILD_ID

    @cache.cache()
    async def minecraft_config(self) -> MinecraftConfig:
        return await MinecraftConfig.from_db(GUILD_ID, self.bot)

    @tasks.loop(minutes=10)
    async def minecraft(self):
        config = await self.minecraft_config()
        if not config.check:
            return False

        e = discord.Embed(color=0x4CAF50)
        e.title = "Minecraft Status"
        e.description = ""

        members_lower = {m.name.lower(): m.id for m in self.bot.get_guild(GUILD_ID).members}

        any_online = False
        for s in config.servers:
            server = MinecraftServer(s.ip, int(s.port))

            e.description += f'__**{s.name}**__'

            try:
                status = await server.status()

                any_online = True
                motd = re.sub(r'§\w', '', status.description.get('text'))
                e.description += f' *v{status.version.name}* '
                e.description += f' *({status.latency:.1f}ms)*'

                if status.modinfo:
                    e.description += f' `{status.modinfo.type}, {len(status.modinfo.list)} mods`'

                e.description += '\n'
                e.description += f'```{motd}```'
                e.description += f'{status.players.online} / {status.players.max} players online:\n'

                if status.players.sample:
                    for p in status.players.sample:
                        if p.name.lower() in members_lower.keys():
                            e.description += f'> <@{members_lower[p.name.lower()]}>'

                        else:
                            e.description += f'> {p.name}'

                        e.description += '\n'

            except (TimeoutError, ConnectionRefusedError):
                e.description += f' *(Offline)*\n'

            except Exception:
                import traceback
                traceback.print_exc()

            e.description += '\n'

        e.description.strip()
        e.timestamp = datetime.utcnow()

        if not any_online:
            e.color = 0xF44336

        message: discord.Message = await config.message
        await message.edit(content="", embed=e)


    async def cog_command_error(self, ctx, error):
        if isinstance(error, commands.BadArgument):
            await ctx.send(error)
        elif isinstance(error, commands.CommandInvokeError):
            original = error.original
            if isinstance(original, discord.Forbidden):
                await ctx.send('I do not have permission to execute this action.')
            elif isinstance(original, discord.NotFound):
                await ctx.send(f'This entity does not exist: {original.text}')
            elif isinstance(original, discord.HTTPException):
                await ctx.send('Somehow, an unexpected error occurred. Try again later?')
            else:
                await ctx.send(f'```{error}```')

    @commands.command()
    async def girl(self, ctx):
        subreddits = ['PrettyGirls', 'gentlemanboners', 'cutegirlgifs', 'BeautifulFemales', 'Faces']
        subreddit = self.reddit.subreddit(random.choice(subreddits))
        posts = list(subreddit.top('week'))
        while True:
            post = random.choice(posts)
            if not post.is_self:
                print(post.shortlink)
                await ctx.send(post.url)
                break

    # ha gay
    @commands.command()
    async def man(self, ctx):
        subreddits = ['HotGuys', 'malehairadvice']
        subreddit = self.reddit.subreddit(random.choice(subreddits))
        posts = list(subreddit.top('week'))
        while True:
            post = random.choice(posts)
            if not post.is_self:
                print(post.shortlink)
                await ctx.send(post.url)
                break

    @commands.command()
    async def react(self, ctx, message: typing.Optional[discord.Message], *text: str):
        if not message:
            message = ctx.message

        mappings = {

        }
        for section in text:
            search = discord.utils.find(lambda m: m.name == section, self.bot.emojis)
            # if we have a custom mapping use that
            if section in mappings:
                await message.add_reaction(mappings[section])

            # if this is the name of an emoji use that
            elif search:
                await message.add_reaction(search)

            else:
                for char in section:
                    try: # try to find the character as a letter
                        unicode = unicodedata.lookup(f'REGIONAL INDICATOR SYMBOL LETTER {char.upper()}')
                        await message.add_reaction(unicode)
                    except KeyError:
                        await message.add_reaction(char)


def setup(bot):
    bot.add_cog(Dew(bot))
