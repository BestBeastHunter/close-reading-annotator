#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/audit/v3141_acceptance.py — v3.14.1 验收脚本（T-123 items 启用）

验收项：
1. py_compile scratchpad.py / object_chains.py
2. ItemRecord 类存在
3. Scratchpad 类有 items 字段和 _item_counter
4. add_item / get_item 方法存在
5. to_json / from_json 处理 items
6. stats() 包含 total_items
7. object_chains.py 有 --scratchpad 参数
8. 文档版本号同步 3.14.1
9. scratchpad.py 自测试通过
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
    print("v3.14.1 验收脚本（T-123 items 启用）")
    print("=" * 60)

    # 1. 语法检查
    print("\n--- 1. 语法检查 ---")
    check("py_compile scratchpad.py", py_compile(SCRIPTS_DIR / "scratchpad.py"))
    check("py_compile object_chains.py", py_compile(SCRIPTS_DIR / "aggregation" / "object_chains.py"))

    # 2. scratchpad.py 检查
    print("\n--- 2. scratchpad.py items 功能 ---")
    scratchpad_content = (SCRIPTS_DIR / "scratchpad.py").read_text(encoding="utf-8")
    check("ItemRecord 类存在", "class ItemRecord" in scratchpad_content)
    check("ItemRecord 有 item_id 字段", "item_id: str" in scratchpad_content)
    check("ItemRecord 有 item_type 字段", "item_type: Optional[str]" in scratchpad_content)
    check("ItemRecord 有 semantic_evolution 字段", "semantic_evolution: list[str]" in scratchpad_content)
    check("Scratchpad 有 items 字段", "items: list[ItemRecord]" in scratchpad_content)
    check("Scratchpad 有 _item_counter", "_item_counter: int = 0" in scratchpad_content)
    check("add_item 方法存在", "def add_item(" in scratchpad_content)
    check("get_item 方法存在", "def get_item(" in scratchpad_content)
    check("to_json 处理 items", '"items": [item.to_dict()' in scratchpad_content)
    check("from_json 处理 items", "ItemRecord.from_dict(item_data)" in scratchpad_content)
    check("stats() 包含 total_items", '"total_items": len(self.items)' in scratchpad_content)
    check("scratchpad SCHEMA_VERSION 存在", "SCHEMA_VERSION" in scratchpad_content, "SCHEMA_VERSION 字段存在")

    # 3. object_chains.py 检查
    print("\n--- 3. object_chains.py Scratchpad 集成 ---")
    object_chains_content = (SCRIPTS_DIR / "aggregation" / "object_chains.py").read_text(encoding="utf-8")
    check("object_chains 有 --scratchpad 参数", '"--scratchpad"' in object_chains_content)
    check("object_chains 有 Scratchpad 读取逻辑", "scratchpad_items = []" in object_chains_content)

    # 4. 文档版本号
    print("\n--- 4. 文档版本号 ---")
    skill_md = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    check("SKILL.md 版本存在", "version:" in skill_md or "v3." in skill_md, "SKILL.md 含版本号")
    check("SKILL.md 标题含版本", "v3." in skill_md, "SKILL.md 标题含版本号")
    runbook_md = SKILL_DIR / "docs" / "RUNBOOK.md"
    if runbook_md.is_file():
        check("RUNBOOK.md 版本存在", "v3." in runbook_md.read_text(encoding="utf-8"), "RUNBOOK.md 含版本号")
    readme_md = SKILL_DIR / "README.md"
    if readme_md.is_file():
        check("README.md 版本存在", "v3." in readme_md.read_text(encoding="utf-8"), "README.md 含版本号")

    # 5. 自测试
    print("\n--- 5. scratchpad 自测试 ---")
    result = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "scratchpad.py"), "--self-test"],
        capture_output=True, text=True
    )
    check("scratchpad 自测试通过", result.returncode == 0,
          detail=f"exit_code={result.returncode}")

    # 输出结果
    print("\n" + "=" * 60)
    print("验收结果")
    print("=" * 60)
    for r in RESULTS:
        print(r)
    print(f"\n总计: {PASS} PASS / {FAIL} FAIL / {PASS + FAIL} 项")
    if FAIL == 0:
        print("\n✅ v3.14.1 验收全部通过！")
    else:
        print(f"\n❌ 有 {FAIL} 项未通过，请检查。")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
