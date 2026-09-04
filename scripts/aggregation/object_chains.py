#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v3.0 Step 5 — 物件链追踪（Object Chains）

基于方案文档实现：
- 从 craft.jsonl 的 D15_imagery 中提取重复出现的器物意象
- 重点关注 type="器物意象" 和有 cluster 字段的跨段意象
- 追踪物件的生命周期：首次出现→每次出现→最后出现/消失
- 输出 object_chains.json

用法：
  python scripts/aggregation/object_chains.py \
    --craft outputs/annotations/moon_sixpence_zh/moon_sixpence_zh_craft.jsonl \
    --doc-id moon_sixpence_zh \
    --output-dir outputs/annotations/moon_sixpence_zh/aggregation
"""

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

SCHEMA_VERSION = "3.0.0"

# 物件意象类型优先级
OBJECT_TYPES = ["器物意象", "自然意象", "人体意象", "色彩意象", "抽象意象"]


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


def text_similarity(a: str, b: str) -> float:
    """计算两个文本的相似度（用于物件名归并）。"""
    return SequenceMatcher(None, a, b).ratio()


def extract_imagery(craft_rows: list[dict]) -> list[dict]:
    """从 craft 行中提取所有 D15_imagery 条目。"""
    imagery_items = []
    for row in craft_rows:
        craft = row.get("layers", {}).get("craft", {})
        if not craft:
            craft = row.get("craft", {})
        d15 = craft.get("D15_imagery", [])
        if not isinstance(d15, list):
            continue
        seg_id = row.get("segment_id")
        chapter = row.get("chapter")
        for item in d15:
            if not isinstance(item, dict):
                continue
            imagery_items.append({
                "segment_id": seg_id,
                "segment_index": get_segment_index(seg_id) if seg_id else 0,
                "chapter": chapter,
                "text": item.get("text", ""),
                "type": item.get("type", "未知"),
                "cluster": item.get("cluster"),
                "span": item.get("span"),
            })
    return imagery_items


def cluster_objects(imagery_items: list[dict], similarity_threshold: float = 0.6) -> dict[str, list[dict]]:
    """
    将意象条目聚类为物件链。
    优先按 cluster 字段聚类，其次按 text 相似度。
    """
    clusters = defaultdict(list)
    unclustered = []

    # 第一遍：按 cluster 字段聚类
    for item in imagery_items:
        if item.get("cluster"):
            clusters[f"cluster:{item['cluster']}"].append(item)
        else:
            unclustered.append(item)

    # 第二遍：对无 cluster 的器物意象，按 text 相似度聚类
    object_items = [i for i in unclustered if i["type"] == "器物意象"]
    other_items = [i for i in unclustered if i["type"] != "器物意象"]

    # 简单聚类：逐个分配到最相似的已有簇
    object_clusters = []  # list of (representative_text, items)
    for item in object_items:
        best_cluster = None
        best_sim = 0
        for rep, items in object_clusters:
            sim = text_similarity(item["text"], rep)
            if sim > best_sim:
                best_sim = sim
                best_cluster = (rep, items)
        if best_cluster and best_sim >= similarity_threshold:
            best_cluster[1].append(item)
        else:
            object_clusters.append((item["text"], [item]))

    for i, (rep, items) in enumerate(object_clusters):
        clusters[f"textsim:{rep[:20]}_{i}"] = items

    # 其他类型（非器物）也按 cluster 或单独成链
    for item in other_items:
        if item.get("cluster"):
            continue  # 已在第一遍处理
        # 单独成链（出现次数可能不够，但保留）
        clusters[f"single:{item['text'][:20]}_{item['segment_index']}"] = [item]

    return dict(clusters)


def build_object_chains(clusters: dict[str, list[dict]], min_occurrences: int = 2) -> list[dict]:
    """
    从聚类结果构建物件链。
    只保留出现次数 >= min_occurrences 的链。
    """
    chains = []
    chain_id_counter = 1

    for cluster_key, items in clusters.items():
        if len(items) < min_occurrences:
            continue

        # 按 segment_index 排序
        items_sorted = sorted(items, key=lambda x: x["segment_index"])

        # 确定物件名（取出现次数最多的 text，或第一条的 text）
        from collections import Counter
        text_counts = Counter(i["text"] for i in items_sorted)
        object_name = text_counts.most_common(1)[0][0]

        # 确定主要类型
        type_counts = Counter(i["type"] for i in items_sorted)
        primary_type = type_counts.most_common(1)[0][0]

        # 确定 cluster 标签（如果有）
        # v3.0.1 修复（T-029 P2-3）：sorted(set(...)) 消除 PYTHONHASHSEED 顺序漂移
        cluster_labels = sorted(set(i["cluster"] for i in items_sorted if i.get("cluster")))

        # 生命周期
        first_appearance = items_sorted[0]
        last_appearance = items_sorted[-1]

        # 出现段列表
        segments = [i["segment_id"] for i in items_sorted]
        # v3.0.1 修复（T-029 P2-3）：sorted(set(...)) 消除顺序漂移
        chapters = sorted(set(i["chapter"] for i in items_sorted if i.get("chapter")))

        # 语义变化检测（简单：检查 text 是否有变化）
        unique_texts = sorted(set(i["text"] for i in items_sorted))
        has_semantic_shift = len(unique_texts) > 1

        chain = {
            "chain_id": f"oc_{chain_id_counter:04d}",
            "object_name": object_name,
            "object_type": primary_type,
            "cluster_labels": cluster_labels,
            "occurrence_count": len(items_sorted),
            "first_appearance": {
                "segment_id": first_appearance["segment_id"],
                "chapter": first_appearance.get("chapter"),
                "text": first_appearance["text"],
            },
            "last_appearance": {
                "segment_id": last_appearance["segment_id"],
                "chapter": last_appearance.get("chapter"),
                "text": last_appearance["text"],
            },
            "appearances": [
                {
                    "segment_id": i["segment_id"],
                    "chapter": i.get("chapter"),
                    "text": i["text"],
                    "type": i["type"],
                }
                for i in items_sorted
            ],
            "segments": segments,
            "chapters": chapters,
            "semantic_shift": {
                "has_shift": has_semantic_shift,
                "unique_texts": unique_texts,
                "note": "物件在不同段的表述有差异，可能存在语义演变" if has_semantic_shift else "物件表述一致",
            },
            "lifecycle_span": last_appearance["segment_index"] - first_appearance["segment_index"],
        }
        chains.append(chain)
        chain_id_counter += 1

    # 按出现次数降序
    chains.sort(key=lambda c: c["occurrence_count"], reverse=True)
    return chains


def main() -> int:
    p = argparse.ArgumentParser(description="v3.0 Step 5 — 物件链追踪（Object Chains）")
    p.add_argument("--craft", required=True, help="craft.jsonl 路径")
    p.add_argument("--doc-id", required=True, help="文档 ID")
    p.add_argument("--output-dir", required=True, help="输出目录")
    p.add_argument("--min-occurrences", type=int, default=2, help="最小出现次数（默认2）")
    p.add_argument("--similarity-threshold", type=float, default=0.6, help="文本相似度聚类阈值（默认0.6）")
    args = p.parse_args()

    craft_path = Path(args.craft)
    if not craft_path.is_file():
        print(f"❌ craft 文件不存在：{craft_path}", file=sys.stderr)
        return 2

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # 加载数据
    craft_rows = load_jsonl(craft_path)
    print(f"📖 加载 craft: {len(craft_rows)} 行")

    # 提取意象
    print("\n🚀 Step 1: 从 craft 提取 D15_imagery 条目...")
    imagery_items = extract_imagery(craft_rows)
    print(f"   提取意象条目: {len(imagery_items)} 条")

    # 类型分布
    from collections import Counter
    type_counts = Counter(i["type"] for i in imagery_items)
    print(f"   类型分布: {dict(type_counts)}")

    # 有 cluster 的条目
    clustered = [i for i in imagery_items if i.get("cluster")]
    print(f"   有 cluster 字段: {len(clustered)} 条")

    # 聚类
    print(f"\n🚀 Step 2: 意象聚类（cluster优先 + text相似度，阈值={args.similarity_threshold}）...")
    clusters = cluster_objects(imagery_items, args.similarity_threshold)
    print(f"   聚类数量: {len(clusters)}")
    for key, items in list(clusters.items())[:5]:
        print(f"     {key[:40]}: {len(items)} 条")

    # 构建物件链
    print(f"\n🚀 Step 3: 构建物件链（最小出现次数={args.min_occurrences}）...")
    chains = build_object_chains(clusters, args.min_occurrences)
    print(f"   物件链数量: {len(chains)}")

    # 按类型统计
    chain_type_counts = Counter(c["object_type"] for c in chains)
    print(f"   链类型分布: {dict(chain_type_counts)}")

    # 打印 Top 5
    print(f"\n   Top 5 物件链:")
    for chain in chains[:5]:
        print(f"     {chain['chain_id']}: {chain['object_name'][:30]} ({chain['object_type']}), "
              f"出现{chain['occurrence_count']}次, "
              f"跨度{chain['lifecycle_span']}段, "
              f"语义变化={'是' if chain['semantic_shift']['has_shift'] else '否'}")

    # 构建 object_chains
    print("\n🚀 Step 4: 构建 object_chains.json...")
    object_chains = {
        "doc_id": args.doc_id,
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "object_chains": chains,
        "statistics": {
            "total_chains": len(chains),
            "total_occurrences": sum(c["occurrence_count"] for c in chains),
            "by_type": dict(chain_type_counts),
            "with_semantic_shift": sum(1 for c in chains if c["semantic_shift"]["has_shift"]),
            "avg_occurrences": round(sum(c["occurrence_count"] for c in chains) / len(chains), 2) if chains else 0,
            "max_lifecycle_span": max((c["lifecycle_span"] for c in chains), default=0),
        },
        "extraction_stats": {
            "total_imagery_items": len(imagery_items),
            "by_type": dict(type_counts),
            "with_cluster": len(clustered),
            "clusters_found": len(clusters),
        },
        "_metadata": {
            "method": "rule_based_v3_0",
            "clustering": "cluster字段优先 + text相似度(SequenceMatcher)",
            "min_occurrences": args.min_occurrences,
            "similarity_threshold": args.similarity_threshold,
            "note": "纯规则引擎，基于D15_imagery的cluster和text相似度聚类；器物意象优先，其他类型保留",
        },
    }

    # 写入文件
    out_path = out_dir / f"{args.doc_id}_object_chains.json"
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(object_chains, f, ensure_ascii=False, indent=2)

    print(f"\n✅ object_chains.json 已写入: {out_path}")
    print(f"   物件链: {len(chains)} 条, 总出现次数: {object_chains['statistics']['total_occurrences']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
