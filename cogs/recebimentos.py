import sqlite3
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks

from utils.embeds import create_embed


VENDAS_DB_PATH = Path("data/vendas.db")
RECEBIMENTOS_DB_PATH = Path("data/recebimentos.db")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_conn(db_path: Path):
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    return conn


def init_db():
    with get_conn(RECEBIMENTOS_DB_PATH) as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS recebimento_config (
                guild_id INTEGER PRIMARY KEY,
                webhook_url TEXT,
                destino_guild_id TEXT,
                destino_channel_id TEXT,
                ativo INTEGER NOT NULL DEFAULT 0,
                atualizado_em TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS recebimento_enviados (
                venda_id INTEGER PRIMARY KEY,
                enviado_em TEXT NOT NULL,
                webhook_message_id TEXT
            );
        """)
        conn.commit()


def ensure_config(guild_id: int):
    with get_conn(RECEBIMENTOS_DB_PATH) as conn:
        conn.execute("""
            INSERT OR IGNORE INTO recebimento_config (
                guild_id,
                ativo,
                atualizado_em
            )
            VALUES (?, 0, ?)
        """, (guild_id, now_iso()))
        conn.commit()


def set_webhook(guild_id: int, webhook_url: str):
    ensure_config(guild_id)

    with get_conn(RECEBIMENTOS_DB_PATH) as conn:
        conn.execute("""
            UPDATE recebimento_config
            SET webhook_url = ?,
                atualizado_em = ?
            WHERE guild_id = ?
        """, (webhook_url, now_iso(), guild_id))
        conn.commit()


def set_destino(guild_id: int, destino_guild_id: str, destino_channel_id: str):
    ensure_config(guild_id)

    with get_conn(RECEBIMENTOS_DB_PATH) as conn:
        conn.execute("""
            UPDATE recebimento_config
            SET destino_guild_id = ?,
                destino_channel_id = ?,
                atualizado_em = ?
            WHERE guild_id = ?
        """, (
            destino_guild_id,
            destino_channel_id,
            now_iso(),
            guild_id
        ))
        conn.commit()


def set_ativo(guild_id: int, ativo: bool):
    ensure_config(guild_id)

    with get_conn(RECEBIMENTOS_DB_PATH) as conn:
        conn.execute("""
            UPDATE recebimento_config
            SET ativo = ?,
                atualizado_em = ?
            WHERE guild_id = ?
        """, (1 if ativo else 0, now_iso(), guild_id))
        conn.commit()


def get_config(guild_id: int):
    with get_conn(RECEBIMENTOS_DB_PATH) as conn:
        return conn.execute("""
            SELECT *
            FROM recebimento_config
            WHERE guild_id = ?
            LIMIT 1
        """, (guild_id,)).fetchone()


def venda_ja_enviada(venda_id: int) -> bool:
    with get_conn(RECEBIMENTOS_DB_PATH) as conn:
        row = conn.execute("""
            SELECT venda_id
            FROM recebimento_enviados
            WHERE venda_id = ?
            LIMIT 1
        """, (venda_id,)).fetchone()

        return row is not None


def marcar_venda_enviada(
    venda_id: int,
    webhook_message_id: Optional[str] = None
):
    with get_conn(RECEBIMENTOS_DB_PATH) as conn:
        conn.execute("""
            INSERT OR REPLACE INTO recebimento_enviados (
                venda_id,
                enviado_em,
                webhook_message_id
            )
            VALUES (?, ?, ?)
        """, (
            venda_id,
            now_iso(),
            webhook_message_id
        ))
        conn.commit()


def marcar_vendas_antigas_como_ignoradas(guild_id: int) -> int:
    if not VENDAS_DB_PATH.exists():
        return 0

    try:
        with get_conn(VENDAS_DB_PATH) as conn:
            vendas = conn.execute("""
                SELECT id
                FROM vendas
                WHERE guild_id = ?
                ORDER BY id ASC
            """, (guild_id,)).fetchall()

        total = 0

        for venda in vendas:
            venda_id = venda["id"]

            if venda_ja_enviada(venda_id):
                continue

            marcar_venda_enviada(
                venda_id=venda_id,
                webhook_message_id="ignorada_antes_da_ativacao"
            )

            total += 1

        return total

    except sqlite3.OperationalError as error:
        print(f"[RECEBIMENTO] Erro ao ignorar vendas antigas: {error}")
        return 0


def buscar_vendas_pendentes(guild_id: int):
    if not VENDAS_DB_PATH.exists():
        return []

    try:
        with get_conn(VENDAS_DB_PATH) as conn:
            rows = conn.execute("""
                SELECT *
                FROM vendas
                WHERE guild_id = ?
                ORDER BY id ASC
            """, (guild_id,)).fetchall()

        vendas = []

        for row in rows:
            if not venda_ja_enviada(row["id"]):
                vendas.append(row)

            if len(vendas) >= 20:
                break

        return vendas

    except sqlite3.OperationalError as error:
        print(f"[RECEBIMENTO] Erro ao ler vendas.db: {error}")
        return []


def buscar_venda_por_id(venda_id: int):
    if not VENDAS_DB_PATH.exists():
        return None

    try:
        with get_conn(VENDAS_DB_PATH) as conn:
            return conn.execute("""
                SELECT *
                FROM vendas
                WHERE id = ?
                LIMIT 1
            """, (venda_id,)).fetchone()

    except sqlite3.OperationalError:
        return None


def buscar_itens_venda(venda_id: int):
    if not VENDAS_DB_PATH.exists():
        return []

    try:
        with get_conn(VENDAS_DB_PATH) as conn:
            return conn.execute("""
                SELECT *
                FROM venda_itens
                WHERE venda_id = ?
                ORDER BY id ASC
            """, (venda_id,)).fetchall()

    except sqlite3.OperationalError:
        return []


def obter_campo(row, campo: str, padrao=None):
    try:
        if campo in row.keys():
            return row[campo]
    except Exception:
        pass

    return padrao


def formatar_dinheiro(valor: float) -> str:
    valor_formatado = f"{valor:,.2f}"
    valor_formatado = valor_formatado.replace(",", "X")
    valor_formatado = valor_formatado.replace(".", ",")
    valor_formatado = valor_formatado.replace("X", ".")

    return f"R$ {valor_formatado}"


def cortar_texto(texto: str, limite: int = 1000) -> str:
    if not texto:
        return "Não informado"

    if len(texto) <= limite:
        return texto

    return texto[:limite - 3] + "..."


def montar_texto_itens_recebimento(itens) -> str:
    if not itens:
        return "Não informado"

    linhas = []

    for item in itens:
        nome = str(item["produto_nome"])[:18]
        quantidade = str(item["quantidade"])

        valor_unitario = formatar_dinheiro(float(item["valor_unitario"]))
        subtotal = formatar_dinheiro(float(item["subtotal"]))

        linhas.append(
            f"{nome:<18} x{quantidade:<4} {valor_unitario:<15} {subtotal}"
        )

    texto = "\n".join(linhas)

    return f"```{texto}```"


def montar_embed_recebimento(venda, itens):
    tipo = obter_campo(venda, "tipo", "pista")
    tipo_nome = "Parceria" if tipo == "parceria" else "Pista"

    if tipo == "parceria":
        fac = obter_campo(venda, "fac_parceira", None) or "Parceria não informada"
        produto_parceria = obter_campo(venda, "produto_parceria", None)

        if produto_parceria:
            organizacao = f"{fac} — {produto_parceria}"
        else:
            organizacao = fac
    else:
        organizacao = "Pista"

    embed = create_embed(
        title=f"Relatório de Venda #{venda['id']}",
        description=f"Tipo de venda: {tipo_nome}"
    )

    embed.add_field(
        name="Organização",
        value=cortar_texto(organizacao, 1000),
        inline=False
    )

    embed.add_field(
        name="Produtos vendidos",
        value=montar_texto_itens_recebimento(itens),
        inline=False
    )

    embed.add_field(
        name="Responsáveis pela venda",
        value=cortar_texto(venda["responsaveis"], 1000),
        inline=False
    )

    embed.add_field(
        name="Resumo financeiro",
        value=f"Valor total: **{formatar_dinheiro(float(venda['valor_total']))}**",
        inline=False
    )

    return embed


async def enviar_webhook(webhook_url: str, embed: discord.Embed):
    async with aiohttp.ClientSession() as session:
        webhook = discord.Webhook.from_url(
            webhook_url,
            session=session
        )

        mensagem = await webhook.send(
            embed=embed,
            wait=True
        )

        return mensagem


class WebhookRecebimentoModal(discord.ui.Modal, title="Configurar Webhook"):
    webhook_url = discord.ui.TextInput(
        label="URL do webhook",
        placeholder="Cole aqui o webhook do canal de destino",
        style=discord.TextStyle.paragraph,
        max_length=500,
        required=True
    )

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.guild is None:
            await interaction.response.send_message(
                "Esse comando só pode ser usado dentro de um servidor.",
                ephemeral=True
            )
            return

        url = str(self.webhook_url.value).strip()

        if not (
            url.startswith("https://discord.com/api/webhooks/")
            or url.startswith("https://discordapp.com/api/webhooks/")
        ):
            await interaction.response.send_message(
                "Webhook inválido. Confira se você copiou a URL completa do webhook.",
                ephemeral=True
            )
            return

        set_webhook(interaction.guild.id, url)

        await interaction.response.send_message(
            "Webhook de recebimento configurado com sucesso.",
            ephemeral=True
        )


class Recebimentos(commands.Cog):
    config_recebimento = app_commands.Group(
        name="config_recebimento",
        description="Configura o envio de recebimentos por webhook."
    )

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        init_db()
        self.verificar_recebimentos.start()

    def cog_unload(self):
        self.verificar_recebimentos.cancel()

    @config_recebimento.command(
        name="webhook",
        description="Abre um modal para configurar o webhook de recebimento."
    )
    @app_commands.default_permissions(manage_guild=True)
    async def webhook(
        self,
        interaction: discord.Interaction
    ):
        await interaction.response.send_modal(WebhookRecebimentoModal())

    @config_recebimento.command(
        name="destino",
        description="Salva o ID do servidor e canal de destino apenas para controle."
    )
    @app_commands.default_permissions(manage_guild=True)
    async def destino(
        self,
        interaction: discord.Interaction,
        servidor_id: str,
        canal_id: str
    ):
        await interaction.response.defer(ephemeral=True)

        if interaction.guild is None:
            await interaction.followup.send(
                "Esse comando só pode ser usado dentro de um servidor.",
                ephemeral=True
            )
            return

        set_destino(
            guild_id=interaction.guild.id,
            destino_guild_id=servidor_id,
            destino_channel_id=canal_id
        )

        await interaction.followup.send(
            "Destino de recebimento salvo com sucesso.",
            ephemeral=True
        )

    @config_recebimento.command(
        name="ativar",
        description="Ativa o envio automático ignorando vendas antigas."
    )
    @app_commands.default_permissions(manage_guild=True)
    async def ativar(
        self,
        interaction: discord.Interaction
    ):
        await interaction.response.defer(ephemeral=True)

        if interaction.guild is None:
            await interaction.followup.send(
                "Esse comando só pode ser usado dentro de um servidor.",
                ephemeral=True
            )
            return

        config = get_config(interaction.guild.id)

        if not config or not config["webhook_url"]:
            await interaction.followup.send(
                "Configure o webhook primeiro com /config_recebimento webhook.",
                ephemeral=True
            )
            return

        ignoradas = marcar_vendas_antigas_como_ignoradas(interaction.guild.id)

        set_ativo(interaction.guild.id, True)

        await interaction.followup.send(
            f"Envio automático de recebimentos ativado.\n"
            f"Vendas antigas ignoradas: **{ignoradas}**.\n"
            f"A partir de agora, somente vendas novas serão enviadas.",
            ephemeral=True
        )

    @config_recebimento.command(
        name="desativar",
        description="Desativa o envio automático de recebimentos."
    )
    @app_commands.default_permissions(manage_guild=True)
    async def desativar(
        self,
        interaction: discord.Interaction
    ):
        await interaction.response.defer(ephemeral=True)

        if interaction.guild is None:
            await interaction.followup.send(
                "Esse comando só pode ser usado dentro de um servidor.",
                ephemeral=True
            )
            return

        set_ativo(interaction.guild.id, False)

        await interaction.followup.send(
            "Envio automático de recebimentos desativado.",
            ephemeral=True
        )

    @config_recebimento.command(
        name="listar",
        description="Mostra a configuração atual do recebimento."
    )
    @app_commands.default_permissions(manage_guild=True)
    async def listar(
        self,
        interaction: discord.Interaction
    ):
        await interaction.response.defer(ephemeral=True)

        if interaction.guild is None:
            await interaction.followup.send(
                "Esse comando só pode ser usado dentro de um servidor.",
                ephemeral=True
            )
            return

        config = get_config(interaction.guild.id)

        webhook_status = "Não configurado"
        destino_servidor = "Não configurado"
        destino_canal = "Não configurado"
        status = "Desativado"

        if config:
            if config["webhook_url"]:
                webhook_status = "Configurado"

            if config["destino_guild_id"]:
                destino_servidor = config["destino_guild_id"]

            if config["destino_channel_id"]:
                destino_canal = config["destino_channel_id"]

            status = "Ativo" if config["ativo"] == 1 else "Desativado"

        embed = create_embed(
            title="Configuração de Recebimento",
            description="Configuração atual do envio por webhook."
        )

        embed.add_field(name="Webhook", value=webhook_status, inline=False)
        embed.add_field(name="Servidor destino", value=destino_servidor, inline=False)
        embed.add_field(name="Canal destino", value=destino_canal, inline=False)
        embed.add_field(name="Status", value=status, inline=False)

        await interaction.followup.send(
            embed=embed,
            ephemeral=True
        )

    @config_recebimento.command(
        name="testar",
        description="Envia uma embed de teste para o webhook configurado."
    )
    @app_commands.default_permissions(manage_guild=True)
    async def testar(
        self,
        interaction: discord.Interaction
    ):
        await interaction.response.defer(ephemeral=True)

        if interaction.guild is None:
            await interaction.followup.send(
                "Esse comando só pode ser usado dentro de um servidor.",
                ephemeral=True
            )
            return

        config = get_config(interaction.guild.id)

        if not config or not config["webhook_url"]:
            await interaction.followup.send(
                "Configure o webhook primeiro com /config_recebimento webhook.",
                ephemeral=True
            )
            return

        itens_teste = [
            {
                "produto_nome": "Algema",
                "quantidade": 4,
                "valor_unitario": 12000,
                "subtotal": 48000
            },
            {
                "produto_nome": "Corda",
                "quantidade": 4,
                "valor_unitario": 5000,
                "subtotal": 20000
            }
        ]

        embed = create_embed(
            title="Relatório de Venda #TESTE",
            description="Tipo de venda: Pista"
        )

        embed.add_field(
            name="Organização",
            value="Pista",
            inline=False
        )

        embed.add_field(
            name="Produtos vendidos",
            value=montar_texto_itens_recebimento(itens_teste),
            inline=False
        )

        embed.add_field(
            name="Responsáveis pela venda",
            value="Ana",
            inline=False
        )

        embed.add_field(
            name="Resumo financeiro",
            value="Valor total: **R$ 68.000,00**",
            inline=False
        )

        try:
            await enviar_webhook(config["webhook_url"], embed)

            await interaction.followup.send(
                "Teste enviado com sucesso.",
                ephemeral=True
            )

        except Exception as error:
            print(f"[RECEBIMENTO] Erro ao testar webhook: {error}")

            await interaction.followup.send(
                "Erro ao enviar teste pelo webhook. Confira a URL.",
                ephemeral=True
            )

    @app_commands.command(
        name="recebimento_reenviar",
        description="Reenvia manualmente uma venda para o webhook de recebimento."
    )
    @app_commands.default_permissions(manage_guild=True)
    async def recebimento_reenviar(
        self,
        interaction: discord.Interaction,
        venda_id: int
    ):
        await interaction.response.defer(ephemeral=True)

        if interaction.guild is None:
            await interaction.followup.send(
                "Esse comando só pode ser usado dentro de um servidor.",
                ephemeral=True
            )
            return

        config = get_config(interaction.guild.id)

        if not config or not config["webhook_url"]:
            await interaction.followup.send(
                "Configure o webhook primeiro com /config_recebimento webhook.",
                ephemeral=True
            )
            return

        venda = buscar_venda_por_id(venda_id)

        if not venda:
            await interaction.followup.send(
                "Venda não encontrada.",
                ephemeral=True
            )
            return

        itens = buscar_itens_venda(venda_id)
        embed = montar_embed_recebimento(venda, itens)

        try:
            mensagem = await enviar_webhook(config["webhook_url"], embed)
            marcar_venda_enviada(venda_id, str(mensagem.id))

            await interaction.followup.send(
                f"Venda #{venda_id} reenviada com sucesso.",
                ephemeral=True
            )

        except Exception as error:
            print(f"[RECEBIMENTO] Erro ao reenviar venda #{venda_id}: {error}")

            await interaction.followup.send(
                "Erro ao reenviar a venda pelo webhook.",
                ephemeral=True
            )

    @tasks.loop(seconds=30)
    async def verificar_recebimentos(self):
        for guild in self.bot.guilds:
            config = get_config(guild.id)

            if not config:
                continue

            if config["ativo"] != 1:
                continue

            if not config["webhook_url"]:
                continue

            vendas = buscar_vendas_pendentes(guild.id)

            for venda in vendas:
                itens = buscar_itens_venda(venda["id"])
                embed = montar_embed_recebimento(venda, itens)

                try:
                    mensagem = await enviar_webhook(
                        webhook_url=config["webhook_url"],
                        embed=embed
                    )

                    marcar_venda_enviada(
                        venda_id=venda["id"],
                        webhook_message_id=str(mensagem.id)
                    )

                    print(f"[RECEBIMENTO] Venda #{venda['id']} enviada pelo webhook.")

                except Exception as error:
                    print(f"[RECEBIMENTO] Erro ao enviar venda #{venda['id']}: {error}")

    @verificar_recebimentos.before_loop
    async def before_verificar_recebimentos(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(Recebimentos(bot))