#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v2.9 Step 2 — 场景图重建（Scene Graph）

纯规则引擎（不调 LLM）：
  1. 读取每段的 D08.time/space（时空信息）
  2. 判断相邻段连续性：time 连续 + space 相同 + D01 功能连续 → 合并为同一场景
  3. 场景拆分：time 跳跃或 space 变化 → 新场景
  4. 输出 scene_graph.json（每个场景的起止 segment、时长、地点、功能标签序列、出场角色）

用法：
  python scripts/aggregation/scene_graph.py \
    --segments outputs/annotations/moon_sixpence_zh/moon_sixpence_zh_segments.jsonl \
    --structure outputs/annotations/moon_sixpence_zh/moon_sixpence_zh_structure.jsonl \
    --doc-id moon_sixpence_zh \
    --output-dir outputs/annotations/moon_sixpence_zh/aggregation \
    --entity-graph outputs/annotations/moon_sixpence_zh/aggregation/moon_sixpence_zh_entity_graph.json
"""

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

SCHEMA_VERSION = "2.9.0"

# D01 叙事功能枚举
NARRATIVE_FUNCTIONS = {
    "背景铺垫", "激励事件", "上升行动", "转折", "高潮",
    "下降行动", "结局", "过渡", "复合功能", "无法判断"
}

# 场景合并的功能连续性规则：相邻段如果都是这些功能，倾向于合并
CONTINUOUS_FUNCTIONS = {"背景铺垫", "上升行动", "过渡", "无法判断"}
# 场景边界功能：出现这些功能倾向于开始新场景
BOUNDARY_FUNCTIONS = {"激励事件", "转折", "高潮", "结局"}


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


def extract_spatiotemporal(structure_rows: list[dict]) -> dict[str, dict]:
    """
    从 structure 层提取每段的时空信息和叙事功能。
    返回 {segment_id: {"time": str|None, "space": str|None, "d01": str|None, "d04_intensity": int|None}}
    """
    result = {}
    for row in structure_rows:
        seg_id = row.get("segment_id")
        if not seg_id:
            continue
        layers = row.get("layers", {})
        structure = layers.get("structure", {})
        if not structure:
            # 兼容旧格式（顶层 structure）
            structure = row.get("structure", {})

        d08 = structure.get("D08", {})
        d01 = structure.get("D01")
        d04 = structure.get("D04", {})

        result[seg_id] = {
            "time": d08.get("time") if isinstance(d08, dict) else None,
            "space": d08.get("space") if isinstance(d08, dict) else None,
            "d01": d01 if isinstance(d01, str) else None,
            "d04_intensity": d04.get("intensity") if isinstance(d04, dict) else None,
        }
    return result


def normalize_space(space: str | None) -> str | None:
    """标准化地点名称，去除常见前缀后缀。"""
    if not space:
        return None
    # 去除"在"、"位于"等前缀
    space = re.sub(r'^(在|位于|到了|来到|进入|离开)\s*', '', space)
    # 去除"里"、"中"、"内"等后缀
    space = re.sub(r'\s*(里|中|内|上|下|旁|附近)$', '', space)
    return space.strip() if space.strip() else None


def normalize_time(time_str: str | None) -> dict | None:
    """
    标准化时间描述，尝试解析为可比较的结构。
    返回 {"raw": str, "order_hint": float|None, "is_explicit": bool}
    """
    if not time_str:
        return None

    raw = time_str.strip()
    order_hint = None
    is_explicit = False

    # 尝试匹配明确的时间描述
    time_patterns = [
        (r'(早晨|早上|清晨|黎明|破晓)', 1.0),
        (r'(上午|中午|正午|午时)', 2.0),
        (r'(下午|午后|傍晚|黄昏|日落)', 3.0),
        (r'(晚上|夜里|夜晚|午夜|深夜|子时)', 4.0),
    ]
    for pattern, hint in time_patterns:
        if re.search(pattern, raw):
            order_hint = hint
            is_explicit = True
            break

    # 章节/天数提示
    chapter_match = re.search(r'第([一二三四五六七八九十百千\d]+)[章节回]', raw)
    if chapter_match:
        is_explicit = True

    return {"raw": raw, "order_hint": order_hint, "is_explicit": is_explicit}


def is_time_continuous(prev_time: dict | None, curr_time: dict | None) -> bool:
    """判断相邻两段的时间是否连续。"""
    # 都没有时间信息 → 视为连续（无法判断）
    if not prev_time and not curr_time:
        return True
    # 一个有一个没有 → 视为连续（保守）
    if not prev_time or not curr_time:
        return True
    # 都有明确时间
    if prev_time["is_explicit"] and curr_time["is_explicit"]:
        # 如果有 order_hint，比较顺序
        if prev_time["order_hint"] and curr_time["order_hint"]:
            # 时间顺序不后退 → 连续（同一天内的时间推进）
            return curr_time["order_hint"] >= prev_time["order_hint"]
        # 原始文本相同 → 连续
        return prev_time["raw"] == curr_time["raw"]
    return True


def is_space_same(prev_space: str | None, curr_space: str | None) -> bool:
    """判断相邻两段的地点是否相同。"""
    prev_norm = normalize_space(prev_space)
    curr_norm = normalize_space(curr_space)
    # 都没有地点信息 → 视为相同（无法判断）
    if not prev_norm and not curr_norm:
        return True
    # 一个有一个没有 → 视为相同（保守）
    if not prev_norm or not curr_norm:
        return True
    # 完全相同
    if prev_norm == curr_norm:
        return True
    # 包含关系（如"巴黎"和"巴黎的画室"）
    if prev_norm in curr_norm or curr_norm in prev_norm:
        return True
    return False


def is_function_continuous(prev_d01: str | None, curr_d01: str | None) -> bool:
    """判断相邻两段的叙事功能是否连续（倾向于合并）。"""
    if not prev_d01 or not curr_d01:
        return True
    # 如果当前段是边界功能，倾向于开始新场景
    if curr_d01 in BOUNDARY_FUNCTIONS and prev_d01 not in BOUNDARY_FUNCTIONS:
        return False
    # 如果前一段是结局，当前段应该是新场景
    if prev_d01 == "结局":
        return False
    return True


def build_scenes(segments: list[dict], spatio: dict[str, dict]) -> list[dict]:
    """
    构建场景列表。
    遍历所有段，根据时空连续性和功能连续性决定是否合并到当前场景。
    """
    scenes = []
    current_scene = None

    for i, seg in enumerate(segments):
        seg_id = seg["segment_id"]
        info = spatio.get(seg_id, {})

        # 如果是第一段，创建新场景
        if current_scene is None:
            current_scene = {
                "scene_id": f"scene_{len(scenes) + 1:03d}",
                "start_segment": seg_id,
                "start_index": i,
                "end_segment": seg_id,
                "end_index": i,
                "segments": [seg_id],
                "time_labels": [],
                "space_labels": [],
                "function_sequence": [],
                "intensity_values": [],
            }
            if info.get("time"):
                current_scene["time_labels"].append(info["time"])
            if info.get("space"):
                current_scene["space_labels"].append(info["space"])
            if info.get("d01"):
                current_scene["function_sequence"].append(info["d01"])
            if info.get("d04_intensity"):
                current_scene["intensity_values"].append(info["d04_intensity"])
            continue

        # 获取前一段的信息
        prev_seg_id = segments[i - 1]["segment_id"]
        prev_info = spatio.get(prev_seg_id, {})

        # 判断是否应该开始新场景
        prev_time = normalize_time(prev_info.get("time"))
        curr_time = normalize_time(info.get("time"))
        time_cont = is_time_continuous(prev_time, curr_time)
        space_same = is_space_same(prev_info.get("space"), info.get("space"))
        func_cont = is_function_continuous(prev_info.get("d01"), info.get("d01"))

        # 三个条件都满足 → 合并到当前场景
        if time_cont and space_same and func_cont:
            current_scene["end_segment"] = seg_id
            current_scene["end_index"] = i
            current_scene["segments"].append(seg_id)
            if info.get("time") and info["time"] not in current_scene["time_labels"]:
                current_scene["time_labels"].append(info["time"])
            if info.get("space") and info["space"] not in current_scene["space_labels"]:
                current_scene["space_labels"].append(info["space"])
            if info.get("d01"):
                current_scene["function_sequence"].append(info["d01"])
            if info.get("d04_intensity"):
                current_scene["intensity_values"].append(info["d04_intensity"])
        else:
            # 结束当前场景，开始新场景
            scenes.append(current_scene)
            current_scene = {
                "scene_id": f"scene_{len(scenes) + 1:03d}",
                "start_segment": seg_id,
                "start_index": i,
                "end_segment": seg_id,
                "end_index": i,
                "segments": [seg_id],
                "time_labels": [],
                "space_labels": [],
                "function_sequence": [],
                "intensity_values": [],
            }
            if info.get("time"):
                current_scene["time_labels"].append(info["time"])
            if info.get("space"):
                current_scene["space_labels"].append(info["space"])
            if info.get("d01"):
                current_scene["function_sequence"].append(info["d01"])
            if info.get("d04_intensity"):
                current_scene["intensity_values"].append(info["d04_intensity"])

    # 别忘了最后一个场景
    if current_scene:
        scenes.append(current_scene)

    return scenes


def enrich_scene_with_entities(scene: dict, entity_graph: dict | None) -> dict:
    """用实体图谱丰富场景信息（出场角色）。"""
    if not entity_graph:
        scene["characters_present"] = []
        return scene

    seg_set = set(scene["segments"])
    characters = []
    for entity in entity_graph.get("entities", []):
        entity_segs = set()
        for mention in entity.get("mentions_sample", []):
            if mention.get("segment_id") in seg_set:
                entity_segs.add(mention["segment_id"])
        if entity_segs:
            characters.append({
                "entity_id": entity["entity_id"],
                "name": entity["canonical_name"],
                "mention_count_in_scene": len(entity_segs),
            })
    # 按出场次数降序
    characters.sort(key=lambda c: c["mention_count_in_scene"], reverse=True)
    scene["characters_present"] = characters
    return scene


def main() -> int:
    p = argparse.ArgumentParser(description="v2.9 Step 2 — 场景图重建（Scene Graph）")
    p.add_argument("--segments", required=True, help="segments.jsonl 路径")
    p.add_argument("--structure", required=True, help="structure.jsonl 路径")
    p.add_argument("--doc-id", required=True, help="文档 ID")
    p.add_argument("--output-dir", required=True, help="输出目录")
    p.add_argument("--entity-graph", default=None, help="entity_graph.json 路径（用于丰富场景出场角色）")
    args = p.parse_args()

    segments_path = Path(args.segments)
    structure_path = Path(args.structure)
    if not segments_path.is_file():
        print(f"❌ segments 文件不存在：{segments_path}", file=sys.stderr)
        return 2
    if not structure_path.is_file():
        print(f"❌ structure 文件不存在：{structure_path}", file=sys.stderr)
        return 2

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # 加载数据
    segments = load_jsonl(segments_path)
    structure_rows = load_jsonl(structure_path)
    print(f"📖 加载 segments: {len(segments)} 段, structure: {len(structure_rows)} 行")

    # 加载实体图谱
    entity_graph = None
    if args.entity_graph and Path(args.entity_graph).is_file():
        with open(args.entity_graph, "r", encoding="utf-8") as f:
            entity_graph = json.load(f)
        print(f"📖 加载 entity_graph: {entity_graph.get('total_entities', 0)} 个实体")

    # Step 1: 提取时空信息
    print("\n🚀 Step 1: 提取时空信息...")
    spatio = extract_spatiotemporal(structure_rows)
    has_time = sum(1 for v in spatio.values() if v.get("time"))
    has_space = sum(1 for v in spatio.values() if v.get("space"))
    has_d01 = sum(1 for v in spatio.values() if v.get("d01"))
    print(f"   有 time 信息: {has_time}/{len(spatio)} 段")
    print(f"   有 space 信息: {has_space}/{len(spatio)} 段")
    print(f"   有 D01 信息: {has_d01}/{len(spatio)} 段")

    # Step 2: 构建场景
    print("\n🚀 Step 2: 构建场景...")
    scenes = build_scenes(segments, spatio)
    print(f"   构建了 {len(scenes)} 个场景")

    # Step 3: 丰富场景信息
    print("\n🚀 Step 3: 丰富场景信息（出场角色）...")
    for scene in scenes:
        # 计算场景统计
        scene["segment_count"] = len(scene["segments"])
        scene["primary_time"] = scene["time_labels"][0] if scene["time_labels"] else None
        scene["primary_space"] = scene["space_labels"][0] if scene["space_labels"] else None
        scene["primary_function"] = max(set(scene["function_sequence"]), key=scene["function_sequence"].count) if scene["function_sequence"] else None
        scene["avg_intensity"] = sum(scene["intensity_values"]) / len(scene["intensity_values"]) if scene["intensity_values"] else None
        scene["max_intensity"] = max(scene["intensity_values"]) if scene["intensity_values"] else None
        # 用实体图谱丰富
        enrich_scene_with_entities(scene, entity_graph)

    # Step 4: 构建 scene_graph
    print("\n🚀 Step 4: 构建 scene_graph.json...")
    scene_graph = {
        "doc_id": args.doc_id,
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "total_scenes": len(scenes),
        "total_segments": len(segments),
        "avg_segments_per_scene": round(len(segments) / len(scenes), 2) if scenes else 0,
        "scenes": scenes,
        "_metadata": {
            "method": "rule_based_v2_9",
            "merge_criteria": "time_continuous AND space_same AND function_continuous",
            "boundary_functions": sorted(list(BOUNDARY_FUNCTIONS)),
            "note": "时空信息缺失时采用保守策略（倾向于合并），D08 填充率低会导致场景粒度偏粗",
        },
    }

    # 写入文件
    out_path = out_dir / f"{args.doc_id}_scene_graph.json"
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(scene_graph, f, ensure_ascii=False, indent=2)

    print(f"\n✅ scene_graph.json 已写入: {out_path}")
    print(f"   场景数: {len(scenes)}")
    print(f"   平均每场景段数: {scene_graph['avg_segments_per_scene']}")
    print("\n📊 场景列表（前 15 个）:")
    for scene in scenes[:15]:
        chars = ", ".join(c["name"] for c in scene["characters_present"][:3]) if scene["characters_present"] else "无"
        print(f"   {scene['scene_id']}: {scene['start_segment']}~{scene['end_segment']} "
              f"({scene['segment_count']}段) "
              f"time={scene['primary_time'] or '?'} "
              f"space={scene['primary_space'] or '?'} "
              f"func={scene['primary_function'] or '?'} "
              f"chars=[{chars}]")

    return 0


if __name__ == "__main__":
    sys.exit(main())
