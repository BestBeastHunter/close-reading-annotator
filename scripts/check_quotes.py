#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/check_quotes.py — 引文子串预检工具（v3.15.0 新增，T-130）

用途：
  在注入批注前（或注入失败重试前），全量预检所有"引文类"字段是否都是
  对应 segment 原文的子串。覆盖：
    - emotion 层：D19.key_phrases[]（短语）
    - craft 层：D13–D17 条目的 text（金句/修辞/意象/词汇/句式）
    - interpretation 层：D06.content（信息控制，引号内引文为强约束）
  命中规则与 validate_output 口径一致：精确子串 → 空白归一子串（warning 级）。
  失败直接打印"段 + 字段 + 缺失短语"，让 Agent 在注入前就修正，而不是
  注入后被校验器逐条拒绝再翻源码。

用法：
  python scripts/check_quotes.py <emotion|craft|interpretation|merged>.jsonl \
      --segments {doc_id}_segments.jsonl [--layer-type emotion] [--fuzzy] [--fail-fast]

  # 示例：预检 emotion 与 craft 两个文件
  python scripts/check_quotes.py {doc}_emotion.jsonl --segments {doc}_segments.jsonl --layer-type emotion
  python scripts/check_quotes.py {doc}_craft.jsonl --segments {doc}_segments.jsonl --layer-type craft

零第三方依赖：仅 Python 3.8+ 标准库。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def _load_jsonl(path: Path) -> list[dict]:
    out: list[dict] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError as e:
                    print(f"⚠️ {path} 第 {len(out) + 1} 行 JSON 解析失败：{e}", file=sys.stderr)
    return out


def _load_segment_texts(segments_path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for row in _load_jsonl(segments_path):
        sid = row.get("segment_id")
        ts = row.get("text_span")
        if sid and isinstance(ts, dict) and ts.get("text"):
            out[sid] = ts["text"]
    return out


def _normalize_ws(s: str) -> str:
    return re.sub(r"\s+", "", s)


def _check_quote(seg_text: str, quote: str) -> tuple[bool, bool]:
    """返回 (精确命中, 空白归一命中)。"""
    if not quote:
        return True, True
    if quote in seg_text:
        return True, True
    norm_q = _normalize_ws(quote)
    if norm_q and norm_q in _normalize_ws(seg_text):
        return False, True
    return False, False


def _iter_quotes(row: dict, layer_type: str) -> list[tuple[str, str]]:
    """从一行批注中提取 (字段说明, 引文) 列表。"""
    out: list[tuple[str, str]] = []
    layers = row.get("layers") or {}

    if layer_type == "emotion":
        # v2.8.0+ 直接格式：layers.emotion.*（expression.key_phrases[]）
        emo = layers.get("emotion") if layers.get("emotion") else row.get("emotion")
        if isinstance(emo, dict):
            expr = emo.get("expression")
            if isinstance(expr, dict):
                for i, kp in enumerate(expr.get("key_phrases") or []):
                    if isinstance(kp, str):
                        out.append((f"expression.key_phrases[{i}]", kp))
            # v2.7.0 嵌套格式兼容：layers.emotion.D19_emotion_analysis.expression.key_phrases
            d19 = emo.get("D19_emotion_analysis")
            if isinstance(d19, dict):
                expr2 = d19.get("expression")
                if isinstance(expr2, dict):
                    for i, kp in enumerate(expr2.get("key_phrases") or []):
                        if isinstance(kp, str):
                            out.append((f"D19.expression.key_phrases[{i}]", kp))

    elif layer_type == "craft":
        craft = layers.get("craft") if layers.get("craft") else row.get("craft")
        if isinstance(craft, dict):
            for dim in ("D13_golden_lines", "D14_rhetoric", "D15_imagery", "D16_diction", "D17_syntax"):
                for i, it in enumerate(craft.get(dim) or []):
                    if isinstance(it, dict) and it.get("text"):
                        out.append((f"{dim}[{i}].text", str(it["text"])))

    elif layer_type == "interpretation":
        interp = layers.get("interpretation") if layers.get("interpretation") else row.get("interpretation")
        if isinstance(interp, dict):
            d06 = interp.get("D06")
            if isinstance(d06, dict) and d06.get("content"):
                out.append(("D06.content", str(d06["content"])))

    elif layer_type == "merged":
        # merged 行：从各层分别提取
        for sub, lt in (("emotion", "emotion"), ("craft", "craft"), ("interpretation", "interpretation")):
            sub_row = {"layers": {sub: row.get(sub)}}
            out.extend(_iter_quotes(sub_row, lt))

    return out


def main() -> int:
    p = argparse.ArgumentParser(description="引文子串预检工具 v3.15.0（T-130）")
    p.add_argument("input_file", type=str, help="批注 JSONL（emotion/craft/interpretation/merged）")
    p.add_argument("--segments", required=True, type=str, help="segments.jsonl 路径")
    p.add_argument("--layer-type", default=None, type=str,
                   help="层类型（emotion/craft/interpretation/merged）；不传则按文件内容自动探测")
    p.add_argument("--fuzzy", action="store_true", help="空白归一命中也列出（warning 级）")
    p.add_argument("--fail-fast", action="store_true", help="首个失败即停止")
    args = p.parse_args()

    inp = Path(args.input_file)
    if not inp.is_file():
        print(f"❌ 批注文件不存在：{inp}", file=sys.stderr)
        return 2
    segs_path = Path(args.segments)
    if not segs_path.is_file():
        print(f"❌ segments 文件不存在：{segs_path}", file=sys.stderr)
        return 2

    rows = _load_jsonl(inp)
    seg_texts = _load_segment_texts(segs_path)
    if not rows:
        print("⚠️ 批注文件为空，无需预检")
        return 0
    if not seg_texts:
        print("❌ segments 无有效文本（检查 segment_id/text_span.text）", file=sys.stderr)
        return 2

    # 自动探测层类型
    layer_type = args.layer_type
    if layer_type is None:
        sample = rows[0]
        layers = sample.get("layers") or {}
        if layers.get("emotion") or sample.get("emotion"):
            layer_type = "emotion"
        elif layers.get("craft") or sample.get("craft"):
            layer_type = "craft"
        elif layers.get("interpretation") or sample.get("interpretation"):
            layer_type = "interpretation"
        else:
            print("❌ 无法自动探测层类型，请显式 --layer-type", file=sys.stderr)
            return 2

    total = 0
    passed = 0
    fuzzy_hits: list[tuple[str, str, str]] = []
    failures: list[tuple[str, str, str]] = []

    for row in rows:
        sid = row.get("segment_id")
        if not sid or sid not in seg_texts:
            continue
        seg_text = seg_texts[sid]
        for field, quote in _iter_quotes(row, layer_type):
            total += 1
            exact, norm = _check_quote(seg_text, quote)
            if exact:
                passed += 1
            elif norm:
                fuzzy_hits.append((sid, field, quote))
            else:
                failures.append((sid, field, quote))
                if args.fail_fast:
                    break
        if args.fail_fast and failures:
            break

    print("=" * 66)
    print(f"引文预检（{layer_type}）：{passed + len(fuzzy_hits) + len(failures)} 条引文 / "
          f"{len(seg_texts)} 段")
    print("=" * 66)
    print(f"✅ 精确命中: {passed}")
    if fuzzy_hits:
        print(f"⚠️ 空白归一命中: {len(fuzzy_hits)}（注入时校验器按相似度≥95% 可能通过，建议核对）")
        if args.fuzzy:
            for sid, field, q in fuzzy_hits[:20]:
                print(f"   · {sid} {field}: {q[:60]!r}")
    if failures:
        print(f"❌ 非子串失败: {len(failures)}（注入前必须修正，否则被校验器拒绝）")
        for sid, field, q in failures[:30]:
            print(f"   ✖ {sid} {field}: {q[:80]!r}")
        if len(failures) > 30:
            print(f"   ... 其余 {len(failures) - 30} 条略")
        return 1
    print("🎉 全部引文均为原文子串，可安全注入")
    return 0


if __name__ == "__main__":
    sys.exit(main())
