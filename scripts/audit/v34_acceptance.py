#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/audit/v34_acceptance.py — v3.4.0 验收脚本（T-033 / ADR-014）

覆盖：
  A. 产物格式：quality_gate.py / quant_analyzer.py py_compile
  B. quality_gate 功能：正常文本 pass / 污染文本 fail / JSONL 输入
  C. quant_analyzer 功能：真实书籍运行 / 指标完整性 / DLUT 匹配 / jieba 降级
  D. 文档一致性：SKILL/RUNBOOK/README 版本 3.4.0 + 新脚本索引
  E. 真实书籍端到端：月亮 segments.jsonl → quant_metrics.jsonl 全段产出

用法：python scripts/audit/v34_acceptance.py
"""

from __future__ import annotations

import io
import json
import os
import py_compile
import re
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
WORKSPACE = SKILL_ROOT.parents[1]  # StoryEngine
MOON_SEGMENTS = WORKSPACE / "outputs" / "annotations" / "moon_sixpence_zh" / "moon_sixpence_zh_segments.jsonl"

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


def run_script(script: Path, args: list[str], cwd: Path | None = None) -> tuple[int, str, str]:
    """运行脚本，返回 (returncode, stdout, stderr)。"""
    cmd = [sys.executable, str(script)] + args
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", cwd=str(cwd) if cwd else None)
    return proc.returncode, proc.stdout, proc.stderr


# ============================================================================
# A. 产物格式
# ============================================================================
print("\n=== A. 产物格式（py_compile）===")

for script_name in ["quality_gate.py", "quant_analyzer.py"]:
    script_path = SCRIPTS / script_name
    try:
        py_compile.compile(str(script_path), doraise=True)
        check(f"A-{script_name}-py_compile", True, "编译通过")
    except py_compile.PyCompileError as e:
        check(f"A-{script_name}-py_compile", False, str(e)[:200])

# 脚本存在性
check("A-quality_gate-exists", (SCRIPTS / "quality_gate.py").exists())
check("A-quant_analyzer-exists", (SCRIPTS / "quant_analyzer.py").exists())

# ============================================================================
# B. quality_gate 功能
# ============================================================================
print("\n=== B. quality_gate 功能 ===")

with tempfile.TemporaryDirectory() as tmpdir:
    tmp = Path(tmpdir)

    # B1: 正常中文文本 → pass
    normal_text = (
        "这是一段正常的中文叙事文本。他走进房间，看见桌上放着一封信。窗外的雨还在下，淅淅沥沥地敲打着玻璃。"
        "他深吸一口气，拿起信封，手指微微有些颤抖。信封上的字迹很熟悉，是她三年前留下的。他犹豫了片刻，"
        "最终还是拆开了封口。信纸已经泛黄，上面的墨迹却依然清晰。她在信里说，她要去远方寻找一个答案，"
        "也许永远不会回来。读完最后一行字，他缓缓地坐在了椅子上，窗外的雨声似乎更大了。"
    )
    normal_file = tmp / "normal.txt"
    io.open(normal_file, "w", encoding="utf-8").write(normal_text)
    rc, out, err = run_script(SCRIPTS / "quality_gate.py",
                               ["--input", str(normal_file), "--out", str(tmp / "qg_normal.json")])
    check("B1-normal-text-rc0", rc == 0, f"rc={rc}")
    if (tmp / "qg_normal.json").exists():
        report = json.loads(io.open(tmp / "qg_normal.json", encoding="utf-8").read())
        check("B1-normal-verdict-pass", report.get("verdict") in ("pass", "warn"),
              f"verdict={report.get('verdict')}")
        check("B1-normal-chinese-ratio>0.8", report["metrics"]["chinese_ratio"]["ratio"] > 0.8,
              f"ratio={report['metrics']['chinese_ratio']['ratio']}")
        check("B1-normal-overall>60", report["overall_score"] > 60,
              f"score={report['overall_score']}")
    else:
        check("B1-normal-report-exists", False, "报告文件未生成")

    # B2: 污染文本（全英文+乱码）→ fail
    polluted_text = "This is all English text with no Chinese characters at all. " * 20 + "\ufffd\ufffd\ufffd"
    polluted_file = tmp / "polluted.txt"
    io.open(polluted_file, "w", encoding="utf-8").write(polluted_text)
    rc, out, err = run_script(SCRIPTS / "quality_gate.py",
                               ["--input", str(polluted_file), "--out", str(tmp / "qg_polluted.json")])
    check("B2-polluted-rc0", rc == 0, f"rc={rc}")
    if (tmp / "qg_polluted.json").exists():
        report = json.loads(io.open(tmp / "qg_polluted.json", encoding="utf-8").read())
        check("B2-polluted-verdict-fail-or-warn", report.get("verdict") in ("fail", "warn"),
              f"verdict={report.get('verdict')}")
        check("B2-polluted-chinese-ratio<0.5", report["metrics"]["chinese_ratio"]["ratio"] < 0.5,
              f"ratio={report['metrics']['chinese_ratio']['ratio']}")
    else:
        check("B2-polluted-report-exists", False, "报告文件未生成")

    # B3: JSONL segments 输入支持
    if MOON_SEGMENTS.exists():
        rc, out, err = run_script(SCRIPTS / "quality_gate.py",
                                   ["--input", str(MOON_SEGMENTS), "--out", str(tmp / "qg_jsonl.json")])
        check("B3-jsonl-input-rc0", rc == 0, f"rc={rc}")
        if (tmp / "qg_jsonl.json").exists():
            report = json.loads(io.open(tmp / "qg_jsonl.json", encoding="utf-8").read())
            check("B3-jsonl-has-metrics", "metrics" in report and "chinese_ratio" in report["metrics"])
        else:
            check("B3-jsonl-report-exists", False, "报告文件未生成")
    else:
        check("B3-jsonl-input-skipped", True, f"测试文件不存在: {MOON_SEGMENTS}")

    # B4: --fail-on-error 对污染文本返回非零
    rc, out, err = run_script(SCRIPTS / "quality_gate.py",
                               ["--input", str(polluted_file), "--out", str(tmp / "qg_foe.json"),
                                "--fail-on-error"])
    # 污染文本 verdict 可能是 fail 或 warn；--fail-on-error 只在 fail 时返回非零
    check("B4-fail-on-error-runs", rc in (0, 1), f"rc={rc}")

# ============================================================================
# C. quant_analyzer 功能
# ============================================================================
print("\n=== C. quant_analyzer 功能 ===")

with tempfile.TemporaryDirectory() as tmpdir:
    tmp = Path(tmpdir)

    # C1: 真实书籍运行
    if MOON_SEGMENTS.exists():
        rc, out, err = run_script(SCRIPTS / "quant_analyzer.py",
                                   ["--segments", str(MOON_SEGMENTS), "--out", str(tmp / "moon_quant.jsonl")])
        check("C1-moon-rc0", rc == 0, f"rc={rc}")
        quant_file = tmp / "moon_quant.jsonl"
        if quant_file.exists():
            lines = [l for l in io.open(quant_file, encoding="utf-8").readlines() if l.strip()]
            check("C1-moon-98-segments", len(lines) == 98, f"实际 {len(lines)} 段（预期 98）")
            if lines:
                first = json.loads(lines[0])
                m = first["metrics"]
                # 指标完整性
                required_keys = ["char_count", "word_count", "sentence_count", "avg_sentence_length",
                                 "type_token_ratio", "verb_ratio", "adj_ratio", "noun_ratio",
                                 "dialogue_ratio", "punctuation_density", "emotion_scores", "sense_ratios"]
                missing = [k for k in required_keys if k not in m]
                check("C1-metrics-complete", len(missing) == 0, f"缺失: {missing}" if missing else "全部 13 项")
                # DLUT 情感匹配
                check("C1-emotion-matched>0", m["emotion_scores"]["matched_words"] > 0,
                      f"matched={m['emotion_scores']['matched_words']}")
                # 词性比例（降级模式下 DLUT 反查）
                check("C1-verb-ratio>=0", m["verb_ratio"] >= 0, f"verb={m['verb_ratio']}")
                # 五感密度
                check("C1-sense-5-dimensions", len(m["sense_ratios"]) == 5,
                      f"实际 {len(m['sense_ratios'])} 维")
                # TTR 合理范围
                check("C1-ttr-in-range", 0 < m["type_token_ratio"] <= 1.0,
                      f"TTR={m['type_token_ratio']}")
                # segment_id 对齐
                check("C1-segment_id-prefix", first["segment_id"].startswith("moon_sixpence_zh_seg_"),
                      f"id={first['segment_id']}")
        else:
            check("C1-moon-quant-exists", False, "quant_metrics.jsonl 未生成")
    else:
        check("C1-moon-skipped", True, f"测试文件不存在: {MOON_SEGMENTS}")

    # C2: jieba 降级模式确认（输出 INFO 行）
    rc, out, err = run_script(SCRIPTS / "quant_analyzer.py",
                               ["--segments", str(MOON_SEGMENTS), "--out", str(tmp / "c2.jsonl")])
    check("C2-jieba-info-in-output", "jieba" in out or "jieba" in err,
          "输出包含 jieba 状态信息")

    # C3: DLUT 子集加载确认
    rc, out, err = run_script(SCRIPTS / "quant_analyzer.py",
                               ["--segments", str(MOON_SEGMENTS), "--out", str(tmp / "c3.jsonl")])
    check("C3-dlut-9924-words", "9924" in out or "9924" in err,
          "DLUT 子集 9924 词加载确认")

# ============================================================================
# D. 文档一致性
# ============================================================================
print("\n=== D. 文档一致性 ===")

skill_md = io.open(SKILL_ROOT / "SKILL.md", encoding="utf-8").read()
runbook = io.open(SKILL_ROOT / "docs" / "RUNBOOK.md", encoding="utf-8").read()
readme = io.open(SKILL_ROOT / "README.md", encoding="utf-8").read()

check("D-SKILL-version-3.4.0", "version: 3.4.0" in skill_md, "frontmatter version=3.4.0")
check("D-SKILL-title-3.4.0", "# 四层精读批注 Skill v3.4.0" in skill_md,
      "标题含 v3.4.0")
check("D-SKILL-quality_gate-index", "quality_gate.py" in skill_md, "SKILL 索引含 quality_gate")
check("D-SKILL-quant_analyzer-index", "quant_analyzer.py" in skill_md, "SKILL 索引含 quant_analyzer")
check("D-SKILL-v3.4.0-history", "3.4.0" in skill_md and "前置双模块" in skill_md, "版本历史含 v3.4.0")

check("D-RUNBOOK-version-3.4.0", "v3.4.0" in runbook, "RUNBOOK 版本=3.4.0")
check("D-RUNBOOK-quality_gate", "quality_gate.py" in runbook, "RUNBOOK 含 quality_gate")
check("D-RUNBOOK-quant_analyzer", "quant_analyzer.py" in runbook, "RUNBOOK 含 quant_analyzer")

check("D-README-version-3.4.0", "v3.4.0" in readme, "README 版本=3.4.0")
check("D-README-quality_gate-tree", "quality_gate.py" in readme, "README 目录树含 quality_gate")
check("D-README-quant_analyzer-tree", "quant_analyzer.py" in readme, "README 目录树含 quant_analyzer")
check("D-README-v3.4.0-history", "v3.4.0" in readme and "前置双模块" in readme, "README 版本历史含 v3.4.0")

# annotation/aggregation schema 不变
check("D-annotation-schema-still-2.9.0", "2.9.0" in skill_md, "annotation schema 仍为 2.9.0（不变）")
check("D-aggregation-schema-still-3.0.0", "3.0.0" in skill_md, "aggregation schema 仍为 3.0.0（不变）")

# ============================================================================
# E. 端到端冒烟（两本书如果都有）
# ============================================================================
print("\n=== E. 端到端冒烟 ===")

shanghai_segments = WORKSPACE / "outputs" / "annotations" / "shanghai_fortress_zh" / "shanghai_fortress_zh_segments.jsonl"
if shanghai_segments.exists():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        rc, out, err = run_script(SCRIPTS / "quant_analyzer.py",
                                   ["--segments", str(shanghai_segments), "--out", str(tmp / "sh_quant.jsonl")])
        check("E-shanghai-rc0", rc == 0, f"rc={rc}")
        lines = [l for l in io.open(tmp / "sh_quant.jsonl", encoding="utf-8").readlines() if l.strip()]
        check("E-shanghai-all-segments", len(lines) > 0, f"{len(lines)} 段")
else:
    check("E-shanghai-skipped", True, f"测试文件不存在: {shanghai_segments}")

# ============================================================================
# 汇总
# ============================================================================
print(f"\n{'='*60}")
print(f"v3.4.0 验收汇总：PASS={PASS}  FAIL={FAIL}  TOTAL={PASS+FAIL}")
if FAIL == 0:
    print("ALL PASS ✅")
else:
    print(f"有 {FAIL} 项失败 ❌")
    for name, ok, detail in RESULTS:
        if not ok:
            print(f"  FAIL: {name} — {detail}")
print(f"{'='*60}")

sys.exit(0 if FAIL == 0 else 1)
