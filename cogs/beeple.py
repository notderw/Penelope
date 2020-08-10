import os
import re
import discord
import unicodedata
from discord.ext import commands, tasks

import praw
from peony import PeonyClient

from typing import List

from .utils.logging import CogLogger

# TWITTER
TWITTER_CONSUMER_TOKEN = os.environ.get("TWITTER_CONSUMER_TOKEN")
TWITTER_CONSUMER_SECRET = os.environ.get("TWITTER_CONSUMER_SECRET")
TWITTER_ACCESS_TOKEN = os.environ.get("TWITTER_ACCESS_TOKEN")
TWITTER_ACCESS_TOKEN_SECRET = os.environ.get("TWITTER_ACCESS_TOKEN_SECRET")

GUILD = 216389071457615872
CHANNEL = 681312561576411183

REACTIONS = ['WHITE HEAVY CHECK MARK', 'CROSS MARK']

re_tags = re.compile("everyday(s)?", re.IGNORECASE)
re_hashtag = re.compile("#\w+")
re_title = re.compile("([A-Z]{1,}[\s\W]\s?)")

class BeepleObject(object):
    def __init__(self, tweet):
        self.id = None
        self.title = re_hashtag.sub("", tweet.text[:-23])
        self.url = tweet.entities['media'][0]['media_url_https'] + "?name=orig"

        self.log = CogLogger('Penelope', self)

    async def submit(self, subreddit: praw.models.Subreddits) -> None:
        submission = subreddit.submit(self.title, url=self.url, flair_id='8c1b7e86-e96b-11e8-852f-0e6f8368cab6', resubmit=False)
        submission.mod.approve()
        self.log.info(f'Submitted {self.title} {submission.shortlink}')

    async def queue(self, channel: discord.abc.Messageable) -> None:
        m = await channel.send(embed=self.embed)
        for r in REACTIONS:
            await m.add_reaction(unicodedata.lookup(r))

        self.id = m.id

    @property
    def embed(self) -> discord.Embed:
        e = discord.Embed()
        e.color = 0x673AB7
        e.description = self.title
        e.set_image(url=self.url)
        return e


class Beeple(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

        self.queue : List[BeepleObject] = []

        self.reddit = praw.Reddit('RenegadeAI', user_agent='Penelope Discord bot by /u/RenegadeAI')
        self.subreddit = self.reddit.subreddit('beeple')

        self.twitter = PeonyClient(consumer_key=TWITTER_CONSUMER_TOKEN,
                                    consumer_secret=TWITTER_CONSUMER_SECRET,
                                    access_token=TWITTER_ACCESS_TOKEN,
                                    access_token_secret=TWITTER_ACCESS_TOKEN_SECRET)

        self.monitor.start()

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

    def cog_unload(self):
        self.monitor.cancel()

    @property
    def channel(self) -> discord.abc.Messageable:
        return self.bot.get_channel(CHANNEL)

    @tasks.loop(minutes=10)
    async def monitor(self):
        tweets = await self.twitter.api.statuses.user_timeline.get(screen_name = 'beeple', count = 5, exclude_replies = True, include_rts = False, trim_user = True, since_id = self.last_post)
        for tweet in reversed(tweets):
            if not 'media' in tweet.entities:
                continue

            obj = BeepleObject(tweet)

            self.last_post = tweet["id"]

            if list(filter(re_tags.match, [ht['text'] for ht in tweet.entities['hashtags']])):
                obj.title = ''.join(re.findall(re_title, obj.title)).strip()

                await obj.submit(self.subreddit)
                await self.bot.redis.set("beeple_last", self.last_post)
                break

            else:
                await obj.queue(self.channel)
                self.queue.append(obj)

    @monitor.before_loop
    async def before_monitor(self):
        await self.bot.wait_until_ready()
        self.last_post = await self.bot.redis.get("beeple_last")

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        if payload.user_id == self.bot.user.id:
            return

        if payload.guild_id is None:
            return

        if payload.guild_id != GUILD:
            return

        if payload.channel_id != CHANNEL:
            return


        reaction = unicodedata.name(payload.emoji.name)
        items = list(filter(lambda x: x.id == payload.message_id, self.queue))
        message: discord.Message = await self.channel.fetch_message(payload.message_id)

        if not items:
            if reaction in REACTIONS:
                await message.delete()

            return

        obj: BeepleObject = items[0]

        if reaction == 'WHITE HEAVY CHECK MARK':
            try:
                await obj.submit(self.subreddit)
                await message.clear_reactions()
                await message.add_reaction('\N{OK HAND SIGN}')

            except Exception as e:
                import traceback
                traceback.print_exc()
                await self.channel.send(e)
                await message.clear_reactions()
                await message.add_reaction('\N{BLACK QUESTION MARK ORNAMENT}')
                return

        if reaction == 'CROSS MARK':
            await message.delete()

        await self.bot.redis.set("beeple_last", self.last_post)


def setup(bot):
    bot.add_cog(Beeple(bot))
