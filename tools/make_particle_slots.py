"""Находит частицы в grammar/sentences.tsv для упражнения «Частицы» тренажёра.

Зависимости: pip install fugashi unidic-lite. Результат: grammar/particle_slots.json
(список [номер предложения, позиция символа, частица]); запускать после правки sentences.tsv.
"""
import csv, json
from pathlib import Path

import fugashi

ROOT = Path(__file__).resolve().parent.parent
TARGET = {"は", "が", "を", "に", "で", "へ", "と", "から", "まで", "より", "も", "の", "や", "しか", "だけ", "ばかり", "でも"}
KINDS = {"格助詞", "係助詞", "副助詞"}

def main():
    lines = [l for l in (ROOT / "grammar/sentences.tsv").read_text(encoding="utf-8").splitlines() if l and not l.startswith("#")]
    rows = list(csv.DictReader(lines, delimiter="\t"))
    tagger = fugashi.Tagger()
    slots = []
    for i, r in enumerate(rows):
        pos = 0
        text = r["jp"]
        for w in tagger(text):
            start = text.index(w.surface, pos)
            pos = start + len(w.surface)
            if w.feature.pos1 == "助詞" and w.surface in TARGET and w.feature.pos2 in KINDS:
                # を/に/で внутри «〜てください»-подобных связок не трогаем; в цитате 「」 тоже
                if start == 0 or text.count("「", 0, start) > text.count("」", 0, start):
                    continue
                if w.surface == "は" and text[start - 1] == "で" and text[pos:pos + 2] in ("あり", "ない"):
                    continue  # часть связки ではありません / ではない
                slots.append([i, start, w.surface])
    (ROOT / "grammar/particle_slots.json").write_text(json.dumps(slots, ensure_ascii=False), encoding="utf-8")
    print(len(slots), "slots in", len(rows), "sentences")

if __name__ == "__main__":
    main()
