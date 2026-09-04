#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/select_segments.py — 段采样分层策略（v2.7 工程化修复轮，决策 18）

解决「分级策略只管层不管段」：把「20% 深度档提供 80% 价值」从人工拍脑袋选段
变成规则驱动的可复现采样。输入 structure.jsonl（已批全量的轻量结构层），输出
每段应跑哪一档的采样计划。

档位语义：
  deep  —— 深度档：额外跑 interpretation（+ craft 等昂贵层）；
  light —— 轻量档：structure 已覆盖即可，不追加深度层；
  skip  —— 过渡/背景铺垫段：可跳过后续精读。

默认规则（可用 CLI 覆盖）：
  1) D01 ∈ {激励事件, 上升行动, 高潮, 转折}            → deep（关键叙事段）
  2) D04.intensity ≥ 6（默认阈值）                     → deep（情绪峰值段）
  3) D07.is_switch_point == true                        → deep（视角切换段）
  4) D10 含对话                                        → 可选 deep（--dialogue-as-deep，默认关，避免比例失控）
  5) D01 ∈ {背景铺垫, 过渡}                            → skip
  6) 其余（下降行动 / 结局 / 复合功能 / 无法判断…）    → light

规则确定 + 透明：plan 文件携带 rule_desc，谁都能看出某段为何分到哪档。

用法：
  # 生成采样计划（输出 <doc_id>_segment_plan.json）
  python scripts/select_segments.py --structure out/sample_novel_zh_structure.jsonl

  # 自定义阈值 / 规则
  python scripts/select_segments.py --structure out/xxx_structure.jsonl \
      --deep-intensity 5 --no-switch-point --dialogue-as-deep \
      --output out/xxx_plan.json

下游消费：run_pipeline.py --plan <plan.json>（深度层只跑 deep 段）。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

# v2.5.1 修复 #1：Windows GBK 控制台 UnicodeEncodeError
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# 与 P4 触发集合（annotate_segment.TRIGGER_D01）保持一致：关键叙事段
DEEP_D01_DEFAULT = {"激励事件", "上升行动", "高潮", "转折"}
SKIP_D01_DEFAULT = {"背景铺垫", "过渡"}


def _load_structure(path: Path) -> list[tuple[str, dict]]:
    """返回 [(segment_id, layers.structure 内容)]。行缺失 layers.structure 时记 warning 并跳过。"""
    rows: list[tuple[str, dict]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            sid = obj.get("segment_id")
            layers = obj.get("layers") or {}
            st = layers.get("structure")
            if not sid or not isinstance(st, dict):
                print(f"⚠️ 跳过缺结构层的行：{sid}", file=sys.stderr)
                continue
            rows.append((sid, st))
    return rows


def _pick_tier(st: dict, cfg: dict) -> tuple[str, list[str]]:
    """返回 (tier, reasons)。cfg: {deep_d01, skip_d01, deep_intensity,
    switch_point(bool), dialogue_as_deep(bool)}"""
    reasons: list[str] = []
    d01 = st.get("D01")
    d04 = st.get("D04") or {}
    try:
        intensity = int(d04.get("intensity") or 0)
    except (TypeError, ValueError):
        intensity = 0
    d07 = st.get("D07") or {}
    switch_point = bool(d07.get("is_switch_point"))
    has_dialogue = st.get("D10") is not None

    if d01 in cfg["deep_d01"]:
        reasons.append(f"D01={d01}")
    if intensity >= cfg["deep_intensity"]:
        reasons.append(f"D04.intensity={intensity}≥{cfg['deep_intensity']}")
    if cfg["switch_point"] and switch_point:
        reasons.append("D07.is_switch_point=true")
    if cfg["dialogue_as_deep"] and has_dialogue:
        reasons.append("D10 含对话（--dialogue-as-deep）")
    if reasons:
        return "deep", reasons

    if d01 in cfg["skip_d01"]:
        return "skip", [f"D01={d01}（过渡/背景，低优先）"]
    return "light", ["其余段"]


def main() -> int:
    p = argparse.ArgumentParser(
        description="【精读批注 v2.7 工程化修复轮】段采样分层策略：把 20% 深度档从人工选段变规则驱动")
    p.add_argument("--structure", required=True, help="structure.jsonl 路径（已批全量结构层）")
    p.add_argument("--doc-id", default=None, help="文档 ID（默认从 structure 文件名前缀推断）")
    p.add_argument("--output", default=None, help="计划输出路径（默认 <doc_id>_segment_plan.json）")
    p.add_argument("--deep-d01", default=None,
                   help="深度档 D01 白名单（逗号分隔，覆盖默认 {激励事件,上升行动,高潮,转折}）")
    p.add_argument("--skip-d01", default=None,
                   help="跳过档 D01 白名单（逗号分隔，覆盖默认 {背景铺垫,过渡}）")
    p.add_argument("--deep-intensity", type=int, default=6, help="D04.intensity ≥ N 入深度档（默认 6）")
    p.add_argument("--no-switch-point", dest="switch_point", action="store_false",
                   help="不把视角切换段（D07.is_switch_point）计入深度档")
    p.add_argument("--dialogue-as-deep", action="store_true",
                   help="把含对话段（D10 非 null）计入深度档（默认关）")
    args = p.parse_args()

    struct_path = Path(args.structure)
    if not struct_path.is_file():
        print(f"❌ structure.jsonl 不存在：{struct_path}", file=sys.stderr)
        return 2
    doc_id = args.doc_id or struct_path.name.replace("_structure.jsonl", "")
    cfg = {
        "deep_d01": {s.strip() for s in args.deep_d01.split(",") if s.strip()} if args.deep_d01 else DEEP_D01_DEFAULT,
        "skip_d01": {s.strip() for s in args.skip_d01.split(",") if s.strip()} if args.skip_d01 else SKIP_D01_DEFAULT,
        "deep_intensity": args.deep_intensity,
        "switch_point": args.switch_point,
        "dialogue_as_deep": args.dialogue_as_deep,
    }
    rows = _load_structure(struct_path)
    if not rows:
        print("❌ structure.jsonl 无有效行（每行需含 layers.structure）", file=sys.stderr)
        return 2

    tiers: dict[str, list[str]] = {"deep": [], "light": [], "skip": []}
    per_segment: dict[str, dict] = {}
    for sid, st in rows:
        tier, reasons = _pick_tier(st, cfg)
        tiers[tier].append(sid)
        per_segment[sid] = {"tier": tier, "reasons": reasons}

    out_path = Path(args.output) if args.output else (struct_path.parent / f"{doc_id}_segment_plan.json")
    plan = {
        "doc_id": doc_id,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "rule_version": "1.0",
        "rule_desc": {
            "deep_d01": sorted(cfg["deep_d01"]),
            "deep_intensity_at_least": cfg["deep_intensity"],
            "switch_point_in_deep": cfg["switch_point"],
            "dialogue_as_deep": cfg["dialogue_as_deep"],
            "skip_d01": sorted(cfg["skip_d01"]),
        },
        "tiers": {k: sorted(v) for k, v in tiers.items()},
        "per_segment": per_segment,
    }
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(plan, f, ensure_ascii=False, indent=2)

    total = len(rows)
    n_deep, n_light, n_skip = len(tiers["deep"]), len(tiers["light"]), len(tiers["skip"])
    print(f"📄 doc_id     : {doc_id}")
    print(f"📄 输入结构行 : {total}")
    print(f"🔴 deep   : {n_deep:>3} ({100*n_deep/total:4.1f}%)  → 深度层（interpretation/craft…）")
    print(f"🟡 light  : {n_light:>3} ({100*n_light/total:4.1f}%)  → structure 已覆盖，不追加")
    print(f"⚪ skip   : {n_skip:>3} ({100*n_skip/total:4.1f}%)  → 过渡/背景，可跳过精读")
    print(f"📄 计划已写入 : {out_path}")
    if not tiers["deep"]:
        print("⚠️ 无任何 deep 段。请检查 structure 行数、D01 值是否命中白名单，或调低 --deep-intensity。",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
