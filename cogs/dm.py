from io import BytesIO
from datetime import datetime
from typing import Optional, List, Text

import discord
from discord.ext import commands

from pymongo.collection import Collection

GUILD = 187711261377691648
CATEGORY = 752680280950702161

class InvalidDMContext(Exception):
    pass

class DM(commands.Cog):
    """Direct Message management commands"""

    def __init__(self, bot):
        self.bot = bot

        self.collection: Collection = bot.db.dm


    @property
    def guild(self) -> discord.Guild:
        return self.bot.get_guild(GUILD)

    @property
    def category(self) -> discord.CategoryChannel:
        return self.guild.get_channel(CATEGORY)


    async def cog_check(self, ctx):
        return await self.bot.is_owner(ctx.author)

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
            elif isinstance(original, InvalidDMContext):
                await ctx.send('You can\'t do that here')
            else:
                print(original)


    async def user_from_channel(self, channel: discord.TextChannel) -> discord.User:
        doc = await self.collection.find_one({'channel': channel.id}, {'user': True})
        return self.bot.get_user(doc['user'])

    async def get_dm_channel(self, user: discord.User) -> discord.TextChannel:
        doc = await self.collection.find_one({'user': user.id}, {'channel': True})

        if doc and 'channel' in doc:
            return self.guild.get_channel(doc['channel'])

        channel = await self.category.create_text_channel(str(user))

        await self.collection.find_one_and_update(
            {'user': user.id},
            {'$set': {'channel': channel.id}},
            upsert=True
        )

        await self.system_message(channel, f'Created new DM channel for {user} {user.mention} ({user.id})')

        return channel

    async def system_message(self, channel: discord.TextChannel, message: str):
        bot = self.guild.get_member(self.bot.user.id)
        e = discord.Embed(description='', color=bot.color)
        e.set_author(name=f'[SYSTEM]')
        e.description += f'{message}'
        e.timestamp = datetime.now()

        await channel.send(embed=e)

    async def attachments_to_files(self, attachments: List[discord.Attachment]) -> List[discord.File]:
        files = []
        for attachment in attachments:
            buffer = BytesIO(await attachment.read())
            files.append(discord.File(buffer, filename=attachment.filename))

        return files


    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.id == self.bot.user.id:
            return

        if message.guild:
            return

        channel = await self.get_dm_channel(message.author)

        e = discord.Embed(color = 0x4CAF50)
        e.description = f'{message.content}'
        e.timestamp = datetime.now()
        e.set_author(name=f'{message.author.name}#{message.author.discriminator}', icon_url=message.author.avatar_url)

        files = await self.attachments_to_files(message.attachments)

        await channel.send(embed=e, files=files)


    @commands.group(name='dm', invoke_without_command=True, hidden=True)
    async def dm(self, ctx):
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @dm.command()
    async def new(self, ctx, user: discord.User):
        channel = await self.get_dm_channel(user)
        await ctx.send(f'{channel.mention}')

    @dm.command(aliases=['r', 'send', 's'])
    async def reply(self, ctx, *, msg: Optional[Text] = ""):
        if not ctx.channel.category_id or ctx.channel.category_id != CATEGORY:
            raise InvalidDMContext()

        user = await self.user_from_channel(ctx.channel)

        files = await self.attachments_to_files(ctx.message.attachments)

        try:
            sent = await user.send(msg, files=files)
        except discord.Forbidden as e:
            await self.system_message(ctx, f'Error: {e.text}')
            return

        e = discord.Embed(color = 0x2196F3)
        e.description = f'{msg}'

        e.timestamp = datetime.now()
        e.set_author(name=f'{ctx.author.name}#{ctx.author.discriminator}', icon_url=ctx.author.avatar_url)

        # lazyass
        files = await self.attachments_to_files(sent.attachments)
        await ctx.send(embed=e, files=files)

        await ctx.message.delete()

    @dm.command()
    async def close(self, ctx):
        if not ctx.channel.category_id or ctx.channel.category_id != CATEGORY:
            raise InvalidDMContext()

        await self.collection.find_one_and_delete({'channel': ctx.channel.id})
        await ctx.channel.delete(reason=f'DM closed by {ctx.author}')


def setup(bot):
    bot.add_cog(DM(bot))
