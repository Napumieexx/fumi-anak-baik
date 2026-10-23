import random
import json
import os
import discord
from discord.ext import commands

MARK = {1: "❌", 2: "⭕"}


class TicTacToe(discord.ui.View):
    def __init__(self, x_player, o_player):
        super().__init__(timeout=180)
        self.players = {1: x_player, 2: o_player}
        self.turn = 1
        self.board = [0] * 9
        self.finished = False
        self.message = None
        self.update_buttons()

    def update_buttons(self):
        # View ini hanya berisi sembilan tombol kotak.
        for i, button in enumerate(self.children):
            button.label = MARK[self.board[i]] if self.board[i] else str(i + 1)
            button.disabled = bool(self.board[i]) or self.finished

    def winner(self):
        lines = [
            (0, 1, 2), (3, 4, 5), (6, 7, 8),
            (0, 3, 6), (1, 4, 7), (2, 5, 8),
            (0, 4, 8), (2, 4, 6),
        ]
        for a, b, c in lines:
            if self.board[a] and self.board[a] == self.board[b] == self.board[c]:
                return self.board[a]
        return 0

    async def move(self, interaction: discord.Interaction, index: int):
        if self.finished:
            await interaction.response.send_message("Game sudah selesai.", ephemeral=True)
            return
        if interaction.user.id != self.players[self.turn].id:
            await interaction.response.send_message(
                f"Giliran {self.players[self.turn].mention}.", ephemeral=True
            )
            return
        if self.board[index]:
            await interaction.response.send_message("Kotak sudah terisi.", ephemeral=True)
            return

        self.board[index] = self.turn
        win = self.winner()
        if win or all(self.board):
            self.finished = True
            self.update_buttons()
            result = (
                f"🏆 {self.players[win].mention} menang ({MARK[win]})!"
                if win else "🤝 Seri!"
            )
            await interaction.response.edit_message(content=result, view=self)
            return

        self.turn = 2 if self.turn == 1 else 1
        self.update_buttons()
        await interaction.response.edit_message(
            content=f"**Tic-tac-toe** — giliran {self.players[self.turn].mention} ({MARK[self.turn]})",
            view=self,
        )

    @discord.ui.button(label="1", style=discord.ButtonStyle.secondary, row=0)
    async def c0(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.move(interaction, 0)

    @discord.ui.button(label="2", style=discord.ButtonStyle.secondary, row=0)
    async def c1(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.move(interaction, 1)

    @discord.ui.button(label="3", style=discord.ButtonStyle.secondary, row=0)
    async def c2(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.move(interaction, 2)

    @discord.ui.button(label="4", style=discord.ButtonStyle.secondary, row=1)
    async def c3(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.move(interaction, 3)

    @discord.ui.button(label="5", style=discord.ButtonStyle.secondary, row=1)
    async def c4(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.move(interaction, 4)

    @discord.ui.button(label="6", style=discord.ButtonStyle.secondary, row=1)
    async def c5(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.move(interaction, 5)

    @discord.ui.button(label="7", style=discord.ButtonStyle.secondary, row=2)
    async def c6(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.move(interaction, 6)

    @discord.ui.button(label="8", style=discord.ButtonStyle.secondary, row=2)
    async def c7(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.move(interaction, 7)

    @discord.ui.button(label="9", style=discord.ButtonStyle.secondary, row=2)
    async def c8(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.move(interaction, 8)

    async def on_timeout(self):
        if self.finished:
            return
        self.finished = True
        for button in self.children:
            button.disabled = True
        if self.message:
            try:
                await self.message.edit(
                    content="⌛ Tic-tac-toe berakhir karena tidak ada langkah.",
                    view=self,
                )
            except discord.HTTPException:
                pass


class RPSView(discord.ui.View):
    """Suit melawan Fumi menggunakan tombol interaktif."""
    def __init__(self, player):
        super().__init__(timeout=60)
        self.player_id = player.id
        self.finished = False
        self.message = None

    async def choose(self, interaction: discord.Interaction, choice: str):
        if interaction.user.id != self.player_id:
            await interaction.response.send_message(
                "Tombol ini bukan untukmu. Jalankan perintah suit milikmu sendiri ya!",
                ephemeral=True,
            )
            return
        if self.finished:
            await interaction.response.send_message("Ronde ini sudah selesai.", ephemeral=True)
            return

        self.finished = True
        bot_choice = random.choice(("batu", "gunting", "kertas"))
        wins = {("batu", "gunting"), ("gunting", "kertas"), ("kertas", "batu")}
        if choice == bot_choice:
            result = "🤝 Seri!"
        elif (choice, bot_choice) in wins:
            result = "🎉 Kamu menang!"
        else:
            result = "😄 Fumi menang!"

        for button in self.children:
            button.disabled = True
        await interaction.response.edit_message(
            content=(
                f"**Suit Fumi**\nKamu memilih **{choice.title()}**.\n"
                f"Fumi memilih **{bot_choice.title()}**.\n\n{result}"
            ),
            view=self,
        )

    @discord.ui.button(label="🪨 Batu", style=discord.ButtonStyle.primary)
    async def batu(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.choose(interaction, "batu")

    @discord.ui.button(label="✂️ Gunting", style=discord.ButtonStyle.primary)
    async def gunting(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.choose(interaction, "gunting")

    @discord.ui.button(label="📄 Kertas", style=discord.ButtonStyle.primary)
    async def kertas(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.choose(interaction, "kertas")

    async def on_timeout(self):
        if self.finished:
            return
        self.finished = True
        for button in self.children:
            button.disabled = True
        if self.message:
            try:
                await self.message.edit(
                    content="⌛ Waktu memilih suit habis. Jalankan `!rps` untuk ronde baru.",
                    view=self,
                )
            except discord.HTTPException:
                pass


class FriendRPSInviteView(discord.ui.View):
    """Undangan suit antarpemain."""
    def __init__(self, challenger, opponent):
        super().__init__(timeout=30)
        self.challenger = challenger
        self.opponent = opponent
        self.message = None
        self.resolved = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.opponent.id:
            await interaction.response.send_message(
                "Undangan ini bukan untukmu.", ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="Terima", emoji="✅", style=discord.ButtonStyle.success)
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.resolved:
            await interaction.response.send_message("Undangan sudah diproses.", ephemeral=True)
            return
        self.resolved = True
        for item in self.children:
            item.disabled = True

        game = FriendRPSView(self.challenger, self.opponent)
        await interaction.response.edit_message(
            content=(
                f"✊ **Suit Versus Teman**\n{self.challenger.mention} vs {self.opponent.mention}\n"
                "Undangan diterima! Kedua pemain, pilih tombol di pesan ronde baru."
            ),
            view=self,
        )
        game.message = await interaction.channel.send(
            f"🎮 **Ronde suit dimulai!**\n{self.challenger.mention} vs {self.opponent.mention}\n"
            "Pilihan dirahasiakan sampai keduanya memilih.",
            view=game,
        )

    @discord.ui.button(label="Tolak", emoji="✖️", style=discord.ButtonStyle.danger)
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.resolved:
            await interaction.response.send_message("Undangan sudah diproses.", ephemeral=True)
            return
        self.resolved = True
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            content=f"❌ {self.opponent.mention} menolak tantangan suit.",
            view=self,
        )

    async def on_timeout(self):
        if self.resolved:
            return
        self.resolved = True
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                await self.message.edit(content="⌛ Undangan suit kedaluwarsa.", view=self)
            except discord.HTTPException:
                pass


class FriendRPSView(discord.ui.View):
    """Kedua pemain memilih secara privat; hasil tampil setelah keduanya memilih."""
    def __init__(self, challenger, opponent):
        super().__init__(timeout=60)
        self.players = {challenger.id: challenger, opponent.id: opponent}
        self.choices = {}
        self.message = None
        self.finished = False

    async def choose(self, interaction: discord.Interaction, choice: str):
        if self.finished:
            await interaction.response.send_message("Ronde ini sudah selesai.", ephemeral=True)
            return
        if interaction.user.id not in self.players:
            await interaction.response.send_message("Kamu bukan pemain di ronde ini.", ephemeral=True)
            return
        if interaction.user.id in self.choices:
            await interaction.response.send_message("Pilihanmu sudah tersimpan.", ephemeral=True)
            return

        self.choices[interaction.user.id] = choice
        await interaction.response.send_message(
            "Pilihanmu sudah tersimpan. Menunggu pemain lain...", ephemeral=True
        )
        if len(self.choices) == 2:
            await self.finish_round()

    async def finish_round(self):
        if self.finished:
            return
        self.finished = True
        for item in self.children:
            item.disabled = True

        ids = list(self.players.keys())
        first, second = ids[0], ids[1]
        choice1, choice2 = self.choices[first], self.choices[second]
        wins = {("batu", "gunting"), ("gunting", "kertas"), ("kertas", "batu")}
        if choice1 == choice2:
            result = "🤝 Hasilnya seri!"
        elif (choice1, choice2) in wins:
            result = f"🏆 {self.players[first].mention} menang!"
        else:
            result = f"🏆 {self.players[second].mention} menang!"

        if self.message:
            try:
                await self.message.edit(
                    content=(
                        f"✊ **Hasil Suit Versus**\n"
                        f"{self.players[first].mention} memilih **{choice1.title()}**.\n"
                        f"{self.players[second].mention} memilih **{choice2.title()}**.\n\n{result}"
                    ),
                    view=self,
                )
            except discord.HTTPException:
                pass

    @discord.ui.button(label="🪨 Batu", style=discord.ButtonStyle.primary, row=0)
    async def batu(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.choose(interaction, "batu")

    @discord.ui.button(label="✂️ Gunting", style=discord.ButtonStyle.primary, row=0)
    async def gunting(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.choose(interaction, "gunting")

    @discord.ui.button(label="📄 Kertas", style=discord.ButtonStyle.primary, row=0)
    async def kertas(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.choose(interaction, "kertas")

    async def on_timeout(self):
        if self.finished:
            return
        self.finished = True
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                if self.choices:
                    chosen_names = [self.players[user_id].mention for user_id in self.choices]
                    content = (
                        "⌛ Waktu memilih habis. Ronde dibatalkan.\n"
                        "Pilihan sudah masuk dari: " + ", ".join(chosen_names)
                    )
                else:
                    content = "⌛ Waktu memilih habis. Tidak ada pemain yang memilih."
                await self.message.edit(content=content, view=self)
            except discord.HTTPException:
                pass


class GuessNumberView(discord.ui.View):
    """Tebak angka 1-24 dengan halaman tombol."""
    def __init__(self, player, target, on_finish=None):
        super().__init__(timeout=120)
        self.player_id = player.id
        self.player_mention = player.mention
        self.target = target
        self.page = 0
        self.finished = False
        self.attempts = 0
        self.message = None
        self.on_finish = on_finish
        self.build_page()

    def finish(self):
        self.finished = True
        if self.on_finish:
            self.on_finish()

    def build_page(self):
        self.clear_items()
        start = self.page * 8 + 1
        end = min(start + 7, 24)
        for number in range(start, end + 1):
            button = discord.ui.Button(
                label=str(number),
                style=discord.ButtonStyle.secondary,
                row=(number - start) // 4,
            )
            button.callback = self.make_callback(number)
            self.add_item(button)

        prev_button = discord.ui.Button(
            label="◀ Sebelumnya",
            style=discord.ButtonStyle.primary,
            row=4,
            disabled=self.page == 0,
        )
        prev_button.callback = self.previous_page
        self.add_item(prev_button)

        next_button = discord.ui.Button(
            label="Berikutnya ▶",
            style=discord.ButtonStyle.primary,
            row=4,
            disabled=self.page == 2,
        )
        next_button.callback = self.next_page
        self.add_item(next_button)

    def make_callback(self, number):
        async def callback(interaction: discord.Interaction):
            if interaction.user.id != self.player_id:
                await interaction.response.send_message(
                    "Game ini bukan milikmu. Jalankan `!tebakangka` untuk bermain sendiri.",
                    ephemeral=True,
                )
                return
            if self.finished:
                await interaction.response.send_message("Game sudah selesai.", ephemeral=True)
                return

            self.attempts += 1
            if number == self.target:
                self.finish()
                for item in self.children:
                    item.disabled = True
                await interaction.response.edit_message(
                    content=(
                        f"🎉 Benar, {interaction.user.mention}! Angkanya **{self.target}**.\n"
                        f"Kamu berhasil dalam **{self.attempts}** tebakan!"
                    ),
                    view=self,
                )
                return

            hint = "📈 Terlalu kecil!" if number < self.target else "📉 Terlalu besar!"
            await interaction.response.send_message(
                f"{hint} Tebakanmu: **{number}**. Coba lagi!",
                ephemeral=True,
            )

        return callback

    async def previous_page(self, interaction: discord.Interaction):
        if interaction.user.id != self.player_id:
            await interaction.response.send_message("Game ini bukan milikmu.", ephemeral=True)
            return
        if self.finished:
            await interaction.response.send_message("Game sudah selesai.", ephemeral=True)
            return
        self.page = max(0, self.page - 1)
        self.build_page()
        await interaction.response.edit_message(content=self.prompt_text(), view=self)

    async def next_page(self, interaction: discord.Interaction):
        if interaction.user.id != self.player_id:
            await interaction.response.send_message("Game ini bukan milikmu.", ephemeral=True)
            return
        if self.finished:
            await interaction.response.send_message("Game sudah selesai.", ephemeral=True)
            return
        self.page = min(2, self.page + 1)
        self.build_page()
        await interaction.response.edit_message(content=self.prompt_text(), view=self)

    def prompt_text(self):
        return (
            f"🎯 **Tebak Angka Fumi (1–24)**\n"
            f"{self.player_mention}, pilih satu angka. Kamu mendapat petunjuk jika tebakanmu terlalu kecil atau besar.\n"
            f"Halaman **{self.page + 1}/3** · Tebakan: **{self.attempts}**"
        )

    async def on_timeout(self):
        if self.finished:
            return
        self.finish()
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                await self.message.edit(
                    content=f"⌛ Waktu habis! Angka rahasianya **{self.target}**.",
                    view=self,
                )
            except discord.HTTPException:
                pass


# =========================
# GACHA VERSUS
# =========================
GACHA_ROSTER_FILE = os.getenv("GACHA_ROSTER_FILE", "gacha_roster.json")


def _load_gacha_rosters():
    try:
        with open(GACHA_ROSTER_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _save_gacha_rosters(rosters):
    temp_path = GACHA_ROSTER_FILE + ".tmp"
    with open(temp_path, "w", encoding="utf-8") as file:
        json.dump(rosters, file, ensure_ascii=False, indent=2)
    os.replace(temp_path, GACHA_ROSTER_FILE)


class GachaVersusView(discord.ui.View):
    def __init__(self, roster, owner_id):
        super().__init__(timeout=180)
        self.roster = list(roster)
        self.owner_id = owner_id
        self.pairs = []
        self.used = set()
        self.finished = False
        self.message = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "Hanya pembuat sesi gacha yang bisa memakai tombol ini.", ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="Gacha pasangan", emoji="🎲", style=discord.ButtonStyle.primary)
    async def draw_pair(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.finished:
            await interaction.response.send_message("Sesi gacha sudah selesai.", ephemeral=True)
            return
        remaining = [name for name in self.roster if name not in self.used]
        if len(remaining) < 2:
            await interaction.response.send_message(
                "Peserta yang belum dipasangkan kurang dari dua. Tambahkan peserta atau reset daftar.",
                ephemeral=True,
            )
            return
        first, second = random.sample(remaining, 2)
        self.used.update((first, second))
        self.pairs.append((first, second))
        await interaction.response.edit_message(content=self.render_text(), view=self)

    @discord.ui.button(label="Selesai", emoji="🏁", style=discord.ButtonStyle.secondary)
    async def finish_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.finished = True
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            content=self.render_text() + "\n\n🏁 Sesi gacha ditutup. Daftar peserta tetap tersimpan.",
            view=self,
        )

    def render_text(self):
        lines = ["🎲 **GACHA VERSUS**", "", "**Hasil pasangan:**"]
        if self.pairs:
            lines.extend(
                f"**{i}.** {first} ⚔️ {second}"
                for i, (first, second) in enumerate(self.pairs, 1)
            )
        else:
            lines.append("Belum ada pasangan yang diundi.")
        remaining = [name for name in self.roster if name not in self.used]
        lines.extend([
            "",
            f"👥 Peserta awal: **{len(self.roster)}**",
            f"✅ Sudah mendapat pasangan: **{len(self.used)}**",
            f"⌛ Belum dipasangkan: **{len(remaining)}**",
            "",
            "Tekan **Gacha pasangan** untuk mengundi dua peserta berikutnya.",
        ])
        return "\n".join(lines)

    async def on_timeout(self):
        if self.finished:
            return
        self.finished = True
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                await self.message.edit(
                    content=self.render_text() + "\n\n⌛ Sesi gacha kedaluwarsa.",
                    view=self,
                )
            except discord.HTTPException:
                pass


def setup_games(bot):
    @bot.command(name="ttt", aliases=["tictactoe"])
    async def ttt(ctx, opponent: discord.Member = None):
        if opponent is None:
            await ctx.send("Gunakan `!ttt @teman`.")
            return
        if opponent.bot or opponent.id == ctx.author.id:
            await ctx.send("Pilih anggota lain, bukan dirimu sendiri atau bot.")
            return
        view = TicTacToe(ctx.author, opponent)
        view.message = await ctx.send(
            f"**Tic-tac-toe**\n{ctx.author.mention} ❌ vs {opponent.mention} ⭕\n"
            f"Giliran {ctx.author.mention} (❌)",
            view=view,
        )

    @bot.command(name="rps", aliases=["suit"])
    async def rps(ctx, opponent: discord.Member = None):
        if opponent is None:
            view = RPSView(ctx.author)
            view.message = await ctx.send(
                f"✊ **Suit melawan Fumi!** {ctx.author.mention}, pilih tombolmu di bawah.",
                view=view,
            )
            return
        if opponent.bot or opponent.id == ctx.author.id:
            await ctx.send("Pilih anggota lain, bukan dirimu sendiri atau bot.")
            return
        view = FriendRPSInviteView(ctx.author, opponent)
        view.message = await ctx.send(
            f"✊ **Tantangan Suit!**\n{ctx.author.mention} menantang {opponent.mention} bermain suit.\n"
            f"{opponent.mention}, terima atau tolak tantangan ini.",
            view=view,
        )

    active_numbers = {}

    @bot.command(name="tebakangka")
    async def tebakangka(ctx):
        key = (ctx.guild.id if ctx.guild else 0, ctx.author.id)
        existing = active_numbers.get(key)
        if existing and not existing.finished:
            await ctx.send("Kamu masih punya game Tebak Angka yang aktif!")
            return

        def clear_session():
            active_numbers.pop(key, None)

        view = GuessNumberView(ctx.author, random.randint(1, 24), on_finish=clear_session)
        view.message = await ctx.send(view.prompt_text(), view=view)
        active_numbers[key] = view

    @bot.command(name="gamehelp")
    async def gamehelp(ctx):
        await ctx.send(
            "**Minigames Fumi**\n"
            "`!ttt @teman` — tic-tac-toe dengan tombol\n"
            "`!rps` — suit melawan Fumi\n"
            "`!rps @teman` — tantang teman bermain suit\n"
            "`!tebakangka` — tebak angka 1–24\n"
            "`!gacha_add Nama1, Nama2` — tambah peserta gacha (izin Kelola Server)\n"
            "`!gacha_list` — lihat daftar peserta\n"
            "`!gacha_remove Nama` — hapus peserta (izin Kelola Server)\n"
            "`!gacha_versus` — mulai undian pasangan (izin Kelola Server)\n"
            "`!gacha_reset` — hapus daftar peserta (izin Kelola Server)\n"
            "`!gacha_help` — bantuan gacha"
        )

    # =========================
    # GACHA COMMANDS
    # =========================
    @bot.command(name="gacha_add")
    @commands.has_guild_permissions(manage_guild=True)
    async def gacha_add(ctx, *, names: str):
        roster = _load_gacha_rosters()
        key = str(ctx.guild.id)
        participants = roster.setdefault(key, [])
        added = []
        for raw_name in names.split(","):
            name = raw_name.strip()
            if name and name.casefold() not in {item.casefold() for item in participants}:
                participants.append(name)
                added.append(name)
        _save_gacha_rosters(roster)
        if added:
            await ctx.send("✅ Peserta ditambahkan: " + ", ".join(added))
        else:
            await ctx.send("Tidak ada peserta baru. Pastikan nama dipisahkan dengan koma dan tidak duplikat.")

    @bot.command(name="gacha_list")
    async def gacha_list(ctx):
        roster = _load_gacha_rosters()
        participants = roster.get(str(ctx.guild.id), []) if ctx.guild else []
        if not participants:
            await ctx.send("Daftar gacha masih kosong. Tambahkan dengan `!gacha_add Nama1, Nama2`.")
            return
        await ctx.send("📋 **Daftar Peserta Gacha**\n" + "\n".join(
            f"{i}. {name}" for i, name in enumerate(participants, 1)
        ))

    @bot.command(name="gacha_remove")
    @commands.has_guild_permissions(manage_guild=True)
    async def gacha_remove(ctx, *, name: str):
        if not ctx.guild:
            await ctx.send("Perintah ini hanya bisa dipakai di server.")
            return
        roster = _load_gacha_rosters()
        key = str(ctx.guild.id)
        participants = roster.get(key, [])
        match = next((item for item in participants if item.casefold() == name.strip().casefold()), None)
        if match is None:
            await ctx.send(f"Peserta **{name.strip()}** tidak ditemukan.")
            return
        participants.remove(match)
        _save_gacha_rosters(roster)
        await ctx.send(f"🗑️ Peserta **{match}** dihapus dari daftar.")

    @bot.command(name="gacha_versus")
    @commands.has_guild_permissions(manage_guild=True)
    async def gacha_versus(ctx):
        if not ctx.guild:
            await ctx.send("Perintah ini hanya bisa dipakai di server.")
            return
        roster = _load_gacha_rosters()
        participants = roster.get(str(ctx.guild.id), [])
        if len(participants) < 2:
            await ctx.send("Minimal perlu dua peserta. Tambahkan dengan `!gacha_add Nama1, Nama2`.")
            return
        view = GachaVersusView(participants, ctx.author.id)
        view.message = await ctx.send(view.render_text(), view=view)

    @bot.command(name="gacha_reset")
    @commands.has_guild_permissions(manage_guild=True)
    async def gacha_reset(ctx):
        if not ctx.guild:
            await ctx.send("Perintah ini hanya bisa dipakai di server.")
            return
        roster = _load_gacha_rosters()
        key = str(ctx.guild.id)
        if key not in roster or not roster[key]:
            await ctx.send("Daftar peserta gacha sudah kosong.")
            return
        del roster[key]
        _save_gacha_rosters(roster)
        await ctx.send("♻️ Daftar peserta gacha berhasil di-reset.")

    @bot.command(name="gacha_help")
    async def gacha_help(ctx):
        await ctx.send(
            "**Bantuan Gacha Versus**\n"
            "`!gacha_add Nama1, Nama2, Nama3` — tambah peserta (Kelola Server)\n"
            "`!gacha_list` — lihat daftar peserta\n"
            "`!gacha_remove Nama` — hapus peserta (Kelola Server)\n"
            "`!gacha_versus` — mulai undian pasangan (Kelola Server)\n"
            "`!gacha_reset` — hapus daftar peserta (Kelola Server)\n\n"
            "Satu sesi memasangkan peserta secara acak tanpa memasangkan orang yang sama dua kali. "
            "Jika jumlah peserta ganjil, satu peserta terakhir tidak mendapat pasangan."
        )

    @gacha_add.error
    @gacha_remove.error
    @gacha_versus.error
    @gacha_reset.error
    async def gacha_permission_error(ctx, error):
        if isinstance(error, commands.MissingPermissions):
            await ctx.send("⛔ Kamu perlu izin **Kelola Server (Manage Server)** untuk perintah itu.")
        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.send("⚠️ Masukkan nama peserta. Contoh: `!gacha_add Nafumi, Lyra`.")
        else:
            raise error
