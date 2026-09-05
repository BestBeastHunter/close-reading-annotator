#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/audit/v38_acceptance.py — v3.8.0 验收脚本（T-037 / ADR-014 决定 5）

覆盖：
  A. 产物格式：writing_techniques.py py_compile
  B. 脚本功能（月亮）：合法输入产出、输出格式正确、4 子模块存在
  C. 转场技巧：4 类转场计数 + transition_density + 详情字段
  D. 悬念设置：6 项指标 + suspense_intensity + 伏笔回收对
  E. 蒙太奇手法：3 类蒙太奇 + montage_density + 详情字段
  F. 钩子类型：4 类钩子 + hook_density + 段 ID 列表
  G. 综合技法评估：writing_style 枚举 + dominant_techniques + 密度
  H. 文档一致性：SKILL/RUNBOOK/README 版本 3.8.0 + aggregation schema 含 writing_techniques
  I. 端到端（上海堡垒）：两本书都能跑通且结果合理

用法：python scripts/audit/v38_acceptance.py
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
ANNOT = WORKSPACE / "outputs" / "annotations"

MOON_STRUCTURE = ANNOT / "moon_sixpence_zh" / "moon_sixpence_zh_structure.jsonl"
MOON_INTERPRETATION = ANNOT / "moon_sixpence_zh" / "moon_sixpence_zh_interpretation.jsonl"
MOON_CROSS = ANNOT / "moon_sixpence_zh" / "moon_sixpence_zh_cross_segment.jsonl"

SHANGHAI_STRUCTURE = ANNOT / "shanghai_fortress_zh" / "shanghai_fortress_zh_structure.jsonl"
SHANGHAI_INTERPRETATION = ANNOT / "shanghai_fortress_zh" / "shanghai_fortress_zh_interpretation.jsonl"
SHANGHAI_CROSS = ANNOT / "shanghai_fortress_zh" / "shanghai_fortress_zh_cross_segment.jsonl"

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


def run_writing_techniques(structure_path: Path, interpretation_path: Path,
                            cross_path: Path, doc_id: str, out_dir: Path) -> tuple[int, str, str]:
    cmd = [sys.executable, str(SCRIPTS / "aggregation" / "writing_techniques.py"),
           "--structure", str(structure_path),
           "--interpretation", str(interpretation_path),
           "--cross-segment", str(cross_path),
           "--doc-id", doc_id, "--output-dir", str(out_dir)]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return proc.returncode, proc.stdout, proc.stderr


# ============================================================================
# A. 产物格式
# ============================================================================
print("\n=== A. 产物格式（py_compile）===")

try:
    py_compile.compile(str(SCRIPTS / "aggregation" / "writing_techniques.py"), doraise=True)
    check("A-writing_techniques-py_compile", True, "编译通过")
except py_compile.PyCompileError as e:
    check("A-writing_techniques-py_compile", False, str(e)[:200])

check("A-script-exists", (SCRIPTS / "aggregation" / "writing_techniques.py").exists())

# ============================================================================
# B. 脚本功能（月亮）
# ============================================================================
print("\n=== B. 脚本功能（月亮与六便士）===")

moon_data = None
with tempfile.TemporaryDirectory() as tmpdir:
    tmp = Path(tmpdir)
    rc, out, err = run_writing_techniques(MOON_STRUCTURE, MOON_INTERPRETATION, MOON_CROSS,
                                            "moon_sixpence_zh", tmp)
    check("B-moon-rc0", rc == 0, f"rc={rc}")
    out_file = tmp / "moon_sixpence_zh_writing_techniques.json"
    check("B-moon-output-exists", out_file.exists())

    if out_file.exists():
        moon_data = json.loads(io.open(out_file, encoding="utf-8").read())
        check("B-moon-schema-version", moon_data.get("schema_version") == "3.1.0",
              f"schema_version={moon_data.get('schema_version')}")
        check("B-moon-doc-id", moon_data.get("document_id") == "moon_sixpence_zh")
        check("B-moon-total-segments", moon_data.get("total_segments") == 89,
              f"total={moon_data.get('total_segments')}")
        check("B-moon-has-transitions", "transitions" in moon_data)
        check("B-moon-has-suspense", "suspense" in moon_data)
        check("B-moon-has-montage", "montage" in moon_data)
        check("B-moon-has-hooks", "hooks" in moon_data)
        check("B-moon-has-overall", "overall_assessment" in moon_data)

# ============================================================================
# C. 转场技巧
# ============================================================================
print("\n=== C. 转场技巧 ===")

if moon_data is not None:
    tr = moon_data["transitions"]
    check("C-transitions-total", isinstance(tr.get("total_transitions"), int) and tr["total_transitions"] >= 0)
    check("C-transitions-time", isinstance(tr.get("time_transitions"), int))
    check("C-transitions-space", isinstance(tr.get("space_transitions"), int) and tr["space_transitions"] > 0,
          f"space={tr.get('space_transitions')}（月亮场景频繁切换，应>0）")
    check("C-transitions-detail", isinstance(tr.get("detail_transitions"), int))
    check("C-transitions-suspense", isinstance(tr.get("suspense_transitions"), int))
    check("C-transitions-density", 0 <= tr.get("transition_density", -1) <= 2,
          f"density={tr.get('transition_density')}（应 0-2）")
    check("C-transitions-detail-list", isinstance(tr.get("transitions"), list))
    # 验证转场详情字段
    if tr.get("transitions"):
        first = tr["transitions"][0]
        check("C-transition-fields", all(k in first for k in ["from_segment_id", "to_segment_id", "transition_types"]),
              "转场详情字段完整")
        check("C-transition-type-fields", all(k in first["transition_types"][0] for k in ["type"]),
              "转场类型含 type 字段")
else:
    check("C-transitions-skipped", False, "moon_data 为 None，跳过")

# ============================================================================
# D. 悬念设置
# ============================================================================
print("\n=== D. 悬念设置 ===")

if moon_data is not None:
    sus = moon_data["suspense"]
    check("D-suspense-hidden-count", isinstance(sus.get("total_hidden_segments"), int) and sus["total_hidden_segments"] > 0,
          f"hidden={sus.get('total_hidden_segments')}（月亮有 6 个隐藏段，应>0）")
    check("D-suspense-setup-questions", isinstance(sus.get("setup_questions_count"), int))
    check("D-suspense-serial", isinstance(sus.get("serial_suspense_count"), int))
    check("D-suspense-unresolved", isinstance(sus.get("unresolved_suspense_count"), int))
    check("D-suspense-foreshadow", isinstance(sus.get("foreshadow_payoff_pairs"), int) and sus["foreshadow_payoff_pairs"] > 0,
          f"foreshadow={sus.get('foreshadow_payoff_pairs')}（月亮 cross_refs 有 4 对伏笔回收，应>0）")
    valid_intensity = {"low", "moderate", "high"}
    check("D-suspense-intensity-valid", sus.get("suspense_intensity") in valid_intensity,
          f"intensity={sus.get('suspense_intensity')}")
    check("D-suspense-derivation", "D06_hide_pattern_sequence" in sus.get("derivation_method", ""))
    # 验证伏笔回收对详情
    if sus.get("foreshadow_pairs_detail"):
        first = sus["foreshadow_pairs_detail"][0]
        check("D-foreshadow-fields", all(k in first for k in ["ref_id", "foreshadow_segment", "payoff_segment"]),
              "伏笔回收对详情字段完整")
else:
    check("D-suspense-skipped", False, "moon_data 为 None，跳过")

# ============================================================================
# E. 蒙太奇手法
# ============================================================================
print("\n=== E. 蒙太奇手法 ===")

if moon_data is not None:
    mon = moon_data["montage"]
    check("E-montage-parallel", isinstance(mon.get("parallel_montage_count"), int))
    check("E-montage-cross", isinstance(mon.get("cross_montage_count"), int))
    check("E-montage-contrast", isinstance(mon.get("contrast_montage_count"), int))
    check("E-montage-total", isinstance(mon.get("total_montage_instances"), int) and mon["total_montage_instances"] >= 0)
    check("E-montage-density", 0 <= mon.get("montage_density", -1) <= 2,
          f"density={mon.get('montage_density')}（应 0-2）")
    check("E-montage-parallel-list", isinstance(mon.get("parallel_montage"), list))
    # 验证平行蒙太奇详情字段
    if mon.get("parallel_montage"):
        first = mon["parallel_montage"][0]
        check("E-parallel-fields", all(k in first for k in ["start_segment_index", "end_segment_index", "location_changes"]),
              "平行蒙太奇详情字段完整")
    check("E-montage-derivation", "sliding_window" in mon.get("derivation_method", ""))
else:
    check("E-montage-skipped", False, "moon_data 为 None，跳过")

# ============================================================================
# F. 钩子类型
# ============================================================================
print("\n=== F. 钩子类型 ===")

if moon_data is not None:
    hk = moon_data["hooks"]
    check("F-hooks-total", isinstance(hk.get("total_hooked_segments"), int) and hk["total_hooked_segments"] > 0)
    check("F-hooks-suspense", isinstance(hk.get("suspense_hooks_count"), int))
    check("F-hooks-action", isinstance(hk.get("action_hooks_count"), int) and hk["action_hooks_count"] > 0,
          f"action={hk.get('action_hooks_count')}（月亮有高潮段，应>0）")
    check("F-hooks-emotion", isinstance(hk.get("emotion_hooks_count"), int))
    check("F-hooks-scene", isinstance(hk.get("scene_hooks_count"), int) and hk["scene_hooks_count"] > 0,
          f"scene={hk.get('scene_hooks_count')}（月亮场景切换多，应>0）")
    check("F-hooks-density", 0 <= hk.get("hook_density", -1) <= 1,
          f"density={hk.get('hook_density')}（应 0-1）")
    check("F-hooks-suspense-list", isinstance(hk.get("suspense_hook_segments"), list))
    check("F-hooks-action-list", isinstance(hk.get("action_hook_segments"), list))
    check("F-hooks-derivation", "segment_tail" in hk.get("derivation_method", ""))
else:
    check("F-hooks-skipped", False, "moon_data 为 None，跳过")

# ============================================================================
# G. 综合技法评估
# ============================================================================
print("\n=== G. 综合技法评估 ===")

if moon_data is not None:
    oa = moon_data["overall_assessment"]
    check("G-overall-total", isinstance(oa.get("total_technique_instances"), int) and oa["total_technique_instances"] > 0)
    check("G-overall-density", isinstance(oa.get("technique_density_per_segment"), float) and oa["technique_density_per_segment"] > 0)
    valid_styles = {"技法密集型（高技巧写作）", "技法均衡型（标准叙事）", "技法简约型（白描风格）"}
    check("G-overall-style-valid", oa.get("writing_style") in valid_styles,
          f"style={oa.get('writing_style')}")
    # 月亮是标准叙事，应为技法均衡型
    check("G-overall-moon-balanced", oa.get("writing_style") == "技法均衡型（标准叙事）",
          f"月亮应为技法均衡型，实际={oa.get('writing_style')}")
    check("G-overall-dominant", isinstance(oa.get("dominant_techniques"), list) and len(oa["dominant_techniques"]) == 4,
          f"dominant={oa.get('dominant_techniques')}（应 4 项排序）")
    check("G-overall-note", "note" in oa)
else:
    check("G-overall-skipped", False, "moon_data 为 None，跳过")

# ============================================================================
# H. 文档一致性
# ============================================================================
print("\n=== H. 文档一致性 ===")

skill_md = io.open(SKILL_ROOT / "SKILL.md", encoding="utf-8").read()
runbook = io.open(SKILL_ROOT / "docs" / "RUNBOOK.md", encoding="utf-8").read()
readme = io.open(SKILL_ROOT / "README.md", encoding="utf-8").read()
agg_schema = io.open(SKILL_ROOT / "references" / "aggregation-schema.md", encoding="utf-8").read()

check("H-SKILL-version-3.8.0", "version: 3.8.0" in skill_md)
check("H-SKILL-title-3.8.0", "v3.8.0" in skill_md)
check("H-SKILL-v3.8.0-history", "3.8.0" in skill_md and "叙事技法分析" in skill_md)
check("H-SKILL-writing_techniques-in-workflow", "writing_techniques.py" in skill_md and "⑥" in skill_md)
check("H-SKILL-10-scripts", "10 个脚本" in skill_md or "10 脚本" in skill_md)

check("H-RUNBOOK-version-3.8.0", "v3.8.0" in runbook)
check("H-RUNBOOK-writing_techniques-cli", "writing_techniques.py" in runbook)
check("H-RUNBOOK-10-scripts", "10 脚本" in runbook)

check("H-README-version-3.8.0", "v3.8.0" in readme)
check("H-README-writing_techniques-tree", "writing_techniques.py" in readme)
check("H-README-aggregation-schema-3.1.0", "3.1.0" in readme)

check("H-agg-schema-version-3.1.0", "v3.1.0" in agg_schema)
check("H-agg-schema-writing_techniques-section", "writing_techniques.json" in agg_schema and "转场技巧" in agg_schema)
check("H-agg-schema-section-10", "## 十、writing_techniques.json" in agg_schema)

# ============================================================================
# I. 端到端（上海堡垒）
# ============================================================================
print("\n=== I. 端到端（上海堡垒）===")

if SHANGHAI_STRUCTURE.exists() and SHANGHAI_INTERPRETATION.exists():
    sh_data = None
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        rc, out, err = run_writing_techniques(SHANGHAI_STRUCTURE, SHANGHAI_INTERPRETATION, SHANGHAI_CROSS,
                                                "shanghai_fortress_zh", tmp)
        check("I-shanghai-rc0", rc == 0, f"rc={rc}")
        sh_file = tmp / "shanghai_fortress_zh_writing_techniques.json"
        if sh_file.exists():
            sh_data = json.loads(io.open(sh_file, encoding="utf-8").read())

    if sh_data is not None:
        check("I-shanghai-total-segments", sh_data.get("total_segments") == 63,
              f"total={sh_data.get('total_segments')}")
        check("I-shanghai-4-submodules", all(k in sh_data for k in ["transitions", "suspense", "montage", "hooks"]))
        # 上海堡垒是科幻战争，悬念强度应≥moderate
        sh_sus = sh_data["suspense"]
        check("I-shanghai-suspense-high-or-moderate",
              sh_sus.get("suspense_intensity") in ("high", "moderate"),
              f"上海堡垒悬念强度={sh_sus.get('suspense_intensity')}（应 high/moderate）")
        # 上海堡垒技法密度应高于月亮（战争题材快节奏）
        sh_oa = sh_data["overall_assessment"]
        moon_oa = moon_data["overall_assessment"] if moon_data else {"technique_density_per_segment": 0}
        check("I-shanghai-density-higher-than-moon",
              sh_oa.get("technique_density_per_segment", 0) >= moon_oa.get("technique_density_per_segment", 0),
              f"上海={sh_oa.get('technique_density_per_segment')} vs 月亮={moon_oa.get('technique_density_per_segment')}")
        # 上海堡垒应为技法密集型
        check("I-shanghai-dense-style", sh_oa.get("writing_style") == "技法密集型（高技巧写作）",
              f"上海堡垒应为技法密集型，实际={sh_oa.get('writing_style')}")
else:
    check("I-shanghai-skipped", True, f"测试文件不存在")

# ============================================================================
# 汇总
# ============================================================================
print(f"\n{'='*60}")
print(f"v3.8.0 验收汇总：PASS={PASS}  FAIL={FAIL}  TOTAL={PASS+FAIL}")
if FAIL == 0:
    print("ALL PASS ✅")
else:
    print(f"有 {FAIL} 项失败 ❌")
    for name, ok, detail in RESULTS:
        if not ok:
            print(f"  FAIL: {name} — {detail}")
print(f"{'='*60}")

sys.exit(0 if FAIL == 0 else 1)
