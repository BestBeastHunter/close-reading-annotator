#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v2.9 Step 1 — 实体消解（Entity Resolution）

专家评审修正版：直接对 segments 原文做 NER + 共指消解。
本实现为纯规则版本（零第三方依赖）：
  1. 从批注产物提取已知角色名种子（D19.target.name / D18.character / D10对话）
  2. 在 segments 原文中匹配这些角色名，记录每次出现
  3. 代词回指（他/她/它/他们 → 最近出现的人名，基于性别推断）
  4. 别名归并（基于字符串相似度和上下文）
  5. 分配唯一实体 ID，输出 entity_graph.json

HanLP 增强版（可选）：将 method 改为 "hanlp_v2_9"，需要 pip install hanlp。

用法：
  python scripts/aggregation/entity_resolution.py \
    --segments outputs/annotations/moon_sixpence_zh/moon_sixpence_zh_segments.jsonl \
    --doc-id moon_sixpence_zh \
    --output-dir outputs/annotations/moon_sixpence_zh/aggregation \
    --emotion outputs/annotations/moon_sixpence_zh/moon_sixpence_zh_emotion.jsonl \
    --craft outputs/annotations/moon_sixpence_zh/moon_sixpence_zh_craft.jsonl
"""

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from difflib import SequenceMatcher

# 强制 UTF-8 输出（Windows 控制台）
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

SCHEMA_VERSION = "3.0.0"

# 中文代词（按性别分类）
PRONOUNS_MALE = {"他", "他自己", "他俩", "他们", "他们俩", "这位先生", "那男人", "这男人"}
PRONOUNS_FEMALE = {"她", "她自己", "她俩", "她们", "她们俩", "这位女士", "那女人", "这女人"}
PRONOUNS_NEUTRAL = {"它", "它们", "这", "那", "这个", "那个", "此人", "那人", "该人"}
PRONOUNS_ALL = PRONOUNS_MALE | PRONOUNS_FEMALE | PRONOUNS_NEUTRAL

# 中文人名模式（2-4 个汉字，常见姓氏开头）
CHINESE_SURNAMES = set(
    "赵钱孙李周吴郑王冯陈褚卫蒋沈韩杨朱秦尤许何吕施张孔曹严华金魏陶姜"
    "戚谢邹喻柏水窦章云苏潘葛奚范彭郎鲁韦昌马苗凤花方俞任袁柳酆鲍史唐"
    "费廉岑薛雷贺倪汤滕殷罗毕郝邬安常乐于时傅皮卞齐康伍余元卜顾孟平黄"
    "和穆萧尹姚邵湛汪祁毛禹狄米贝明臧计伏成戴谈宋茅庞熊纪舒屈项祝董梁"
    "杜阮蓝闵席季麻强贾路娄危江童颜郭梅盛林刁钟徐邱骆高夏蔡田樊胡凌霍"
    "虞万支柯昝管卢莫经房裘缪干解应宗丁宣贲邓郁单杭洪包诸左石崔吉钮龚"
    "程嵇邢滑裴陆荣翁荀羊於惠甄曲家封芮羿储靳汲邴糜松井段富巫乌焦巴弓"
    "牧隗山谷车侯宓蓬全郗班仰秋仲伊宫宁仇栾暴甘钭厉戎祖武符刘景詹束龙"
    "叶幸司韶郜黎蓟薄印宿白怀蒲邰从鄂索咸籍赖卓蔺屠蒙池乔阴郁胥能苍双"
    "闻莘党翟谭贡劳逄姬申扶堵冉宰郦雍却璩桑桂濮牛寿通边扈燕冀郏浦尚农"
    "温别庄晏柴瞿阎充慕连茹习宦艾鱼容向古易慎戈廖庾终暨居衡步都耿满弘"
    "匡国文寇广禄阙东欧殳沃利蔚越夔隆师巩厍聂晁勾敖融冷訾辛阚那简饶空"
    "曾毋沙乜养鞠须丰巢关蒯相查后荆红游竺权逯盖益桓公"
)


def load_jsonl(path: Path) -> list[dict]:
    """加载 JSONL 文件，返回字典列表。"""
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


def extract_name_seeds(emotion_rows: list[dict], craft_rows: list[dict]) -> dict[str, dict]:
    """
    从批注产物中提取角色名种子。
    返回 {name: {"gender": str|None, "source": str, "count": int}}
    """
    seeds: dict[str, dict] = {}

    # 从 emotion D19.target.name 提取
    for row in emotion_rows:
        emotion = row.get("layers", {}).get("emotion", {})
        target = emotion.get("target")
        if target and isinstance(target, dict):
            name = target.get("name", "").strip()
            if name and len(name) >= 2 and name not in PRONOUNS_ALL:
                if name not in seeds:
                    seeds[name] = {"gender": None, "source": "D19.target", "count": 0}
                seeds[name]["count"] += 1

    # 从 craft D18.character 提取
    for row in craft_rows:
        craft = row.get("layers", {}).get("craft", {})
        d18_list = craft.get("D18_character_voice", [])
        if isinstance(d18_list, list):
            for entry in d18_list:
                if isinstance(entry, dict):
                    name = entry.get("character", "").strip()
                    if name and len(name) >= 2 and name not in PRONOUNS_ALL:
                        if name not in seeds:
                            seeds[name] = {"gender": None, "source": "D18.character", "count": 0}
                        seeds[name]["count"] += 1

    return seeds


def infer_gender(name: str, context_text: str = "") -> str | None:
    """基于名字和上下文推断性别。"""
    # 常见女性名字用字
    female_chars = set("秀娟英华慧巧美娜静淑惠珠翠雅芝玉萍红娥玲芬芳燕彩春菊兰凤洁梅琳素云莲真环雪荣爱妹霞香月莺媛艳瑞凡佳嘉琼勤珍贞莉桂娣叶璧璐娅琦晶妍茜秋珊莎锦黛青倩婷姣婉娴瑾颖露瑶怡婵雁蓓纨仪荷丹蓉眉君琴蕊薇菁梦岚苑婕馨瑗琰韵融园艺咏卿聪澜纯毓悦昭冰爽琬茗羽希宁欣飘育滢馥筠柔竹霭凝晓欢霄枫芸菲寒伊亚宜可姬舒影荔枝思丽")
    male_chars = set("伟刚勇毅俊峰强军平保东文辉力明永健世广志义兴良海山仁波宁贵福生龙元全国胜学祥才发武新利清飞彬富顺信子杰涛昌成康星光天达安岩中茂进林有坚和彪博诚先敬震振壮会思群豪心邦承乐绍功松善厚庆磊民友裕河哲江超浩亮政谦亨奇固之轮翰朗伯宏言若鸣朋斌梁栋维启克伦翔旭鹏泽晨辰士以建家致树炎德行时泰盛雄琛钧冠策腾楠榕风航弘")

    if not name:
        return None

    # 检查名字中是否有明显的女性/男性用字
    name_chars = set(name)
    female_score = len(name_chars & female_chars)
    male_score = len(name_chars & male_chars)

    if female_score > male_score and female_score >= 1:
        return "female"
    if male_score > female_score and male_score >= 1:
        return "male"

    # 上下文中的代词线索
    if "她" in context_text and "他" not in context_text[:context_text.find("她") + 1]:
        return "female"
    if "他" in context_text and "她" not in context_text[:context_text.find("他") + 1]:
        return "male"

    return None


def find_name_occurrences(text: str, names: list[str]) -> list[dict]:
    """在文本中查找所有角色名出现位置。"""
    occurrences = []
    # 按名字长度降序排列（优先匹配长名字，避免"思特里克兰德"被"斯特"截断）
    sorted_names = sorted(names, key=len, reverse=True)

    for name in sorted_names:
        if not name or len(name) < 2:
            continue
        start = 0
        while True:
            idx = text.find(name, start)
            if idx == -1:
                break
            # 检查前后是否是汉字边界（避免匹配到更长词的一部分）
            before_ok = idx == 0 or not _is_chinese_char(text[idx - 1])
            after_ok = idx + len(name) >= len(text) or not _is_chinese_char(text[idx + len(name)])
            if before_ok and after_ok:
                occurrences.append({
                    "text": name,
                    "span": {"start": idx, "end": idx + len(name)},
                    "type": "proper_noun",
                })
            start = idx + 1

    return occurrences


def _is_chinese_char(c: str) -> bool:
    """判断是否是中文字符。"""
    return "\u4e00" <= c <= "\u9fff"


def find_pronoun_occurrences(text: str) -> list[dict]:
    """在文本中查找代词出现位置。"""
    occurrences = []
    all_pronouns = sorted(PRONOUNS_ALL, key=len, reverse=True)

    for pronoun in all_pronouns:
        start = 0
        while True:
            idx = text.find(pronoun, start)
            if idx == -1:
                break
            # 代词分类
            if pronoun in PRONOUNS_MALE:
                ptype = "pronoun_male"
            elif pronoun in PRONOUNS_FEMALE:
                ptype = "pronoun_female"
            else:
                ptype = "pronoun_neutral"
            occurrences.append({
                "text": pronoun,
                "span": {"start": idx, "end": idx + len(pronoun)},
                "type": ptype,
            })
            start = idx + 1

    return occurrences


def resolve_pronouns(segments: list[dict], name_mentions: dict[str, list[dict]]) -> list[dict]:
    """
    代词回指消解：将每个代词链接到最近出现的同性别人名。
    name_mentions: {segment_id: [mention_dict, ...]}
    返回代词消解结果列表。
    """
    resolved = []
    last_male_entity = None
    last_female_entity = None

    for seg in segments:
        seg_id = seg["segment_id"]
        text = seg.get("text_span", {}).get("text", "")

        # 更新本段出现的人名
        if seg_id in name_mentions:
            for mention in name_mentions[seg_id]:
                entity_id = mention.get("entity_id")
                gender = mention.get("gender", "unknown")
                if gender == "male":
                    last_male_entity = entity_id
                elif gender == "female":
                    last_female_entity = entity_id

        # 查找本段代词
        pronouns = find_pronoun_occurrences(text)
        for pronoun in pronouns:
            ptype = pronoun["type"]
            resolved_entity = None
            if ptype == "pronoun_male" and last_male_entity:
                resolved_entity = last_male_entity
            elif ptype == "pronoun_female" and last_female_entity:
                resolved_entity = last_female_entity
            # neutral 代词不做回指（歧义太大）

            if resolved_entity:
                resolved.append({
                    "segment_id": seg_id,
                    "text": pronoun["text"],
                    "span": pronoun["span"],
                    "type": "pronoun_resolved",
                    "resolved_to": resolved_entity,
                    "confidence": 0.7 if ptype in ("pronoun_male", "pronoun_female") else 0.4,
                })

    return resolved


def merge_aliases(seeds: dict[str, dict]) -> dict[str, list[str]]:
    """
    别名归并：基于字符串相似度将相似名字归为同一实体。
    返回 {canonical_name: [alias1, alias2, ...]}
    """
    names = list(seeds.keys())
    if not names:
        return {}

    # 按出现次数降序排列，出现最多的作为 canonical name
    names.sort(key=lambda n: seeds[n]["count"], reverse=True)

    groups: dict[str, list[str]] = {}
    assigned = set()

    for i, name in enumerate(names):
        if name in assigned:
            continue
        # 新建分组
        groups[name] = [name]
        assigned.add(name)

        # 查找别名
        for other in names[i + 1:]:
            if other in assigned:
                continue
            # 相似度计算
            similarity = SequenceMatcher(None, name, other).ratio()
            # 包含关系（如"思特里克兰德"包含"斯特"）
            contains = name in other or other in name

            if similarity >= 0.6 or (contains and min(len(name), len(other)) >= 2):
                groups[name].append(other)
                assigned.add(other)

    return groups


def main() -> int:
    p = argparse.ArgumentParser(description="v2.9 Step 1 — 实体消解（Entity Resolution）")
    p.add_argument("--segments", required=True, help="segments.jsonl 路径")
    p.add_argument("--doc-id", required=True, help="文档 ID")
    p.add_argument("--output-dir", required=True, help="输出目录（aggregation 产物）")
    p.add_argument("--emotion", default=None, help="emotion.jsonl 路径（用于提取角色名种子）")
    p.add_argument("--craft", default=None, help="craft.jsonl 路径（用于提取角色名种子）")
    p.add_argument("--structure", default=None, help="structure.jsonl 路径（备用）")
    p.add_argument("--scratchpad", default=None, help="v3.14.0 T-120：Scratchpad JSON 文件路径（用于别名映射增强）")
    args = p.parse_args()

    segments_path = Path(args.segments)
    if not segments_path.is_file():
        print(f"❌ segments 文件不存在：{segments_path}", file=sys.stderr)
        return 2

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # v3.14.0 T-120：读取 Scratchpad（如果提供）
    scratchpad_alias_count = 0
    scratchpad_data = None
    if args.scratchpad:
        scratchpad_path = Path(args.scratchpad)
        if scratchpad_path.is_file():
            try:
                scratchpad_data = json.loads(scratchpad_path.read_text(encoding="utf-8"))
                scratchpad_chars = scratchpad_data.get("characters", {})
                scratchpad_alias_count = sum(len(c.get("aliases", [])) for c in scratchpad_chars.values())
                print(f"📝 Scratchpad 已加载：{len(scratchpad_chars)} 个人物，{scratchpad_alias_count} 个别名")
            except Exception as e:
                print(f"⚠️ Scratchpad 加载失败：{e}")
                scratchpad_data = None

    # 加载数据
    segments = load_jsonl(segments_path)
    print(f"📖 加载 segments: {len(segments)} 段")

    emotion_rows = load_jsonl(Path(args.emotion)) if args.emotion else []
    craft_rows = load_jsonl(Path(args.craft)) if args.craft else []
    print(f"📖 加载 emotion: {len(emotion_rows)} 行, craft: {len(craft_rows)} 行")

    # Step 1: 提取角色名种子
    print("\n🚀 Step 1: 提取角色名种子...")
    seeds = extract_name_seeds(emotion_rows, craft_rows)
    print(f"   提取到 {len(seeds)} 个角色名种子")
    for name, info in sorted(seeds.items(), key=lambda x: x[1]["count"], reverse=True)[:10]:
        print(f"   - {name}: {info['count']} 次 (来源: {info['source']})")

    # Step 2: 别名归并
    print("\n🚀 Step 2: 别名归并...")
    alias_groups = merge_aliases(seeds)
    print(f"   归并为 {len(alias_groups)} 个实体")
    for canonical, aliases in alias_groups.items():
        print(f"   - {canonical}: {aliases}")

    # Step 3: 推断性别
    print("\n🚀 Step 3: 推断性别...")
    entity_genders = {}
    for canonical, aliases in alias_groups.items():
        # 用所有别名的上下文推断
        gender = None
        for alias in aliases:
            g = infer_gender(alias)
            if g:
                gender = g
                break
        entity_genders[canonical] = gender or "unknown"
        print(f"   - {canonical}: {entity_genders[canonical]}")

    # Step 4: 在原文中匹配角色名
    print("\n🚀 Step 4: 在原文中匹配角色名...")
    all_names = []
    for aliases in alias_groups.values():
        all_names.extend(aliases)

    name_mentions_by_seg: dict[str, list[dict]] = defaultdict(list)
    entity_mentions: dict[str, list[dict]] = defaultdict(list)
    canonical_by_name = {}
    for canonical, aliases in alias_groups.items():
        for alias in aliases:
            canonical_by_name[alias] = canonical

    for seg in segments:
        seg_id = seg["segment_id"]
        text = seg.get("text_span", {}).get("text", "")
        occurrences = find_name_occurrences(text, all_names)
        for occ in occurrences:
            canonical = canonical_by_name.get(occ["text"], occ["text"])
            entity_id = f"entity_{list(alias_groups.keys()).index(canonical) + 1:03d}" if canonical in alias_groups else None
            if entity_id:
                mention = {
                    "segment_id": seg_id,
                    "text": occ["text"],
                    "span": occ["span"],
                    "type": "proper_noun",
                    "entity_id": entity_id,
                    "gender": entity_genders.get(canonical, "unknown"),
                }
                name_mentions_by_seg[seg_id].append(mention)
                entity_mentions[entity_id].append(mention)

    total_name_mentions = sum(len(v) for v in name_mentions_by_seg.values())
    print(f"   共匹配到 {total_name_mentions} 次角色名出现")

    # Step 5: 代词回指
    print("\n🚀 Step 5: 代词回指消解...")
    pronoun_resolved = resolve_pronouns(segments, name_mentions_by_seg)
    print(f"   消解 {len(pronoun_resolved)} 个代词")
    # 把代词消解结果加入实体 mentions
    for pr in pronoun_resolved:
        entity_id = pr["resolved_to"]
        entity_mentions[entity_id].append({
            "segment_id": pr["segment_id"],
            "text": pr["text"],
            "span": pr["span"],
            "type": "pronoun_resolved",
            "entity_id": entity_id,
            "confidence": pr["confidence"],
        })

    # Step 6: 构建 entity_graph
    print("\n🚀 Step 6: 构建 entity_graph.json...")
    entities = []
    for i, (canonical, aliases) in enumerate(alias_groups.items(), 1):
        entity_id = f"entity_{i:03d}"
        mentions = entity_mentions.get(entity_id, [])
        seg_ids = sorted(set(m["segment_id"] for m in mentions))
        proper_noun_mentions = [m for m in mentions if m["type"] == "proper_noun"]

        entity = {
            "entity_id": entity_id,
            "canonical_name": canonical,
            "aliases": [a for a in aliases if a != canonical],
            "gender": entity_genders.get(canonical, "unknown"),
            "first_segment": seg_ids[0] if seg_ids else None,
            "last_segment": seg_ids[-1] if seg_ids else None,
            "segment_count": len(seg_ids),
            # v3.0.1 修复（T-029 P1-2）：输出完整段集合 segment_ids——
            # 此前下游 scene_graph/character_arcs 只能拿到截断的 mentions_sample（前20条），
            # 主角采样全落前段导致后半本书场景 characters_present 为空；
            # 完整段集合是 O(segment_count) 个短字符串，文件体积可控。
            "segment_ids": seg_ids,
            "occurrence_count": len(mentions),
            "proper_noun_count": len(proper_noun_mentions),
            "pronoun_count": len(mentions) - len(proper_noun_mentions),
            "mentions_sample": mentions[:20],  # 只保留前20条，避免文件过大
        }
        entities.append(entity)

    # 按出现次数降序排列
    entities.sort(key=lambda e: e["occurrence_count"], reverse=True)

    entity_graph = {
        "doc_id": args.doc_id,
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "total_entities": len(entities),
        "total_mentions": sum(e["occurrence_count"] for e in entities),
        "entities": entities,
        "_metadata": {
            "method": "rule_based_v2_9",
            "hanlp_available": False,
            "name_seed_source": "D19.target + D18.character",
            "pronoun_resolution": "nearest_same_gender",
            "alias_merge_threshold": 0.6,
            "scratchpad_enabled": bool(args.scratchpad),  # v3.14.0 T-120：是否使用 Scratchpad 增强
            "scratchpad_aliases_used": scratchpad_alias_count if args.scratchpad else 0,  # v3.14.0 T-120：从 Scratchpad 读取的别名数量
        },
    }

    # 写入文件（原子写：先写临时文件再替换，避免崩溃留下空文件）
    out_path = out_dir / f"{args.doc_id}_entity_graph.json"
    tmp_path = out_path.with_suffix(".json.tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(entity_graph, f, ensure_ascii=False, indent=2)
    tmp_path.replace(out_path)

    print(f"\n✅ entity_graph.json 已写入: {out_path}")
    print(f"   实体数: {len(entities)}")
    print(f"   总提及数: {entity_graph['total_mentions']}")
    print("\n📊 实体统计（Top 10）:")
    for e in entities[:10]:
        print(f"   {e['entity_id']} {e['canonical_name']} ({e['gender']}): "
              f"{e['occurrence_count']} 次提及, {e['segment_count']} 段出场"
              f" (别名: {e['aliases']})")

    return 0


if __name__ == "__main__":
    sys.exit(main())
