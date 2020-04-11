
import re
import traceback
import unicodedata
import logging

from enum import Enum
from typing import List
from datetime import datetime

import discord
from discord.ext import commands, tasks

from motor.motor_asyncio import AsyncIOMotorCollection
from pymongo import ReturnDocument

from .utils import cache, checks

log = logging.getLogger('Penelope')

banned = [
    "nig(?:ga|ger)",
    "fag",
    "tard",
    "jew",
    "^(?!sus)spic(?!y)",  # Matches `spic` but not `suspicious` or `spicy`
    "chink",
    "gay",
    "queer",
    "fudgel" # super secret test word
]

re_terms = re.compile("\w*(" + "|".join(banned) + ")\w*", re.MULTILINE | re.IGNORECASE)

log.debug(re_terms.pattern)

class NoChannelException(Exception):
    pass


class ModQueueConfig:
    __slots__ = ('_bot', 'enabled', 'queue_channel_id', 'log_channel_id')

    @classmethod
    def from_doc(cls, doc, bot):
        self = cls()

        self._bot: commands.Bot = bot

        modqueue = doc.get('modqueue', {})

        self.enabled = modqueue.get('enabled', False)
        self.queue_channel_id = modqueue.get('queue_channel_id', None)
        self.log_channel_id = modqueue.get('log_channel_id', None)

        return self

    def __repr__(self):
        return f'<{self.__class__.__name__} {self.enabled=}>'

    @property
    def queue_channel(self) -> discord.TextChannel:
        channel = self._bot.get_channel(self.queue_channel_id)
        if not channel:
            raise NoChannelException
        return channel

    @property
    def log_channel(self) -> discord.TextChannel:
        channel = self._bot.get_channel(self.log_channel_id)
        if not channel:
            raise NoChannelException
        return channel


class ModQueueItem(object):
    __slots__ = ('_bot', 'id', 'type', 'author_id', 'guild_id', 'message', 'matches', 'timestamp', 'action', 'mod_id', 'action_timestamp')

    @classmethod
    def from_doc(cls, doc, bot: commands.Bot):
        self = cls()
        self._bot = bot
        self.id = doc['id']
        self.type = ModQueueItem.Type(doc['type'])
        self.author_id = doc['author_id']
        self.guild_id = doc['guild_id']
        self.message = ModQueueItem.Message.from_doc(doc, bot)
        self.matches = doc['matches']
        self.timestamp = doc['timestamp']

        self.action = doc.get('action', None)
        self.mod_id = doc.get('mod_id', None)
        self.action_timestamp = doc.get('action_timestamp', None)

        return self

    @property
    def author(self) -> discord.User:
        return self._bot.get_user(self.author_id)

    @property
    def guild(self) -> discord.Guild:
        return self._bot.get_guild(self.guild_id)

    class Type(Enum):
        MESSAGE = 0
        NAME    = 1

    class Message:
        __slots__ = ('_bot', 'id', 'channel_id', 'clean_content')
        @classmethod
        def from_doc(cls, doc, bot: commands.Bot):
            if 'message' not in doc:
                return None

            message = doc['message']

            self = cls()
            self._bot = bot
            self.id = message['id']
            self.channel_id = message['channel_id']
            self.clean_content = message['clean_content']
            return self

        @property
        def channel(self):
            return self._bot.get_channel(self.channel_id)

        async def delete(self):
            m = await self.channel.fetch_message(self.id)
            await m.delete()


EMOJI_MAP = {
    0: 'HAMMER',
    1: 'HEAVY EXCLAMATION MARK SYMBOL',
    2: 'OK HAND SIGN'
}

COLOR_MAP = {
    0: 0xE53935, # RED
    1: 0xFFB300, # YELLOW
    2: 0x43A047  # GREEN
}

class Action(Enum):
    BAN    = 0
    STRIKE = 1
    IGNORE = 2

    @property
    def emoji(self):
        return unicodedata.lookup(EMOJI_MAP[self.value])

    @property
    def color(self):
        return COLOR_MAP[self.value]

    @classmethod
    def lookup(cls, emoji: discord.PartialEmoji):
        try:
            if emoji.is_custom_emoji():
                val = f'<:{emoji.name}:{emoji.id}>'
            else:
                val = unicodedata.name(emoji.name)
            # ugly but it works
            return cls(list(EMOJI_MAP.keys())[list(EMOJI_MAP.values()).index(val)])
        except ValueError:
            return None

class ModQueue(commands.Cog):
    """ModQueue for flagged words"""

    def __init__(self, bot):
        self.bot = bot
        self.collection: AsyncIOMotorCollection = self.bot.db.modqueue

    @cache.cache()
    async def get_config(self, guild_id) -> ModQueueConfig:
        doc = await self.bot.guild_config(guild_id)
        return ModQueueConfig.from_doc(doc, self.bot)

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


    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        if payload.guild_id is None:
            return

        action = Action.lookup(payload.emoji)
        if not action:
            return

        config = await self.get_config(payload.guild_id)
        if not config.enabled:
            return

        mod = self.bot.get_user(payload.user_id)
        if mod.bot:
            return

        doc = await self.collection.find_one({'id': payload.message_id})
        if not doc:
            return

        item = ModQueueItem.from_doc(doc, self.bot)

        try:
            if action is Action.BAN:
                await item.author.send(f'You have been banned from {item.guild.name} for the following message:\n> {item.message.clean_content}\n\nTo appeal this ban, please contact /r/AMD modmail: https://www.reddit.com/message/compose?to=/r/AMD')
                await item.guild.ban(item.author, reason = 'Use of "' + ', '.join(item.matches) + f'". Queue ID: {item.id}')

            elif action is Action.STRIKE:
                await item.author.send(f'You have been issued a strike in {item.guild.name} for the following message:\n> {item.message.clean_content}')

                await item.message.delete()

        except discord.NotFound:
            log.info(f'{self.__class__.__name__} Message not found, ignoring')
            pass

        except Exception as e:
            traceback.print_exc()
            await config.log_channel.send(f'Error handling action {action.name.lower()} on {item.author.name}, {e}')

        finally:
            await self.collection.find_one_and_update(
                {'id': item.id},
                {'$set': {
                    'action': action.value,
                    'mod_id': mod.id,
                    'action_timestamp': datetime.utcnow()
                }}
            )

            e = discord.Embed(color=action.color)
            e.description = ''
            e.description += f'{item.author.mention}\n'
            e.description += 'Detected words: ' + ' '.join(f'`{x}`' for x in item.matches) + '\n'
            e.description += f'**In message:**```{item.message.clean_content}```'

            e.timestamp = datetime.now()
            e.set_author(name=f'{item.author.name}#{item.author.discriminator}', icon_url=item.author.avatar_url)

            await config.log_channel.send(f'Action submitted: {action.name.lower()} by `{mod.name}#{mod.discriminator}`', embed=e)

            m = await config.queue_channel.fetch_message(item.id)
            await m.delete()


    @commands.Cog.listener()
    async def on_message(self, message):
        if message.guild is None:
            return

        if message.author.bot:
            return

        config = await self.get_config(message.guild.id)
        if not config.enabled:
            return

        matches = re_terms.findall(message.clean_content.strip())

        if not matches:
            return

        e = discord.Embed(color=0xF44336)
        e.description = ''
        e.description += f'{message.author.mention} [Jump to message](https://discordapp.com/channels/{message.guild.id}/{message.channel.id}/{message.id})\n'
        e.description += 'Detected words: ' + ' '.join(f'`{x}`' for x in matches) + '\n'
        e.description += f'**In message:**```{message.clean_content}```'

        strikes: List[ModQueueItem] = []
        async for doc in self.collection.find({"guild_id": message.guild.id, "author_id": message.author.id, "action": Action.STRIKE.value}):
            strikes.append(ModQueueItem.from_doc(doc, self.bot))

        if strikes:
            e.description += f'\n**Previous Strikes ({len(strikes)})**\n'
            for i, strike in enumerate(strikes):
                e.description += f'{i+1}. ' + ' '.join(f'`{x}`' for x in strike.matches) + f' {strike.action_timestamp.strftime("%b %d %Y")}\n'

        e.timestamp = datetime.now()
        e.set_author(name=f'{message.author.name}#{message.author.discriminator}', icon_url=message.author.avatar_url)

        msg = await config.queue_channel.send("Naughty words detected", embed=e)

        for action in [Action.BAN, Action.STRIKE, Action.IGNORE]:
            await msg.add_reaction(action.emoji)

        await self.collection.insert_one({
            "id": msg.id,
            "type": ModQueueItem.Type.MESSAGE.value,
            "author_id": message.author.id,
            "guild_id": message.guild.id,
            "message": {
                "id": message.id,
                "channel_id": message.channel.id,
                "clean_content": message.clean_content
            },
            "matches": matches,
            "timestamp": datetime.utcnow()
        })

    @commands.Cog.listener()
    async def on_member_join(self, member):
        await self.check_member_identitity(member)

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        if before.nick == after.nick:
            return

        await self.check_member_identitity(after)

    async def check_member_identitity(self, member: discord.Member):
        config = await self.get_config(member.guild.id)
        if not config.enabled:
            return

        for text in [member.name, member.nick]:
            if not text:
                continue

            matches = re_terms.findall(text)

            if matches:
                e = discord.Embed(color=0xF44336)
                e.set_author(name=f'{member.name}#{member.discriminator}', icon_url=member.avatar_url)
                e.description = f'{member.mention}\n'
                e.description += f'`{"``".join(matches)}`\n'
                e.description += f'- Username: {member.name}#{member.discriminator}\n'
                e.description += f'- Nickname: {member.nick}\n'
                e.set_footer(text=f'User ID: {member.id}')
                e.timestamp = datetime.now()

                msg = await config.queue_channel.send(f'Naughty user', embed=e)

                break

    ############
    # COMMANDS #
    ############

    async def update_config(self, guild_id, data):
        doc = await self.bot.db.guild_config.find_one_and_update(
            {"id": guild_id},
            {"$set": data},
            upsert = True,
            return_document = ReturnDocument.AFTER
        )
        self.get_config.invalidate(self, guild_id)
        return ModQueueConfig.from_doc(doc, self.bot)


    @commands.group(aliases=['mq'])
    @commands.guild_only()
    @checks.is_mod()
    async def modqueue(self, ctx):
        pass

    @modqueue.group(aliases=['c'], invoke_without_command=True)
    async def config(self, ctx):
        # quick n dirty
        config = await self.get_config(ctx.guild.id)
        e = discord.Embed(color=0xD81B60)
        e.description = '```\n'

        for attr in dir(config):
            try:
                if attr.startswith('_'):
                    continue

                val = config.__getattribute__(attr)
                if callable(val):
                    continue

                e.description += f'{attr} -> {val}\n'

            except:
                pass

        e.description += '```'
        await ctx.send(embed=e)

    @config.command()
    async def toggle(self, ctx):
        config = await self.get_config(ctx.guild.id)
        config = await self.update_config({"modqueue.enabled": not config.enabled})
        await ctx.send(f'ModQueue -> {config.enabled=}')

    @config.command()
    async def queue(self, ctx, channel: discord.TextChannel):
        config = await self.update_config(ctx.guild.id, {"modqueue.queue_channel_id": channel.id})
        await ctx.send(f'ModQueue -> {config.queue_channel_id=} {config.queue_channel.mention}')

    @config.command()
    async def log(self, ctx, channel: discord.TextChannel):
        config = await self.update_config(ctx.guild.id, {"modqueue.log_channel_id": channel.id})
        await ctx.send(f'ModQueue -> {config.log_channel_id=} {config.log_channel.mention}')


def setup(bot):
    bot.add_cog(ModQueue(bot))