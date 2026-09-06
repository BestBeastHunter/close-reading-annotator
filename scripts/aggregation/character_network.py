#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v3.11.0 新增 — 人物关系网络聚合（Character Network）

基于 entity_graph 共现矩阵 + D19.target（情感对象）+ D18（对话关系），
构建带关系类型和强度的人物关系网络。

纯规则引擎（不调 LLM），零第三方依赖。

关系类型（10类）：亲情/爱情/友情/战友/敌对/上下级/师徒/暗恋/合作/陌生
强度计算：共现频次(0.4) + 情感指向强度(0.3) + 对话频次(0.3)

用法：
  python scripts/aggregation/character_network.py \
    --entity-graph outputs/annotations/xxx/aggregation/xxx_entity_graph.json \
    --emotion outputs/annotations/xxx/xxx_emotion.jsonl \
    --craft outputs/annotations/xxx/xxx_craft.jsonl \
    --doc-id xxx \
    --output-dir outputs/annotations/xxx/aggregation
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

SCHEMA_VERSION = "3.2.0"

# 关系类型枚举（10类）
RELATION_TYPES = [
    "亲情", "爱情", "友情", "战友", "敌对",
    "上下级", "师徒", "暗恋", "合作", "陌生",
]

# 情感词→关系倾向映射（用于从 D19.target 推断关系类型）
EMOTION_TO_RELATION = {
    "思念": "亲情", "眷恋": "亲情",
    "爱慕": "爱情", "心动": "爱情", "甜蜜": "爱情",
    "信任": "友情", "温暖": "友情",
    "坚定": "战友", "热血": "战友",
    "愤怒": "敌对", "仇恨": "敌对", "厌恶": "敌对",
    "敬畏": "上下级", "服从": "上下级",
    "敬佩": "师徒", "感激": "师徒",
    "羞涩": "暗恋", "期待": "暗恋",
    "默契": "合作", "协作": "合作",
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


def build_cooccurrence_matrix(entity_graph: dict) -> dict[tuple[str, str], int]:
    """从 entity_graph 构建共现矩阵：{(entity_id_a, entity_id_b): cooccurrence_count}"""
    matrix = defaultdict(int)
    entities = entity_graph.get("entities", [])
    # 构建 entity_id → segment_ids 映射
    ent_segments = {}
    for ent in entities:
        eid = ent.get("entity_id")
        seg_ids = ent.get("segment_ids", [])
        if not seg_ids:
            # 回退：从 mentions_sample 提取
            seg_ids = list(set(m.get("segment_id") for m in ent.get("mentions_sample", []) if m.get("segment_id")))
        if eid and seg_ids:
            ent_segments[eid] = set(seg_ids)

    # 计算两两共现
    eids = sorted(ent_segments.keys())
    for i in range(len(eids)):
        for j in range(i + 1, len(eids)):
            common = ent_segments[eids[i]] & ent_segments[eids[j]]
            if common:
                matrix[(eids[i], eids[j])] = len(common)
    return matrix


def extract_emotion_targets(emotion_rows: list[dict]) -> dict[tuple[str, str], list[dict]]:
    """从 emotion 层提取 D19.target 情感指向：{(source_name, target_name): [emotion_data]}"""
    targets = defaultdict(list)
    for row in emotion_rows:
        emotion = row.get("layers", {}).get("emotion", {})
        if not emotion:
            emotion = row.get("emotion", {})
        primary = emotion.get("D19_emotion_analysis") or emotion.get("primary") or {}
        if isinstance(primary, dict):
            target = primary.get("target")
            emotion_word = primary.get("emotion", "")
            intensity = primary.get("intensity", 5)
            seg_id = row.get("segment_id", "")
            if target and isinstance(target, str) and len(target) <= 20:
                # source 暂时用 "叙述者"，后续可以从 entity_graph 匹配
                targets[("叙述者", target)].append({
                    "emotion": emotion_word,
                    "intensity": intensity,
                    "segment_id": seg_id,
                })
    return targets


def extract_dialogue_pairs(craft_rows: list[dict]) -> dict[tuple[str, str], int]:
    """从 craft 层 D18 提取对话对：{(speaker_a, speaker_b): dialogue_count}"""
    pairs = defaultdict(int)
    # 收集每段的说话者列表
    seg_speakers = defaultdict(list)
    for row in craft_rows:
        craft = row.get("layers", {}).get("craft") or row.get("craft") or {}
        d18 = craft.get("D18_character_voice", []) or []
        seg_id = row.get("segment_id", "")
        for item in d18:
            if isinstance(item, dict):
                char = item.get("character", "")
                if char and len(char) <= 20:
                    seg_speakers[seg_id].append(char)
    # 同一段内多个说话者 → 对话对
    for seg_id, speakers in seg_speakers.items():
        unique_speakers = sorted(set(speakers))
        for i in range(len(unique_speakers)):
            for j in range(i + 1, len(unique_speakers)):
                pairs[(unique_speakers[i], unique_speakers[j])] += 1
    return pairs


def infer_relation_type(cooccurrence: int, emotion_data: list, dialogue_count: int) -> tuple[str, float]:
    """推断关系类型和强度。返回 (relation_type, strength 0-1)"""
    # 强度计算：共现(0.4) + 情感(0.3) + 对话(0.3)
    cooc_score = min(cooccurrence / 10.0, 1.0) * 0.4
    emo_score = 0.0
    if emotion_data:
        avg_intensity = sum(e.get("intensity", 5) for e in emotion_data) / len(emotion_data)
        emo_score = min(avg_intensity / 10.0, 1.0) * 0.3
    dial_score = min(dialogue_count / 5.0, 1.0) * 0.3
    strength = round(cooc_score + emo_score + dial_score, 3)

    # 关系类型推断
    # 优先级：情感指向 > 对话频次 > 共现
    relation_type = "陌生"
    if emotion_data:
        # 从情感词推断关系类型
        for e in emotion_data:
            emo = e.get("emotion", "")
            for key, rel in EMOTION_TO_RELATION.items():
                if key in emo:
                    relation_type = rel
                    break
            if relation_type != "陌生":
                break
    if relation_type == "陌生" and dialogue_count >= 2:
        relation_type = "合作"
    if relation_type == "陌生" and cooccurrence >= 3:
        relation_type = "友情"
    if strength < 0.1:
        relation_type = "陌生"

    return relation_type, strength


def build_character_network(entity_graph: dict, emotion_rows: list, craft_rows: list, doc_id: str) -> dict:
    """构建人物关系网络"""
    entities = entity_graph.get("entities", [])
    ent_map = {e.get("entity_id"): e for e in entities if e.get("entity_id")}

    # 1. 共现矩阵
    cooc_matrix = build_cooccurrence_matrix(entity_graph)

    # 2. 情感指向
    emotion_targets = extract_emotion_targets(emotion_rows)

    # 3. 对话对
    dialogue_pairs = extract_dialogue_pairs(craft_rows)

    # 4. 构建边
    edges = []
    edge_id = 0
    all_pairs = set(cooc_matrix.keys())

    # 合并情感和对话中的 pair（需要 name→entity_id 映射）
    name_to_eid = {}
    for eid, ent in ent_map.items():
        name = ent.get("canonical_name", "")
        if name:
            name_to_eid[name] = eid
        for alias in ent.get("aliases", []):
            if alias:
                name_to_eid[alias] = eid

    # 构建 nodes
    nodes = []
    for eid, ent in ent_map.items():
        nodes.append({
            "id": eid,
            "name": ent.get("canonical_name", ""),
            "centrality": round(ent.get("occurrence_count", 0) / max(1, max(e.get("occurrence_count", 1) for e in entities)), 3),
            "occurrence_count": ent.get("occurrence_count", 0),
            "segment_count": ent.get("segment_count", 0),
        })

    # 5. 对每对实体构建边
    processed_pairs = set()
    for (eid_a, eid_b), cooc in cooc_matrix.items():
        pair_key = tuple(sorted([eid_a, eid_b]))
        if pair_key in processed_pairs:
            continue
        processed_pairs.add(pair_key)

        name_a = ent_map.get(eid_a, {}).get("canonical_name", "")
        name_b = ent_map.get(eid_b, {}).get("canonical_name", "")

        # 查找情感数据
        emo_data = []
        for (src, tgt), data in emotion_targets.items():
            if (src in name_a or name_a in src) and (tgt in name_b or name_b in tgt):
                emo_data.extend(data)
            elif (src in name_b or name_b in src) and (tgt in name_a or name_a in tgt):
                emo_data.extend(data)

        # 查找对话数据
        dial_count = 0
        for (spk_a, spk_b), count in dialogue_pairs.items():
            if (spk_a in name_a or name_a in spk_a) and (spk_b in name_b or name_b in spk_b):
                dial_count += count
            elif (spk_a in name_b or name_b in spk_a) and (spk_b in name_a or name_a in spk_b):
                dial_count += count

        relation_type, strength = infer_relation_type(cooc, emo_data, dial_count)

        edge_id += 1
        edges.append({
            "edge_id": f"rel_{edge_id:04d}",
            "source": eid_a,
            "target": eid_b,
            "source_name": name_a,
            "target_name": name_b,
            "relation": relation_type,
            "strength": strength,
            "cooccurrence": cooc,
            "dialogue_count": dial_count,
            "emotion_mentions": len(emo_data),
        })

    # 6. 简单社区检测（基于关系类型分组）
    communities = []
    relation_groups = defaultdict(list)
    for edge in edges:
        if edge["relation"] != "陌生":
            relation_groups[edge["relation"]].append(edge["source_name"])
            relation_groups[edge["relation"]].append(edge["target_name"])
    for i, (rel, members) in enumerate(sorted(relation_groups.items())):
        communities.append({
            "community_id": f"comm_{i+1:03d}",
            "label": rel,
            "members": sorted(set(members)),
        })

    return {
        "doc_id": doc_id,
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now().isoformat(),
        "generator": "character_network.py v3.11.0",
        "total_nodes": len(nodes),
        "total_edges": len(edges),
        "nodes": nodes,
        "edges": edges,
        "communities": communities,
        "_metadata": {
            "method": "rule_based_v3_11",
            "relation_types": RELATION_TYPES,
            "strength_formula": "cooccurrence(0.4) + emotion(0.3) + dialogue(0.3)",
            "note": "关系类型为规则推断，建议 LLM 复核；strength 为相对值",
        },
    }


def main() -> int:
    p = argparse.ArgumentParser(description="v3.11.0 人物关系网络聚合")
    p.add_argument("--entity-graph", required=True, help="entity_graph.json 路径")
    p.add_argument("--emotion", default=None, help="emotion.jsonl 路径（可选）")
    p.add_argument("--craft", default=None, help="craft.jsonl 路径（可选）")
    p.add_argument("--doc-id", required=True)
    p.add_argument("--output-dir", required=True)
    args = p.parse_args()

    entity_graph_path = Path(args.entity_graph)
    if not entity_graph_path.is_file():
        print(f"❌ entity_graph 不存在: {entity_graph_path}", file=sys.stderr)
        return 1

    entity_graph = json.loads(entity_graph_path.read_text(encoding="utf-8"))
    emotion_rows = load_jsonl(Path(args.emotion)) if args.emotion else []
    craft_rows = load_jsonl(Path(args.craft)) if args.craft else []

    network = build_character_network(entity_graph, emotion_rows, craft_rows, args.doc_id)

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{args.doc_id}_character_network.json"
    out_path.write_text(json.dumps(network, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"✅ 人物关系网络构建完成: {network['total_nodes']} 节点, {network['total_edges']} 边")
    print(f"   关系类型分布:")
    rel_dist = defaultdict(int)
    for e in network["edges"]:
        rel_dist[e["relation"]] += 1
    for rel, count in sorted(rel_dist.items(), key=lambda x: -x[1]):
        print(f"     {rel}: {count}")
    print(f"   输出 → {out_path.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
