#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v3.0 Step 6.1 — 故事图合并（Story Graph Assembly）

合并所有子图谱为单一 story_graph.json：
- entity_graph（实体图谱）
- scene_graph（场景图）
- character_arcs（角色弧线）
- causal_graph（因果图）
- object_chains（物件链）
- story_metadata（故事类型推断，可选）

用法：
  python scripts/aggregation/story_graph.py \
    --aggregation-dir outputs/annotations/moon_sixpence_zh/aggregation \
    --doc-id moon_sixpence_zh \
    --output-dir outputs/annotations/moon_sixpence_zh/aggregation
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

# 期望的子图谱文件名后缀
EXPECTED_SUBGRAPHS = [
    ("entity_graph", "实体图谱"),
    ("scene_graph", "场景图"),
    ("character_arcs", "角色弧线"),
    ("causal_graph", "因果图"),
    ("object_chains", "物件链"),
]
OPTIONAL_SUBGRAPHS = [
    ("story_metadata", "故事类型推断"),
]


def load_json(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def main() -> int:
    p = argparse.ArgumentParser(description="v3.0 Step 6.1 — 故事图合并（Story Graph Assembly）")
    p.add_argument("--aggregation-dir", required=True, help="聚合产物目录（包含各子图谱JSON）")
    p.add_argument("--doc-id", required=True, help="文档 ID")
    p.add_argument("--output-dir", required=True, help="输出目录")
    args = p.parse_args()

    agg_dir = Path(args.aggregation_dir)
    if not agg_dir.is_dir():
        print(f"❌ 聚合目录不存在：{agg_dir}", file=sys.stderr)
        return 2

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # 加载所有子图谱
    print(f"📂 聚合目录: {agg_dir}")
    subgraphs = {}
    missing = []

    for suffix, name in EXPECTED_SUBGRAPHS:
        path = agg_dir / f"{args.doc_id}_{suffix}.json"
        data = load_json(path)
        if data is None:
            missing.append(f"{name} ({path.name})")
            print(f"  ⚠️ 缺失: {name} ({path.name})")
        else:
            subgraphs[suffix] = data
            print(f"  ✅ 加载: {name} ({path.name})")

    # 加载可选子图谱
    for suffix, name in OPTIONAL_SUBGRAPHS:
        path = agg_dir / f"{args.doc_id}_{suffix}.json"
        data = load_json(path)
        if data is not None:
            subgraphs[suffix] = data
            print(f"  ✅ 加载(可选): {name} ({path.name})")

    if missing:
        print(f"\n⚠️ 警告: {len(missing)} 个必需子图谱缺失，合并结果将不完整")
    else:
        print(f"\n✅ 全部 {len(EXPECTED_SUBGRAPHS)} 个必需子图谱加载成功")

    # 构建 story_graph
    print("\n🚀 构建 story_graph.json...")

    # 提取各子图谱的核心数据
    story_graph = {
        "doc_id": args.doc_id,
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "story_graph": {
            # 实体图谱
            "entities": subgraphs.get("entity_graph", {}).get("entities", []),
            "entity_statistics": {
                "total_entities": subgraphs.get("entity_graph", {}).get("total_entities", 0),
                "total_mentions": subgraphs.get("entity_graph", {}).get("total_mentions", 0),
            },
            # 场景图
            "scenes": subgraphs.get("scene_graph", {}).get("scenes", []),
            "scene_statistics": {
                "total_scenes": subgraphs.get("scene_graph", {}).get("total_scenes", 0),
                "avg_segments_per_scene": subgraphs.get("scene_graph", {}).get("avg_segments_per_scene", 0),
            },
            # 角色弧线
            "character_arcs": subgraphs.get("character_arcs", {}).get("character_arcs", []),
            "character_arc_statistics": {
                "total_characters": subgraphs.get("character_arcs", {}).get("total_characters", 0),
                "total_trajectory_points": subgraphs.get("character_arcs", {}).get("total_trajectory_points", 0),
            },
            # 因果图
            "causal_edges": subgraphs.get("causal_graph", {}).get("causal_graph", {}).get("edges", []),
            "causal_chains": subgraphs.get("causal_graph", {}).get("causal_graph", {}).get("chains", []),
            "causal_statistics": subgraphs.get("causal_graph", {}).get("statistics", {}),
            # 物件链
            "object_chains": subgraphs.get("object_chains", {}).get("object_chains", []),
            "object_chain_statistics": subgraphs.get("object_chains", {}).get("statistics", {}),
        },
        # 故事元数据（可选，来自故事类型推断）
        "story_metadata": subgraphs.get("story_metadata", {}).get("story_metadata"),
        "story_summary": subgraphs.get("story_metadata", {}).get("summary"),
        # 全局统计
        "global_statistics": {
            "subgraphs_loaded": len(subgraphs),
            "subgraphs_missing": missing,
            "total_entities": subgraphs.get("entity_graph", {}).get("total_entities", 0),
            "total_scenes": subgraphs.get("scene_graph", {}).get("total_scenes", 0),
            "total_characters": subgraphs.get("character_arcs", {}).get("total_characters", 0),
            "total_causal_edges": subgraphs.get("causal_graph", {}).get("statistics", {}).get("total_edges", 0),
            "total_object_chains": subgraphs.get("object_chains", {}).get("statistics", {}).get("total_chains", 0),
        },
        "_metadata": {
            "method": "assembly_v3_0",
            "subgraph_sources": [f"{args.doc_id}_{s}.json" for s, _ in EXPECTED_SUBGRAPHS],
            "note": "合并5个子图谱为单一story_graph；各子图谱保留原始结构，全局统计用于快速概览",
        },
    }

    # 写入文件
    out_path = out_dir / f"{args.doc_id}_story_graph.json"
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(story_graph, f, ensure_ascii=False, indent=2)

    # 打印统计
    gs = story_graph["global_statistics"]
    print(f"\n✅ story_graph.json 已写入: {out_path}")
    print(f"   子图谱: {gs['subgraphs_loaded']} 个加载, {len(gs['subgraphs_missing'])} 个缺失")
    print(f"   实体: {gs['total_entities']}, 场景: {gs['total_scenes']}, 角色: {gs['total_characters']}")
    print(f"   因果边: {gs['total_causal_edges']}, 物件链: {gs['total_object_chains']}")

    if story_graph.get("story_summary"):
        print(f"   故事类型: {story_graph['story_summary'].get('one_line', 'N/A')}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
