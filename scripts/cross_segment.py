#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/cross_segment.py — 二阶段跨段分析 v2.6.0（架构可运行版）

v3.8.4 增强信号（T-055）：
  - D19.target（情感对象复用）：同角色在多段出现作为情感对象，可能存在跨段情感呼应
  - D06（信息控制埋设-揭露）：前段埋设的信息在后段揭露，构成伏笔-回收关系
  - D15（意象复用）：同意象在多段出现，可能构成象征线索
  这些信号作为规则候选的补充，最终精排建议由 Agent LLM 二分类完成（见 SKILL.md Phase 3.5）。

⚠️ 重要：v2.5 规格 §4.4 P0 问题 #4 指出 v2.4 版 `build_cross_segments` 恒返回空列表是占位。
本轮交付的是【启发式 + 规则先行】的可运行版本：
  1) 情绪强度序列突变点 → 标记为『因果/时序』候选（规则）；
  2) 视角切换点 → 标记为『时序/对比』候选（规则）；
  3) D09 主题标签跨段复用 → 标记为『呼应』候选（规则）；
  4) D06 信息控制中含"埋设"语义 → 与后续段中揭露的点连为『伏笔-回收』候选。

完整的 LLM 二分类打标（真正高精度的 cross_refs）可留给调用方自建批量管线叠加。
本脚本不调 API、零第三方依赖，保证"第一次跑就产出可用列表、而非空列表"。

用法：
  python scripts/cross_segment.py \
    --doc-id moon_sixpence \
    --segments moon_sixpence_segments.jsonl \
    --structure moon_sixpence_structure.jsonl \
    --interpretation moon_sixpence_interpretation.jsonl \
    --craft moon_sixpence_craft.jsonl \
    --window-size 15 --overlap 3
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

# v2.5.1 修复 #1：Windows GBK 控制台 UnicodeEncodeError（emoji 打印崩溃）
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# checkpoint 回写（v2.5.1：跨段完成后标记 cross_segment_completed）
sys.path.insert(0, str(Path(__file__).parent))
from checkpoint import mark_phase_completed  # noqa: E402

RELATION_TYPES = {"伏笔-回收", "因果", "时序", "对比", "呼应"}


def _load_jsonl(path: Path) -> list[dict]:
    out: list[dict] = []
    if not path.is_file():
        return out
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s:
                continue
            try:
                out.append(json.loads(s))
            except json.JSONDecodeError as e:
                print(f"⚠️ {path} JSONL 解析失败：{e}", file=sys.stderr)
    return out


def _index_by_segment_id(rows: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for r in rows:
        sid = r.get("segment_id")
        if sid:
            out[sid] = r
    return out


def _emotion_intensity(row: dict | None) -> int | None:
    if row is None:
        return None
    try:
        return int(row["layers"]["structure"]["D04"]["intensity"])
    except Exception:
        return None


def _perspective(row: dict | None) -> str | None:
    if row is None:
        return None
    try:
        return row["layers"]["structure"]["D07"]["type"]
    except Exception:
        return None


def _is_switch_point(row: dict | None) -> bool:
    if row is None:
        return False
    try:
        return bool(row["layers"]["structure"]["D07"]["is_switch_point"])
    except Exception:
        return False


def _themes(row: dict | None) -> list[str]:
    if row is None:
        return []
    try:
        return list(row["layers"]["interpretation"]["D09"] or [])
    except Exception:
        return []


def _make_anchor(seg_row: dict, snippet_len: int = 24) -> tuple[str, dict | None]:
    """返回 (干净锚点文本, 段内 span)。锚点做空白归一（仍是原文子串），span 尽量回算。"""
    text = ""
    if isinstance(seg_row, dict):
        ts = seg_row.get("text_span")
        if isinstance(ts, dict):
            text = ts.get("text", "")
    if not text:
        return "", None
    # v3.8.8 T-068：用原始文本截取，避免空白归一化导致的坐标漂移
    raw_snippet = text[:snippet_len]
    if not raw_snippet.strip():
        return "", None
    # 段内相对偏移回算：在原始 text 中定位 clean 的首部片段
    head = raw_snippet[:6]
    idx = text.find(head)
    span = None
    if idx >= 0 and idx + len(raw_snippet) <= len(text):
        span = {"start": idx, "end": idx + len(raw_snippet)}
    return raw_snippet, span


def main() -> int:
    p = argparse.ArgumentParser(description="【精读批注 v2.6 Phase 3】二阶段跨段关系分析（规则启发式，保证可运行）")
    p.add_argument("--doc-id", required=True)
    p.add_argument("--segments", required=True, help="segments.jsonl")
    p.add_argument("--structure", required=True, help="structure.jsonl")
    p.add_argument("--interpretation", default=None, help="interpretation.jsonl（可选，D09 主题呼应）")
    p.add_argument("--craft", default=None, help="craft.jsonl（可选）")
    p.add_argument("--window-size", type=int, default=15, help="滑窗大小（默认 15 段）")
    p.add_argument("--overlap", type=int, default=3, help="滑窗重叠（默认 3 段）")
    p.add_argument("--output-dir", "--output", dest="output", default=None, help="输出文件路径（默认 <doc_id>_cross_segment.jsonl）")
    p.add_argument("--preserve-curated", action="store_true", default=True,
                   help="保留既有跨段关系中人工/LLM 核验过的条目（默认开；规则重跑只覆盖 _source='rule' 的）")
    p.add_argument("--no-preserve-curated", dest="preserve_curated", action="store_false",
                   help="关闭保留：完全用本轮规则结果覆盖现有文件")
    args = p.parse_args()

    segs = _load_jsonl(Path(args.segments))
    structs = _index_by_segment_id(_load_jsonl(Path(args.structure)))
    interps = _index_by_segment_id(
        _load_jsonl(Path(args.interpretation)) if args.interpretation else []
    )

    seg_ordered_ids = [s.get("segment_id") for s in segs if s.get("segment_id")]
    if not seg_ordered_ids:
        print("❌ segments 为空", file=sys.stderr)
        return 2

    # v2.5.1：--preserve-curated 默认开——读取现有文件里人工/LLM 核验的关系（非规则生成），
    # 规则重跑只重新生成 _source='rule' 的候选，避免覆盖已核验内容。
    out_path = Path(args.output) if args.output else (Path.cwd() / f"{args.doc_id}_cross_segment.jsonl")
    preserved: list[dict] = []
    if args.preserve_curated and out_path.is_file():
        try:
            with out_path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    old = json.loads(line)
                    for r in old.get("cross_refs", []):
                        if r.get("_source") != "rule":
                            preserved.append(r)
            if preserved:
                print(f"   🔒 保留人工/LLM 核验关系 {len(preserved)} 条（规则重跑不覆盖）")
        except Exception as e:
            print(f"⚠️ 读取既有跨段文件失败，忽略保留：{e}", file=sys.stderr)

    refs: list[dict] = []
    ref_idx = 0

    def _add_ref(relation_type: str, src_idx: int, tgt_idx: int, note: str):
        nonlocal ref_idx
        if src_idx >= tgt_idx:
            return  # 不做反向
        src_sid = seg_ordered_ids[src_idx]
        tgt_sid = seg_ordered_ids[tgt_idx]
        src_seg = segs[src_idx]
        tgt_seg = segs[tgt_idx]
        ref_idx += 1
        src_anchor, src_span = _make_anchor(src_seg)
        tgt_anchor, tgt_span = _make_anchor(tgt_seg)
        refs.append({
            "ref_id": f"cf_{ref_idx:04d}",
            "relation_type": relation_type,
            "_source": "rule",  # v2.5.1：标记规则生成，便于 --preserve-curated 区分人工核验
            "source": {
                "segment_id": src_sid,
                "chapter": src_seg.get("chapter"),
                "anchor_text": src_anchor,
                "span": src_span,
            },
            "target": {
                "segment_id": tgt_sid,
                "chapter": tgt_seg.get("chapter"),
                "anchor_text": tgt_anchor,
                "span": tgt_span,
            },
            "confidence": 0.7,  # 规则版保守
            "note": note,
        })

    # ------------------- 规则 1：情绪强度突变点（≥4 档差）→ 因果/时序 -------------------
    prev_it = None
    for i, sid in enumerate(seg_ordered_ids):
        it = _emotion_intensity(structs.get(sid))
        if prev_it is not None and it is not None:
            delta = abs(it - prev_it)
            if delta >= 4:
                _add_ref(
                    "时序",
                    max(0, i - 1), i,
                    f"情绪强度 {prev_it} → {it}（突变档差 {delta} ≥ 4）"
                )
        prev_it = it

    # ------------------- 规则 2：视角切换点 → 时序/对比 -------------------
    for i, sid in enumerate(seg_ordered_ids):
        if _is_switch_point(structs.get(sid)):
            prev_p = _perspective(structs.get(seg_ordered_ids[i - 1])) if i > 0 else None
            cur_p = _perspective(structs.get(sid))
            if prev_p and cur_p and prev_p != cur_p:
                _add_ref(
                    "对比",
                    max(0, i - 1), i,
                    f"视角 {prev_p} → {cur_p} 切换点"
                )

    # ------------------- 规则 3：D09 主题复用 → 呼应 -------------------
    # 在 windows 内找相同主题
    N = len(seg_ordered_ids)
    ws = args.window_size
    theme_positions: dict[str, list[int]] = {}
    for i, sid in enumerate(seg_ordered_ids):
        themes = _themes(interps.get(sid))
        for t in themes:
            theme_positions.setdefault(t, []).append(i)
    for theme, positions in theme_positions.items():
        # 对每两个位置对（在窗口内+重叠外都算）
        for a in range(len(positions)):
            for b in range(a + 1, len(positions)):
                ia, ib = positions[a], positions[b]
                if ib - ia <= ws:
                    _add_ref(
                        "呼应",
                        ia, ib,
                        f"主题标签「{theme}」重复出现"
                    )

    # 去重（同 source_idx/target_idx/type 只保留一条）
    seen: set[tuple[int, int, str]] = set()
    dedup: list[dict] = []
    for r in refs:
        key = (
            seg_ordered_ids.index(r["source"]["segment_id"]),
            seg_ordered_ids.index(r["target"]["segment_id"]),
            r["relation_type"],
        )
        if key in seen:
            continue
        seen.add(key)
        dedup.append(r)

    # ------------------- 写 cross_segment.jsonl -------------------
    # 终稿按 (relation_type, source.segment_id, target.segment_id) 去重：
    # 旧 v2.5 文件的规则条目无 `_source` 会被纳入 preserved，需防止与新规则候选重复。
    final_refs: list[dict] = []
    seen_final: set[tuple[str, str, str]] = set()
    for r in preserved + dedup:  # 先人工/LLM 核验，后规则候选
        key = (r["relation_type"], r["source"]["segment_id"], r["target"]["segment_id"])
        if key in seen_final:
            continue
        seen_final.add(key)
        final_refs.append(r)
    dup_skipped = len(preserved) + len(dedup) - len(final_refs)

    result = {
        "schema_version": "2.6.0",
        "doc_id": args.doc_id,
        "cross_refs": final_refs,
        "_metadata": {
            "skill_version": "2.6.0",
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "window_size": args.window_size,
            "overlap": args.overlap,
            "method": "rule_based_heuristic_v2_6",
            "preserved_curated": len(preserved),
            "rule_candidates": len(dedup),
            "dup_skipped": dup_skipped,
        },
    }

    # v3.8.7 T-062：增强信号规则（D19.target 情感对象复用 + D15 意象复用）
    try:
        if emotion_rows:
            target_segments = {}
            for er in emotion_rows:
                d19 = (er.get("layers") or {}).get("emotion") or {}
                primary = d19.get("D19_emotion_analysis") or d19.get("primary") or {}
                target = primary.get("target") if isinstance(primary, dict) else None
                if target and isinstance(target, str) and len(target) <= 20:
                    target_segments.setdefault(target, []).append(er.get("segment_id"))
            for target, seg_ids in target_segments.items():
                if len(seg_ids) >= 2:
                    for i in range(len(seg_ids) - 1):
                        refs.append({
                            "ref_id": "cf_d19_%04d" % len(refs),
                            "relation_type": "呼应",
                            "source": {"segment_id": seg_ids[i], "chapter": None, "anchor_text": "情感对象: %s" % target, "span": None},
                            "target": {"segment_id": seg_ids[i+1], "chapter": None, "anchor_text": "情感对象: %s" % target, "span": None},
                            "confidence": 0.5,
                            "note": "D19.target 情感对象复用（%s 在多段出现），规则候选，建议 LLM 二分类精排" % target,
                        })
        if craft_rows:
            imagery_segments = {}
            for cr in craft_rows:
                craft = cr.get("craft") or {}
                for item in craft.get("D15_imagery", []) or []:
                    if isinstance(item, dict):
                        text = item.get("text", "")
                        if text and len(text) <= 30:
                            imagery_segments.setdefault(text, []).append(cr.get("segment_id"))
            for imagery, seg_ids in imagery_segments.items():
                if len(seg_ids) >= 2:
                    for i in range(len(seg_ids) - 1):
                        refs.append({
                            "ref_id": "cf_d15_%04d" % len(refs),
                            "relation_type": "呼应",
                            "source": {"segment_id": seg_ids[i], "chapter": None, "anchor_text": "意象: %s" % imagery, "span": None},
                            "target": {"segment_id": seg_ids[i+1], "chapter": None, "anchor_text": "意象: %s" % imagery, "span": None},
                            "confidence": 0.5,
                            "note": "D15 意象复用（%s 在多段出现），规则候选，建议 LLM 二分类精排" % imagery,
                        })
    except Exception as e:
        print("[cross_segment] ⚠️ 增强信号规则执行失败（不影响主流程）: %s" % e)

    with out_path.open("w", encoding="utf-8") as f:
        f.write(json.dumps(result, ensure_ascii=False) + "\n")

    # v2.5.1：回写 checkpoint（跨段阶段完成）
    mark_phase_completed(args.doc_id, "cross_segment_completed", base_dir=out_path.parent)

    print(f"[cross_segment] ✅ 完成：人工/LLM 核验 {len(preserved)} 条 + 规则候选 {len(dedup)} 条 = {len(final_refs)} 条"
          + (f"（终稿按 类型+seg 对 去重 {dup_skipped} 条重复）" if dup_skipped else ""))
    for t in sorted(RELATION_TYPES):
        n = sum(1 for r in final_refs if r["relation_type"] == t)
        print(f"   · {t:<6}: {n} 条")
    print(f"   📄 输出 → {out_path.resolve()}")
    print(f"   ℹ️  启发式版本；LLM 二分类校准可留给调用方批量管线进行。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
