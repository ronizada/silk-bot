import discord
from discord import app_commands
from discord.ext import commands

from utils.embeds import create_embed


class Ping(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="ping",
        description="Verifica a latência do bot."
    )
    async def ping(self, interaction: discord.Interaction):
        latency_ms = round(self.bot.latency * 1000)

        embed = create_embed(
            title="🏓 Pong!",
            description="Bot online e respondendo normalmente."
        )

        embed.add_field(
            name="Latência",
            value=f"`{latency_ms}ms`",
            inline=False
        )

        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Ping(bot))