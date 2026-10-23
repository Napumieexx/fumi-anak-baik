import random
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

    def update_buttons(self):
        for i, button in enumerate(self.children):
            button.label = MARK[self.board[i]] if self.board[i] else " "
            button.disabled = bool(self.board[i]) or self.finished

    def winner(self):
        lines = [(0,1,2),(3,4,5),(6,7,8),(0,3,6),(1,4,7),(2,5,8),(0,4,8),(2,4,6)]
        for a, b, c in lines:
            if self.board[a] and self.board[a] == self.board[b] == self.board[c]:
                return self.board[a]
        return 0

    async def move(self, interaction, index):
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

    @discord.ui.button(label=" ", style=discord.ButtonStyle.secondary, row=0)
    async def c0(self, interaction, button): await self.move(interaction, 0)
    @discord.ui.button(label=" ", style=discord.ButtonStyle.secondary, row=0)
    async def c1(self, interaction, button): await self.move(interaction, 1)
    @discord.ui.button(label=" ", style=discord.ButtonStyle.secondary, row=0)
    async def c2(self, interaction, button): await self.move(interaction, 2)
    @discord.ui.button(label=" ", style=discord.ButtonStyle.secondary, row=1)
    async def c3(self, interaction, button): await self.move(interaction, 3)
    @discord.ui.button(label=" ", style=discord.ButtonStyle.secondary, row=1)
    async def c4(self, interaction, button): await self.move(interaction, 4)
    @discord.ui.button(label=" ", style=discord.ButtonStyle.secondary, row=1)
    async def c5(self, interaction, button): await self.move(interaction, 5)
    @discord.ui.button(label=" ", style=discord.ButtonStyle.secondary, row=2)
    async def c6(self, interaction, button): await self.move(interaction, 6)
    @discord.ui.button(label=" ", style=discord.ButtonStyle.secondary, row=2)
    async def c7(self, interaction, button): await self.move(interaction, 7)
    @discord.ui.button(label=" ", style=discord.ButtonStyle.secondary, row=2)
    async def c8(self, interaction, button): await self.move(interaction, 8)

    async def on_timeout(self):
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

    async def choose(self, interaction, choice):
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
                f"**Suit Fumi**\nKamu memilih **{choice}**.\n"
                f"Fumi memilih **{bot_choice}**.\n\n{result}"
            ),
            view=self,
        )

    @discord.ui.button(label="🪨 Batu", style=discord.ButtonStyle.primary)
    async def batu(self, interaction, button):
        await self.choose(interaction, "batu")

    @discord.ui.button(label="✂️ Gunting", style=discord.ButtonStyle.primary)
    async def gunting(self, interaction, button):
        await self.choose(interaction, "gunting")

    @discord.ui.button(label="📄 Kertas", style=discord.ButtonStyle.primary)
    async def kertas(self, interaction, button):
        await self.choose(interaction, "kertas")

    async def on_timeout(self):
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


class GuessNumberView(discord.ui.View):
    """Tebak angka 1-24 dengan halaman tombol, khusus pemulai game."""
    def __init__(self, player, target):
        super().__init__(timeout=120)
        self.player_id = player.id
        self.player_mention = player.mention
        self.target = target
        self.page = 0
        self.finished = False
        self.attempts = 0
        self.message = None
        self.build_page()

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
        async def callback(interaction):
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
                self.finished = True
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

    async def previous_page(self, interaction):
        if interaction.user.id != self.player_id:
            await interaction.response.send_message("Game ini bukan milikmu.", ephemeral=True)
            return
        if self.finished:
            await interaction.response.send_message("Game sudah selesai.", ephemeral=True)
            return
        self.page -= 1
        self.build_page()
        await interaction.response.edit_message(
            content=self.prompt_text(), view=self
        )

    async def next_page(self, interaction):
        if interaction.user.id != self.player_id:
            await interaction.response.send_message("Game ini bukan milikmu.", ephemeral=True)
            return
        if self.finished:
            await interaction.response.send_message("Game sudah selesai.", ephemeral=True)
            return
        self.page += 1
        self.build_page()
        await interaction.response.edit_message(
            content=self.prompt_text(), view=self
        )

    def prompt_text(self):
        return (
            f"🎯 **Tebak Angka Fumi (1–24)**\n"
            f"{self.player_mention}, "
            f"pilih satu angka. Kamu mendapat petunjuk kalau tebakanmu terlalu kecil atau besar.\n"
            f"Halaman **{self.page + 1}/3** · Tebakan: **{self.attempts}**"
        )

    async def on_timeout(self):
        self.finished = True
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
    async def rps(ctx):
        view = RPSView(ctx.author)
        await ctx.send(
            f"✊ **Suit melawan Fumi!** {ctx.author.mention}, pilih tombolmu di bawah.",
            view=view,
        )

    active_numbers = {}

    @bot.command(name="tebakangka")
    async def tebakangka(ctx):
        key = (ctx.guild.id if ctx.guild else 0, ctx.author.id)
        target = random.randint(1, 24)
        view = GuessNumberView(ctx.author, target)
        view.message = await ctx.send(view.prompt_text(), view=view)
        active_numbers[key] = view

    @bot.command(name="gamehelp")
    async def gamehelp(ctx):
        await ctx.send(
            "**Minigames Fumi**\n"
            "`!ttt @teman` — tic-tac-toe dengan tombol\n"
            "`!rps` — suit dengan tombol batu/gunting/kertas\n"
            "`!tebakangka` — tebak angka 1–24 dengan tombol\n"
            "Game berakhir jika tebakan benar atau waktu habis."
        )
