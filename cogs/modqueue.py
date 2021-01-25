import re
import traceback
import unicodedata

from enum import Enum
from typing import List, Optional, Text, Union
from datetime import datetime, timedelta
from asyncio import sleep

import discord
from discord.ext import commands, tasks

from motor.motor_asyncio import AsyncIOMotorCollection
from pymongo import ReturnDocument

from .utils import cache, checks
from .utils.config import CogConfig
from .utils.logging import CogLogger

banned = [
    "nig(?:ga|ger)",
    "fag",
    "(?<!bas)tard",
    "jew",
    "(?<!su)spic(?!y)",  # Matches `spic` but not `suspicious` or `spicy`
    "chink",
    "gay",
    "queer",
    "fudgel" # super secret test word
]

RE_TERMS = re.compile("(\w*(" + "|".join(banned) + ")\w*)", re.MULTILINE | re.IGNORECASE)


class ModQueueConfig(CogConfig):
    name = 'modqueue'

    enabled: bool = False
    queue_channel: discord.TextChannel
    log_channel: discord.TextChannel

    @property
    def check(self):
        return self.enabled \
            and self.log_channel is not None \
            and self.queue_channel is not None


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
                val = unicodedata.name(emoji.name[0])
            # ugly but it works
            return cls(list(EMOJI_MAP.keys())[list(EMOJI_MAP.values()).index(val)])
        except ValueError:
            return None
        except TypeError:
            print(f'ModQueue:Action - Failed to decode emoji "{emoji.name}"')
            return None


class ModQueueItem(object):
    __slots__ = ('_bot', '_collection', 'id', 'type', 'author_id', 'guild_id', 'message', 'matches', 'timestamp', 'edits', 'action', 'mod_id', 'action_timestamp', 'deleted_at', 'deleted_by_id')

    @classmethod
    def from_doc(cls, doc, bot: commands.Bot, collection):
        self = cls()
        self._bot = bot
        self._collection = collection
        self._from_doc(doc)

        return self

    def _from_doc(self, doc):
        self.id = doc.get('id')
        self.type = ModQueueItem.Type(doc['type'])
        self.author_id = doc['author_id']
        self.guild_id = doc['guild_id']
        self.message = ModQueueItem.Message.from_doc(doc, self._bot)
        self.matches = doc['matches']
        self.timestamp = doc['timestamp']

        self.deleted_at = doc.get('deleted_at', False)
        self.deleted_by_id = doc.get('deleted_by_id', None)

        self.edits = None
        if 'edits' in doc:
            self.edits = [ModQueueItem.Edit.from_doc(d) for d in doc['edits']]

        self.action = None
        if 'action' in doc:
            self.action = Action(doc['action'])

        self.mod_id = doc.get('mod_id', None)
        self.action_timestamp = doc.get('action_timestamp', None)

    @property
    def author(self) -> discord.User:
        return self._bot.get_user(self.author_id)

    @property
    def guild(self) -> discord.Guild:
        return self._bot.get_guild(self.guild_id)

    @property
    def deleted_by(self) -> discord.User:
        return self._bot.get_user(self.deleted_by_id)

    @staticmethod
    def check(message):
        return RE_TERMS.findall(message.clean_content.strip())

    async def embed(self) -> discord.Embed:
        e = discord.Embed(color=self.action.color if self.action else 0xF44336)
        e.description = ''
        e.description += f'{self.author.mention} '

        if not self.deleted_at and not self.action or self.action is Action.IGNORE:
            e.description += f'[Jump to message](https://discordapp.com/channels/{self.guild.id}/{self.message.channel.id}/{self.message.id})'

        e.description += '\n\n'

        if self.deleted_at:
            td = self.deleted_at - self.timestamp
            e.description += f'***MESSAGE WAS DELETED*** *({td.seconds/60:.0f} minutes)* '

            if self.deleted_by:
                e.description += f'*(by {self.deleted_by.mention})*'

            e.description += '\n\n'

        if self.edits:
            for i, edit in enumerate(reversed(self.edits)):
                td = edit.timestamp - self.timestamp
                e.description += f'**__Edit {len(self.edits) - i}__** '

                e.description += '*('
                if td.days:
                    e.description += f'{td.days} days '

                e.description += f'{td.seconds/60:.0f} minutes'
                e.description += ')*\n'

                e.description += f'Flags: '
                matches = RE_TERMS.findall(edit.clean_content)
                if matches:
                    e.description += ", ".join(f'`{match[0]}`' for match in matches)
                else:
                    e.description += "None"

                e.description += f'\n'
                e.description += f'```{edit.clean_content}```'

                e.description += '\n'

            e.description += '**__Original__**\n'


        e.description += f'Flags: '
        e.description += ", ".join(f'`{match[0]}`' for match in self.matches)

        e.description += '\n'
        e.description += f'```{self.message.clean_content}```'

        strikes: List[ModQueueItem] = []
        async for doc in self._collection.find({"guild_id": self.guild.id, "author_id": self.author.id, "action": Action.STRIKE.value}):
            item = ModQueueItem.from_doc(doc, self._bot, self._collection)
            if item.id == self.id:
                pass

            strikes.append(item)

        if strikes:
            e.description += f'\n**Previous Strikes ({len(strikes)})**\n'
            for i, strike in enumerate(strikes):
                e.description += f'{i+1}. ' + ' '.join(f'`{m[1]}` -' for m in strike.matches) + f' {strike.action_timestamp.strftime("%d %b %Y")}\n'

        e.timestamp = datetime.now()
        e.set_author(name=f'{self.author.name}#{self.author.discriminator}', icon_url=self.author.avatar_url)

        return e

    async def refresh_embed(self, message: discord.Message):
        embed = await self.embed()
        await message.edit(embed=embed)

    async def submit_action(self, action, mod):
        doc = await self._collection.find_one_and_update(
            {'id': self.id},
            {'$set': {
                'action': action.value,
                'mod_id': mod.id,
                'action_timestamp': datetime.utcnow()
            }},
            return_document=ReturnDocument.AFTER
        )

        self._from_doc(doc)

    async def add_edit(self, message: discord.Message):
        doc = await self._collection.find_one_and_update(
            {'id': self.id},
            {'$push': {
                'edits': {
                    'clean_content': message.clean_content,
                    'timestamp': message.edited_at
                }
            }},
            return_document=ReturnDocument.AFTER
        )

        self._from_doc(doc)

    async def set_deleted(self, deleted_by: Union[discord.User, None]):
        data = {
            'deleted_at': datetime.utcnow()
        }

        if deleted_by:
            data['deleted_by_id'] = deleted_by.id

        doc = await self._collection.find_one_and_update(
            {'id': self.id},
            {'$set': data },
            return_document=ReturnDocument.AFTER
        )

        self._from_doc(doc)


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

    class Edit:
        __slots__ = ('timestamp', 'clean_content')
        @classmethod
        def from_doc(cls, doc):
            self = cls()
            self.clean_content = doc['clean_content']
            self.timestamp = doc['timestamp']
            return self


class ModQueueWrapper:
    def __init__(self, bot, collection):
        self._bot = bot
        self._collection = collection

    async def make(self, doc) -> ModQueueItem:
        return ModQueueItem.from_doc(doc, self._bot, self._collection)

    async def add(self, data):
        await self._collection.insert_one(data)

    async def find(self, **kwargs) -> Union[ModQueueItem, None]:
        doc = await self._collection.find_one(kwargs)
        if not doc:
            return None
        return await self.make(doc)


class ModQueue(commands.Cog):
    """ModQueue for flagged words"""

    def __init__(self, bot):
        self.bot = bot
        self.collection: AsyncIOMotorCollection = self.bot.db.modqueue

        self.log = CogLogger('Penelope', self)

        self.log.debug(RE_TERMS.pattern)

        self.queue = ModQueueWrapper(self.bot, self.collection)

    @cache.cache()
    async def get_config(self, guild_id) -> ModQueueConfig:
        return await ModQueueConfig.from_db(guild_id, self.bot)

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

    async def dm(self, user: discord.User, message, ctx):
        try:
            await user.send(message)

        except discord.Forbidden as e:
            self.log.debug(f'Could not send DM to {user.name}#{user.discriminator} ({user.id}): {e}')
            await ctx.send(f'Could not send message to `{user.name}#{user.discriminator}`, user must have DM\'s disabled')

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        if payload.guild_id is None:
            return

        action = Action.lookup(payload.emoji)
        if not action:
            return

        config = await self.get_config(payload.guild_id)
        if not config.check:
            return

        mod = self.bot.get_user(payload.user_id)
        if mod.bot:
            return

        item = await self.queue.find(id=payload.message_id)
        if not item:
            return

        try:
            if action is Action.BAN:
                await self.dm(item.author, f'You have been banned from {item.guild.name} for the following message:\n> {item.message.clean_content}\n\nTo appeal this ban, please contact /r/AMD modmail: https://www.reddit.com/message/compose?to=/r/AMD', config.log_channel)
                await item.guild.ban(item.author, reason = f'Message: "{item.message.clean_content}". Queue ID: {item.id}')

            elif action is Action.STRIKE:
                await self.dm(item.author, f'You have been issued a strike in {item.guild.name} for the following message:\n> {item.message.clean_content}', config.log_channel)
                await item.message.delete()

        except discord.NotFound:
            self.log.debug(f'Message not found, ignoring')
            pass

        except Exception as e:
            traceback.print_exc()
            await config.log_channel.send(f'Unhandled exception handling action {action.name.lower()} on `{item.author.name}#{item.author.discriminator}`, {e}')

        finally:
            await item.submit_action(action, mod)

            e = await item.embed()
            await config.log_channel.send(f'Action submitted: {action.name.lower()} by `{mod.name}#{mod.discriminator}`', embed=e)

            m = await config.queue_channel.fetch_message(item.id)
            await m.delete()

    @commands.Cog.listener()
    async def on_raw_message_edit(self, payload):
        channel = self.bot.get_channel(payload.channel_id)

        if channel.guild is None:
            return

        config = await self.get_config(channel.guild.id)
        if not config.check:
            return

        item = await self.queue.find(**{'message.id': payload.message_id})
        if not item:
            return

        message = await channel.fetch_message(payload.message_id)
        if not message.edited_at:
            return

        await item.add_edit(message)

        message = await config.queue_channel.fetch_message(item.id)
        await item.refresh_embed(message)

    @commands.Cog.listener()
    async def on_raw_message_delete(self, payload):
        if payload.guild_id is None:
            return

        config = await self.get_config(payload.guild_id)
        if not config.check:
            return

        item = await self.queue.find(**{'message.id': payload.message_id})
        if not item:
            return

        await sleep(1) # allow the audit logs to catch up

        deleted_by = None
        guild = self.bot.get_guild(payload.guild_id)
        after = datetime.utcnow() - timedelta(seconds=10)
        async for entry in guild.audit_logs(action=discord.AuditLogAction.message_delete, limit=10): # this is shit but it should work most of the time
            if not entry.created_at > after:
                break
            if entry.target.id == item.author.id and entry.extra.channel.id == item.message.channel.id:
                deleted_by = entry.user
                break

        await item.set_deleted(deleted_by)

        message = await config.queue_channel.fetch_message(item.id)
        await item.refresh_embed(message)

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.guild is None:
            return

        if message.author.bot:
            return

        config = await self.get_config(message.guild.id)
        if not config.check:
            return

        matches = ModQueueItem.check(message)
        if not matches:
            return

        data = {
            "type": ModQueueItem.Type.MESSAGE.value,
            "author_id": message.author.id,
            "guild_id": message.guild.id,
            "message": {
                "id": message.id,
                "channel_id": message.channel.id,
                "clean_content": message.clean_content
            },
            "matches": matches,
            "timestamp": message.created_at
        }

        item = await self.queue.make(data)
        e = await item.embed()

        msg = await config.queue_channel.send("Naughty words detected", embed=e)

        for action in [Action.BAN, Action.STRIKE, Action.IGNORE]:
            await msg.add_reaction(action.emoji)

        data['id'] = msg.id

        await self.queue.add(data)

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
        if not config.check:
            return

        for text in [member.name, member.nick]:
            if not text:
                continue

            matches = RE_TERMS.findall(text)

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

    @commands.group(aliases=['mq'], invoke_without_command=True)
    @commands.guild_only()
    @checks.is_mod()
    async def modqueue(self, ctx):
        pass

    @modqueue.command(aliases=['c'])
    async def config(self, ctx, param: Optional[Text], arg: Optional[Text]):
        config = await self.get_config(ctx.guild.id)
        await config.handle_command(ctx, param, arg)


def setup(bot):
    bot.add_cog(ModQueue(bot))
