import random

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
        e.set_author(name=f'{ctx.author.nick}', icon_url=ctx.author.avatar_url)

        await ctx.send(embed=e)


def setup(bot):
    bot.add_cog(Meme(bot))
