import random

from urllib.parse import quote_plus

import discord
from discord.ext import commands

class Meme(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(aliases=['s'])
    async def sarcasm(self, ctx, *, text: str):
        result = ""
        for char in text:
            if random.choice([0, 1]) < 1:
                result += char.lower()
            else:
                result += char.upper()

        e = discord.Embed(color = ctx.author.color)
        e.description = f'> {result}'
        e.set_author(name=f'{ctx.author.nick or ctx.author.name}', icon_url=ctx.author.avatar_url)

        await ctx.send(embed=e)

    @commands.command()
    async def lmgtfy(self, ctx, *, q):
        await ctx.send(f'<https://lmgtfy.com/?q={quote_plus(q)}&s=d>')


def setup(bot):
    bot.add_cog(Meme(bot))
