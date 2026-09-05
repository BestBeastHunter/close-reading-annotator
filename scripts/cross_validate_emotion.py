#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/cross_validate_emotion.py — DLUT 弱信号交叉验证工具 v3.8.2（T-044）

基于 DLUT 子集（v3.3 已引入，9,924 词）对 segment 原文做情感词频统计，
计算 DLUT 推断的主导情感（褒义/贬义/中性），与 D19 主情感的 polarity 对比。

双轨存储：在批注中新增 _baseline_emotion 字段（DLUT 推断结果），保留原 D19 主情感。

用法：
  python scripts/cross_validate_emotion.py --emotion <doc_id>_emotion.jsonl --segments <doc_id>_segments.jsonl --output <output>.jsonl
  python scripts/cross_validate_emotion.py --emotion <doc_id>_emotion.jsonl --segments <doc_id>_segments.jsonl --in-place
  python scripts/cross_validate_emotion.py --dir <annotations_dir> --doc-id <doc_id> --in-place
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from collections import Counter

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# DLUT 子集路径（随包分发，v3.3 引入）
DLUT_SUBSET_PATH = Path(__file__).parent.parent / "references" / "lexicon-dlut-subset.json"


def load_dlut_subset() -> dict:
    """加载 DLUT 子集（word -> polarity）
    
    DLUT 子集格式（v3.3 引入）：
      顶层键：meta, class_codes, words
      words 数组元素：{"w":"脏乱","pos":"adj","cls":["NN"],"int":7,"pol":2,"aux":[]}
      pol: 1=褒义, 2=贬义, 0=中性
    """
    if not DLUT_SUBSET_PATH.exists():
        print(f"⚠️ DLUT 子集不存在: {DLUT_SUBSET_PATH}，使用空词表", file=sys.stderr)
        return {}
    
    with open(DLUT_SUBSET_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    # 构建 word -> polarity 映射
    word_polarity = {}
    words = data.get("words", []) if isinstance(data, dict) else data
    
    if isinstance(words, list):
        for item in words:
            word = item.get("w", "")
            pol = item.get("pol", "")
            if word and pol != "":
                # DLUT pol: 1=褒义, 2=贬义, 0=中性
                if pol == 1 or pol == "1":
                    word_polarity[word] = "positive"
                elif pol == 2 or pol == "2":
                    word_polarity[word] = "negative"
                elif pol == 0 or pol == "0":
                    word_polarity[word] = "neutral"
    elif isinstance(words, dict):
        for word, item in words.items():
            if isinstance(item, dict):
                pol = item.get("pol", item.get("polarity", ""))
                if pol == 1 or pol == "1" or pol == "positive":
                    word_polarity[word] = "positive"
                elif pol == 2 or pol == "2" or pol == "negative":
                    word_polarity[word] = "negative"
                elif pol == 0 or pol == "0" or pol == "neutral":
                    word_polarity[word] = "neutral"
    
    return word_polarity


def load_jsonl(path: Path) -> list[dict]:
    """加载 JSONL 文件"""
    rows = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return rows


def save_jsonl(rows: list[dict], path: Path) -> None:
    """保存 JSONL 文件（原子写）"""
    tmp = path.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    tmp.replace(path)


def segment_text_emotion_stats(text: str, word_polarity: dict) -> dict:
    """对 segment 原文做情感词频统计，返回 DLUT 推断的主导情感"""
    if not text or not word_polarity:
        return {"positive_count": 0, "negative_count": 0, "neutral_count": 0, "total_matched": 0, "dominant_polarity": "neutral", "matched_words": []}
    
    positive_count = 0
    negative_count = 0
    neutral_count = 0
    matched_words = []
    
    # 最大正向匹配（2 字词优先）
    i = 0
    while i < len(text):
        matched = False
        # 尝试 2 字词
        if i + 1 < len(text):
            bigram = text[i:i+2]
            if bigram in word_polarity:
                pol = word_polarity[bigram]
                if pol == "positive":
                    positive_count += 1
                elif pol == "negative":
                    negative_count += 1
                else:
                    neutral_count += 1
                matched_words.append({"word": bigram, "polarity": pol})
                i += 2
                matched = True
                continue
        
        # 尝试 1 字词
        if not matched:
            char = text[i]
            if char in word_polarity:
                pol = word_polarity[char]
                if pol == "positive":
                    positive_count += 1
                elif pol == "negative":
                    negative_count += 1
                else:
                    neutral_count += 1
                matched_words.append({"word": char, "polarity": pol})
            i += 1
    
    # 确定主导情感
    total = positive_count + negative_count + neutral_count
    if total == 0:
        dominant = "neutral"
    elif positive_count >= negative_count and positive_count >= neutral_count:
        dominant = "positive"
    elif negative_count >= positive_count and negative_count >= neutral_count:
        dominant = "negative"
    else:
        dominant = "neutral"
    
    return {
        "positive_count": positive_count,
        "negative_count": negative_count,
        "neutral_count": neutral_count,
        "total_matched": total,
        "dominant_polarity": dominant,
        "matched_words": matched_words[:10],  # 只保留前 10 个匹配词
    }


def cross_validate_emotion_file(emotion_path: Path, segments_path: Path, 
                                  output_path: Path | None = None, 
                                  in_place: bool = False) -> dict:
    """对单个 emotion JSONL 文件做 DLUT 交叉验证"""
    emotion_rows = load_jsonl(emotion_path)
    segment_rows = load_jsonl(segments_path)
    
    if not emotion_rows:
        print(f"⚠️ {emotion_path} 为空，跳过")
        return {"total": 0, "validated": 0, "consistent": 0, "consistency_rate": 0}
    
    # 构建 segment_id -> text 映射
    segment_texts = {}
    for row in segment_rows:
        seg_id = row.get("segment_id", "")
        text = row.get("text_span", {}).get("text", "") if isinstance(row.get("text_span"), dict) else ""
        if seg_id and text:
            segment_texts[seg_id] = text
    
    # 加载 DLUT 子集
    word_polarity = load_dlut_subset()
    
    validated = 0
    consistent = 0
    inconsistent = 0
    inconsistencies = []
    
    for row in emotion_rows:
        seg_id = row.get("segment_id", "")
        text = segment_texts.get(seg_id, "")
        
        if not text:
            continue
        
        # DLUT 推断
        dlut_result = segment_text_emotion_stats(text, word_polarity)
        dlut_polarity = dlut_result["dominant_polarity"]
        
        # D19 主情感极性
        d19 = row.get("layers", {}).get("emotion", {}) or row.get("emotion", {})
        d19_polarity = d19.get("primary", {}).get("polarity", "") if isinstance(d19.get("primary"), dict) else ""
        
        # 一致性判断（mixed 视为与 positive/negative 都一致）
        if d19_polarity == "mixed" or dlut_polarity == "neutral":
            is_consistent = True  # mixed 或 neutral 视为一致
        elif d19_polarity == dlut_polarity:
            is_consistent = True
        else:
            is_consistent = False
        
        if is_consistent:
            consistent += 1
        else:
            inconsistent += 1
            if len(inconsistencies) < 20:
                inconsistencies.append({
                    "segment": seg_id,
                    "d19_polarity": d19_polarity,
                    "dlut_polarity": dlut_polarity,
                    "dlut_positive": dlut_result["positive_count"],
                    "dlut_negative": dlut_result["negative_count"],
                })
        
        # 回写 baseline_emotion
        row["_baseline_emotion"] = {
            "source": "dlut_subset_v33",
            "dominant_polarity": dlut_polarity,
            "positive_count": dlut_result["positive_count"],
            "negative_count": dlut_result["negative_count"],
            "neutral_count": dlut_result["neutral_count"],
            "total_matched": dlut_result["total_matched"],
            "matched_words_sample": dlut_result["matched_words"],
            "consistent_with_d19": is_consistent,
        }
        
        # 更新 _metadata
        metadata = row.get("_metadata", {})
        metadata["emotion_cross_validated"] = True
        metadata["emotion_cross_validated_at"] = "v3.8.2"
        row["_metadata"] = metadata
        
        validated += 1
    
    # 保存
    if in_place:
        save_jsonl(emotion_rows, emotion_path)
        output_path = emotion_path
    elif output_path:
        save_jsonl(emotion_rows, output_path)
    else:
        output_path = emotion_path.with_name(emotion_path.stem + "_cross_validated.jsonl")
        save_jsonl(emotion_rows, output_path)
    
    consistency_rate = consistent / validated * 100 if validated > 0 else 0
    
    stats = {
        "total": len(emotion_rows),
        "validated": validated,
        "consistent": consistent,
        "inconsistent": inconsistent,
        "consistency_rate": round(consistency_rate, 1),
        "dlut_word_count": len(word_polarity),
        "output": str(output_path),
        "inconsistencies_sample": inconsistencies,
    }
    
    return stats


def main():
    parser = argparse.ArgumentParser(description="DLUT 弱信号交叉验证工具 v3.8.2（T-044）")
    parser.add_argument("--emotion", type=str, help="emotion JSONL 文件路径")
    parser.add_argument("--segments", type=str, help="segments.jsonl 路径")
    parser.add_argument("--output", type=str, help="输出文件路径")
    parser.add_argument("--in-place", action="store_true", help="直接覆盖原文件")
    parser.add_argument("--dir", type=str, help="批注目录（批量处理，需配合 --doc-id）")
    parser.add_argument("--doc-id", type=str, help="文档 ID（批量处理时使用）")
    
    args = parser.parse_args()
    
    if args.dir and args.doc_id:
        # 批量处理模式
        ann_dir = Path(args.dir) / args.doc_id
        emotion_path = ann_dir / f"{args.doc_id}_emotion.jsonl"
        segments_path = Path(args.dir).parent / "segments" / f"{args.doc_id}_segments.jsonl"
        
        if not emotion_path.exists():
            print(f"❌ emotion 文件不存在: {emotion_path}")
            sys.exit(1)
        if not segments_path.exists():
            # 尝试其他路径
            segments_path = ann_dir / f"{args.doc_id}_segments.jsonl"
        
        stats = cross_validate_emotion_file(emotion_path, segments_path, in_place=args.in_place)
    elif args.emotion and args.segments:
        stats = cross_validate_emotion_file(Path(args.emotion), Path(args.segments), 
                                              Path(args.output) if args.output else None,
                                              args.in_place)
    else:
        parser.print_help()
        sys.exit(1)
    
    # 打印结果
    print("=" * 60)
    print("DLUT 弱信号交叉验证结果")
    print("=" * 60)
    print(f"总行数: {stats['total']}")
    print(f"已验证: {stats['validated']}")
    print(f"一致: {stats['consistent']}")
    print(f"不一致: {stats['inconsistent']}")
    print(f"一致率: {stats['consistency_rate']}%")
    print(f"DLUT 词表大小: {stats['dlut_word_count']}")
    print(f"输出文件: {stats['output']}")
    print("=" * 60)
    
    if stats.get("inconsistencies_sample"):
        print("\n不一致样例（前20条）:")
        for inc in stats["inconsistencies_sample"]:
            print(f"  {inc['segment']}: D19={inc['d19_polarity']} vs DLUT={inc['dlut_polarity']} (褒{inc['dlut_positive']}/贬{inc['dlut_negative']})")


if __name__ == "__main__":
    main()
