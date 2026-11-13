from __future__ import annotations

import asyncio
import os
import random
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from urllib.parse import urlparse, unquote

import aiohttp
import discord
from discord.ext import commands


# Fumi Music - High Quality direct-stream player
# Playback accepts direct audio-stream URLs from sources that authorize bot playback.
# It intentionally does not extract/rip audio from Spotify or YouTube URLs.

PLAYER_COLOR = discord.Color.from_rgb(35, 190, 120)
ERROR_COLOR = discord.Color.orange()


@dataclass
class Track:
    url: str
    title: str
    requester_id: int
    webpage_url: str | None = None
    duration: str = "Durasi tidak diketahui"
    duration_seconds: int | None = None
    thumbnail: str | None = None
    artist: str | None = None


@dataclass
class GuildPlayer:
    queue: deque[Track] = field(default_factory=deque)
    history: deque[Track] = field(default_factory=lambda: deque(maxlen=30))
    current: Track | None = None
    repeat: bool = False
    volume: float = 0.70
    text_channel_id: int | None = None
    started_at: float | None = None
    paused_at: float | None = None
    paused_total: float = 0.0
    message: discord.Message | None = None
    view: discord.ui.View | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    suppress_next: bool = False


class FumiPlayerView(discord.ui.View):
    def __init__(self, cog: "Music", guild_id: int):
        super().__init__(timeout=900)
        self.cog = cog
        self.guild_id = guild_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.guild is None or interaction.guild.id != self.guild_id:
            await interaction.response.send_message("Player ini bukan milik server kamu.", ephemeral=True)
            return False
        voice = getattr(interaction.user, "voice", None)
        if not voice or not voice.channel:
            await interaction.response.send_message("Masuk ke voice channel terlebih dahulu.", ephemeral=True)
            return False
        player = self.cog.players.get(self.guild_id)
        if not player or not interaction.guild.voice_client:
            await interaction.response.send_message("Belum ada musik yang diputar.", ephemeral=True)
            return False
        bot_voice = interaction.guild.voice_client
        if bot_voice.channel and voice.channel.id != bot_voice.channel.id:
            await interaction.response.send_message("Kamu harus berada di voice channel yang sama dengan Fumi.", ephemeral=True)
            return False
        return True

    async def _ack(self, interaction: discord.Interaction, message: str):
        if not interaction.response.is_done():
            await interaction.response.send_message(message, ephemeral=True)

    @discord.ui.button(emoji="⏮️", style=discord.ButtonStyle.secondary, row=0)
    async def previous_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        ok = await self.cog.previous_track(self.guild_id)
        await self._ack(interaction, "Memutar lagu sebelumnya." if ok else "Tidak ada lagu sebelumnya.")

    @discord.ui.button(emoji="⏹️", style=discord.ButtonStyle.danger, row=0)
    async def stop_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.stop_track(self.guild_id)
        await self._ack(interaction, "Pemutaran dihentikan. Fumi tetap berada di voice channel.")

    @discord.ui.button(emoji="⏯️", style=discord.ButtonStyle.primary, row=0)
    async def pause_resume_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        voice = interaction.guild.voice_client
        if voice.is_playing():
            voice.pause()
            player = self.cog.players[self.guild_id]
            player.paused_at = time.monotonic()
            await self._ack(interaction, "Musik dijeda.")
        elif voice.is_paused():
            voice.resume()
            player = self.cog.players[self.guild_id]
            if player.paused_at is not None:
                player.paused_total += time.monotonic() - player.paused_at
                player.paused_at = None
            await self._ack(interaction, "Musik dilanjutkan.")
        else:
            await self._ack(interaction, "Tidak ada lagu yang sedang diputar.")

    @discord.ui.button(emoji="⏭️", style=discord.ButtonStyle.secondary, row=0)
    async def skip_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        voice = interaction.guild.voice_client
        if voice and (voice.is_playing() or voice.is_paused()):
            voice.stop()
            await self._ack(interaction, "Lagu dilewati.")
        else:
            await self._ack(interaction, "Tidak ada lagu yang sedang diputar.")

    @discord.ui.button(emoji="🔁", style=discord.ButtonStyle.success, row=0)
    async def repeat_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        player = self.cog.players[self.guild_id]
        player.repeat = not player.repeat
        button.style = discord.ButtonStyle.success if player.repeat else discord.ButtonStyle.secondary
        await interaction.response.edit_message(embed=self.cog.make_embed(self.guild_id), view=self)


class Music(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.players: dict[int, GuildPlayer] = defaultdict(GuildPlayer)
        self.progress_task: asyncio.Task | None = None

    async def cog_load(self):
        self.progress_task = asyncio.create_task(self.progress_updater())

    def cog_unload(self):
        if self.progress_task:
            self.progress_task.cancel()

    async def progress_updater(self):
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            for guild_id, player in list(self.players.items()):
                if player.current and player.message:
                    await self.refresh_player(guild_id)
            # Satu edit pada pesan player tiap 5 detik; tidak membuat pesan baru.
            await asyncio.sleep(5)

    def get_player(self, guild_id: int) -> GuildPlayer:
        return self.players[guild_id]

    @staticmethod
    def _safe_title(url: str) -> str:
        parsed = urlparse(url)
        name = unquote(parsed.path.rsplit("/", 1)[-1]).strip()
        return name or parsed.netloc or "Audio stream"

    @staticmethod
    def _is_direct_url(value: str) -> bool:
        try:
            parsed = urlparse(value)
            return parsed.scheme in ("http", "https") and bool(parsed.netloc)
        except Exception:
            return False

    @staticmethod
    def _format_time(seconds: int) -> str:
        seconds = max(0, int(seconds))
        return f"{seconds // 60:02}:{seconds % 60:02}"

    @staticmethod
    def _progress_bar(elapsed: int, duration: int, width: int = 16) -> str:
        ratio = min(1.0, max(0.0, elapsed / duration)) if duration > 0 else 0.0
        filled = min(width, int(ratio * width))
        return "🟩" * filled + "▬" * (width - filled)

    def make_embed(self, guild_id: int) -> discord.Embed:
        player = self.get_player(guild_id)
        track = player.current
        if track is None:
            embed = discord.Embed(
                title="🎵 FUMI MUSIC PLAYER",
                description="Belum ada lagu yang diputar. Gunakan `!p <URL audio langsung>` untuk memulai.",
                color=PLAYER_COLOR,
            )
            embed.add_field(name="Queue", value=f"{len(player.queue)} lagu", inline=True)
            embed.add_field(name="Mode", value="High Quality", inline=True)
            return embed

        elapsed = 0
        if player.started_at is not None:
            reference_time = player.paused_at if player.paused_at is not None else time.monotonic()
            elapsed = max(0, int(reference_time - player.started_at - player.paused_total))

        embed = discord.Embed(title="🎵 FUMI MUSIC PLAYER", color=PLAYER_COLOR)
        title = discord.utils.escape_markdown(track.title)
        artist_line = f"\n**Artist:** {discord.utils.escape_markdown(track.artist)}" if track.artist else ""
        embed.description = f"**{title}**{artist_line}\nRequested by <@{track.requester_id}>"

        if track.thumbnail:
            embed.set_thumbnail(url=track.thumbnail)
        elif track.webpage_url:
            embed.url = track.webpage_url

        if track.duration_seconds and track.duration_seconds > 0:
            elapsed = min(elapsed, track.duration_seconds)
            bar = self._progress_bar(elapsed, track.duration_seconds)
            progress_text = (
                f"`{self._format_time(elapsed)}` {bar} "
                f"`{self._format_time(track.duration_seconds)}`"
            )
        else:
            progress_text = f"`{self._format_time(elapsed)}`  🔴 LIVE / durasi tidak diketahui"
        embed.add_field(name="Progress", value=progress_text, inline=False)

        next_tracks = list(player.queue)[:3]
        if next_tracks:
            queue_text = "\n".join(
                f"`{i}.` {discord.utils.escape_markdown(item.title)[:70]}"
                for i, item in enumerate(next_tracks, 1)
            )
        else:
            queue_text = "Tidak ada lagu berikutnya."
        embed.add_field(name=f"Up Next · {len(player.queue)} lagu", value=queue_text, inline=False)
        embed.add_field(name="Audio", value="High Quality · Opus / voice channel", inline=True)
        embed.add_field(name="Repeat", value="Aktif" if player.repeat else "Nonaktif", inline=True)
        embed.set_footer(text="Fumi Music • !shuffle untuk mengacak antrean")
        return embed

    async def lookup_track_metadata(self, track: Track):
        """Cari cover dan metadata katalog berdasarkan nama file/track yang terbaca dari URL."""
        raw_name = self._safe_title(track.url)
        # Hindari pencarian yang tidak berguna untuk endpoint generik seperti /stream atau /live.
        stem = raw_name.rsplit(".", 1)[0]
        query = stem.replace("_", " ").replace("-", " ").strip()
        if len(query) < 3 or query.lower() in {"stream", "audio", "live", "music", "listen"}:
            return
        timeout = aiohttp.ClientTimeout(total=6)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(
                    "https://itunes.apple.com/search",
                    params={"term": query, "entity": "song", "limit": 1},
                ) as response:
                    if response.status != 200:
                        return
                    data = await response.json(content_type=None)
            results = data.get("results") or []
            if not results:
                return
            item = results[0]
            track.title = item.get("trackName") or track.title
            track.artist = item.get("artistName")
            artwork = item.get("artworkUrl100")
            if artwork:
                track.thumbnail = artwork.replace("100x100bb", "600x600bb")
            duration_ms = item.get("trackTimeMillis")
            if isinstance(duration_ms, (int, float)) and duration_ms > 0:
                track.duration_seconds = int(duration_ms / 1000)
                track.duration = self._format_time(track.duration_seconds)
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError) as error:
            print(f"Metadata/thumbnail lookup dilewati: {error}")

    async def refresh_player(self, guild_id: int):
        player = self.get_player(guild_id)
        if player.message:
            try:
                await player.message.edit(embed=self.make_embed(guild_id), view=player.view)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass

    async def connect_for_context(self, ctx: commands.Context) -> discord.VoiceClient | None:
        if not ctx.guild:
            await ctx.send("Command musik hanya bisa digunakan di server.")
            return None
        if not ctx.author.voice or not ctx.author.voice.channel:
            await ctx.send("Masuk ke voice channel terlebih dahulu.")
            return None
        voice = ctx.guild.voice_client
        try:
            if voice is None:
                voice = await ctx.author.voice.channel.connect()
            elif voice.channel != ctx.author.voice.channel:
                await voice.move_to(ctx.author.voice.channel)
            return voice
        except (discord.Forbidden, discord.HTTPException) as error:
            await ctx.send(f"Fumi gagal bergabung ke voice channel: `{error}`")
            return None

    async def start_next(self, guild_id: int):
        player = self.get_player(guild_id)
        guild = self.bot.get_guild(guild_id)
        if guild is None:
            return
        voice = guild.voice_client
        if voice is None or voice.is_playing() or voice.is_paused():
            return

        async with player.lock:
            if player.repeat and player.current is not None:
                track = player.current
            elif player.queue:
                if player.current is not None:
                    player.history.append(player.current)
                track = player.queue.popleft()
                player.current = track
            else:
                player.current = None
                player.started_at = None
                await self.refresh_player(guild_id)
                return

            player.started_at = time.monotonic()
            player.paused_at = None
            player.paused_total = 0.0

            # FFmpeg decodes the authorized stream to PCM; discord.py encodes it as Opus
            # using the voice connection's negotiated bitrate/codec.
            before_options = "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"
            options = "-vn -ac 2 -ar 48000"
            try:
                source = discord.PCMVolumeTransformer(
                    discord.FFmpegPCMAudio(track.url, before_options=before_options, options=options),
                    volume=player.volume,
                )
                def after_play(error: Exception | None):
                    if error:
                        print(f"Fumi Music playback error: {error}")
                    future = asyncio.run_coroutine_threadsafe(self._after_track(guild_id), self.bot.loop)
                    try:
                        future.result(timeout=0)
                    except Exception:
                        pass
                voice.play(source, after=after_play)
            except Exception as error:
                print(f"Gagal memulai audio: {error}")
                player.current = None
                if player.queue:
                    self.bot.loop.call_soon(asyncio.create_task, self.start_next(guild_id))
            await self.refresh_player(guild_id)

    async def _after_track(self, guild_id: int):
        player = self.get_player(guild_id)
        if player.suppress_next:
            player.suppress_next = False
            await self.refresh_player(guild_id)
            return
        if not player.repeat:
            if player.current is not None:
                player.history.append(player.current)
            player.current = None
        await self.start_next(guild_id)

    async def stop_track(self, guild_id: int):
        player = self.get_player(guild_id)
        guild = self.bot.get_guild(guild_id)
        voice = guild.voice_client if guild else None
        if voice and (voice.is_playing() or voice.is_paused()):
            player.suppress_next = True
            voice.stop()
        player.current = None
        player.started_at = None
        player.paused_at = None
        await self.refresh_player(guild_id)

    async def previous_track(self, guild_id: int) -> bool:
        player = self.get_player(guild_id)
        if not player.history:
            return False
        guild = self.bot.get_guild(guild_id)
        voice = guild.voice_client if guild else None
        previous = player.history.pop()
        if player.current:
            player.queue.appendleft(player.current)
        player.queue.appendleft(previous)
        player.current = None
        player.repeat = False
        if voice and (voice.is_playing() or voice.is_paused()):
            player.suppress_next = True
            voice.stop()
        await self.start_next(guild_id)
        return True

    @commands.command(name="p", aliases=["play"])
    async def play_command(self, ctx: commands.Context, *, query: str):
        if not self._is_direct_url(query):
            await ctx.send(
                "Untuk saat ini `!p` menerima **URL audio langsung** dari sumber yang mengizinkan streaming bot. "
                "Judul lagu dan link halaman Spotify/YouTube belum bisa diputar langsung tanpa integrasi sumber audio resmi."
            )
            return
        voice = await self.connect_for_context(ctx)
        if voice is None:
            return
        player = self.get_player(ctx.guild.id)
        track = Track(url=query, title=self._safe_title(query), requester_id=ctx.author.id, webpage_url=query)
        await self.lookup_track_metadata(track)
        if voice.is_playing() or voice.is_paused() or player.current is not None:
            player.queue.append(track)
            await ctx.send(f"➕ **Ditambahkan ke antrean:** {discord.utils.escape_markdown(track.title)}")
            await self.refresh_player(ctx.guild.id)
        else:
            player.queue.append(track)
            player.text_channel_id = ctx.channel.id
            await self.start_next(ctx.guild.id)
            await self.send_or_update_player(ctx)

    async def send_or_update_player(self, ctx: commands.Context):
        player = self.get_player(ctx.guild.id)
        view = FumiPlayerView(self, ctx.guild.id)
        player.view = view
        if player.message:
            try:
                await player.message.edit(embed=self.make_embed(ctx.guild.id), view=view)
                return
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                player.message = None
        player.message = await ctx.send(embed=self.make_embed(ctx.guild.id), view=view)

    @commands.command(name="shuffle")
    async def shuffle_command(self, ctx: commands.Context):
        player = self.get_player(ctx.guild.id)
        if len(player.queue) < 2:
            await ctx.send("Antrean membutuhkan minimal 2 lagu untuk diacak.")
            return
        items = list(player.queue)
        random.shuffle(items)
        player.queue = deque(items)
        await ctx.send("🔀 Antrean berhasil diacak.")
        await self.refresh_player(ctx.guild.id)

    @commands.command(name="queue", aliases=["q"])
    async def queue_command(self, ctx: commands.Context):
        player = self.get_player(ctx.guild.id)
        embed = discord.Embed(title="📜 FUMI MUSIC QUEUE", color=PLAYER_COLOR)
        if player.current:
            embed.add_field(name="Now Playing", value=player.current.title, inline=False)
        if player.queue:
            lines = [f"`{i}.` {track.title[:80]}" for i, track in enumerate(list(player.queue)[:15], 1)]
            embed.add_field(name=f"Up Next · {len(player.queue)} lagu", value="\n".join(lines), inline=False)
        else:
            embed.add_field(name="Queue", value="Antrean kosong.", inline=False)
        await ctx.send(embed=embed)

    @commands.command(name="leave", aliases=["disconnect"])
    async def leave_command(self, ctx: commands.Context):
        if not ctx.guild.voice_client:
            await ctx.send("Fumi tidak sedang berada di voice channel.")
            return
        player = self.get_player(ctx.guild.id)
        player.suppress_next = True
        player.queue.clear()
        player.current = None
        await ctx.guild.voice_client.disconnect()
        await ctx.send("👋 Fumi telah meninggalkan voice channel.")

    @commands.command(name="help", aliases=["musichelp", "mhelp"])
    async def music_help_command(self, ctx: commands.Context):
        embed = discord.Embed(title="🎵 FUMI MUSIC — HELP", color=PLAYER_COLOR)
        embed.add_field(
            name="Pemutaran",
            value=("`!p <URL audio>` — Putar audio\n`!queue` — Lihat antrean\n"
                   "`!leave` — Keluar dari voice channel"),
            inline=False,
        )
        embed.add_field(
            name="Kontrol player",
            value="Gunakan tombol Previous, Stop, Pause/Resume, Skip, dan Repeat pada embed player.",
            inline=False,
        )
        embed.add_field(name="Antrean", value="`!shuffle` — Acak antrean", inline=False)
        embed.set_footer(text="High Quality • Sumber audio harus mengizinkan streaming bot")
        await ctx.send(embed=embed)

    @commands.Cog.listener()
    async def on_ready(self):
        print("Fumi Music extension aktif (High Quality).")


async def setup(bot: commands.Bot):
    # Use Fumi Music help instead of discord.py's generic help command.
    bot.remove_command("help")
    await bot.add_cog(Music(bot))
