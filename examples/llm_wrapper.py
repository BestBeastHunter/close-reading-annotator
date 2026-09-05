#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
examples/llm_wrapper.py — --llm-cmd 协议官方参考模板（决策 18 遗漏②补齐）

背景：SKILL.md / run_pipeline.py / annotate_segment.py 长期引用「python 你的llm_wrapper.py」
但包内从无官方实现，示例路径是虚构的。本文件即该协议的最小可运行参考实现。

──────────────────────────────────────────────────────────────────────────
--llm-cmd 协议（annotate_segment.py:_run_llm_external 定义，本文件严格对齐）：
  stdin   ← 一行动 JSON：
            {"segment": {…segments.jsonl 行…},
             "request_layers": ["structure", …],
             "schema_version": "2.9.0",
             "structure_trigger_block": {D01,D04,D10} | null}   # 仅 emotion 层注入
  stdout  → 一行动 JSON（批注行对象）：
            {schema_version, annotation_id, document_id, segment_id, chapter,
             section_type, text_span, <layer 内容>, confidence, null_reasons,
             alternatives, status, _metadata}
  退出码 0 = 成功；非 0 = 该条失败（annotate 记入 failed，不写 checkpoint）。
──────────────────────────────────────────────────────────────────────────

用法：
  # 1) mock 冒烟（不调任何 API，确定性产出合法 structure 行——跑通链路用）：
  python examples/llm_wrapper.py --mock
  #    用 --llm-cmd 实测：annotate_segment --all-pending 时它会按 request_layers 返回
  #    mock 只支持 structure；其余层请接真实模型（见下）。

  # 2) 接入真实模型（替换下方 _call_model() 实现，见文件内 TODO）：
  #    python examples/llm_wrapper.py
  #    建议设置环境变量：CRA_WRAPPER_MODEL / CRA_WRAPPER_BASE_URL / CRA_WRAPPER_API_KEY

零第三方依赖（stdlib urllib 即可接 OpenAI 兼容 /api/chat）。跨平台。
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# v2.5.1 修复 #1：Windows GBK 控制台 UnicodeEncodeError
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

PACKAGE_ROOT = Path(__file__).resolve().parent.parent  # skill 包根
TEMPLATES_DIR = PACKAGE_ROOT / "templates"
SCHEMA_VERSION = "2.9.0"


# ---------------- 批注行构造（从模板骨架填充段级字段） ----------------

def _layer_from_template(payload: dict, layer: str) -> dict:
    """读 templates/<layer>-output.json 骨架，把段级占位字段换成真实值。

    骨架本身是经 validate_output.py 0 error 校验的模板；此处只替换
    segment_id/document_id/chapter/section_type/text_span/annotation_id
    /_metadata，层内容保持模板默认（mock 模式：链路优先于语义精度）。
    """
    tpl_path = TEMPLATES_DIR / f"{layer}-output.json"
    if not tpl_path.is_file():
        raise FileNotFoundError(f"模板缺失：{tpl_path}")
    with tpl_path.open("r", encoding="utf-8") as f:
        row = json.load(f)

    seg = payload.get("segment") or {}
    seg_id = seg.get("segment_id") or ""
    doc_id = seg.get("document_id") or payload.get("document_id") or seg_id.split("_seg_")[0]
    text_span = seg.get("text_span") or {}

    row.pop("_comment", None)
    row["schema_version"] = payload.get("schema_version", SCHEMA_VERSION)
    row["annotation_id"] = f"{seg_id}_{layer}_ann_0"
    row["document_id"] = doc_id
    row["segment_id"] = seg_id
    row["chapter"] = seg.get("chapter")
    row["section_type"] = seg.get("section_type") or "body"
    row["text_span"] = text_span  # 段级真实坐标 + 原文（子串校验依赖它）
    row["_metadata"] = {
        "skill_version": SCHEMA_VERSION,
        "model": "llm_wrapper_mock",
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "layer": layer,
        "annotation_pass": "P1" if layer == "structure" else "P2",
    }
    return row


def _mock_structure_row(payload: dict) -> dict:
    """确定性产出一条合法 structure 行（语义取模板默认，仅供链路冒烟）。"""
    return _layer_from_template(payload, "structure")


# ---------------- 真实模型接入点（TODO：替换为你自己的调用） ----------------

def _call_model(payload: dict) -> dict:
    """把 payload（含原文 segment + request_layers）交给真实 LLM，返回批注行对象。

    TODO(接入你的模型)：替换本函数实现。骨架参考——
      1. 用 payload["segment"]["text_span"]["text"] 取原文；
      2. 把 SKILL.md（或本包 references/schema.md + templates/<layer>-output.json）
         拼进 system prompt，要求输出整行批注 JSON；
      3. 调你的 API（OpenAI 兼容 /api/chat 可直接用 urllib，零依赖）；
      4. 解析返回 JSON 并 return。

    未接入前：本函数不直达，mock 模式由 main() 拦截（structure），
    其余层走到这里打印指引后以非 0 退出，annotate 会记为 failed。
    """
    seg_id = (payload.get("segment") or {}).get("segment_id") or "?"
    layers = payload.get("request_layers") or []
    print(
        f"⚠️ examples/llm_wrapper.py 未接入真实模型：{seg_id} layers={layers} 无法产出。\n"
        "   请打开本文件编辑 _call_model()（或仅用 --mock 跑 structure 冒烟）。",
        file=sys.stderr,
    )
    sys.exit(3)


# ---------------- main ----------------

def main() -> int:
    mock = "--mock" in sys.argv[1:]
    raw = sys.stdin.read()
    if not raw.strip():
        print("❌ 无 stdin 输入（协议：一行动 JSON payload）", file=sys.stderr)
        return 2
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"❌ stdin 不是合法 JSON：{e}", file=sys.stderr)
        return 2
    if not isinstance(payload, dict):
        print("❌ payload 必须是 object", file=sys.stderr)
        return 2

    layers = payload.get("request_layers") or []
    if not layers:
        print("❌ payload.request_layers 为空", file=sys.stderr)
        return 2

    # 一次调用只产一个 layer（annotate 调度壳按 layer 逐次调用）
    layer = layers[0]

    if mock:
        if layer != "structure":
            print(
                f"⚠️ mock 只支持 structure（本次请求 {layer}）。请接真实模型。",
                file=sys.stderr,
            )
            return 3
        row = _mock_structure_row(payload)
    else:
        row = _call_model(payload)

    # stdout 输出最终批注行（annotate_segment 会做校验/落盘/checkpoint）
    sys.stdout.write(json.dumps(row, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
