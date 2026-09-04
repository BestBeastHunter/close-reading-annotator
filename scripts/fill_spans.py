#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/fill_spans.py — 存量批注 span 回补/校正工具 v2.6.0（新增）

用途：
  对 2.5.0 时代已产出的批注（可能缺 span 或 span 漂移）做一次性回填：
    1) craft 文件：对 D13–D17 每个带 text 的条目，在对应 segment 的
       text_span.text 中重新定位，回填 {start, end}（段内相对偏移）。
    2) cross_segment 文件：对每条 cross_ref 的 source/target，按其
       anchor_text 在其 segment 中重新定位，回填 span（此前规则版为 None）。
  锚点定位做两次尝试：原文精确子串 → 空白归一化子串（对齐 validate_output
  的引文校验规则）。找不到的条目不改动、打印报告，供人工处置。

用法：
  python scripts/fill_spans.py --segments {doc_id}_segments.jsonl \
      --file {doc_id}_craft.jsonl
  python scripts/fill_spans.py --segments {doc_id}_segments.jsonl \
      --file {doc_id}_cross_segment.jsonl
  python scripts/fill_spans.py --segments segs.jsonl --file craft.jsonl \
      --output craft_filled.jsonl     # 写到新文件
  python scripts/fill_spans.py --segments segs.jsonl --file craft.jsonl \
      --dry-run                       # 只报告不写盘

零第三方依赖：仅 Python 3.8+ 标准库。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# v2.5.1 修复 #1：Windows GBK 控制台 UnicodeEncodeError（emoji 打印崩溃）
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# v2.7 工程化修复轮（决策 18）：span 定位算法抽为公共模块 scripts/span_locator.py，本脚本复用
sys.path.insert(0, str(Path(__file__).parent))
from span_locator import (  # noqa: E402
    CRAFT_TEXT_DIMS,
    find_span,
    slice_similarity,
)


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
    """segment_id → text_span.text"""
    out: dict[str, str] = {}
    for row in _load_jsonl(segments_path):
        sid = row.get("segment_id")
        ts = row.get("text_span")
        if sid and isinstance(ts, dict) and ts.get("text"):
            out[sid] = ts["text"]
    return out


def _fill_craft_row(row: dict, seg_text: str) -> tuple[int, int, list[str]]:
    """返回 (改动数, 保持数, 无法定位清单[seg_id, dim, text] 文本行说明)。"""
    changed = 0
    kept = 0
    unmatched: list[str] = []
    craft = row.get("craft")
    if not isinstance(craft, dict):
        return 0, 0, unmatched
    for dim in CRAFT_TEXT_DIMS:
        for it in craft.get(dim, []) or []:
            if not isinstance(it, dict):
                continue
            quote = (it.get("text") or "").strip()
            if not quote:
                continue
            cur = it.get("span")
            if cur and slice_similarity(seg_text, cur, quote) >= 0.95:
                kept += 1
                continue
            new = find_span(seg_text, quote) if seg_text else None
            if new:
                it["span"] = new
                changed += 1
            else:
                if cur:
                    kept += 1  # 定位不到但旧 span 近似可用 → 保留，交给人工
                unmatched.append(f"    · {row.get('segment_id')} {dim}: {quote[:36]!r} 在段内找不到")
    return changed, kept, unmatched


def _fill_cross_row(obj: dict, seg_texts: dict[str, str]) -> tuple[int, list[str]]:
    """cross_segment 单行：回填 source/target 的 span。返回 (改动数, 无法定位清单)。"""
    changed = 0
    unmatched: list[str] = []
    for i, ref in enumerate(obj.get("cross_refs", []) or []):
        for end in ("source", "target"):
            node = ref.get(end)
            if not isinstance(node, dict):
                continue
            anchor = (node.get("anchor_text") or "").strip()
            if not anchor:
                continue
            text = seg_texts.get(node.get("segment_id"), "")
            new = find_span(text, anchor) if text else None
            if new:
                if node.get("span") != new:
                    node["span"] = new
                    changed += 1
            else:
                if text:
                    unmatched.append(f"    · refs[{i}].{end} {node.get('segment_id')}: anchor={anchor[:36]!r} 在段内找不到")
    return changed, unmatched


def main() -> int:
    p = argparse.ArgumentParser(
        description="【精读批注 v2.6】存量批注 span 回补/校正（craft D13–D17 / cross_segment source+target）"
    )
    p.add_argument("--segments", required=True, help="segments.jsonl（提供每段 text_span.text）")
    p.add_argument("--file", required=True, help="目标 jsonl：craft 或 cross_segment 产物")
    p.add_argument("--output", default=None, help="输出路径（默认原文件原地覆盖；建议先备份）")
    p.add_argument("--dry-run", action="store_true", help="只报告、不写盘")
    args = p.parse_args()

    seg_path = Path(args.segments)
    file_path = Path(args.file)
    if not seg_path.is_file():
        print(f"❌ segments 不存在：{seg_path}", file=sys.stderr)
        return 2
    if not file_path.is_file():
        print(f"❌ 目标文件不存在：{file_path}", file=sys.stderr)
        return 2

    seg_texts = _load_segment_texts(seg_path)
    rows = _load_jsonl(file_path)
    if not rows:
        print("❌ 目标文件为空", file=sys.stderr)
        return 2

    total_changed = 0
    total_kept = 0
    total_unmatched: list[str] = []

    if "cross_refs" in rows[0]:
        # cross_segment 产物（单行）
        changed, unmatched = _fill_cross_row(rows[0], seg_texts)
        total_changed += changed
        total_unmatched.extend(unmatched)
    elif "craft" in rows[0] or any(k in rows[0] for k in CRAFT_TEXT_DIMS):
        # craft 产物（每行一段）
        for row in rows:
            seg_text = seg_texts.get(row.get("segment_id"), "")
            changed, kept, unmatched = _fill_craft_row(row, seg_text)
            total_changed += changed
            total_kept += kept
            total_unmatched.extend(unmatched)
    else:
        print("❌ 无法识别文件类型（既非 craft 也非 cross_segment 结构）", file=sys.stderr)
        return 2

    # 报告
    print(f"[fill_spans] 已定位回填 {total_changed} 处；保持既有 {total_kept} 处")
    if total_unmatched:
        print(f"[fill_spans] ⚠️ {len(total_unmatched)} 处无法在段内定位（未改动，需人工核对）：")
        for line in total_unmatched[:40]:
            print(line)
        if len(total_unmatched) > 40:
            print(f"    … 其余 {len(total_unmatched) - 40} 处省略")
    else:
        print("[fill_spans] ✅ 全部可定位，无遗漏")

    if args.dry_run:
        print("[fill_spans] --dry-run：未写盘")
        return 0

    out_path = Path(args.output) if args.output else file_path
    with out_path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"[fill_spans] 📄 已写入 → {out_path.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
