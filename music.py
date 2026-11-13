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
# Metadata discovery: iTunes, MusicBrainz, Deezer. Playback discovery: Jamendo, Internet Archive, Audius, optional official SoundCloud API.
# Spotify/YouTube page URLs are not extracted or ripped; metadata is never treated as an audio license.

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
    fallback_tracks: list["Track"] = field(default_factory=list, repr=False)


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

    async def _defer(self, interaction: discord.Interaction):
        # Acknowledge within Discord's interaction deadline before doing async work.
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)

    async def _ack(self, interaction: discord.Interaction, message: str):
        # Use followup after defer; fall back to initial response if not deferred.
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)

    @discord.ui.button(emoji="⏮️", style=discord.ButtonStyle.secondary, row=0)
    async def previous_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._defer(interaction)
        try:
            ok = await self.cog.previous_track(self.guild_id)
            await self._ack(interaction, "Memutar lagu sebelumnya." if ok else "Tidak ada lagu sebelumnya.")
        except Exception:
            await self._ack(interaction, "Gagal memutar lagu sebelumnya. Coba lagi.")
            raise

    @discord.ui.button(emoji="⏹️", style=discord.ButtonStyle.danger, row=0)
    async def stop_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._defer(interaction)
        try:
            await self.cog.stop_track(self.guild_id)
            await self._ack(interaction, "Pemutaran dihentikan. Fumi tetap berada di voice channel.")
        except Exception:
            await self._ack(interaction, "Gagal menghentikan pemutaran. Coba lagi.")
            raise

    @discord.ui.button(emoji="⏯️", style=discord.ButtonStyle.primary, row=0)
    async def pause_resume_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._defer(interaction)
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
        await self._defer(interaction)
        voice = interaction.guild.voice_client
        if voice and (voice.is_playing() or voice.is_paused()):
            voice.stop()
            await self._ack(interaction, "Lagu dilewati.")
        else:
            await self._ack(interaction, "Tidak ada lagu yang sedang diputar.")

    @discord.ui.button(emoji="🔁", style=discord.ButtonStyle.success, row=0)
    async def repeat_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._defer(interaction)
        player = self.cog.players[self.guild_id]
        player.repeat = not player.repeat
        button.style = discord.ButtonStyle.success if player.repeat else discord.ButtonStyle.secondary
        await interaction.message.edit(embed=self.cog.make_embed(self.guild_id), view=self)
        await self._ack(interaction, "Repeat diaktifkan." if player.repeat else "Repeat dinonaktifkan.")


class Music(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.players: dict[int, GuildPlayer] = defaultdict(GuildPlayer)
        self.progress_task: asyncio.Task | None = None
        self.jamendo_client_id = os.getenv("JAMENDO_CLIENT_ID")
        self.audius_api_key = os.getenv("AUDIUS_API_KEY")
        self.spotify_client_id = os.getenv("SPOTIFY_CLIENT_ID")
        self.spotify_client_secret = os.getenv("SPOTIFY_CLIENT_SECRET")
        self._spotify_token: str | None = None
        self._spotify_token_expires_at: float = 0.0
        self.soundcloud_client_id = os.getenv("SOUNDCLOUD_CLIENT_ID")
        self.soundcloud_client_secret = os.getenv("SOUNDCLOUD_CLIENT_SECRET")
        self._soundcloud_token: str | None = None
        self._soundcloud_token_expires_at: float = 0.0
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

    @staticmethod
    def _normalize_text(value: str | None) -> str:
        import unicodedata

        value = unicodedata.normalize("NFKD", value or "")
        value = "".join(ch for ch in value if not unicodedata.combining(ch))
        value = value.casefold()
        value = re.sub(r"[^\w\s]", " ", value, flags=re.UNICODE)
        return re.sub(r"\s+", " ", value).strip()

    @staticmethod
    def _parse_explicit_query(query: str) -> tuple[str, str | None]:
        """Recognize common 'title - artist' and 'title by artist' forms."""
        text = query.strip()
        patterns = (r"\s+[–—-]\s+", r"\s+by\s+", r"\s+\|\s+")
        for pattern in patterns:
            parts = re.split(pattern, text, maxsplit=1, flags=re.IGNORECASE)
            if len(parts) == 2 and parts[0].strip() and parts[1].strip():
                return parts[0].strip(), parts[1].strip()
        return text, None

    @staticmethod
    def _search_variants(query: str) -> list[str]:
        """Generate safe query variants while preserving title and artist words."""
        q = re.sub(r"\s+", " ", query).strip()
        variants: list[str] = []
        if not q:
            return variants

        variants.append(q)
        title, artist = Music._parse_explicit_query(q)
        if artist:
            variants.extend((f"{title} {artist}", title))
        plain = re.sub(r"[^\w\s]", " ", q, flags=re.UNICODE)
        plain = re.sub(r"\s+", " ", plain).strip()
        if plain and plain.casefold() != q.casefold():
            variants.append(plain)

        seen: set[str] = set()
        result: list[str] = []
        for item in variants:
            key = item.casefold()
            if key and key not in seen:
                seen.add(key)
                result.append(item)
        return result[:4]

    @staticmethod
    def _token_similarity(left: str, right: str) -> float:
        """Similarity from 0..1, using RapidFuzz when installed."""
        if not left or not right:
            return 0.0
        try:
            from rapidfuzz import fuzz
            return max(
                fuzz.ratio(left, right),
                fuzz.partial_ratio(left, right) * 0.92,
                fuzz.token_sort_ratio(left, right),
            ) / 100.0
        except Exception:
            from difflib import SequenceMatcher
            return SequenceMatcher(None, left, right).ratio()

    @classmethod
    def _match_score(cls, query: str, title: str | None, artist: str | None = None) -> float:
        """
        Rank candidate title/artist against a user's query.
        Handles typos and spacing (e.g. 'yungkai' vs 'yung kai') while
        rejecting candidates that only share a generic title word.
        """
        q = cls._normalize_text(query)
        t = cls._normalize_text(title)
        a = cls._normalize_text(artist)
        if not q or not t:
            return 0.0

        wanted_title, wanted_artist = cls._parse_explicit_query(query)
        if wanted_artist:
            wt = cls._normalize_text(wanted_title)
            wa = cls._normalize_text(wanted_artist)
            title_score = cls._token_similarity(wt, t)
            artist_score = cls._token_similarity(wa.replace(" ", ""), a.replace(" ", ""))
            if title_score < 0.55 or artist_score < 0.52:
                return 0.0
            return 0.68 * title_score + 0.32 * artist_score

        q_tokens = q.split()
        title_tokens = t.split()
        artist_tokens = a.split()
        if not q_tokens:
            return 0.0

        def best_token_match(token: str, candidates: list[str], compact_candidate: str) -> float:
            scores = [cls._token_similarity(token, candidate) for candidate in candidates]
            if len(token) >= 5 and token in compact_candidate:
                scores.append(0.96)
            return max(scores, default=0.0)

        title_matches = [
            best_token_match(token, title_tokens, t.replace(" ", ""))
            for token in q_tokens
        ]
        artist_matches = [
            best_token_match(token, artist_tokens, a.replace(" ", ""))
            for token in q_tokens
        ]
        combined_matches = [max(x, y) for x, y in zip(title_matches, artist_matches)]

        # Fuzzy token coverage makes typo-tolerant matching possible.
        coverage = sum(1 for score in combined_matches if score >= 0.76) / len(q_tokens)
        title_coverage = sum(1 for score in title_matches if score >= 0.76) / len(q_tokens)
        artist_coverage = sum(1 for score in artist_matches if score >= 0.76) / len(q_tokens)

        # A multiword query must be represented by title and/or artist,
        # not merely by a single shared word such as "wildflower".
        if len(q_tokens) >= 2 and coverage < 0.67:
            return 0.0
        if title_coverage == 0 and artist_coverage < 0.67:
            return 0.0

        whole_title_score = cls._token_similarity(q, t)
        score = (
            0.52 * coverage
            + 0.25 * title_coverage
            + 0.15 * artist_coverage
            + 0.08 * whole_title_score
        )
        return min(1.0, score)

    @staticmethod
    def _is_explicit_cc_license(license_url: str | None) -> bool:
        """Only accept a clearly identified Creative Commons/public-domain license URL."""
        if not isinstance(license_url, str):
            return False
        value = license_url.casefold()
        return (
            "creativecommons.org/licenses/" in value
            or "creativecommons.org/publicdomain/" in value
        )

    async def _metadata_search_itunes(self, query: str) -> list[dict[str, str]]:
        """iTunes is metadata/cover discovery only; it does not provide playback permission."""
        timeout = aiohttp.ClientTimeout(total=8)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(
                    "https://itunes.apple.com/search",
                    params={"term": query, "entity": "song", "limit": 8},
                ) as response:
                    if response.status != 200:
                        return []
                    data = await response.json(content_type=None)
            output = []
            for item in data.get("results") or []:
                title, artist = item.get("trackName"), item.get("artistName")
                if title:
                    output.append({
                        "title": str(title),
                        "artist": str(artist or ""),
                        "source": "iTunes",
                    })
            return output
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as error:
            print(f"Fumi iTunes metadata warning: {error}")
            return []

    async def _metadata_search_deezer(self, query: str) -> list[dict[str, str]]:
        """Deezer search is used for metadata only, never as an audio stream."""
        timeout = aiohttp.ClientTimeout(total=8)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(
                    "https://api.deezer.com/search/track",
                    params={"q": query, "limit": 8},
                ) as response:
                    if response.status != 200:
                        return []
                    data = await response.json(content_type=None)
            output = []
            for item in data.get("data") or []:
                title = item.get("title")
                artist = (item.get("artist") or {}).get("name")
                if title:
                    output.append({
                        "title": str(title),
                        "artist": str(artist or ""),
                        "source": "Deezer",
                    })
            return output
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as error:
            print(f"Fumi Deezer metadata warning: {error}")
            return []

    async def _metadata_search_musicbrainz(self, query: str) -> list[dict[str, str]]:
        """MusicBrainz recording lookup; metadata only, with an identifying User-Agent."""
        timeout = aiohttp.ClientTimeout(total=10)
        headers = {"User-Agent": "FumiDiscordMusicBot/1.0 (metadata search)"}
        try:
            async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
                async with session.get(
                    "https://musicbrainz.org/ws/2/recording/",
                    params={"query": query, "fmt": "json", "limit": 8},
                ) as response:
                    if response.status != 200:
                        return []
                    data = await response.json(content_type=None)
            output = []
            for item in data.get("recordings") or []:
                title = item.get("title")
                artist_parts = []
                for credit in item.get("artist-credit") or []:
                    if isinstance(credit, dict):
                        artist = credit.get("name") or (credit.get("artist") or {}).get("name")
                        if artist:
                            artist_parts.append(str(artist))
                if title:
                    output.append({
                        "title": str(title),
                        "artist": " ".join(artist_parts),
                        "source": "MusicBrainz",
                    })
            return output
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as error:
            print(f"Fumi MusicBrainz metadata warning: {error}")
            return []

    async def discover_metadata_queries(self, query: str) -> list[str]:
        """
        Expand a user query using independent metadata catalogs.
        Returned strings are still searched against licensed playback providers only.
        """
        tasks = (
            self._metadata_search_itunes(query),
            self._metadata_search_deezer(query),
            self._metadata_search_musicbrainz(query),
        )
        results = await asyncio.gather(*tasks, return_exceptions=True)
        candidates: list[tuple[float, str]] = []
        for result in results:
            if isinstance(result, Exception):
                print(f"Fumi metadata discovery warning: {type(result).__name__}: {result}")
                continue
            for item in result:
                score = self._match_score(query, item.get("title"), item.get("artist"))
                if score >= 0.55:
                    candidate_query = " ".join(
                        part for part in (item.get("title"), item.get("artist")) if part
                    ).strip()
                    if candidate_query:
                        candidates.append((score, candidate_query))

        candidates.sort(key=lambda pair: pair[0], reverse=True)
        output: list[str] = []
        seen = {self._normalize_text(query)}
        for _, candidate in candidates:
            key = self._normalize_text(candidate)
            if key and key not in seen:
                seen.add(key)
                output.append(candidate)
            if len(output) >= 2:
                break
        return output

    async def search_jamendo(self, query: str, track_id: str | None = None) -> Track | None:
        """Cari beberapa variasi judul/artis di katalog Jamendo dan ambil stream resmi."""
        if not self.jamendo_client_id:
            return None

        timeout = aiohttp.ClientTimeout(total=22)
        audio_formats = ("mp32", "mp31")
        variants = [query] if track_id else self._search_variants(query)
        candidates: dict[str, tuple[float, dict]] = {}
        last_error = None

        async with aiohttp.ClientSession(timeout=timeout) as session:
            for variant in variants:
                for audio_format in audio_formats:
                    params = {
                        "client_id": self.jamendo_client_id,
                        "format": "json",
                        "limit": 30,
                        "audioformat": audio_format,
                        "imagesize": 500,
                        "include": "licenses",
                        "type": "single albumtrack",
                        "order": "relevance",
                    }
                    if track_id:
                        params["id"] = track_id
                    else:
                        params["search"] = variant

                    try:
                        async with session.get("https://api.jamendo.com/v3.0/tracks/", params=params) as response:
                            if response.status != 200:
                                last_error = RuntimeError(f"Jamendo HTTP {response.status}")
                                continue
                            data = await response.json(content_type=None)
                    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as error:
                        last_error = error
                        continue

                    headers = data.get("headers", {})
                    if headers.get("status") != "success":
                        last_error = RuntimeError(headers.get("error_message") or "Jamendo API error")
                        continue

                    for row in data.get("results") or []:
                        if not isinstance(row, dict):
                            continue
                        audio = row.get("audio")
                        if not isinstance(audio, str) or not audio.startswith(("http://", "https://")):
                            continue
                        license_url = row.get("license_ccurl")
                        if not self._is_explicit_cc_license(license_url):
                            continue
                        row_id = str(row.get("id") or audio)
                        score = self._match_score(query, row.get("name"), row.get("artist_name"))
                        old = candidates.get(row_id)
                        if old is None or score > old[0]:
                            candidates[row_id] = (score, row)
                    # Jika sudah ada kecocokan sangat kuat, tidak perlu semua format.
                    if candidates and max(score for score, _ in candidates.values()) >= 0.92:
                        break
                if candidates and max(score for score, _ in candidates.values()) >= 0.92:
                    break

        if not candidates:
            if last_error:
                print(f"Fumi Jamendo search warning: {last_error}")
            return None

        # Jangan mengembalikan hasil acak: pilih kecocokan tertinggi, dengan URL audio resmi.
        best_score, item = max(candidates.values(), key=lambda pair: pair[0])
        if best_score < 0.68:
            return None
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

    async def search_internet_archive(self, query: str) -> Track | None:
        """Cari audio IA dengan beberapa pola metadata; hanya putar item berlisensi jelas."""
        timeout = aiohttp.ClientTimeout(total=22)
        variants = self._search_variants(query)
        if not variants:
            return None

        from urllib.parse import quote
        search_url = "https://archive.org/advancedsearch.php"
        docs_by_id: dict[str, dict] = {}
        async with aiohttp.ClientSession(timeout=timeout) as session:
            for variant in variants:
                safe = variant.replace('"', ' ').strip()
                if not safe:
                    continue
                # Query broadens title/creator matching; license validation remains mandatory below.
                params = {
                    "q": f'mediatype:audio AND (title:"{safe}" OR creator:"{safe}" OR title:({safe}))',
                    "fl[]": ["identifier", "title", "creator", "licenseurl", "description", "subject"],
                    "rows": 30,
                    "page": 1,
                    "output": "json",
                }
                try:
                    async with session.get(search_url, params=params) as response:
                        if response.status != 200:
                            continue
                        data = await response.json(content_type=None)
                except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
                    continue
                for doc in data.get("response", {}).get("docs", []):
                    identifier = doc.get("identifier")
                    if identifier:
                        docs_by_id[identifier] = doc

            ranked_docs = sorted(
                docs_by_id.values(),
                key=lambda d: self._match_score(query, d.get("title"), d.get("creator") if isinstance(d.get("creator"), str) else " ".join(d.get("creator") or [])),
                reverse=True,
            )

            for doc in ranked_docs[:40]:
                creator_value = doc.get("creator")
                creator_text = creator_value if isinstance(creator_value, str) else " ".join(creator_value or [])
                if self._match_score(query, doc.get("title"), creator_text) < 0.68:
                    continue
                identifier = doc.get("identifier")
                license_url = doc.get("licenseurl") or ""
                if not identifier or not (
                    "creativecommons.org/licenses/" in license_url
                    or "creativecommons.org/publicdomain/" in license_url
                ):
                    continue
                try:
                    async with session.get(f"https://archive.org/metadata/{identifier}") as response:
                        if response.status != 200:
                            continue
                        metadata = await response.json(content_type=None)
                except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
                    continue

                candidates = []
                for file_info in metadata.get("files", []):
                    name = file_info.get("name", "")
                    fmt = (file_info.get("format") or "").lower()
                    lower = name.lower()
                    if lower.endswith((".mp3", ".ogg", ".flac", ".wav", ".m4a")) and not any(
                        marker in lower for marker in ("spectrogram", "thumbnail", "sample", "_small", "preview")
                    ):
                        size = int(file_info.get("size") or 0)
                        candidates.append((size, name))
                    elif fmt in {"mp3", "vbr mp3", "ogg vorbis", "flac", "wave", "m4a"}:
                        if lower.endswith((".mp3", ".ogg", ".flac", ".wav", ".m4a")):
                            candidates.append((int(file_info.get("size") or 0), name))
                if not candidates:
                    continue
                _, filename = max(candidates, key=lambda item: item[0])
                creator = doc.get("creator")
                if isinstance(creator, list):
                    creator = ", ".join(str(x) for x in creator[:2])
                duration = None
                return Track(
                    url=f"https://archive.org/download/{identifier}/{quote(filename, safe='/')}",
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


    async def _validate_stream_url(self, url: str) -> bool:
        """Follow redirects and request only a tiny byte range to reject HTML/error pages."""
        timeout = aiohttp.ClientTimeout(total=12, connect=6, sock_read=6)
        headers = {"Range": "bytes=0-1", "Icy-MetaData": "0"}
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url, headers=headers, allow_redirects=True) as response:
                    if response.status not in (200, 206):
                        return False
                    content_type = (response.headers.get("Content-Type") or "").lower()
                    if any(x in content_type for x in ("text/html", "application/json", "text/plain")):
                        return False
                    await response.content.read(2)
                    return True
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
            return False

    async def search_audius(self, query: str) -> Track | None:
        """Search public streamable Audius tracks using the official read-only API."""
        timeout = aiohttp.ClientTimeout(total=14, connect=7, sock_read=8)
        params = {"query": query, "limit": 20}
        if self.audius_api_key:
            params["api_key"] = self.audius_api_key
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(
                    "https://api.audius.co/v1/tracks/search", params=params
                ) as response:
                    if response.status != 200:
                        return None
                    payload = await response.json(content_type=None)

            ranked = []
            for item in payload.get("data") or []:
                if not isinstance(item, dict):
                    continue
                user = item.get("user") or {}
                title = str(item.get("title") or "")
                artist = str(user.get("name") or user.get("handle") or "")
                streamable = item.get("isStreamable", item.get("is_streamable", True))
                if streamable is False or str(streamable).lower() in {"false", "0", "no"}:
                    continue
                if item.get("isStreamGated") or item.get("is_stream_gated"):
                    continue
                score = self._match_score(query, title, artist)
                if score >= 0.60:
                    ranked.append((score, item))

            ranked.sort(key=lambda pair: pair[0], reverse=True)
            for score, item in ranked[:5]:
                track_id = item.get("id")
                if not track_id:
                    continue
                stream_url = f"https://api.audius.co/v1/tracks/{track_id}/stream"
                if self.audius_api_key:
                    from urllib.parse import urlencode
                    stream_url += "?" + urlencode({"api_key": self.audius_api_key})

                artwork = item.get("artwork") or {}
                duration_seconds = item.get("duration")
                try:
                    duration_seconds = int(float(duration_seconds)) if duration_seconds is not None else None
                except (TypeError, ValueError):
                    duration_seconds = None
                duration_text = (
                    f"{duration_seconds // 60}:{duration_seconds % 60:02d}"
                    if duration_seconds else "Durasi tidak diketahui"
                )
                return Track(
                    url=stream_url,
                    title=str(item.get("title") or query),
                    requester_id=0,
                    webpage_url=item.get("permalink") or "https://audius.co",
                    duration=duration_text,
                    duration_seconds=duration_seconds,
                    thumbnail=artwork.get("_480x480") or artwork.get("_1000x1000") or artwork.get("_150x150"),
                    artist=str((item.get("user") or {}).get("name") or ""),
                    license_url=None,
                    source="Audius",
                )
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, TypeError) as error:
            print(f"Fumi Audius search warning: {type(error).__name__}: {error}")
        return None

    async def _get_soundcloud_token(self) -> str | None:
        """Cache official SoundCloud Client Credentials token for public playback/search."""
        if not self.soundcloud_client_id or not self.soundcloud_client_secret:
            return None
        if self._soundcloud_token and time.time() < self._soundcloud_token_expires_at - 90:
            return self._soundcloud_token
        timeout = aiohttp.ClientTimeout(total=12)
        try:
            auth = aiohttp.BasicAuth(self.soundcloud_client_id, self.soundcloud_client_secret)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(
                    "https://secure.soundcloud.com/oauth/token",
                    data={"grant_type": "client_credentials"},
                    auth=auth,
                    headers={"Accept": "application/json"},
                ) as response:
                    if response.status != 200:
                        print(f"Fumi SoundCloud token error: HTTP {response.status}")
                        return None
                    data = await response.json(content_type=None)
            token = data.get("access_token")
            if not token:
                return None
            self._soundcloud_token = str(token)
            self._soundcloud_token_expires_at = time.time() + int(data.get("expires_in") or 3600)
            return self._soundcloud_token
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as error:
            print(f"Fumi SoundCloud auth warning: {type(error).__name__}: {error}")
            return None

    async def search_soundcloud(self, query: str) -> Track | None:
        """Optional official SoundCloud API provider; inactive without credentials in env."""
        token = await self._get_soundcloud_token()
        if not token:
            return None
        timeout = aiohttp.ClientTimeout(total=16, connect=7, sock_read=9)
        headers = {"Authorization": f"OAuth {token}", "Accept": "application/json"}
        try:
            async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
                async with session.get(
                    "https://api.soundcloud.com/tracks",
                    params={"q": query, "access": "playable", "limit": 20},
                ) as response:
                    if response.status != 200:
                        print(f"Fumi SoundCloud search warning: HTTP {response.status}")
                        return None
                    payload = await response.json(content_type=None)

                rows = payload.get("collection", payload if isinstance(payload, list) else [])
                ranked = []
                for item in rows or []:
                    if not isinstance(item, dict):
                        continue
                    access = str(item.get("access") or "").lower()
                    if access and access != "playable":
                        continue
                    user = item.get("user") or {}
                    artist = str(item.get("metadata_artist") or user.get("username") or user.get("full_name") or "")
                    score = self._match_score(query, item.get("title"), artist)
                    if score >= 0.60:
                        ranked.append((score, item))
                ranked.sort(key=lambda pair: pair[0], reverse=True)

                for score, item in ranked[:5]:
                    urn = item.get("urn")
                    if not urn:
                        continue
                    from urllib.parse import quote
                    encoded_urn = quote(str(urn), safe=":")
                    async with session.get(
                        f"https://api.soundcloud.com/tracks/{encoded_urn}/streams"
                    ) as response:
                        if response.status != 200:
                            continue
                        stream_data = await response.json(content_type=None)
                    stream_url = (
                        stream_data.get("http_mp3_128_url")
                        or stream_data.get("http_aac_160_url")
                        or stream_data.get("preview_mp3_128_url")
                    )
                    if not stream_url:
                        continue
                    duration_ms = item.get("duration")
                    try:
                        duration_seconds = int(int(duration_ms) / 1000) if duration_ms else None
                    except (TypeError, ValueError):
                        duration_seconds = None
                    duration_text = (
                        f"{duration_seconds // 60}:{duration_seconds % 60:02d}"
                        if duration_seconds else "Durasi tidak diketahui"
                    )
                    return Track(
                        url=str(stream_url),
                        title=str(item.get("title") or query),
                        requester_id=0,
                        webpage_url=item.get("permalink_url"),
                        duration=duration_text,
                        duration_seconds=duration_seconds,
                        thumbnail=item.get("artwork_url"),
                        artist=str((item.get("user") or {}).get("username") or ""),
                        license_url=None,
                        source="SoundCloud",
                    )
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, TypeError) as error:
            print(f"Fumi SoundCloud search warning: {type(error).__name__}: {error}")
        return None

    async def search_multi_source(self, query: str) -> Track | None:
        """
        Maximum Search:
        metadata expansion + parallel search across Jamendo, Internet Archive,
        Audius and optional official SoundCloud API. Select the best matching
        candidate only after its media URL passes a lightweight HTTP validation.
        """
        query_candidates = [query]
        try:
            query_candidates.extend(await self.discover_metadata_queries(query))
        except Exception as error:
            print(f"Fumi metadata discovery warning: {type(error).__name__}: {error}")

        unique_queries = []
        seen = set()
        for candidate in query_candidates:
            normalized = self._normalize_text(candidate)
            if normalized and normalized not in seen:
                seen.add(normalized)
                unique_queries.append(candidate)
            if len(unique_queries) >= 4:
                break

        providers = [
            ("Jamendo", self.search_jamendo),
            ("Internet Archive", self.search_internet_archive),
            ("Audius", self.search_audius),
        ]
        if self.soundcloud_client_id and self.soundcloud_client_secret:
            providers.append(("SoundCloud", self.search_soundcloud))

        jobs = [
            (provider_name, candidate, method(candidate))
            for candidate in unique_queries
            for provider_name, method in providers
        ]
        results = await asyncio.gather(*(job[2] for job in jobs), return_exceptions=True)

        ranked = []
        errors = []
        for index, result in enumerate(results):
            provider_name, searched_query, _ = jobs[index]
            if isinstance(result, Exception):
                errors.append(f"{provider_name}: {type(result).__name__}: {result}")
                continue
            if result is None:
                continue
            score = self._match_score(query, result.title, result.artist)
            if score < 0.66:
                continue
            if not await self._validate_stream_url(result.url):
                continue
            provider_bonus = {
                "Jamendo": 0.012,
                "Audius": 0.009,
                "SoundCloud": 0.006,
                "Internet Archive": 0.0,
            }.get(result.source, 0.0)
            ranked.append((score + provider_bonus, index, result))

        if errors:
            print("Fumi Maximum Search warnings: " + " | ".join(errors[:8]))
        if not ranked:
            return None
        ranked.sort(key=lambda item: item[0], reverse=True)
        best_score, _, best_track = ranked[0]
        best_track.fallback_tracks = []
        for _, _, alternative in ranked[1:]:
            if alternative.url != best_track.url:
                alternative.requester_id = best_track.requester_id
                alternative.fallback_tracks = []
                best_track.fallback_tracks.append(alternative)
        print(
            "Fumi Maximum Search selected: "
            f"provider={best_track.source}; title={best_track.title!r}; "
            f"artist={best_track.artist!r}; score={best_score:.3f}; "
            f"fallbacks={len(best_track.fallback_tracks)}"
        )
        return best_track


    async def _get_spotify_token(self) -> str | None:
        """Cache Spotify Web API Client Credentials token; no user account access."""
        if not self.spotify_client_id or not self.spotify_client_secret:
            return None
        if self._spotify_token and time.time() < self._spotify_token_expires_at - 60:
            return self._spotify_token
        timeout = aiohttp.ClientTimeout(total=12)
        try:
            auth = aiohttp.BasicAuth(self.spotify_client_id, self.spotify_client_secret)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(
                    "https://accounts.spotify.com/api/token",
                    data={"grant_type": "client_credentials"},
                    auth=auth,
                ) as response:
                    if response.status != 200:
                        print(f"Fumi Spotify token warning: HTTP {response.status}")
                        return None
                    data = await response.json(content_type=None)
            token = data.get("access_token")
            if not token:
                return None
            self._spotify_token = str(token)
            self._spotify_token_expires_at = time.time() + int(data.get("expires_in") or 3600)
            return self._spotify_token
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as error:
            print(f"Fumi Spotify auth warning: {type(error).__name__}: {error}")
            return None

    async def spotify_track_metadata(self, url: str) -> dict | None:
        """Read official Spotify track metadata (title, artists, album, ISRC) when configured."""
        match = re.search(r"open\.spotify\.com/(?:intl-[a-z-]+/)?track/([A-Za-z0-9]+)", url)
        if not match:
            return None
        token = await self._get_spotify_token()
        if not token:
            return None
        timeout = aiohttp.ClientTimeout(total=12)
        try:
            async with aiohttp.ClientSession(
                timeout=timeout,
                headers={"Authorization": f"Bearer {token}"},
            ) as session:
                async with session.get(
                    f"https://api.spotify.com/v1/tracks/{match.group(1)}"
                ) as response:
                    if response.status != 200:
                        return None
                    item = await response.json(content_type=None)
            artists = [artist.get("name", "") for artist in item.get("artists", []) if artist.get("name")]
            external_ids = item.get("external_ids") or {}
            return {
                "title": str(item.get("name") or ""),
                "artist": ", ".join(artists),
                "album": str((item.get("album") or {}).get("name") or ""),
                "isrc": str(external_ids.get("isrc") or ""),
                "duration_ms": item.get("duration_ms"),
                "thumbnail": next(
                    (image.get("url") for image in (item.get("album") or {}).get("images", []) if image.get("url")),
                    None,
                ),
            }
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as error:
            print(f"Fumi Spotify metadata warning: {type(error).__name__}: {error}")
            return None

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
        """Count audio calls and the underlying UDP socket send attempts."""
        if getattr(voice, "_fumi_sender_instrumented", False):
            return

        stats: dict[str, int | str] = {
            "attempts": 0, "returned": 0, "errors": 0, "last_error": "",
            "udp_attempts": 0, "udp_sent": 0, "udp_errors": 0, "last_udp_error": "",
        }
        self.voice_send_stats[guild_id] = stats

        # discord.py catches OSError from send_packet() and logs a dropped packet.
        # Count the lower-level sendall too, or a dropped UDP packet can look successful.
        connection = getattr(voice, "_connection", None)
        original_packet_send = getattr(connection, "send_packet", None)
        if connection is not None and callable(original_packet_send):
            def counted_packet_send(packet: bytes):
                stats["udp_attempts"] = int(stats["udp_attempts"]) + 1
                try:
                    result = original_packet_send(packet)
                    stats["udp_sent"] = int(stats["udp_sent"]) + 1
                    return result
                except Exception as error:
                    stats["udp_errors"] = int(stats["udp_errors"]) + 1
                    stats["last_udp_error"] = f"{type(error).__name__}: {error}"[:250]
                    raise

            connection.send_packet = counted_packet_send

        original_send = voice.send_audio_packet

        def counted_send(data: bytes, *, encode: bool = True) -> None:
            stats["attempts"] = int(stats["attempts"]) + 1
            try:
                original_send(data, encode=encode)
                stats["returned"] = int(stats["returned"]) + 1
            except Exception as error:
                stats["errors"] = int(stats["errors"]) + 1
                stats["last_error"] = f"{type(error).__name__}: {error}"[:250]
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
                    future = asyncio.run_coroutine_threadsafe(
                        self._after_track(guild_id, playback_error=error), self.bot.loop
                    )
                    try:
                        future.result(timeout=0)
                    except Exception:
                        pass
                voice.play(source, after=after_play)
            except Exception as error:
                print(f"Gagal memulai audio dari {track.source}: {error}")
                if track.fallback_tracks:
                    fallback = track.fallback_tracks.pop(0)
                    fallback.fallback_tracks = list(track.fallback_tracks)
                    fallback.requester_id = track.requester_id
                    player.queue.appendleft(fallback)
                    print(f"Fumi fallback: mencoba {fallback.source} — {fallback.title}")
                player.current = None
                if player.queue:
                    self.bot.loop.call_soon(asyncio.create_task, self.start_next(guild_id))
            await self.refresh_player(guild_id)

    async def _after_track(self, guild_id: int, playback_error: Exception | None = None):
        player = self.get_player(guild_id)
        if player.suppress_next:
            player.suppress_next = False
            await self.refresh_player(guild_id)
            return

        failed_track = player.current
        if playback_error and failed_track and failed_track.fallback_tracks:
            fallback = failed_track.fallback_tracks.pop(0)
            fallback.fallback_tracks = list(failed_track.fallback_tracks)
            fallback.requester_id = failed_track.requester_id
            player.queue.appendleft(fallback)
            print(
                f"Fumi playback fallback after stream error: "
                f"{fallback.source} — {fallback.title}"
            )

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
                spotify_meta = await self.spotify_track_metadata(query)
                if spotify_meta and spotify_meta.get("title"):
                    spotify_title = str(spotify_meta["title"])
                    spotify_artist = str(spotify_meta.get("artist") or "")
                    spotify_search_query = " ".join(
                        part for part in (spotify_title, spotify_artist) if part
                    ).strip()
                else:
                    spotify_title = await self.spotify_oembed_title(query)
                    if not spotify_title:
                        await status.edit(content=(
                            "❌ Metadata Spotify tidak dapat dibaca. Kirim judul lagu dan artisnya "
                            "agar Fumi bisa mencari di katalog audio yang tersedia."
                        ))
                        return
                    # oEmbed fallback has only a display title, so normalize version suffixes.
                    version_suffix = re.match(
                        r"^(.*?)\s*[-–—]\s*(.*?)\s+(?:official\s+)?"
                        r"(?:remix|edit|version|sped\s*up|slowed|nightcore)\b.*$",
                        spotify_title,
                        flags=re.IGNORECASE,
                    )
                    if version_suffix:
                        spotify_search_query = " ".join(
                            part for part in (version_suffix.group(1).strip(), version_suffix.group(2).strip())
                            if part
                        )
                    else:
                        spotify_search_query = re.sub(r"\s*[-–—]\s*", " ", spotify_title)
                    spotify_search_query = re.sub(r"\s+", " ", spotify_search_query).strip()

                track = await self.search_multi_source(spotify_search_query or spotify_title)
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
            status = await ctx.send(f"🔎 Maximum Search: mencari di Jamendo, Internet Archive, dan Audius untuk **{discord.utils.escape_markdown(query)}**...")
            try:
                track = await self.search_multi_source(query)
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, RuntimeError) as error:
                await status.edit(content=f"❌ Pencarian musik gagal: `{error}`")
                return
            if track is None:
                await status.edit(
                    content="Tidak menemukan stream yang cocok dan dapat diakses di Jamendo, Internet Archive, atau Audius. Lagu komersial tertentu memang tidak tersedia di katalog gratis ini. Coba judul + artis, atau tautan audio resmi yang mengizinkan streaming bot."
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
            # Setiap !p memindahkan player card terbaru ke bagian paling bawah channel.
            await self.send_or_update_player(ctx)
        else:
            player.queue.append(track)
            await self.start_next(ctx.guild.id)
            await self.send_or_update_player(ctx)

    async def send_or_update_player(self, ctx: commands.Context):
        """Kirim player card baru di bawah, lalu hapus card lama agar channel tetap rapi."""
        player = self.get_player(ctx.guild.id)
        old_message = player.message
        view = FumiPlayerView(self, ctx.guild.id)
        player.view = view

        # Kirim dahulu agar UI lama tidak hilang bila pengiriman pesan baru gagal.
        new_message = await ctx.send(embed=self.make_embed(ctx.guild.id), view=view)
        player.message = new_message

        if old_message is not None:
            try:
                await old_message.delete()
            except discord.NotFound:
                pass
            except (discord.Forbidden, discord.HTTPException):
                # Jika Discord menolak penghapusan, matikan tombol lama dan bersihkan embed-nya.
                try:
                    await old_message.edit(
                        content="↪️ Player telah diperbarui di bawah.",
                        embed=None,
                        view=None,
                    )
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    pass

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
        connection_state = getattr(voice, "_connection", None) if voice is not None else None
        if connection_state is not None:
            protocol_version = getattr(connection_state, "dave_protocol_version", None)
            dave_session = getattr(connection_state, "dave_session", None)
            can_encrypt = getattr(connection_state, "can_encrypt", None)
            downgraded = getattr(connection_state, "dave_downgraded", None)
            mode = getattr(connection_state, "mode", None)
            udp_socket = getattr(connection_state, "socket", None)
            try:
                udp_socket_open = bool(udp_socket and udp_socket.fileno() >= 0)
            except Exception:
                udp_socket_open = False
            try:
                privacy_session_active = bool(voice.voice_privacy_code)
            except Exception:
                privacy_session_active = False

            dave_runtime = (
                f"Protocol version: **{protocol_version if protocol_version is not None else 'unknown'}**\n"
                f"Session object: **{'ada' if dave_session is not None else 'tidak ada'}**\n"
                f"Can encrypt: **{can_encrypt if can_encrypt is not None else 'unknown'}**\n"
                f"Privacy session aktif: **{privacy_session_active}**\n"
                f"Downgraded: **{downgraded if downgraded is not None else 'unknown'}**\n"
                f"Voice mode: `{mode if mode is not None else 'unknown'}`\n"
                f"UDP socket terbuka: **{udp_socket_open}**"
            )
        else:
            dave_runtime = "Voice connection state belum tersedia."

        embed.add_field(name="discord.py version", value=f"`{discord_version}`", inline=True)
        embed.add_field(name="DAVE / Voice runtime", value=f"{davey_status}\n{dave_runtime}", inline=False)
        if voice is not None:
            try:
                latency_text = f"{voice.latency * 1000:.0f} ms"
            except Exception:
                latency_text = "Tidak tersedia"
            embed.add_field(name="Voice latency", value=latency_text, inline=True)

        send_stats = self.voice_send_stats.get(ctx.guild.id)
        if send_stats is not None:
            send_text = (
                f"Audio calls: **{send_stats['attempts']:,}**\n"
                f"Audio calls returned: **{send_stats['returned']:,}**\n"
                f"Audio call errors: **{send_stats['errors']:,}**\n"
                f"UDP send attempts: **{send_stats.get('udp_attempts', 0):,}**\n"
                f"UDP sendall success: **{send_stats.get('udp_sent', 0):,}**\n"
                f"UDP send errors/drops: **{send_stats.get('udp_errors', 0):,}**"
            )
            if send_stats.get("last_error"):
                send_text += f"\nLast audio error: `{str(send_stats['last_error'])[:150]}`"
            if send_stats.get("last_udp_error"):
                send_text += f"\nLast UDP error: `{str(send_stats['last_udp_error'])[:150]}`"
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

    @commands.command(name="voiceprobe", aliases=["vprobe", "cekvoice"])
    @commands.guild_only()
    async def voice_probe_command(self, ctx: commands.Context):
        """Tes inti Opus, DAVE, Voice Client, dan jalur audio; hasil dikirim ke channel."""
        voice = ctx.guild.voice_client
        player = self.get_player(ctx.guild.id)

        embed = discord.Embed(
            title="🔎 FUMI VOICE CORE PROBE",
            color=PLAYER_COLOR,
        )

        if voice is None or not voice.is_connected():
            embed.add_field(
                name="Voice connection",
                value="❌ Tidak terhubung. Jalankan !afkvoice atau !p terlebih dahulu.",
                inline=False,
            )
            await ctx.send(embed=embed)
            return

        # 1) Uji encoder Opus sungguhan, bukan hanya cek library terpasang.
        try:
            opus_loaded = discord.opus.is_loaded()
        except Exception:
            opus_loaded = False

        if opus_loaded:
            try:
                encoder = discord.opus.Encoder()
                encoded = encoder.encode(bytes(3840), 960)  # 20 ms, 48 kHz, stereo PCM
                opus_result = f"✅ Encode berhasil ({len(encoded)} byte)"
                try:
                    encoder = None
                except Exception:
                    pass
            except Exception as error:
                opus_result = f"❌ Encode gagal: {type(error).__name__}: {str(error)[:180]}"
        else:
            opus_result = "❌ discord.opus.is_loaded() = False"

        embed.add_field(name="1. Opus encode test", value=opus_result, inline=False)

        # 2) Periksa status DAVE tanpa menampilkan objek/kunci rahasia.
        state = getattr(voice, "_connection", None)
        session = getattr(state, "dave_session", None) if state else None
        can_encrypt = getattr(state, "can_encrypt", None) if state else None
        protocol = getattr(state, "dave_protocol_version", None) if state else None
        downgraded = getattr(state, "dave_downgraded", None) if state else None
        mode = getattr(state, "mode", None) if state else None

        ready_checks = []
        if session is not None:
            for attr in ("ready", "is_ready", "_ready"):
                try:
                    value = getattr(session, attr, None)
                    if callable(value):
                        value = value()
                    if isinstance(value, (bool, int, str)):
                        ready_checks.append(f"{attr}={value}")
                except Exception:
                    ready_checks.append(f"{attr}=error")

        dave_lines = [
            f"Session object: **{'ada' if session is not None else 'tidak ada'}**",
            f"Can encrypt: **{can_encrypt if can_encrypt is not None else 'unknown'}**",
            f"Protocol: **{protocol if protocol is not None else 'unknown'}**",
            f"Downgraded: **{downgraded if downgraded is not None else 'unknown'}**",
            f"Mode: `{mode if mode is not None else 'unknown'}`",
        ]
        if ready_checks:
            dave_lines.append("Session readiness: `" + ", ".join(ready_checks) + "`")
        embed.add_field(name="2. DAVE encryption state", value="\n".join(dave_lines), inline=False)

        # 3) Socket dan status player. UDP success bukan bukti bahwa pendengar menerima audio.
        sock = getattr(state, "socket", None) if state else None
        try:
            socket_open = bool(sock and sock.fileno() >= 0)
        except Exception:
            socket_open = False

        source = getattr(voice, "source", None)
        try:
            source_is_opus = bool(source and source.is_opus())
        except Exception:
            source_is_opus = None

        playback_lines = [
            f"Connected: **{voice.is_connected()}**",
            f"Playing: **{voice.is_playing()}**",
            f"Paused: **{voice.is_paused()}**",
            f"UDP socket open: **{socket_open}**",
            f"Audio source: `{type(source).__name__ if source is not None else 'none'}`",
            f"Source already Opus: **{source_is_opus if source_is_opus is not None else 'unknown'}**",
        ]
        embed.add_field(name="3. Voice playback path", value="\n".join(playback_lines), inline=False)

        # 4) Tampilkan penghitung kirim terakhir yang sudah dikumpulkan extension.
        send = self.voice_send_stats.get(ctx.guild.id, {})
        if send:
            send_lines = [
                f"Audio calls: **{send.get('attempts', 0):,}**",
                f"UDP attempts: **{send.get('udp_attempts', 0):,}**",
                f"UDP send success: **{send.get('udp_sent', 0):,}**",
                f"UDP send errors: **{send.get('udp_errors', 0):,}**",
            ]
        else:
            send_lines = ["Belum ada statistik pengiriman; mulai putar lagu setelah bot tersambung."]
        embed.add_field(name="4. Send counters", value="\n".join(send_lines), inline=False)

        # 5) Beri kesimpulan otomatis berdasarkan pemeriksaan inti.
        if not opus_loaded or "Encode gagal" in opus_result:
            verdict = "❌ **Masalah encoder Opus lokal.** Perbaiki pemuatan/library Opus terlebih dahulu."
        elif can_encrypt is False:
            verdict = "❌ **DAVE belum siap (`can_encrypt=False`).** Ini titik kegagalan utama yang terlihat; UDP/PCM yang normal tidak membuktikan paket dapat didekripsi Discord."
        elif can_encrypt is None:
            verdict = "⚠️ Status DAVE tidak dapat dibaca dari Voice Client ini. Perlu log transisi DAVE yang lebih spesifik."
        elif not voice.is_playing() and not voice.is_paused():
            verdict = "⚠️ Tidak ada audio yang sedang diputar saat probe dijalankan."
        else:
            verdict = "🟡 Opus dan status enkripsi tampak siap. Jika tetap tidak terdengar, perlu uji penerimaan di klien Discord/packet-level; angka UDP lokal saja tidak cukup."
        embed.add_field(name="Kesimpulan probe", value=verdict, inline=False)
        embed.set_footer(text="Jalankan saat lagu sedang diputar. Tidak menampilkan URL, token, atau kunci.")
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
