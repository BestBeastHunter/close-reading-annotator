#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/checkpoint.py — 断点续跑状态管理 v2.7.0（含 emotion 层 / emotion_skipped）

轻量级 checkpoint 读写与进度查询。
作为 annotate_segment.py / cross_segment.py / merge_layers.py 的公共工具模块。

零第三方依赖。

命令行用法（状态查询）：
  # 查询某文档当前进度
  python scripts/checkpoint.py status --doc-id sample_novel_zh

  # 重置某层的完成状态（比如重跑 structure）
  python scripts/checkpoint.py reset-layer --doc-id sample_novel_zh --layer structure

  # 整体重置
  python scripts/checkpoint.py reset-all --doc-id sample_novel_zh
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

# v2.5.1 修复 #1：Windows GBK 控制台 UnicodeEncodeError（emoji 打印崩溃）
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def _ckpt_path(doc_id: str, base_dir: Path | None = None) -> Path:
    return (base_dir or Path.cwd()) / f"{doc_id}_checkpoint.json"


def load_checkpoint(doc_id: str, base_dir: Path | None = None) -> dict | None:
    p = _ckpt_path(doc_id, base_dir)
    if not p.is_file():
        return None
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_checkpoint(checkpoint: dict, base_dir: Path | None = None) -> None:
    """原子写（写 temp 后 rename），避免半写导致损坏。"""
    checkpoint["last_updated"] = datetime.now().isoformat(timespec="seconds")
    p = _ckpt_path(checkpoint["doc_id"], base_dir)
    tmp = p.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(checkpoint, f, ensure_ascii=False, indent=2)
    tmp.replace(p)


def mark_layer_completed(doc_id: str, segment_id: str, layer: str, base_dir: Path | None = None) -> bool:
    ckpt = load_checkpoint(doc_id, base_dir)
    if ckpt is None:
        return False
    entry = next(
        (c for c in ckpt["completed"] if c["segment"] == segment_id),
        None,
    )
    if entry is None:
        ckpt["completed"].append({"segment": segment_id, "layers": [layer]})
    else:
        if layer not in entry["layers"]:
            entry["layers"].append(layer)
    save_checkpoint(ckpt, base_dir)
    return True


def is_layer_completed(doc_id: str, segment_id: str, layer: str, base_dir: Path | None = None) -> bool:
    ckpt = load_checkpoint(doc_id, base_dir)
    if ckpt is None:
        return False
    entry = next(
        (c for c in ckpt["completed"] if c["segment"] == segment_id),
        None,
    )
    return bool(entry and layer in entry.get("layers", []))


def get_pending_layers(doc_id: str, segment_id: str, all_layers: list[str], base_dir: Path | None = None) -> list[str]:
    ckpt = load_checkpoint(doc_id, base_dir)
    if ckpt is None:
        return list(all_layers)
    entry = next(
        (c for c in ckpt["completed"] if c["segment"] == segment_id),
        None,
    )
    done = entry.get("layers", []) if entry else []
    return [l for l in all_layers if l not in done]


# v2.5.1：Phase 3/4/5 阶段标记（cross_segment/merged/render_report 完成后调用）
PHASE_KEYS = ("cross_segment_completed", "merged_completed", "render_report_completed")


def mark_phase_completed(doc_id: str, phase_key: str, base_dir: Path | None = None, value: bool = True) -> bool:
    if phase_key not in PHASE_KEYS:
        return False
    ckpt = load_checkpoint(doc_id, base_dir)
    if ckpt is None:
        return False
    ckpt[phase_key] = value
    save_checkpoint(ckpt, base_dir)
    return True


def is_phase_completed(doc_id: str, phase_key: str, base_dir: Path | None = None) -> bool:
    ckpt = load_checkpoint(doc_id, base_dir)
    return bool(ckpt and ckpt.get(phase_key))


# ---------------- v3.13.0 Runtime Scratchpad 快照 ----------------

def save_scratchpad_snapshot(checkpoint: dict, scratchpad) -> None:
    """
    v3.13.0：将 Runtime Scratchpad 序列化为 dict 存入 checkpoint。
    scratchpad 可以是 Scratchpad 对象或 None（None 时不保存）。
    """
    if scratchpad is None:
        return
    try:
        if hasattr(scratchpad, "to_json"):
            checkpoint["scratchpad_snapshot"] = json.loads(scratchpad.to_json())
        elif isinstance(scratchpad, dict):
            checkpoint["scratchpad_snapshot"] = scratchpad
    except Exception as e:
        print(f"[checkpoint] ⚠️ Scratchpad 快照保存失败：{e}", file=sys.stderr)


def load_scratchpad_snapshot(checkpoint):
    """
    v3.13.0：从 checkpoint 中恢复 Runtime Scratchpad。
    返回 Scratchpad 对象或 None（checkpoint 无快照时）。
    """
    if checkpoint is None or not isinstance(checkpoint, dict) or "scratchpad_snapshot" not in checkpoint:
        return None
    try:
        from scratchpad import Scratchpad
        snapshot = checkpoint["scratchpad_snapshot"]
        if isinstance(snapshot, str):
            return Scratchpad.from_json(snapshot)
        elif isinstance(snapshot, dict):
            return Scratchpad.from_json(json.dumps(snapshot, ensure_ascii=False))
    except Exception as e:
        print(f"[checkpoint] ⚠️ Scratchpad 快照恢复失败：{e}", file=sys.stderr)
    return None


# ---------------- CLI ----------------

def _base_dir(args) -> Path | None:
    return Path(args.dir) if getattr(args, "dir", None) else None


def cmd_status(args: argparse.Namespace) -> int:
    base_dir = _base_dir(args)
    ckpt = load_checkpoint(args.doc_id, base_dir)
    if ckpt is None:
        print(f"❌ checkpoint 不存在：{_ckpt_path(args.doc_id, base_dir)}", file=sys.stderr)
        return 2
    total = ckpt["total_segments"]
    completed_segments = len(ckpt["completed"])
    # 统计每层完成数量
    layer_counts: dict[str, int] = {}
    for entry in ckpt["completed"]:
        for l in entry.get("layers", []):
            layer_counts[l] = layer_counts.get(l, 0) + 1
    print(f"📄 doc_id           : {ckpt['doc_id']}")
    print(f"📊 schema_version   : {ckpt.get('schema_version', 'N/A')}")
    print(f"📊 total_segments   : {total}")
    print(f"✅ 完成片段数       : {completed_segments}/{total} ({100*completed_segments/total if total else 0:.0f}%)")
    print(f"📈 各层完成情况     :")
    for layer in ("structure", "interpretation", "craft", "emotion"):
        n = layer_counts.get(layer, 0)
        pct = 100 * n / total if total else 0
        print(f"     {layer:<15}: {n}/{total} ({pct:.0f}%)")
    skipped = ckpt.get("emotion_skipped", [])
    if skipped:
        print(f"     emotion_skipped : {len(skipped)} 段（P4 判定不触发）")
    print(f"🔗 cross_segment    : {'✅ done' if ckpt.get('cross_segment_completed') else '⏳ pending'}")
    print(f"🔀 merged           : {'✅ done' if ckpt.get('merged_completed') else '⏳ pending'}")
    print(f"📝 report           : {'✅ done' if ckpt.get('render_report_completed') else '⏳ pending'}")
    print(f"🕒 创建时间         : {ckpt.get('created_at', 'N/A')}")
    print(f"🕒 最近更新         : {ckpt.get('last_updated', 'N/A')}")
    return 0


def cmd_reset_layer(args: argparse.Namespace) -> int:
    base_dir = _base_dir(args)
    ckpt = load_checkpoint(args.doc_id, base_dir)
    if ckpt is None:
        print(f"❌ checkpoint 不存在：{_ckpt_path(args.doc_id, base_dir)}", file=sys.stderr)
        return 2
    layer = args.layer
    for entry in ckpt["completed"]:
        if layer in entry.get("layers", []):
            entry["layers"] = [l for l in entry["layers"] if l != layer]
    if layer == "structure":
        ckpt["cross_segment_completed"] = False
        ckpt["merged_completed"] = False
        ckpt["render_report_completed"] = False
    if layer in ("interpretation", "craft", "emotion"):
        ckpt["merged_completed"] = False
        ckpt["render_report_completed"] = False
    save_checkpoint(ckpt, base_dir)
    print(f"✅ 已重置 layer={layer} 完成状态（下游阶段也被重置）")
    return 0


def cmd_reset_all(args: argparse.Namespace) -> int:
    base_dir = _base_dir(args)
    ckpt = load_checkpoint(args.doc_id, base_dir)
    if ckpt is None:
        print(f"❌ checkpoint 不存在：{_ckpt_path(args.doc_id, base_dir)}", file=sys.stderr)
        return 2
    ckpt["completed"] = []
    ckpt["cross_segment_completed"] = False
    ckpt["merged_completed"] = False
    ckpt["render_report_completed"] = False
    save_checkpoint(ckpt, base_dir)
    print("✅ 已整体重置 checkpoint（保留 total_segments）")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="【精读批注 v2.6】断点续跑 checkpoint 管理工具")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("status", help="查看某文档当前进度")
    s.add_argument("--doc-id", required=True)
    s.add_argument("--dir", default=None, help="checkpoint 所在目录（默认当前目录）")
    s.set_defaults(func=cmd_status)

    r = sub.add_parser("reset-layer", help="重置某层完成状态（会连带重置依赖此层的下游阶段）")
    r.add_argument("--doc-id", required=True)
    r.add_argument("--layer", choices=["structure", "interpretation", "emotion", "craft"], required=True)
    r.add_argument("--dir", default=None, help="checkpoint 所在目录（默认当前目录）")
    r.set_defaults(func=cmd_reset_layer)

    a = sub.add_parser("reset-all", help="整体重置")
    a.add_argument("--doc-id", required=True)
    a.add_argument("--dir", default=None, help="checkpoint 所在目录（默认当前目录）")
    a.set_defaults(func=cmd_reset_all)

    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
