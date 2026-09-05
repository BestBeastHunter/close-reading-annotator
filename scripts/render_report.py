#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/render_report.py — 人类可读报告渲染 v2.7.0

支持 --format html / md。
零第三方依赖：HTML 纯手写（不需要任何 PyPI HTML 库），Markdown 直接输出。

用法：
  python scripts/render_report.py --doc-id moon_sixpence --format html
  python scripts/render_report.py --doc-id moon_sixpence --format md
"""

from __future__ import annotations

import argparse
import html
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from checkpoint import load_checkpoint, save_checkpoint, mark_phase_completed  # noqa: E402

# v2.5.1 修复 #1：Windows GBK 控制台 UnicodeEncodeError（emoji 打印崩溃）
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def _load_jsonl(p: Path) -> list[dict]:
    out: list[dict] = []
    if not p.is_file():
        return out
    with p.open("r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if s:
                try:
                    out.append(json.loads(s))
                except json.JSONDecodeError:
                    pass
    return out


def _emotion_core(row: dict | None) -> str:
    if not row:
        return ""
    try:
        return row["layers"]["structure"]["D04"]["core"]
    except Exception:
        return ""


def _emotion_intensity(row: dict | None) -> int:
    if not row:
        return 0
    try:
        return int(row["layers"]["structure"]["D04"]["intensity"])
    except Exception:
        return 0


def _pace(row: dict | None) -> int:
    if not row:
        return 0
    try:
        return int(row["layers"]["structure"]["D05"])
    except Exception:
        return 0


def _bar_html(value: int, max_v: int, color: str) -> str:
    ratio = max(0, min(1, value / max_v))
    return (
        f'<div style="background:#eee;width:160px;display:inline-block">'
        f'<div style="background:{color};height:14px;width:{int(ratio * 100)}%"></div>'
        f'</div> {value}/{max_v}'
    )


def _index_by_segment_id(rows: list[dict]) -> dict[str, dict]:
    return {r["segment_id"]: r for r in rows if r.get("segment_id")}


def _emotion_summaries(emotions: dict) -> list[dict]:
    """把 emotion.jsonl 行折叠成摘要行（MD/HTML 报告共用，保证两格式同源）。

    摘要含：段号/章节/主情感/极性/强度/对象/次级情感/段内弧/key_phrases。
    没有 D19 数据的行会被跳过。
    """
    rows: list[dict] = []
    for sid, e in emotions.items():
        d19 = ((e.get("layers") or {}).get("emotion") or {}).get("D19_emotion_analysis")
        if not d19:
            continue
        p = d19.get("primary") or {}
        tgt = d19.get("target") or {}
        sec = d19.get("secondary") or []
        arc = d19.get("arc")
        num = sid.rsplit("_seg_", 1)[-1] if "_seg_" in sid else sid
        sec_s = "、".join(str(x.get("emotion")) for x in sec[:2]) or "-"
        tgt_s = tgt.get("name") or "-"
        arc_s = "-"
        if arc:
            b, a = arc.get("before") or {}, arc.get("after") or {}
            arc_s = f"{b.get('emotion')}({b.get('intensity')})→{a.get('emotion')}({a.get('intensity')})"
        exp = d19.get("expression") or {}
        rows.append({
            "num": num,
            "chapter": e.get("chapter") or "-",
            "emotion": p.get("emotion") or "-",
            "polarity": p.get("polarity") or "-",
            "intensity": p.get("intensity") or "-",
            "target": tgt_s,
            "secondary": sec_s,
            "arc": arc_s,
            "key_phrases": exp.get("key_phrases") or [],
        })
    return rows


def render_html(doc_id: str, out_path: Path, segs: list[dict], structs: dict, interps: dict, craft: dict, refs: list[dict], ckpt: dict | None, emotions: dict | None = None) -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    parts: list[str] = []
    parts.append("<!doctype html><html><head><meta charset='utf-8'>")
    parts.append(f"<title>精读批注报告 · {html.escape(doc_id)}</title>")
    parts.append("<style>"
                 "body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;margin:24px;line-height:1.6;}"
                 "h1{color:#222;border-bottom:2px solid #444;}"
                 "h2{color:#333;border-bottom:1px solid #ccc;margin-top:2em;}"
                 "table{border-collapse:collapse;margin:12px 0;}"
                 "th,td{border:1px solid #bbb;padding:6px 10px;font-size:14px;vertical-align:top;}"
                 "th{background:#f2f2f2;}"
                 ".muted{color:#666;}"
                 ".seg-card{border:1px solid #ddd;border-radius:6px;padding:14px;margin:12px 0;background:#fafafa;}"
                 "</style></head><body>")
    parts.append(f"<h1>精读批注报告 · {html.escape(doc_id)}</h1>")
    parts.append(f"<p class='muted'>生成时间：{now}</p>")

    # 概览
    total = len(segs)
    if ckpt:
        parts.append("<h2>📊 批注进度概览</h2>")
        parts.append("<table><tr><th>指标</th><th>值</th></tr>")
        parts.append(f"<tr><td>片段总数</td><td>{ckpt.get('total_segments', total)}</td></tr>")
        done = len(ckpt.get("completed", []))
        parts.append(f"<tr><td>已完成片段</td><td>{done}/{total} ({(100*done/total if total else 0):.0f}%)</td></tr>")
        parts.append(f"<tr><td>跨段分析</td><td>{'✅' if ckpt.get('cross_segment_completed') else '⏳'}</td></tr>")
        parts.append(f"<tr><td>四层合并</td><td>{'✅' if ckpt.get('merged_completed') else '⏳'}</td></tr>")
        parts.append("</table>")

    # 结构层摘要表
    parts.append("<h2>🧱 Layer 1 结构层摘要</h2>")
    parts.append("<table><tr>"
                 "<th>seg</th><th>章节</th><th>D01 功能</th>"
                 "<th>D04 情绪/强度</th><th>D04 极性</th><th>D05 节奏</th>"
                 "<th>D07 视角</th></tr>")
    for s in segs:
        sid = s.get("segment_id", "")
        r = structs.get(sid)
        parts.append("<tr>")
        parts.append(f"<td>{html.escape(sid)}</td>")
        parts.append(f"<td>{html.escape(str(s.get('chapter','')))}</td>")
        try:
            parts.append(f"<td>{html.escape(r['layers']['structure']['D01'])}</td>")
        except Exception:
            parts.append("<td class='muted'>—</td>")
        em = _emotion_core(r)
        iv = _emotion_intensity(r)
        parts.append(f"<td>{html.escape(em)} {iv}</td>")
        try:
            parts.append(f"<td>{html.escape(str(r['layers']['structure']['D04'].get('polarity', '')))}</td>")
        except Exception:
            parts.append("<td class='muted'>—</td>")
        parts.append(f"<td>{_bar_html(_pace(r), 5, '#4a90e2')}</td>")
        try:
            parts.append(f"<td>{html.escape(r['layers']['structure']['D07']['type'])}</td>")
        except Exception:
            parts.append("<td class='muted'>—</td>")
        parts.append("</tr>")
    parts.append("</table>")

    # v2.7.0：HTML 报告新增 Layer 2.5 情感分析摘要（D19 · P4 Pass，与 MD 同源 _emotion_summaries）
    emo_rows = _emotion_summaries(emotions or {})
    if emo_rows:
        parts.append("<h2>🎭 Layer 2.5 情感分析摘要（D19 · P4 · v2.7.0）</h2>")
        parts.append("<table><tr><th>seg</th><th>章节</th><th>主情感</th><th>极性</th>"
                     "<th>强度</th><th>对象</th><th>次级</th><th>段内弧</th></tr>")
        for r in emo_rows:
            parts.append(
                f"<tr><td>{html.escape(str(r['num']))}</td>"
                f"<td>{html.escape(str(r['chapter']))}</td>"
                f"<td>{html.escape(str(r['emotion']))}</td>"
                f"<td>{html.escape(str(r['polarity']))}</td>"
                f"<td>{r['intensity']}</td>"
                f"<td>{html.escape(str(r['target']))}</td>"
                f"<td>{html.escape(str(r['secondary']))}</td>"
                f"<td>{html.escape(str(r['arc']))}</td></tr>"
            )
        parts.append("</table>")
        parts.append("<p><b>情感关键短语（D19.expression.key_phrases）</b></p>")
        parts.append("<ul>")
        for r in emo_rows:
            if not r["key_phrases"]:
                continue
            parts.append(f"<li>（seg_{r['num']}）{html.escape(' ／ '.join(r['key_phrases']))}</li>")
        parts.append("</ul>")

    # 跨段关系
    if refs:
        parts.append("<h2>🔗 Layer 4 跨段关系候选（启发式）</h2>")
        parts.append("<table><tr><th>#</th><th>类型</th><th>起点</th><th>终点</th><th>说明</th></tr>")
        for i, r in enumerate(refs, 1):
            parts.append(f"<tr><td>{i}</td>"
                         f"<td>{html.escape(r.get('relation_type',''))}</td>"
                         f"<td>{html.escape(r.get('source',{}).get('segment_id',''))}</td>"
                         f"<td>{html.escape(r.get('target',{}).get('segment_id',''))}</td>"
                         f"<td>{html.escape(str(r.get('note','')))}</td></tr>")
        parts.append("</table>")
    else:
        parts.append("<h2>🔗 Layer 4 跨段关系</h2><p class='muted'>暂无可展示的跨段关系。</p>")

    # 逐段展示
    parts.append("<h2>📄 逐段详情（前 20 段）</h2>")
    preview = segs[:20]
    for s in preview:
        sid = s.get("segment_id", "")
        parts.append(f"<div class='seg-card'><h3>{html.escape(sid)} · {html.escape(str(s.get('chapter','')))}</h3>")
        ts = s.get("text_span", {})
        text = ts.get("text", "") if isinstance(ts, dict) else ""
        parts.append(f"<p>{html.escape(text[:400])}{'…' if len(text) > 400 else ''}</p>")
        r = interps.get(sid)
        if r:
            themes = _themes_of(r)
            if themes:
                parts.append(f"<p><b>D09 主题：</b> {html.escape('、'.join(themes))}</p>")
        c = craft.get(sid)
        if c and c.get("craft") and c["craft"].get("D13_golden_lines"):
            items = c["craft"]["D13_golden_lines"][:3]
            parts.append("<p><b>D13 佳句（前3）：</b></p><ul>")
            for it in items:
                parts.append(f"<li>{html.escape(it.get('text',''))} — <i>{html.escape(it.get('reason',''))}</i></li>")
            parts.append("</ul>")
        parts.append("</div>")

    parts.append("<p class='muted'>—— Report rendered by close-reading-annotator v2.7.0 ——</p>")
    parts.append("</body></html>")
    out_path.write_text("".join(parts), encoding="utf-8")


def _themes_of(r: dict) -> list[str]:
    try:
        return list(r["layers"]["interpretation"]["D09"] or [])
    except Exception:
        return []


def render_md(doc_id: str, out_path: Path, segs: list[dict], structs: dict, interps: dict, craft: dict, refs: list[dict], ckpt: dict | None, emotions: dict | None = None) -> None:
    lines: list[str] = []
    lines.append(f"# 精读批注报告 · {doc_id}")
    lines.append("")
    lines.append(f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")
    if ckpt:
        done = len(ckpt.get("completed", []))
        total = ckpt.get("total_segments", len(segs))
        lines.append("## 📊 进度概览")
        lines.append("")
        lines.append(f"- 片段总数：{total}")
        lines.append(f"- 已完成片段：{done}/{total}")
        lines.append(f"- 跨段分析：{'✅' if ckpt.get('cross_segment_completed') else '⏳'}")
        lines.append(f"- 四层合并：{'✅' if ckpt.get('merged_completed') else '⏳'}")
        lines.append("")
    lines.append("## 🧱 Layer 1 结构层摘要")
    lines.append("")
    lines.append("| seg | 章节 | D01 | D04情绪 | D04强度 | D04极性 | D05节奏 | D07视角 |")
    lines.append("|-----|------|-----|---------|---------|---------|---------|---------|")
    for s in segs:
        sid = s.get("segment_id", "")
        r = structs.get(sid)
        d01 = d04 = d07 = pol = "-"
        iv = 0
        pv = 0
        if r:
            try:
                d01 = r["layers"]["structure"]["D01"]
                d04 = r["layers"]["structure"]["D04"]["core"]
                iv = int(r["layers"]["structure"]["D04"]["intensity"])
                pol = r["layers"]["structure"]["D04"].get("polarity", "-")
                pv = int(r["layers"]["structure"]["D05"])
                d07 = r["layers"]["structure"]["D07"]["type"]
            except Exception:
                pass
        lines.append(f"| {sid} | {s.get('chapter','')} | {d01} | {d04} | {iv} | {pol} | {pv} | {d07} |")

    # v2.5.1：MD 报告补齐 Layer 2 / Layer 3 摘要（之前 HTML 有、MD 缺失）
    if interps:
        theme_counter: dict[str, int] = {}
        rel_counter: dict[str, int] = {}
        for sid, r in interps.items():
            for t in _themes_of(r):
                theme_counter[t] = theme_counter.get(t, 0) + 1
            nr = r.get("layers", {}).get("interpretation", {}).get("narrator_reliability")
            if nr:
                rel_counter[nr] = rel_counter.get(nr, 0) + 1
        if theme_counter:
            lines.append("")
            lines.append("## 🔍 Layer 2 阐释层摘要")
            lines.append("")
            lines.append("**Top 主题标签（D09 跨段频次）**")
            lines.append("")
            for t, c in sorted(theme_counter.items(), key=lambda x: -x[1])[:10]:
                lines.append(f"- {t}（{c} 段）")
        if rel_counter:
            lines.append("")
            lines.append("**叙述者可靠性分布**")
            lines.append("")
            for nr, c in rel_counter.items():
                lines.append(f"- {nr}：{c} 段")

    # v2.7.0：MD/HTML 报告新增 Layer 2.5 情感分析摘要（D19 · P4 Pass，两格式同源）
    emo_rows = _emotion_summaries(emotions or {})
    if emo_rows:
        lines.append("")
        lines.append("## 🎭 Layer 2.5 情感分析摘要（D19 · P4 · v2.7.0）")
        lines.append("")
        lines.append("| seg | 章节 | 主情感 | 极性 | 强度 | 对象 | 次级 | 段内弧 |")
        lines.append("|-----|------|--------|------|------|------|------|--------|")
        for r in emo_rows:
            lines.append(
                f"| {r['num']} | {r['chapter']} | {r['emotion']} "
                f"| {r['polarity']} | {r['intensity']} "
                f"| {r['target']} | {r['secondary']} | {r['arc']} |"
            )
        lines.append("")
        lines.append("**情感关键短语（D19.expression.key_phrases）**")
        lines.append("")
        for r in emo_rows:
            if not r["key_phrases"]:
                continue
            lines.append(f"- （seg_{r['num']}）{' ／ '.join(r['key_phrases'])}")

    if craft:
        golden: list[tuple[str, dict]] = []
        rhet_counter: dict[str, int] = {}
        for sid, c in craft.items():
            cr = c.get("craft") or {}
            for it in cr.get("D13_golden_lines", []) or []:
                golden.append((sid, it))
            for it in cr.get("D14_rhetoric", []) or []:
                rt = it.get("type", "")
                if rt:
                    rhet_counter[rt] = rhet_counter.get(rt, 0) + 1
        if rhet_counter:
            lines.append("")
            lines.append("**修辞手法统计（D14）**")
            lines.append("")
            for rt, c in sorted(rhet_counter.items(), key=lambda x: -x[1]):
                lines.append(f"- {rt}：{c} 处")
        if golden:
            lines.append("")
            lines.append("**D13 佳句 Top 10（按 quality_score 降序）**")
            lines.append("")
            golden.sort(key=lambda x: -(x[1].get("quality_score", 0) or 0))
            for sid, it in golden[:10]:
                lines.append(f"- （{sid}）{it.get('text','')} —— {it.get('reason','')}（评分 {it.get('quality_score','?')}）")

    if refs:
        lines.append("")
        lines.append("## 🔗 Layer 4 跨段关系候选")
        lines.append("")
        lines.append("| # | 类型 | 起点 | 终点 | 说明 |")
        lines.append("|---|------|------|------|------|")
        for i, r in enumerate(refs, 1):
            lines.append(
                f"| {i} | {r.get('relation_type','')} "
                f"| {r.get('source',{}).get('segment_id','')} "
                f"| {r.get('target',{}).get('segment_id','')} "
                f"| {r.get('note','')} |"
            )
    out_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    p = argparse.ArgumentParser(description="【精读批注 v2.7 Phase 5】人类可读报告渲染（HTML/Markdown，含 Layer 2.5 情感摘要）")
    p.add_argument("--doc-id", required=True)
    p.add_argument("--segments", default=None, help="segments.jsonl（默认在 <cwd>/<doc_id>_segments.jsonl）")
    p.add_argument("--format", choices=["html", "md"], default="html")
    p.add_argument("--output-dir", "--output", dest="output", default=None, help="输出文件（默认 <doc_id>_report.html/.md）")
    args = p.parse_args()

    cwd = Path.cwd()
    seg_path = Path(args.segments) if args.segments else (cwd / f"{doc_id}_segments.jsonl")
    if not seg_path.is_file():
        print(f"❌ segments 不存在：{seg_path}", file=sys.stderr)
        return 2

    segs = _load_jsonl(seg_path)
    base_dir = seg_path.parent
    doc_id = args.doc_id

    structs = _index_by_segment_id(_load_jsonl(base_dir / f"{doc_id}_structure.jsonl"))
    interps = _index_by_segment_id(_load_jsonl(base_dir / f"{doc_id}_interpretation.jsonl"))
    craft = _index_by_segment_id(_load_jsonl(base_dir / f"{doc_id}_craft.jsonl"))
    emotions: dict = {}
    emo_path = base_dir / f"{doc_id}_emotion.jsonl"
    if emo_path.is_file():
        emotions = _index_by_segment_id(_load_jsonl(emo_path))
    cross_refs: list[dict] = []
    cross_path = base_dir / f"{doc_id}_cross_segment.jsonl"
    if cross_path.is_file():
        with cross_path.open("r", encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if s:
                    try:
                        cross_refs = json.loads(s).get("cross_refs", [])
                        break
                    except json.JSONDecodeError:
                        pass
    ckpt = load_checkpoint(doc_id, base_dir)

    if args.format == "html":
        out_path = Path(args.output) if args.output else (cwd / f"{doc_id}_report.html")
        render_html(doc_id, out_path, segs, structs, interps, craft, cross_refs, ckpt, emotions)
    else:
        out_path = Path(args.output) if args.output else (cwd / f"{doc_id}_report.md")
        render_md(doc_id, out_path, segs, structs, interps, craft, cross_refs, ckpt, emotions)

    if ckpt is not None:
        ckpt["render_report_completed"] = True
        save_checkpoint(ckpt, base_dir)
    print(f"[render_report] ✅ 报告生成 → {out_path.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
