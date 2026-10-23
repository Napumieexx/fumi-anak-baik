
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
LOG_CHANNEL_ID = os.getenv("LOG_CHANNEL_ID")


# =========================
# DISCORD INTENTS
# =========================

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents
)


# =========================
# FUNGSI MOD LOG
# =========================

async def send_mod_log(guild, embed):
    """Mengirim embed ke channel Mod Log."""

    if not LOG_CHANNEL_ID:
        print("LOG_CHANNEL_ID belum diatur.")
        return False

    try:
        channel_id = int(LOG_CHANNEL_ID)
    except ValueError:
        print("LOG_CHANNEL_ID harus berupa angka.")
        return False

    log_channel = bot.get_channel(channel_id)

    if log_channel is None:
        try:
            log_channel = await bot.fetch_channel(channel_id)
        except (
            discord.NotFound,
            discord.Forbidden,
            discord.HTTPException
        ) as error:
            print(f"Channel log tidak dapat diakses: {error}")
            return False

    if not isinstance(log_channel, discord.TextChannel):
        print("ID Mod Log bukan channel teks yang didukung.")
        return False

    if guild is not None and log_channel.guild.id != guild.id:
        print("Channel Mod Log berada di server yang berbeda.")
        return False

    try:
        await log_channel.send(embed=embed)
        return True
    except (
        discord.Forbidden,
        discord.HTTPException
    ) as error:
        print(f"Gagal mengirim moderation log: {error}")
        return False


# =========================
# BOT READY
# =========================

@bot.event
async def on_ready():
    database.setup_database()

    print(f"Bot berhasil online sebagai {bot.user}")
    print("Database siap.")
    print("Moderation system aktif.")

    if LOG_CHANNEL_ID:
        print(f"Mod Log dikonfigurasi: {LOG_CHANNEL_ID}")
    else:
        print("Mod Log belum aktif: LOG_CHANNEL_ID belum diatur.")


# =========================
# MESSAGE DETECTOR
# =========================

@bot.event
async def on_message(message):

    # Abaikan pesan dari bot
    if message.author.bot:
        return

    # Deteksi hanya pesan dari server Discord
    if message.guild is None:
        await bot.process_commands(message)
        return

    detected = detect_words(message.content)

# Pengecualian untuk cerita tentang hewan
text_lower = message.content.lower()

animal_context = [
    "dikejar sama anjing",
    "dikejar anjing",
    "anjingku",
    "anjing gue",
    "anjing gw",
    "anjing peliharaan",
    "anjing itu menggonggong",
    "anjingnya menggonggong",
    "anjing lucu",
]

if any(phrase in text_lower for phrase in animal_context):
    detected = [
        item for item in detected
        if item["matched"].lower() != "anjing"
    ]

if detected:
    
        # =========================
        # HITUNG SCORE
        # =========================

        if config.COUNT_DUPLICATE_WORDS:
            total_score = sum(
                item["score"] for item in detected
            )
        else:
            unique_words = {}

            for item in detected:
                matched = item["matched"]

                if matched not in unique_words:
                    unique_words[matched] = item["score"]

            total_score = sum(unique_words.values())

        # =========================
        # SIMPAN KE DATABASE
        # =========================

        score, violations = database.add_violation(
            message.author.id,
            str(message.author),
            total_score
        )

        # =========================
        # HAPUS PESAN
        # =========================

        try:
            await message.delete()
        except discord.Forbidden:
            print("Tidak punya izin menghapus pesan.")
        except discord.NotFound:
            pass
        except discord.HTTPException as error:
            print(f"Gagal menghapus pesan: {error}")

        # =========================
        # TENTUKAN WARNING
        # =========================

        warning_number = None

        if score <= config.WARNING_1_MAX:
            warning_number = 1
        elif score <= config.WARNING_2_MAX:
            warning_number = 2
        elif score <= config.WARNING_3_MAX:
            warning_number = 3

        # =========================
        # TIMEOUT
        # =========================

        timeout_status = "Tidak diperlukan"

        if score >= config.TIMEOUT_SCORE:
            try:
                await message.author.timeout(
                    timedelta(minutes=config.TIMEOUT_MINUTES),
                    reason="Melewati batas skor pelanggaran."
                )

                timeout_status = (
                    f"Berhasil ({config.TIMEOUT_MINUTES} menit)"
                )

                warning_text = (
                    f"⚠️ {message.author.mention} "
                    f"kamu mendapatkan **TIMEOUT "
                    f"{config.TIMEOUT_MINUTES} menit**.\n"
                    f"Skor pelanggaran: **{score}**"
                )

            except discord.Forbidden:
                timeout_status = "Gagal: izin tidak cukup"

                warning_text = (
                    f"⚠️ {message.author.mention} "
                    f"skormu sudah mencapai **{score}**.\n"
                    "Bot tidak memiliki izin untuk memberikan timeout."
                )

            except discord.HTTPException as error:
                timeout_status = f"Gagal: {error.code}"

                warning_text = (
                    f"⚠️ {message.author.mention} "
                    f"skormu sudah mencapai **{score}**.\n"
                    "Terjadi kesalahan saat memberikan timeout."
                )

        else:
            warning_text = (
                f"⚠️ {message.author.mention} "
                "pesanmu melanggar aturan.\n"
                f"Skor pelanggaran bertambah **+{total_score}**.\n"
                f"Total skor: **{score}**\n"
                f"Warning: **{warning_number}/3**"
            )

        # =========================
        # KIRIM WARNING
        # =========================

        try:
            await message.channel.send(
                warning_text,
                delete_after=config.WARNING_DELETE_AFTER
            )
        except discord.Forbidden:
            print("Tidak punya izin mengirim warning.")
        except discord.HTTPException as error:
            print(f"Gagal mengirim warning: {error}")

        # =========================
        # LOG MODERATOR
        # =========================

        detected_names = ", ".join(
            f"{item['matched']} ({item['similarity']:.0f}%)"
            for item in detected
        )

        embed = discord.Embed(
            title="🚨 Moderation Log",
            color=discord.Color.orange(),
            description=(
                f"**User:** {message.author.mention}\n"
                f"**User ID:** `{message.author.id}`\n"
                f"**Channel:** {message.channel.mention}\n"
                f"**Skor tambahan:** +{total_score}\n"
                f"**Total skor:** {score}\n"
                f"**Jumlah pelanggaran:** {violations}\n"
                f"**Warning:** "
                f"{warning_number if warning_number is not None else 'Tidak ada'}\n"
                f"**Status timeout:** {timeout_status}\n"
                f"**Terdeteksi:** {detected_names}"
            ),
            timestamp=discord.utils.utcnow()
        )

        await send_mod_log(message.guild, embed)

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
        print(f"Command error: {error}")


# =========================
# START BOT
# =========================

if not TOKEN:
    raise RuntimeError(
        "DISCORD_TOKEN belum ditemukan di environment."
    )

bot.run(TOKEN)
