#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/export_dataset.py — 脱敏导出训练数据（精读批注 Skill 配套工具）

功能：
  将 Skill 产出的任一批注 JSONL（structure / interpretation / craft / emotion
  各层、merged.jsonl 均可；输入可能带原文 text_span.text、完整原文片段）
  转换为完全剥离原文的训练数据 JSON。
  严格遵循版权合规红线（禁止把受版权保护的原文片段入库）：
  「分析即销毁」——训练数据只保留抽象结构化字段。

输入：
  任一批注层 JSONL / merged.jsonl（每行 = 一条 Skill 产物，可能含 text_span.text）

输出：
  dataset.json，结构：
  {
    "schema_version": "2.7.0",
    "exported_at": "<ISO8601>",
    "document_ids": ["doc1", "doc2", ...],
    "annotations": [
      {
        // 保留的抽象字段：
        "schema_version", "annotation_id", "document_id",
        "text_span": { "hash", "start_char", "end_char", "char_length" },  // 注意：text 字段被替换为【已脱敏】+仅存长度
        "layers": { structure, interpretation, craft, emotion }  // 纯结构化枚举/数字/标签数组
        "confidence", "null_reasons", "alternatives",
        "status",
        "_metadata": { skill_version, model, generated_at, annotation_pass }
      },
      ...
    ],
    "stats": {
      "total_annotations": N,
      "per_doc_count": { doc_id: n },
      "per_status_count": { tentative/confirmed/superseded: n },
      "removed_fields": ["text_span.text", "其他可能含原文的字段"]
    }
  }

零第三方依赖：仅 Python 3.6+ 标准库。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


REMOVED_FIELDS_NOTICE = [
    # 原文片段本身（最核心的脱敏目标）
    'text_span.text',
]

# 可能用户误填、含原文的字段黑名单——如果在输出 JSON 中发现这些键，递归地移除/替换为占位符
_PLAINTEXT_BLACKLIST_SUBSTRINGS = (
    '原文',   # 如 "原文片段"、"原始文本" 等键名
    'source', 'raw_text', 'plain_text',  # 常见英文等价命名
)

_SANITIZED_PLACEHOLDER = '【已脱敏】'


def _sanitize_recursive(obj: object) -> object:
    """递归地把所有可能含原文的字符串/字段值脱敏：
       - text_span.text → 直接替换为 【已脱敏】，同时补充 char_length
       - 任何键名含有「原文」/source/raw_text 等黑名单子串的 → 替换为占位符
       - 其他字符串和结构原样保留（结构字段是安全的）
    """
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            # 特殊情况：text_span → 额外处理 text
            if k == 'text_span' and isinstance(v, dict) and 'text' in v:
                t = v.get('text')
                char_len = len(t) if isinstance(t, str) else None
                sanitized = dict(v)
                sanitized['text'] = _SANITIZED_PLACEHOLDER
                if char_len is not None:
                    sanitized['char_length'] = char_len
                out[k] = sanitized
                continue
            # 黑名单键名 → 无论值是什么，直接脱敏
            if any(sub in str(k) for sub in _PLAINTEXT_BLACKLIST_SUBSTRINGS):
                out[k] = _SANITIZED_PLACEHOLDER
                continue
            out[k] = _sanitize_recursive(v)
        return out
    if isinstance(obj, list):
        return [_sanitize_recursive(x) for x in obj]
    # 标量（字符串/数字/布尔/null）一律原样返回——结构枚举是安全的
    return obj


def main() -> int:
    parser = argparse.ArgumentParser(
        description='将批注 JSONL 脱敏导出为训练数据：完全剥离原文，仅保留结构化字段。'
    )
    parser.add_argument('--input', required=True, type=str,
                        help='输入批注 JSONL 路径（每行一条 Skill 产物，各层/merged 均可）')
    parser.add_argument('--output', required=True, type=str,
                        help='输出 dataset.json 路径')
    parser.add_argument('--pretty', action='store_true',
                        help='输出用缩进 2 空格（默认 false 以压缩 JSON 节省空间）')
    args = parser.parse_args()

    in_path = Path(args.input)
    if not in_path.is_file():
        print(f'[export_dataset] 错误：找不到输入文件 {in_path}', file=sys.stderr)
        return 2
    out_path = Path(args.output)

    anns: list[dict] = []
    doc_ids: list[str] = []
    per_doc_count: dict[str, int] = {}
    per_status_count: dict[str, int] = {}
    schema_version_seen: set[str] = set()

    line_no = 0
    total = 0
    skipped = 0
    with in_path.open('r', encoding='utf-8') as f:
        for raw_line in f:
            line_no += 1
            line = raw_line.strip()
            if not line:
                continue
            total += 1
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as e:
                print(f'[export_dataset] 警告：JSONL 第 {line_no} 行解析失败，跳过：{e}', file=sys.stderr)
                skipped += 1
                continue
            if not isinstance(obj, dict):
                print(f'[export_dataset] 警告：JSONL 第 {line_no} 行不是对象，跳过', file=sys.stderr)
                skipped += 1
                continue

            # 1. 脱敏（递归清理可能含原文的字段）
            clean = _sanitize_recursive(obj)

            # 2. 统计
            doc_id = clean.get('document_id') or '__unknown_doc__'
            per_doc_count[doc_id] = per_doc_count.get(doc_id, 0) + 1
            status = clean.get('status') or '__no_status__'
            per_status_count[status] = per_doc_count.get(status, 0)
            per_status_count[status] = per_status_count.get(status, 0) + 1
            if 'schema_version' in clean and isinstance(clean['schema_version'], str):
                schema_version_seen.add(clean['schema_version'])
            if doc_id not in doc_ids:
                doc_ids.append(doc_id)
            anns.append(clean)

    # 决定输出 schema_version（优先取出现最多的 SUPPORTED 版本）
    if len(schema_version_seen) == 1:
        out_schema_v = next(iter(schema_version_seen))
    else:
        out_schema_v = 'mixed-' + ','.join(sorted(schema_version_seen)) or 'unknown'
        print(
            f'[export_dataset] 警告：输入混合了多种 schema_version: {sorted(schema_version_seen)}，'
            '建议用同一版本批注后再导出训练数据。',
            file=sys.stderr,
        )

    dataset = {
        'schema_version': out_schema_v,
        'exported_at': datetime.now(timezone.utc).astimezone().isoformat(timespec='seconds'),
        'document_ids': doc_ids,
        'annotations': anns,
        'stats': {
            'total_lines_in_jsonl': total,
            'total_annotations': len(anns),
            'skipped_lines': skipped,
            'per_doc_count': per_doc_count,
            'per_status_count': per_status_count,
            'schema_versions_found': sorted(schema_version_seen),
            'removed_fields': REMOVED_FIELDS_NOTICE + [
                f'任何键名含以下子串的字段: {_PLAINTEXT_BLACKLIST_SUBSTRINGS}',
            ],
        },
    }

    indent = 2 if args.pretty else None
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(dataset, ensure_ascii=False, indent=indent), encoding='utf-8')

    print(
        f'[export_dataset] 完成：{len(anns)} 条批注脱敏导出到 {out_path.resolve()}\n'
        f'  来源文档 {len(doc_ids)} 份，混合 schema 版本 {sorted(schema_version_seen)}\n'
        f'  已移除可能含原文的字段：{REMOVED_FIELDS_NOTICE}'
    )
    return 0


if __name__ == '__main__':
    sys.exit(main())
