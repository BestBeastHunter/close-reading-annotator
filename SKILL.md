---
name: close-reading-annotator
version: 3.14.1
description: 对小说、剧本等叙事文本进行四层精读批注。输出结构层(叙事功能/情绪/节奏/视角/时空/对话功能/描写类型) + 阐释层(信息控制/主题/叙述者可靠性) + 情感层(角色情感/情感对象/段内情感弧，P4 触发式) + 文笔层(佳句/修辞/意象/词汇/句式/人物语言指纹) + 跨段层(伏笔链/段间关系)。支持断点续跑、层粒度重跑、引文子串校验、span 位置断言、craft层自动修复(v3.8.1)、三项校准功能(v3.8.2：quality_score/confidence/DLUT交叉验证)。适用于：小说精读、故事拆解、叙事分析、文笔拆解。不用于技术文档、论文、代码。
author: BestBeastHunter
license: MIT
---

# 四层精读批注 Skill v3.14.1

对叙事文本进行**四层结构化批注**（外加 L2.5 情感分析）：Layer 1「语义-结构层」、Layer 2「阐释-判断层」、Layer 2.5「情感分析层」（D19，P4 触发式）、Layer 3「文笔-语言层」、Layer 4「跨段-关系层」。批注之上叠加**全局聚合层**（v2.9/v3.0，`scripts/aggregation/`）：实体消解 → 场景图 → 角色弧线 → 故事类型推断 → 因果链/物件链 → 故事图合并 → 适配器输出。

**核心原则**：每段每层独立落盘 → 断点续跑 → Layer 4 二阶段执行 → 四层合并输出 → 聚合层拼图出全局叙事结构。

> **版本声明（决策 22：三版本域解耦）**：
> - **skill version** = `3.14.1`（本文件 frontmatter = README = RUNBOOK）。v3.14.1 items 启用（T-123）：①scratchpad.py 新增 ItemRecord 类 + items 物品表 + add_item/get_item 方法 + to_json/from_json 处理 items；②update_from_annotation 从 D15 意象提取中抽取器物/人体/色彩意象物品；③object_chains.py 新增 --scratchpad 参数利用 Scratchpad 物品信息增强物件链分析。v3.14.0 聚合层增强 + P1级4项简化吸收。（本文件 frontmatter = README = RUNBOOK）。v3.14.0 聚合层增强 + P1级4项简化吸收（ADR-029，T-120~T-124）：①event_function（事件功能：开启/发展/高潮/收束）；②narrative_speed（叙事速度：场景/概述/省略/正常）；③actantial_role（行动元角色：主要行动者/辅助者/阻碍者）；④desire_structure（欲望结构：pursues/driven_by/opposed_by）；⑤聚合层利用Scratchpad（entity_resolution.py --scratchpad参数）。aggregation schema 3.4.0→3.5.0。v3.13.2 Scratchpad深度优化。（本文件 frontmatter = README = RUNBOOK）。v3.13.2 Scratchpad 深度优化（ADR-029，T-117/T-118）：①LLM 生成人物描述工具（update_description/generate_description_prompt/get_characters_needing_description）；②第三人称代词最近匹配指称消解（他/她/他们根据最近出现人物推断，标记为待确认）；③待确认项注入 prompt（v3.13.0 已实现）。v3.13.1 事件/人物分析增强（ADR-029，T-111~T-116）。v3.13.1 事件/人物分析增强（ADR-029，T-111/T-112/T-115）：①事件显赫度评分（salience_score=因果位置0.4+叙述篇幅0.3+重复频率0.3，核心/卫星事件分层）；②人物复杂度评分（complexity_score=性格特征数0.4+情感方差0.3+关系数0.3，扁平/圆形/尖形分类）；③人物厚度+能动性曲线+出现密度分布+对话主导权；④Scratchpad抽取质量优化（D10.speaker抽取+代词回指+D06伏笔-回收事件对+编辑距离别名匹配增强）。v3.13.0 Runtime Scratchpad（ADR-029，T-107~T-110）。v3.8.2 三项校准功能（ADR-017，T-042/T-043/T-044）：①quality_score 校准（基于 Craft 层 D13-D17 加权评分，基础分40%+数量分40%+多样性分20%）；②confidence 信号驱动重算（5信号加权：校验通过30%+字段完整性25%+引文精度20%+枚举合法性15%+跨层一致性10%，confidence_method=recalibrated_v382）；③DLUT 弱信号交叉验证（基于 DLUT 子集 9901 词对 segment 原文做情感词频统计，与 D19 主情感对比，双轨存储 _baseline_emotion 字段，平均一致率 88.7%）。v3.8.1 工程化加固（ADR-016，T-038/T-039/T-040）：span_locator 模糊匹配增强 + annotate_segment --auto-fix + SKILL.md 枚举值速查表。v3.8 叙事技法分析（ADR-014，T-037）；v3.7 叙事结构分析（ADR-014，T-036）；v3.6 原子化扩展字段（ADR-014，T-035）；v3.5 精细化切分器/重排（ADR-014，T-034）；v3.4 前置双模块（ADR-014，T-033）；v3.3 DLUT 完整引入（ADR-013，T-032）；v3.2 一致性基础设施（ADR-012，T-031）；v3.1 词表手术（ADR-011，T-030）。
> - **annotation schema_version** = `2.10.0`（`references/schema.md` §一 = 批注 JSON `schema_version` = annotate_segment.py / examples/llm_wrapper.py）。v2.10.0 新增 5 个可选字段（D07._narrator_identity / D08._time_type / D08._narrative_level / D06._techniques / D12_narrative_mode），全部可选允许 null。**注意**：批注数据 schema 与 skill 版本解耦，skill 升 3.x 不代表批注字段变更。
> - **aggregation schema_version** = `3.4.0`（`references/aggregation-schema.md` = `scripts/aggregation/*.py`）。v3.13.1 causal_graph/character_arcs 新增 event_hierarchy/causal_structure/event_attributes/character_type/character_depth/agency_curve/density_distribution/dialogue_dominance。v3.7 新增 narrative_structure.json 产物。
> - 校验器向后兼容 `schema_version: 2.5.0 / 2.6.0 / 2.7.0 / 2.8.0 / 2.9.0 / 2.10.0`（旧产物版本分支豁免，不迁移；v2.10.0 新增可选字段缺失时视为 null 放行）。
> - **枚举真源**：批注层 `references/schema.md`；聚合层 `references/aggregation-schema.md`（本文件速览 / validate_output.py / templates 均须同步）。**唯一例外**：D19 `emotion` 枚举（50 词）真源为 `references/emotion-lexicon.md`（决策 17 特批）。词表演化映射参考：`references/emotion-taxonomy.md`（DLUT 21 小类三级映射，ADR-013）。

---

## 0. 定位与两种运行模式（决策 18 修订）

| 模式 | 适用环境 | scripts/ 的角色 |
|:--|:--|:--|
| **A. Agentic 完整工作流** | IDE / 有代码执行能力的 Agent | **核心组件**：切分、校验、幂等落盘、checkpoint、合并、报告全依赖它。推荐入口 `run_pipeline.py` 一条命令跑 Phase 1–5 |
| **B. 纯 LLM 手动降级** | 无工具、只把本文件当 system prompt | 可选：你手动分段、按本文件内联枚举逐段产 JSON，用户自己落盘（无法自动校验） |

> 完整工作流中 scripts/ **不是可选辅助**——没有它只能产出零散 JSON。纯 LLM 手动模式仍可用（枚举/锚点已内联，保证无工具也能产出合规 JSON），但自动化能力依赖 scripts/。

脚本全部零第三方依赖（纯 Python 3.8+ stdlib），跨平台。

---

## 1. 激活条件

**触发**（用户说以下任一即可）：
- 中文：「精读这段文本」/「拆解这个故事」/「分析这段的叙事」/「批注这段：xxx」/「做精读」/「精读+文笔拆解」/「拆伏笔链」
- 英文："close reading" / "annotate this narrative" / "close-read this segment" / "analyze craft"

**不触发**（礼貌拒绝）：
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

## 3. 工作流（Phase 1–5 + P4）

> **⚠️ 开工前强制**：D04.core 只能从 v2.9.0 新 20 个枚举词里选（见 §4.1，2.8.0 及更早旧词仅旧产物合法），自造词被 validate 直接拒。按 Phase 顺序执行，不要跳步。

### 0）推荐入口：一条命令（决策 18 新增）

```bash
# 原文 → 报告，断点续跑；深度层只跑采样计划的 deep 段
python scripts/run_pipeline.py --input <原文.txt> --doc-id <doc_id> \
    --output-dir <输出目录> --plan <输出目录>/<doc_id>_segment_plan.json \
    --llm-cmd "python 你的llm_wrapper.py" --report-format md

# 骨架模式（批注已就绪，只跑跨段→合并→报告）
python scripts/run_pipeline.py --doc-id <doc_id> --output-dir <out> --phases 3,4,5
```

也可用 `select_segments.py` 单独生成采样计划再手动分 Phase（见 §3.6）。

### 3.1 Phase 1：输入预处理

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

> **💡 推荐下一步（提升批注精度）**：执行 **Phase 1.5 场景语义切分（LumberChunker）**——按章节/字数粗切可能导致一个 segment 包含多个场景，影响批注精度。用 `examples/scene_boundary_wrapper.py` 一行命令判断场景边界，再用 `reshape_segments.py` 重排为场景级 segments。详见 [§3.1.5 Phase 1.5](#315-phase-15场景语义切分lumberchunker推荐标准流程v35-新增)。

### 3.1.5 Phase 1.5：场景语义切分（LumberChunker，**推荐标准流程**，v3.5 新增）

> **定位（推荐标准流程）**：Phase 1 粗切分按章节+2000 token 机械切分，**可能导致一个 segment 包含多个场景/事件** → LLM 精读时被混淆（D01 叙事功能判断、D04 情绪强度、D19 情感分析都不知道该聚焦哪个场景）→ **批注精度下降**。
>
> 本阶段（LumberChunker）用 Agent 自身 LLM 做**场景边界判断**（只标记不切分），再由纯脚本 `reshape_segments.py` 按边界点从原文按字符位置重切，输出场景级 final_segments。**确保每个 segment 是一个语义/场景单元，是提升批注精度的必要管道。**
>
> **v3.12.0 易用性提升**：新增 `examples/scene_boundary_wrapper.py` 官方 wrapper，一行命令就能跑场景边界判断，不需要自己写批量调用脚本。

**四阶段流程**：
```
Phase 1 粗切分（preprocess.py）→ Phase 1.5a 场景边界判断（Agent LLM）→ Phase 1.5b 后处理重排（reshape_segments.py）→ Phase 2 精细批注（annotate_segment.py，不变）
```

**Phase 1.5a：场景边界判断（Agent 用自身 LLM 执行，输出 scene_boundary.json）**

> **v3.12.0 推荐方式**：直接用官方 wrapper 脚本，不需要自己写批量调用：
> ```bash
> # 1. 设置 API 环境变量（兼容 OpenAI / DeepSeek / 任何 OpenAI 兼容接口）
> export SCENE_BOUNDARY_API_KEY="your-api-key"
> export SCENE_BOUNDARY_BASE_URL="https://api.deepseek.com/v1"  # 可选
> export SCENE_BOUNDARY_MODEL="deepseek-chat"  # 可选
>
> # 2. 运行 wrapper（一行命令）
> python examples/scene_boundary_wrapper.py \
>   --segments <out>/{doc_id}_segments.jsonl \
>   --output <out>/scene_boundary.json \
>   --doc-id <doc_id>
>
> # 3. 用 reshape_segments.py 重排
> python scripts/reshape_segments.py \
>   --segments <out>/{doc_id}_segments.jsonl \
>   --boundaries <out>/scene_boundary.json \
>   --original <原文文件路径> \
>   --doc-id <doc_id> \
>   --output-dir <out>/
> ```
>
> 也支持 `--dry-run`（只打印将调用的对数，不实际调用）、`--max-pairs`（限制处理对数，用于测试）、`--retries`（失败重试次数）。

**手动方式（不使用 wrapper 时）**：

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

> **注意**：只标记边界，不实际切分。章节边界（chapter 变化）由 reshape_segments.py 自动识别为场景边界，无需 LLM 判断。若不执行本阶段（跳过场景边界判断），reshape_segments.py 仅按章节边界合并，仍可产出更粗粒度的场景级 segments。

**Phase 1.5b：后处理重排（纯脚本 reshape_segments.py）**

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
- 场景级 segment 是"完整场景段落"但不一定是"语义原子"（场景内可有多个叙事单元，靠 Phase 2 LLM 自己识别）
- 新旧 ID 映射保证下游可追溯（批注产物中的 segment_id 可用映射表回溯到原始粗切段）

**Phase 2 使用重排结果**：将 `annotate_segment.py` 的 `--segments` 参数指向 `{doc_id}_final_segments.jsonl` 即可，其余流程不变。


### 3.1.6 Runtime Scratchpad（运行时便签本，v3.13.0 新增）

> **定位**：Agent 在单本书批注过程中自主维护的轻量级工作记忆区。不是"缩小版聚合层"，而是"输入质量增强层"——为聚合层提供更干净的输入数据。

**解决的核心问题**：
1. 无状态批注导致指称不一致（同一人物用不同指称："江洋"/"我"/"灰鹰三号"）
2. 开放型字段（人物/事件）塞进封闭集 schema 导致大量 null

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

**CLI 参数**：
- `--scratchpad`：启用 Runtime Scratchpad（默认启用）
- `--no-scratchpad`：关闭 Runtime Scratchpad

**持久化**：
- 独立文件：`{doc_id}_scratchpad.json`
- checkpoint 快照：`{doc_id}_checkpoint.json` 中的 `scratchpad_snapshot` 字段
- 断点续跑时自动从 checkpoint 或独立文件恢复

**信息抽取规则**（v3.13.0 规则版）：
- 人物：从 D19.target（情感对象）+ D18.character（语言指纹）提取
- 事件：从 D01 ∈ {激励事件/高潮/转折/下降行动/结局} 的段提取
- 别名聚合：编辑距离相似度 ≥0.6 时标记为"待确认"，注入 prompt 时让 LLM 顺便确认

### 3.2 Phase 2：逐片段批注（核心循环）

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

`--layers` 组合：`structure` / `structure,interpretation` / `structure,interpretation,craft`；emotion 单独（§3.5）。

**状态机（断点续跑）**：
- 完成一个 `(segment, layer)` → annotate_segment 自动调 `mark_layer_completed` 更新 checkpoint；再次运行自动跳过已完成（幂等续传）。
- 强制重跑：`--force`（层 JSONL 幂等 upsert，不产生重复行）；或 `python scripts/checkpoint.py reset-layer --doc-id <doc_id> --layer structure`（连带重置依赖它的下游阶段）。

**校验（annotate_segment 自动执行）**：校验失败 → **自动 span 修复并重试 ≤3 次**（craft 层 span 缺失/漂移自动回算，决策 18 兑现），仍失败则不写入 checkpoint 并显式退出。

### 3.3 Phase 3：二阶段跨段分析（Layer 4）

**⚠️ Layer 4 不能在逐片段中混跑**——需看到整本书 L1/L2 图景才能判伏笔-回收链。

```bash
python scripts/cross_segment.py --doc-id <doc_id> \
    --segments <out>/{doc_id}_segments.jsonl --structure <out>/{doc_id}_structure.jsonl \
    --interpretation <out>/{doc_id}_interpretation.jsonl --craft <out>/{doc_id}_craft.jsonl \
    --window-size 15 --overlap 3
```

**产出**：`{doc_id}_cross_segment.jsonl`（schema.md §六 L4）。每条 `cross_ref` 是**双引用**（segment_id + anchor_text，防漂移可重定位）。落地版为**启发式规则**（情绪突变=因果候选、视角切换=时序候选、D09 复用=呼应候选、D06 埋设-揭露=伏笔-回收候选），`_metadata.method = "rule_based_heuristic_v2_6"`；高精度 LLM 二分类留给调用方管线叠加。

**v2.6.0 行为**：`--preserve-curated`（默认开）保留人工/LLM 核验关系（`_source != "rule"`）不被规则重跑覆盖；完成后自动回写 `cross_segment_completed`；`anchor_text` 空白归一并可回算段内 span。


### 3.4.5 Phase 3.5：跨段关系 LLM 二分类精排（可选，v3.12.0 新增）

> **定位**：cross_segment.py 的规则候选（含 v3.12.0 新增的 D19.target 情感对象复用、D15 意象复用信号）召回率高但精度有限。本阶段用 Agent 自身 LLM 对规则候选做二分类精排，过滤误报，提升 cross_refs 质量。

**执行方式**：对 cross_segment.py 产出的每条 cross_ref，用 LLM 判断"这条关系是否真实成立"。

**判断 Prompt**：
```
你是叙事关系分析专家。请判断以下跨段关系是否真实成立。

【关系类型】{relation_type}
【起点段】{source.segment_id}，锚点：{source.anchor_text}
【终点段】{target.segment_id}，锚点：{target.anchor_text}
【规则说明】{note}

请判断：
1. 起点段和终点段之间是否确实存在这种{relation_type}关系？
2. 锚点文本是否准确反映了这种关系？

输出 JSON（严格格式）：
{
  "ref_id": "{ref_id}",
  "is_valid": true/false,
  "confidence": 0.0-1.0,
  "reason": "一句话说明判断依据"
}
```

**输出**：精排后的 cross_segment.jsonl（只保留 is_valid=true 的关系，confidence 更新为 LLM 判断值）。

> **注意**：这是可选步骤。规则候选已经可用，精排能提升精度但需要额外 LLM 调用。成本敏感时可跳过。

### 3.4 Phase 4/5：合并 + 报告

```bash
python scripts/merge_layers.py --doc-id <doc_id> --segments <out>/{doc_id}_segments.jsonl
# 产出 {doc_id}_merged.jsonl：同段 L1/L2/L2.5/L3 + cross_refs 投影嵌套（schema.md §六 Merged）

python scripts/render_report.py --doc-id <doc_id> --format md   # 或 html（默认）
# 产出 {doc_id}_report.md/.html：结构全景 + L2/L3 摘要 + L4 关系清单；零第三方依赖内联样式
```

### 3.6 Phase 6：后处理校准（v3.8.2 新增，推荐执行）

> **定位**：四层批注 + 跨段 + 合并 + 报告全部完成后，对已有批注做三项确定性后处理校准，提升批注质量和下游可用性。**可选但推荐**——校准是纯后处理，不破坏既有批注，可随时重跑。
>
> **v3.8.3 重要修复**：此前版本仅在版本历史中提到这三个脚本，未集成到主工作流，导致外部用户跑完 Phase 1-5 后不知道还需要校准。v3.8.3 起在工作流中明确列出，并在 `run_pipeline.py` 中默认自动执行（`--calibrate` 默认开启，`--no-calibrate` 可关闭）。

**三项校准功能**：

| # | 校准脚本 | 功能 | 输出字段 |
|:--:|:---------|:-----|:---------|
| 1 | `scripts/calibrate_quality.py` | **quality_score 校准**——基于 Craft 层 D13-D17 的加权评分（D13佳句30% + D14修辞20% + D15意象20% + D16词汇15% + D17句式15%），评分公式=基础分40% + 数量分40% + 多样性分20%，计算每段 craft 层的文笔质量分（0-100） | craft 行新增 `_quality_score` + `_quality_breakdown` |
| 2 | `scripts/recalibrate_confidence.py` | **confidence 信号驱动重算**——基于 5 个确定性信号加权重算 confidence：①校验是否通过（30%）②必填字段完整性（25%）③引文匹配精度（20%）④枚举值合法性（15%）⑤跨层一致性（10%，D04 vs D19 极性/强度一致性） | 全部四层行的 `confidence.overall` 重算 + `confidence.confidence_method=recalibrated_v382` + `_recalibration_breakdown` |
| 3 | `scripts/cross_validate_emotion.py` | **DLUT 弱信号交叉验证**——基于 DLUT 子集（v3.3 已引入，9,924 词，随包分发）对 segment 原文做情感词频统计，计算 DLUT 推断的主导情感（褒义/贬义/中性），与 D19 主情感的 polarity 对比。DLUT 为弱信号，一致率 >70% 即达标（D19 可表达复合情感和上下文语境） | emotion 行新增 `_baseline_emotion`（含 positive_count/negative_count/neutral_count/dominant_polarity/matched_words_sample/consistent_with_d19），保留原 D19 主情感 |

**执行命令（在产物目录下，doc_id 替换为实际值）**：

```bash
# 方式一：逐个执行（推荐，便于观察每步输出）
python scripts/calibrate_quality.py --dir <out_dir> --doc-id <doc_id> --in-place
python scripts/recalibrate_confidence.py --dir <out_dir> --doc-id <doc_id> --all-layers --in-place
python scripts/cross_validate_emotion.py --dir <out_dir> --doc-id <doc_id> --in-place

# 方式二：run_pipeline 自动执行（v3.8.3 起默认开启）
python scripts/run_pipeline.py --doc-id <doc_id> --input <raw.txt> --phases 1,2,3,4,5,6
# 或仅跑校准（假设 Phase 1-5 已完成）
python scripts/run_pipeline.py --doc-id <doc_id> --input <raw.txt> --phases 6
```

**金标准 20 部验证结果（v3.8.2）**：
- quality_score 分布合理：高分 61.6（手/猫/上海的狐步舞等文学质量高的作品）/ 中分 47.6（月牙儿）/ 基础分 44.6（其他 13 部）
- confidence emotion 层有 1-7 个唯一值（跨层一致性差异），craft 层 0.9-0.95
- DLUT 交叉验证平均一致率 **88.7%**（超过 70% 目标），14 部作品 100% 一致，最低 33.3%（为奴隶的母亲，DLUT 弱信号不考虑上下文语境，合理）

### 3.5 Phase 2.5：P4 情感分析 Pass（Layer 2.5 · D19 · 触发式）

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

### 3.6 段采样分层策略（决策 18 新增）

分级策略此前只管「层」不管「段」。`select_segments.py` 读已批全量的 structure，把每段分档，让「20% 深度档」规则化而非人工选段：

```bash
python scripts/select_segments.py --structure <out>/{doc_id}_structure.jsonl
# 产出 {doc_id}_segment_plan.json（tiers: deep/light/skip + per_segment 理由）
```

**默认分档规则**（CLI 可覆盖）：D01 ∈ {激励事件, 上升行动, 高潮, 转折} 或 D04.intensity ≥ 6 或 D07.is_switch_point=true → **deep**（再跑 interpretation/craft…）；D01 ∈ {背景铺垫, 过渡} → **skip**；其余 → **light**。下游 `run_pipeline.py --plan` 消费：structure 全量跑，深度层只跑 deep 段。

### 3.7 聚合层（v2.9/v3.0，可选但推荐）——批注 → 全局叙事结构

**批注管"逐段信号"，聚合管"全书拼图"**。聚合层把 L1-L4 批注（+D19/D15/D18 细粒度信号）组装成全局叙事图，供生成侧 / 叙事分析直接消费。10 个脚本纯规则零第三方依赖，全链路 <2s/本。

```bash
AGG=scripts/aggregation
# ① 实体消解（D19.target + D18.character + 人名 NER → entity_graph）
python $AGG/entity_resolution.py --segments <out>/{doc_id}_segments.jsonl --doc-id <doc_id> \
    --output-dir <out>/aggregation --emotion <out>/{doc_id}_emotion.jsonl \
    --craft <out>/{doc_id}_craft.jsonl --structure <out>/{doc_id}_structure.jsonl
# ② 场景图（D08 时空 + D01 功能连续性合并段 → scene_graph）
python $AGG/scene_graph.py --segments <out>/{doc_id}_segments.jsonl --structure <out>/{doc_id}_structure.jsonl \
    --doc-id <doc_id> --output-dir <out>/aggregation --entity-graph <out>/aggregation/{doc_id}_entity_graph.json
# ③ 角色弧线（按实体聚合 D19/D04 情绪点 → character_arcs）
python $AGG/character_arcs.py --segments <out>/{doc_id}_segments.jsonl --structure <out>/{doc_id}_structure.jsonl \
    --emotion <out>/{doc_id}_emotion.jsonl --entity-graph <out>/aggregation/{doc_id}_entity_graph.json \
    --doc-id <doc_id> --output-dir <out>/aggregation
# ④ 故事类型推断（六维：题材/叙事风格/时间结构/情感曲线/节奏/读者体验 → story_metadata）
python $AGG/story_type_inference.py --segments <out>/{doc_id}_segments.jsonl --structure <out>/{doc_id}_structure.jsonl \
    --interpretation <out>/{doc_id}_interpretation.jsonl --emotion <out>/{doc_id}_emotion.jsonl \
    --doc-id <doc_id> --output-dir <out>/aggregation
# ⑤ 叙事结构分析（v3.7 新增：弗雷塔格五幕+热奈特聚焦+叙事时间线+救猫咪节拍+叙事层级 → narrative_structure）
python $AGG/narrative_structure.py --structure <out>/{doc_id}_structure.jsonl \
    --doc-id <doc_id> --output-dir <out>/aggregation
# ⑥ 叙事技法分析（v3.8 新增：转场技巧+悬念设置+蒙太奇手法+钩子类型 → writing_techniques）
python $AGG/writing_techniques.py --structure <out>/{doc_id}_structure.jsonl \
    --interpretation <out>/{doc_id}_interpretation.jsonl \
    [--cross-segment <out>/{doc_id}_cross_segment.jsonl] \
    --doc-id <doc_id> --output-dir <out>/aggregation
# ⑦ 因果链（cross_segment 关系 → CAUSE/ENABLE 边）
python $AGG/causal_graph.py --cross-segment <out>/{doc_id}_cross_segment.jsonl --structure <out>/{doc_id}_structure.jsonl \
    --doc-id <doc_id> --output-dir <out>/aggregation
# ⑧ 物件链（D15 意象聚类 → object_chains）
python $AGG/object_chains.py --craft <out>/{doc_id}_craft.jsonl --doc-id <doc_id> --output-dir <out>/aggregation
# ⑨ 故事图合并（五子图谱 + story_metadata → story_graph.json）
python $AGG/story_graph.py --aggregation-dir <out>/aggregation --doc-id <doc_id> --output-dir <out>/aggregation
# ⑩ 适配器（story_graph → text2story / YARN / NCP 三种叙事格式）
python $AGG/adapters.py --story-graph <out>/aggregation/{doc_id}_story_graph.json \
    --doc-id <doc_id> --output-dir <out>/aggregation/adapters --formats text2story,yarn,ncp
```

**产物依赖链**：①②③④⑤⑥ 只依赖批注层 JSONL；⑦ 依赖 cross_segment；⑧ 依赖①-⑦全部；⑨ 依赖⑧。失败/缺输入时各脚本自行报错退出，可逐脚本重跑（覆盖写，幂等）。

**聚合层 Schema 唯一真源**：`references/aggregation-schema.md`（决策 22）。改字段先改该文件再改脚本。
**v3.0.1 修复摘要**（决策 22）：adapters 字段名对齐上游真实字段（text2story/YARN/NCP 内容性字段全部非占位）、entity_resolution 输出 `segment_ids` 完整段集合（修复出场角色截断）、全脚本 `sorted(set(...))` 确定性、题材词表去书名化。

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

### 4.0 枚举值速查表（v3.8.1 新增，LLM 生成批注时一眼可查）

> **唯一真源**：`references/schema.md`。本表为速查引用，改枚举先改 schema.md 再同步本表。

| 维度 | 字段 | 合法枚举值 |
|:----:|:----|:----------|
| **D01** | 叙事功能 | `背景铺垫` / `激励事件` / `上升行动` / `高潮` / `下降行动` / `结局` / `过渡` / `插叙` / `倒叙` / `尾声` |
| **D04.core** | 情绪基调（20词，v2.9.0） | `信任` / `压抑` / `厌恶` / `喜悦` / `复仇` / `嫉妒` / `孤独` / `屈辱` / `希望` / `平静` / `恐惧` / `悬疑` / `悲伤` / `惊讶` / `愤怒` / `渴望` / `焦虑` / `绝望` / `羞耻` / `释然` |
| **D04.polarity** | 极性 | `positive` / `negative` / `neutral` / `mixed` |
| **D06.type** | 信息控制 | `揭示` / `隐藏` / `误导` / `复合` |
| **D07.type** | 叙事视角 | `第一人称` / `第三人称` / `第二人称` / `多视角` / `第一人称旁观者` / `不可靠叙述者` / `全知视角` / `有限视角` |
| **D10** | 对话功能 | `推进情节` / `揭示性格` / `传递信息` / `制造冲突` / `缓和气氛` / `表达情感` / `暗示主题` / `过渡衔接` |
| **D11** | 描写类型（非空数组） | `外貌描写` / `动作描写` / `语言描写` / `心理描写` / `环境描写` / `细节描写` / `场面描写` / `神态描写` |
| **D14.type** | 修辞手法 | `比喻` / `拟人` / `排比` / `反讽` / `通感` / `夸张` / `对比` / `象征` |
| **D15.type** | 意象类型 | `自然意象` / `器物意象` / `人体意象` / `色彩意象` / `抽象意象` |
| **D16.pos** | 词汇词性 | `动词` / `形容词` / `副词` / `名词` |
| **D17.type** | 句式类型 | `排比` / `长短交替` / `倒装` / `独词句` / `对偶` / `设问` |
| **D19.primary** | 主情感（50词，v2.9.0） | 见 `references/emotion-lexicon.md` §二（50词全量表）；常用：`喜悦`/`悲伤`/`愤怒`/`恐惧`/`惊讶`/`期待`/`厌恶`/`信任`/`依恋`/`绝望`/`焦虑`/`孤独`/`羞耻`/`渴望`/`嫉妒`/`迷茫`/`感动`/`得意`/`悲欣交集`/`爱恨交织`/`苦乐参半`/`克制中的温情`/`冷峻中的悲悯`/`叙述性冷漠`/`反讽性平静` |
| **D19.polarity** | 情感极性 | `positive` / `negative` / `neutral` / `mixed` |
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

- D06：`type ∈ {揭示/隐藏/误导/复合}`；content 中引号引的**引文必须是 `text_span.text` 子串**（validate 抽引号并校验子串 + 95% 相似度）。**_techniques（v2.10.0 可选）**：信息控制具体技巧数组（可多选）——延迟揭示/选择性披露/视角遮蔽/不可靠叙述者误导/信息过载/误导性伏笔/悬念留白。
- D09：`string[] | null`，**≤3 个**（超=截断+报错）。
- narrator_reliability：可靠 / 部分不可靠 / 不可靠 / 无法判断。

### 4.3 Layer 2.5（D19）要点

定位：L2 语义扩展——D19 做角色/精细情感（50 词，v2.9.0 补 羞耻/渴望/嫉妒/迷茫/感动/得意），区别于 L1 D04 段落氛围摘要（20 词粗粒度）；同情绪都产出时**以 D19 为准**（决策 17）。

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

### 4.7 置信度 + status 自动推导

- `confidence.overall ∈ [0,1]`；`confidence_method ∈ {model_self_report, consistency_check, human_review}`。
- **Structure 七维 `per_dimension` 必须填 0–1 数字**（即使主值 null 也表示「我确定没值」）；Interpretation/Craft 可 null。P4 触发段 `per_dimension.D19` 必填。
- status 对齐（`status != superseded` 时）：overall ≥0.8 → `confirmed`（打 tentative=warning）；<0.8 → `tentative`（打 confirmed=**error**）。

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

## 6. 分级策略（成本红线）

| 档级 | 跑哪些层 | 典型用途 |
|:--:|:--|:--|
| 轻量档 | Phase 1 + 2（仅 structure）+ 4 | 大规模批量扩充基数 |
| **标准档**（默认）| Phase 1 + 2（structure+interpretation）+ 3 + 4 | 普通精读 / 拆解 |
| 深度档 | Phase 1–5 全跑（含 craft + report）| 金标准样本 / 训练集核心 |

> 【成本红线】严禁把全量深度维度跑应用到百万级文本——20% 深度档提供 80% 价值。**段轴采样**（§3.6）：structure 全量（便宜）→ `select_segments` 分档 → 深度层只跑 deep 段，把红线从"人工克制"变成"规则强制"。

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
| **聚合层 Schema 完整定义（唯一真源）** | `references/aggregation-schema.md` | 跑/改 `scripts/aggregation/` 10 脚本或消费聚合产物前 |
| **Few-shot 完整批注示例** | `references/annotation-examples.md` | 开始批注前看 1–2 条找感觉 |
| **情绪校准锚点完整表** | `references/emotion-anchors.md` | 情绪强度犹豫时 |
| **D19 情感词表（50 词，枚举真源）** | `references/emotion-lexicon.md` | 跑 P4/D19 前必读 |
| **D01 叙事功能判别锚点（每词 2 示例 + 边界判定表）** | `references/function-anchors.md` | 写 D01 前必读（v3.1 新增，Freytag 五幕 + Labov 六要素） |
| **节奏校准锚点完整表** | `references/pace-anchors.md` | 节奏犹豫时 |
| **每层输出模板（可直接填充）** | `templates/*-output.json` | 避免漏字段 |
| **数据质量看门狗（粗切前硬门槛）** | `scripts/quality_gate.py` | 对原始文本做五维检测（中文占比/引号闭合/乱码/段落结构/重复性），产出 quality_report.json；**粗切分前必须跑一遍**，fail 项需修复后再进入 preprocess（v3.4 新增） |
| **计算文学分析（逐 segment 量化指标）** | `scripts/quant_analyzer.py` | 重排后、批注前逐 segment 计算句长/TTR/词性/对话占比/标点/情感词频（DLUT 子集）/五感密度，产出 quant_metrics.jsonl，作为 LLM 批注的硬证据注入；jieba 可选，缺失自动降级（v3.4 新增） |
| **精细化切分重排（场景级 segments）** | `scripts/reshape_segments.py` | Phase 1.5 后处理：读粗切 segments + scene_boundary.json（Agent 场景边界判断）+ 原始文本 → final_segments.jsonl（场景级，scene_NNN 编号）+ 新旧 ID 映射表；按字符区间从原文重切，章节边界自动识别（v3.5 新增） |
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

| 版本 | 日期 | 变化 |
|------|------|------|
| **3.9.0** | 2026-09-06 | **兜底切分 + 调用链补全（ADR-020）**：①preprocess.py 新增按字符数粗切兜底（--fallback 默认开启，触发条件：章节边界<3个/单段>5000字符/段数<3段且全文>5000字符，--fallback-chars 默认2000，保留句子边界切分，pollution_warning 标记"v3.12.0兜底切分"），解决遇到奇奇怪怪章节标题识别不出来时全文塞进单段的问题；②SKILL.md 调用链补全——新增 Phase 1.5 场景边界判断（LLM 语义化切分 Prompt 模板）+ Phase 1.6 精细化重排（reshape_segments.py 调用入口），明确 reshape_segments.py / merge_batch.py / check_enum_consistency.py 三个新增脚本在工作流中的调用位置，解决"装载了脚本但 agent 调用不到"的问题。annotation/aggregation schema 不变（纯工程化增强）。 |
| **3.8.4** | 2026-09-06 | **外部实战反馈修复轮（ADR-019）**：外部 AI agent 用 v3.8.2 跑《球状闪电》后提交试用反馈，暴露 7 项 skill 设计缺陷。①**preprocess 切分器增强（T-050）**：新增纯文字小节标题识别（「XX之一」模式/数字序列/中文数字序列）+ 短行启发式标题检测函数 is_possible_section_title，修复「大学」「异象之一」等纯文字标题不被识别导致 17.5 万字符塞进单段的问题；②**场景边界语义化切分（T-051）**：新增 scripts/reshape_segments.py（LumberChunker 思想 Skill 化——粗切→LLM边界判断→脚本重排→精细批注），SKILL.md 新增 Phase 1.5 场景边界判断 Prompt 模板；③**CLI 参数统一（T-052）**：cross_segment.py/render_report.py 统一为 --output-dir（--output 为兼容别名），修复文档与代码不一致导致首次执行报错的问题；④**render_report 变量作用域修复（T-053）**：--segments 改为可选，自动从 output-dir 推断；⑤**枚举真源同步（T-054）**：新增 scripts/check_enum_consistency.py 三方一致性检查工具（schema.md ↔ validate_output.py ↔ SKILL.md），以校验器为权威真源；⑥**cross_segment 规则增强（T-055）**：纳入 D19.target/D06埋设-揭露/D15意象复用作为候选信号，SKILL.md 新增 Phase 3.5 LLM 二分类精排可选步骤；⑦**工具补全（T-056）**：新增 scripts/merge_batch.py（官方 batch 合并注入工具，自动去重+幂等 upsert）+ annotate_segment.py 新增 doc_id 合法性校验 + RUNBOOK.md 新增 PowerShell 编码注意事项和 batch 合并工作流。annotation/aggregation schema 不变（纯工程化增强和体验修复）。**背景**：Owner 让外部 AI agent 用最新发布版跑刘慈欣《球状闪电》，agent 提交详细试用反馈报告（reports/试用反馈报告.md），核心结论是「骨架（校验/续跑/版本治理/聚合）是生产级的，但切分器和文档同步这两个外围环节在真实中文科幻文本上不够皮实」。 |
| **3.8.3** | 2026-09-06 | **实战审计修复轮（ADR-018）**：外部 AI agent 用 v3.8.2 跑《球状闪电》暴露的 5 项 skill 本身设计缺陷修复。①`annotate_segment.py` SCHEMA_VERSION 常量从 2.9.0 同步为 2.10.0（v3.6.0 已升级 schema 但此处忘记同步，导致 craft/emotion 层 schema_version=2.9.0 与 structure/interpretation=2.10.0 不一致）；②**SKILL.md 工作流新增 Phase 6 后处理校准**——明确说明四层批注完成后需运行 calibrate_quality.py / recalibrate_confidence.py / cross_validate_emotion.py 三个校准脚本，给出完整命令行示例（此前仅在版本历史中提到，外部用户跑完 Phase 1-5 后不知道还需校准，导致 v3.8.2 三项核心功能完全不生效）；③`run_pipeline.py` 集成 Phase 6——新增 `--calibrate`/`--no-calibrate` 参数（默认开启），Phase 5 完成后自动运行三项校准，校准失败不阻断主流程（打印警告继续），默认 phases 从 1-5 改为 1-6；④`merge_layers.py` 生成 merged.jsonl 时每行写入 `schema_version=2.10.0`（此前 merged 行无 schema_version 字段）；⑤`checkpoint.py` save_checkpoint 时确保 schema_version=2.10.0（旧产物 checkpoint schema_version=2.6.0）；⑥`RUNBOOK.md` 新增「产物目录清理」章节——提醒删除 `_batch_*.jsonl` 等临时文件，给出必留产物清单。annotation/aggregation schema 不变（纯 bugfix 和流程集成）。**背景**：Owner 让外部 AI agent 用最新发布版 v3.8.2 跑刘慈欣《球状闪电》（59 段，四层批注全完成，校验全部 PASS），审计产物时发现 v3.8.2 三项校准功能完全未生效（quality_score 0/55 段、recalibrated confidence 0/227 条、baseline_emotion 0/58 段），根因是校准脚本未集成到主工作流；同时发现 schema_version 不一致等 4 项缺陷。 |
| **3.3.0** | 2026-09-05 | **DLUT 完整引入（ADR-013，T-032）**：①新建 `scripts/build_dlut_subset.py`——从本地全量 xlsx（27,465 词）按文学精读适配规则清洗（词性 adj/verb/noun/adv + 词长 ≤2 + 义项合并），生成 `references/lexicon-dlut-subset.json`（9,924 词，含来源/许可/引用声明，随包分发，D19 命中率 33/50 与全量一致）；②新建 `references/emotion-taxonomy.md`——DLUT 21 小类 → Plutchik 8 基元 → D19 词位三级映射表（NN/NM 双认 + NG 归类注记，词表演化归约裁决表）；③`scripts/lexicon_crosscheck.py` 升级 v3.3——**默认读仓库内子集**（--subset），子集缺失回退本地全量 xlsx（--dlut），NRC 文件缺失自动跳过抽样（降级不报错），一般使用者无需任何外部数据即可跑词表演化工具；④README §八.3 重写（子集已分发 + 维护者才需全量 + NRC 仍禁再分发）。 |
| **3.8.2** | 2026-09-05 | **三项校准功能（ADR-017，T-042/T-043/T-044）**：①`scripts/calibrate_quality.py`——quality_score 校准，基于 Craft 层 D13-D17 加权评分（D13佳句30%+D14修辞20%+D15意象20%+D16词汇15%+D17句式15%），评分公式=基础分40%+数量分40%+多样性分20%，回写到批注 JSONL 的 `_quality_score` 字段；②`scripts/recalibrate_confidence.py`——confidence 信号驱动重算，基于 5 个确定性信号加权（校验通过30%+必填字段完整性25%+引文匹配精度20%+枚举值合法性15%+跨层一致性10%），回写到 `confidence.overall`，`confidence_method=recalibrated_v382`；③`scripts/cross_validate_emotion.py`——DLUT 弱信号交叉验证，基于 DLUT 子集（v3.3 已引入，9901 词，随包分发）对 segment 原文做情感词频统计，计算 DLUT 推断的主导情感（褒义/贬义/中性），与 D19 主情感的 polarity 对比，双轨存储 `_baseline_emotion` 字段（保留原 D19 主情感）。annotation/aggregation schema 不变（三项均为后处理校准，新增可选元字段 `_quality_score`/`_baseline_emotion`，不破坏既有字段）。**金标准 20 部验证结果**：quality_score 分布合理（高分61.6/中分47.6/基础分44.6，文学质量高的作品得分更高）；confidence emotion 层有 1-7 个唯一值（跨层一致性差异）；DLUT 交叉验证平均一致率 88.7%（超过 70% 目标，14 部作品 100% 一致）。**背景**：T-020 backlog 中规划的三项校准功能（原计划需要人工标注集），因 T-004 金标准 20 部全量批注完成后有了 122 段四层批注作为锚点集，可以实现确定性校准（无需人工标注集）。原计划的 cnsenti 弱信号调整为基于 DLUT 子集的情感词频弱信号交叉验证。 |
| **3.8.1** | 2026-09-05 | **工程化加固（ADR-016，T-038/T-039/T-040）**：①`span_locator.py` 模糊匹配增强——在原有①精确子串②空白归一化子串之后，新增③去标点归一化子串④SequenceMatcher 相似度≥0.85 模糊匹配，自动定位最相似子串并修正引文文本，返回 {span, text, match_level, similarity, warning}；`repair_craft_row` 升级为使用 fuzzy_find_span，模糊匹配时自动修正引文文本并记录警告；②`annotate_segment.py` 新增 `--auto-fix`/`--no-auto-fix` CLI 参数（默认开启），craft 层校验失败时自动调用 fuzzy_find_span 修正引文和 span 后重试，兑现 SKILL.md 长期声称的"校验失败自动重试3次"承诺；③SKILL.md 新增 §4.0 枚举值速查表——集中列出 D01/D04/D06/D07/D10/D11/D14/D15/D16/D17/D19/cross_segment 共 15 个维度的全部合法枚举值，LLM 生成批注时一眼可查，无需翻 schema.md。annotation/aggregation schema 不变（纯工程化加固，零 schema 变更）。**背景**：T-004 金标准 20 部全量批注执行中，craft 层大规模失败（月牙儿 34/36 失败），根因是 LLM 写的引文有细微偏差（多标点/少字/概括词），原 span_locator 只支持精确+空白归一两级匹配，无法修复；同时枚举值散落在 schema.md 各处，LLM 容易用错枚举值（D14='细节'/'反复'、D15='动物意象'等）。修复后预期 craft 层失败率从 ~50% 降至 <5%。 |
| **3.8.0** | 2026-09-05 | **叙事技法分析（ADR-014，T-037）**：聚合层第 10 脚本 `writing_techniques.py`，产出 writing_techniques.json。4 子模块规则粗筛（同因果链"规则粗筛+LLM精排"架构）：①转场技巧（时间转场=年份差≥2或季节变化/空间转场=地点关键词变化/细节过渡=背景铺垫→过渡→上升行动/悬念转场=高潮转折→下降背景硬切）；②悬念设置（设疑法=D06隐藏含疑问词/连环设悬=连续≥3段隐藏/伏笔回收对=cross_refs/悬念留白=隐藏后5段内无揭示）；③蒙太奇手法（平行蒙太奇=5段窗口内地点变化≥3/交叉蒙太奇=D05≥4且D01快速切换/对比蒙太奇=相邻段D04极性相反且强度≥5）；④钩子类型（悬念钩子=段尾D06隐藏或D01转折/行动钩子=D05≥4或D01高潮/情感钩子=D04 intensity≥7/场景钩子=段首地点关键词变化）。综合技法评估（技法密度/写作风格/主导技法）。aggregation schema 不变（3.1.0，新增产物同版本）。annotation schema 不变（纯聚合新增）。 |
| **3.7.0** | 2026-09-05 | **叙事结构分析（ADR-014，T-036）**：聚合层第 9 脚本 `scripts/aggregation/narrative_structure.py`，产出 narrative_structure.json。P0：弗雷塔格五幕（从 D01 序列按幕转换点推导，六幕区间+关键转折点+结构健康度）+ 热奈特聚焦（从 D07.type 统计+_narrator_identity，主导聚焦+切换率+复杂度+叙述者可靠性）；P1：叙事时间线（从 D08.time+_time_type，时间节点+时间跳跃+时间结构类型，旧产物降级为关键词推断）+ 救猫咪节拍（简化 14 节拍，位置百分比定位+D01 信号验证）；P2：叙事层级图（从 D08._narrative_level，旧产物降级标注）。aggregation schema 3.0→3.1。annotation schema 不变（纯聚合新增）。 |
| **3.6.0** | 2026-09-05 | **原子化扩展字段（ADR-014，T-035）**：annotation schema 2.9.0→2.10.0，新增 5 个可选字段——①`D07._narrator_identity`（叙述者身份 ID，跨段追踪）；②`D08._time_type`（linear/flashback/flashforward/analepsis/prolepsis 时间结构类型）；③`D08._narrative_level`（1/2/3+ 叙事层级）；④`D06._techniques`（7 种信息控制技巧数组：延迟揭示/选择性披露/视角遮蔽/不可靠叙述者误导/信息过载/误导性伏笔/悬念留白）；⑤`D12_narrative_mode`（热奈特叙事话语模式：场景/概述/停顿/省略/摘要 + density + is_summary + is_scene）。全部可选允许 null，LLM 无法判断时 null；旧产物零迁移（校验器缺失字段视为 null 放行）。schema.md/validate_output.py/templates 全链同步。设计意图：这 5 个字段是 v3.7 叙事结构分析（聚合层）的原子信号前置依赖。 |
| **3.5.0** | 2026-09-05 | **精细化切分器/重排（ADR-014，T-034）**：①SKILL.md 新增 Phase 1.5 场景边界判断 Prompt（LumberChunker 思想 Skill 化，Agent 用自身 LLM 判断相邻段是否同场景，四维度：地点变化/时间跳跃/视角切换/主题断裂，输出 scene_boundary.json 只标记不切）；②新建 `scripts/reshape_segments.py`——后处理切分重排（读 segments_rough + scene_boundary + 原始文本 → final_segments.jsonl + segment_id_mapping.json，按 start_char/end_char 从原文按字符区间重切，重新编号 scene_NNN，建立新旧 ID 映射，坐标自校验）；③重排规则优先级：章节边界自动切 > scene_boundary 显式标记 > 默认合并；④annotation/aggregation schema 不变（纯预处理增强，Phase 2 annotate_segment 不变，只需 --segments 指向 final_segments）。 |
| **3.4.0** | 2026-09-05 | **前置双模块（ADR-014，T-033）**：①新建 `scripts/quality_gate.py`——数据质量看门狗（粗切前硬门槛）：中文字符占比/引号闭合率/乱码检测/段落结构稳定性/重复性检测五维评分，产出 quality_report.json（pass/warn/fail + 修复建议），支持 --fail-on-error CI 集成；②新建 `scripts/quant_analyzer.py`——计算文学分析（重排后批注前，逐 segment 独立）：句长/TTR/词性占比/对话占比/标点密度/情感词频（复用 DLUT 子集，pol 编码 1=褒2=贬0=中）/五感密度（视觉/听觉/触觉/嗅觉/味觉内置词表），产出 quant_metrics.jsonl；jieba 为可选依赖，缺失时自动降级为 DLUT 子集最大正向匹配（2 字词优先）+ 子集词性反查；③annotation schema 不变（2.9.0），aggregation schema 不变（3.0.0）——纯前置脚本，零 schema 变更。 |
| **3.2.0** | 2026-09-05 | **一致性基础设施（ADR-012，T-031）**：①新建 `scripts/lexicon_crosscheck.py`——DLUT 21 小类 / NRC 中文版数据**本地化对照**（数据不进 git，NRC 许可禁再分发）：D19 覆盖度检查 + 候选词生成（首跑：D19 50 词命中 33/66%，真实缺口小类 NH/NI/NL，NN=数据版"贬责"代码实证修正文献 NM）；②新建 `scripts/collect_lexicon_candidates.py`——WikiSkill 经验回写管道（arXiv:2608.27454）：产物自由情感词 ≥3 次 → 候选，兑现 emotion-lexicon §四协议（首跑：两本书 0 自由词=语料与 50 词表完全一致）；③Trace2Skill SoP（arXiv:2603.25158）：collect `--sop` 输出 RUNBOOK 校验错误修复表自动行（已并入 RUNBOOK §3）；④`examples/llm_wrapper.py` 新增 `build_enum_schema()` + `--show-schema`（D04 20 词 / D19 50 词 JSON Schema 枚举约束，OpenAI 兼容 response_format 接入点）；⑤emotion-lexicon.md 新增 §四.b「基元归约审查协议」——DLUT 21 小类作中文归约中间层（只引分类体系不引数据全文）+ README §八.3 数据获取与许可指引。 |
| **3.1.0** | 2026-09-05 | **词表手术与一致性加固（ADR-011，T-030）**：①D04.core 手术——删 4 非情绪词（尊严/背叛/贪婪/宽恕）→ 补 4 高频情绪（羞耻/惊讶/渴望/厌恶），annotation schema 2.8.0→2.9.0（新增枚举=次版本），validate 对 2.8.0 及更早旧词版本分支豁免；②D19 44→50——补 羞耻/渴望/嫉妒/迷茫/感动/得意，4 姿态复合词标注使用条件（emotion-lexicon.md v2）；③新建 `references/function-anchors.md`（D01 每词 2 示例 + 边界判定表，依据 Freytag 五幕 + Labov 六要素）；④新建 `scripts/term_normalizer.py` 同义词归一化（自由词→枚举词保守映射）；⑤全链同步（schema.md / emotion-anchors polarity 映射 / validate_output / templates / README-RUNBOOK 索引）+ SKILL.md 瘦身（§9 安装移 README）；⑥词库选型参照 NRC EmoLex（Plutchik 8 基元）与大连理工中文情感本体库（7 大类 21 小类）完成交叉验证。**验收**：py_compile 全绿 + 2.8.0 旧产物（含"尊严"）校验版本豁免通过 + 2.9.0 新词表校验断言通过 + 词表 grep 同步一致。 |
| **3.0.1** | 2026-09-05 | **聚合层修复轮（决策 22，T-029 闭环）**：①adapters.py 字段名对齐上游真实字段——text2story events 改读 `primary_function/primary_time/characters_present`（原读不存在的 scene_summary/time/characters 全占位）、participants 统一 PER（原读不存在的 entity_type 全员误标 ORG）、YARN label 改读 primary_function、NCP 角色改读 `arc_classification.arc_type/trajectory_length/trajectory_sample`（原恒空）+ plot_structure 七桶按 primary_function 实际填充（原死结构）；②entity_resolution 输出 `segment_ids` 完整段集合 + scene_graph/character_arcs 优先完整段集合、采样不足回退原文别名匹配（修复出场角色截断，后半本书 characters_present 大面积为空）；③全脚本 `sorted(set(...))` + scene_graph primary_function 平票确定性 tie-break（消除 PYTHONHASHSEED 顺序漂移，复现性验证 6 产物两次运行哈希一致）；④character_arcs 回退阈值 `< segment_count`（原 *0.5 致 coverage_rate 虚高）；⑤题材关键词去书名化（删上海堡垒/月亮专属词，T-004 前置）；⑥无可靠性标注时 `is_reliable=None`（原默认 True 无证据声称可靠）；⑦文档收编：SKILL §3.7 聚合层章节 + 版本历史、README 版本治理表修正、RUNBOOK 补 8 脚本 CLI 速查、design-decisions 决策 19–22、新建 `references/aggregation-schema.md`（聚合层 Schema 真源）；⑧版本号解耦 ADR（决策 22）：skill version=3.0.1 / annotation schema=2.8.0 / aggregation schema=3.0.0 三域独立。**验收**：两本书全链路重跑 + 内容断言 ALL PASS（占位 0 / 空 tense 0 / 空 participants ≤5% 且均为 frontmatter/过渡段 / PER>0 / trajectory 非空 / plot_structure 非空）。 |
| **3.0.0** | 2026-09-04 | **生成器就绪（决策 21）**：新增 `scripts/aggregation/causal_graph.py`（因果链，D01 校验端过滤）、`object_chains.py`（物件链，D15 意象聚类）、`story_graph.py`（五子图谱合并）、`adapters.py`（text2story/YARN/NCP 三适配器）。两本书验证通过。 |
| **2.9.0** | 2026-09-04 | **全局聚合器 MVP（决策 20）**：新增 `scripts/aggregation/`——`entity_resolution.py`（实体消解）、`scene_graph.py`（场景图重建）、`character_arcs.py`（角色弧线）、`story_type_inference.py`（故事类型六维推断）。纯规则零依赖。 |
| **2.8.0** | 2026-09-04 | **数据修复与管道硬化（决策 19）**：Gate 0 冻结侦查（manifest/contamination/segmentation_version_record）+ R1.0 根因复盘（`docs/rca/data_quality_rca_v28.md`，修正"emotion 空壳行"格式误判）+ Gate 1 数据修复（594 行格式统一：craft→layers.craft、emotion→layers.emotion 直接格式、checkpoint 重建、`_provenance` 全覆盖）+ Gate 2 机械验证（audit_v27.py 0 error）+ Gate 3 D18 补齐（shanghai 92.1%）。schema.md 同步 2.8.0（craft/emotion 格式统一 + `_provenance` 全局元字段）。审计脚本归档 `scripts/audit/archive_v28/`。 |
| **2.7.0** | 2026-09-04 | 新增 **D19 情感分析**（P4 Pass，Layer 2.5 语义扩展）：独立 `emotion.jsonl` + emotion-output 模板 + `emotion-lexicon.md`（44 词，D19 枚举真源例外）；schema/validate/checkpoint/merge/render 全接入；P4 触发条件四则。L1–L3 schema 不变，旧产物零迁移（决策 17）。**同日工程化修复轮（决策 18，未升版）**：annotate_segment 新增 `--input-json` 非交互注入 + `--all-pending` 批量驱动 + 校验失败自动 span 修复重试 ≤3 次（兑现承诺）+ 幂等 upsert 落盘；span 定位抽公共模块 `span_locator.py`（fill_spans 复用）；新增 `select_segments.py`（段采样分层）与 `run_pipeline.py`（Phase 1–5 一体化 + --plan/--resume）；SKILL.md 定位改写（scripts=核心组件）+ 瘦身；新增 `docs/RUNBOOK.md`。 |
| **2.6.0** | 2026-09-04 | 真实全本（月亮与六便士）打补丁 + 小增强（v2.5.1 合入）：①Windows GBK 打印崩溃修复；②checkpoint 加载路径错位修复；③cross_segment 完成自动回写标记；④MD 报告补 L2/L3 摘要；⑤HTML 报告补 D04 极性列；⑥D04.polarity 必填（旧产物豁免）；⑦cross_segment 锚点清洗 + `--preserve-curated`；⑧checkpoint.py 加 `--dir`；⑨新增 `fill_spans.py`；⑩全脚本升 2.6.0。 |
| 2.5.0 | 2026-09-04 | 3→4 层架构大升级 + 7 项 P0 bug 修复（ID 碰撞/坐标漂移/无边界截断/frontmatter 丢弃/L4 占位/merge 字段/segment_id 前缀）+ schema 单一真源 + 4 层模板 + checkpoint 状态机 + span 段内相对偏移。 |
| ≤2.3.0 | 2026-08-31~09-03 | 早期单片段版。2.2.0（12 维含 D02/D03）**已废弃**。 |

> 版本号（决策 22 解耦后）：**skill version** SemVer 主版本=能力不兼容；次版本=新增能力；修订号=修复轮。**annotation schema_version** 独立演进（当前 2.9.0）。**aggregation schema_version** 独立演进（当前 3.0.0）。三者解耦，各自域内一致。

---

*精读批注 Skill v3.3.0 — "先验证，再声称；每段每层落盘；二阶段跨段；四层合一，情感入轨；全局聚合，图谱拼图。从『规格正确』走向『实现可运行』。"*

