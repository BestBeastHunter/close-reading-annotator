#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/span_locator.py — span 定位公共模块（v2.7 工程化修复轮，决策 18；v3.8.1 模糊匹配增强，ADR-016）

定位算法与 validate_output.py 的引文校验口径对齐（决策 3 / SKILL.md §五 引文校验）：
  1) 原文精确子串 → 命中返回 {start, end}；
  2) 空白归一化子串（" ".join(s.split())）→ 通过 index_map 回算 raw 下标；
  3) 去标点归一化子串（v3.8.1 新增）→ 去掉所有标点符号后匹配，回算 raw 下标；
  4) 模糊相似度匹配（v3.8.1 新增）→ SequenceMatcher 相似度 >= 0.85 时自动定位
     最相似子串并修正引文文本，返回修正后的 text + span + warning。

被以下脚本复用：
  - annotate_segment.py：校验失败时对 span 缺失/漂移的 craft 条目自动回算修正（兑现「自动重试 <=3 次」）；
  - fill_spans.py：存量产物（craft / cross_segment）的 span 一次性回补。

零第三方依赖，仅 Python 3.8+ 标准库。
"""

from __future__ import annotations

import re
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

# 模糊匹配相似度阈值（v3.8.1，ADR-016）
# 0.85 = 允许约 15% 的字符差异（如多一个标点、少一个字、同义词替换）
FUZZY_SIMILARITY_THRESHOLD = 0.85

# 标点符号正则（中英文标点全覆盖，v3.8.1）
_PUNCT_CHARS = (
    r"，。！？；：、"
    r"\u201c\u201d\u2018\u2019"  # ""''
    r"\u300c\u300d\u300e\u300f"  # 「」『』
    r"（）《》【】—…·"
    r",\.!?;:\-\"'()\[\]{}<>\\/`~@#\$%\^&\*\+=\|"
)
PUNCTUATION_RE = re.compile(r"[" + _PUNCT_CHARS + r"]")


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


def remove_punctuation(raw: str) -> tuple[str, list[int]]:
    """去掉所有标点符号，保留空白和文字。

    返回 (去标点文本, 每个去标点字符对应的 raw 下标)。
    用于 v3.8.1 第 3 级匹配：LLM 写的引文可能多/少了标点符号。
    """
    norm_chars: list[str] = []
    index_map: list[int] = []
    for i, ch in enumerate(raw):
        if PUNCTUATION_RE.match(ch):
            continue
        norm_chars.append(ch)
        index_map.append(i)
    return "".join(norm_chars), index_map


def find_span(raw_text: str, quote: str) -> dict | None:
    """定位 quote 在 raw_text 中的段内相对 span；找不到返回 None。

    返回格式与 schema.md §3.2 一致：{"start": int, "end": int}。

    匹配策略（v3.8.1 前 2 级）：
      1) 原文精确子串
      2) 空白归一化子串
    注意：本函数不做模糊匹配（保持向后兼容）。需要模糊匹配请用 fuzzy_find_span。
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


def fuzzy_find_span(raw_text: str, quote: str) -> dict | None:
    """模糊定位 quote 在 raw_text 中的段内相对 span（v3.8.1 新增，ADR-016）。

    4 级匹配策略，逐级降级：
      1) 原文精确子串 -> match_level="exact"
      2) 空白归一化子串 -> match_level="whitespace_normalized"
      3) 去标点归一化子串 -> match_level="punctuation_removed"
      4) 模糊相似度匹配（SequenceMatcher >= 0.85）-> match_level="fuzzy_similarity"
         自动定位最相似子串，修正引文文本为原文中实际匹配的子串。

    返回格式：
    {
        "span": {"start": int, "end": int},
        "text": str,           # 修正后的引文文本（模糊匹配时返回原文实际子串）
        "match_level": str,    # "exact" / "whitespace_normalized" / "punctuation_removed" / "fuzzy_similarity"
        "similarity": float,   # 相似度（模糊匹配时有值，其他级别为 1.0）
        "warning": str | None  # 警告信息（模糊匹配时记录修正前后文本，供审计）
    }

    找不到返回 None。
    """
    if not raw_text or not quote:
        return None
    quote = quote.strip()
    if not quote:
        return None

    # 1) 精确子串
    idx = raw_text.find(quote)
    if idx >= 0:
        return {
            "span": {"start": idx, "end": idx + len(quote)},
            "text": quote,
            "match_level": "exact",
            "similarity": 1.0,
            "warning": None,
        }

    # 2) 空白归一化子串
    hay, hay_map = collapse_whitespace(raw_text)
    needle = " ".join(quote.split())
    if needle:
        n = hay.find(needle)
        if n >= 0:
            s = hay_map[n]
            e = hay_map[n + len(needle) - 1] + 1
            if s < e <= len(raw_text):
                actual_text = raw_text[s:e]
                return {
                    "span": {"start": s, "end": e},
                    "text": actual_text,
                    "match_level": "whitespace_normalized",
                    "similarity": 1.0,
                    "warning": None if actual_text == quote else f"空白归一化匹配：原文={actual_text!r}，输入={quote!r}",
                }

    # 3) 去标点归一化子串（v3.8.1 新增）
    hay_nopunct, hay_map_nopunct = remove_punctuation(raw_text)
    needle_nopunct = PUNCTUATION_RE.sub("", needle)
    if needle_nopunct:
        n = hay_nopunct.find(needle_nopunct)
        if n >= 0:
            s = hay_map_nopunct[n]
            e = hay_map_nopunct[n + len(needle_nopunct) - 1] + 1
            if s < e <= len(raw_text):
                actual_text = raw_text[s:e]
                return {
                    "span": {"start": s, "end": e},
                    "text": actual_text,
                    "match_level": "punctuation_removed",
                    "similarity": 1.0,
                    "warning": f"去标点匹配：原文={actual_text!r}，输入={quote!r}",
                }

    # 4) 模糊相似度匹配（v3.8.1 新增）
    # 滑动窗口：在原文中找与 quote 最相似的子串
    best_ratio = 0.0
    best_start = -1
    best_end = -1
    quote_len = len(quote)
    # 窗口大小：quote_len 的 0.7~1.5 倍，避免过长/过短
    min_window = max(1, int(quote_len * 0.7))
    max_window = min(len(raw_text), int(quote_len * 1.5) + 1)
    # 步长：窗口越大步长越大，保证性能（O(n) 而非 O(n^2)）
    for window_len in range(min_window, max_window + 1):
        step = max(1, window_len // 4)
        for start in range(0, len(raw_text) - window_len + 1, step):
            end = start + window_len
            candidate = raw_text[start:end]
            ratio = SequenceMatcher(None, candidate, quote).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_start = start
                best_end = end
                # 提前终止：找到完全匹配
                if best_ratio >= 0.99:
                    break
        if best_ratio >= 0.99:
            break

    if best_ratio >= FUZZY_SIMILARITY_THRESHOLD and best_start >= 0:
        actual_text = raw_text[best_start:best_end]
        return {
            "span": {"start": best_start, "end": best_end},
            "text": actual_text,
            "match_level": "fuzzy_similarity",
            "similarity": round(best_ratio, 4),
            "warning": f"模糊匹配（相似度={best_ratio:.2f}）：原文={actual_text!r}，输入={quote!r}",
        }

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


def repair_craft_row(ann: dict) -> tuple[int, list[str], list[str]]:
    """对单条 craft 层行（顶层含 craft 键）自动回算 D13-D17 条目的 span。

    v3.8.1 升级（ADR-016）：使用 fuzzy_find_span 替代 find_span，支持 4 级匹配
    （精确->空白归一->去标点->模糊相似度）。模糊匹配时自动修正引文文本为原文
    中实际匹配的子串，并记录 warning。

    规则：条目 text 段内可定位，且「span 缺失 或 切片相似度 < 0.95」-> 用
    fuzzy_find_span 回算重写。已正确（>=0.95）或定位不到的条目不动（后者进
    unmatched 供人工处置）。

    返回 (changed, unmatched, warnings)：
      changed=改写条数；
      unmatched=段内定位不到的条目说明列表；
      warnings=模糊匹配修正的警告信息列表（供审计）。

    v3.8.1 bugfix：同时支持顶层 craft 和 layers.craft 两种格式
    （--input-json 注入的对象是 layers.craft 格式，此前只找顶层 craft 导致 auto-fix 失效）。
    """
    craft = ann.get("craft")
    if not isinstance(craft, dict):
        # 支持 layers.craft 格式（--input-json 注入的对象）
        layers = ann.get("layers")
        if isinstance(layers, dict):
            craft = layers.get("craft")
    if not isinstance(craft, dict):
        return 0, [], []
    text_span = ann.get("text_span")
    seg_text = (text_span or {}).get("text", "") if isinstance(text_span, dict) else ""
    if not seg_text:
        return 0, [], []
    changed = 0
    unmatched: list[str] = []
    warnings: list[str] = []
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
            # v3.8.1：使用 fuzzy_find_span 替代 find_span
            result = fuzzy_find_span(seg_text, text)
            if result:
                it["span"] = result["span"]
                # 模糊匹配时自动修正引文文本
                if result["text"] != text:
                    it["text"] = result["text"]
                if result["warning"]:
                    warnings.append(f"{dim}: {result['warning']}")
                changed += 1
            elif cur is None:
                unmatched.append(f"{dim}: {text[:36]!r} 在段内定位不到")
    return changed, unmatched, warnings
