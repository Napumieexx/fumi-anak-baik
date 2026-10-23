import discord
from discord.ext import commands


PURPLE = discord.Color.from_rgb(105, 75, 190)


def make_embed(title, description):
    embed = discord.Embed(
        title=title,
        description=description,
        color=PURPLE
    )
    embed.set_footer(text="Fumi Anak Baik • Pilih tombol untuk menjelajah")
    return embed


class FumiMenuView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)

    @discord.ui.button(label="Games", emoji="🎮", style=discord.ButtonStyle.primary, row=0)
    async def games_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = make_embed(
            "🎮 Game Center",
            "**Pilih permainan lewat command berikut:**\n\n"
            "▫️ `!ttt @teman` — Tic-tac-toe melawan teman\n"
            "▫️ `!rps` — Suit melawan Fumi\n"
            "▫️ `!tebakangka` — Tebak angka 1–24\n\n"
            "Gunakan `!gamehelp` untuk melihat daftar game."
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="Quiz", emoji="🧠", style=discord.ButtonStyle.success, row=0)
    async def quiz_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = make_embed(
            "🧠 Quiz Arena",
            "**Mulai kuis dengan tombol jawaban A/B/C/D:**\n\n"
            "▫️ `!kuis` — Kategori campuran\n"
            "▫️ `!kuis receh` — Tebak-tebakan receh\n"
            "▫️ `!kuis logika` — Logika menjebak\n"
            "▫️ `!kuis trivia` — Pengetahuan umum\n\n"
            "Jawaban benar mendapat **+10 poin**."
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="Leaderboard", emoji="🏆", style=discord.ButtonStyle.secondary, row=0)
    async def leaderboard_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = make_embed(
            "🏆 Poin & Peringkat",
            "Lihat skor kuis dan peringkat server:\n\n"
            "▫️ `!poin` — Poin kuismu\n"
            "▫️ `!poin @teman` — Poin kuis anggota lain\n"
            "▫️ `!leaderboard` — Peringkat 10 besar\n\n"
            "Poin kuis saat ini disimpan di memori dan akan kembali nol jika bot dimulai ulang."
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="Moderasi", emoji="🛡️", style=discord.ButtonStyle.secondary, row=1)
    async def moderation_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = make_embed(
            "🛡️ Pusat Moderasi",
            "Command moderasi Fumi:\n\n"
            "▫️ `!score` — Cek skor pelanggaran sendiri\n"
            "▫️ `!score @anggota` — Cek skor anggota\n"
            "▫️ `!reset_score @anggota` — Reset skor (perlu izin **Manage Messages**)\n"
            "▫️ `!test` — Tes status bot\n\n"
            "Fumi akan memproses pelanggaran sesuai konfigurasi server."
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="Bantuan", emoji="ℹ️", style=discord.ButtonStyle.secondary, row=1)
    async def help_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = make_embed(
            "ℹ️ Bantuan Fumi",
            "**Prefix command:** `!`\n\n"
            "▫️ `!menu` — Buka menu utama\n"
            "▫️ `!gamehelp` — Bantuan game\n"
            "▫️ `!kuishelp` — Bantuan kuis\n"
            "▫️ `!score` — Cek skor moderasi\n\n"
            "Kalau ada command yang tidak merespons, pastikan Fumi online dan punya izin yang diperlukan."
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


def setup_menu(bot: commands.Bot):
    @bot.command(name="menu", aliases=["fumi", "start"])
    async def menu(ctx: commands.Context):
        embed = discord.Embed(
            title="🌙 FUMI ANAK BAIK",
            description=(
                "Selamat datang di pusat kendali Fumi!\n"
                "Pilih kategori di bawah untuk melihat fitur yang tersedia.\n\n"
                "🎮 **Games**  ·  🧠 **Quiz**  ·  🏆 **Leaderboard**\n"
                "🛡️ **Moderasi**  ·  ℹ️ **Bantuan**"
            ),
            color=PURPLE
        )
        if bot.user:
            embed.set_thumbnail(url=bot.user.display_avatar.url)
        embed.set_footer(text="Fumi Anak Baik • Fun, fair, and friendly")
        view = FumiMenuView()
        await ctx.send(embed=embed, view=view)
