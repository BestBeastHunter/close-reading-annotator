#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/run_pipeline.py — Phase 1–8 一体化驱动（v3.17.0 流程重构：连续编号、无任何可选步骤）

把八个阶段串成一条命令：原文 → 报告，支持断点续跑（读 checkpoint 跳过已完成阶段）。

  Phase 1  输入预处理   quality_gate.py（质量门硬门槛）+ preprocess.py（粗切分）
  Phase 2  精确切分     LumberChunker 场景语义切分：scene_boundary_wrapper.py（边界判断）→ reshape_segments.py（重排，产出 final_segments.jsonl + segment_id_mapping.json）
  Phase 3  逐段批注     annotate_segment.py   ← 批注来源三选一（见下），四层全量 × 全部 segment（v3.17.0 起无采样/无档级）
  Phase 4  跨段分析     cross_segment.py      （规则启发式）
  Phase 5  聚合层       scripts/aggregation/ 12 脚本全跑（实体消解→人物网络→场景图→角色弧线→故事类型→叙事结构→技法→因果→物件→传记→故事图→适配器）
  Phase 6  嵌套合并     merge_layers.py
  Phase 7  后处理校准   calibrate_quality.py + recalibrate_confidence.py + cross_validate_emotion.py（v3.17.0 起位于报告之前）
  Phase 8  报告渲染     render_report.py      （html/md，最后一步，含全部四层 + 跨段 + 聚合分析）

Phase 3 批注来源（skill 不捆绑 API，三种模式）：
  A. --llm-cmd "python your_wrapper.py"   全自动：调度壳逐个调用外部 LLM wrapper
  B. --input-json <file>                  Agent 自备批注行，一次性注入（校验/落盘/checkpoint 由调度壳做）
  C. 都不给                           骨架模式：跳过 Phase 3（需已有 structure 才能跑 Phase 4+）

断点续跑：
  每次成功完成一个阶段即写 checkpoint 阶段标记；再次运行时默认跳过已完成阶段
  （--force 强制重跑）。逐段批注完成度由 annotate_segment 自己的 checkpoint 管理。

用法：
  # 一条命令全流程（四层全量 + 聚合 + 校准 + 报告）
  python scripts/run_pipeline.py --input 小说.txt --doc-id novel \
      --output-dir out --llm-cmd "python tools/my_llm_wrapper.py" --report-format md

  # 骨架模式（已有人工/LLM 批注，只跑跨段→聚合→合并→校准→报告）
  python scripts/run_pipeline.py --doc-id novel --output-dir out --phases 4,5,6,7,8

  # 断点续跑（之前 Phase 1/2 已完成）
  python scripts/run_pipeline.py --doc-id novel --output-dir out --llm-cmd "..."
"""

from __future__ import annotations

import argparse
import os
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
AGG_DIR = SCRIPTS / "aggregation"

PHASE_KEYS = {  # 阶段号 → checkpoint 阶段标记
    4: "cross_segment_completed",
    5: "aggregation_completed",
    6: "merged_completed",
    8: "render_report_completed",
}

# 聚合层 12 脚本调用序列（依赖顺序：实体→网络/场景/弧线/类型/结构→技法/因果/物件→传记→故事图→适配器）
# 每项：(脚本相对路径, [参数名列表]，参数从 run 上下文取值)
_AGG_SCRIPTS = [
    "entity_resolution.py",
    "character_network.py",
    "scene_graph.py",
    "character_arcs.py",
    "story_type_inference.py",
    "narrative_structure.py",
    "writing_techniques.py",
    "causal_graph.py",
    "object_chains.py",
    "character_biographies.py",
    "story_graph.py",
    "adapters.py",
]


def _run_phase(phase_no: int, doc_id: str, out_dir: Path, cmd: list[str], extra_cwd: Path | None = None) -> bool:
    script = cmd[0]
    if Path(script).is_absolute():
        script_path = Path(script)
    else:
        script_path = SCRIPTS / script
    print(f"\n{'=' * 66}\n🚀 Phase {phase_no}  {script_path.name}\n{'=' * 66}")
    proc = subprocess.run(
        [PY, str(script_path)] + cmd[1:],
        cwd=str(extra_cwd or out_dir),
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


def _run_aggregation(phase_no: int, doc_id: str, out_dir: Path, agg_out: Path,
                     segments_path: Path, layer_paths: dict, cross_path: Path | None) -> bool:
    """Phase 5：聚合层 12 脚本全跑（v3.17.0 必须阶段，不再可关闭）。"""
    agg_out.mkdir(parents=True, exist_ok=True)
    eg = agg_out / f"{doc_id}_entity_graph.json"

    def _p(name: str) -> str | None:
        p = layer_paths.get(name)
        return str(p) if p and p.is_file() else None

    calls = [
        # ① 实体消解
        ["aggregation/entity_resolution.py", "--segments", str(segments_path),
         "--structure", _p("structure"), "--interpretation", _p("interpretation"),
         "--emotion", _p("emotion"), "--craft", _p("craft"),
         "--doc-id", doc_id, "--output-dir", str(agg_out)],
        # ② 人物关系网络（依赖 entity_graph）
        ["aggregation/character_network.py", "--entity-graph", str(eg),
         "--emotion", _p("emotion"), "--craft", _p("craft"),
         "--doc-id", doc_id, "--output-dir", str(agg_out)],
        # ③ 场景图（依赖 structure + entity_graph）
        ["aggregation/scene_graph.py", "--segments", str(segments_path),
         "--structure", _p("structure"), "--entity-graph", str(eg),
         "--doc-id", doc_id, "--output-dir", str(agg_out)],
        # ④ 角色弧线（依赖 structure/emotion/entity_graph）
        ["aggregation/character_arcs.py", "--segments", str(segments_path),
         "--structure", _p("structure"), "--emotion", _p("emotion"), "--craft", _p("craft"),
         "--entity-graph", str(eg),
         "--doc-id", doc_id, "--output-dir", str(agg_out)],
        # ⑤ 故事类型推断
        ["aggregation/story_type_inference.py", "--segments", str(segments_path),
         "--structure", _p("structure"), "--interpretation", _p("interpretation"),
         "--emotion", _p("emotion"),
         "--doc-id", doc_id, "--output-dir", str(agg_out)],
        # ⑥ 叙事结构
        ["aggregation/narrative_structure.py", "--structure", _p("structure"),
         "--doc-id", doc_id, "--output-dir", str(agg_out)],
        # ⑦ 叙事技法（依赖 cross_segment）
        ["aggregation/writing_techniques.py", "--structure", _p("structure"),
         "--interpretation", _p("interpretation"),
         "--cross-segment", str(cross_path) if cross_path and cross_path.is_file() else None,
         "--doc-id", doc_id, "--output-dir", str(agg_out)],
        # ⑧ 因果图（依赖 cross_segment）
        ["aggregation/causal_graph.py", "--cross-segment", str(cross_path) if cross_path and cross_path.is_file() else "",
         "--structure", _p("structure"), "--emotion", _p("emotion"),
         "--interpretation", _p("interpretation"), "--craft", _p("craft"),
         "--doc-id", doc_id, "--output-dir", str(agg_out)],
        # ⑨ 物件链（依赖 craft）
        ["aggregation/object_chains.py", "--craft", _p("craft"),
         "--doc-id", doc_id, "--output-dir", str(agg_out), "--include-all-types"],
        # ⑩ 人物传记（依赖多数产物）
        ["aggregation/character_biographies.py", "--segments", str(segments_path),
         "--structure", _p("structure"), "--interpretation", _p("interpretation"),
         "--craft", _p("craft"), "--emotion", _p("emotion"),
         "--cross-segment", str(cross_path) if cross_path and cross_path.is_file() else None,
         "--entity-graph", str(eg),
         "--character-arcs", str(agg_out / f"{doc_id}_character_arcs.json"),
         "--character-network", str(agg_out / f"{doc_id}_character_network.json"),
         "--narrative-structure", str(agg_out / f"{doc_id}_narrative_structure.json"),
         "--doc-id", doc_id, "--output-dir", str(agg_out)],
        # ⑪ 故事图合并（依赖全部聚合产物）
        ["aggregation/story_graph.py", "--aggregation-dir", str(agg_out),
         "--doc-id", doc_id, "--output-dir", str(agg_out)],
        # ⑫ 适配器输出（依赖 story_graph）
        ["aggregation/adapters.py", "--story-graph", str(agg_out / f"{doc_id}_story_graph.json"),
         "--doc-id", doc_id, "--output-dir", str(agg_out)],
    ]
    for name, cmd in zip(_AGG_SCRIPTS, calls):
        # 过滤 None 参数（缺失文件时省略可选参数）
        cmd = [c for c in cmd if c is not None]
        print(f"\n--- 聚合 {name} ---")
        proc = subprocess.run(
            [PY, str(SCRIPTS / cmd[0])] + cmd[1:],
            cwd=str(agg_out),
            encoding="utf-8",
            errors="replace",
        )
        if proc.returncode != 0:
            print(f"❌ 聚合脚本 {name} 失败 (exit={proc.returncode})，继续后续脚本", file=sys.stderr)
    mark_phase_completed(doc_id, "aggregation_completed", out_dir)
    return True


def main() -> int:
    p = argparse.ArgumentParser(
        description="【精读批注 v3.17.0】Phase 1–8 一体化驱动（连续编号；无任何可选步骤；聚合/校准/精确切分均为必须）+ 断点续跑")
    p.add_argument("--input", default=None, help="原始文本文件（Phase 1 切分需要）")
    p.add_argument("--doc-id", required=True, help="文档 ID")
    p.add_argument("--output-dir", default=".", help="所有产物的输出目录（默认当前）")
    p.add_argument("--phases", default="1,2,3,4,5,6,7,8", help="要运行的阶段，逗号分隔（默认全跑 1-8）")
    p.add_argument("--segments", default=None, help="已切好的 segments.jsonl（Phase 1 跳过时的备选入口）")
    p.add_argument("--scene-boundary", default=None,
                   help="已生成的 scene_boundary.json（Phase 2 跳过 LumberChunker 边界判断、直接 reshape 的备选入口）")
    p.add_argument("--layers", default="structure,interpretation,craft,emotion",
                   help="批注层，逗号分隔（默认四层全量）。v3.17.0 起不再有采样/档级，全部 segment 全部层")
    p.add_argument("--llm-cmd", default=None, help="外部 LLM wrapper 命令（Phase 3 来源 A）")
    p.add_argument("--input-json", default=None, help="批注行文件（Phase 3 来源 B，Agent 自备）")
    p.add_argument("--report-format", choices=["html", "md"], default="html",
                   help="Phase 8 报告格式（默认 html）")
    p.add_argument("--force", action="store_true", help="强制重跑已完成阶段/片段")
    p.add_argument("--skip-annotate", action="store_true",
                   help="跳过 Phase 3（骨架模式，只跑跨段/聚合/合并/校准/报告）")
    p.add_argument("--cleanup", action="store_true", default=True,
                   help="完成后自动清理 _batch_*.jsonl 临时文件（默认开启），v3.8.9 T-076")
    p.add_argument("--no-cleanup", action="store_false", dest="cleanup", help="不清理临时文件")
    args = p.parse_args()

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    doc_id = args.doc_id

    phases = sorted({int(x.strip()) for x in args.phases.split(",") if x.strip() in "12345678"})
    if not phases:
        print("❌ --phases 必须在 {1,2,3,4,5,6,7,8} 内", file=sys.stderr)
        return 2

    layers = [l.strip() for l in args.layers.split(",") if l.strip()]
    ALLOW = {"structure", "interpretation", "craft", "emotion"}
    layers = [l for l in layers if l in ALLOW]

    ckpt = load_checkpoint(doc_id, out_dir)
    if not args.force and ckpt:
        print(f"📊 checkpoint 已存在：{doc_id}_checkpoint.json（读断点；--force 强制重跑）")

    # ---------- Phase 1：输入预处理（质量门 + 粗切分） ----------
    segments_path = Path(args.segments) if args.segments else (out_dir / f"{doc_id}_segments.jsonl")
    if 1 in phases:
        # 1a. 质量门（硬门槛，fail 则阻断）
        if args.input:
            qr_path = out_dir / f"{doc_id}_quality_report.json"
            if args.force or not qr_path.is_file():
                ok = _run_phase(1, doc_id, out_dir, [
                    "quality_gate.py", "--input", args.input,
                    "--out", str(qr_path), "--fail-on-error",
                ])
                if not ok:
                    print("❌ Phase 1 质量门未通过：请修复原文后重跑（质量门为硬门槛，不允许跳过）", file=sys.stderr)
                    return 1
            else:
                print(f"⏭ Phase 1a 质量门跳过：{qr_path} 已存在（--force 重跑）")
        else:
            print("⏭ Phase 1a 质量门跳过：无 --input（骨架模式）")
        # 1b. 粗切分
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
            print(f"⏭ Phase 1b 跳过：{segments_path} 已存在（--force 可重切）")
    if not segments_path.is_file():
        print(f"❌ segments 不存在：{segments_path}", file=sys.stderr)
        return 2

    # ---------- Phase 2：LumberChunker 场景语义精确切分（必须） ----------
    final_segments_path = out_dir / f"{doc_id}_final_segments.jsonl"
    if 2 in phases:
        boundary_path = Path(args.scene_boundary) if args.scene_boundary else (
            out_dir / f"{doc_id}_scene_boundary.json")
        if args.force or not final_segments_path.is_file():
            # 2a. 场景边界判断（无现成 boundary 时调 LumberChunker wrapper）
            if not boundary_path.is_file():
                wrapper = SCRIPTS.parent / "examples" / "scene_boundary_wrapper.py"
                if not wrapper.is_file():
                    print(f"❌ Phase 2 找不到 LumberChunker wrapper：{wrapper}", file=sys.stderr)
                    return 1
                ok = _run_phase(2, doc_id, out_dir, [
                    str(wrapper), "--segments", str(segments_path),
                    "--output", str(boundary_path), "--doc-id", doc_id,
                ])
                if not ok:
                    print("❌ Phase 2 场景边界判断失败："
                          "需设置 SCENE_BOUNDARY_API_KEY 或提供 --scene-boundary 文件"
                          "（LumberChunker 精确切分为必须步骤，不允许跳过）", file=sys.stderr)
                    return 1
            else:
                print(f"⏭ Phase 2a 跳过：{boundary_path} 已存在（--force 重跑）")
            # 2b. reshape 重排
            ok = _run_phase(2, doc_id, out_dir, [
                "reshape_segments.py", "--segments", str(segments_path),
                "--boundaries", str(boundary_path),
                "--original", str(Path(args.input)) if args.input else None,
                "--doc-id", doc_id, "--output-dir", str(out_dir),
            ])
            if not ok:
                return 1
            final_segments_path = out_dir / f"{doc_id}_final_segments.jsonl"
        else:
            print(f"⏭ Phase 2 跳过：{final_segments_path} 已存在（--force 重跑）")
    # 后续阶段使用精确切分后的 segments（若存在）
    if final_segments_path.is_file():
        segments_path = final_segments_path
        print(f"📌 后续阶段使用精确切分段：{segments_path}")

    # ---------- Phase 3：逐段批注（四层全量，无采样） ----------
    if 3 in phases and not args.skip_annotate:
        if not args.input_json and not args.llm_cmd:
            print("⚠️ Phase 3 无批注来源（无 --llm-cmd / --input-json）→ 骨架模式：跳过 Phase 3。"
                  "若 structure.jsonl 已有内容，后续 Phase 4–8 可继续。")
        else:
            base_ann = [
                "annotate_segment.py", "--segments", str(segments_path),
                "--doc-id", doc_id, "--output-dir", str(out_dir),
            ]
            if args.force:
                base_ann.append("--force")

            if args.input_json:
                # 来源 B：Agent 自备批注行，一次注入（幂等）
                ok = _run_phase(3, doc_id, out_dir, base_ann + ["--input-json", args.input_json])
                if not ok:
                    return 1
            elif args.llm_cmd:
                # 来源 A：外部 LLM wrapper，四层全量 × 全部 segment（v3.17.0 无采样/无档级）
                for layer in layers:
                    ok = _run_phase(3, doc_id, out_dir, base_ann + [
                        "--layers", layer, "--all-pending", "--llm-cmd", args.llm_cmd])
                    if not ok:
                        return 1

    # ---------- Phase 4：跨段分析（规则） ----------
    structure_path = out_dir / f"{doc_id}_structure.jsonl"
    interp_path = out_dir / f"{doc_id}_interpretation.jsonl"
    craft_path = out_dir / f"{doc_id}_craft.jsonl"
    emotion_path = out_dir / f"{doc_id}_emotion.jsonl"
    layer_paths = {
        "structure": structure_path,
        "interpretation": interp_path,
        "craft": craft_path,
        "emotion": emotion_path,
    }
    cross_path = out_dir / f"{doc_id}_cross_segment.jsonl"

    if 4 in phases:
        if ckpt and ckpt.get(PHASE_KEYS[4]) and not args.force:
            print(f"⏭ Phase 4 跳过：{PHASE_KEYS[4]}=done（--force 重跑）")
        else:
            if not structure_path.is_file():
                print(f"⚠️ Phase 4 跳过：{structure_path} 不存在（需先完成 structure 批注）",
                      file=sys.stderr)
            else:
                ok = _run_phase(4, doc_id, out_dir, [
                    "cross_segment.py", "--doc-id", doc_id,
                    "--segments", str(segments_path), "--structure", str(structure_path),
                ])
                if not ok:
                    return 1

    # ---------- Phase 5：聚合层（必须，位于跨段与合并之间） ----------
    if 5 in phases:
        if ckpt and ckpt.get(PHASE_KEYS[5]) and not args.force:
            print(f"⏭ Phase 5 跳过：{PHASE_KEYS[5]}=done（--force 重跑）")
        else:
            ok = _run_aggregation(5, doc_id, out_dir, out_dir / "aggregation",
                                  segments_path, layer_paths, cross_path)
            if not ok:
                return 1

    # ---------- Phase 6：合并 ----------
    if 6 in phases:
        if ckpt and ckpt.get(PHASE_KEYS[6]) and not args.force:
            print(f"⏭ Phase 6 跳过：{PHASE_KEYS[6]}=done（--force 重跑）")
        else:
            ok = _run_phase(6, doc_id, out_dir, [
                "merge_layers.py", "--doc-id", doc_id, "--segments", str(segments_path)])
            if not ok:
                return 1

    # ---------- Phase 7：后处理校准（必须，位于报告之前） ----------
    if 7 in phases:
        print("\n🔧 Phase 7：后处理校准（quality_score + confidence 重算 + DLUT 交叉验证）")

        # 7.1 quality_score 校准（需要 craft 层）
        if craft_path.is_file():
            ok = _run_phase(7, doc_id, out_dir, [
                "calibrate_quality.py", "--dir", str(out_dir), "--doc-id", doc_id, "--in-place"])
            if not ok:
                print("⚠️ quality_score 校准失败，继续后续校准（不阻断主流程）")
        else:
            print("⏭ quality_score 校准跳过：无 craft.jsonl")

        # 7.2 confidence 信号驱动重算（需要全部四层）
        all_layers_exist = all(p.is_file() for p in [structure_path, interp_path, craft_path, emotion_path])
        if all_layers_exist:
            ok = _run_phase(7, doc_id, out_dir, [
                "recalibrate_confidence.py", "--dir", str(out_dir), "--doc-id", doc_id,
                "--all-layers", "--in-place"])
            if not ok:
                print("⚠️ confidence 重算失败，继续后续校准（不阻断主流程）")
        else:
            print("⏭ confidence 重算跳过：四层批注不完整")

        # 7.3 DLUT 弱信号交叉验证（需要 emotion 层）
        if emotion_path.is_file():
            ok = _run_phase(7, doc_id, out_dir, [
                "cross_validate_emotion.py", "--dir", str(out_dir), "--doc-id", doc_id, "--in-place"])
            if not ok:
                print("⚠️ DLUT 交叉验证失败（不阻断主流程）")
        else:
            print("⏭ DLUT 交叉验证跳过：无 emotion.jsonl")

    # ---------- Phase 8：报告渲染（最后一步，必须最后执行） ----------
    if 8 in phases:
        if ckpt and ckpt.get(PHASE_KEYS[8]) and not args.force:
            print(f"⏭ Phase 8 跳过：{PHASE_KEYS[8]}=done（--force 重跑）")
        else:
            agg_dir = out_dir / "aggregation"
            ok = _run_phase(8, doc_id, out_dir, [
                "render_report.py", "--doc-id", doc_id,
                "--segments", str(segments_path), "--format", args.report_format,
                "--agg-dir", str(agg_dir) if agg_dir.is_dir() else str(out_dir),
            ])
            if not ok:
                return 1

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
