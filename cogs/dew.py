import typing
import random
import unicodedata

import discord
from discord.ext import commands


GUILD_ID = 216389071457615872


class Dew(commands.Cog):
    """thiccc bot for dew's server"""

    def __init__(self, bot):
        self.bot = bot

    def cog_check(self, ctx):
        return ctx.guild and ctx.guild.id == GUILD_ID

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
