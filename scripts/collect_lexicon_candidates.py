# -*- coding: utf-8 -*-
"""
scripts/collect_lexicon_candidates.py — 词表演化候选收集器（WikiSkill 经验回写管道）

功能：
  1. 扫描产物 JSONL（emotion 层）中所有 D19 情感词（primary / secondary[] / arc.before / arc.after）
  2. 以**当前** D19 词表白名单为基准，找出"会被 validate_output.py 拒收的自由情感词"
  3. 统计出现频率（同一情感语义 ≥3 次 → 触发词表演化协议 emotion-lexicon.md §四）
  4. 给每个候选词附"可归约建议"（用 term_normalizer 映射 / DLUT 小类 / 字面基元匹配）
  5. 输出：
     a. Markdown 候选报告（默认）
     b. --sop：直接输出 RUNBOOK 校验错误修复表可粘贴行（Trace2Skill SoP 自动生成）

输入/输出：
  输入：--dir <产物目录>（递归找 *_emotion.jsonl；或用 --files 指定）
        --d19 <emotion-lexicon.md>（D19 白名单真源）
  输出：--out <report.md>；--sop <sop.md>（可选）；stdout 摘要

依赖：Python 3.10+ 纯 stdlib。零第三方依赖。
版本：v3.2.0（T-031-②③，ADR-012）。
"""

from __future__ import annotations

import argparse
import io
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

# term_normalizer 保守映射（与 scripts/term_normalizer.py 同源策略；此处内联避免循环依赖）
# 说明：collect 的"可归约建议"优先查 term_normalizer；未覆盖时按字面/基元近似给出提示。
EMOTION_PATH_KEYS = ("emotion",)


def load_d19_whitelist(path: Path) -> set[str]:
    """从 emotion-lexicon.md 解析当前白名单（与 lexicon_crosscheck 同逻辑）。"""
    words: set[str] = set()
    with io.open(path, encoding="utf-8") as f:
        lines = f.readlines()
    in_table = False
    for ln in lines:
        s = ln.strip()
        if s.startswith("## 二、词表全量"):
            in_table = True
            continue
        if in_table:
            if s.startswith("##") and "词表全量" not in s:
                break
            if s.startswith("| **") and "|" in s[3:]:
                word = s.split("|")[1].strip().strip("**").strip()
                if word:
                    words.add(word)
    return words


def load_normalizer_map(path: Path | None) -> dict[str, str]:
    """从 term_normalizer.py 提取同义映射（自由词 → 枚举词）。失败时返回空表。"""
    if path is None or not path.exists():
        return {}
    text = io.open(path, encoding="utf-8").read()
    # 提取形如 "自由词": "枚举词" 的映射条目
    mapping: dict[str, str] = {}
    for m in re.finditer(r'"([^"]{1,8})"\s*:\s*"([^"]{1,8})"', text):
        free, enum = m.group(1), m.group(2)
        # 只收 D19 相关的词级映射（长度 1-8，中文）
        if re.fullmatch(r"[\u4e00-\u9fff]{1,8}", free) and re.fullmatch(r"[\u4e00-\u9fff]{1,8}", enum):
            mapping[free] = enum
    return mapping


def extract_emotions(obj: dict) -> list[str]:
    """从一条 emotion 产物中提取所有 D19 情感词（递归找 emotion 键）。"""
    out: list[str] = []
    stack = [obj]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            for k, v in cur.items():
                if k == "emotion" and isinstance(v, str) and v.strip():
                    out.append(v.strip())
                elif isinstance(v, (dict, list)):
                    stack.append(v)
        elif isinstance(cur, list):
            stack.extend(cur)
    return out


def scan_files(files: list[Path]) -> Counter[str]:
    """扫描 JSONL，统计全部 D19 情感词频（无论是否白名单）。"""
    freq: Counter[str] = Counter()
    per_word_locs: defaultdict[str, list[tuple[str, str]]] = defaultdict(list)  # word -> [(file, segment_id)]
    for fp in files:
        with io.open(fp, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                seg = rec.get("segment_id") or rec.get("annotation_id") or "?"
                for w in extract_emotions(rec):
                    freq[w] += 1
                    if len(per_word_locs[w]) < 3:
                        per_word_locs[w].append((fp.name, seg))
    return freq, per_word_locs


def main() -> int:
    ap = argparse.ArgumentParser(description="词表演化候选收集器（WikiSkill 经验回写）")
    ap.add_argument("--dir", type=Path, default=None,
                    help="产物目录（递归找 *_emotion.jsonl / *_emotion_*.jsonl）")
    ap.add_argument("--files", type=str, default=None, help="逗号分隔的 JSONL 文件列表（优先于 --dir）")
    ap.add_argument("--d19", type=Path,
                    default=Path(__file__).resolve().parent.parent / "references" / "emotion-lexicon.md",
                    help="D19 词表真源 md")
    ap.add_argument("--normalizer", type=Path,
                    default=Path(__file__).resolve().parent / "term_normalizer.py",
                    help="term_normalizer.py 路径（用于可归约建议）")
    ap.add_argument("--min-freq", type=int, default=3, help="候选触发频率（协议默认 ≥3）")
    ap.add_argument("--out", type=Path, default=None, help="候选报告 md 路径")
    ap.add_argument("--sop", type=Path, default=None, help="SoP 输出 md 路径（RUNBOOK 修复表行）")
    args = ap.parse_args()

    if args.files:
        files = [Path(p.strip()) for p in args.files.split(",") if p.strip()]
    elif args.dir:
        files = sorted(args.dir.rglob("*emotion*.jsonl"))
    else:
        print("[ERROR] 必须提供 --dir 或 --files", file=sys.stderr)
        return 2
    files = [f for f in files if f.exists()]
    if not files:
        print("[ERROR] 未找到任何 emotion JSONL 文件", file=sys.stderr)
        return 2

    if not args.d19.exists():
        print(f"[ERROR] D19 真源不存在: {args.d19}", file=sys.stderr)
        return 2

    whitelist = load_d19_whitelist(args.d19)
    norm_map = load_normalizer_map(args.normalizer)
    freq, locs = scan_files(files)

    # 非白名单词（会被 validate 拒收的自由情感词），按频率降序
    free_words = [(w, n) for w, n in freq.items() if w not in whitelist]
    free_words.sort(key=lambda x: (-x[1], x[0]))
    triggers = [w for w, n in free_words if n >= args.min_freq]

    # ---- 报告 ----
    lines: list[str] = []
    lines.append("# 词表演化候选收集报告（v3.2.0 / T-031-② WikiSkill 经验回写）\n")
    lines.append(f"- 扫描文件：{len(files)} 个（{', '.join(f.name for f in files[:5])}{'…' if len(files) > 5 else ''}）")
    lines.append(f"- 词表基准：D19 白名单 {len(whitelist)} 词（emotion-lexicon.md 当前版本）")
    lines.append(f"- 触发阈值：同一自由情感词出现 ≥ {args.min_freq} 次（协议 §四）\n")
    lines.append("## 一、非白名单自由情感词（validate 会拒收）\n")
    lines.append("| 词 | 出现次数 | 可归约建议 | 首次出现位置 |")
    lines.append("|----|----------|-----------|--------------|")
    for w, n in free_words:
        suggest = norm_map.get(w, "（无映射，需人工判定基元归约）")
        loc = "；".join(f"{f}:{s}" for f, s in locs.get(w, [])[:2])
        lines.append(f"| {w} | {n} | {suggest} | {loc} |")
    lines.append("")
    lines.append(f"> 共 {len(free_words)} 个自由词，其中 **{len(triggers)} 个达到触发阈值**（≥{args.min_freq} 次）。\n")
    lines.append("## 二、候选词清单（达到触发阈值，进入词表演化协议裁决）\n")
    if triggers:
        lines.append("| 候选词 | 出现次数 | 建议动作 |")
        lines.append("|--------|----------|----------|")
        for w in triggers:
            n = freq[w]
            if w in norm_map:
                act = f"提示标注者用既有词「{norm_map[w]}」（语义重复，不新增）"
            else:
                act = "记入候选，随版本发布正式入表（需先过基元归约审查）"
            lines.append(f"| {w} | {n} | {act} |")
    else:
        lines.append("（无）")
    lines.append("")
    lines.append("## 三、协议裁决说明\n")
    lines.append("| 情形 | 动作 |")
    lines.append("|------|------|")
    lines.append(f"| 自由词 ≥{args.min_freq} 且可归约到基元 | 记入候选，随版本发布正式入表 |")
    lines.append(f"| 自由词 ≥{args.min_freq} 但与既有词近义 | 不新增，提示用既有词（normalizer 已给出建议） |")
    lines.append(f"| 自由词 <{args.min_freq} | 不触发；如标注者认为必须，走人工申请 |")
    report = "\n".join(lines) + "\n"

    # ---- SoP 输出（Trace2Skill：运行经验 → RUNBOOK 修复表行）----
    sop_lines: list[str] = []
    sop_lines.append("## 校验错误修复表（自动生成行，v3.2.0）\n")
    sop_lines.append("| 报错特征 | 修复动作 | 来源 |")
    sop_lines.append("|----------|----------|------|")
    for w in triggers:
        if w in norm_map:
            act = f"`{w}` → 替换为既有词 `{norm_map[w]}`（语义重复，不入表）"
            src = "collect_lexicon_candidates 经验回写"
        else:
            act = f"`{w}` 出现 {freq[w]} 次：按词表演化协议入候选，待版本发布入表"
            src = "collect_lexicon_candidates 经验回写"
        sop_lines.append(f"| D19 用了白名单外词 `{w}` | {act} | {src} |")
    sop = "\n".join(sop_lines) + "\n"

    if args.out:
        io.open(args.out, "w", encoding="utf-8", newline="").write(report)
        print(f"[OK] 候选报告已写入 {args.out}")
    else:
        print(report)
    if args.sop:
        io.open(args.sop, "w", encoding="utf-8", newline="").write(sop)
        print(f"[OK] SoP 已写入 {args.sop}")

    print(f"[SUMMARY] 扫描 {len(files)} 文件 | 白名单 {len(whitelist)} | 自由词 {len(free_words)} | 触发候选 {len(triggers)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
