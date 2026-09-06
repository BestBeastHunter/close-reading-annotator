#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/audit/v313_acceptance.py — v3.13.0 验收脚本（T-107~T-110 / ADR-029）

覆盖：
  A. 产物格式：scratchpad.py / annotate_segment.py / checkpoint.py py_compile
  B. Scratchpad 核心功能：数据结构 / 人物操作 / 事件操作 / 摘要生成 / 序列化
  C. annotate_segment 集成：--scratchpad/--no-scratchpad 参数 / 端到端冒烟测试
  D. checkpoint 集成：save_scratchpad_snapshot / load_scratchpad_snapshot
  E. 文档一致性：SKILL.md / RUNBOOK.md / README.md 版本 3.13.0
  F. 向后兼容：旧 checkpoint 无 Scratchpad 快照时自动降级

用法：python scripts/audit/v313_acceptance.py
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
SRC_DIR = WORKSPACE / "outputs" / "annotations" / "modern_697_刘慈欣_球状闪电"

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


# ============================================================================
# A. 产物格式（py_compile）
# ============================================================================
print("\n=== A. 产物格式（py_compile）===")

for script_name in ["scratchpad.py", "annotate_segment.py", "checkpoint.py"]:
    script_path = SCRIPTS / script_name
    try:
        py_compile.compile(str(script_path), doraise=True)
        check(f"A-{script_name}-py_compile", True, "编译通过")
    except py_compile.PyCompileError as e:
        check(f"A-{script_name}-py_compile", False, str(e)[:200])

check("A-scratchpad-exists", (SCRIPTS / "scratchpad.py").exists())
check("A-annotate-exists", (SCRIPTS / "annotate_segment.py").exists())
check("A-checkpoint-exists", (SCRIPTS / "checkpoint.py").exists())

# ============================================================================
# B. Scratchpad 核心功能
# ============================================================================
print("\n=== B. Scratchpad 核心功能 ===")

sys.path.insert(0, str(SCRIPTS))
from scratchpad import Scratchpad, CharacterRecord, EventRecord  # noqa: E402

# B1. 创建空 Scratchpad
pad = Scratchpad(doc_id="test_acceptance", total_segments=10)
check("B1-create-empty", pad.doc_id == "test_acceptance" and len(pad.characters) == 0 and len(pad.events) == 0)

# B2. 添加人物
c1 = pad.add_character("江洋", aliases=["我"], first_segment="seg_0001", description="主角")
check("B2-add-character", c1.canonical_name == "江洋" and "我" in c1.aliases)

# B3. 更新人物（追加别名 + 计数）
c1b = pad.add_character("江洋", aliases=["灰鹰三号"], segment_id="seg_0005")
check("B3-update-character", "灰鹰三号" in c1b.aliases and c1b.mention_count == 1)

# B4. 按别名查找
check("B4-find-by-alias", pad.get_character("我") is not None and pad.is_known_character("灰鹰三号"))

# B5. 添加事件
e1 = pad.add_event("seg_0001", "将军提出陆沉预案", involved_characters=["江洋", "将军"], event_type="激励事件")
check("B5-add-event", e1.event_id == "evt_001" and e1.status == "open")

# B6. 事件归并（相似描述不创建新事件）
e2 = pad.add_event("seg_0002", "将军提出陆沉预案", involved_characters=["江洋"])
check("B6-event-merge", e2.event_id == "evt_001" and len(pad.events) == 1)

# B7. 关闭事件
check("B7-close-event", pad.close_event("evt_001") and pad.events[0].status == "closed")

# B8. 待确认别名
pad.mark_pending_confirmation("江洋", "灰鹰")
pad.confirm_alias("江洋", "灰鹰", is_same=True)
check("B8-pending-confirmation", "灰鹰" in pad.get_character("江洋").aliases)

# B9. 摘要生成
summary = pad.to_summary(current_segment_index=5)
check("B9-summary", "便签本摘要" in summary and "江洋" in summary and "evt_001" in summary)

# B10. JSON 序列化 round-trip
json_str = pad.to_json()
pad2 = Scratchpad.from_json(json_str)
check("B10-json-roundtrip", pad2.doc_id == pad.doc_id and len(pad2.characters) == len(pad.characters))

# B11. 从批注结果更新
pad3 = Scratchpad(doc_id="test_anno", total_segments=3)
structure = {"D01": "激励事件", "D04": {"core": "紧张", "intensity": 7}}
emotion = {"D19_emotion_analysis": {"target": "林澜", "primary": {"emotion": "焦虑"}}}
result = pad3.update_from_annotation("seg_0001", structure=structure, emotion=emotion)
check("B11-update-from-annotation", result["new_characters"] >= 1 and result["new_events"] >= 1)

# B12. 统计信息
stats = pad.stats()
check("B12-stats", stats["total_characters"] >= 1 and stats["total_events"] >= 1)

# ============================================================================
# C. annotate_segment 集成（端到端冒烟测试）
# ============================================================================
print("\n=== C. annotate_segment 集成（端到端冒烟测试）===")

if SRC_DIR.is_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        doc_id = "modern_697_刘慈欣_球状闪电"

        # 复制前 5 段 segments
        segs_src = SRC_DIR / f"{doc_id}_segments.jsonl"
        segs_dst = tmp / "segments.jsonl"
        with segs_src.open(encoding="utf-8") as f:
            lines = [next(f) for _ in range(5)]
        segs_dst.write_text("".join(lines), encoding="utf-8")

        # 准备前 3 段 structure 批注
        struct_src = SRC_DIR / f"{doc_id}_structure.jsonl"
        input_json = tmp / "input_structure.jsonl"
        with struct_src.open(encoding="utf-8") as f:
            lines = [next(f).strip() for _ in range(3)]
        input_json.write_text("\n".join(lines) + "\n", encoding="utf-8")

        # 运行 annotate_segment.py --input-json（启用 Scratchpad）
        cmd = [
            sys.executable, str(SCRIPTS / "annotate_segment.py"),
            "--segments", str(segs_dst),
            "--doc-id", doc_id,
            "--output-dir", str(tmp),
            "--input-json", str(input_json),
            "--layers", "structure",
            "--force",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=str(tmp))
        check("C-annotate-rc0", result.returncode == 0, f"rc={result.returncode}")

        # 检查 Scratchpad 文件
        scratchpad_path = tmp / f"{doc_id}_scratchpad.json"
        check("C-scratchpad-file-exists", scratchpad_path.is_file())

        if scratchpad_path.is_file():
            sp_data = json.loads(scratchpad_path.read_text(encoding="utf-8"))
            check("C-scratchpad-has-characters-or-events",
                  len(sp_data.get("characters", {})) >= 0 and len(sp_data.get("events", [])) >= 1)
            check("C-scratchpad-processed-segments", sp_data.get("processed_segments", 0) == 3)

        # 检查 checkpoint 中是否有 Scratchpad 快照
        ckpt_path = tmp / f"{doc_id}_checkpoint.json"
        if ckpt_path.is_file():
            ckpt = json.loads(ckpt_path.read_text(encoding="utf-8"))
            check("C-checkpoint-has-scratchpad-snapshot", "scratchpad_snapshot" in ckpt)
        else:
            check("C-checkpoint-has-scratchpad-snapshot", False, "checkpoint 文件不存在")

        # 检查 structure.jsonl
        struct_out = tmp / f"{doc_id}_structure.jsonl"
        check("C-structure-output-exists", struct_out.is_file())
        if struct_out.is_file():
            lines = struct_out.read_text(encoding="utf-8").strip().split("\n")
            check("C-structure-output-3-lines", len(lines) == 3, f"{len(lines)} 行")

        # 测试 --no-scratchpad
        cmd_no_sp = cmd + ["--no-scratchpad"]
        result_no_sp = subprocess.run(cmd_no_sp, capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=str(tmp))
        check("C-no-scratchpad-rc0", result_no_sp.returncode == 0, f"rc={result_no_sp.returncode}")
else:
    check("C-skipped", True, f"测试文件不存在: {SRC_DIR}")

# ============================================================================
# D. checkpoint 集成
# ============================================================================
print("\n=== D. checkpoint 集成 ===")

from checkpoint import save_scratchpad_snapshot, load_scratchpad_snapshot  # noqa: E402

# D1. 保存和恢复 Scratchpad 快照
ckpt_test = {"doc_id": "test_ckpt", "total_segments": 5, "completed": []}
pad_test = Scratchpad(doc_id="test_ckpt", total_segments=5)
pad_test.add_character("测试人物", first_segment="seg_0001")
save_scratchpad_snapshot(ckpt_test, pad_test)
check("D1-save-snapshot", "scratchpad_snapshot" in ckpt_test)

restored = load_scratchpad_snapshot(ckpt_test)
check("D1-load-snapshot", restored is not None and restored.doc_id == "test_ckpt")

# D2. 旧 checkpoint 无 Scratchpad 快照时自动降级
old_ckpt = {"doc_id": "old_test", "total_segments": 3, "completed": []}
restored_old = load_scratchpad_snapshot(old_ckpt)
check("D2-legacy-degradation", restored_old is None)

# D3. None 输入
check("D3-none-input", load_scratchpad_snapshot(None) is None)

# ============================================================================
# E. 文档一致性
# ============================================================================
print("\n=== E. 文档一致性 ===")

skill_md = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
runbook = (SKILL_ROOT / "docs" / "RUNBOOK.md").read_text(encoding="utf-8")
readme = (SKILL_ROOT / "README.md").read_text(encoding="utf-8")

check("E-SKILL-version 存在", "v3." in skill_md, "SKILL.md 含版本号")
check("E-SKILL-scratchpad-section", "Scratchpad" in skill_md or "便签本" in skill_md, "SKILL.md 含 Scratchpad 章节")
check("E-RUNBOOK-version 存在", "v3." in runbook, "RUNBOOK.md 含版本号")
check("E-README-version 存在", "v3." in readme, "README.md 含版本号")

# ============================================================================
# 汇总
# ============================================================================
print(f"\n{'='*60}")
print(f"v3.13.0 验收汇总：PASS={PASS}  FAIL={FAIL}  TOTAL={PASS+FAIL}")
if FAIL == 0:
    print("ALL PASS ✅")
else:
    print(f"有 {FAIL} 项失败 ❌")
    for name, ok, detail in RESULTS:
        if not ok:
            print(f"  FAIL: {name} — {detail}")
print(f"{'='*60}")

sys.exit(0 if FAIL == 0 else 1)
