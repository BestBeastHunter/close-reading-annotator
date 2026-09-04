#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/span_locator.py — span 定位公共模块（v2.7 工程化修复轮，决策 18）

定位算法与 validate_output.py 的引文校验口径对齐（决策 3 / SKILL.md §五 引文校验）：
  1) 原文精确子串 → 命中返回 {start, end}；
  2) 空白归一化子串（" ".join(s.split())）→ 通过 index_map 回算 raw 下标。

被以下脚本复用：
  - annotate_segment.py：校验失败时对 span 缺失/漂移的 craft 条目自动回算修正（兑现「自动重试 ≤3 次」）；
  - fill_spans.py：存量产物（craft / cross_segment）的 span 一次性回补。

零第三方依赖，仅 Python 3.8+ 标准库。
"""

from __future__ import annotations

from difflib import SequenceMatcher

# craft 中带 text+span 的维度（D18 用 pattern、span 规则不同，不在此列）
# 与 validate_output.py / fill_spans.py 使用的维度集合保持一致。
CRAFT_TEXT_DIMS = [
    "D13_golden_lines",
    "D14_rhetoric",
    "D15_imagery",
    "D16_diction",
    "D17_syntax",
]


def collapse_whitespace(raw: str) -> tuple[str, list[int]]:
    """把任意连续空白折叠为单个空格（对齐 " ".join(s.split())）。

    返回 (归一文本, 每个归一字符对应的 raw 下标)。开头/结尾空白丢弃。
    """
    norm_chars: list[str] = []
    index_map: list[int] = []
    prev_ws = True  # 开头空白丢弃
    for i, ch in enumerate(raw):
        if ch.isspace():
            if not prev_ws:
                norm_chars.append(" ")
                index_map.append(i)
            prev_ws = True
        else:
            norm_chars.append(ch)
            index_map.append(i)
            prev_ws = False
    if norm_chars and norm_chars[-1] == " ":
        norm_chars.pop()
        index_map.pop()
    return "".join(norm_chars), index_map


def find_span(raw_text: str, quote: str) -> dict | None:
    """定位 quote 在 raw_text 中的段内相对 span；找不到返回 None。

    返回格式与 schema.md §3.2 一致：{"start": int, "end": int}。
    """
    if not raw_text or not quote:
        return None
    quote = quote.strip()
    if not quote:
        return None
    # 1) 精确子串
    idx = raw_text.find(quote)
    if idx >= 0:
        return {"start": idx, "end": idx + len(quote)}
    # 2) 空白归一化子串（validate_output 的引文校验同口径）
    hay, hay_map = collapse_whitespace(raw_text)
    needle = " ".join(quote.split())
    if not needle:
        return None
    n = hay.find(needle)
    if n < 0:
        return None
    s = hay_map[n]
    e = hay_map[n + len(needle) - 1] + 1
    if s < e <= len(raw_text):
        return {"start": s, "end": e}
    return None


def slice_similarity(raw_text: str, span: dict | None, text: str) -> float:
    """现有 span 切片与 text 的相似度（difflib ratio，与 validate 一致）。

    边界非法 / span 缺失返回 0.0。
    """
    try:
        if not span or not raw_text:
            return 0.0
        s, e = int(span["start"]), int(span["end"])
        if not (0 <= s < e <= len(raw_text)):
            return 0.0
        return SequenceMatcher(None, raw_text[s:e], text).ratio()
    except Exception:
        return 0.0


def repair_craft_row(ann: dict) -> tuple[int, list[str]]:
    """对单条 craft 层行（顶层含 craft 键）自动回算 D13–D17 条目的 span。

    规则：条目 text 段内可定位，且「span 缺失 或 切片相似度 < 0.95」→ 用
    find_span 回算重写。已正确（≥0.95）或定位不到的条目不动（后者进
    unmatched 供人工处置）。

    返回 (changed, unmatched)：changed=改写条数；unmatched=段内定位不到的
    条目说明列表。
    """
    craft = ann.get("craft")
    if not isinstance(craft, dict):
        return 0, []
    text_span = ann.get("text_span")
    seg_text = (text_span or {}).get("text", "") if isinstance(text_span, dict) else ""
    if not seg_text:
        return 0, []
    changed = 0
    unmatched: list[str] = []
    for dim in CRAFT_TEXT_DIMS:
        for it in craft.get(dim, []) or []:
            if not isinstance(it, dict):
                continue
            text = (it.get("text") or "").strip()
            if not text:
                continue
            cur = it.get("span")
            if (
                isinstance(cur, dict)
                and slice_similarity(seg_text, cur, text) >= 0.95
            ):
                continue
            new = find_span(seg_text, text)
            if new:
                it["span"] = new
                changed += 1
            elif cur is None:
                unmatched.append(f"{dim}: {text[:36]!r} 在段内定位不到")
    return changed, unmatched
