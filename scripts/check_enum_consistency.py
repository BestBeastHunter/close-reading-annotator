#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/check_enum_consistency.py — 枚举一致性自检（v3.15.0 新增，T-125）

用途：
  以 scripts/validate_output.py 的枚举常量集为唯一真源，解析 SKILL.md §4.0
  速查表，比对两者是否一致。任何不一致都会导致"按文档写被校验器拒"，
  本脚本让这类分裂在开发期就被发现。

用法：
  python scripts/check_enum_consistency.py
    → 0 不一致时 exit 0；有差异时逐条打印并 exit 1

设计：
  - validator 真源：用 ast 直接读取 validate_output.py 中的集合字面量
    （D01_VALUES / D04_CORE_VALUES / D07_TYPES / D10_VALUES / D11_VALUES /
     EMOTION_LEXICON_VALUES / RHETORIC_TYPES / IMAGERY_TYPES / POS_TYPES /
     SYNTAX_TYPES / D06_TYPES / NARRATOR_RELIABILITY_VALUES / D06_TECHNIQUES /
     D08_TIME_TYPES / D08_NARRATIVE_LEVELS / D12_MODES）
  - SKILL.md 侧：正则提取速查表行中反引号包裹的 `值`（以 / 分隔），
    与 validator 常量集做集合比对；SKILL 有而 validator 无 / validator 有而
    SKILL 缺 → 都算不一致。

零第三方依赖：仅 Python 3.8+ 标准库。
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VALIDATOR = ROOT / "scripts" / "validate_output.py"
SKILL_MD = ROOT / "SKILL.md"

# validator 中需要检查的常量名 → 说明
CHECKED_CONSTANTS = {
    "D01_VALUES": "D01 叙事功能",
    "D04_CORE_VALUES": "D04.core 情绪基调(20)",
    "D07_TYPES": "D07.type 叙事视角",
    "D10_VALUES": "D10 对话功能",
    "D11_VALUES": "D11 描写类型",
    "EMOTION_LEXICON_VALUES": "D19 情感词表(50)",
    "RHETORIC_TYPES": "D14 修辞手法",
    "IMAGERY_TYPES": "D15 意象类型",
    "POS_TYPES": "D16 词汇词性",
    "SYNTAX_TYPES": "D17 句式类型",
    "D06_TYPES": "D06.type 信息控制",
    "NARRATOR_RELIABILITY_VALUES": "narrator_reliability",
    "D08_TIME_TYPES": "D08._time_type",
    "D12_MODES": "D12.mode 叙事话语",
}


def load_validator_constants() -> dict[str, set[str]]:
    """用 ast 从 validate_output.py 提取集合常量。"""
    tree = ast.parse(VALIDATOR.read_text(encoding="utf-8"))
    out: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            name = node.targets[0].id if isinstance(node.targets[0], ast.Name) else ""
            if name in CHECKED_CONSTANTS and isinstance(node.value, ast.Set):
                out[name] = {
                    el.value for el in node.value.elts if isinstance(el, ast.Constant)
                }
    return out


def extract_skill_table() -> dict[str, set[str]]:
    """从 SKILL.md §4.0 速查表提取每个维度的合法值集合。

    解析规则：对形如 `| **D01** | ... | `a` / `b` / `c` |` 的行，
    取最后一列中所有反引号包裹、且不是说明文字的值。
    """
    out: dict[str, set[str]] = {}
    in_table = False
    for line in SKILL_MD.read_text(encoding="utf-8").splitlines():
        if line.startswith("### 4.0"):
            in_table = True
            continue
        if in_table and line.startswith("### "):
            break
        if not in_table or not line.startswith("|"):
            continue
        # 行形如 | **D01** | 叙事功能 | `a` / `b` |
        m = re.match(r"\|\s*\*\*(D\d+(?:\.\w+)?|narrator_reliability|cross_segment\.\w+)\*\*", line)
        if not m:
            continue
        dim = m.group(1)
        # 提取该行所有反引号包裹的独立值（排除反引号内的中文说明）
        cells = [c.strip() for c in line.split("|")]
        # 行尾通常有收尾管道 → 最后一个 cell 为空，取倒数第二个
        last = cells[-2] if len(cells) >= 2 else (cells[-1] if cells else "")
        values = set(re.findall(r"`([^`]+)`", last))
        # 过滤明显说明性短语（含空格/括号/斜杠的都视为说明，但值本身可能含连字符如"伏笔-回收"）
        cleaned = {
            v.strip()
            for v in values
            if v.strip() and not re.search(r"[\s（(）)]", v) and "：" not in v and "见" not in v and "§" not in v
        }
        out[dim] = cleaned
    return out


def main() -> int:
    validator_consts = load_validator_constants()
    skill_table = extract_skill_table()

    if not validator_consts:
        print("❌ 无法从 validate_output.py 提取枚举常量（解析失败？）", file=sys.stderr)
        return 2

    # 维度名映射：validator 常量名 → SKILL 表维度名
    dim_map = {
        "D01_VALUES": "D01",
        "D04_CORE_VALUES": "D04.core",
        "D07_TYPES": "D07.type",
        "D10_VALUES": "D10",
        "D11_VALUES": "D11",
        "EMOTION_LEXICON_VALUES": "D19.primary",
        "RHETORIC_TYPES": "D14.type",
        "IMAGERY_TYPES": "D15.type",
        "POS_TYPES": "D16.pos",
        "SYNTAX_TYPES": "D17.type",
        "D06_TYPES": "D06.type",
        "NARRATOR_RELIABILITY_VALUES": "narrator_reliability",
        "D08_TIME_TYPES": "D08._time_type",
        "D12_MODES": "D12.mode",
    }

    issues: list[str] = []
    for const_name, label in CHECKED_CONSTANTS.items():
        validator_set = validator_consts.get(const_name)
        skill_dim = dim_map.get(const_name)
        skill_set = skill_table.get(skill_dim or "") if skill_dim else None
        if validator_set is None:
            issues.append(f"⚠️ {const_name}: validator 中未找到常量")
            continue
        if skill_set is None:
            issues.append(f"⚠️ {label}: SKILL.md §4.0 中未找到对应行（dim={skill_dim}）")
            continue
        only_validator = validator_set - skill_set
        only_skill = skill_set - validator_set
        if only_validator:
            issues.append(
                f"❌ {label}: validator 有但 SKILL 速查表缺 → {sorted(only_validator)}"
            )
        if only_skill:
            issues.append(
                f"❌ {label}: SKILL 速查表有但 validator 无（自造词源）→ {sorted(only_skill)}"
            )

    print("=" * 66)
    print("枚举一致性自检（validator 真源 vs SKILL.md §4.0 速查表）")
    print("=" * 66)
    if not issues:
        checked = ", ".join(CHECKED_CONSTANTS)
        print(f"✅ 全部一致（检查 {len(CHECKED_CONSTANTS)} 个维度）：{checked}")
        return 0
    for msg in issues:
        print(msg)
    print(f"\n❌ 共 {len(issues)} 处不一致——速查表与校验器分裂会让 Agent 按文档写被拒。")
    print("   修复原则：以 validate_output.py 为准重写 SKILL.md §4.0 对应行。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
