# -*- coding: utf-8 -*-
"""
scripts/audit/v32_acceptance.py — v3.2 一致性基础设施验收（T-031 / ADR-012）

覆盖：
  1. 新脚本 py_compile（lexicon_crosscheck / collect_lexicon_candidates / llm_wrapper）
  2. collect 功能测试：构造含自由情感词的测试 JSONL → 检出 ≥3 次触发候选
  3. crosscheck 首跑断言：D19 命中 33 / 真实缺口小类 NH,NI,NL / 候选 ≥20
  4. llm_wrapper --show-schema：D04 20 词 + D19 50 词枚举
  5. 文档一致性：SKILL 版本历史 3.2.0 / emotion-lexicon §四.b / README §八.3 / RUNBOOK §2.6+§3
  6. 数据文件不进 skill 仓库（datasets 位于工作区根，skill 独立仓库无副本）

用法：python scripts/audit/v32_acceptance.py
退出码 0 = ALL PASS；非 0 = 有失败项。
"""

from __future__ import annotations

import io
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]            # skill 仓库根
SKILL = ROOT
WORKSPACE = ROOT.parents[1]                            # 工作区根（StoryEngine）
SCRIPTS = SKILL / "scripts"
OUT = WORKSPACE / "outputs" / "annotations"

PASS: list[str] = []
FAIL: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(f"{name}" + (f" — {detail}" if detail else ""))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def py_compile_all() -> None:
    print("\n[1/6] py_compile 新脚本")
    for rel in ["scripts/lexicon_crosscheck.py", "scripts/collect_lexicon_candidates.py", "examples/llm_wrapper.py"]:
        p = SKILL / rel
        r = subprocess.run([sys.executable, "-m", "py_compile", str(p)], capture_output=True, text=True)
        check(f"py_compile {rel}", r.returncode == 0, r.stderr.strip()[:200])


def collect_functional() -> None:
    print("\n[2/6] collect 功能测试（构造自由词测试 JSONL）")
    test_records = []
    for i in range(4):
        test_records.append({
            "schema_version": "2.9.0", "annotation_id": f"t_seg_{i:04d}_emotion_ann_0",
            "document_id": "t", "segment_id": f"t_seg_{i:04d}", "chapter": None,
            "section_type": "body",
            "text_span": {"hash": f"h{i}", "start_char": 0, "end_char": 10, "text": "测试文本"},
            "layers": {"emotion": {"primary": {"emotion": "羞愧", "intensity": 5, "polarity": "negative"}}},
            "confidence": {"overall": 0.8, "per_dimension": {"D19": 0.8}},
            "null_reasons": {}, "alternatives": [], "status": "confirmed", "_metadata": {},
        })
    with tempfile.TemporaryDirectory() as td:
        fp = Path(td) / "t_emotion.jsonl"
        with io.open(fp, "w", encoding="utf-8") as f:
            for rec in test_records:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        r = subprocess.run(
            [sys.executable, str(SCRIPTS / "collect_lexicon_candidates.py"),
             "--files", str(fp), "--min-freq", "3"],
            capture_output=True, text=True, encoding="utf-8",
        )
        ok = "触发候选 1" in r.stdout and "羞愧" in r.stdout
        check("collect 检出自由词 ≥3 次触发", ok, r.stdout.strip().splitlines()[-1])


def crosscheck_report() -> None:
    print("\n[3/6] crosscheck 首跑报告断言")
    rep = OUT / "lexicon_crosscheck_report.md"
    if not rep.exists():
        check("crosscheck 报告存在", False, str(rep))
        return
    s = io.open(rep, encoding="utf-8").read()
    checks = [
        ("D19 命中率 33/66%", "33（66.0%）" in s),
        ("真实缺口小类 NH/NI/NL", "NH, NI, NL" in s),
        ("候选清单含跳脚/红眼/丢丑", all(w in s for w in ["跳脚", "红眼", "丢丑"])),
        ("NN=数据版贬责代码标注", "数据版代码为 NN" in s),
        ("NRC 人工抽查结论已追加", "## 五、NRC 中文版人工抽查结论" in s),
    ]
    for name, ok in checks:
        check(f"crosscheck {name}", ok)


def collect_report() -> None:
    print("\n[4/6] collect 首跑报告断言")
    rep = OUT / "lexicon_candidates_report.md"
    if not rep.exists():
        check("collect 报告存在", False, str(rep))
        return
    s = io.open(rep, encoding="utf-8").read()
    check("collect 首跑 0 自由词（语料与 50 词表一致）", "自由词 0" in s or "共 0 个自由词" in s)
    sop = OUT / "lexicon_sop_snippet.md"
    check("SoP 片段存在", sop.exists())


def llm_wrapper_schema() -> None:
    print("\n[5/6] llm_wrapper --show-schema 枚举约束")
    r = subprocess.run(
        [sys.executable, str(SKILL / "examples" / "llm_wrapper.py"), "--show-schema", "all"],
        capture_output=True, text=True, encoding="utf-8",
    )
    out = r.stdout
    check("D04 20 词枚举", all(w in out for w in ["平静", "压抑", "羞耻", "渴望", "厌恶"]) and "20 词" in out)
    check("D19 50 词枚举", "50 词" in out and "冷峻中的悲悯" in out and "反讽性平静" in out)
    # mock 冒烟仍可用
    payload = json.dumps({
        "segment": {"segment_id": "t_seg_0001", "document_id": "t",
                    "text_span": {"start_char": 0, "end_char": 10, "text": "abcdefghij"}},
        "request_layers": ["structure"], "schema_version": "2.9.0",
    }, ensure_ascii=False)
    r2 = subprocess.run(
        [sys.executable, str(SKILL / "examples" / "llm_wrapper.py"), "--mock"],
        input=payload, capture_output=True, text=True, encoding="utf-8",
    )
    check("mock 冒烟仍产出合法行", r2.returncode == 0 and '"status": "confirmed"' in r2.stdout)


def doc_consistency() -> None:
    print("\n[6/6] 文档一致性")
    skill_md = io.open(SKILL / "SKILL.md", encoding="utf-8").read()
    lexicon = io.open(SKILL / "references" / "emotion-lexicon.md", encoding="utf-8").read()
    readme = io.open(SKILL / "README.md", encoding="utf-8").read()
    runbook = io.open(SKILL / "docs" / "RUNBOOK.md", encoding="utf-8").read()
    checks = [
        ("SKILL 版本历史含 3.2.0", "**3.2.0**" in skill_md and "ADR-012" in skill_md),
        ("SKILL 索引含词表演化工具", "lexicon_crosscheck" in skill_md and "collect_lexicon_candidates" in skill_md),
        ("emotion-lexicon §四.b DLUT 21 小类", "四.b 基元归约审查协议" in lexicon and "NN" in lexicon),
        ("README §八.3 数据指引", "Do not redistribute" in readme and "ir.dlut.edu.cn" in readme),
        ("RUNBOOK §2.6 新脚本", "lexicon_crosscheck" in runbook and "collect_lexicon_candidates" in runbook),
        ("RUNBOOK §3 SoP 自动生成行", "经验回写管道" in runbook),
    ]
    for name, ok in checks:
        check(name, ok)


def main() -> int:
    print("=" * 60)
    print("v3.2 一致性基础设施验收（T-031 / ADR-012）")
    print("=" * 60)
    py_compile_all()
    collect_functional()
    crosscheck_report()
    collect_report()
    llm_wrapper_schema()
    doc_consistency()
    print("\n" + "=" * 60)
    print(f"结果：PASS {len(PASS)} / FAIL {len(FAIL)}")
    if FAIL:
        print("失败项：")
        for f in FAIL:
            print(f"  ❌ {f}")
        return 1
    print("✅ ALL PASS — v3.2 验收通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
