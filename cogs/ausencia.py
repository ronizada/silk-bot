import re
import sqlite3
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands, tasks

from utils.embeds import create_embed


DB_PATH = Path("data/ausencias.db")
BR_TZ = timezone(timedelta(hours=-3))


def now_dt() -> datetime:
    return datetime.now(BR_TZ)


def now_iso() -> str:
    return now_dt().isoformat()


def get_conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    return conn


def init_db():
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS ausencia_config (
                guild_id INTEGER PRIMARY KEY,
                painel_channel_id INTEGER,
                painel_message_id INTEGER,
                registro_channel_id INTEGER,
                cargo_id INTEGER
            );

            CREATE TABLE IF NOT EXISTS ausencias (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                nome TEXT NOT NULL,
                motivo TEXT NOT NULL,
                periodo_texto TEXT NOT NULL,
                inicio_em TEXT NOT NULL,
                fim_em TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'ativa',
                registro_channel_id INTEGER,
                registro_message_id INTEGER,
                criado_em TEXT NOT NULL,
                finalizado_em TEXT
            );
        """)
        conn.commit()


def get_config(guild_id: int):
    with get_conn() as conn:
        return conn.execute("""
            SELECT *
            FROM ausencia_config
            WHERE guild_id = ?
            LIMIT 1
        """, (guild_id,)).fetchone()


def ensure_config(guild_id: int):
    with get_conn() as conn:
        conn.execute("""
            INSERT OR IGNORE INTO ausencia_config (guild_id)
            VALUES (?)
        """, (guild_id,))
        conn.commit()


def set_painel_channel(guild_id: int, channel_id: int):
    ensure_config(guild_id)

    with get_conn() as conn:
        conn.execute("""
            UPDATE ausencia_config
            SET painel_channel_id = ?
            WHERE guild_id = ?
        """, (channel_id, guild_id))
        conn.commit()


def set_painel_message(guild_id: int, message_id: int):
    ensure_config(guild_id)

    with get_conn() as conn:
        conn.execute("""
            UPDATE ausencia_config
            SET painel_message_id = ?
            WHERE guild_id = ?
        """, (message_id, guild_id))
        conn.commit()


def set_registro_channel(guild_id: int, channel_id: int):
    ensure_config(guild_id)

    with get_conn() as conn:
        conn.execute("""
            UPDATE ausencia_config
            SET registro_channel_id = ?
            WHERE guild_id = ?
        """, (channel_id, guild_id))
        conn.commit()


def set_cargo(guild_id: int, cargo_id: int):
    ensure_config(guild_id)

    with get_conn() as conn:
        conn.execute("""
            UPDATE ausencia_config
            SET cargo_id = ?
            WHERE guild_id = ?
        """, (cargo_id, guild_id))
        conn.commit()


def criar_ausencia(
    guild_id: int,
    user_id: int,
    nome: str,
    motivo: str,
    periodo_texto: str,
    inicio_em: str,
    fim_em: str,
    registro_channel_id: Optional[int]
) -> int:
    with get_conn() as conn:
        cursor = conn.execute("""
            INSERT INTO ausencias (
                guild_id,
                user_id,
                nome,
                motivo,
                periodo_texto,
                inicio_em,
                fim_em,
                status,
                registro_channel_id,
                criado_em
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, 'ativa', ?, ?)
        """, (
            guild_id,
            user_id,
            nome,
            motivo,
            periodo_texto,
            inicio_em,
            fim_em,
            registro_channel_id,
            now_iso()
        ))

        conn.commit()
        return cursor.lastrowid


def atualizar_msg_registro(ausencia_id: int, message_id: int):
    with get_conn() as conn:
        conn.execute("""
            UPDATE ausencias
            SET registro_message_id = ?
            WHERE id = ?
        """, (message_id, ausencia_id))
        conn.commit()


def finalizar_ausencia(ausencia_id: int):
    with get_conn() as conn:
        conn.execute("""
            UPDATE ausencias
            SET status = 'finalizada',
                finalizado_em = ?
            WHERE id = ?
        """, (now_iso(), ausencia_id))
        conn.commit()


def buscar_ausencias_vencidas():
    agora = now_iso()

    with get_conn() as conn:
        return conn.execute("""
            SELECT *
            FROM ausencias
            WHERE status = 'ativa'
            AND fim_em <= ?
        """, (agora,)).fetchall()


def buscar_ausencias_ativas(guild_id: int):
    with get_conn() as conn:
        return conn.execute("""
            SELECT *
            FROM ausencias
            WHERE guild_id = ?
            AND status = 'ativa'
            ORDER BY fim_em ASC
        """, (guild_id,)).fetchall()


def usuario_tem_outra_ausencia_ativa(guild_id: int, user_id: int, ignorar_id: int):
    with get_conn() as conn:
        row = conn.execute("""
            SELECT COUNT(*) AS total
            FROM ausencias
            WHERE guild_id = ?
            AND user_id = ?
            AND status = 'ativa'
            AND id != ?
        """, (guild_id, user_id, ignorar_id)).fetchone()

        return row["total"] > 0


def parse_data(data_texto: str, fim_do_dia: bool = False) -> datetime:
    partes = data_texto.strip().split()

    data = partes[0]
    hora = partes[1] if len(partes) > 1 else None

    dia, mes, ano = data.split("/")

    dia = int(dia)
    mes = int(mes)
    ano = int(ano)

    if ano < 100:
        ano += 2000

    if hora:
        hora_part, minuto_part = hora.split(":")
        hora_int = int(hora_part)
        minuto_int = int(minuto_part)
    else:
        if fim_do_dia:
            hora_int = 23
            minuto_int = 59
        else:
            hora_int = 0
            minuto_int = 0

    return datetime(
        year=ano,
        month=mes,
        day=dia,
        hour=hora_int,
        minute=minuto_int,
        tzinfo=BR_TZ
    )


def parse_periodo(periodo: str):
    encontrados = re.findall(
        r"\d{1,2}/\d{1,2}/\d{2,4}(?:\s+\d{1,2}:\d{2})?",
        periodo
    )

    if not encontrados:
        return None, None, (
            "Período inválido. Use `DD/MM/AAAA até DD/MM/AAAA` "
            "ou `DD/MM/AAAA HH:MM até DD/MM/AAAA HH:MM`."
        )

    try:
        if len(encontrados) == 1:
            inicio = now_dt()
            fim = parse_data(encontrados[0], fim_do_dia=True)
        else:
            inicio = parse_data(encontrados[0], fim_do_dia=False)
            fim = parse_data(encontrados[1], fim_do_dia=True)

    except ValueError:
        return None, None, "Data inválida. Confira o dia, mês, ano e horário."

    if fim <= now_dt():
        return None, None, "A data final da ausência precisa ser maior que a data atual."

    if inicio > fim:
        return None, None, "A data de início não pode ser maior que a data final."

    return inicio, fim, None


def formatar_data(dt_iso: str) -> str:
    dt = datetime.fromisoformat(dt_iso)
    return dt.strftime("%d/%m/%Y às %H:%M")


def cortar_texto(texto: str, limite: int = 1000) -> str:
    if len(texto) <= limite:
        return texto

    return texto[:limite - 3] + "..."


def montar_embed_painel():
    embed = create_embed(
        title="Sistema de Ausência",
        description=(
            "Clique no botão abaixo para registrar sua ausência.\n\n"
            "Informe seu nome, motivo e período da ausência."
        )
    )

    embed.add_field(
        name="Formato do período",
        value=(
            "`DD/MM/AAAA até DD/MM/AAAA`\n"
            "`DD/MM/AAAA HH:MM até DD/MM/AAAA HH:MM`\n\n"
            "Exemplo:\n"
            "`20/05/2026 até 25/05/2026`"
        ),
        inline=False
    )

    return embed


def montar_embed_ausencia(ausencia, status_texto: str = "Ativa"):
    embed = create_embed(
        title=f"Registro de Ausência #{ausencia['id']}",
        description=f"Status: **{status_texto}**"
    )

    embed.add_field(
        name="Membro",
        value=f"<@{ausencia['user_id']}>",
        inline=True
    )

    embed.add_field(
        name="Nome",
        value=cortar_texto(ausencia["nome"], 1000),
        inline=True
    )

    embed.add_field(
        name="Motivo",
        value=cortar_texto(ausencia["motivo"], 1000),
        inline=False
    )

    embed.add_field(
        name="Período informado",
        value=cortar_texto(ausencia["periodo_texto"], 1000),
        inline=False
    )

    embed.add_field(
        name="Início",
        value=formatar_data(ausencia["inicio_em"]),
        inline=True
    )

    embed.add_field(
        name="Término",
        value=formatar_data(ausencia["fim_em"]),
        inline=True
    )

    if ausencia["finalizado_em"]:
        embed.add_field(
            name="Finalizada em",
            value=formatar_data(ausencia["finalizado_em"]),
            inline=False
        )

    return embed


class AusenciaModal(discord.ui.Modal, title="Registrar Ausência"):
    nome = discord.ui.TextInput(
        label="Nome",
        placeholder="Ex: Scott Majestic Stokovisk",
        max_length=80,
        required=True
    )

    motivo = discord.ui.TextInput(
        label="Motivo",
        placeholder="Ex: Viagem, trabalho, problemas pessoais...",
        style=discord.TextStyle.paragraph,
        max_length=500,
        required=True
    )

    periodo = discord.ui.TextInput(
        label="Período",
        placeholder="Ex: 20/05/2026 até 25/05/2026",
        max_length=120,
        required=True
    )

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.guild is None:
            await interaction.response.send_message(
                "Esse sistema só funciona dentro do servidor.",
                ephemeral=True
            )
            return

        config = get_config(interaction.guild.id)

        if not config:
            await interaction.response.send_message(
                "O sistema de ausência ainda não foi configurado.",
                ephemeral=True
            )
            return

        if not config["cargo_id"]:
            await interaction.response.send_message(
                "O cargo de ausência ainda não foi configurado.",
                ephemeral=True
            )
            return

        if not config["registro_channel_id"]:
            await interaction.response.send_message(
                "O canal de registro de ausências ainda não foi configurado.",
                ephemeral=True
            )
            return

        nome = str(self.nome.value).strip()
        motivo = str(self.motivo.value).strip()
        periodo_texto = str(self.periodo.value).strip()

        inicio, fim, erro = parse_periodo(periodo_texto)

        if erro:
            await interaction.response.send_message(
                erro,
                ephemeral=True
            )
            return

        cargo = interaction.guild.get_role(config["cargo_id"])

        if cargo is None:
            await interaction.response.send_message(
                "O cargo de ausência configurado não foi encontrado.",
                ephemeral=True
            )
            return

        canal_registro = interaction.guild.get_channel(config["registro_channel_id"])

        if canal_registro is None:
            try:
                canal_registro = await interaction.guild.fetch_channel(
                    config["registro_channel_id"]
                )
            except discord.HTTPException:
                await interaction.response.send_message(
                    "O canal de registro configurado não foi encontrado.",
                    ephemeral=True
                )
                return

        try:
            await interaction.user.add_roles(
                cargo,
                reason="Ausência registrada pelo sistema."
            )

        except discord.Forbidden:
            await interaction.response.send_message(
                "Não consegui entregar o cargo de ausência. Coloque meu cargo acima do cargo de ausência.",
                ephemeral=True
            )
            return

        ausencia_id = criar_ausencia(
            guild_id=interaction.guild.id,
            user_id=interaction.user.id,
            nome=nome,
            motivo=motivo,
            periodo_texto=periodo_texto,
            inicio_em=inicio.isoformat(),
            fim_em=fim.isoformat(),
            registro_channel_id=canal_registro.id
        )

        with get_conn() as conn:
            ausencia = conn.execute("""
                SELECT *
                FROM ausencias
                WHERE id = ?
            """, (ausencia_id,)).fetchone()

        embed = montar_embed_ausencia(
            ausencia=ausencia,
            status_texto="Ativa"
        )

        try:
            msg = await canal_registro.send(embed=embed)
            atualizar_msg_registro(ausencia_id, msg.id)

            await interaction.response.send_message(
                f"Sua ausência foi registrada e o cargo {cargo.mention} foi aplicado.",
                ephemeral=True
            )

        except discord.Forbidden:
            await interaction.response.send_message(
                "Ausência salva, mas não consegui enviar o registro no canal configurado.",
                ephemeral=True
            )


class AusenciaPainelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Registrar Ausência",
        style=discord.ButtonStyle.primary,
        custom_id="ausencia_registrar"
    )
    async def registrar_ausencia(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        await interaction.response.send_modal(AusenciaModal())


class Ausencia(commands.Cog):
    config_ausencia = app_commands.Group(
        name="config_ausencia",
        description="Configura o sistema de ausências."
    )

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        init_db()

        try:
            self.bot.add_view(AusenciaPainelView())
        except ValueError:
            pass

        self.verificar_ausencias.start()

    def cog_unload(self):
        self.verificar_ausencias.cancel()

    @config_ausencia.command(
        name="painel",
        description="Define o canal onde ficará o painel de ausência."
    )
    @app_commands.default_permissions(manage_guild=True)
    async def painel(
        self,
        interaction: discord.Interaction,
        canal: discord.TextChannel
    ):
        await interaction.response.defer(ephemeral=True)

        if interaction.guild is None:
            await interaction.followup.send(
                "Esse comando só pode ser usado dentro de um servidor.",
                ephemeral=True
            )
            return

        set_painel_channel(interaction.guild.id, canal.id)

        try:
            msg = await canal.send(
                embed=montar_embed_painel(),
                view=AusenciaPainelView()
            )

            set_painel_message(interaction.guild.id, msg.id)

            await interaction.followup.send(
                f"Painel de ausência enviado em {canal.mention}.",
                ephemeral=True
            )

        except discord.Forbidden:
            await interaction.followup.send(
                "Não tenho permissão para enviar mensagem nesse canal.",
                ephemeral=True
            )

    @config_ausencia.command(
        name="cargo",
        description="Define o cargo que será entregue para quem registrar ausência."
    )
    @app_commands.default_permissions(manage_guild=True)
    async def cargo(
        self,
        interaction: discord.Interaction,
        cargo: discord.Role
    ):
        await interaction.response.defer(ephemeral=True)

        if interaction.guild is None:
            await interaction.followup.send(
                "Esse comando só pode ser usado dentro de um servidor.",
                ephemeral=True
            )
            return

        set_cargo(interaction.guild.id, cargo.id)

        await interaction.followup.send(
            f"Cargo de ausência configurado como {cargo.mention}.",
            ephemeral=True
        )

    @config_ausencia.command(
        name="registro",
        description="Define o canal onde os registros de ausência serão enviados."
    )
    @app_commands.default_permissions(manage_guild=True)
    async def registro(
        self,
        interaction: discord.Interaction,
        canal: discord.TextChannel
    ):
        await interaction.response.defer(ephemeral=True)

        if interaction.guild is None:
            await interaction.followup.send(
                "Esse comando só pode ser usado dentro de um servidor.",
                ephemeral=True
            )
            return

        set_registro_channel(interaction.guild.id, canal.id)

        await interaction.followup.send(
            f"Canal de registro de ausências configurado em {canal.mention}.",
            ephemeral=True
        )

    @config_ausencia.command(
        name="listar",
        description="Mostra a configuração atual do sistema de ausência."
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

        painel = "Não configurado"
        registro = "Não configurado"
        cargo = "Não configurado"

        if config:
            if config["painel_channel_id"]:
                painel = f"<#{config['painel_channel_id']}>"

            if config["registro_channel_id"]:
                registro = f"<#{config['registro_channel_id']}>"

            if config["cargo_id"]:
                cargo = f"<@&{config['cargo_id']}>"

        embed = create_embed(
            title="Configuração de Ausência",
            description="Configuração atual do sistema."
        )

        embed.add_field(name="Canal do painel", value=painel, inline=False)
        embed.add_field(name="Canal de registro", value=registro, inline=False)
        embed.add_field(name="Cargo de ausência", value=cargo, inline=False)

        await interaction.followup.send(
            embed=embed,
            ephemeral=True
        )

    @app_commands.command(
        name="ausencias_ativas",
        description="Lista as ausências ativas."
    )
    @app_commands.default_permissions(manage_guild=True)
    async def ausencias_ativas(
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

        ausencias = buscar_ausencias_ativas(interaction.guild.id)

        if not ausencias:
            await interaction.followup.send(
                "Nenhuma ausência ativa no momento.",
                ephemeral=True
            )
            return

        texto = ""

        for ausencia in ausencias:
            linha = (
                f"**#{ausencia['id']}** - <@{ausencia['user_id']}> "
                f"até **{formatar_data(ausencia['fim_em'])}**\n"
            )

            if len(texto) + len(linha) > 3900:
                texto += "..."
                break

            texto += linha

        embed = create_embed(
            title="Ausências Ativas",
            description=texto
        )

        await interaction.followup.send(
            embed=embed,
            ephemeral=True
        )

    @tasks.loop(minutes=1)
    async def verificar_ausencias(self):
        ausencias = buscar_ausencias_vencidas()

        for ausencia in ausencias:
            guild = self.bot.get_guild(ausencia["guild_id"])

            if guild is None:
                continue

            config = get_config(guild.id)

            if not config or not config["cargo_id"]:
                finalizar_ausencia(ausencia["id"])
                continue

            cargo = guild.get_role(config["cargo_id"])
            membro = guild.get_member(ausencia["user_id"])

            if membro is None:
                try:
                    membro = await guild.fetch_member(ausencia["user_id"])
                except discord.HTTPException:
                    membro = None

            finalizar_ausencia(ausencia["id"])

            if (
                membro
                and cargo
                and not usuario_tem_outra_ausencia_ativa(
                    guild_id=guild.id,
                    user_id=ausencia["user_id"],
                    ignorar_id=ausencia["id"]
                )
            ):
                try:
                    await membro.remove_roles(
                        cargo,
                        reason="Período de ausência finalizado."
                    )
                except discord.HTTPException:
                    pass

            with get_conn() as conn:
                ausencia_atualizada = conn.execute("""
                    SELECT *
                    FROM ausencias
                    WHERE id = ?
                """, (ausencia["id"],)).fetchone()

            if ausencia_atualizada["registro_channel_id"] and ausencia_atualizada["registro_message_id"]:
                canal = guild.get_channel(ausencia_atualizada["registro_channel_id"])

                if canal is None:
                    try:
                        canal = await guild.fetch_channel(
                            ausencia_atualizada["registro_channel_id"]
                        )
                    except discord.HTTPException:
                        canal = None

                if canal:
                    try:
                        msg = await canal.fetch_message(
                            ausencia_atualizada["registro_message_id"]
                        )

                        await msg.edit(
                            embed=montar_embed_ausencia(
                                ausencia=ausencia_atualizada,
                                status_texto="Finalizada"
                            )
                        )
                    except discord.HTTPException:
                        pass

    @verificar_ausencias.before_loop
    async def before_verificar_ausencias(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(Ausencia(bot))