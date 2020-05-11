from io import BytesIO
from typing import Optional, List, Text

import discord

from datetime import datetime
from discord.ext import commands
from prettytable import PrettyTable, MSWORD_FRIENDLY

from .utils.formats import TabularData

DM_CHANNEL = 621139648143556628

class DM(commands.Cog):
    """Direct Message management commands"""

    def __init__(self, bot):
        self.bot = bot

    async def cog_check(self, ctx):
        return await self.bot.is_owner(ctx.author)

    @property
    def dm_channel(self):
        return self.bot.get_channel(DM_CHANNEL)

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
                print(original)

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

        e = discord.Embed(color = 0x4CAF50)
        e.description = f'**Message recieved:**\n{message.content}'
        e.timestamp = datetime.now()
        e.set_author(name=f'{message.author.name}#{message.author.discriminator}', icon_url=message.author.avatar_url)
        e.set_footer(text=f'User ID: {message.author.id}')

        files = await self.attachments_to_files(message.attachments)

        await self.dm_channel.send(embed=e, files=files)

    @commands.group(name='dm', invoke_without_command=True, hidden=True)
    @commands.is_owner()
    async def dm(self, ctx):

        table = PrettyTable()
        table.border = False
        table.header = False
        table.align = 'l'
        table.padding_width = 1

        for channel in reversed(self.bot.private_channels):
            if hasattr(channel, 'recipient'):
                table.add_row([f'{channel.recipient.name}#{channel.recipient.discriminator}\n{channel.created_at.strftime("%Y%m%d %H%M")} UTC', f'{channel.recipient.id}'])

        print(table)

        e = discord.Embed(color = 0x29B6F6)
        e.description = f'**Recent DMs** \n\n ```{table}```'
        e.timestamp = datetime.now()
        await ctx.send(embed=e)

    @dm.command(aliases=['h'])
    async def history(self, ctx, user: discord.User, limit: int = 10):
        if not user.dm_channel:
            return await ctx.send("No DM histroy with this user")

        table = PrettyTable(["Name", "Message"])
        table.border = False
        table.header = False
        table.align = "l"
        table.padding_width = 1

        last_author = None
        for message in reversed(await user.dm_channel.history(limit=limit).flatten()):
            if message.author == last_author:

                table.add_row(['', message.clean_content])
                last_author = None

            else:
                table.add_row([f'{message.author.name}', message.clean_content])

            last_author = message.author

        e = discord.Embed(color = 0x29B6F6)
        # e.description = f'**DM History**'
        e.timestamp = user.dm_channel.created_at
        e.set_author(name=f'{user.name}#{user.discriminator}', icon_url=user.avatar_url)
        e.set_footer(text=f'ID: {user.id}')

        await ctx.send(f'```Last {limit} messages```\n```{table}```', embed=e)

    @dm.command(aliases=['s'])
    async def send(self, ctx, user: discord.User, *, msg: Optional[Text] = ""):
        files = await self.attachments_to_files(ctx.message.attachments)

        sent = await user.send(msg, files=files)

        e = discord.Embed(color = 0x2196F3)
        e.description = f'**Message sent:**\n{msg}'

        if sent.attachments:
            e.description += "\n\n**Attachments:**\n"
            for attachment in sent.attachments:
                e.description += f'[{attachment.filename}]({attachment.url})\n'

        e.timestamp = datetime.now()
        e.set_author(name=f'{user.name}#{user.discriminator}', icon_url=user.avatar_url)
        e.set_footer(text=f'Recipient ID: {user.id}')

        await ctx.send(embed=e)

        await ctx.message.delete()

def setup(bot):
    bot.add_cog(DM(bot))
