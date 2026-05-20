import os
import discord
from dotenv import load_dotenv

load_dotenv()


def get_embed_color() -> discord.Color:
    color_hex = os.getenv("EMBED_COLOR", "#FF24AB")
    color_hex = color_hex.replace("#", "")

    try:
        return discord.Color(int(color_hex, 16))
    except ValueError:
        return discord.Color(int("FF24AB", 16))


def create_embed(
    title: str | None = None,
    description: str | None = None
) -> discord.Embed:
    embed = discord.Embed(
        title=title,
        description=description,
        color=get_embed_color()
    )

    embed.set_footer(
        text=os.getenv("EMBED_FOOTER", "CodeStore™ All rights reserved")
    )

    return embed