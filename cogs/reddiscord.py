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

        self._monitor_task = bot.loop.create_task(self.monitor_db())

    def cog_unload(self):
        self._monitor_task.cancel()

    @commands.Cog.listener()
    @checks.is_in_guilds(GUILD)
    async def on_member_join(self, member):
        data = await self.db.users.find_one({"discord.id": str(member.id)})

        if(data and data.get("verified")):
            await set_verified(member.id)

    @commands.Cog.listener()
    @checks.is_in_guilds(GUILD)
    async def on_member_ban(self, guild, user):
        await self.db.users.find_one_and_update({"discord.id": user.id}, {"verified": False, "banned": True})
        log.info(f'BANNED {user.name + "#" + user.discriminator} ON {user.server.name}')

    @commands.Cog.listener()
    @checks.is_in_guilds(GUILD)
    async def on_member_unban(self, guild, user):
        await self.db.users.find_one_and_update({"discord.id": user.id}, {"banned": False})
        log.info(f'UNBANNED {user.name + "#" + user.discriminator} ON {guild.name}')

    async def monitor_db(self):
        #First we check the queue for any old additions if this garbage was down
        backlog = await self.db.queue.find({}).to_list(None)
        if(backlog):
            log.debug('Catching up, one sec')

            for item in backlog:
                user = await self.db.users.find_one({"_id": item["ref"]})

                if user.get("verified"):
                    await self.set_verified(user['discord']['id'])

                else:
                    log.warning(f'Weird, {item["ref"]} was in the queue but is not verified.')

                    await self.db.queue.find_one_and_delete({"_id": item['_id']})

        # Monitor DB for changes
        try:
            _stream = self.db.queue.watch()
            print("Monitoring DB")
            async for change in _stream:
                if change["operationType"] == "insert":
                    user = await self.db.users.find_one({"_id": change["fullDocument"]["ref"]})

                    if user.get("verified") and not user.get("banned"):
                        await self.set_verified(int(user['discord']['id']))

                        await self.db.queue.find_one_and_delete({"_id": change["fullDocument"]['_id']})

        # handle asyncio.Task.cancel
        except asyncio.CancelledError:
            print("Monitoring Task Killed")

        except Exception as e:
            log.error(f'Error in Monitoring Task: {e}')

            wh = self.bot.stats_webhook
            embed = discord.Embed(title='Reddiscord', colour=0xE53935)
            embed.add_field(name='Error in Monitoring Task', value=f'{e}', inline=False)
            embed.timestamp = datetime.datetime.utcnow()
            await wh.send(embed=embed)

        finally:
            try:
                _stream.close()
            except:
                pass

    async def set_verified(self, member_id):
        server = self.bot.get_guild(GUILD) # Get serer object from ID
        role = discord.utils.get(server.roles, id=VERIFIED_ROLE) # Get role object of verified role by ID
        member = server.get_member(member_id) # Get member object by discord user ID

        if member: # Someone might verify before they join the server idk
            try:
                await member.add_roles(role) # Add user as verified
                await member.send("Congratulations! You are now verified!") # Send the verified message
                log.info(f'VERIFIED {member.name}#{member.discriminator} ON {server.name}')

            except Exception as e:
                log.error(f'ERROR ADDING ROLE FOR {member.name}#{member.discriminator} IN {server.name}: {e}') # Log an error if there was a problem

def setup(bot):
    bot.add_cog(Reddiscord(bot))
