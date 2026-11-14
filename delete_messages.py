from __future__ import annotations

import asyncio
import discord
from discord.ext import commands


class DeleteMessages(commands.Cog):
    """Moderation commands for deleting messages."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command(
    name="bersihkan",
    aliases=["purge", "deletebulk"])
    
    @commands.guild_only()
    @commands.has_permissions(manage_messages=True)
    @commands.bot_has_permissions(manage_messages=True, read_message_history=True)
    async def clear_messages(self, ctx: commands.Context, amount: int):
        """Delete up to 100 recent messages, excluding the command itself."""
        if amount < 1 or amount > 100:
            await ctx.reply(
                "Masukkan jumlah antara **1 sampai 100**. Contoh: `!clear 20`.",
                mention_author=False,
                delete_after=6,
            )
            return

        try:
            deleted = await ctx.channel.purge(
                limit=amount + 1,
                check=lambda message: message.id != ctx.message.id,
                bulk=True,
                reason=f"Bulk message cleanup requested by {ctx.author} ({ctx.author.id})",
            )
        except discord.Forbidden:
            await ctx.reply(
                "Fumi tidak memiliki izin **Manage Messages** atau **Read Message History**.",
                mention_author=False,
                delete_after=8,
            )
            return
        except discord.HTTPException:
            await ctx.reply(
                "Discord gagal menghapus pesan. Coba lagi sebentar.",
                mention_author=False,
                delete_after=8,
            )
            return

        # Delete the command message separately so the command itself is removed too.
        try:
            await ctx.message.delete()
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass

        confirmation = await ctx.send(
            f"🧹 Berhasil menghapus **{len(deleted)} pesan** di channel ini."
        )
        await asyncio.sleep(5)
        try:
            await confirmation.delete()
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass

    @commands.command(name="del")
    @commands.guild_only()
    @commands.has_permissions(manage_messages=True)
    @commands.bot_has_permissions(manage_messages=True)
    async def delete_command_message(self, ctx: commands.Context):
        """Delete only the command message used to invoke this command."""
        try:
            await ctx.message.delete()
        except discord.Forbidden:
            await ctx.send("Fumi tidak memiliki izin **Manage Messages**.", delete_after=8)
        except discord.HTTPException:
            await ctx.send("Pesan tidak bisa dihapus. Coba lagi.", delete_after=8)

    @clear_messages.error
    @delete_command_message.error
    async def delete_error(self, ctx: commands.Context, error: commands.CommandError):
        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.reply(
                "Gunakan `!clear <jumlah>`. Contoh: `!clear 20`.",
                mention_author=False,
                delete_after=8,
            )
        elif isinstance(error, commands.MissingPermissions):
            await ctx.reply(
                "Kamu membutuhkan izin **Manage Messages** untuk menggunakan fitur ini.",
                mention_author=False,
                delete_after=8,
            )
        elif isinstance(error, commands.BotMissingPermissions):
            await ctx.reply(
                "Fumi membutuhkan izin **Manage Messages** dan **Read Message History**.",
                mention_author=False,
                delete_after=8,
            )
        elif isinstance(error, commands.NoPrivateMessage):
            await ctx.reply("Perintah ini hanya bisa digunakan di server.", mention_author=False)
        else:
            raise error


async def setup(bot: commands.Bot):
    await bot.add_cog(DeleteMessages(bot))
