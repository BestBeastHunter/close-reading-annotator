# -*- coding: utf-8 -*-
"""
scripts/lexicon_crosscheck.py — 外部情感词库对照器（DLUT / NRC ↔ D19 词表）

功能：
  1. 解析 DLUT《情感词汇本体》xlsx（纯 stdlib：zipfile + ElementTree，零第三方依赖）
  2. 解析 NRC EmoLex 中文版（Chinese-Simplified，11 列 tab 分隔）
  3. 对照 D19 词表（references/emotion-lexicon.md）：
     a. D19 50 词在 DLUT 的词级命中率
     b. DLUT 7 大类 21 小类 → D19 覆盖缺口（哪些小类 D19 一个词都没有）
     c. 候选词清单：DLUT 中强度高、D19 缺、且情感分类可归约到 D19 基元者
     d. NRC 中文版抽样质量抽查（机翻质量评估，供是否可信参考）
  4. 输出 Markdown 报告（--out），摘要打印到 stdout

输入/输出：
  输入：--subset <json>（默认 ../references/lexicon-dlut-subset.json，仓库内清洗子集，**优先使用**）
        --dlut <xlsx>（默认 ../../../datasets/情感词汇本体/情感词汇本体.xlsx，子集缺失时回退全量）
        --nrc  <中文版 txt>（默认 ../../../datasets/NRC-Emotion-Lexicon/OneFilePerLanguage/Chinese-Simplified-NRC-EmoLex.txt，缺失时跳过抽样）
        --d19  <emotion-lexicon.md>（默认 ../references/emotion-lexicon.md）
  输出：--out <report.md>；stdout 摘要

依赖：
  Python 3.10+，纯 stdlib（zipfile/xml.etree.ElementTree/re/argparse）。
  v3.3.0（T-032-L3，ADR-013）：默认读仓库内 DLUT 清洗子集（一般使用者无需外部数据）；
  NRC 文件缺失时抽样自动跳过（NRC 中文版仅体系参照，见 ADR-012/013）。

版本：
  v3.3.0（T-031-① + T-032-L3，ADR-012/ADR-013）。配套词表演化协议见 references/emotion-lexicon.md §四、
  三级映射表见 references/emotion-taxonomy.md。
"""

from __future__ import annotations

import argparse
import io
import json
import re
import sys
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

# ---------------------------------------------------------------------------
# DLUT 7 大类 21 小类代码映射
# 文献代码（《情感词汇本体的构造》论文 20 小类 + 后续扩展 21 小类）：
#   乐=PA/PE；好=PD/PH/PG/PB/PK；怒=NA；哀=NB/NJ/NH/PF；惧=NC/NI；
#   恶=NE/NG/ND/NK/NL/NM(贬责)；惊=PC
# 实证修正（2026-09-05，对照官方 xlsx 词频统计）：
#   数据中"贬责"类代码为 **NN**（7583 词，例：脏乱→NN 强度7 极性2），NM 出现 0 次。
#   判定 NN=贬责（数据版代码），NM 为文献常见代号，两者同义，映射表同时认。
# ---------------------------------------------------------------------------
DLUT_CLASSES: dict[str, tuple[list[str], str | None]] = {
    "乐": (["PA", "PE"], "喜悦"),        # PA 快乐 / PE 安心
    "好": (["PD", "PH", "PG", "PB", "PK"], None),  # 尊敬/赞扬/相信/喜爱/祝愿 → 依词定
    "怒": (["NA"], "愤怒"),
    "哀": (["NB", "NJ", "NH", "PF"], "悲伤"),  # 悲伤/失望/内疚/思念
    "惧": (["NC", "NI"], "恐惧"),        # 恐惧/慌
    "恶": (["NE", "NG", "ND", "NK", "NL", "NM", "NN"], None),  # 烦闷/羞/憎恶/妒忌/怀疑/贬责
    "惊": (["PC"], "惊讶"),
}
# 小类 → 大类 反查
SUB_TO_MAJOR: dict[str, str] = {}
for _major, (_subs, _base) in DLUT_CLASSES.items():
    for _s in _subs:
        SUB_TO_MAJOR[_s] = _major

# 大类 → D19 基元词的映射（用于候选词"可归约"判定与建议词位）
MAJOR_TO_BASE_WORD: dict[str, str] = {
    "乐": "喜悦",
    "好": "信任",      # 好类含 PG 相信；具体词归约时按小类再细调（PB喜爱→喜悦、PK祝愿→期待）
    "怒": "愤怒",
    "哀": "悲伤",
    "惧": "恐惧",
    "恶": "厌恶",
    "惊": "惊讶",
}
# 小类 → 建议 D19 词位（比大类映射更精确，用于候选清单的建议列）
SUB_TO_SUGGEST: dict[str, str] = {
    "PA": "喜悦", "PE": "安宁", "PD": "崇敬", "PH": "崇敬", "PG": "信任",
    "PB": "喜悦", "PK": "期待", "NA": "愤怒", "NB": "悲伤", "NJ": "绝望",
    "NH": "羞耻", "PF": "眷恋", "NC": "恐惧", "NI": "恐慌", "NE": "厌倦",
    "NG": "羞耻", "ND": "厌恶", "NK": "嫉妒", "NL": "疏离", "NM": "鄙夷",
    "NN": "鄙夷",  # 数据版"贬责"代码
    "PC": "惊讶",
}

# NRC 8 基元 + 2 极性 的列索引（Chinese-Simplified 11 列）
NRC_COLS = ["anger", "anticipation", "disgust", "fear", "joy",
            "negative", "positive", "sadness", "surprise", "trust"]


# ---------------------------------------------------------------------------
# xlsx 解析（纯 stdlib）
# ---------------------------------------------------------------------------
def read_shared_strings(zf: zipfile.ZipFile) -> list[str]:
    """读取 xl/sharedStrings.xml，返回字符串表。"""
    try:
        xml_bytes = zf.read("xl/sharedStrings.xml")
    except KeyError:
        return []
    root = ET.fromstring(xml_bytes)
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    out: list[str] = []
    for si in root.findall("m:si", ns):
        # 拼接所有 <t> 文本（处理富文本分段）
        parts = []
        for t in si.iter("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t"):
            parts.append(t.text or "")
        out.append("".join(parts))
    return out


def read_sheet_rows(zf: zipfile.ZipFile, shared: list[str], sheet_path: str = "xl/worksheets/sheet1.xml") -> list[list[str]]:
    """读取工作表为二维字符串表（仅解析 inline/shared 字符串与数值）。"""
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    root = ET.fromstring(zf.read(sheet_path))
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
    """解析 DLUT xlsx → [{word, pos, emotion, intensity, polarity}]（跳过表头与空行）。"""
    with zipfile.ZipFile(path) as zf:
        shared = read_shared_strings(zf)
        rows = read_sheet_rows(zf, shared)
    records: list[dict] = []
    for r in rows[1:]:  # 跳过表头
        if len(r) < 7:
            continue
        word = (r[0] or "").strip()
        if not word:
            continue
        emotion = (r[4] or "").strip().upper()
        if not emotion:
            continue
        try:
            intensity = int(float(r[5])) if r[5] else 0
            polarity = int(float(r[6])) if r[6] else 0
        except (ValueError, TypeError):
            intensity, polarity = 0, 0
        records.append({
            "word": word, "pos": (r[1] or "").strip(), "emotion": emotion,
            "intensity": intensity, "polarity": polarity,
        })
    return records


def load_nrc_cn(path: Path) -> list[dict]:
    """解析 NRC 中文版 → [{en, zh, flags}]，flags 为 8 基元+2 极性 的 0/1 字典。"""
    records: list[dict] = []
    with io.open(path, encoding="utf-8") as f:
        for i, line in enumerate(f):
            if i == 0 and line.startswith("English"):
                continue
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 12:
                continue
            en, zh = parts[0].strip(), parts[-1].strip()
            if not en or not zh:
                continue
            flags = {k: parts[1 + idx].strip() == "1" for idx, k in enumerate(NRC_COLS)}
            records.append({"en": en, "zh": zh, "flags": flags})
    return records


# ---------------------------------------------------------------------------
# 子集加载（v3.3.0：仓库内清洗子集为默认数据源）
# ---------------------------------------------------------------------------
def load_subset(path: Path) -> tuple[list[dict], dict]:
    """读 lexicon-dlut-subset.json → records（cls 展开为 emotion）+ meta。"""
    data = json.loads(io.open(path, encoding="utf-8").read())
    records: list[dict] = []
    for w in data.get("words", []):
        for c in w.get("cls", []):
            records.append({
                "word": w["w"], "pos": w.get("pos", ""), "emotion": c,
                "intensity": w.get("int", 0), "polarity": w.get("pol", 0),
            })
    return records, data.get("meta", {})


# ---------------------------------------------------------------------------
# D19 词表解析
# ---------------------------------------------------------------------------
def load_d19(path: Path) -> list[str]:
    """从 emotion-lexicon.md 词表全量表解析 D19 枚举词（去重、保序）。"""
    words: list[str] = []
    seen: set[str] = set()
    with io.open(path, encoding="utf-8") as f:
        lines = f.readlines()
    in_table = False
    for ln in lines:
        s = ln.strip()
        if s.startswith("## 二、词表全量"):
            in_table = True
            continue
        if in_table:
            # 表格结束：下一个 ## 标题
            if s.startswith("##") and "词表全量" not in s:
                break
            if s.startswith("| **") and "|" in s[3:]:
                word = s.split("|")[1].strip().strip("**").strip()
                if word and word not in seen:
                    seen.add(word)
                    words.append(word)
    return words


# ---------------------------------------------------------------------------
# 归一化
# ---------------------------------------------------------------------------
def norm_word(w: str) -> str:
    """词形归一化：去空白、括号注、书名号等修饰。"""
    w = re.sub(r"[（(].*?[)）]", "", w)
    w = re.sub(r"[《》「」『』\"“”'‘’·]", "", w)
    return w.strip()


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description="DLUT/NRC 词库 ↔ D19 词表对照器（纯 stdlib）")
    root = Path(__file__).resolve().parents[3]  # 工作区根（scripts → close-reading-annotator → skills → 工作区）
    ap.add_argument("--dlut", type=Path, default=root / "datasets" / "情感词汇本体" / "情感词汇本体.xlsx",
                    help="DLUT xlsx 路径（默认工作区 datasets；仅子集缺失时回退使用）")
    ap.add_argument("--subset", type=Path,
                    default=Path(__file__).resolve().parent.parent / "references" / "lexicon-dlut-subset.json",
                    help="DLUT 清洗子集 JSON 路径（默认 ../references/lexicon-dlut-subset.json，优先使用）")
    ap.add_argument("--nrc", type=Path,
                    default=root / "datasets" / "NRC-Emotion-Lexicon" / "OneFilePerLanguage" / "Chinese-Simplified-NRC-EmoLex.txt",
                    help="NRC 中文版 txt 路径")
    ap.add_argument("--d19", type=Path, default=Path(__file__).resolve().parent.parent / "references" / "emotion-lexicon.md",
                    help="D19 词表真源 md 路径")
    ap.add_argument("--out", type=Path, default=None, help="输出报告 md 路径（默认 stdout 同目录）")
    ap.add_argument("--candidates", type=int, default=30, help="候选词清单条数上限")
    ap.add_argument("--max-len", type=int, default=2, help="候选词最大字数（默认 2，对齐 D19 形态）")
    ap.add_argument("--nrc-sample", type=int, default=40, help="NRC 中文版抽样条数")
    ap.add_argument("--seed", type=int, default=42, help="抽样随机种子（确定性）")
    args = ap.parse_args()

    missing = [p for p in (args.d19,) if not Path(p).exists()]
    if missing:
        print(f"[ERROR] 文件不存在: {[str(m) for m in missing]}", file=sys.stderr)
        return 2

    d19_words = load_d19(args.d19)

    # ---- DLUT 数据源：子集优先，回退全量 ----
    dlut: list[dict] = []
    data_mode = "none"
    dlut_label = "未提供"
    if Path(args.subset).exists():
        dlut, subset_meta = load_subset(args.subset)
        data_mode = "subset"
        dlut_label = f"lexicon-dlut-subset.json（{len(dlut):,} 词，仓库内）"
    elif Path(args.dlut).exists():
        dlut = load_dlut(args.dlut)
        data_mode = "full"
        dlut_label = f"{args.dlut.name}（{len(dlut):,} 词，本地全量）"
    else:
        print(f"[WARN] DLUT 子集与全量均不存在——覆盖度/候选词部分跳过。子集:{args.subset} 全量:{args.dlut}", file=sys.stderr)

    # ---- NRC：缺失降级为跳过抽样 ----
    nrc: list[dict] = []
    nrc_label = "未提供"
    if Path(args.nrc).exists():
        nrc = load_nrc_cn(args.nrc)
        nrc_label = f"{args.nrc.name}（{len(nrc):,} 词，本地）"

    # ---- 1) D19 命中率 ----
    dlut_words = {norm_word(r["word"]) for r in dlut}
    hit = [w for w in d19_words if norm_word(w) in dlut_words]
    miss = [w for w in d19_words if norm_word(w) not in dlut_words]

    # ---- 2) DLUT 小类 → D19 覆盖缺口 ----
    d19_norm = {norm_word(w) for w in d19_words}
    sub_count: dict[str, int] = {}
    sub_d19_hit: dict[str, set[str]] = {}
    for r in dlut:
        s = r["emotion"]
        if s not in SUB_TO_MAJOR:
            continue
        sub_count[s] = sub_count.get(s, 0) + 1
        sub_d19_hit.setdefault(s, set())
        if norm_word(r["word"]) in d19_norm:
            sub_d19_hit[s].add(norm_word(r["word"]))

    # ---- 3) 候选词清单 ----
    # 过滤规则：DLUT 词面未命中 D19、强度≥5、极性非中性、词长 1-2 字（对齐 D19 词表形态，
    # 过滤 DLUT 中大量 4 字成语/俗语噪声——如 PH 赞扬类 8591 词中多数为成语）。
    max_len = max(2, args.max_len)
    candidates: list[dict] = []
    seen_cand: set[str] = set()
    for r in dlut:
        s = r["emotion"]
        if s not in SUB_TO_MAJOR:
            continue
        w = norm_word(r["word"])
        if not w or len(w) > max_len or w in d19_norm or w in seen_cand:
            continue
        if r["intensity"] < 5 or r["polarity"] == 0:
            continue
        seen_cand.add(w)
        major = SUB_TO_MAJOR[s]
        suggest = SUB_TO_SUGGEST.get(s, MAJOR_TO_BASE_WORD.get(major, "?"))
        candidates.append({
            "word": w, "sub": s, "major": major,
            "intensity": r["intensity"], "polarity": r["polarity"],
            "suggest": suggest,
        })
    # 按强度降序 → 按小类平衡（每小类最多 quota 个）→ 词序确定性
    candidates.sort(key=lambda x: (-x["intensity"], x["word"]))
    quota = max(1, args.candidates // max(1, len({c["sub"] for c in candidates})))
    per_sub: dict[str, int] = {}
    balanced: list[dict] = []
    for c in candidates:
        if per_sub.get(c["sub"], 0) >= quota:
            continue
        per_sub[c["sub"]] = per_sub.get(c["sub"], 0) + 1
        balanced.append(c)
        if len(balanced) >= args.candidates:
            break
    candidates = balanced

    # ---- 4) NRC 中文版抽样 ----
    import random
    rng = random.Random(args.seed)
    sample = rng.sample(nrc, min(args.nrc_sample, len(nrc))) if nrc else []

    # ---- 报告 ----
    lines: list[str] = []
    lines.append("# 外部词库 ↔ D19 词表对照报告（v3.3.0 / T-032-L3 / ADR-013）\n")
    lines.append(f"- DLUT 数据源：{dlut_label}（模式={data_mode}）｜NRC 中文版：{nrc_label}｜D19 词表 {len(d19_words)} 词")
    if data_mode == "subset":
        lines.append(f"- 子集来源：{subset_meta.get('source', '')}（{subset_meta.get('citation', '')}）。子集仅作词表演化参考数据源，D19 50 词表仍为 validate 唯一真源。")
    else:
        lines.append("- 说明：全量数据文件仅本地使用、不进 git；DLUT 分类代码按 7 大类 21 小类标准映射（见 references/emotion-taxonomy.md）。\n")
    lines.append("## 一、D19 词级命中率（词面精确匹配）\n")
    lines.append(f"| 指标 | 值 |")
    lines.append(f"|------|----|")
    lines.append(f"| D19 词数 | {len(d19_words)} |")
    lines.append(f"| DLUT 命中 | {len(hit)}（{len(hit)/max(len(d19_words),1)*100:.1f}%） |")
    lines.append(f"| DLUT 未命中 | {len(miss)}（{', '.join(miss) if miss else '无'}） |")
    lines.append("")
    lines.append("> 未命中多为复合词/姿态词/文学专名（如 悲欣交集、冷峻中的悲悯），词面不匹配属预期；DLUT 以单字词/双字词为主。\n")
    lines.append("## 二、DLUT 21 小类 → D19 覆盖缺口\n")
    lines.append("| 大类 | 小类 | DLUT 词数 | D19 命中词数 | 覆盖状态 |")
    lines.append("|------|------|-----------|-------------|----------|")
    gap_subs: list[str] = []
    for major, (subs, _) in DLUT_CLASSES.items():
        for s in subs:
            total = sub_count.get(s, 0)
            hits = len(sub_d19_hit.get(s, set()))
            if s == "NM":
                status = "数据版代码为 NN"
            elif hits > 0:
                status = "覆盖"
            else:
                status = "**缺口**"
            if hits == 0 and s != "NM":
                gap_subs.append(s)
            lines.append(f"| {major} | {s} | {total} | {hits} | {status} |")
    lines.append("")
    if gap_subs:
        lines.append(f"> **真实缺口小类**：{', '.join(gap_subs)}（D19 无任何词面命中；NM 为文献代码，数据版对应 NN 已覆盖）。这些类别是词表演化时优先关注的方向。\n")
    lines.append("## 三、候选词清单（DLUT 高频、D19 缺、可归约到基元，按小类平衡）\n")
    lines.append("| 候选词 | DLUT 小类 | 大类 | 强度 | 极性 | 建议 D19 词位 | 备注 |")
    lines.append("|--------|-----------|------|------|------|---------------|------|")
    eval_subs = {"PH", "NN"}  # DLUT 语义偏"评价"而非"情感"的小类，需标注谨慎
    for c in candidates:
        note = "评价类词，入表需审" if c["sub"] in eval_subs else ""
        lines.append(f"| {c['word']} | {c['sub']} | {c['major']} | {c['intensity']} | {c['polarity']} | {c['suggest']} | {note} |")
    lines.append("")
    lines.append("> 候选词须经「词表演化协议」（emotion-lexicon.md §四：产物中同一语义 ≥3 次）核验后才可入表；本清单仅为数据侧候选。\n")
    lines.append("## 四、NRC 中文版抽样质量抽查\n")
    lines.append(f"| 英文 | 中文翻译 | 情感标记（ang/ant/dis/fea/joy/neg/pos/sad/sur/tru） | 抽查意见 |")
    lines.append("|------|----------|--------------------------------------------------|----------|")
    zh_quality = 0
    for r in sample:
        flags = "".join("1" if r["flags"][k] else "0" for k in NRC_COLS)
        lines.append(f"| {r['en']} | {r['zh']} | {flags} | 待人工核 |")
    lines.append("")
    lines.append(f"> 抽样 {len(sample)} 条（seed={args.seed}）。NRC 40 语言版为机器翻译，中文版质量需人工抽查后决定是否作为候选数据源。")

    report = "\n".join(lines) + "\n"
    if args.out:
        io.open(args.out, "w", encoding="utf-8", newline="").write(report)
        print(f"[OK] 报告已写入 {args.out}")
    else:
        print(report)

    print(f"[SUMMARY] D19={len(d19_words)} 命中={len(hit)}({len(hit)/max(len(d19_words),1)*100:.1f}%) 缺口小类={len(gap_subs)} 候选={len(candidates)} NRC抽样={len(sample)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
