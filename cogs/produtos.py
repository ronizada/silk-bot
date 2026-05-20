import sqlite3
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from utils.embeds import create_embed


DB_PATH = Path("data/produtos.db")


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
            CREATE TABLE IF NOT EXISTS produtos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome TEXT NOT NULL UNIQUE,
                valor_parceria REAL NOT NULL,
                valor_pista REAL NOT NULL,
                ativo INTEGER NOT NULL DEFAULT 1,
                criado_em TEXT NOT NULL,
                atualizado_em TEXT NOT NULL
            );
        """)
        conn.commit()


def converter_valor(valor: str) -> Optional[float]:
    valor = valor.strip()
    valor = valor.replace("R$", "")
    valor = valor.replace(" ", "")
    valor = valor.replace(".", "")
    valor = valor.replace(",", ".")

    try:
        numero = float(valor)

        if numero < 0:
            return None

        return numero

    except ValueError:
        return None


def formatar_dinheiro(valor: float) -> str:
    valor_formatado = f"{valor:,.2f}"
    valor_formatado = valor_formatado.replace(",", "X")
    valor_formatado = valor_formatado.replace(".", ",")
    valor_formatado = valor_formatado.replace("X", ".")

    return f"R$ {valor_formatado}"


def criar_produto(nome: str, valor_parceria: float, valor_pista: float):
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO produtos (
                nome, valor_parceria, valor_pista, ativo, criado_em, atualizado_em
            )
            VALUES (?, ?, ?, 1, ?, ?)
        """, (
            nome,
            valor_parceria,
            valor_pista,
            now_iso(),
            now_iso()
        ))
        conn.commit()


def buscar_produto(nome: str):
    with get_conn() as conn:
        return conn.execute("""
            SELECT *
            FROM produtos
            WHERE LOWER(nome) = LOWER(?)
            LIMIT 1
        """, (nome,)).fetchone()


def listar_produtos(ativos_apenas: bool = True):
    with get_conn() as conn:
        if ativos_apenas:
            return conn.execute("""
                SELECT *
                FROM produtos
                WHERE ativo = 1
                ORDER BY nome ASC
            """).fetchall()

        return conn.execute("""
            SELECT *
            FROM produtos
            ORDER BY nome ASC
        """).fetchall()


def atualizar_produto(
    produto_id: int,
    nome: str,
    valor_parceria: float,
    valor_pista: float
):
    with get_conn() as conn:
        conn.execute("""
            UPDATE produtos
            SET nome = ?,
                valor_parceria = ?,
                valor_pista = ?,
                ativo = 1,
                atualizado_em = ?
            WHERE id = ?
        """, (
            nome,
            valor_parceria,
            valor_pista,
            now_iso(),
            produto_id
        ))
        conn.commit()


def remover_produto(produto_id: int):
    with get_conn() as conn:
        conn.execute("""
            UPDATE produtos
            SET ativo = 0,
                atualizado_em = ?
            WHERE id = ?
        """, (
            now_iso(),
            produto_id
        ))
        conn.commit()


class ProdutoCadastroModal(discord.ui.Modal, title="Cadastrar Produto"):
    nome = discord.ui.TextInput(
        label="Nome do produto",
        placeholder="Ex: Lockpick",
        max_length=80,
        required=True
    )

    valor_parceria = discord.ui.TextInput(
        label="Valor parceria",
        placeholder="Ex: 15000 ou 15.000",
        max_length=20,
        required=True
    )

    valor_pista = discord.ui.TextInput(
        label="Valor pista",
        placeholder="Ex: 25000 ou 25.000",
        max_length=20,
        required=True
    )

    async def on_submit(self, interaction: discord.Interaction):
        nome = str(self.nome.value).strip()
        valor_parceria = converter_valor(str(self.valor_parceria.value))
        valor_pista = converter_valor(str(self.valor_pista.value))

        if not nome:
            await interaction.response.send_message(
                "❌ O nome do produto não pode ficar vazio.",
                ephemeral=True
            )
            return

        if valor_parceria is None:
            await interaction.response.send_message(
                "❌ Valor de parceria inválido. Use algo como `15000`, `15.000` ou `15000,50`.",
                ephemeral=True
            )
            return

        if valor_pista is None:
            await interaction.response.send_message(
                "❌ Valor de pista inválido. Use algo como `25000`, `25.000` ou `25000,50`.",
                ephemeral=True
            )
            return

        produto_existente = buscar_produto(nome)

        if produto_existente and produto_existente["ativo"] == 1:
            await interaction.response.send_message(
                "❌ Já existe um produto ativo com esse nome.",
                ephemeral=True
            )
            return

        try:
            if produto_existente:
                atualizar_produto(
                    produto_id=produto_existente["id"],
                    nome=nome,
                    valor_parceria=valor_parceria,
                    valor_pista=valor_pista
                )
            else:
                criar_produto(
                    nome=nome,
                    valor_parceria=valor_parceria,
                    valor_pista=valor_pista
                )

            embed = create_embed(
                title="✅ Produto cadastrado",
                description="O produto foi salvo com sucesso."
            )

            embed.add_field(name="Produto", value=nome, inline=False)
            embed.add_field(
                name="Valor parceria",
                value=formatar_dinheiro(valor_parceria),
                inline=True
            )
            embed.add_field(
                name="Valor pista",
                value=formatar_dinheiro(valor_pista),
                inline=True
            )

            await interaction.response.send_message(
                embed=embed,
                ephemeral=True
            )

        except sqlite3.IntegrityError:
            await interaction.response.send_message(
                "❌ Já existe um produto cadastrado com esse nome.",
                ephemeral=True
            )


class ProdutoAlterarModal(discord.ui.Modal, title="Alterar Produto"):
    def __init__(self, produto):
        super().__init__()

        self.produto = produto

        self.nome.default = produto["nome"]
        self.valor_parceria.default = str(produto["valor_parceria"])
        self.valor_pista.default = str(produto["valor_pista"])

    nome = discord.ui.TextInput(
        label="Nome do produto",
        placeholder="Ex: Lockpick",
        max_length=80,
        required=True
    )

    valor_parceria = discord.ui.TextInput(
        label="Valor parceria",
        placeholder="Ex: 15000 ou 15.000",
        max_length=20,
        required=True
    )

    valor_pista = discord.ui.TextInput(
        label="Valor pista",
        placeholder="Ex: 25000 ou 25.000",
        max_length=20,
        required=True
    )

    async def on_submit(self, interaction: discord.Interaction):
        nome = str(self.nome.value).strip()
        valor_parceria = converter_valor(str(self.valor_parceria.value))
        valor_pista = converter_valor(str(self.valor_pista.value))

        if not nome:
            await interaction.response.send_message(
                "❌ O nome do produto não pode ficar vazio.",
                ephemeral=True
            )
            return

        if valor_parceria is None:
            await interaction.response.send_message(
                "❌ Valor de parceria inválido.",
                ephemeral=True
            )
            return

        if valor_pista is None:
            await interaction.response.send_message(
                "❌ Valor de pista inválido.",
                ephemeral=True
            )
            return

        produto_com_mesmo_nome = buscar_produto(nome)

        if (
            produto_com_mesmo_nome
            and produto_com_mesmo_nome["id"] != self.produto["id"]
        ):
            await interaction.response.send_message(
                "❌ Já existe outro produto com esse nome.",
                ephemeral=True
            )
            return

        atualizar_produto(
            produto_id=self.produto["id"],
            nome=nome,
            valor_parceria=valor_parceria,
            valor_pista=valor_pista
        )

        embed = create_embed(
            title="✅ Produto alterado",
            description="As informações do produto foram atualizadas."
        )

        embed.add_field(name="Produto", value=nome, inline=False)
        embed.add_field(
            name="Valor parceria",
            value=formatar_dinheiro(valor_parceria),
            inline=True
        )
        embed.add_field(
            name="Valor pista",
            value=formatar_dinheiro(valor_pista),
            inline=True
        )

        await interaction.response.send_message(
            embed=embed,
            ephemeral=True
        )


class Produtos(commands.Cog):
    produto = app_commands.Group(
        name="produto",
        description="Gerencia os produtos da fac."
    )

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        init_db()

    @produto.command(
        name="cadastrar",
        description="Abre um modal para cadastrar um produto."
    )
    @app_commands.default_permissions(manage_guild=True)
    async def cadastrar(
        self,
        interaction: discord.Interaction
    ):
        await interaction.response.send_modal(ProdutoCadastroModal())

    @produto.command(
        name="alterar",
        description="Abre um modal para alterar um produto existente."
    )
    @app_commands.default_permissions(manage_guild=True)
    async def alterar(
        self,
        interaction: discord.Interaction,
        nome: str
    ):
        produto = buscar_produto(nome)

        if not produto or produto["ativo"] == 0:
            await interaction.response.send_message(
                "❌ Produto não encontrado ou está removido.",
                ephemeral=True
            )
            return

        await interaction.response.send_modal(ProdutoAlterarModal(produto))

    @produto.command(
        name="remover",
        description="Remove um produto da lista ativa."
    )
    @app_commands.default_permissions(manage_guild=True)
    async def remover(
        self,
        interaction: discord.Interaction,
        nome: str
    ):
        produto = buscar_produto(nome)

        if not produto or produto["ativo"] == 0:
            await interaction.response.send_message(
                "❌ Produto não encontrado ou já está removido.",
                ephemeral=True
            )
            return

        remover_produto(produto["id"])

        await interaction.response.send_message(
            f"✅ Produto **{produto['nome']}** removido da lista ativa.",
            ephemeral=True
        )

    @produto.command(
        name="consultar",
        description="Consulta os valores de um produto."
    )
    async def consultar(
        self,
        interaction: discord.Interaction,
        nome: str
    ):
        produto = buscar_produto(nome)

        if not produto or produto["ativo"] == 0:
            await interaction.response.send_message(
                "❌ Produto não encontrado.",
                ephemeral=True
            )
            return

        embed = create_embed(
            title=f"📦 {produto['nome']}",
            description="Valores cadastrados para esse produto."
        )

        embed.add_field(
            name="Valor parceria",
            value=formatar_dinheiro(produto["valor_parceria"]),
            inline=True
        )

        embed.add_field(
            name="Valor pista",
            value=formatar_dinheiro(produto["valor_pista"]),
            inline=True
        )

        await interaction.response.send_message(
            embed=embed,
            ephemeral=True
        )

    @produto.command(
        name="listar",
        description="Lista todos os produtos ativos."
    )
    async def listar(
        self,
        interaction: discord.Interaction
    ):
        produtos = listar_produtos(ativos_apenas=True)

        if not produtos:
            await interaction.response.send_message(
                "❌ Nenhum produto cadastrado ainda.",
                ephemeral=True
            )
            return

        embed = create_embed(
            title="📦 Produtos cadastrados",
            description="Lista de produtos ativos e seus valores."
        )

        texto = ""

        for produto in produtos:
            linha = (
                f"**{produto['nome']}**\n"
                f"Parceria: {formatar_dinheiro(produto['valor_parceria'])}\n"
                f"Pista: {formatar_dinheiro(produto['valor_pista'])}\n\n"
            )

            if len(texto) + len(linha) > 3900:
                texto += "..."
                break

            texto += linha

        embed.add_field(
            name="Produtos",
            value=texto,
            inline=False
        )

        await interaction.response.send_message(
            embed=embed,
            ephemeral=True
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Produtos(bot))