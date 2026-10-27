"""Собирает тренажёр trainer/index.html из шаблона trainer/template.html и данных курса.

Запуск:  python tools/build_trainer.py [--artifact путь]
Нужен pandoc (для карты грамматики). Флаг --artifact дополнительно пишет версию
без <!doctype>/<head> — в таком виде страница публикуется как артефакт claude.ai.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

from build_anki import ROOT, kanji_breakdown, load_core, load_vocab, read_tsv

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


def build_data():
    kanji_info = {r["kanji"]: r for r in load_core()}
    words = [{"e": v["expr"], "k": v["kana"], "r": v["ru"], "l": int(v["lessons"][0]), "p": v["pos"],
              "t": v["type"], "kb": kanji_breakdown(v["expr"], kanji_info)} for v in load_vocab()]
    sentences = [{"l": int(r["lesson"]), "p": r["pattern"], "j": r["jp"], "r": r["ru"], "f": r["furigana"]}
                 for r in read_tsv(ROOT / "grammar" / "sentences.tsv")]
    slots = json.loads((ROOT / "grammar" / "particle_slots.json").read_text(encoding="utf-8"))
    return {"words": words, "sentences": sentences, "slots": slots, "topics": lesson_topics()}


def main():
    template = (ROOT / "trainer" / "template.html").read_text(encoding="utf-8")
    data = json.dumps(build_data(), ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    page = template.replace("__DATA__", data).replace("<!--__GRAMMAR__-->", grammar_html())
    out = ROOT / "trainer" / "index.html"
    out.write_text(SKELETON_HEAD + page + "</body></html>", encoding="utf-8")
    print(f"{out.relative_to(ROOT)}: {out.stat().st_size // 1024} КБ")
    if "--artifact" in sys.argv:
        dst = Path(sys.argv[sys.argv.index("--artifact") + 1])
        dst.write_text(page, encoding="utf-8")
        print(f"артефакт: {dst}")


if __name__ == "__main__":
    main()
