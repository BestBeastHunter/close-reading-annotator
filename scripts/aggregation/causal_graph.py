#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v3.0 Step 4 — 因果链生成（Causal Graph）

基于方案文档和专家评审C修正实现：
- 因果边生成源：cross_segment.jsonl 中的"因果"关系 + "伏笔-回收"关系
- D01 功能序列从生成端移到校验端：只用于过滤反向边（target在source之前）和孤立边
- 因果边类型：CAUSE（直接导致）、ENABLE（预设促成/伏笔回收）、PREVENT（阻止/阻碍）
- 每条边有来源（cross_refs ref_id）和置信度

用法：
  python scripts/aggregation/causal_graph.py \
    --cross-segment outputs/annotations/moon_sixpence_zh/moon_sixpence_zh_cross_segment.jsonl \
    --structure outputs/annotations/moon_sixpence_zh/moon_sixpence_zh_structure.jsonl \
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

SCHEMA_VERSION = "3.0.0"

# 因果边类型
EDGE_TYPE_CAUSE = "CAUSE"      # 直接导致
EDGE_TYPE_ENABLE = "ENABLE"    # 预设促成/伏笔回收
EDGE_TYPE_PREVENT = "PREVENT"  # 阻止/阻碍

# cross_segment relation_type → 因果边类型映射
RELATION_TO_EDGE = {
    "因果": EDGE_TYPE_CAUSE,
    "伏笔-回收": EDGE_TYPE_ENABLE,
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
    p.add_argument("--doc-id", required=True, help="文档 ID")
    p.add_argument("--output-dir", required=True, help="输出目录")
    args = p.parse_args()

    cross_path = Path(args.cross_segment)
    structure_path = Path(args.structure)
    for path, name in [(cross_path, "cross_segment"), (structure_path, "structure")]:
        if not path.is_file():
            print(f"❌ {name} 文件不存在：{path}", file=sys.stderr)
            return 2

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # 加载数据
    cross_refs = load_cross_refs(cross_path)
    structure_rows = load_jsonl(structure_path)
    d01_index = build_d01_index(structure_rows)

    print(f"📖 加载 cross_refs: {len(cross_refs)} 条")
    print(f"📖 加载 structure: {len(structure_rows)} 行, D01索引: {len(d01_index)} 段")

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
    causal_graph = {
        "doc_id": args.doc_id,
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "causal_graph": {
            "nodes": list(set(
                [e["source"]["segment_id"] for e in edges] +
                [e["target"]["segment_id"] for e in edges]
            )),
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
        },
        "validation": {
            "method": "d01_function_sequence_v1",
            "description": "D01从生成端移到校验端：只过滤反向边（target在source之前）和孤立边（无D01批注），不用于生成边",
            "direction_check": f"{len(edges)} 条通过方向校验",
            "d01_coverage": f"{len(edges)} 条两端均有D01批注",
            "filtered_details": filtered,
        },
        "_metadata": {
            "method": "rule_based_v3_0",
            "edge_sources": ["cross_segment.因果", "cross_segment.伏笔-回收"],
            "note": "纯规则引擎，基于cross_segment已有关系；D01仅用于校验端过滤，不生成边（专家评审C修正）",
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
