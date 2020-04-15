import io

import difflib
from datetime import datetime
from typing import List, Optional, Text

import discord
from discord.ext import commands

from .utils import cache, checks
from .utils.config import CogConfig

from motor.motor_asyncio import AsyncIOMotorDatabase

class NoLogChannelException(Exception):
    pass

class LogConfig(CogConfig):
    name = 'log'

    enabled: bool
    broadcast_channel: discord.TextChannel

    @property
    def check(self):
        return self.enabled \
            and self.broadcast_channel is not None


def listener_check(ctx) -> bool:
    print(ctx.author.bot)
    return ctx.guild and not ctx.author.bot


class Log(commands.Cog):
    """Server event logging"""

    def __init__(self, bot):
        self.bot = bot
        self.db: AsyncIOMotorDatabase = bot.mongo.penelope

    @cache.cache()
    async def get_config(self, guild_id) -> LogConfig:
        return await LogConfig.from_db(guild_id, self.bot)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not message.guild or message.author.bot:
            return

        config = await self.get_config(message.guild.id)
        if not config.check:
            return

        await self.db.messages.insert_one({
            "id": message.id,
            "type": str(message.type),
            "author": message.author.id,
            "content": message.content,
            "channel": message.channel.id,
            "mentions": message.raw_mentions,
            "channel_mentions": message.raw_channel_mentions,
            "role_mentions": message.raw_role_mentions,
            "guild": message.guild.id,
            "clean_content": message.clean_content,
            "attachments": [{
                "id": attachment.id,
                "filename": attachment.filename,
                "proxy_url": attachment.proxy_url
                } for attachment in message.attachments],
            "created_at": message.created_at
        })

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if not after.guild or after.author.bot:
            return

        config = await self.get_config(after.guild.id)
        if not config.check:
            return

        if before.content == after.content:
            return

        await self.db.messages.find_one_and_update(
            {"id": before.id},
            {
                "$set": {
                    "content": after.content,
                    "clean_content": after.clean_content,
                    "mentions": after.raw_mentions,
                    "channel_mentions": after.raw_channel_mentions,
                    "role_mentions": after.raw_role_mentions,
                    "edited_at": after.edited_at
                },
                "$push": {
                    "edits": {
                        "content": before.content,
                        "clean_content": before.clean_content,
                        "edited_at": before.edited_at
                    }
                }
            }
        )

        e = discord.Embed(color = 0x29B6F6)
        e.description = f'<@{after.author.id}> **edited message in** <#{after.channel.id}> [Jump to message](https://discordapp.com/channels/{after.guild.id}/{after.channel.id}/{after.id})'
        e.description += "```diff\n"

        diff: str = difflib.ndiff(
            before.content.splitlines(),
            after.content.splitlines()
        )

        for line in diff:
            if line.startswith('?'): # idk these are annoying
                continue

            e.description += line.replace('```', '[code]') + '\n'

        e.description += "```"
        e.timestamp = after.edited_at or datetime.now()
        e.set_author(name=f'{after.author.name}#{after.author.discriminator}', icon_url=before.author.avatar_url)
        e.set_footer(text=f'User ID: {after.author.id}')

        await config.broadcast_channel.send(embed=e)

    # could just use on_message_delete but I wanna catch fuckers deleting super old shit too
    @commands.Cog.listener()
    async def on_raw_message_delete(self, payload: discord.RawMessageDeleteEvent):
        if not payload.guild_id:
            return

        config = await self.get_config(payload.guild_id)
        if not config.check:
            return

        await self.db.messages.find_one_and_update(
            {"id": payload.message_id},
            {"$set": {"deleted": True}}
        )

        channel: discord.abc.Messageable = self.bot.get_channel(payload.channel_id)
        message: discord.Message = None

        data: dict = await self.db.messages.find_one({"id": payload.message_id})

        # Attempt to pull the cached message
        if payload.cached_message is not None:
            message = payload.cached_message

        # Attempt to pull message data from the db
        elif data:
            # weird shit but it works and its prettier than some other shit I tried
            data = {
                **data,
                'author': {'id': data['author']},
                'attachments': [{
                    **a,
                    'size': 0
                } for a in data['attachments']                ],
                'embeds': [],
                'edited_timestamp': None,
                'pinned': False,
                'mention_everyone': False,
                'tts': False
            }
            message = discord.Message(state=channel._state, channel=channel, data=data)

        else:
            e = discord.Embed(color = 0xF44336)
            e.timestamp = datetime.now()
            e.description = f'Message `{payload.channel_id}` was deleted from <#{payload.channel_id}>, unfortunately the message was not cached'
            await config.broadcast_channel.send(embed=e)
            return

        if message.author.bot:
            return

        e = discord.Embed(color = 0xF44336)
        e.description = f'<@{message.author.id}>**\'s message deleted in** <#{message.channel.id}>'
        e.timestamp = datetime.now()
        e.set_author(name=f'{message.author.name}#{message.author.discriminator}', icon_url=message.author.avatar_url)
        e.set_footer(text=f'User ID: {message.author.id} | Message ID: {message.id}')

        # Attempt to correlate with audit logs
        async for entry in self.bot.get_guild(payload.guild_id).audit_logs(action=discord.AuditLogAction.message_delete):
            if entry.target.id == message.author.id and entry.extra.channel.id == message.channel.id:
                e.description += f' by <@{entry.user.id}>'
                break


        if message.content:
            e.description += "\n\n"
            e.description += f'```{message.content}```'

        e.description += "\n\n"

        files = []

        for attachment in message.attachments:
            buffer = io.BytesIO()

            async with self.bot.session.get(attachment.proxy_url) as resp:
                while True:
                    chunk = await resp.content.read(10)
                    if not chunk:
                        break
                    buffer.write(chunk)

            buffer.seek(0)
            files.append(discord.File(buffer, filename=attachment.filename))

            e.description += f'[Attachment {attachment.filename}]({attachment.proxy_url})\n'

        await config.broadcast_channel.send(embed=e, files=files)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        config = await self.get_config(member.guild.id)
        if not config.check:
            return

        e = discord.Embed(color = 0x4CAF50)
        e.description = f'<@{member.id}> **joined the server** '
        e.timestamp = datetime.now()
        e.set_author(name=f'{member.name}#{member.discriminator}', icon_url=member.avatar_url)
        e.set_footer(text=f'ID: {member.id}')

        await config.broadcast_channel.send(embed=e)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        config = await self.get_config(member.guild.id)
        if not config.check:
            return

        e = discord.Embed(color = 0xFF9800)
        e.description = f'<@{member.id}> **left the server**'
        e.timestamp = datetime.now()
        e.set_author(name=f'{member.name}#{member.discriminator}', icon_url=member.avatar_url)
        e.set_footer(text=f'ID: {member.id}')

        await config.broadcast_channel.send(embed=e)

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        config = await self.get_config(after.guild.id)
        if not config.check:
            return

        # I just want to keep track of nickname changes for now
        if before.nick == after.nick:
            return

        e = discord.Embed(color = 0x673AB7)
        e.set_author(name=f'{after.name}#{after.discriminator}', icon_url=after.avatar_url)
        e.description = f'<@{after.id}> **changed nickname**'
        e.add_field(name="Before", value=before.nick)
        e.add_field(name="After", value=after.nick)
        e.set_footer(text=f'ID: {after.id}')
        e.timestamp = datetime.now()

        await config.broadcast_channel.send(embed=e)

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        config = await self.get_config(payload.guild_id)
        if not config.check:
            return

        user = self.bot.get_user(payload.user_id)

        if user.bot:
            return

        e = discord.Embed(color = 0xE91E63)
        e.set_author(name=f'{user.name}#{user.discriminator}', icon_url=user.avatar_url)
        e.description = f'<@{user.id}> **added reaction {payload.emoji} to** [a message](https://discordapp.com/channels/{payload.guild_id}/{payload.channel_id}/{payload.message_id}) in <#{payload.channel_id}>'
        e.timestamp = datetime.now()

        await config.broadcast_channel.send(embed=e)

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        config = await self.get_config(payload.guild_id)
        if not config.check:
            return

        user = self.bot.get_user(payload.user_id)

        if user.bot:
            return

        e = discord.Embed(color = 0xE91E63)
        e.set_author(name=f'{user.name}#{user.discriminator}', icon_url=user.avatar_url)
        e.description = f'<@{user.id}> **removed reaction {payload.emoji} from** [a message](https://discordapp.com/channels/{payload.guild_id}/{payload.channel_id}/{payload.message_id}) in <#{payload.channel_id}>'
        e.timestamp = datetime.now()

        await config.broadcast_channel.send(embed=e)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        config = await self.get_config(member.guild.id)
        if not config.check:
            return

        e = discord.Embed(color = 0x673AB7)
        e.description = f'<@{member.id}> '
        e.timestamp = datetime.now()
        e.set_author(name=f'{member.name}#{member.discriminator}', icon_url=member.avatar_url)

        for attr in ['afk', 'channel', 'deaf', 'mute', 'self_deaf', 'self_mute', 'self_stream', 'self_video']:
            if before.__getattribute__(attr) == after.__getattribute__(attr):
                continue

            if attr == 'channel':
                if after.channel is not None:
                    e.description += f'**joined voice channel** {after.channel.name}'
                else:
                    e.description += f'**left voice channel** {before.channel.name}'

        e.set_footer(text=f'ID: {member.id}')

        await config.broadcast_channel.send(embed=e)

    ##########################################################################################

    @commands.group(invoke_without_command=True)
    @commands.guild_only()
    @checks.is_mod()
    async def log(self, ctx):
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @log.command(aliases=['c'])
    async def config(self, ctx, param: Optional[Text], arg: Optional[Text]):
        config = await self.get_config(ctx.guild.id)
        await config.handle_command(ctx, param, arg)


def setup(bot):
    bot.add_cog(Log(bot))
