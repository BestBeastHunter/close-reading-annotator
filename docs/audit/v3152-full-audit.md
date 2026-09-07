# v3.15.2 全面代码审计报告（HEAD=403eee6，带《活着》真实产物）

- 审计人：A-DOUBAO（MainAgent 执行）
- 审计对象：`skills/close-reading-annotator` 仓库 HEAD `403eee6`（v3.15.2），scripts/ 全部 39 个 py + SKILL/RUNBOOK/references/templates + 《活着》真实产物（examples\活着\，48 段四层 + 聚合层）
- 审计方法：`doubao-coding-analyze-codebase`（调用链/数据契约摸底）→ `doubao-coding-diagnose-and-fix-bugs`（缺陷分类）→ **当前 HEAD 代码 + 《活着》真实产物重跑验证**（防止"合成数据与真实产物同构"假绿）
- 审计日期：2026-09-07

---

## 一、结论摘要

| 级别 | 数量 | 说明 |
|------|------|------|
| 🔴 P0（功能失效） | 1 | cross_segment 增强信号双重失效（死代码） |
| 🟠 P1（静默数据丢失） | 1 | causal_graph emotion_targets 类型判断错误 |
| 🟡 P2（防御/语义缺陷） | 2 | preprocess 兜底 is_polluted 语义矛盾；annotate 模式 A 缺 _pad_metadata |
| 🟢 P3（文档/交付） | 2 | check_quotes 文档缺失；发布包滞后于 HEAD |
| ✅ 复查通过 | 10+ | 上次审计遗留项全部核实已修 |

**总评**：v3.15 三个版本的修复质量高，上次 A-AUDIT 指出的 P0 类缺陷（键名不一致、Phase6 路径、枚举分裂）已全部闭环。本轮新发现的两个真缺陷均为**同型 bug 成簇**（上次教训验证：`D19.target` 类型假设在 scratchpad 修了、在 cross_segment/causal_graph 遗留）。

---

## 二、🔴 P0-1：cross_segment.py 增强信号规则双重失效（v3.12.0 功能完全无效）

### 位置
`scripts/cross_segment.py` L312-386（增强信号块）+ L286-310（final_refs/result 构建）+ L388（写盘）

### 缺陷①：追加到错误列表（结果永不落盘）
- L286-293 已用 `preserved + dedup` 构建 `final_refs` → L296-310 构建 `result`（`cross_refs: final_refs`）→ **L312-386 增强块才执行**，对 `refs.append(...)`（L353/L376）
- `refs` 在 L269-281 已被消费（去重成 `dedup`），追加对它**没有下游消费者**——`result` 不会更新，写盘（L388）的是不含增强信号的 `result`
- **v3.9.0 T-078 注释声称"追加到 refs（在 final_refs 去重之前）"，实际代码位置在 final_refs 构建之后**——修复不完整

### 缺陷②：D19.target 类型判断错误（即使①修了也不触发）
- L348：`target and isinstance(target, str) and len(target) <= 20`
- `validate_output.py` L471-481 规定 D19.target 是 **object**（`{name, entity_id, relation}`）——真实产物是 dict
- → D19.target 情感对象呼应信号**在两种批注格式下都不可能触发**

### 证据（当前 HEAD 重跑《活着》）
```
《活着》D15 意象多段复用：{雪:2, 羊:2, 眼泪:2, 月光:2}（应产生 ≥4 条 cf_d15 呼应候选）
重跑 cross_segment → 29 条，_source 全部 = rule，enhanced = []（0 条增强信号）
```
### 影响
- SKILL.md §3.4.5 宣称"规则候选（含 v3.12.0 新增的 D19.target 情感对象复用、D15 意象复用信号）"——**空头承诺**
- Phase 3.5 LLM 精排的输入少了一类高质量候选（情感对象/意象跨段呼应）

### 修复方案
把增强信号块移到 `final_refs` 去重（L293）**之前**，直接追加到 `refs`；D19.target 改为取 dict 的 `name`：

```python
# 在 L269 去重之前插入（读 emotion/craft 行 → 提取信号 → refs.append）
# target 兼容：dict → target.get("name")；str → 原样
```

---

## 三、🟠 P1-1：causal_graph.py emotion_targets 类型判断错误（静默丢数据）

### 位置
`scripts/aggregation/causal_graph.py` L191-193（build_segment_info_index 内）

### 缺陷
```python
targets = d19.get("target") or []
if isinstance(targets, list):   # ← 真实 D19.target 是 dict
    info_index[seg_id]["emotion_targets"] = [t.get("name") for t in targets ...]
```
- `validate_output.py` 规定 D19.target 是 object；`《活着》` 真实产物 target 为 `{"name": "...", "entity_id": null, "relation": null}`
- → `isinstance(targets, list)` 恒 False → `emotion_targets` 恒空 → `build_event_attributes` 的 participants 丢失"D19.target 情感对象"
- 与 scratchpad T-115 修复的是**同一型 bug**（同型成簇），scratchpad 已修、causal_graph 遗留

### 影响
聚合层 event_attributes.participants 少了情感对象维度（非崩溃，静默缺失）

### 修复方案
```python
targets = d19.get("target") or []
if isinstance(targets, dict):
    tgt = targets.get("name")
    if tgt:
        info_index[seg_id]["emotion_targets"] = [tgt]
elif isinstance(targets, list):
    info_index[seg_id]["emotion_targets"] = [t.get("name") for t in targets if isinstance(t, dict) and t.get("name")]
```

---

## 四、🟡 P2

### P2-1：preprocess.py 兜底切分 is_polluted 语义矛盾
- 位置：`scripts/preprocess.py` L577 / L598
- 兜底段 `"is_polluted": False` 但 `"pollution_warning": "v3.8.5兜底切分(章节边界识别不足)"`——有警告却标记未污染，字段语义冲突，误导下游（如按 is_polluted 过滤的实现）
- 修复：兜底段 `is_polluted` 应为 `True`

### P2-2：annotate_segment.py 模式 A（--all-pending + --llm-cmd）缺 _pad_metadata
- 位置：`scripts/annotate_segment.py` L580（模式 A）vs L640（模式 B）/ L699（模式 C）
- 模式 B/C 都对返回行调 `_pad_metadata(obj, seg)` 补 text_span/segment_id/schema_version；模式 A 直接 `_commit_after_validate`——若第三方 wrapper 未按协议输出 text_span，引文校验全挂且报错难懂
- 官方 examples/llm_wrapper.py 补了 text_span（协议注释也要求），故官方路径不受影响；属防御一致性缺陷
- 修复：模式 A 在 `_commit_after_validate` 前补 `_pad_metadata(obj, seg)`

---

## 五、🟢 P3

### P3-1：check_quotes.py 已实现但文档零引用
- 用户反馈 C4（引文预检工具）已落地：`scripts/check_quotes.py` 可运行（`check_quotes.py --segments <path> <input_file>`），含 --fuzzy/--fail-fast
- 但 SKILL.md / RUNBOOK.md / README.md **均无引用** → 使用者不知道有这个工具
- 修复：SKILL §Phase 2 或 RUNBOOK 补一行用法

### P3-2：发布包滞后于 HEAD（流程问题）
- 《活着》产物由**旧发布包**生成，证据：
  - `causal_graph.json` 的 `_metadata` 无 `degraded_notes` 键（当前 HEAD 有），note 为 v3.13.1 旧文案，`total_edges=0`（D01 关键段 34 段，旧版无降级路径）
  - 报告无"聚合分析"章节（当前 HEAD 重跑加载 8 个聚合模块 ✅）
- 当前 HEAD 重跑验证均正常：causal_graph 17 边（T-140 降级路径生效）、render_report 聚合 8 模块、scene_graph 43 场景
- 影响：使用者拿到的发布包 ≠ HEAD → v3.15.x 修复未生效
- 修复：重新打包发布（含 v3.15.0/1/2 全部修复）

---

## 六、上次审计遗留项复查（全部通过 ✅）

| 上次问题 | 现状 | 证据 |
|---------|------|------|
| D13_notable_lines vs golden_lines 键名分裂 | ✅ 全仓统一 golden_lines | calibrate/recalibrate/validate/span_locator 全一致 |
| recalibrate D07 枚举与 validate 不一致 | ✅ 已一致 | L47 `{第一人称,第二人称,第三人称有限,第三人称全知,多视角,不可靠叙述者,客观叙事}` |
| merge_layers craft 格式兼容 | ✅ 兼容 layers.craft + 顶层 | L124 `(c_row.get("craft") or (c_row.get("layers") or {}).get("craft"))` |
| cross_segment --output-dir 别名 | ✅ 双别名 + 目录自动拼文件名 | L146/L168-170 |
| cross_segment span 坐标漂移（T-068） | ✅ 原始文本截取 | L124-134 `raw_snippet = text[:snippet_len]` |
| quality_gate 英文引号重复计数（T-069） | ✅ 单独统计 | LEFT/RIGHT 仅中文引号 + english_quotes 单独计 |
| preprocess 兜底无法关闭 | ✅ --no-fallback | L422-423 |
| Phase6 路径假设（嵌套 vs 平铺） | ✅ 批量模式先探测 | calibrate/recalibrate 均含目录降级 |
| entity_resolution 局部 import json | ✅ 已删（模块级 import） | L319 直接用 json |
| scratchpad D19 dict target / D06 隐藏揭示 | ✅ 已修 | scratchpad.py L716+（T-115 修复） |
| character_arcs D13 归属过滤（T-141） | ✅ 仅含角色名金句计入 | L378 `if not (character_name in text): continue` |
| render_report 切分质量小节（T-134） | ✅ pollution 已入报告 | L355-358/775/981 |
| causal_graph 降级路径（T-140） | ✅ 当前 HEAD 17 边 | 重跑《活着》验证 |

---

## 七、修复优先级与建议

| 优先级 | 问题 | 工作量 |
|--------|------|--------|
| P0-1 | cross_segment 增强信号（追加位置 + target 类型） | ~0.5h |
| P1-1 | causal_graph emotion_targets 类型 | ~0.2h |
| P2-1 | preprocess is_polluted 语义 | ~0.1h |
| P2-2 | annotate 模式 A _pad_metadata | ~0.1h |
| P3-1 | check_quotes 文档补充 | ~0.1h |
| P3-2 | 发布包重打（含 v3.15.x） | ~0.2h |

**建议**：P0/P1 直接修复（死代码，无争议）；修复后用《活着》真实产物重跑 cross_segment + causal_graph 复验（增强信号 ≥4 条、emotion_targets 非空）。

---

## 八、补充发现（审计过程中新增）

### P0-1 追加缺陷③：增强信号按输出目录硬编码定位产物（已一并修复）
- 增强信号块原实现从 `out_path.parent`（输出目录）找 `{doc_id}_emotion.jsonl` / `{doc_id}_craft.jsonl`——独立调用 cross_segment（--output-dir 与输入产物不同目录）时找不到文件，增强信号静默为空
- 修复：emotion 按 `segments` 同目录定位；craft 优先用 `--craft` 显式传入，否则按 segments 同目录约定

### 修复记录（v3.16.0 T-143）
| # | 文件 | 修复 | 验证（《活着》真实产物重跑） |
|---|------|------|------|
| P0-1 | cross_segment.py | 增强块移到 final_refs 去重**之前**；D19.target dict 兼容（顶层取，非 primary）；路径按输入目录；preserve 条件改 `startswith("rule")` | 29 rule + **11 rule_enhanced**（凤霞×3/家珍×2/有庆×2 情感对象 + 雪/羊/眼泪/月光意象） |
| P1-1 | causal_graph.py | D19 取数兼容直接格式（`or emotion`）；target dict/list 双兼容 | participants 覆盖 9 角色（12/20 节点），含情感对象 |
| P2-1 | preprocess.py | 兜底段 is_polluted False→True（2 处） | 语义一致 |
| P2-2 | annotate_segment.py | 模式 A 补 `_pad_metadata` | 与模式 B/C 对齐 |
| P3-1 | SKILL.md | §4.6 补 check_quotes.py 用法 | 文档可发现 |

### 修复后遗留（发布层）
- **P3-2 发布包重打**：examples\活着\ 产物系旧发布包生成（causal_graph 0 边、报告无聚合）——需在下次打包时以 HEAD 全链路重跑回写，非代码缺陷
