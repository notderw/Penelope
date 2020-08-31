import os
import traceback

import discord
from discord.ext import commands

from watchgod import awatch

from .utils.logging import CogLogger

class Development(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.log = CogLogger('Penelope', self)

        self.bot.cogs["Meta"].update_presence.cancel()

        self._task = bot.loop.create_task(self.reload_cogs_on_change())

    def cog_unload(self):
        self._task.cancel()

    async def cog_check(self, ctx):
        return await self.bot.is_owner(ctx.author)

    async def reload_cogs_on_change(self):
        try:
            await self.bot.wait_until_ready()
            await self.bot.change_presence(status=discord.Status.dnd, activity=discord.Activity(type=discord.ActivityType.watching, name="for changes [dev]"))

            async for changes in awatch('cogs'):
                for change in changes:
                    file = change[1]
                    if len(file.split('/')) == 2:
                        module = os.path.splitext(file)[0].replace('/', '.')
                        self.log.info(f'Module {module} changed')
                        try:
                            self.bot.reload_extension(module)

                        except commands.ExtensionNotLoaded:
                            pass

                        except commands.ExtensionError as e:
                            await self.bot.stats_webhook.send(f'{e.__class__.__name__}: {e}')
                            traceback.print_exc()

                        else:
                            await self.bot.change_presence(status=discord.Status.online, activity=discord.Activity(type=discord.ActivityType.playing, name=f"reloaded {module} [dev]"))

        except Exception as e:
            self.log.error(e)
            traceback.print_exc()


def setup(bot):
    bot.add_cog(Development(bot))
