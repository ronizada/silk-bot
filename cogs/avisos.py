import discord
from discord import app_commands
from discord.ext import commands

from utils.embeds import create_embed


class AvisoModal(discord.ui.Modal, title="Criar Aviso"):
    def __init__(
        self,
        canal: discord.TextChannel,
        cargos: list[discord.Role]
    ):
        super().__init__()

        self.canal = canal
        self.cargos = cargos

    titulo = discord.ui.TextInput(
        label="Título do aviso",
        placeholder="Ex: 📢 Aviso importante",
        max_length=256,
        required=True
    )

    mensagem = discord.ui.TextInput(
        label="Mensagem",
        placeholder="Digite aqui as informações da fac, farm ou valores...",
        style=discord.TextStyle.paragraph,
        max_length=4000,
        required=True
    )

    async def on_submit(self, interaction: discord.Interaction):
        titulo = str(self.titulo.value).strip()
        mensagem = str(self.mensagem.value).strip()

        embed = create_embed(
            title=titulo,
            description=mensagem
        )

        try:
            await self.canal.send(embed=embed)

            if self.cargos:
                mencoes = " ".join(cargo.mention for cargo in self.cargos)

                await self.canal.send(
                    content=mencoes,
                    allowed_mentions=discord.AllowedMentions(
                        roles=self.cargos,
                        users=False,
                        everyone=False
                    )
                )

            await interaction.response.send_message(
                f"✅ Aviso enviado com sucesso em {self.canal.mention}.",
                ephemeral=True
            )

        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ Não tenho permissão para enviar mensagem ou mencionar cargos nesse canal.",
                ephemeral=True
            )

        except discord.HTTPException:
            await interaction.response.send_message(
                "❌ Ocorreu um erro ao tentar enviar o aviso.",
                ephemeral=True
            )


class CargoSelect(discord.ui.RoleSelect):
    def __init__(self):
        super().__init__(
            placeholder="Selecione os cargos que serão mencionados",
            min_values=0,
            max_values=25
        )

    async def callback(self, interaction: discord.Interaction):
        view: AvisoConfigView = self.view

        cargos = []

        for cargo in self.values:
            if cargo.is_default():
                continue

            cargos.append(cargo)

        view.cargos = cargos

        await interaction.response.defer()


class AvisoConfigView(discord.ui.View):
    def __init__(
        self,
        autor_id: int,
        canal: discord.TextChannel
    ):
        super().__init__(timeout=300)

        self.autor_id = autor_id
        self.canal = canal
        self.cargos: list[discord.Role] = []

        self.add_item(CargoSelect())

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.autor_id:
            await interaction.response.send_message(
                "❌ Apenas quem usou o comando pode configurar esse aviso.",
                ephemeral=True
            )
            return False

        return True

    @discord.ui.button(
        label="Criar aviso",
        emoji="📢",
        style=discord.ButtonStyle.primary
    )
    async def criar_aviso(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        modal = AvisoModal(
            canal=self.canal,
            cargos=self.cargos
        )

        await interaction.response.send_modal(modal)


class Avisos(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="aviso",
        description="Abre um painel para enviar um aviso em um canal."
    )
    @app_commands.default_permissions(manage_guild=True)
    async def aviso(
        self,
        interaction: discord.Interaction,
        canal: discord.TextChannel
    ):
        embed = create_embed(
            title="📢 Criar aviso",
            description=(
                f"Canal escolhido: {canal.mention}\n\n"
                "Selecione abaixo os cargos que deseja mencionar.\n"
                "Depois clique em **Criar aviso** para escrever a mensagem."
            )
        )

        embed.add_field(
            name="Observação",
            value="Se não selecionar nenhum cargo, o aviso será enviado sem menção.",
            inline=False
        )

        await interaction.response.send_message(
            embed=embed,
            view=AvisoConfigView(
                autor_id=interaction.user.id,
                canal=canal
            ),
            ephemeral=True
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Avisos(bot))