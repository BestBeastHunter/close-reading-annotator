#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/annotate_segment.py — 批注调度壳 v2.7.0（工程化修复轮，决策 18）

⚠️ 本脚本是【调度壳】，不内嵌大模型调用。职责：
  1) 读取 segments.jsonl 中指定 segment_id 的原文片段；
  2) 读取 checkpoint 判断该 (segment, layer) 是否已完成；
  3) 从三种来源取得批注 JSON：手动粘贴 / 外部 LLM（--llm-cmd）/ 文件注入（--input-json）；
  4) 校验 → 校验失败自动 span 修复并重试（≤3 次，兑现文档承诺）→ 落盘 → 更新 checkpoint。

layer ∈ {structure, interpretation, craft, emotion}（v2.7.0 新增 emotion = P4 D19：
  自动读取 structure.jsonl 注入该段 D01/D04/D10 作为触发判定上下文；
  key_phrases 子串校验需要原文，脚本会从 segments 行补齐 text_span）。

工程化修复轮新增（v2.7 修复轮，决策 18）：
  - --input-json <file>：非交互注入。文件每行 = 一条最终批注行对象（或整体 JSON/JSONL）；
    行对象自带 segment_id（缺省用 --segment），层类型由内容自动推断
    （layers.structure / layers.interpretation / layers.emotion / 顶层 craft）。
    已完成 (segment, layer) 默认跳过（幂等续传），--force 强制重跑。
  - 校验失败自动重试 ≤3 次：craft 层若属 span 缺失/漂移，自动用 scripts/span_locator.py
    回算修正后重新校验（其余类型错误直接失败，不写 checkpoint）。
  - --all-pending：批量驱动。与 --llm-cmd 连用 = 对 checkpoint 未完成的 (segment, layer)
    逐个调用外部 LLM；与 --input-json 连用 = 只处理输入中未完成的行。
    批内单条失败记录 failed 清单并继续，不整批退出。
  - 落盘改为 upsert（同 segment 同层旧行被替换，不产生重复行），原子写。

用法：
  # 1) 单片段 + 单层（手动模式，打印 prompt 后粘贴 JSON）
  python scripts/annotate_segment.py --segments out/xxx_segments.jsonl \
      --doc-id xxx --segment xxx_seg_0001 --layers structure --output-dir out

  # 2) 非交互注入：Agent 生成整行批注 JSON 后喂入（推荐 Agent 工作流）
  python scripts/annotate_segment.py --segments out/xxx_segments.jsonl \
      --doc-id xxx --output-dir out --input-json batch_ann.jsonl

  # 3) 批量：未完成段全跑外部 LLM
  python scripts/annotate_segment.py --segments out/xxx_segments.jsonl \
      --doc-id xxx --layers structure --output-dir out \
      --all-pending --llm-cmd "python your_llm_wrapper.py"

  # 4) P4 情感层（自动注入该段 D01/D04/D10）
  python scripts/annotate_segment.py --segments out/xxx_segments.jsonl \
      --doc-id xxx --segment xxx_seg_0091 --layers emotion --output-dir out
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# v2.5.1 修复 #1：Windows GBK 控制台 UnicodeEncodeError（emoji 打印崩溃）
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# 导入同仓模块（checkpoint / span_locator / validate_output）
sys.path.insert(0, str(Path(__file__).parent))
from checkpoint import (  # noqa: E402
    is_layer_completed,
    load_checkpoint,
    mark_layer_completed,
    save_checkpoint,
)
from span_locator import repair_craft_row  # noqa: E402
from validate_output import (  # noqa: E402
    SUPPORTED_SCHEMA_VERSIONS,
    _call_validator,
)

SCHEMA_VERSION = "2.9.0"

ALL_LAYERS = ["structure", "interpretation", "craft", "emotion"]

# P4 触发条件 #2：D01 ∈ 关键叙事段（决策 17 / SKILL.md Phase 2.5）
TRIGGER_D01 = {"激励事件", "上升行动", "高潮", "转折"}

# 自动修复最多尝试的校验轮数（初始 1 次 + 修复后重试 ≤2 = 共 ≤3 次）
MAX_VALIDATE_ROUNDS = 3


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
        "要求：emotion 必须选自 references/emotion-lexicon.md 50 词白名单"
        "（无对应词→选最接近词 + expression.note 说明，不造新词）；"
    )
    lines.append(
        "结构按 templates/emotion-output.json：primary 必填；secondary/target/trigger/arc 无明确依据一律 "
        "null + 顶层 null_reasons，禁止编造情感对象与情感弧；"
    )
    lines.append("expression.key_phrases 每项必须是上文原文的子串（校验 error 级）。")
    return "\n".join(lines)


def _manual_prompt(seg: dict, layers: list[str], struct_blk: dict | None = None) -> str:
    # 修复（决策 18 遗漏①）：context_prev/next 不再硬截断到 200 字符——
    # preprocess 已按 --overlap-chars（默认 200，可配置更大）生成上下文锚点，
    # 这里完整呈现，避免丢跨段判断信息（D07 视角切换 / D06 埋设）；
    # 空锚点显式标注段首/段尾，不误加 "..."（原实现无论是否截断都打 ...，误导 LLM）。
    ctx_prev = (seg.get("context_prev") or "").strip()
    ctx_next = (seg.get("context_next") or "").strip()
    out = [
        "\n========================= 手动模式 LLM 输入 =========================\n",
        f"segment_id: {seg['segment_id']}\n",
        f"chapter: {seg.get('chapter')}\n",
        f"section_type: {seg.get('section_type')}\n",
        f"context_prev: {ctx_prev}\n" if ctx_prev else "context_prev:（无——本段位于章首/全书开头）\n",
        f"context_next: {ctx_next}\n" if ctx_next else "context_next:（无——本段位于章尾/全书结尾）\n",
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


# ---------------- 层识别 / 幂等落盘 / 校验+修复 ----------------

def _resolve_layer(obj: dict) -> str | None:
    """从批注行对象内容推断层类型（对齐 validate_output._call_validator 的 auto 启发）。"""
    if not isinstance(obj, dict):
        return None
    layers = obj.get("layers")
    if isinstance(layers, dict):
        for layer in ALL_LAYERS:
            if layers.get(layer) is not None:
                return layer
    if obj.get("craft") is not None:
        return "craft"
    if obj.get("emotion") is not None:
        return "emotion"
    return None


def _pad_metadata(obj: dict, seg: dict) -> None:
    """补齐行级元数据：text_span 供子串校验；segment_id / schema_version 供行级校验。"""
    if "text_span" not in obj and seg.get("text_span"):
        obj["text_span"] = seg["text_span"]
    obj.setdefault("segment_id", seg["segment_id"])
    obj.setdefault("schema_version", SCHEMA_VERSION)


def _upsert_jsonl(path: Path, segment_id: str, obj: dict) -> None:
    """层 JSONL 幂等写入：同 segment 同层旧行被替换（force 重跑不产生重复行），原子写。"""
    rows: list[dict] = []
    if path.is_file():
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if row.get("segment_id") != segment_id:
                    rows.append(row)
    rows.append(obj)
    tmp = path.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    tmp.replace(path)


def _validate_obj(obj: dict, layer: str) -> tuple[list[str], list[str]]:
    """行级校验（同 validate_output 口径：_call_validator + schema_version 白名单）。"""
    errs, warns = _call_validator(obj, layer)
    sv = obj.get("schema_version")
    if sv not in SUPPORTED_SCHEMA_VERSIONS:
        errs.insert(0, f"schema_version={sv!r} 不在允许集合 {sorted(SUPPORTED_SCHEMA_VERSIONS)} 内")
    return errs, warns


def _commit_with_retry(seg: dict, layer: str, obj: dict, auto_fix: bool = True) -> tuple[bool, str]:
    """校验（失败自动 span 修复重试 ≤3 轮）。返回 (ok, 说明文本)。

    说明文本供调用方打印；失败时内容包含最后一次校验错误详情。
    落盘动作由调用方（_commit_after_validate）在成功返回后执行。

    v3.8.1：新增 auto_fix 参数，控制 craft 层校验失败时是否自动修复 span/引文。
    """
    # 校验 + 自动修复循环
    last_errs: list[str] = []
    last_warns: list[str] = []
    repaired_once = False
    for attempt in range(1, MAX_VALIDATE_ROUNDS + 1):
        errs, warns = _validate_obj(obj, layer)
        last_errs, last_warns = errs, warns
        if not errs:
            msg = (
                f"✅ 校验通过（attempt {attempt}）"
                + (f"，自动修复 span {repaired_once} 条后通过" if repaired_once else "")
            )
            return True, msg
        # 仅 craft 层可自动修复（span 缺失/漂移类）；其余层不尝试修复
        if layer == "craft" and auto_fix:
            changed, unmatched, warnings = repair_craft_row(obj)
            if changed:
                repaired_once = True
                print(f"  ↻ attempt {attempt} 校验失败 → span 自动回算修正 {changed} 条，重试")
                for w in warnings:
                    print(f"    ⚠ {w}")
                continue
        break
    detail = "\n".join(f"   ✖ {e}" for e in last_errs) or "(无 error 明细)"
    warn_detail = "\n".join(f"   ⚠ {w}" for w in last_warns)
    return False, f"❌ 校验未通过（尝试 {MAX_VALIDATE_ROUNDS} 轮）:\n{detail}\n{warn_detail}".rstrip()


def _write_layer(out_dir: Path, doc_id: str, layer: str, obj: dict) -> Path:
    path = out_dir / f"{doc_id}_{layer}.jsonl"
    _upsert_jsonl(path, obj["segment_id"], obj)
    return path


def _append_checkpoint_created(segs: dict, args, base_dir: Path) -> None:
    """首次落盘前 checkpoint 不存在 → 初始化 minimal（兼容结构字段）。"""
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
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
        save_checkpoint(minimal, base_dir)


# ---------------- 输入加载 ----------------

def _load_input_objects(path: Path) -> list[dict]:
    """读取 --input-json：支持单个 JSON 对象、JSON 数组、或 JSONL（每行一个批注对象）。"""
    text = path.read_text(encoding="utf-8")
    text = text.strip()
    if not text:
        return []
    try:
        data = json.loads(text)
        if isinstance(data, list):
            return [d for d in data if isinstance(d, dict)]
        if isinstance(data, dict):
            return [data]
        print("❌ --input-json 顶层必须是 object 或 array", file=sys.stderr)
        return []
    except json.JSONDecodeError:
        pass
    # 按 JSONL 逐行解析
    items: list[dict] = []
    for i, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as e:
            print(f"⚠️ --input-json 第 {i} 行解析失败，跳过：{e}", file=sys.stderr)
            continue
        if isinstance(obj, dict):
            items.append(obj)
    return items


# ---------------- main ----------------

def main() -> int:
    p = argparse.ArgumentParser(
        description="【精读批注 v2.7 工程化修复轮】批注调度壳（手动 / --llm-cmd / --input-json / --all-pending）")
    p.add_argument("--segments", required=True, help="segments.jsonl 路径")
    p.add_argument("--doc-id", required=True, help="文档 ID")
    p.add_argument("--segment", default=None,
                   help="segment_id（如 moon_sixpence_seg_0001）。单段模式需要；批量模式（--input-json 自带 / --all-pending）可省略")
    p.add_argument("--layers", default="structure,interpretation,craft",
                   help="要跑的层，逗号分隔。默认三层全开；emotion（v2.7.0 P4 D19）需显式加入")
    p.add_argument("--checkpoint", default=None,
                   help="checkpoint.json 路径（默认为 <cwd>/<doc_id>_checkpoint.json）")
    p.add_argument("--output-dir", default=".",
                   help="layer JSONL 输出目录（默认当前）")
    p.add_argument("--llm-cmd", default=None,
                   help="外部 LLM 命令；未指定则进入手动粘贴模式（单段模式）")
    p.add_argument("--input-json", default=None,
                   help="批注结果文件（单 JSON / JSON 数组 / JSONL）。非交互注入：行对象自带 segment_id，"
                        "层类型自动推断；已完成 (segment, layer) 默认跳过")
    p.add_argument("--all-pending", action="store_true",
                   help="批量模式：处理 checkpoint 未完成的 (segment, layer)。需与 --llm-cmd 或 --input-json 连用")
    p.add_argument("--force", action="store_true",
                   help="忽略 checkpoint，强制重跑（层 JSONL 幂等 upsert，不产生重复行）")
    p.add_argument("--auto-fix", dest="auto_fix", action="store_true", default=True,
                   help="craft 层校验失败时自动修复 span/引文（v3.8.1 默认开启）")
    p.add_argument("--no-auto-fix", dest="auto_fix", action="store_false",
                   help="关闭 craft 层自动修复（校验失败直接退出）")
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
    out_dir.mkdir(parents=True, exist_ok=True)

    segs = _load_segments(segs_path)
    seg_ids: list[str] = list(segs.keys())

    # checkpoint 定位（v2.5.1：--checkpoint 路径优先，否则 cwd）
    base_dir = Path(args.checkpoint).parent if args.checkpoint else Path.cwd()

    def ensure_ckpt():
        if load_checkpoint(args.doc_id, base_dir) is None:
            _append_checkpoint_created(segs, args, base_dir)

    failed: list[tuple[str, str, str]] = []  # (segment_id, layer, reason)

    # ---------- 模式 A：批量驱动 ----------
    if args.all_pending:
        if not args.input_json and not args.llm_cmd:
            print("❌ --all-pending 需要 --llm-cmd（外部 LLM）或 --input-json（文件注入）作为批注来源",
                  file=sys.stderr)
            return 2
        ensure_ckpt()
        scope_ids = [args.segment] if args.segment else seg_ids
        for sid in scope_ids:
            if sid not in segs:
                print(f"⚠️ segment_id={sid} 不在 segments 中，跳过", file=sys.stderr)
                continue
            seg = segs[sid]
            pending_layers = [
                l for l in layers
                if args.force or not is_layer_completed(args.doc_id, sid, l, base_dir)
            ]
            if not pending_layers:
                continue
            for layer in pending_layers:
                struct_blk = _load_structure_block(out_dir, args.doc_id, sid) if layer == "emotion" else None
                try:
                    obj = _run_llm_external(args.llm_cmd, seg, [layer], struct_blk)
                except SystemExit:
                    failed.append((sid, layer, "外部 LLM 调用失败（详见上方）"))
                    continue
                ok, msg = _commit_after_validate(seg, layer, obj, out_dir, args, base_dir)
                if ok:
                    print(f"✅ {sid} {layer} 落盘")
                else:
                    failed.append((sid, layer, msg))
        # 汇总
        if failed:
            print(f"\n⚠️ 批量完成：{len(failed)} 条失败（未写入 checkpoint，可 --resume 重跑）")
            for sid, layer, reason in failed[:20]:
                print(f"   ✖ {sid} {layer}: {reason[:200]}")
            return 1
        print("\n✅ 批量全部完成")
        return 0

    # ---------- 模式 B：--input-json 非交互注入 ----------
    if args.input_json:
        inp = Path(args.input_json)
        if not inp.is_file():
            print(f"❌ --input-json 文件不存在：{inp}", file=sys.stderr)
            return 2
        ensure_ckpt()
        objects = _load_input_objects(inp)
        if not objects:
            print("❌ --input-json 无可解析的批注对象", file=sys.stderr)
            return 2
        for obj in objects:
            sid = obj.get("segment_id") or args.segment
            if not sid or sid not in segs:
                print(f"⚠️ 行对象缺少有效 segment_id（有 {obj.get('segment_id')!r}），跳过", file=sys.stderr)
                continue
            layer = _resolve_layer(obj)
            if layer is None:
                print(f"⚠️ {sid} 行对象无法推断层类型（需 layers.<layer> 或顶层 craft），跳过",
                      file=sys.stderr)
                continue
            if layer not in layers:
                print(f"⚠️ {sid} 推断层 {layer} 不在 --layers {layers} 中，跳过", file=sys.stderr)
                continue
            if not args.force and is_layer_completed(args.doc_id, sid, layer, base_dir):
                print(f"⏭ {sid} {layer} 已完成（--force 可重跑）")
                continue
            seg = segs[sid]
            _pad_metadata(obj, seg)
            ok, msg = _commit_after_validate(seg, layer, obj, out_dir, args, base_dir)
            if ok:
                print(f"✅ {sid} {layer} 落盘 → {out_dir / f'{args.doc_id}_{layer}.jsonl'}")
            else:
                failed.append((sid, layer, msg))
                print(msg)
        if failed:
            print(f"\n⚠️ 注入完成：{len(failed)}/{len(objects)} 条失败（已打印明细）")
            return 1
        print("\n✅ 注入全部落盘")
        return 0

    # ---------- 模式 C：单段（手动 / 外部 LLM）----------
    if not args.segment:
        print("❌ 请指定 --segment（单段模式）或使用 --input-json / --all-pending（批量模式）",
              file=sys.stderr)
        return 2
    if args.segment not in segs:
        print(f"❌ segment_id={args.segment} 不在 {segs_path}", file=sys.stderr)
        return 2
    seg = segs[args.segment]
    ensure_ckpt()

    for layer in layers:
        if not args.force and is_layer_completed(args.doc_id, args.segment, layer, base_dir):
            print(f"⏭ {args.segment} {layer} 已完成（--force 可强制重跑）")
            continue
        print(f"\n🚀 开始批注 {args.segment} layer={layer}")
        struct_blk = _load_structure_block(out_dir, args.doc_id, args.segment) if layer == "emotion" else None
        if args.llm_cmd:
            obj = _run_llm_external(args.llm_cmd, seg, [layer], struct_blk)
        else:
            obj = _run_llm_manual(seg, [layer], struct_blk)
        _pad_metadata(obj, seg)
        ok, msg = _commit_after_validate(seg, layer, obj, out_dir, args, base_dir)
        if ok:
            print(f"✅ {args.segment} {layer} 落盘 → {out_dir / f'{args.doc_id}_{layer}.jsonl'}")
        else:
            print(msg)
            return 3
    return 0


def _commit_after_validate(
    seg: dict,
    layer: str,
    obj: dict,
    out_dir: Path,
    args: argparse.Namespace,
    base_dir: Path,
) -> tuple[bool, str]:
    """统一提交路径：校验（自动修复重试 ≤3）→ 落盘 → checkpoint 登记。返回 (ok, msg)。"""
    ok, msg = _commit_with_retry(seg, layer, obj, auto_fix=getattr(args, "auto_fix", True))
    if not ok:
        return False, msg
    out_path = _write_layer(out_dir, args.doc_id, layer, obj)
    mark_layer_completed(args.doc_id, obj["segment_id"], layer, base_dir)
    return True, f"✅ 已落盘 → {out_path}"


if __name__ == "__main__":
    sys.exit(main())
