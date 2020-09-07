import re
import json

from io import BytesIO
from typing import Optional

import discord
from discord.ext import commands

from .utils.checks import is_admin

from urllib.parse import urlparse, parse_qs
from base64 import urlsafe_b64decode, urlsafe_b64encode

DISCOHOOK_BASE = 'https://discohook.org'

class Embeds(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

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

    def build(self, j: str) -> discord.Embed:
        if j.startswith(DISCOHOOK_BASE):
            b64 = parse_qs(urlparse(j).query).get('message')[0] + '===' # Python doesn't care about extra padding
            j = urlsafe_b64decode(b64).decode('utf-8')

            data = json.loads(j)['message']

        else:
            data = json.loads(j)

        return discord.Embed.from_dict(data['embeds'][0])

    @commands.group(name='embeds', aliases=['e'], hidden=True)
    @is_admin()
    async def embeds(self, ctx):
        """Create and edit embeds

        Uses https://discohook.org for ease of viewing and editing embeds
        """
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @embeds.command()
    async def create(self, ctx, channel: Optional[discord.TextChannel], *, source: Optional[str]):
        """Create an embed from a discohook url or raw json"""
        if not channel:
            channel = ctx

        if not source and ctx.message.attachments:
            source = await ctx.message.attachments[0].read()

        await channel.send(embed=self.build(source))
        await ctx.send("\N{OK HAND SIGN}")

    @embeds.command()
    async def dump(self, ctx, channel: Optional[discord.TextChannel], message_id: int, return_json: Optional[bool] = False):
        """Get the source json data for an embed, returns a discohook url by default"""
        if not channel:
            channel = ctx

        message = await channel.fetch_message(message_id)

        embeds = []
        for embed in message.embeds:
            embeds.append(embed.to_dict())

        j = json.dumps({"message": {"embeds": embeds}})
        b64 = urlsafe_b64encode(j.encode('utf-8')).decode('utf-8')

        url = f'{DISCOHOOK_BASE}/?message={b64}'

        if len(url) > 2000 or return_json:
            fp = BytesIO(bytes(j, encoding='utf-8'))
            await ctx.send(file=discord.File(fp, filename='embed.json'))
            return

        await ctx.send(f'<{url}>')

    @embeds.command()
    async def edit(self, ctx, channel: Optional[discord.TextChannel], message_id: int, *, source: Optional[str]):
        """Edit an embed"""
        if not channel:
            channel = ctx

        if not source and ctx.message.attachments:
            source = await ctx.message.attachments[0].read()

        message = await channel.fetch_message(message_id)
        await message.edit(embed=self.build(source))
        await ctx.send("\N{OK HAND SIGN}")


def setup(bot):
    bot.add_cog(Embeds(bot))
