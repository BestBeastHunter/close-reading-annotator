#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/quant_analyzer.py — 计算文学分析模块（v3.4.0 / T-033-L2 / ADR-014）

逐 segment 计算量化文学指标，作为 LLM 精读批注的"硬证据"。
纯 stdlib 优先；jieba 为可选依赖，缺失时自动降级为 DLUT 子集最大正向匹配。

输入：精读批注 Skill 产出的 {doc_id}_segments.jsonl（含 segment_id + text_span.text）
输出：{doc_id}_quant_metrics.jsonl（逐 segment 对齐，segment_id + metrics）

指标：
  - char_count / word_count / sentence_count / avg_sentence_length
  - type_token_ratio (TTR)
  - verb_ratio / adj_ratio / noun_ratio（jieba.posseg 或 DLUT 子集降级）
  - dialogue_ratio（引号内字符占比）
  - punctuation_density
  - emotion_scores（positive / negative / anxiety，基于 DLUT 子集匹配）
  - sense_ratios（视觉 / 听觉 / 触觉 / 嗅觉 / 味觉，内置五感词表）

用法：
  python scripts/quant_analyzer.py --segments outputs/.../moon_segments.jsonl
  python scripts/quant_analyzer.py --segments ... --out ... --dlut-subset references/lexicon-dlut-subset.json
"""

from __future__ import annotations

import argparse
import io
import json
import re
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

SCHEMA_VERSION = "3.4.0"

SENTENCE_END_RE = re.compile(r"[。！？；…!?;]+")
_PUNCT_CHARS = "，。！？；：、" + '"' + "'" + "「」『』（）《》【】—…·,.!?;:()[]{}-"
PUNCTUATION_RE = re.compile("[" + re.escape(_PUNCT_CHARS) + "]")
DIALOGUE_RE = re.compile(r'[「『"“‘].*?[」』"”’]', re.DOTALL)

SENSE_LEXICON = {
    "visual": ["看", "望", "瞧", "盯", "瞥", "瞪", "瞄", "注视", "凝视", "环视", "俯视", "仰视",
               "瞥见", "看清", "看见", "看到", "目光", "眼神", "眼睛", "眼", "视线", "颜色", "色彩",
               "光", "亮", "暗", "黑", "白", "红", "绿", "蓝", "黄", "灰", "金", "银", "紫", "橙",
               "影", "影子", "阴影", "光辉", "光芒", "闪烁", "闪耀", "耀眼", "刺眼", "模糊", "清晰"],
    "auditory": ["听", "闻", "声响", "声音", "声", "响", "叫", "喊", "吼", "啸", "鸣", "啼",
                 "嚎", "哭", "笑", "叹", "哼", "呢喃", "低语", "耳语", "沉默", "寂静", "安静",
                 "嘈杂", "喧闹", "喧哗", "震耳", "刺耳", "悦耳", "动听", "旋律", "节奏", "音调",
                 "音色", "音量", "回声", "回音", "余音", "钟声", "鼓声", "琴声", "风声", "雨声",
                 "雷声", "水声", "脚步声", "敲门声", "门响"],
    "tactile": ["摸", "触", "碰", "揉", "捏", "抓", "握", "拍", "打", "抚摸", "触摸", "触感",
                "粗糙", "光滑", "柔软", "坚硬", "冰冷", "冰凉", "温暖", "温热", "烫", "凉", "冷",
                "热", "暖", "刺痛", "疼痛", "痛", "痒", "麻", "酸", "胀", "沉重", "轻盈", "软",
                "硬", "湿", "干", "黏", "滑", "涩", "紧绷", "松弛"],
    "olfactory": ["闻", "嗅", "气味", "味道", "香", "臭", "芬芳", "芳香", "清香", "幽香", "醇香",
                  "腥", "膻", "腐", "霉", "酸臭", "刺鼻", "浓郁", "淡雅", "香气", "臭味", "气息",
                  "香味", "异味", "花香", "果香", "酒香", "茶香", "药香", "泥土气息", "海风气息"],
    "gustatory": ["尝", "吃", "喝", "咽", "嚼", "咬", "舔", "吞", "味道", "滋味", "口感", "酸",
                  "甜", "苦", "辣", "咸", "涩", "鲜", "淡", "浓", "美味", "难吃", "甘甜", "苦涩",
                  "辛辣", "酸甜", "咸鲜", "清淡", "油腻", "清爽", "醇厚", "干涩", "润滑", "酥脆",
                  "软糯", "嚼劲", "回味", "余味"],
}

_HAS_JIEBA = False
try:
    import jieba
    import jieba.posseg as pseg
    _HAS_JIEBA = True
except ImportError:
    pass

_CJK_CHAR_RE = re.compile(r"[\u4e00-\u9fff]")
_ALNUM_RUN_RE = re.compile(r"[a-zA-Z0-9]+")


def load_dlut_subset(path: Path) -> dict[str, dict]:
    """加载 DLUT 清洗子集，返回 {word: {cls, int, pol, pos}}。"""
    if not path.exists():
        return {}
    data = json.loads(io.open(path, encoding="utf-8").read())
    result: dict[str, dict] = {}
    for w in data.get("words", []):
        result[w["w"]] = {"cls": w.get("cls", []), "int": w.get("int", 0),
                           "pol": w.get("pol", 0), "pos": w.get("pos", "")}
    return result


def tokenize(text: str, dlut_words: set[str] | None = None) -> tuple[list[str], dict[str, int]]:
    """分词 + 词性统计。有 jieba 用 jieba，无则 DLUT 子集最大正向匹配降级。"""
    if _HAS_JIEBA:
        words = [w for w in jieba.cut(text) if w.strip()]
        pos_counts: dict[str, int] = {}
        for word, flag in pseg.cut(text):
            if not word.strip():
                continue
            cat = flag[0].lower() if flag else "x"
            pos_counts[cat] = pos_counts.get(cat, 0) + 1
        return words, pos_counts

    words: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if dlut_words and i + 1 < n and text[i:i + 2] in dlut_words:
            words.append(text[i:i + 2])
            i += 2
        elif _CJK_CHAR_RE.match(ch):
            words.append(ch)
            i += 1
        else:
            m = _ALNUM_RUN_RE.match(text, i)
            if m:
                words.append(m.group())
                i = m.end()
            else:
                i += 1
    return words, {}


def compute_metrics(text: str, dlut: dict[str, dict], dlut_words: set[str]) -> dict:
    """对单段文本计算全部量化指标。"""
    words, pos_counts = tokenize(text, dlut_words)

    char_count = len(text)
    word_count = len(words)
    unique_words = len(set(words))
    ttr = unique_words / max(word_count, 1)

    sentences = [s for s in SENTENCE_END_RE.split(text) if s.strip()]
    sentence_count = len(sentences)
    avg_sentence_length = char_count / max(sentence_count, 1)

    if pos_counts:
        verb_ratio = pos_counts.get("v", 0) / max(word_count, 1)
        adj_ratio = pos_counts.get("a", 0) / max(word_count, 1)
        noun_ratio = pos_counts.get("n", 0) / max(word_count, 1)
    else:
        v = a = n = 0
        for w in words:
            info = dlut.get(w)
            if info:
                if info["pos"] == "verb":
                    v += 1
                elif info["pos"] == "adj":
                    a += 1
                elif info["pos"] == "noun":
                    n += 1
        verb_ratio = v / max(word_count, 1)
        adj_ratio = a / max(word_count, 1)
        noun_ratio = n / max(word_count, 1)

    dialogue_chars = sum(len(m) for m in DIALOGUE_RE.findall(text))
    dialogue_ratio = dialogue_chars / max(char_count, 1)

    punct_count = len(PUNCTUATION_RE.findall(text))
    punctuation_density = punct_count / max(char_count, 1)

    pos_emotion = neg_emotion = anxiety = 0
    for w in words:
        info = dlut.get(w)
        if info:
            # DLUT pol 编码：0=中性, 1=褒义(正面), 2=贬义(负面), 3=兼有
            if info["pol"] == 1:
                pos_emotion += 1
            elif info["pol"] == 2:
                neg_emotion += 1
            if any(c in ("NC", "NI", "NB", "NJ", "NH", "PF") for c in info["cls"]):
                anxiety += 1
    emotion_scores = {
        "positive": round(pos_emotion / max(word_count, 1), 4),
        "negative": round(neg_emotion / max(word_count, 1), 4),
        "anxiety": round(anxiety / max(word_count, 1), 4),
        "matched_words": pos_emotion + neg_emotion,
    }

    sense_ratios: dict[str, float] = {}
    for sense, lexicon in SENSE_LEXICON.items():
        count = sum(text.count(w) for w in lexicon)
        sense_ratios[sense] = round(count / max(char_count, 1), 5)

    return {
        "char_count": char_count,
        "word_count": word_count,
        "sentence_count": sentence_count,
        "avg_sentence_length": round(avg_sentence_length, 1),
        "type_token_ratio": round(ttr, 4),
        "verb_ratio": round(verb_ratio, 4),
        "adj_ratio": round(adj_ratio, 4),
        "noun_ratio": round(noun_ratio, 4),
        "dialogue_ratio": round(dialogue_ratio, 4),
        "punctuation_density": round(punctuation_density, 4),
        "emotion_scores": emotion_scores,
        "sense_ratios": sense_ratios,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="计算文学分析——逐 segment 量化指标（纯 stdlib 优先，jieba 可选）")
    ap.add_argument("--segments", type=Path, required=True, help="输入 segments.jsonl")
    ap.add_argument("--out", type=Path, default=None, help="输出 quant_metrics.jsonl")
    ap.add_argument("--dlut-subset", type=Path,
                    default=Path(__file__).resolve().parent.parent / "references" / "lexicon-dlut-subset.json",
                    help="DLUT 清洗子集路径")
    args = ap.parse_args()

    if not args.segments.exists():
        print(f"[ERROR] 输入文件不存在: {args.segments}", file=sys.stderr)
        return 2

    dlut = load_dlut_subset(args.dlut_subset)
    dlut_words = set(dlut.keys())
    print(f"[INFO] jieba={'可用' if _HAS_JIEBA else '未安装（降级为DLUT最大正向匹配）'}；DLUT 子集={len(dlut)} 词")

    out_path = args.out or args.segments.parent / f"{args.segments.stem.replace('_segments', '')}_quant_metrics.jsonl"

    processed = 0
    with io.open(args.segments, encoding="utf-8") as fin, \
         io.open(out_path, "w", encoding="utf-8", newline="") as fout:
        for line in fin:
            line = line.strip()
            if not line:
                continue
            try:
                seg = json.loads(line)
            except json.JSONDecodeError:
                continue
            seg_id = seg.get("segment_id", f"seg_{processed:04d}")
            text = (
                seg.get("text_span", {}).get("text")
                or seg.get("text")
                or seg.get("content")
                or ""
            )
            if not text:
                continue
            metrics = compute_metrics(text, dlut, dlut_words)
            record = {
                "schema_version": SCHEMA_VERSION,
                "segment_id": seg_id,
                "metrics": metrics,
            }
            fout.write(json.dumps(record, ensure_ascii=False) + "\n")
            processed += 1

    print(f"[OK] 量化指标已写入 {out_path}（{processed} 段）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
