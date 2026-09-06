#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/preprocess.py — 输入预处理脚本 v2.6.0

功能：
  对长篇叙事文本做：章节边界识别、frontmatter 标记、智能切分、
  上下文锚点追加、checkpoint 初始化。
  是 v2.3 split_text.py 的 v2.5 继任者。

零第三方依赖：仅 Python 3.6+ 标准库。

P0 级 Bug 修复清单（v2.5 三方评审 §2.4，本脚本已全部修复）：
  [x] #1 split_long_segment ID 碰撞 —— 使用全局 seg_counter，不再从 0 重编。
  [x] #2 split_long_segment 坐标漂移 —— 所有子片段使用 original[start:end]==text 自校验。
  [x] #3 无章节边界时全书截断 2000 字 —— 退化到按长度智能切分（不截断），
         显式打印警告，不做 sys.exit 硬失败。
  [x] #4 frontmatter 被丢弃 —— 作为 section_type="frontmatter" 的 segment 输出。
  [x] #7 segment_id 不带 doc_id 前缀 —— 统一为 "{doc_id}_seg_{NNNN}"。

输出：
  - {doc_id}_segments.jsonl
  - {doc_id}_checkpoint.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path

# v2.5.1 修复 #1：Windows GBK 控制台 UnicodeEncodeError（emoji 打印崩溃）
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


# --------------------------- 章节边界正则（v2.5 修复版）---------------------------

CHAPTER_PATTERNS: list[tuple[str, str]] = [
    # 中文章节标题
    (r"^\s*第[一二三四五六七八九十百千万零两]+\s*章\b.*$", "chapter"),
    (r"^\s*第[0-9]+\s*章\b.*$", "chapter"),
    # 仅数字的章标题（兼容「一」「十二」单独一行）
    (r"^\s*[一二三四五六七八九十百千万零两]+\s*$", "chapter"),
    # 英文章节
    (r"^\s*Chapter\s+[0-9IVXLCDM]+\b.*$", "chapter"),
    (r"^\s*CHAPTER\s+[0-9IVXLCDM]+\b.*$", "chapter"),
    # 仅罗马数字
    (r"^\s*[IVXLCDM]+\s*$", "chapter"),
    # 特殊章节
    (r"^\s*序章\s*$", "prologue"),
    (r"^\s*楔子\s*$", "prologue"),
    (r"^\s*尾声\s*$", "epilogue"),
    (r"^\s*后记\s*$", "epilogue"),
    (r"^\s*Prologue\s*$", "prologue"),
    (r"^\s*EPILOGUE\s*$", "epilogue"),
    (r"^\s*Epilogue\s*$", "epilogue"),
    # v3.8.4 新增（T-050）：纯文字小节标题识别
    (r"^\s*.{1,12}之[一二三四五六七八九十]+\s*$", "chapter"),  # 「异象之一」「林云之二」模式
    (r"^\s*[0-9]+[、.．]\s*.{0,20}\s*$", "chapter"),  # 「1. xxx」「2、xxx」数字序列
    (r"^\s*[一二三四五六七八九十]+[、.．]\s*.{0,20}\s*$", "chapter"),  # 「一、xxx」中文数字序列
]

# v3.8.9 T-075：常见小说网站广告水印清理正则
AD_WATERMARK_PATTERNS = [
    r"本作品下载于[^\n]+",
    r"更多好看小说下载敬请访问[^\n]+",
    r"笔趣阁[^\n]*",
    r"www\.[a-zA-Z0-9]+\.(com|net|org|cn)[^\n]*",
    r"感谢打赏[^\n]*",
    r"求收藏[^\n]*",
    r"求推荐[^\n]*",
    r"求月票[^\n]*",
]

def clean_ad_watermarks(text: str) -> str:
    """清理常见小说网站广告水印。v3.8.9 T-075"""
    for pattern in AD_WATERMARK_PATTERNS:
        text = re.sub(pattern, "", text)
    # 清理多余空行
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def normalize_text(text: str) -> str:
    """与 Schema 严格一致：strip + \\r\\n / \\r → \\n。"""
    return text.replace("\r\n", "\n").replace("\r", "\n").strip()




def is_possible_section_title(line: str, prev_line: str = "", next_line: str = "") -> bool:
    """v3.8.4 新增（T-050）：短行启发式标题检测。
    判断一行是否可能是小节标题：
    - 长度较短（2-15字符）
    - 前后有空行或短行
    - 不以标点结尾（排除正文句子）
    - 不是纯数字（已被 CHAPTER_PATTERNS 覆盖）
    """
    line = line.strip()
    if not line or len(line) > 15 or len(line) < 2:
        return False
    # 不以句号、问号、感叹号、逗号结尾（正文句子特征）
    if line[-1] in "。！？，、；：":
        return False
    # 包含空格且长度>10，可能是正文
    if " " in line and len(line) > 10:
        return False
    # 前后有空行（标题特征）
    has_blank_before = not prev_line.strip()
    has_blank_after = not next_line.strip()
    if has_blank_before and has_blank_after:
        return True
    if has_blank_before and len(line) <= 8:
        return True
    return False

def compute_hash(text: str) -> str:
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()[:16]


def estimate_tokens(text: str) -> int:
    """粗略 token 估计（中文字符 1:1，英文按词）。"""
    if not text:
        return 0
    cn = len(re.findall(r"[\u4e00-\u9fff]", text))
    en = len(re.findall(r"[A-Za-z]+", text))
    return max(1, cn + en + max(0, len(text) - cn - en) // 4)


# --------------------------- 边界检测 ---------------------------

def detect_chapter_boundaries(text: str) -> list[dict]:
    """检测所有章节边界，列表返回 position/name/section_type。
    排序后保证按 position 递增，且相近（<10 字符）边界去重。"""
    boundaries: list[dict] = []
    for pattern, s_type in CHAPTER_PATTERNS:
        for m in re.finditer(pattern, text, re.MULTILINE):
            pos = m.start()
            # 重复边界去重
            if any(abs(b["position"] - pos) < 10 for b in boundaries):
                continue
            boundaries.append({
                "position": pos,
                "text": m.group().strip(),
                "name": m.group().strip(),
                "section_type": s_type,  # prologue / chapter / epilogue
            })
    boundaries.sort(key=lambda b: b["position"])

    # 章节编号（从 1 开始），prologue 作为 0 章
    chapter_counter = 0
    for b in boundaries:
        if b["section_type"] == "prologue":
            b["chapter_index"] = 0
        else:
            chapter_counter += 1
            b["chapter_index"] = chapter_counter
    return boundaries


def detect_frontmatter(text: str, boundaries: list[dict]) -> tuple[str, int, str | None]:
    """返回 (frontmatter_text, frontmatter_end_offset, warning)。
    frontmatter = 第一个章节边界之前的所有内容。"""
    if not boundaries:
        # 全书没有章节边界 → 警告，frontmatter 视为全文
        return text, len(text), (
            "未检测到任何章节边界（'第X章'/'Chapter X'/'序章'/'楔子'等），"
            "全文将按长度智能切分（section_type=frontmatter），可能识别失败。"
        )
    first_pos = boundaries[0]["position"]
    return text[:first_pos], first_pos, None


# --------------------------- 切分核心 ---------------------------

def _assert_text_slice_matches(original: str, start: int, end: int, expected: str):
    """自校验：original[start:end] 必须与 expected 完全一致（忽略末尾单个换行差）。
    用来修复 #2 坐标漂移 bug。失败直接抛异常——避免静默产出损坏数据。"""
    sliced = original[start:end]
    if sliced == expected:
        return
    # 允许末尾差一个换行
    if sliced.rstrip("\n") == expected.rstrip("\n"):
        return
    raise AssertionError(
        f"[preprocess] 坐标漂移！start={start} end={end} sliced_len={len(sliced)} "
        f"expected_len={len(expected)} slice[:30]={sliced[:30]!r} "
        f"expected[:30]={expected[:30]!r}"
    )


def split_chapter_text(
    chapter_text: str,
    chapter_name: str,
    chapter_index: int,
    section_type: str,
    base_offset: int,
    original: str,
    max_tokens: int,
    doc_id: str,
    seg_counter_start: int,
) -> tuple[list[dict], int]:
    """把一个 chapter（或 frontmatter）切成合适大小的 segments。
    返回 (segments_list, next_seg_counter)。
    - seg_counter_start 是**全局**计数器（修复 #1 ID 碰撞）。
    - base_offset 是 chapter_text 在【原始全文】中的偏移。
    - original 是【原始全文】，用于 #2 坐标自校验。
    """
    # 先按段落块切开
    para_spans: list[tuple[int, int, str]] = []  # (rel_start, rel_end, text)
    for m in re.finditer(r"[^\n]+(\n\s*\n?|$)", chapter_text):
        para_text = m.group().strip("\n")
        if not para_text.strip():
            continue
        rel_s = m.start()
        rel_e = rel_s + len(m.group())
        para_spans.append((rel_s, rel_e, para_text))

    if not para_spans:
        # 空章节 → 一条空 seg
        rel_s, rel_e = 0, len(chapter_text)
        seg_text = chapter_text
        g_start = base_offset + rel_s
        g_end = base_offset + rel_e
        _assert_text_slice_matches(original, g_start, g_end, seg_text)
        seg = {
            "segment_index": seg_counter_start,
            "segment_id": f"{doc_id}_seg_{seg_counter_start:04d}",
            "chapter": chapter_name,
            "chapter_index": chapter_index,
            "section_type": section_type,
            "text": seg_text,
            "start_char": g_start,
            "end_char": g_end,
            "hash": compute_hash(seg_text),
            "approx_tokens": estimate_tokens(seg_text),
            "context_prev": "",
            "context_next": "",
            "is_polluted": False,
            "pollution_warning": None,
        }
        return [seg], seg_counter_start + 1

    # 按段落贪心合并，不超 max_tokens
    segments: list[dict] = []
    current_rel_start: int | None = None
    current_rel_end: int | None = None
    current_text = ""
    current_tokens = 0

    def flush_current():
        nonlocal current_rel_start, current_rel_end, current_text, current_tokens
        if current_rel_start is None or current_rel_end is None:
            return
        seg_counter = seg_counter_start + len(segments)
        seg_text = current_text
        g_start = base_offset + current_rel_start
        g_end = base_offset + current_rel_end
        # 坐标自校验（修复 #2）
        _assert_text_slice_matches(original, g_start, g_end, seg_text)
        segments.append({
            "segment_index": seg_counter,
            "segment_id": f"{doc_id}_seg_{seg_counter:04d}",
            "chapter": chapter_name,
            "chapter_index": chapter_index,
            "section_type": section_type,
            "text": seg_text,
            "start_char": g_start,
            "end_char": g_end,
            "hash": compute_hash(seg_text),
            "approx_tokens": estimate_tokens(seg_text),
            "context_prev": "",
            "context_next": "",
            "is_polluted": False,
            "pollution_warning": None,
        })
        current_rel_start = current_rel_end = None
        current_text = ""
        current_tokens = 0

    for rel_s, rel_e, para_text in para_spans:
        para_tokens = estimate_tokens(para_text)
        # 如果单独一段超过 max_tokens，要句子级子切
        if para_tokens > max_tokens:
            flush_current()
            sentence_subs = _split_by_sentences(
                para_text, para_rel_offset=rel_s,
                max_tokens=max_tokens,
            )
            for sub_rel_s, sub_rel_e, sub_text in sentence_subs:
                seg_counter = seg_counter_start + len(segments)
                g_start = base_offset + sub_rel_s
                g_end = base_offset + sub_rel_e
                _assert_text_slice_matches(original, g_start, g_end, sub_text)
                segments.append({
                    "segment_index": seg_counter,
                    "segment_id": f"{doc_id}_seg_{seg_counter:04d}",
                    "chapter": chapter_name,
                    "chapter_index": chapter_index,
                    "section_type": section_type,
                    "text": sub_text,
                    "start_char": g_start,
                    "end_char": g_end,
                    "hash": compute_hash(sub_text),
                    "approx_tokens": estimate_tokens(sub_text),
                    "context_prev": "",
                    "context_next": "",
                    "is_polluted": False,
                    "pollution_warning": None,
                })
            continue

        if current_tokens + para_tokens > max_tokens and current_tokens > 0:
            flush_current()

        if current_rel_start is None:
            current_rel_start = rel_s
        current_rel_end = rel_e
        # 拼接文本，保留原始换行
        addon = chapter_text[rel_s:rel_e]
        current_text = current_text + addon if current_text else addon
        current_tokens += para_tokens

    flush_current()
    return segments, seg_counter_start + len(segments)


def _split_by_sentences(
    para_text: str,
    para_rel_offset: int,
    max_tokens: int,
) -> list[tuple[int, int, str]]:
    """对超长段落按句子边界切，返回 (段内rel_start, 段内rel_end, text)。"""
    results: list[tuple[int, int, str]] = []
    # 句子边界：中文句号/问号/叹号/省略号/分号/引号闭合
    boundaries = [0]
    # 注意：Python 源码文件编码，避免不可见字符——逐字明确列出
    _PUNCT = "。？！；!?;\u2026"  # … U+2026
    _CLOSE = "\u201d\"\'\u300e\u300d"  # 」 』 右引号（兼容多种）
    for m in re.finditer(r"([" + re.escape(_PUNCT) + r"]{1,6}|[" + re.escape(_CLOSE) + r"])", para_text):
        boundaries.append(m.end())
    boundaries.append(len(para_text))

    cur_start_abs = 0  # 相对 para_text
    cur_tokens = 0
    i = 0
    while i + 1 < len(boundaries):
        s = boundaries[i]
        e = boundaries[i + 1]
        chunk = para_text[s:e]
        tok = estimate_tokens(chunk)
        if cur_tokens + tok > max_tokens and cur_tokens > 0:
            sub_text = para_text[cur_start_abs:s]
            rel_s = para_rel_offset + cur_start_abs
            rel_e = para_rel_offset + s
            results.append((rel_s, rel_e, sub_text))
            cur_start_abs = s
            cur_tokens = 0
        cur_tokens += tok
        i += 1
    sub_text = para_text[cur_start_abs:]
    if sub_text.strip():
        results.append((
            para_rel_offset + cur_start_abs,
            para_rel_offset + len(para_text),
            sub_text,
        ))
    return results


def add_context_window(segments: list[dict], overlap_chars: int) -> list[dict]:
    """为每段追加前后 overlap_chars 字符上下文锚点。"""
    for i, seg in enumerate(segments):
        if i > 0:
            prev_text = segments[i - 1]["text"]
            seg["context_prev"] = prev_text[-overlap_chars:] if len(prev_text) > overlap_chars else prev_text
        else:
            seg["context_prev"] = ""
        if i < len(segments) - 1:
            next_text = segments[i + 1]["text"]
            seg["context_next"] = next_text[:overlap_chars]
        else:
            seg["context_next"] = ""
    return segments


def create_initial_checkpoint(doc_id: str, segments: list[dict]) -> dict:
    now = datetime.now().isoformat(timespec="seconds")
    return {
        "doc_id": doc_id,
        "schema_version": "2.6.0",
        "total_segments": len(segments),
        "completed": [],
        "cross_segment_completed": False,
        "merged_completed": False,
        "render_report_completed": False,
        "last_updated": now,
        "created_at": now,
    }


# --------------------------- main ---------------------------

def main() -> int:
    p = argparse.ArgumentParser(
        description="【精读批注 v2.6 Phase 1】输入预处理：章节边界+frontmatter+切分+checkpoint。"
    )
    p.add_argument("--input", required=True, help="原始文本文件路径（支持 utf-8 / gbk 自动回退）")
    p.add_argument("--doc-id", required=True, help="文档 ID（所有输出文件前缀、segment_id 前缀）")
    p.add_argument("--max-tokens", type=int, default=2000, help="单段理想 token 数（粗略，默认 2000）")
    p.add_argument("--overlap-chars", type=int, default=200, help="上下文锚点字符数（默认 200）")
    p.add_argument("--fallback", dest="fallback", action="store_true", default=True,
                       help="兜底切分（默认开启）：章节边界过少或单段过长时自动按字符数粗切")
    p.add_argument("--no-fallback", dest="fallback", action="store_false",
                   help="关闭兜底切分（仅用章节边界切分）")
    p.add_argument("--fallback-chars", type=int, default=2000,
                   help="兜底切分单段字符数（默认 2000，约等于 2000 token）")
    p.add_argument("--output-dir", type=str, default=None,
                   help="输出目录（默认为当前工作目录；产出 segments.jsonl + checkpoint.json 放这里）")
    args = p.parse_args()

    in_path = Path(args.input)
    if not in_path.is_file():
        print(f"[preprocess] 错误：找不到输入文件 {in_path}", file=sys.stderr)
        return 2

    raw = in_path.read_bytes()
    text = None
    for enc in ("utf-8", "utf-8-sig", "gbk", "gb18030"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        print(f"[preprocess] 错误：无法解码 {in_path}（utf-8/gbk 都失败）", file=sys.stderr)
        return 2

    original = text  # 始终保留 original 用作坐标自校验 base
    # 统一换行（保留 original 的实际字符偏移，因为 normalize 只是前后去首尾；真正影响 hash 的 normalize 在 compute_hash 内做）
    original = original.replace("\r\n", "\n").replace("\r", "\n")

    out_dir = Path(args.output_dir) if args.output_dir else Path.cwd()
    out_dir.mkdir(parents=True, exist_ok=True)
    segs_out = out_dir / f"{args.doc_id}_segments.jsonl"
    ckpt_out = out_dir / f"{args.doc_id}_checkpoint.json"

    boundaries = detect_chapter_boundaries(original)
    print(f"[preprocess] 检测到 {len(boundaries)} 个章节/楔子/尾声边界")

    frontmatter_text, frontmatter_end, fm_warning = detect_frontmatter(original, boundaries)
    if fm_warning:
        print(f"[preprocess] ⚠️ {fm_warning}")

    all_segments: list[dict] = []
    seg_counter = 0

    # --- frontmatter 作为第一段（修复 #4）---
    if fm_warning is None and frontmatter_text.strip():
        # 有章节边界 → frontmatter 独立 seg（section_type=frontmatter）
        seg_text = frontmatter_text
        rel_s, rel_e = 0, frontmatter_end
        g_start, g_end = 0, frontmatter_end
        _assert_text_slice_matches(original, g_start, g_end, original[g_start:g_end])
        seg_text = original[g_start:g_end]
        if seg_text.strip():
            all_segments.append({
                "segment_index": seg_counter,
                "segment_id": f"{args.doc_id}_seg_{seg_counter:04d}",
                "chapter": "frontmatter",
                "chapter_index": 0,
                "section_type": "frontmatter",
                "text": seg_text,
                "start_char": g_start,
                "end_char": g_end,
                "hash": compute_hash(seg_text),
                "approx_tokens": estimate_tokens(seg_text),
                "context_prev": "",
                "context_next": "",
                "is_polluted": False,
                "pollution_warning": None,
            })
            seg_counter += 1
    elif fm_warning is not None:
        # 没有任何章节边界（修复 #3）：frontmatter=全文，但退化到按长度切分，section_type=frontmatter
        warning_val = fm_warning
        chapter_chunks, seg_counter = split_chapter_text(
            original,
            chapter_name="未知章节",
            chapter_index=1,
            section_type="frontmatter",
            base_offset=0,
            original=original,
            max_tokens=args.max_tokens,
            doc_id=args.doc_id,
            seg_counter_start=0,
        )
        for s in chapter_chunks:
            s["is_polluted"] = True
            s["pollution_warning"] = warning_val
        all_segments.extend(chapter_chunks)
        # 无章节边界直接进最终输出流程
    else:
        # 有章节边界，但 frontmatter 空（开头直接是第一章）——不产出 frontmatter 段
        pass

    # --- 章节 body（仅在有章节边界时走）---
    if boundaries:
        for i, b in enumerate(boundaries):
            start = b["position"]
            end = boundaries[i + 1]["position"] if i + 1 < len(boundaries) else len(original)
            chapter_text = original[start:end]
            b_section_type = "body" if b["section_type"] == "chapter" else (
                "frontmatter" if b["section_type"] == "prologue" else "epilogue"
            )
            chapter_chunks, seg_counter = split_chapter_text(
                chapter_text,
                chapter_name=b["name"],
                chapter_index=b["chapter_index"],
                section_type=b_section_type,
                base_offset=start,
                original=original,
                max_tokens=args.max_tokens,
                doc_id=args.doc_id,
                seg_counter_start=seg_counter,
            )
            all_segments.extend(chapter_chunks)


    # --- v3.8.5 兜底切分检查（T-057）---
    if args.fallback and all_segments:
        total_chars = sum(len(s.get("text", "")) for s in all_segments)
        max_seg_chars = max(len(s.get("text", "")) for s in all_segments)
        need_fallback = False
        fallback_reason = ""
        if len(boundaries) < 3 and total_chars > 5000:
            need_fallback = True
            fallback_reason = "章节边界过少(%d个)且全文较长(%d字符)" % (len(boundaries), total_chars)
        elif max_seg_chars > 5000:
            need_fallback = True
            fallback_reason = "单段过长(%d字符)" % max_seg_chars
        elif len(all_segments) < 3 and total_chars > 5000:
            need_fallback = True
            fallback_reason = "段数过少(%d段)且全文较长" % len(all_segments)

        if need_fallback:
            print("[preprocess] ⚠️ 触发兜底切分：%s" % fallback_reason)
            print("[preprocess] 按字符数粗切（每段约 %d 字符，保留句子边界）..." % args.fallback_chars)
            fallback_segs = []
            seg_counter = 0
            cur_start = 0
            cur_text = ""
            for i, ch in enumerate(original):
                cur_text += ch
                if len(cur_text) >= args.fallback_chars and ch in "。！？；!?;…":
                    fallback_segs.append({
                        "segment_index": seg_counter,
                        "segment_id": "%s_seg_%04d" % (args.doc_id, seg_counter),
                        "chapter": "兜底切分",
                        "chapter_index": seg_counter + 1,
                        "section_type": "body",
                        "text": cur_text,
                        "start_char": cur_start,
                        "end_char": i + 1,
                        "hash": compute_hash(cur_text),
                        "approx_tokens": estimate_tokens(cur_text),
                        "context_prev": "",
                        "context_next": "",
                        "is_polluted": False,
                        "pollution_warning": "v3.8.5兜底切分(章节边界识别不足)",
                    })
                    seg_counter += 1
                    cur_start = i + 1
                    cur_text = ""
            if cur_text.strip():
                fallback_segs.append({
                    "segment_index": seg_counter,
                    "segment_id": "%s_seg_%04d" % (args.doc_id, seg_counter),
                    "chapter": "兜底切分",
                    "chapter_index": seg_counter + 1,
                    "section_type": "body",
                    "text": cur_text,
                    "start_char": cur_start,
                    "end_char": len(original),
                    "hash": compute_hash(cur_text),
                    "approx_tokens": estimate_tokens(cur_text),
                    "context_prev": "",
                    "context_next": "",
                    "is_polluted": False,
                    "pollution_warning": "v3.8.5兜底切分(章节边界识别不足)",
                })
            all_segments = fallback_segs
            print("[preprocess] ✅ 兜底切分完成：%d 段（每段约%d字符）" % (len(all_segments), args.fallback_chars))
            print("[preprocess] 💡 建议：后续可用 Phase 1.5 场景边界判断 + reshape_segments.py 做精细化重排")

    # --- 上下文锚点 ---
    all_segments = add_context_window(all_segments, args.overlap_chars)

    # --- 写 segments.jsonl（每行含 schema_version/document_id 顶层字段，兼容下游）---
    with segs_out.open("w", encoding="utf-8") as f:
        for s in all_segments:
            record = {
                "schema_version": "2.6.0",
                "document_id": args.doc_id,
                "segment_index": s["segment_index"],
                "segment_id": s["segment_id"],
                "chapter": s["chapter"],
                "chapter_index": s["chapter_index"],
                "section_type": s["section_type"],
                "text_span": {
                    "hash": s["hash"],
                    "start_char": s["start_char"],
                    "end_char": s["end_char"],
                    "text": s["text"],
                },
                "approx_tokens": s["approx_tokens"],
                "context_prev": s["context_prev"],
                "context_next": s["context_next"],
                "is_polluted": s["is_polluted"],
                "pollution_warning": s["pollution_warning"],
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    # --- 写 checkpoint.json ---
    ckpt = create_initial_checkpoint(args.doc_id, all_segments)
    with ckpt_out.open("w", encoding="utf-8") as f:
        json.dump(ckpt, f, ensure_ascii=False, indent=2)

    total_tokens = estimate_tokens(original)
    print(
        f"[preprocess] ✅ 完成：共 {len(all_segments)} 个片段，"
        f"≈ {total_tokens} tokens"
    )
    print(f"   📄 segments：{segs_out.resolve()}")
    print(f"   📄 checkpoint：{ckpt_out.resolve()}")
    if fm_warning:
        print(f"   ⚠️ {fm_warning}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
