#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/reshape_segments.py — 精细化切分重排（v3.5.0 / T-034 / ADR-014）

基于 LumberChunker 思想的 Skill 化实现：Phase 1 粗切分 → Phase 2 场景边界判断（Agent 用自身 LLM）
→ Phase 3 后处理切分重排（本脚本）→ Phase 4 精细批注（annotate_segment.py 不变）。

本脚本职责：
  1. 读取 preprocess.py 产出的粗切 segments_rough.jsonl（含 start_char/end_char 字符偏移）
  2. 读取 scene_boundary.json（Agent 判断的相邻段场景边界，可选）
  3. 读取原始文本文件，按合并后的字符区间重新截取文本
  4. 重新编号为 scene_001, scene_002, ...
  5. 建立新旧 segment ID 映射（哪些旧 segment 合并成了哪个新 segment）
  6. 自校验：original[start:end] == text（坐标漂移检测）

场景边界判定规则（优先级从高到低）：
  1. 章节边界（chapter / section_type 变化）→ 自动场景边界（无需 LLM 判断）
  2. scene_boundary.json 中显式 is_scene_boundary=true → 场景边界
  3. 其余相邻段 → 合并到同一场景（默认连续）

输入：
  --segments   粗切 segments.jsonl（preprocess.py 产出）
  --boundaries scene_boundary.json（Agent 场景边界判断，可选；缺失时仅按章节边界切分）
  --original   原始文本文件（用于按字符区间重切；若 segments 中 text 已完整可省略）
  --doc-id     文档 ID
  --output-dir 输出目录

输出：
  {doc_id}_final_segments.jsonl   重排后的场景级 segments
  {doc_id}_segment_id_mapping.json 新旧 ID 映射表

用法：
  python scripts/reshape_segments.py \
    --segments out/moon_segments.jsonl \
    --boundaries out/moon_scene_boundary.json \
    --original book.txt \
    --doc-id moon_sixpence_zh \
    --output-dir out/
"""

from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

SCHEMA_VERSION = "3.5.0"


def load_segments(path: Path) -> list[dict]:
    """加载粗切 segments，按 start_char 排序。"""
    segs: list[dict] = []
    with io.open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                seg = json.loads(line)
            except json.JSONDecodeError:
                continue
            segs.append(seg)
    segs.sort(key=lambda s: s.get("text_span", {}).get("start_char", 0))
    return segs


def load_boundaries(path: Path | None) -> dict[tuple[str, str], dict]:
    """加载场景边界判断，返回 {(seg_id_a, seg_id_b): boundary_info}。"""
    if not path or not path.exists():
        return {}
    data = json.loads(io.open(path, encoding="utf-8").read())
    result: dict[tuple[str, str], dict] = {}
    for b in data.get("boundaries", []):
        key = (b["between_segment"], b["and_segment"])
        result[key] = b
    return result


def is_chapter_boundary(seg_a: dict, seg_b: dict) -> bool:
    """判断两个相邻 segment 之间是否是章节边界（自动场景边界）。"""
    chap_a = seg_a.get("chapter") or seg_a.get("section_type") or ""
    chap_b = seg_b.get("chapter") or seg_b.get("section_type") or ""
    return chap_a != chap_b


def group_segments_by_scene(
    segments: list[dict],
    boundaries: dict[tuple[str, str], dict],
) -> list[list[dict]]:
    """
    将 segments 按场景分组。
    返回 [[seg1, seg2], [seg3], ...]，每个子列表是同一场景的连续 segments。
    """
    if not segments:
        return []

    groups: list[list[dict]] = [[segments[0]]]

    for i in range(1, len(segments)):
        prev = segments[i - 1]
        curr = segments[i]
        prev_id = prev.get("segment_id", "")
        curr_id = curr.get("segment_id", "")

        # 判定是否场景边界
        is_boundary = False
        boundary_reason = ""

        # 规则1：章节边界
        if is_chapter_boundary(prev, curr):
            is_boundary = True
            boundary_reason = "chapter_boundary"

        # 规则2：scene_boundary.json 显式标记
        b = boundaries.get((prev_id, curr_id))
        if b and b.get("is_scene_boundary"):
            is_boundary = True
            boundary_reason = b.get("boundary_type", "llm_judged")

        if is_boundary:
            groups.append([curr])
        else:
            groups[-1].append(curr)

    return groups


def reshape_group(
    group: list[dict],
    scene_index: int,
    doc_id: str,
    original_text: str | None,
) -> tuple[dict, list[str]]:
    """
    将一组同场景 segments 合并为一个场景级 segment。
    返回 (new_segment, old_segment_ids)。
    """
    start_char = group[0]["text_span"]["start_char"]
    end_char = group[-1]["text_span"]["end_char"]
    old_ids = [s["segment_id"] for s in group]

    # 从原文重切（优先），否则用 segments 中的 text 拼接
    if original_text is not None:
        text = original_text[start_char:end_char]
        # 自校验：与拼接文本的相似度（允许首尾空白差）
        concat = "".join(s["text_span"]["text"] for s in group)
        if text.strip() != concat.strip():
            # 坐标可能有微小偏差，用原文为准但记录警告
            print(f"  [WARN] scene_{scene_index:03d} 原文切片与拼接文本存在差异（start={start_char} end={end_char}），以原文为准")
    else:
        text = "".join(s["text_span"]["text"] for s in group)

    # 章节信息取第一个 segment 的
    chapter = group[0].get("chapter", "")
    section_type = group[0].get("section_type", "")

    new_seg = {
        "schema_version": SCHEMA_VERSION,
        "document_id": doc_id,
        "segment_index": scene_index,
        "segment_id": f"{doc_id}_scene_{scene_index:03d}",
        "chapter": chapter,
        "chapter_index": group[0].get("chapter_index", 0),
        "section_type": section_type,
        "scene_level": True,
        "merged_from_count": len(group),
        "text_span": {
            "start_char": start_char,
            "end_char": end_char,
            "text": text,
        },
    }
    return new_seg, old_ids


def main() -> int:
    ap = argparse.ArgumentParser(description="精细化切分重排——按场景边界合并粗切 segments（纯 stdlib）")
    ap.add_argument("--segments", type=Path, required=True, help="粗切 segments.jsonl（preprocess.py 产出）")
    ap.add_argument("--boundaries", type=Path, default=None, help="scene_boundary.json（Agent 场景边界判断，可选）")
    ap.add_argument("--original", type=Path, default=None, help="原始文本文件（用于按字符区间重切；省略时用 segments 中 text 拼接）")
    ap.add_argument("--doc-id", type=str, required=True, help="文档 ID")
    ap.add_argument("--output-dir", type=Path, required=True, help="输出目录")
    args = ap.parse_args()

    if not args.segments.exists():
        print(f"[ERROR] segments 文件不存在: {args.segments}", file=sys.stderr)
        return 2

    # 加载
    segments = load_segments(args.segments)
    boundaries = load_boundaries(args.boundaries)
    original_text = None
    if args.original and args.original.exists():
        original_text = io.open(args.original, encoding="utf-8", errors="replace").read()

    print(f"[INFO] 加载粗切 segments: {len(segments)} 段")
    print(f"[INFO] 场景边界判断: {len(boundaries)} 条" + (f"（{args.boundaries}）" if args.boundaries else "（未提供，仅按章节边界）"))
    print(f"[INFO] 原始文本: {'已加载（按字符区间重切）' if original_text else '未提供（用 segments text 拼接）'}")

    # 按场景分组
    groups = group_segments_by_scene(segments, boundaries)
    print(f"[INFO] 场景分组: {len(groups)} 个场景（由 {len(segments)} 段粗切合并）")

    # 重排
    args.output_dir.mkdir(parents=True, exist_ok=True)
    final_segments_path = args.output_dir / f"{args.doc_id}_final_segments.jsonl"
    mapping_path = args.output_dir / f"{args.doc_id}_segment_id_mapping.json"

    mapping: list[dict] = []
    with io.open(final_segments_path, "w", encoding="utf-8", newline="") as fout:
        for idx, group in enumerate(groups):
            new_seg, old_ids = reshape_group(group, idx, args.doc_id, original_text)
            fout.write(json.dumps(new_seg, ensure_ascii=False) + "\n")
            mapping.append({
                "new_segment_id": new_seg["segment_id"],
                "old_segment_ids": old_ids,
                "start_char": new_seg["text_span"]["start_char"],
                "end_char": new_seg["text_span"]["end_char"],
                "merged_count": len(old_ids),
            })

    io.open(mapping_path, "w", encoding="utf-8", newline="").write(
        json.dumps({
            "schema_version": SCHEMA_VERSION,
            "document_id": args.doc_id,
            "total_scenes": len(groups),
            "total_original_segments": len(segments),
            "mapping": mapping,
        }, ensure_ascii=False, indent=2) + "\n"
    )

    # 统计
    scene_sizes = [len(g) for g in groups]
    avg_size = sum(scene_sizes) / max(len(scene_sizes), 1)
    print(f"\n[OK] 重排完成")
    print(f"  输出: {final_segments_path}（{len(groups)} 个场景级 segment）")
    print(f"  映射: {mapping_path}")
    print(f"  统计: 每场景平均合并 {avg_size:.1f} 段 | 最大 {max(scene_sizes)} 段 | 最小 {min(scene_sizes)} 段")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
