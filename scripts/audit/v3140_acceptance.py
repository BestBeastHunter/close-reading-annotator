#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/audit/v3140_acceptance.py — v3.14.0 验收脚本（T-124）

验收项：
1. py_compile causal_graph.py / character_arcs.py / entity_resolution.py
2. T-121：event_function + narrative_speed 存在
3. T-122：actantial_role + desire_structure 存在
4. T-120：entity_resolution --scratchpad 参数存在
5. 文档版本号同步 3.14.0
6. aggregation schema 3.5.0
"""
import sys
import subprocess
from pathlib import Path

SKILL_DIR = Path(__file__).parent.parent.parent
SCRIPTS_DIR = SKILL_DIR / "scripts"

PASS = 0
FAIL = 0
RESULTS = []


def check(name: str, condition: bool, detail: str = ""):
    global PASS, FAIL
    if condition:
        PASS += 1
        RESULTS.append(f"[PASS] {name}" + (f" — {detail}" if detail else ""))
    else:
        FAIL += 1
        RESULTS.append(f"[FAIL] {name}" + (f" — {detail}" if detail else ""))


def py_compile(path: Path) -> bool:
    result = subprocess.run(
        [sys.executable, "-m", "py_compile", str(path)],
        capture_output=True, text=True
    )
    return result.returncode == 0


def main():
    print("=" * 60)
    print("v3.14.0 验收脚本（T-124）")
    print("=" * 60)

    # 1. 语法检查
    print("\n--- 1. 语法检查 ---")
    check("py_compile causal_graph.py", py_compile(SCRIPTS_DIR / "aggregation" / "causal_graph.py"))
    check("py_compile character_arcs.py", py_compile(SCRIPTS_DIR / "aggregation" / "character_arcs.py"))
    check("py_compile entity_resolution.py", py_compile(SCRIPTS_DIR / "aggregation" / "entity_resolution.py"))

    # 2. T-121：事件分析增强
    print("\n--- 2. T-121 事件分析增强 ---")
    causal_content = (SCRIPTS_DIR / "aggregation" / "causal_graph.py").read_text(encoding="utf-8")
    check("compute_event_function 函数存在", "def compute_event_function" in causal_content)
    check("compute_narrative_speed 函数存在", "def compute_narrative_speed" in causal_content)
    check("nodes 包含 event_function 字段", '"event_function"' in causal_content)
    check("nodes 包含 narrative_speed 字段", '"narrative_speed"' in causal_content)
    check("statistics 包含 event_function_distribution", "event_function_distribution" in causal_content)
    check("statistics 包含 narrative_speed_distribution", "narrative_speed_distribution" in causal_content)
    check("causal_graph SCHEMA_VERSION 3.5.0", 'SCHEMA_VERSION = "3.5.0"' in causal_content)

    # 3. T-122：人物分析增强
    print("\n--- 3. T-122 人物分析增强 ---")
    arcs_content = (SCRIPTS_DIR / "aggregation" / "character_arcs.py").read_text(encoding="utf-8")
    check("compute_actantial_role 函数存在", "def compute_actantial_role" in arcs_content)
    check("compute_desire_structure 函数存在", "def compute_desire_structure" in arcs_content)
    check("character_arc 包含 actantial_role 字段", '"actantial_role"' in arcs_content)
    check("character_arc 包含 desire_structure 字段", '"desire_structure"' in arcs_content)
    check("character_arcs SCHEMA_VERSION 3.5.0", 'SCHEMA_VERSION = "3.5.0"' in arcs_content)

    # 4. T-120：聚合层利用 Scratchpad
    print("\n--- 4. T-120 聚合层利用 Scratchpad ---")
    entity_content = (SCRIPTS_DIR / "aggregation" / "entity_resolution.py").read_text(encoding="utf-8")
    check("entity_resolution --scratchpad 参数存在", '"--scratchpad"' in entity_content)
    check("entity_resolution scratchpad_enabled 记录", "scratchpad_enabled" in entity_content)

    # 5. 文档版本号
    print("\n--- 5. 文档版本号 ---")
    skill_md = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    check("SKILL.md version 3.14.0", "version: 3.14.0" in skill_md)
    check("SKILL.md 标题 v3.14.0", "v3.14.0" in skill_md)
    runbook_md = SKILL_DIR / "docs" / "RUNBOOK.md"
    if runbook_md.is_file():
        check("RUNBOOK.md v3.14.0", "3.14.0" in runbook_md.read_text(encoding="utf-8"))
    readme_md = SKILL_DIR / "README.md"
    if readme_md.is_file():
        check("README.md v3.14.0", "3.14.0" in readme_md.read_text(encoding="utf-8"))
    agg_schema = SKILL_DIR / "references" / "aggregation-schema.md"
    if agg_schema.is_file():
        check("aggregation-schema.md v3.5.0", "3.5.0" in agg_schema.read_text(encoding="utf-8"))

    # 输出结果
    print("\n" + "=" * 60)
    print("验收结果")
    print("=" * 60)
    for r in RESULTS:
        print(r)
    print(f"\n总计: {PASS} PASS / {FAIL} FAIL / {PASS + FAIL} 项")
    if FAIL == 0:
        print("\n✅ v3.14.0 验收全部通过！")
    else:
        print(f"\n❌ 有 {FAIL} 项未通过，请检查。")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
