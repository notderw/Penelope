import logging
import asyncio
import discord
import datetime
import typing
from discord.ext import commands

from .utils import checks

log = logging.getLogger('Penelope')

GUILD = 185565668639244289
VERIFIED_ROLE = 190693397856649216

class Reddiscord(commands.Cog):
    """Reddiscord: https://github.com/notderw/rdscrd"""

    def __init__(self, bot):
        self.bot = bot
        self.db = bot.mongo.reddiscord

        self._task = bot.loop.create_task(self.monitor_db())

    def cog_unload(self):
        self._task.cancel()

    def cog_check(self, ctx):
        if not (ctx.guild and ctx.guild.id == GUILD):
            return False

        mod_roles = [
            185565865033465856, # Administrator
            185565928333770752 # Moderator
        ]

        if not [role for role in ctx.author.roles if role.id in mod_roles]:
            return False

        return True

    @commands.Cog.listener()
    async def on_member_join(self, member):
        if member.guild.id != GUILD:
            return

        data = await self.db.users.find_one({"discord.id": str(member.id)})

        if(data and data.get("verified")):
            await self.set_verified(member.id)

    @commands.Cog.listener()
    async def on_member_ban(self, guild, user):
        if guild.id != GUILD:
            return

        await self.db.users.find_one_and_update({"discord.id": user.id}, {"$set": {"verified": False, "banned": True}})
        log.info(f'{self.__class__.__name__} - Banned {user.name + "#" + user.discriminator} ON {guild.name}')

    @commands.Cog.listener()
    async def on_member_unban(self, guild, user):
        if guild.id != GUILD:
            return

        await self.db.users.find_one_and_update({"discord.id": user.id}, {"$set": {"banned": False}})
        log.info(f'{self.__class__.__name__} - Un-banned {user.name + "#" + user.discriminator} ON {guild.name}')

    async def monitor_db(self):
        await self.bot.wait_until_ready()
        #First we check the queue for any old additions if this garbage was down
        backlog = await self.db.queue.find({}).to_list(None)
        if backlog:
            log.info(f'{self.__class__.__name__} - Catching up, one sec ({len(backlog)} items)')

            for item in backlog:
                user = await self.db.users.find_one({"_id": item["ref"]})

                if user.get("verified"):
                    await self.set_verified(int(user['discord']['id']))

                else:
                    log.warning(f'{self.__class__.__name__} - Weird, {item["ref"]} was in the queue but is not verified.')

                await self.db.queue.find_one_and_delete({"_id": item['_id']})

        # Monitor DB for changes
        try:
            _stream = self.db.queue.watch()
            log.info(f'{self.__class__.__name__} - Monitoring DB')
            async for change in _stream:
                if change["operationType"] == "insert":
                    user = await self.db.users.find_one({"_id": change["fullDocument"]["ref"]})

                    if user.get("verified") and not user.get("banned"):
                        await self.set_verified(int(user['discord']['id']))

                        await self.db.queue.find_one_and_delete({"_id": change["fullDocument"]['_id']})

        # handle asyncio.Task.cancel
        except asyncio.CancelledError:
            log.warning(f'{self.__class__.__name__} - Monitoring Task Killed')

        except Exception as e:
            log.error(f'{self.__class__.__name__} - Error in Monitoring Task: {e}')

            try:
                await _stream.close()
            except:
                pass

            embed = discord.Embed(title='Reddiscord', colour=0xE53935)
            embed.add_field(name='Error in Monitoring Task', value=f'{e}', inline=False)
            embed.timestamp = datetime.datetime.utcnow()
            await self.bot.stats_webhook.send(embed=embed)

            self._task.cancel()
            self._task = self.bot.loop.create_task(self.monitor_db())

    async def set_verified(self, member_id):
        guild = self.bot.get_guild(GUILD) # Get serer object from ID
        role = discord.utils.get(guild.roles, id=VERIFIED_ROLE) # Get role object of verified role by ID
        member = guild.get_member(member_id) # Get member object by discord user ID

        if member: # Someone might verify before they join the server idk
            try:
                await member.add_roles(role) # Add user as verified
                await member.send("Congratulations! You are now verified!") # Send the verified message
            except Exception as e:
                log.error(f'{self.__class__.__name__} - Error asdding role for {member.name}#{member.discriminator} in {guild.name}: {e}') # Log an error if there was a problem
            else:
                log.info(f'{self.__class__.__name__} - Verified {member.name}#{member.discriminator} in {guild.name}')

    @commands.group(name='reddiscord', invoke_without_command=True, aliases=['rdscrd', 'verification'])
    async def reddiscord(self, ctx, query: typing.Union[discord.User, str]):
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
    async def rd(self, ctx, *, duser: typing.Union[discord.User, str]):
        """Force query a Discord account"""
        await self.discord(ctx, duser)

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
