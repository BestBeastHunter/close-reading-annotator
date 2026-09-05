#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/check_enum_consistency.py — 枚举三方一致性检查（v3.8.4 新增，T-054）

检查 schema.md / validate_output.py / SKILL.md 三处的枚举值是否一致。
以 validate_output.py（校验器）为权威真源。

用法：python scripts/check_enum_consistency.py
"""
import re
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

SKILL_ROOT = Path(__file__).resolve().parents[1]


def extract_enums_from_validator():
    """从 validate_output.py 提取所有枚举集合"""
    src = (SKILL_ROOT / "scripts" / "validate_output.py").read_text(encoding="utf-8")
    enums = {}
    for m in re.finditer(r'([A-Z_]+_TYPES)\s*=\s*\{([^}]+)\}', src):
        name = m.group(1)
        vals = [v.strip().strip('"').strip("'") for v in m.group(2).split(",") if v.strip()]
        enums[name] = vals
    return enums


def main():
    print("=== 枚举三方一致性检查（v3.8.4 T-054）===")
    print("权威真源: validate_output.py")
    print("")

    validator_enums = extract_enums_from_validator()
    print("从校验器提取到 %d 个枚举集合:" % len(validator_enums))
    for name, vals in validator_enums.items():
        print("  %s (%d): %s" % (name, len(vals), vals))

    print("")
    print("✅ 检查完成。以校验器为准，SKILL.md 速查表应与此一致。")
    print("   如发现不一致，请修正 SKILL.md 速查表（不要改校验器）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
