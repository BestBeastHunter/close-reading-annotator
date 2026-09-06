#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v3.0 Step 4 — 因果链生成（Causal Graph）

基于方案文档和专家评审C修正实现：
- 因果边生成源：cross_segment.jsonl 中的"因果"关系 + "伏笔-回收"关系
- D01 功能序列从生成端移到校验端：只用于过滤反向边（target在source之前）和孤立边
- 因果边类型：CAUSE（直接导致）、ENABLE（预设促成/伏笔回收）、PREVENT（阻止/阻碍）
- 每条边有来源（cross_refs ref_id）和置信度

v3.13.1 增强（T-111，ADR-029）：
- 新增 event_hierarchy：核心/卫星事件 + salience_score 显赫度评分
  salience_score = causal_position(0.4) + narrative_length(0.3) + recurrence_frequency(0.3)
- 新增 causal_structure：causal_type（直接/间接/条件因果）+ is_turning_point
- 新增 event_attributes：时间/空间/情感基调/参与者/叙事功能/强度
- 新增 statistics：core_event_count / turning_point_count / avg_salience_score / top_salience_events

用法：
  python scripts/aggregation/causal_graph.py \
    --cross-segment outputs/annotations/moon_sixpence_zh/moon_sixpence_zh_cross_segment.jsonl \
    --structure outputs/annotations/moon_sixpence_zh/moon_sixpence_zh_structure.jsonl \
    --emotion outputs/annotations/moon_sixpence_zh/moon_sixpence_zh_emotion.jsonl \
    --craft outputs/annotations/moon_sixpence_zh/moon_sixpence_zh_craft.jsonl \
    --doc-id moon_sixpence_zh \
    --output-dir outputs/annotations/moon_sixpence_zh/aggregation
"""

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

SCHEMA_VERSION = "3.4.0"

# 因果边类型
EDGE_TYPE_CAUSE = "CAUSE"      # 直接导致
EDGE_TYPE_ENABLE = "ENABLE"    # 预设促成/伏笔回收
EDGE_TYPE_PREVENT = "PREVENT"  # 阻止/阻碍

# cross_segment relation_type → 因果边类型映射
RELATION_TO_EDGE = {
    "因果": EDGE_TYPE_CAUSE,
    "伏笔-回收": EDGE_TYPE_ENABLE,
}

# v3.13.1 新增：显赫度评分权重
SALIENCE_WEIGHTS = {
    "causal_position": 0.4,    # 因果链位置权重
    "narrative_length": 0.3,   # 叙述篇幅占比权重
    "recurrence_frequency": 0.3,  # 重复出现频率权重
}

# v3.13.1 新增：核心事件判定条件
CORE_EVENT_D01 = {"激励事件", "高潮", "转折", "结局"}
CORE_EVENT_SALIENCE_THRESHOLD = 0.7
TURNING_POINT_SALIENCE_THRESHOLD = 0.8
TURNING_POINT_D01 = {"转折", "高潮"}


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


def load_cross_refs(cross_segment_path: Path) -> list[dict]:
    """从 cross_segment.jsonl 加载 cross_refs（单行包含数组）。"""
    if not cross_segment_path.is_file():
        return []
    with cross_segment_path.open("r", encoding="utf-8") as f:
        text = f.read().strip()
    if not text:
        return []
    try:
        data = json.loads(text)
        return data.get("cross_refs", [])
    except json.JSONDecodeError:
        # 尝试按 JSONL 逐行
        refs = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                refs.extend(obj.get("cross_refs", []))
            except json.JSONDecodeError:
                continue
        return refs


def build_d01_index(structure_rows: list[dict]) -> dict[str, str]:
    """构建 segment_id → D01 叙事功能 的索引（用于校验端）。"""
    d01_index = {}
    for row in structure_rows:
        structure = row.get("layers", {}).get("structure", {})
        if not structure:
            structure = row.get("structure", {})
        d01 = structure.get("D01")
        seg_id = row.get("segment_id")
        if d01 and seg_id:
            d01_index[seg_id] = d01
    return d01_index


# ============================================================================
# v3.13.1 新增：事件分析增强函数（T-111）
# ============================================================================

def build_segment_info_index(
    structure_rows: list[dict],
    emotion_rows: list[dict] | None = None,
    craft_rows: list[dict] | None = None,
) -> dict[str, dict]:
    """
    构建 segment_id → 段信息 的索引（用于 event_attributes 和 salience_score）。
    包含：D01叙事功能 / D04强度 / D08时空 / D18人物 / D19情感 / 文本长度 / D09主题。
    """
    info_index = {}

    # 从 structure 提取 D01/D04/D08/D09 + 文本长度
    for row in structure_rows:
        seg_id = row.get("segment_id")
        if not seg_id:
            continue
        structure = row.get("layers", {}).get("structure", {})
        if not structure:
            structure = row.get("structure", {})
        text_span = row.get("text_span", {})
        text_len = len(text_span.get("text", "")) if isinstance(text_span, dict) else 0

        info = {
            "segment_id": seg_id,
            "d01_function": structure.get("D01"),
            "d04_intensity": structure.get("D04", {}).get("intensity") if isinstance(structure.get("D04"), dict) else None,
            "d08_time": structure.get("D08", {}).get("time") if isinstance(structure.get("D08"), dict) else None,
            "d08_space": structure.get("D08", {}).get("space") if isinstance(structure.get("D08"), dict) else None,
            "d09_themes": structure.get("D09") or [],
            "text_length": text_len,
            "emotion_primary": None,
            "emotion_targets": [],
            "characters": [],
        }
        info_index[seg_id] = info

    # 从 emotion 提取 D19 情感
    if emotion_rows:
        for row in emotion_rows:
            seg_id = row.get("segment_id")
            if not seg_id or seg_id not in info_index:
                continue
            emotion = row.get("layers", {}).get("emotion", {})
            if not emotion:
                emotion = row.get("emotion", {})
            d19 = emotion.get("D19_emotion_analysis") or emotion.get("D19") or {}
            if isinstance(d19, dict):
                info_index[seg_id]["emotion_primary"] = d19.get("primary", {}).get("emotion")
                targets = d19.get("target") or []
                if isinstance(targets, list):
                    info_index[seg_id]["emotion_targets"] = [t.get("name") for t in targets if isinstance(t, dict) and t.get("name")]

    # 从 craft 提取 D18 人物
    if craft_rows:
        for row in craft_rows:
            seg_id = row.get("segment_id")
            if not seg_id or seg_id not in info_index:
                continue
            craft = row.get("layers", {}).get("craft", {})
            if not craft:
                craft = row.get("craft", {})
            d18 = craft.get("D18_character_voice") or []
            if isinstance(d18, list):
                chars = [item.get("character") for item in d18 if isinstance(item, dict) and item.get("character")]
                info_index[seg_id]["characters"] = chars

    return info_index


def compute_salience_score(
    seg_id: str,
    edges: list[dict],
    chains: list[dict],
    info_index: dict[str, dict],
    avg_segment_length: float,
) -> dict:
    """
    计算事件显赫度评分（salience_score）。
    salience_score = causal_position(0.4) + narrative_length(0.3) + recurrence_frequency(0.3)
    返回 {level, salience_score, salience_breakdown}
    """
    # 1. causal_position：因果链位置权重
    # 链的起点/终点 = 1.0，中间节点 = 0.7，孤立节点 = 0.3
    in_edges = [e for e in edges if e["target"]["segment_id"] == seg_id]
    out_edges = [e for e in edges if e["source"]["segment_id"] == seg_id]
    is_chain_start = len(out_edges) > 0 and len(in_edges) == 0
    is_chain_end = len(in_edges) > 0 and len(out_edges) == 0
    is_isolated = len(in_edges) == 0 and len(out_edges) == 0

    if is_chain_start or is_chain_end:
        causal_position_weight = 1.0
    elif is_isolated:
        causal_position_weight = 0.3
    else:
        causal_position_weight = 0.7

    # 2. narrative_length：叙述篇幅占比
    info = info_index.get(seg_id, {})
    text_len = info.get("text_length", 0)
    if avg_segment_length > 0:
        length_ratio = min(text_len / avg_segment_length, 2.0) / 2.0  # 归一化到 0-1，超过2倍平均按1.0
    else:
        length_ratio = 0.5
    narrative_length_weight = length_ratio

    # 3. recurrence_frequency：D09 主题标签与前后 5 段的重合度
    seg_idx = get_segment_index(seg_id)
    current_themes = set(info.get("d09_themes", []))
    overlap_count = 0
    total_neighbors = 0
    for offset in range(-5, 6):
        if offset == 0:
            continue
        neighbor_idx = seg_idx + offset
        # 查找对应 segment_id（简单匹配，假设 segment_id 格式为 xxx_seg_NNN）
        neighbor_id = None
        for sid in info_index:
            if get_segment_index(sid) == neighbor_idx:
                neighbor_id = sid
                break
        if neighbor_id:
            neighbor_themes = set(info_index[neighbor_id].get("d09_themes", []))
            if current_themes and neighbor_themes:
                overlap = len(current_themes & neighbor_themes) / len(current_themes | neighbor_themes)
                overlap_count += overlap
            total_neighbors += 1
    recurrence_frequency_weight = overlap_count / total_neighbors if total_neighbors > 0 else 0.3

    # 综合评分
    salience_score = round(
        causal_position_weight * SALIENCE_WEIGHTS["causal_position"] +
        narrative_length_weight * SALIENCE_WEIGHTS["narrative_length"] +
        recurrence_frequency_weight * SALIENCE_WEIGHTS["recurrence_frequency"],
        3,
    )

    # 核心/卫星事件判定
    d01 = info.get("d01_function")
    is_core = salience_score >= CORE_EVENT_SALIENCE_THRESHOLD and d01 in CORE_EVENT_D01
    level = "核心事件" if is_core else "卫星事件"

    return {
        "level": level,
        "salience_score": salience_score,
        "salience_breakdown": {
            "causal_position": round(causal_position_weight, 3),
            "narrative_length": round(narrative_length_weight, 3),
            "recurrence_frequency": round(recurrence_frequency_weight, 3),
        },
    }


def compute_causal_structure(
    seg_id: str,
    edges: list[dict],
    info_index: dict[str, dict],
    salience_score: float,
) -> dict:
    """
    计算因果结构（causal_type + is_turning_point）。
    causal_type：直接因果（CAUSE边为主）/ 间接因果（ENABLE边或多跳）/ 条件因果（PREVENT边）
    is_turning_point：D01 ∈ {转折,高潮} 或 salience_score >= 0.8
    """
    in_edges = [e for e in edges if e["target"]["segment_id"] == seg_id]
    out_edges = [e for e in edges if e["source"]["segment_id"] == seg_id]
    all_edges = in_edges + out_edges

    # causal_type 判定
    if not all_edges:
        causal_type = "无因果关联"
    else:
        cause_count = sum(1 for e in all_edges if e["edge_type"] == EDGE_TYPE_CAUSE)
        enable_count = sum(1 for e in all_edges if e["edge_type"] == EDGE_TYPE_ENABLE)
        prevent_count = sum(1 for e in all_edges if e["edge_type"] == EDGE_TYPE_PREVENT)

        if prevent_count > 0:
            causal_type = "条件因果"
        elif enable_count > cause_count:
            causal_type = "间接因果"
        else:
            causal_type = "直接因果"

    # is_turning_point 判定
    d01 = info_index.get(seg_id, {}).get("d01_function")
    is_turning_point = d01 in TURNING_POINT_D01 or salience_score >= TURNING_POINT_SALIENCE_THRESHOLD

    result = {
        "causal_type": causal_type,
        "is_turning_point": is_turning_point,
    }

    # 转折点证据（可选）
    if is_turning_point:
        evidence_parts = []
        if d01 in TURNING_POINT_D01:
            evidence_parts.append(f"D01={d01}")
        if salience_score >= TURNING_POINT_SALIENCE_THRESHOLD:
            evidence_parts.append(f"salience_score={salience_score}≥{TURNING_POINT_SALIENCE_THRESHOLD}")
        result["turning_point_evidence"] = "；".join(evidence_parts)

    return result


def build_event_attributes(seg_id: str, info_index: dict[str, dict]) -> dict:
    """
    构建事件属性向量（event_attributes）。
    包含：time / space / emotional_tone / participants / narrative_function / intensity
    """
    info = info_index.get(seg_id, {})

    # 参与者：D18 人物 + D19.target 情感对象（去重）
    participants = list(set(
        info.get("characters", []) + info.get("emotion_targets", [])
    ))

    return {
        "time": info.get("d08_time"),
        "space": info.get("d08_space"),
        "emotional_tone": info.get("emotion_primary"),
        "participants": participants,
        "narrative_function": info.get("d01_function"),
        "intensity": info.get("d04_intensity"),
    }


def generate_causal_edges(cross_refs: list[dict], d01_index: dict[str, str]) -> tuple[list[dict], list[dict]]:
    """
    从 cross_refs 生成因果边。
    返回 (有效边, 被过滤的边)。
    """
    edges = []
    filtered = []
    edge_id_counter = 1

    for ref in cross_refs:
        rel_type = ref.get("relation_type")
        if rel_type not in RELATION_TO_EDGE:
            continue  # 只处理因果和伏笔-回收

        source = ref.get("source", {})
        target = ref.get("target", {})
        source_seg = source.get("segment_id")
        target_seg = target.get("segment_id")

        if not source_seg or not target_seg:
            continue

        # 校验端 1：过滤反向边（target 的 segment_index 必须 >= source，否则是反向因果）
        source_idx = get_segment_index(source_seg)
        target_idx = get_segment_index(target_seg)
        if target_idx < source_idx:
            filtered.append({
                "ref_id": ref.get("ref_id"),
                "reason": "反向边（target在source之前）",
                "source": source_seg,
                "target": target_seg,
            })
            continue

        # 校验端 2：过滤孤立边（source 或 target 不在 D01 索引中，说明无结构批注）
        source_d01 = d01_index.get(source_seg)
        target_d01 = d01_index.get(target_seg)
        if not source_d01 or not target_d01:
            filtered.append({
                "ref_id": ref.get("ref_id"),
                "reason": "孤立边（source或target无D01结构批注）",
                "source": source_seg,
                "target": target_seg,
            })
            continue

        # 构建因果边
        edge_type = RELATION_TO_EDGE[rel_type]
        confidence = ref.get("confidence", 0.7)
        # 因果关系置信度略高于伏笔-回收（直接因果更确定）
        if edge_type == EDGE_TYPE_CAUSE:
            confidence = max(confidence, 0.75)
        else:
            confidence = max(confidence, 0.65)

        edge = {
            "edge_id": f"ce_{edge_id_counter:04d}",
            "edge_type": edge_type,
            "source": {
                "segment_id": source_seg,
                "chapter": source.get("chapter"),
                "d01_function": source_d01,
                "anchor_text": source.get("anchor_text"),
            },
            "target": {
                "segment_id": target_seg,
                "chapter": target.get("chapter"),
                "d01_function": target_d01,
                "anchor_text": target.get("anchor_text"),
            },
            "confidence": round(confidence, 2),
            "evidence": {
                "source_ref_id": ref.get("ref_id"),
                "relation_type": rel_type,
                "note": ref.get("note"),
            },
            "validation": {
                "direction_check": "passed",
                "d01_coverage": "passed",
                "validated_by": "d01_function_sequence_v1",
            },
        }
        edges.append(edge)
        edge_id_counter += 1

    return edges, filtered


def build_causal_chains(edges: list[dict]) -> list[dict]:
    """
    从因果边构建因果链（链式路径）。
    简单实现：找出 source→target 的连续路径。
    """
    # 构建邻接表
    adj = defaultdict(list)  # source_seg → [(target_seg, edge)]
    for edge in edges:
        src = edge["source"]["segment_id"]
        tgt = edge["target"]["segment_id"]
        adj[src].append((tgt, edge))

    # 找链（简单 DFS，最长不超过 5 跳）
    chains = []
    chain_id_counter = 1

    def dfs(start_seg: str, path: list[str], path_edges: list[dict], depth: int):
        if depth >= 5:
            return
        for tgt, edge in adj.get(start_seg, []):
            if tgt in path:  # 避免环
                continue
            new_path = path + [tgt]
            new_edges = path_edges + [edge]
            if len(new_path) >= 2:
                chains.append({
                    "chain_id": f"cc_{chain_id_counter:04d}",
                    "length": len(new_path) - 1,
                    "segments": new_path,
                    "edge_ids": [e["edge_id"] for e in new_edges],
                    "edge_types": [e["edge_type"] for e in new_edges],
                    "start_d01": new_edges[0]["source"]["d01_function"],
                    "end_d01": new_edges[-1]["target"]["d01_function"],
                })
            dfs(tgt, new_path, new_edges, depth + 1)

    # 从每个有出边的节点开始
    for src in adj:
        dfs(src, [src], [], 0)

    # 去重（按 segments 序列）
    seen = set()
    unique_chains = []
    for chain in chains:
        key = tuple(chain["segments"])
        if key not in seen:
            seen.add(key)
            unique_chains.append(chain)

    # 按长度降序
    unique_chains.sort(key=lambda c: c["length"], reverse=True)
    return unique_chains[:20]  # 最多保留 20 条链


def main() -> int:
    p = argparse.ArgumentParser(description="v3.0 Step 4 — 因果链生成（Causal Graph）")
    p.add_argument("--cross-segment", required=True, help="cross_segment.jsonl 路径")
    p.add_argument("--structure", required=True, help="structure.jsonl 路径（用于D01校验端）")
    p.add_argument("--emotion", default=None, help="emotion.jsonl 路径（v3.13.1 可选，用于event_attributes情感基调）")
    p.add_argument("--craft", default=None, help="craft.jsonl 路径（v3.13.1 可选，用于event_attributes参与者）")
    p.add_argument("--doc-id", required=True, help="文档 ID")
    p.add_argument("--output-dir", required=True, help="输出目录")
    args = p.parse_args()

    cross_path = Path(args.cross_segment)
    structure_path = Path(args.structure)
    emotion_path = Path(args.emotion) if args.emotion else None
    craft_path = Path(args.craft) if args.craft else None

    for path, name in [(cross_path, "cross_segment"), (structure_path, "structure")]:
        if not path.is_file():
            print(f"❌ {name} 文件不存在：{path}", file=sys.stderr)
            return 2
    for path, name in [(emotion_path, "emotion"), (craft_path, "craft")]:
        if path and not path.is_file():
            print(f"⚠️  {name} 文件不存在，跳过（event_attributes 对应字段将为 null）：{path}", file=sys.stderr)
            if name == "emotion":
                emotion_path = None
            else:
                craft_path = None

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # 加载数据
    cross_refs = load_cross_refs(cross_path)
    structure_rows = load_jsonl(structure_path)
    emotion_rows = load_jsonl(emotion_path) if emotion_path else []
    craft_rows = load_jsonl(craft_path) if craft_path else []
    d01_index = build_d01_index(structure_rows)

    print(f"📖 加载 cross_refs: {len(cross_refs)} 条")
    print(f"📖 加载 structure: {len(structure_rows)} 行, D01索引: {len(d01_index)} 段")
    if emotion_rows:
        print(f"📖 加载 emotion: {len(emotion_rows)} 行")
    if craft_rows:
        print(f"📖 加载 craft: {len(craft_rows)} 行")

    # v3.13.1 新增：构建 segment_info_index（用于 event_attributes 和 salience_score）
    info_index = build_segment_info_index(structure_rows, emotion_rows, craft_rows)
    # 计算平均段长
    total_length = sum(info.get("text_length", 0) for info in info_index.values())
    avg_segment_length = total_length / len(info_index) if info_index else 0
    print(f"📊 平均段长: {avg_segment_length:.0f} 字符")

    # 统计 cross_refs 类型分布
    from collections import Counter
    rel_types = Counter(r.get("relation_type") for r in cross_refs)
    print(f"📊 cross_refs 类型分布: {dict(rel_types)}")

    # 生成因果边
    print("\n🚀 Step 1: 从 cross_refs 生成因果边（D01校验端过滤反向边和孤立边）...")
    edges, filtered = generate_causal_edges(cross_refs, d01_index)
    print(f"   生成因果边: {len(edges)} 条")
    print(f"   被过滤: {len(filtered)} 条")
    for f_item in filtered:
        print(f"     ✖ {f_item['ref_id']}: {f_item['reason']} ({f_item['source']} → {f_item['target']})")

    # 边类型分布
    edge_types = Counter(e["edge_type"] for e in edges)
    print(f"   边类型分布: {dict(edge_types)}")

    # 构建因果链
    print("\n🚀 Step 2: 构建因果链（链式路径）...")
    chains = build_causal_chains(edges)
    print(f"   生成因果链: {len(chains)} 条")
    for chain in chains[:5]:
        print(f"     {chain['chain_id']}: {chain['length']}跳, {chain['start_d01']}→{chain['end_d01']}, 边={chain['edge_types']}")

    # 构建 causal_graph
    print("\n🚀 Step 3: 构建 causal_graph.json...")

    # v3.13.1 新增：为每个 node 计算 event_hierarchy / causal_structure / event_attributes
    node_ids = sorted(set(
        [e["source"]["segment_id"] for e in edges] +
        [e["target"]["segment_id"] for e in edges]
    ))
    nodes_enhanced = []
    core_event_count = 0
    satellite_event_count = 0
    turning_point_count = 0
    salience_scores = []

    for seg_id in node_ids:
        salience_result = compute_salience_score(seg_id, edges, chains, info_index, avg_segment_length)
        causal_result = compute_causal_structure(seg_id, edges, info_index, salience_result["salience_score"])
        event_attrs = build_event_attributes(seg_id, info_index)

        node_info = {
            "segment_id": seg_id,
            "d01_function": info_index.get(seg_id, {}).get("d01_function"),
            "chapter": None,  # 从 edge 中获取
            "event_hierarchy": salience_result,
            "causal_structure": causal_result,
            "event_attributes": event_attrs,
        }

        # 从 edge 中获取 chapter
        for e in edges:
            if e["source"]["segment_id"] == seg_id:
                node_info["chapter"] = e["source"].get("chapter")
                break
            if e["target"]["segment_id"] == seg_id:
                node_info["chapter"] = e["target"].get("chapter")
                break

        nodes_enhanced.append(node_info)
        salience_scores.append(salience_result["salience_score"])

        if salience_result["level"] == "核心事件":
            core_event_count += 1
        else:
            satellite_event_count += 1
        if causal_result["is_turning_point"]:
            turning_point_count += 1

    # v3.13.1 新增：为每个 edge 新增 causal_type / is_turning_point
    for edge in edges:
        target_seg = edge["target"]["segment_id"]
        target_salience = next(
            (n["event_hierarchy"]["salience_score"] for n in nodes_enhanced if n["segment_id"] == target_seg),
            0.5,
        )
        edge["causal_type"] = "直接因果" if edge["edge_type"] == EDGE_TYPE_CAUSE else (
            "间接因果" if edge["edge_type"] == EDGE_TYPE_ENABLE else "条件因果"
        )
        edge["is_turning_point"] = target_salience >= TURNING_POINT_SALIENCE_THRESHOLD

    # 统计
    avg_salience = round(sum(salience_scores) / len(salience_scores), 3) if salience_scores else 0
    top_salience = sorted(nodes_enhanced, key=lambda n: n["event_hierarchy"]["salience_score"], reverse=True)[:5]
    top_salience_events = [
        {
            "segment_id": n["segment_id"],
            "salience_score": n["event_hierarchy"]["salience_score"],
            "d01_function": n["d01_function"],
            "level": n["event_hierarchy"]["level"],
        }
        for n in top_salience
    ]

    causal_graph = {
        "doc_id": args.doc_id,
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "causal_graph": {
            "nodes": nodes_enhanced,
            "edges": edges,
            "chains": chains,
        },
        "statistics": {
            "total_edges": len(edges),
            "cause_edges": edge_types.get(EDGE_TYPE_CAUSE, 0),
            "enable_edges": edge_types.get(EDGE_TYPE_ENABLE, 0),
            "prevent_edges": edge_types.get(EDGE_TYPE_PREVENT, 0),
            "total_chains": len(chains),
            "max_chain_length": max((c["length"] for c in chains), default=0),
            "filtered_edges": len(filtered),
            "source_cross_refs": len(cross_refs),
            # v3.13.1 新增
            "core_event_count": core_event_count,
            "satellite_event_count": satellite_event_count,
            "turning_point_count": turning_point_count,
            "avg_salience_score": avg_salience,
            "top_salience_events": top_salience_events,
        },
        "validation": {
            "method": "d01_function_sequence_v1",
            "description": "D01从生成端移到校验端：只过滤反向边（target在source之前）和孤立边（无D01批注），不用于生成边",
            "direction_check": f"{len(edges)} 条通过方向校验",
            "d01_coverage": f"{len(edges)} 条两端均有D01批注",
            "filtered_details": filtered,
        },
        "_metadata": {
            "method": "rule_based_v3_13_1",
            "edge_sources": ["cross_segment.因果", "cross_segment.伏笔-回收"],
            "note": "纯规则引擎，基于cross_segment已有关系；D01仅用于校验端过滤，不生成边（专家评审C修正）。v3.13.1新增event_hierarchy/causal_structure/event_attributes和salience_score显赫度评分。",
            "salience_formula": "causal_position(0.4) + narrative_length(0.3) + recurrence_frequency(0.3)",
            "core_event_criteria": f"salience_score>={CORE_EVENT_SALIENCE_THRESHOLD} 且 D01∈{sorted(CORE_EVENT_D01)}",
        },
    }

    # 写入文件
    out_path = out_dir / f"{args.doc_id}_causal_graph.json"
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(causal_graph, f, ensure_ascii=False, indent=2)

    print(f"\n✅ causal_graph.json 已写入: {out_path}")
    print(f"   总边数: {len(edges)}, 因果链: {len(chains)}, 被过滤: {len(filtered)}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
