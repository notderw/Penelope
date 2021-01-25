import os, sys
import asyncio
import traceback
import time
import datetime
import logging
import json
import aiohttp

from collections import Counter, deque

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo.errors import ServerSelectionTimeoutError
import aioredis

import discord
from discord.ext import commands
from cogs.utils import context

from derw import makeLogger

# DISCORD
TOKEN = os.environ.get("TOKEN")
CLIENT_ID = os.environ.get("CLIENT_ID")

# REDIS
REDIS_URI = os.environ.get("REDIS_URI")

# DATABASE
MONGO_URI = os.environ.get("MONGO_URI")

# STATS
STATS_ID = os.environ.get("STATS_ID")
STATS_TOKEN = os.environ.get("STATS_TOKEN")

# DEVELOPMENT
DEVELOPMENT = os.environ.get("DEVELOPMENT")

log = makeLogger('Penelope')
log.setLevel(logging.INFO)

os.environ['TZ'] = 'UTC'
time.tzset()

description = """
Hello human.
"""

initial_extensions = (
    'cogs.meta',
    'cogs.admin',
    'cogs.mod',
    'cogs.reddiscord',
    'cogs.meme',
    'cogs.log',
    'cogs.dm',
    'cogs.modqueue',
    'cogs.dew',
    'cogs.beeple',
    'cogs.minecraft',
    'cogs.embeds'
)

if DEVELOPMENT:
    log.setLevel(logging.DEBUG)
    initial_extensions = initial_extensions + ('cogs.development',)

async def _prefix_callable(bot, msg):
    user_id = bot.user.id
    base = [f'<@!{user_id}> ', f'<@{user_id}> ']
    if msg.guild is None:
        base.append('!')
        base.append('?')
    else:
        if await bot.redis.hexists("penelope_prefixes", msg.guild.id):
            try:
                prefixes = json.loads(await bot.redis.hget("penelope_prefixes", msg.guild.id))
            except ValueError:
                prefixes = []
        else:
            prefixes = []

        base.extend(prefixes)
    return base

class Penelope(commands.AutoShardedBot):
    def __init__(self):
        super().__init__(command_prefix=_prefix_callable, description=description,
                         pm_help=None, help_attrs=dict(hidden=True), fetch_offline_members=False,
                         intents=discord.Intents.all())

        self.client_id = CLIENT_ID
        self.development = DEVELOPMENT

        self._prev_events = deque(maxlen=10)

        # in case of even further spam, add a cooldown mapping
        # for people who excessively spam commands
        self.spam_control = commands.CooldownMapping.from_cooldown(10, 12, commands.BucketType.user)

        # A counter to auto-ban frequent spammers
        # Triggering the rate limit 5 times in a row will auto-ban the user from the bot.
        self._auto_spam_count = Counter()

    def load_initial_extensions(self):
        for extension in initial_extensions:
            try:
                self.load_extension(extension)
            except Exception as e:
                log.error(f'{self.__class__.__name__} - Failed to load extension {extension}.')
                traceback.print_exc()

    async def on_socket_response(self, msg):
        self._prev_events.append(msg)

    async def on_command_error(self, ctx, error):
        if isinstance(error, commands.NoPrivateMessage):
            await ctx.author.send('This command cannot be used in private messages.')
        elif isinstance(error, commands.DisabledCommand):
            await ctx.author.send('Sorry. This command is disabled and cannot be used.')
        elif isinstance(error, commands.CommandInvokeError):
            original = error.original
            if not isinstance(original, discord.HTTPException):
                print(f'In {ctx.command.qualified_name}:', file=sys.stderr)
                traceback.print_tb(original.__traceback__)
                print(f'{original.__class__.__name__}: {original}', file=sys.stderr)
        elif isinstance(error, commands.ArgumentParsingError):
            await ctx.send(error)

    def get_guild_prefixes(self, guild, *, local_inject=_prefix_callable):
        proxy_msg = discord.Object(id=None)
        proxy_msg.guild = guild
        return local_inject(self, proxy_msg)

    async def get_raw_guild_prefixes(self, guild_id):
        if await self.redis.hexists("penelope_prefixes", guild_id):
            try:
                return json.loads(await self.redis.hget("penelope_prefixes", guild_id))
            except ValueError:
                return []
        else:
            return []

    async def set_guild_prefixes(self, guild, prefixes):
        if len(prefixes) == 0:
            await self.redis.hmset("penelope_prefixes", guild.id, "")
        elif len(prefixes) > 10:
            raise RuntimeError('Cannot have more than 10 custom prefixes.')
        else:
            await self.redis.hmset("penelope_prefixes", guild.id, json.dumps(prefixes))

    async def add_to_blacklist(self, object_id):
        await self.redis.sadd("penelope_blacklist", object_id)

    async def remove_from_blacklist(self, object_id):
        await self.redis.srem("penelope_blacklist", object_id)

    async def on_ready(self):
        if not hasattr(self, 'uptime'):
            self.uptime = datetime.datetime.utcnow()

            log.info(f'{self.__class__.__name__} - Ready: {self.user} (ID: {self.user.id})')

        if self.development:
            log.info(f'{self.__class__.__name__} - Development mode enabled')

    @property
    def stats_webhook(self):
        hook = discord.Webhook.partial(id=STATS_ID, token=STATS_TOKEN, adapter=discord.AsyncWebhookAdapter(self.session))
        return hook

    def log_spammer(self, ctx, message, retry_after, *, autoblock=False):
        guild_name = getattr(ctx.guild, 'name', 'No Guild (DMs)')
        guild_id = getattr(ctx.guild, 'id', None)
        fmt = 'User %s (ID %s) in guild %r (ID %s) spamming, retry_after: %.2fs'
        log.warning(fmt, message.author, message.author.id, guild_name, guild_id, retry_after)
        if not autoblock:
            return

        wh = self.stats_webhook
        embed = discord.Embed(title='Auto-blocked Member', colour=0xDDA453)
        embed.add_field(name='Member', value=f'{message.author} (ID: {message.author.id})', inline=False)
        embed.add_field(name='Guild Info', value=f'{guild_name} (ID: {guild_id})', inline=False)
        embed.add_field(name='Channel Info', value=f'{message.channel} (ID: {message.channel.id}', inline=False)
        embed.timestamp = datetime.datetime.utcnow()
        return wh.send(embed=embed)

    async def process_commands(self, message):
        ctx = await self.get_context(message, cls=context.Context)

        if ctx.command is None:
            return

        blacklist = await self.redis.smembers("penelope_blacklist")

        if ctx.author.id in blacklist:
            return

        if ctx.guild is not None and ctx.guild.id in blacklist:
            return

        bucket = self.spam_control.get_bucket(message)
        retry_after = bucket.update_rate_limit()
        author_id = message.author.id
        if retry_after and author_id != self.owner_id:
            self._auto_spam_count[author_id] += 1
            if self._auto_spam_count[author_id] >= 5:
                await self.add_to_blacklist(author_id)
                del self._auto_spam_count[author_id]
                await self.log_spammer(ctx, message, retry_after, autoblock=True)
            else:
                self.log_spammer(ctx, message, retry_after)
            return
        else:
            self._auto_spam_count.pop(author_id, None)

        await self.invoke(ctx)

    async def on_message(self, message):
        if message.author.bot:
            return
        await self.process_commands(message)

    async def on_guild_join(self, guild):
        if guild.id in await self.redis.smembers("penelope_blacklist"):
            await guild.leave()

    async def guild_config(self, guild_id) -> dict:
        doc = await self.db.guild_config.find_one({"id": guild_id})
        return doc or {}

    async def close(self):
        await super().close()
        await self.session.close()
        self.mongo.close()
        self.redis.close()
        await self.redis.wait_closed()

    async def init_http(self):
        self.session = aiohttp.ClientSession()

    async def init_mongo(self):
        self.mongo = AsyncIOMotorClient(MONGO_URI)
        # motor doesnt attempt a connection until you try to do something
        await self.mongo.admin.command("ismaster")
        # Default bot database
        self.db: AsyncIOMotorDatabase = self.mongo.penelope
        log.info(f'{self.__class__.__name__} - Connected to mongo')

    async def init_redis(self):
        self.redis = await aioredis.create_redis_pool(REDIS_URI)
        log.info(f'{self.__class__.__name__} - Connected to redis')

    def run(self):
        try:
            super().run(TOKEN, reconnect=True)
        finally:
            with open('prev_events.log', 'w', encoding='utf-8') as fp:
                for data in self._prev_events:
                    try:
                        x = json.dumps(data, ensure_ascii=True, indent=4)
                    except:
                        fp.write(f'{data}\n')
                    else:
                        fp.write(f'{x}\n')

def run():
    bot = Penelope()

    loop = asyncio.get_event_loop()

    loop.run_until_complete(bot.init_http())

    try:
        loop.run_until_complete(bot.init_mongo())
    except ServerSelectionTimeoutError:
        log.exception("Could not connect to mongo, timed out\nExiting.")
        return

    try:
        loop.run_until_complete(bot.init_redis())
    except TimeoutError:
        log.exception("Could not connect to redis, timed out\nExiting.")
        return

    bot.load_initial_extensions()
    bot.run()

if __name__ == "__main__":
    run()
