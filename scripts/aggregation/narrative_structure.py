#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v3.7 Step — 叙事结构分析（Narrative Structure Analysis）

基于 Backgrounds/叙事结构模块.md 方案实现。
纯规则引擎（不调 LLM），完全基于现有字段的统计聚合：
  P0：弗雷塔格五幕（Freytag's Pyramid）— 从 D01 序列推导
  P0：热奈特聚焦（Genette Focalization）— 从 D07 统计 + _narrator_identity
  P1：叙事时间线（Narrative Timeline）— 从 D08.time 序列 + _time_type
  P1：救猫咪节拍（Save the Cat Beats，简化 10 节拍）— 从 D01+D05+D08
  P2：叙事层级图（Narrative Levels）— 从 D08._narrative_level
  P2：格雷马斯行动元（Greimas Actantial Model，简化版）— 从角色弧线+实体

降级策略：v3.6 新字段（_time_type/_narrative_level/_narrator_identity/D12）缺失时，
从 D01/D07/D08 原始字段降级推断，输出中标注 derivation_method。

用法：
  python scripts/aggregation/narrative_structure.py \
    --structure outputs/annotations/moon_sixpence_zh/moon_sixpence_zh_structure.jsonl \
    --doc-id moon_sixpence_zh \
    --output-dir outputs/annotations/moon_sixpence_zh/aggregation
"""

import argparse
import io
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

SCHEMA_VERSION = "3.1.0"

# 弗雷塔格五幕映射（D01 → 幕）
FREYTAG_MAP = {
    "背景铺垫": "exposition",
    "激励事件": "inciting_incident",
    "上升行动": "rising_action",
    "转折": "climax",
    "高潮": "climax",  # 高潮也归入 climax 区域
    "下降行动": "falling_action",
    "结局": "resolution",
    "过渡": "transition",
    "复合功能": "transition",
    "无法判断": "transition",
}

# 热奈特聚焦映射（D07.type → 聚焦类型）
GENETTE_FOCALIZATION_MAP = {
    "第一人称": "first_person_focalization",
    "第二人称": "second_person_focalization",
    "第三人称有限": "internal_focalization",
    "第三人称全知": "zero_focalization",
    "多视角": "variable_focalization",
    "不可靠叙述者": "unreliable_focalization",
    "客观叙事": "external_focalization",
}

# 倒叙/插叙关键词（用于 _time_type 缺失时的降级推断）
FLASHBACK_KEYWORDS = ["回忆", "回想", "多年前", "曾经", "以前", "过去", "那年", "小时候", "童年", "往事", "记忆中", "昔日"]
FLASHFORWARD_KEYWORDS = ["多年后", "后来", "将来", "未来", "若干年后", "十年后", "从此以后"]
ANALEPSIS_KEYWORDS = ["话说", "却说", "且说", "原来", "此前", "在此之前"]
PROLEPSIS_KEYWORDS = ["且说", "话分两头", "预知后事", "暂且不表"]

# 救猫咪 10 节拍（简化版，从 15 节拍压缩）
SAVE_THE_CAT_BEATS = [
    ("opening_image", 0.0, 0.05, "开场画面"),
    ("theme_stated", 0.05, 0.10, "主题呈现"),
    ("setup", 0.0, 0.10, "铺垫"),
    ("catalyst", 0.10, 0.15, "激励事件"),
    ("debate", 0.15, 0.25, "辩论"),
    ("break_into_two", 0.25, 0.30, "进入第二幕"),
    ("fun_and_games", 0.30, 0.55, "游戏时间"),
    ("midpoint", 0.45, 0.55, "中点"),
    ("bad_guys_close_in", 0.55, 0.75, "坏人逼近"),
    ("all_is_lost", 0.70, 0.80, "一切尽失"),
    ("dark_night_of_soul", 0.75, 0.85, "灵魂黑夜"),
    ("break_into_three", 0.80, 0.90, "进入第三幕"),
    ("finale", 0.85, 0.98, "结局"),
    ("final_image", 0.95, 1.0, "终场画面"),
]


def load_structure(path: Path) -> list[dict]:
    """加载 structure.jsonl，按 segment_index 排序。"""
    anns = []
    with io.open(path, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            ann = json.loads(line)
            anns.append(ann)
    anns.sort(key=lambda a: a.get("segment_index", 0))
    return anns


# ============================================================================
# P0：弗雷塔格五幕
# ============================================================================
def analyze_freytag(anns: list[dict]) -> dict:
    """从 D01 序列推导弗雷塔格五幕结构。按幕转换点定义区间（非连续块统计）。"""
    total = len(anns)
    if total == 0:
        return {"error": "no segments"}

    # 按顺序提取 D01
    d01_sequence = [(i, a["layers"]["structure"].get("D01", "无法判断")) for i, a in enumerate(anns)]

    # 统计各幕出现次数
    acts_count = defaultdict(int)
    for idx, d01 in d01_sequence:
        act = FREYTAG_MAP.get(d01, "transition")
        acts_count[act] += 1

    # 按顺序识别各幕的首次出现位置（幕转换点）
    first_occurrence = {}
    for idx, d01 in d01_sequence:
        act = FREYTAG_MAP.get(d01, "transition")
        if act not in first_occurrence:
            first_occurrence[act] = idx

    # 定义幕区间：从该幕首次出现到下一个"主要幕"首次出现（或全书末尾）
    # 主要幕顺序：exposition → inciting_incident → rising_action → climax → falling_action → resolution
    major_acts_order = ["exposition", "inciting_incident", "rising_action", "climax", "falling_action", "resolution"]
    act_ranges = {}
    for i, act in enumerate(major_acts_order):
        if act not in first_occurrence:
            continue
        start = first_occurrence[act]
        # 找下一个主要幕的首次出现位置
        end = total - 1
        for next_act in major_acts_order[i + 1:]:
            if next_act in first_occurrence and first_occurrence[next_act] > start:
                end = first_occurrence[next_act] - 1
                break
        act_ranges[act] = {
            "start_segment": start,
            "end_segment": end,
            "segment_count_in_range": end - start + 1,
            "segment_count_labeled": acts_count.get(act, 0),
            "percentage": round(acts_count.get(act, 0) / total * 100, 1),
        }

    # 识别关键转折点
    inciting_idx = first_occurrence.get("inciting_incident")
    climax_idx = first_occurrence.get("climax")
    resolution_idx = first_occurrence.get("resolution")

    # 结构完整性评估
    required_acts = ["exposition", "inciting_incident", "rising_action", "climax", "falling_action", "resolution"]
    missing_acts = [a for a in required_acts if a not in act_ranges]

    # 五幕占比是否健康（经验法：上升行动应占最大比例）
    rising_pct = act_ranges.get("rising_action", {}).get("percentage", 0)
    structure_health = "healthy" if rising_pct >= 20 and len(missing_acts) <= 1 else "needs_review"

    return {
        "total_segments": total,
        "act_ranges": act_ranges,
        "key_turning_points": {
            "inciting_incident_segment": inciting_idx,
            "climax_segment": climax_idx,
            "resolution_segment": resolution_idx,
        },
        "missing_acts": missing_acts,
        "structure_health": structure_health,
        "derivation_method": "D01_sequence_mapping + act_transition_points",
        "note": "act_ranges 按幕转换点定义区间（非连续块统计）；segment_count_labeled 是该幕标签实际出现次数，segment_count_in_range 是区间内 segment 总数（可能包含其他幕的交错标签）",
    }


# ============================================================================
# P0：热奈特聚焦
# ============================================================================
def analyze_focalization(anns: list[dict]) -> dict:
    """从 D07 统计 + _narrator_identity 推导热奈特聚焦类型。"""
    total = len(anns)
    if total == 0:
        return {"error": "no segments"}

    d07_types = Counter()
    narrator_identities = Counter()
    switch_points = 0
    has_narrator_identity = False

    for a in anns:
        d07 = a["layers"]["structure"].get("D07", {})
        d07_type = d07.get("type", "未知")
        d07_types[d07_type] += 1
        if d07.get("is_switch_point"):
            switch_points += 1
        nid = d07.get("_narrator_identity")
        if nid:
            has_narrator_identity = True
            narrator_identities[nid] += 1

    # 主导聚焦类型
    dominant_type = d07_types.most_common(1)[0][0] if d07_types else "未知"
    dominant_focalization = GENETTE_FOCALIZATION_MAP.get(dominant_type, "unknown")

    # 聚焦复杂度评估
    unique_types = len(d07_types)
    dominant_count = d07_types.most_common(1)[0][1] if d07_types else 0
    dominant_ratio = dominant_count / total if total > 0 else 0
    if dominant_ratio >= 0.95 and switch_points == 0:
        complexity = "simple_single_focalization"
    elif dominant_ratio >= 0.80 and switch_points <= total * 0.1:
        complexity = "moderate_occasional_shift"
    else:
        complexity = "complex_multiple_focalization"

    # 叙述者可靠性
    unreliable_count = d07_types.get("不可靠叙述者", 0)
    narrator_reliability = "unreliable" if unreliable_count > total * 0.1 else "reliable_or_not_marked"

    result = {
        "total_segments": total,
        "dominant_d07_type": dominant_type,
        "dominant_focalization": dominant_focalization,
        "d07_type_distribution": dict(d07_types),
        "focalization_switch_count": switch_points,
        "focalization_switch_rate": round(switch_points / total, 3),
        "complexity": complexity,
        "narrator_reliability": narrator_reliability,
        "derivation_method": "D07_type_statistics",
    }

    if has_narrator_identity:
        result["narrator_identity_distribution"] = dict(narrator_identities)
        result["narrator_identity_count"] = len(narrator_identities)
        result["derivation_method"] += "+_narrator_identity"
    else:
        result["narrator_identity_note"] = "_narrator_identity 字段未填充（v3.6 新字段，旧产物缺失），叙述者身份分析降级为 D07.type 统计"

    return result


# ============================================================================
# P1：叙事时间线
# ============================================================================
def extract_time_marker(time_text: str) -> dict | None:
    """从 D08.time 文本中提取时间标记。"""
    if not time_text or time_text == "null":
        return None

    # 检测年份
    year_match = re.search(r"(\d{3,4})\s*年", time_text)
    # 检测季节
    season_match = re.search(r"(春|夏|秋|冬|春天|夏天|秋天|冬天)", time_text)
    # 检测时间段
    period_match = re.search(r"(上午|下午|中午|晚上|深夜|凌晨|黄昏|黎明|早晨|清晨)", time_text)
    # 检测相对时间
    relative_match = re.search(r"(多年前|多年后|不久前|不久后|几天后|几个月后|一年后|十年后)", time_text)

    return {
        "raw": time_text,
        "year": year_match.group(1) if year_match else None,
        "season": season_match.group(1) if season_match else None,
        "period": period_match.group(1) if period_match else None,
        "relative": relative_match.group(1) if relative_match else None,
    }


def infer_time_type(time_text: str, d01: str) -> str:
    """从 D08.time 文本 + D01 降级推断时间类型（_time_type 缺失时使用）。"""
    if not time_text:
        return "unknown"

    text = time_text

    # 倒叙关键词
    for kw in FLASHBACK_KEYWORDS:
        if kw in text:
            return "flashback"

    # 预叙关键词
    for kw in FLASHFORWARD_KEYWORDS:
        if kw in text:
            return "flashforward"

    # 追叙关键词
    for kw in ANALEPSIS_KEYWORDS:
        if kw in text:
            return "analepsis"

    # 默认线性
    return "linear"


def analyze_timeline(anns: list[dict]) -> dict:
    """从 D08.time 序列 + _time_type 重建叙事时间线。"""
    total = len(anns)
    if total == 0:
        return {"error": "no segments"}

    timeline_nodes = []
    time_types = Counter()
    has_time_type_field = False
    time_jumps = []

    prev_year = None
    prev_segment_idx = None

    for i, a in enumerate(anns):
        d08 = a["layers"]["structure"].get("D08", {})
        time_text = d08.get("time")
        d01 = a["layers"]["structure"].get("D01", "")

        # 优先使用 _time_type
        time_type = d08.get("_time_type")
        if time_type:
            has_time_type_field = True
        else:
            # 降级推断
            time_type = infer_time_type(time_text, d01)

        time_types[time_type] += 1

        # 提取时间标记
        marker = extract_time_marker(time_text)

        node = {
            "segment_index": i,
            "segment_id": a.get("segment_id", ""),
            "time_text": time_text,
            "time_type": time_type,
            "time_marker": marker,
        }
        timeline_nodes.append(node)

        # 检测时间跳跃
        if marker and marker.get("year") and prev_year:
            try:
                year_diff = abs(int(marker["year"]) - int(prev_year))
                if year_diff >= 5:
                    time_jumps.append({
                        "from_segment": prev_segment_idx,
                        "to_segment": i,
                        "year_span": year_diff,
                        "from_year": prev_year,
                        "to_year": marker["year"],
                    })
            except (ValueError, TypeError):
                pass

        if marker and marker.get("year"):
            prev_year = marker["year"]
            prev_segment_idx = i

    # 主导时间结构
    dominant_time_type = time_types.most_common(1)[0][0] if time_types else "unknown"

    # 时间结构复杂度
    nonlinear_count = sum(v for k, v in time_types.items() if k not in ("linear", "unknown"))
    nonlinear_ratio = nonlinear_count / total if total > 0 else 0
    if nonlinear_count == 0 and not time_jumps:
        time_structure = "linear_simple"
    elif nonlinear_ratio <= 0.15 and len(time_jumps) <= 2:
        time_structure = "linear_with_occasional_flashback"
    else:
        time_structure = "complex_nonlinear"

    result = {
        "total_segments": total,
        "dominant_time_type": dominant_time_type,
        "time_type_distribution": dict(time_types),
        "time_structure": time_structure,
        "time_jump_count": len(time_jumps),
        "time_jumps": time_jumps[:10],  # 最多显示 10 个
        "timeline_nodes": timeline_nodes,
        "derivation_method": "_time_type_field" if has_time_type_field else "D08.time_text_keyword_inference（降级：_time_type 字段未填充）",
    }

    return result


# ============================================================================
# P1：救猫咪节拍（简化版）
# ============================================================================
def analyze_save_the_cat(anns: list[dict], freytag: dict) -> dict:
    """从 D01+D05+D08 推导救猫咪节拍（简化 10 节拍定位）。"""
    total = len(anns)
    if total == 0:
        return {"error": "no segments"}

    beats = []
    for beat_id, start_pct, end_pct, beat_name in SAVE_THE_CAT_BEATS:
        start_idx = int(total * start_pct)
        end_idx = min(int(total * end_pct), total - 1)

        # 统计该区间内的 D01 分布
        d01_in_range = Counter()
        d05_in_range = []
        for i in range(start_idx, end_idx + 1):
            if i < len(anns):
                s = anns[i]["layers"]["structure"]
                d01_in_range[s.get("D01", "?")] += 1
                d05 = s.get("D05")
                if d05:
                    d05_in_range.append(d05)

        avg_d05 = round(sum(d05_in_range) / len(d05_in_range), 2) if d05_in_range else None
        dominant_d01 = d01_in_range.most_common(1)[0][0] if d01_in_range else "?"

        beats.append({
            "beat_id": beat_id,
            "beat_name": beat_name,
            "start_segment": start_idx,
            "end_segment": end_idx,
            "percentage_range": f"{int(start_pct*100)}%-{int(end_pct*100)}%",
            "dominant_d01": dominant_d01,
            "avg_d05_pace": avg_d05,
            "segment_count": end_idx - start_idx + 1,
        })

    # 节拍完整性评估（关键节拍：区间内存在对应 D01 信号即视为匹配，非要求主导）
    key_beats = ["catalyst", "midpoint", "all_is_lost", "finale"]
    # 信号映射：每个关键节拍对应的 D01 信号集合（区间内存在任一即匹配）
    signal_map = {
        "catalyst": {"激励事件"},
        "midpoint": {"转折", "高潮"},
        "all_is_lost": {"下降行动", "转折"},
        "finale": {"结局"},
    }
    beats_with_strong_signal = []
    for b in beats:
        if b["beat_id"] in key_beats:
            expected_signals = signal_map.get(b["beat_id"], set())
            # 检查该区间内是否存在期望的 D01 信号
            d01_in_range_set = set()
            for i in range(b["start_segment"], min(b["end_segment"] + 1, len(anns))):
                d01_in_range_set.add(anns[i]["layers"]["structure"].get("D01", "?"))
            if d01_in_range_set & expected_signals:
                beats_with_strong_signal.append(b["beat_id"])

    return {
        "total_segments": total,
        "beats": beats,
        "key_beats_with_strong_signal": beats_with_strong_signal,
        "key_beats_total": len(key_beats),
        "beat_completeness": round(len(beats_with_strong_signal) / len(key_beats) * 100, 1),
        "derivation_method": "position_percentage_mapping + D01_signal_verification",
        "note": "救猫咪节拍为基于位置百分比的粗略定位，非精确节拍检测；需结合 D01 信号验证",
    }


# ============================================================================
# P2：叙事层级图
# ============================================================================
def analyze_narrative_levels(anns: list[dict]) -> dict:
    """从 D08._narrative_level 统计叙事层级。"""
    total = len(anns)
    if total == 0:
        return {"error": "no segments"}

    levels = Counter()
    has_level_field = False

    for a in anns:
        d08 = a["layers"]["structure"].get("D08", {})
        level = d08.get("_narrative_level")
        if level:
            has_level_field = True
            levels[level] += 1
        else:
            levels["unknown"] += 1

    result = {
        "total_segments": total,
        "level_distribution": dict(levels),
        "dominant_level": levels.most_common(1)[0][0] if levels else "unknown",
        "derivation_method": "_narrative_level_field" if has_level_field else "field_not_filled（降级：_narrative_level 未填充，无法分析叙事层级）",
    }

    if not has_level_field:
        result["note"] = "v3.6 新字段 _narrative_level 在旧产物中未填充；建议用 v3.6+ 重新批注后再分析叙事层级"

    return result


# ============================================================================
# 主流程
# ============================================================================
def main() -> int:
    ap = argparse.ArgumentParser(description="v3.7 叙事结构分析（弗雷塔格五幕+热奈特聚焦+叙事时间线+救猫咪节拍）")
    ap.add_argument("--structure", type=Path, required=True, help="structure.jsonl 路径")
    ap.add_argument("--doc-id", type=str, required=True, help="文档 ID")
    ap.add_argument("--output-dir", type=Path, required=True, help="输出目录")
    args = ap.parse_args()

    if not args.structure.exists():
        print(f"[ERROR] structure 文件不存在: {args.structure}", file=sys.stderr)
        return 2

    anns = load_structure(args.structure)
    print(f"[INFO] 加载 {len(anns)} 条 structure 批注")

    # P0
    freytag = analyze_freytag(anns)
    print(f"[INFO] 弗雷塔格五幕：{freytag.get('structure_health', '?')}，缺失幕={freytag.get('missing_acts', [])}")

    focalization = analyze_focalization(anns)
    print(f"[INFO] 热奈特聚焦：{focalization.get('dominant_focalization', '?')}，复杂度={focalization.get('complexity', '?')}")

    # P1
    timeline = analyze_timeline(anns)
    print(f"[INFO] 叙事时间线：{timeline.get('time_structure', '?')}，时间跳跃={timeline.get('time_jump_count', 0)}")

    save_the_cat = analyze_save_the_cat(anns, freytag)
    print(f"[INFO] 救猫咪节拍：关键节拍信号匹配率={save_the_cat.get('beat_completeness', 0)}%")

    # P2
    narrative_levels = analyze_narrative_levels(anns)
    print(f"[INFO] 叙事层级：{narrative_levels.get('dominant_level', '?')}")

    # 汇总输出
    output = {
        "schema_version": SCHEMA_VERSION,
        "document_id": args.doc_id,
        "generated_at": datetime.now().isoformat(),
        "generator": "narrative_structure.py v3.7.0",
        "total_segments": len(anns),
        "freytag_pyramid": freytag,
        "genette_focalization": focalization,
        "narrative_timeline": timeline,
        "save_the_cat_beats": save_the_cat,
        "narrative_levels": narrative_levels,
    }

    args.output_dir.mkdir(parents=True, exist_ok=True)
    out_path = args.output_dir / f"{args.doc_id}_narrative_structure.json"
    io.open(out_path, "w", encoding="utf-8", newline="").write(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n"
    )
    print(f"[OK] 叙事结构分析已写入 {out_path}")
    print(f"[SUMMARY] 弗雷塔格={freytag['structure_health']} 聚焦={focalization['dominant_focalization']} 时间结构={timeline['time_structure']} 节拍匹配={save_the_cat['beat_completeness']}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
