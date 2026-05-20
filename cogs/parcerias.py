import sqlite3
from pathlib import Path
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands

from utils.embeds import create_embed


DB_PATH = Path("data/parcerias.db")


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
            CREATE TABLE IF NOT EXISTS parcerias (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome_fac TEXT NOT NULL UNIQUE COLLATE NOCASE,
                produto TEXT NOT NULL,
                ativo INTEGER NOT NULL DEFAULT 1,
                criado_por INTEGER NOT NULL,
                criado_em TEXT NOT NULL,
                atualizado_em TEXT NOT NULL
            );
        """)
        conn.commit()


def criar_parceria(nome_fac: str, produto: str, criado_por: int):
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO parcerias (
                nome_fac, produto, ativo, criado_por, criado_em, atualizado_em
            )
            VALUES (?, ?, 1, ?, ?, ?)
        """, (
            nome_fac,
            produto,
            criado_por,
            now_iso(),
            now_iso()
        ))
        conn.commit()


def buscar_parceria(nome_fac: str):
    with get_conn() as conn:
        return conn.execute("""
            SELECT *
            FROM parcerias
            WHERE LOWER(nome_fac) = LOWER(?)
            LIMIT 1
        """, (nome_fac,)).fetchone()


def listar_parcerias(ativos_apenas: bool = True):
    with get_conn() as conn:
        if ativos_apenas:
            return conn.execute("""
                SELECT *
                FROM parcerias
                WHERE ativo = 1
                ORDER BY nome_fac ASC
            """).fetchall()

        return conn.execute("""
            SELECT *
            FROM parcerias
            ORDER BY nome_fac ASC
        """).fetchall()


def atualizar_parceria(
    parceria_id: int,
    nome_fac: str,
    produto: str
):
    with get_conn() as conn:
        conn.execute("""
            UPDATE parcerias
            SET nome_fac = ?,
                produto = ?,
                ativo = 1,
                atualizado_em = ?
            WHERE id = ?
        """, (
            nome_fac,
            produto,
            now_iso(),
            parceria_id
        ))
        conn.commit()


def remover_parceria(parceria_id: int):
    with get_conn() as conn:
        conn.execute("""
            UPDATE parcerias
            SET ativo = 0,
                atualizado_em = ?
            WHERE id = ?
        """, (
            now_iso(),
            parceria_id
        ))
        conn.commit()


def cortar_texto(texto: str, limite: int = 3900) -> str:
    if len(texto) <= limite:
        return texto

    return texto[:limite - 3] + "..."


class ParceriaRegistroModal(discord.ui.Modal, title="Registrar Parceria"):
    nome_fac = discord.ui.TextInput(
        label="Nome da fac",
        placeholder="Ex: Los Santos Customs",
        max_length=80,
        required=True
    )

    produto = discord.ui.TextInput(
        label="Produto que essa fac trabalha",
        placeholder="Ex: Lockpick, Colete, Munição...",
        max_length=120,
        required=True
    )

    async def on_submit(self, interaction: discord.Interaction):
        nome_fac = str(self.nome_fac.value).strip()
        produto = str(self.produto.value).strip()

        if not nome_fac:
            await interaction.response.send_message(
                "❌ O nome da fac não pode ficar vazio.",
                ephemeral=True
            )
            return

        if not produto:
            await interaction.response.send_message(
                "❌ O produto não pode ficar vazio.",
                ephemeral=True
            )
            return

        parceria_existente = buscar_parceria(nome_fac)

        if parceria_existente and parceria_existente["ativo"] == 1:
            await interaction.response.send_message(
                "❌ Essa fac já está registrada como parceria.",
                ephemeral=True
            )
            return

        try:
            if parceria_existente:
                atualizar_parceria(
                    parceria_id=parceria_existente["id"],
                    nome_fac=nome_fac,
                    produto=produto
                )
            else:
                criar_parceria(
                    nome_fac=nome_fac,
                    produto=produto,
                    criado_por=interaction.user.id
                )

            embed = create_embed(
                title="✅ Parceria registrada",
                description="A parceria foi salva com sucesso."
            )

            embed.add_field(
                name="Fac",
                value=nome_fac,
                inline=True
            )

            embed.add_field(
                name="Produto",
                value=produto,
                inline=True
            )

            await interaction.response.send_message(
                embed=embed,
                ephemeral=True
            )

        except sqlite3.IntegrityError:
            await interaction.response.send_message(
                "❌ Já existe uma parceria registrada com esse nome.",
                ephemeral=True
            )


class ParceriaAlterarModal(discord.ui.Modal, title="Alterar Parceria"):
    def __init__(self, parceria):
        super().__init__()

        self.parceria = parceria

        self.nome_fac.default = parceria["nome_fac"]
        self.produto.default = parceria["produto"]

    nome_fac = discord.ui.TextInput(
        label="Nome da fac",
        placeholder="Ex: Los Santos Customs",
        max_length=80,
        required=True
    )

    produto = discord.ui.TextInput(
        label="Produto que essa fac trabalha",
        placeholder="Ex: Lockpick, Colete, Munição...",
        max_length=120,
        required=True
    )

    async def on_submit(self, interaction: discord.Interaction):
        nome_fac = str(self.nome_fac.value).strip()
        produto = str(self.produto.value).strip()

        if not nome_fac:
            await interaction.response.send_message(
                "❌ O nome da fac não pode ficar vazio.",
                ephemeral=True
            )
            return

        if not produto:
            await interaction.response.send_message(
                "❌ O produto não pode ficar vazio.",
                ephemeral=True
            )
            return

        parceria_mesmo_nome = buscar_parceria(nome_fac)

        if (
            parceria_mesmo_nome
            and parceria_mesmo_nome["id"] != self.parceria["id"]
            and parceria_mesmo_nome["ativo"] == 1
        ):
            await interaction.response.send_message(
                "❌ Já existe outra parceria com esse nome.",
                ephemeral=True
            )
            return

        try:
            atualizar_parceria(
                parceria_id=self.parceria["id"],
                nome_fac=nome_fac,
                produto=produto
            )

            embed = create_embed(
                title="✅ Parceria alterada",
                description="As informações da parceria foram atualizadas."
            )

            embed.add_field(
                name="Fac",
                value=nome_fac,
                inline=True
            )

            embed.add_field(
                name="Produto",
                value=produto,
                inline=True
            )

            await interaction.response.send_message(
                embed=embed,
                ephemeral=True
            )

        except sqlite3.IntegrityError:
            await interaction.response.send_message(
                "❌ Já existe uma parceria registrada com esse nome.",
                ephemeral=True
            )


class Parcerias(commands.Cog):
    parceria = app_commands.Group(
        name="parceria",
        description="Gerencia as parcerias da fac."
    )

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        init_db()

    @parceria.command(
        name="registrar",
        description="Abre um modal para registrar uma parceria."
    )
    @app_commands.default_permissions(manage_guild=True)
    async def registrar(
        self,
        interaction: discord.Interaction
    ):
        await interaction.response.send_modal(ParceriaRegistroModal())

    @parceria.command(
        name="alterar",
        description="Abre um modal para alterar uma parceria."
    )
    @app_commands.default_permissions(manage_guild=True)
    async def alterar(
        self,
        interaction: discord.Interaction,
        nome_fac: str
    ):
        parceria = buscar_parceria(nome_fac)

        if not parceria or parceria["ativo"] == 0:
            await interaction.response.send_message(
                "❌ Parceria não encontrada ou está removida.",
                ephemeral=True
            )
            return

        await interaction.response.send_modal(
            ParceriaAlterarModal(parceria)
        )

    @parceria.command(
        name="remover",
        description="Remove uma parceria da lista ativa."
    )
    @app_commands.default_permissions(manage_guild=True)
    async def remover(
        self,
        interaction: discord.Interaction,
        nome_fac: str
    ):
        parceria = buscar_parceria(nome_fac)

        if not parceria or parceria["ativo"] == 0:
            await interaction.response.send_message(
                "❌ Parceria não encontrada ou já está removida.",
                ephemeral=True
            )
            return

        remover_parceria(parceria["id"])

        await interaction.response.send_message(
            f"✅ Parceria **{parceria['nome_fac']}** removida da lista ativa.",
            ephemeral=True
        )

    @parceria.command(
        name="consultar",
        description="Consulta o produto de uma parceria."
    )
    async def consultar(
        self,
        interaction: discord.Interaction,
        nome_fac: str
    ):
        parceria = buscar_parceria(nome_fac)

        if not parceria or parceria["ativo"] == 0:
            await interaction.response.send_message(
                "❌ Parceria não encontrada.",
                ephemeral=True
            )
            return

        embed = create_embed(
            title=f"🤝 {parceria['nome_fac']}",
            description="Informações da parceria registrada."
        )

        embed.add_field(
            name="Fac",
            value=parceria["nome_fac"],
            inline=True
        )

        embed.add_field(
            name="Produto",
            value=parceria["produto"],
            inline=True
        )

        await interaction.response.send_message(
            embed=embed,
            ephemeral=True
        )

    @parceria.command(
        name="listar",
        description="Lista todas as parcerias ativas."
    )
    async def listar(
        self,
        interaction: discord.Interaction
    ):
        parcerias = listar_parcerias(ativos_apenas=True)

        if not parcerias:
            await interaction.response.send_message(
                "❌ Nenhuma parceria registrada ainda.",
                ephemeral=True
            )
            return

        embed = create_embed(
            title="🤝 Parcerias registradas",
            description="Lista de facs parceiras e os produtos que elas trabalham."
        )

        texto = ""

        for parceria in parcerias:
            linha = (
                f"**{parceria['nome_fac']}** ➜ `{parceria['produto']}`\n"
            )

            if len(texto) + len(linha) > 3900:
                texto += "..."
                break

            texto += linha

        embed.add_field(
            name="Fac / Produto",
            value=cortar_texto(texto),
            inline=False
        )

        await interaction.response.send_message(
            embed=embed,
            ephemeral=True
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Parcerias(bot))