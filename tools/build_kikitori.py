"""Собирает данные тренажёра и карту грамматики для 毎日の聞きとり50日 下.

Зависимости: pip install genanki fugashi unidic-lite
Запуск: python tools/build_kikitori.py [--source файл_или_каталог]

Источник: массив уроков в lessons.json либо файлы по одному уроку в каталоге.
Поля урока: lesson, title, main, supporting, phrases. Необязательное vocab
дополняет словарь строками [написание, чтение, перевод, часть речи].
"""

import argparse
from collections import defaultdict
import html
import json
from pathlib import Path
import re
import unicodedata

import fugashi

from add_furigana import KANJI, furigana, hira
from build_anki import load_vocab
from build_trainer import ROOT, build_shoho, radical, short_id
from make_particle_slots import KINDS, TARGET


FIRST_LESSON = 26
LAST_LESSON = 50
LESSON_RANGE = range(FIRST_LESSON, LAST_LESSON + 1)
POSITIONS = {"v5", "v1", "vs", "vk", "adj-i", "adj-na", ""}
CONJUGATION = {"五段": "v5", "上一段": "v1", "下一段": "v1", "サ行変格": "vs", "カ行変格": "vk"}
LEXICAL_POS = {"名詞", "代名詞", "動詞", "形容詞", "形状詞", "副詞", "連体詞", "感動詞"}
VOCAB_CONTEXT = re.compile(r"^\([^()]+\)")
DIGIT_KANA = ("ぜろ", "いち", "に", "さん", "よん", "ご", "ろく", "なな", "はち", "きゅう")
COUNTER_KANA = {"時間": "じかん", "時": "じ", "分": "ふん", "日": "にち", "月": "がつ", "年間": "ねんかん", "年": "ねん",
                "週間": "しゅうかん", "人": "にん", "円": "えん", "万": "まん", "本": "ほん", "歳": "さい", "台": "だい",
                "枚": "まい", "回": "かい", "階": "かい", "丁目": "ちょうめ", "号": "ごう", "番地": "ばんち", "番線": "ばんせん",
                "番": "ばん", "部": "ぶ"}
COUNTER_RE = re.compile(r"([0-9０-９]+) (" + "|".join(COUNTER_KANA) + r")\[[^\]]+\]")
WEEKDAYS = dict(zip("月火水木金土日", ("げつ", "か", "すい", "もく", "きん", "ど", "にち"), strict=True))
DAYS = {2: "ふつか", 3: "みっか", 4: "よっか", 5: "いつか", 6: "むいか", 7: "なのか",
        8: "ようか", 9: "ここのか", 10: "とおか", 14: "じゅうよっか", 20: "はつか", 24: "にじゅうよっか"}


def load_lessons(source, *, complete=True):
    """Читает исходники и проверяет, что строки каждого урока имеют нужные поля."""
    paths = sorted(source.rglob("*.json")) if source.is_dir() else [source]
    by_number = {}
    for path in paths:
        entries = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(entries, dict):
            entries = [entries]
        for entry in entries:
            lesson = entry.get("lesson")
            if lesson not in LESSON_RANGE or lesson in by_number:
                raise ValueError(f"{path}: неверный или повторный номер урока {lesson}")
            if not isinstance(entry.get("title"), str) or not entry["title"].strip():
                raise ValueError(f"{path}: отсутствует заголовок урока {lesson}")
            for key, sizes in (("main", (3,)), ("supporting", (4,)), ("phrases", (2, 3)), ("vocab", (3, 4))):
                rows = entry.get(key, [])
                if key in ("main", "phrases") and not rows:
                    raise ValueError(f"{path}: урок {lesson}, отсутствует {key}")
                for row in rows:
                    if not isinstance(row, list) or len(row) not in sizes or not all(isinstance(cell, str) for cell in row):
                        raise ValueError(f"{path}: урок {lesson}, неверная строка {key}: {row!r}")
                    required = row[:3] if key == "vocab" else row
                    if not all(cell.strip() for cell in required):
                        raise ValueError(f"{path}: урок {lesson}, пустое поле {key}: {row!r}")
                    if key == "vocab" and len(row) == 4 and row[3] not in POSITIONS:
                        raise ValueError(f"{path}: урок {lesson}, неизвестная часть речи {row[3]!r}")
            by_number[lesson] = entry
    missing = sorted(set(LESSON_RANGE) - by_number.keys())
    if not by_number or complete and missing:
        raise ValueError(f"{source}: отсутствуют уроки {', '.join(map(str, missing))}")
    return [by_number[n] for n in sorted(by_number)]


def no_context(text):
    return VOCAB_CONTEXT.sub("", text)


def match_key(text):
    """Сопоставляет запись из упражнения и ту же фразу в карте грамматики."""
    text = unicodedata.normalize("NFKC", text)
    return re.sub(r"[\s、。｡､！？!?…・]+", "", text)


def number_kana(number):
    if number < 10:
        return DIGIT_KANA[number]
    for unit, reading, changes in ((10000, "まん", {}), (1000, "せん", {3: "さんぜん", 8: "はっせん"}),
                                   (100, "ひゃく", {3: "さんびゃく", 6: "ろっぴゃく", 8: "はっぴゃく"}),
                                   (10, "じゅう", {})):
        if number >= unit:
            major, rest = divmod(number, unit)
            head = changes.get(major) or ((number_kana(major) if major != 1 or unit == 10000 else "") + reading)
            return head + (number_kana(rest) if rest else "")


def read_counter(number, counter):
    prefix = number_kana(number)
    last = number % 10
    shortened = prefix[:-1] + "っ"  # いち → いっ, ろく → ろっ, はち → はっ, じゅう → じゅっ
    gemination = last in {1, 8} or last == 0 and number % 100 != 0
    fallback = COUNTER_KANA[counter]
    if counter == "分":
        if gemination or last == 6:
            return shortened + "ぷん"
        return prefix + ("ぷん" if last in {3, 4} else "ふん")
    if counter in {"時", "時間", "月"} and last in {4, 7, 9}:
        special = {4: "し" if counter == "月" else "よ", 7: "しち", 9: "く"}
        return prefix[:-len(DIGIT_KANA[last])] + special[last] + fallback
    if counter == "日":
        return DAYS.get(number, prefix + "にち")
    if counter == "人" and number in {1, 2, 4}:
        return {1: "ひとり", 2: "ふたり", 4: "よにん"}[number]
    if counter == "本":
        if gemination or last == 6:
            return shortened + "ぽん"
        return prefix + ("ぼん" if last == 3 else "ほん")
    if counter == "階" and last == 3:
        return prefix + "がい"
    if counter == "歳" and number == 20:
        return "はたち"
    if counter in {"週間", "歳", "回", "階"} and gemination:
        return shortened + fallback
    return prefix + fallback


def kikitori_furigana(tagger, text):
    reading = furigana(tagger, text)
    reading = re.sub(r"([月火水木金土日])曜\[[^\]]+\] ?日\[[^\]]+\]",
                     lambda m: f"{m[1]}曜日[{WEEKDAYS[m[1]]}ようび]", reading)
    reading = reading.replace("富士[ふじ] 山[やま]", "富士山[ふじさん]")
    reading = re.sub(r"何\[なん\](?=[をがに])", "何[なに]", reading)

    def annotate(match):
        digits, counter = match.groups()
        return f" {digits}{counter}[{read_counter(int(digits), counter)}]"

    return COUNTER_RE.sub(annotate, reading).strip()


def word_key(written, reading):
    return no_context(written), hira(no_context(reading))


def vocab_index(words):
    result = {}
    for original, trainer_word in zip(load_vocab(), words, strict=True):
        for spelling in (trainer_word["e"], original["kanji"], original["kana"]):
            if spelling:
                result.setdefault(word_key(spelling, trainer_word["k"]), trainer_word)
    # UniDic prefers にっぽん for 日本 even when the lesson materials use にほん.
    if ("日本", "にほん") in result:
        result["日本", "にっぽん"] = result["日本", "にほん"]
    return result


def observed_words(tokens, glossary):
    """Сверяет основы UniDic со словарём. Для составных слов проверяет соседние токены."""
    for start, token in enumerate(tokens):
        if token.feature.pos1 not in LEXICAL_POS:
            continue
        spelling_prefix = ""
        reading_prefix = ""
        for part in tokens[start:start + 5]:
            if part.feature.pos1 in {"補助記号", "空白"}:
                break
            feature = part.feature
            spelling = feature.orthBase or part.surface
            reading = feature.kanaBase or part.surface
            key = word_key(spelling_prefix + spelling, reading_prefix + reading)
            item = None
            has_spelling = bool(KANJI.search(key[0]))
            lemma = (feature.lemma or "").split("-", 1)[0]
            if feature.pos1 in LEXICAL_POS | {"接尾辞"} and not has_spelling and lemma:
                # Для слов, записанных каной, UniDic часто знает каноническое написание.
                lemma_key = (spelling_prefix + lemma, key[1])
                item = glossary.get(lemma_key)
            if feature.pos1 in LEXICAL_POS | {"接尾辞"}:
                item = item or glossary.get(key)
            if item is not None and item["e"] == "引く" and not has_spelling:
                # У Сёхо 引く означает «вычитать», а здесь ひく — игра на пианино или простуда.
                item = None
            if item is not None and not (part is token and item["p"].startswith("v") and feature.pos1 != "動詞"):
                found = dict(item)
                if not item["p"] and part is token:
                    written_forms = {no_context(item["e"]), item["s"]} - {""}
                    if (feature.pos1 == "動詞" and feature.pos2 == "一般"
                            and written_forms.intersection({spelling, lemma})):
                        found["p"] = CONJUGATION.get(feature.cType.split("-", 1)[0], "")
                    elif feature.pos1 == "形容詞" and item["k"].endswith("い"):
                        found["p"] = "adj-i"
                yield found
            spelling_prefix += part.surface
            reading_prefix += feature.kana or part.surface


def remember_word(words, item, lesson):
    key = item["e"], item["k"]
    if key not in words:
        words[key] = {**item, "id": short_id("kikitori", *key), "l": lesson, "ls": [lesson]}
    else:
        entry = words[key]
        if lesson not in entry["ls"]:
            entry["ls"].append(lesson)
        if not entry["p"]:
            entry["p"] = item["p"]


def particle_slots(tokens, text, sentence_index):
    pos = 0
    for word in tokens:
        start = text.index(word.surface, pos)
        pos = start + len(word.surface)
        if word.feature.pos1 != "助詞" or word.feature.pos2 not in KINDS or word.surface not in TARGET:
            continue
        if start == 0 or any(text.count(left, 0, start) > text.count(right, 0, start)
                             for left, right in (("「", "」"), ("『", "』"))):
            continue
        if word.surface == "は" and text[start - 1] == "で" and text[pos:pos + 2] in ("あり", "ない"):
            continue
        yield [sentence_index, start, word.surface]


def add_kanji(core_kanji, additional_kanji, occurrences, words):
    examples = defaultdict(list)
    for word in words:
        for ch in set(KANJI.findall(word["e"] + word["s"])):
            spelling = word["e"] if ch in word["e"] else word["s"]
            examples[ch].append([spelling, word["k"], word["r"], word["l"]])
    result = []
    # У примеров Сёхо номера уроков принадлежат другому учебнику.
    fallback = {entry["c"]: [[w, k, r, None] for w, k, r, _ in entry["ex"]] for entry in core_kanji}
    fallback.update({entry["c"]: entry["ex"] for entry in additional_kanji})
    for entry in core_kanji + additional_kanji:
        char = entry["c"]
        if char not in occurrences:
            continue
        lessons = sorted(occurrences[char])
        ordered = sorted(examples[char], key=lambda example: (example[3], len(example[0])))
        distinct = {}
        for example in ordered + fallback[char]:
            distinct.setdefault(tuple(example[:2]), example)
        display = list(distinct.values())[:6]
        cue = display[0][1:3] if display else entry["cue"]
        result.append({**entry, "l": lessons[0], "ls": lessons, "ex": display, "cue": cue})
    return sorted(result, key=lambda entry: (entry["l"], entry["c"]))


def load_additional_kanji(source, known):
    if not source.exists():
        return []
    rows = []
    seen = set(known)
    for entry in json.loads(source.read_text(encoding="utf-8")):
        char = entry["c"]
        if char in seen:
            continue
        if len(char) != 1 or not KANJI.fullmatch(char):
            raise ValueError(f"{source}: недопустимый знак {char!r}")
        seen.add(char)
        rows.append({**entry, "rad": radical(char) or entry.get("rad", ""), "ex": entry.get("ex", []),
                     "cue": entry.get("cue", ["", ""])})
    return rows


def build_kikitori(lessons, kanji_source=ROOT / "data/kikitori/kanji.json"):
    past_data = build_shoho()
    core_kanji = past_data["kanji"]
    additional_kanji = load_additional_kanji(kanji_source, {row["c"] for row in core_kanji})
    kanji_meanings = {row["c"]: row["m"].split(";")[0] for row in core_kanji + additional_kanji}
    reference_words = vocab_index(past_data["words"])
    words, occurrences = {}, defaultdict(set)
    sentences, slots, topics = [], [], []
    tagger = fugashi.Tagger()
    for lesson in lessons:
        number = lesson["lesson"]
        glossary = reference_words.copy()
        # Ручная лексика служит также подсказкой для новых слов, найденных в тексте.
        for spelling, reading, ru, *pos in lesson.get("vocab", []):
            kb = " · ".join(f"{ch} — {kanji_meanings[ch]}" for ch in dict.fromkeys(KANJI.findall(spelling)) if ch in kanji_meanings)
            word = {"e": spelling, "k": reading, "s": "", "r": ru, "p": pos[0] if pos else "", "t": "word", "kb": kb}
            glossary[word_key(spelling, reading)] = word
            remember_word(words, word, number)

        grammar = {}
        for _, pattern, _, example in lesson.get("supporting", []):
            grammar.setdefault(match_key(example), pattern)
        for pattern, _, example in reversed(lesson["main"]):
            grammar[match_key(example)] = pattern

        seen = set()
        for japanese, russian, *labels in lesson["phrases"]:
            japanese, russian = japanese.strip(), russian.strip()
            if (japanese, russian) in seen:
                continue
            seen.add((japanese, russian))
            label = labels[0] if labels else grammar.get(match_key(japanese), f"Фразы урока {number}")
            tokens = list(tagger(japanese))
            slots.extend(particle_slots(tokens, japanese, len(sentences)))
            sentences.append({"id": short_id("kikitori", str(number), japanese, russian), "l": number,
                              "p": label, "j": japanese, "r": russian, "f": kikitori_furigana(tagger, japanese)})
            for char in set(KANJI.findall(japanese)):
                occurrences[char].add(number)
            for word in observed_words(tokens, glossary):
                remember_word(words, word, number)

        topics.append({"from": number, "to": number, "label": f"Урок {number}",
                       "text": lesson["title"] + " · " + ", ".join(row[0] for row in lesson["main"])})

    word_list = sorted(words.values(), key=lambda entry: (entry["l"], entry["e"], entry["k"]))
    return {"minLesson": FIRST_LESSON, "maxLesson": LAST_LESSON, "words": word_list,
            "kanji": add_kanji(core_kanji, additional_kanji, occurrences, word_list),
            "sentences": sentences, "slots": slots, "topics": topics}


def grammar_markdown(lessons):
    def render_points(points):
        return [f"- **{pattern}** — {description} <span lang=\"ja\">{html.escape(example)}</span>"
                for pattern, description, example in points]

    lines = ["# 毎日の聞きとり50日 下. Грамматика по урокам", "",
             "Основные конструкции выделены в каждом уроке. Остальная грамматика сгруппирована по роли в примерах и диалогах."]
    for lesson in lessons:
        lines.extend(["", f"## Урок {lesson['lesson']}. {lesson['title']}", "", "### Основная грамматика", ""])
        lines.extend(render_points(lesson["main"]))
        support = defaultdict(list)
        for group, *point in lesson.get("supporting", []):
            support[group].append(point)
        if support:
            lines.extend(["", "### Другие конструкции урока"])
            for group, points in support.items():
                lines.extend(["", f"#### {group}", "", *render_points(points)])
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "data/kikitori/lessons.json")
    parser.add_argument("--kanji-source", type=Path, default=ROOT / "data/kikitori/kanji.json")
    parser.add_argument("--data-output", type=Path, default=ROOT / "data/kikitori/trainer.json")
    parser.add_argument("--grammar-output", type=Path, default=ROOT / "grammar/kikitori.md")
    args = parser.parse_args()
    lessons = load_lessons(args.source)
    data = build_kikitori(lessons, args.kanji_source)
    args.data_output.parent.mkdir(parents=True, exist_ok=True)
    args.grammar_output.parent.mkdir(parents=True, exist_ok=True)
    args.data_output.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    args.grammar_output.write_text(grammar_markdown(lessons), encoding="utf-8")
    print(f"{len(lessons)} уроков, {len(data['sentences'])} фраз, {len(data['words'])} слов, "
          f"{len(data['kanji'])} кандзи, {len(data['slots'])} частиц")


if __name__ == "__main__":
    main()
