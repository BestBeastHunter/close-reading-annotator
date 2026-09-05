#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/merge_batch.py — 官方 batch 合并注入工具（v3.8.4 新增，T-056）

用途：多 Agent 并行批注时，各自生成 _batch_*.jsonl 临时文件，
      用本工具合并为正式层文件，自动去重（按 segment_id），幂等 upsert。

用法：
  python scripts/merge_batch.py --batch-dir <产物目录> --layer <structure|interpretation|craft|emotion> --doc-id <doc_id>

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
    p = argparse.ArgumentParser(description="v3.8.4 官方 batch 合并注入工具（T-056）")
    p.add_argument("--batch-dir", required=True, help="包含 _batch_*.jsonl 的目录")
    p.add_argument("--layer", required=True, choices=["structure", "interpretation", "craft", "emotion"])
    p.add_argument("--doc-id", required=True, help="文档 ID")
    p.add_argument("--output", default=None, help="输出文件路径（默认 <batch-dir>/<doc_id>_<layer>.jsonl）")
    p.add_argument("--dry-run", action="store_true", help="只报告不写盘")
    args = p.parse_args()

    batch_dir = Path(args.batch_dir)
    if not batch_dir.is_dir():
        print("❌ 目录不存在: %s" % batch_dir, file=sys.stderr)
        return 2

    # 发现所有 _batch_*.jsonl 文件
    batch_files = sorted(batch_dir.glob("*_batch_*%s*.jsonl" % args.layer))
    if not batch_files:
        batch_files = sorted(batch_dir.glob("_batch_*.jsonl"))
    if not batch_files:
        print("❌ 未找到 _batch_*.jsonl 文件", file=sys.stderr)
        return 2

    print("📂 发现 %d 个 batch 文件:" % len(batch_files))
    for f in batch_files:
        print("   - %s" % f.name)

    # 合并并去重（按 segment_id，后出现的覆盖先出现的）
    merged = {}
    total_rows = 0
    for bf in batch_files:
        rows = load_jsonl(bf)
        total_rows += len(rows)
        for row in rows:
            sid = row.get("segment_id")
            if sid:
                merged[sid] = row  # 幂等 upsert

    print("")
    print("📊 合并统计:")
    print("   总输入行数: %d" % total_rows)
    print("   去重后行数: %d" % len(merged))
    print("   重复行数: %d" % (total_rows - len(merged)))

    if args.dry_run:
        print("")
        print("🔍 dry-run 模式，不写盘。")
        return 0

    # 写输出
    output_path = Path(args.output) if args.output else (batch_dir / ("%s_%s.jsonl" % (args.doc_id, args.layer)))
    with output_path.open("w", encoding="utf-8") as f:
        for sid in sorted(merged.keys()):
            f.write(json.dumps(merged[sid], ensure_ascii=False) + "\n")

    print("")
    print("✅ 合并完成: %d 行 → %s" % (len(merged), output_path.resolve()))
    print("   建议: 合并后删除 batch 文件: rm %s/_batch_*.jsonl" % batch_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
