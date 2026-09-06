#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/calibrate_quality.py — quality_score 校准工具 v3.8.2（T-042）

基于 Craft 层 D13-D17 的加权评分，对已有批注计算 quality_score 并回写。
纯确定性算法，零 LLM 调用，可复现。

评分公式（权重）：
  - D13 佳句数量/质量：30%（数量 60% + 类型多样性 40%）
  - D14 修辞密度：20%（数量 60% + 类型多样性 40%）
  - D15 意象丰富度：20%（数量 60% + 类型多样性 40%）
  - D16 词汇精度：15%（数量 60% + 词性多样性 40%）
  - D17 句式多样性：15%（数量 60% + 类型多样性 40%）

每个维度评分 = min(count / max_count, 1.0) * 0.6 + min(unique_types / total_types, 1.0) * 0.4
最终 quality_score = 加权平均 * 100（0-100 分）

用法：
  python scripts/calibrate_quality.py --craft <doc_id>_craft.jsonl --output <doc_id>_craft_calibrated.jsonl
  python scripts/calibrate_quality.py --craft <doc_id>_craft.jsonl --in-place  # 直接覆盖原文件
  python scripts/calibrate_quality.py --dir <annotations_dir> --doc-id <doc_id> --in-place
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from collections import Counter

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# 各维度的合法类型总数（用于多样性评分）
DIMENSION_TYPES = {
    "D13_golden_lines": {"type": ["佳句", "警句", "点睛之笔", "意境句", "哲理句", "细节句"]},
    "D14_rhetoric": {"type": ["比喻", "拟人", "排比", "反讽", "通感", "夸张", "对比", "象征"]},
    "D15_imagery": {"type": ["自然意象", "器物意象", "人体意象", "色彩意象", "抽象意象"]},
    "D16_diction": {"pos": ["动词", "形容词", "副词", "名词"]},
    "D17_syntax": {"type": ["排比", "长短交替", "倒装", "独词句", "对偶", "设问"]},
}

# 各维度的权重
WEIGHTS = {
    "D13_golden_lines": 0.30,
    "D14_rhetoric": 0.20,
    "D15_imagery": 0.20,
    "D16_diction": 0.15,
    "D17_syntax": 0.15,
}

# 各维度的最大数量参考值（用于数量评分，超过则满分）
# v3.8.2 调整：降低阈值，使短篇批注的分数更合理
MAX_COUNTS = {
    "D13_golden_lines": 3,
    "D14_rhetoric": 2,
    "D15_imagery": 2,
    "D16_diction": 2,
    "D17_syntax": 2,
}


def load_jsonl(path: Path) -> list[dict]:
    """加载 JSONL 文件"""
    rows = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError as e:
                    print(f"⚠️ JSON 解析失败: {e}", file=sys.stderr)
    return rows


def save_jsonl(rows: list[dict], path: Path) -> None:
    """保存 JSONL 文件（原子写）"""
    tmp = path.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    tmp.replace(path)


def calculate_dimension_score(items: list[dict], dim_key: str, type_field: str) -> tuple[float, dict]:
    """计算单个维度的评分（0-1），返回 (score, detail)
    
    评分公式（v3.8.2 调整）：
      - 基础分：有至少 1 个条目 = 0.4（40 分）
      - 数量分：min(count / max_count, 1.0) * 0.4（40 分）
      - 多样性分：min(unique_types / total_types, 1.0) * 0.2（20 分）
    """
    if not items:
        return 0.0, {"count": 0, "unique_types": 0, "base_score": 0.0, "count_score": 0.0, "diversity_score": 0.0}
    
    count = len(items)
    type_field_key = "type" if type_field == "type" else "pos"
    types = [item.get(type_field_key, "") for item in items if item.get(type_field_key)]
    unique_types = len(set(types))
    total_types = len(DIMENSION_TYPES[dim_key][type_field_key])
    
    # 基础分（40%）：有至少 1 个条目
    base_score = 0.4
    
    # 数量分（40%）
    count_score = min(count / MAX_COUNTS[dim_key], 1.0) * 0.4
    
    # 多样性分（20%）
    diversity_score = min(unique_types / total_types, 1.0) * 0.2 if total_types > 0 else 0.0
    
    score = base_score + count_score + diversity_score
    
    detail = {
        "count": count,
        "unique_types": unique_types,
        "total_types": total_types,
        "base_score": round(base_score, 3),
        "count_score": round(count_score, 3),
        "diversity_score": round(diversity_score, 3),
    }
    
    return score, detail


def calculate_quality_score(craft_data: dict) -> tuple[float, dict]:
    """计算 craft 层的 quality_score（0-100），返回 (score, breakdown)"""
    breakdown = {}
    weighted_sum = 0.0
    total_weight = 0.0
    
    for dim_key, weight in WEIGHTS.items():
        items = craft_data.get(dim_key, []) or []
        type_field = "pos" if dim_key == "D16_diction" else "type"
        
        score, detail = calculate_dimension_score(items, dim_key, type_field)
        weighted_sum += score * weight
        total_weight += weight
        breakdown[dim_key] = {
            "score": round(score * 100, 1),
            "weight": weight,
            **detail,
        }
    
    quality_score = round(weighted_sum / total_weight * 100, 1) if total_weight > 0 else 0.0
    
    return quality_score, breakdown


def calibrate_craft_file(craft_path: Path, output_path: Path | None = None, in_place: bool = False) -> dict:
    """校准单个 craft JSONL 文件"""
    rows = load_jsonl(craft_path)
    
    if not rows:
        print(f"⚠️ {craft_path} 为空，跳过")
        return {"total": 0, "calibrated": 0}
    
    calibrated = 0
    scores = []
    
    for row in rows:
        # 获取 craft 数据（支持顶层 craft 和 layers.craft 两种格式）
        craft_data = row.get("craft") or row.get("layers", {}).get("craft", {})
        
        if not craft_data:
            continue
        
        quality_score, breakdown = calculate_quality_score(craft_data)
        
        # 回写 quality_score
        row["_quality_score"] = quality_score
        row["_quality_breakdown"] = breakdown
        
        # 更新 _metadata
        metadata = row.get("_metadata", {})
        metadata["quality_calibrated"] = True
        metadata["quality_calibrated_at"] = "v3.8.2"
        row["_metadata"] = metadata
        
        scores.append(quality_score)
        calibrated += 1
    
    # 保存
    if in_place:
        save_jsonl(rows, craft_path)
        output_path = craft_path
    elif output_path:
        save_jsonl(rows, output_path)
    else:
        # 默认输出到同目录的 _calibrated 文件
        output_path = craft_path.with_name(craft_path.stem + "_calibrated.jsonl")
        save_jsonl(rows, output_path)
    
    # 统计
    stats = {
        "total": len(rows),
        "calibrated": calibrated,
        "avg_score": round(sum(scores) / len(scores), 1) if scores else 0,
        "min_score": min(scores) if scores else 0,
        "max_score": max(scores) if scores else 0,
        "output": str(output_path),
    }
    
    return stats


def main():
    parser = argparse.ArgumentParser(description="quality_score 校准工具 v3.8.2（T-042）")
    parser.add_argument("--craft", type=str, help="craft JSONL 文件路径")
    parser.add_argument("--output", type=str, help="输出文件路径（默认同目录 _calibrated）")
    parser.add_argument("--in-place", action="store_true", help="直接覆盖原文件")
    parser.add_argument("--dir", type=str, help="批注目录（批量处理，需配合 --doc-id）")
    parser.add_argument("--doc-id", type=str, help="文档 ID（批量处理时使用）")
    
    args = parser.parse_args()
    
    if args.dir and args.doc_id:
        # 批量处理模式
        # v3.9.0 T-079：先尝试 dir/doc_id/doc_id_craft.jsonl，不存在则降级为 dir/doc_id_craft.jsonl
        craft_path = Path(args.dir) / args.doc_id / f"{args.doc_id}_craft.jsonl"
        if not craft_path.exists():
            craft_path = Path(args.dir) / f"{args.doc_id}_craft.jsonl"
        if not craft_path.exists():
            print(f"❌ 文件不存在: {craft_path}")
            sys.exit(1)
        stats = calibrate_craft_file(craft_path, in_place=args.in_place)
    elif args.craft:
        craft_path = Path(args.craft)
        if not craft_path.exists():
            print(f"❌ 文件不存在: {craft_path}")
            sys.exit(1)
        output_path = Path(args.output) if args.output else None
        stats = calibrate_craft_file(craft_path, output_path, in_place=args.in_place)
    else:
        parser.print_help()
        sys.exit(1)
    
    # 打印结果
    print("=" * 60)
    print("quality_score 校准结果")
    print("=" * 60)
    print(f"总行数: {stats['total']}")
    print(f"已校准: {stats['calibrated']}")
    print(f"平均分: {stats['avg_score']}")
    print(f"最低分: {stats['min_score']}")
    print(f"最高分: {stats['max_score']}")
    print(f"输出文件: {stats['output']}")
    print("=" * 60)


if __name__ == "__main__":
    main()
