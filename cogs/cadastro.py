import sqlite3
from pathlib import Path
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands

from utils.embeds import create_embed


DB_PATH = Path("data/cadastros.db")


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def get_conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS cadastros (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                nome TEXT NOT NULL,
                passaporte TEXT NOT NULL,
                telefone TEXT NOT NULL,
                recrutador TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pendente',
                message_id INTEGER,
                aprovado_por INTEGER,
                criado_em TEXT NOT NULL,
                atualizado_em TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS cadastro_config (
                chave TEXT PRIMARY KEY,
                valor TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS cadastro_cargos (
                cargo_id INTEGER PRIMARY KEY
            );
        """)
        conn.commit()


def set_config(chave: str, valor: str):
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO cadastro_config (chave, valor)
            VALUES (?, ?)
            ON CONFLICT(chave) DO UPDATE SET valor = excluded.valor
        """, (chave, valor))
        conn.commit()


def get_config(chave: str):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT valor FROM cadastro_config WHERE chave = ?",
            (chave,)
        ).fetchone()

        return row["valor"] if row else None


def add_cargo(cargo_id: int):
    with get_conn() as conn:
        conn.execute("""
            INSERT OR IGNORE INTO cadastro_cargos (cargo_id)
            VALUES (?)
        """, (cargo_id,))
        conn.commit()


def remove_cargo(cargo_id: int):
    with get_conn() as conn:
        conn.execute(
            "DELETE FROM cadastro_cargos WHERE cargo_id = ?",
            (cargo_id,)
        )
        conn.commit()


def clear_cargos():
    with get_conn() as conn:
        conn.execute("DELETE FROM cadastro_cargos")
        conn.commit()


def get_cargos():
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT cargo_id FROM cadastro_cargos"
        ).fetchall()

        return [row["cargo_id"] for row in rows]


def criar_cadastro(user_id, nome, passaporte, telefone, recrutador):
    with get_conn() as conn:
        cursor = conn.execute("""
            INSERT INTO cadastros (
                user_id, nome, passaporte, telefone, recrutador,
                status, criado_em, atualizado_em
            )
            VALUES (?, ?, ?, ?, ?, 'pendente', ?, ?)
        """, (
            user_id,
            nome,
            passaporte,
            telefone,
            recrutador,
            now_iso(),
            now_iso()
        ))
        conn.commit()
        return cursor.lastrowid


def atualizar_message_id(cadastro_id, message_id):
    with get_conn() as conn:
        conn.execute("""
            UPDATE cadastros
            SET message_id = ?, atualizado_em = ?
            WHERE id = ?
        """, (message_id, now_iso(), cadastro_id))
        conn.commit()


def buscar_ultimo_cadastro_usuario(user_id):
    with get_conn() as conn:
        return conn.execute("""
            SELECT * FROM cadastros
            WHERE user_id = ?
            ORDER BY id DESC
            LIMIT 1
        """, (user_id,)).fetchone()


def buscar_cadastro_por_message_id(message_id):
    with get_conn() as conn:
        return conn.execute("""
            SELECT * FROM cadastros
            WHERE message_id = ?
            LIMIT 1
        """, (message_id,)).fetchone()


def atualizar_status(cadastro_id, status, aprovado_por=None):
    with get_conn() as conn:
        conn.execute("""
            UPDATE cadastros
            SET status = ?, aprovado_por = ?, atualizado_em = ?
            WHERE id = ?
        """, (status, aprovado_por, now_iso(), cadastro_id))
        conn.commit()


async def buscar_canal_aprovacao(bot):
    canal_id = get_config("canal_aprovacao_id")

    if not canal_id or not canal_id.isdigit():
        return None

    canal = bot.get_channel(int(canal_id))

    if canal is None:
        try:
            canal = await bot.fetch_channel(int(canal_id))
        except discord.HTTPException:
            return None

    return canal


class CadastroModal(discord.ui.Modal, title="Cadastro de Membro"):
    nome = discord.ui.TextInput(
        label="Nome",
        placeholder="Ex: Scott Majestic Stokovisk",
        max_length=50
    )

    passaporte = discord.ui.TextInput(
        label="Passaporte",
        placeholder="Ex: 133",
        max_length=10
    )

    telefone = discord.ui.TextInput(
        label="Telefone",
        placeholder="Digite somente 6 números",
        min_length=6,
        max_length=6
    )

    recrutador = discord.ui.TextInput(
        label="Recrutador",
        placeholder="Nome de quem te indicou",
        max_length=50
    )

    async def on_submit(self, interaction: discord.Interaction):
        nome = str(self.nome.value).strip()
        passaporte = str(self.passaporte.value).strip()
        telefone = str(self.telefone.value).strip()
        recrutador = str(self.recrutador.value).strip()

        if not passaporte.isdigit():
            await interaction.response.send_message(
                "❌ O passaporte precisa conter somente números.",
                ephemeral=True
            )
            return

        if not telefone.isdigit() or len(telefone) != 6:
            await interaction.response.send_message(
                "❌ O telefone precisa ter exatamente 6 números.",
                ephemeral=True
            )
            return

        ultimo = buscar_ultimo_cadastro_usuario(interaction.user.id)

        if ultimo and ultimo["status"] == "pendente":
            await interaction.response.send_message(
                "❌ Você já possui um cadastro pendente de aprovação.",
                ephemeral=True
            )
            return

        if ultimo and ultimo["status"] == "aprovado":
            await interaction.response.send_message(
                "❌ Você já possui um cadastro aprovado.",
                ephemeral=True
            )
            return

        canal_aprovacao = await buscar_canal_aprovacao(interaction.client)

        if canal_aprovacao is None:
            await interaction.response.send_message(
                "❌ O canal de aprovação ainda não foi configurado.",
                ephemeral=True
            )
            return

        cargos_ids = get_cargos()

        if not cargos_ids:
            await interaction.response.send_message(
                "❌ Nenhum cargo automático foi configurado ainda.",
                ephemeral=True
            )
            return

        cadastro_id = criar_cadastro(
            user_id=interaction.user.id,
            nome=nome,
            passaporte=passaporte,
            telefone=telefone,
            recrutador=recrutador
        )

        embed = create_embed(
            title="📥 Novo cadastro pendente",
            description="Um novo membro enviou o cadastro para aprovação."
        )

        embed.add_field(name="Usuário", value=interaction.user.mention, inline=False)
        embed.add_field(name="Nome", value=nome, inline=True)
        embed.add_field(name="Passaporte", value=passaporte, inline=True)
        embed.add_field(name="Telefone", value=telefone, inline=True)
        embed.add_field(name="Recrutador", value=recrutador, inline=False)
        embed.add_field(name="Status", value="⏳ Pendente", inline=False)

        msg = await canal_aprovacao.send(
            embed=embed,
            view=CadastroAprovacaoView()
        )

        atualizar_message_id(cadastro_id, msg.id)

        await interaction.response.send_message(
            "✅ Seu cadastro foi enviado para aprovação da administração.",
            ephemeral=True
        )


class CadastroPainelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Fazer cadastro",
        emoji="📝",
        style=discord.ButtonStyle.primary,
        custom_id="cadastro_abrir_modal"
    )
    async def abrir_modal(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        await interaction.response.send_modal(CadastroModal())


class CadastroAprovacaoView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    def tem_permissao(self, interaction: discord.Interaction):
        perms = interaction.user.guild_permissions
        return perms.administrator or perms.manage_guild

    @discord.ui.button(
        label="Aprovar",
        emoji="✅",
        style=discord.ButtonStyle.success,
        custom_id="cadastro_aprovar"
    )
    async def aprovar(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        if not self.tem_permissao(interaction):
            await interaction.response.send_message(
                "❌ Você não tem permissão para aprovar cadastros.",
                ephemeral=True
            )
            return

        cadastro = buscar_cadastro_por_message_id(interaction.message.id)

        if not cadastro:
            await interaction.response.send_message(
                "❌ Cadastro não encontrado no banco de dados.",
                ephemeral=True
            )
            return

        if cadastro["status"] != "pendente":
            await interaction.response.send_message(
                f"❌ Esse cadastro já está como **{cadastro['status']}**.",
                ephemeral=True
            )
            return

        cargos_ids = get_cargos()

        if not cargos_ids:
            await interaction.response.send_message(
                "❌ Nenhum cargo automático foi configurado.",
                ephemeral=True
            )
            return

        try:
            membro = interaction.guild.get_member(cadastro["user_id"])

            if membro is None:
                membro = await interaction.guild.fetch_member(cadastro["user_id"])

        except discord.NotFound:
            await interaction.response.send_message(
                "❌ Esse usuário não está mais no servidor.",
                ephemeral=True
            )
            return

        cargos = []
        cargos_nao_encontrados = []

        for cargo_id in cargos_ids:
            cargo = interaction.guild.get_role(int(cargo_id))

            if cargo is None:
                cargos_nao_encontrados.append(str(cargo_id))
            else:
                cargos.append(cargo)

        if cargos_nao_encontrados:
            await interaction.response.send_message(
                "❌ Alguns cargos configurados não foram encontrados no servidor: "
                + ", ".join(cargos_nao_encontrados),
                ephemeral=True
            )
            return

        novo_nome = f"{cadastro['passaporte']} | {cadastro['nome']}"

        if len(novo_nome) > 32:
            novo_nome = novo_nome[:32]

        try:
            await membro.edit(
                nick=novo_nome,
                reason=f"Cadastro aprovado por {interaction.user}"
            )

            await membro.add_roles(
                *cargos,
                reason=f"Cadastro aprovado por {interaction.user}"
            )

        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ Não consegui renomear ou dar cargo. Coloca o cargo do bot acima dos membros e acima dos cargos que ele vai entregar.",
                ephemeral=True
            )
            return

        except discord.HTTPException:
            await interaction.response.send_message(
                "❌ Ocorreu um erro ao tentar aprovar esse cadastro.",
                ephemeral=True
            )
            return

        atualizar_status(
            cadastro_id=cadastro["id"],
            status="aprovado",
            aprovado_por=interaction.user.id
        )

        cargos_texto = "\n".join(cargo.mention for cargo in cargos)

        embed = create_embed(
            title="✅ Cadastro aprovado",
            description=f"O cadastro de {membro.mention} foi aprovado."
        )

        embed.add_field(name="Nome", value=cadastro["nome"], inline=True)
        embed.add_field(name="Passaporte", value=cadastro["passaporte"], inline=True)
        embed.add_field(name="Telefone", value=cadastro["telefone"], inline=True)
        embed.add_field(name="Recrutador", value=cadastro["recrutador"], inline=False)
        embed.add_field(name="Cargos entregues", value=cargos_texto, inline=False)
        embed.add_field(name="Aprovado por", value=interaction.user.mention, inline=False)

        await interaction.response.edit_message(embed=embed, view=None)

    @discord.ui.button(
        label="Recusar",
        emoji="❌",
        style=discord.ButtonStyle.danger,
        custom_id="cadastro_recusar"
    )
    async def recusar(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        if not self.tem_permissao(interaction):
            await interaction.response.send_message(
                "❌ Você não tem permissão para recusar cadastros.",
                ephemeral=True
            )
            return

        cadastro = buscar_cadastro_por_message_id(interaction.message.id)

        if not cadastro:
            await interaction.response.send_message(
                "❌ Cadastro não encontrado no banco de dados.",
                ephemeral=True
            )
            return

        if cadastro["status"] != "pendente":
            await interaction.response.send_message(
                f"❌ Esse cadastro já está como **{cadastro['status']}**.",
                ephemeral=True
            )
            return

        atualizar_status(
            cadastro_id=cadastro["id"],
            status="recusado",
            aprovado_por=interaction.user.id
        )

        embed = create_embed(
            title="❌ Cadastro recusado",
            description="Esse cadastro foi recusado pela administração."
        )

        embed.add_field(name="Nome", value=cadastro["nome"], inline=True)
        embed.add_field(name="Passaporte", value=cadastro["passaporte"], inline=True)
        embed.add_field(name="Telefone", value=cadastro["telefone"], inline=True)
        embed.add_field(name="Recrutador", value=cadastro["recrutador"], inline=False)
        embed.add_field(name="Recusado por", value=interaction.user.mention, inline=False)

        await interaction.response.edit_message(embed=embed, view=None)


class Cadastro(commands.Cog):
    config_cadastro = app_commands.Group(
        name="config_cadastro",
        description="Configura o sistema de cadastro."
    )

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        init_db()

        try:
            self.bot.add_view(CadastroPainelView())
            self.bot.add_view(CadastroAprovacaoView())
        except ValueError:
            pass

    @app_commands.command(
        name="enviar_cadastro",
        description="Envia o painel de cadastro em um canal."
    )
    @app_commands.default_permissions(manage_guild=True)
    async def enviar_cadastro(
        self,
        interaction: discord.Interaction,
        canal: discord.TextChannel
    ):
        embed = create_embed(
            title="📋 Cadastro de Membro",
            description="Clique no botão abaixo para realizar seu cadastro."
        )

        embed.add_field(
            name="Informações necessárias",
            value=(
                "• Nome\n"
                "• Passaporte\n"
                "• Telefone de 6 dígitos\n"
                "• Nome do recrutador"
            ),
            inline=False
        )

        await canal.send(
            embed=embed,
            view=CadastroPainelView()
        )

        await interaction.response.send_message(
            f"✅ Painel de cadastro enviado em {canal.mention}.",
            ephemeral=True
        )

    @config_cadastro.command(
        name="canal",
        description="Define o canal onde os cadastros serão enviados para aprovação."
    )
    @app_commands.default_permissions(manage_guild=True)
    async def config_canal(
        self,
        interaction: discord.Interaction,
        canal: discord.TextChannel
    ):
        set_config("canal_aprovacao_id", str(canal.id))

        await interaction.response.send_message(
            f"✅ Canal de aprovação configurado para {canal.mention}.",
            ephemeral=True
        )

    @config_cadastro.command(
        name="cargo_adicionar",
        description="Adiciona um cargo automático para quem for aprovado."
    )
    @app_commands.default_permissions(manage_guild=True)
    async def cargo_adicionar(
        self,
        interaction: discord.Interaction,
        cargo: discord.Role
    ):
        add_cargo(cargo.id)

        await interaction.response.send_message(
            f"✅ Cargo {cargo.mention} adicionado à lista de cargos automáticos.",
            ephemeral=True
        )

    @config_cadastro.command(
        name="cargo_remover",
        description="Remove um cargo automático do cadastro."
    )
    @app_commands.default_permissions(manage_guild=True)
    async def cargo_remover(
        self,
        interaction: discord.Interaction,
        cargo: discord.Role
    ):
        remove_cargo(cargo.id)

        await interaction.response.send_message(
            f"✅ Cargo {cargo.mention} removido da lista de cargos automáticos.",
            ephemeral=True
        )

    @config_cadastro.command(
        name="cargos_limpar",
        description="Remove todos os cargos automáticos configurados."
    )
    @app_commands.default_permissions(manage_guild=True)
    async def cargos_limpar(
        self,
        interaction: discord.Interaction
    ):
        clear_cargos()

        await interaction.response.send_message(
            "✅ Todos os cargos automáticos foram removidos.",
            ephemeral=True
        )

    @config_cadastro.command(
        name="listar",
        description="Mostra a configuração atual do sistema de cadastro."
    )
    @app_commands.default_permissions(manage_guild=True)
    async def listar_config(
        self,
        interaction: discord.Interaction
    ):
        canal_id = get_config("canal_aprovacao_id")
        cargos_ids = get_cargos()

        canal_texto = f"<#{canal_id}>" if canal_id else "Não configurado"

        if cargos_ids:
            cargos_texto = "\n".join(f"<@&{cargo_id}>" for cargo_id in cargos_ids)
        else:
            cargos_texto = "Nenhum cargo configurado"

        embed = create_embed(
            title="⚙️ Configuração do Cadastro",
            description="Configuração atual do sistema de cadastro."
        )

        embed.add_field(name="Canal de aprovação", value=canal_texto, inline=False)
        embed.add_field(name="Cargos automáticos", value=cargos_texto, inline=False)

        await interaction.response.send_message(
            embed=embed,
            ephemeral=True
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Cadastro(bot))