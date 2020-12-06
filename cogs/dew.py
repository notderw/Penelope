import os
import random
import unicodedata

from typing import Optional, Text
from datetime import datetime

import discord
from discord.ext import commands, tasks

from aiogoogle import Aiogoogle
from pydantic import BaseModel

from .utils import cache
from .utils.logging import CogLogger
from .utils.config import CogConfig


GUILD_ID = 216389071457615872

GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET")
GOOGLE_REFRESH_TOKEN = os.environ.get("GOOGLE_REFRESH_TOKEN")


class DewConfig(CogConfig):
    name = 'dew'

    videos_channel: discord.TextChannel

    @property
    def check(self):
        return False

class YoutubeChannel(BaseModel):
    id: str
    title: str

class YoutubeVideo(BaseModel):
    id: str

class Dew(commands.Cog):
    """thiccc bot for dew's server"""

    def __init__(self, bot):
        self.bot = bot

        self.log = CogLogger('Penelope', self)

        self.init_yt()

    def cog_unload(self):
        self.youtube.cancel()

    async def cog_check(self, ctx):
        return (await self.bot.is_owner(ctx.author)) or (ctx.guild and ctx.guild.id == GUILD_ID)

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

    @property
    def guild(self):
        return self.bot.get_guild(GUILD_ID)

    @commands.group(aliases=['d'], invoke_without_command=True)
    @commands.guild_only()
    @commands.is_owner()
    async def dew(self, ctx):
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    #####################################################################################
    #
    #     YOUTUBE
    #
    #####################################################################################

    def init_yt(self):
        self.google = Aiogoogle(
            client_creds={
                'client_id': GOOGLE_CLIENT_ID,
                'client_secret': GOOGLE_CLIENT_SECRET
            },
            user_creds={
                'access_token': '',
                'refresh_token': GOOGLE_REFRESH_TOKEN,
                'expires_at': "1970-01-01T00:00:00" # shit won't auto refresh the token if this isn't here
            }
        )

        self.youtube.start()

    async def api(self):
        return await self.google.discover('youtube', 'v3')

    async def fetch_subscriptions(self):
        self.log.debug('YouTube - fetched subscriptions')
        yt = await self.api()
        data = await self.google.as_user(
            yt.subscriptions.list(mine=True, part='snippet', maxResults=50),
        )

        channels = [YoutubeChannel(id=c["snippet"]["resourceId"]["channelId"], title=c["snippet"]["title"]) for c in data['items']]

        await self.bot.redis.hmset_dict('youtube_subscriptions', {c.id: c.title for c in channels})

        return channels

    async def get_channels(self):
        data = await self.bot.redis.hgetall('youtube_subscriptions')

        if not data:
            return await self.fetch_subscriptions()

        return [YoutubeChannel(id=k, title=v) for k, v in data.items()]

    async def get_videos(self, channel: YoutubeChannel):
        after = (await self.bot.redis.get('youtube_after')) or f'{datetime.utcnow().isoformat()}Z'
        yt = await self.api()
        data = await self.google.as_user(
            yt.activities.list(channelId=channel.id, part='contentDetails', maxResults=15, publishedAfter=after),
        )

        for item in data["items"]:
            if not "upload" in item["contentDetails"]:
                continue

            yield YoutubeVideo(id=item["contentDetails"]["upload"]["videoId"])


    @tasks.loop(minutes=20)
    async def youtube(self):
        self.log.debug('YouTube - checking for new videos')

        # this is annoying
        self.google.user_creds = {**self.google.user_creds, 'refresh_token': GOOGLE_REFRESH_TOKEN}

        config = await self.get_config(GUILD_ID)

        for channel in await self.get_channels():
            async for video in self.get_videos(channel):
                self.log.debug(f'YouTube - new video {video.id}')
                await config.videos_channel.send(f'https://youtu.be/{video.id}')

        await self.bot.redis.set('youtube_after', f'{datetime.utcnow().isoformat()}Z')

    @youtube.before_loop
    async def before_youtube(self):
        await self.bot.wait_until_ready()

    @youtube.after_loop
    async def after_youtube(self):
        if self.youtube.is_being_cancelled():
            await self.google.__aexit__(None, None, None)

    @dew.group(name='youtube', aliases=['yt'])
    async def yt(self, ctx):
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)


    @yt.command()
    async def sync(self, ctx):
        e = discord.Embed(description='')

        for c in await self.fetch_subscriptions():
            e.description += f'[{c.title}](https://youtube.com/channel/{c.id})\n'

        await ctx.send(embed=e)

    #####################################################################################
    #
    #     CONFIG
    #
    #####################################################################################

    @cache.cache()
    async def get_config(self, guild_id) -> DewConfig:
        return await DewConfig.from_db(guild_id, self.bot)

    @dew.command(aliases=['c'])
    async def config(self, ctx, param: Optional[Text], arg: Optional[Text]):
        config = await self.get_config(ctx.guild.id)
        await config.handle_command(ctx, param, arg)

    #####################################################################################
    #
    #     MISC
    #
    #####################################################################################

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
    async def react(self, ctx, message: Optional[discord.Message], *text: str):
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
