#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/run_pipeline.py — Phase 1–6 一体化驱动（v2.7 工程化修复轮，决策 18；v3.8.3 新增 Phase 6 后处理校准）

把五个阶段串成一条命令：原文 → 报告，支持断点续跑（读 checkpoint 跳过已完成阶段）。

  Phase 1  切分        preprocess.py
  Phase 2  逐段批注    annotate_segment.py   ← 批注来源三选一（见下）
  Phase 3  跨段分析    cross_segment.py      （规则启发式）
  Phase 4  嵌套合并    merge_layers.py
  Phase 5  报告渲染    render_report.py      （html/md）
  Phase 6  后处理校准  calibrate_quality.py + recalibrate_confidence.py + cross_validate_emotion.py（v3.8.2 新增，v3.8.3 集成，--calibrate 默认开启）

Phase 2 批注来源（skill 不捆绑 API，三种模式）：
  A. --llm-cmd "python your_wrapper.py"   全自动：调度壳逐个调用外部 LLM wrapper
  B. --input-json <file>                  Agent 自备批注行，一次性注入（校验/落盘/checkpoint 由调度壳做）
  C. 都不给                           骨架模式：跳过 Phase 2（需已有 structure 才能跑 Phase 3+）

分级档位（决策 18）：
  --plan <select_segments.py 产物>：structure 全量跑；interpretation/craft/emotion
  只跑 plan 标为 deep 的段——让「20% 深度档」落地为规则而非人工选段。

断点续跑：
  每次成功完成一个阶段即写 checkpoint 阶段标记；再次运行时默认跳过已完成阶段
  （--force 强制重跑）。逐段批注完成度由 annotate_segment 自己的 checkpoint 管理。

用法：
  # 一条命令全流程（结构层全量 + 深档层），report 输出 md
  python scripts/run_pipeline.py --input 小说.txt --doc-id novel \
      --output-dir out --plan out/novel_segment_plan.json \
      --llm-cmd "python tools/my_llm_wrapper.py" --report-format md

  # 骨架模式（已有人工/LLM 批注，只跑跨段→合并→报告）
  python scripts/run_pipeline.py --doc-id novel --output-dir out --phases 3,4,5

  # 断点续跑（之前 Phase 1/2 已完成）
  python scripts/run_pipeline.py --doc-id novel --output-dir out --llm-cmd "..."
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

# v2.5.1 修复 #1：Windows GBK 控制台 UnicodeEncodeError
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

sys.path.insert(0, str(Path(__file__).parent))
from checkpoint import (  # noqa: E402
    load_checkpoint,
    mark_phase_completed,
)

PY = sys.executable
SCRIPTS = Path(__file__).parent

PHASE_KEYS = {  # 阶段号 → checkpoint 阶段标记
    3: "cross_segment_completed",
    4: "merged_completed",
    5: "render_report_completed",
}


def _load_plan(plan_path: Path) -> dict | None:
    try:
        with plan_path.open("r", encoding="utf-8") as f:
            plan = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"❌ 读取计划文件失败：{e}", file=sys.stderr)
        return None
    if not isinstance(plan, dict) or not isinstance(plan.get("tiers"), dict):
        print(f"❌ 计划文件格式无效（缺 tiers 字段）：{plan_path}", file=sys.stderr)
        return None
    return plan


def _run_phase(phase_no: int, doc_id: str, out_dir: Path, cmd: list[str]) -> bool:
    print(f"\n{'=' * 66}\n🚀 Phase {phase_no}  {cmd[0]}\n{'=' * 66}")
    proc = subprocess.run(
        [PY, str(SCRIPTS / cmd[0])] + cmd[1:],
        cwd=str(out_dir),
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        print(f"\n❌ Phase {phase_no} 失败 (exit={proc.returncode})。"
              f"可修复后用相同命令重跑（已完成的阶段会自动跳过）。", file=sys.stderr)
        return False
    if phase_no in PHASE_KEYS:
        mark_phase_completed(doc_id, PHASE_KEYS[phase_no], out_dir)
    return True


def main() -> int:
    p = argparse.ArgumentParser(
        description="【精读批注 v2.7 工程化修复轮】Phase 1–5 一体化驱动 + 断点续跑")
    p.add_argument("--input", default=None, help="原始文本文件（Phase 1 切分需要）")
    p.add_argument("--doc-id", required=True, help="文档 ID")
    p.add_argument("--output-dir", default=".", help="所有产物的输出目录（默认当前）")
    p.add_argument("--phases", default="1,2,3,4,5,6", help="要运行的阶段，逗号分隔（默认全跑，含 Phase 6 校准）")
    p.add_argument("--segments", default=None, help="已切好的 segments.jsonl（Phase 1 跳过时的备选入口）")
    p.add_argument("--layers", default="structure,interpretation,craft",
                   help="候选层，逗号分隔。structure 始终全量；interpretation/craft/emotion 受 --plan 档位约束")
    p.add_argument("--llm-cmd", default=None, help="外部 LLM wrapper 命令（Phase 2 来源 A）")
    p.add_argument("--input-json", default=None, help="批注行文件（Phase 2 来源 B，Agent 自备）")
    p.add_argument("--plan", default=None,
                   help="select_segments.py 产物：深度层只跑标为 deep 的段（structure 不受限）")
    p.add_argument("--report-format", choices=["html", "md"], default="html",
                   help="Phase 5 报告格式（默认 html）")
    p.add_argument("--force", action="store_true", help="强制重跑已完成阶段/片段")
    p.add_argument("--skip-annotate", action="store_true", help="跳过 Phase 2（骨架模式，只跑跨段/合并/报告）")
    p.add_argument("--aggregation", dest="aggregation", action="store_true", default=True,
                       help="Phase 4.5 聚合分析（默认开启），v3.10.0 T-089")
    p.add_argument("--no-aggregation", dest="aggregation", action="store_false",
                       help="关闭 Phase 4.5 聚合分析")
    p.add_argument("--aggregation-level", choices=["core", "full"], default="full",
                       help="聚合级别：core=核心5个脚本，full=全部10个脚本（默认full）")
    p.add_argument("--calibrate", dest="calibrate", action="store_true", default=True, help="Phase 6 后处理校准（默认开启）：quality_score + confidence 重算 + DLUT 交叉验证")
    p.add_argument("--no-calibrate", dest="calibrate", action="store_false", help="关闭 Phase 6 后处理校准")
    p.add_argument("--cleanup", action="store_true", default=True, help="完成后自动清理 _batch_*.jsonl 临时文件（默认开启），v3.8.9 T-076")
    p.add_argument("--no-cleanup", action="store_false", dest="cleanup", help="不清理临时文件")
    args = p.parse_args()

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    doc_id = args.doc_id

    phases = sorted({int(x.strip()) for x in args.phases.split(",") if x.strip() in "123456"})
    if not phases:
        print("❌ --phases 必须在 {1,2,3,4,5,6} 内", file=sys.stderr)
        return 2

    layers = [l.strip() for l in args.layers.split(",") if l.strip()]
    ALLOW = {"structure", "interpretation", "craft", "emotion"}
    layers = [l for l in layers if l in ALLOW]

    ckpt = load_checkpoint(doc_id, out_dir)
    if not args.force and ckpt:
        print(f"📊 checkpoint 已存在：{doc_id}_checkpoint.json（读断点；--force 强制重跑）")

    # ---------- Phase 1：切分 ----------
    segments_path = Path(args.segments) if args.segments else (out_dir / f"{doc_id}_segments.jsonl")
    if 1 in phases:
        if args.force or not segments_path.is_file():
            if not args.input:
                print("❌ Phase 1 需要 --input（源文本），或已存在的 --segments", file=sys.stderr)
                return 2
            ok = _run_phase(1, doc_id, out_dir, [
                "preprocess.py", "--input", args.input,
                "--doc-id", doc_id, "--output-dir", str(out_dir),
            ])
            if not ok:
                return 1
        else:
            print(f"⏭ Phase 1 跳过：{segments_path} 已存在（--force 可重切）")
    if not segments_path.is_file():
        print(f"❌ segments 不存在：{segments_path}", file=sys.stderr)
        return 2

    plan: dict | None = None
    if args.plan:
        plan = _load_plan(Path(args.plan))
        if plan is None:
            return 2
        deep_ids = plan["tiers"].get("deep", [])
        print(f"📄 采样计划：{len(deep_ids)} 段为深度档"
              f"（结构层全量；interpretation/craft/emotion 只跑这些段）")
    else:
        deep_ids = None

    # ---------- Phase 2：逐段批注 ----------
    if 2 in phases and not args.skip_annotate:
        if not args.input_json and not args.llm_cmd:
            print("⚠️ Phase 2 无批注来源（无 --llm-cmd / --input-json）→ 骨架模式：跳过 Phase 2。"
                  "若 structure.jsonl 已有内容，后续 Phase 3–5 可继续。")
        else:
            base_ann = [
                "annotate_segment.py", "--segments", str(segments_path),
                "--doc-id", doc_id, "--output-dir", str(out_dir),
            ]
            if args.force:
                base_ann.append("--force")

            if args.input_json:
                # 来源 B：Agent 自备批注行，一次注入（幂等）
                ok = _run_phase(2, doc_id, out_dir, base_ann + ["--input-json", args.input_json])
                if not ok:
                    return 1
            elif args.llm_cmd:
                # 来源 A：外部 LLM wrapper
                # 1) structure 始终全量
                ok = _run_phase(2, doc_id, out_dir, base_ann + [
                    "--layers", "structure", "--all-pending", "--llm-cmd", args.llm_cmd])
                if not ok:
                    return 1
                # 2) 深度层：有 plan 按 deep 段逐段跑；无 plan 则全量 pending
                deep_layers = [l for l in layers if l != "structure"]
                if deep_layers:
                    if plan and not deep_ids:
                        # 采样计划存在但无 deep 段：深度层无目标，跳过（structure 已全量覆盖）
                        print("⚠️ 采样计划无 deep 段 → 跳过深度层（结构层已全量执行）")
                    elif plan:
                        for sid in deep_ids:
                            ok = _run_phase(2, doc_id, out_dir, base_ann + [
                                "--segment", sid, "--layers", ",".join(deep_layers),
                                "--llm-cmd", args.llm_cmd])
                            if not ok:
                                return 1
                    else:
                        ok = _run_phase(2, doc_id, out_dir, base_ann + [
                            "--layers", ",".join(deep_layers), "--all-pending",
                            "--llm-cmd", args.llm_cmd])
                        if not ok:
                            return 1

    # ---------- Phase 3：跨段分析（规则） ----------
    if 3 in phases:
        if ckpt and ckpt.get(PHASE_KEYS[3]) and not args.force:
            print(f"⏭ Phase 3 跳过：{PHASE_KEYS[3]}=done（--force 重跑）")
        else:
            structure_path = out_dir / f"{doc_id}_structure.jsonl"
            if not structure_path.is_file():
                print(f"⚠️ Phase 3 跳过：{structure_path} 不存在（需先完成 structure 批注）",
                      file=sys.stderr)
            else:
                ok = _run_phase(3, doc_id, out_dir, [
                    "cross_segment.py", "--doc-id", doc_id,
                    "--segments", str(segments_path), "--structure", str(structure_path),
                ])
                if not ok:
                    return 1

    # ---------- Phase 4：合并 ----------
    if 4 in phases:
        if ckpt and ckpt.get(PHASE_KEYS[4]) and not args.force:
            print(f"⏭ Phase 4 跳过：{PHASE_KEYS[4]}=done（--force 重跑）")
        else:
            ok = _run_phase(4, doc_id, out_dir, [
                "merge_layers.py", "--doc-id", doc_id, "--segments", str(segments_path)])
            if not ok:
                return 1

    # ---------- Phase 5：报告 ----------
    if 5 in phases:
        if ckpt and ckpt.get(PHASE_KEYS[5]) and not args.force:
            print(f"⏭ Phase 5 跳过：{PHASE_KEYS[5]}=done（--force 重跑）")
        else:
            ok = _run_phase(5, doc_id, out_dir, [
                "render_report.py", "--doc-id", doc_id,
                "--segments", str(segments_path), "--format", args.report_format])
            if not ok:
                return 1


    # ---------- Phase 6：后处理校准（v3.8.2 新增，v3.8.3 集成） ----------
    if 6 in phases and args.calibrate:
        print("\n🔧 Phase 6：后处理校准（quality_score + confidence 重算 + DLUT 交叉验证）")
        craft_path = out_dir / f"{doc_id}_craft.jsonl"
        emotion_path = out_dir / f"{doc_id}_emotion.jsonl"
        structure_path = out_dir / f"{doc_id}_structure.jsonl"
        interp_path = out_dir / f"{doc_id}_interpretation.jsonl"

        # 6.1 quality_score 校准（需要 craft 层）
        if craft_path.is_file():
            ok = _run_phase(6, doc_id, out_dir, [
                "calibrate_quality.py", "--dir", str(out_dir), "--doc-id", doc_id, "--in-place"])
            if not ok:
                print("⚠️ quality_score 校准失败，继续后续校准（不阻断主流程）")
        else:
            print("⏭ quality_score 校准跳过：无 craft.jsonl")

        # 6.2 confidence 信号驱动重算（需要全部四层）
        all_layers_exist = all(p.is_file() for p in [structure_path, interp_path, craft_path, emotion_path])
        if all_layers_exist:
            ok = _run_phase(6, doc_id, out_dir, [
                "recalibrate_confidence.py", "--dir", str(out_dir), "--doc-id", doc_id,
                "--all-layers", "--in-place"])
            if not ok:
                print("⚠️ confidence 重算失败，继续后续校准（不阻断主流程）")
        else:
            print("⏭ confidence 重算跳过：四层批注不完整")

        # 6.3 DLUT 弱信号交叉验证（需要 emotion 层）
        if emotion_path.is_file():
            ok = _run_phase(6, doc_id, out_dir, [
                "cross_validate_emotion.py", "--dir", str(out_dir), "--doc-id", doc_id, "--in-place"])
            if not ok:
                print("⚠️ DLUT 交叉验证失败（不阻断主流程）")
        else:
            print("⏭ DLUT 交叉验证跳过：无 emotion.jsonl")

    elif 6 in phases and not args.calibrate:
        print("⏭ Phase 6 跳过：--no-calibrate 已关闭")

    print("\n✅ run_pipeline 全部完成。产物目录：", out_dir)

    # v3.8.9 T-076：自动清理 _batch_*.jsonl 临时文件
    if getattr(args, "cleanup", True):
        output_dir = Path(args.output_dir) if args.output_dir else Path.cwd()
        batch_files = list(output_dir.glob("_batch_*.jsonl"))
        if batch_files:
            for bf in batch_files:
                bf.unlink()
            print(f"  🧹 已清理 {len(batch_files)} 个 _batch_*.jsonl 临时文件")
    return 0


if __name__ == "__main__":
    sys.exit(main())
