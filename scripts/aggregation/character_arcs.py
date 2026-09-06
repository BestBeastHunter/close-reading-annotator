#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v2.9 Step 3 — 角色弧线重建（Character Arcs）

纯数据聚合（不调 LLM）：
  1. 按实体 ID 聚合该实体在所有 segment 中的 D04 + D19 数据
  2. 按 segment_index 时序排序，生成时间序列
  3. 输出每个角色的情感状态轨迹（时间→情绪→强度→极性）
  4. 判定弧线类型（上升/下降/平稳/波动/悲剧/喜剧）

用法：
  python scripts/aggregation/character_arcs.py \
    --segments outputs/annotations/moon_sixpence_zh/moon_sixpence_zh_segments.jsonl \
    --structure outputs/annotations/moon_sixpence_zh/moon_sixpence_zh_structure.jsonl \
    --emotion outputs/annotations/moon_sixpence_zh/moon_sixpence_zh_emotion.jsonl \
    --entity-graph outputs/annotations/moon_sixpence_zh/aggregation/moon_sixpence_zh_entity_graph.json \
    --doc-id moon_sixpence_zh \
    --output-dir outputs/annotations/moon_sixpence_zh/aggregation
"""

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

SCHEMA_VERSION = "3.0.0"

# 情绪极性映射
POLARITY_SCORE = {
    "positive": 1.0,
    "negative": -1.0,
    "neutral": 0.0,
    "mixed": 0.0,
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
    """从 segment_id 中提取序号。"""
    # 格式: <doc_id>_seg_<NNNN>
    parts = seg_id.rsplit("_seg_", 1)
    if len(parts) == 2:
        try:
            return int(parts[1])
        except ValueError:
            pass
    return 0


def extract_emotion_data(emotion_rows: list[dict]) -> dict[str, dict]:
    """
    从 emotion 层提取每段的 D19 情感数据。
    返回 {segment_id: {"primary_emotion": str, "intensity": int, "polarity": str, "target": str|None}}
    """
    result = {}
    for row in emotion_rows:
        seg_id = row.get("segment_id")
        if not seg_id:
            continue
        emotion = row.get("layers", {}).get("emotion", {})
        if not emotion:
            emotion = row.get("emotion", {})
        primary = emotion.get("primary", {})
        target = emotion.get("target", {})
        result[seg_id] = {
            "primary_emotion": primary.get("emotion") if isinstance(primary, dict) else None,
            "intensity": primary.get("intensity") if isinstance(primary, dict) else None,
            "polarity": primary.get("polarity") if isinstance(primary, dict) else None,
            "target_name": target.get("name") if isinstance(target, dict) else None,
            "has_arc": emotion.get("arc", {}).get("has_shift", False) if isinstance(emotion.get("arc"), dict) else False,
        }
    return result


def extract_structure_data(structure_rows: list[dict]) -> dict[str, dict]:
    """
    从 structure 层提取每段的 D04 情绪基调数据。
    返回 {segment_id: {"core": str, "intensity": int, "polarity": str, "d01": str}}
    """
    result = {}
    for row in structure_rows:
        seg_id = row.get("segment_id")
        if not seg_id:
            continue
        structure = row.get("layers", {}).get("structure", {})
        if not structure:
            structure = row.get("structure", {})
        d04 = structure.get("D04", {})
        result[seg_id] = {
            "core": d04.get("core") if isinstance(d04, dict) else None,
            "intensity": d04.get("intensity") if isinstance(d04, dict) else None,
            "polarity": d04.get("polarity") if isinstance(d04, dict) else None,
            "d01": structure.get("D01"),
        }
    return result


def find_entity_segments(entity: dict, segments: list[dict]) -> list[str]:
    """
    找出实体出现的所有段。
    优先用 entity_graph 的完整 segment_ids（v3.0.1 新增），
    否则用 mentions_sample，采样不足时用别名在原文中匹配。
    """
    # v3.0.1 修复（T-029 P1-2 + P2-1）：完整段集合优先——不再依赖截断的 mentions_sample
    full_ids = entity.get("segment_ids")
    if full_ids:
        return sorted(full_ids, key=get_segment_index)

    seg_ids = set()
    # 从 mentions_sample 中提取
    for mention in entity.get("mentions_sample", []):
        sid = mention.get("segment_id")
        if sid:
            seg_ids.add(sid)
    # 采样未覆盖全部 segment_count → 用别名在原文中匹配
    # （阈值修正：原实现 `< segment_count * 0.5` 会让 segment_count≤40 的中等角色
    #  20 条采样即超半数而不回退 → 静默漏段 + coverage_rate 虚高）
    if len(seg_ids) < entity.get("segment_count", 0):
        aliases = [entity["canonical_name"]] + entity.get("aliases", [])
        for seg in segments:
            text = seg.get("text_span", {}).get("text", "")
            for alias in aliases:
                if alias and alias in text:
                    seg_ids.add(seg["segment_id"])
                    break
    return sorted(seg_ids, key=get_segment_index)


def classify_arc(trajectory: list[dict]) -> dict:
    """
    分类弧线类型。
    基于情绪强度和极性的时序变化。
    """
    if len(trajectory) < 2:
        return {"arc_type": "insufficient_data", "confidence": 0.0, "description": "数据点不足，无法判定弧线类型"}

    # 提取极性分数序列
    polarities = []
    intensities = []
    for point in trajectory:
        pol = point.get("polarity")
        if pol in POLARITY_SCORE:
            polarities.append(POLARITY_SCORE[pol])
        inten = point.get("intensity")
        if inten is not None:
            intensities.append(inten)

    if not polarities:
        return {"arc_type": "unknown", "confidence": 0.0, "description": "无极性数据"}

    # 计算趋势
    first_half = polarities[:len(polarities) // 2]
    second_half = polarities[len(polarities) // 2:]
    avg_first = sum(first_half) / len(first_half) if first_half else 0
    avg_second = sum(second_half) / len(second_half) if second_half else 0
    trend = avg_second - avg_first

    # 计算波动
    if len(polarities) >= 2:
        variance = sum((p - sum(polarities)/len(polarities))**2 for p in polarities) / len(polarities)
    else:
        variance = 0

    # 最终状态
    final_polarity = polarities[-1]
    final_intensity = intensities[-1] if intensities else None

    # 分类
    if trend > 0.3 and final_polarity > 0:
        arc_type = "上升（喜剧弧线）"
        description = f"情绪极性从 {avg_first:.2f} 上升到 {avg_second:.2f}，最终状态积极"
    elif trend < -0.3 and final_polarity < 0:
        arc_type = "下降（悲剧弧线）"
        description = f"情绪极性从 {avg_first:.2f} 下降到 {avg_second:.2f}，最终状态消极"
    elif variance > 0.5:
        arc_type = "波动（起伏弧线）"
        description = f"情绪波动较大（方差 {variance:.2f}），经历多次起伏"
    elif abs(trend) < 0.2 and variance < 0.3:
        arc_type = "平稳（恒定弧线）"
        description = f"情绪状态相对稳定（趋势 {trend:.2f}，方差 {variance:.2f}）"
    else:
        arc_type = "复合（复杂弧线）"
        description = f"趋势 {trend:.2f}，方差 {variance:.2f}，无法简单归类"

    confidence = min(1.0, len(trajectory) / 20.0)  # 数据点越多置信度越高

    return {
        "arc_type": arc_type,
        "confidence": round(confidence, 2),
        "description": description,
        "trend_score": round(trend, 2),
        "variance": round(variance, 2),
        "final_polarity": final_polarity,
        "final_intensity": final_intensity,
    }




# v3.11.0 T-096~T-097：性格特征聚合
TRAIT_LEXICON = {
    "责任感强": {"keywords": ["必须", "责任", "担当", "配平", "保护", "守护"], "weight": 1.0},
    "勇敢": {"keywords": ["冲", "不怕", "勇往直前", "牺牲", "冲锋"], "weight": 1.0},
    "懦弱": {"keywords": ["怕", "退缩", "不敢", "逃避", "颤抖"], "weight": 1.0},
    "机智": {"keywords": ["想办法", "灵机", "巧妙", "计策", "反应快"], "weight": 1.0},
    "谨慎": {"keywords": ["小心", "仔细", "检查", "确认", "稳妥"], "weight": 1.0},
    "冲动": {"keywords": ["二话不说", "直接", "贸然", "不顾", "急躁"], "weight": 1.0},
    "忠诚": {"keywords": ["服从", "坚守", "不背叛", "信任", "追随"], "weight": 1.0},
    "善良": {"keywords": ["心疼", "同情", "帮助", "温柔", "关心"], "weight": 1.0},
    "残忍": {"keywords": ["冷酷", "无情", "残忍", "狠毒", "冷漠"], "weight": 1.0},
    "幽默": {"keywords": ["笑", "调侃", "玩笑", "滑稽", "逗"], "weight": 0.8},
    "严肃": {"keywords": ["严肃", "凝重", "沉重", "不苟言笑", "认真"], "weight": 0.8},
    "敏感": {"keywords": ["在意", "多想", "敏感", "细腻", "察觉"], "weight": 0.8},
    "豁达": {"keywords": ["无所谓", "看开", "洒脱", "不在乎", "释然"], "weight": 0.8},
    "固执": {"keywords": ["坚持", "倔强", "不改", "认定", "顽固"], "weight": 0.8},
    "灵活": {"keywords": ["随机应变", "变通", "灵活", "调整", "适应"], "weight": 0.8},
    "自信": {"keywords": ["肯定", "确信", "自信", "胸有成竹", "没问题"], "weight": 0.9},
    "自卑": {"keywords": ["不如", "差", "不行", "没用", "自卑"], "weight": 0.9},
    "冷静": {"keywords": ["冷静", "镇定", "平静", "不慌", "沉稳"], "weight": 0.9},
    "焦虑": {"keywords": ["焦虑", "紧张", "不安", "心慌", "着急"], "weight": 0.9},
    "果断": {"keywords": ["果断", "立刻", "马上", "毫不犹豫", "决断"], "weight": 0.9},
    "犹豫": {"keywords": ["犹豫", "迟疑", "纠结", "徘徊", "拿不定"], "weight": 0.9},
    "无私": {"keywords": ["奉献", "牺牲", "为别人", "不计较", "付出"], "weight": 0.9},
    "自私": {"keywords": ["只为自己", "自私", "不顾别人", "利己", "贪心"], "weight": 0.9},
    "温柔": {"keywords": ["温柔", "柔和", "轻声", "温暖", "体贴"], "weight": 0.9},
    "冷酷": {"keywords": ["冷酷", "冰冷", "冷淡", "无情", "刻薄"], "weight": 0.9},
    "热情": {"keywords": ["热情", "热烈", "积极", "主动", "热心"], "weight": 0.9},
    "冷漠": {"keywords": ["冷漠", "冷淡", "无所谓", "漠不关心", "疏离"], "weight": 0.9},
    "理想主义": {"keywords": ["理想", "信念", "追求", "梦想", "执着"], "weight": 0.8},
    "现实主义": {"keywords": ["现实", "实际", "务实", "利益", "权衡"], "weight": 0.8},
}


def infer_character_traits(character_name: str, emotion_rows: list, craft_rows: list,
                            structure_rows: list, segments: list) -> list[dict]:
    """v3.11.0 T-097：基于 D18+D19+D14-D17 跨段统计推断性格特征"""
    trait_scores = defaultdict(lambda: {"score": 0.0, "evidence": [], "segments": set()})

    # 1. 从 D18 人物语言指纹推断（口癖/言说动词→性格倾向）
    for row in craft_rows:
        craft = row.get("layers", {}).get("craft") or row.get("craft") or {}
        d18 = craft.get("D18_character_voice", []) or []
        seg_id = row.get("segment_id", "")
        for item in d18:
            if isinstance(item, dict):
                char = item.get("character", "")
                if char and (char in character_name or character_name in char):
                    pattern = item.get("pattern", "")
                    # 口癖匹配性格词表
                    for trait, info in TRAIT_LEXICON.items():
                        for kw in info["keywords"]:
                            if kw in pattern:
                                trait_scores[trait]["score"] += info["weight"]
                                trait_scores[trait]["evidence"].append(pattern[:50])
                                trait_scores[trait]["segments"].add(seg_id)

    # 2. 从 D19 情感序列推断（持续情感模式→性格特质）
    char_emotions = defaultdict(list)
    for row in emotion_rows:
        emotion = row.get("layers", {}).get("emotion", {})
        if not emotion:
            emotion = row.get("emotion", {})
        primary = emotion.get("D19_emotion_analysis") or emotion.get("primary") or {}
        if isinstance(primary, dict):
            target = primary.get("target", "")
            emo = primary.get("emotion", "")
            intensity = primary.get("intensity", 5)
            seg_id = row.get("segment_id", "")
            if target and (target in character_name or character_name in target):
                char_emotions[emo].append({"intensity": intensity, "segment_id": seg_id})

    # 情感模式→性格映射
    emotion_to_trait = {
        "焦虑": "焦虑", "紧张": "焦虑", "不安": "敏感",
        "愤怒": "冲动", "暴躁": "冲动",
        "平静": "冷静", "镇定": "冷静",
        "喜悦": "热情", "兴奋": "热情",
        "悲伤": "敏感", "忧愁": "敏感",
        "恐惧": "懦弱", "害怕": "懦弱",
    }
    for emo, instances in char_emotions.items():
        if len(instances) >= 2:  # 至少出现2次才算特质
            trait = emotion_to_trait.get(emo)
            if trait and trait in TRAIT_LEXICON:
                avg_intensity = sum(i["intensity"] for i in instances) / len(instances)
                trait_scores[trait]["score"] += len(instances) * 0.5 * (avg_intensity / 10.0)
                trait_scores[trait]["evidence"].append(f"情感'{emo}'出现{len(instances)}次")
                for i in instances:
                    trait_scores[trait]["segments"].add(i["segment_id"])

    # 3. 从 craft 层修辞/意象偏好推断（性格侧面）
    for row in craft_rows:
        craft = row.get("layers", {}).get("craft") or row.get("craft") or {}
        seg_id = row.get("segment_id", "")
        # D14 修辞偏好
        d14 = craft.get("D14_rhetoric", []) or []
        for item in d14:
            if isinstance(item, dict):
                detail = item.get("detail", "")
                for trait, info in TRAIT_LEXICON.items():
                    for kw in info["keywords"]:
                        if kw in detail:
                            trait_scores[trait]["score"] += info["weight"] * 0.3
                            trait_scores[trait]["segments"].add(seg_id)

    # 排序并取 top-5
    sorted_traits = sorted(trait_scores.items(), key=lambda x: -x[1]["score"])[:5]
    result = []
    for trait, data in sorted_traits:
        if data["score"] > 0:
            result.append({
                "trait": trait,
                "frequency": len(data["segments"]),
                "confidence": round(min(data["score"] / 5.0, 0.95), 3),
                "evidence": data["evidence"][:3],
                "evidence_segments": sorted(data["segments"])[:10],
            })
    return result

def main() -> int:
    p = argparse.ArgumentParser(description="v2.9 Step 3 — 角色弧线重建（Character Arcs）")
    p.add_argument("--segments", required=True, help="segments.jsonl 路径")
    p.add_argument("--structure", required=True, help="structure.jsonl 路径")
    p.add_argument("--emotion", required=True, help="emotion.jsonl 路径")
    p.add_argument("--entity-graph", required=True, help="entity_graph.json 路径")
    p.add_argument("--doc-id", required=True, help="文档 ID")
    p.add_argument("--output-dir", required=True, help="输出目录")
    args = p.parse_args()

    segments_path = Path(args.segments)
    structure_path = Path(args.structure)
    emotion_path = Path(args.emotion)
    entity_graph_path = Path(args.entity_graph)

    for path, name in [(segments_path, "segments"), (structure_path, "structure"),
                        (emotion_path, "emotion"), (entity_graph_path, "entity_graph")]:
        if not path.is_file():
            print(f"❌ {name} 文件不存在：{path}", file=sys.stderr)
            return 2

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # 加载数据
    segments = load_jsonl(segments_path)
    structure_rows = load_jsonl(structure_path)
    emotion_rows = load_jsonl(emotion_path)
    with open(entity_graph_path, "r", encoding="utf-8") as f:
        entity_graph = json.load(f)

    print(f"📖 加载 segments: {len(segments)} 段")
    print(f"📖 加载 structure: {len(structure_rows)} 行, emotion: {len(emotion_rows)} 行")
    print(f"📖 加载 entity_graph: {entity_graph.get('total_entities', 0)} 个实体")

    # 提取情感数据
    print("\n🚀 Step 1: 提取情感数据...")
    emotion_data = extract_emotion_data(emotion_rows)
    structure_data = extract_structure_data(structure_rows)
    print(f"   有 D19 情感数据: {len(emotion_data)} 段")
    print(f"   有 D04 情绪基调: {len(structure_data)} 段")

    # 为每个实体构建弧线
    print("\n🚀 Step 2: 构建角色弧线...")
    character_arcs = []
    entities = entity_graph.get("entities", [])

    for entity in entities:
        entity_id = entity["entity_id"]
        canonical_name = entity["canonical_name"]

        # 找出实体出现的段
        entity_segs = find_entity_segments(entity, segments)
        if not entity_segs:
            continue

        # 构建时序轨迹
        trajectory = []
        for seg_id in entity_segs:
            seg_idx = get_segment_index(seg_id)
            # 优先用 D19 情感数据，其次用 D04 情绪基调
            if seg_id in emotion_data:
                ed = emotion_data[seg_id]
                point = {
                    "segment_id": seg_id,
                    "segment_index": seg_idx,
                    "emotion_source": "D19",
                    "emotion": ed["primary_emotion"],
                    "intensity": ed["intensity"],
                    "polarity": ed["polarity"],
                    "target": ed["target_name"],
                    "has_arc_shift": ed["has_arc"],
                }
            elif seg_id in structure_data:
                sd = structure_data[seg_id]
                point = {
                    "segment_id": seg_id,
                    "segment_index": seg_idx,
                    "emotion_source": "D04",
                    "emotion": sd["core"],
                    "intensity": sd["intensity"],
                    "polarity": sd["polarity"],
                    "target": None,
                    "has_arc_shift": False,
                }
            else:
                continue
            trajectory.append(point)

        if not trajectory:
            continue

        # 分类弧线
        arc_classification = classify_arc(trajectory)

        # 计算统计
        intensities = [p["intensity"] for p in trajectory if p["intensity"] is not None]
        polarities = [POLARITY_SCORE[p["polarity"]] for p in trajectory if p["polarity"] in POLARITY_SCORE]
        d19_count = sum(1 for p in trajectory if p["emotion_source"] == "D19")
        d04_count = sum(1 for p in trajectory if p["emotion_source"] == "D04")

        character_arc = {
            "entity_id": entity_id,
            "canonical_name": canonical_name,
            "aliases": entity.get("aliases", []),
            "gender": entity.get("gender", "unknown"),
            "total_segments_present": len(entity_segs),
            "trajectory_length": len(trajectory),
            "coverage_rate": round(len(trajectory) / len(entity_segs), 2) if entity_segs else 0,
            "first_segment": trajectory[0]["segment_id"] if trajectory else None,
            "last_segment": trajectory[-1]["segment_id"] if trajectory else None,
            "avg_intensity": round(sum(intensities) / len(intensities), 2) if intensities else None,
            "max_intensity": max(intensities) if intensities else None,
            "min_intensity": min(intensities) if intensities else None,
            "avg_polarity": round(sum(polarities) / len(polarities), 2) if polarities else None,
            "d19_coverage": d19_count,
            "d04_coverage": d04_count,
            "arc_classification": arc_classification,
            "traits_aggregated": infer_character_traits(canonical_name, emotion_rows, craft_rows, structure_rows, segments),
            "key_moments": [p for p in trajectory if p.get("has_arc_shift") or (p.get("intensity") and p["intensity"] >= 7)][:10],
            "trajectory_sample": trajectory[:30],  # 只保留前30个点，避免文件过大
        }
        character_arcs.append(character_arc)

    # 按出场段数降序排列
    character_arcs.sort(key=lambda c: c["total_segments_present"], reverse=True)

    # 构建 character_arcs.json
    print("\n🚀 Step 3: 构建 character_arcs.json...")
    result = {
        "doc_id": args.doc_id,
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "total_characters": len(character_arcs),
        "total_trajectory_points": sum(c["trajectory_length"] for c in character_arcs),
        "character_arcs": character_arcs,
        "_metadata": {
            "method": "rule_based_v2_9",
            "emotion_source_priority": "D19 > D04",
            "arc_classification": "trend + variance + final_state",
            "note": "D19 为 P4 触发式（仅关键段有），D04 为全量（每段都有），覆盖率差异是设计预期",
        },
    }

    # 写入文件
    out_path = out_dir / f"{args.doc_id}_character_arcs.json"
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"\n✅ character_arcs.json 已写入: {out_path}")
    print(f"   角色数: {len(character_arcs)}")
    print(f"   总轨迹点: {result['total_trajectory_points']}")
    print("\n📊 角色弧线统计（Top 10）:")
    for arc in character_arcs[:10]:
        ac = arc["arc_classification"]
        print(f"   {arc['entity_id']} {arc['canonical_name']} ({arc['gender']}): "
              f"{arc['trajectory_length']} 轨迹点/{arc['total_segments_present']} 出场段 "
              f"(覆盖率 {arc['coverage_rate']*100:.0f}%) "
              f"→ {ac['arc_type']} (置信度 {ac['confidence']})")

    return 0


if __name__ == "__main__":
    sys.exit(main())
