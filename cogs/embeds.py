import re
import json

from io import BytesIO
from typing import Optional

import discord
from discord.ext import commands


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

    def build(self, j) -> discord.Embed:
        data = json.loads(j)
        return discord.Embed.from_dict(data)

    @commands.group(name='embeds', aliases=['e'], hidden=True)
    @commands.is_owner()
    async def embeds(self, ctx):
        pass

    @embeds.command()
    async def create(self, ctx, messageable: Optional[discord.TextChannel], *, j: Optional[str]):
        if not messageable:
            messageable = ctx

        if not j and ctx.message.attachments:
            j = await ctx.message.attachments[0].read()

        await messageable.send(embed=self.build(j))
        await ctx.send("\N{OK HAND SIGN}")

    @embeds.command()
    async def dump(self, ctx, messageable: Optional[discord.TextChannel], message_id: int):
        if not messageable:
            messageable = ctx

        message = await messageable.fetch_message(message_id)

        embeds = []
        for embed in message.embeds:
            embeds.append(embed.to_dict())

        j = json.dumps({"embeds": embeds})

        if len(j) > 2000:
            fp = BytesIO(bytes(j, encoding='utf-8'))
            await ctx.send(file=discord.File(fp, filename='embed.json'))
            return

        await ctx.send(f'```{j}```')

    @embeds.command()
    async def edit(self, ctx, messageable: Optional[discord.TextChannel], message_id: int, *, j: Optional[str]):
        if not messageable:
            messageable = ctx

        if not j and ctx.message.attachments:
            j = await ctx.message.attachments[0].read()

        message = await messageable.fetch_message(message_id)
        await message.edit(embed=self.build(j))
        await ctx.send("\N{OK HAND SIGN}")


def setup(bot):
    bot.add_cog(Embeds(bot))
