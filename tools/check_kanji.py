"""Проверка kanji_core.txt: полнота по таблице 新出漢字表 и сверка чтений с KANJIDIC2."""
import re, sqlite3, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Таблица 新出漢字表 (стр. 391–392 учебника): урок -> знаки
TABLE = {
 3:"中上山下川",4:"人男女木",5:"一二三四五六七八九十子本",6:"花大百円小千金万水",
 7:"日月学入年生",8:"土火行見毎",9:"早今時分半校来赤先",10:"天気雨北南国同雪東空西京高町",
 11:"何文父語友工場話森外海会出食手社",12:"電近車方青止犬字切糸",13:"朝午前後少休足聞英体左右名",
 14:"数待紙書持買物色",15:"言夜知昼間読音林牛元答所帰",16:"風歩立長母兄姉弟妹走鳥",
 17:"白茶黄黒晴星光草",18:"地図引口戸店形家",19:"思考院魚医者商楽新記画市役銀員",
 20:"作台味使竹毛米薬声古多飲",21:"温夕週両親勉強田畑活仕事品船玉目正有",22:"野球曜写真絵集習漢練原遊自由",
 23:"葉調録泳動運転乗打耳安堂都",24:"番族身代選結婚顔悪歯痛計度首鼻重短冷氷",
 25:"発法最肉筆寝起横側広村病公園飛機",26:"美術館通道橋係注意路線駅酒守春冬夏秋実",
 27:"急門用荷席置暑静試験消暗交故鉄終問題",28:"室号階晩退受住丁式去卒業売洋服着",
 29:"念妻指輪案内状送助教歌",30:"次技級説明組型取証",31:"招落務死世界利心開建械辞",
 32:"旅岸費全部以貸予約寒良植育例性返伝",33:"願様私君失礼研究昨申飯輸関遠",34:"航港昭和池料理馬向",
}

def kata2hira(s):
    return "".join(chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" else c for c in s)

def load_core(path=ROOT / "data/kanji_core.txt"):
    rows, lesson = [], None
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        if line.startswith("@"):
            lesson = int(line[1:]); continue
        k, mean, on, kun, extra = (line.split("|") + [""] * 5)[:5]
        rows.append(dict(kanji=k, lesson=lesson, meaning=mean,
                         on=[x for x in on.split("、") if x], kun=[x for x in kun.split("、") if x],
                         extra=extra.strip()))
    return rows

def main():
    rows = load_core()
    table_all = "".join(TABLE.values())
    core = [r["kanji"] for r in rows]
    print("table:", len(table_all), "core:", len(core))
    dup = {k for k in core if core.count(k) > 1}
    if dup: print("DUPLICATES:", dup)
    print("missing from core:", set(table_all) - set(core))
    print("extra in core:", set(core) - set(table_all))
    for r in rows:
        if r["kanji"] not in TABLE.get(r["lesson"], "") and r["kanji"] != "母":
            print("lesson mismatch:", r["kanji"], r["lesson"])
    db = sqlite3.connect(sys.argv[1]) if len(sys.argv) > 1 else None
    if not db: return
    q = ("select r.r_type, r.value from character ch join rm_group g on g.cid=ch.ID "
         "join reading r on r.gid=g.ID where ch.literal=? and r.r_type in ('ja_on','ja_kun')")
    bad = 0
    for r in rows:
        kd = list(db.execute(q, (r["kanji"],)))
        ons = {kata2hira(v) for t, v in kd if t == "ja_on"}
        kuns = {v.replace("-", "") for t, v in kd if t == "ja_kun"}
        for o in r["on"]:
            if kata2hira(o) not in ons:
                print("ON?", r["kanji"], o, sorted(ons)); bad += 1
        for k in r["kun"]:
            if k not in kuns and k.replace(".", "") not in {x.replace(".", "") for x in kuns}:
                print("KUN?", r["kanji"], k, sorted(kuns)); bad += 1
    print("reading issues:", bad)

if __name__ == "__main__":
    main()
