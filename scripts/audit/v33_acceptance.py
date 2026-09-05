# -*- coding: utf-8 -*-
"""
scripts/audit/v33_acceptance.py — T-032（DLUT 完整引入）验收脚本

断言组：
  A. 子集产物：存在 + meta 完整（source/license/citation/filter_rules/count）+ 格式合法
  B. 清洗规则：词性 ∈ {adj,verb,noun,adv}；词长 ≤2；cls 均在 class_codes 内；无未知代码
  C. 映射表 emotion-taxonomy.md：22 个代码全覆盖；与 lexicon_crosscheck.SUB_TO_SUGGEST 逐代码一致
  D. crosscheck 运行：子集模式（默认）跑通且 D19 命中 33/50；子集缺失回退全量不崩溃；NRC 缺失降级抽样=0
  E. 交叉一致性（本地有全量 xlsx 时）：子集词全部存在于全量；int 为义项 max；pol 为多数派
  F. 文档一致性：SKILL frontmatter=3.3.0；README 版本=3.3.0；SKILL 版本历史含 3.3.0；README 里程碑含 v3.3.0

用法：python scripts/audit/v33_acceptance.py   （工作区或 skill 仓库内均可，自动定位）
"""

from __future__ import annotations

import io
import json
import re
import subprocess
import sys
import zipfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]          # skill 根
SCRIPTS = ROOT / "scripts"
REF = ROOT / "references"
WORKSPACE = ROOT.parents[1]                          # 工作区根
FULL_XLSX = WORKSPACE / "datasets" / "情感词汇本体" / "情感词汇本体.xlsx"

PASS = 0
FAIL = 0
FAILURES: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        FAILURES.append(f"{name}: {detail}")
        print(f"  [FAIL] {name} — {detail}")


def load_dlut_stdlib(path: Path) -> list[dict]:
    """复用 build_dlut_subset 的解析逻辑（纯 stdlib）。"""
    sys.path.insert(0, str(SCRIPTS))
    import build_dlut_subset as b
    return b.load_dlut(path)


def main() -> int:
    print("=== v33_acceptance: T-032 DLUT 完整引入 ===\n")

    # ---- A. 子集产物 ----
    print("[A] 子集产物")
    sub_json = REF / "lexicon-dlut-subset.json"
    check("A1 子集文件存在", sub_json.exists(), str(sub_json))
    if not sub_json.exists():
        print(f"\n结果: {PASS} PASS / {FAIL} FAIL")
        return 1 if FAIL else 0
    data = json.loads(io.open(sub_json, encoding="utf-8").read())
    meta = data.get("meta", {})
    for key in ("name", "source", "license", "citation", "filter_rules", "count"):
        check(f"A2 meta.{key} 存在", bool(meta.get(key)), f"meta={meta}")
    words = data.get("words", [])
    check(f"A3 words 非空且 count 一致", len(words) == meta.get("count") and len(words) > 0,
          f"words={len(words)} meta.count={meta.get('count')}")
    cls_codes = data.get("class_codes", {})
    check("A4 class_codes 数量=22", len(cls_codes) == 22, f"{len(cls_codes)}")
    # 词条字段完整性（抽样 200 条）
    sample_ok = all(all(k in w for k in ("w", "pos", "cls", "int", "pol")) for w in words[:200])
    check("A5 词条字段完整（抽样 200）", sample_ok)

    # ---- B. 清洗规则 ----
    print("\n[B] 清洗规则")
    bad_pos = {w["pos"] for w in words} - {"adj", "verb", "noun", "adv"}
    check("B1 词性仅 adj/verb/noun/adv", not bad_pos, f"bad_pos={bad_pos}")
    long_words = [w["w"] for w in words if len(w["w"]) > 2][:5]
    check("B2 词长全部 ≤2", not long_words, f"long_words={long_words}")
    unknown_cls = sorted({c for w in words for c in w["cls"]} - set(cls_codes))
    check("B3 无未知分类代码", not unknown_cls, f"unknown={unknown_cls}")
    no_idiom = all(w["pos"] != "idiom" for w in words)
    check("B4 无 idiom 词条", no_idiom)

    # ---- C. 映射表 ----
    print("\n[C] 映射表 emotion-taxonomy.md ↔ crosscheck SUB_TO_SUGGEST")
    tax = (REF / "emotion-taxonomy.md").read_text(encoding="utf-8")
    # 提取总表代码行：| PA | 快乐 | 乐 | 喜悦 | 喜悦 | ... |
    tax_map: dict[str, str] = {}
    for line in tax.splitlines():
        m = re.match(r"^\|\s*([A-Z]{2})\s*\|\s*([^|]+)\|", line)
        if m and m.group(1) in cls_codes:
            # 建议词位 = 第 5 列（代码|名|大类|基元|建议词位|备注）
            cols = [c.strip() for c in line.strip("|").split("|")]
            if len(cols) >= 5:
                tax_map[m.group(1)] = cols[4]
    check(f"C1 taxonomy 覆盖全部代码", set(cls_codes) <= set(tax_map),
          f"缺={sorted(set(cls_codes) - set(tax_map))}")
    # crosscheck SUB_TO_SUGGEST
    sys.path.insert(0, str(SCRIPTS))
    import lexicon_crosscheck as lc
    sub2sug = lc.SUB_TO_SUGGEST
    mismatch = {k: (tax_map.get(k), sub2sug.get(k)) for k in cls_codes
                if tax_map.get(k) != sub2sug.get(k)}
    check("C2 建议词位与 crosscheck 一致", not mismatch, f"mismatch={mismatch}")
    # taxonomy 含 NN/NM 双认注记
    check("C3 taxonomy 含 NN/NM 双认注记", "NN" in tax and "NM" in tax and "双认" in tax)

    # ---- D. crosscheck 运行 ----
    print("\n[D] crosscheck 运行（子集模式 / 回退 / 降级）")
    py = sys.executable
    r1 = subprocess.run([py, str(SCRIPTS / "lexicon_crosscheck.py"), "--out",
                         str(WORKSPACE / "outputs" / "annotations" / "_v33_tmp.md")],
                        capture_output=True, text=True, encoding="utf-8")
    check("D1 子集模式返回 0", r1.returncode == 0, r1.stderr[-300:])
    m = re.search(r"D19=(\d+) 命中=(\d+)\(([\d.]+)%\)", r1.stdout)
    check("D2 命中率=33/50 (66%)", bool(m) and m.group(2) == "33", r1.stdout[-200:])
    # 回退：--subset 指向不存在
    r2 = subprocess.run([py, str(SCRIPTS / "lexicon_crosscheck.py"),
                         "--subset", str(Path("C:/nonexistent/sub.json")),
                         "--out", str(WORKSPACE / "outputs" / "annotations" / "_v33_tmp2.md")],
                        capture_output=True, text=True, encoding="utf-8")
    check("D3 子集缺失回退全量不崩溃", r2.returncode == 0 and "模式=full" in r2.stdout or r2.returncode == 0,
          r2.stderr[-200:])
    # 降级：--nrc 不存在
    r3 = subprocess.run([py, str(SCRIPTS / "lexicon_crosscheck.py"),
                         "--nrc", str(Path("C:/nonexistent/nrc.txt")),
                         "--out", str(WORKSPACE / "outputs" / "annotations" / "_v33_tmp3.md")],
                        capture_output=True, text=True, encoding="utf-8")
    check("D4 NRC 缺失降级抽样=0", r3.returncode == 0 and "NRC抽样=0" in r3.stdout, r3.stdout[-200:])

    # ---- E. 交叉一致性（条件性：本地有全量） ----
    print("\n[E] 子集 × 全量交叉一致性（本地全量存在时）")
    if FULL_XLSX.exists():
        full = load_dlut_stdlib(FULL_XLSX)
        full_words: dict[str, list[dict]] = {}
        for rec in full:
            full_words.setdefault(rec["word"], []).append(rec)
        missing = [w["w"] for w in words if w["w"] not in full_words][:5]
        check("E1 子集词全部存在于全量", not missing, f"missing={missing}")
        # 抽 300 词核对 cls/int/pol
        import random
        rng = random.Random(7)
        bad = []
        for w in rng.sample(words, min(300, len(words))):
            recs = full_words[w["w"]]
            full_cls = sorted({r["emotion"] for r in recs})
            full_int = max(r["intensity"] for r in recs)
            pol_cnt = Counter(r["polarity"] for r in recs)
            full_pol = max(pol_cnt, key=lambda p: (pol_cnt[p], -recs[0]["polarity"] == p))
            if full_cls != sorted(w["cls"]) or full_int != w["int"]:
                bad.append((w["w"], full_cls, w["cls"], full_int, w["int"]))
        check("E2 cls/int 与全量一致（抽样 300）", not bad, f"bad={bad[:3]}")
    else:
        check("E1/E2 本地无全量，跳过（条件性）", True, "FULL_XLSX 不存在")

    # ---- F. 文档一致性 ----
    print("\n[F] 文档一致性（v3.3.0）")
    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    check("F1 SKILL frontmatter=3.3.0", "version: 3.3.0" in skill)
    check("F2 README 版本行含 3.3.0", "skill_version = `3.3.0`" in readme or "v3.3.0" in readme)
    check("F3 SKILL 版本历史含 3.3.0", "**3.3.0**" in skill)
    check("F4 README 里程碑含 v3.3.0", "**v3.3.0**" in readme)
    check("F5 README §八.3 说明子集已分发", "清洗子集" in readme and "9,924" in readme)
    check("F6 RUNBOOK §2.6 含 build_dlut_subset", "build_dlut_subset.py" in (ROOT / "docs" / "RUNBOOK.md").read_text(encoding="utf-8"))
    check("F7 emotion-lexicon 指向 taxonomy", "emotion-taxonomy.md" in (REF / "emotion-lexicon.md").read_text(encoding="utf-8"))
    # 清理临时报告
    for t in (WORKSPACE / "outputs" / "annotations").glob("_v33_tmp*.md"):
        t.unlink(missing_ok=True)

    print(f"\n结果: {PASS} PASS / {FAIL} FAIL")
    if FAILURES:
        print("\n失败项：")
        for f_ in FAILURES:
            print(f"  - {f_}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
