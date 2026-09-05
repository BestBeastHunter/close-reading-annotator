#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/audit/v36_acceptance.py — v3.6.0 验收脚本（T-035 / ADR-014 决定 3）

覆盖：
  A. 产物格式：schema.md / validate_output.py / templates py_compile
  B. schema.md 一致性：版本 2.10.0 + 5 字段定义存在
  C. validate_output.py：枚举常量存在 + 校验逻辑存在
  D. templates：structure/interpretation 模板包含新字段
  E. 文档一致性：SKILL/RUNBOOK/README 版本 3.6.0 + schema 2.10.0
  F. 端到端：合法 structure JSON 通过 validate；非法枚举值报错

用法：python scripts/audit/v36_acceptance.py
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
REFERENCES = SKILL_ROOT / "references"
TEMPLATES = SKILL_ROOT / "templates"

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


def run_validate(ann: dict) -> tuple[int, str, str]:
    """跑 validate_output.py 校验单条 JSON。"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False, encoding="utf-8") as f:
        f.write(json.dumps(ann, ensure_ascii=False) + "\n")
        tmp_path = f.name
    cmd = [sys.executable, str(SCRIPTS / "validate_output.py"), "--jsonl", tmp_path, "--layer-type", "structure"]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return proc.returncode, proc.stdout, proc.stderr


# ============================================================================
# A. 产物格式
# ============================================================================
print("\n=== A. 产物格式（py_compile）===")

for fname in ["validate_output.py"]:
    try:
        py_compile.compile(str(SCRIPTS / fname), doraise=True)
        check(f"A-{fname}-py_compile", True, "编译通过")
    except py_compile.PyCompileError as e:
        check(f"A-{fname}-py_compile", False, str(e)[:200])

check("A-schema-md-exists", (REFERENCES / "schema.md").exists())
check("A-structure-template-exists", (TEMPLATES / "structure-output.json").exists())
check("A-interpretation-template-exists", (TEMPLATES / "interpretation-output.json").exists())

# ============================================================================
# B. schema.md 一致性
# ============================================================================
print("\n=== B. schema.md 一致性 ===")

schema_md = io.open(REFERENCES / "schema.md", encoding="utf-8").read()

check("B-schema-version-2.10.0", "v2.10.0" in schema_md and "2.10.0" in schema_md)
check("B-D07-narrator-identity", "_narrator_identity" in schema_md)
check("B-D08-time-type", "_time_type" in schema_md and "linear" in schema_md and "flashback" in schema_md)
check("B-D08-narrative-level", "_narrative_level" in schema_md and '"1"' in schema_md and '"2"' in schema_md and '"3+"' in schema_md)
check("B-D06-techniques", "_techniques" in schema_md and "延迟揭示" in schema_md and "选择性披露" in schema_md)
check("B-D12-narrative-mode", "D12_narrative_mode" in schema_md and "场景" in schema_md and "概述" in schema_md and "停顿" in schema_md and "省略" in schema_md and "摘要" in schema_md)
check("B-D12-density-is_summary-is_scene", "density" in schema_md and "is_summary" in schema_md and "is_scene" in schema_md)
check("B-v2.10.0-change-summary", "ADR-014" in schema_md and "原子化扩展字段" in schema_md)
check("B-output-example-2.10.0", '"schema_version": "2.10.0"' in schema_md)
check("B-output-example-D12", "D12_narrative_mode" in schema_md.split("Structure 层输出根结构")[1] if "Structure 层输出根结构" in schema_md else False)

# ============================================================================
# C. validate_output.py
# ============================================================================
print("\n=== C. validate_output.py 校验逻辑 ===")

validate_src = io.open(SCRIPTS / "validate_output.py", encoding="utf-8").read()

check("C-D08_TIME_TYPES-const", "D08_TIME_TYPES" in validate_src and "linear" in validate_src and "prolepsis" in validate_src)
check("C-D08_NARRATIVE_LEVELS-const", "D08_NARRATIVE_LEVELS" in validate_src)
check("C-D06_TECHNIQUES-const", "D06_TECHNIQUES" in validate_src and "延迟揭示" in validate_src)
check("C-D12_MODES-const", "D12_MODES" in validate_src and "场景" in validate_src and "省略" in validate_src)
check("C-D07-narrator-identity-check", "_narrator_identity" in validate_src)
check("C-D08-time-type-check", "_time_type" in validate_src and "D08_TIME_TYPES" in validate_src)
check("C-D08-narrative-level-check", "_narrative_level" in validate_src and "D08_NARRATIVE_LEVELS" in validate_src)
check("C-D12-narrative-mode-check", "D12_narrative_mode" in validate_src and "density" in validate_src and "is_summary" in validate_src and "is_scene" in validate_src)
check("C-D06-techniques-check", "_techniques" in validate_src and "D06_TECHNIQUES" in validate_src)

# ============================================================================
# D. templates
# ============================================================================
print("\n=== D. templates 字段包含 ===")

struct_tpl = json.loads(io.open(TEMPLATES / "structure-output.json", encoding="utf-8").read())
interp_tpl = json.loads(io.open(TEMPLATES / "interpretation-output.json", encoding="utf-8").read())

check("D-struct-schema-2.10.0", struct_tpl["schema_version"] == "2.10.0")
check("D-struct-D07-has-narrator-identity", "_narrator_identity" in struct_tpl["layers"]["structure"]["D07"])
check("D-struct-D08-has-time-type", "_time_type" in struct_tpl["layers"]["structure"]["D08"])
check("D-struct-D08-has-narrative-level", "_narrative_level" in struct_tpl["layers"]["structure"]["D08"])
check("D-struct-has-D12", "D12_narrative_mode" in struct_tpl["layers"]["structure"])
check("D-struct-D12-has-all-fields", all(k in struct_tpl["layers"]["structure"]["D12_narrative_mode"] for k in ["mode", "density", "is_summary", "is_scene"]))

check("D-interp-schema-2.10.0", interp_tpl["schema_version"] == "2.10.0")
check("D-interp-D06-has-techniques", "_techniques" in interp_tpl["layers"]["interpretation"]["D06_information_control"])
check("D-interp-D06-techniques-is-array", isinstance(interp_tpl["layers"]["interpretation"]["D06_information_control"]["_techniques"], list))

# ============================================================================
# E. 文档一致性
# ============================================================================
print("\n=== E. 文档一致性 ===")

skill_md = io.open(SKILL_ROOT / "SKILL.md", encoding="utf-8").read()
runbook = io.open(SKILL_ROOT / "docs" / "RUNBOOK.md", encoding="utf-8").read()
readme = io.open(SKILL_ROOT / "README.md", encoding="utf-8").read()

check("E-SKILL-version-3.6.0", "version: 3.6.0" in skill_md)
check("E-SKILL-title-3.6.0", "# 四层精读批注 Skill v3.6.0" in skill_md)
check("E-SKILL-schema-2.10.0", "2.10.0" in skill_md and "annotation schema_version" in skill_md)
check("E-SKILL-v3.6.0-history", "3.6.0" in skill_md and "原子化扩展字段" in skill_md)
check("E-SKILL-D12-in-layer1-table", "D12" in skill_md and "叙事话语模式" in skill_md)
check("E-SKILL-D06-techniques-in-layer2", "_techniques" in skill_md and "延迟揭示" in skill_md)

check("E-RUNBOOK-version-3.6.0", "v3.6.0" in runbook)
check("E-RUNBOOK-schema-2.10.0", "2.10.0" in runbook)

check("E-README-version-3.6.0", "v3.6.0" in readme)
check("E-README-schema-2.10.0", "2.10.0" in readme)
check("E-README-v3.6.0-history", "v3.6.0" in readme and "原子化扩展字段" in readme)

check("E-aggregation-schema-still-3.0.0", "3.0.0" in skill_md, "aggregation schema 仍为 3.0.0（不变）")

# ============================================================================
# F. 端到端（validate_output.py 实际运行）
# ============================================================================
print("\n=== F. 端到端（validate_output.py 实际运行）===")

# F1: 合法 structure JSON（含全部 5 个新字段）应通过
valid_ann = {
    "schema_version": "2.10.0",
    "annotation_id": "test_seg_0001_structure_ann_0",
    "document_id": "test",
    "segment_id": "test_seg_0001",
    "chapter": "第一章",
    "section_type": "body",
    "text_span": {"hash": "abc123", "start_char": 0, "end_char": 7, "text": "测试文本内容。"},
    "layers": {
        "structure": {
            "D01": "背景铺垫",
            "D04": {"core": "平静", "modifier": None, "intensity": 3, "polarity": "neutral"},
            "D05": 3,
            "D07": {"type": "第三人称有限", "is_switch_point": False, "switch_from": None, "switch_to": None, "_narrator_identity": "narrator_001"},
            "D08": {"time": "下午", "space": "客厅", "_time_type": "linear", "_narrative_level": "1"},
            "D10": None,
            "D11": ["环境描写"],
            "D12_narrative_mode": {"mode": "场景", "density": 0.85, "is_summary": False, "is_scene": True},
        }
    },
    "confidence": {"overall": 0.8, "confidence_method": "model_self_report", "per_dimension": {"D01": 0.9, "D04": 0.85, "D05": 0.9, "D07": 0.9, "D08": 0.85, "D10": 0.95, "D11": 0.9}},
    "null_reasons": {"D10": "无对话"},
    "alternatives": [],
    "status": "confirmed",
    "_metadata": {"skill_version": "3.6.0", "model": "test", "generated_at": "2026-09-05T00:00:00+08:00", "layer": "structure"},
}

rc, out, err = run_validate(valid_ann)
check("F1-valid-structure-pass", rc == 0, f"rc={rc}")

# F2: 非法 D08._time_type 应报错
invalid_ann = json.loads(json.dumps(valid_ann))
invalid_ann["layers"]["structure"]["D08"]["_time_type"] = "invalid_type"
rc, out, err = run_validate(invalid_ann)
check("F2-invalid-time-type-fail", rc != 0, f"rc={rc}（应报错）")

# F3: 非法 D12.mode 应报错
invalid_ann2 = json.loads(json.dumps(valid_ann))
invalid_ann2["layers"]["structure"]["D12_narrative_mode"]["mode"] = "非法模式"
rc, out, err = run_validate(invalid_ann2)
check("F3-invalid-D12-mode-fail", rc != 0, f"rc={rc}（应报错）")

# F4: 新字段全部 null 应通过（可选字段）
null_ann = json.loads(json.dumps(valid_ann))
null_ann["layers"]["structure"]["D07"]["_narrator_identity"] = None
null_ann["layers"]["structure"]["D08"]["_time_type"] = None
null_ann["layers"]["structure"]["D08"]["_narrative_level"] = None
null_ann["layers"]["structure"]["D12_narrative_mode"] = None
rc, out, err = run_validate(null_ann)
check("F4-all-new-fields-null-pass", rc == 0, f"rc={rc}（可选字段 null 应通过）")

# F5: 旧 schema 2.9.0 产物（无新字段）应通过（向后兼容）
legacy_ann = json.loads(json.dumps(valid_ann))
legacy_ann["schema_version"] = "2.9.0"
del legacy_ann["layers"]["structure"]["D07"]["_narrator_identity"]
del legacy_ann["layers"]["structure"]["D08"]["_time_type"]
del legacy_ann["layers"]["structure"]["D08"]["_narrative_level"]
del legacy_ann["layers"]["structure"]["D12_narrative_mode"]
rc, out, err = run_validate(legacy_ann)
check("F5-legacy-2.9.0-pass", rc == 0, f"rc={rc}（旧产物向后兼容）")

# ============================================================================
# 汇总
# ============================================================================
print(f"\n{'='*60}")
print(f"v3.6.0 验收汇总：PASS={PASS}  FAIL={FAIL}  TOTAL={PASS+FAIL}")
if FAIL == 0:
    print("ALL PASS ✅")
else:
    print(f"有 {FAIL} 项失败 ❌")
    for name, ok, detail in RESULTS:
        if not ok:
            print(f"  FAIL: {name} — {detail}")
print(f"{'='*60}")

sys.exit(0 if FAIL == 0 else 1)
