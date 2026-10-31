"""Собирает тренажёр trainer/index.html из шаблона trainer/template.html и данных курса.

Запуск:  python tools/build_trainer.py [--artifact путь]
Нужен pandoc (для карты грамматики). Флаг --artifact дополнительно пишет версию
без <!doctype>/<head> — в таком виде страница публикуется как артефакт claude.ai.
"""
import base64
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

from build_anki import ROOT, kanji_breakdown, kanji_examples, load_core, load_examples, load_vocab, read_tsv

SKELETON_HEAD = ('<!doctype html><html lang="ru"><head><meta charset="utf-8">'
                 '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
                 '<style>:root{color-scheme:light;padding-top:env(safe-area-inset-top);padding-bottom:env(safe-area-inset-bottom)}'
                 'body{margin:0;font:14px system-ui,sans-serif}img{max-width:100%}[hidden]{display:none!important}</style>'
                 '</head><body>')


def grammar_html():
    md = ROOT / "grammar" / "grammar_system.md"
    html = subprocess.run(["pandoc", "-f", "gfm", "-t", "html", str(md)],
                          check=True, capture_output=True, text=True).stdout
    html = re.sub(r"<table>", '<div class="tablewrap"><table>', html)
    return html.replace("</table>", "</table></div>")


def lesson_topics():
    """Строки таблицы «Карта уроков» из grammar_system.md — для подсказки собеседнику."""
    text = (ROOT / "grammar" / "grammar_system.md").read_text(encoding="utf-8")
    section = text.split("## 10.", 1)[1].split("## 11.", 1)[0]
    topics = []
    for line in section.splitlines():
        m = re.match(r"\|\s*(\d+)(?:–(\d+))?\s*\|\s*(.+?)\s*\|", line)
        if m:
            a, b = int(m.group(1)), int(m.group(2) or m.group(1))
            label = f"Уроки {a}–{b}" if a != b else f"Урок {a}"
            topics.append({"from": a, "to": b, "label": label, "text": m.group(3)})
    return topics


def short_id(*parts):
    """Стабильный идентификатор карточки: не меняется при пересборке, пока не меняется само слово/фраза."""
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:10]


def stroke_data():
    """Порядок черт из KanjiVG в компактном виде: [пути штрихов, позиции номеров]."""
    out = {}
    for svg in sorted((ROOT / "data" / "kanjivg").glob("*.svg")):
        text = svg.read_text(encoding="utf-8")
        paths = re.findall(r'<path[^>]*\sd="([^"]+)"', text)
        nums = re.findall(r'<text transform="matrix\(1 0 0 1 ([\d.]+) ([\d.]+)\)">\d+</text>', text)
        out[chr(int(svg.stem, 16))] = [paths, [[float(x), float(y)] for x, y in nums]]
    return out


def radical(ch):
    """Ключ знака по разметке KanjiVG: традиционный, иначе общий, иначе по словарю Нельсона."""
    svg = ROOT / "data" / "kanjivg" / f"{ord(ch):05x}.svg"
    if not svg.exists():
        return ""
    found = dict((kind, el) for el, kind in re.findall(r'kvg:element="([^"]+)"[^>]*?kvg:radical="([^"]+)"', svg.read_text(encoding="utf-8")))
    return next((found[k] for k in ("tradit", "general", "nelson") if k in found), "")


def build_data():
    core = load_core()
    kanji_info = {r["kanji"]: r for r in core}
    words = [{"id": short_id(v["expr"], v["kana"]), "e": v["expr"], "k": v["kana"], "s": v["kanji"] if v["kanji"] != v["expr"] else "",
              "r": v["ru"], "l": int(v["lessons"][0]), "p": v["pos"], "t": v["type"],
              "kb": kanji_breakdown(v["expr"], kanji_info)} for v in load_vocab()]
    textbook_words = load_examples()
    kanji = []
    for row in core:
        examples, cue = kanji_examples(row, textbook_words)
        kanji.append({"c": row["kanji"], "l": row["lesson"], "m": row["meaning"], "on": row["on"], "kun": row["kun"], "rad": radical(row["kanji"]),
                      "ex": [list(e) for e in examples], "cue": list(cue)})
    sentences = [{"id": short_id(r["jp"]), "l": int(r["lesson"]), "p": r["pattern"], "j": r["jp"], "r": r["ru"],
                  "f": r["furigana"]} for r in read_tsv(ROOT / "grammar" / "sentences.tsv")]
    slots = json.loads((ROOT / "grammar" / "particle_slots.json").read_text(encoding="utf-8"))
    return {"words": words, "kanji": kanji, "strokes": stroke_data(), "sentences": sentences, "slots": slots,
            "topics": lesson_topics()}


def boot_logo():
    """Логотип МГИМО для заставки сайта (пиксельная версия, trainer/boot_logo.png)."""
    png = base64.b64encode((ROOT / "trainer" / "boot_logo.png").read_bytes()).decode()
    return f'<img class="boot-logo" src="data:image/png;base64,{png}" alt="" width="118" height="87">'


def main():
    template = (ROOT / "trainer" / "template.html").read_text(encoding="utf-8")
    data = json.dumps(build_data(), ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    page = template.replace("__DATA__", data).replace("<!--__GRAMMAR__-->", grammar_html())
    out = ROOT / "trainer" / "index.html"
    site = page.replace("<!--__BOOTLOGO__-->", boot_logo()).replace(
        "<!--__BOOTSUB__-->", '<div class="boot-sub">Неофициальный учебный тренажёр студента МГИМО</div>')
    out.write_text(SKELETON_HEAD + site + "</body></html>", encoding="utf-8")
    print(f"{out.relative_to(ROOT)}: {out.stat().st_size // 1024} КБ")
    if "--artifact" in sys.argv:
        # В артефакте на claude.ai заставки нет: без символики университета и без перекрытой миниатюры.
        start, end = page.index("<!--BOOT-->"), page.index("<!--/BOOT-->") + len("<!--/BOOT-->")
        dst = Path(sys.argv[sys.argv.index("--artifact") + 1])
        dst.write_text(page[:start] + page[end:], encoding="utf-8")
        print(f"артефакт: {dst}")


if __name__ == "__main__":
    main()
