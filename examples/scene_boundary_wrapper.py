#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
examples/scene_boundary_wrapper.py — LumberChunker 场景边界判断官方 wrapper（v3.8.6 新增，T-059）

用途：读取粗切 segments.jsonl，逐对调用 LLM 判断相邻段之间是否是场景边界，输出 scene_boundary.json。
这是 SKILL.md Phase 1.5a 的官方实现模板，Agent 不需要自己写批量调用脚本。

零第三方依赖：仅 Python 3.8+ 标准库（urllib 调用 OpenAI 兼容 API）。

用法：
  # 1. 设置 API 环境变量（兼容 OpenAI / DeepSeek / 任何 OpenAI 兼容接口）
  export SCENE_BOUNDARY_API_KEY="your-api-key"
  export SCENE_BOUNDARY_BASE_URL="https://api.deepseek.com/v1"  # 可选，默认 https://api.openai.com/v1
  export SCENE_BOUNDARY_MODEL="deepseek-chat"  # 可选，默认 gpt-4o-mini

  # 2. 运行 wrapper
  python examples/scene_boundary_wrapper.py \
    --segments outputs/annotations/moon_sixpence/moon_sixpence_segments.jsonl \
    --output outputs/annotations/moon_sixpence/scene_boundary.json \
    --doc-id moon_sixpence

  # 3. 用 reshape_segments.py 重排
  python scripts/reshape_segments.py \
    --segments outputs/annotations/moon_sixpence/moon_sixpence_segments.jsonl \
    --boundaries outputs/annotations/moon_sixpence/scene_boundary.json \
    --original <原文文件路径> \
    --doc-id moon_sixpence \
    --output-dir outputs/annotations/moon_sixpence/

选项：
  --dry-run    只打印将调用的 LLM 对数，不实际调用（用于测试）
  --max-pairs  最多处理多少对（用于测试，默认全部）
  --retries    单对失败重试次数（默认 3）
"""

import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# LumberChunker 场景边界判断 Prompt（与 SKILL.md Phase 1.5a 一致）
SCENE_BOUNDARY_PROMPT = """你是叙事场景边界检测专家。请判断以下两个相邻叙事段落之间是否存在"场景边界"（即两者是否属于同一个连续场景）。

【段落 N】{seg_n_text}

【段落 N+1】{seg_n1_text}

判断维度（满足任一即视为场景边界）：
1. 地点变化：场景从一个地点转到另一个地点
2. 时间跳跃：时间发生明显跳跃（非连续流逝）
3. 视角切换：叙述视角或聚焦人物发生切换
4. 主题断裂：叙事主题或情绪基调发生明显转折

输出 JSON（严格格式，不要额外文字）：
{{
  "between_segment": "{seg_n_id}",
  "and_segment": "{seg_n1_id}",
  "is_scene_boundary": true/false,
  "boundary_type": "location_change" | "time_jump" | "pov_switch" | "thematic_break" | "continuous",
  "confidence": 0.0-1.0,
  "reason": "一句话说明判断依据（is_scene_boundary=false 时写'同一场景，连续叙事'）"
}}"""


def load_segments(path: Path) -> list[dict]:
    """读取 segments.jsonl，返回 segment 列表"""
    segments = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                segments.append(json.loads(line))
    return segments


def call_llm(prompt: str, api_key: str, base_url: str, model: str, retries: int = 3) -> dict:
    """调用 OpenAI 兼容 API，返回解析后的 JSON"""
    url = f"{base_url.rstrip('/')}/chat/completions"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )

    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                content = result["choices"][0]["message"]["content"]
                return json.loads(content)
        except (urllib.error.URLError, json.JSONDecodeError, KeyError) as e:
            if attempt < retries - 1:
                wait = 2 ** attempt
                print(f"  ⚠️ 调用失败（{e}），{wait}秒后重试（{attempt+1}/{retries}）...")
                time.sleep(wait)
            else:
                raise


def main() -> int:
    p = argparse.ArgumentParser(description="LumberChunker 场景边界判断官方 wrapper（v3.8.6）")
    p.add_argument("--segments", required=True, help="粗切 segments.jsonl 路径")
    p.add_argument("--output", required=True, help="输出 scene_boundary.json 路径")
    p.add_argument("--doc-id", required=True, help="文档 ID")
    p.add_argument("--dry-run", action="store_true", help="只打印将调用的对数，不实际调用")
    p.add_argument("--max-pairs", type=int, default=None, help="最多处理多少对（默认全部）")
    p.add_argument("--retries", type=int, default=3, help="单对失败重试次数（默认 3）")
    p.add_argument("--context-chars", type=int, default=500, help="每段取前多少字符作为判断上下文（默认 500）")
    args = p.parse_args()

    # 读取环境变量
    api_key = os.environ.get("SCENE_BOUNDARY_API_KEY", "")
    base_url = os.environ.get("SCENE_BOUNDARY_BASE_URL", "https://api.openai.com/v1")
    model = os.environ.get("SCENE_BOUNDARY_MODEL", "gpt-4o-mini")

    if not args.dry_run and not api_key:
        print("[scene_boundary] ❌ 错误：未设置 SCENE_BOUNDARY_API_KEY 环境变量", file=sys.stderr)
        print("  请先设置：export SCENE_BOUNDARY_API_KEY='your-api-key'", file=sys.stderr)
        return 2

    # 读取 segments
    seg_path = Path(args.segments)
    if not seg_path.is_file():
        print(f"[scene_boundary] ❌ 错误：找不到 segments 文件 {seg_path}", file=sys.stderr)
        return 2
    segments = load_segments(seg_path)
    print(f"[scene_boundary] 读取到 {len(segments)} 个粗切段")

    # 生成相邻对
    pairs = []
    for i in range(len(segments) - 1):
        pairs.append((segments[i], segments[i + 1]))
    print(f"[scene_boundary] 将判断 {len(pairs)} 对相邻段的场景边界")

    if args.max_pairs:
        pairs = pairs[: args.max_pairs]
        print(f"[scene_boundary] 限制为前 {args.max_pairs} 对")

    if args.dry_run:
        print("[scene_boundary] ✅ dry-run 模式，不实际调用 LLM")
        print(f"  将调用 {len(pairs)} 次 LLM")
        print(f"  API: {base_url}")
        print(f"  Model: {model}")
        return 0

    # 逐对调用 LLM
    boundaries = []
    for idx, (seg_n, seg_n1) in enumerate(pairs):
        seg_n_text = seg_n.get("text_span", {}).get("text", "")[: args.context_chars]
        seg_n1_text = seg_n1.get("text_span", {}).get("text", "")[: args.context_chars]
        prompt = SCENE_BOUNDARY_PROMPT.format(
            seg_n_text=seg_n_text,
            seg_n1_text=seg_n1_text,
            seg_n_id=seg_n.get("segment_id", ""),
            seg_n1_id=seg_n1.get("segment_id", ""),
        )
        print(f"  [{idx+1}/{len(pairs)}] 判断 {seg_n.get('segment_id')} ↔ {seg_n1.get('segment_id')}...", end=" ")
        try:
            result = call_llm(prompt, api_key, base_url, model, args.retries)
            boundaries.append(result)
            is_boundary = result.get("is_scene_boundary", False)
            btype = result.get("boundary_type", "unknown")
            print(f"{'🔴 边界' if is_boundary else '🟢 连续'} ({btype})")
        except Exception as e:
            print(f"❌ 失败: {e}")
            # 失败时默认连续（保守策略，不切分）
            boundaries.append({
                "between_segment": seg_n.get("segment_id", ""),
                "and_segment": seg_n1.get("segment_id", ""),
                "is_scene_boundary": False,
                "boundary_type": "continuous",
                "confidence": 0.0,
                "reason": f"LLM调用失败，默认连续（错误: {e}）",
            })

    # 输出 scene_boundary.json
    output = {
        "schema_version": "3.5.0",
        "document_id": args.doc_id,
        "generator": "scene_boundary_wrapper.py v3.8.6",
        "total_pairs": len(pairs),
        "boundary_count": sum(1 for b in boundaries if b.get("is_scene_boundary")),
        "boundaries": boundaries,
    }
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\n[scene_boundary] ✅ 完成！输出: {out_path.resolve()}")
    print(f"  总对数: {len(pairs)}，边界数: {output['boundary_count']}，连续数: {len(pairs) - output['boundary_count']}")
    print(f"  下一步: python scripts/reshape_segments.py --segments <segments.jsonl> --boundaries {out_path} --original <原文> --doc-id {args.doc_id} --output-dir <out>")
    return 0


if __name__ == "__main__":
    sys.exit(main())
