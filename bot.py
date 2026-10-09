import os
from datetime import timedelta

import discord
from discord.ext import commands
from dotenv import load_dotenv

import config
import database
from detector import detect_words


# =========================
# LOAD ENV
# =========================

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")

# Opsional:
# Isi LOG_CHANNEL_ID di .env kalau ingin log pelanggaran
LOG_CHANNEL_ID = os.getenv("LOG_CHANNEL_ID")


# =========================
# DISCORD INTENTS
# =========================

intents = discord.Intents.default()
intents.message_content = True


bot = commands.Bot(
    command_prefix="!",
    intents=intents
)


# =========================
# BOT READY
# =========================

@bot.event
async def on_ready():
    database.setup_database()

    print(f"Bot berhasil online sebagai {bot.user}")
    print("Database siap.")
    print("Moderation system aktif.")


# =========================
# MESSAGE DETECTOR
# =========================

@bot.event
async def on_message(message):

    # Abaikan pesan dari bot
    if message.author.bot:
        return

    detected = detect_words(message.content)

    if detected:

        # ==================================
        # HITUNG SCORE
        # ==================================

        if config.COUNT_DUPLICATE_WORDS:
            total_score = sum(
                item["score"]
                for item in detected
            )

        else:
            # Kata yang sama hanya dihitung sekali
            unique_words = {}

            for item in detected:
                matched = item["matched"]

                if matched not in unique_words:
                    unique_words[matched] = item["score"]

            total_score = sum(unique_words.values())


        # ==================================
        # SIMPAN KE DATABASE
        # ==================================

        score, violations = database.add_violation(
            message.author.id,
            str(message.author),
            total_score
        )


        # ==================================
        # HAPUS PESAN
        # ==================================

        try:
            await message.delete()
        except discord.Forbidden:
            print("Tidak punya izin menghapus pesan.")
        except discord.NotFound:
            pass


        # ==================================
        # TENTUKAN WARNING
        # ==================================

        warning_number = None

        if score <= config.WARNING_1_MAX:
            warning_number = 1

        elif score <= config.WARNING_2_MAX:
            warning_number = 2

        elif score <= config.WARNING_3_MAX:
            warning_number = 3


        # ==================================
        # TIMEOUT
        # ==================================

        if score >= config.TIMEOUT_SCORE:

            try:
                await message.author.timeout(
                    timedelta(
                        minutes=config.TIMEOUT_MINUTES
                    ),
                    reason="Melewati batas skor pelanggaran."
                )

                warning_text = (
                    f"⚠️ {message.author.mention} "
                    f"kamu mendapatkan **TIMEOUT {config.TIMEOUT_MINUTES} menit**.\n"
                    f"Skor pelanggaran: **{score}**"
                )

            except discord.Forbidden:

                warning_text = (
                    f"⚠️ {message.author.mention} "
                    f"skormu sudah mencapai **{score}**.\n"
                    f"Bot tidak memiliki izin untuk memberikan timeout."
                )

        else:

            warning_text = (
                f"⚠️ {message.author.mention} "
                f"pesanmu melanggar aturan.\n"
                f"Skor pelanggaran bertambah **+{total_score}**.\n"
                f"Total skor: **{score}**\n"
                f"Warning: **{warning_number}/3**"
            )


        # ==================================
        # KIRIM WARNING
        # ==================================

        try:

            warning_message = await message.channel.send(
                warning_text,
                delete_after=config.WARNING_DELETE_AFTER
            )

        except discord.Forbidden:
            warning_message = None


        # ==================================
        # LOG MODERATOR
        # ==================================

        if LOG_CHANNEL_ID:

            try:

                log_channel = bot.get_channel(
                    int(LOG_CHANNEL_ID)
                )

                if log_channel:

                    detected_names = ", ".join(
                        f"{item['matched']} "
                        f"({item['similarity']:.0f}%)"
                        for item in detected
                    )

                    embed = discord.Embed(
                        title="🚨 Moderation Log",
                        description=(
                            f"**User:** {message.author.mention}\n"
                            f"**Channel:** {message.channel.mention}\n"
                            f"**Score:** +{total_score}\n"
                            f"**Total:** {score}\n"
                            f"**Terdeteksi:** {detected_names}"
                        ),
                        timestamp=discord.utils.utcnow()
                    )

                    await log_channel.send(
                        embed=embed
                    )

            except Exception as error:

                print(
                    f"Gagal mengirim moderation log: {error}"
                )


    # Tetap proses command seperti !score
    await bot.process_commands(message)


# =========================
# COMMAND: !score
# =========================

@bot.command()
async def score(ctx, member: discord.Member = None):

    if member is None:
        member = ctx.author

    user = database.get_user(member.id)

    if user is None:

        await ctx.send(
            f"📊 {member.mention} belum memiliki pelanggaran.",
            delete_after=7
        )

        return

    _, username, total_score, violations, last_violation = user

    await ctx.send(
        f"📊 **Moderation Score**\n\n"
        f"User: {member.mention}\n"
        f"Score: **{total_score}**\n"
        f"Violations: **{violations}**",
        delete_after=10
    )


# =========================
# COMMAND: !reset_score
# =========================

@bot.command()
@commands.has_permissions(manage_messages=True)
async def reset_score(ctx, member: discord.Member):

    success = database.reset_score(member.id)

    if success:

        await ctx.send(
            f"✅ Score {member.mention} berhasil di-reset.",
            delete_after=7
        )

    else:

        await ctx.send(
            f"ℹ️ {member.mention} belum memiliki data score.",
            delete_after=7
        )


# =========================
# COMMAND: !test
# =========================

@bot.command()
async def test(ctx):

    await ctx.send(
        "✅ Moderation bot aktif!",
        delete_after=5
    )


# =========================
# ERROR HANDLER
# =========================

@bot.event
async def on_command_error(ctx, error):

    if isinstance(error, commands.MissingPermissions):

        await ctx.send(
            "❌ Kamu tidak punya izin untuk menggunakan command ini.",
            delete_after=5
        )

    elif isinstance(error, commands.MissingRequiredArgument):

        await ctx.send(
            "❌ Format command belum lengkap.",
            delete_after=5
        )

    elif isinstance(error, commands.MemberNotFound):

        await ctx.send(
            "❌ Member tidak ditemukan.",
            delete_after=5
        )

    elif isinstance(error, commands.CommandNotFound):
        pass

    else:

        print(
            f"Command error: {error}"
        )


# =========================
# START BOT
# =========================

if not TOKEN:
    raise RuntimeError(
        "DISCORD_TOKEN belum ditemukan di file .env"
    )

bot.run(TOKEN)