#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/audit/v3131_acceptance.py — v3.13.1 验收脚本（T-116）

验收项：
1. py_compile 所有修改过的脚本
2. causal_graph.py 新字段存在（event_hierarchy/causal_structure/event_attributes/salience_score）
3. character_arcs.py 新字段存在（character_type/character_depth/agency_curve/density_distribution/dialogue_dominance）
4. scratchpad.py 新功能存在（D10.speaker抽取/代词回指/D06伏笔-回收/编辑距离增强）
5. character_biographies.py 集成新字段
6. render_report.py 新增2章节
7. 文档版本号同步 3.13.1
8. 自测试通过（scratchpad --self-test）
"""
import json
import sys
import subprocess
from pathlib import Path

SKILL_DIR = Path(__file__).parent.parent.parent
SCRIPTS_DIR = SKILL_DIR / "scripts"
AGG_DIR = SCRIPTS_DIR / "aggregation"

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
    print("v3.13.1 验收脚本（T-116）")
    print("=" * 60)

    # 1. py_compile 所有修改过的脚本
    print("\n--- 1. 语法检查 ---")
    scripts_to_check = [
        AGG_DIR / "causal_graph.py",
        AGG_DIR / "character_arcs.py",
        AGG_DIR / "character_biographies.py",
        SCRIPTS_DIR / "scratchpad.py",
        SCRIPTS_DIR / "render_report.py",
    ]
    for script in scripts_to_check:
        check(f"py_compile {script.name}", py_compile(script))

    # 2. causal_graph.py 新字段
    print("\n--- 2. causal_graph.py 新字段 ---")
    cg_content = (AGG_DIR / "causal_graph.py").read_text(encoding="utf-8")
    check("event_hierarchy 存在", "event_hierarchy" in cg_content)
    check("causal_structure 存在", "causal_structure" in cg_content)
    check("event_attributes 存在", "event_attributes" in cg_content)
    check("salience_score 存在", "salience_score" in cg_content)
    check("SALIENCE_WEIGHTS 常量存在", "SALIENCE_WEIGHTS" in cg_content)
    check("SCHEMA_VERSION 3.4.0", 'SCHEMA_VERSION = "3.4.0"' in cg_content)

    # 3. character_arcs.py 新字段
    print("\n--- 3. character_arcs.py 新字段 ---")
    ca_content = (AGG_DIR / "character_arcs.py").read_text(encoding="utf-8")
    check("character_type 存在", "character_type" in ca_content)
    check("character_depth 存在", "character_depth" in ca_content)
    check("agency_curve 存在", "agency_curve" in ca_content)
    check("density_distribution 存在", "density_distribution" in ca_content)
    check("dialogue_dominance 存在", "dialogue_dominance" in ca_content)
    check("complexity_score 存在", "complexity_score" in ca_content)
    check("COMPLEXITY_WEIGHTS 常量存在", "COMPLEXITY_WEIGHTS" in ca_content)
    check("SCHEMA_VERSION 3.4.0", 'SCHEMA_VERSION = "3.4.0"' in ca_content)

    # 4. scratchpad.py 新功能
    print("\n--- 4. scratchpad.py 新功能 ---")
    sp_content = (SCRIPTS_DIR / "scratchpad.py").read_text(encoding="utf-8")
    check("D10.speaker 人物抽取存在", "D10_dialogue" in sp_content or "D10" in sp_content)
    check("代词回指处理存在", "has_first_person" in sp_content or "第一人称" in sp_content)
    check("D06 伏笔-回收事件对存在", "伏笔" in sp_content or "previous_plant" in sp_content)
    check("编辑距离别名匹配增强存在", "HONORIFIC_SUFFIXES" in sp_content)
    check("find_similar_character 阈值0.5", "threshold: float = 0.5" in sp_content)
    check("SCHEMA_VERSION 3.13.1", 'SCHEMA_VERSION = "3.13.1"' in sp_content)

    # 5. character_biographies.py 集成新字段
    print("\n--- 5. character_biographies.py 集成 ---")
    cb_content = (AGG_DIR / "character_biographies.py").read_text(encoding="utf-8")
    check("character_type 集成存在", "character_type" in cb_content)
    check("character_depth 集成存在", "character_depth" in cb_content)
    check("agency_curve 集成存在", "agency_curve" in cb_content)
    check("appearance_stats 集成存在", "appearance_stats" in cb_content)
    check("dialogue_dominance 集成存在", "dialogue_dominance" in cb_content)

    # 6. render_report.py 新增2章节
    print("\n--- 6. render_report.py 新增章节 ---")
    rr_content = (SCRIPTS_DIR / "render_report.py").read_text(encoding="utf-8")
    check("事件显赫度分析章节存在", "事件显赫度分析" in rr_content)
    check("人物能动性分析章节存在", "人物能动性分析" in rr_content)
    check("salience_score 排行存在", "salience_score" in rr_content)
    check("agency_distribution 存在", "agency_distribution" in rr_content)

    # 7. 文档版本号同步
    print("\n--- 7. 文档版本号 ---")
    skill_md = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    check("SKILL.md version 3.13.1", "version: 3.13.1" in skill_md)
    check("SKILL.md 标题 v3.13.1", "v3.13.1" in skill_md)
    runbook_md = (SKILL_DIR / "docs" / "RUNBOOK.md")
    if runbook_md.is_file():
        check("RUNBOOK.md v3.13.1", "3.13.1" in runbook_md.read_text(encoding="utf-8"))
    readme_md = (SKILL_DIR / "README.md")
    if readme_md.is_file():
        check("README.md v3.13.1", "3.13.1" in readme_md.read_text(encoding="utf-8"))
    agg_schema = (SKILL_DIR / "references" / "aggregation-schema.md")
    if agg_schema.is_file():
        check("aggregation-schema.md v3.4.0", "v3.4.0" in agg_schema.read_text(encoding="utf-8"))

    # 8. scratchpad 自测试
    print("\n--- 8. scratchpad 自测试 ---")
    result = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "scratchpad.py"), "--self-test"],
        capture_output=True, text=True
    )
    check("scratchpad --self-test 通过", "12/12 PASS" in result.stdout or "ALL PASS" in result.stdout,
          f"exit_code={result.returncode}")

    # 输出结果
    print("\n" + "=" * 60)
    print("验收结果")
    print("=" * 60)
    for r in RESULTS:
        print(r)
    print(f"\n总计: {PASS} PASS / {FAIL} FAIL / {PASS + FAIL} 项")
    if FAIL == 0:
        print("\n✅ v3.13.1 验收全部通过！")
    else:
        print(f"\n❌ 有 {FAIL} 项未通过，请检查。")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
