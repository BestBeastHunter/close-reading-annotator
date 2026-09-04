#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v2.9 Step 4 — 故事类型推断（Story Type Inference）

基于 Backgrounds/v29故事类型推断.md 方案实现。
纯规则引擎（不调 LLM），完全基于现有字段的统计聚合：
  1. 题材类型（科幻/言情/悬疑/战争/历史/奇幻/都市/成长）— D09 主题标签聚合
  2. 叙事风格（第一人称/第三人称/多视角/不可靠叙述）— D07 视角统计
  3. 时间结构（线性/倒叙/插叙/多线并行）— D08 时空序列
  4. 情感曲线形态（悲剧/喜剧/悲喜剧/开放式）— D04/D19 情感序列
  5. 叙事节奏类型（快节奏/慢节奏/张弛交替）— D05 节奏序列
  6. 读者情感体验类型（虐/甜/燃/治愈/虐甜混合）— D19 情感标签聚合

用法：
  python scripts/aggregation/story_type_inference.py \
    --segments outputs/annotations/moon_sixpence_zh/moon_sixpence_zh_segments.jsonl \
    --structure outputs/annotations/moon_sixpence_zh/moon_sixpence_zh_structure.jsonl \
    --interpretation outputs/annotations/moon_sixpence_zh/moon_sixpence_zh_interpretation.jsonl \
    --emotion outputs/annotations/moon_sixpence_zh/moon_sixpence_zh_emotion.jsonl \
    --doc-id moon_sixpence_zh \
    --output-dir outputs/annotations/moon_sixpence_zh/aggregation
"""

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

SCHEMA_VERSION = "2.9.0"

# 题材类型关键词映射（D09 标签中包含这些词 → 对应题材）
GENRE_KEYWORDS = {
    "科幻": ["科幻", "星际", "宇宙", "未来", "科技", "机器人", "AI", "人工智能", "外星", "太空",
             "泡防御", "德尔塔", "捕食者", "文明", "星舰", "量子", "赛博", "末世", "末日",
             "外星人", "入侵", "防御罩", "能量", "飞船", "空间站", "虚拟", "赛博朋克"],
    "言情": ["爱情", "恋爱", "言情", "情感", "暗恋", "告白", "分手", "婚姻", "暧昧", "痴情",
             "虐恋", "甜宠", "初恋", "相思", "情侣", "恋人", "表白", "失恋"],
    "悬疑": ["悬疑", "推理", "侦探", "谜团", "真相", "阴谋", "反转", "伏笔", "悬念", "揭秘",
             "凶案", "破案", "谜题", "线索"],
    "战争": ["战争", "军事", "战斗", "战役", "军队", "武器", "防御", "入侵", "保卫战", "前线",
             "战场", "士兵", "将军", "轰炸", "抵抗", "炮火", "弹药", "部队", "指挥官"],
    "历史": ["历史", "古代", "朝代", "传记", "回忆录", "年代", "世纪", "王朝", "宫廷", "史诗",
             "编年", "史料", "考古"],
    "奇幻": ["奇幻", "魔法", "玄幻", "修仙", "精灵", "龙族", "异世界", "巫师", "咒语", "神魔",
             "妖怪", "剑与魔法", "斗气"],
    "都市": ["都市", "城市", "职场", "生活", "日常", "社会", "白领", "打工", "北漂", "沪漂",
             "市井", "公寓", "地铁", "写字楼"],
    "成长": ["成长", "青春", "校园", "励志", "蜕变", "觉醒", "自我实现", "追梦", "迷茫", "顿悟",
             "成熟", "理想", "画家", "艺术家", "艺术", "理想主义", "追求", "灵魂", "自由",
             "天才", "创作", "绘画", "音乐", "文学"],
}

# 极性分数映射
POLARITY_SCORE = {
    "positive": 1.0,
    "negative": -1.0,
    "neutral": 0.0,
    "mixed": 0.0,
}


def load_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    rows = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def get_segment_index(seg_id: str) -> int:
    parts = seg_id.rsplit("_seg_", 1)
    if len(parts) == 2:
        try:
            return int(parts[1])
        except ValueError:
            pass
    return 0


# ==================== 维度 1：题材类型推断 ====================

def infer_genre(interpretation_rows: list[dict], structure_rows: list[dict],
                 emotion_rows: list[dict]) -> dict:
    """基于 D09 主题标签聚合推断题材类型。"""
    # 收集所有 D09 标签
    all_tags = []
    for row in interpretation_rows:
        interp = row.get("layers", {}).get("interpretation", {})
        if not interp:
            interp = row.get("interpretation", {})
        d09 = interp.get("D09", [])
        if isinstance(d09, list):
            all_tags.extend(d09)

    tag_counter = Counter(all_tags)
    total_tags = len(all_tags)
    total_segments = max(len(structure_rows), 1)

    if total_tags == 0:
        return {
            "primary": "未知",
            "secondary": [],
            "confidence": 0.0,
            "evidence": {"primary_signal": "无 D09 主题标签数据", "secondary_signal": ""},
            "tag_distribution": {},
        }

    # 计算每个题材的得分
    genre_scores = defaultdict(float)
    genre_evidence = defaultdict(list)

    for tag, count in tag_counter.items():
        for genre, keywords in GENRE_KEYWORDS.items():
            for kw in keywords:
                if kw in tag:
                    genre_scores[genre] += count
                    genre_evidence[genre].append(f"'{tag}'出现{count}次")
                    break

    # 按得分排序
    sorted_genres = sorted(genre_scores.items(), key=lambda x: x[1], reverse=True)

    if not sorted_genres:
        # 没有匹配到关键词，用 Top 标签作为参考
        top_tags = tag_counter.most_common(3)
        return {
            "primary": "其他",
            "secondary": [],
            "confidence": 0.3,
            "evidence": {
                "primary_signal": f"D09 Top标签: {', '.join(f'{t}({c}次)' for t, c in top_tags)}，未匹配到标准题材关键词",
                "secondary_signal": "",
            },
            "tag_distribution": dict(tag_counter.most_common(10)),
        }

    primary = sorted_genres[0][0]
    primary_score = sorted_genres[0][1]
    secondary = [g for g, s in sorted_genres[1:3] if s > 0]

    # 置信度计算
    # 信号1：Top标签集中度
    max_tag_freq = tag_counter.most_common(1)[0][1] if tag_counter else 0
    concentration = max_tag_freq / total_segments

    # 信号2：题材得分集中度（primary 占比）
    total_genre_score = sum(s for _, s in sorted_genres)
    genre_concentration = primary_score / total_genre_score if total_genre_score > 0 else 0

    # 信号3：标签多样性（标签种类数/总标签数，越低越集中）
    tag_diversity = len(tag_counter) / total_tags if total_tags > 0 else 1.0

    confidence = 0.0
    if concentration > 0.3:
        confidence += 0.3
    elif concentration > 0.15:
        confidence += 0.15

    if genre_concentration > 0.5:
        confidence += 0.3
    elif genre_concentration > 0.3:
        confidence += 0.15

    if tag_diversity < 0.2:
        confidence += 0.2
    elif tag_diversity < 0.5:
        confidence += 0.1

    confidence = min(confidence, 0.95)

    return {
        "primary": primary,
        "secondary": secondary,
        "confidence": round(confidence, 2),
        "evidence": {
            "primary_signal": f"D09标签中'{primary}'相关关键词出现{primary_score}次，占题材总得分{genre_concentration*100:.0f}%",
            "secondary_signal": f"次要题材信号: {', '.join(genre_evidence.get(secondary[0], ['无'])[:2]) if secondary else '无明显次要题材'}",
        },
        "genre_scores": dict(sorted_genres),
        "tag_distribution": dict(tag_counter.most_common(10)),
    }


# ==================== 维度 2：叙事风格推断 ====================

def infer_narrative_style(structure_rows: list[dict], interpretation_rows: list[dict]) -> dict:
    """基于 D07 视角统计推断叙事风格。"""
    perspective_counter = Counter()
    switch_points = 0
    total_with_d07 = 0

    for row in structure_rows:
        structure = row.get("layers", {}).get("structure", {})
        if not structure:
            structure = row.get("structure", {})
        d07 = structure.get("D07", {})
        if isinstance(d07, dict) and d07.get("type"):
            perspective_counter[d07["type"]] += 1
            total_with_d07 += 1
            if d07.get("is_switch_point"):
                switch_points += 1

    # 叙述者可靠性
    reliability_counter = Counter()
    for row in interpretation_rows:
        interp = row.get("layers", {}).get("interpretation", {})
        if not interp:
            interp = row.get("interpretation", {})
        rel = interp.get("narrator_reliability")
        if rel:
            reliability_counter[rel] += 1

    if total_with_d07 == 0:
        return {
            "type": "未知",
            "is_reliable": None,
            "is_linear": None,
            "confidence": 0.0,
            "evidence": "无 D07 视角数据",
            "perspective_distribution": {},
        }

    # 判断视角类型
    dominant_perspective = perspective_counter.most_common(1)[0]
    dominant_ratio = dominant_perspective[1] / total_with_d07
    has_switch = switch_points > 0
    num_perspectives = len(perspective_counter)

    if has_switch or num_perspectives >= 3:
        style_type = "多视角叙事"
    elif dominant_perspective[0] == "第一人称" and dominant_ratio > 0.5:
        style_type = "第一人称叙述"
    elif dominant_perspective[0] == "第三人称有限" and dominant_ratio > 0.5:
        style_type = "第三人称有限视角"
    elif dominant_perspective[0] == "第三人称全知" and dominant_ratio > 0.5:
        style_type = "第三人称全知视角"
    elif dominant_ratio > 0.5:
        style_type = f"{dominant_perspective[0]}主导"
    else:
        style_type = "混合视角"

    # 可靠性
    is_reliable = True
    if "不可靠" in reliability_counter or "部分不可靠" in reliability_counter:
        is_reliable = False

    # 置信度
    confidence = min(dominant_ratio, 0.95) if not has_switch else max(0.5, 1.0 - switch_points / total_with_d07)

    return {
        "type": style_type,
        "is_reliable": is_reliable,
        "is_linear": not has_switch,
        "confidence": round(confidence, 2),
        "evidence": f"D07视角分布: {dict(perspective_counter)}；视角切换点: {switch_points}个；叙述者可靠性: {dict(reliability_counter) if reliability_counter else '未标注'}",
        "perspective_distribution": dict(perspective_counter),
        "switch_point_count": switch_points,
    }


# ==================== 维度 3：时间结构推断 ====================

def infer_time_structure(structure_rows: list[dict]) -> dict:
    """基于 D08 时空序列检测时间结构。"""
    time_sequence = []
    for row in sorted(structure_rows, key=lambda r: get_segment_index(r.get("segment_id", ""))):
        structure = row.get("layers", {}).get("structure", {})
        if not structure:
            structure = row.get("structure", {})
        d08 = structure.get("D08", {})
        if isinstance(d08, dict):
            time_str = d08.get("time")
            if time_str:
                time_sequence.append({
                    "segment_id": row.get("segment_id"),
                    "time": time_str,
                    "index": get_segment_index(row.get("segment_id", "")),
                })

    if len(time_sequence) < 3:
        return {
            "type": "未知",
            "has_flashback": False,
            "has_parallel": False,
            "confidence": 0.0,
            "evidence": "D08.time 数据不足（<3段）",
        }

    # 检测倒叙/回溯：后面的段时间描述中包含"回忆"、"多年前"、"曾经"、"那年"等词
    flashback_keywords = ["回忆", "回想", "多年前", "曾经", "那年", "那时", "小时候", "童年",
                          "往事", "昔日", "从前", "记忆中", "恍如隔世", "追溯"]
    flashback_count = 0
    flashback_segments = []

    for item in time_sequence:
        for kw in flashback_keywords:
            if kw in item["time"]:
                flashback_count += 1
                flashback_segments.append(item["segment_id"])
                break

    # 检测时间跳跃：相邻段时间描述差异大
    time_jumps = 0
    for i in range(1, len(time_sequence)):
        prev_time = time_sequence[i - 1]["time"]
        curr_time = time_sequence[i]["time"]
        # 如果时间描述完全不同且没有连续性词（"第二天"、"随后"、"接着"）
        continuity_words = ["第二天", "次日", "随后", "接着", "然后", "不久", "片刻", "一会儿",
                            "同时", "其间", "之后", "之前"]
        has_continuity = any(w in curr_time for w in continuity_words)
        if not has_continuity and prev_time != curr_time:
            time_jumps += 1

    # 判断类型
    # 注意：回忆框架（开头/结尾有"回忆"、"多年后"等）不等于多线并行
    # 真正的多线并行需要：大量倒叙穿插 + 大量时间跳跃，且不是集中在开头/结尾
    if flashback_count >= 3 and time_jumps >= 8:
        time_type = "多线并行/非线性叙事"
    elif flashback_count >= 3 or (flashback_count >= 1 and time_jumps >= 5):
        time_type = "倒叙/插叙结构"
    elif time_jumps >= 8:
        time_type = "跳跃式叙事"
    elif flashback_count >= 1:
        time_type = "线性叙事（含回忆穿插）"
    else:
        time_type = "线性叙事"

    confidence = min(0.95, 0.4 + (flashback_count + time_jumps) * 0.03) if time_type != "未知" else 0.3

    return {
        "type": time_type,
        "has_flashback": flashback_count > 0,
        "has_parallel": time_type == "多线并行/非线性叙事",
        "flashback_count": flashback_count,
        "time_jump_count": time_jumps,
        "confidence": round(confidence, 2),
        "evidence": f"检测到{flashback_count}处倒叙/回溯标记，{time_jumps}处时间跳跃；倒叙段: {flashback_segments[:5]}",
    }


# ==================== 维度 4：情感曲线形态推断 ====================

def infer_emotion_arc(structure_rows: list[dict], emotion_rows: list[dict]) -> dict:
    """基于 D04/D19 情感序列推断情感曲线形态。"""
    # 收集时序情感数据
    emotion_timeline = []
    for row in sorted(structure_rows, key=lambda r: get_segment_index(r.get("segment_id", ""))):
        structure = row.get("layers", {}).get("structure", {})
        if not structure:
            structure = row.get("structure", {})
        d04 = structure.get("D04", {})
        if isinstance(d04, dict) and d04.get("polarity"):
            emotion_timeline.append({
                "segment_id": row.get("segment_id"),
                "source": "D04",
                "emotion": d04.get("core"),
                "intensity": d04.get("intensity"),
                "polarity": d04.get("polarity"),
                "index": get_segment_index(row.get("segment_id", "")),
            })

    # 用 D19 补充（优先 D19，因为更精细）
    d19_by_seg = {}
    for row in emotion_rows:
        emotion = row.get("layers", {}).get("emotion", {})
        if not emotion:
            emotion = row.get("emotion", {})
        primary = emotion.get("primary", {})
        if isinstance(primary, dict) and primary.get("polarity"):
            d19_by_seg[row.get("segment_id")] = {
                "source": "D19",
                "emotion": primary.get("emotion"),
                "intensity": primary.get("intensity"),
                "polarity": primary.get("polarity"),
            }

    # 合并：D19 覆盖 D04
    for item in emotion_timeline:
        if item["segment_id"] in d19_by_seg:
            item.update(d19_by_seg[item["segment_id"]])

    if len(emotion_timeline) < 5:
        return {
            "pattern": "数据不足",
            "start_polarity": None,
            "end_polarity": None,
            "peak_intensity": None,
            "peak_segment": None,
            "confidence": 0.0,
            "evidence": "情感时序数据不足（<5段）",
        }

    # 计算开头/结尾极性（取前10%和后10%的段，而不是固定3段）
    n = len(emotion_timeline)
    window = max(3, n // 10)
    start_items = emotion_timeline[:window]
    end_items = emotion_timeline[-window:]
    start_polarity_score = sum(POLARITY_SCORE.get(i["polarity"], 0) for i in start_items) / len(start_items)
    end_polarity_score = sum(POLARITY_SCORE.get(i["polarity"], 0) for i in end_items) / len(end_items)

    # 全书整体极性分布（更重要）
    all_polarity_scores = [POLARITY_SCORE.get(i["polarity"], 0) for i in emotion_timeline]
    polarity_scores = all_polarity_scores  # 兼容后续计算
    overall_avg = sum(all_polarity_scores) / len(all_polarity_scores)
    neg_count = sum(1 for s in all_polarity_scores if s < 0)
    pos_count = sum(1 for s in all_polarity_scores if s > 0)
    neg_ratio = neg_count / len(all_polarity_scores)
    pos_ratio = pos_count / len(all_polarity_scores)

    start_polarity = "positive" if start_polarity_score > 0.3 else ("negative" if start_polarity_score < -0.3 else "mixed/neutral")
    end_polarity = "positive" if end_polarity_score > 0.3 else ("negative" if end_polarity_score < -0.3 else "mixed/neutral")

    # 趋势
    trend = end_polarity_score - start_polarity_score

    # 峰值
    intensities = [i["intensity"] for i in emotion_timeline if i.get("intensity")]
    peak_intensity = max(intensities) if intensities else None
    peak_item = max(emotion_timeline, key=lambda x: x.get("intensity") or 0)
    peak_segment = peak_item["segment_id"]
    # 峰值位置（0=开头，1=结尾）
    peak_position = get_segment_index(peak_segment) / max(get_segment_index(emotion_timeline[-1]["segment_id"]), 1)

    # 波动
    if len(polarity_scores) >= 2:
        variance = sum((p - sum(polarity_scores)/len(polarity_scores))**2 for p in polarity_scores) / len(polarity_scores)
    else:
        variance = 0

    # 判断曲线形态（综合全书整体分布 + 趋势 + 峰值位置）
    # 悲剧：整体 negative 占主导，或结尾 negative 且趋势下行
    # 喜剧：整体 positive 占主导，或结尾 positive 且趋势上行
    # 悲喜剧：有起伏，结尾 mixed/neutral 或 positive 但整体有大量 negative
    if neg_ratio > 0.5 and (end_polarity == "negative" or trend < -0.1):
        arc_pattern = "悲剧弧线（压抑→下行）"
    elif pos_ratio > 0.5 and (end_polarity == "positive" or trend > 0.1):
        arc_pattern = "喜剧弧线（上升→圆满）"
    elif variance > 0.3 and (end_polarity == "mixed/neutral" or (neg_ratio > 0.3 and pos_ratio > 0.3)):
        arc_pattern = "悲喜剧弧线（起伏→释然）"
    elif variance > 0.5:
        arc_pattern = "波动型弧线（大起大落）"
    elif end_polarity == "mixed/neutral" and neg_ratio > 0.3:
        arc_pattern = "悲剧弧线（余韵悠长）"
    elif end_polarity == "mixed/neutral":
        arc_pattern = "开放式结局（余韵悠长）"
    else:
        arc_pattern = "平稳型弧线"

    # 情感路径描述（取5个关键点）
    key_points = []
    step = max(1, len(emotion_timeline) // 5)
    for i in range(0, len(emotion_timeline), step):
        item = emotion_timeline[i]
        key_points.append(f"{item.get('emotion') or item['polarity']}({item.get('intensity') or '?'})")
    pattern_str = "→".join(key_points[:6])

    confidence = min(0.9, 0.4 + len(emotion_timeline) * 0.01)

    return {
        "pattern": arc_pattern,
        "emotion_path": pattern_str,
        "start_polarity": start_polarity,
        "end_polarity": end_polarity,
        "trend_score": round(trend, 2),
        "variance": round(variance, 2),
        "peak_intensity": peak_intensity,
        "peak_segment": peak_segment,
        "confidence": round(confidence, 2),
        "evidence": f"开头极性={start_polarity}({start_polarity_score:.2f})，结尾极性={end_polarity}({end_polarity_score:.2f})，趋势={trend:.2f}，波动方差={variance:.2f}，数据点={len(emotion_timeline)}",
    }


# ==================== 维度 5：叙事节奏类型推断 ====================

def infer_pace(structure_rows: list[dict]) -> dict:
    """基于 D05 节奏序列推断叙事节奏类型。"""
    paces = []
    for row in structure_rows:
        structure = row.get("layers", {}).get("structure", {})
        if not structure:
            structure = row.get("structure", {})
        d05 = structure.get("D05")
        if isinstance(d05, (int, float)) and 1 <= d05 <= 5:
            paces.append(d05)

    if len(paces) < 3:
        return {
            "type": "未知",
            "avg_pace": None,
            "variance": None,
            "confidence": 0.0,
            "evidence": "D05 节奏数据不足（<3段）",
        }

    avg_pace = sum(paces) / len(paces)
    variance = sum((p - avg_pace)**2 for p in paces) / len(paces)

    if avg_pace > 3.5 and variance < 1.0:
        pace_type = "快节奏叙事"
    elif avg_pace < 2.5 and variance < 1.0:
        pace_type = "慢节奏叙事"
    elif variance >= 1.0:
        pace_type = "张弛交替（快慢结合）"
    else:
        pace_type = "中速叙事"

    confidence = min(0.9, 0.5 + len(paces) * 0.01)

    # 节奏分布
    pace_dist = Counter(paces)

    return {
        "type": pace_type,
        "avg_pace": round(avg_pace, 2),
        "variance": round(variance, 2),
        "min_pace": min(paces),
        "max_pace": max(paces),
        "confidence": round(confidence, 2),
        "evidence": f"D05均值={avg_pace:.2f}，方差={variance:.2f}，范围={min(paces)}-{max(paces)}，数据点={len(paces)}",
        "pace_distribution": {str(k): v for k, v in sorted(pace_dist.items())},
    }


# ==================== 维度 6：读者情感体验类型推断 ====================

def infer_reader_experience(emotion_rows: list[dict], structure_rows: list[dict]) -> dict:
    """基于 D19 情感标签聚合推断读者情感体验类型。"""
    polarity_counter = Counter()
    intensities = []
    high_intensity_count = 0  # intensity >= 7
    positive_high = 0
    negative_high = 0

    for row in emotion_rows:
        emotion = row.get("layers", {}).get("emotion", {})
        if not emotion:
            emotion = row.get("emotion", {})
        primary = emotion.get("primary", {})
        if isinstance(primary, dict):
            pol = primary.get("polarity")
            inten = primary.get("intensity")
            if pol:
                polarity_counter[pol] += 1
            if isinstance(inten, (int, float)):
                intensities.append(inten)
                if inten >= 7:
                    high_intensity_count += 1
                    if pol == "positive":
                        positive_high += 1
                    elif pol == "negative":
                        negative_high += 1

    total = sum(polarity_counter.values())
    if total == 0:
        # 用 D04 兜底
        for row in structure_rows:
            structure = row.get("layers", {}).get("structure", {})
            if not structure:
                structure = row.get("structure", {})
            d04 = structure.get("D04", {})
            if isinstance(d04, dict) and d04.get("polarity"):
                polarity_counter[d04["polarity"]] += 1
                if isinstance(d04.get("intensity"), (int, float)):
                    intensities.append(d04["intensity"])
        total = sum(polarity_counter.values())

    if total == 0:
        return {
            "primary": "未知",
            "secondary": [],
            "confidence": 0.0,
            "evidence": "无情感数据",
            "polarity_distribution": {},
        }

    neg_ratio = polarity_counter.get("negative", 0) / total
    pos_ratio = polarity_counter.get("positive", 0) / total
    mixed_ratio = polarity_counter.get("mixed", 0) / total
    high_ratio = high_intensity_count / total if total > 0 else 0

    # 判断体验类型
    if neg_ratio > 0.5 and high_ratio > 0.3:
        primary_exp = "虐心"
    elif pos_ratio > 0.5 and high_ratio < 0.3:
        primary_exp = "治愈"
    elif pos_ratio > 0.4 and positive_high > negative_high:
        primary_exp = "燃"
    elif pos_ratio > 0.5:
        primary_exp = "甜"
    elif neg_ratio > 0.3 and pos_ratio > 0.3:
        primary_exp = "虐甜混合"
    elif neg_ratio > 0.4:
        primary_exp = "压抑"
    else:
        primary_exp = "复杂/中性"

    # 次要体验
    secondary = []
    if primary_exp != "虐心" and neg_ratio > 0.3:
        secondary.append("虐心")
    if primary_exp != "甜" and pos_ratio > 0.3:
        secondary.append("甜")
    if primary_exp != "燃" and high_ratio > 0.3 and positive_high > 0:
        secondary.append("燃")
    if primary_exp != "治愈" and pos_ratio > 0.4 and high_ratio < 0.3:
        secondary.append("治愈")

    confidence = min(0.9, 0.4 + total * 0.01)

    return {
        "primary": primary_exp,
        "secondary": secondary[:2],
        "confidence": round(confidence, 2),
        "evidence": f"极性分布: negative={neg_ratio*100:.0f}%, positive={pos_ratio*100:.0f}%, mixed={mixed_ratio*100:.0f}%；高强度(>=7)占比={high_ratio*100:.0f}%；数据点={total}",
        "polarity_distribution": dict(polarity_counter),
        "avg_intensity": round(sum(intensities) / len(intensities), 2) if intensities else None,
        "high_intensity_ratio": round(high_ratio, 2),
    }


# ==================== 主函数 ====================

def main() -> int:
    p = argparse.ArgumentParser(description="v2.9 Step 4 — 故事类型推断（Story Type Inference）")
    p.add_argument("--segments", required=True, help="segments.jsonl 路径")
    p.add_argument("--structure", required=True, help="structure.jsonl 路径")
    p.add_argument("--interpretation", default=None, help="interpretation.jsonl 路径（用于D09题材推断）")
    p.add_argument("--emotion", default=None, help="emotion.jsonl 路径（用于D19情感曲线）")
    p.add_argument("--doc-id", required=True, help="文档 ID")
    p.add_argument("--output-dir", required=True, help="输出目录")
    args = p.parse_args()

    segments_path = Path(args.segments)
    structure_path = Path(args.structure)
    for path, name in [(segments_path, "segments"), (structure_path, "structure")]:
        if not path.is_file():
            print(f"❌ {name} 文件不存在：{path}", file=sys.stderr)
            return 2

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # 加载数据
    segments = load_jsonl(segments_path)
    structure_rows = load_jsonl(structure_path)
    interpretation_rows = load_jsonl(Path(args.interpretation)) if args.interpretation else []
    emotion_rows = load_jsonl(Path(args.emotion)) if args.emotion else []

    print(f"📖 加载 segments: {len(segments)} 段")
    print(f"📖 加载 structure: {len(structure_rows)} 行, interpretation: {len(interpretation_rows)} 行, emotion: {len(emotion_rows)} 行")

    # 6 个维度推断
    print("\n🚀 Step 1: 题材类型推断...")
    genre = infer_genre(interpretation_rows, structure_rows, emotion_rows)
    print(f"   题材: {genre['primary']} (次要: {genre['secondary']}, 置信度: {genre['confidence']})")

    print("\n🚀 Step 2: 叙事风格推断...")
    narrative_style = infer_narrative_style(structure_rows, interpretation_rows)
    print(f"   风格: {narrative_style['type']} (可靠: {narrative_style['is_reliable']}, 置信度: {narrative_style['confidence']})")

    print("\n🚀 Step 3: 时间结构推断...")
    time_structure = infer_time_structure(structure_rows)
    print(f"   时间结构: {time_structure['type']} (倒叙: {time_structure['has_flashback']}, 置信度: {time_structure['confidence']})")

    print("\n🚀 Step 4: 情感曲线形态推断...")
    emotion_arc = infer_emotion_arc(structure_rows, emotion_rows)
    print(f"   情感曲线: {emotion_arc['pattern']} (开头: {emotion_arc['start_polarity']}, 结尾: {emotion_arc['end_polarity']}, 置信度: {emotion_arc['confidence']})")

    print("\n🚀 Step 5: 叙事节奏类型推断...")
    pace = infer_pace(structure_rows)
    print(f"   节奏: {pace['type']} (均值: {pace['avg_pace']}, 方差: {pace['variance']}, 置信度: {pace['confidence']})")

    print("\n🚀 Step 6: 读者情感体验类型推断...")
    reader_experience = infer_reader_experience(emotion_rows, structure_rows)
    print(f"   读者体验: {reader_experience['primary']} (次要: {reader_experience['secondary']}, 置信度: {reader_experience['confidence']})")

    # 构建 story_metadata
    print("\n🚀 Step 7: 构建 story_metadata.json...")
    story_metadata = {
        "doc_id": args.doc_id,
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "story_metadata": {
            "genre": genre,
            "narrative_style": narrative_style,
            "time_structure": time_structure,
            "emotion_arc": emotion_arc,
            "pace": pace,
            "reader_experience": reader_experience,
        },
        "summary": {
            "one_line": f"{genre['primary']}题材 · {narrative_style['type']} · {time_structure['type']} · {emotion_arc['pattern']} · {pace['type']} · 读者体验{reader_experience['primary']}",
            "avg_confidence": round(sum([
                genre["confidence"], narrative_style["confidence"], time_structure["confidence"],
                emotion_arc["confidence"], pace["confidence"], reader_experience["confidence"]
            ]) / 6, 2),
        },
        "_metadata": {
            "method": "rule_based_v2_9",
            "dimensions": ["genre", "narrative_style", "time_structure", "emotion_arc", "pace", "reader_experience"],
            "data_sources": {
                "genre": "D09主题标签聚合",
                "narrative_style": "D07视角统计+narrator_reliability",
                "time_structure": "D08.time序列检测",
                "emotion_arc": "D04+D19情感时序聚合",
                "pace": "D05节奏序列",
                "reader_experience": "D19极性比例+强度分布",
            },
            "note": "纯规则引擎，无需LLM调用；置信度基于数据充分度和信号集中度",
        },
    }

    # 写入文件
    out_path = out_dir / f"{args.doc_id}_story_metadata.json"
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(story_metadata, f, ensure_ascii=False, indent=2)

    print(f"\n✅ story_metadata.json 已写入: {out_path}")
    print(f"\n📊 一句话总结: {story_metadata['summary']['one_line']}")
    print(f"   平均置信度: {story_metadata['summary']['avg_confidence']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
