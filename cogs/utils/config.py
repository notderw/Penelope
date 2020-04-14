from abc import ABC, abstractmethod
from typing import get_type_hints, cast, Dict, Any, NoReturn

import discord
from discord.ext.commands import Bot, Context, BadArgument

from pymongo import ReturnDocument

import logging
log = logging.getLogger('Penelope')

class CogConfig(ABC):
    """Uses python type hints to autofill the guild config for a cog"""
    _bot: Bot

    @property
    def type_hints(self) -> Dict:
        return get_type_hints(self)

    @property
    def _embed(self) -> discord.Embed:
        e = discord.Embed(color=0xD81B60)
        e.title = f'{self.__class__.__name__}'
        return e


    async def handle_command(self, ctx: Context, param, argument):
        if not param:
            await self._send_params(ctx)

        else:
            try:
                arg = await self._convert_argument(ctx, argument, param)

                await self._update_config(param, arg)

                e = self._embed
                e.description = f'Set **{param}** = {self.__getattribute__(param)}'
                await ctx.send(embed=e)

            except BadArgument as e:
                await ctx.send(e)


    async def _send_params(self, ctx):
        e = self._embed
        e.title += ' \N{WHITE HEAVY CHECK MARK}' if self.check else ' \N{CROSS MARK}'
        e.description = ''

        for param, hint in self.type_hints.items():
            e.description += f'**{param}** ({hint.__name__}) = '

            arg = self.__getattribute__(param)
            if isinstance(arg, discord.abc.Messageable):
                e.description += f'{arg.mention}'
            else:
                e.description += f'{arg}'

            e.description += '\n'

        e.description += ''
        await ctx.send(embed=e)


    async def _convert_argument(self, ctx, argument, param) -> Any:
        if param not in self.type_hints:
            raise BadArgument(f'`{param}` is not a valid config option')

        return await ctx.command._actual_conversion(ctx, self.type_hints[param], argument, param)


    async def _update_config(self, param, arg) -> NoReturn:
        data = {f'{self.name}.{param}': arg}

        if isinstance(arg, discord.abc.Messageable):
            data = {f'{self.name}.{param}_id': arg.id}

        doc = await self._bot.db.guild_config.find_one_and_update(
            {"id": self._guild_id},
            {"$set": data},
            upsert = True,
            return_document = ReturnDocument.AFTER
        )

        self.from_doc(doc)


    @classmethod
    async def from_db(cls, guild_id, bot):
        self = cls()
        self._guild_id = guild_id
        self._bot = bot

        doc = await bot.guild_config(guild_id)
        self.from_doc(doc)

        log.debug(f'{self.__class__.__name__} - Loaded guild {guild_id} config from db')

        return self


    def wrap_lambda(self, func, target):
        # We have to wrap these functions in another function, or else they will all refer back to the same shit
        # kinda ugly, but its the only solution I could find
        return lambda self: func(target)

    def from_doc(self, doc: Dict) -> NoReturn:
        doc = doc.get(self.name, {})
        for param, hint in self.type_hints.items():
            if issubclass(hint, discord.abc.Messageable):
                param_id = f'{param}_id'
                arg = doc.get(param_id, None)

                setattr(self, param_id, arg)

                if hint is discord.TextChannel:
                    func: discord.TextChannel = self.wrap_lambda(self._bot.get_channel, arg)

                elif hint is discord.User:
                    func: discord.User = self.wrap_lambda(self._bot.get_user, arg)

                else:
                    log.warning(f'{self.__class__.__name__} - {hint} not implemented in from_doc')

                setattr(self.__class__, param, property(func)) # Low key black magic, setting @property dynamically

            else:
                if hasattr(self, param):
                    default = self.__getattribute__(param)
                else:
                    default = None

                arg = doc.get(param, default)
                setattr(self, param, arg)


    def __repr__(self):
        return f'<{self.__class__.__name__} {" ".join([f"{p}={self.__getattribute__(p)}" for p, h in self.type_hints.items()])}>'

    @property
    @abstractmethod
    def check(self):
        return self.enabled
