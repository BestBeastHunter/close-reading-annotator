#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/quality_gate.py — 数据质量看门狗（v3.4.0 / T-033-L1 / ADR-014）

在粗切分之前对原始文本做硬门槛检测，防止 LLM 精读"垃圾输入"。
纯 stdlib，零依赖。

检测维度：
  1. 中文字符占比（chinese_ratio）—— <0.8 视为严重污染（全是英文乱码或 HTML 标签）
  2. 引号闭合率（quote_balance）—— 左右引号数量差过大 = 对话被截断
  3. 乱码/特殊符号密度（garbage_density）—— � / &nbsp; / \\x00 / \\ufffd 等
  4. 段落结构稳定性（paragraph_stability）—— 平均段落长度 / 标准差 / 空段落比例
  5. 重复性检测（repetition_score）—— 连续重复段落（网站水印/重复粘贴）

输出：quality_report.json
  - overall_score: 0-100
  - verdict: "pass" / "warn" / "fail"
  - metrics: 各项指标详情
  - recommendations: 修复建议

用法：
  python scripts/quality_gate.py --input novel.txt --out quality_report.json
  python scripts/quality_gate.py --input segments.jsonl   # 支持 segments.jsonl（读 text_span.text）
"""

from __future__ import annotations

import argparse
import io
import json
import re
import sys
from pathlib import Path
from statistics import mean, pstdev

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

SCHEMA_VERSION = "3.4.0"

# 中文字符 Unicode 范围（CJK 统一表意文字 + 扩展A + 标点）
CJK_RE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf\u3000-\u303f\uff00-\uffef]")
# 乱码/特殊符号
GARBAGE_RE = re.compile(r"[\ufffd\u0000-\u0008\u000b\u000c\u000e-\u001f]|&nbsp;|&amp;|&lt;|&gt;|<br\s*/?>|<p\s*>|</p>|<div[^>]*>|</div>", re.IGNORECASE)
# 左右引号（中文 + 英文）
LEFT_QUOTES = "「『“‘"  # v3.8.8 T-069: 仅中文左引号，英文引号单独统计
RIGHT_QUOTES = "」』”’"  # v3.8.8 T-069: 仅中文右引号


def load_text(input_path: Path) -> str:
    """读取输入：.txt 直接读；.jsonl 读 segments 的 text_span.text 拼接。"""
    if input_path.suffix.lower() == ".jsonl":
        texts: list[str] = []
        with io.open(input_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                # 兼容多种字段名
                text = (
                    obj.get("text_span", {}).get("text")
                    or obj.get("text")
                    or obj.get("content")
                    or ""
                )
                if text:
                    texts.append(text)
        return "\n\n".join(texts)
    else:
        return io.open(input_path, encoding="utf-8", errors="replace").read()


def check_chinese_ratio(text: str, threshold: float) -> dict:
    """中文字符占比。"""
    total = len(text)
    if total == 0:
        return {"score": 0, "ratio": 0.0, "status": "fail", "detail": "文本为空"}
    chinese = len(CJK_RE.findall(text))
    ratio = chinese / total
    if ratio >= threshold:
        status, score = "pass", 100
    elif ratio >= threshold * 0.7:
        status, score = "warn", int(ratio / threshold * 80)
    else:
        status, score = "fail", int(ratio / threshold * 40)
    return {
        "score": max(0, min(100, score)),
        "ratio": round(ratio, 4),
        "chinese_chars": chinese,
        "total_chars": total,
        "status": status,
        "threshold": threshold,
    }


def check_quote_balance(text: str, threshold: float) -> dict:
    """引号闭合率：左右引号数量差 / 左引号总数。"""
    # v3.8.8 T-069: 英文引号 " 和 ' 没有左右之分，单独统计总数（不参与左右平衡）
    english_quotes = sum(text.count(c) for c in "\"'")
    left = sum(text.count(c) for c in LEFT_QUOTES)
    right = sum(text.count(c) for c in RIGHT_QUOTES)
    if left == 0 and right == 0:
        return {"score": 100, "status": "pass", "detail": "无引号（非对话体）",
                "left": 0, "right": 0, "imbalance_ratio": 0.0}
    total_quotes = left + right
    diff = abs(left - right)
    ratio = diff / max(total_quotes, 1)
    if ratio <= threshold:
        status, score = "pass", 100
    elif ratio <= threshold * 2:
        status, score = "warn", int((1 - ratio) * 80)
    else:
        status, score = "fail", int((1 - ratio) * 50)
    return {
        "score": max(0, min(100, score)),
        "left_quotes": left,
        "right_quotes": right,
        "imbalance_ratio": round(ratio, 4),
        "status": status,
        "threshold": threshold,
    }


def check_garbage(text: str) -> dict:
    """乱码/特殊符号密度。"""
    total = len(text)
    if total == 0:
        return {"score": 0, "status": "fail", "detail": "文本为空"}
    matches = GARBAGE_RE.findall(text)
    # matches 可能是 tuple（正则有分组），统一计数
    garbage_count = sum(1 for m in matches if m)
    density = garbage_count / total
    if density <= 0.001:
        status, score = "pass", 100
    elif density <= 0.01:
        status, score = "warn", int((1 - density * 50) * 80)
    else:
        status, score = "fail", int(max(0, (1 - density * 10) * 40))
    return {
        "score": max(0, min(100, score)),
        "garbage_count": garbage_count,
        "density": round(density, 6),
        "status": status,
        "samples": matches[:5] if matches else [],
    }


def check_paragraph_structure(text: str) -> dict:
    """段落结构稳定性：按空行分段，计算平均长度/标准差/空段落比例。"""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if not paragraphs:
        return {"score": 0, "status": "fail", "detail": "无有效段落"}
    lengths = [len(p) for p in paragraphs]
    avg_len = mean(lengths)
    std_len = pstdev(lengths) if len(lengths) > 1 else 0
    cv = std_len / avg_len if avg_len > 0 else 0  # 变异系数
    # 极短段落（<10字）比例
    very_short = sum(1 for l in lengths if l < 10)
    short_ratio = very_short / len(lengths)
    # 评分：变异系数适中（0.3-1.0）为佳，过大=结构不稳定，过小=可能全是短行
    # 段落数 <=2 时无法判断结构稳定性，给 warn（不 fail）
    if len(lengths) <= 2:
        status, score = "warn", 75
    elif 0.2 <= cv <= 1.2 and short_ratio < 0.3:
        status, score = "pass", 100
    elif cv <= 2.0 and short_ratio < 0.5:
        status, score = "warn", 70
    else:
        status, score = "fail", 40
    return {
        "score": score,
        "paragraph_count": len(paragraphs),
        "avg_length": round(avg_len, 1),
        "std_length": round(std_len, 1),
        "cv": round(cv, 3),
        "very_short_ratio": round(short_ratio, 3),
        "status": status,
    }


def check_repetition(text: str) -> dict:
    """重复性检测：连续重复段落 + 高频 N-gram（简化版：5-gram 重复率）。"""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if not paragraphs:
        return {"score": 0, "status": "fail", "detail": "无有效段落"}
    # 连续完全重复段落
    consecutive_dupes = 0
    for i in range(1, len(paragraphs)):
        if paragraphs[i] == paragraphs[i - 1] and len(paragraphs[i]) > 20:
            consecutive_dupes += 1
    # 5-gram 字符级重复率（采样前 5000 字符避免太慢）
    sample = text[:5000]
    n = 5
    if len(sample) <= n:
        ngram_dup_ratio = 0.0
    else:
        grams = [sample[i:i+n] for i in range(len(sample) - n + 1)]
        unique = len(set(grams))
        ngram_dup_ratio = 1 - unique / len(grams)
    if consecutive_dupes == 0 and ngram_dup_ratio < 0.3:
        status, score = "pass", 100
    elif consecutive_dupes <= 2 and ngram_dup_ratio < 0.5:
        status, score = "warn", 70
    else:
        status, score = "fail", 40
    return {
        "score": score,
        "consecutive_duplicate_paragraphs": consecutive_dupes,
        "ngram_duplicate_ratio": round(ngram_dup_ratio, 3),
        "status": status,
    }


def build_recommendations(metrics: dict) -> list[str]:
    """根据各项指标状态生成修复建议。"""
    recs: list[str] = []
    if metrics["chinese_ratio"]["status"] == "fail":
        recs.append("中文字符占比过低：检查源文件是否为英文/乱码/HTML 标签，需重新获取干净文本")
    elif metrics["chinese_ratio"]["status"] == "warn":
        recs.append("中文字符占比偏低：可能含大量英文对话或代码，建议人工确认是否为预期内容")
    if metrics["quote_balance"]["status"] != "pass":
        recs.append(f"引号未闭合（左{metrics['quote_balance']['left_quotes']}/右{metrics['quote_balance']['right_quotes']}）：文本可能被截断，检查章节完整性")
    if metrics["garbage"]["status"] != "pass":
        recs.append(f"检测到乱码/HTML标签（{metrics['garbage']['garbage_count']}处）：需清洗源文件，去除 � / &nbsp; / HTML 标签")
    if metrics["paragraph_structure"]["status"] == "fail":
        recs.append("段落结构不稳定：可能换行符丢失（全文一段）或换行符过多（每行一段），需修复段落分隔")
    if metrics["repetition"]["status"] != "pass":
        recs.append(f"检测到重复内容（连续重复{metrics['repetition']['consecutive_duplicate_paragraphs']}段）：可能是网站水印或重复粘贴，需去重")
    if not recs:
        recs.append("所有检测项通过，文本质量良好，可进入粗切分流程")
    return recs


def main() -> int:
    ap = argparse.ArgumentParser(description="数据质量看门狗——原始文本硬门槛检测（纯 stdlib）")
    ap.add_argument("--input", type=Path, required=True, help="输入文件（.txt 原始文本 或 .jsonl segments）")
    ap.add_argument("--out", type=Path, default=None, help="输出 quality_report.json 路径（默认输入同目录）")
    ap.add_argument("--threshold-chinese", type=float, default=0.8, help="中文字符占比门槛（默认 0.8）")
    ap.add_argument("--threshold-quote", type=float, default=0.1, help="引号不平衡率门槛（默认 0.1）")
    ap.add_argument("--fail-on-error", action="store_true", help="检测到 fail 项时返回非零退出码（CI 用）")
    args = ap.parse_args()

    if not args.input.exists():
        print(f"[ERROR] 输入文件不存在: {args.input}", file=sys.stderr)
        return 2

    text = load_text(args.input)

    metrics = {
        "chinese_ratio": check_chinese_ratio(text, args.threshold_chinese),
        "quote_balance": check_quote_balance(text, args.threshold_quote),
        "garbage": check_garbage(text),
        "paragraph_structure": check_paragraph_structure(text),
        "repetition": check_repetition(text),
    }

    # 总分：加权平均（中文占比权重最高）
    weights = {"chinese_ratio": 0.30, "quote_balance": 0.15, "garbage": 0.20,
               "paragraph_structure": 0.20, "repetition": 0.15}
    overall = sum(metrics[k]["score"] * w for k, w in weights.items())

    # 裁决：任一 fail → fail；任一 warn → warn；全 pass → pass
    statuses = [m["status"] for m in metrics.values()]
    if "fail" in statuses:
        verdict = "fail"
    elif "warn" in statuses:
        verdict = "warn"
    else:
        verdict = "pass"

    report = {
        "schema_version": SCHEMA_VERSION,
        "tool": "quality_gate.py",
        "input_file": str(args.input),
        "input_size_chars": len(text),
        "overall_score": round(overall, 1),
        "verdict": verdict,
        "metrics": metrics,
        "recommendations": build_recommendations(metrics),
    }

    out_path = args.out or args.input.parent / "quality_report.json"
    io.open(out_path, "w", encoding="utf-8", newline="").write(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    )

    print(f"[OK] 质量报告已写入 {out_path}")
    print(f"[SUMMARY] 总分={overall:.1f} 裁决={verdict} "
          f"中文占比={metrics['chinese_ratio']['ratio']} "
          f"引号差={metrics['quote_balance']['imbalance_ratio']} "
          f"乱码={metrics['garbage']['garbage_count']} "
          f"段落数={metrics['paragraph_structure']['paragraph_count']} "
          f"重复段={metrics['repetition']['consecutive_duplicate_paragraphs']}")

    if args.fail_on_error and verdict == "fail":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
