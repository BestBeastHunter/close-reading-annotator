#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/scratchpad.py — Runtime Scratchpad（运行时便签本）v3.13.1

v3.13.1 T-115 增强：
  - 人物抽取增加 D10.speaker 对话说话者
  - 增加代词回指处理（第一人称"我"自动绑定主角）
  - D06 埋设-揭露形成伏笔-回收事件对（揭露时自动关闭对应埋设）
  - 别名聚合增强（降低阈值0.6→0.5 + 称谓后缀处理 + 包含关系判断）

定位：Agent 在单本书批注过程中自主维护的轻量级工作记忆区。
不是"缩小版聚合层"，而是"输入质量增强层"——为聚合层提供更干净的输入数据。

解决的核心问题：
  1. 无状态批注导致指称不一致（同一人物用不同指称）
  2. 开放型字段（人物/事件）塞进封闭集 schema 导致大量 null

设计原则：
  - 纯 stdlib 零依赖
  - 摘要级存储（每人/事件仅一句话描述），非全量
  - 注入 Prompt 的摘要控制在 500-800 token
  - 向后兼容（旧 checkpoint 无 Scratchpad 时自动创建空实例）

用法（作为模块导入）：
  from scratchpad import Scratchpad
  pad = Scratchpad(doc_id="moon_sixpence", total_segments=89)
  pad.add_character("江洋", aliases=["我"], first_segment="seg_0001", description="主角")
  pad.add_event("seg_0001", "将军提出陆沉预案", involved=["将军", "江洋"])
  summary = pad.to_summary(current_segment_index=23)
  json_str = pad.to_json()
  pad2 = Scratchpad.from_json(json_str)

用法（CLI 冒烟测试）：
  python scripts/scratchpad.py --self-test
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Optional

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

SCHEMA_VERSION = "3.13.1"

# 触发事件识别的 D01 功能值
TRIGGER_EVENT_D01 = {"激励事件", "高潮", "转折", "下降行动", "结局"}

# 摘要长度控制（中文字符数，约等于 token 数的 1.5-2 倍）
MAX_SUMMARY_CHARS = 1200  # 约 600-800 token
MAX_CHARACTERS_IN_SUMMARY = 15
MAX_EVENTS_IN_SUMMARY = 20
MAX_ALIASES_PER_CHARACTER = 10
DESCRIPTION_MAX_LEN = 50


# ============================================================================
# 数据结构
# ============================================================================

@dataclass
class CharacterRecord:
    """人物记录——摘要级，每人仅一句话描述"""
    canonical_name: str                          # 规范名（最高频指称）
    aliases: list[str] = field(default_factory=list)  # 别名列表
    first_segment: str = ""                      # 首现段 ID
    last_segment: str = ""                       # 最近出现段 ID
    description: str = ""                        # 一句话描述（≤50字，规则生成）
    mention_count: int = 0                       # 出现次数
    related_events: list[str] = field(default_factory=list)  # 相关事件 ID 列表
    pending_confirmation: list[str] = field(default_factory=list)  # 待确认的可能别名

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "CharacterRecord":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class EventRecord:
    """事件记录——摘要级，每事件仅一句话描述"""
    event_id: str                                # 格式：evt_001（全书唯一，计数器分配）
    description: str                             # 一句话描述（≤50字）
    segment_id: str                              # 所在段 ID
    involved_characters: list[str] = field(default_factory=list)  # 涉及人物（canonical_name）
    event_type: Optional[str] = None             # 可选：激励事件/转折/高潮等
    status: str = "open"                         # "open"（未结束）或 "closed"（已结束）

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "EventRecord":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class Scratchpad:
    """运行时便签本——每本书一份，Agent 在批注过程中自主维护"""
    doc_id: str
    total_segments: int = 0
    processed_segments: int = 0
    last_updated: str = ""
    characters: dict[str, CharacterRecord] = field(default_factory=dict)  # canonical_name → 人物记录
    events: list[EventRecord] = field(default_factory=list)                # 按发现顺序存储
    _event_counter: int = 0                                                  # 内部事件 ID 计数器

    def __post_init__(self):
        if not self.last_updated:
            self.last_updated = datetime.now().isoformat()

    # ========================================================================
    # 人物操作
    # ========================================================================

    def add_character(
        self,
        name: str,
        aliases: Optional[list[str]] = None,
        first_segment: str = "",
        description: str = "",
        segment_id: str = "",
    ) -> CharacterRecord:
        """添加或更新人物。如果 canonical_name 已存在则追加别名/更新描述。"""
        name = name.strip()
        if not name:
            raise ValueError("人物名不能为空")

        if name in self.characters:
            rec = self.characters[name]
            if aliases:
                for a in aliases:
                    if a not in rec.aliases and a != name:
                        rec.aliases.append(a)
            if description and len(description) <= DESCRIPTION_MAX_LEN:
                rec.description = description
            if segment_id:
                rec.last_segment = segment_id
                rec.mention_count += 1
            self._touch()
            return rec

        rec = CharacterRecord(
            canonical_name=name,
            aliases=[a for a in (aliases or []) if a != name],
            first_segment=first_segment or segment_id,
            last_segment=segment_id or first_segment,
            description=description[:DESCRIPTION_MAX_LEN] if description else f"{name}，{first_segment or segment_id}段出现",
            mention_count=1 if segment_id else 0,
        )
        self.characters[name] = rec
        self._touch()
        return rec

    def get_character(self, name: str) -> Optional[CharacterRecord]:
        """按 canonical_name 或别名查找人物。"""
        if name in self.characters:
            return self.characters[name]
        for rec in self.characters.values():
            if name in rec.aliases:
                return rec
        return None

    def is_known_character(self, name: str) -> bool:
        """判断该名字是否为已知人物（含别名）。"""
        return self.get_character(name) is not None

    # v3.13.1 T-115 新增：称谓后缀列表（匹配时忽略，提升别名识别率）
    HONORIFIC_SUFFIXES = ["先生", "小姐", "女士", "太太", "夫人", "上尉", "中尉", "少校", "上校",
                           "将军", "司令", "政委", "老师", "教授", "博士", "医生", "护士",
                           "同学", "朋友", "同志", "师傅", "老板", "经理", "主任", "科长", "处长", "局长"]

    def _strip_honorific(self, name: str) -> str:
        """v3.13.1 T-115 新增：去除称谓后缀，返回核心名字。"""
        for suffix in self.HONORIFIC_SUFFIXES:
            if name.endswith(suffix) and len(name) > len(suffix):
                return name[:-len(suffix)]
        return name

    def find_similar_character(self, name: str, threshold: float = 0.5) -> Optional[CharacterRecord]:
        """
        v3.13.1 T-115 增强：查找可能是同一人物的别名（编辑距离相似度）。
        增强点：
          1. 降低默认阈值 0.6→0.5
          2. 去除称谓后缀后再比较（如"江洋"和"江上尉"视为相似）
          3. 包含关系判断（短名字是长名字子串时也可能是同一人，如"思特里克兰德"和"思特里克兰德先生"）
        返回最相似的人物或 None。
        """
        best_rec = None
        best_score = 0.0
        name_stripped = self._strip_honorific(name)

        for rec in self.characters.values():
            candidates = [rec.canonical_name] + rec.aliases
            for c in candidates:
                c_stripped = self._strip_honorific(c)
                # 1. 编辑距离相似度（去除称谓后缀后比较）
                score = SequenceMatcher(None, name_stripped, c_stripped).ratio()
                # 2. 包含关系加分（短名字是长名字的子串）
                if len(name_stripped) >= 2 and len(c_stripped) >= 2:
                    if name_stripped in c_stripped or c_stripped in name_stripped:
                        score = max(score, 0.7)
                if score > best_score and score >= threshold:
                    best_score = score
                    best_rec = rec
        return best_rec

    def add_alias(self, canonical_name: str, alias: str) -> bool:
        """为已知人物添加别名。返回是否成功。"""
        rec = self.get_character(canonical_name)
        if rec is None:
            return False
        if alias not in rec.aliases and alias != rec.canonical_name:
            rec.aliases.append(alias)
            if len(rec.aliases) > MAX_ALIASES_PER_CHARACTER:
                rec.aliases = rec.aliases[:MAX_ALIASES_PER_CHARACTER]
            self._touch()
        return True

    def mark_pending_confirmation(self, canonical_name: str, suspect_alias: str) -> None:
        """标记待确认的可能别名（注入 prompt 时让 LLM 顺便确认）。"""
        rec = self.get_character(canonical_name)
        if rec is not None and suspect_alias not in rec.pending_confirmation:
            rec.pending_confirmation.append(suspect_alias)
            self._touch()

    def confirm_alias(self, canonical_name: str, alias: str, is_same: bool) -> None:
        """确认待确认别名。is_same=True 则加入别名列表，否则移除待确认。"""
        rec = self.get_character(canonical_name)
        if rec is None:
            return
        if alias in rec.pending_confirmation:
            rec.pending_confirmation.remove(alias)
        if is_same:
            self.add_alias(canonical_name, alias)
        self._touch()

    # ========================================================================
    # 事件操作
    # ========================================================================

    def add_event(
        self,
        segment_id: str,
        description: str,
        involved_characters: Optional[list[str]] = None,
        event_type: Optional[str] = None,
    ) -> EventRecord:
        """添加新事件。自动分配 event_id（evt_NNN）。"""
        description = description.strip()[:50]
        if not description:
            raise ValueError("事件描述不能为空")

        # 事件归并：如果与已有事件描述相似度高，不创建新事件
        existing = self._find_similar_event(description)
        if existing is not None:
            if segment_id and segment_id not in [e.segment_id for e in self.events if e.event_id == existing.event_id]:
                existing.segment_id = segment_id  # 更新为最近出现段
            if involved_characters:
                for c in involved_characters:
                    if c not in existing.involved_characters:
                        existing.involved_characters.append(c)
            self._touch()
            return existing

        self._event_counter += 1
        event_id = f"evt_{self._event_counter:03d}"
        rec = EventRecord(
            event_id=event_id,
            description=description,
            segment_id=segment_id,
            involved_characters=involved_characters or [],
            event_type=event_type,
            status="open",
        )
        self.events.append(rec)

        # 关联人物的 related_events
        for c_name in (involved_characters or []):
            c_rec = self.get_character(c_name)
            if c_rec and event_id not in c_rec.related_events:
                c_rec.related_events.append(event_id)

        self._touch()
        return rec

    def _find_similar_event(self, description: str, threshold: float = 0.75) -> Optional[EventRecord]:
        """查找描述相似的已有事件（用于事件归并）。"""
        best = None
        best_score = 0.0
        for ev in self.events:
            score = SequenceMatcher(None, description, ev.description).ratio()
            if score > best_score and score >= threshold:
                best_score = score
                best = ev
        return best

    def close_event(self, event_id: str) -> bool:
        """标记事件为已结束。返回是否成功。"""
        for ev in self.events:
            if ev.event_id == event_id:
                ev.status = "closed"
                self._touch()
                return True
        return False

    def get_open_events(self) -> list[EventRecord]:
        """获取所有未结束的事件。"""
        return [ev for ev in self.events if ev.status == "open"]

    # ========================================================================
    # 从批注结果中提取信息（v3.13.0 规则版）
    # ========================================================================

    def update_from_annotation(
        self,
        segment_id: str,
        structure: Optional[dict] = None,
        emotion: Optional[dict] = None,
        craft: Optional[dict] = None,
        interpretation: Optional[dict] = None,
    ) -> dict:
        """
        从单段批注结果中提取新人物/事件，更新 Scratchpad。
        v3.13.0 规则版：
          - 人物：从 D19.target + D18.character 提取
          - 事件：从 D01 ∈ TRIGGER_EVENT_D01 的段提取（段摘要作为事件描述）
        返回更新摘要（新增人物数/新增事件数）。
        """
        new_chars = 0
        new_events = 0

        # 1. 从 emotion 层提取人物（D19.target）
        if emotion:
            d19 = emotion.get("D19_emotion_analysis") or emotion
            target = d19.get("target")
            if target and isinstance(target, str) and target.strip():
                target_name = target.strip()
                if not self.is_known_character(target_name):
                    # 检查是否为可能的别名
                    similar = self.find_similar_character(target_name)
                    if similar:
                        self.mark_pending_confirmation(similar.canonical_name, target_name)
                    else:
                        self.add_character(target_name, segment_id=segment_id)
                        new_chars += 1
                else:
                    rec = self.get_character(target_name)
                    if rec:
                        rec.last_segment = segment_id
                        rec.mention_count += 1

            # D19.secondary 中的 target
            secondary = d19.get("secondary") or []
            if isinstance(secondary, list):
                for sec in secondary:
                    if isinstance(sec, dict):
                        sec_target = sec.get("target")
                        if sec_target and isinstance(sec_target, str) and sec_target.strip():
                            if not self.is_known_character(sec_target.strip()):
                                similar = self.find_similar_character(sec_target.strip())
                                if similar:
                                    self.mark_pending_confirmation(similar.canonical_name, sec_target.strip())
                                else:
                                    self.add_character(sec_target.strip(), segment_id=segment_id)
                                    new_chars += 1

        # 2. 从 craft 层提取人物（D18.character）
        if craft:
            d18_list = craft.get("D18_character_voice") or []
            if isinstance(d18_list, list):
                for item in d18_list:
                    if isinstance(item, dict):
                        char_name = item.get("character")
                        if char_name and isinstance(char_name, str) and char_name.strip():
                            if not self.is_known_character(char_name.strip()):
                                similar = self.find_similar_character(char_name.strip())
                                if similar:
                                    self.mark_pending_confirmation(similar.canonical_name, char_name.strip())
                                else:
                                    self.add_character(char_name.strip(), segment_id=segment_id)
                                    new_chars += 1
                            else:
                                rec = self.get_character(char_name.strip())
                                if rec:
                                    rec.last_segment = segment_id
                                    rec.mention_count += 1

        # 2.5 v3.13.1 T-115 新增：从 structure 层提取人物（D10.speaker 对话说话者）
        if structure:
            d10 = structure.get("D10_dialogue") or structure.get("D10")
            if isinstance(d10, list):
                for item in d10:
                    if isinstance(item, dict):
                        speaker = item.get("speaker") or item.get("character")
                        if speaker and isinstance(speaker, str) and speaker.strip():
                            speaker_name = speaker.strip()
                            # 跳过纯代词（后续由代词回指处理）
                            if speaker_name in ("我", "你", "他", "她", "它", "我们", "你们", "他们", "她们"):
                                continue
                            if not self.is_known_character(speaker_name):
                                similar = self.find_similar_character(speaker_name)
                                if similar:
                                    self.mark_pending_confirmation(similar.canonical_name, speaker_name)
                                else:
                                    self.add_character(speaker_name, segment_id=segment_id)
                                    new_chars += 1
                            else:
                                rec = self.get_character(speaker_name)
                                if rec:
                                    rec.last_segment = segment_id
                                    rec.mention_count += 1

        # 2.6 v3.13.1 T-115 新增：代词回指处理（第一人称"我"绑定到第一个出现的主要人物）
        if structure or emotion:
            # 检测本段是否有第一人称代词"我"作为情感对象或说话者
            has_first_person = False
            if emotion:
                d19 = emotion.get("D19_emotion_analysis") or emotion
                target = d19.get("target")
                if target and isinstance(target, str) and target.strip() == "我":
                    has_first_person = True
            if structure and not has_first_person:
                d10 = structure.get("D10_dialogue") or structure.get("D10")
                if isinstance(d10, list):
                    for item in d10:
                        if isinstance(item, dict) and (item.get("speaker") == "我" or item.get("character") == "我"):
                            has_first_person = True
                            break

            if has_first_person and self.characters:
                # 找到第一个出现的主要人物（mention_count 最高或 first_segment 最早）
                protagonist = max(
                    self.characters.values(),
                    key=lambda r: (r.mention_count, -get_segment_index(r.first_segment) if r.first_segment else 0),
                    default=None,
                )
                if protagonist and "我" not in protagonist.aliases and "我" != protagonist.canonical_name:
                    protagonist.aliases.append("我")
                    if len(protagonist.aliases) > MAX_ALIASES_PER_CHARACTER:
                        protagonist.aliases = protagonist.aliases[:MAX_ALIASES_PER_CHARACTER]
                    protagonist.mention_count += 1
                    protagonist.last_segment = segment_id
                    self._touch()

        # 3. 从 structure 层提取事件（D01 ∈ 关键叙事段）
        if structure:
            d01 = structure.get("D01")
            if d01 in TRIGGER_EVENT_D01:
                # 生成事件描述：D01功能 + 段摘要（取 D04 情感或 D10 对话信息）
                d04 = structure.get("D04") or {}
                intensity = d04.get("intensity", 0)
                emotion_label = d04.get("core", "")
                desc_parts = [f"{d01}"]
                if emotion_label:
                    desc_parts.append(f"（{emotion_label}，强度{intensity}）")
                event_desc = "".join(desc_parts)[:50]

                # 涉及人物：本段已知人物
                involved = [
                    rec.canonical_name
                    for rec in self.characters.values()
                    if rec.last_segment == segment_id or segment_id in [rec.first_segment, rec.last_segment]
                ]

                self.add_event(
                    segment_id=segment_id,
                    description=event_desc,
                    involved_characters=involved,
                    event_type=d01,
                )
                new_events += 1

        # 4. v3.13.1 T-115 增强：从 interpretation 层提取事件（D06 埋设-揭露 → 伏笔-回收事件对）
        if interpretation:
            d06 = interpretation.get("D06_information_control")
            if isinstance(d06, dict):
                d06_type = d06.get("type")
                if d06_type in ("埋设", "揭露"):
                    content = d06.get("content", "")[:30]
                    event_desc = f"信息{d06_type}：{content}"[:50]
                    event_id = self.add_event(
                        segment_id=segment_id,
                        description=event_desc,
                        event_type=f"信息{d06_type}",
                    )
                    new_events += 1

                    # v3.13.1 T-115 新增：伏笔-回收事件对关联
                    # 当检测到"揭露"时，查找之前最近的"埋设"事件，形成关联
                    if d06_type == "揭露" and event_id:
                        # 查找之前的埋设事件（按 segment_id 倒序找最近的）
                        previous_plant = None
                        for evt in reversed(self.events):
                            if evt.event_type == "信息埋设" and evt.segment_id != segment_id:
                                # 简单内容相似度判断（前10字符匹配）
                                if content[:10] and content[:10] in evt.description:
                                    previous_plant = evt
                                    break
                        if previous_plant is None:
                            # 没有内容匹配的，取最近一个埋设事件
                            for evt in reversed(self.events):
                                if evt.event_type == "信息埋设" and evt.segment_id != segment_id:
                                    previous_plant = evt
                                    break
                        if previous_plant:
                            # 关闭埋设事件（标记为已回收）
                            previous_plant.status = "closed"
                            # 在揭露事件描述中增加关联信息
                            current_evt = next((e for e in self.events if e.event_id == event_id), None)
                            if current_evt:
                                current_evt.description = f"{current_evt.description}（回收自{previous_plant.event_id}）"[:50]
                            self._touch()

        self.processed_segments += 1
        self._touch()
        return {"new_characters": new_chars, "new_events": new_events}

    # ========================================================================
    # 摘要生成（注入 Prompt 用）
    # ========================================================================

    def to_summary(self, current_segment_index: int = 0, max_characters: int = MAX_CHARACTERS_IN_SUMMARY) -> str:
        """
        生成注入 Prompt 的摘要文本（500-800 token）。
        格式：
          【便签本摘要 - 处理到第 N 段】
          已知人物：
          - 江洋（别名：我、灰鹰三号）：预备役中尉，泡防御技术员
          ...
          已知事件：
          - evt_001（seg_0001）：将军提出"陆沉预案"
          ...
          待确认：大猪/二猪 是否为同一人物？
        """
        lines = []
        lines.append(f"【便签本摘要 - 处理到第 {current_segment_index} 段】")

        # 已知人物（按 mention_count 降序，最多 max_characters）
        sorted_chars = sorted(
            self.characters.values(),
            key=lambda c: c.mention_count,
            reverse=True,
        )[:max_characters]

        if sorted_chars:
            lines.append("已知人物：")
            for rec in sorted_chars:
                alias_str = f"（别名：{'、'.join(rec.aliases[:5])}）" if rec.aliases else ""
                desc = rec.description or f"出场{rec.mention_count}次"
                lines.append(f"- {rec.canonical_name}{alias_str}：{desc}")

        # 已知事件（最近的 MAX_EVENTS_IN_SUMMARY 个）
        recent_events = self.events[-MAX_EVENTS_IN_SUMMARY:]
        if recent_events:
            lines.append("已知事件：")
            for ev in recent_events:
                type_str = f"[{ev.event_type}]" if ev.event_type else ""
                lines.append(f"- {ev.event_id}（{ev.segment_id}）{type_str}：{ev.description}")

        # 待确认项
        pending_items = []
        for rec in self.characters.values():
            for alias in rec.pending_confirmation:
                pending_items.append(f"{alias}/{rec.canonical_name} 是否为同一人物？")
        if pending_items:
            lines.append("待确认：" + "；".join(pending_items[:3]))

        summary = "\n".join(lines)

        # 长度控制：如果超过 MAX_SUMMARY_CHARS，截断人物列表
        if len(summary) > MAX_SUMMARY_CHARS and max_characters > 5:
            # 递归减少人物数量
            return self.to_summary(current_segment_index, max_characters=max(3, max_characters // 2))

        return summary

    # ========================================================================
    # 序列化
    # ========================================================================

    def to_json(self) -> str:
        """序列化为 JSON 字符串。"""
        data = {
            "schema_version": SCHEMA_VERSION,
            "doc_id": self.doc_id,
            "total_segments": self.total_segments,
            "processed_segments": self.processed_segments,
            "last_updated": self.last_updated,
            "characters": {k: v.to_dict() for k, v in self.characters.items()},
            "events": [ev.to_dict() for ev in self.events],
            "_event_counter": self._event_counter,
        }
        return json.dumps(data, ensure_ascii=False, indent=2)

    @classmethod
    def from_json(cls, json_str: str) -> "Scratchpad":
        """从 JSON 字符串反序列化。"""
        data = json.loads(json_str)
        pad = cls(
            doc_id=data.get("doc_id", ""),
            total_segments=data.get("total_segments", 0),
            processed_segments=data.get("processed_segments", 0),
            last_updated=data.get("last_updated", ""),
        )
        pad._event_counter = data.get("_event_counter", 0)
        for name, char_data in (data.get("characters") or {}).items():
            pad.characters[name] = CharacterRecord.from_dict(char_data)
        for ev_data in (data.get("events") or []):
            pad.events.append(EventRecord.from_dict(ev_data))
        return pad

    def save(self, path: str | Path) -> None:
        """保存到文件。"""
        Path(path).write_text(self.to_json(), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "Scratchpad":
        """从文件加载。"""
        return cls.from_json(Path(path).read_text(encoding="utf-8"))

    # ========================================================================
    # 内部方法
    # ========================================================================

    def _touch(self) -> None:
        """更新最后修改时间。"""
        self.last_updated = datetime.now().isoformat()

    def stats(self) -> dict:
        """返回统计信息。"""
        return {
            "doc_id": self.doc_id,
            "total_characters": len(self.characters),
            "total_events": len(self.events),
            "open_events": len(self.get_open_events()),
            "pending_confirmations": sum(len(c.pending_confirmation) for c in self.characters.values()),
            "processed_segments": self.processed_segments,
            "total_segments": self.total_segments,
        }


# ============================================================================
# CLI 冒烟测试
# ============================================================================

def _self_test() -> int:
    """自测试：验证数据结构和方法正常工作。"""
    print("=== Runtime Scratchpad 自测试 ===")
    failures = 0

    # 1. 创建空 Scratchpad
    pad = Scratchpad(doc_id="test_book", total_segments=10)
    assert pad.doc_id == "test_book"
    assert len(pad.characters) == 0
    assert len(pad.events) == 0
    print("[PASS] 1. 创建空 Scratchpad")

    # 2. 添加人物
    c1 = pad.add_character("江洋", aliases=["我"], first_segment="seg_0001", description="主角，预备役中尉")
    assert c1.canonical_name == "江洋"
    assert "我" in c1.aliases
    assert c1.mention_count == 0  # first_segment 不计数
    print("[PASS] 2. 添加人物")

    # 3. 更新人物（追加别名 + 计数）
    c1b = pad.add_character("江洋", aliases=["灰鹰三号"], segment_id="seg_0005")
    assert "灰鹰三号" in c1b.aliases
    assert c1b.mention_count == 1
    assert c1b.last_segment == "seg_0005"
    print("[PASS] 3. 更新人物（追加别名+计数）")

    # 4. 按别名查找
    found = pad.get_character("我")
    assert found is not None and found.canonical_name == "江洋"
    assert pad.is_known_character("灰鹰三号")
    assert not pad.is_known_character("不存在的人")
    print("[PASS] 4. 按别名查找")

    # 5. 添加事件
    e1 = pad.add_event("seg_0001", "将军提出陆沉预案", involved_characters=["江洋", "将军"], event_type="激励事件")
    assert e1.event_id == "evt_001"
    assert e1.status == "open"
    assert "江洋" in e1.involved_characters
    # 人物的 related_events 应关联
    c1_updated = pad.get_character("江洋")
    assert "evt_001" in c1_updated.related_events
    print("[PASS] 5. 添加事件（含人物关联）")

    # 6. 事件归并（相似描述不创建新事件）
    e2 = pad.add_event("seg_0002", "将军提出陆沉预案", involved_characters=["江洋"])
    assert e2.event_id == "evt_001"  # 归并为同一事件
    assert len(pad.events) == 1
    print("[PASS] 6. 事件归并（相似描述不创建新事件）")

    # 7. 关闭事件
    assert pad.close_event("evt_001")
    assert pad.events[0].status == "closed"
    assert len(pad.get_open_events()) == 0
    print("[PASS] 7. 关闭事件")

    # 8. 待确认别名
    pad.mark_pending_confirmation("江洋", "灰鹰")
    c1_check = pad.get_character("江洋")
    assert "灰鹰" in c1_check.pending_confirmation
    pad.confirm_alias("江洋", "灰鹰", is_same=True)
    assert "灰鹰" in c1_check.aliases
    assert "灰鹰" not in c1_check.pending_confirmation
    print("[PASS] 8. 待确认别名机制")

    # 9. 摘要生成
    summary = pad.to_summary(current_segment_index=5)
    assert "便签本摘要" in summary
    assert "江洋" in summary
    assert "evt_001" in summary
    assert len(summary) <= 2000  # 合理长度
    print(f"[PASS] 9. 摘要生成（{len(summary)} 字符）")

    # 10. JSON 序列化 round-trip
    json_str = pad.to_json()
    pad2 = Scratchpad.from_json(json_str)
    assert pad2.doc_id == pad.doc_id
    assert len(pad2.characters) == len(pad.characters)
    assert len(pad2.events) == len(pad.events)
    assert pad2.get_character("江洋").canonical_name == "江洋"
    print("[PASS] 10. JSON 序列化 round-trip")

    # 11. 从批注结果更新
    pad3 = Scratchpad(doc_id="test_anno", total_segments=3)
    structure = {"D01": "激励事件", "D04": {"core": "紧张", "intensity": 7}}
    emotion = {"D19_emotion_analysis": {"target": "林澜", "primary": {"emotion": "焦虑"}}}
    result = pad3.update_from_annotation("seg_0001", structure=structure, emotion=emotion)
    assert result["new_characters"] >= 1  # 林澜是新人物
    assert result["new_events"] >= 1  # 激励事件创建新事件
    assert pad3.is_known_character("林澜")
    print(f"[PASS] 11. 从批注结果更新（新人物{result['new_characters']}，新事件{result['new_events']}）")

    # 12. 统计信息
    stats = pad.stats()
    assert stats["total_characters"] >= 1
    assert stats["total_events"] >= 1
    print(f"[PASS] 12. 统计信息：{stats}")

    print(f"\n=== 自测试完成：12/12 PASS ===")
    return 0


def main():
    parser = argparse.ArgumentParser(description="Runtime Scratchpad（运行时便签本）v3.13.0")
    parser.add_argument("--self-test", action="store_true", help="运行自测试")
    parser.add_argument("--doc-id", help="文档 ID（用于 CLI 操作）")
    parser.add_argument("--load", help="从 JSON 文件加载 Scratchpad")
    parser.add_argument("--save", help="保存到 JSON 文件")
    parser.add_argument("--summary", action="store_true", help="打印摘要")
    parser.add_argument("--stats", action="store_true", help="打印统计信息")
    args = parser.parse_args()

    if args.self_test:
        sys.exit(_self_test())

    pad = None
    if args.load:
        pad = Scratchpad.load(args.load)
    elif args.doc_id:
        pad = Scratchpad(doc_id=args.doc_id)

    if pad is None:
        parser.print_help()
        sys.exit(1)

    if args.stats:
        print(json.dumps(pad.stats(), ensure_ascii=False, indent=2))

    if args.summary:
        print(pad.to_summary())

    if args.save:
        pad.save(args.save)
        print(f"已保存到 {args.save}")


if __name__ == "__main__":
    main()
