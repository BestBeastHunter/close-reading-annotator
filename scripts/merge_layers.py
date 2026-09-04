#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/merge_layers.py — 四层 + D19 情感（可选）合并为嵌套文档 v2.7.0

把同一段的 segments + structure + interpretation + craft + cross_segment 按 segment 为轴心合并；
D19 emotion 文件存在时并入顶层 emotion 字段（v2.7.0，缺失则跳过）。
cross_segment 的 ref 被投影到每段的 cross_refs_sources / cross_refs_targets 上。

修复早期审计指出的 bug：「merge_layers 读 text_span，但 preprocess 输出平铺字段」——
本实现兼容两种形态：优先读 obj["text_span"]，不存在则用 seg["text_span"] 兜底。

用法：
  python scripts/merge_layers.py \
    --doc-id moon_sixpence \
    --segments moon_sixpence_segments.jsonl
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

# checkpoint
sys.path.insert(0, str(Path(__file__).parent))
from checkpoint import load_checkpoint, save_checkpoint  # noqa: E402


def _load_jsonl(path: Path) -> list[dict]:
    out: list[dict] = []
    if not path.is_file():
        return out
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if s:
                try:
                    out.append(json.loads(s))
                except json.JSONDecodeError as e:
                    print(f"⚠️ {path} 行解析失败：{e}", file=sys.stderr)
    return out


def _index_by_segment_id(rows: list[dict]) -> dict[str, dict]:
    return {r["segment_id"]: r for r in rows if r.get("segment_id")}


def _load_cross_refs(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if s:
                try:
                    obj = json.loads(s)
                    return obj.get("cross_refs", [])
                except json.JSONDecodeError:
                    return []
    return []


def main() -> int:
    p = argparse.ArgumentParser(description="【精读批注 v2.7 Phase 4】四层(+D19 情感可选)嵌套合并 + checkpoint 标记")
    p.add_argument("--doc-id", required=True)
    p.add_argument("--segments", required=True, help="segments.jsonl")
    p.add_argument("--output", default=None, help="输出 merged.jsonl 路径（默认 <doc_id>_merged.jsonl）")
    args = p.parse_args()

    doc_id = args.doc_id
    seg_path = Path(args.segments)
    base_dir = seg_path.parent

    segs = _load_jsonl(seg_path)
    struct = _index_by_segment_id(_load_jsonl(base_dir / f"{doc_id}_structure.jsonl"))
    interp = _index_by_segment_id(_load_jsonl(base_dir / f"{doc_id}_interpretation.jsonl"))
    craft = _index_by_segment_id(_load_jsonl(base_dir / f"{doc_id}_craft.jsonl"))
    # emotion（v2.7.0 D19，P4 可选产物；文件不存在视为未跑，跳过）
    emo_path = base_dir / f"{doc_id}_emotion.jsonl"
    emotion = _index_by_segment_id(_load_jsonl(emo_path)) if emo_path.exists() else {}
    refs = _load_cross_refs(base_dir / f"{doc_id}_cross_segment.jsonl")

    # 投影 cross_refs 到每个段
    src_map: dict[str, list[str]] = {}
    tgt_map: dict[str, list[str]] = {}
    for r in refs:
        s = r.get("source", {}).get("segment_id")
        t = r.get("target", {}).get("segment_id")
        if s:
            src_map.setdefault(s, []).append(r.get("ref_id", ""))
        if t:
            tgt_map.setdefault(t, []).append(r.get("ref_id", ""))

    merged_rows: list[dict] = []
    for seg in segs:
        sid = seg.get("segment_id")
        if not sid:
            continue
        text_span = seg.get("text_span")
        s_row = struct.get(sid)
        i_row = interp.get(sid)
        c_row = craft.get(sid)
        e_row = emotion.get(sid)
        merged_rows.append({
            "segment_id": sid,
            "chapter": seg.get("chapter"),
            "chapter_index": seg.get("chapter_index"),
            "section_type": seg.get("section_type"),
            "text_span": text_span,
            "approx_tokens": seg.get("approx_tokens"),
            "structure": s_row["layers"]["structure"] if s_row and s_row.get("layers", {}).get("structure") else None,
            "interpretation": i_row["layers"]["interpretation"] if i_row and i_row.get("layers", {}).get("interpretation") else None,
            "emotion": e_row["layers"]["emotion"] if e_row and e_row.get("layers", {}).get("emotion") else None,
            "craft": c_row.get("craft") if c_row and c_row.get("craft") else None,
            "cross_refs_sources": src_map.get(sid, []),
            "cross_refs_targets": tgt_map.get(sid, []),
        })

    out_path = Path(args.output) if args.output else (base_dir / f"{doc_id}_merged.jsonl")
    with out_path.open("w", encoding="utf-8") as f:
        for r in merged_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # checkpoint 标记（v2.5.1：用 base_dir 定位 checkpoint）
    ckpt = load_checkpoint(doc_id, base_dir)
    if ckpt is not None:
        ckpt["merged_completed"] = True
        save_checkpoint(ckpt, base_dir)

    print(f"[merge_layers] ✅ 完成：{len(merged_rows)} 段 → {out_path.resolve()}")
    print(f"   - segments：{len(segs)}")
    print(f"   - structure 命中：{len(struct)}")
    print(f"   - interpretation 命中：{len(interp)}")
    print(f"   - emotion 命中（v2.7.0 D19）：{len(emotion)}")
    print(f"   - craft 命中：{len(craft)}")
    print(f"   - cross_refs：{len(refs)} 条")
    return 0


if __name__ == "__main__":
    sys.exit(main())
