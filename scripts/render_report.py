#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/render_report.py — 人类可读报告渲染 v3.15.1（报告重构：T-133~T-136）

支持 --format html / md。零第三方依赖：HTML 纯手写（含内联 SVG 可视化），
Markdown 直接输出。

v3.15.1 重构要点：
  - T-133 报告流程：新增 --agg-dir 显式指定聚合产物目录（默认 <segments 父目录>/aggregation）；
    聚合层跑完后可直接重跑本脚本重生成报告（幂等）；MD 报告也输出聚合分析章节。
  - T-134 四层完整呈现：修复 _emotion_summaries 对 v2.8 直接格式（layers.emotion.*）的兼容
    （此前只认 v2.7 嵌套格式 → 真实产物 L2.5 摘要为空）；HTML 逐段详情改为全量折叠展示
    （不再截断前 20 段），每段含四层全部字段；新增"切分质量"小节（pollution_warning）。
  - T-135 聚合分析完整集成：HTML/MD 均输出聚合 10 模块章节（story_type / narrative_structure /
    character_arcs / entity_graph / scene_graph / causal_graph / object_chains /
    character_network / character_biographies / writing_techniques）。
  - T-136 可视化（零依赖 SVG）：情感强度曲线（D04）、节奏曲线（D05）、角色情感弧（D19，
    top 角色）、HTML 目录（TOC）。无第三方 JS/CDN。

用法：
  python scripts/render_report.py --doc-id moon_sixpence --format html
  python scripts/render_report.py --doc-id moon_sixpence --format md --agg-dir <out>/aggregation
"""

from __future__ import annotations

import argparse
import html
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from checkpoint import load_checkpoint, save_checkpoint  # noqa: E402

# v2.5.1 修复 #1：Windows GBK 控制台 UnicodeEncodeError（emoji 打印崩溃）
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

AGG_FILES = [
    ("story_type", "{doc}_story_metadata.json"),
    ("narrative_structure", "{doc}_narrative_structure.json"),
    ("character_arcs", "{doc}_character_arcs.json"),
    ("entity_graph", "{doc}_entity_graph.json"),
    ("scene_graph", "{doc}_scene_graph.json"),
    ("causal_graph", "{doc}_causal_graph.json"),
    ("event_sequence", "{doc}_event_sequence.json"),
    ("object_chains", "{doc}_object_chains.json"),
    ("character_network", "{doc}_character_network.json"),
    ("character_biographies", "{doc}_character_biographies.json"),
    ("writing_techniques", "{doc}_writing_techniques.json"),
    ("story_graph", "{doc}_story_graph.json"),
]

# v3.17.0：适配器三格式摘要（text2story/yarn/ncp，位于聚合产物目录）
ADAPTER_FORMATS = (
    ("text2story", "text2story"),
    ("yarn", "yarn"),
    ("ncp", "ncp"),
)


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


def _load_aggregation(agg_dir: Path, doc_id: str) -> dict:
    """读取聚合层产物（T-133：目录可来自 --agg-dir，默认 <segments 父目录>/aggregation）。

    缺失的模块返回空 dict（不阻塞报告生成）。
    """
    agg: dict = {}
    if agg_dir is None or not agg_dir.exists():
        return agg
    for key, fname in AGG_FILES:
        fpath = agg_dir / fname.format(doc=doc_id)
        if fpath.exists():
            try:
                agg[key] = json.loads(fpath.read_text(encoding="utf-8"))
            except Exception:
                pass
    # v3.17.0：适配器三格式（text2story/yarn/ncp）摘要——双路径探测：
    # 根目录（新 run_pipeline Phase 5 输出）与 adapters/ 子目录（v3.16.x 旧产物）兼容
    adapters_summary = []
    for fmt_key, _label in ADAPTER_FORMATS:
        fpath = agg_dir / f"{doc_id}_{fmt_key}.json"
        if not fpath.exists():
            fpath = agg_dir / "adapters" / f"{doc_id}_{fmt_key}.json"
        if fpath.exists():
            try:
                data = json.loads(fpath.read_text(encoding="utf-8"))
                adapters_summary.append({
                    "format": fmt_key,
                    "file": fpath.name,
                    "summary": data if isinstance(data, (dict, list)) else {"note": str(data)[:200]},
                })
            except Exception:
                pass
    if adapters_summary:
        agg["adapters"] = {"formats": adapters_summary}
    return agg


# ========================================================================
# 数据访问辅助（v2.8 直接格式 + v2.7 嵌套格式双兼容）
# ========================================================================

def _layer_of(row: dict, layer: str) -> dict:
    """从行对象取指定层内容（兼容 layers.<layer> 嵌套 / merged 顶层 / 顶层同名键）。"""
    if not isinstance(row, dict):
        return {}
    layers = row.get("layers")
    if isinstance(layers, dict) and isinstance(layers.get(layer), dict):
        return layers[layer]
    if isinstance(row.get(layer), dict):
        return row[layer]
    return {}


def _structure_of(row: dict) -> dict:
    return _layer_of(row, "structure")


def _interpretation_of(row: dict) -> dict:
    return _layer_of(row, "interpretation")


def _emotion_of(row: dict) -> dict:
    """emotion 行内容：v2.8 直接格式 layers.emotion.*；v2.7 嵌套 D19_emotion_analysis 兼容。"""
    emo = _layer_of(row, "emotion")
    if isinstance(emo, dict):
        d19 = emo.get("D19_emotion_analysis")
        if isinstance(d19, dict):
            return d19
        return emo
    return {}


def _craft_of(row: dict) -> dict:
    return _layer_of(row, "craft")


# ========================================================================
# SVG 可视化（T-136，零第三方依赖）
# ========================================================================

_SVG_W = 1000
_SVG_H = 240
_SVG_X0 = 44
_SVG_X1 = 984
_SVG_Y0 = 16
_SVG_Y1 = 206
_COLORS = ["#4a90e2", "#e74c3c", "#2ecc71", "#f39c12", "#9b59b6", "#1abc9c", "#e67e22", "#34495e"]


def _svg_axes(y_max: int, y_label: str) -> list[str]:
    parts = [
        f'<line x1="{_SVG_X0}" y1="{_SVG_Y1}" x2="{_SVG_X1}" y2="{_SVG_Y1}" stroke="#999" stroke-width="1"/>',
        f'<line x1="{_SVG_X0}" y1="{_SVG_Y0}" x2="{_SVG_X0}" y2="{_SVG_Y1}" stroke="#999" stroke-width="1"/>',
    ]
    for tick in range(y_max + 1):
        y = _SVG_Y1 - (_SVG_Y1 - _SVG_Y0) * tick / max(y_max, 1)
        parts.append(f'<line x1="{_SVG_X0}" y1="{y:.1f}" x2="{_SVG_X1}" y2="{y:.1f}" stroke="#eee" stroke-width="1"/>')
        parts.append(f'<text x="{_SVG_X0 - 6}" y="{y + 4:.1f}" font-size="10" fill="#888" text-anchor="end">{tick}</text>')
    parts.append(f'<text x="{_SVG_X0}" y="{_SVG_Y0 - 6}" font-size="11" fill="#555">{html.escape(y_label)}</text>')
    return parts


def _svg_polyline(values: list[float | int | None], y_max: int, color: str, label: str, radius: float = 3.0) -> str:
    """画一条折线。values 中 None 表示断点（跳过连线）。返回 SVG 片段字符串。"""
    n = len(values)
    if n < 2:
        return ""
    pts: list[str] = []
    last_pt: tuple[float, float] | None = None
    for i, v in enumerate(values):
        if v is None:
            last_pt = None
            continue
        x = _SVG_X0 + (_SVG_X1 - _SVG_X0) * i / max(n - 1, 1)
        y = _SVG_Y1 - (_SVG_Y1 - _SVG_Y0) * float(v) / max(y_max, 1)
        pts.append(f'{x:.1f},{y:.1f}')
        last_pt = (x, y)
    if len(pts) < 2:
        return ""
    out = [
        f'<polyline points="{" ".join(pts)}" fill="none" stroke="{color}" stroke-width="2" stroke-linejoin="round"/>'
    ]
    # 数据点
    for i, v in enumerate(values):
        if v is None:
            continue
        x = _SVG_X0 + (_SVG_X1 - _SVG_X0) * i / max(n - 1, 1)
        y = _SVG_Y1 - (_SVG_Y1 - _SVG_Y0) * float(v) / max(y_max, 1)
        out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{radius}" fill="{color}"/>')
    out.append(
        f'<text x="{_SVG_X0}" y="{_SVG_Y1 + 18}" font-size="12" fill="{color}" font-weight="bold">'
        f'{html.escape(label)}</text>'
    )
    return "".join(out)


def svg_intensity_curve(segs: list[dict], structs: dict) -> str:
    """D04.intensity 情感强度曲线（全段）。"""
    values: list[int | None] = []
    for s in segs:
        r = structs.get(s.get("segment_id", ""))
        try:
            values.append(int(_structure_of(r)["D04"]["intensity"]))
        except Exception:
            values.append(None)
    if len(values) < 2 or all(v is None for v in values):
        return ""
    return (
        f'<svg viewBox="0 0 {_SVG_W} {_SVG_H + 26}" width="100%" style="max-width:1000px;border:1px solid #eee;'
        f'border-radius:6px;background:#fff">'
        + "".join(_svg_axes(10, "情感强度 (D04, 1-10)"))
        + _svg_polyline(values, 10, "#e74c3c", "情感强度", radius=3.0)
        + "</svg>"
    )


def svg_pace_curve(segs: list[dict], structs: dict) -> str:
    """D05 节奏曲线（全段）。"""
    values: list[int | None] = []
    for s in segs:
        r = structs.get(s.get("segment_id", ""))
        try:
            values.append(int(_structure_of(r)["D05"]))
        except Exception:
            values.append(None)
    if len(values) < 2 or all(v is None for v in values):
        return ""
    return (
        f'<svg viewBox="0 0 {_SVG_W} {_SVG_H + 26}" width="100%" style="max-width:1000px;border:1px solid #eee;'
        f'border-radius:6px;background:#fff">'
        + "".join(_svg_axes(5, "节奏 (D05, 1-5)"))
        + _svg_polyline(values, 5, "#4a90e2", "节奏", radius=3.0)
        + "</svg>"
    )


def svg_character_emotion_arc(emotions: dict, segs: list[dict], top_n: int = 5) -> str:
    """D19 角色情感弧：按 target.name 聚合，top 角色各一条强度折线。"""
    # 段序映射
    seg_order = {s.get("segment_id", ""): i for i, s in enumerate(segs)}
    # 角色 → [(seg_idx, intensity)]
    per_char: dict[str, list[tuple[int, int]]] = {}
    for sid, e in emotions.items():
        d19 = _emotion_of(e)
        p = d19.get("primary") or {}
        tgt = (d19.get("target") or {}).get("name")
        if not tgt or sid not in seg_order:
            continue
        try:
            iv = int(p.get("intensity"))
        except Exception:
            continue
        per_char.setdefault(tgt, []).append((seg_order[sid], iv))
    ranked = sorted(per_char.items(), key=lambda kv: -len(kv[1]))[:top_n]
    if not ranked or len(segs) < 2:
        return ""
    n = len(segs)
    parts: list[str] = ["<svg", f' viewBox="0 0 {_SVG_W} {_SVG_H + 26}" width="100%"',
                        ' style="max-width:1000px;border:1px solid #eee;border-radius:6px;background:#fff">']
    parts.extend(_svg_axes(10, "角色情感强度 (D19, 1-10)"))
    for ci, (name, pts) in enumerate(ranked):
        values: list[int | None] = [None] * n
        for idx, iv in pts:
            values[idx] = iv
        parts.append(_svg_polyline(values, 10, _COLORS[ci % len(_COLORS)], f"{name}（{len(pts)} 段）", radius=2.5))
    parts.append("</svg>")
    return "".join(parts)


# ========================================================================
# 文本摘要辅助（HTML / MD 共用，保证两格式同源）
# ========================================================================

def _index_by_segment_id(rows: list[dict]) -> dict[str, dict]:
    return {r["segment_id"]: r for r in rows if r.get("segment_id")}


def _emotion_core(row: dict | None) -> str:
    if not row:
        return ""
    try:
        return _structure_of(row)["D04"]["core"]
    except Exception:
        return ""


def _emotion_intensity(row: dict | None) -> int:
    if not row:
        return 0
    try:
        return int(_structure_of(row)["D04"]["intensity"])
    except Exception:
        return 0


def _pace(row: dict | None) -> int:
    if not row:
        return 0
    try:
        return int(_structure_of(row)["D05"])
    except Exception:
        return 0


def _bar_html(value: int, max_v: int, color: str) -> str:
    ratio = max(0, min(1, value / max_v))
    return (
        f'<div style="background:#eee;width:160px;display:inline-block">'
        f'<div style="background:{color};height:14px;width:{int(ratio * 100)}%"></div>'
        f'</div> {value}/{max_v}'
    )


def _emotion_summaries(emotions: dict) -> list[dict]:
    """把 emotion.jsonl 行折叠成摘要行（MD/HTML 报告共用，保证两格式同源）。

    v3.15.1 T-134：兼容 v2.8 直接格式（layers.emotion.*）与 v2.7 嵌套格式
    （layers.emotion.D19_emotion_analysis.*）——此前只认嵌套格式，导致真实
    产物（v2.8+）的 L2.5 摘要为空。
    摘要含：段号/章节/主情感/极性/强度/对象/次级情感/段内弧/key_phrases。
    """
    rows: list[dict] = []
    for sid, e in emotions.items():
        d19 = _emotion_of(e)
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
            "segment_id": sid,
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


def _themes_of(r: dict) -> list[str]:
    try:
        return list(_interpretation_of(r).get("D09") or [])
    except Exception:
        return []


def _seg_pollution_stats(segs: list[dict]) -> dict:
    """切分质量统计（T-134）：兜底切分段数 / pollution_warning 计数。"""
    polluted = [s for s in segs if s.get("pollution_warning")]
    return {"total": len(segs), "polluted": len(polluted), "samples": [s.get("pollution_warning") for s in polluted[:5]]}


# ========================================================================
# 聚合层渲染
# ========================================================================

def _story_type_rows(st: dict) -> list[tuple[str, str]]:
    """故事概览 → (标签, 值) 行列表。"""
    md = st.get("story_metadata", {})
    summary = st.get("summary", {})
    rows = [
        ("题材类型", str(md.get("genre", {}).get("primary", "未知"))),
        ("叙事风格", str(md.get("narrative_style", {}).get("type", "未知"))),
        ("时间结构", str(md.get("time_structure", {}).get("type", "未知"))),
        ("情感曲线", str(md.get("emotion_arc", {}).get("pattern", "未知"))),
        ("叙事节奏", str(md.get("pace", {}).get("type", "未知"))),
        ("阅读体验", str(md.get("reader_experience", {}).get("primary", "未知"))),
    ]
    one = summary.get("one_line", "")
    if one:
        rows.append(("一句话摘要", str(one)))
    return rows


def _narrative_structure_rows(ns: dict) -> list[tuple[str, str]]:
    freytag = ns.get("freytag_pyramid", {})
    focal = ns.get("genette_focalization", {})
    timeline = ns.get("narrative_timeline", {})
    ktp = freytag.get("key_turning_points", {})
    rows = [
        ("结构健康度", str(freytag.get("structure_health", "未知"))),
        ("激励事件", str(ktp.get("inciting_incident_segment", "未定位"))),
        ("高潮", str(ktp.get("climax_segment", "未定位"))),
        ("结局", str(ktp.get("resolution_segment", "未定位"))),
        ("主导聚焦", str(focal.get("dominant_focalization", "未知"))),
        ("聚焦复杂度", str(focal.get("complexity", "未知"))),
        ("时间结构", str(timeline.get("time_structure", "未知"))),
    ]
    return rows


def _render_aggregation_md(agg: dict, doc_id: str) -> list[str]:
    """MD 版聚合分析章节（T-135）。返回 Markdown 行列表。"""
    if not agg:
        return ["## 📊 聚合分析", "", "未运行聚合分析（需先跑 aggregation/ 10 脚本），本报告不含全局叙事分析。", ""]
    lines = ["## 📊 聚合分析（全局叙事）", ""]
    if "story_type" in agg:
        lines.append("### 🎭 故事概览")
        lines.append("")
        for k, v in _story_type_rows(agg["story_type"]):
            lines.append(f"- **{k}**：{v}")
        lines.append("")
    if "narrative_structure" in agg:
        lines.append("### 🏗️ 叙事结构")
        lines.append("")
        for k, v in _narrative_structure_rows(agg["narrative_structure"]):
            lines.append(f"- **{k}**：{v}")
        lines.append("")
    if "entity_graph" in agg:
        eg = agg["entity_graph"]
        lines.append("### 🧑🤝🧑 实体图谱")
        lines.append("")
        lines.append(f"- 实体总数：{eg.get('total_entities', 0)}，总提及：{eg.get('total_mentions', 0)}")
        for e in eg.get("entities", [])[:10]:
            lines.append(f"  - {e.get('canonical_name','?')}：{e.get('occurrence_count',0)} 次 / {e.get('segment_count',0)} 段")
        lines.append("")
    if "scene_graph" in agg:
        sg = agg["scene_graph"]
        lines.append("### 🏞️ 场景图")
        lines.append("")
        lines.append(f"- 场景总数：{sg.get('total_scenes', 0)}")
        for sc in sg.get("scenes", [])[:10]:
            _loc = sc.get('primary_space') or '?'
            _cnt = sc.get('segment_count', 0)
            _fn = sc.get('primary_function') or '?'
            _chars = "、".join(c.get('name', '') for c in (sc.get('characters_present') or [])[:3]) or '无'
            lines.append(f"  - {sc.get('scene_id','?')}：{_loc}（{_cnt} 段，{_fn}）出场：{_chars}")
        lines.append("")
    if "character_arcs" in agg:
        ca = agg["character_arcs"]
        arcs = ca.get("character_arcs", [])
        lines.append("### 👥 角色弧线")
        lines.append("")
        lines.append(f"- 角色数：{len(arcs)}")
        for c in arcs[:10]:
            name = c.get("canonical_name", "未知")
            at = c.get("arc_classification", {}).get("arc_type", "未知")
            cov = c.get("coverage_rate", 0)
            lines.append(f"  - {name}：弧线 {at}，覆盖率 {cov:.0%}")
        lines.append("")
    if "character_network" in agg:
        cn = agg["character_network"]
        lines.append("### 🕸️ 人物关系网络")
        lines.append("")
        lines.append(f"- 关系边数：{cn.get('total_edges', 0)}，社区数：{len(cn.get('communities', []))}")
        for ed in cn.get("edges", [])[:10]:
            lines.append(f"  - {ed.get('source','?')} —({ed.get('relation','')})→ {ed.get('target','?')}（强度 {ed.get('strength',0):.2f}）")
        lines.append("")
    if "causal_graph" in agg:
        cg = agg["causal_graph"]
        stats = cg.get("statistics", {})
        lines.append("### ⛓️ 因果图")
        lines.append("")
        lines.append(f"- 因果边：{stats.get('total_edges', 0)}，因果链：{stats.get('total_chains', 0)}，"
                     f"核心事件：{stats.get('core_event_count', 0)}")
        for ch in cg.get("chains", [])[:5]:
            lines.append(f"  - 链 {ch.get('chain_id','?')}：{ch.get('description','')[:60]}")
        lines.append("")
    if "event_sequence" in agg:
        es = agg["event_sequence"]
        stats = es.get("statistics", {})
        lines.append("### 📅 事件序列")
        lines.append("")
        lines.append(f"- 事件总数：{es.get('total_events', 0)}，核心 {stats.get('core_event_count', 0)} / "
                     f"卫星 {stats.get('satellite_event_count', 0)}，转折 {stats.get('turning_point_count', 0)}")
        for ev in es.get("event_sequence", [])[:15]:
            _hl = (ev.get("hierarchy") or {}).get("level") or "—"
            _sal = (ev.get("hierarchy") or {}).get("salience_score")
            _sal_s = f"，显赫度 {_sal:.2f}" if isinstance(_sal, (int, float)) else ""
            _part = "、".join(ev.get("participants") or ev.get("present_characters") or []) or "无"
            lines.append(f"  - **{ev.get('event_id','?')}**（{_hl}{_sal_s}）：{str(ev.get('description',''))[:50]}"
                         f"〔{ev.get('segment_id','?')} / {ev.get('scene_id') or '无场景'} / 人物：{_part}〕")
        lines.append("")
    if "object_chains" in agg:
        oc = agg["object_chains"]
        stats = oc.get("statistics", {})
        lines.append("### 📦 物件链")
        lines.append("")
        lines.append(f"- 物件链数：{stats.get('total_chains', 0)}")
        for ch in oc.get("chains", [])[:10]:
            lines.append(f"  - {ch.get('object_name','?')}（{ch.get('object_type','')}）：出现 {ch.get('occurrence_count',0)} 次")
        lines.append("")
    if "character_biographies" in agg:
        cb = agg["character_biographies"]
        bios = cb.get("biographies", {})
        if isinstance(bios, dict):
            items = list(bios.items())
        else:
            items = [(b.get("name", "?"), b) for b in (bios if isinstance(bios, list) else [])]
        lines.append("### 📖 人物传记")
        lines.append("")
        lines.append(f"- 传记数：{len(items)}")
        for name, bio in items[:10]:
            bio_inner = bio.get("biography", bio) if isinstance(bio, dict) else {}
            summary = bio_inner.get("summary", "")
            lines.append(f"  - **{name}**：{summary}")
        lines.append("")
    if "writing_techniques" in agg:
        wt = agg["writing_techniques"]
        lines.append("### ✍️ 叙事技法")
        lines.append("")
        _oa = wt.get("overall_assessment", {})
        lines.append(f"- 技法实例：{_oa.get('total_technique_instances', 0)}，密度：{_oa.get('technique_density_per_segment', 0):.2f}/段，风格：{_oa.get('writing_style', '?')}")
        for _t in _oa.get("dominant_techniques", [])[:5]:
            if isinstance(_t, list) and len(_t) == 2:
                lines.append(f"  - {_t[0]}：{_t[1]} 例")
            elif isinstance(_t, str):
                lines.append(f"  - {_t}")
        for t in wt.get("techniques", [])[:10]:
            lines.append(f"  - {t.get('technique','')}：{t.get('count',0)} 处")
        lines.append("")
    if "story_graph" in agg:
        sg = agg["story_graph"]
        gs = sg.get("global_statistics", {})
        lines.append("### 🧩 故事图（全局合并）")
        lines.append("")
        lines.append(f"- 实体 {gs.get('total_entities', 0)} / 场景 {gs.get('total_scenes', 0)} / "
                     f"角色 {gs.get('total_characters', 0)} / 因果边 {gs.get('total_causal_edges', 0)} / "
                     f"物件链 {gs.get('total_object_chains', 0)}")
        gtype = sg.get("graph_type") or sg.get("meta", {}).get("graph_type", "")
        if gtype:
            lines.append(f"- 图谱类型：{gtype}")
        lines.append("")
    if "adapters" in agg:
        lines.append("### 🔌 适配器输出（text2story / YARN / NCP）")
        lines.append("")
        for fmt in agg["adapters"].get("formats", []):
            fname = fmt.get("file", "?")
            lines.append(f"- **{fmt.get('format')}**：`{fname}`")
        lines.append("")
    return lines


def _render_aggregation_html(agg: dict, doc_id: str) -> str:
    """渲染聚合层 HTML 章节（T-135：10 模块全量）。"""
    if not agg:
        return ('<div class="section"><h2>📊 聚合分析</h2>'
                '<p style="color:#888">未运行聚合分析（需先跑 aggregation/ 10 脚本），'
                '如需全局叙事分析请在聚合层完成后重跑本脚本（--agg-dir 指定聚合产物目录）。</p></div>')
    parts = ['<div class="section"><h2 id="agg">📊 聚合分析（全局叙事）</h2>']

    def _table(rows: list[tuple[str, str]]) -> None:
        parts.append('<table border="1" cellpadding="6" style="border-collapse:collapse">')
        for k, v in rows:
            parts.append(f'<tr><td><b>{html.escape(k)}</b></td><td>{html.escape(v)}</td></tr>')
        parts.append('</table>')

    if "story_type" in agg:
        parts.append('<h3 id="agg-story">🎭 故事概览</h3>')
        _table(_story_type_rows(agg["story_type"]))

    if "narrative_structure" in agg:
        parts.append('<h3 id="agg-narr">🏗️ 叙事结构</h3>')
        _table(_narrative_structure_rows(agg["narrative_structure"]))

    if "entity_graph" in agg:
        eg = agg["entity_graph"]
        parts.append(f'<h3 id="agg-entity">🧑‍🤝‍🧑 实体图谱（{eg.get("total_entities", 0)} 实体 / '
                     f'{eg.get("total_mentions", 0)} 提及）</h3>')
        parts.append('<table border="1" cellpadding="6" style="border-collapse:collapse">')
        parts.append('<tr><th>实体</th><th>性别</th><th>提及</th><th>出场段</th><th>别名</th></tr>')
        for e in eg.get("entities", [])[:15]:
            parts.append(f'<tr><td>{html.escape(str(e.get("canonical_name","")))}</td>'
                         f'<td>{html.escape(str(e.get("gender","")))}</td>'
                         f'<td>{e.get("occurrence_count",0)}</td>'
                         f'<td>{e.get("segment_count",0)}</td>'
                         f'<td>{html.escape("、".join(e.get("aliases", [])[:5]))}</td></tr>')
        parts.append('</table>')

    if "scene_graph" in agg:
        sg = agg["scene_graph"]
        parts.append(f'<h3 id="agg-scene">🏞️ 场景图（{sg.get("total_scenes", 0)} 场景）</h3>')
        parts.append('<table border="1" cellpadding="6" style="border-collapse:collapse">')
        parts.append('<tr><th>场景</th><th>摘要</th></tr>')
        for sc in sg.get("scenes", [])[:15]:
            _loc = sc.get('primary_space') or '?'
            _cnt = sc.get('segment_count', 0)
            _fn = sc.get('primary_function') or '?'
            _chars = "、".join(c.get('name', '') for c in (sc.get('characters_present') or [])[:3]) or '无'
            parts.append(f'<tr><td>{html.escape(str(sc.get("scene_id","")))}</td>'
                         f'<td>{html.escape(f"{_loc}（{_cnt} 段，{_fn}）出场：{_chars}")[:120]}</td></tr>')
        parts.append('</table>')

    if "character_arcs" in agg:
        ca = agg["character_arcs"]
        arcs = ca.get("character_arcs", [])
        parts.append(f'<h3 id="agg-arcs">👥 角色弧线（{len(arcs)} 个角色）</h3>')
        if arcs:
            parts.append('<table border="1" cellpadding="6" style="border-collapse:collapse">')
            parts.append('<tr><th>角色</th><th>弧线类型</th><th>覆盖率</th><th>出场段数</th><th>性格特征</th></tr>')
            for c in arcs[:12]:
                name = c.get("canonical_name", "未知")
                arc_type = c.get("arc_classification", {}).get("arc_type", "未知")
                coverage = c.get("coverage_rate", 0)
                seg_count = c.get("total_segments_present", 0)
                traits = "、".join(t.get("trait", "") for t in (c.get("traits_aggregated") or [])[:4])
                parts.append(f'<tr><td>{html.escape(str(name))}</td><td>{html.escape(str(arc_type))}</td>'
                             f'<td>{coverage:.1%}</td><td>{seg_count}</td><td>{html.escape(traits)}</td></tr>')
            parts.append('</table>')
            if len(arcs) > 12:
                parts.append(f'<p style="color:#888">... 还有 {len(arcs) - 12} 个角色，详见 character_arcs.json</p>')

    if "character_network" in agg:
        cn = agg["character_network"]
        parts.append(f'<h3 id="agg-network">🕸️ 人物关系网络（{cn.get("total_edges", 0)} 边 / '
                     f'{len(cn.get("communities", []))} 社区）</h3>')
        parts.append('<table border="1" cellpadding="6" style="border-collapse:collapse">')
        parts.append('<tr><th>关系</th><th>类型</th><th>强度</th><th>证据段</th></tr>')
        for ed in cn.get("edges", [])[:15]:
            parts.append(f'<tr><td>{html.escape(str(ed.get("source","")))} → {html.escape(str(ed.get("target","")))}</td>'
                         f'<td>{html.escape(str(ed.get("relation","")))}</td>'
                         f'<td>{ed.get("strength", 0):.2f}</td>'
                         f'<td>{html.escape("、".join(ed.get("evidence_segments", [])[:4]))}</td></tr>')
        parts.append('</table>')

    if "causal_graph" in agg:
        cg = agg["causal_graph"]
        stats = cg.get("statistics", {})
        parts.append(f'<h3 id="agg-causal">⛓️ 因果图（{stats.get("total_edges", 0)} 边 / '
                     f'{stats.get("total_chains", 0)} 链 / 核心事件 {stats.get("core_event_count", 0)}）</h3>')
        if cg.get("chains"):
            parts.append('<ul>')
            for ch in cg.get("chains", [])[:8]:
                parts.append(f'<li>{html.escape(str(ch.get("description",""))[:80])}</li>')
            parts.append('</ul>')

    if "event_sequence" in agg:
        es = agg["event_sequence"]
        stats = es.get("statistics", {})
        parts.append(f'<h3 id="agg-events">📅 事件序列（{es.get("total_events", 0)} 事件 / 核心 '
                     f'{stats.get("core_event_count", 0)} / 卫星 {stats.get("satellite_event_count", 0)} / '
                     f'转折 {stats.get("turning_point_count", 0)}）</h3>')
        rows = es.get("event_sequence", [])[:20]
        if rows:
            parts.append('<table border="1" cellpadding="6" style="border-collapse:collapse">')
            parts.append('<tr><th>事件</th><th>层级</th><th>显赫度</th><th>描述</th><th>段/场景</th><th>人物</th><th>类型</th></tr>')
            for ev in rows:
                _hl = (ev.get("hierarchy") or {}).get("level") or "—"
                _sal = (ev.get("hierarchy") or {}).get("salience_score")
                _sal_s = f'{_sal:.2f}' if isinstance(_sal, (int, float)) else '—'
                _part = html.escape("、".join(ev.get("participants") or ev.get("present_characters") or []) or "无")
                _et = html.escape(str(ev.get("event_type") or ev.get("d01_function") or "—"))
                parts.append(f'<tr><td>{html.escape(str(ev.get("event_id","")))}</td>'
                             f'<td>{html.escape(_hl)}</td><td>{_sal_s}</td>'
                             f'<td>{html.escape(str(ev.get("description",""))[:60])}</td>'
                             f'<td>{html.escape(str(ev.get("segment_id","")))} / {html.escape(str(ev.get("scene_id") or "—"))}</td>'
                             f'<td>{_part}</td><td>{_et}</td></tr>')
            parts.append('</table>')

    if "object_chains" in agg:
        oc = agg["object_chains"]
        stats = oc.get("statistics", {})
        parts.append(f'<h3 id="agg-objects">📦 物件链（{stats.get("total_chains", 0)} 条）</h3>')
        parts.append('<table border="1" cellpadding="6" style="border-collapse:collapse">')
        parts.append('<tr><th>物件</th><th>类型</th><th>出现</th><th>跨度</th><th>语义变化</th></tr>')
        for ch in oc.get("chains", [])[:15]:
            parts.append(f'<tr><td>{html.escape(str(ch.get("object_name","")))}</td>'
                         f'<td>{html.escape(str(ch.get("object_type","")))}</td>'
                         f'<td>{ch.get("occurrence_count",0)}</td>'
                         f'<td>{ch.get("lifecycle_span",0)}</td>'
                         f'<td>{"是" if ch.get("semantic_shift",{}).get("has_shift") else "否"}</td></tr>')
        parts.append('</table>')

    if "character_biographies" in agg:
        cb = agg["character_biographies"]
        bios = cb.get("biographies", {})
        items = list(bios.items()) if isinstance(bios, dict) else (
            [(b.get("name", "?"), b) for b in bios] if isinstance(bios, list) else [])
        parts.append(f'<h3 id="agg-bios">📖 人物传记（{len(items)}）</h3>')
        for name, bio in items[:8]:
            bio_inner = bio.get("biography", bio) if isinstance(bio, dict) else {}
            summary = bio_inner.get("summary", "")
            first = bio_inner.get("first_appearance", "")
            last = bio_inner.get("last_appearance", "")
            parts.append(f'<div class="seg-card"><b>{html.escape(str(name))}</b>'
                         f'<span class="muted">（首现 {html.escape(str(first))} · 末现 {html.escape(str(last))}）</span>'
                         f'<p>{html.escape(str(summary))}</p></div>')

    if "writing_techniques" in agg:
        wt = agg["writing_techniques"]
        _oa = wt.get("overall_assessment", {})
        density = _oa.get("technique_density_per_segment", 0)
        parts.append(f'<h3 id="agg-write">✍️ 叙事技法（{_oa.get("total_technique_instances", 0)} 实例 · '
                     f'{density:.2f}/段 · {html.escape(str(_oa.get("writing_style", "?")))}）</h3>')
        parts.append('<table border="1" cellpadding="6" style="border-collapse:collapse">')
        parts.append('<tr><th>技法</th><th>次数</th><th>示例段</th></tr>')
        for _t in _oa.get("dominant_techniques", [])[:5]:
            if isinstance(_t, list) and len(_t) == 2:
                parts.append(f'<tr><td>{html.escape(str(_t[0]))}</td><td>{_t[1]}</td><td class="muted">主导</td></tr>')
        for t in wt.get("techniques", [])[:15]:
            parts.append(f'<tr><td>{html.escape(str(t.get("technique","")))}</td>'
                         f'<td>{t.get("count",0)}</td>'
                         f'<td>{html.escape("、".join(t.get("example_segments", [])[:3]))}</td></tr>')
        parts.append('</table>')

    if "story_graph" in agg:
        sg = agg["story_graph"]
        gs = sg.get("global_statistics", {})
        parts.append(f'<h3 id="agg-storygraph">🧩 故事图（全局合并）</h3>')
        parts.append('<table border="1" cellpadding="6" style="border-collapse:collapse">')
        parts.append('<tr><th>实体</th><th>场景</th><th>角色</th><th>因果边</th><th>物件链</th></tr>')
        parts.append(f'<tr><td>{gs.get("total_entities", 0)}</td><td>{gs.get("total_scenes", 0)}</td>'
                     f'<td>{gs.get("total_characters", 0)}</td><td>{gs.get("total_causal_edges", 0)}</td>'
                     f'<td>{gs.get("total_object_chains", 0)}</td></tr>')
        parts.append('</table>')
        gtype = sg.get("graph_type") or sg.get("meta", {}).get("graph_type", "")
        if gtype:
            parts.append(f'<p class="muted">图谱类型：{html.escape(str(gtype))}</p>')
        parts.append('</div>')

    if "adapters" in agg:
        parts.append('<h3 id="agg-adapters">🔌 适配器输出（text2story / YARN / NCP）</h3>')
        parts.append('<table border="1" cellpadding="6" style="border-collapse:collapse">')
        parts.append('<tr><th>格式</th><th>文件</th></tr>')
        for fmt in agg["adapters"].get("formats", []):
            parts.append(f'<tr><td>{html.escape(str(fmt.get("format","")))}</td>'
                         f'<td><code>{html.escape(str(fmt.get("file","")))}</code></td></tr>')
        parts.append('</table>')
        parts.append('</div>')

    parts.append('</div>')
    return "".join(parts)


# ========================================================================
# 逐段详情（T-134：全量 + 四层全字段）
# ========================================================================

def _field_rows(obj: dict, prefix: str = "") -> list[tuple[str, str]]:
    """把 dict 扁平化成 (路径, 值) 行，数组展开为多行。"""
    rows: list[tuple[str, str]] = []
    for k, v in obj.items():
        path = f"{prefix}.{k}" if prefix else str(k)
        if isinstance(v, dict):
            rows.extend(_field_rows(v, path))
        elif isinstance(v, list):
            if not v:
                rows.append((path, "[]"))
            else:
                for i, it in enumerate(v):
                    if isinstance(it, dict):
                        rows.extend(_field_rows(it, f"{path}[{i}]"))
                    else:
                        rows.append((f"{path}[{i}]", str(it)))
        elif v is None:
            rows.append((path, "null"))
        else:
            rows.append((path, str(v)))
    return rows


def _segment_detail_html(s: dict, structs: dict, interps: dict, emotions: dict, craft: dict) -> str:
    """单段四层全量详情 HTML（<details> 折叠）。"""
    sid = s.get("segment_id", "")
    ts = s.get("text_span", {})
    text = ts.get("text", "") if isinstance(ts, dict) else ""
    pollution = s.get("pollution_warning")

    rows: list[tuple[str, str]] = [("文本预览", text[:300] + ("…" if len(text) > 300 else ""))]
    if pollution:
        rows.append(("⚠️ 切分警告", str(pollution)))

    def _layer_block(title: str, content: dict) -> None:
        if content:
            rows.append((f"◆ {title}", ""))
            rows.extend(_field_rows(content))

    _layer_block("L1 结构层", _structure_of(structs.get(sid)))
    _layer_block("L2 阐释层", _interpretation_of(interps.get(sid)))
    emo = _emotion_of(emotions.get(sid))
    if emo:
        rows.append(("◆ L2.5 情感层", ""))
        for k, v in emo.items():
            if k == "expression" and isinstance(v, dict) and v.get("key_phrases"):
                rows.append(("expression.key_phrases", "、".join(str(x) for x in v["key_phrases"])))
            elif isinstance(v, dict):
                rows.extend(_field_rows(v, f"emotion.{k}"))
            elif isinstance(v, list):
                rows.append((f"emotion.{k}", json.dumps(v, ensure_ascii=False)[:120]))
            elif v is None:
                rows.append((f"emotion.{k}", "null"))
            else:
                rows.append((f"emotion.{k}", str(v)))
    cr = _craft_of(craft.get(sid))
    if cr:
        rows.append(("◆ L3 文笔层", ""))
        rows.extend(_field_rows(cr))

    head = f"{html.escape(sid)} · {html.escape(str(s.get('chapter','')))}"
    if pollution:
        head += " <span style='color:#e67e22'>⚠ 兜底切分</span>"
    parts = [f"<details class='seg-card'><summary><b>{head}</b></summary><table border='1' "
             "cellpadding='5' style='border-collapse:collapse;margin-top:8px'>"]
    for k, v in rows:
        if not v:
            parts.append(f"<tr><td colspan='2' style='background:#f5f5f5'><b>{html.escape(k)}</b></td></tr>")
        else:
            parts.append(f"<tr><td style='width:220px;color:#666'>{html.escape(k)}</td><td>{html.escape(v)}</td></tr>")
    parts.append("</table></details>")
    return "".join(parts)


# ========================================================================
# HTML 渲染
# ========================================================================

def render_html(doc_id: str, out_path: Path, segs: list[dict], structs: dict, interps: dict,
                craft: dict, refs: list[dict], ckpt: dict | None, emotions: dict | None = None,
                aggregation: dict = None) -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    emotions = emotions or {}
    parts: list[str] = []
    parts.append("<!doctype html><html><head><meta charset='utf-8'>")
    parts.append(f"<title>精读批注报告 · {html.escape(doc_id)}</title>")
    parts.append("<style>"
                 "body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;margin:24px;line-height:1.6;}"
                 "h1{color:#222;border-bottom:2px solid #444;}"
                 "h2{color:#333;border-bottom:1px solid #ccc;margin-top:2em;}"
                 "h3{margin-top:1.4em;}"
                 "table{border-collapse:collapse;margin:12px 0;}"
                 "th,td{border:1px solid #bbb;padding:6px 10px;font-size:14px;vertical-align:top;}"
                 "th{background:#f2f2f2;}"
                 ".muted{color:#666;}"
                 ".seg-card{border:1px solid #ddd;border-radius:6px;padding:10px 14px;margin:8px 0;background:#fafafa;}"
                 "details.seg-card summary{cursor:pointer;font-size:15px;}"
                 "nav.toc{background:#f8f8f8;border:1px solid #ddd;border-radius:6px;padding:10px 16px;margin:12px 0;}"
                 "nav.toc a{color:#2c6cb0;text-decoration:none;margin-right:12px;}"
                 "</style></head><body>")
    parts.append(f"<h1>精读批注报告 · {html.escape(doc_id)}</h1>")
    parts.append(f"<p class='muted'>生成时间：{now} · close-reading-annotator v3.15.1</p>")

    # TOC（T-136）
    toc_items = [
        ("#agg", "聚合分析"), ("#progress", "批注进度"), ("#vis", "可视化"),
        ("#l1", "L1 结构层摘要"), ("#l2", "L2 阐释层摘要"), ("#l25", "L2.5 情感摘要"),
        ("#l3", "L3 文笔摘要"), ("#l4", "L4 跨段关系"), ("#segments", "逐段详情"),
    ]
    parts.append("<nav class='toc'><b>目录：</b>")
    for href, label in toc_items:
        parts.append(f"<a href='{href}'>{html.escape(label)}</a>")
    parts.append("</nav>")

    # 聚合分析（T-135）
    parts.append(_render_aggregation_html(aggregation, doc_id))

    # 可视化（T-136）
    parts.append("<h2 id='vis'>📈 可视化</h2>")
    svg_emo = svg_intensity_curve(segs, structs)
    if svg_emo:
        parts.append("<h3>情感强度曲线（D04）</h3>")
        parts.append(svg_emo)
    svg_pace = svg_pace_curve(segs, structs)
    if svg_pace:
        parts.append("<h3>节奏曲线（D05）</h3>")
        parts.append(svg_pace)
    svg_char = svg_character_emotion_arc(emotions, segs)
    if svg_char:
        parts.append("<h3>角色情感弧（D19，top 5）</h3>")
        parts.append(svg_char)
    if not (svg_emo or svg_pace or svg_char):
        parts.append("<p class='muted'>暂无足够数据生成可视化（需 L1 structure 或 L2.5 emotion 数据）。</p>")

    # 切分质量（T-134）
    ps = _seg_pollution_stats(segs)
    parts.append("<h2 id='quality'>🔪 切分质量</h2>")
    parts.append("<table><tr><th>片段总数</th><th>兜底切分段</th><th>说明</th></tr>")
    note = ("原文无章节边界触发字符数兜底切分" if ps["polluted"] else "章节/段落边界识别正常") + (
        f"（{ps['samples'][0]}" if ps["samples"] else "")
    note += "）" if ps["samples"] else ""
    parts.append(f"<tr><td>{ps['total']}</td><td>{ps['polluted']}</td><td class='muted'>{html.escape(note)}</td></tr>")
    parts.append("</table>")

    # 进度
    parts.append("<h2 id='progress'>📊 批注进度概览</h2>")
    total = len(segs)
    if ckpt:
        parts.append("<table><tr><th>指标</th><th>值</th></tr>")
        parts.append(f"<tr><td>片段总数</td><td>{ckpt.get('total_segments', total)}</td></tr>")
        done = len(ckpt.get("completed", []))
        parts.append(f"<tr><td>已完成片段</td><td>{done}/{total} ({(100 * done / total if total else 0):.0f}%)</td></tr>")
        parts.append(f"<tr><td>跨段分析</td><td>{'✅' if ckpt.get('cross_segment_completed') else '⏳'}</td></tr>")
        parts.append(f"<tr><td>四层合并</td><td>{'✅' if ckpt.get('merged_completed') else '⏳'}</td></tr>")
        parts.append("</table>")
    else:
        parts.append(f"<p class='muted'>片段总数：{total}（无 checkpoint）</p>")

    # L1 结构层摘要
    parts.append("<h2 id='l1'>🧱 Layer 1 结构层摘要</h2>")
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
            parts.append(f"<td>{html.escape(_structure_of(r)['D01'])}</td>")
        except Exception:
            parts.append("<td class='muted'>—</td>")
        em = _emotion_core(r)
        iv = _emotion_intensity(r)
        parts.append(f"<td>{html.escape(em)} {iv}</td>")
        try:
            parts.append(f"<td>{html.escape(str(_structure_of(r)['D04'].get('polarity', '')))}</td>")
        except Exception:
            parts.append("<td class='muted'>—</td>")
        parts.append(f"<td>{_bar_html(_pace(r), 5, '#4a90e2')}</td>")
        try:
            parts.append(f"<td>{html.escape(_structure_of(r)['D07']['type'])}</td>")
        except Exception:
            parts.append("<td class='muted'>—</td>")
        parts.append("</tr>")
    parts.append("</table>")

    # L2 阐释层摘要（T-134：HTML 补齐——此前只有 MD 有）
    if interps:
        theme_counter: dict[str, int] = {}
        rel_counter: dict[str, int] = {}
        d06_counter: dict[str, int] = {}
        for sid, r in interps.items():
            for t in _themes_of(r):
                theme_counter[t] = theme_counter.get(t, 0) + 1
            nr = _interpretation_of(r).get("narrator_reliability")
            if nr:
                rel_counter[nr] = rel_counter.get(nr, 0) + 1
            d06 = _interpretation_of(r).get("D06")
            if isinstance(d06, dict) and d06.get("type"):
                d06_counter[d06["type"]] = d06_counter.get(d06["type"], 0) + 1
        parts.append("<h2 id='l2'>🔍 Layer 2 阐释层摘要</h2>")
        if theme_counter:
            parts.append("<p><b>Top 主题标签（D09 跨段频次）</b></p><ul>")
            for t, c in sorted(theme_counter.items(), key=lambda x: -x[1])[:10]:
                parts.append(f"<li>{html.escape(t)}（{c} 段）</li>")
            parts.append("</ul>")
        if rel_counter:
            parts.append("<p><b>叙述者可靠性分布</b></p><ul>")
            for nr, c in rel_counter.items():
                parts.append(f"<li>{html.escape(nr)}：{c} 段</li>")
            parts.append("</ul>")
        if d06_counter:
            parts.append("<p><b>信息控制类型分布（D06）</b></p><ul>")
            for t, c in d06_counter.items():
                parts.append(f"<li>{html.escape(t)}：{c} 段</li>")
            parts.append("</ul>")

    # L2.5 情感摘要（T-134：修复 v2.8 直接格式）
    emo_rows = _emotion_summaries(emotions)
    if emo_rows:
        parts.append("<h2 id='l25'>🎭 Layer 2.5 情感分析摘要（D19 · P4）</h2>")
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
        parts.append("<p><b>情感关键短语（D19.expression.key_phrases）</b></p><ul>")
        for r in emo_rows:
            if not r["key_phrases"]:
                continue
            parts.append(f"<li>（seg_{r['num']}）{html.escape(' ／ '.join(r['key_phrases']))}</li>")
        parts.append("</ul>")

    # L3 文笔摘要（T-134：HTML 补齐）
    if craft:
        golden: list[tuple[str, dict]] = []
        rhet_counter: dict[str, int] = {}
        imagery_counter: dict[str, int] = {}
        syntax_counter: dict[str, int] = {}
        for sid, c in craft.items():
            cr = _craft_of(c)
            for it in cr.get("D13_golden_lines", []) or []:
                golden.append((sid, it))
            for it in cr.get("D14_rhetoric", []) or []:
                if it.get("type"):
                    rhet_counter[it["type"]] = rhet_counter.get(it["type"], 0) + 1
            for it in cr.get("D15_imagery", []) or []:
                if it.get("type"):
                    imagery_counter[it["type"]] = imagery_counter.get(it["type"], 0) + 1
            for it in cr.get("D17_syntax", []) or []:
                if it.get("type"):
                    syntax_counter[it["type"]] = syntax_counter.get(it["type"], 0) + 1
        parts.append("<h2 id='l3'>✍️ Layer 3 文笔层摘要</h2>")
        if rhet_counter:
            parts.append("<p><b>修辞手法统计（D14）</b></p><ul>")
            for rt, c in sorted(rhet_counter.items(), key=lambda x: -x[1]):
                parts.append(f"<li>{html.escape(rt)}：{c} 处</li>")
            parts.append("</ul>")
        if imagery_counter:
            parts.append("<p><b>意象类型统计（D15）</b></p><ul>")
            for rt, c in sorted(imagery_counter.items(), key=lambda x: -x[1]):
                parts.append(f"<li>{html.escape(rt)}：{c} 处</li>")
            parts.append("</ul>")
        if syntax_counter:
            parts.append("<p><b>句式类型统计（D17）</b></p><ul>")
            for rt, c in sorted(syntax_counter.items(), key=lambda x: -x[1]):
                parts.append(f"<li>{html.escape(rt)}：{c} 处</li>")
            parts.append("</ul>")
        if golden:
            parts.append("<p><b>D13 佳句 Top 10（按 quality_score 降序）</b></p><ul>")
            golden.sort(key=lambda x: -(x[1].get("quality_score", 0) or 0))
            for sid, it in golden[:10]:
                parts.append(f"<li>（{html.escape(sid)}）{html.escape(it.get('text',''))} "
                             f"— <i>{html.escape(it.get('reason',''))}</i>（评分 {it.get('quality_score','?')}）</li>")
            parts.append("</ul>")

    # L4 跨段关系
    if refs:
        parts.append("<h2 id='l4'>🔗 Layer 4 跨段关系候选（启发式）</h2>")
        parts.append("<table><tr><th>#</th><th>类型</th><th>起点</th><th>终点</th><th>说明</th></tr>")
        for i, r in enumerate(refs, 1):
            parts.append(f"<tr><td>{i}</td>"
                         f"<td>{html.escape(r.get('relation_type',''))}</td>"
                         f"<td>{html.escape(r.get('source',{}).get('segment_id',''))}</td>"
                         f"<td>{html.escape(r.get('target',{}).get('segment_id',''))}</td>"
                         f"<td>{html.escape(str(r.get('note','')))}</td></tr>")
        parts.append("</table>")
    else:
        parts.append("<h2 id='l4'>🔗 Layer 4 跨段关系</h2><p class='muted'>暂无可展示的跨段关系。</p>")

    # 逐段全量详情（T-134：全量 + <details> 折叠）
    parts.append("<h2 id='segments'>📄 逐段详情（全量，点击展开）</h2>")
    for s in segs:
        parts.append(_segment_detail_html(s, structs, interps, emotions, craft))

    parts.append("<p class='muted'>—— Report rendered by close-reading-annotator v3.15.1 ——</p>")
    parts.append("</body></html>")
    out_path.write_text("".join(parts), encoding="utf-8")


# ========================================================================
# Markdown 渲染
# ========================================================================

def render_md(doc_id: str, out_path: Path, segs: list[dict], structs: dict, interps: dict,
              craft: dict, refs: list[dict], ckpt: dict | None, emotions: dict | None = None,
              aggregation: dict = None) -> None:
    emotions = emotions or {}
    lines: list[str] = []
    lines.append(f"# 精读批注报告 · {doc_id}")
    lines.append("")
    lines.append(f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")

    # T-135：MD 报告聚合分析（此前缺失）
    lines.extend(_render_aggregation_md(aggregation or {}, doc_id))

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

    # T-134：切分质量
    ps = _seg_pollution_stats(segs)
    lines.append("## 🔪 切分质量")
    lines.append("")
    lines.append(f"- 片段总数：{ps['total']}")
    lines.append(f"- 兜底切分段：{ps['polluted']}")
    if ps["samples"]:
        lines.append(f"- 说明：{ps['samples'][0]}")
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
                d01 = _structure_of(r)["D01"]
                d04 = _structure_of(r)["D04"]["core"]
                iv = int(_structure_of(r)["D04"]["intensity"])
                pol = _structure_of(r)["D04"].get("polarity", "-")
                pv = int(_structure_of(r)["D05"])
                d07 = _structure_of(r)["D07"]["type"]
            except Exception:
                pass
        lines.append(f"| {sid} | {s.get('chapter','')} | {d01} | {d04} | {iv} | {pol} | {pv} | {d07} |")

    if interps:
        theme_counter: dict[str, int] = {}
        rel_counter: dict[str, int] = {}
        for sid, r in interps.items():
            for t in _themes_of(r):
                theme_counter[t] = theme_counter.get(t, 0) + 1
            nr = _interpretation_of(r).get("narrator_reliability")
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

    # T-134：修复 v2.8 直接格式后，MD 情感摘要真正有数据
    emo_rows = _emotion_summaries(emotions)
    if emo_rows:
        lines.append("")
        lines.append("## 🎭 Layer 2.5 情感分析摘要（D19 · P4）")
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
        imagery_counter: dict[str, int] = {}
        syntax_counter: dict[str, int] = {}
        voice_counter: dict[str, int] = {}
        for sid, c in craft.items():
            cr = _craft_of(c)
            for it in cr.get("D13_golden_lines", []) or []:
                golden.append((sid, it))
            for it in cr.get("D14_rhetoric", []) or []:
                rt = it.get("type", "") if isinstance(it, dict) else ""
                if rt:
                    rhet_counter[rt] = rhet_counter.get(rt, 0) + 1
            for it in cr.get("D15_imagery", []) or []:
                _it = it.get("type", "") if isinstance(it, dict) else ""
                if _it:
                    imagery_counter[_it] = imagery_counter.get(_it, 0) + 1
            for it in cr.get("D17_syntax", []) or []:
                _st = it.get("type", "") if isinstance(it, dict) else ""
                if _st:
                    syntax_counter[_st] = syntax_counter.get(_st, 0) + 1
            for it in cr.get("D18_character_voice", []) or []:
                _ch = it.get("character", "") if isinstance(it, dict) else ""
                if _ch:
                    voice_counter[_ch] = voice_counter.get(_ch, 0) + 1
        # v3.16.4 T-153：MD 版补 Layer 3 文笔层标题（HTML 已有，MD 此前散落无标题）
        lines.append("")
        lines.append("## 🖋️ Layer 3 文笔层摘要")
        lines.append("")
        if rhet_counter:
            lines.append("")
            lines.append("**修辞手法统计（D14）**")
            lines.append("")
            for rt, c in sorted(rhet_counter.items(), key=lambda x: -x[1]):
                lines.append(f"- {rt}：{c} 处")
        if imagery_counter:
            lines.append("")
            lines.append("**意象类型统计（D15）**")
            lines.append("")
            for rt, c in sorted(imagery_counter.items(), key=lambda x: -x[1]):
                lines.append(f"- {rt}：{c} 处")
        if syntax_counter:
            lines.append("")
            lines.append("**句式类型统计（D17）**")
            lines.append("")
            for rt, c in sorted(syntax_counter.items(), key=lambda x: -x[1]):
                lines.append(f"- {rt}：{c} 处")
        if voice_counter:
            lines.append("")
            lines.append("**人物语言指纹（D18，Top 8）**")
            lines.append("")
            for rt, c in sorted(voice_counter.items(), key=lambda x: -x[1])[:8]:
                lines.append(f"- {rt}：{c} 段")
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


# ========================================================================
# main
# ========================================================================

def main() -> int:
    p = argparse.ArgumentParser(
        description="【精读批注 Phase 5】人类可读报告渲染（HTML/Markdown，v3.15.1 含聚合与可视化）")
    p.add_argument("--doc-id", required=True)
    p.add_argument("--segments", default=None, help="segments.jsonl（默认在 <cwd>/<doc_id>_segments.jsonl）")
    p.add_argument("--format", choices=["html", "md"], default="html")
    p.add_argument("--output-dir", "--output", dest="output", default=None, help="输出文件（默认 <doc_id>_report.html/.md）")
    p.add_argument("--agg-dir", default=None,
                   help="v3.15.1 T-133：聚合产物目录（默认 <segments 父目录>/aggregation）。"
                        "聚合层跑完后用本参数重生成报告即可纳入全局分析。")
    args = p.parse_args()

    doc_id = args.doc_id
    cwd = Path.cwd()
    seg_path = Path(args.segments) if args.segments else (cwd / f"{doc_id}_segments.jsonl")
    if not seg_path.is_file():
        print(f"❌ segments 不存在：{seg_path}", file=sys.stderr)
        return 2

    segs = _load_jsonl(seg_path)
    base_dir = seg_path.parent
    agg_dir = Path(args.agg_dir) if args.agg_dir else (base_dir / "aggregation")

    # v3.16.4 T-153：--output-dir/--output 兼容"目录"与"文件路径"两种传法——
    # 规则：①已是文件 → 直接用；②带 .md/.html 扩展名 → 当文件路径；
    # ③其余（目录，含尚不存在的）→ 自动 mkdir 并拼 <doc_id>_report.<fmt>。
    _out_arg = args.output
    if _out_arg:
        _out_path = Path(_out_arg)
        _is_dir_like = (
            _out_path.is_dir()
            or (not _out_path.is_file() and _out_path.suffix.lower() not in (".md", ".html", ".htm"))
        )
        if _is_dir_like:
            _out_path.mkdir(parents=True, exist_ok=True)
            _out_path = _out_path / f"{doc_id}_report.{args.format}"
        args.output = str(_out_path)

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

    # T-133：聚合层数据（--agg-dir 显式指定）
    aggregation = _load_aggregation(agg_dir, doc_id)
    if aggregation:
        print(f"[render_report] ✅ 已加载聚合分析（{len(aggregation)} 个模块）← {agg_dir}")
    else:
        print(f"[render_report] ⚠️ 未找到聚合产物（{agg_dir}），报告将不含聚合分析。"
              f"聚合层跑完后用 --agg-dir 重跑本脚本即可。")

    if args.format == "html":
        out_path = Path(args.output) if args.output else (base_dir / f"{doc_id}_report.html")
        if out_path.is_dir():
            print(f"⚠️ --output-dir 收到目录（{out_path}），自动拼接文件名 → {out_path / f'{doc_id}_report.html'}", file=sys.stderr)
            out_path = out_path / f"{doc_id}_report.html"
        render_html(doc_id, out_path, segs, structs, interps, craft, cross_refs, ckpt, emotions, aggregation)
    else:
        out_path = Path(args.output) if args.output else (base_dir / f"{doc_id}_report.md")
        if out_path.is_dir():
            print(f"⚠️ --output-dir 收到目录（{out_path}），自动拼接文件名 → {out_path / f'{doc_id}_report.md'}", file=sys.stderr)
            out_path = out_path / f"{doc_id}_report.md"
        render_md(doc_id, out_path, segs, structs, interps, craft, cross_refs, ckpt, emotions, aggregation)

    if ckpt is not None:
        ckpt["render_report_completed"] = True
        save_checkpoint(ckpt, base_dir)
    print(f"[render_report] ✅ 报告生成 → {out_path.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
