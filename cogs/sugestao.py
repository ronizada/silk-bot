import sqlite3
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from utils.embeds import create_embed


DB_PATH = Path("data/sugestoes.db")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS sugestao_config (
                guild_id INTEGER PRIMARY KEY,
                channel_id INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS sugestoes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                message_id INTEGER,
                thread_id INTEGER,
                author_id INTEGER NOT NULL,
                texto TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'aberta',
                criado_em TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS sugestao_votes (
                sugestao_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                voto TEXT NOT NULL,
                criado_em TEXT NOT NULL,
                atualizado_em TEXT NOT NULL,
                PRIMARY KEY (sugestao_id, user_id)
            );
        """)
        conn.commit()


def set_config_canal(guild_id: int, channel_id: int):
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO sugestao_config (guild_id, channel_id)
            VALUES (?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET channel_id = excluded.channel_id
        """, (guild_id, channel_id))
        conn.commit()


def get_config_canal(guild_id: int) -> Optional[int]:
    with get_conn() as conn:
        row = conn.execute("""
            SELECT channel_id FROM sugestao_config
            WHERE guild_id = ?
        """, (guild_id,)).fetchone()

        return row["channel_id"] if row else None


def criar_sugestao(guild_id: int, channel_id: int, author_id: int, texto: str) -> int:
    with get_conn() as conn:
        cursor = conn.execute("""
            INSERT INTO sugestoes (
                guild_id, channel_id, author_id, texto, criado_em
            )
            VALUES (?, ?, ?, ?, ?)
        """, (guild_id, channel_id, author_id, texto, now_iso()))

        conn.commit()
        return cursor.lastrowid


def atualizar_sugestao_msg_thread(
    sugestao_id: int,
    message_id: Optional[int] = None,
    thread_id: Optional[int] = None
):
    with get_conn() as conn:
        if message_id is not None:
            conn.execute("""
                UPDATE sugestoes
                SET message_id = ?
                WHERE id = ?
            """, (message_id, sugestao_id))

        if thread_id is not None:
            conn.execute("""
                UPDATE sugestoes
                SET thread_id = ?
                WHERE id = ?
            """, (thread_id, sugestao_id))

        conn.commit()


def buscar_sugestao_por_id(sugestao_id: int):
    with get_conn() as conn:
        return conn.execute("""
            SELECT * FROM sugestoes
            WHERE id = ?
            LIMIT 1
        """, (sugestao_id,)).fetchone()


def buscar_sugestao_por_message_id(guild_id: int, message_id: int):
    with get_conn() as conn:
        return conn.execute("""
            SELECT * FROM sugestoes
            WHERE guild_id = ? AND message_id = ?
            LIMIT 1
        """, (guild_id, message_id)).fetchone()


def registrar_voto(sugestao_id: int, user_id: int, voto: str):
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO sugestao_votes (
                sugestao_id, user_id, voto, criado_em, atualizado_em
            )
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(sugestao_id, user_id) DO UPDATE SET
                voto = excluded.voto,
                atualizado_em = excluded.atualizado_em
        """, (
            sugestao_id,
            user_id,
            voto,
            now_iso(),
            now_iso()
        ))

        conn.commit()


def contar_votos(sugestao_id: int):
    with get_conn() as conn:
        concordo = conn.execute("""
            SELECT COUNT(*) AS total
            FROM sugestao_votes
            WHERE sugestao_id = ? AND voto = 'concordo'
        """, (sugestao_id,)).fetchone()["total"]

        discordo = conn.execute("""
            SELECT COUNT(*) AS total
            FROM sugestao_votes
            WHERE sugestao_id = ? AND voto = 'discordo'
        """, (sugestao_id,)).fetchone()["total"]

        return concordo, discordo


def listar_votos(sugestao_id: int):
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT user_id, voto
            FROM sugestao_votes
            WHERE sugestao_id = ?
            ORDER BY atualizado_em ASC
        """, (sugestao_id,)).fetchall()

        concordaram = []
        discordaram = []

        for row in rows:
            if row["voto"] == "concordo":
                concordaram.append(row["user_id"])
            elif row["voto"] == "discordo":
                discordaram.append(row["user_id"])

        return concordaram, discordaram


def cortar_texto(texto: str, limite: int = 1000) -> str:
    if len(texto) <= limite:
        return texto

    return texto[:limite - 3] + "..."


def formatar_porcentagem(valor: int, total: int) -> int:
    if total <= 0:
        return 0

    return round((valor / total) * 100)


def formatar_lista_usuarios(ids: list[int]) -> str:
    if not ids:
        return "Ninguém votou."

    texto = "\n".join(f"<@{user_id}>" for user_id in ids)
    return cortar_texto(texto, 1000)


def criar_embed_sugestao(sugestao, thread: Optional[discord.Thread] = None):
    criado_em = datetime.fromisoformat(sugestao["criado_em"])
    data_formatada = discord.utils.format_dt(criado_em, style="f")

    embed = create_embed(
        title=f"Sugestão #{sugestao['id']}",
        description=cortar_texto(sugestao["texto"], 3900)
    )

    embed.add_field(
        name="Enviada por",
        value=f"<@{sugestao['author_id']}> • {data_formatada}",
        inline=False
    )

    if thread:
        embed.add_field(
            name="Debate",
            value=thread.mention,
            inline=False
        )
    elif sugestao["thread_id"]:
        embed.add_field(
            name="Debate",
            value=f"<#{sugestao['thread_id']}>",
            inline=False
        )

    return embed


class SugestaoView(discord.ui.View):
    def __init__(self, sugestao_id: Optional[int] = None):
        super().__init__(timeout=None)

        self.sugestao_id = sugestao_id
        self.atualizar_botoes()

    def atualizar_botoes(self):
        concordo = 0
        discordo = 0

        if self.sugestao_id:
            concordo, discordo = contar_votos(self.sugestao_id)

        total = concordo + discordo

        pct_concordo = formatar_porcentagem(concordo, total)
        pct_discordo = formatar_porcentagem(discordo, total)

        for item in self.children:
            if item.custom_id == "sugestao_concordo":
                item.label = f"Concordo {pct_concordo}% • {concordo}"

            elif item.custom_id == "sugestao_discordo":
                item.label = f"Discordo {pct_discordo}% • {discordo}"

            elif item.custom_id == "sugestao_total":
                item.label = f"Total de votos {total}"

    async def votar(self, interaction: discord.Interaction, voto: str):
        if not interaction.guild or not interaction.message:
            await interaction.response.send_message(
                "❌ Não consegui identificar essa sugestão.",
                ephemeral=True
            )
            return

        sugestao = buscar_sugestao_por_message_id(
            interaction.guild.id,
            interaction.message.id
        )

        if not sugestao:
            await interaction.response.send_message(
                "❌ Sugestão não encontrada no banco de dados.",
                ephemeral=True
            )
            return

        registrar_voto(
            sugestao_id=sugestao["id"],
            user_id=interaction.user.id,
            voto=voto
        )

        sugestao_atualizada = buscar_sugestao_por_id(sugestao["id"])

        embed = criar_embed_sugestao(sugestao_atualizada)
        view = SugestaoView(sugestao["id"])

        await interaction.response.edit_message(
            embed=embed,
            view=view
        )

    @discord.ui.button(
        label="Concordo 0% • 0",
        style=discord.ButtonStyle.success,
        custom_id="sugestao_concordo"
    )
    async def concordo(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        await self.votar(interaction, "concordo")

    @discord.ui.button(
        label="Discordo 0% • 0",
        style=discord.ButtonStyle.danger,
        custom_id="sugestao_discordo"
    )
    async def discordo(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        await self.votar(interaction, "discordo")

    @discord.ui.button(
        label="Total de votos 0",
        style=discord.ButtonStyle.secondary,
        custom_id="sugestao_total",
        disabled=True
    )
    async def total(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        pass

    @discord.ui.button(
        label="Ver votos",
        emoji="👀",
        style=discord.ButtonStyle.primary,
        custom_id="sugestao_ver_votos"
    )
    async def ver_votos(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        if not interaction.guild or not interaction.message:
            await interaction.response.send_message(
                "❌ Não consegui identificar essa sugestão.",
                ephemeral=True
            )
            return

        permissoes = interaction.user.guild_permissions

        if not permissoes.administrator and not permissoes.manage_guild:
            await interaction.response.send_message(
                "❌ Apenas administradores podem ver quem votou.",
                ephemeral=True
            )
            return

        sugestao = buscar_sugestao_por_message_id(
            interaction.guild.id,
            interaction.message.id
        )

        if not sugestao:
            await interaction.response.send_message(
                "❌ Sugestão não encontrada no banco de dados.",
                ephemeral=True
            )
            return

        concordaram, discordaram = listar_votos(sugestao["id"])

        embed = create_embed(
            title=f"👀 Votos da Sugestão #{sugestao['id']}",
            description="Lista de pessoas que votaram."
        )

        embed.add_field(
            name=f"Concordaram ({len(concordaram)})",
            value=formatar_lista_usuarios(concordaram),
            inline=False
        )

        embed.add_field(
            name=f"Discordaram ({len(discordaram)})",
            value=formatar_lista_usuarios(discordaram),
            inline=False
        )

        await interaction.response.send_message(
            embed=embed,
            ephemeral=True
        )


class Sugestoes(commands.Cog):
    config_sugestao = app_commands.Group(
        name="config_sugestao",
        description="Configura o sistema de sugestões."
    )

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        init_db()

        try:
            self.bot.add_view(SugestaoView())
        except ValueError:
            pass

    @config_sugestao.command(
        name="canal",
        description="Define o canal onde as pessoas vão enviar sugestões."
    )
    @app_commands.default_permissions(manage_guild=True)
    async def config_canal(
        self,
        interaction: discord.Interaction,
        canal: discord.TextChannel
    ):
        await interaction.response.defer(ephemeral=True)

        if interaction.guild is None:
            await interaction.followup.send(
                "❌ Esse comando só pode ser usado dentro de um servidor.",
                ephemeral=True
            )
            return

        try:
            set_config_canal(interaction.guild.id, canal.id)

            await interaction.followup.send(
                f"✅ Canal de sugestões configurado para {canal.mention}.",
                ephemeral=True
            )

        except Exception as error:
            print(f"[ERRO] /config_sugestao canal: {error}")

            await interaction.followup.send(
                "❌ Deu erro ao salvar o canal de sugestões. Olha o terminal.",
                ephemeral=True
            )

    @config_sugestao.command(
        name="listar",
        description="Mostra o canal de sugestões configurado."
    )
    @app_commands.default_permissions(manage_guild=True)
    async def listar_config(
        self,
        interaction: discord.Interaction
    ):
        await interaction.response.defer(ephemeral=True)

        if interaction.guild is None:
            await interaction.followup.send(
                "❌ Esse comando só pode ser usado dentro de um servidor.",
                ephemeral=True
            )
            return

        try:
            canal_id = get_config_canal(interaction.guild.id)

            canal_texto = f"<#{canal_id}>" if canal_id else "Não configurado"

            embed = create_embed(
                title="⚙️ Configuração de Sugestões",
                description="Configuração atual do sistema."
            )

            embed.add_field(
                name="Canal de sugestões",
                value=canal_texto,
                inline=False
            )

            await interaction.followup.send(
                embed=embed,
                ephemeral=True
            )

        except Exception as error:
            print(f"[ERRO] /config_sugestao listar: {error}")

            await interaction.followup.send(
                "❌ Deu erro ao listar a configuração. Olha o terminal.",
                ephemeral=True
            )

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        if not message.guild:
            return

        canal_configurado_id = get_config_canal(message.guild.id)

        if not canal_configurado_id:
            return

        if message.channel.id != canal_configurado_id:
            return

        texto = message.content.strip()

        try:
            await message.delete()
        except discord.Forbidden:
            print("[ERRO] Sem permissão para apagar mensagem no canal de sugestões.")
        except discord.HTTPException:
            pass

        if not texto:
            try:
                aviso = await message.channel.send(
                    f"{message.author.mention}, envie uma sugestão em texto.",
                    allowed_mentions=discord.AllowedMentions(users=True)
                )

                await aviso.delete(delay=8)

            except discord.HTTPException:
                pass

            return

        try:
            sugestao_id = criar_sugestao(
                guild_id=message.guild.id,
                channel_id=message.channel.id,
                author_id=message.author.id,
                texto=texto
            )

            sugestao = buscar_sugestao_por_id(sugestao_id)

            embed = criar_embed_sugestao(sugestao)
            view = SugestaoView(sugestao_id)

            sugestao_msg = await message.channel.send(
                embed=embed,
                view=view
            )

            atualizar_sugestao_msg_thread(
                sugestao_id=sugestao_id,
                message_id=sugestao_msg.id
            )

            thread = await sugestao_msg.create_thread(
                name=f"Sugestão #{sugestao_id}",
                auto_archive_duration=1440,
                reason="Tópico criado automaticamente para debate da sugestão."
            )

            atualizar_sugestao_msg_thread(
                sugestao_id=sugestao_id,
                thread_id=thread.id
            )

            sugestao_atualizada = buscar_sugestao_por_id(sugestao_id)

            embed_atualizada = criar_embed_sugestao(
                sugestao_atualizada,
                thread=thread
            )

            await sugestao_msg.edit(
                embed=embed_atualizada,
                view=SugestaoView(sugestao_id)
            )

            await thread.send(
                f"Espaço aberto para debater a sugestão #{sugestao_id}.\n"
                "Mantenham a conversa organizada e objetiva."
            )

        except discord.Forbidden:
            await message.channel.send(
                "❌ Não tenho permissão para apagar mensagens, enviar embed ou criar tópicos neste canal."
            )

        except discord.HTTPException as error:
            print(f"[ERRO] HTTP ao criar sugestão: {error}")

            await message.channel.send(
                "❌ Ocorreu um erro ao tentar criar a sugestão."
            )

        except Exception as error:
            print(f"[ERRO] Erro inesperado no sistema de sugestões: {error}")

            await message.channel.send(
                "❌ Deu erro interno ao criar a sugestão. Olha o terminal."
            )


async def setup(bot: commands.Bot):
    await bot.add_cog(Sugestoes(bot))