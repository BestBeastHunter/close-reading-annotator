# -*- coding: utf-8 -*-
"""
scripts/build_dlut_subset.py — DLUT《情感词汇本体》清洗子集生成器（v3.3.0 / ADR-013 / T-032-L1）

功能：
  从本地全量 xlsx（27,466 词）按文学精读适配规则清洗，输出 references/lexicon-dlut-subset.json。
  子集是 lexicon_crosscheck.py 的默认数据源（--subset）——其他用户无需本地全量即可跑词表演化工具。

清洗规则（对齐 D19 词级形态）：
  1. 词性过滤：保留 adj/verb/noun/adv；排除 idiom（14,986 词，成语/熟语，非词级情感；其中 2 字词仅 6 个，无损）、prep/nw
  2. 词长过滤：≤2 字（D19 50 词均为 1-2 字形态；3+ 字基本是成语/专名/熟语）
  3. 义项合并：同词多义项 → cls 列表去重 + aux 合并 + intensity 取 max + polarity 取多数派（平票取第一条）

输出 JSON schema：
  meta: {name, source, source_url, version, license, citation, filter_rules, generated_by, generated_at, count}
  class_codes: {代码: {major: 大类, name: 小类名, base_word: 归约基元建议}}
  words: [{w, pos, cls:[...], int, pol, aux:[...]}, ...]

许可（DLUT 官方）：仅供科研及教学使用；未经允许不得用于商业用途；使用需引用论文。
本子集仅作词表演化参考数据源，不参与批注主链路（D19 50 词表仍是 validate 唯一枚举真源）。

输入/输出：
  输入：--dlut <xlsx>（默认 ../../../datasets/情感词汇本体/情感词汇本体.xlsx，仅本地存在时）
  输出：--out <json>（默认 ../references/lexicon-dlut-subset.json）

依赖：Python 3.10+，纯 stdlib（zipfile/xml.etree.ElementTree/json/argparse）。
版本：v1.0（T-032-L1，ADR-013）。
"""

from __future__ import annotations

import argparse
import json
import sys
import zipfile
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

# ---------------------------------------------------------------------------
# DLUT 21 小类 → 大类 / 名称 / 归约基元建议
# 文献标准（《情感词汇本体的构造》，情报学报 2008）：
#   乐=快乐PA/安心PE；好=尊敬PD/赞扬PH/相信PG/喜爱PB/祝愿PK；怒=愤怒NA；
#   哀=悲伤NB/失望NJ/内疚NH/思念PF；惧=慌NI/恐惧NC/羞NG；
#   恶=烦闷NE/憎恶ND/妒忌NK/怀疑NL/贬责NM；惊=惊奇PC
# 实证注记（2026-09-05，对照官方 xlsx 词频）：数据中"贬责"代码为 NN（7583 词），NM 出现 0 次——NN/NM 同义双认。
# 基元建议 = 该小类候选词归约到 D19 基础层/扩展层时的首选词位（与 lexicon_crosscheck.SUB_TO_SUGGEST 一致）。
# ---------------------------------------------------------------------------
CLASS_CODES: dict[str, dict] = {
    "PA": {"major": "乐", "name": "快乐", "base_word": "喜悦"},
    "PE": {"major": "乐", "name": "安心", "base_word": "安宁"},
    "PD": {"major": "好", "name": "尊敬", "base_word": "崇敬"},
    "PH": {"major": "好", "name": "赞扬", "base_word": "崇敬"},  # 评价类词，入 D19 需审
    "PG": {"major": "好", "name": "相信", "base_word": "信任"},
    "PB": {"major": "好", "name": "喜爱", "base_word": "喜悦"},
    "PK": {"major": "好", "name": "祝愿", "base_word": "期待"},
    "NA": {"major": "怒", "name": "愤怒", "base_word": "愤怒"},
    "NB": {"major": "哀", "name": "悲伤", "base_word": "悲伤"},
    "NJ": {"major": "哀", "name": "失望", "base_word": "绝望"},
    "NH": {"major": "哀", "name": "内疚", "base_word": "羞耻"},
    "PF": {"major": "哀", "name": "思念", "base_word": "眷恋"},
    "NI": {"major": "惧", "name": "慌", "base_word": "恐慌"},
    "NC": {"major": "惧", "name": "恐惧", "base_word": "恐惧"},
    "NG": {"major": "惧", "name": "羞", "base_word": "羞耻"},
    "NE": {"major": "恶", "name": "烦闷", "base_word": "厌倦"},
    "ND": {"major": "恶", "name": "憎恶", "base_word": "厌恶"},
    "NK": {"major": "恶", "name": "妒忌", "base_word": "嫉妒"},
    "NL": {"major": "恶", "name": "怀疑", "base_word": "疏离"},  # 建议词位=疏离，入表需审
    "NM": {"major": "恶", "name": "贬责", "base_word": "鄙夷"},  # 文献代码（数据中 0 词）
    "NN": {"major": "恶", "name": "贬责", "base_word": "鄙夷"},  # 数据版代码（7583 词）
    "PC": {"major": "惊", "name": "惊奇", "base_word": "惊讶"},
}

KEEP_POS = {"adj", "verb", "noun", "adv"}


# ---------------------------------------------------------------------------
# xlsx 解析（纯 stdlib，与 lexicon_crosscheck.py 同源实现）
# ---------------------------------------------------------------------------
def read_shared_strings(zf: zipfile.ZipFile) -> list[str]:
    try:
        xml_bytes = zf.read("xl/sharedStrings.xml")
    except KeyError:
        return []
    root = ET.fromstring(xml_bytes)
    out: list[str] = []
    for si in root.iter("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}si"):
        parts = []
        for t in si.iter("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t"):
            parts.append(t.text or "")
        out.append("".join(parts))
    return out


def read_sheet_rows(zf: zipfile.ZipFile, shared: list[str]) -> list[list[str]]:
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    root = ET.fromstring(zf.read("xl/worksheets/sheet1.xml"))
    rows: list[list[str]] = []
    for row in root.iter("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}row"):
        cells: list[str] = []
        for c in row.iter("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}c"):
            t = c.get("t")
            v = c.find("m:v", ns)
            val = ""
            if v is not None and v.text is not None:
                if t == "s":
                    idx = int(v.text)
                    val = shared[idx] if idx < len(shared) else ""
                else:
                    val = v.text
            cells.append(val)
        rows.append(cells)
    return rows


def load_dlut(path: Path) -> list[dict]:
    """解析 xlsx → 原始词条（word/pos/emotion/intensity/polarity/aux）。"""
    with zipfile.ZipFile(path) as zf:
        shared = read_shared_strings(zf)
        rows = read_sheet_rows(zf, shared)
    records: list[dict] = []
    for r in rows[1:]:
        if len(r) < 6:  # 主列必需：词/词性/情感分类/强度/极性；aux 为空单元格时无 <c> 元素，安全取值
            continue
        word = (r[0] or "").strip()
        pos = (r[1] or "").strip()
        emotion = (r[4] or "").strip().upper()
        if not word or not emotion:
            continue
        def _num(s, d=0):
            try:
                return int(float(s)) if s else d
            except (ValueError, TypeError):
                return d
        aux = (r[7] or "").strip().upper() if len(r) > 7 else ""
        records.append({
            "word": word, "pos": pos, "emotion": emotion,
            "intensity": _num(r[5]), "polarity": _num(r[6]),
            "aux": [aux] if aux else [],
        })
    return records


def build_subset(records: list[dict]) -> list[dict]:
    """清洗 + 义项合并。"""
    merged: dict[str, dict] = {}
    order: list[str] = []
    for rec in records:
        if rec["pos"] not in KEEP_POS:
            continue
        if len(rec["word"]) > 2:
            continue
        w = rec["word"]
        if w not in merged:
            merged[w] = {"w": w, "pos": rec["pos"], "cls": [], "int": 0,
                         "pol": [], "aux": []}
            order.append(w)
        m = merged[w]
        if rec["emotion"] not in m["cls"]:
            m["cls"].append(rec["emotion"])
        for a in rec["aux"]:
            if a and a not in m["aux"]:
                m["aux"].append(a)
        m["int"] = max(m["int"], rec["intensity"])
        m["pol"].append(rec["polarity"])
    # 极性取多数派（平票取第一个）
    for w in order:
        m = merged[w]
        cnt = Counter(m["pol"])
        m["pol"] = max(cnt, key=lambda p: (cnt[p], -m["pol"].index(p)))
        m["cls"].sort()
        m["aux"].sort()
    return [merged[w] for w in order]


def main() -> int:
    ap = argparse.ArgumentParser(description="DLUT 情感词汇本体清洗子集生成器")
    ap.add_argument("--dlut", default=None, help="DLUT xlsx 路径（默认 ../../../datasets/情感词汇本体/情感词汇本体.xlsx）")
    ap.add_argument("--out", default=None, help="输出 JSON 路径（默认 ../references/lexicon-dlut-subset.json）")
    args = ap.parse_args()

    dlut = Path(args.dlut) if args.dlut else Path(__file__).resolve().parents[3] / "datasets" / "情感词汇本体" / "情感词汇本体.xlsx"
    out = Path(args.out) if args.out else Path(__file__).resolve().parents[1] / "references" / "lexicon-dlut-subset.json"

    if not dlut.exists():
        print(f"[ERROR] DLUT 全量文件不存在：{dlut}\n"
              f"        本脚本需要本地全量 xlsx（官方下载：https://ir.dlut.edu.cn/info/1013/1142.htm）。\n"
              f"        一般使用者无需运行本脚本——仓库已附带清洗子集 lexicon-dlut-subset.json。")
        return 2

    records = load_dlut(dlut)
    total = len(records)
    words = build_subset(records)
    # 子集内代码核验：不应出现 CLASS_CODES 之外的新代码
    unknown = sorted({c for w in words for c in w["cls"]} - set(CLASS_CODES))
    if unknown:
        print(f"[WARN] 子集内出现未登记代码：{unknown}（请补 CLASS_CODES）")

    payload = {
        "meta": {
            "name": "DLUT emotion lexicon subset (literary-annotation adapted)",
            "source": "大连理工大学《情感词汇本体》",
            "source_url": "https://ir.dlut.edu.cn/info/1013/1142.htm",
            "version": "subset-v1.0 (base: DLUT 2020)",
            "license": "仅供科研及教学使用；未经允许不得用于商业用途；使用需引用论文。",
            "citation": "徐琳宏, 林鸿飞, 潘宇, 任惠, 陈建美. 情感词汇本体的构造. 情报学报, 2008, 27(2): 180-185.",
            "filter_rules": "词性∈{adj,verb,noun,adv} 且 词长≤2；排除 idiom(14986)/prep/nw；同词多义项合并(cls去重, int取max, pol取多数派)",
            "generated_by": "scripts/build_dlut_subset.py",
            "generated_at": "2026-09-05",
            "source_total_entries": total,
            "count": len(words),
        },
        "class_codes": CLASS_CODES,
        "words": words,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    print(f"[OK] 子集已生成：{out}")
    print(f"  全量 {total} 条 → 子集 {len(words)} 词（清洗率 {len(words)/total*100:.1f}%）")
    from collections import Counter as _C
    pos_c = _C(w["pos"] for w in words)
    print(f"  词性分布：{dict(pos_c)}")
    print(f"  class_codes：{len(CLASS_CODES)} 个；未知代码 {unknown or '无'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
