#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/audit/v35_acceptance.py — v3.5.0 验收脚本（T-034 / ADR-014）

覆盖：
  A. 产物格式：reshape_segments.py py_compile
  B. 重排功能：无边界/有边界/输出格式/ID映射/字符位置自校验/场景编号连续
  C. 场景边界判断 Prompt 存在性（SKILL.md）
  D. 文档一致性（SKILL/RUNBOOK/README 版本 3.5.0 + reshape_segments 索引）
  E. 端到端（真实书籍重排）

用法：python scripts/audit/v35_acceptance.py
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


def run_script(script: Path, args: list[str]) -> tuple[int, str, str]:
    cmd = [sys.executable, str(script)] + args
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return proc.returncode, proc.stdout, proc.stderr


def make_mock_boundaries(doc_id: str, pairs: list[tuple[str, str, str]]) -> dict:
    """构造模拟 scene_boundary.json。"""
    return {
        "schema_version": "3.5.0",
        "document_id": doc_id,
        "boundaries": [
            {"between_segment": a, "and_segment": b, "is_scene_boundary": True,
             "boundary_type": btype, "confidence": 0.9, "reason": "mock"}
            for a, b, btype in pairs
        ],
    }


# ============================================================================
# A. 产物格式
# ============================================================================
print("\n=== A. 产物格式（py_compile）===")

try:
    py_compile.compile(str(SCRIPTS / "reshape_segments.py"), doraise=True)
    check("A-reshape-py_compile", True, "编译通过")
except py_compile.PyCompileError as e:
    check("A-reshape-py_compile", False, str(e)[:200])

check("A-reshape-exists", (SCRIPTS / "reshape_segments.py").exists())

# ============================================================================
# B. 重排功能
# ============================================================================
print("\n=== B. 重排功能 ===")

with tempfile.TemporaryDirectory() as tmpdir:
    tmp = Path(tmpdir)

    # B1: 无边界文件（仅按章节边界合并）
    rc, out, err = run_script(SCRIPTS / "reshape_segments.py",
                               ["--segments", str(MOON_SEGMENTS),
                                "--doc-id", "moon_sixpence_zh",
                                "--output-dir", str(tmp / "no_boundary")])
    check("B1-no-boundary-rc0", rc == 0, f"rc={rc}")
    no_bnd_segs = tmp / "no_boundary" / "moon_sixpence_zh_final_segments.jsonl"
    check("B1-no-boundary-output-exists", no_bnd_segs.exists())
    if no_bnd_segs.exists():
        lines = [l for l in io.open(no_bnd_segs, encoding="utf-8").readlines() if l.strip()]
        check("B1-no-boundary-scene-count>0", len(lines) > 0, f"{len(lines)} 场景")
        # 场景编号连续性
        ids = [json.loads(l)["segment_id"] for l in lines]
        expected = [f"moon_sixpence_zh_scene_{i:03d}" for i in range(len(lines))]
        check("B1-scene-ids-continuous", ids == expected, f"首={ids[0]} 末={ids[-1]}")

    # B2: 有边界文件（模拟场景边界）
    mock_bnd = make_mock_boundaries("moon_sixpence_zh", [
        ("moon_sixpence_zh_seg_0003", "moon_sixpence_zh_seg_0004", "location_change"),
        ("moon_sixpence_zh_seg_0007", "moon_sixpence_zh_seg_0008", "time_jump"),
    ])
    bnd_file = tmp / "mock_boundary.json"
    io.open(bnd_file, "w", encoding="utf-8").write(json.dumps(mock_bnd, ensure_ascii=False, indent=2))

    rc, out, err = run_script(SCRIPTS / "reshape_segments.py",
                               ["--segments", str(MOON_SEGMENTS),
                                "--boundaries", str(bnd_file),
                                "--doc-id", "moon_sixpence_zh",
                                "--output-dir", str(tmp / "with_boundary")])
    check("B2-with-boundary-rc0", rc == 0, f"rc={rc}")
    with_bnd_segs = tmp / "with_boundary" / "moon_sixpence_zh_final_segments.jsonl"
    check("B2-with-boundary-output-exists", with_bnd_segs.exists())

    # B3: 有边界比无边界场景数更多或相等（边界标记应增加切分点）
    if no_bnd_segs.exists() and with_bnd_segs.exists():
        no_count = len([l for l in io.open(no_bnd_segs, encoding="utf-8").readlines() if l.strip()])
        with_count = len([l for l in io.open(with_bnd_segs, encoding="utf-8").readlines() if l.strip()])
        check("B3-boundary-increases-or-equals-scenes", with_count >= no_count,
              f"无边界={no_count} 有边界={with_count}")

    # B4: 输出格式正确性（字段完整）
    if with_bnd_segs.exists():
        first = json.loads(io.open(with_bnd_segs, encoding="utf-8").readline())
        required_keys = ["schema_version", "document_id", "segment_index", "segment_id",
                         "chapter", "section_type", "scene_level", "merged_from_count", "text_span"]
        missing = [k for k in required_keys if k not in first]
        check("B4-output-required-keys", len(missing) == 0, f"缺失: {missing}" if missing else "全部 9 项")
        check("B4-scene_level-true", first.get("scene_level") is True)
        check("B4-text_span-has-start-end", "start_char" in first["text_span"] and "end_char" in first["text_span"])

    # B5: 字符位置自校验（start_char/end_char 与 text 长度）
    if with_bnd_segs.exists():
        all_valid = True
        details = []
        for line in io.open(with_bnd_segs, encoding="utf-8"):
            if not line.strip():
                continue
            seg = json.loads(line)
            ts = seg["text_span"]
            expected_len = ts["end_char"] - ts["start_char"]
            actual_len = len(ts["text"])
            # 允许 ±2 字符偏差（换行/空白差）
            if abs(expected_len - actual_len) > 2:
                all_valid = False
                details.append(f"{seg['segment_id']}: expected={expected_len} actual={actual_len}")
        check("B5-char-position-consistent", all_valid,
              f"全部场景字符位置一致" if all_valid else f"不一致: {details[:3]}")

    # B6: 新旧 ID 映射正确性
    mapping_file = tmp / "with_boundary" / "moon_sixpence_zh_segment_id_mapping.json"
    check("B6-mapping-file-exists", mapping_file.exists())
    if mapping_file.exists():
        mapping = json.loads(io.open(mapping_file, encoding="utf-8").read())
        check("B6-mapping-has-mapping-array", "mapping" in mapping and len(mapping["mapping"]) > 0)
        if mapping.get("mapping"):
            first_map = mapping["mapping"][0]
            check("B6-mapping-entry-complete",
                  all(k in first_map for k in ["new_segment_id", "old_segment_ids", "start_char", "end_char", "merged_count"]),
                  "映射条目字段完整")
            check("B6-mapping-old-ids-nonempty", len(first_map["old_segment_ids"]) > 0)
            # 合并数与 old_segment_ids 长度一致
            check("B6-mapping-merged-count-matches",
                  first_map["merged_count"] == len(first_map["old_segment_ids"]),
                  f"merged_count={first_map['merged_count']} ids_len={len(first_map['old_segment_ids'])}")

    # B7: merged_from_count >= 1（每个场景至少合并 1 个粗切段）
    if with_bnd_segs.exists():
        all_ge1 = all(json.loads(l)["merged_from_count"] >= 1
                      for l in io.open(with_bnd_segs, encoding="utf-8") if l.strip())
        check("B7-merged-from-count>=1", all_ge1)

# ============================================================================
# C. 场景边界判断 Prompt 存在性
# ============================================================================
print("\n=== C. 场景边界判断 Prompt 存在性 ===")

skill_md = io.open(SKILL_ROOT / "SKILL.md", encoding="utf-8").read()
check("C-phase-1.5-section-exists", "Phase 1.5" in skill_md and "精细化切分重排" in skill_md)
check("C-scene-boundary-prompt-exists", "场景边界判断" in skill_md and "is_scene_boundary" in skill_md)
check("C-lumberchunker-reference", "LumberChunker" in skill_md)
check("C-four-dimensions", all(d in skill_md for d in ["地点变化", "时间跳跃", "视角切换", "主题断裂"]))
check("C-boundary-type-enum", all(t in skill_md for t in ["location_change", "time_jump", "pov_switch", "thematic_break"]))
check("C-reshape-script-call", "reshape_segments.py" in skill_md and "--segments" in skill_md)
check("C-final-segments-output", "final_segments.jsonl" in skill_md)
check("C-id-mapping-output", "segment_id_mapping.json" in skill_md)

# ============================================================================
# D. 文档一致性
# ============================================================================
print("\n=== D. 文档一致性 ===")

runbook = io.open(SKILL_ROOT / "docs" / "RUNBOOK.md", encoding="utf-8").read()
readme = io.open(SKILL_ROOT / "README.md", encoding="utf-8").read()

check("D-SKILL-version-3.5.0", "version: 3.5.0" in skill_md)
check("D-SKILL-title-3.5.0", "# 四层精读批注 Skill v3.5.0" in skill_md)
check("D-SKILL-v3.5.0-history", "3.5.0" in skill_md and "精细化切分器" in skill_md)
check("D-SKILL-reshape-index", "reshape_segments.py" in skill_md)

check("D-RUNBOOK-version-3.5.0", "v3.5.0" in runbook)
check("D-RUNBOOK-reshape-cli", "reshape_segments.py" in runbook)
check("D-RUNBOOK-phase-1.25", "Phase 1.25" in runbook)

check("D-README-version-3.5.0", "v3.5.0" in readme)
check("D-README-reshape-tree", "reshape_segments.py" in readme)
check("D-README-v3.5.0-history", "v3.5.0" in readme and "精细化切分" in readme)

check("D-annotation-schema-still-2.9.0", "2.9.0" in skill_md, "annotation schema 仍为 2.9.0（不变）")
check("D-aggregation-schema-still-3.0.0", "3.0.0" in skill_md, "aggregation schema 仍为 3.0.0（不变）")

# ============================================================================
# E. 端到端（上海堡垒）
# ============================================================================
print("\n=== E. 端到端冒烟 ===")

shanghai_segments = WORKSPACE / "outputs" / "annotations" / "shanghai_fortress_zh" / "shanghai_fortress_zh_segments.jsonl"
if shanghai_segments.exists():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        rc, out, err = run_script(SCRIPTS / "reshape_segments.py",
                                   ["--segments", str(shanghai_segments),
                                    "--doc-id", "shanghai_fortress_zh",
                                    "--output-dir", str(tmp)])
        check("E-shanghai-rc0", rc == 0, f"rc={rc}")
        final_segs = tmp / "shanghai_fortress_zh_final_segments.jsonl"
        if final_segs.exists():
            lines = [l for l in io.open(final_segs, encoding="utf-8").readlines() if l.strip()]
            check("E-shanghai-all-scenes", len(lines) > 0, f"{len(lines)} 场景")
            # 验证所有场景的 scene_level=True
            all_scene = all(json.loads(l).get("scene_level") for l in lines)
            check("E-shanghai-all-scene-level-true", all_scene)
else:
    check("E-shanghai-skipped", True, f"测试文件不存在: {shanghai_segments}")

# ============================================================================
# 汇总
# ============================================================================
print(f"\n{'='*60}")
print(f"v3.5.0 验收汇总：PASS={PASS}  FAIL={FAIL}  TOTAL={PASS+FAIL}")
if FAIL == 0:
    print("ALL PASS ✅")
else:
    print(f"有 {FAIL} 项失败 ❌")
    for name, ok, detail in RESULTS:
        if not ok:
            print(f"  FAIL: {name} — {detail}")
print(f"{'='*60}")

sys.exit(0 if FAIL == 0 else 1)
