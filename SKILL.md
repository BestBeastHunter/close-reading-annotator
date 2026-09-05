---
name: close-reading-annotator
version: 3.6.0
description: 对小说、剧本等叙事文本进行四层精读批注。输出结构层(叙事功能/情绪/节奏/视角/时空/对话功能/描写类型) + 阐释层(信息控制/主题/叙述者可靠性) + 情感层(角色情感/情感对象/段内情感弧，P4 触发式) + 文笔层(佳句/修辞/意象/词汇/句式/人物语言指纹) + 跨段层(伏笔链/段间关系)。支持断点续跑、层粒度重跑、引文子串校验、span 位置断言。适用于：小说精读、故事拆解、叙事分析、文笔拆解。不用于技术文档、论文、代码。
author: BestBeastHunter
license: MIT
---

# 四层精读批注 Skill v3.6.0

对叙事文本进行**四层结构化批注**（外加 L2.5 情感分析）：Layer 1「语义-结构层」、Layer 2「阐释-判断层」、Layer 2.5「情感分析层」（D19，P4 触发式）、Layer 3「文笔-语言层」、Layer 4「跨段-关系层」。批注之上叠加**全局聚合层**（v2.9/v3.0，`scripts/aggregation/`）：实体消解 → 场景图 → 角色弧线 → 故事类型推断 → 因果链/物件链 → 故事图合并 → 适配器输出。

**核心原则**：每段每层独立落盘 → 断点续跑 → Layer 4 二阶段执行 → 四层合并输出 → 聚合层拼图出全局叙事结构。

> **版本声明（决策 22：三版本域解耦）**：
> - **skill version** = `3.6.0`（本文件 frontmatter = README = RUNBOOK）。v3.6 原子化扩展字段（ADR-014，T-035）：annotation schema 2.9.0→2.10.0，新增 5 个可选字段（D07._narrator_identity / D08._time_type / D08._narrative_level / D06._techniques / D12_narrative_mode），全部可选允许 null，旧产物零迁移；v3.5 精细化切分器/重排（ADR-014，T-034）；v3.4 前置双模块（ADR-014，T-033）；v3.3 DLUT 完整引入（ADR-013，T-032）；v3.2 一致性基础设施（ADR-012，T-031）；v3.1 词表手术（ADR-011，T-030）。
> - **annotation schema_version** = `2.10.0`（`references/schema.md` §一 = 批注 JSON `schema_version` = annotate_segment.py / examples/llm_wrapper.py）。v2.10.0 新增 5 个可选字段（D07._narrator_identity / D08._time_type / D08._narrative_level / D06._techniques / D12_narrative_mode），全部可选允许 null。**注意**：批注数据 schema 与 skill 版本解耦，skill 升 3.x 不代表批注字段变更。
> - **aggregation schema_version** = `3.0.0`（`references/aggregation-schema.md` = `scripts/aggregation/*.py`）。
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

### 3.1.5 Phase 1.5：精细化切分重排（v3.5 新增，LumberChunker 思想 Skill 化）

> **定位**：Phase 1 粗切分按章节+2000 token 机械切分，可能把同一场景切成多段、或把不同场景塞进同一段。本阶段用 Agent 自身 LLM 做**场景边界判断**（只标记不切分），再由纯脚本 `reshape_segments.py` 按边界点从原文按字符位置重切，输出场景级 final_segments。

**四阶段流程**：
```
Phase 1 粗切分（preprocess.py）→ Phase 1.5a 场景边界判断（Agent LLM）→ Phase 1.5b 后处理重排（reshape_segments.py）→ Phase 2 精细批注（annotate_segment.py，不变）
```

**Phase 1.5a：场景边界判断（Agent 用自身 LLM 执行，输出 scene_boundary.json）**

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

### 3.4 Phase 4/5：合并 + 报告

```bash
python scripts/merge_layers.py --doc-id <doc_id> --segments <out>/{doc_id}_segments.jsonl
# 产出 {doc_id}_merged.jsonl：同段 L1/L2/L2.5/L3 + cross_refs 投影嵌套（schema.md §六 Merged）

python scripts/render_report.py --doc-id <doc_id> --format md   # 或 html（默认）
# 产出 {doc_id}_report.md/.html：结构全景 + L2/L3 摘要 + L4 关系清单；零第三方依赖内联样式
```

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

**批注管"逐段信号"，聚合管"全书拼图"**。聚合层把 L1-L4 批注（+D19/D15/D18 细粒度信号）组装成全局叙事图，供生成侧 / 叙事分析直接消费。8 个脚本纯规则零第三方依赖，全链路 <2s/本。

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
# ⑤ 因果链（cross_segment 关系 → CAUSE/ENABLE 边）
python $AGG/causal_graph.py --cross-segment <out>/{doc_id}_cross_segment.jsonl --structure <out>/{doc_id}_structure.jsonl \
    --doc-id <doc_id> --output-dir <out>/aggregation
# ⑥ 物件链（D15 意象聚类 → object_chains）
python $AGG/object_chains.py --craft <out>/{doc_id}_craft.jsonl --doc-id <doc_id> --output-dir <out>/aggregation
# ⑦ 故事图合并（五子图谱 + story_metadata → story_graph.json）
python $AGG/story_graph.py --aggregation-dir <out>/aggregation --doc-id <doc_id> --output-dir <out>/aggregation
# ⑧ 适配器（story_graph → text2story / YARN / NCP 三种叙事格式）
python $AGG/adapters.py --story-graph <out>/aggregation/{doc_id}_story_graph.json \
    --doc-id <doc_id> --output-dir <out>/aggregation/adapters --formats text2story,yarn,ncp
```

**产物依赖链**：①②③④⑥ 只依赖批注层 JSONL；⑤ 依赖 cross_segment；⑦ 依赖①-⑥全部；⑧ 依赖⑦。失败/缺输入时各脚本自行报错退出，可逐脚本重跑（覆盖写，幂等）。

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
| **聚合层 Schema 完整定义（唯一真源）** | `references/aggregation-schema.md` | 跑/改 `scripts/aggregation/` 8 脚本或消费聚合产物前 |
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
| **3.3.0** | 2026-09-05 | **DLUT 完整引入（ADR-013，T-032）**：①新建 `scripts/build_dlut_subset.py`——从本地全量 xlsx（27,465 词）按文学精读适配规则清洗（词性 adj/verb/noun/adv + 词长 ≤2 + 义项合并），生成 `references/lexicon-dlut-subset.json`（9,924 词，含来源/许可/引用声明，随包分发，D19 命中率 33/50 与全量一致）；②新建 `references/emotion-taxonomy.md`——DLUT 21 小类 → Plutchik 8 基元 → D19 词位三级映射表（NN/NM 双认 + NG 归类注记，词表演化归约裁决表）；③`scripts/lexicon_crosscheck.py` 升级 v3.3——**默认读仓库内子集**（--subset），子集缺失回退本地全量 xlsx（--dlut），NRC 文件缺失自动跳过抽样（降级不报错），一般使用者无需任何外部数据即可跑词表演化工具；④README §八.3 重写（子集已分发 + 维护者才需全量 + NRC 仍禁再分发）。 |
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
