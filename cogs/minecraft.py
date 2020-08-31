import re
import traceback

from datetime import datetime
from typing import List, Dict, Optional, NoReturn

import dns.resolver

from mcstatus import MinecraftServer

import discord
from discord.ext import commands, tasks

from .utils import cache, checks
from .utils.config import CogConfig


class Server:
    __slots__ = ('name', 'ip')

    def __init__(self, doc):
        self.ip = doc["ip"]
        self.name = doc.get("name")

    def __str__(self):
        return f'{self.ip} {self.name}'

    async def resolve(self, loop):
        return await loop.run_in_executor(None, self._resolve)

    def _resolve(self):
        addr = self.ip.split(':')

        port = addr[1] if len(addr) == 2 else 25565
        addr = addr[0]

        try:
            for r in dns.resolver.query(f'_minecraft._tcp.{addr}', 'SRV'):
                addr = r.target
                port = r.port

            for r in dns.resolver.query(self.ip, 'A'):
                addr = r.address

        except dns.resolver.NXDOMAIN:
            pass

        finally:
            return (addr, port)


class MinecraftConfig(CogConfig):
    name = 'minecraft'

    enabled: bool = False
    channel: discord.TextChannel
    message: discord.Message
    servers: List[Server] = []

    def from_doc(self, doc: Dict) -> NoReturn:
        super().from_doc(doc)

        self.servers: List[Server] = [Server(s) for s in self.servers]

    @property
    def check(self):
        return self.enabled \
            and self.message_id is not None


class Minecraft(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

        self.updater.start()

    def cog_unload(self):
        self.updater.cancel()

    @cache.cache()
    async def get_config(self, guild_id) -> MinecraftConfig:
        return await MinecraftConfig.from_db(guild_id, self.bot)

    @tasks.loop(minutes=10)
    async def updater(self):
        await self.bot.wait_until_ready()

        async for doc in self.bot.db.guild_config.find({'minecraft.enabled': True}, {'id': True}):
            try:
                guild_id = doc['id']
                config = await self.get_config(guild_id)

                if not config.check:
                    continue

                e = await self.render(config)

                message: discord.Message = await config.message
                await message.edit(content="", embed=e)

            except Exception as e:
                traceback.print_exc()

    async def render(self, config):
        e = discord.Embed(color=0x4CAF50)
        e.title = "Minecraft Status"
        e.description = ""

        any_online = False
        for s in config.servers:
            addr, port = await s.resolve(self.bot.loop)
            server = MinecraftServer(addr, port)

            e.description += f'__**{s.name}**__'

            try:
                status = await server.status()

                any_online = True
                motd = re.sub(r'§\w', '', status.description.get('text'))
                e.description += f' `{status.version.name}` '
                e.description += f' *({status.latency:.1f}ms)*'

                if status.modinfo:
                    e.description += f' `{status.modinfo.type}, {len(status.modinfo.list)} mods`'

                e.description += '\n'
                if motd:
                    e.description += f'```{motd}```'
                e.description += f'{status.players.online} / {status.players.max} players online:\n'

                if status.players.sample:
                    for p in status.players.sample:
                        e.description += f'> {discord.utils.escape_markdown(p.name)}\n'

            except (TimeoutError, ConnectionRefusedError):
                e.description += f' *(Offline)*\n'

            except Exception:
                import traceback
                traceback.print_exc()

            e.description += '\n'

        e.description.strip()
        e.timestamp = datetime.utcnow()

        if not any_online:
            e.color = 0xF44336

        return e

    ##########################################################################################

    @commands.group(aliases=['mc'], invoke_without_command=True)
    @commands.guild_only()
    @checks.is_mod()
    async def minecraft(self, ctx):
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @minecraft.command()
    async def deploy(self, ctx):
        config = await self.get_config(ctx.guild.id)
        if not config.check:
            await ctx.send('nope')
            return

        e = await self.render(config)

        message: discord.Message = await config.message
        await message.edit(content="", embed=e)

    @minecraft.group(aliases=['c'], invoke_without_command=True)
    async def config(self, ctx, *args):
        config = await self.get_config(ctx.guild.id)
        await config.handle_command(ctx, *args)

    @config.group(invoke_without_command=True)
    async def servers(self, ctx):
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @servers.command()
    async def add(self, ctx, ip: str, name: Optional[str]):
        await self.bot.db.guild_config.find_one_and_update(
            {'id': ctx.guild.id },
            {'$push': {
                'minecraft.servers': {
                    'ip': ip,
                    'name': name
                }
            }}
        )

        self.get_config.invalidate(self, ctx.guild.id)

        config = await self.get_config(ctx.guild.id)
        await ctx.send(embed=await config._single_param_embed('servers'))

        await self.deploy(config)

    @servers.command()
    async def remove(self, ctx, index: int):
        config = await self.get_config(ctx.guild.id)

        await self.bot.db.guild_config.find_one_and_update(
            {'id': ctx.guild.id},
            {'$pull': {
                'minecraft.servers': {
                    'ip': config.servers[index].ip
                }
            }}
        )

        self.get_config.invalidate(self, ctx.guild.id)

        config = await self.get_config(ctx.guild.id)
        await ctx.send(embed=await config._single_param_embed('servers'))

        await self.deploy(config)


def setup(bot):
    bot.add_cog(Minecraft(bot))
