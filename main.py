import os
import asyncio
import traceback
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = os.getenv("GUILD_ID")


async def on_app_command_error(
    interaction: discord.Interaction,
    error: app_commands.AppCommandError
):
    print("\n[ERRO SLASH COMMAND]")
    print(f"Comando: /{interaction.command.name if interaction.command else 'desconhecido'}")
    print(f"Usuário: {interaction.user}")
    print(f"Servidor: {interaction.guild.name if interaction.guild else 'DM'}")
    traceback.print_exception(type(error), error, error.__traceback__)

    mensagem = "❌ Deu erro interno nesse comando. Olha o terminal do VS Code."

    try:
        if interaction.response.is_done():
            await interaction.followup.send(mensagem, ephemeral=True)
        else:
            await interaction.response.send_message(mensagem, ephemeral=True)
    except Exception:
        pass


class FacBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()

        # Necessário para o cog de sugestões ler mensagens normais
        intents.message_content = True

        super().__init__(
            command_prefix="!",
            intents=intents,
            help_command=None
        )

    async def setup_hook(self):
        print("[BOT] Iniciando carregamento dos cogs...")

        await self.load_cogs()

        # Tratador global de erro dos slash commands
        self.tree.on_error = on_app_command_error

        if GUILD_ID:
            guild = discord.Object(id=int(GUILD_ID))

            # Limpa comandos antigos do servidor
            self.tree.clear_commands(guild=guild)

            # Copia os comandos carregados dos cogs para o servidor
            self.tree.copy_global_to(guild=guild)

            synced = await self.tree.sync(guild=guild)

            print(f"[SLASH] {len(synced)} comando(s) sincronizado(s) no servidor {GUILD_ID}")

            for command in synced:
                print(f"[SLASH] /{command.name} sincronizado")

        else:
            synced = await self.tree.sync()

            print(f"[SLASH] {len(synced)} comando(s) global(is) sincronizado(s)")

            for command in synced:
                print(f"[SLASH] /{command.name} sincronizado")

    async def load_cogs(self):
        cogs_path = Path("cogs")

        if not cogs_path.exists():
            print("[ERRO] Pasta cogs não encontrada.")
            return

        for file in cogs_path.glob("*.py"):
            if file.name.startswith("__"):
                continue

            extension = f"cogs.{file.stem}"

            try:
                await self.load_extension(extension)
                print(f"[COG] {extension} carregado com sucesso")

            except Exception as error:
                print(f"[ERRO] Falha ao carregar {extension}: {error}")
                traceback.print_exception(type(error), error, error.__traceback__)

    async def on_error(self, event_method: str, *args, **kwargs):
        print(f"\n[ERRO EVENTO] {event_method}")
        traceback.print_exc()

    async def on_ready(self):
        print("-" * 40)
        print(f"[BOT] Online como {self.user}")
        print(f"[BOT] ID: {self.user.id}")
        print("-" * 40)


async def main():
    print("[BOT] Ligando...")

    if not TOKEN:
        print("[ERRO] DISCORD_TOKEN não encontrado no .env")
        return

    bot = FacBot()

    try:
        await bot.start(TOKEN)

    except discord.LoginFailure:
        print("[ERRO] Token inválido. Confere o DISCORD_TOKEN no .env")

    except discord.PrivilegedIntentsRequired:
        print("[ERRO] O bot precisa do Message Content Intent ativado.")
        print("[INFO] Vai no Discord Developer Portal > Bot > Privileged Gateway Intents.")
        print("[INFO] Ativa a opção: MESSAGE CONTENT INTENT.")

    except Exception as error:
        print(f"[ERRO] Erro inesperado: {error}")
        traceback.print_exception(type(error), error, error.__traceback__)

    finally:
        if not bot.is_closed():
            await bot.close()


if __name__ == "__main__":
    asyncio.run(main())