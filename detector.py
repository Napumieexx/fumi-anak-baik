import json
import re
from rapidfuzz import process, fuzz


with open("words.json", "r", encoding="utf-8") as file:
    BAD_WORDS = json.load(file)


def normalize_word(word):
    """
    Mengubah huruf besar menjadi kecil
    dan menghilangkan pengulangan huruf.
    
    Contoh:
    anjgggg -> anjg
    baaaaabi -> babi
    """
    word = word.lower()
    return re.sub(r"(.)\1+", r"\1", word)


def clean_text(text):
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return text


def detect_words(text):
    text = clean_text(text)

    # Pisahkan pesan menjadi kata-kata
    raw_words = text.split()

    detected = []

    for raw_word in raw_words:
        word = normalize_word(raw_word)

        # Cocok langsung
        if word in BAD_WORDS:
            detected.append({
                "word": raw_word,
                "matched": word,
                "score": BAD_WORDS[word],
                "similarity": 100
            })
            continue

        # Pencocokan fuzzy
        result = process.extractOne(
            word,
            BAD_WORDS.keys(),
            scorer=fuzz.ratio
        )

        if result:
            matched_word, similarity, _ = result

            if similarity >= 95:
                detected.append({
                    "word": raw_word,
                    "matched": matched_word,
                    "score": BAD_WORDS[matched_word],
                    "similarity": similarity
                })

    return detected
