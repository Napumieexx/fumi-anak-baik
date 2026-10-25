import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

from rapidfuzz import process
from rapidfuzz.distance import OSA

BASE_DIR = Path(__file__).resolve().parent

# ---------- Konfigurasi ----------
LEET = str.maketrans("4@3105$7", "aaeiosst")
SUFFIXES = ("nya", "ku", "mu", "in", "an", "kan", "lah")
MIN_STEM = 3          # sisa kata minimal setelah imbuhan dibuang
MIN_FUZZY_LEN = 6     # kata < 6 huruf hanya boleh exact match
DEFAULT_SAFE = {"kontrol", "bangsa", "bangsal", "anjung"}

MENTION_OR_URL = re.compile(r"<a?[@#:][^>]*>|https?://\S+")
REPEATS = re.compile(r"(.)\1+")          # aaa  -> a
REPEATS3 = re.compile(r"(.)\1{2,}")      # aaaa -> aa
NON_TEXT = re.compile(r"[^a-z0-9@$\s]")


# ---------- Normalisasi ----------
def normalize_word(word):
    """Huruf kecil + hapus pengulangan huruf (baaabi -> babi)."""
    return REPEATS.sub(r"\1", word.lower())


def clean_text(text):
    """Buang mention/emoji/URL, NFKD, hapus aksen, sisakan a-z 0-9 @ $."""
    text = MENTION_OR_URL.sub(" ", text)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()
    return NON_TEXT.sub(" ", text)


def merge_spaced(tokens):
    """Gabung >=3 huruf tunggal berurutan: a n j i n g -> anjing."""
    out, buf = [], []
    for t in tokens + [""]:               # sentinel "" untuk flush buffer
        if len(t) == 1:
            buf.append(t)
            continue
        out.extend(["".join(buf)] if len(buf) >= 3 else buf)
        buf = []
        if t:
            out.append(t)
    return out


# ---------- Load data ----------
def _load_dictionary(path):
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    entries = {}
    for word, score in raw.items():
        if isinstance(score, bool) or not isinstance(score, (int, float)):
            raise ValueError(f"Skor tidak valid untuk '{word}': {score!r}")
        w = word.lower()
        entries[w] = score                        # bentuk persis
        n = normalize_word(w)
        if len(n) >= MIN_STEM:
            entries.setdefault(n, score)          # bentuk tanpa huruf ganda
    return entries


def _load_safe(path):
    try:
        with open(path, encoding="utf-8") as f:
            words = json.load(f)
    except FileNotFoundError:
        words = []
    return DEFAULT_SAFE | {normalize_word(w) for w in words}


ENTRIES = _load_dictionary(BASE_DIR / "words.json")
SAFE = _load_safe(BASE_DIR / "whitelist.json")
FUZZY_CHOICES = [k for k in ENTRIES if len(k) >= MIN_FUZZY_LEN and k.isalpha()]


# ---------- Pencocokan ----------
def _forms(token):
    """Bentuk kandidat unik: (asli, leet) x (apa adanya, huruf ganda
    dilonggarkan, huruf ganda dihapus) + stem tanpa imbuhan.
    Tuple kedua True = bentuk 'base' yang boleh dicek fuzzy."""
    seen = set()

    def emit(f):
        if f and f not in seen:
            seen.add(f)
            return True
        return False

    for variant in (token, token.translate(LEET)):
        base = REPEATS.sub(r"\1", variant)
        for form in (variant, REPEATS3.sub(r"\1\1", variant), base):
            if emit(form):
                yield form, False
        for suf in SUFFIXES:
            if base.endswith(suf) and len(base) - len(suf) >= MIN_STEM:
                stem = base[: -len(suf)]
                if emit(stem):
                    yield stem, False
        yield base, True


@lru_cache(maxsize=4096)
def _match_token(token):
    if token in SAFE or normalize_word(token) in SAFE:
        return None

    fuzzy_bases = []
    for form, is_base_marker in _forms(token):
        if is_base_marker:
            fuzzy_bases.append(form)
        elif form in SAFE:
            continue
        elif form in ENTRIES:                     # exact: O(1)
            return form, ENTRIES[form], 100.0

    # Fuzzy: jarak edit OSA (sisip/hapus/ganti/tukar 2 huruf = 1 edit)
    for base in dict.fromkeys(fuzzy_bases):
        if len(base) < MIN_FUZZY_LEN or base in SAFE:
            continue
        max_d = 1 if len(base) <= 7 else 2
        hit = process.extractOne(
            base, FUZZY_CHOICES, scorer=OSA.distance, score_cutoff=max_d
        )
        if hit:
            matched, dist, _ = hit
            sim = 100 * (1 - dist / max(len(base), len(matched)))
            return matched, ENTRIES[matched], round(sim, 1)
    return None


def detect_words(text):
    """list[dict] berisi word/matched/score/similarity (kompatibel bot.py)."""
    tokens = merge_spaced(clean_text(text).split())
    detected = []
    for token in tokens:
        hit = _match_token(token)
        if hit:
            matched, score, sim = hit
            detected.append({"word": token, "matched": matched,
                             "score": score, "similarity": sim})
    return detected
