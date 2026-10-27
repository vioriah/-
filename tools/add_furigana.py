"""Добавляет колонку furigana (формат Anki: 漢字[かんじ]) в grammar/sentences.tsv.

Нужно только при добавлении новых предложений. Зависимости: pip install fugashi unidic-lite
Автоматическая разметка иногда ошибается в чтениях чисел и счётных слов — для этого есть FIXES;
после запуска просмотрите новые строки глазами.
"""
import csv, re, sys
from pathlib import Path

import fugashi

ROOT = Path(__file__).resolve().parent.parent
KANJI = re.compile(r'[一-鿿々]')
FIXES = [
    ('アメリカ 人[にん]', 'アメリカ 人[じん]'), ('中国[ちゅうごく] 人[にん]', '中国[ちゅうごく] 人[じん]'),
    ('あの 方[ほう]', 'あの 方[かた]'), ('何[なん]か', '何[なに]か'), ('何[なん]も', '何[なに]も'),
    ('一[いち] 本[ぽん]', '一本[いっぽん]'), ('三[さん] 本[ぽん]', '三本[さんぼん]'),
    ('四[よん] 月[がつ]', '四月[しがつ]'), ('日曜[にちよう] 日[ひ]', '日曜日[にちようび]'),
    ('一[いち]か 月[げつ]', '一[いっ]か 月[げつ]'), ('一[いち] 週間[しゅうかん]', '一週間[いっしゅうかん]'),
    ('九[きゅう] 時[じ]', '九時[くじ]'), ('今[こん] ', '今[いま] '), ('米[べい]', '米[こめ]'),
    ('何時[いつ]', '何時[なんじ]'), ('一[いち] 階[かい]', '一階[いっかい]'), ('日本[にっぽん]', '日本[にほん]'),
]

def hira(s):
    return ''.join(chr(ord(c) - 0x60) if 'ァ' <= c <= 'ヶ' else c for c in s)

def token(surf, kana):
    if not KANJI.search(surf):
        return surf
    r = hira(kana)
    i = 0
    while i < min(len(surf), len(r)) and not KANJI.match(surf[i]) and surf[i] == r[i]:
        i += 1
    j = 0
    while j < min(len(surf), len(r)) - i and not KANJI.match(surf[-1 - j]) and surf[-1 - j] == r[-1 - j]:
        j += 1
    core, rcore, pre, suf = surf[i:len(surf) - j], r[i:len(r) - j], surf[:i], surf[len(surf) - j:]
    parts = re.findall(r'[一-鿿々]+|[^一-鿿々]+', core)
    if len(parts) > 1:
        m = re.match(''.join('(.+?)' if KANJI.match(p) else re.escape(p) for p in parts) + '$', rcore)
        if m:
            groups = iter(m.groups())
            return pre + ''.join(f' {p}[{next(groups)}]' if KANJI.match(p) else p for p in parts) + suf
    return f'{pre} {core}[{rcore}]{suf}'

def furigana(tagger, text):
    out = ''.join(token(w.surface, w.feature.kana or w.surface) for w in tagger(text)).strip()
    for a, b in FIXES:
        out = out.replace(a, b)
    return out

def main(path=ROOT / 'grammar/sentences.tsv', force=False):
    lines = path.read_text(encoding='utf-8').splitlines()
    head = [l for l in lines if l.startswith('#')]
    rows = list(csv.DictReader([l for l in lines if not l.startswith('#')], delimiter='\t'))
    tagger = fugashi.Tagger()
    for r in rows:
        if force or not r.get('furigana'):
            r['furigana'] = furigana(tagger, r['jp'])
    cols = ['lesson', 'pattern', 'jp', 'ru', 'furigana']
    with path.open('w', encoding='utf-8', newline='') as f:
        f.write('\n'.join(head) + '\n')
        w = csv.DictWriter(f, cols, delimiter='\t', lineterminator='\n', extrasaction='ignore')
        w.writeheader()
        w.writerows(rows)
    print(len(rows), 'rows')

if __name__ == '__main__':
    main(force='--force' in sys.argv)
