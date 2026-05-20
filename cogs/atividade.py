import discord
from discord.ext import commands


class Atividade(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.status_aplicado = False

    @commands.Cog.listener()
    async def on_ready(self):
        if self.status_aplicado:
            return

        await self.bot.change_presence(
            status=discord.Status.online,
            activity=discord.Game(name="Driftando...")
        )

        self.status_aplicado = True
        print("[ATIVIDADE] Status definido como: Driftando...")


async def setup(bot: commands.Bot):
    await bot.add_cog(Atividade(bot))