#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/validate_output.py — 统一校验脚本 v2.7.0（含 D19/emotion 文件校验）

校验范围（四层所有产物）：
  - structure.jsonl      : Structure 层批注（必填枚举 / 强度范围 / 必填非 null）
  - interpretation.jsonl : Interpretation 层批注（含 D06 引文子串校验）
  - craft.jsonl          : 文笔层批注（含引文子串 + span 位置断言 + 相似度 ≥95%）
  - cross_segment.jsonl  : 跨段层（枚举校验 / 双引用完整性）
  - merged.jsonl         : 合并后嵌套文档（结构校验）

零第三方依赖：仅 Python 3.6+ 标准库。

用法：
  # 校验单条 JSON 或单个 JSON 文件
  python scripts/validate_output.py --json path/to/one.json

  # 校验 JSONL（逐行）
  python scripts/validate_output.py --jsonl path/to/xxx.structure.jsonl

  # 指定层类型（auto 时按文件名猜测：structure/interpretation/craft/cross_segment/merged）
  python scripts/validate_output.py --jsonl xxx.jsonl --layer-type structure

  # 读取 segments.jsonl（跨段校验、D18 全文引文需要）
  python scripts/validate_output.py --jsonl xxx.craft.jsonl --segments xxx_segments.jsonl
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

# v2.5.1 修复 #1：Windows GBK 控制台 UnicodeEncodeError（emoji 打印崩溃）
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ---------------- 与 schema.md 严格一致的枚举 ----------------

# v2.9.0：D04 词表手术（删 尊严/背叛/贪婪/宽恕 4 非情绪词 → 补 羞耻/惊讶/渴望/厌恶）；2.8.0 及更早产物旧词版本分支豁免（历史数据豁免，非可选）；D19 44→50 词（补 羞耻/渴望/嫉妒/迷茫/感动/得意）
SUPPORTED_SCHEMA_VERSIONS = {"2.5.0", "2.6.0", "2.7.0", "2.8.0", "2.9.0"}
SUPPORTED_STATUS = {"tentative", "confirmed", "superseded"}
SUPPORTED_SECTION_TYPE = {"frontmatter", "body", "epilogue"}

# D01 叙事功能
D01_VALUES = {
    "背景铺垫", "激励事件", "上升行动", "转折", "高潮",
    "下降行动", "结局", "过渡", "复合功能", "无法判断",
}

# D04 核心情绪（20，v2.9.0 手术后的新词表）
D04_CORE_VALUES = {
    "平静", "压抑", "焦虑", "悲伤", "愤怒", "恐惧", "喜悦", "希望", "绝望",
    "孤独", "信任", "屈辱", "嫉妒", "复仇", "悬疑", "释然",
    "羞耻", "惊讶", "渴望", "厌恶",
}

# D04 旧版词表（2.8.0 及更早产物版本分支豁免——历史数据豁免，非可选）
D04_CORE_LEGACY_VALUES = D04_CORE_VALUES | {"尊严", "背叛", "贪婪", "宽恕"}

# D04 情感极性（v2.6.0 新增。2.6.0 产物必填；2.5.0 旧产物豁免——历史数据豁免，非可选）
D04_POLARITY_VALUES = {"positive", "negative", "neutral", "mixed"}

# D07 视角类型（7）
D07_TYPES = {
    "第一人称", "第二人称", "第三人称有限", "第三人称全知",
    "多视角", "不可靠叙述者", "客观叙事",
}

# D10 对话功能（6）
D10_VALUES = {"推动情节", "揭示性格", "传递信息", "制造冲突", "营造氛围", "复合功能"}

# D11 描写类型（5）
D11_VALUES = {"环境描写", "心理描写", "动作描写", "外貌描写", "感官描写"}

# Layer 2 额外枚举
D06_TYPES = {"揭示", "隐藏", "误导", "复合"}
NARRATOR_RELIABILITY_VALUES = {"可靠", "部分不可靠", "不可靠", "无法判断"}

# D19 情感词表（v2.9.0，50 词。真源 = references/emotion-lexicon.md，白名单必须逐词同步该文件）
EMOTION_LEXICON_VALUES = {
    # 基础层（Plutchik 8 基元）
    "喜悦", "悲伤", "愤怒", "恐惧", "惊讶", "期待", "厌恶", "信任",
    # 文学扩展层（42 词，v2.9.0 补 6：羞耻/渴望/嫉妒/迷茫/感动/得意）
    "依恋", "眷恋", "温情", "甜蜜", "哀恸", "苍凉", "怅惘", "物哀", "悲悯", "怀旧",
    "心碎", "绝望", "宽慰", "安宁", "旷达", "释然", "崇敬", "敬畏", "震撼", "崇高感",
    "荒诞感", "漂泊感", "隐忍", "焦虑", "恐慌", "鄙夷", "疏离", "厌倦", "冷漠",
    "羞耻", "渴望", "嫉妒", "迷茫", "感动", "得意",
    "悲欣交集", "爱恨交织", "苦乐参半",
    # 姿态复合词（4，表面姿态与底色情感冲突时使用）
    "克制中的温情", "冷峻中的悲悯", "叙述性冷漠", "反讽性平静",
}

# Craft 维度枚举
RHETORIC_TYPES = {"比喻", "拟人", "排比", "反讽", "通感", "夸张", "对比", "象征"}
IMAGERY_TYPES = {"自然意象", "器物意象", "人体意象", "色彩意象", "抽象意象"}
POS_TYPES = {"动词", "形容词", "副词", "名词"}
SYNTAX_TYPES = {"排比", "长短交替", "倒装", "独词句", "对偶", "设问"}

# Cross-segment 关系类型
RELATION_TYPES = {"伏笔-回收", "因果", "时序", "对比", "呼应"}

# 置信度 method
CONFIDENCE_METHODS = {"model_self_report", "consistency_check", "human_review"}


def _normalize_whitespace(s: str) -> str:
    return " ".join(s.split())


def _extract_quoted(text: str) -> list[str]:
    """从自由文本提取引号内容：「」、""、《》。"""
    if not text:
        return []
    pattern = re.compile(r"[「」\"\"《》]")
    parts = pattern.split(text)
    return [p.strip() for i, p in enumerate(parts) if i % 2 == 1 and p.strip()]


def _seq_ratio(a: str, b: str) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


# ---------------- 结构/层校验 ----------------

def _is_valid_confidence_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and 0.0 <= float(v) <= 1.0


def _check_required_root_keys(ann: dict) -> list[str]:
    required = [
        "schema_version", "annotation_id", "document_id", "segment_id",
        "chapter", "section_type", "text_span", "confidence",
        "null_reasons", "alternatives", "status", "_metadata",
    ]
    return [f"缺失必填顶层字段：{k}" for k in required if k not in ann]


def _check_text_span(ann: dict) -> list[str]:
    errs = []
    ts = ann.get("text_span", {})
    if not isinstance(ts, dict):
        return ["text_span 必须是 object"]
    for k in ("hash", "start_char", "end_char", "text"):
        if k not in ts:
            errs.append(f"text_span.{k} 缺失")
    text = ts.get("text", "")
    s, e = ts.get("start_char", -1), ts.get("end_char", -1)
    if isinstance(s, int) and isinstance(e, int) and isinstance(text, str):
        if len(text) != e - s:
            errs.append(f"text_span.text 长度 ({len(text)}) 与 end-start ({e - s}) 不一致")
    return errs


def _check_confidence_and_status(ann: dict, layer_name: str) -> tuple[list[str], list[str]]:
    """返回 (errors, warnings)。含 status 置信度规则自动推导（§四.C）。"""
    errs: list[str] = []
    warns: list[str] = []
    conf = ann.get("confidence", {})
    if not isinstance(conf, dict):
        return ["confidence 必须是 object"], []
    overall = conf.get("overall")
    if not _is_valid_confidence_number(overall):
        errs.append(f"confidence.overall 必须是 0-1 数字，实际 {overall!r}")
    method = conf.get("confidence_method")
    if method not in CONFIDENCE_METHODS:
        errs.append(f"confidence.confidence_method 必须是 {sorted(CONFIDENCE_METHODS)} 之一")
    per_dim = conf.get("per_dimension", {})
    if not isinstance(per_dim, dict):
        errs.append("confidence.per_dimension 必须是 object")

    # 必填维度：layer=structure 的 7 维必须是数字（不能 null）
    required_dims_struct = ["D01", "D04", "D05", "D07", "D08", "D10", "D11"]
    optional_dims_interp = ["D06", "D09"]
    optional_dims_craft = ["D13", "D14", "D15", "D16", "D17", "D18"]

    if layer_name == "structure":
        for d in required_dims_struct:
            if not _is_valid_confidence_number(per_dim.get(d)):
                errs.append(f"confidence.per_dimension.{d} 必须是 0-1 数字（必填维度，即使 null 情形也填）")
    elif layer_name == "interpretation":
        for d in optional_dims_interp:
            v = per_dim.get(d)
            if v is not None and not _is_valid_confidence_number(v):
                errs.append(f"confidence.per_dimension.{d} 无效：{v!r}")
    elif layer_name == "craft":
        for d in optional_dims_craft:
            v = per_dim.get(d)
            if v is not None and not _is_valid_confidence_number(v):
                errs.append(f"confidence.per_dimension.{d} 无效：{v!r}")
    elif layer_name == "emotion":
        if not _is_valid_confidence_number(per_dim.get("D19")):
            errs.append("confidence.per_dimension.D19 必须是 0-1 数字（P4 触发段必填）")

    # status 枚举
    if ann.get("status") not in SUPPORTED_STATUS:
        errs.append(f"status 必须在 {sorted(SUPPORTED_STATUS)} 内，实际 {ann.get('status')!r}")

    # §四.C 自动推导（仅当 status != superseded 时）
    status = ann.get("status")
    if isinstance(overall, (int, float)) and status != "superseded":
        if overall >= 0.8 and status != "confirmed":
            warns.append(
                f"confidence.overall={overall:.2f}>=0.8 但 status={status!r}（应为 confirmed，建议检查是否人工审核）"
            )
        if overall < 0.8 and status == "confirmed":
            errs.append(
                f"confidence.overall={overall:.2f}<0.8 但 status=confirmed，违反 §四.C 规则"
            )
    return errs, warns


def _check_null_reasons_and_alternatives(ann: dict) -> list[str]:
    errs: list[str] = []
    nr = ann.get("null_reasons")
    if not isinstance(nr, dict):
        errs.append("null_reasons 必须是 object")
    alts = ann.get("alternatives")
    if not isinstance(alts, list):
        errs.append("alternatives 必须是 array")
    return errs


# ---------------- Layer 校验 ----------------

def validate_structure_layer(ann: dict) -> tuple[list[str], list[str]]:
    errs, warns = _check_required_root_keys(ann), []
    if errs:
        return errs, warns
    layers = ann.get("layers", {})
    struct = layers.get("structure")
    if not isinstance(struct, dict):
        return [*errs, "layers.structure 缺失"], []
    errs.extend(_check_text_span(ann))
    cerrs, cwarns = _check_confidence_and_status(ann, "structure")
    errs.extend(cerrs)
    warns.extend(cwarns)
    errs.extend(_check_null_reasons_and_alternatives(ann))

    # D01
    d01 = struct.get("D01")
    if d01 not in D01_VALUES:
        errs.append(f"D01={d01!r} 不在枚举中")
    # D04
    d04 = struct.get("D04")
    if isinstance(d04, dict):
        core = d04.get("core")
        intensity = d04.get("intensity")
        if core not in D04_CORE_VALUES:
            if ann.get("schema_version") in {"2.5.0", "2.6.0", "2.7.0", "2.8.0"} and core in D04_CORE_LEGACY_VALUES:
                pass  # 2.8.0 及更早旧词版本分支豁免（历史数据豁免）
            else:
                errs.append(f"D04.core={core!r} 不在枚举 {sorted(D04_CORE_VALUES)} 内")
        if not (isinstance(intensity, int) and 1 <= intensity <= 10):
            errs.append(f"D04.intensity={intensity!r} 必须是 1-10 整数")
        pol = d04.get("polarity")
        if pol not in D04_POLARITY_VALUES:
            if ann.get("schema_version") == "2.6.0":
                errs.append(f"D04.polarity 缺失或={pol!r}：v2.6.0 产物必填，必须 ∈ {sorted(D04_POLARITY_VALUES)}")
            elif pol is not None:
                errs.append(f"D04.polarity={pol!r} 必须是 {sorted(D04_POLARITY_VALUES)} 之一（2.5.0 旧产物无此字段，出现则须合法）")
    else:
        errs.append("D04 必须是 object")
    # D05
    d05 = struct.get("D05")
    if not (isinstance(d05, int) and 1 <= d05 <= 5):
        errs.append(f"D05={d05!r} 必须是 1-5 整数")
    # D07
    d07 = struct.get("D07")
    if isinstance(d07, dict):
        if d07.get("type") not in D07_TYPES:
            errs.append(f"D07.type={d07.get('type')!r} 不在枚举中")
        if not isinstance(d07.get("is_switch_point"), bool):
            errs.append("D07.is_switch_point 必须是 bool")
    else:
        errs.append("D07 必须是 object")
    # D08
    d08 = struct.get("D08")
    if not isinstance(d08, dict) or "time" not in d08 or "space" not in d08:
        errs.append("D08 必须是含 time/space 的 object")
    # D10（可 null）
    d10 = struct.get("D10")
    if d10 is not None and d10 not in D10_VALUES:
        errs.append(f"D10={d10!r} 不在枚举中")
    # D11（非空数组）
    d11 = struct.get("D11")
    if not isinstance(d11, list) or len(d11) == 0:
        errs.append("D11 必须是非空数组（至少 1 种描写类型）")
    else:
        for it in d11:
            if it not in D11_VALUES:
                errs.append(f"D11 含非法值 {it!r}")

    # section_type
    if ann.get("section_type") not in SUPPORTED_SECTION_TYPE:
        errs.append(f"section_type 必须在 {sorted(SUPPORTED_SECTION_TYPE)} 内")

    return errs, warns


def validate_interpretation_layer(ann: dict) -> tuple[list[str], list[str]]:
    errs, warns = _check_required_root_keys(ann), []
    if errs:
        return errs, warns
    layers = ann.get("layers", {})
    interp = layers.get("interpretation")
    if not isinstance(interp, dict):
        return [*errs, "layers.interpretation 缺失"], []
    errs.extend(_check_text_span(ann))
    cerrs, cwarns = _check_confidence_and_status(ann, "interpretation")
    errs.extend(cerrs)
    warns.extend(cwarns)
    errs.extend(_check_null_reasons_and_alternatives(ann))

    text_src = ann.get("text_span", {}).get("text", "")
    norm_src = _normalize_whitespace(text_src)

    # D06（信息控制）引文校验
    d06 = interp.get("D06_information_control")
    if d06 is not None:
        if not isinstance(d06, dict):
            errs.append("D06_information_control 必须是 object 或 null")
        else:
            if d06.get("type") not in D06_TYPES:
                errs.append(f"D06.type={d06.get('type')!r} 不在枚举中")
            content = d06.get("content", "") or ""
            quotes = _extract_quoted(content)
            for q in quotes:
                if not q:
                    continue
                if _normalize_whitespace(q) not in norm_src:
                    errs.append(f"D06 引文不在原文中: {q[:50]!r}")
    # D09（主题标签，≤3）
    d09 = interp.get("D09")
    if d09 is not None:
        if not isinstance(d09, list):
            errs.append("D09 必须是数组或 null")
        elif len(d09) > 3:
            errs.append(f"D09 标签数 {len(d09)} 超过上限 3")
    # narrator_reliability
    nr = interp.get("narrator_reliability")
    if nr is not None and nr not in NARRATOR_RELIABILITY_VALUES:
        errs.append(f"narrator_reliability={nr!r} 不在枚举 {sorted(NARRATOR_RELIABILITY_VALUES)} 内")

    return errs, warns


def validate_emotion_layer(ann: dict) -> tuple[list[str], list[str]]:
    """D19 情感分析（emotion.jsonl，v2.7.0，P4 Pass）校验。

    emotion 枚举真源 = references/emotion-lexicon.md（50 词）；key_phrases 必须过原文子串校验；
    target / trigger / arc 均 null-合法（禁止为凑结构编造情感弧）。
    """
    errs, warns = _check_required_root_keys(ann), []
    if errs:
        return errs, warns
    layers = ann.get("layers", {})
    emo = layers.get("emotion")
    if not isinstance(emo, dict):
        return [*errs, "layers.emotion 缺失"], []
    d19 = emo.get("D19_emotion_analysis")
    if not isinstance(d19, dict):
        # v2.8.0+ 直接格式（layers.emotion.primary.* 等）兼容：识别到 primary 即提升一层校验；
        # 兼容 v2.8 数据修复后未升版本号、但结构已为直接格式的混合产物（如 moon 2.7.0+直接格式）。
        if isinstance(emo.get("primary"), dict):
            d19 = emo
        else:
            return [*errs, "layers.emotion.D19_emotion_analysis 缺失"], []
    errs.extend(_check_text_span(ann))
    cerrs, cwarns = _check_confidence_and_status(ann, "emotion")
    errs.extend(cerrs)
    warns.extend(cwarns)
    errs.extend(_check_null_reasons_and_alternatives(ann))

    text_src = ann.get("text_span", {}).get("text", "")
    norm_src = _normalize_whitespace(text_src)

    def _chk_emo(prefix, e):
        """校验一个情感对象（emotion/intensity/polarity 三元组）。"""
        if not isinstance(e, dict):
            errs.append(f"{prefix} 必须是 object")
            return
        em = e.get("emotion")
        if em not in EMOTION_LEXICON_VALUES:
            errs.append(f"{prefix}.emotion={em!r} 不在 emotion-lexicon.md 词表（50 词）内")
        it = e.get("intensity")
        if not (isinstance(it, int) and 1 <= it <= 10):
            errs.append(f"{prefix}.intensity={it!r} 必须是 1-10 整数")
        pol = e.get("polarity")
        if pol not in D04_POLARITY_VALUES:
            errs.append(f"{prefix}.polarity={pol!r} 必须 ∈ {sorted(D04_POLARITY_VALUES)}")

    # 1. primary（必填）
    _chk_emo("D19.primary", d19.get("primary"))
    # 2. secondary（null 或 1-2 项）
    sec = d19.get("secondary")
    if sec is not None:
        if not isinstance(sec, list) or not sec:
            errs.append("D19.secondary 必须是 null 或非空数组")
        elif len(sec) > 2:
            warns.append(f"D19.secondary 建议 ≤ 2 项（当前 {len(sec)}）")
        else:
            for i, s in enumerate(sec):
                _chk_emo(f"D19.secondary[{i}]", s)
    # 3. target（null-合法）
    tgt = d19.get("target")
    if tgt is not None:
        if not isinstance(tgt, dict):
            errs.append("D19.target 必须是 object 或 null")
        else:
            if not (isinstance(tgt.get("name"), str) and tgt.get("name").strip()):
                errs.append("D19.target.name 必填字符串（target 非 null 时）")
            for k in ("entity_id", "relation"):
                v = tgt.get(k)
                if v is not None and not isinstance(v, str):
                    errs.append(f"D19.target.{k} 必须是 string 或 null")
    # 4. trigger（null-合法）
    trg = d19.get("trigger")
    if trg is not None:
        if not isinstance(trg, dict):
            errs.append("D19.trigger 必须是 object 或 null")
        else:
            if not (isinstance(trg.get("description"), str) and trg["description"].strip()):
                errs.append("D19.trigger.description 必填非空字符串（trigger 非 null 时）")
            ss = trg.get("source_segment")
            if ss is not None and not isinstance(ss, str):
                errs.append("D19.trigger.source_segment 必须是 string 或 null")
    # 5. arc（null-合法；非 null 必须有位移）
    arc = d19.get("arc")
    if arc is not None:
        if not isinstance(arc, dict):
            errs.append("D19.arc 必须是 object 或 null")
        elif arc.get("has_shift") is not True:
            errs.append("D19.arc.has_shift 必须为 true（arc 非 null 时）")
        else:
            if not (isinstance(arc.get("shift_point"), str) and arc["shift_point"].strip()):
                errs.append("D19.arc.shift_point 必填非空字符串（arc 非 null 时）")
            _chk_emo("D19.arc.before", arc.get("before"))
            _chk_emo("D19.arc.after", arc.get("after"))
    # 6. expression（必填；key_phrases 逐条原文子串）
    exp = d19.get("expression")
    if not isinstance(exp, dict):
        errs.append("D19.expression 必须存在")
    else:
        for k in ("direct", "indirect"):
            if not isinstance(exp.get(k), bool):
                errs.append(f"D19.expression.{k} 必须是 boolean")
        kps = exp.get("key_phrases")
        if not isinstance(kps, list) or not kps:
            errs.append("D19.expression.key_phrases 必须是非空数组（每项为原文子串）")
        else:
            for i, kp in enumerate(kps):
                if not isinstance(kp, str) or not kp.strip():
                    errs.append(f"D19.expression.key_phrases[{i}] 必须是字符串")
                    continue
                if _normalize_whitespace(kp) not in norm_src:
                    errs.append(f"D19.expression.key_phrases 不在原文中: {kp[:50]!r}")
        note = exp.get("note")
        if note is not None and not isinstance(note, str):
            errs.append("D19.expression.note 必须是 string 或 null")
    return errs, warns


def _validate_craft_entry(
    dim: str,
    item: dict,
    text_src: str,
) -> tuple[list[str], list[str]]:
    """校验单个 craft 条目：引文子串 + span 位置。"""
    errs, warns = [], []
    if not isinstance(item, dict):
        return [f"{dim} 条目必须是 object"], []
    item_text = item.get("text", "")
    if not isinstance(item_text, str) or not item_text:
        return [f"{dim} 条目缺少 text"], []
    norm_src = _normalize_whitespace(text_src)
    norm_q = _normalize_whitespace(item_text)
    # 5.B 子串验证
    if norm_q not in norm_src:
        errs.append(f"{dim} 引文不在原文中: {item_text[:50]!r}")
        return errs, warns
    # 5.B 位置验证
    span = item.get("span")
    if span is not None:
        if not isinstance(span, dict) or "start" not in span or "end" not in span:
            errs.append(f"{dim} span 必须是含 start/end 的 object 或 null")
            return errs, warns
        s, e = span["start"], span["end"]
        if not (isinstance(s, int) and isinstance(e, int) and 0 <= s < e <= len(text_src)):
            errs.append(f"{dim} span 越界: start={s} end={e} src_len={len(text_src)}")
            return errs, warns
        sliced = text_src[s:e]
        ratio = _seq_ratio(_normalize_whitespace(sliced), norm_q)
        if ratio < 0.85:
            errs.append(f"{dim} span 切片与 text 相似度仅 {ratio:.2f} (<0.85，漂移严重)")
        elif ratio < 0.95:
            warns.append(f"{dim} span 切片与 text 相似度 {ratio:.2f}（<0.95，建议微调 span 边界）")
    return errs, warns


def validate_craft_layer(ann: dict) -> tuple[list[str], list[str]]:
    errs, warns = _check_required_root_keys(ann), []
    if errs:
        return errs, warns
    craft = ann.get("craft")
    if not isinstance(craft, dict):
        # v2.8.0+ 格式统一：craft 在 layers.craft 下（v2.7 顶层 craft 旧格式版本分支豁免）
        layers_craft = (ann.get("layers") or {}).get("craft")
        if isinstance(layers_craft, dict):
            craft = layers_craft
        else:
            return [*errs, "顶层 craft 键缺失（必须是 object）"], []
    errs.extend(_check_text_span(ann))
    cerrs, cwarns = _check_confidence_and_status(ann, "craft")
    errs.extend(cerrs)
    warns.extend(cwarns)
    errs.extend(_check_null_reasons_and_alternatives(ann))
    text_src = ann.get("text_span", {}).get("text", "")

    # D13 佳句（quality_score 1-5）
    for it in craft.get("D13_golden_lines", []) or []:
        e, w = _validate_craft_entry("D13", it, text_src)
        errs.extend(e)
        warns.extend(w)
        qs = it.get("quality_score")
        if qs is not None and not (isinstance(qs, int) and 1 <= qs <= 5):
            errs.append(f"D13 quality_score={qs!r} 必须是 1-5 整数")
    # D14 修辞
    for it in craft.get("D14_rhetoric", []) or []:
        e, w = _validate_craft_entry("D14", it, text_src)
        errs.extend(e)
        warns.extend(w)
        if it.get("type") not in RHETORIC_TYPES:
            errs.append(f"D14.type={it.get('type')!r} 不在枚举中")
    # D15 意象
    for it in craft.get("D15_imagery", []) or []:
        e, w = _validate_craft_entry("D15", it, text_src)
        errs.extend(e)
        warns.extend(w)
        if it.get("type") not in IMAGERY_TYPES:
            errs.append(f"D15.type={it.get('type')!r} 不在枚举中")
    # D16 词汇
    for it in craft.get("D16_diction", []) or []:
        e, w = _validate_craft_entry("D16", it, text_src)
        errs.extend(e)
        warns.extend(w)
        if it.get("pos") not in POS_TYPES:
            errs.append(f"D16.pos={it.get('pos')!r} 不在枚举中")
    # D17 句式
    for it in craft.get("D17_syntax", []) or []:
        e, w = _validate_craft_entry("D17", it, text_src)
        errs.extend(e)
        warns.extend(w)
        if it.get("type") not in SYNTAX_TYPES:
            errs.append(f"D17.type={it.get('type')!r} 不在枚举中")
    # D18 人物语言指纹（放宽：引文可以不在本段内，warning 级别）
    for it in craft.get("D18_character_voice", []) or []:
        if not isinstance(it, dict):
            errs.append("D18 条目必须是 object")
            continue
        pattern = it.get("pattern", "") or ""
        if not pattern:
            errs.append("D18 条目缺少 pattern（习语/口癖）")
            continue
        norm_src = _normalize_whitespace(text_src)
        if _normalize_whitespace(pattern) not in norm_src:
            warns.append(f"D18 pattern={pattern[:40]!r} 不在本段 text_span（可接受：D18 跨段聚合）")
    return errs, warns


def validate_cross_segment(obj: dict) -> tuple[list[str], list[str]]:
    errs, warns = [], []
    for k in ("schema_version", "doc_id", "cross_refs"):
        if k not in obj:
            errs.append(f"缺失顶层字段：{k}")
    refs = obj.get("cross_refs", [])
    if not isinstance(refs, list):
        return [*errs, "cross_refs 必须是 array"], []
    for i, ref in enumerate(refs):
        prefix = f"cross_refs[{i}]"
        for key in ("ref_id", "relation_type", "source", "target"):
            if key not in ref:
                errs.append(f"{prefix} 缺少 {key}")
        if ref.get("relation_type") not in RELATION_TYPES:
            errs.append(f"{prefix}.relation_type={ref.get('relation_type')!r} 不在枚举中")
        for end in ("source", "target"):
            node = ref.get(end, {})
            if not isinstance(node, dict):
                continue
            if "segment_id" not in node:
                errs.append(f"{prefix}.{end} 缺少 segment_id（位置 ID，双引用要求）")
            if not node.get("anchor_text"):
                warns.append(f"{prefix}.{end} 缺少 anchor_text（内容锚点，双引用要求建议补全）")
    return errs, warns


def validate_merged(obj: dict) -> tuple[list[str], list[str]]:
    errs: list[str] = []
    for k in ("segment_id", "chapter", "section_type", "text_span"):
        if k not in obj:
            errs.append(f"merged 缺少顶层字段 {k}")
    return errs, []


# ---------------- 入口 ----------------

def _detect_layer_from_path(path: Path) -> str:
    name = path.name
    if ".structure." in name:
        return "structure"
    if ".interpretation." in name:
        return "interpretation"
    if ".emotion." in name:
        return "emotion"
    if ".craft." in name:
        return "craft"
    if ".cross_segment." in name:
        return "cross_segment"
    if ".merged." in name:
        return "merged"
    # keywords fallback
    if "structure" in name:
        return "structure"
    if "interpretation" in name:
        return "interpretation"
    if "emotion" in name:
        return "emotion"
    if "craft" in name:
        return "craft"
    if "cross_segment" in name:
        return "cross_segment"
    if "merged" in name:
        return "merged"
    return "auto"


def _call_validator(obj: dict, layer: str) -> tuple[list[str], list[str]]:
    if layer == "structure":
        return validate_structure_layer(obj)
    if layer == "interpretation":
        return validate_interpretation_layer(obj)
    if layer == "emotion":
        return validate_emotion_layer(obj)
    if layer == "craft":
        return validate_craft_layer(obj)
    if layer == "cross_segment":
        return validate_cross_segment(obj)
    if layer == "merged":
        return validate_merged(obj)
    # auto：尝试基于存在键启发
    if isinstance(obj, dict):
        if obj.get("layers", {}).get("structure"):
            return validate_structure_layer(obj)
        if obj.get("layers", {}).get("interpretation"):
            return validate_interpretation_layer(obj)
        if obj.get("layers", {}).get("emotion"):
            return validate_emotion_layer(obj)
        if obj.get("craft") is not None:
            return validate_craft_layer(obj)
        if obj.get("cross_refs") is not None:
            return validate_cross_segment(obj)
        if obj.get("segment_id") and "structure" in obj:
            return validate_merged(obj)
    return [f"无法识别层类型，请用 --layer-type 指定：structure/interpretation/craft/cross_segment/merged"], []


def _load_jsonl(path: Path) -> list[dict]:
    items: list[dict] = []
    with path.open("r", encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                items.append(json.loads(line))
            except json.JSONDecodeError as e:
                print(f"⚠️ JSONL 第 {i} 行解析失败：{e}", file=sys.stderr)
    return items


def main() -> int:
    p = argparse.ArgumentParser(description="【精读批注 v2.6】四层输出统一校验（枚举/引文/span/置信度/status）")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--json", help="单个 JSON 文件或 JSON 字符串")
    g.add_argument("--jsonl", help="JSONL 文件（逐行校验）")
    p.add_argument("--layer-type", choices=["auto", "structure", "interpretation", "emotion", "craft", "cross_segment", "merged"], default="auto")
    p.add_argument("--segments", help="segments.jsonl（跨段/D18 校验可选）")
    args = p.parse_args()

    objects: list[tuple[str, dict]] = []  # (label, obj)

    if args.json:
        if Path(args.json).is_file():
            with open(args.json, "r", encoding="utf-8") as f:
                obj = json.load(f)
            objects.append((args.json, obj))
        else:
            obj = json.loads(args.json)
            objects.append(("cli-inline", obj))
    else:
        jp = Path(args.jsonl)
        if not jp.is_file():
            print(f"❌ 文件不存在：{jp}", file=sys.stderr)
            return 2
        for i, obj in enumerate(_load_jsonl(jp)):
            objects.append((f"{jp}#L{i+1}", obj))

    if args.layer_type == "auto" and args.jsonl:
        guessed = _detect_layer_from_path(Path(args.jsonl))
        if guessed != "auto":
            args.layer_type = guessed
            print(f"[validate_output] 根据文件名推断 layer-type = {guessed}")

    total = 0
    passed = 0
    total_err = 0
    total_warn = 0
    for label, obj in objects:
        total += 1
        errs, warns = _call_validator(obj, args.layer_type)
        # schema_version 校验
        sv = obj.get("schema_version") if isinstance(obj, dict) else None
        if sv not in SUPPORTED_SCHEMA_VERSIONS and not (args.layer_type == "merged"):
            errs.insert(0, f"schema_version={sv!r} 不在允许集合 {sorted(SUPPORTED_SCHEMA_VERSIONS)} 内（merged 层可放宽）")
        if not errs:
            passed += 1
        else:
            total_err += len(errs)
        total_warn += len(warns)
        # 输出每条
        status_icon = "✅" if not errs else "❌"
        print(f"{status_icon} {label}")
        for e in errs:
            print(f"   ✖ error: {e}")
        for w in warns:
            print(f"   ⚠ warning: {w}")

    print(
        f"\n[validate_output] 总计 {total} 条：✅ {passed} 通过，❌ {total - passed} 失败，"
        f"error={total_err}, warning={total_warn}"
    )
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
