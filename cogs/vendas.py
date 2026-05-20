import sqlite3
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from utils.embeds import create_embed


VENDAS_DB_PATH = Path("data/vendas.db")
PRODUTOS_DB_PATH = Path("data/produtos.db")
PARCERIAS_DB_PATH = Path("data/parcerias.db")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_conn(db_path: Path):
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    return conn


def init_db():
    with get_conn(VENDAS_DB_PATH) as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS vendas_config (
                guild_id INTEGER PRIMARY KEY,
                channel_id INTEGER NOT NULL DEFAULT 0,
                panel_message_id INTEGER,
                relatorio_channel_id INTEGER
            );

            CREATE TABLE IF NOT EXISTS vendas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                message_id INTEGER,
                tipo TEXT NOT NULL,
                fac_parceira TEXT,
                produto_parceria TEXT,
                produtos_texto TEXT NOT NULL,
                responsaveis TEXT NOT NULL,
                valor_total REAL NOT NULL,
                comissao REAL NOT NULL,
                vendedor_id INTEGER NOT NULL,
                criado_em TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS venda_itens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                venda_id INTEGER NOT NULL,
                produto_nome TEXT NOT NULL,
                quantidade INTEGER NOT NULL,
                valor_unitario REAL NOT NULL,
                subtotal REAL NOT NULL
            );
        """)

        columns_config = [
            row["name"]
            for row in conn.execute("PRAGMA table_info(vendas_config)").fetchall()
        ]

        if "relatorio_channel_id" not in columns_config:
            conn.execute(
                "ALTER TABLE vendas_config ADD COLUMN relatorio_channel_id INTEGER"
            )

        columns_vendas = [
            row["name"]
            for row in conn.execute("PRAGMA table_info(vendas)").fetchall()
        ]

        if "produto_parceria" not in columns_vendas:
            conn.execute(
                "ALTER TABLE vendas ADD COLUMN produto_parceria TEXT"
            )

        conn.commit()


def set_config_canal(guild_id: int, channel_id: int):
    with get_conn(VENDAS_DB_PATH) as conn:
        conn.execute("""
            INSERT INTO vendas_config (guild_id, channel_id)
            VALUES (?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET
                channel_id = excluded.channel_id
        """, (guild_id, channel_id))
        conn.commit()


def set_config_relatorio(guild_id: int, channel_id: int):
    with get_conn(VENDAS_DB_PATH) as conn:
        conn.execute("""
            INSERT INTO vendas_config (guild_id, channel_id, relatorio_channel_id)
            VALUES (?, 0, ?)
            ON CONFLICT(guild_id) DO UPDATE SET
                relatorio_channel_id = excluded.relatorio_channel_id
        """, (guild_id, channel_id))
        conn.commit()


def update_panel_message_id(guild_id: int, message_id: int):
    with get_conn(VENDAS_DB_PATH) as conn:
        conn.execute("""
            UPDATE vendas_config
            SET panel_message_id = ?
            WHERE guild_id = ?
        """, (message_id, guild_id))
        conn.commit()


def get_config(guild_id: int):
    with get_conn(VENDAS_DB_PATH) as conn:
        return conn.execute("""
            SELECT *
            FROM vendas_config
            WHERE guild_id = ?
            LIMIT 1
        """, (guild_id,)).fetchone()


def listar_produtos():
    if not PRODUTOS_DB_PATH.exists():
        return []

    try:
        with get_conn(PRODUTOS_DB_PATH) as conn:
            rows = conn.execute("""
                SELECT *
                FROM produtos
                WHERE ativo = 1
                ORDER BY nome ASC
                LIMIT 25
            """).fetchall()

            return [dict(row) for row in rows]

    except sqlite3.OperationalError:
        return []


def buscar_produto_por_id(produto_id: int):
    if not PRODUTOS_DB_PATH.exists():
        return None

    try:
        with get_conn(PRODUTOS_DB_PATH) as conn:
            row = conn.execute("""
                SELECT *
                FROM produtos
                WHERE id = ?
                AND ativo = 1
                LIMIT 1
            """, (produto_id,)).fetchone()

            return dict(row) if row else None

    except sqlite3.OperationalError:
        return None


def listar_parcerias():
    if not PARCERIAS_DB_PATH.exists():
        return []

    try:
        with get_conn(PARCERIAS_DB_PATH) as conn:
            rows = conn.execute("""
                SELECT *
                FROM parcerias
                WHERE ativo = 1
                ORDER BY nome_fac ASC
                LIMIT 25
            """).fetchall()

            return [dict(row) for row in rows]

    except sqlite3.OperationalError:
        return []


def buscar_parceria_por_id(parceria_id: int):
    if not PARCERIAS_DB_PATH.exists():
        return None

    try:
        with get_conn(PARCERIAS_DB_PATH) as conn:
            row = conn.execute("""
                SELECT *
                FROM parcerias
                WHERE id = ?
                AND ativo = 1
                LIMIT 1
            """, (parceria_id,)).fetchone()

            return dict(row) if row else None

    except sqlite3.OperationalError:
        return None


def criar_venda(
    guild_id: int,
    channel_id: int,
    tipo: str,
    fac_parceira: Optional[str],
    produto_parceria: Optional[str],
    produtos_texto: str,
    responsaveis: str,
    valor_total: float,
    comissao: float,
    vendedor_id: int
) -> int:
    with get_conn(VENDAS_DB_PATH) as conn:
        cursor = conn.execute("""
            INSERT INTO vendas (
                guild_id,
                channel_id,
                tipo,
                fac_parceira,
                produto_parceria,
                produtos_texto,
                responsaveis,
                valor_total,
                comissao,
                vendedor_id,
                criado_em
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            guild_id,
            channel_id,
            tipo,
            fac_parceira,
            produto_parceria,
            produtos_texto,
            responsaveis,
            valor_total,
            comissao,
            vendedor_id,
            now_iso()
        ))

        conn.commit()
        return cursor.lastrowid


def criar_item_venda(
    venda_id: int,
    produto_nome: str,
    quantidade: int,
    valor_unitario: float,
    subtotal: float
):
    with get_conn(VENDAS_DB_PATH) as conn:
        conn.execute("""
            INSERT INTO venda_itens (
                venda_id,
                produto_nome,
                quantidade,
                valor_unitario,
                subtotal
            )
            VALUES (?, ?, ?, ?, ?)
        """, (
            venda_id,
            produto_nome,
            quantidade,
            valor_unitario,
            subtotal
        ))

        conn.commit()


def atualizar_message_id_venda(venda_id: int, message_id: int):
    with get_conn(VENDAS_DB_PATH) as conn:
        conn.execute("""
            UPDATE vendas
            SET message_id = ?
            WHERE id = ?
        """, (message_id, venda_id))
        conn.commit()


def formatar_dinheiro(valor: float) -> str:
    valor_formatado = f"{valor:,.2f}"
    valor_formatado = valor_formatado.replace(",", "X")
    valor_formatado = valor_formatado.replace(".", ",")
    valor_formatado = valor_formatado.replace("X", ".")

    return f"R$ {valor_formatado}"


def cortar_texto(texto: str, limite: int = 1000) -> str:
    if len(texto) <= limite:
        return texto

    return texto[:limite - 3] + "..."


def normalizar_nome(texto: str) -> str:
    return texto.strip().lower()


def separar_linha_produto(linha: str):
    linha = linha.strip()
    separadores = [":", "-", "=", ",", ";"]

    for sep in separadores:
        if sep in linha:
            partes = linha.rsplit(sep, 1)
            return partes[0].strip(), partes[1].strip()

    partes = linha.rsplit(" ", 1)

    if len(partes) == 2:
        return partes[0].strip(), partes[1].strip()

    return linha, ""


def parse_quantidades(texto: str, produtos: list[dict]):
    linhas = [
        linha.strip()
        for linha in texto.splitlines()
        if linha.strip()
    ]

    if not linhas:
        return None, ["Nenhuma quantidade foi informada."]

    quantidades = {}
    erros = []

    somente_numeros = all(linha.isdigit() for linha in linhas)

    if somente_numeros and len(linhas) == len(produtos):
        for index, produto in enumerate(produtos):
            quantidade = int(linhas[index])

            if quantidade <= 0:
                erros.append(f"A quantidade de {produto['nome']} precisa ser maior que zero.")
                continue

            quantidades[produto["id"]] = quantidade

        return quantidades, erros

    produtos_por_nome = {
        normalizar_nome(produto["nome"]): produto
        for produto in produtos
    }

    for linha in linhas:
        nome, quantidade_texto = separar_linha_produto(linha)

        quantidade_texto = quantidade_texto.lower()
        quantidade_texto = quantidade_texto.replace("x", "")
        quantidade_texto = quantidade_texto.strip()

        if not quantidade_texto.isdigit():
            erros.append(
                f"Quantidade inválida em {linha}. Use o formato: Produto: quantidade"
            )
            continue

        produto = produtos_por_nome.get(normalizar_nome(nome))

        if not produto:
            erros.append(f"O produto {nome} não está entre os produtos selecionados.")
            continue

        quantidade = int(quantidade_texto)

        if quantidade <= 0:
            erros.append(f"A quantidade de {produto['nome']} precisa ser maior que zero.")
            continue

        quantidades[produto["id"]] = quantidade

    for produto in produtos:
        if produto["id"] not in quantidades:
            erros.append(f"Faltou informar a quantidade de {produto['nome']}.")

    return quantidades, erros


def calcular_venda(produtos: list[dict], quantidades: dict, tipo: str):
    campo_valor = "valor_parceria" if tipo == "parceria" else "valor_pista"

    itens = []
    total = 0.0

    for produto in produtos:
        quantidade = int(quantidades[produto["id"]])
        valor_unitario = float(produto[campo_valor])
        subtotal = valor_unitario * quantidade

        itens.append({
            "produto_nome": produto["nome"],
            "quantidade": quantidade,
            "valor_unitario": valor_unitario,
            "subtotal": subtotal
        })

        total += subtotal

    comissao = total * 0.50

    return {
        "itens": itens,
        "total": total,
        "comissao": comissao
    }


def montar_texto_itens(itens: list[dict]) -> str:
    linhas = []

    for item in itens:
        nome = item["produto_nome"][:18]
        qtd = str(item["quantidade"])
        unitario = formatar_dinheiro(item["valor_unitario"])
        subtotal = formatar_dinheiro(item["subtotal"])

        linhas.append(
            f"{nome:<18} x{qtd:<4} {unitario:<15} {subtotal}"
        )

    texto = "\n".join(linhas)

    return f"```{texto}```"


def montar_produtos_texto_original(itens: list[dict]) -> str:
    linhas = []

    for item in itens:
        linhas.append(f"{item['produto_nome']}: {item['quantidade']}")

    return "\n".join(linhas)


def montar_embed_painel():
    embed = create_embed(
        title="Registro de Vendas",
        description=(
            "Selecione abaixo o tipo de venda que deseja registrar.\n\n"
            "Venda Parceria: venda feita para uma fac parceira cadastrada.\n"
            "Venda Pista: venda feita diretamente na pista."
        )
    )

    embed.add_field(
        name="Observação",
        value=(
            "Antes de registrar vendas, cadastre os produtos e as parcerias.\n"
            "Os valores são puxados automaticamente do cadastro de produtos."
        ),
        inline=False
    )

    return embed


def montar_embed_relatorio(
    venda_id: int,
    tipo: str,
    fac_parceira: Optional[str],
    produto_parceria: Optional[str],
    itens: list[dict],
    responsaveis: str,
    total: float,
    comissao: float,
    vendedor: discord.Member | discord.User
):
    tipo_nome = "Parceria" if tipo == "parceria" else "Pista"

    embed = create_embed(
        title=f"Relatório de Venda #{venda_id}",
        description=f"Tipo de venda: {tipo_nome}"
    )

    if tipo == "parceria":
        embed.add_field(
            name="Fac parceira",
            value=f"**{fac_parceira}** — Produto da parceria: **{produto_parceria}**",
            inline=False
        )

    embed.add_field(
        name="Produtos vendidos",
        value=montar_texto_itens(itens),
        inline=False
    )

    embed.add_field(
        name="Responsáveis pela venda",
        value=cortar_texto(responsaveis, 1000),
        inline=False
    )

    embed.add_field(
        name="Resumo financeiro",
        value=(
            f"Valor total: **{formatar_dinheiro(total)}**\n"
            f"Comissão 50%: **{formatar_dinheiro(comissao)}**"
        ),
        inline=False
    )

    embed.add_field(
        name="Registrado por",
        value=vendedor.mention,
        inline=False
    )

    return embed


class FacParceiraSelect(discord.ui.Select):
    def __init__(self, parcerias: list[dict]):
        options = []

        for parceria in parcerias[:25]:
            options.append(
                discord.SelectOption(
                    label=parceria["nome_fac"][:100],
                    description=f"Produto: {parceria['produto']}"[:100],
                    value=str(parceria["id"])
                )
            )

        super().__init__(
            placeholder="Selecione a fac parceira",
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        view.parceria_id = int(self.values[0])

        await interaction.response.defer()


class ProdutoSelect(discord.ui.Select):
    def __init__(self, produtos: list[dict]):
        options = []

        for produto in produtos[:25]:
            options.append(
                discord.SelectOption(
                    label=produto["nome"][:100],
                    description=(
                        f"Parceria: {formatar_dinheiro(produto['valor_parceria'])} | "
                        f"Pista: {formatar_dinheiro(produto['valor_pista'])}"
                    )[:100],
                    value=str(produto["id"])
                )
            )

        super().__init__(
            placeholder="Selecione os produtos vendidos",
            min_values=1,
            max_values=max(1, min(25, len(options))),
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        view.produto_ids = [int(value) for value in self.values]

        await interaction.response.defer()


class VendaParceriaSetupView(discord.ui.View):
    def __init__(
        self,
        autor_id: int,
        parcerias: list[dict],
        produtos: list[dict]
    ):
        super().__init__(timeout=300)

        self.autor_id = autor_id
        self.parceria_id: Optional[int] = None
        self.produto_ids: list[int] = []

        self.add_item(FacParceiraSelect(parcerias))
        self.add_item(ProdutoSelect(produtos))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.autor_id:
            await interaction.response.send_message(
                "Apenas quem iniciou o registro pode usar esse painel.",
                ephemeral=True
            )
            return False

        return True

    @discord.ui.button(
        label="Continuar",
        style=discord.ButtonStyle.success
    )
    async def continuar(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        if not self.parceria_id:
            await interaction.response.send_message(
                "Selecione a fac parceira antes de continuar.",
                ephemeral=True
            )
            return

        if not self.produto_ids:
            await interaction.response.send_message(
                "Selecione pelo menos um produto antes de continuar.",
                ephemeral=True
            )
            return

        parceria = buscar_parceria_por_id(self.parceria_id)

        if not parceria:
            await interaction.response.send_message(
                "A parceria selecionada não foi encontrada.",
                ephemeral=True
            )
            return

        produtos = []

        for produto_id in self.produto_ids:
            produto = buscar_produto_por_id(produto_id)

            if produto:
                produtos.append(produto)

        if not produtos:
            await interaction.response.send_message(
                "Nenhum produto selecionado foi encontrado.",
                ephemeral=True
            )
            return

        await interaction.response.send_modal(
            VendaQuantidadeModal(
                tipo="parceria",
                parceria=parceria,
                produtos=produtos
            )
        )


class VendaPistaSetupView(discord.ui.View):
    def __init__(
        self,
        autor_id: int,
        produtos: list[dict]
    ):
        super().__init__(timeout=300)

        self.autor_id = autor_id
        self.produto_ids: list[int] = []

        self.add_item(ProdutoSelect(produtos))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.autor_id:
            await interaction.response.send_message(
                "Apenas quem iniciou o registro pode usar esse painel.",
                ephemeral=True
            )
            return False

        return True

    @discord.ui.button(
        label="Continuar",
        style=discord.ButtonStyle.primary
    )
    async def continuar(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        if not self.produto_ids:
            await interaction.response.send_message(
                "Selecione pelo menos um produto antes de continuar.",
                ephemeral=True
            )
            return

        produtos = []

        for produto_id in self.produto_ids:
            produto = buscar_produto_por_id(produto_id)

            if produto:
                produtos.append(produto)

        if not produtos:
            await interaction.response.send_message(
                "Nenhum produto selecionado foi encontrado.",
                ephemeral=True
            )
            return

        await interaction.response.send_modal(
            VendaQuantidadeModal(
                tipo="pista",
                parceria=None,
                produtos=produtos
            )
        )


class VendaQuantidadeModal(discord.ui.Modal):
    def __init__(
        self,
        tipo: str,
        parceria: Optional[dict],
        produtos: list[dict]
    ):
        titulo = "Venda Parceria" if tipo == "parceria" else "Venda Pista"

        super().__init__(title=titulo)

        self.tipo = tipo
        self.parceria = parceria
        self.produtos = produtos

        linhas_default = "\n".join(
            f"{produto['nome']}: "
            for produto in produtos
        )

        self.quantidades_input = discord.ui.TextInput(
            label="Quantidades",
            placeholder="Preencha a quantidade ao lado de cada produto.",
            style=discord.TextStyle.paragraph,
            max_length=1000,
            required=True,
            default=linhas_default
        )

        self.responsaveis_input = discord.ui.TextInput(
            label="Responsáveis pela venda",
            placeholder="Ex: Scott, Bruno e Ana",
            style=discord.TextStyle.paragraph,
            max_length=500,
            required=True
        )

        self.add_item(self.quantidades_input)
        self.add_item(self.responsaveis_input)

    async def on_submit(self, interaction: discord.Interaction):
        await processar_venda(
            interaction=interaction,
            tipo=self.tipo,
            parceria=self.parceria,
            produtos=self.produtos,
            quantidades_texto=str(self.quantidades_input.value).strip(),
            responsaveis=str(self.responsaveis_input.value).strip()
        )


async def processar_venda(
    interaction: discord.Interaction,
    tipo: str,
    parceria: Optional[dict],
    produtos: list[dict],
    quantidades_texto: str,
    responsaveis: str
):
    if interaction.guild is None:
        await interaction.response.send_message(
            "Esse sistema só funciona dentro do servidor.",
            ephemeral=True
        )
        return

    if not responsaveis:
        await interaction.response.send_message(
            "Informe os responsáveis pela venda.",
            ephemeral=True
        )
        return

    quantidades, erros = parse_quantidades(
        texto=quantidades_texto,
        produtos=produtos
    )

    if erros:
        embed = create_embed(
            title="Erro ao registrar venda",
            description="\n".join(f"- {erro}" for erro in erros)
        )

        await interaction.response.send_message(
            embed=embed,
            ephemeral=True
        )
        return

    config = get_config(interaction.guild.id)

    if not config or not config["relatorio_channel_id"]:
        await interaction.response.send_message(
            "O canal de relatório de vendas ainda não foi configurado.",
            ephemeral=True
        )
        return

    canal_relatorio = interaction.guild.get_channel(config["relatorio_channel_id"])

    if canal_relatorio is None:
        try:
            canal_relatorio = await interaction.guild.fetch_channel(
                config["relatorio_channel_id"]
            )
        except discord.HTTPException:
            await interaction.response.send_message(
                "Não consegui encontrar o canal de relatório configurado.",
                ephemeral=True
            )
            return

    resultado = calcular_venda(
        produtos=produtos,
        quantidades=quantidades,
        tipo=tipo
    )

    fac_nome = None
    produto_parceria = None

    if tipo == "parceria" and parceria:
        fac_nome = parceria["nome_fac"]
        produto_parceria = parceria["produto"]

    produtos_texto = montar_produtos_texto_original(resultado["itens"])

    venda_id = criar_venda(
        guild_id=interaction.guild.id,
        channel_id=canal_relatorio.id,
        tipo=tipo,
        fac_parceira=fac_nome,
        produto_parceria=produto_parceria,
        produtos_texto=produtos_texto,
        responsaveis=responsaveis,
        valor_total=resultado["total"],
        comissao=resultado["comissao"],
        vendedor_id=interaction.user.id
    )

    for item in resultado["itens"]:
        criar_item_venda(
            venda_id=venda_id,
            produto_nome=item["produto_nome"],
            quantidade=item["quantidade"],
            valor_unitario=item["valor_unitario"],
            subtotal=item["subtotal"]
        )

    embed = montar_embed_relatorio(
        venda_id=venda_id,
        tipo=tipo,
        fac_parceira=fac_nome,
        produto_parceria=produto_parceria,
        itens=resultado["itens"],
        responsaveis=responsaveis,
        total=resultado["total"],
        comissao=resultado["comissao"],
        vendedor=interaction.user
    )

    try:
        msg = await canal_relatorio.send(embed=embed)
        atualizar_message_id_venda(venda_id, msg.id)

        await interaction.response.send_message(
            f"Venda registrada com sucesso em {canal_relatorio.mention}.",
            ephemeral=True
        )

    except discord.Forbidden:
        await interaction.response.send_message(
            "Não tenho permissão para enviar o relatório no canal configurado.",
            ephemeral=True
        )

    except discord.HTTPException:
        await interaction.response.send_message(
            "Ocorreu um erro ao enviar o relatório da venda.",
            ephemeral=True
        )


class VendasPainelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Venda Parceria",
        style=discord.ButtonStyle.success,
        custom_id="vendas_parceria"
    )
    async def venda_parceria(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        parcerias = listar_parcerias()
        produtos = listar_produtos()

        if not parcerias:
            await interaction.response.send_message(
                "Nenhuma parceria cadastrada. Use o comando /parceria registrar primeiro.",
                ephemeral=True
            )
            return

        if not produtos:
            await interaction.response.send_message(
                "Nenhum produto cadastrado. Use o comando /produto cadastrar primeiro.",
                ephemeral=True
            )
            return

        embed = create_embed(
            title="Registrar Venda Parceria",
            description=(
                "Selecione a fac parceira e os produtos vendidos.\n"
                "Depois clique em Continuar para informar as quantidades."
            )
        )

        await interaction.response.send_message(
            embed=embed,
            view=VendaParceriaSetupView(
                autor_id=interaction.user.id,
                parcerias=parcerias,
                produtos=produtos
            ),
            ephemeral=True
        )

    @discord.ui.button(
        label="Venda Pista",
        style=discord.ButtonStyle.primary,
        custom_id="vendas_pista"
    )
    async def venda_pista(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        produtos = listar_produtos()

        if not produtos:
            await interaction.response.send_message(
                "Nenhum produto cadastrado. Use o comando /produto cadastrar primeiro.",
                ephemeral=True
            )
            return

        embed = create_embed(
            title="Registrar Venda Pista",
            description=(
                "Selecione os produtos vendidos.\n"
                "Depois clique em Continuar para informar as quantidades."
            )
        )

        await interaction.response.send_message(
            embed=embed,
            view=VendaPistaSetupView(
                autor_id=interaction.user.id,
                produtos=produtos
            ),
            ephemeral=True
        )


class Vendas(commands.Cog):
    config_vendas = app_commands.Group(
        name="config_vendas",
        description="Configura o sistema de vendas."
    )

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        init_db()

        try:
            self.bot.add_view(VendasPainelView())
        except ValueError:
            pass

    @config_vendas.command(
        name="canal",
        description="Define o canal onde ficará o painel de registro de vendas."
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
                "Esse comando só pode ser usado dentro de um servidor.",
                ephemeral=True
            )
            return

        try:
            set_config_canal(interaction.guild.id, canal.id)

            painel_msg = await canal.send(
                embed=montar_embed_painel(),
                view=VendasPainelView()
            )

            update_panel_message_id(
                guild_id=interaction.guild.id,
                message_id=painel_msg.id
            )

            await interaction.followup.send(
                f"Canal do painel de vendas configurado em {canal.mention}.",
                ephemeral=True
            )

        except discord.Forbidden:
            await interaction.followup.send(
                "Não tenho permissão para enviar mensagem nesse canal.",
                ephemeral=True
            )

        except Exception as error:
            print(f"[ERRO] /config_vendas canal: {error}")

            await interaction.followup.send(
                "Deu erro ao configurar o canal de vendas. Olha o terminal.",
                ephemeral=True
            )

    @config_vendas.command(
        name="relatorio",
        description="Define o canal onde os relatórios das vendas serão enviados."
    )
    @app_commands.default_permissions(manage_guild=True)
    async def config_relatorio(
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

        set_config_relatorio(interaction.guild.id, canal.id)

        await interaction.followup.send(
            f"Canal de relatório de vendas configurado em {canal.mention}.",
            ephemeral=True
        )

    @config_vendas.command(
        name="painel",
        description="Reenvia o painel de registro de vendas no canal configurado."
    )
    @app_commands.default_permissions(manage_guild=True)
    async def reenviar_painel(
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

        if not config or not config["channel_id"]:
            await interaction.followup.send(
                "Nenhum canal de painel de vendas configurado ainda.",
                ephemeral=True
            )
            return

        canal = interaction.guild.get_channel(config["channel_id"])

        if canal is None:
            await interaction.followup.send(
                "O canal configurado não foi encontrado.",
                ephemeral=True
            )
            return

        painel_msg = await canal.send(
            embed=montar_embed_painel(),
            view=VendasPainelView()
        )

        update_panel_message_id(
            guild_id=interaction.guild.id,
            message_id=painel_msg.id
        )

        await interaction.followup.send(
            f"Painel reenviado em {canal.mention}.",
            ephemeral=True
        )

    @config_vendas.command(
        name="listar",
        description="Mostra os canais configurados para vendas."
    )
    @app_commands.default_permissions(manage_guild=True)
    async def listar_config(
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

        canal_painel = "Não configurado"
        canal_relatorio = "Não configurado"

        if config:
            if config["channel_id"]:
                canal_painel = f"<#{config['channel_id']}>"

            if config["relatorio_channel_id"]:
                canal_relatorio = f"<#{config['relatorio_channel_id']}>"

        embed = create_embed(
            title="Configuração de Vendas",
            description="Configuração atual do sistema de vendas."
        )

        embed.add_field(
            name="Canal do painel",
            value=canal_painel,
            inline=False
        )

        embed.add_field(
            name="Canal de relatório",
            value=canal_relatorio,
            inline=False
        )

        await interaction.followup.send(
            embed=embed,
            ephemeral=True
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Vendas(bot))