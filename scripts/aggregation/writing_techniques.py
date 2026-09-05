#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v3.8 — 叙事技法分析（Writing Techniques Analysis）

基于 Backgrounds/精读批注skill优化方案.md 实现。
纯规则引擎（不调 LLM），完全基于现有字段的序列模式匹配：
  1. 转场技巧（transitions）—— 时间转场/空间转场/细节过渡/悬念转场
  2. 悬念设置（suspense）—— 设疑法/连环设悬/伏笔-回收对/悬念留白
  3. 蒙太奇手法（montage）—— 平行蒙太奇/交叉蒙太奇/对比蒙太奇
  4. 钩子类型（hooks）—— 悬念钩子/行动钩子/情感钩子/场景钩子

用法：
  python scripts/aggregation/writing_techniques.py \
    --structure outputs/annotations/moon_sixpence_zh/moon_sixpence_zh_structure.jsonl \
    --interpretation outputs/annotations/moon_sixpence_zh/moon_sixpence_zh_interpretation.jsonl \
    --cross-segment outputs/annotations/moon_sixpence_zh/moon_sixpence_zh_cross_segment.jsonl \
    --doc-id moon_sixpence_zh \
    --output-dir outputs/annotations/moon_sixpence_zh/aggregation
"""

from __future__ import annotations

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

# 设疑法疑问词（D06 content 中包含这些词 → 设疑法）
SUSPENSE_QUESTION_WORDS = ["为什么", "怎么", "究竟", "难道", "莫非", "到底", "谁知", "不料",
                             "竟然", "居然", "未曾想", "殊不知", "谁曾想", "岂料", "偏偏"]

# 悬念留白阈值：D06 隐藏后多少段内无揭示 → 视为留白
SUSPENSE_UNRESOLVED_THRESHOLD = 5

# 蒙太奇窗口大小
MONTAGE_WINDOW = 5
PARALLEL_MONTAGE_SPACE_CHANGES = 3
CROSS_MONTAGE_SWITCHES = 2

# 对比蒙太奇强度阈值
CONTRAST_MONTAGE_INTENSITY = 5

# 季节关键词
SEASON_KEYWORDS = ["春", "夏", "秋", "冬", "春天", "夏天", "秋天", "冬天", "春季", "夏季", "秋季", "冬季"]

# 时间转场阈值：年份差≥2 或季节变化才算明显时间转场
TIME_TRANSITION_YEAR_GAP = 2


def extract_year(text: str) -> int | None:
    """从时间文本中提取第一个 4 位年份。"""
    if not text:
        return None
    m = re.search(r"\b(1[5-9]\d{2}|20\d{2})\b", text)
    return int(m.group(1)) if m else None


def extract_season(text: str) -> str | None:
    """从时间文本中提取季节。"""
    if not text:
        return None
    for kw in SEASON_KEYWORDS:
        if kw in text:
            return kw[0]  # 返回"春夏秋冬"单字
    return None


def extract_location_keyword(text: str) -> str | None:
    """从空间文本中提取主要地点关键词（取第一个逗号/分号/；前的地点，去掉修饰词）。"""
    if not text:
        return None
    # 取第一个主要地点（逗号/分号/（ 之前的部分）
    primary = re.split(r"[，,；;（(]", text)[0].strip()
    # 去掉"法国（...）"这类括号注
    primary = re.sub(r"[（(].*?[)）]", "", primary).strip()
    return primary if primary else None


def build_interp_index(interpretation: list[dict]) -> dict[str, dict]:
    """按 segment_id 建立 interpretation 索引。"""
    idx = {}
    for ann in interpretation:
        seg_id = ann.get("segment_id", "")
        if seg_id:
            idx[seg_id] = ann
    return idx


# ---------------------------------------------------------------------------
# 加载
# ---------------------------------------------------------------------------
def load_jsonl(path: Path) -> list[dict]:
    rows = []
    with io.open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def load_cross_segment(path: Path) -> list[dict]:
    """cross_segment.jsonl 只有 1 条记录，顶层含 cross_refs 数组。"""
    if not path.exists():
        return []
    with io.open(path, encoding="utf-8") as f:
        data = json.loads(f.readline())
    return data.get("cross_refs", [])


# ---------------------------------------------------------------------------
# 1. 转场技巧
# ---------------------------------------------------------------------------
def analyze_transitions(structure: list[dict]) -> dict:
    """检测相邻段之间的转场类型。使用提取的年份/季节/地点关键词，避免文本微变化导致虚高。"""
    transitions = []
    time_transitions = 0
    space_transitions = 0
    detail_transitions = 0
    suspense_transitions = 0

    for i in range(1, len(structure)):
        prev = structure[i - 1]["layers"]["structure"]
        curr = structure[i]["layers"]["structure"]
        prev_d08 = prev.get("D08", {})
        curr_d08 = curr.get("D08", {})
        prev_time = (prev_d08.get("time") or "").strip()
        curr_time = (curr_d08.get("time") or "").strip()
        prev_space = (prev_d08.get("space") or "").strip()
        curr_space = (curr_d08.get("space") or "").strip()
        prev_d01 = prev.get("D01", "")
        curr_d01 = curr.get("D01", "")

        transition_types = []

        # 时间转场：提取年份/季节，只有明显变化才算
        prev_year = extract_year(prev_time)
        curr_year = extract_year(curr_time)
        prev_season = extract_season(prev_time)
        curr_season = extract_season(curr_time)
        is_time_jump = False
        year_span = 0
        season_changed = False

        if prev_year and curr_year:
            year_span = abs(curr_year - prev_year)
            if year_span >= TIME_TRANSITION_YEAR_GAP:
                is_time_jump = True
        if prev_season and curr_season and prev_season != curr_season:
            season_changed = True
            # 同一年内季节变化也算转场（如春→秋）
            if not is_time_jump:
                is_time_jump = True

        if is_time_jump:
            transition_types.append({
                "type": "时间转场",
                "from_time": prev_time[:60],
                "to_time": curr_time[:60],
                "year_span": year_span,
                "season_changed": season_changed,
            })
            time_transitions += 1

        # 空间转场：提取主要地点关键词，只有关键词变化才算
        prev_loc = extract_location_keyword(prev_space)
        curr_loc = extract_location_keyword(curr_space)
        if prev_loc and curr_loc and prev_loc != curr_loc:
            transition_types.append({
                "type": "空间转场",
                "from_location": prev_loc,
                "to_location": curr_loc,
            })
            space_transitions += 1

        # 细节过渡：D01 从"背景铺垫"→"过渡"→"上升行动"（平滑过渡）
        if prev_d01 == "背景铺垫" and curr_d01 == "过渡":
            transition_types.append({"type": "细节过渡", "pattern": "背景铺垫→过渡"})
            detail_transitions += 1
        elif prev_d01 == "过渡" and curr_d01 == "上升行动":
            transition_types.append({"type": "细节过渡", "pattern": "过渡→上升行动"})
            detail_transitions += 1

        # 悬念转场：段尾高潮/转折 → 下段下降/背景（硬切）
        if prev_d01 in ("高潮", "转折") and curr_d01 in ("下降行动", "背景铺垫", "结局"):
            transition_types.append({
                "type": "悬念转场",
                "from_d01": prev_d01,
                "to_d01": curr_d01,
                "pattern": f"{prev_d01}→{curr_d01}（硬切）",
            })
            suspense_transitions += 1

        if transition_types:
            transitions.append({
                "from_segment_index": i - 1,
                "to_segment_index": i,
                "from_segment_id": structure[i - 1].get("segment_id", ""),
                "to_segment_id": structure[i].get("segment_id", ""),
                "transition_types": transition_types,
            })

    total = len(transitions)
    return {
        "total_transitions": total,
        "time_transitions": time_transitions,
        "space_transitions": space_transitions,
        "detail_transitions": detail_transitions,
        "suspense_transitions": suspense_transitions,
        "transition_density": round(total / max(len(structure) - 1, 1), 3),
        "transitions": transitions[:50],  # 最多保留 50 条详情
        "truncated": len(transitions) > 50,
    }


# ---------------------------------------------------------------------------
# 2. 悬念设置
# ---------------------------------------------------------------------------
def analyze_suspense(structure: list[dict], interpretation: list[dict], cross_refs: list[dict]) -> dict:
    """检测悬念设置模式。使用 segment_id 索引。"""
    # 按 segment_id 建 interpretation 索引
    interp_by_id = build_interp_index(interpretation)

    setup_questions = []  # 设疑法
    serial_suspense = []  # 连环设悬
    unresolved = []  # 悬念留白

    # 遍历 structure，检测 D06 隐藏模式
    hide_segments = []  # (segment_index, segment_id, content)
    for i, ann in enumerate(structure):
        seg_id = ann.get("segment_id", "")
        interp = interp_by_id.get(seg_id, {})
        d06 = interp.get("layers", {}).get("interpretation", {}).get("D06_information_control")
        if d06 and isinstance(d06, dict) and d06.get("type") == "隐藏":
            content = d06.get("content", "")
            hide_segments.append((i, seg_id, content))

            # 设疑法：content 含疑问词
            matched_words = [w for w in SUSPENSE_QUESTION_WORDS if w in content]
            if matched_words:
                setup_questions.append({
                    "segment_index": i,
                    "segment_id": seg_id,
                    "question_words": matched_words,
                    "content_excerpt": content[:100],
                })

    # 连环设悬：连续 ≥3 段 D06 隐藏
    if len(hide_segments) >= 3:
        indices = [h[0] for h in hide_segments]
        run_start = 0
        for j in range(1, len(indices)):
            if indices[j] != indices[j - 1] + 1:
                if j - run_start >= 3:
                    serial_suspense.append({
                        "start_segment_index": indices[run_start],
                        "end_segment_index": indices[j - 1],
                        "length": j - run_start,
                        "segment_ids": [hide_segments[k][1] for k in range(run_start, j)],
                    })
                run_start = j
        # 检查最后一段
        if len(indices) - run_start >= 3:
            serial_suspense.append({
                "start_segment_index": indices[run_start],
                "end_segment_index": indices[-1],
                "length": len(indices) - run_start,
                "segment_ids": [hide_segments[k][1] for k in range(run_start, len(indices))],
            })

    # 悬念留白：D06 隐藏后 SUSPENSE_UNRESOLVED_THRESHOLD 段内无揭示
    for hide_idx, hide_seg_id, hide_content in hide_segments:
        has_reveal = False
        for k in range(hide_idx + 1, min(hide_idx + 1 + SUSPENSE_UNRESOLVED_THRESHOLD, len(structure))):
            next_seg_id = structure[k].get("segment_id", "")
            interp = interp_by_id.get(next_seg_id, {})
            d06 = interp.get("layers", {}).get("interpretation", {}).get("D06_information_control")
            if d06 and isinstance(d06, dict) and d06.get("type") == "揭示":
                has_reveal = True
                break
        if not has_reveal:
            unresolved.append({
                "segment_index": hide_idx,
                "segment_id": hide_seg_id,
                "content_excerpt": hide_content[:100],
                "unresolved_window": SUSPENSE_UNRESOLVED_THRESHOLD,
            })

    # 伏笔-回收对：从 cross_refs 提取
    foreshadow_pairs = []
    for ref in cross_refs:
        if ref.get("relation_type") == "伏笔-回收":
            foreshadow_pairs.append({
                "ref_id": ref.get("ref_id", ""),
                "foreshadow_segment": ref.get("source", {}).get("segment_id", ""),
                "payoff_segment": ref.get("target", {}).get("segment_id", ""),
                "foreshadow_anchor": ref.get("source", {}).get("anchor_text", "")[:80],
                "payoff_anchor": ref.get("target", {}).get("anchor_text", "")[:80],
                "confidence": ref.get("confidence", 0),
            })

    total_hide = len(hide_segments)
    suspense_intensity = "low"
    if total_hide >= 10 or len(foreshadow_pairs) >= 5:
        suspense_intensity = "high"
    elif total_hide >= 5 or len(foreshadow_pairs) >= 2:
        suspense_intensity = "moderate"

    return {
        "total_hidden_segments": total_hide,
        "setup_questions_count": len(setup_questions),
        "serial_suspense_count": len(serial_suspense),
        "unresolved_suspense_count": len(unresolved),
        "foreshadow_payoff_pairs": len(foreshadow_pairs),
        "suspense_intensity": suspense_intensity,
        "setup_questions": setup_questions[:20],
        "serial_suspense_runs": serial_suspense[:10],
        "unresolved_suspense": unresolved[:20],
        "foreshadow_pairs_detail": foreshadow_pairs[:20],
        "derivation_method": "D06_hide_pattern_sequence + cross_refs_foreshadow_payoff",
    }


# ---------------------------------------------------------------------------
# 3. 蒙太奇手法
# ---------------------------------------------------------------------------
def analyze_montage(structure: list[dict]) -> dict:
    """检测蒙太奇手法。"""
    parallel_montage = []  # 平行蒙太奇
    cross_montage = []  # 交叉蒙太奇
    contrast_montage = []  # 对比蒙太奇

    n = len(structure)

    # 平行蒙太奇：滑动窗口内地点关键词变化 ≥3 次
    for start in range(n - MONTAGE_WINDOW + 1):
        window = structure[start:start + MONTAGE_WINDOW]
        locations = []
        for ann in window:
            space = (ann["layers"]["structure"].get("D08", {}).get("space") or "").strip()
            loc = extract_location_keyword(space)
            if loc:
                locations.append(loc)
        # 统计地点变化次数
        changes = 0
        for j in range(1, len(locations)):
            if locations[j] != locations[j - 1]:
                changes += 1
        if changes >= PARALLEL_MONTAGE_SPACE_CHANGES:
            parallel_montage.append({
                "start_segment_index": start,
                "end_segment_index": start + MONTAGE_WINDOW - 1,
                "window_size": MONTAGE_WINDOW,
                "location_changes": changes,
                "locations_in_window": list(dict.fromkeys(locations)),  # 去重保序
            })

    # 交叉蒙太奇：D05≥4 且 D01 在上升/高潮/转折间快速切换
    high_pace_segments = []
    for i, ann in enumerate(structure):
        d05 = ann["layers"]["structure"].get("D05", 0)
        d01 = ann["layers"]["structure"].get("D01", "")
        if d05 >= 4 and d01 in ("上升行动", "高潮", "转折"):
            high_pace_segments.append((i, d01))

    # 检测 ≤3 段内 D01 切换 ≥2 次
    for j in range(len(high_pace_segments) - 1):
        idx_j, d01_j = high_pace_segments[j]
        switches = 0
        switch_d01s = [d01_j]
        for k in range(j + 1, min(j + 4, len(high_pace_segments))):
            idx_k, d01_k = high_pace_segments[k]
            if idx_k - idx_j <= 3 and d01_k != d01_j:
                switches += 1
                switch_d01s.append(d01_k)
        if switches >= CROSS_MONTAGE_SWITCHES:
            cross_montage.append({
                "start_segment_index": idx_j,
                "end_segment_index": high_pace_segments[min(j + 3, len(high_pace_segments) - 1)][0],
                "d01_switches": switches,
                "d01_sequence": switch_d01s,
            })

    # 对比蒙太奇：相邻段 D04 polarity 相反且 intensity≥5
    for i in range(1, n):
        prev_d04 = structure[i - 1]["layers"]["structure"].get("D04", {})
        curr_d04 = structure[i]["layers"]["structure"].get("D04", {})
        prev_pol = prev_d04.get("polarity", "")
        curr_pol = curr_d04.get("polarity", "")
        prev_int = prev_d04.get("intensity", 0)
        curr_int = curr_d04.get("intensity", 0)
        # polarity 相反：positive vs negative，或 mixed 与任一极性
        is_contrast = False
        if prev_pol in ("positive",) and curr_pol in ("negative",):
            is_contrast = True
        elif prev_pol in ("negative",) and curr_pol in ("positive",):
            is_contrast = True
        elif prev_pol == "mixed" and curr_pol in ("positive", "negative"):
            is_contrast = True
        elif curr_pol == "mixed" and prev_pol in ("positive", "negative"):
            is_contrast = True

        if is_contrast and prev_int >= CONTRAST_MONTAGE_INTENSITY and curr_int >= CONTRAST_MONTAGE_INTENSITY:
            contrast_montage.append({
                "from_segment_index": i - 1,
                "to_segment_index": i,
                "from_emotion": prev_d04.get("core", ""),
                "to_emotion": curr_d04.get("core", ""),
                "from_polarity": prev_pol,
                "to_polarity": curr_pol,
                "from_intensity": prev_int,
                "to_intensity": curr_int,
            })

    montage_density = round((len(parallel_montage) + len(cross_montage) + len(contrast_montage)) / max(n, 1), 3)
    total_montage = len(parallel_montage) + len(cross_montage) + len(contrast_montage)

    return {
        "parallel_montage_count": len(parallel_montage),
        "cross_montage_count": len(cross_montage),
        "contrast_montage_count": len(contrast_montage),
        "total_montage_instances": total_montage,
        "montage_density": montage_density,
        "parallel_montage": parallel_montage[:15],
        "cross_montage": cross_montage[:15],
        "contrast_montage": contrast_montage[:20],
        "derivation_method": "sliding_window_location_change + D05_pace + D01_function_switch + D04_polarity_contrast",
    }


# ---------------------------------------------------------------------------
# 4. 钩子类型
# ---------------------------------------------------------------------------
def analyze_hooks(structure: list[dict], interpretation: list[dict]) -> dict:
    """检测段尾/段首钩子类型。使用 segment_id 索引和地点关键词。"""
    interp_by_id = build_interp_index(interpretation)

    suspense_hooks = []  # 悬念钩子
    action_hooks = []  # 行动钩子
    emotion_hooks = []  # 情感钩子
    scene_hooks = []  # 场景钩子

    n = len(structure)

    for i, ann in enumerate(structure):
        seg_id = ann.get("segment_id", "")
        struct = ann["layers"]["structure"]
        d01 = struct.get("D01", "")
        d04 = struct.get("D04", {})
        d05 = struct.get("D05", 0)
        d08 = struct.get("D08", {})
        space = (d08.get("space") or "").strip()
        loc = extract_location_keyword(space)

        interp = interp_by_id.get(seg_id, {})
        d06 = interp.get("layers", {}).get("interpretation", {}).get("D06_information_control")

        # 悬念钩子：段尾 D06 隐藏 或 D01=转折
        if (d06 and isinstance(d06, dict) and d06.get("type") == "隐藏") or d01 == "转折":
            suspense_hooks.append(seg_id)

        # 行动钩子：D05≥4 或 D01=高潮
        if d05 >= 4 or d01 == "高潮":
            action_hooks.append(seg_id)

        # 情感钩子：D04 intensity≥7
        intensity = d04.get("intensity", 0)
        if intensity >= 7:
            emotion_hooks.append(seg_id)

        # 场景钩子：段首地点关键词与上一段不同（新场景开场）
        if i > 0:
            prev_space = (structure[i - 1]["layers"]["structure"].get("D08", {}).get("space") or "").strip()
            prev_loc = extract_location_keyword(prev_space)
            if loc and prev_loc and loc != prev_loc:
                scene_hooks.append(seg_id)

    total_hooks = len(set(suspense_hooks + action_hooks + emotion_hooks + scene_hooks))

    return {
        "total_hooked_segments": total_hooks,
        "suspense_hooks_count": len(suspense_hooks),
        "action_hooks_count": len(action_hooks),
        "emotion_hooks_count": len(emotion_hooks),
        "scene_hooks_count": len(scene_hooks),
        "hook_density": round(total_hooks / max(n, 1), 3),
        "suspense_hook_segments": suspense_hooks[:30],
        "action_hook_segments": action_hooks[:30],
        "emotion_hook_segments": emotion_hooks[:30],
        "scene_hook_segments": scene_hooks[:30],
        "derivation_method": "segment_tail_D01_D04_D05_D06 + segment_head_location_keyword_change",
    }


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description="叙事技法分析（v3.8 / T-037 / ADR-014 决定 5）")
    ap.add_argument("--structure", type=Path, required=True, help="structure.jsonl 路径")
    ap.add_argument("--interpretation", type=Path, required=True, help="interpretation.jsonl 路径")
    ap.add_argument("--cross-segment", type=Path, default=None, help="cross_segment.jsonl 路径（可选）")
    ap.add_argument("--doc-id", type=str, required=True, help="文档 ID")
    ap.add_argument("--output-dir", type=Path, required=True, help="输出目录")
    args = ap.parse_args()

    missing = [p for p in (args.structure, args.interpretation) if not p.exists()]
    if missing:
        print(f"[ERROR] 文件不存在: {[str(m) for m in missing]}", file=sys.stderr)
        return 2

    structure = load_jsonl(args.structure)
    interpretation = load_jsonl(args.interpretation)
    cross_refs = load_cross_segment(args.cross_segment) if args.cross_segment else []

    print(f"[INFO] 加载 {len(structure)} 条 structure / {len(interpretation)} 条 interpretation / {len(cross_refs)} 条 cross_refs")

    # 1. 转场技巧
    transitions = analyze_transitions(structure)
    print(f"[INFO] 转场技巧：总{transitions['total_transitions']}处（时间{transitions['time_transitions']}/空间{transitions['space_transitions']}/细节{transitions['detail_transitions']}/悬念{transitions['suspense_transitions']}）")

    # 2. 悬念设置
    suspense = analyze_suspense(structure, interpretation, cross_refs)
    print(f"[INFO] 悬念设置：隐藏段{suspense['total_hidden_segments']}/设疑{suspense['setup_questions_count']}/连环设悬{suspense['serial_suspense_count']}/留白{suspense['unresolved_suspense_count']}/伏笔回收{suspense['foreshadow_payoff_pairs']}，强度={suspense['suspense_intensity']}")

    # 3. 蒙太奇手法
    montage = analyze_montage(structure)
    print(f"[INFO] 蒙太奇：平行{montage['parallel_montage_count']}/交叉{montage['cross_montage_count']}/对比{montage['contrast_montage_count']}，密度={montage['montage_density']}")

    # 4. 钩子类型
    hooks = analyze_hooks(structure, interpretation)
    print(f"[INFO] 钩子：悬念{hooks['suspense_hooks_count']}/行动{hooks['action_hooks_count']}/情感{hooks['emotion_hooks_count']}/场景{hooks['scene_hooks_count']}，总{hooks['total_hooked_segments']}段")

    # 综合技法评估
    total_techniques = (transitions["total_transitions"] + suspense["total_hidden_segments"] +
                         montage["parallel_montage_count"] + montage["cross_montage_count"] +
                         montage["contrast_montage_count"] + hooks["total_hooked_segments"])
    technique_density = round(total_techniques / max(len(structure), 1), 2)

    if technique_density >= 3.0:
        overall_style = "技法密集型（高技巧写作）"
    elif technique_density >= 1.5:
        overall_style = "技法均衡型（标准叙事）"
    else:
        overall_style = "技法简约型（白描/自然主义）"

    output = {
        "schema_version": SCHEMA_VERSION,
        "document_id": args.doc_id,
        "generated_at": datetime.now().isoformat(),
        "generator": "writing_techniques.py v3.8.0",
        "total_segments": len(structure),
        "overall_assessment": {
            "total_technique_instances": total_techniques,
            "technique_density_per_segment": technique_density,
            "writing_style": overall_style,
            "dominant_techniques": sorted([
                ("转场", transitions["total_transitions"]),
                ("悬念", suspense["total_hidden_segments"]),
                ("蒙太奇", montage["parallel_montage_count"] + montage["cross_montage_count"] + montage["contrast_montage_count"]),
                ("钩子", hooks["total_hooked_segments"]),
            ], key=lambda x: -x[1]),
            "note": "规则粗筛结果（同因果链架构）；转场/蒙太奇/场景钩子使用提取的地点关键词（extract_location_keyword）而非完整 D08.space 文本，避免文本微变化导致虚高；时间转场阈值为年份差≥2 或季节变化。后续可用 LLM 精排。",
        },
        "transitions": transitions,
        "suspense": suspense,
        "montage": montage,
        "hooks": hooks,
    }

    args.output_dir.mkdir(parents=True, exist_ok=True)
    out_path = args.output_dir / f"{args.doc_id}_writing_techniques.json"
    with io.open(out_path, "w", encoding="utf-8", newline="") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"[OK] 叙事技法分析已写入 {out_path}")
    print(f"[SUMMARY] 技法密度={technique_density}/段 风格={overall_style} 转场={transitions['total_transitions']} 悬念={suspense['total_hidden_segments']} 蒙太奇={montage['parallel_montage_count']+montage['cross_montage_count']+montage['contrast_montage_count']} 钩子={hooks['total_hooked_segments']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
