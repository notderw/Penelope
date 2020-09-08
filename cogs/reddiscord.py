import asyncio
import datetime
import secrets
from typing import Union, Optional, Text

import discord
from discord.ext import commands

from .utils import checks, cache
from .utils.config import CogConfig
from .utils.logging import CogLogger

BASE_URI = 'https://reddiscord.derw.xyz'

class ReddiscordConfig(CogConfig):
    name = 'reddiscord'

    enabled: bool = False
    verified_role: discord.Role

    @property
    def check(self):
        return self.enabled \
            and self.verified_role is not None


class ReddiscordUser:
    token: str
    verified: bool
    verified_at: datetime.datetime
    banned: bool

    def __init__(self, bot: commands.Bot, db):
        self._bot = bot
        self._db = db

    @classmethod
    async def from_discord(cls, bot, db, user: discord.User):
        self = cls(bot, db)

        doc = await db.users.find_one({'discord.id': user.id})
        self.from_doc(doc or {'discord': {'name': f'{user.name}#{user.discriminator}', 'id': user.id}})

        return self

    def from_doc(self, doc):
        self.token = doc.get('token', None)
        self.verified = doc.get('verified', False)
        self.verified_at = doc.get('verified_at', None)
        self.banned = doc.get('banned', False)
        self.discord = ReddiscordUser.Discord(doc)
        self.reddit = ReddiscordUser.Reddit(doc)
        return self

    async def make_token(self):
        while True:
            token = secrets.token_urlsafe(128)
            # Sanity check to prevent double assigning tokens
            if await self._db.users.count_documents({'secret.token': token}, limit = 1) == 0:
                break

        await self._db.users.find_one_and_update(
            {'discord.id': self.discord.id},
            {'$set': {
                'token': token,
                'discord.name': self.discord.name
            }},
            upsert = True
        )

        return token

    async def setprocessed(self):
        await self._db.users.find_one_and_update(
            {'discord.id': self.discord.id},
            {'$set': {
                'processed': True
            }},
        )


    class Discord:
        name: Text
        id: int

        def __init__(self, doc):
            d = doc['discord']
            self.name = d['name']
            self.id = d['id']

    class Reddit:
        name: Text
        id: Text

        def __init__(self, doc):
            r = doc.get('reddit', {})
            self.name = r.get('name')
            self.id = r.get('id')


class Reddiscord(commands.Cog):
    """Reddiscord: https://github.com/notderw/rdscrd"""

    def __init__(self, bot):
        self.bot = bot
        self.db = bot.mongo.reddiscord

        self.log = CogLogger('Penelope', self)

        self._task = bot.loop.create_task(self.monitor_db())

    @cache.cache()
    async def get_config(self, guild_id) -> ReddiscordConfig:
        return await ReddiscordConfig.from_db(guild_id, self.bot)

    def cog_unload(self):
        self._task.cancel()

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        config = await self.get_config(member.guild.id)
        if not config.check:
            return

        ru = await ReddiscordUser.from_discord(self.bot, self.db, member)

        if ru.verified:
            await member.add_roles(config.verified_role)
            self.log.debug(f'{member.name}#{member.discriminator} ({member.id}) joined {member.guild.name} ({member.guild.id}) and is already verified, added role {config.verified_role}')
            return

        if not ru.token:
            self.log.debug(f'{member.name}#{member.discriminator} ({member.id}) joined {member.guild.name} ({member.guild.id}) and has no token, sending welcome message')

            token = await ru.make_token()

            message = (
                'You have joined a Reddiscord enabled server!\n'
                f'Click the link below to get the `{config.verified_role}` role in {member.guild.name}\n'
                '*Do not share this link with anyone! It is linked __exclusively__ with your Discord account, and will only work once!*\n'
                f'<{BASE_URI}/v/{token}>'
            )

            try:
                await member.send(message)
            except discord.Forbidden as e:
                self.log.error(f'Could not send join message to {member}: {e.text}')

            return

        self.log.debug(f'{ru.discord.name} ({ru.discord.id}) joined {member.guild.name} ({member.guild.id})')


    async def process(self, ru: ReddiscordUser):
        for guild in self.bot.guilds:
            config = await self.get_config(guild.id)
            if config.enabled:
                try:
                    await guild.get_member(ru.discord.id).add_roles(config.verified_role)
                    self.log.info(f'Added role {config.verified_role} to {ru.discord.name} ({ru.discord.id}) on {guild} ({guild.id})')
                except:
                    self.log.error(f'Error adding role {config.verified_role} to {ru.discord.name} ({ru.discord.id}) on {guild} ({guild.id}): {e}')

        await ru.setprocessed()

        try:
            user = self.bot.get_user(ru.discord.id)
            await user.send('Reddiscord verification successful!')
        except Exception as e:
            self.log.error(f'Error sending message: {e}')


    async def monitor_db(self):
        await self.bot.wait_until_ready()

        self.log.info(f'Monitoring Task Started')

        try:
            async for doc in self.db.users.find({'verified': True, 'processed': {'$exists': False}}):
                ru = ReddiscordUser(self.bot, self.db).from_doc(doc)
                await self.process(ru)

            # Monitor DB for changes
            async with self.db.users.watch(full_document='updateLookup') as stream:
                async for change in stream:
                    if change["operationType"] == "update" \
                        and 'verified' in change['updateDescription']['updatedFields'] \
                        and change['updateDescription']['updatedFields']['verified'] == True:
                            doc = change['fullDocument']
                            ru = ReddiscordUser(self.bot, self.db).from_doc(doc)
                            await self.process(ru)

        # handle asyncio.Task.cancel
        except asyncio.CancelledError:
            self.log.warning(f'Monitoring Task Killed')

        except Exception as e:
            self.log.error(f'Error in Monitoring Task: {e}')

            embed = discord.Embed(title='Reddiscord', colour=0xE53935)
            embed.add_field(name='Error in Monitoring Task', value=f'{e}', inline=False)
            embed.timestamp = datetime.datetime.utcnow()
            await self.bot.stats_webhook.send(embed=embed)

        #     self._task.cancel()
        #     self._task = self.bot.loop.create_task(self.monitor_db())

    @checks.is_mod()
    @commands.group(name='reddiscord', invoke_without_command=True, aliases=['rdscrd', 'verification'])
    async def reddiscord(self, ctx, query: Union[discord.User, str]):
        """Query a reddit or Discord user to see their verification status"""
        print(type(query), query)
        if isinstance(query, str) and query.startswith('/u/'):
            await self.reddit(ctx, query)

        elif isinstance(query, discord.User):
            await self.discord(ctx, query)

    @reddiscord.command(name='reddit', aliases=['r'])
    async def rr(self, ctx, *, ruser: str):
        """Force query a reddit account"""
        await self.reddit(ctx, ruser)

    @reddiscord.command(name='discord', aliases=['d'])
    async def rd(self, ctx, *, duser: Union[discord.User, str]):
        """Force query a Discord account"""
        await self.discord(ctx, duser)

    @reddiscord.command(aliases=['c'])
    async def config(self, ctx, param: Optional[Text], arg: Optional[Text]):
        config = await self.get_config(ctx.guild.id)
        await config.handle_command(ctx, param, arg)

    async def reddit(self, ctx, ruser):
        data = await self.db.users.find_one({"reddit.name": { "$regex": ruser.replace("/u/", ""), "$options": "i"}})
        await self.render(ctx, data)

    async def discord(self, ctx, duser):
        data = await self.db.users.find_one({"discord.id": str(duser.id) if isinstance(duser, discord.User) else duser})
        await self.render(ctx, data)

    async def render(self, ctx, data):
        if not data or "reddit" not in data:
            await ctx.send("User has not verified")
            return

        user = self.bot.get_user(int(data["discord"]["id"]))

        e = discord.Embed(title=f'/u/{data["reddit"]["name"]}', url=f'https://reddit.com/u/{data["reddit"]["name"]}')

        if user:
            e.description = f'{user.mention}\n\n`{user.id}`'
            e.set_thumbnail(url=f"https://cdn.discordapp.com/avatars/{user.id}/{user.avatar}.jpg?size=32")
            e.set_footer(text=f'Verified at {datetime.datetime.fromtimestamp(data["verified_at"]).strftime("%H:%M, %a %b %d")}')
            e.colour = 0x29B6F6

        else:
            e.description = f'User no longer exists (was `{data["discord"]["name"]}`)'
            e.colour = 0xFF5722

        if data.get('banned'):
            e.description += '\n\n**User was banned**'
            e.colour = 0xF44336

        await ctx.send(embed=e)


def setup(bot):
    bot.add_cog(Reddiscord(bot))
