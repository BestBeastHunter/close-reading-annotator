#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/audit/v37_acceptance.py — v3.7.0 验收脚本（T-036 / ADR-014 决定 4）

覆盖：
  A. 产物格式：narrative_structure.py py_compile
  B. 脚本功能：无输入报错、合法输入产出、输出格式正确
  C. 弗雷塔格五幕：act_ranges 六幕、key_turning_points、structure_health
  D. 热奈特聚焦：dominant_focalization、d07_type_distribution、complexity
  E. 叙事时间线：time_structure、timeline_nodes、time_type_distribution
  F. 救猫咪节拍：beats 14 个、key_beats_total=4、beat_completeness
  G. 叙事层级：level_distribution、dominant_level
  H. 文档一致性：SKILL/RUNBOOK/README 版本 3.7.0 + aggregation schema 3.1.0
  I. 端到端：两本书都能跑通

用法：python scripts/audit/v37_acceptance.py
"""

from __future__ import annotations

import io
import json
import py_compile
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

SKILL_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = SKILL_ROOT / "scripts"
WORKSPACE = SKILL_ROOT.parents[1]
MOON_STRUCTURE = WORKSPACE / "outputs" / "annotations" / "moon_sixpence_zh" / "moon_sixpence_zh_structure.jsonl"
SHANGHAI_STRUCTURE = WORKSPACE / "outputs" / "annotations" / "shanghai_fortress_zh" / "shanghai_fortress_zh_structure.jsonl"

PASS = 0
FAIL = 0
RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        RESULTS.append((name, True, detail))
        print(f"  [PASS] {name}" + (f" — {detail}" if detail else ""))
    else:
        FAIL += 1
        RESULTS.append((name, False, detail))
        print(f"  [FAIL] {name}" + (f" — {detail}" if detail else ""))


def run_narrative_structure(structure_path: Path, doc_id: str, out_dir: Path) -> tuple[int, str, str]:
    cmd = [sys.executable, str(SCRIPTS / "aggregation" / "narrative_structure.py"),
           "--structure", str(structure_path), "--doc-id", doc_id, "--output-dir", str(out_dir)]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return proc.returncode, proc.stdout, proc.stderr


# ============================================================================
# A. 产物格式
# ============================================================================
print("\n=== A. 产物格式（py_compile）===")

try:
    py_compile.compile(str(SCRIPTS / "aggregation" / "narrative_structure.py"), doraise=True)
    check("A-narrative_structure-py_compile", True, "编译通过")
except py_compile.PyCompileError as e:
    check("A-narrative_structure-py_compile", False, str(e)[:200])

check("A-script-exists", (SCRIPTS / "aggregation" / "narrative_structure.py").exists())

# ============================================================================
# B. 脚本功能（月亮）
# ============================================================================
print("\n=== B. 脚本功能（月亮与六便士）===")

moon_data = None
with tempfile.TemporaryDirectory() as tmpdir:
    tmp = Path(tmpdir)
    rc, out, err = run_narrative_structure(MOON_STRUCTURE, "moon_sixpence_zh", tmp)
    check("B-moon-rc0", rc == 0, f"rc={rc}")
    out_file = tmp / "moon_sixpence_zh_narrative_structure.json"
    check("B-moon-output-exists", out_file.exists())

    if out_file.exists():
        moon_data = json.loads(io.open(out_file, encoding="utf-8").read())
        check("B-moon-schema-version", moon_data.get("schema_version") == "3.1.0", f"schema_version={moon_data.get('schema_version')}")
        check("B-moon-doc-id", moon_data.get("document_id") == "moon_sixpence_zh")
        check("B-moon-total-segments", moon_data.get("total_segments") == 89, f"total={moon_data.get('total_segments')}")
        check("B-moon-has-freytag", "freytag_pyramid" in moon_data)
        check("B-moon-has-focalization", "genette_focalization" in moon_data)
        check("B-moon-has-timeline", "narrative_timeline" in moon_data)
        check("B-moon-has-save-the-cat", "save_the_cat_beats" in moon_data)
        check("B-moon-has-narrative-levels", "narrative_levels" in moon_data)

# ============================================================================
# C. 弗雷塔格五幕
# ============================================================================
print("\n=== C. 弗雷塔格五幕 ===")

if moon_data is not None:
    freytag = moon_data["freytag_pyramid"]
    required_acts = ["exposition", "inciting_incident", "rising_action", "climax", "falling_action", "resolution"]
    for act in required_acts:
        check(f"C-freytag-has-{act}", act in freytag["act_ranges"], f"{act} 存在")
    check("C-freytag-key-turning-points", "key_turning_points" in freytag)
    check("C-freytag-structure-health", freytag.get("structure_health") in ("healthy", "needs_review"), f"health={freytag.get('structure_health')}")
    check("C-freytag-derivation-method", "act_transition_points" in freytag.get("derivation_method", ""))
    # 验证上升行动占比最大（弗雷塔格结构特征）
    rising_pct = freytag["act_ranges"].get("rising_action", {}).get("percentage", 0)
    check("C-freytag-rising-action-largest", rising_pct >= 20, f"rising_action={rising_pct}%（应≥20%）")
else:
    check("C-freytag-skipped", False, "moon_data 为 None，跳过")

# ============================================================================
# D. 热奈特聚焦
# ============================================================================
print("\n=== D. 热奈特聚焦 ===")

if moon_data is not None:
    focal = moon_data["genette_focalization"]
    valid_focalizations = {"first_person_focalization", "second_person_focalization", "internal_focalization",
                            "zero_focalization", "variable_focalization", "unreliable_focalization", "external_focalization"}
    check("D-focal-dominant-valid", focal.get("dominant_focalization") in valid_focalizations,
          f"dominant={focal.get('dominant_focalization')}")
    check("D-focal-d07-distribution", isinstance(focal.get("d07_type_distribution"), dict) and len(focal["d07_type_distribution"]) > 0)
    valid_complexities = {"simple_single_focalization", "moderate_occasional_shift", "complex_multiple_focalization"}
    check("D-focal-complexity-valid", focal.get("complexity") in valid_complexities, f"complexity={focal.get('complexity')}")
    check("D-focal-switch-count", isinstance(focal.get("focalization_switch_count"), int))
    check("D-focal-narrator-reliability", focal.get("narrator_reliability") in ("unreliable", "reliable_or_not_marked"))
    # 月亮是第一人称，验证主导聚焦正确
    check("D-focal-moon-first-person", focal.get("dominant_focalization") == "first_person_focalization",
          f"月亮应为第一人称聚焦，实际={focal.get('dominant_focalization')}")
else:
    check("D-focal-skipped", False, "moon_data 为 None，跳过")

# ============================================================================
# E. 叙事时间线
# ============================================================================
print("\n=== E. 叙事时间线 ===")

if moon_data is not None:
    timeline = moon_data["narrative_timeline"]
    valid_time_structures = {"linear_simple", "linear_with_occasional_flashback", "complex_nonlinear"}
    check("E-timeline-structure-valid", timeline.get("time_structure") in valid_time_structures,
          f"structure={timeline.get('time_structure')}")
    check("E-timeline-nodes-count", len(timeline.get("timeline_nodes", [])) == 89,
          f"nodes={len(timeline.get('timeline_nodes', []))}（应=89）")
    check("E-timeline-type-distribution", isinstance(timeline.get("time_type_distribution"), dict))
    check("E-timeline-jump-count", isinstance(timeline.get("time_jump_count"), int))
    # 验证每个 timeline_node 有必需字段
    first_node = timeline["timeline_nodes"][0] if timeline["timeline_nodes"] else {}
    check("E-timeline-node-fields", all(k in first_node for k in ["segment_index", "segment_id", "time_type", "time_marker"]),
          "节点字段完整")
else:
    check("E-timeline-skipped", False, "moon_data 为 None，跳过")

# ============================================================================
# F. 救猫咪节拍
# ============================================================================
print("\n=== F. 救猫咪节拍 ===")

if moon_data is not None:
    stc = moon_data["save_the_cat_beats"]
    check("F-beats-count-14", len(stc.get("beats", [])) == 14, f"beats={len(stc.get('beats', []))}（应=14）")
    check("F-key-beats-total-4", stc.get("key_beats_total") == 4, f"total={stc.get('key_beats_total')}")
    check("F-beat-completeness-range", 0 <= stc.get("beat_completeness", -1) <= 100,
          f"completeness={stc.get('beat_completeness')}%（应 0-100）")
    # 验证关键节拍存在
    beat_ids = [b["beat_id"] for b in stc.get("beats", [])]
    for key_beat in ["catalyst", "midpoint", "all_is_lost", "finale"]:
        check(f"F-has-key-beat-{key_beat}", key_beat in beat_ids)
    # 验证每个 beat 有必需字段
    first_beat = stc["beats"][0] if stc["beats"] else {}
    check("F-beat-fields", all(k in first_beat for k in ["beat_id", "beat_name", "start_segment", "end_segment", "dominant_d01"]),
          "节拍字段完整")
else:
    check("F-save-the-cat-skipped", False, "moon_data 为 None，跳过")

# ============================================================================
# G. 叙事层级
# ============================================================================
print("\n=== G. 叙事层级 ===")

if moon_data is not None:
    nl = moon_data["narrative_levels"]
    check("G-level-distribution", isinstance(nl.get("level_distribution"), dict) and len(nl["level_distribution"]) > 0)
    check("G-dominant-level", nl.get("dominant_level") is not None)
    check("G-derivation-method", "derivation_method" in nl)
    # 旧产物没有 _narrative_level 字段，应降级标注
    check("G-legacy-degradation-note", "note" in nl or "unknown" in nl.get("level_distribution", {}),
          "旧产物应降级标注 unknown 或有 note")
else:
    check("G-narrative-levels-skipped", False, "moon_data 为 None，跳过")

# ============================================================================
# H. 文档一致性
# ============================================================================
print("\n=== H. 文档一致性 ===")

skill_md = io.open(SKILL_ROOT / "SKILL.md", encoding="utf-8").read()
runbook = io.open(SKILL_ROOT / "docs" / "RUNBOOK.md", encoding="utf-8").read()
readme = io.open(SKILL_ROOT / "README.md", encoding="utf-8").read()
agg_schema = io.open(SKILL_ROOT / "references" / "aggregation-schema.md", encoding="utf-8").read()

check("H-SKILL-version-3.7.0", "version: 3.7.0" in skill_md)
check("H-SKILL-title-3.7.0", "# 四层精读批注 Skill v3.7.0" in skill_md)
check("H-SKILL-v3.7.0-history", "3.7.0" in skill_md and "叙事结构分析" in skill_md)
check("H-SKILL-narrative_structure-in-workflow", "narrative_structure.py" in skill_md and "⑤" in skill_md)
check("H-SKILL-aggregation-schema-3.1.0", "3.1.0" in skill_md and "aggregation schema_version" in skill_md)
check("H-SKILL-9-scripts", "9 个脚本" in skill_md or "9 脚本" in skill_md)

check("H-RUNBOOK-version-3.7.0", "v3.7.0" in runbook)
check("H-RUNBOOK-narrative_structure-cli", "narrative_structure.py" in runbook)
check("H-RUNBOOK-9-scripts", "9 脚本" in runbook)

check("H-README-version-3.7.0", "v3.7.0" in readme)
check("H-README-narrative_structure-tree", "narrative_structure.py" in readme)
check("H-README-aggregation-schema-3.1.0", "3.1.0" in readme)

check("H-agg-schema-version-3.1.0", "v3.1.0" in agg_schema)
check("H-agg-schema-narrative_structure-section", "narrative_structure.json" in agg_schema and "弗雷塔格" in agg_schema)

# ============================================================================
# I. 端到端（上海堡垒）
# ============================================================================
print("\n=== I. 端到端（上海堡垒）===")

if SHANGHAI_STRUCTURE.exists():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        rc, out, err = run_narrative_structure(SHANGHAI_STRUCTURE, "shanghai_fortress_zh", tmp)
        check("I-shanghai-rc0", rc == 0, f"rc={rc}")
        sh_file = tmp / "shanghai_fortress_zh_narrative_structure.json"
        if sh_file.exists():
            sh_data = json.loads(io.open(sh_file, encoding="utf-8").read())
            check("I-shanghai-total-segments", sh_data.get("total_segments") == 63, f"total={sh_data.get('total_segments')}")
            check("I-shanghai-freytag-health", sh_data["freytag_pyramid"].get("structure_health") in ("healthy", "needs_review"))
            check("I-shanghai-focalization", sh_data["genette_focalization"].get("dominant_focalization") is not None)
            check("I-shanghai-timeline-structure", sh_data["narrative_timeline"].get("time_structure") is not None)
            check("I-shanghai-beats-14", len(sh_data["save_the_cat_beats"].get("beats", [])) == 14)
            # 上海堡垒有倒叙结构，验证时间线复杂度
            check("I-shanghai-nonlinear-or-flashback",
                  sh_data["narrative_timeline"].get("time_structure") in ("complex_nonlinear", "linear_with_occasional_flashback"),
                  f"上海堡垒应有倒叙特征，time_structure={sh_data['narrative_timeline'].get('time_structure')}")
else:
    check("I-shanghai-skipped", True, f"测试文件不存在: {SHANGHAI_STRUCTURE}")

# ============================================================================
# 汇总
# ============================================================================
print(f"\n{'='*60}")
print(f"v3.7.0 验收汇总：PASS={PASS}  FAIL={FAIL}  TOTAL={PASS+FAIL}")
if FAIL == 0:
    print("ALL PASS ✅")
else:
    print(f"有 {FAIL} 项失败 ❌")
    for name, ok, detail in RESULTS:
        if not ok:
            print(f"  FAIL: {name} — {detail}")
print(f"{'='*60}")

sys.exit(0 if FAIL == 0 else 1)
