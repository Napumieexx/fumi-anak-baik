from __future__ import annotations

import asyncio
import importlib.metadata
import math
import struct
import os
import random
import re
import shutil
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from urllib.parse import urlparse, unquote

import aiohttp
import discord
from discord.ext import commands


# Fumi Music - High Quality player
# Search playback uses Jamendo API stream URLs; direct authorized audio URLs are also supported.
# Spotify/YouTube page URLs are not extracted or ripped.

PLAYER_COLOR = discord.Color.from_rgb(35, 190, 120)
ERROR_COLOR = discord.Color.orange()


class CountingPCMVolumeTransformer(discord.PCMVolumeTransformer):
    """Count PCM frames and measure signal energy without storing audio."""
    def __init__(self, original, volume: float = 1.0):
        super().__init__(original, volume=volume)
        self.frames_read = 0
        self.bytes_read = 0
        self.samples_read = 0
        self.sum_squares = 0
        self.peak_abs = 0
        self.silent_frames = 0

    def read(self) -> bytes:
        data = super().read()
        if data:
            self.frames_read += 1
            self.bytes_read += len(data)
            usable = len(data) - (len(data) % 2)
            if usable:
                samples = struct.unpack("<" + "h" * (usable // 2), data[:usable])
                peak = max(abs(sample) for sample in samples)
                self.peak_abs = max(self.peak_abs, peak)
                self.sum_squares += sum(sample * sample for sample in samples)
                self.samples_read += len(samples)
                if peak < 100:
                    self.silent_frames += 1
        return data

    @property
    def rms(self) -> float:
        if not self.samples_read:
            return 0.0
        return math.sqrt(self.sum_squares / self.samples_read)


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
    license_url: str | None = None
    source: str = "Direct audio"


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
        self.jamendo_client_id = os.getenv("JAMENDO_CLIENT_ID")
        self.last_playback_error: dict[int, str] = {}
        self.audio_stats: dict[int, CountingPCMVolumeTransformer] = {}
        self.voice_send_stats: dict[int, dict[str, int | str]] = {}

    async def cog_load(self):
        # Log the actual runtime packages so hosting logs can confirm the
        # installed voice/DAVE dependencies after a restart.
        try:
            discord_version = importlib.metadata.version("discord.py")
        except importlib.metadata.PackageNotFoundError:
            discord_version = getattr(discord, "__version__", "unknown")
        try:
            davey_version = importlib.metadata.version("davey")
            davey_status = f"installed ({davey_version})"
        except importlib.metadata.PackageNotFoundError:
            davey_status = "NOT INSTALLED"
        try:
            opus_status = "loaded" if discord.opus.is_loaded() else "not loaded"
        except Exception:
            opus_status = "check failed"

        print(f"Fumi voice diagnostics: discord.py={discord_version}; davey={davey_status}; opus={opus_status}")
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
                description="Belum ada lagu yang diputar. Gunakan `!p <judul lagu>` atau URL audio langsung.",
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
        embed.add_field(name="Audio", value=f"{track.source} · Opus voice", inline=True)
        if track.license_url:
            embed.add_field(name="License", value=f"[Info lisensi]({track.license_url})", inline=True)
        embed.add_field(name="Repeat", value="Aktif" if player.repeat else "Nonaktif", inline=True)
        embed.set_footer(text="Fumi Music • Multi-source audio • !shuffle untuk mengacak antrean")
        return embed

    async def search_jamendo(self, query: str, track_id: str | None = None) -> Track | None:
        """Cari track di katalog Jamendo dan ambil URL stream resmi."""
        if not self.jamendo_client_id:
            raise RuntimeError(
                "JAMENDO_CLIENT_ID belum diatur. Masukkan Client ID Jamendo ke environment/.env."
            )

        timeout = aiohttp.ClientTimeout(total=20)
        # mp32 adalah MP3 VBR berkualitas lebih baik. Format lain menjadi fallback
        # jika suatu track tidak menyediakan URL audio pada format tersebut.
        audio_formats = ("mp32", "mp31", "ogg", "flac")
        last_error = None

        async with aiohttp.ClientSession(timeout=timeout) as session:
            for audio_format in audio_formats:
                params = {
                    "client_id": self.jamendo_client_id,
                    "format": "json",
                    "limit": 10,
                    "audioformat": audio_format,
                    "imagesize": 500,
                    "include": "licenses",
                    # API secara default hanya mengembalikan track album.
                    # Sertakan single juga agar hasil pencarian lebih lengkap.
                    "type": "single albumtrack",
                }
                if track_id:
                    params["id"] = track_id
                else:
                    params["search"] = query

                try:
                    async with session.get(
                        "https://api.jamendo.com/v3.0/tracks/",
                        params=params,
                    ) as response:
                        if response.status != 200:
                            body = (await response.text())[:300]
                            last_error = RuntimeError(
                                f"Jamendo API HTTP {response.status}: {body}"
                            )
                            continue
                        data = await response.json(content_type=None)
                except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as error:
                    last_error = error
                    continue

                headers = data.get("headers", {})
                if headers.get("status") != "success":
                    last_error = RuntimeError(
                        headers.get("error_message") or "Pencarian Jamendo gagal."
                    )
                    continue

                results = data.get("results") or []
                item = next(
                    (
                        row for row in results
                        if isinstance(row, dict)
                        and isinstance(row.get("audio"), str)
                        and row["audio"].startswith(("http://", "https://"))
                    ),
                    None,
                )
                if not item:
                    continue

                duration = int(item.get("duration") or 0)
                license_url = item.get("license_ccurl")
                if not license_url:
                    licenses = item.get("licenses") or []
                    if licenses and isinstance(licenses[0], dict):
                        license_url = licenses[0].get("url")

                return Track(
                    url=item["audio"],
                    title=item.get("name") or query,
                    artist=item.get("artist_name"),
                    requester_id=0,
                    webpage_url=item.get("shareurl") or item.get("shorturl"),
                    duration=self._format_time(duration) if duration else "Durasi tidak diketahui",
                    duration_seconds=duration or None,
                    thumbnail=item.get("image") or item.get("album_image"),
                    license_url=license_url,
                    source="Jamendo",
                )

        if last_error:
            raise RuntimeError(f"Gagal menghubungi katalog Jamendo: {last_error}") from last_error
        return None

    async def search_internet_archive(self, query: str) -> Track | None:
        """Cari audio Internet Archive hanya jika item mencantumkan lisensi yang jelas."""
        timeout = aiohttp.ClientTimeout(total=18)
        safe_query = query.replace('"', ' ').strip()
        if not safe_query:
            return None

        search_url = "https://archive.org/advancedsearch.php"
        params = {
            "q": f'mediatype:audio AND (title:"{safe_query}" OR creator:"{safe_query}")',
            "fl[]": ["identifier", "title", "creator", "licenseurl"],
            "rows": 8,
            "page": 1,
            "output": "json",
        }

        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(search_url, params=params) as response:
                if response.status != 200:
                    raise RuntimeError(f"Internet Archive search HTTP {response.status}")
                data = await response.json(content_type=None)

            docs = data.get("response", {}).get("docs", [])
            for doc in docs:
                identifier = doc.get("identifier")
                license_url = doc.get("licenseurl") or ""
                # Jangan putar item tanpa lisensi yang dapat diverifikasi.
                if not identifier or not (
                    "creativecommons.org/licenses/" in license_url
                    or "creativecommons.org/publicdomain/" in license_url
                ):
                    continue

                metadata_url = f"https://archive.org/metadata/{identifier}"
                async with session.get(metadata_url) as response:
                    if response.status != 200:
                        continue
                    metadata = await response.json(content_type=None)

                files = metadata.get("files", [])
                candidates = []
                for file_info in files:
                    name = file_info.get("name", "")
                    fmt = (file_info.get("format") or "").lower()
                    lower_name = name.lower()
                    if lower_name.endswith(".mp3") and "original" not in lower_name and "_spectrogram" not in lower_name:
                        size = int(file_info.get("size") or 0)
                        candidates.append((size, name))
                    elif fmt in {"mp3", "vbr mp3"} and lower_name.endswith(".mp3"):
                        size = int(file_info.get("size") or 0)
                        candidates.append((size, name))

                if not candidates:
                    continue
                # Pilih file MP3 terbesar agar tidak mengambil thumbnail/preview kecil.
                _, filename = max(candidates, key=lambda item: item[0])
                from urllib.parse import quote
                audio_url = f"https://archive.org/download/{identifier}/{quote(filename, safe='/')}"
                creator = doc.get("creator")
                if isinstance(creator, list):
                    creator = ", ".join(str(x) for x in creator[:2])
                duration = None
                return Track(
                    url=audio_url,
                    title=doc.get("title") or query,
                    artist=creator if isinstance(creator, str) else None,
                    requester_id=0,
                    webpage_url=f"https://archive.org/details/{identifier}",
                    duration="Durasi tidak diketahui",
                    duration_seconds=duration,
                    license_url=license_url,
                    source="Internet Archive",
                )
        return None

    async def search_multi_source(self, query: str) -> Track | None:
        """Mode tes: pencarian judul hanya memakai Internet Archive.

        Jamendo tetap bisa dipakai jika pengguna memberikan URL track Jamendo,
        tetapi tidak dipanggil untuk pencarian teks atau pencarian metadata Spotify.
        """
        try:
            return await self.search_internet_archive(query)
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, RuntimeError) as error:
            print(f"Fumi Internet Archive search error: {error}")
            raise RuntimeError(f"Internet Archive: {error}") from error

    async def spotify_oembed_title(self, url: str) -> str | None:
        """Ambil judul publik dari oEmbed Spotify; tidak mengambil audio Spotify."""
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(
                "https://open.spotify.com/oembed", params={"url": url}
            ) as response:
                if response.status != 200:
                    return None
                data = await response.json(content_type=None)
                title = data.get("title")
                return title.strip() if isinstance(title, str) and title.strip() else None

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

    def instrument_voice_sender(self, guild_id: int, voice: discord.VoiceClient) -> None:
        """Count send_audio_packet calls without exposing stream URLs or secrets."""
        if getattr(voice, "_fumi_sender_instrumented", False):
            return
        original_send = voice.send_audio_packet
        stats: dict[str, int | str] = {"attempts": 0, "returned": 0, "errors": 0, "last_error": ""}
        self.voice_send_stats[guild_id] = stats

        def counted_send(data: bytes, *, encode: bool = True) -> None:
            stats["attempts"] = int(stats["attempts"]) + 1
            try:
                original_send(data, encode=encode)
                stats["returned"] = int(stats["returned"]) + 1
            except Exception as error:
                stats["errors"] = int(stats["errors"]) + 1
                stats["last_error"] = str(error)[:250]
                raise

        voice.send_audio_packet = counted_send  # type: ignore[method-assign]
        voice._fumi_sender_instrumented = True  # type: ignore[attr-defined]

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
            self.instrument_voice_sender(ctx.guild.id, voice)
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
            options = "-vn"
            try:
                source = CountingPCMVolumeTransformer(
                    discord.FFmpegPCMAudio(track.url, before_options=before_options, options=options),
                    volume=player.volume,
                )
                self.audio_stats[guild_id] = source
                def after_play(error: Exception | None):
                    if error:
                        self.last_playback_error[guild_id] = str(error)[:500]
                        print(f"Fumi Music playback error: {error}")
                    else:
                        self.last_playback_error.pop(guild_id, None)
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
        if ctx.guild is None:
            await ctx.send("Command musik hanya bisa digunakan di server.")
            return

        lowered = query.lower().strip()
        is_youtube = "youtube.com/" in lowered or "youtu.be/" in lowered
        is_spotify = "open.spotify.com/" in lowered
        if is_youtube:
            await ctx.send(
                "Link YouTube dikenali, tetapi Fumi tidak mengambil audio dari halaman tersebut. "
                "Kirim judul lagu atau URL audio yang memang mengizinkan streaming bot."
            )
            return

        if is_spotify:
            status = await ctx.send("🔎 Membaca metadata Spotify, lalu mencari versi audio berlisensi...")
            try:
                spotify_title = await self.spotify_oembed_title(query)
                if not spotify_title:
                    await status.edit(content=(
                        "❌ Metadata Spotify tidak dapat dibaca. Kirim judul lagu dan artisnya "
                        "agar Fumi bisa mencari di katalog audio yang tersedia."
                    ))
                    return
                track = await self.search_multi_source(spotify_title)
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, RuntimeError) as error:
                await status.edit(content=f"❌ Pencarian sumber audio gagal: `{error}`")
                return
            if track is None:
                await status.edit(content=(
                    f"Lagu **{discord.utils.escape_markdown(spotify_title)}** tidak ditemukan "
                    "di sumber audio berlisensi yang tersedia. Spotify hanya dipakai untuk metadata, bukan audio."
                ))
                return
            track.requester_id = ctx.author.id
            try:
                await status.delete()
            except discord.HTTPException:
                pass

        # Link halaman track Jamendo dapat di-resolve melalui API resmi Jamendo.
        jamendo_match = re.search(r"jamendo\.com/(?:[a-z]{2}/)?track/(\d+)", lowered)
        if is_spotify:
            pass  # Track sudah ditemukan melalui metadata Spotify + katalog audio berlisensi.
        elif jamendo_match:
            status = await ctx.send("🔎 Membuka track Jamendo...")
            try:
                track = await self.search_jamendo(query, track_id=jamendo_match.group(1))
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, RuntimeError) as error:
                await status.edit(content=f"❌ Gagal membuka track Jamendo: `{error}`")
                return
            if track is None:
                await status.edit(content="Track Jamendo tidak ditemukan atau stream tidak tersedia.")
                return
            track.requester_id = ctx.author.id
            try:
                await status.delete()
            except discord.HTTPException:
                pass
        elif self._is_direct_url(query):
            track = Track(
                url=query, title=self._safe_title(query), requester_id=ctx.author.id, webpage_url=query
            )
            await self.lookup_track_metadata(track)
        else:
            status = await ctx.send(f"🔎 Menguji Internet Archive saja untuk **{discord.utils.escape_markdown(query)}**...")
            try:
                track = await self.search_multi_source(query)
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, RuntimeError) as error:
                await status.edit(content=f"❌ Pencarian musik gagal: `{error}`")
                return
            if track is None:
                await status.edit(
                    content="Tidak menemukan audio berlisensi yang cocok di katalog Fumi. Coba judul + nama artis lain."
                )
                return
            track.requester_id = ctx.author.id
            try:
                await status.delete()
            except discord.HTTPException:
                pass

        voice = await self.connect_for_context(ctx)
        if voice is None:
            return

        player = self.get_player(ctx.guild.id)
        player.text_channel_id = ctx.channel.id
        if voice.is_playing() or voice.is_paused() or player.current is not None:
            player.queue.append(track)
            await ctx.send(f"➕ **Ditambahkan ke antrean:** {discord.utils.escape_markdown(track.title)}")
            await self.refresh_player(ctx.guild.id)
        else:
            player.queue.append(track)
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

    @commands.command(name="musicdebug", aliases=["mdebug"])
    async def music_debug_command(self, ctx: commands.Context):
        """Diagnostik musik yang hasilnya dikirim ke channel tempat command dipakai."""
        if ctx.guild is None:
            await ctx.send("Diagnostik musik hanya bisa digunakan di server.")
            return

        player = self.get_player(ctx.guild.id)
        voice = ctx.guild.voice_client
        ffmpeg_path = shutil.which("ffmpeg")
        ffprobe_path = shutil.which("ffprobe")

        embed = discord.Embed(title="🩺 FUMI MUSIC DIAGNOSTICS", color=PLAYER_COLOR)
        embed.add_field(name="FFmpeg", value=(f"✅ Terdeteksi: `{ffmpeg_path}`" if ffmpeg_path else "❌ Tidak ditemukan di PATH"), inline=False)
        embed.add_field(name="FFprobe", value=(f"✅ Terdeteksi: `{ffprobe_path}`" if ffprobe_path else "⚠️ Tidak ditemukan (opsional)"), inline=False)

        if voice is None:
            voice_status = "❌ Fumi tidak terhubung ke voice channel."
        else:
            channel_name = getattr(voice.channel, "name", "Unknown")
            voice_status = f"✅ Terhubung ke **{channel_name}**"
            voice_status += f"\nPlaying: **{voice.is_playing()}** | Paused: **{voice.is_paused()}**"
        embed.add_field(name="Voice connection", value=voice_status, inline=False)

        try:
            opus_loaded = discord.opus.is_loaded()
        except Exception:
            opus_loaded = False
        embed.add_field(
            name="Opus encoder",
            value="✅ Library Opus terdeteksi" if opus_loaded else "❌ Library Opus belum termuat",
            inline=False,
        )
        # discord.py 2.7.1+ includes DAVE voice support; report runtime versions
        # because an older already-installed package may remain on the host.
        try:
            discord_version = importlib.metadata.version("discord.py")
        except importlib.metadata.PackageNotFoundError:
            discord_version = getattr(discord, "__version__", "Tidak diketahui")
        try:
            davey_version = importlib.metadata.version("davey")
            davey_status = f"✅ davey {davey_version}"
        except importlib.metadata.PackageNotFoundError:
            davey_status = "❌ Paket davey tidak terpasang"
        try:
            has_dave = getattr(discord.voice_client, "has_dave", None)
            dave_support = "Tersedia" if has_dave is True else ("Tidak tersedia" if has_dave is False else "Tidak dapat dipastikan")
        except Exception:
            dave_support = "Tidak dapat diperiksa"
        embed.add_field(name="discord.py version", value=f"`{discord_version}`", inline=True)
        embed.add_field(name="DAVE support", value=f"{davey_status}\nRuntime: **{dave_support}**", inline=True)
        if voice is not None:
            try:
                latency_text = f"{voice.latency * 1000:.0f} ms"
            except Exception:
                latency_text = "Tidak tersedia"
            embed.add_field(name="Voice latency", value=latency_text, inline=True)

        send_stats = self.voice_send_stats.get(ctx.guild.id)
        if send_stats is not None:
            send_text = (
                f"Attempts: **{send_stats['attempts']:,}**\n"
                f"Returned: **{send_stats['returned']:,}**\n"
                f"Errors: **{send_stats['errors']:,}**"
            )
            if send_stats.get("last_error"):
                send_text += f"\nLast error: `{str(send_stats['last_error'])[:180]}`"
        else:
            send_text = "Belum terpasang; jalankan `!p` setelah update lalu cek lagi."
        embed.add_field(name="Discord audio send", value=send_text, inline=False)

        stats = self.audio_stats.get(ctx.guild.id)
        if stats is not None:
            silent_pct = (stats.silent_frames / stats.frames_read * 100) if stats.frames_read else 0.0
            rms_pct = stats.rms / 32767 * 100
            peak_pct = stats.peak_abs / 32767 * 100
            embed.add_field(
                name="PCM frames terbaca",
                value=(
                    f"{stats.frames_read:,} frame · {stats.bytes_read:,} byte\n"
                    f"RMS: **{stats.rms:.1f}** ({rms_pct:.2f}%)\n"
                    f"Peak: **{stats.peak_abs}** ({peak_pct:.2f}%)\n"
                    f"Frame hampir senyap: **{silent_pct:.1f}%**"
                ),
                inline=False,
            )
        else:
            embed.add_field(name="PCM frames terbaca", value="Belum ada data source aktif.", inline=True)

        track = player.current
        if track:
            parsed = urlparse(track.url)
            host = parsed.netloc or "Tidak diketahui"
            track_status = f"**{discord.utils.escape_markdown(track.title)[:100]}**\nHost stream: `{host}`\nSumber: `{getattr(track, 'source', 'Tidak diketahui')}`"
        else:
            track_status = "Tidak ada track aktif."
        embed.add_field(name="Track aktif", value=track_status, inline=False)
        embed.add_field(name="Queue", value=f"{len(player.queue)} lagu", inline=True)
        embed.add_field(name="Volume", value=f"{int(player.volume * 100)}%", inline=True)
        embed.add_field(name="Jamendo Client ID", value="✅ Tersedia" if self.jamendo_client_id else "❌ Belum diatur", inline=True)

        last_error = self.last_playback_error.get(ctx.guild.id)
        embed.add_field(name="Playback error terakhir", value=f"```{last_error[:900]}```" if last_error else "Tidak ada error playback yang tercatat sejak bot aktif.", inline=False)

        # Uji decode stream aktif secara terpisah dari Discord Voice.
        # Hanya ringkasan hasil yang dikirim; URL stream tidak pernah ditampilkan.
        if track and ffmpeg_path:
            test_msg = await ctx.send("🔬 Menguji apakah FFmpeg benar-benar bisa membaca dan mendekode stream aktif (maks. 8 detik)...")
            try:
                proc = await asyncio.create_subprocess_exec(
                    ffmpeg_path, "-nostdin", "-hide_banner", "-v", "error",
                    "-i", track.url, "-t", "5", "-f", "null", "-",
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.PIPE,
                )
                _, stderr = await asyncio.wait_for(proc.communicate(), timeout=8)
                detail = (stderr or b"").decode("utf-8", errors="replace").strip()
                if proc.returncode == 0:
                    result = "✅ FFmpeg berhasil mendekode stream selama tes. Sumber audio terbaca."
                else:
                    result = f"❌ FFmpeg gagal mendekode stream (exit {proc.returncode})."
                if detail:
                    result += "\n```\n" + detail[:900] + "\n```"
                await test_msg.edit(content=result)
            except asyncio.TimeoutError:
                try:
                    proc.kill()
                    await proc.wait()
                except Exception:
                    pass
                await test_msg.edit(content="⚠️ Tes stream melewati batas 8 detik. Stream lambat, macet, atau tidak merespons.")
            except Exception as error:
                await test_msg.edit(content=f"❌ Tes stream gagal dijalankan: `{str(error)[:300]}`")
        elif not track:
            embed.add_field(name="Tes stream", value="Putar lagu terlebih dahulu, lalu jalankan `!musicdebug` lagi.", inline=False)

        embed.set_footer(text="Diagnostik tidak menampilkan URL stream atau rahasia konfigurasi.")
        await ctx.send(embed=embed)

    @commands.command(name="help", aliases=["musichelp", "mhelp"])
    async def music_help_command(self, ctx: commands.Context):
        embed = discord.Embed(title="🎵 FUMI MUSIC — HELP", color=PLAYER_COLOR)
        embed.add_field(
            name="Pemutaran",
            value=("`!p <judul lagu>` — Cari di Internet Archive (mode tes)\n"
                   "`!p <link track Jamendo>` — Putar track Jamendo\n"
                   "`!p <URL audio langsung>` — Putar stream yang diizinkan\n"
                   "`!queue` — Lihat antrean\n`!leave` — Keluar dari voice channel"),
            inline=False,
        )
        embed.add_field(
            name="Kontrol player",
            value="Gunakan tombol Previous, Stop, Pause/Resume, Skip, dan Repeat pada embed player.",
            inline=False,
        )
        embed.add_field(name="Antrean", value="`!shuffle` — Acak antrean", inline=False)
        embed.add_field(
            name="Link yang didukung",
            value="Jamendo track URL dan URL audio langsung. Spotify digunakan untuk metadata lalu dicari di katalog berlisensi; audio Spotify/YouTube tidak diambil langsung.",
            inline=False,
        )
        embed.set_footer(text="High Quality • Jamendo + URL audio langsung yang diizinkan")
        await ctx.send(embed=embed)

    @commands.Cog.listener()
    async def on_ready(self):
        print("Fumi Music extension aktif (High Quality) — text search: Internet Archive only.")


async def setup(bot: commands.Bot):
    # Use Fumi Music help instead of discord.py's generic help command.
    bot.remove_command("help")
    await bot.add_cog(Music(bot))
