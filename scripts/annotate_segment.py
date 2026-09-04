#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/annotate_segment.py — 单片段四层 + D19 情感(可选)批注调用入口 v2.7.0

⚠️ 本脚本是【调度壳】，不内嵌大模型调用。
它负责：
  1) 读取 segments.jsonl 中指定 segment_id 的原文片段；
  2) 读取 checkpoint 判断该 (segment, layer) 是否已完成；
  3) 调用 LLM 生产者（通过环境变量或插件注入）产出批注 JSON；
  4) 调 validate_output.py 校验；
  5) 校验通过写 layer JSONL + 更新 checkpoint。

layer ∈ {structure, interpretation, craft, emotion}（v2.7.0 新增 emotion = P4 D19：
  自动读取 structure.jsonl 注入该段 D01/D04/D10 作为触发判定上下文；
  key_phrases 子串校验需要原文，脚本会从 segments 行补齐 text_span）。

⚠️ LLM 调用采用【外部注入】：通过 --llm-cmd <外部命令> 指定；
   未指定时进入"手动模式"——打印出标准 SKILL Prompt 输入片段，
   让用户复制给 LLM / 手动粘贴回 JSON。
   脚本保持 v2.5 架构决策：不捆绑任何具体 API 厂商
   （DeepSeek/Qwen/GPT 等均可通过 --llm-cmd 接入），是可选工具。

用法：
  # 单片段 + 单层（手动模式）
  python scripts/annotate_segment.py \
    --segments moon_sixpence_segments.jsonl \
    --checkpoint moon_sixpence_checkpoint.json \
    --doc-id moon_sixpence \
    --segment moon_sixpence_seg_0001 \
    --layers structure \
    --output-dir .

  # 单片段 + P4 情感层 D19（v2.7.0：自动注入该段 D01/D04/D10 + 原文）
  python scripts/annotate_segment.py \
    --segments moon_sixpence_segments.jsonl \
    --doc-id moon_sixpence \
    --segment moon_sixpence_seg_0091 \
    --layers emotion \
    --output-dir .

  # 单层 + 提供外部 LLM 命令（接收 stdin JSON 返回 stdout JSON）
  python scripts/annotate_segment.py \
    --segments xxx_segments.jsonl --doc-id xxx \
    --segment xxx_seg_0001 --layers structure,interpretation,craft \
    --llm-cmd "python your_llm_wrapper.py"
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

# v2.5.1 修复 #1：Windows GBK 控制台 UnicodeEncodeError（emoji 打印崩溃）
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# 导入 checkpoint 工具
sys.path.insert(0, str(Path(__file__).parent))
from checkpoint import (  # noqa: E402
    mark_layer_completed,
    is_layer_completed,
    load_checkpoint,
    save_checkpoint,
)

SCHEMA_VERSION = "2.7.0"

ALL_LAYERS = ["structure", "interpretation", "craft", "emotion"]

# P4 触发条件 #2：D01 ∈ 关键叙事段（决策 17 / SKILL.md Phase 2.5）
TRIGGER_D01 = {"激励事件", "上升行动", "高潮", "转折"}


def _load_segments(segments_path: Path) -> dict[str, dict]:
    out: dict[str, dict] = {}
    with segments_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            out[obj.get("segment_id")] = obj
    return out


def _load_structure_block(out_dir: Path, doc_id: str, segment_id: str) -> dict | None:
    """读 <out_dir>/<doc_id>_structure.jsonl，返回该段 {D01,D04,D10} P4 判定块；不存在返回 None。"""
    path = out_dir / f"{doc_id}_structure.jsonl"
    if not path.is_file():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)
                if row.get("segment_id") != segment_id:
                    continue
                st = (row.get("layers") or {}).get("structure") or {}
                return {"D01": st.get("D01"), "D04": st.get("D04"), "D10": st.get("D10")}
    except json.JSONDecodeError:
        pass
    return None


def _trigger_notes(block: dict | None) -> tuple[bool, list[str]]:
    """P4 触发判定（SKILL.md Phase 2.5 条件 1–3；条件 4「用户显式要求」由人工行使）。"""
    if block is None:
        return False, []
    reasons: list[str] = []
    d04 = block.get("D04") or {}
    try:
        iv = int(d04.get("intensity") or 0)
    except (TypeError, ValueError):
        iv = 0
    if iv >= 4:
        reasons.append(f"D04.intensity={iv} ≥ 4")
    if block.get("D01") in TRIGGER_D01:
        reasons.append(f"D01 ∈ 关键叙事（{block.get('D01')}）")
    if block.get("D10") is not None:
        reasons.append("D10 非 null（含对话）")
    return bool(reasons), reasons


def _emotion_manual_block(seg: dict, struct_blk: dict | None) -> str:
    triggered, reasons = _trigger_notes(struct_blk)
    lines = [
        "\n----- P4 · D19 情感分析（layer=emotion）专用输入 -----",
    ]
    if struct_blk is not None:
        lines.append("该段 structure 判定上下文（D01/D04/D10）：")
        lines.append(json.dumps(struct_blk, ensure_ascii=False, indent=2))
        if triggered:
            lines.append("✅ 触发命中：" + "；".join(reasons))
        else:
            lines.append("⚠️ 未命中触发条件 1–3（intensity≥4 / D01 关键叙事 / D10 对话）。")
            lines.append("   如属『用户显式要求深度情感分析』（触发条件 4）可继续；否则建议跳过并登记 emotion_skipped。")
    else:
        lines.append("⚠️ 未找到该段 structure 行：无法自动判定触发，请人工按 P4 条件核对。")
    lines.append(
        "要求：emotion 必须选自 references/emotion-lexicon.md 44 词白名单"
        "（无对应词→选最接近词 + expression.note 说明，不造新词）；"
    )
    lines.append(
        "结构按 templates/emotion-output.json：primary 必填；secondary/target/trigger/arc 无明确依据一律 "
        "null + 顶层 null_reasons，禁止编造情感对象与情感弧；"
    )
    lines.append("expression.key_phrases 每项必须是上文原文的子串（校验 error 级）。")
    return "\n".join(lines)


def _manual_prompt(seg: dict, layers: list[str], struct_blk: dict | None = None) -> str:
    out = [
        "\n========================= 手动模式 LLM 输入 =========================\n",
        f"segment_id: {seg['segment_id']}\n",
        f"chapter: {seg.get('chapter')}\n",
        f"section_type: {seg.get('section_type')}\n",
        f"context_prev: {seg.get('context_prev', '')[:200]}...\n",
        f"context_next: {seg.get('context_next', '')[:200]}...\n",
        "-------------------- 原文片段 begin --------------------\n",
        f"{seg.get('text_span', {}).get('text', '')}\n",
        "-------------------- 原文片段 end ----------------------\n",
        f"请按 close-reading-annotator SKILL.md 产出 layers={layers} 的整行 JSON"
        "（顶层 schema_version/segment_id + layers 内容）。\n",
    ]
    if "emotion" in layers:
        out.append(_emotion_manual_block(seg, struct_blk))
    out.append(
        "复制 JSON 后粘贴回脚本（粘贴完按 Ctrl+Z + 回车 [Windows] 或 Ctrl+D [Unix]）：\n"
        "====================================================================\n"
    )
    return "".join(out)


def _run_llm_external(cmd: str, seg: dict, layers: list[str], struct_blk: dict | None = None) -> dict:
    payload: dict = {
        "segment": seg,
        "request_layers": layers,
        "schema_version": SCHEMA_VERSION,
    }
    if "emotion" in layers:
        payload["structure_trigger_block"] = struct_blk  # 供外部 LLM 做 P4 触发判定
    # v2.7.0（T-013c 加固）：子进程统一 UTF-8（Windows 下 text=True 默认 GBK 解码，会因中文输出崩）
    # v2.7.0（T-013c 加固）：不用 shell=True——在 COMSPEC/默认 shell 为 PowerShell 的机器上，
    #        pwsh 会吞掉子进程 stdin（把 JSON 当命令解析），导致外部 LLM 收不到输入。
    #        shlex.split(posix=True)：双引号内反斜杠仅在 $ ` " \ 换行前转义，
    #        Windows 含空格路径用双引号包裹即可保留（建议路径用正斜杠，如 python tools/x.py）。
    # 外部 LLM 约定：stdin 收 UTF-8 JSON，stdout 返 UTF-8 JSON。
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    result = subprocess.run(
        shlex.split(cmd, posix=True),
        input=json.dumps(payload, ensure_ascii=False),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        shell=False,
    )
    if result.returncode != 0:
        err_txt = (result.stderr or "")[:1000]
        print(f"❌ LLM 外部命令失败 (exit={result.returncode})\nSTDERR: {err_txt}", file=sys.stderr)
        sys.exit(3)
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        out_txt = (result.stdout or "")[:800]
        print(f"❌ LLM 外部命令输出不是合法 JSON。前 800 字符:\n{out_txt}", file=sys.stderr)
        sys.exit(3)


def _run_llm_manual(seg: dict, layers: list[str], struct_blk: dict | None = None) -> dict:
    print(_manual_prompt(seg, layers, struct_blk), end="")
    try:
        raw = sys.stdin.read()
    except KeyboardInterrupt:
        print("\n🚫 中断", file=sys.stderr)
        sys.exit(4)
    if not raw.strip():
        print("❌ 没粘贴 JSON", file=sys.stderr)
        sys.exit(4)
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"❌ JSON 解析失败：{e}", file=sys.stderr)
        sys.exit(4)


def _append_jsonl(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def main() -> int:
    p = argparse.ArgumentParser(
        description="【精读批注 v2.7 Phase 2 / P4】单片段批注调度壳（手动模式或外部 LLM 注入）")
    p.add_argument("--segments", required=True, help="segments.jsonl 路径")
    p.add_argument("--doc-id", required=True, help="文档 ID")
    p.add_argument("--segment", required=True, help="segment_id（如 moon_sixpence_seg_0001）")
    p.add_argument("--layers", default="structure,interpretation,craft",
                   help="要跑的层，逗号分隔。默认三层全开；emotion（v2.7.0 P4 D19）需显式加入，"
                        "如 --layers emotion（将自动注入该段 D01/D04/D10 判定上下文）")
    p.add_argument("--checkpoint", default=None,
                   help="checkpoint.json 路径（默认为 <cwd>/<doc_id>_checkpoint.json）")
    p.add_argument("--output-dir", default=".",
                   help="layer JSONL 输出目录（默认当前）")
    p.add_argument("--llm-cmd", default=None,
                   help="外部 LLM 命令；未指定则进入手动粘贴模式")
    p.add_argument("--force", action="store_true",
                   help="忽略 checkpoint，强制重跑")
    args = p.parse_args()

    layers = [l.strip() for l in args.layers.split(",") if l.strip() in ALL_LAYERS]
    if not layers:
        print(f"❌ --layers 必须至少包含 {ALL_LAYERS} 之一", file=sys.stderr)
        return 2
    segs_path = Path(args.segments)
    if not segs_path.is_file():
        print(f"❌ segments 文件不存在：{segs_path}", file=sys.stderr)
        return 2
    out_dir = Path(args.output_dir)

    segs = _load_segments(segs_path)
    if args.segment not in segs:
        print(f"❌ segment_id={args.segment} 不在 {segs_path}", file=sys.stderr)
        return 2
    seg = segs[args.segment]

    # P4 情感层：读 structure.jsonl 该段 D01/D04/D10 作为触发判定上下文（无文件/行则 None）
    struct_blk = _load_structure_block(out_dir, args.doc_id, args.segment) if "emotion" in layers else None
    if "emotion" in layers:
        trig, notes = _trigger_notes(struct_blk)
        if trig:
            print(f"[P4] {args.segment} 触发命中：" + "；".join(notes))
        elif struct_blk is None:
            print(f"[P4] {args.segment} ⚠️ 找不到 structure 行，无法自动判定触发（请人工核对 P4 条件）")
        else:
            print(f"[P4] {args.segment} ⚠️ 未命中触发条件 1–3（intensity≥4 / D01 关键叙事 / D10 对话）"
                  "——如属『用户显式要求』（条件 4）可继续；否则建议跳段并登记 emotion_skipped")

    # checkpoint（v2.5.1：--checkpoint 路径优先，否则用 cwd；--dir 显式指定目录）
    base_dir = Path(args.checkpoint).parent if args.checkpoint else Path.cwd()
    ckpt_path = base_dir / f"{args.doc_id}_checkpoint.json"
    if not ckpt_path.is_file():
        print(f"⚠️ checkpoint 不存在：{ckpt_path}，将在首次完成后创建")

    for layer in layers:
        if not args.force and is_layer_completed(args.doc_id, args.segment, layer, base_dir):
            print(f"⏭ {args.segment} {layer} 已完成（--force 可强制重跑）")
            continue

        print(f"\n🚀 开始批注 {args.segment} layer={layer}")
        if args.llm_cmd:
            obj = _run_llm_external(args.llm_cmd, seg, [layer], struct_blk if layer == "emotion" else None)
        else:
            obj = _run_llm_manual(seg, [layer], struct_blk if layer == "emotion" else None)

        # 补齐行级元数据：text_span 供 D19.key_phrases 子串校验；segment_id/schema_version 供行级校验
        if "text_span" not in obj and seg.get("text_span"):
            obj["text_span"] = seg["text_span"]
        obj.setdefault("segment_id", args.segment)
        obj.setdefault("schema_version", SCHEMA_VERSION)

        # 校验
        tmp_json = Path(out_dir) / f".tmp_{args.segment}_{layer}.json"
        tmp_json.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
        val_cmd = [
            sys.executable, str(Path(__file__).parent / "validate_output.py"),
            "--json", str(tmp_json),
            "--layer-type", layer,
        ]
        # v2.7.0（T-013c 加固）：UTF-8 捕获子进程输出（Windows 默认 GBK 会崩，见 _run_llm_external 注释）
        proc = subprocess.run(
            val_cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        tmp_json.unlink(missing_ok=True)
        if proc.returncode != 0:
            print("❌ 校验失败，未落盘：")
            print(proc.stdout or "")
            print(proc.stderr or "")
            return 3

        # 落盘
        out_path = out_dir / f"{args.doc_id}_{layer}.jsonl"
        _append_jsonl(out_path, obj)
        # checkpoint（若不存在，初始化为 minimal，兼容结构字段即可）
        if load_checkpoint(args.doc_id, base_dir) is None:
            minimal = {
                "doc_id": args.doc_id,
                "schema_version": SCHEMA_VERSION,
                "total_segments": len(segs),
                "completed": [],
                "emotion_skipped": [],
                "cross_segment_completed": False,
                "merged_completed": False,
                "render_report_completed": False,
                "created_at": obj.get("_metadata", {}).get("generated_at", ""),
            }
            save_checkpoint(minimal, base_dir)
        mark_layer_completed(args.doc_id, args.segment, layer, base_dir)
        print(f"✅ {args.segment} {layer} 落盘 → {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
