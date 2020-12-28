import inspect

from abc import ABC, abstractmethod
from collections.abc import Iterable

import typing
from typing import Dict, Any, NoReturn

import discord
from discord.ext.commands import Bot, Context, BadArgument

from pymongo import ReturnDocument

import logging
log = logging.getLogger('Penelope')

class CogConfig(ABC):
    """Uses python type hints to autofill the guild config for a cog"""
    _bot: Bot

    def __new__(cls):
        self = super().__new__(cls)
        self.type_hints = typing.get_type_hints(cls)
        del self.type_hints['_bot'] # ehh
        return self


    def __getattr__(self, name):
        if name == 'guild':
            return self._bot.get_guild(self._guild_id)

        if name in self.type_hints:
            hint = self.type_hints[name]
            param_id = self.__getattribute__(self._serialize_param(name))

            if typing.get_origin(hint) is list:
                hint = typing.get_args(hint)[0]
                return [self._get_param(p_id, hint) for p_id in param_id]

            return self._get_param(param_id, hint)


    def _get_param(self, param_id, hint):
        if hint is discord.TextChannel:
            return self._bot.get_channel(param_id)

        elif hint is discord.User:
            return self._bot.get_user(param_id)

        elif hint is discord.Role:
            return self.guild.get_role(param_id)

        elif hint is discord.Message:
            if not param_id:
                return None
            param = list(map(int, param_id.split(':')))
            return self._bot.get_channel(param[0]).fetch_message(param[1])

        else:
            log.warning(f'{self.__class__.__name__} - {hint} not implemented in __getattr__')


    @property
    def _embed(self) -> discord.Embed:
        e = discord.Embed(color=0xD81B60)
        e.title = f'{self.__class__.__name__}'
        return e


    async def handle_command(self, ctx: Context, *args):
        args = list(args)
        if not any(args):
            await self._send_params(ctx)

        else:
            param = args.pop(0)
            try:
                if param not in self.type_hints:
                    raise BadArgument(f'`{param}` is not a valid config option')

                hint = self.type_hints[param]
                origin = typing.get_origin(hint)

                if origin is list:
                    action = args.pop(0).strip()
                    hint = typing.get_args(self.type_hints[param])[0]

                    singlearg = await self._convert_argument(ctx, hint, args, param)

                    arg = getattr(self, param)

                    if action == 'add':
                        if not singlearg in arg:
                            arg.append(singlearg)

                    elif action == 'remove':
                        arg.remove(singlearg)

                    else:
                        raise BadArgument(f'Must use \'add\' or \'remove\' for List parameter {param}')

                else:
                    arg = await self._convert_argument(ctx, hint, args, param)

                await self._update_config(param, arg)

                await ctx.send(embed=await self._single_param_embed(param))

            except BadArgument as e:
                await ctx.send(e)

    async def _single_param_embed(self, param):
        e = self._embed
        e.description = await self._render_param(param)
        return e

    async def _render_hint(self, param) -> str:
        hint = self.type_hints[param]
        origin = typing.get_origin(hint)
        if origin and issubclass(origin, Iterable):
            return f'**{param}** ({origin.__name__.capitalize()}[{typing.get_args(hint)[0].__name__}]):\n'

        else:
            return f'**{param}** ({hint.__name__}) = '

    def _render_val(self, val) -> str:
        if isinstance(val, (discord.abc.Messageable, discord.Role)):
            return val.mention
        elif isinstance(val, discord.Message):
            return f'[Message]({val.jump_url})'
        else:
            return val

    async def _render_arg(self, param) -> str:
        arg = getattr(self, param)

        if inspect.iscoroutine(arg):
            arg = await arg

        if isinstance(arg, Iterable):
            return '\n'.join([f'- {self._render_val(s)}' for s in arg])
        else:
            return self._render_val(arg)

    async def _render_param(self, param):
        return await self._render_hint(param) \
            + str(await self._render_arg(param)) \
            + '\n'

    async def _send_params(self, ctx):
        e = self._embed
        e.title += ' \N{WHITE HEAVY CHECK MARK}' if self.check else ' \N{CROSS MARK}'
        e.description = ''

        for param, hint in self.type_hints.items():
            e.description += await self._render_param(param)

        e.description += ''
        await ctx.send(embed=e)

    async def _convert_argument(self, ctx, converter, args, param) -> Any:
        if converter is discord.Message:
            converter = discord.TextChannel

        if converter is str:
            args = ' '.join(args)
        else:
            args = args[0]

        converted = await ctx.command._actual_conversion(ctx, converter, args, param)

        if converter is discord.Message:
            return await converted.fetch_message(args[1])

        return converted

    def _make_key(self, param, hint):
        if issubclass(hint, discord.abc.Snowflake):
            return f'{param}_id'

        return f'{param}'

    def _serialize_param(self, param) -> dict:
        hint = self.type_hints[param]

        if typing.get_origin(hint) is list:
            hint = typing.get_args(hint)[0]

            return f'{self._make_key(param, hint)}s'

        return self._make_key(param, hint)

    def _make_val(self, val):
        if isinstance(val, discord.Message):
            return f'{val.channel.id}:{val.id}'

        if issubclass(type(val), discord.abc.Snowflake):
            return val.id

        return val

    def _serialize_arg(self, val):
        if isinstance(val, list):
            return [self._make_val(v) for v in val]

        return self._make_val(val)

    async def _update_config(self, param, arg) -> NoReturn:
        data = {f'{self.name}.{self._serialize_param(param)}': self._serialize_arg(arg)}

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

        log.debug(f'{self.__class__.__name__} - Loaded guild "{self.guild.name}" ({self.guild.id}) config from db')

        return self


    def from_doc(self, doc: Dict) -> NoReturn:
        doc = doc.get(self.name, {})
        for param, hint in self.type_hints.items():
            param_id = self._serialize_param(param)

            if hasattr(self, param):
                default = getattr(self, param)
            elif typing.get_origin(hint) is list:
                default = []
            else:
                default = None

            arg = doc.get(param_id, default)

            setattr(self, param_id, arg)


    def __repr__(self):
        return f'<{self.__class__.__name__} {" ".join([f"{p}={getattr(self, p)}" for p, h in self.type_hints.items()])}>'

    @property
    @abstractmethod
    def check(self):
        return self.enabled
