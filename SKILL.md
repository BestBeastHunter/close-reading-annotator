---
name: close-reading-annotator
version: 3.18.0
description: 对小说、剧本等叙事文本进行四层精读批注。输出结构层(叙事功能/情绪/节奏/视角/时空/对话功能/描写类型) + 阐释层(信息控制/主题/叙述者可靠性) + 情感层(角色情感/情感对象/段内情感弧，P4 触发式) + 文笔层(佳句/修辞/意象/词汇/句式/人物语言指纹) + 跨段层(伏笔链/段间关系)。支持断点续跑、层粒度重跑、引文子串校验、span 位置断言、craft层自动修复(v3.8.1)、三项校准功能(v3.8.2：quality_score/confidence/DLUT交叉验证)。适用于：小说精读、故事拆解、叙事分析、文笔拆解。不用于技术文档、论文、代码。
author: BestBeastHunter
license: MIT
---

# 四层精读批注 Skill v3.18.0

对叙事文本进行**四层结构化批注**（外加 L2.5 情感分析）：Layer 1「语义-结构层」、Layer 2「阐释-判断层」、Layer 2.5「情感分析层」（D19，P4 触发式）、Layer 3「文笔-语言层」、Layer 4「跨段-关系层」。批注之上叠加**全局聚合层**（v2.9/v3.0，`scripts/aggregation/`）：实体消解 → 场景图 → 角色弧线 → 故事类型推断 → 因果链/物件链 → 故事图合并 → 适配器输出。

**核心原则**：每段每层独立落盘 → 断点续跑 → Layer 4 二阶段执行 → 四层合并输出 → 聚合层拼图出全局叙事结构。

> **版本声明（决策 22：三版本域解耦）**：
> - **skill version** = `3.18.0`（本文件 frontmatter = README = RUNBOOK）。最近变更：v3.18.0 增强模块接入轮——①**计算文学模块接入正式流程**（Phase 2c 必须）：LumberChunker 重排（2b）产出 final_segments 后，run_pipeline 自动调 quant_analyzer.py 计算逐段量化指标（句长/TTR/词性/对话占比/标点/情感词频/五感密度）产出 quant_metrics.jsonl，Phase 3 批注须参考本段量化指标（设计依据：Backgrounds 计算文学分析模块.md——重排后、批注前、逐段独立、作为 LLM 批注硬证据）；②**事件分析补独立事件序列产物**（aggregation schema 3.6.0）：新脚本 scripts/aggregation/event_sequence.py 以运行时便签本 events 为主序（真实事件描述/参与者/类型/状态），对齐因果图（层级/显赫度/因果边）、场景图（场景归属）、结构层（D01/D08）、实体图（在场人物），输出 {doc_id}_event_sequence.json（按段序 + 核心/卫星/转折统计 + top 显赫度）；聚合层 12 脚本 → 13，报告新增事件序列章节（MD/HTML）；③README/RUNBOOK/aggregation-schema/version-history 同步。上一版本 v3.17.1：Phase 2a 口径明确——场景边界判断以 **Agent prompt 判断为主流程**（无需任何外部 API key），wrapper 降级为命令行自动化替代（非 Agent 环境用）。上一版本 v3.17.0：流程架构重构（Owner 指令：无任何可选步骤、全部必须、连续编号）——①run_pipeline 重构为连续 Phase 1–8：质量门+粗切→LumberChunker 精确切分（必须）→逐段批注（四层全量）→跨段→聚合层（12 脚本全跑，修复 --aggregation 死代码）→合并→校准（移到报告前）→报告（最后一步）；②聚合层由"可选但推荐"升级为必须，report 展示全部 12 模块（补 story_graph/adapters 渲染）；③Phase 3.5 LLM 精排（可选）移除、段采样分层从工作流移除（--plan 参数删除）、全量深度为唯一正式流程；④run_pipeline 集成质量门为 Phase 1a 硬门槛。上一版本 v3.16.4：《发条橙》产物审查修复轮（7 项）。**完整版本历史见 `references/version-history.md` 与文末「版本历史」表。**
> - **annotation schema_version** = `2.10.0`（真源 `references/schema.md` §一 = 批注 JSON `schema_version` = annotate_segment.py / examples/llm_wrapper.py）。v2.10.0 新增 5 个可选字段（D07._narrator_identity / D08._time_type / D08._narrative_level / D06._techniques / D12_narrative_mode），全部允许 null，旧产物零迁移。
> - **aggregation schema_version** = `3.6.0`（真源 `references/aggregation-schema.md` = `scripts/aggregation/*.py`）。v3.6.0 新增 event_sequence.json 产物（事件序列）。变更历史见文末「版本历史」表。
> - 校验器向后兼容 `schema_version: 2.5.0 / 2.6.0 / 2.7.0 / 2.8.0 / 2.9.0 / 2.10.0`（旧产物版本分支豁免，不迁移；v2.10.0 新增可选字段缺失时视为 null 放行）。
> - **枚举真源**：批注层 `references/schema.md`；聚合层 `references/aggregation-schema.md`（本文件速览 / validate_output.py / templates 均须同步）。**唯一例外**：D19 `emotion` 枚举（50 词）真源为 `references/emotion-lexicon.md`（决策 17 特批）。词表演化映射参考：`references/emotion-taxonomy.md`（DLUT 21 小类三级映射，ADR-013）。

---

## 0. 定位与两种运行模式（决策 18 修订）

| 模式 | 适用环境 | scripts/ 的角色 |
|:--|:--|:--|
| **A. Agentic 完整工作流** | IDE / 有代码执行能力的 Agent | **核心组件**：切分、校验、幂等落盘、checkpoint、合并、报告全依赖它。入口 `run_pipeline.py` 一条命令跑 Phase 1–8 |
| **B. 纯 LLM 手动降级** | 无工具、只把本文件当 system prompt | 仅限无代码环境：你手动分段、按本文件内联枚举逐段产 JSON，用户自己落盘（无法自动校验）。有工具时一律走 A |

> 完整工作流中 scripts/ **不是可选辅助**——没有它只能产出零散 JSON。纯 LLM 手动模式仍可用（枚举/锚点已内联，保证无工具也能产出合规 JSON），但自动化能力依赖 scripts/。

脚本全部零第三方依赖（纯 Python 3.8+ stdlib），跨平台。

---

## 1. 激活条件

**适用文本（v3.16.1 明确为中文定位）**：本 skill 面向**中文叙事文本**（含中文译本）。英文等其他语言的叙事文本请提供中文译本后再批注——锚点表、D19 词表、DLUT 词典、quality_gate 中文占比检测均按中文设计，对非中文文本不保证批注质量。

**触发**（用户说以下任一即可，指令语言不限中英，但文本须为中文）：
- 中文：「精读这段文本」/「拆解这个故事」/「分析这段的叙事」/「批注这段：xxx」/「做精读」/「精读+文笔拆解」/「拆伏笔链」
- 英文："close reading" / "annotate this narrative" / "close-read this segment" / "analyze craft"

**不触发**（礼貌拒绝）：
- 非中文叙事文本（请提供中文译本后再批注）
- 技术文档、论文、代码、API 文档、纯数据表格分析
- 纯诗歌体（提示维度覆盖可能不足，请确认）
- 单条片段字数 < 30 字（请用户提供更长上下文）

---

## 2. 内联校准锚点（纯 LLM 模式关键摘要；完整表见 references）

### D04 情绪强度锚点（真源 `references/emotion-anchors.md`）
| 强度 | 外显行为/文学描述对照（摘要） |
|:--:|:--|
| 1-3 | 他微微皱眉 / 她感到一丝不安 / 语气略带不满 / 环境描写微冷 |
| 4-6 | 他深吸一口气 / 她感到一阵失落 / 声音在发抖 / 眼眶微湿但忍住 |
| 7-8 | 他绝望地瘫坐 / 她歇斯底里地大笑 / 胸口像被重锤击中 / 失声呜咽 |
| 9-10 | 他撕心裂肺地嚎哭 / 感觉整个世界崩塌 / 血液凝固 / 万念俱灰的死志 |

### D05 叙事节奏锚点（真源 `references/pace-anchors.md`）
| 节奏 | 特征（摘要） |
|:--:|:--|
| 1 | 大段环境/心理描写，几乎没有动作推进，对话 ≤1 句或无 |
| 2 | 以描写+静态交互为主，小步信息推进 |
| **3** | 描写与动作交替，叙事平稳推进（基线） |
| 4 | 以动作和对话为主，事件进展快，切场景 |
| 5 | 主要是对话和快速动作，信息密度极高，句子短、频繁换行 |

---

## 3. 工作流（Phase 1–8）

> **⚠️ 开工前强制**：D04.core 只能从 v2.9.0 新 20 个枚举词里选（见 §4.1，2.8.0 及更早旧词仅旧产物合法），自造词被 validate 直接拒。按 Phase 顺序执行，**不允许跳过任何阶段**（v3.17.0 起本 skill 无任何可选步骤，全部阶段必须执行）。

### 0）统一入口：一条命令（决策 18 新增，v3.17.0 改为 Phase 1–8 全流程）

```bash
# 原文 → 报告，断点续跑；四层全量 × 全部 segment（无采样、无档级）
python scripts/run_pipeline.py --input <原文.txt> --doc-id <doc_id> \
    --output-dir <输出目录> \
    --llm-cmd "python 你的llm_wrapper.py" --report-format md

# 骨架模式（批注已就绪，只跑跨段→聚合→合并→校准→报告）
python scripts/run_pipeline.py --doc-id <doc_id> --output-dir <out> --phases 4,5,6,7,8
```

> **v3.17.0 流程架构**：`run_pipeline.py` 按连续编号 Phase 1–8 驱动全流程——①输入预处理（质量门+粗切）→②LumberChunker 场景语义精确切分（必须）→③逐段批注（四层全量）→④跨段分析→⑤聚合层（12 脚本全跑）→⑥合并→⑦后处理校准→⑧报告渲染（最后一步）。**没有可选阶段**：聚合层、校准、精确切分均为必须步骤。

### 3.1 Phase 1：输入预处理（质量门 + 粗切分）

**1a. 质量门（硬门槛，必须）**：

```bash
python scripts/quality_gate.py --input <原文文件路径> --out <输出目录>/<doc_id>_quality_report.json --fail-on-error
```

对原始文本做五维检测（中文占比/引号闭合/乱码/段落结构/重复性）。**fail 项必须修复后重跑**，不允许带病进入切分（否则后续批注全链路失真）。

**1b. 粗切分**：

```bash
python scripts/preprocess.py --input <原文文件路径> --doc-id <doc_id> --output-dir <输出目录>
```

**产出**：`{doc_id}_segments.jsonl`（segment_id / chapter / section_type / text_span / context_prev / context_next）+ `{doc_id}_checkpoint.json`。

**关键约束（v2.5 P0 修复）**：
1. 章节边界：支持「第X章」「Chapter X」「一二…单独成行（含行首空白）」「序章/楔子/尾声/后记/Prologue/Epilogue」
2. frontmatter 显式输出为 `section_type="frontmatter"` 的 seg（不丢弃、不截断）
3. 无章节边界：退化按段落+句子智能长度切分，**全书不截断**，打 `pollution_warning`
4. 每段 ≈2000 token；超长段落按句子边界子切
5. 每段前后 200 字符上下文锚点
6. `segment_id` = `{doc_id}_seg_{4位十进制}`（带 doc_id 前缀防多文档碰撞）
7. 坐标经 `_assert_text_slice_matches` 自校验（漂移=抛异常，不产出损坏数据）

**验证**：`python scripts/checkpoint.py status --doc-id <doc_id>`，total_segments 与 segments.jsonl 行数一致。

### 3.2 Phase 2：LumberChunker 场景语义精确切分（必须，v3.5 新增 / v3.17.0 升级为必须）

> **定位（必须步骤，不是可选）**：Phase 1 粗切分按章节+2000 token 机械切分，**可能导致一个 segment 包含多个场景/事件** → LLM 精读时被混淆（D01 叙事功能判断、D04 情绪强度、D19 情感分析都不知道该聚焦哪个场景）→ **批注精度下降**。
>
> 本阶段（LumberChunker）用 Agent 自身 LLM 做**场景边界判断**（只标记不切分），再由纯脚本 `reshape_segments.py` 按边界点从原文按字符位置重切，输出场景级 final_segments。**确保每个 segment 是一个语义/场景单元——这是批注精度的必要管道，v3.17.0 起为必须步骤，不允许跳过。**

**流程**：
```
Phase 1 粗切分（preprocess.py）→ Phase 2a 场景边界判断（Agent LLM / wrapper）→ Phase 2b 后处理重排（reshape_segments.py）→ Phase 3 精细批注（annotate_segment.py）
```

**Phase 2a：场景边界判断（输出 scene_boundary.json）**

> **主流程（Agent prompt 判断，无需任何外部 API key，v3.17.1 明确）**：Agent 自身即 LLM——本阶段与 Phase 3 逐段批注同构：按下方判断 Prompt 逐对判断相邻段（seg_N, seg_N+1）是否场景边界，收集结果写 `scene_boundary.json`，交给 Phase 2b 重排。**这是标准执行路径。**
>
> **替代方式（命令行自动化，非 Agent 环境）**：`examples/scene_boundary_wrapper.py` 用 OpenAI 兼容 API 批量判断，适合无 Agent 的纯命令行用户（需设 `SCENE_BOUNDARY_API_KEY`，可选 `SCENE_BOUNDARY_BASE_URL` / `SCENE_BOUNDARY_MODEL`），一行命令产出同样的 `scene_boundary.json`。Agent 工作流无需此脚本。

对每对相邻 segment（seg_N, seg_N+1），判断两者之间是否是**场景边界**。判断维度：
对每对相邻 segment（seg_N, seg_N+1），判断两者之间是否是**场景边界**。判断维度：

| 维度 | 边界信号 |
|------|---------|
| 地点变化 | 场景从 A 地转到 B 地（客厅→医院、地球→火星） |
| 时间跳跃 | 时间从 A 时刻跳到 B 时刻（白天→夜晚、童年→成年） |
| 视角切换 | 叙述视角从角色 A 转到角色 B，或第一人称↔第三人称 |
| 主题断裂 | 叙事主题/情绪基调发生明显转折（喜剧→悲剧、平静→紧张） |

**判断 Prompt（逐对执行，输出严格 JSON）**：

```
你是叙事场景边界检测专家。请判断以下两个相邻叙事段落之间是否存在"场景边界"（即两者是否属于同一个连续场景）。

【段落 N】{seg_N.text_span.text[:500]}

【段落 N+1】{seg_N+1.text_span.text[:500]}

判断维度（满足任一即视为场景边界）：
1. 地点变化：场景从一个地点转到另一个地点
2. 时间跳跃：时间发生明显跳跃（非连续流逝）
3. 视角切换：叙述视角或聚焦人物发生切换
4. 主题断裂：叙事主题或情绪基调发生明显转折

输出 JSON（严格格式，不要额外文字）：
{
  "between_segment": "{seg_N.segment_id}",
  "and_segment": "{seg_N+1.segment_id}",
  "is_scene_boundary": true/false,
  "boundary_type": "location_change" | "time_jump" | "pov_switch" | "thematic_break" | "continuous",
  "confidence": 0.0-1.0,
  "reason": "一句话说明判断依据（is_scene_boundary=false 时写'同一场景，连续叙事'）"
}
```

将所有判断结果收集为 `scene_boundary.json`：
```json
{
  "schema_version": "3.5.0",
  "document_id": "{doc_id}",
  "boundaries": [ {上述每个判断结果}, ... ]
}
```

> **注意**：只标记边界，不实际切分。章节边界（chapter 变化）由 reshape_segments.py 自动识别为场景边界，无需 LLM 判断。**即使不做 LLM 边界判断（如纯脚本环境），也必须执行 Phase 2b 用章节边界重排**——v3.17.0 起 reshape 本身是必须步骤。

**Phase 2b：后处理重排（纯脚本 reshape_segments.py，必须）**

```bash
python scripts/reshape_segments.py \
  --segments <out>/{doc_id}_segments.jsonl \
  --boundaries <out>/{doc_id}_scene_boundary.json \
  --original <原文文件路径> \
  --doc-id <doc_id> \
  --output-dir <out>/
```

**产出**：
- `{doc_id}_final_segments.jsonl`——场景级 segments（segment_id=`{doc_id}_scene_{NNN}`，含 `merged_from_count` 标记合并了多少粗切段）
- `{doc_id}_segment_id_mapping.json`——新旧 ID 映射表（哪些粗切 segment 合并成了哪个场景 segment，含字符区间）

**重排规则**（优先级从高到低）：
1. 章节边界（chapter/section_type 变化）→ 自动场景边界
2. scene_boundary.json 中 `is_scene_boundary=true` → 场景边界
3. 其余相邻段 → 合并到同一场景（默认连续）

**关键特性**：
- 按 `start_char`/`end_char` 从原文重新截取文本（坐标自校验，漂移=警告）
- 场景级 segment 是"完整场景段落"但不一定是"语义原子"（场景内可有多个叙事单元，靠 Phase 3 LLM 自己识别）
- 新旧 ID 映射保证下游可追溯（批注产物中的 segment_id 可用映射表回溯到原始粗切段）

**Phase 2c：计算文学分析（纯脚本 quant_analyzer.py，必须，v3.18.0 接入）**

```bash
python scripts/quant_analyzer.py --segments <out>/{doc_id}_final_segments.jsonl --out <out>/{doc_id}_quant_metrics.jsonl
```

> **定位（必须步骤）**：为每个场景级 segment 计算量化指标——句长/词汇丰富度（TTR）/词性占比/对话占比/标点密度/情感词频（DLUT 子集）/五感密度，产出 `{doc_id}_quant_metrics.jsonl`（与 final_segments 逐段对齐）。**这些指标是 Phase 3 批注的量化硬证据**：节奏判断（D05）参考 avg_sentence_length/标点密度，文笔层（D13-D17）参考 TTR/词性占比，对话判断（D10）参考 dialogue_ratio，情感判断（D19）参考 emotion_scores。jieba 可选（缺失自动降级为 DLUT 最大正向匹配，产物 tokenizer 字段显式标记模式）。run_pipeline 在 Phase 2b 后自动执行，不允许跳过。

**Phase 3 使用重排结果与量化证据**：将 `annotate_segment.py` 的 `--segments` 参数指向 `{doc_id}_final_segments.jsonl` 即可（run_pipeline 自动切换）；批注每一段前读取 `{doc_id}_quant_metrics.jsonl` 中对应 segment_id 的指标作为判断依据。

### 3.3 Phase 3：逐段批注（核心循环，四层全量 × 全部 segment）

> **v3.17.0 纪律**：对全部 segment 执行全部四层（structure / interpretation / emotion / craft）批注，**无采样、无档级、无跳过**。P4 情感触发纪律见 §3.7。
>
> **v3.18.0 纪律**：批注每一段前必须读取 Phase 2c 产出的 `quant_metrics.jsonl` 中该段量化指标（句长/TTR/词性占比/对话占比/标点密度/情感词频/五感密度）作为判断的硬证据——D05 节奏参考句长与标点、D10 对话参考 dialogue_ratio、D13-D17 文笔参考 TTR 与词性、D19 情感参考 emotion_scores。

**Runtime Scratchpad（运行时便签本，v3.13.0）**：Agent 在批注过程中自主维护的轻量级工作记忆区，提升指称一致性（见下文）。

对每段每层：**独立调用、独立校验、独立落盘**。层文件：`{doc_id}_{structure|interpretation|craft|emotion}.jsonl`。

```bash
# ① 单段手动模式：脚本打印 LLM 输入 → 输出 JSON 粘贴回去
python scripts/annotate_segment.py --segments <out>/{doc_id}_segments.jsonl \
    --doc-id <doc_id> --segment <doc_id>_seg_0001 --layers structure --output-dir <out>

# ② 非交互注入（Agent 自备批注 JSON → 校验/落盘/checkpoint 全自动）【决策 18 推荐】
python scripts/annotate_segment.py --segments <out>/{doc_id}_segments.jsonl \
    --doc-id <doc_id> --output-dir <out> --input-json <批注行.jsonl>

# ③ 全自动批量（外部 LLM wrapper；--all-pending 只处理未完成段）
python scripts/annotate_segment.py --segments <out>/{doc_id}_segments.jsonl \
    --doc-id <doc_id> --output-dir <out> --layers structure \
    --all-pending --llm-cmd "python 你的llm_wrapper.py"
```

`--layers` 组合：`structure` / `structure,interpretation` / `structure,interpretation,craft`；emotion 单独（P4 触发式，见 §3.7）。

**状态机（断点续跑）**：
- 完成一个 `(segment, layer)` → annotate_segment 自动调 `mark_layer_completed` 更新 checkpoint；再次运行自动跳过已完成（幂等续传）。
- 强制重跑：`--force`（层 JSONL 幂等 upsert，不产生重复行）；或 `python scripts/checkpoint.py reset-layer --doc-id <doc_id> --layer structure`（连带重置依赖它的下游阶段）。

**校验（annotate_segment 自动执行）**：校验失败 → **自动 span 修复并重试 ≤3 次**（craft 层 span 缺失/漂移自动回算，决策 18 兑现），仍失败则不写入 checkpoint 并显式退出。

**Runtime Scratchpad 细节**：

> **定位**：不是"缩小版聚合层"，而是"输入质量增强层"——为聚合层提供更干净的输入数据。

**工作机制**：
```
每段处理前：Scratchpad 摘要（已知人物/事件）→ 注入 Prompt → LLM 批注更一致
每段处理后：从批注结果中提取新人物/事件 → 更新 Scratchpad
全书完成后：Scratchpad 作为额外输入 → 聚合层（entity_graph / character_biographies）
```

**数据结构**：
- `CharacterRecord`：canonical_name / aliases / first_segment / last_segment / description / mention_count / related_events
- `EventRecord`：event_id / description / segment_id / involved_characters / event_type / status
- `Scratchpad`：characters（dict）+ events（list）+ 元信息

**摘要注入格式**（500-800 token）：
```
【便签本摘要 - 处理到第 23 段】
已知人物：
- 江洋（别名：我、灰鹰三号）：预备役中尉，泡防御技术员
- 林澜（别名：林上尉）：协调员，江洋暗恋对象
已知事件：
- evt_001（seg_0001）：将军提出"陆沉预案"
待确认：大猪/二猪 是否为同一人物？
```

**CLI 参数**：`--scratchpad`（默认启用）/ `--no-scratchpad`。
**持久化**：独立文件 `{doc_id}_scratchpad.json` + checkpoint 快照 `scratchpad_snapshot`；断点续跑自动恢复。
**信息抽取规则**（v3.13.0 规则版）：人物从 D19.target（情感对象）+ D18.character 提取；事件从 D01 ∈ {激励事件/高潮/转折/下降行动/结局} 提取；别名编辑距离 ≥0.6 标记"待确认"注入 prompt 让 LLM 确认。

### 3.4 Phase 4：跨段分析（Layer 4，二阶段）

**⚠️ Layer 4 不能在逐片段中混跑**——需看到整本书 L1/L2 图景才能判伏笔-回收链。

```bash
python scripts/cross_segment.py --doc-id <doc_id> \
    --segments <out>/{doc_id}_segments.jsonl --structure <out>/{doc_id}_structure.jsonl \
    --interpretation <out>/{doc_id}_interpretation.jsonl --craft <out>/{doc_id}_craft.jsonl \
    --window-size 15 --overlap 3
```

**产出**：`{doc_id}_cross_segment.jsonl`（schema.md §六 L4）。每条 `cross_ref` 是**双引用**（segment_id + anchor_text，防漂移可重定位）。落地版为**启发式规则**（情绪突变=因果候选、视角切换=时序候选、D09 复用=呼应候选、D06 埋设-揭露=伏笔-回收候选），`_metadata.method = "rule_based_heuristic_v2_6"`。

**v2.6.0 行为**：`--preserve-curated`（默认开）保留人工/LLM 核验关系（`_source != "rule"`）不被规则重跑覆盖；完成后自动回写 `cross_segment_completed`；`anchor_text` 空白归一并可回算段内 span。

> **v3.17.0 说明**：此前的"Phase 3.5 LLM 二分类精排（可选）"已**移除**——规则候选即最终跨段产物；需要更高精度的场景可在聚合层后自行叠加外部 LLM 后处理，不属于本 skill 的必须/可选流程。

### 3.5 Phase 5：聚合层（必须，v3.17.0 升级）——批注 → 全局叙事结构

> **定位（必须，不是可选）**：批注管"逐段信号"，聚合管"全书拼图"。聚合层把 L1-L4 批注（+D19/D15/D18 细粒度信号）组装成全局叙事图，**全部 13 个脚本必须按依赖顺序执行**，产物全部进入 Phase 8 报告展示。纯规则零第三方依赖，全链路 <2s/本。

```bash
AGG=scripts/aggregation
# ① 实体消解（D19.target + D18.character + 人名 NER → entity_graph）
python $AGG/entity_resolution.py --segments <out>/{doc_id}_segments.jsonl --doc-id <doc_id> \
    --output-dir <out>/aggregation --emotion <out>/{doc_id}_emotion.jsonl \
    --craft <out>/{doc_id}_craft.jsonl --structure <out>/{doc_id}_structure.jsonl
# ② 人物关系网络（entity_graph + D19 情感对象 → character_network，v3.17.0 纳入必须链）
python $AGG/character_network.py --entity-graph <out>/aggregation/{doc_id}_entity_graph.json \
    --emotion <out>/{doc_id}_emotion.jsonl --craft <out>/{doc_id}_craft.jsonl \
    --doc-id <doc_id> --output-dir <out>/aggregation
# ③ 场景图（D08 时空 + D01 功能连续性合并段 → scene_graph）
python $AGG/scene_graph.py --segments <out>/{doc_id}_segments.jsonl --structure <out>/{doc_id}_structure.jsonl \
    --doc-id <doc_id> --output-dir <out>/aggregation --entity-graph <out>/aggregation/{doc_id}_entity_graph.json
# ④ 角色弧线（按实体聚合 D19/D04 情绪点 → character_arcs）
python $AGG/character_arcs.py --segments <out>/{doc_id}_segments.jsonl --structure <out>/{doc_id}_structure.jsonl \
    --emotion <out>/{doc_id}_emotion.jsonl --entity-graph <out>/aggregation/{doc_id}_entity_graph.json \
    --doc-id <doc_id> --output-dir <out>/aggregation
# ⑤ 故事类型推断（六维：题材/叙事风格/时间结构/情感曲线/节奏/读者体验 → story_metadata）
python $AGG/story_type_inference.py --segments <out>/{doc_id}_segments.jsonl --structure <out>/{doc_id}_structure.jsonl \
    --interpretation <out>/{doc_id}_interpretation.jsonl --emotion <out>/{doc_id}_emotion.jsonl \
    --doc-id <doc_id> --output-dir <out>/aggregation
# ⑥ 叙事结构分析（弗雷塔格五幕+热奈特聚焦+叙事时间线+救猫咪节拍+叙事层级 → narrative_structure）
python $AGG/narrative_structure.py --structure <out>/{doc_id}_structure.jsonl \
    --doc-id <doc_id> --output-dir <out>/aggregation
# ⑦ 叙事技法分析（转场技巧+悬念设置+蒙太奇手法+钩子类型 → writing_techniques）
python $AGG/writing_techniques.py --structure <out>/{doc_id}_structure.jsonl \
    --interpretation <out>/{doc_id}_interpretation.jsonl \
    --cross-segment <out>/{doc_id}_cross_segment.jsonl \
    --doc-id <doc_id> --output-dir <out>/aggregation
# ⑧ 因果链（cross_segment 关系 → CAUSE/ENABLE 边）
python $AGG/causal_graph.py --cross-segment <out>/{doc_id}_cross_segment.jsonl --structure <out>/{doc_id}_structure.jsonl \
    --doc-id <doc_id> --output-dir <out>/aggregation
# ⑨ 事件序列（scratchpad 事件 + 因果图/场景图/实体图对齐 → event_sequence.json，v3.18.0 新增）
python $AGG/event_sequence.py --segments <out>/{doc_id}_segments.jsonl --structure <out>/{doc_id}_structure.jsonl \
    --scratchpad <out>/{doc_id}_scratchpad.json \
    --causal-graph <out>/aggregation/{doc_id}_causal_graph.json \
    --scene-graph <out>/aggregation/{doc_id}_scene_graph.json \
    --entity-graph <out>/aggregation/{doc_id}_entity_graph.json \
    --doc-id <doc_id> --output-dir <out>/aggregation
# ⑩ 物件链（D15 意象聚类 → object_chains）
python $AGG/object_chains.py --craft <out>/{doc_id}_craft.jsonl --doc-id <doc_id> --output-dir <out>/aggregation \
    --include-all-types
# ⑪ 人物传记（按人物聚合时间线/关键时刻/关系/情感弧/金句 → character_biographies）
python $AGG/character_biographies.py --segments <out>/{doc_id}_segments.jsonl \
    --structure <out>/{doc_id}_structure.jsonl --interpretation <out>/{doc_id}_interpretation.jsonl \
    --craft <out>/{doc_id}_craft.jsonl --emotion <out>/{doc_id}_emotion.jsonl \
    --cross-segment <out>/{doc_id}_cross_segment.jsonl \
    --entity-graph <out>/aggregation/{doc_id}_entity_graph.json \
    --character-arcs <out>/aggregation/{doc_id}_character_arcs.json \
    --character-network <out>/aggregation/{doc_id}_character_network.json \
    --narrative-structure <out>/aggregation/{doc_id}_narrative_structure.json \
    --doc-id <doc_id> --output-dir <out>/aggregation
# ⑫ 故事图合并（全子图谱 + story_metadata → story_graph.json）
python $AGG/story_graph.py --aggregation-dir <out>/aggregation --doc-id <doc_id> --output-dir <out>/aggregation
# ⑬ 适配器（story_graph → text2story / YARN / NCP 三种叙事格式）
python $AGG/adapters.py --story-graph <out>/aggregation/{doc_id}_story_graph.json \
    --doc-id <doc_id> --output-dir <out>/aggregation --formats text2story,yarn,ncp
```

**产物依赖链**：①→②（人物网络依赖实体图）→③④⑤⑥（依赖批注层 + 实体图）→⑦⑧（依赖批注层 + cross_segment）→⑨（事件序列，依赖因果图/场景图/实体图/scratchpad）→⑩（物件链，依赖 craft）→⑪（人物传记，依赖①-⑩ 产物）→⑫（故事图，依赖全部子图谱）→⑬（适配器，依赖故事图）。失败/缺输入时各脚本自行报错退出，可逐脚本重跑（覆盖写，幂等）。**run_pipeline Phase 5 按此顺序自动全跑。**

**聚合层 Schema 唯一真源**：`references/aggregation-schema.md`（决策 22）。改字段先改该文件再改脚本。
**v3.0.1 修复摘要**（决策 22）：adapters 字段名对齐上游真实字段、entity_resolution 输出 `segment_ids` 完整段集合、全脚本 `sorted(set(...))` 确定性、题材词表去书名化。

### 3.6 Phase 6：合并

```bash
python scripts/merge_layers.py --doc-id <doc_id> --segments <out>/{doc_id}_segments.jsonl
# 产出 {doc_id}_merged.jsonl：同段 L1/L2/L2.5/L3 + cross_refs 投影嵌套（schema.md §六 Merged）
```

### 3.7 Phase 7：P4 情感分析 + 后处理校准（必须）

> **v3.17.0 顺序**：P4 情感 Pass 是 Phase 3 批注的一部分（emotion 层按触发纪律产出）；Phase 7 校准是**必须的后处理**，位于**报告之前**——校准结果回写后，报告展示校准后的批注。

**P4 情感分析 Pass（Layer 2.5 · D19 · 触发式，属于 Phase 3）**：

**不是每个段都要做 D19**。判定不触发 → 登记 `emotion_skipped`（区别于"没批"）。

| # | P4 触发条件（任一命中即触发） | 依据（structure 层） |
|:--:|:--|:--|
| 1 | 本段情绪强度 ≥ 4 | `D04.intensity ≥ 4` |
| 2 | 本段为叙事关键段 | `D01 ∈ {激励事件, 上升行动, 高潮, 转折}` |
| 3 | 本段含对话 | `D10` 非 null |
| 4 | 用户显式要求深度情感分析 | 调用指令 |

```bash
# 手动模式：自动打印该段原文 + D01/D04/D10 判定上下文 + P4 纪律
python scripts/annotate_segment.py --segments <out>/{doc_id}_segments.jsonl \
    --doc-id <doc_id> --segment <doc_id>_seg_0091 --layers emotion --output-dir <out>
```

**关键纪律**：`emotion` 只能选自 `references/emotion-lexicon.md` 50 词（词表没有→选最接近词 + `expression.note` 说明，不造新词）；`target/trigger/arc` 无明确依据一律 null + 顶层 `null_reasons`，**禁止编造情感对象与情感弧**；`expression.key_phrases` 每项必须是原文子串（校验 error 级）。

**Phase 7 三项后处理校准（必须，位于报告之前）**：

| # | 校准脚本 | 功能 | 输出字段 |
|:--:|:---------|:-----|:---------|
| 1 | `scripts/calibrate_quality.py` | **quality_score 校准**——基于 Craft 层 D13-D17 的加权评分（D13佳句30% + D14修辞20% + D15意象20% + D16词汇15% + D17句式15%），评分公式=基础分40% + 数量分40% + 多样性分20%，计算每段 craft 层的文笔质量分（0-100） | craft 行新增 `_quality_score` + `_quality_breakdown` |
| 2 | `scripts/recalibrate_confidence.py` | **confidence 信号驱动重算**——基于 5 个确定性信号加权重算 confidence：①校验是否通过（30%）②必填字段完整性（25%）③引文匹配精度（20%）④枚举值合法性（15%）⑤跨层一致性（10%，D04 vs D19 极性/强度一致性） | 全部四层行的 `confidence.overall` 重算 + `confidence.confidence_method=recalibrated_v382` + `_recalibration_breakdown` |
| 3 | `scripts/cross_validate_emotion.py` | **DLUT 弱信号交叉验证**——基于 DLUT 子集（v3.3 已引入，9,924 词，随包分发）对 segment 原文做情感词频统计，计算 DLUT 推断的主导情感（褒义/贬义/中性），与 D19 主情感的 polarity 对比。DLUT 为弱信号，一致率 >70% 即达标 | emotion 行新增 `_baseline_emotion`（含 positive_count/negative_count/neutral_count/dominant_polarity/matched_words_sample/consistent_with_d19），保留原 D19 主情感 |

**执行命令（在产物目录下，doc_id 替换为实际值）**：

```bash
# 方式一：逐个执行（推荐，便于观察每步输出）
python scripts/calibrate_quality.py --dir <out_dir> --doc-id <doc_id> --in-place
python scripts/recalibrate_confidence.py --dir <out_dir> --doc-id <doc_id> --all-layers --in-place
python scripts/cross_validate_emotion.py --dir <out_dir> --doc-id <doc_id> --in-place

# 方式二：run_pipeline 自动执行（Phase 7，位于报告之前）
python scripts/run_pipeline.py --doc-id <doc_id> --input <raw.txt>
```

**金标准 20 部验证结果（v3.8.2）**：
- quality_score 分布合理：高分 61.6（手/猫/上海的狐步舞等文学质量高的作品）/ 中分 47.6（月牙儿）/ 基础分 44.6（其他 13 部）
- confidence emotion 层有 1-7 个唯一值（跨层一致性差异），craft 层 0.9-0.95
- DLUT 交叉验证平均一致率 **88.7%**（超过 70% 目标），14 部作品 100% 一致，最低 33.3%（为奴隶的母亲，DLUT 弱信号不考虑上下文语境，合理）

### 3.8 Phase 8：报告渲染（最后一步，必须）

> **v3.17.0 纪律**：报告是**最后一步**——聚合层（Phase 5）与校准（Phase 7）必须在报告之前完成；报告展示**全部四层批注 + 跨段关系 + 聚合层 13 模块**。

```bash
python scripts/render_report.py --doc-id <doc_id> --format md --agg-dir <out>/aggregation  # 或 html（默认）
# 产出 {doc_id}_report.md/.html：结构全景 + L2/L3 摘要 + L4 关系清单 + 聚合分析（故事概览/叙事结构/实体图谱/场景图/角色弧线/人物网络/因果图/事件序列/物件链/人物传记/叙事技法/故事图/适配器三格式）；零第三方依赖内联样式
```

---
## 4. 四层输出架构速览 + 最易错点

完整字段定义见 `references/schema.md` §六（**唯一真源**）。本节为速览 + 易错点 + 纯 LLM 模式必备枚举。

| 层 | 维度 | 必做/按需 | 落盘文件 |
|:-:|:----|:--------:|:--------|
| **L1 结构层** | D01 叙事功能 / D04 情绪基调 / D05 叙事节奏 / D07 叙事视角 / D08 时空标记 / D10 对话功能 / D11 描写类型 / **D12 叙事话语模式（v2.10.0 新增，可选）** | ✅ **必做**（D12 可选） | `{doc_id}_structure.jsonl` |
| **L2 阐释层** | D06 信息控制 / D09 主题标签(≤3) / narrator_reliability | ⚡ 按需 | `{doc_id}_interpretation.jsonl` |
| **L2.5 情感层** | D19（主情感/复合/对象/触发点/段内弧/表达）| ⚡ P4 触发式 | `{doc_id}_emotion.jsonl` |
| **L3 文笔层** | D13 佳句 / D14 修辞 / D15 意象 / D16 词汇 / D17 句式 / D18 语言指纹 | ⚡ 按需 | `{doc_id}_craft.jsonl` |
| **L4 跨段层** | 伏笔-回收 / 因果 / 时序 / 对比 / 呼应（双引用）| 🔁 二阶段整体一次 | `{doc_id}_cross_segment.jsonl` |

### 4.0 枚举值速查表（v3.15.0 重写，LLM 生成批注时一眼可查）

> **唯一真源**：`scripts/validate_output.py` 的枚举常量集（与 `references/schema.md` 严格一致）。本表为速查快照，改枚举先改 validator 再同步本表与 schema.md。
> **一致性自检**：`python scripts/check_enum_consistency.py` —— 自动比对 validator 常量集与本节速查表，0 不一致才允许发布。改枚举后必须重跑。

> ⚠️ **两套词表警告（高频踩坑）**：**D04.core（20 词）与 D19（50 词）是两套不同的词表**！`孤独` / `希望` / `压抑` / `屈辱` / `释然` 等**只在 D04**（段落氛围），**不在 D19**（角色/精细情感）。**D19 替代实操**：`屈辱`→`羞耻`/`绝望`；`压抑`→`隐忍`/`绝望`；`希望`→`期待`；`孤独`→`疏离`/`漂泊感`；`释然`→`宽慰`/`旷达`。（D19 缺词时选最接近词 + `expression.note` 说明，不造新词）精细情感）。写 D19 时用 D19 表，写 D04 时用 D04 表，混用会被校验器拒绝。

| 维度 | 字段 | 合法枚举值 |
|:----:|:----|:----------|
| **D01** | 叙事功能 | `背景铺垫` / `激励事件` / `上升行动` / `转折` / `高潮` / `下降行动` / `结局` / `过渡` / `复合功能` / `无法判断` |
| **D04.core** | 情绪基调（20词，v2.9.0） | `平静` / `压抑` / `焦虑` / `悲伤` / `愤怒` / `恐惧` / `喜悦` / `希望` / `绝望` / `孤独` / `信任` / `屈辱` / `嫉妒` / `复仇` / `悬疑` / `释然` / `羞耻` / `惊讶` / `渴望` / `厌恶` |
| **D04.polarity** | 极性 | `positive` / `negative` / `neutral` / `mixed` |
| **D06.type** | 信息控制 | `揭示` / `隐藏` / `误导` / `复合` |
| **D07.type** | 叙事视角 | `第一人称` / `第二人称` / `第三人称有限` / `第三人称全知` / `多视角` / `不可靠叙述者` / `客观叙事` |
| **D08._time_type** | 时间结构（v2.10.0 可选） | `linear` / `flashback` / `flashforward` / `analepsis` / `prolepsis` |
| **D10** | 对话功能 | `推动情节` / `揭示性格` / `传递信息` / `制造冲突` / `营造氛围` / `复合功能` |
| **D11** | 描写类型（非空数组） | `环境描写` / `心理描写` / `动作描写` / `外貌描写` / `感官描写` |
| **D13** | 佳句 | text+span；`quality_score` **范围 1-5**（v3.16.3 明确，勿写 6+）；reason 必填 |
| **D12.mode** | 叙事话语（v2.10.0 可选） | `场景` / `概述` / `停顿` / `省略` / `摘要` |
| **D14.type** | 修辞手法 | `比喻` / `拟人` / `排比` / `反讽` / `通感` / `夸张` / `对比` / `象征`（**对偶/设问属 D17 句式枚举**，勿填此处） |
| **D15.type** | 意象类型 | `自然意象` / `器物意象` / `人体意象` / `色彩意象` / `抽象意象` |
| **D16.pos** | 词汇词性 | `动词` / `形容词` / `副词` / `名词` |
| **D17.type** | 句式类型 | `排比` / `长短交替` / `倒装` / `独词句` / `对偶` / `设问` |
| **D19.primary** | 主情感（50词，v2.9.0，全表） | 基础层：`喜悦` / `悲伤` / `愤怒` / `恐惧` / `惊讶` / `期待` / `厌恶` / `信任` ｜ 文学扩展层：`依恋` / `眷恋` / `温情` / `甜蜜` / `哀恸` / `苍凉` / `怅惘` / `物哀` / `悲悯` / `怀旧` / `心碎` / `绝望` / `宽慰` / `安宁` / `旷达` / `释然` / `崇敬` / `敬畏` / `震撼` / `崇高感` / `荒诞感` / `漂泊感` / `隐忍` / `焦虑` / `恐慌` / `鄙夷` / `疏离` / `厌倦` / `冷漠` / `羞耻` / `渴望` / `嫉妒` / `迷茫` / `感动` / `得意` ｜ 复合词：`悲欣交集` / `爱恨交织` / `苦乐参半` ｜ 姿态复合词（表面笔调与底色情感冲突时）：`克制中的温情` / `冷峻中的悲悯` / `叙述性冷漠` / `反讽性平静` |
| **D19.polarity** | 情感极性 | `positive` / `negative` / `neutral` / `mixed` |
| **narrator_reliability** | 叙述者可靠性 | `可靠` / `部分不可靠` / `不可靠` / `无法判断` |
| **cross_segment.relation_type** | 跨段关系 | `伏笔-回收` / `因果` / `时序` / `对比` / `呼应` |

> **v3.8.1 自动修复**：craft 层（D13-D17）引文校验失败时，`annotate_segment.py` 默认开启 `--auto-fix`，自动调用 `span_locator.fuzzy_find_span` 做 4 级匹配（精确→空白归一→去标点→模糊相似度≥0.85），修正引文文本和 span 后重试。用 `--no-auto-fix` 可关闭。

### 4.1 Layer 1 易错点（必做）

| 维度 | 类型 | 关键约束 | 易错点 |
|:--:|:--|:--|:--|
| D01 | 枚举 | 背景铺垫/激励事件/上升行动/转折/高潮/下降行动/结局/过渡/复合功能/无法判断 | 自造词=报错 |
| D04 | 对象 | **core 从下方 v2.9.0 新 20 词选**；modifier 可 null；intensity 1-10 整数；**polarity 必填** ∈ positive/negative/neutral/mixed | `core:"敬仰"`=非法；漏 intensity/polarity=非法；2.9.0 产物写旧词（尊严/背叛/贪婪/宽恕）=非法 |
| D05 | 整数 | 1 / 2 / 3 / 4 / 5 | 小数/越界=报错 |
| D07 | 对象 | type ∈ 第一人称/第二人称/第三人称有限/第三人称全知/多视角/不可靠叙述者/客观叙事；**_narrator_identity（v2.10.0 可选）**：叙述者身份 ID（如 "narrator_001"），跨段追踪同一叙述者，无法判断时 null | is_switch_point 没前后文证据一律 false；_narrator_identity 不要写具体人名（应写 ID 或 null） |
| D08 | 对象 | time/space 均 string\|null；**_time_type（v2.10.0 可选）** ∈ linear/flashback/flashforward/analepsis/prolepsis；**_narrative_level（v2.10.0 可选）** ∈ "1"/"2"/"3+" | 子字段 null 不写 null_reasons（仅 D08 整体 null 才写）；_time_type 拿不准写 "linear"（默认线性）或 null |
| D10 | 枚举\|null | 推动情节/揭示性格/传递信息/制造冲突/营造氛围/复合功能 | 无对话=null + null_reasons.D10 |
| D11 | 数组 | 环境/心理/动作/外貌/感官描写（可多选 ≥1）| **严禁 null / 空数组**；纯议论段写 `["心理描写"]` 给低置信度 |
| **D12（v2.10.0 可选）** | 对象\|null | **mode** ∈ 场景/概述/停顿/省略/摘要（热奈特叙事话语）；**density** 0-1 数字或 null；**is_summary** bool；**is_scene** bool | 无法判断时整体 null（不写 null_reasons）；场景=对话+动作实时展示（density≈0.8-1.0），概述=压缩叙述（density≈0.3-0.6），省略=时间跳跃（density≈0），停顿=描写暂停（density≈0） |

**D04.core v2.9.0 新 20 枚举词（必须严格从中选 1）**：平静 / 压抑 / 焦虑 / 悲伤 / 愤怒 / 恐惧 / 喜悦 / 希望 / 绝望 / 孤独 / 信任 / 屈辱 / 嫉妒 / 复仇 / 悬疑 / 释然 / 羞耻 / 惊讶 / 渴望 / 厌恶
> **v2.9.0 手术（ADR-011）**：删 4 非情绪词（尊严=价值状态 / 背叛=事件关系 / 贪婪=动机特质 / 宽恕=行为美德）→ 补 4 中文文学高频情绪（羞耻 / 惊讶 / 渴望 / 厌恶）。2.8.0 及更早产物的旧词由校验器版本分支豁免，**新产物一律写新词表**。

**D04.polarity（必填）**：positive / negative / neutral / mixed，四值覆盖全部段落；多重情绪交织/反讽张力写 `mixed`；拿不准按 `references/emotion-anchors.md` 的 core→极性缺省映射兜底。极性由**文本语义**判断，不由文风/情节走向推导。

### 4.2 Layer 2 要点

- D06：`type ∈ {揭示/隐藏/误导/复合}`；**content 无引号时整体视为引文，必须是 `text_span.text` 子串**——不能自由概括、不能写相邻段原文（validate 无引号时整体校验，v3.15.0 T-137）；有引号时只校验引号内引文。**_techniques（v2.10.0 可选）**：信息控制具体技巧数组（可多选）——延迟揭示/选择性披露/视角遮蔽/不可靠叙述者误导/信息过载/误导性伏笔/悬念留白。
- D09：`string[] | null`，**≤3 个**（超=截断+报错）。
- narrator_reliability：可靠 / 部分不可靠 / 不可靠 / 无法判断。

### 4.3 Layer 2.5（D19）要点

定位：L2 语义扩展——D19 做角色/精细情感（50 词，v2.9.0 补 羞耻/渴望/嫉妒/迷茫/感动/得意），区别于 L1 D04 段落氛围摘要（20 词粗粒度）；同情绪都产出时**以 D19 为准**（决策 17）。

> **D04/D19 对照实操（v3.16.3 高频踩坑）**：D04 的 20 词（段落氛围）与 D19 的 50 词（角色情感）**不是子集关系**。常见错法：`屈辱`/`压抑`/`希望`/`孤独`/`释然` 在 D04 合法、**在 D19 非法**（validate 直接拒）。D19 写作时若词表没有目标情感，用**最接近词 + note 说明**：`屈辱`→`羞耻`；`压抑`→`隐忍`；`希望`→`期待`；`孤独`→`疏离`/`漂泊感`。

| 子字段 | 校验要点 |
|:--|:--|
| `primary`（必填）| emotion ∈ 50 词（emotion-lexicon.md 真源）；intensity 1-10；polarity ∈ 四值 |
| `secondary`（null 或 ≤2）| 已固化复合词（悲欣交集/爱恨交织/苦乐参半）直接作 primary，不拆 |
| `target/trigger/arc`（null-合法）| 非 null 时 name/description 必填；arc 仅真实位移才 `has_shift:true` |
| `expression`（必填）| `key_phrases` 每项过原文子串校验（error 级）|

### 4.4 Layer 3 要点（craft）

**所有条目必须带 `span: {start, end}` 段内相对偏移**（merge 自动换算全局偏移）。校验三层断言：子串命中 → span 边界合法 → 切片相似度 ≥95%。

| 维度 | 条目(text+span)附加字段 |
|:--|:--|
| D13 佳句 | reason, quality_score(1-5) |
| D14 修辞 | type ∈ {比喻/拟人/排比/反讽/通感/夸张/对比/象征}, detail |
| D15 意象 | type ∈ {自然/器物/人体/色彩/抽象意象}, cluster\|null |
| D16 词汇 | pos ∈ {动词/形容词/副词/名词}, reason, alternatives[] |
| D17 句式 | type ∈ {排比/长短交替/倒装/独词句/对偶/设问}, effect |
| D18 语言指纹 | character, pattern, occurrence_count；**span 可 null**（人物口癖天然跨段，引文可不在本段内=warning 级允许）|

### 4.5 Layer 4 要点

关系类型：伏笔-回收 / 因果 / 时序 / 对比 / 呼应。每条 cross_ref 的 source/target 必须同时带 segment_id + anchor_text。

### 4.6 引文与 span 校验（validate_output.py 核心）

1. 引文抽取：引号 `「」""《》` 包裹内容，或 Craft 条目 `text`。
2. 子串验证（归一化后）：`" ".join(quote.split())` 必须为 `" ".join(text_span.text.split())` 的子串，未命中 = error。D19.key_phrases **每一项**同规则。
3. span 位置断言：`0 ≤ start < end ≤ len(text)`；切片相似度 ≥95% 通过 / 85-95% warning / <85% error。
4. **span 自动修复**：annotate_segment 校验失败时 craft 条目 span 自动用 `text.find` 回算重试（≤3 轮）；存量文件回补用 `scripts/fill_spans.py`。
5. **引文预检（注入前自检）**：`python scripts/check_quotes.py --segments <segments.jsonl> <批注文件>`（支持 --layer-type/--fuzzy/--fail-fast）——批量注入前全量核对 D06/D19/craft 引文子串，失败直接打印「段 + 缺失短语」，避免注入时才发现整批被拒（v3.16.0 T-143 文档补全）。

### 4.7 置信度 + status 自动推导

- `confidence.overall ∈ [0,1]`；`confidence_method ∈ {model_self_report, consistency_check, human_review}`。
- **Structure 七维 `per_dimension` 必须填 0–1 数字**（即使主值 null 也表示「我确定没值」）；Interpretation/Craft 可 null。P4 触发段 `per_dimension.D19` 必填。
- status 对齐（`status != superseded` 时）：overall ≥0.8 → `confirmed`（打 tentative=warning）；<0.8 → `tentative`（打 confirmed=**error**）。

### 4.8 零填充预防纪律（v3.16.4 T-154）

> **来源**：《发条橙》50 段全量批注审查发现 D06 信息控制 0/50、D12 叙事话语 0/50、D17 句式 0/50、D01 激励事件 0/50——不是文本没有这些特征，而是引导不足导致 Agent 惯性填 null/空数组。以下维度**默认都要判断**，只有明确不适用才空/null + 理由：

| 维度 | 填充纪律 | 明确不适用才空/null 的判据 |
|:--|:--|:--|
| **D01** | 每段必填；**激励事件不限于全书第一段**——它是"打破主角生活平衡的触发事件"，可出现在任何位置（《月亮与六便士》的激励事件是第 7 段思特里克兰德出走；《发条橙》是亚历克斯在柯罗瓦奶吧决定去干一票的那段）。连续多段 `无法判断` 要警惕漏标 | 整段纯叙述衔接、无任何情节推进（罕见） |
| **D06** | L2 每段**必须判断**信息控制行为：作者本段是否在揭示/隐藏/误导/复合控制信息？没有 → null + null_reasons 写明"纯直陈段无信息控制" | 只有完全直陈、零信息差时才 null |
| **D12** | 每段都判断叙事话语模式：场景（对话+动作实时展示）/ 概述（压缩叙述）/ 停顿（描写暂停）/ 省略（时间跳跃）/ 摘要。中文叙事几乎每段可判，不确定先选最接近的 | 仅当四种模式都无法对应（极罕见）才 null |
| **D17** | 每段检测句式特征：排比 / 长短交替 / 倒装 / 独词句 / 对偶 / 设问。中文文本高频出现对偶/设问/长短交替，**D14 修辞里的"对偶/设问"要写到这里**（D14 只有比喻/拟人/排比/反讽/通感/夸张/对比/象征） | 整段无显著句式特征才空数组 |

> **实操提示**：D06 的 `content` 无引号时整体视为引文（必须是本段原文子串）——填充时直接抄本段关键句，不要自由概括，也不要引用相邻段。

---

## 5. 质量约束（每条都必须满足）

| 约束 | 含义 | 不满足怎么办 |
|------|------|------------|
| **先验证再声称** | 声称「Phase N 完成」前 validate/checkpoint 必须通过 | 校验不通过=不写 checkpoint+自动修复重试≤3 次，失败显式退出 |
| **客观性（L1 D08/D10/D11）** | 仅基于字面明确信息 | 信息不足写 null + null_reasons |
| **完整性** | 必填层所有键有效值或 null+理由 | 缺键=validate 直接报错 |
| **多义性承载** | 两种以上合理解读，主值取最信一个，其余写 alternatives | 不要在主值上纠结 |
| **锚点对齐** | D04/D05 对齐内联/完整锚点 | 强度错位 ≥2 档 → overall 置信度 ≤0.7 |
| **引文必真源** | L2/L3/L2.5 引用文本必须是原文子串 + span 对得上 | validate 引文校验=硬 fail |
| **版权合规** | text_span.text 只能携带公版/授权/用户自有内容 | 训练数据入库先跑 `scripts/export_dataset.py` 脱敏 |

---

## 6. 批注深度（全量深度为默认，v3.16.1 修正）

**本 skill 的正式流程 = 对全部 segment 执行四层全量深度批注**（structure / interpretation / emotion / craft）+ 跨段 + 聚合 + 合并 + 校准 + 报告。全量深度是唯一正式档位——每一段都执行同等深度的四层分析，**无采样、无档级、无任何可选步骤**（v3.17.0）。

> v3.17.0 起 `select_segments.py` 段采样脚本从工作流中移除（不再有 §3.6 章节、不再有 `--plan` 参数）。脚本文件保留但**不属于正式流程**；任何标准执行都不得使用采样。

---

## 7. 落盘约定与产物隔离

运行时批注产物**严禁写入 `examples/` 或 skill 包内任何目录**（污染分发包）。统一放调用方工作区输出目录（如 `<调用方>/outputs/annotations/<doc_id>/`），7 个文件 + checkpoint + report 聚在一起；JSONL 每行一条、增量追加、断点不丢。`examples/` 仅放打包输入样例。

---

## 8. 参考文档索引（按需查阅）

> ⚠️ 枚举只认 `references/schema.md`；SKILL.md / validate_output.py / templates 是副本。改枚举 = 先改 schema.md 再同步三者。

| 文档 | 位置 | 何时读 |
|------|------|------|
| **Agent 最小操作契约（CLI 速查 + 校验错误修复表）** | `docs/RUNBOOK.md` | 每个新运行者（尤其 Agent）开始前必读；比本文件更短 |
| **四层 Schema 完整定义（唯一真源）** | `references/schema.md` | 写 D01/D04/D07/D10/D11/关系类型 等不确定时 |
| **聚合层 Schema 完整定义（唯一真源）** | `references/aggregation-schema.md` | 跑/改 `scripts/aggregation/` 13 脚本或消费聚合产物前 |
| **Few-shot 完整批注示例** | `references/annotation-examples.md` | 开始批注前看 1–2 条找感觉 |
| **情绪校准锚点完整表** | `references/emotion-anchors.md` | 情绪强度犹豫时 |
| **D19 情感词表（50 词，枚举真源）** | `references/emotion-lexicon.md` | 跑 P4/D19 前必读 |
| **D01 叙事功能判别锚点（每词 2 示例 + 边界判定表）** | `references/function-anchors.md` | 写 D01 前必读（v3.1 新增，Freytag 五幕 + Labov 六要素） |
| **节奏校准锚点完整表** | `references/pace-anchors.md` | 节奏犹豫时 |
| **每层输出模板（可直接填充）** | `templates/*-output.json` | 避免漏字段 |
| **数据质量看门狗（粗切前硬门槛）** | `scripts/quality_gate.py` | 对原始文本做五维检测（中文占比/引号闭合/乱码/段落结构/重复性），产出 quality_report.json；**粗切分前必须跑一遍**，fail 项需修复后再进入 preprocess（v3.4 新增） |
| **计算文学分析（逐 segment 量化指标）** | `scripts/quant_analyzer.py` | **Phase 2c 必须步骤（v3.18.0 接入）**：重排后、批注前逐 segment 计算句长/TTR/词性/对话占比/标点/情感词频（DLUT 子集）/五感密度，产出 quant_metrics.jsonl，作为 LLM 批注的硬证据注入；jieba 可选，缺失自动降级（v3.4 新增，v3.18.0 编入 run_pipeline Phase 2c） |
| **事件序列聚合（全书事件表）** | `scripts/aggregation/event_sequence.py` | Phase 5 ⑨（必须，v3.18.0 新增）：以 scratchpad.events 为主序，对齐因果图（层级/显赫度/因果边）、场景图、结构层（D01/D08）、实体图（在场人物），输出 event_sequence.json（按段序 + 核心/卫星/转折统计） |
| **场景语义精确切分重排（场景级 segments）** | `scripts/reshape_segments.py` | Phase 2b（必须）：读粗切 segments + scene_boundary.json（Agent 场景边界判断）+ 原始文本 → final_segments.jsonl（场景级，scene_NNN 编号）+ 新旧 ID 映射表；按字符区间从原文重切，章节边界自动识别（v3.5 新增，v3.17.0 升级为必须） |
| **版本历史完整明细（3.9.0 及更早）** | `references/version-history.md` | 查历史版本变更/ADR 关联时 |
| **同义词归一化器（自由词→枚举词保守映射）** | `scripts/term_normalizer.py` | 批量落盘前跑一遍纠偏（v3.1 新增） |
| **词表演化工具（DLUT/NRC 对照 + 经验回写）** | `scripts/lexicon_crosscheck.py` / `scripts/collect_lexicon_candidates.py` | **仅词表维护者（Owner）在词表演化时使用**；一般批注使用者开箱即用、无需下载任何外部数据——crosscheck 默认读仓库内 DLUT 清洗子集 `references/lexicon-dlut-subset.json`（v3.3 新增） |
| **DLUT 三级映射表（21 小类→8 基元→D19 词位）** | `references/emotion-taxonomy.md` | 词表演化归约裁决（v3.3 新增；emotion-lexicon §四.b 完整版） |
| **设计决策记录** | 工作区 `docs/design-decisions.md`（已移出 skill 包归档） | 想改架构前先读；本 skill 包内不再携带 |
| **架构说明 / 审计报告** | 工作区 `docs/architecture.md` / `docs/audit/v30-audit-report.md`（归档） | 深度排查时 |

---

## 9. 跨平台与快速安装

**脚本跨平台**（纯 stdlib，Windows/Linux/macOS 一致）。安装即复制整个目录到 IDE 的 skills 目录，各 IDE 具体路径见 `README.md`「安装」节；纯手动模式可直接把本文件当 system prompt 喂任意大模型。

---

## 10. 版本历史

> **完整版本历史（3.9.0 及更早全部明细 + ADR 关联）已迁移至 `references/version-history.md`**。

**当前版本 3.18.0**——最近变更见文件头版本声明块。近期版本摘要：

| 版本 | 日期 | 变化摘要 |
|------|------|------|
| **3.18.0** | 2026-09-07 | 增强模块接入：①计算文学模块接入正式流程（Phase 2c 必须，quant_analyzer 产出 quant_metrics.jsonl 作为批注量化硬证据）；②事件分析补独立事件序列产物（event_sequence.py 新脚本 + aggregation schema 3.6.0，聚合 12→13 脚本，报告新增事件序列章节） |
| **3.17.1** | 2026-09-07 | Phase 2a 口径明确：场景边界判断以 Agent prompt 判断为主流程（无需外部 API key），wrapper 降为命令行自动化替代（SKILL.md §3.2 / run_pipeline 报错指引 / README / RUNBOOK 同步） |
| **3.17.0** | 2026-09-07 | 流程架构重构（Owner 指令：无任何可选步骤、全部必须、连续编号）：①run_pipeline 重构为连续 Phase 1–8（质量门+粗切→LumberChunker 精确切分必须→四层全量批注→跨段→聚合 12 脚本→合并→校准→报告最后一步）；②聚合层由"可选但推荐"升级为必须 + report 补 story_graph/adapters 渲染（12 模块全显示）；③Phase 3.5 精排/段采样分层/--plan 移除，全量深度唯一；④质量门集成 Phase 1a |
| **3.16.4** | 2026-09-07 | 《发条橙》产物审查 7 项修复（T-150~T-155）：①story_type 视角判定收紧（frontmatter 过滤+真实视角种类+0.7/0.1 阈值，修复 84% 第一人称误判多视角叙事）；②narrative_structure 激励事件容错（无 D01 激励事件时从首个高潮前强功能段逆查推断+derived 标记）；③preprocess 代序/引论边界降级（强正文章节前中文序列小节并入 frontmatter）+ 第X部/卷/Part 章节模式；④render_report 场景图/叙事技法真实字段渲染+MD Layer 3 文笔层摘要+--output-dir 目录语义；⑤SKILL.md 零填充预防纪律（D01/D06/D12/D17）+ annotation-examples 补 D12/D17 示例；⑥scratchpad 抽象物词表提升模块级并与 entity_resolution 39 词同源+schema.md D19.target 语义边界 |
| **3.16.1** | 2026-09-07 | 发布前逐文件总检（T-144/T-145）：聚合脚本 D19.target 同型 bug 修复、文档版本三域统一、全量深度批注为唯一正式档位 |
| **3.16.0** | 2026-09-07 | T-143：cross_segment 增强信号落盘修复（v3.8.7 遗留） |
| **3.15.x** | 2026-09-07 | T-128/T-129：输出参数统一 --output-dir、枚举真源 14 维统一、确定性错误直败、报错去重 |
| **3.14.1** | 2026-09-06 | T-123：Scratchpad items 物品表 + object_chains 集成 |
| **3.13.x** | 2026-09-06 | Runtime Scratchpad（ADR-029）：LLM 描述工具/代词消解/待确认机制/事件显赫度评分 |
| **3.12.0** | 2026-09-06 | Phase 1.5 场景语义切分 wrapper（LumberChunker Skill 化） |

> **版本号语义（决策 22 解耦后）**：skill version SemVer 主版本=能力不兼容；次版本=新增能力；修订号=修复轮。**annotation schema_version** 独立演进（当前 2.10.0）。**aggregation schema_version** 独立演进（当前 3.5.0）。三域解耦，互相不阻塞升版。

---

*精读批注 Skill v3.3.0 — "先验证，再声称；每段每层落盘；二阶段跨段；四层合一，情感入轨；全局聚合，图谱拼图。从『规格正确』走向『实现可运行』。"*

