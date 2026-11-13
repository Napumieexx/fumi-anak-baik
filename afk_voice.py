import discord
from discord.ext import commands
import asyncio


class AFKVoice(commands.Cog):
    """Keeps Fumi connected to one Discord voice channel at a time."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.active_guild_id = None
        self._lock = asyncio.Lock()

    @commands.command(name="afkvoice")
    @commands.guild_only()
    async def afkvoice(self, ctx: commands.Context):
        """Join the voice channel the command author is currently in."""
        if not ctx.author.voice or not ctx.author.voice.channel:
            await ctx.send("Kamu harus masuk Voice Channel terlebih dahulu.")
            return

        channel = ctx.author.voice.channel
        guild = ctx.guild

        async with self._lock:
            if self.active_guild_id is not None and self.active_guild_id != guild.id:
                await ctx.send(
                    "Fumi sedang AFK di server lain. "
                    "Gunakan `!leavevoice` dari server tempat Fumi sedang terhubung."
                )
                return

            voice = guild.voice_client
            try:
                if voice and voice.is_connected():
                    if voice.channel.id != channel.id:
                        await voice.move_to(channel)
                        await ctx.send(f"Fumi dipindahkan ke **{channel.name}** dan sekarang AFK.")
                    else:
                        await ctx.send(f"Fumi sudah berada di **{channel.name}** dan tetap AFK.")
                else:
                    await channel.connect()
                    self.active_guild_id = guild.id
                    await ctx.send(f"Fumi berhasil masuk ke **{channel.name}** dan sekarang AFK.")
            except discord.Forbidden:
                await ctx.send("Fumi tidak punya izin **Connect** di Voice Channel tersebut.")
            except discord.ClientException as exc:
                await ctx.send(f"Fumi tidak bisa terhubung: `{exc}`")
            except discord.HTTPException as exc:
                await ctx.send(f"Discord gagal menghubungkan Fumi: `{exc}`")

    @commands.command(name="movevoice")
    @commands.guild_only()
    async def movevoice(self, ctx: commands.Context):
        """Move Fumi to the command author's current voice channel."""
        if not ctx.author.voice or not ctx.author.voice.channel:
            await ctx.send("Masuk ke Voice Channel tujuan terlebih dahulu.")
            return

        channel = ctx.author.voice.channel
        guild = ctx.guild

        async with self._lock:
            if self.active_guild_id is not None and self.active_guild_id != guild.id:
                await ctx.send("Fumi sedang terhubung di server lain.")
                return

            voice = guild.voice_client
            if not voice or not voice.is_connected():
                await ctx.send("Fumi belum masuk Voice Channel. Gunakan `!afkvoice` terlebih dahulu.")
                return

            try:
                await voice.move_to(channel)
                await ctx.send(f"Fumi dipindahkan ke **{channel.name}**.")
            except discord.Forbidden:
                await ctx.send("Fumi tidak punya izin **Connect** di Voice Channel tujuan.")
            except discord.HTTPException as exc:
                await ctx.send(f"Gagal memindahkan Fumi: `{exc}`")

    @commands.command(name="leavevoice", aliases=["voiceleave", "keluarvoice"])
    @commands.guild_only()
    async def leavevoice(self, ctx: commands.Context):
        """Disconnect Fumi from its current voice channel."""
        async with self._lock:
            voice = ctx.guild.voice_client
            if not voice or not voice.is_connected():
                await ctx.send("Fumi tidak sedang berada di Voice Channel server ini.")
                if self.active_guild_id == ctx.guild.id:
                    self.active_guild_id = None
                return

            try:
                await voice.disconnect(force=True)
                self.active_guild_id = None
                await ctx.send("Fumi sudah keluar dari Voice Channel.")
            except discord.HTTPException as exc:
                await ctx.send(f"Gagal mengeluarkan Fumi: `{exc}`")


async def setup(bot: commands.Bot):
    await bot.add_cog(AFKVoice(bot))
