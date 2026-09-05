#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/merge_segments.py — 场景边界后处理重排工具（v3.8.4 新增，T-051）

基于 LLM 输出的 scene_boundary.json，对粗切 segments.jsonl 做合并/拆分，
重新编号为最终场景段，建立新旧 ID 映射表。

LumberChunker 思想的 Skill 化实现：
  Phase 1: preprocess.py 粗切分（按章节+长度）
  Phase 2: Agent 用 LLM 判断场景边界（输出 scene_boundary.json）
  Phase 3: 本脚本执行实际切分/重排（纯脚本，不依赖 LLM）
  Phase 4: annotate_segment.py 对最终场景段做精细批注

用法：
  python scripts/merge_segments.py \
      --segments <粗切 segments.jsonl> \
      --boundary <scene_boundary.json> \
      --doc-id <doc_id> \
      --output <最终 segments.jsonl 路径>

scene_boundary.json 格式（由 Agent LLM 输出）：
  {
    "boundaries": [
      {"segment_id": "xxx_seg_0002", "is_scene_start": true, "reason": "时间跳跃到次日"},
      {"segment_id": "xxx_seg_0005", "is_scene_start": false, "reason": "同一场景延续"}
    ]
  }

零第三方依赖：仅 Python 3.8+ 标准库。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def load_jsonl(path: Path) -> list:
    rows = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError as e:
                    print("⚠️ %s 行解析失败: %s" % (path, e), file=sys.stderr)
    return rows


def main() -> int:
    p = argparse.ArgumentParser(description="v3.8.4 场景边界后处理重排工具（T-051，LumberChunker 思想 Skill 化）")
    p.add_argument("--segments", required=True, help="粗切 segments.jsonl")
    p.add_argument("--boundary", required=True, help="LLM 输出的 scene_boundary.json")
    p.add_argument("--doc-id", required=True, help="文档 ID")
    p.add_argument("--output", default=None, help="输出最终 segments.jsonl 路径")
    p.add_argument("--mapping-output", default=None, help="新旧 ID 映射表输出路径（默认 <output>.mapping.json）")
    args = p.parse_args()

    segments = load_jsonl(Path(args.segments))
    if not segments:
        print("❌ 粗切 segments 为空", file=sys.stderr)
        return 2

    with open(args.boundary, "r", encoding="utf-8") as f:
        boundary_data = json.load(f)
    boundaries = {b["segment_id"]: b for b in boundary_data.get("boundaries", [])}

    print("📂 输入: %d 个粗切段, %d 条边界标记" % (len(segments), len(boundaries)))

    # 根据 is_scene_start 标记分组
    scenes = []  # 每个场景是一组 segment
    current_scene = []
    for seg in segments:
        sid = seg.get("segment_id")
        b = boundaries.get(sid, {})
        if b.get("is_scene_start", False) and current_scene:
            scenes.append(current_scene)
            current_scene = [seg]
        else:
            current_scene.append(seg)
    if current_scene:
        scenes.append(current_scene)

    print("📊 场景划分: %d 个场景（原 %d 段）" % (len(scenes), len(segments)))

    # 生成最终场景段（合并同场景的文本，重新编号）
    final_segments = []
    mapping = []  # 新旧 ID 映射
    for scene_idx, scene_segs in enumerate(scenes):
        # 合并文本
        merged_text = ""
        merged_start = None
        merged_end = None
        chapter = None
        section_type = "body"
        for seg in scene_segs:
            ts = seg.get("text_span", {})
            if merged_start is None:
                merged_start = ts.get("start_char", 0)
            merged_end = ts.get("end_char", merged_start)
            if chapter is None:
                chapter = seg.get("chapter")
            if seg.get("section_type") == "frontmatter":
                section_type = "frontmatter"
            text = ts.get("text", "")
            if text:
                if merged_text and not merged_text.endswith("\n"):
                    merged_text += "\n"
                merged_text += text

        new_id = "%s_scene_%04d" % (args.doc_id, scene_idx + 1)
        final_seg = {
            "segment_id": new_id,
            "chapter": chapter,
            "section_type": section_type,
            "text_span": {
                "text": merged_text,
                "start_char": merged_start or 0,
                "end_char": merged_end or len(merged_text),
            },
            "approx_tokens": len(merged_text),  # 粗略估计
            "_scene_boundary_reason": boundaries.get(scene_segs[0].get("segment_id", ""), {}).get("reason", ""),
            "_source_segments": [s.get("segment_id") for s in scene_segs],
        }
        final_segments.append(final_seg)

        # 记录映射
        for src_seg in scene_segs:
            mapping.append({
                "old_segment_id": src_seg.get("segment_id"),
                "new_segment_id": new_id,
            })

    # 写输出
    output_path = Path(args.output) if args.output else Path("%s_final_segments.jsonl" % args.doc_id)
    with output_path.open("w", encoding="utf-8") as f:
        for seg in final_segments:
            f.write(json.dumps(seg, ensure_ascii=False) + "\n")

    # 写映射表
    mapping_path = Path(args.mapping_output) if args.mapping_output else Path(str(output_path) + ".mapping.json")
    with mapping_path.open("w", encoding="utf-8") as f:
        json.dump({"doc_id": args.doc_id, "mapping": mapping, "scene_count": len(scenes)}, f, ensure_ascii=False, indent=2)

    print("")
    print("✅ 重排完成: %d 个最终场景段 → %s" % (len(final_segments), output_path.resolve()))
    print("   映射表: %s" % mapping_path.resolve())
    print("")
    print("下一步: 用最终 segments.jsonl 运行 annotate_segment.py 做精细批注")
    return 0


if __name__ == "__main__":
    sys.exit(main())
