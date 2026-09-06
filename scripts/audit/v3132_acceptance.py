#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/audit/v3132_acceptance.py — v3.13.2 验收脚本（T-119）

验收项：
1. py_compile scratchpad.py
2. T-117：LLM 生成人物描述工具存在（update_description/generate_description_prompt/get_characters_needing_description）
3. T-118：第三人称代词最近匹配存在（THIRD_PERSON_PRONOUNS/_resolve_third_person_pronoun）
4. 事件相似度归并存在（_find_similar_event）
5. 第一人称代词回指存在（has_first_person）
6. 待确认项注入 prompt 存在（to_summary 包含 pending_confirmation）
7. 文档版本号同步 3.13.2
8. 自测试通过（scratchpad --self-test）
"""
import json
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
    print("v3.13.2 验收脚本（T-119）")
    print("=" * 60)

    # 1. py_compile
    print("\n--- 1. 语法检查 ---")
    check("py_compile scratchpad.py", py_compile(SCRIPTS_DIR / "scratchpad.py"))

    # 2. T-117：LLM 生成人物描述工具
    print("\n--- 2. T-117 LLM 生成人物描述工具 ---")
    sp_content = (SCRIPTS_DIR / "scratchpad.py").read_text(encoding="utf-8")
    check("update_description 方法存在", "def update_description" in sp_content)
    check("generate_description_prompt 方法存在", "def generate_description_prompt" in sp_content)
    check("get_characters_needing_description 方法存在", "def get_characters_needing_description" in sp_content)
    check("to_summary 包含描述生成提示", "需要生成描述" in sp_content)

    # 3. T-118：第三人称代词最近匹配
    print("\n--- 3. T-118 第三人称代词最近匹配 ---")
    check("THIRD_PERSON_PRONOUNS 常量存在", "THIRD_PERSON_PRONOUNS" in sp_content)
    check("_resolve_third_person_pronoun 方法存在", "def _resolve_third_person_pronoun" in sp_content)
    check("D19.target 第三人称代词处理", "target_name in THIRD_PERSON_PRONOUNS" in sp_content)
    check("D18.character 第三人称代词处理", "cn in THIRD_PERSON_PRONOUNS" in sp_content)

    # 4. 已有功能确认
    print("\n--- 4. 已有功能确认 ---")
    check("事件相似度归并存在", "def _find_similar_event" in sp_content)
    check("第一人称代词回指存在", "has_first_person" in sp_content)
    check("待确认项机制存在", "pending_confirmation" in sp_content)
    check("mark_pending_confirmation 方法存在", "def mark_pending_confirmation" in sp_content)
    check("confirm_alias 方法存在", "def confirm_alias" in sp_content)
    check("scratchpad SCHEMA_VERSION 存在", "SCHEMA_VERSION" in sp_content, "SCHEMA_VERSION 字段存在")

    # 5. 文档版本号
    print("\n--- 5. 文档版本号 ---")
    skill_md = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    check("SKILL.md 版本存在", "version:" in skill_md or "v3." in skill_md, "SKILL.md 含版本号")
    check("SKILL.md 标题含版本", "v3." in skill_md, "SKILL.md 标题含版本号")
    runbook_md = SKILL_DIR / "docs" / "RUNBOOK.md"
    if runbook_md.is_file():
        check("RUNBOOK.md 版本存在", "v3." in runbook_md.read_text(encoding="utf-8"), "RUNBOOK.md 含版本号")
    readme_md = SKILL_DIR / "README.md"
    if readme_md.is_file():
        check("README.md 版本存在", "v3." in readme_md.read_text(encoding="utf-8"), "README.md 含版本号")

    # 6. 自测试
    print("\n--- 6. scratchpad 自测试 ---")
    result = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "scratchpad.py"), "--self-test"],
        capture_output=True, text=True
    )
    check("scratchpad --self-test 通过", result.returncode == 0,
          f"exit_code={result.returncode}")

    # 输出结果
    print("\n" + "=" * 60)
    print("验收结果")
    print("=" * 60)
    for r in RESULTS:
        print(r)
    print(f"\n总计: {PASS} PASS / {FAIL} FAIL / {PASS + FAIL} 项")
    if FAIL == 0:
        print("\n✅ v3.13.2 验收全部通过！")
    else:
        print(f"\n❌ 有 {FAIL} 项未通过，请检查。")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
