"""Собирает колоду Anki anki/nihongo_shoho.apkg из файлов в data/ и grammar/.

Запуск:  pip install genanki && python tools/build_anki.py
Повторный импорт обновлённой колоды не создаёт дублей: у заметок стабильные GUID,
поэтому прогресс повторений сохраняется.
"""
import csv
import html
import re
from pathlib import Path

import genanki

from check_kanji import TABLE, load_core

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "anki" / "nihongo_shoho.apkg"
COURSE_KANJI = set("".join(TABLE.values()))
KANJI_RE = re.compile(r"[一-鿿々]")

# Фиксированные ID, чтобы повторный импорт обновлял, а не дублировал.
DECK_ROOT = "日本語初歩"
DECK_IDS = {"vocab": 1730000101, "kanji": 1730000102, "sent": 1730000103}
MODEL_IDS = {"vocab": 1730000201, "kanji": 1730000202, "sent": 1730000203}

POS_RU = {"v5": "глагол, I группа", "v1": "глагол, II группа", "vs": "глагол する",
          "vk": "глагол 来る", "adj-i": "い‑прилагательное", "adj-na": "な‑прилагательное"}

CSS = """
.card { font-family: "Hiragino Kaku Gothic ProN", "Noto Sans JP", "Yu Gothic", "Meiryo", sans-serif;
  font-size: 20px; text-align: center; color: #1f2328; background: #fbfaf7; line-height: 1.5; }
.card.nightMode { color: #e8e6e3; background: #1e1f22; }
.jp-big { font-size: 56px; margin: 12px 0 4px; }
.jp-mid { font-size: 32px; margin: 8px 0; }
.reading { font-size: 26px; color: #6b4fbb; }
.nightMode .reading { color: #b9a6ff; }
.meaning { font-size: 22px; margin-top: 8px; }
.hint, .meta { font-size: 14px; color: #8a8f98; margin-top: 10px; }
.pattern { display: inline-block; font-size: 15px; padding: 2px 10px; border-radius: 12px;
  background: #ece8ff; color: #4b3a99; margin-top: 10px; }
.nightMode .pattern { background: #3a3354; color: #d6ccff; }
.label { font-size: 13px; color: #8a8f98; text-transform: uppercase; letter-spacing: .05em; }
.readings { display: flex; justify-content: center; gap: 28px; margin: 10px 0; flex-wrap: wrap; }
.readings div { min-width: 120px; }
.on { font-size: 22px; color: #b5482d; } .kun { font-size: 22px; color: #2d7a5b; }
.nightMode .on { color: #ff9f85; } .nightMode .kun { color: #7fd6ae; }
.examples { text-align: left; display: inline-block; font-size: 19px; margin-top: 8px; }
.examples li { margin: 3px 0; } .examples .tb { color: #6b4fbb; font-size: 12px; }
.strokes img { width: 150px; height: 150px; background: #fff; border-radius: 8px; margin-top: 10px; }
.breakdown { font-size: 15px; color: #6d7380; margin-top: 10px; }
ruby rt { font-size: 0.5em; }
"""


def read_tsv(path):
    lines = [l for l in path.read_text(encoding="utf-8").splitlines() if l and not l.startswith("#")]
    return list(csv.DictReader(lines, delimiter="\t"))


def speakable(text):
    """Текст для озвучки: без скобок‑подсказок и знака ～."""
    return re.sub(r"[()（）～〜]", "", text)


def display_form(kana, kanji):
    """Показываем кандзи, только если все иероглифы слова есть в курсе; иначе — кану."""
    if kanji and all(c in COURSE_KANJI for c in KANJI_RE.findall(kanji)):
        return kanji
    return kana


def merge_meanings(*meanings):
    seen, out = set(), []
    for m in meanings:
        for part in re.split(r"[;,]\s*", m):
            part = re.sub(r"^зд\.\s*", "", part.strip())
            if part and part.lower() not in seen:
                seen.add(part.lower())
                out.append(part)
    return ", ".join(out)


def kanji_breakdown(word, kanji_info):
    items = []
    for c in dict.fromkeys(KANJI_RE.findall(word)):
        if c in kanji_info:
            items.append(f"{c} — {kanji_info[c]['meaning'].split(';')[0]}")
    return " · ".join(items)


def ruby(word, reading):
    return f"<ruby>{html.escape(word)}<rt>{html.escape(reading)}</rt></ruby>" if word != reading else html.escape(word)


def kun_display(k):
    stem, _, oku = k.partition(".")
    return f"{stem}<span style='opacity:.55'>{oku}</span>" if oku else stem


# ---------------------------------------------------------------- модели
VOCAB_MODEL = genanki.Model(
    MODEL_IDS["vocab"], "日本語初歩 · Слово",
    fields=[{"name": n} for n in ["Expression", "Reading", "Spelling", "Meaning", "Speak", "PartOfSpeech",
                                   "Kanji", "Lesson"]],
    templates=[
        {"name": "1 Понимание (яп → рус)",
         "qfmt": '<div class="jp-big">{{Expression}}</div><div class="hint">урок {{Lesson}}</div>',
         "afmt": '<div class="jp-big">{{Expression}}</div><div class="reading">{{Reading}}</div>'
                 '{{tts ja_JP:Speak}}<hr id="answer"><div class="meaning">{{Meaning}}</div>'
                 '{{#Spelling}}<div class="meta">пишется также: {{Spelling}}</div>{{/Spelling}}'
                 '{{#PartOfSpeech}}<div class="meta">{{PartOfSpeech}}</div>{{/PartOfSpeech}}'
                 '{{#Kanji}}<div class="breakdown">{{Kanji}}</div>{{/Kanji}}'},
        {"name": "2 Говорение (рус → яп)",
         "qfmt": '<div class="meaning">{{Meaning}}</div>'
                 '{{#PartOfSpeech}}<div class="meta">{{PartOfSpeech}}</div>{{/PartOfSpeech}}'
                 '<div class="hint">скажите вслух по‑японски · урок {{Lesson}}</div>',
         "afmt": '{{FrontSide}}<hr id="answer"><div class="jp-big">{{Expression}}</div>'
                 '<div class="reading">{{Reading}}</div>{{tts ja_JP:Speak}}'
                 '{{#Kanji}}<div class="breakdown">{{Kanji}}</div>{{/Kanji}}'},
    ],
    css=CSS, sort_field_index=0)

KANJI_MODEL = genanki.Model(
    MODEL_IDS["kanji"], "日本語初歩 · Кандзи",
    fields=[{"name": n} for n in ["Kanji", "Meaning", "On", "Kun", "Examples", "WritingCue", "Strokes", "Lesson"]],
    templates=[
        {"name": "1 Узнавание",
         "qfmt": '<div class="jp-big">{{Kanji}}</div><div class="hint">значение и чтения? · урок {{Lesson}}</div>',
         "afmt": '<div class="jp-big">{{Kanji}}</div><hr id="answer"><div class="meaning">{{Meaning}}</div>'
                 '<div class="readings"><div><div class="label">он</div><div class="on">{{On}}</div></div>'
                 '<div><div class="label">кун</div><div class="kun">{{Kun}}</div></div></div>'
                 '<ul class="examples">{{Examples}}</ul><div class="strokes">{{Strokes}}</div>'},
        {"name": "2 Написание",
         "qfmt": '<div class="meaning">{{Meaning}}</div><div class="readings">'
                 '<div><div class="label">он</div><div class="on">{{On}}</div></div>'
                 '<div><div class="label">кун</div><div class="kun">{{Kun}}</div></div></div>'
                 '<div class="jp-mid">{{WritingCue}}</div>'
                 '<div class="hint">напишите иероглиф на бумаге или пальцем · урок {{Lesson}}</div>',
         "afmt": '{{FrontSide}}<hr id="answer"><div class="jp-big">{{Kanji}}</div>'
                 '<div class="strokes">{{Strokes}}</div>'},
    ],
    css=CSS, sort_field_index=0)

SENT_MODEL = genanki.Model(
    MODEL_IDS["sent"], "日本語初歩 · Фраза",
    fields=[{"name": n} for n in ["Japanese", "Furigana", "Russian", "Pattern", "Lesson"]],
    templates=[
        {"name": "1 Скажи по‑японски",
         "qfmt": '<div class="meaning">{{Russian}}</div><div class="pattern">{{Pattern}}</div>'
                 '<div class="hint">скажите вслух, потом откройте ответ · урок {{Lesson}}</div>',
         "afmt": '{{FrontSide}}<hr id="answer"><div class="jp-mid">{{furigana:Furigana}}</div>'
                 '{{tts ja_JP:Japanese}}<div class="hint">повторите вслед за озвучкой (shadowing)</div>'},
        {"name": "2 Аудирование",
         "qfmt": '{{tts ja_JP:Japanese}}<div class="hint">послушайте и поймите фразу (можно повторить звук — R)'
                 ' · урок {{Lesson}}</div>',
         "afmt": '{{FrontSide}}<hr id="answer"><div class="jp-mid">{{furigana:Furigana}}</div>'
                 '<div class="meaning">{{Russian}}</div><div class="pattern">{{Pattern}}</div>'},
    ],
    css=CSS, sort_field_index=0)


def lesson_tag(n):
    return f"{DECK_ROOT}::урок_{int(n):02d}"


def load_vocab():
    """Словарь без имён собственных; одинаковые слова из разных уроков слиты в одну запись."""
    merged = {}
    for r in read_tsv(ROOT / "data" / "vocab.tsv"):
        if r["type"] == "name":
            continue
        expr = display_form(r["kana"], r["kanji"])
        key = (expr, r["kana"])
        if key in merged:
            m = merged[key]
            m["ru"] = merge_meanings(m["ru"], r["ru"])
            m["lessons"].append(r["lesson"])
        else:
            merged[key] = dict(r, expr=expr, ru=merge_meanings(r["ru"]), lessons=[r["lesson"]])
    return list(merged.values())


def build_vocab(deck, kanji_info):
    entries = load_vocab()
    for r in entries:
        expr, kana = r["expr"], r["kana"]
        spelling = r["kanji"] if r["kanji"] and r["kanji"] != expr else ""
        reading = kana if kana != expr else ""
        note = genanki.Note(
            model=VOCAB_MODEL,
            fields=[expr, reading, spelling, r["ru"], speakable(kana), POS_RU.get(r["pos"], ""),
                    kanji_breakdown(expr, kanji_info), r["lessons"][0]],
            tags=[lesson_tag(l) for l in dict.fromkeys(r["lessons"])] + [f"{DECK_ROOT}::{r['type']}"],
            guid=genanki.guid_for("vocab", expr, kana))
        deck.add_note(note)
    return len(entries)


def load_examples():
    """Слова из разделов 新しい漢字 + переводы из словаря и глоссария."""
    gloss = {}
    for r in read_tsv(ROOT / "data" / "vocab.tsv"):
        for w in {r["kanji"], r["kana"]}:
            w = re.sub(r"^\(.*?\)", "", w)
            if w:
                gloss.setdefault((w, re.sub(r"^\(.*?\)", "", r["kana"])), r["ru"])
                gloss.setdefault((w, None), r["ru"])
    for line in (ROOT / "data" / "extra_glossary.tsv").read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#"):
            w, rd, ru = line.split("\t")
            gloss[(w, rd)] = ru
    words = []
    for line in (ROOT / "data" / "textbook_kanji_words.txt").read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        lesson, *pairs = line.split()
        for p in pairs:
            w, rd = p.split(":")
            ru = gloss.get((w, rd)) or gloss.get((w, None)) or gloss.get((rd, None)) or ""
            words.append((w, rd, merge_meanings(ru) if ru else "", int(lesson)))
    return words


def parse_extra(extra):
    out = []
    for m in re.finditer(r"([^\s;\[]+)\[([^\]]+)\]=([^;]+)", extra):
        out.append((m.group(1), m.group(2), m.group(3).strip()))
    return out


def build_kanji(deck, package_media):
    core = load_core()
    textbook_words = load_examples()
    for row in core:
        k = row["kanji"]
        examples, seen = [], set()
        for w, rd, ru, lesson in textbook_words:
            if k in w and (w, rd) not in seen:
                seen.add((w, rd))
                examples.append(f'<li>{ruby(w, rd)} — {html.escape(ru)} <span class="tb">учебник, ур. {lesson}</span></li>')
        for w, rd, ru in parse_extra(row["extra"]):
            if (w, rd) not in seen and len(examples) < 7:
                seen.add((w, rd))
                examples.append(f"<li>{ruby(w, rd)} — {html.escape(ru)}</li>")
        cue = ""
        for w, rd, ru, _ in textbook_words:  # подсказка для написания: слово каной
            if k in w:
                cue = f"{html.escape(rd)} <span class='hint'>({html.escape(ru)})</span>" if ru else html.escape(rd)
                break
        svg = ROOT / "data" / "kanjivg" / f"{ord(k):05x}.svg"
        strokes = ""
        if svg.exists():
            media_name = f"kvg_{svg.name}"
            package_media.append((svg, media_name))
            strokes = f'<img src="{media_name}">'
        note = genanki.Note(
            model=KANJI_MODEL,
            fields=[k, row["meaning"], "、".join(row["on"]) or "—", "、".join(kun_display(x) for x in row["kun"]) or "—",
                    "".join(examples), cue, strokes, str(row["lesson"])],
            tags=[lesson_tag(row["lesson"]), f"{DECK_ROOT}::кандзи"],
            guid=genanki.guid_for("kanji", k))
        deck.add_note(note)
    return len(core)


def build_sentences(deck):
    rows = read_tsv(ROOT / "grammar" / "sentences.tsv")
    for r in rows:
        note = genanki.Note(
            model=SENT_MODEL,
            fields=[r["jp"], r["furigana"], r["ru"], r["pattern"], r["lesson"]],
            tags=[lesson_tag(r["lesson"]), f"{DECK_ROOT}::грамматика"],
            guid=genanki.guid_for("sentence", r["jp"]))
        deck.add_note(note)
    return len(rows)


def main():
    kanji_info = {r["kanji"]: r for r in load_core()}
    vocab = genanki.Deck(DECK_IDS["vocab"], f"{DECK_ROOT}::1 Слова")
    kanji = genanki.Deck(DECK_IDS["kanji"], f"{DECK_ROOT}::2 Кандзи")
    sent = genanki.Deck(DECK_IDS["sent"], f"{DECK_ROOT}::3 Грамматика (фразы)")
    media = []
    counts = (build_vocab(vocab, kanji_info), build_kanji(kanji, media), build_sentences(sent))
    # genanki берёт медиа по имени файла, поэтому копируем SVG с префиксом во временную папку.
    tmp = ROOT / "anki" / ".media"
    tmp.mkdir(parents=True, exist_ok=True)
    files = []
    for src, name in media:
        dst = tmp / name
        dst.write_bytes(src.read_bytes())
        files.append(str(dst))
    OUT.parent.mkdir(exist_ok=True)
    genanki.Package([vocab, kanji, sent], media_files=files).write_to_file(OUT)
    for f in files:
        Path(f).unlink()
    tmp.rmdir()
    print(f"слов: {counts[0]}, кандзи: {counts[1]}, фраз: {counts[2]} → {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
