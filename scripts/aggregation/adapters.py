#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v3.0 Step 6.2-6.4 — 适配器层（Adapters）

将 story_graph.json 转换为三种叙事分析格式：
1. text2story 格式：参与者(participants) + 事件(events) + 时间(times) + 地点(places)
2. YARN 格式：事件链(event chain) + 修辞关系(rhetorical relations)
3. NCP 格式：叙事内容协议(Narrative Content Protocol)，含角色/事件/场景/因果

用法：
  python scripts/aggregation/adapters.py \
    --story-graph outputs/annotations/moon_sixpence_zh/aggregation/moon_sixpence_zh_story_graph.json \
    --doc-id moon_sixpence_zh \
    --output-dir outputs/annotations/moon_sixpence_zh/aggregation/adapters \
    --formats text2story,yarn,ncp
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

SCHEMA_VERSION = "3.0.0"


def load_story_graph(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


# ==================== text2story 适配器 ====================

def adapt_text2story(story_graph: dict, doc_id: str) -> dict:
    """
    转换为 text2story 格式。
    text2story 是一个从文本提取叙事结构的工具，输出包含：
    - participants: 参与者（角色）
    - events: 事件（叙事功能段）
    - times: 时间表达式
    - places: 地点表达式
    """
    sg = story_graph.get("story_graph", {})
    # v3.0.1 修复（T-029 P1-1①）：participants.type 不再依赖不存在的 entity_type——
    # entity_graph 无 entity_type 字段（曾导致全员误标 ORG）。实体图谱的提取目标即角色指称
    # （D19.target / D18.character / 原文人名 NER），故人物实体统一标 PER；
    # 非人物实体（地点/意象误入）属于 entity_resolution 消解质量问题，不在适配器层兜底。

    # 参与者（来自实体图谱；entity_graph 语义即人物实体 → 统一 PER）
    participants = []
    for entity in sg.get("entities", []):
        participants.append({
            "id": entity.get("entity_id", f"p{len(participants)+1}"),
            "name": entity.get("canonical_name", ""),
            "type": "PER",
            "aliases": entity.get("aliases", []),
            "mention_count": entity.get("occurrence_count", 0),
            "segment_count": entity.get("segment_count", 0),
        })

    # 事件（来自场景图，每个场景作为一个事件）
    # v3.0.1 修复（T-029 P1-1①）：text/tense/participants 对齐上游真实字段——
    # 场景无 scene_summary/time/characters，真实字段为 primary_function / primary_time / characters_present
    events = []
    for i, scene in enumerate(sg.get("scenes", []), 1):
        func = scene.get("primary_function") or "未知功能"
        # primary_time 缺失时依次回退 time_labels 首项；仍无 → "未知"（诚实标记数据缺失，非占位）
        tense = (scene.get("primary_time")
                 or (scene.get("time_labels") or [""])[0]
                 or "未知")
        events.append({
            "id": f"e{i:03d}",
            "class": "Event",
            "text": f"{func}（{scene.get('start_segment','')}~{scene.get('end_segment','')}）",
            "tense": tense,
            "participants": scene.get("characters_present", []),
            "start_segment": scene.get("start_segment", ""),
            "end_segment": scene.get("end_segment", ""),
            "function_sequence": scene.get("function_sequence", []),
        })

    # 时间（来自场景的 primary_time 字段）
    times = []
    seen_times = set()
    for scene in sg.get("scenes", []):
        t = scene.get("primary_time")
        if t and t not in seen_times:
            seen_times.add(t)
            times.append({
                "id": f"t{len(times)+1:03d}",
                "text": t,
                "type": "DATE",
                "anchored_to": scene.get("start_segment", ""),
            })

    # 地点（来自场景的 primary_space 字段）
    places = []
    seen_places = set()
    for scene in sg.get("scenes", []):
        p = scene.get("primary_space")
        if p and p not in seen_places:
            seen_places.add(p)
            places.append({
                "id": f"pl{len(places)+1:03d}",
                "text": p,
                "type": "LOC",
                "anchored_to": scene.get("start_segment", ""),
            })

    return {
        "doc_id": doc_id,
        "format": "text2story",
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "participants": participants,
        "events": events,
        "times": times,
        "places": places,
        "statistics": {
            "participant_count": len(participants),
            "event_count": len(events),
            "time_count": len(times),
            "place_count": len(places),
        },
        "_metadata": {
            "source": "story_graph.json",
            "note": "从story_graph转换：实体→participants，场景→events，D08.time→times，D08.space→places",
        },
    }


# ==================== YARN 适配器 ====================

def adapt_yarn(story_graph: dict, doc_id: str) -> dict:
    """
    转换为 YARN (Yet Another Rhetorical Network) 格式。
    YARN 是一种叙事结构表示，基于：
    - event_chain: 事件链（按时间顺序的事件序列）
    - rhetorical_relations: 修辞关系（事件之间的修辞连接）
    """
    sg = story_graph.get("story_graph", {})

    # 事件链（来自场景图，按顺序）
    # v3.0.1 修复（T-029 P1-1③）：label 对齐上游真实字段——场景无 scene_summary，
    # 真实语义标签为 primary_function（曾导致全部事件链 label="事件N" 占位）
    event_chain = []
    for i, scene in enumerate(sg.get("scenes", []), 1):
        event_chain.append({
            "event_id": f"evt_{i:03d}",
            "label": scene.get("primary_function", f"事件{i}"),
            "order": i,
            "start_segment": scene.get("start_segment", ""),
            "end_segment": scene.get("end_segment", ""),
            "duration_segments": scene.get("segment_count", 1),
            "location": scene.get("primary_space", ""),
            "time": scene.get("primary_time", ""),
            "characters": scene.get("characters_present", []),
        })

    # 修辞关系（来自因果图的边）
    rhetorical_relations = []
    for i, edge in enumerate(sg.get("causal_edges", []), 1):
        # 映射因果边类型到修辞关系
        edge_type = edge.get("edge_type", "CAUSE")
        if edge_type == "CAUSE":
            rel_type = "cause"
        elif edge_type == "ENABLE":
            rel_type = "enablement"
        elif edge_type == "PREVENT":
            rel_type = "prevention"
        else:
            rel_type = "elaboration"

        rhetorical_relations.append({
            "relation_id": f"rel_{i:03d}",
            "type": rel_type,
            "source_event": edge.get("source", {}).get("segment_id", ""),
            "target_event": edge.get("target", {}).get("segment_id", ""),
            "confidence": edge.get("confidence", 0.7),
            "evidence": edge.get("evidence", {}).get("note", ""),
        })

    # 物件链作为额外的叙事线索
    object_threads = []
    for i, chain in enumerate(sg.get("object_chains", []), 1):
        object_threads.append({
            "thread_id": f"obj_{i:03d}",
            "object_name": chain.get("object_name", ""),
            "object_type": chain.get("object_type", ""),
            "occurrences": chain.get("occurrence_count", 0),
            "segments": chain.get("segments", []),
        })

    return {
        "doc_id": doc_id,
        "format": "YARN",
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "event_chain": event_chain,
        "rhetorical_relations": rhetorical_relations,
        "object_threads": object_threads,
        "statistics": {
            "event_count": len(event_chain),
            "relation_count": len(rhetorical_relations),
            "object_thread_count": len(object_threads),
        },
        "_metadata": {
            "source": "story_graph.json",
            "note": "从story_graph转换：场景→event_chain，因果边→rhetorical_relations，物件链→object_threads",
        },
    }


# ==================== NCP 适配器 ====================

def adapt_ncp(story_graph: dict, doc_id: str) -> dict:
    """
    转换为 NCP (Narrative Content Protocol) 格式。
    NCP 是一种叙事内容协议，标准化表示：
    - characters: 角色（含弧线）
    - events: 事件（含因果）
    - settings: 场景/设定
    - plot_structure: 情节结构（按叙事功能分段）
    """
    sg = story_graph.get("story_graph", {})

    # 角色（含弧线数据）
    # v3.0.1 修复（T-029 P1-1④）：字段名对齐上游 character_arcs 真实结构——
    # arc_type → arc_classification.arc_type；trajectory_point_count → trajectory_length；
    # trajectory → trajectory_sample（曾导致主角 arc_type=""、trajectory_points=0、emotional_trajectory 恒空）
    characters = []
    for arc in sg.get("character_arcs", []):
        characters.append({
            "character_id": arc.get("entity_id", arc.get("character_id", "")),
            "name": arc.get("canonical_name", ""),
            "gender": arc.get("gender", ""),
            "arc_type": arc.get("arc_classification", {}).get("arc_type", ""),
            "trajectory_points": arc.get("trajectory_length", 0),
            "coverage_rate": arc.get("coverage_rate", 0),
            "d19_coverage": arc.get("d19_coverage", 0),
            "first_appearance": arc.get("first_segment", ""),
            "last_appearance": arc.get("last_segment", ""),
            "emotional_trajectory": [
                {
                    "segment_id": p.get("segment_id", ""),
                    "emotion": p.get("emotion", ""),
                    "intensity": p.get("intensity", 0),
                    "polarity": p.get("polarity", ""),
                }
                for p in (arc.get("trajectory_sample") or [])[:10]  # 最多保留10个点
            ],
        })

    # 事件（含因果关系）
    events = []
    for i, edge in enumerate(sg.get("causal_edges", []), 1):
        events.append({
            "event_id": f"ncp_evt_{i:03d}",
            "source_segment": edge.get("source", {}).get("segment_id", ""),
            "target_segment": edge.get("target", {}).get("segment_id", ""),
            "causal_type": edge.get("edge_type", ""),
            "source_function": edge.get("source", {}).get("d01_function", ""),
            "target_function": edge.get("target", {}).get("d01_function", ""),
            "confidence": edge.get("confidence", 0.7),
        })

    # 场景/设定
    settings = []
    for i, scene in enumerate(sg.get("scenes", []), 1):
        settings.append({
            "setting_id": f"set_{i:03d}",
            "location": scene.get("primary_space", ""),
            "time": scene.get("primary_time", ""),
            "start_segment": scene.get("start_segment", ""),
            "end_segment": scene.get("end_segment", ""),
            "segment_count": scene.get("segment_count", 1),
        })

    # 情节结构（按 D01 叙事功能分组，从场景 primary_function 填充）
    # v3.0.1 修复（T-029 P1-1⑤）：七桶此前初始化后从未填充（死结构）——
    # 现在按场景 primary_function 归类填充，复合功能/无法判断落入 other 桶
    D01_TO_PLOT_BUCKET = {
        "背景铺垫": "exposition",
        "激励事件": "inciting_incident",
        "上升行动": "rising_action",
        "高潮": "climax",
        "下降行动": "falling_action",
        "结局": "resolution",
        "过渡": "transition",
        "复合功能": "other",
        "无法判断": "other",
    }
    plot_structure = {
        "exposition": [],      # 背景铺垫
        "inciting_incident": [],  # 激励事件
        "rising_action": [],   # 上升行动
        "climax": [],          # 高潮
        "falling_action": [],  # 下降行动
        "resolution": [],      # 结局
        "transition": [],      # 过渡
        "other": [],           # 复合功能 / 无法判断
    }
    for scene in sg.get("scenes", []):
        func = scene.get("primary_function") or "无法判断"
        bucket = D01_TO_PLOT_BUCKET.get(func, "other")
        plot_structure[bucket].append({
            "scene_id": scene.get("scene_id", ""),
            "function": func,
            "start_segment": scene.get("start_segment", ""),
            "end_segment": scene.get("end_segment", ""),
            "segment_count": scene.get("segment_count", 1),
        })

    # 故事元数据
    story_metadata = story_graph.get("story_metadata", {})
    story_summary = story_graph.get("story_summary", {})

    return {
        "doc_id": doc_id,
        "format": "NCP",
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "characters": characters,
        "events": events,
        "settings": settings,
        "plot_structure": plot_structure,
        "story_metadata": {
            "genre": story_metadata.get("genre", {}).get("primary", ""),
            "narrative_style": story_metadata.get("narrative_style", {}).get("type", ""),
            "emotion_arc": story_metadata.get("emotion_arc", {}).get("pattern", ""),
            "pace": story_metadata.get("pace", {}).get("type", ""),
            "reader_experience": story_metadata.get("reader_experience", {}).get("primary", ""),
            "one_line_summary": story_summary.get("one_line", ""),
        },
        "statistics": {
            "character_count": len(characters),
            "event_count": len(events),
            "setting_count": len(settings),
        },
        "_metadata": {
            "source": "story_graph.json",
            "note": "从story_graph转换：角色弧线→characters，因果边→events，场景→settings，故事类型→story_metadata",
        },
    }


# ==================== 主函数 ====================

def main() -> int:
    p = argparse.ArgumentParser(description="v3.0 Step 6.2-6.4 — 适配器层（text2story/YARN/NCP）")
    p.add_argument("--story-graph", required=True, help="story_graph.json 路径")
    p.add_argument("--doc-id", required=True, help="文档 ID")
    p.add_argument("--output-dir", required=True, help="输出目录")
    p.add_argument("--formats", default="text2story,yarn,ncp",
                   help="要生成的适配器格式，逗号分隔（默认全部）")
    args = p.parse_args()

    sg_path = Path(args.story_graph)
    if not sg_path.is_file():
        print(f"❌ story_graph 文件不存在：{sg_path}", file=sys.stderr)
        return 2

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # 加载 story_graph
    story_graph = load_story_graph(sg_path)
    print(f"📖 加载 story_graph: {sg_path.name}")
    gs = story_graph.get("global_statistics", {})
    print(f"   实体: {gs.get('total_entities', 0)}, 场景: {gs.get('total_scenes', 0)}, "
          f"角色: {gs.get('total_characters', 0)}, 因果边: {gs.get('total_causal_edges', 0)}, "
          f"物件链: {gs.get('total_object_chains', 0)}")

    formats = [f.strip().lower() for f in args.formats.split(",") if f.strip()]
    print(f"\n🔧 生成适配器格式: {formats}")

    generated = []

    # text2story
    if "text2story" in formats:
        print("\n🚀 转换为 text2story 格式...")
        t2s = adapt_text2story(story_graph, args.doc_id)
        out_path = out_dir / f"{args.doc_id}_text2story.json"
        with out_path.open("w", encoding="utf-8") as f:
            json.dump(t2s, f, ensure_ascii=False, indent=2)
        print(f"   ✅ 已写入: {out_path}")
        print(f"   参与者: {t2s['statistics']['participant_count']}, "
              f"事件: {t2s['statistics']['event_count']}, "
              f"时间: {t2s['statistics']['time_count']}, "
              f"地点: {t2s['statistics']['place_count']}")
        generated.append("text2story")

    # YARN
    if "yarn" in formats:
        print("\n🚀 转换为 YARN 格式...")
        yarn = adapt_yarn(story_graph, args.doc_id)
        out_path = out_dir / f"{args.doc_id}_yarn.json"
        with out_path.open("w", encoding="utf-8") as f:
            json.dump(yarn, f, ensure_ascii=False, indent=2)
        print(f"   ✅ 已写入: {out_path}")
        print(f"   事件链: {yarn['statistics']['event_count']}, "
              f"修辞关系: {yarn['statistics']['relation_count']}, "
              f"物件线索: {yarn['statistics']['object_thread_count']}")
        generated.append("yarn")

    # NCP
    if "ncp" in formats:
        print("\n🚀 转换为 NCP 格式...")
        ncp = adapt_ncp(story_graph, args.doc_id)
        out_path = out_dir / f"{args.doc_id}_ncp.json"
        with out_path.open("w", encoding="utf-8") as f:
            json.dump(ncp, f, ensure_ascii=False, indent=2)
        print(f"   ✅ 已写入: {out_path}")
        print(f"   角色: {ncp['statistics']['character_count']}, "
              f"事件: {ncp['statistics']['event_count']}, "
              f"场景: {ncp['statistics']['setting_count']}")
        print(f"   故事类型: {ncp['story_metadata'].get('one_line_summary', 'N/A')}")
        generated.append("ncp")

    print(f"\n✅ 适配器生成完成: {', '.join(generated)}")
    print(f"   输出目录: {out_dir}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
