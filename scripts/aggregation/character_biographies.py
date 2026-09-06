#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v3.12.0 新增 — 人物传记聚合（Character Biographies）

把按时间顺序的逐段批注重新组织为以人物为中心的传记式分析。

纯规则引擎（不调 LLM），零第三方依赖。所有数据来自现有批注产物和聚合产物。

用法：
  python scripts/aggregation/character_biographies.py \\
    --segments outputs/annotations/xxx/xxx_segments.jsonl \\
    --structure outputs/annotations/xxx/xxx_structure.jsonl \\
    --interpretation outputs/annotations/xxx/xxx_interpretation.jsonl \\
    --craft outputs/annotations/xxx/xxx_craft.jsonl \\
    --emotion outputs/annotations/xxx/xxx_emotion.jsonl \\
    --cross-segment outputs/annotations/xxx/xxx_cross_segment.jsonl \\
    --entity-graph outputs/annotations/xxx/aggregation/xxx_entity_graph.json \\
    --character-arcs outputs/annotations/xxx/aggregation/xxx_character_arcs.json \\
    --character-network outputs/annotations/xxx/aggregation/xxx_character_network.json \\
    --narrative-structure outputs/annotations/xxx/aggregation/xxx_narrative_structure.json \\
    --doc-id xxx \\
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

SCHEMA_VERSION = "3.3.0"

# 主要人物筛选阈值：出场段数 >= 总段数 * 阈值
MAIN_CHARACTER_THRESHOLD = 0.05
# 最多输出的人物传记数量
MAX_BIOGRAPHIES = 15

# 关键时刻类型映射（D01 → key_moment type）
KEY_MOMENT_TYPES = {
    "激励事件": "inciting_incident",
    "高潮": "climax",
    "转折": "turning_point",
    "下降行动": "falling_action",
    "结局": "resolution",
}

# 决策点启发式关键词
DECISION_KEYWORDS = [
    "决定", "选择", "必须", "只能", "只好", "宁愿", "决心", "决意",
    "放弃", "坚持", "答应", "拒绝", "同意", "反对", "承诺", "发誓",
    "计划", "打算", "准备", "考虑", "犹豫", "纠结", "权衡",
]


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


def load_json(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def get_segment_index(seg_id: str) -> int:
    parts = seg_id.rsplit("_seg_", 1)
    if len(parts) == 2:
        try:
            return int(parts[1])
        except ValueError:
            pass
    return 0


def extract_character_mentions(segments: list[dict], entity_graph: dict) -> dict[str, list[str]]:
    """从 entity_graph 提取每个角色在哪些 segment 出现"""
    char_segments = defaultdict(list)
    entities = entity_graph.get("entities", [])
    for ent in entities:
        eid = ent.get("entity_id")
        name = ent.get("canonical_name", "")
        seg_ids = ent.get("segment_ids", [])
        if not seg_ids:
            seg_ids = list(set(m.get("segment_id") for m in ent.get("mentions_sample", []) if m.get("segment_id")))
        if eid and seg_ids:
            char_segments[eid] = sorted(seg_ids, key=get_segment_index)
    return char_segments


def extract_timeline_for_character(
    char_name: str, aliases: list[str],
    segments: list[dict], structure: dict, interpretation: dict,
    craft: dict, emotion: dict, seg_id_to_idx: dict
) -> list[dict]:
    """提取单个角色的时间线（段级批注→人物传记的核心转换）"""
    timeline = []
    all_names = [char_name] + aliases

    for seg in segments:
        seg_id = seg.get("segment_id", "")
        if not seg_id:
            continue

        # 检查该角色是否在本段出现（通过 D18/D19/D10）
        char_present = False
        key_quote = ""
        d18_items = []

        # 检查 craft 层 D18
        craft_row = craft.get(seg_id)
        if craft_row:
            craft_data = craft_row.get("layers", {}).get("craft") or craft_row.get("craft") or {}
            d18 = craft_data.get("D18_character_voice", []) or []
            for item in d18:
                if isinstance(item, dict):
                    speaker = item.get("character", "")
                    if speaker and any(n in speaker or speaker in n for n in all_names):
                        char_present = True
                        d18_items.append(item)
                        pattern = item.get("pattern", "")
                        if pattern and len(pattern) > len(key_quote):
                            key_quote = pattern[:80]

        # 检查 emotion 层 D19.target
        emotion_row = emotion.get(seg_id)
        if emotion_row:
            emo_data = emotion_row.get("layers", {}).get("emotion") or emotion_row.get("emotion") or {}
            primary = emo_data.get("D19_emotion_analysis") or emo_data.get("primary") or {}
            if isinstance(primary, dict):
                target = primary.get("target", "")
                if target and any(n in target or target in n for n in all_names):
                    char_present = True

        # 检查 structure 层 D10（对话）
        struct_row = structure.get(seg_id)
        d01 = ""
        d04_emotion = ""
        d04_intensity = 0
        if struct_row:
            st = struct_row.get("layers", {}).get("structure") or {}
            d01 = st.get("D01", "")
            d04 = st.get("D04", {}) or {}
            if isinstance(d04, dict):
                d04_emotion = d04.get("core", "")
                d04_intensity = d04.get("intensity", 0)

        if not char_present:
            continue

        # 确定事件重要性
        significance = "low"
        if d01 in KEY_MOMENT_TYPES:
            significance = "high"
        elif d04_intensity >= 7:
            significance = "high"
        elif d18_items:
            significance = "medium"

        # 事件描述（基于 D01 + 章节）
        chapter = seg.get("chapter", "")
        event_desc = f"{chapter}：{d01}" if d01 else chapter

        timeline.append({
            "segment_id": seg_id,
            "segment_index": get_segment_index(seg_id),
            "chapter": chapter,
            "event": event_desc,
            "d01_function": d01,
            "emotion": d04_emotion,
            "intensity": d04_intensity,
            "key_quote": key_quote,
            "significance": significance,
            "has_dialogue": bool(d18_items),
        })

    return timeline


def extract_key_moments(timeline: list[dict]) -> list[dict]:
    """从时间线提取关键时刻"""
    key_moments = []
    for item in timeline:
        d01 = item.get("d01_function", "")
        if d01 in KEY_MOMENT_TYPES:
            key_moments.append({
                "type": KEY_MOMENT_TYPES[d01],
                "segment_id": item["segment_id"],
                "chapter": item.get("chapter", ""),
                "description": item.get("event", ""),
                "emotion": item.get("emotion", ""),
                "intensity": item.get("intensity", 0),
                "key_quote": item.get("key_quote", ""),
            })
    return key_moments


def extract_decision_points(timeline: list[dict], craft: dict, char_name: str, aliases: list[str]) -> list[dict]:
    """提取关键决策点（基于 D18 对话 + D16 词汇 + 启发式关键词）"""
    decisions = []
    all_names = [char_name] + aliases

    for item in timeline:
        seg_id = item["segment_id"]
        craft_row = craft.get(seg_id)
        if not craft_row:
            continue
        craft_data = craft_row.get("layers", {}).get("craft") or craft_row.get("craft") or {}

        # 检查 D18 对话中是否包含决策关键词
        d18 = craft_data.get("D18_character_voice", []) or []
        for item_d18 in d18:
            if isinstance(item_d18, dict):
                speaker = item_d18.get("character", "")
                pattern = item_d18.get("pattern", "")
                if speaker and any(n in speaker or speaker in n for n in all_names):
                    if any(kw in pattern for kw in DECISION_KEYWORDS):
                        decisions.append({
                            "segment_id": seg_id,
                            "chapter": item.get("chapter", ""),
                            "decision": pattern[:100],
                            "emotion": item.get("emotion", ""),
                            "intensity": item.get("intensity", 0),
                            "consequence": "",  # 留空，后续可 LLM 补充
                        })
                        break

        # 检查 D16 词汇中是否包含决策关键词
        d16 = craft_data.get("D16_diction", []) or []
        for item_d16 in d16:
            if isinstance(item_d16, dict):
                text = item_d16.get("text", "")
                if any(kw in text for kw in DECISION_KEYWORDS):
                    # 检查是否与该角色相关（简化：只在该角色有对话的段标记）
                    if item.get("has_dialogue"):
                        decisions.append({
                            "segment_id": seg_id,
                            "chapter": item.get("chapter", ""),
                            "decision": f"关键词：{text}",
                            "emotion": item.get("emotion", ""),
                            "intensity": item.get("intensity", 0),
                            "consequence": "",
                        })
                        break

    return decisions[:10]  # 最多10个决策点


def extract_relationships(char_name: str, char_id: str, character_network: dict | None,
                          emotion: dict, all_names: list[str]) -> list[dict]:
    """提取人物关系（带演变）"""
    relationships = []

    if character_network:
        edges = character_network.get("edges", [])
        for edge in edges:
            if edge.get("source_name") == char_name or edge.get("target_name") == char_name:
                target = edge["target_name"] if edge["source_name"] == char_name else edge["source_name"]
                relationships.append({
                    "target": target,
                    "relation": edge.get("relation", "陌生"),
                    "strength": edge.get("strength", 0),
                    "cooccurrence": edge.get("cooccurrence", 0),
                    "dialogue_count": edge.get("dialogue_count", 0),
                    "evolution": [],  # 留空，后续可从 D19.target 时序推断
                })

    # 从 D19.target 时序推断关系演变
    target_timeline = defaultdict(list)
    for seg_id, emo_row in emotion.items():
        emo_data = emo_row.get("layers", {}).get("emotion") or emo_row.get("emotion") or {}
        primary = emo_data.get("D19_emotion_analysis") or emo_data.get("primary") or {}
        if isinstance(primary, dict):
            target = primary.get("target", "")
            emo = primary.get("emotion", "")
            if target and target != char_name and not any(n in target for n in all_names):
                target_timeline[target].append({
                    "segment_id": seg_id,
                    "emotion": emo,
                    "intensity": primary.get("intensity", 5),
                })

    # 把演变信息合并到 relationships
    for rel in relationships:
        target = rel["target"]
        if target in target_timeline:
            events = sorted(target_timeline[target], key=lambda x: get_segment_index(x["segment_id"]))
            rel["evolution"] = [
                {"segment": e["segment_id"], "emotion": e["emotion"], "intensity": e["intensity"]}
                for e in events[:5]  # 最多5个演变节点
            ]

    return sorted(relationships, key=lambda x: -x["strength"])[:8]


def extract_voice_fingerprint(char_name: str, aliases: list[str], craft: dict) -> dict:
    """提取人物语言指纹（整合 D18）"""
    all_names = [char_name] + aliases
    patterns = []
    speech_verbs = defaultdict(int)
    total_dialogue = 0
    total_length = 0

    for seg_id, craft_row in craft.items():
        craft_data = craft_row.get("layers", {}).get("craft") or craft_row.get("craft") or {}
        d18 = craft_data.get("D18_character_voice", []) or []
        for item in d18:
            if isinstance(item, dict):
                speaker = item.get("character", "")
                if speaker and any(n in speaker or speaker in n for n in all_names):
                    pattern = item.get("pattern", "")
                    if pattern:
                        patterns.append(pattern)
                    svd = item.get("speech_verb_distribution", {}) or {}
                    if isinstance(svd, dict):
                        dominant = svd.get("dominant")
                        if dominant:
                            speech_verbs[dominant] += 1
                    dlg_len = item.get("dialogue_length_avg", 0)
                    if dlg_len:
                        total_length += dlg_len
                        total_dialogue += 1

    return {
        "dominant_speech_verb": max(speech_verbs, key=speech_verbs.get) if speech_verbs else None,
        "speech_verb_distribution": dict(speech_verbs),
        "avg_dialogue_length": round(total_length / total_dialogue, 1) if total_dialogue else 0,
        "total_dialogue_turns": total_dialogue,
        "patterns": patterns[:10],
    }


def extract_key_quotes(char_name: str, aliases: list[str], craft: dict, segments: dict) -> list[dict]:
    """提取金句/关键台词（来自 D13 + D18，按人物归属）"""
    all_names = [char_name] + aliases
    quotes = []

    for seg_id, craft_row in craft.items():
        craft_data = craft_row.get("layers", {}).get("craft") or craft_row.get("craft") or {}

        # D13 金句
        d13 = craft_data.get("D13_golden_lines", []) or []
        for item in d13:
            if isinstance(item, dict):
                text = item.get("text", "")
                if text and len(text) >= 5:
                    # 检查是否与该角色相关（简化：该角色在本段有对话）
                    d18 = craft_data.get("D18_character_voice", []) or []
                    char_has_dialogue = any(
                        isinstance(i, dict) and i.get("character", "") and
                        any(n in i.get("character", "") or i.get("character", "") in n for n in all_names)
                        for i in d18
                    )
                    if char_has_dialogue:
                        quotes.append({
                            "text": text[:100],
                            "segment_id": seg_id,
                            "chapter": segments.get(seg_id, {}).get("chapter", ""),
                            "type": "golden_line",
                        })

        # D18 人物语言（作为台词）
        d18 = craft_data.get("D18_character_voice", []) or []
        for item in d18:
            if isinstance(item, dict):
                speaker = item.get("character", "")
                pattern = item.get("pattern", "")
                if speaker and any(n in speaker or speaker in n for n in all_names):
                    if pattern and len(pattern) >= 8:
                        quotes.append({
                            "text": pattern[:100],
                            "segment_id": seg_id,
                            "chapter": segments.get(seg_id, {}).get("chapter", ""),
                            "type": "dialogue",
                        })

    return quotes[:10]  # 最多10条金句


def generate_appreciation(char_name: str, biography: dict) -> str:
    """生成人物综合评价（规则生成，后续可接入 LLM）"""
    role = biography.get("biography", {}).get("role_in_story", "")
    char_type = biography.get("biography", {}).get("character_type", "")
    arc_type = biography.get("emotional_arc", {}).get("arc_type", "")
    traits = [t["trait"] for t in biography.get("character_traits", [])[:3]]
    key_moments_count = len(biography.get("key_moments", []))
    decisions_count = len(biography.get("decision_points", []))
    total_segs = biography.get("biography", {}).get("total_segments", 0)

    parts = [f"{char_name}"]
    if role:
        parts.append(f"，{role}")
    if char_type:
        parts.append(f"，{char_type}人物")
    parts.append(f"。全书出场{total_segs}段")
    if key_moments_count:
        parts.append(f"，参与{key_moments_count}个关键时刻")
    if decisions_count:
        parts.append(f"，做出{decisions_count}个关键决策")
    if traits:
        parts.append(f"。性格特征：{'、'.join(traits)}")
    if arc_type:
        parts.append(f"。情感弧线类型：{arc_type}")
    parts.append("。")

    return "".join(parts)


def build_biography(
    char_id: str, char_name: str, aliases: list[str],
    segments: list[dict], structure: dict, interpretation: dict,
    craft: dict, emotion: dict, cross_segment: dict,
    entity_graph: dict, character_arcs: dict | None,
    character_network: dict | None, narrative_structure: dict | None,
    seg_id_to_idx: dict, segments_by_id: dict
) -> dict:
    """构建单个人物的传记"""

    # 1. 人物概述
    ent = None
    for e in entity_graph.get("entities", []):
        if e.get("entity_id") == char_id or e.get("canonical_name") == char_name:
            ent = e
            break

    total_segments = len(ent.get("segment_ids", [])) if ent else 0
    if not total_segments and ent:
        total_segments = len(set(m.get("segment_id") for m in ent.get("mentions_sample", []) if m.get("segment_id")))

    first_seg = ent.get("first_segment") if ent else None
    last_seg = ent.get("last_segment") if ent else None

    # 角色定位（基于出场频次）
    role_in_story = "主角" if total_segments >= len(segments) * 0.3 else "配角" if total_segments >= len(segments) * 0.1 else "次要角色"

    biography = {
        "character_id": char_id,
        "name": char_name,
        "aliases": aliases,
        "biography": {
            "summary": f"{char_name}，{role_in_story}，全书出场{total_segments}段",
            "first_appearance": first_seg,
            "last_appearance": last_seg,
            "total_segments": total_segments,
            "role_in_story": role_in_story,
            "character_type": "圆形" if total_segments >= len(segments) * 0.2 else "扁平",
            "dynamic_static": "动态" if total_segments >= len(segments) * 0.15 else "静态",
        },
    }

    # 2. 时间线（核心！段级批注→人物传记的转换）
    timeline = extract_timeline_for_character(
        char_name, aliases, segments, structure, interpretation, craft, emotion, seg_id_to_idx
    )
    biography["timeline"] = timeline

    # 3. 关键时刻
    biography["key_moments"] = extract_key_moments(timeline)

    # 4. 关键决策
    biography["decision_points"] = extract_decision_points(timeline, craft, char_name, aliases)

    # 5. 人物关系
    biography["relationships"] = extract_relationships(char_name, char_id, character_network, emotion, [char_name] + aliases)

    # 6. 情感弧线（来自 character_arcs）
    if character_arcs:
        for arc in character_arcs.get("character_arcs", []):
            if arc.get("canonical_name") == char_name or char_id in str(arc.get("entity_id", "")):
                biography["emotional_arc"] = {
                    "arc_type": arc.get("arc_classification", {}).get("arc_type", ""),
                    "start": arc.get("key_moments", [{}])[0] if arc.get("key_moments") else {},
                    "peak": max(arc.get("key_moments", []), key=lambda x: x.get("intensity", 0), default={}),
                    "end": arc.get("key_moments", [{}])[-1] if arc.get("key_moments") else {},
                    "avg_intensity": arc.get("avg_intensity", 0),
                    "variance": arc.get("arc_classification", {}).get("variance", 0),
                }
                break
    if "emotional_arc" not in biography:
        biography["emotional_arc"] = {}

    # 7. 性格特征（来自 character_arcs 的 traits_aggregated）
    if character_arcs:
        for arc in character_arcs.get("character_arcs", []):
            if arc.get("canonical_name") == char_name:
                biography["character_traits"] = arc.get("traits_aggregated", [])
                break
    if "character_traits" not in biography:
        biography["character_traits"] = []

    # 8. 语言指纹
    biography["voice_fingerprint"] = extract_voice_fingerprint(char_name, aliases, craft)

    # 9. 金句
    biography["key_quotes"] = extract_key_quotes(char_name, aliases, craft, segments_by_id)

    # 10. 人物综合评价
    biography["appreciation"] = generate_appreciation(char_name, biography)

    return biography


def main() -> int:
    p = argparse.ArgumentParser(description="v3.12.0 人物传记聚合")
    p.add_argument("--segments", required=True)
    p.add_argument("--structure", required=True)
    p.add_argument("--interpretation", default=None)
    p.add_argument("--craft", default=None)
    p.add_argument("--emotion", default=None)
    p.add_argument("--cross-segment", default=None)
    p.add_argument("--entity-graph", required=True)
    p.add_argument("--character-arcs", default=None)
    p.add_argument("--character-network", default=None)
    p.add_argument("--narrative-structure", default=None)
    p.add_argument("--doc-id", required=True)
    p.add_argument("--output-dir", required=True)
    p.add_argument("--max-biographies", type=int, default=MAX_BIOGRAPHIES)
    args = p.parse_args()

    # 加载数据
    segments = load_jsonl(Path(args.segments))
    structure_rows = load_jsonl(Path(args.structure))
    interp_rows = load_jsonl(Path(args.interpretation)) if args.interpretation else []
    craft_rows = load_jsonl(Path(args.craft)) if args.craft else []
    emotion_rows = load_jsonl(Path(args.emotion)) if args.emotion else []
    cross_rows = load_jsonl(Path(args.cross_segment)) if args.cross_segment else []

    entity_graph = load_json(Path(args.entity_graph)) or {}
    character_arcs = load_json(Path(args.character_arcs)) if args.character_arcs else None
    character_network = load_json(Path(args.character_network)) if args.character_network else None
    narrative_structure = load_json(Path(args.narrative_structure)) if args.narrative_structure else None

    # 索引化
    structure = {r.get("segment_id"): r for r in structure_rows if r.get("segment_id")}
    interpretation = {r.get("segment_id"): r for r in interp_rows if r.get("segment_id")}
    craft = {r.get("segment_id"): r for r in craft_rows if r.get("segment_id")}
    emotion = {r.get("segment_id"): r for r in emotion_rows if r.get("segment_id")}
    cross_segment = cross_rows[0] if cross_rows else {}
    segments_by_id = {s.get("segment_id"): s for s in segments if s.get("segment_id")}
    seg_id_to_idx = {s.get("segment_id"): i for i, s in enumerate(segments)}

    # 筛选主要人物
    char_segments = extract_character_mentions(segments, entity_graph)
    total_segs = len(segments)
    main_chars = []
    for eid, seg_ids in char_segments.items():
        if len(seg_ids) >= max(3, total_segs * MAIN_CHARACTER_THRESHOLD):
            ent = next((e for e in entity_graph.get("entities", []) if e.get("entity_id") == eid), None)
            name = ent.get("canonical_name", eid) if ent else eid
            aliases = ent.get("aliases", []) if ent else []
            main_chars.append((eid, name, aliases, len(seg_ids)))

    # 按出场段数排序，取 top N
    main_chars.sort(key=lambda x: -x[3])
    main_chars = main_chars[:args.max_biographies]

    print(f"📚 人物传记聚合：{len(main_chars)} 个主要人物")

    # 构建每个人物的传记
    biographies = []
    for char_id, char_name, aliases, seg_count in main_chars:
        print(f"  📖 构建 {char_name} 的传记（出场{seg_count}段）...")
        bio = build_biography(
            char_id, char_name, aliases,
            segments, structure, interpretation, craft, emotion, cross_segment,
            entity_graph, character_arcs, character_network, narrative_structure,
            seg_id_to_idx, segments_by_id
        )
        biographies.append(bio)

    # 输出
    result = {
        "doc_id": args.doc_id,
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now().isoformat(),
        "generator": "character_biographies.py v3.12.0",
        "total_biographies": len(biographies),
        "total_segments": total_segs,
        "biographies": biographies,
        "_metadata": {
            "method": "rule_based_v3_12",
            "note": "段级批注→人物传记转换：把按时间顺序的逐段批注重新组织为以人物为中心的传记式分析",
            "main_character_threshold": MAIN_CHARACTER_THRESHOLD,
            "max_biographies": args.max_biographies,
        },
    }

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{args.doc_id}_character_biographies.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n✅ 人物传记聚合完成：{len(biographies)} 个人物传记")
    for bio in biographies[:5]:
        print(f"   - {bio['name']}：{bio['biography']['total_segments']}段，"
              f"{len(bio['timeline'])}个时间线事件，{len(bio['key_moments'])}个关键时刻，"
              f"{len(bio['decision_points'])}个决策点，{len(bio['key_quotes'])}条金句")
    if len(biographies) > 5:
        print(f"   ... 还有 {len(biographies)-5} 个人物")
    print(f"   输出 → {out_path.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
