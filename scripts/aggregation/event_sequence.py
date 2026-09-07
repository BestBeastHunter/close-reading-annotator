#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/aggregation/event_sequence.py — 事件序列聚合（v3.18.0 新增，aggregation schema 3.6.0）

把全书事件按叙事顺序组织为独立的事件表：以运行时便签本（scratchpad）的 events 为主序
（真实事件描述/参与者/类型/状态），对齐因果图（段级事件层级/显赫度/因果结构）、场景图
（场景归属）、结构层（D01 功能 + D08 时空）、实体图（参与者别名→规范名）后输出
{doc_id}_event_sequence.json。事件分析模块的独立产物（此前事件能力分散于 causal_graph /
narrative_structure / cross_segment，本脚本将其收敛为可读、可排序、可统计的事件序列）。

输入（除 --segments 外均可缺失，缺失时自动降级）：
  --segments      segments.jsonl（段序）
  --structure     structure.jsonl（D01 功能 + D08 时空）
  --scratchpad    {doc_id}_scratchpad.json（事件主源；缺失时降级为因果图段级事件）
  --causal-graph  aggregation/{doc_id}_causal_graph.json（事件层级/显赫度/因果边）
  --scene-graph   aggregation/{doc_id}_scene_graph.json（场景归属）
  --entity-graph  aggregation/{doc_id}_entity_graph.json（参与者规范名）

输出：
  {doc_id}_event_sequence.json
  顶层：doc_id / schema_version / generated_at / total_events /
        event_sequence[]（按段序排列，每事件含 event_id/segment_id/description/
        event_type/status/d01_function/time/space/scene_id/participants/
        hierarchy{salience}/causal{type,turning_point,in_edges,out_edges}）/
        statistics（核心/卫星/转折计数、类型与 D01 分布、top salience 事件）/_metadata

依赖：纯 stdlib（Python 3.8+），零第三方依赖，跨平台。
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

SCHEMA_VERSION = "3.6.0"

# v2.5.1 修复 #1：Windows GBK 控制台 UnicodeEncodeError
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


# ============================================================================
# 读取辅助
# ============================================================================

def _load_json(path: Path) -> dict | None:
    if not path or not path.is_file():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def _load_jsonl(path: Path) -> list[dict]:
    out: list[dict] = []
    if not path or not path.is_file():
        return out
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s:
                continue
            try:
                d = json.loads(s)
                if isinstance(d, dict):
                    out.append(d)
            except json.JSONDecodeError:
                continue
    return out


def _get_structure_layer(row: dict) -> dict:
    """兼容 merged/顶层结构等行形态。"""
    return (row.get("layers") or {}).get("structure") or row.get("structure") or {}


# ============================================================================
# 数据装配
# ============================================================================

def _build_segment_index(segments_rows: list[dict]) -> dict[str, int]:
    """segment_id → 段序（0 起）。"""
    idx: dict[str, int] = {}
    for i, row in enumerate(segments_rows):
        sid = row.get("segment_id")
        if sid:
            idx[sid] = i
    return idx


def _build_structure_map(structure_rows: list[dict]) -> dict[str, dict]:
    """segment_id → {d01, time, space}。"""
    m: dict[str, dict] = {}
    for row in structure_rows:
        sid = row.get("segment_id") or row.get("annotation_id", "").split("_ann_")[0]
        lay = _get_structure_layer(row)
        d01 = lay.get("D01")
        d08 = lay.get("D08") or {}
        if isinstance(d01, dict):
            d01 = d01.get("function") or d01.get("value")
        m[sid] = {
            "d01": d01 if isinstance(d01, str) else None,
            "time": (d08.get("time") if isinstance(d08, dict) else None) or None,
            "space": (d08.get("space") if isinstance(d08, dict) else None) or None,
        }
    return m


def _build_causal_map(causal_data: dict | None) -> tuple[dict[str, dict], list[dict]]:
    """segment_id → {d01_function, event_hierarchy, causal_structure}；edges 列表。"""
    node_map: dict[str, dict] = {}
    edges: list[dict] = []
    if not causal_data:
        return node_map, edges
    cg = causal_data.get("causal_graph") or causal_data
    if not isinstance(cg, dict):
        return node_map, edges
    for n in cg.get("nodes") or []:
        sid = n.get("segment_id")
        if sid:
            node_map[sid] = {
                "d01_function": n.get("d01_function"),
                "event_hierarchy": n.get("event_hierarchy") or {},
                "causal_structure": n.get("causal_structure") or {},
            }
    for e in cg.get("edges") or []:
        edges.append(e)
    return node_map, edges


def _build_scene_map(scene_data: dict | None) -> dict[str, str]:
    """segment_id → scene_id。"""
    m: dict[str, str] = {}
    if not scene_data:
        return m
    sg = scene_data.get("scene_graph") or scene_data
    if not isinstance(sg, dict):
        return m
    for scene in sg.get("scenes") or []:
        sid0 = scene.get("scene_id")
        for seg in scene.get("segments") or []:
            m[seg] = sid0
    return m


def _build_entity_maps(entity_data: dict | None) -> tuple[set[str], dict[str, str], dict[str, list[str]]]:
    """(canonical 集合, alias→canonical 映射, segment_id→在场 canonical 列表)。"""
    canon: set[str] = set()
    alias2canon: dict[str, str] = {}
    presence: dict[str, list[str]] = {}
    if not entity_data:
        return canon, alias2canon, presence
    eg = entity_data.get("entity_graph") or entity_data
    if not isinstance(eg, dict):
        return canon, alias2canon, presence
    for ent in eg.get("entities") or []:
        c = ent.get("canonical_name")
        if not c:
            continue
        canon.add(c)
        for a in ent.get("aliases") or []:
            if isinstance(a, str) and a:
                alias2canon[a] = c
        for sid in ent.get("segment_ids") or []:
            if isinstance(sid, str) and sid:
                presence.setdefault(sid, []).append(c)
    for sid in presence:
        presence[sid] = sorted(set(presence[sid]))
    return canon, alias2canon, presence


def _normalize_participant(name: str, canon: set[str], alias2canon: dict[str, str]) -> str:
    name = (name or "").strip()
    if not name:
        return ""
    if name in canon:
        return name
    if name in alias2canon:
        return alias2canon[name]
    return name


# ============================================================================
# 主流程
# ============================================================================

def build_event_sequence(
    segments_rows: list[dict],
    structure_rows: list[dict],
    scratchpad: dict | None,
    causal_data: dict | None,
    scene_data: dict | None,
    entity_data: dict | None,
    doc_id: str,
) -> dict:
    seg_idx = _build_segment_index(segments_rows)
    struct_map = _build_structure_map(structure_rows)
    causal_map, causal_edges = _build_causal_map(causal_data)
    scene_map = _build_scene_map(scene_data)
    canon, alias2canon, presence_map = _build_entity_maps(entity_data)

    # 事件主源：scratchpad.events（真实事件）；缺失时降级为因果图段级事件
    raw_events: list[dict] = []
    if scratchpad and isinstance(scratchpad.get("events"), list):
        for e in scratchpad["events"]:
            raw_events.append({
                "event_id": e.get("event_id") or f"evt_{len(raw_events) + 1:03d}",
                "description": (e.get("description") or "").strip(),
                "segment_id": e.get("segment_id"),
                "involved_characters": e.get("involved_characters") or [],
                "event_type": e.get("event_type"),
                "status": e.get("status", "open"),
                "_source": "scratchpad",
            })
    else:
        # 降级：因果图 nodes（每段一个事件，description 用 D01 功能名）
        for sid, info in sorted(causal_map.items(), key=lambda kv: seg_idx.get(kv[0], 10**9)):
            d01 = info.get("d01_function")
            raw_events.append({
                "event_id": f"evt_{len(raw_events) + 1:03d}",
                "description": d01 or "",
                "segment_id": sid,
                "involved_characters": [],
                "event_type": d01,
                "status": "closed",
                "_source": "causal_graph_nodes",
            })

    # 因果边按段聚合（source/target 匹配事件所在段）
    in_edges_by_seg: dict[str, list[str]] = {}
    out_edges_by_seg: dict[str, list[str]] = {}
    for e in causal_edges:
        src = (e.get("source") or {}).get("segment_id")
        tgt = (e.get("target") or {}).get("segment_id")
        eid = e.get("edge_id") or ""
        if src:
            out_edges_by_seg.setdefault(src, []).append(eid)
        if tgt:
            in_edges_by_seg.setdefault(tgt, []).append(eid)

    event_sequence: list[dict] = []
    for ev in raw_events:
        sid = ev.get("segment_id")
        s_info = struct_map.get(sid, {})
        c_info = causal_map.get(sid, {})
        participants = [
            p for p in (
                _normalize_participant(x, canon, alias2canon)
                for x in ev.get("involved_characters") or []
            ) if p
        ]
        event_sequence.append({
            "event_id": ev["event_id"],
            "segment_id": sid,
            "description": ev["description"],
            "event_type": ev.get("event_type"),
            "status": ev.get("status"),
            "d01_function": s_info.get("d01") or c_info.get("d01_function"),
            "time": s_info.get("time"),
            "space": s_info.get("space"),
            "scene_id": scene_map.get(sid) if sid else None,
            "participants": participants,
            "present_characters": presence_map.get(sid, []) if sid else [],
            "hierarchy": c_info.get("event_hierarchy") or {},
            "causal": {
                "causal_type": (c_info.get("causal_structure") or {}).get("causal_type"),
                "is_turning_point": (c_info.get("causal_structure") or {}).get("is_turning_point"),
                "in_edges": in_edges_by_seg.get(sid, []) if sid else [],
                "out_edges": out_edges_by_seg.get(sid, []) if sid else [],
            },
            "source": ev.get("_source"),
        })

    # 按段序排序（无段信息的事件排最后，保持稳定）
    event_sequence.sort(key=lambda x: (seg_idx.get(x["segment_id"], 10**9), x["event_id"]))

    # 统计
    hierarchy_counter = Counter()
    turning_count = 0
    type_counter = Counter()
    d01_counter = Counter()
    salience_items: list[dict] = []
    for ev in event_sequence:
        level = (ev["hierarchy"] or {}).get("level")
        if level:
            hierarchy_counter[level] += 1
        if ev["causal"].get("is_turning_point"):
            turning_count += 1
        if ev.get("event_type"):
            type_counter[str(ev["event_type"])] += 1
        if ev.get("d01_function"):
            d01_counter[str(ev["d01_function"])] += 1
        sal = (ev["hierarchy"] or {}).get("salience_score")
        if isinstance(sal, (int, float)):
            salience_items.append({
                "event_id": ev["event_id"],
                "description": ev["description"][:50],
                "segment_id": ev["segment_id"],
                "salience_score": round(float(sal), 3),
            })
    salience_items.sort(key=lambda x: x["salience_score"], reverse=True)

    return {
        "doc_id": doc_id,
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "total_events": len(event_sequence),
        "event_sequence": event_sequence,
        "statistics": {
            "core_event_count": hierarchy_counter.get("核心事件", 0),
            "satellite_event_count": hierarchy_counter.get("卫星事件", 0),
            "hierarchy_levels": dict(hierarchy_counter),
            "turning_point_count": turning_count,
            "by_event_type": dict(type_counter),
            "by_d01_function": dict(d01_counter),
            "top_salience_events": salience_items[:10],
        },
        "_metadata": {
            "skill_version": "3.18.0",
            "event_source": "scratchpad" if (scratchpad and isinstance(scratchpad.get("events"), list)) else "causal_graph_nodes_fallback",
            "tokenizer_note": "事件描述来自运行时便签本（批注过程累积）；无 scratchpad 时降级为因果图段级事件",
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description="事件序列聚合（v3.18.0）：以 scratchpad 事件为主序，对齐因果图/场景图/结构层/实体图，输出全书事件表")
    ap.add_argument("--segments", type=Path, required=True, help="segments.jsonl（段序）")
    ap.add_argument("--structure", type=Path, default=None, help="structure.jsonl（D01/D08）")
    ap.add_argument("--scratchpad", type=Path, default=None, help="{doc_id}_scratchpad.json（事件主源）")
    ap.add_argument("--causal-graph", type=Path, default=None, help="aggregation/{doc_id}_causal_graph.json")
    ap.add_argument("--scene-graph", type=Path, default=None, help="aggregation/{doc_id}_scene_graph.json")
    ap.add_argument("--entity-graph", type=Path, default=None, help="aggregation/{doc_id}_entity_graph.json")
    ap.add_argument("--doc-id", required=True, help="文档 ID")
    ap.add_argument("--output-dir", type=Path, default=None, help="输出目录（默认当前）")
    args = ap.parse_args()

    if not args.segments.is_file():
        print(f"[ERROR] segments 不存在: {args.segments}", file=sys.stderr)
        return 2

    out_dir = args.output_dir or Path.cwd()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{args.doc_id}_event_sequence.json"

    segments_rows = _load_jsonl(args.segments)
    structure_rows = _load_jsonl(args.structure) if args.structure else []
    scratchpad = _load_json(args.scratchpad) if args.scratchpad else None
    causal_data = _load_json(args.causal_graph) if args.causal_graph else None
    scene_data = _load_json(args.scene_graph) if args.scene_graph else None
    entity_data = _load_json(args.entity_graph) if args.entity_graph else None

    result = build_event_sequence(
        segments_rows, structure_rows, scratchpad,
        causal_data, scene_data, entity_data, args.doc_id,
    )

    # 原子写（先写临时文件再替换，避免半写产物）
    tmp = out_path.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    tmp.replace(out_path)

    src = result["_metadata"]["event_source"]
    print(f"[OK] 事件序列已写入 {out_path.name}：{result['total_events']} 事件"
          f"（核心 {result['statistics']['core_event_count']} / 卫星 {result['statistics']['satellite_event_count']}"
          f" / 转折 {result['statistics']['turning_point_count']}；来源 {src}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
