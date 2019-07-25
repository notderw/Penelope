import logging
import asyncio
import discord
import datetime
from discord.ext import commands

from .utils import checks

log = logging.getLogger('reddiscord')
log.setLevel(logging.DEBUG)

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
        return ctx.guild and ctx.guild.id == GUILD

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
        log.info(f'[Reddiscord] Banned {user.name + "#" + user.discriminator} ON {user.guild.name}')

    @commands.Cog.listener()
    async def on_member_unban(self, guild, user):
        if guild.id != GUILD:
            return

        await self.db.users.find_one_and_update({"discord.id": user.id}, {"$set": {"banned": False}})
        log.info(f'[Reddiscord] Un-banned {user.name + "#" + user.discriminator} ON {guild.name}')

    async def monitor_db(self):
        await self.bot.wait_until_ready()
        #First we check the queue for any old additions if this garbage was down
        backlog = await self.db.queue.find({}).to_list(None)
        if(backlog):
            log.debug('[Reddiscord] Catching up, one sec')

            for item in backlog:
                user = await self.db.users.find_one({"_id": item["ref"]})

                if user.get("verified"):
                    await self.set_verified(user['discord']['id'])

                else:
                    log.warning(f'[Reddiscord] Weird, {item["ref"]} was in the queue but is not verified.')

                    await self.db.queue.find_one_and_delete({"_id": item['_id']})

        # Monitor DB for changes
        try:
            _stream = self.db.queue.watch()
            print("[Reddiscord] Monitoring DB")
            async for change in _stream:
                if change["operationType"] == "insert":
                    user = await self.db.users.find_one({"_id": change["fullDocument"]["ref"]})

                    if user.get("verified") and not user.get("banned"):
                        await self.set_verified(int(user['discord']['id']))

                        await self.db.queue.find_one_and_delete({"_id": change["fullDocument"]['_id']})

        # handle asyncio.Task.cancel
        except asyncio.CancelledError:
            print("[Reddiscord] Monitoring Task Killed")

        except Exception as e:
            log.error(f'[Reddiscord] Error in Monitoring Task: {e}')

            try:
                _stream.close()
            except:
                pass

            wh = self.bot.stats_webhook
            embed = discord.Embed(title='Reddiscord', colour=0xE53935)
            embed.add_field(name='Error in Monitoring Task', value=f'{e}', inline=False)
            embed.timestamp = datetime.datetime.utcnow()
            await wh.send(embed=embed)

            self._task.cancel()
            self._task = bot.loop.create_task(self.monitor_db())

    async def set_verified(self, member_id):
        guild = self.bot.get_guild(GUILD) # Get serer object from ID
        role = discord.utils.get(guild.roles, id=VERIFIED_ROLE) # Get role object of verified role by ID
        member = guild.get_member(member_id) # Get member object by discord user ID

        if member: # Someone might verify before they join the server idk
            try:
                await member.add_roles(role) # Add user as verified
                await member.send("Congratulations! You are now verified!") # Send the verified message
            except Exception as e:
                log.error(f'[Reddiscord] Error asdding role for {member.name}#{member.discriminator} in {guild.name}: {e}') # Log an error if there was a problem
            else:
                log.info(f'[Reddiscord] Verified {member.name}#{member.discriminator} in {guild.name}')

    @commands.command(hidden=True)
    @commands.has_role(185565928333770752) # Needs the Moderator role
    async def verification(self, ctx, member: discord.Member):
        user = await self.db.users.find_one({"discord.id": str(member.id)})

        if not user or "reddit" not in user:
            return await ctx.send("User has not verified")

        e = discord.Embed(title=f'/u/{user["reddit"]["name"]}', url=f'https://reddit.com/u/{user["reddit"]["name"]}')

        e.set_thumbnail(url=f"https://cdn.discordapp.com/avatars/{member.id}/{member.avatar}.jpg?size=32")
        e.set_footer(text=f'Verified at {datetime.datetime.fromtimestamp(user["verified_at"]).strftime("%H:%M, %a %b %d")}')
        e.colour = member.colour

        await ctx.send(embed=e)

def setup(bot):
    bot.add_cog(Reddiscord(bot))
