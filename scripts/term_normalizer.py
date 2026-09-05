# -*- coding: utf-8 -*-
"""
scripts/term_normalizer.py — 同义词归一化器（v3.1.0，ADR-011 / T-030）

功能：把批注 JSONL 中"自由产出词"保守映射回枚举词，降低跨标注者用词漂移。
  - D04.core（structure 层，v2.9.0 新 20 词）
  - D19 primary/secondary/arc 的 emotion（emotion 层，emotion-lexicon.md 50 词）
  - 只做**确定同义**的保守映射（如 悲哀→悲伤、惊恐→恐惧）；拿不准的一律不改，
    留给 validate_output.py 报错，避免"纠正"变成"伪造"。
  - 归一化不改 schema 字段结构、不注入新字段；改写明细写进报告（默认 stdout + 可选 --report 落盘）。

用法：
  python scripts/term_normalizer.py --file <批注.jsonl> --layer structure|emotion [--in-place] [--report <path>]
示例：
  python scripts/term_normalizer.py --file outputs/annotations/moon/moon_structure.jsonl --layer structure
  python scripts/term_normalizer.py --file outputs/annotations/moon/moon_emotion.jsonl --layer emotion --in-place

输出：
  默认写 <file>.normalized.jsonl（原文件不动）；--in-place 覆盖原文件。
  报告：总行数 / 命中映射数 / 逐词明细（行号、from→to、字段路径）。
"""
import argparse
import io
import json
import sys
from pathlib import Path

# ---------------- 保守同义映射表（随语料扩充） ----------------

# D04.core（structure 层，v2.9.0 新 20 词）
D04_MAPPINGS = {
    "悲哀": "悲伤", "悲痛": "悲伤", "哀伤": "悲伤",
    "惊恐": "恐惧", "害怕": "恐惧", "畏惧": "恐惧", "恐慌": "恐惧",  # 恐慌为 D19 词，D04 归恐惧
    "欢喜": "喜悦", "高兴": "喜悦", "开心": "喜悦", "快乐": "喜悦",
    "期望": "期待", "盼望": "期待",
    "孤单": "孤独", "孤寂": "孤独",
    "吃惊": "惊讶", "惊愕": "惊讶",
    "向往": "渴望", "渴求": "渴望",
    "羞愧": "羞耻", "丢脸": "羞耻",
    "厌烦": "厌恶", "反感": "厌恶",
    "释怀": "释然",
    "心慌": "焦虑", "焦躁": "焦虑",
}

# D19.emotion（emotion 层，emotion-lexicon.md 50 词）
D19_MAPPINGS = {
    "悲哀": "悲伤", "悲痛": "悲伤", "哀伤": "悲伤",
    "欢喜": "喜悦", "高兴": "喜悦", "开心": "喜悦",
    "恼怒": "愤怒", "愤懑": "愤怒", "怒火": "愤怒",
    "害怕": "恐惧", "畏惧": "恐惧",
    "惊奇": "惊讶", "愕然": "惊讶",
    "盼望": "期待", "期盼": "期待",
    "嫌弃": "厌恶", "厌烦": "厌恶",
    "信赖": "信任",
    "怅然": "怅惘",
    "羞愧": "羞耻", "难堪": "羞耻",
    "渴求": "渴望", "向往": "渴望",
    "妒忌": "嫉妒", "妒恨": "嫉妒",
    "困惑": "迷茫", "迷惘": "迷茫", "茫然": "迷茫",
    "自得": "得意",
}

LAYER_MAPPINGS = {
    "structure": D04_MAPPINGS,
    "emotion": D19_MAPPINGS,
}


def _walk(obj, path_prefix, hits):
    """递归遍历找 emotion 字段（emotion 层旧格式 + 新格式都覆盖）。"""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "emotion" and isinstance(v, str):
                hits.append((path_prefix + [k], v))
            else:
                _walk(v, path_prefix + [k], hits)
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            _walk(item, path_prefix + [str(i)], hits)


def normalize_line(line: dict, layer: str, mappings: dict) -> tuple[dict, list]:
    """归一化单行。返回 (行, 改写明细列表)。"""
    changes = []
    if layer == "structure":
        try:
            core = line["layers"]["structure"]["D04"]["core"]
        except (KeyError, TypeError):
            return line, changes
        if isinstance(core, str) and core in mappings:
            line["layers"]["structure"]["D04"]["core"] = mappings[core]
            changes.append(("D04.core", core, mappings[core]))
        return line, changes

    if layer == "emotion":
        hits = []
        _walk(line, [], hits)
        for path, val in hits:
            if val in mappings:
                target = line
                for seg in path[:-1]:
                    if isinstance(seg, str) and seg.isdigit():
                        seg = int(seg)
                    target = target[seg]
                target[path[-1]] = mappings[val]
                changes.append((".".join(map(str, path)), val, mappings[val]))
        return line, changes

    return line, changes


def main():
    ap = argparse.ArgumentParser(description="同义词归一化器（v3.1.0）")
    ap.add_argument("--file", required=True, help="批注 JSONL 路径")
    ap.add_argument("--layer", required=True, choices=["structure", "emotion"], help="层类型")
    ap.add_argument("--in-place", action="store_true", help="覆盖原文件（默认写 <file>.normalized.jsonl）")
    ap.add_argument("--report", default=None, help="改写报告落盘路径（默认 stdout）")
    args = ap.parse_args()

    src = Path(args.file)
    if not src.exists():
        print(f"❌ 文件不存在: {src}")
        sys.exit(1)

    mappings = LAYER_MAPPINGS[args.layer]
    out_lines = []
    all_changes = []
    n_total = 0
    with io.open(src, encoding="utf-8") as f:
        for ln, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            n_total += 1
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as e:
                print(f"⚠️ 第 {ln} 行 JSON 解析失败，跳过: {e}")
                all_changes.append(f"行 {ln}: JSON 解析失败（未改动）")
                out_lines.append(line)
                continue
            obj, changes = normalize_line(obj, args.layer, mappings)
            for path, frm, to in changes:
                all_changes.append(f"行 {ln}: {path}  {frm} → {to}")
            out_lines.append(json.dumps(obj, ensure_ascii=False))

    if args.in_place:
        dst = src
    else:
        dst = src.with_name(src.stem + ".normalized.jsonl")
    with io.open(dst, "w", encoding="utf-8") as f:
        f.write("\n".join(out_lines) + "\n")

    report_lines = [
        f"== term_normalizer 报告 ==",
        f"文件: {src}",
        f"层: {args.layer}",
        f"总行数: {n_total}",
        f"命中映射: {len(all_changes)}",
    ]
    if all_changes:
        report_lines.append("-- 明细 --")
        report_lines.extend(all_changes)
    report = "\n".join(report_lines)
    if args.report:
        with io.open(args.report, "w", encoding="utf-8") as f:
            f.write(report + "\n")
        print(f"✅ 报告已写入 {args.report}")
    print(report)
    print(f"✅ 输出: {dst}（{'已覆盖原文件' if args.in_place else '原文件未动'}）")


if __name__ == "__main__":
    main()
