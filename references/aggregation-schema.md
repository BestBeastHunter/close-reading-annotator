# references/aggregation-schema.md — 全局聚合层产物 Schema 定义 v3.0.0

> **本文件是聚合层产物的唯一真源**（对应审计 P2-12 / 决策 22）。
> 批注四层 Schema 的真源是 `references/schema.md`（v2.9.0）；聚合层（v2.9/v3.0）产物 Schema 以本文件为准。
> 聚合脚本 `scripts/aggregation/*.py` 的 `SCHEMA_VERSION` 统一为 `3.0.0`。
> 字段以两本实测书（月亮与六便士 / 上海堡垒）的真实产物为基准整理，修订字段必须先改本文件再改脚本。

---

## 〇、版本与命名约定

- 聚合产物文件名：`{doc_id}_{entity_graph|scene_graph|character_arcs|story_metadata|causal_graph|object_chains|story_graph}.json`，适配器产物 `{doc_id}_{text2story|yarn|ncp}.json`。
- 所有产物顶层含 `doc_id` / `schema_version` / `generated_at`（ISO8601）。
- 确定性纪律（v3.0.1）：任何集合转列表必须 `sorted(set(...))`；平票取先出现者——禁止依赖 `set()` 迭代顺序（PYTHONHASHSEED 漂移，审计 P2-3）。

---

## 一、entity_graph.json（实体图谱，v2.9 Step 1 / entity_resolution.py）

| 键 | 类型 | 说明 |
|----|------|------|
| `doc_id` / `schema_version` / `generated_at` | string | 顶层元数据 |
| `total_entities` | int | 实体总数 |
| `total_mentions` | int | 全部提及次数合计 |
| `entities[]` | array | 实体列表（按 occurrence_count 降序） |
| `_metadata` | object | `method=rule_based_v2_9` / name_seed_source / pronoun_resolution / alias_merge_threshold |

`entities[]` 字段：

| 键 | 类型 | 说明 |
|----|------|------|
| `entity_id` | string | `entity_{NNN}`（001 起） |
| `canonical_name` | string | 规范名（最高频指称） |
| `aliases` | string[] | 别名（不含 canonical） |
| `gender` | string | male / female / unknown（规则推断，可能不准） |
| `first_segment` / `last_segment` | string\|null | 首/末出场段 ID |
| `segment_count` | int | 出场段数 |
| `segment_ids` | string[] | **v3.0.1 新增**：完整出场段集合（修复 P1-2 出场角色截断的根） |
| `occurrence_count` | int | 总提及次数 |
| `proper_noun_count` / `pronoun_count` | int | 专名/代词提及计数 |
| `mentions_sample` | array | 前 20 条提及样本（`{segment_id,text,span,type,entity_id,confidence}`） |

> 已知限制：`entity_graph` 的提取目标即角色指称（D19.target / D18.character / 原文人名 NER），非人物实体（地点/意象误入）属消解质量问题，不在此层兜底。

---

## 二、scene_graph.json（场景图，v2.9 Step 2 / scene_graph.py）

| 键 | 类型 | 说明 |
|----|------|------|
| `total_scenes` / `total_segments` | int | 场景数 / 段数 |
| `avg_segments_per_scene` | float | 平均每场景段数 |
| `scenes[]` | array | 场景列表（按起始段序） |
| `_metadata` | object | merge_criteria / boundary_functions / note |

`scenes[]` 字段：

| 键 | 类型 | 说明 |
|----|------|------|
| `scene_id` | string | `scene_{NNN}` |
| `start_segment` / `end_segment` | string | 起止段 ID |
| `start_index` / `end_index` | int | 起止段在全书中的序号 |
| `segments` | string[] | 场景包含的段 ID 列表 |
| `time_labels` / `space_labels` | string[] | D08 时间/空间标记聚合 |
| `function_sequence` | string[] | D01 功能序列 |
| `intensity_values` | int[] | D04 强度序列 |
| `segment_count` | int | 段数 |
| `primary_time` / `primary_space` | string\|null | 时间/空间主标记（labels 首项；可为 null） |
| `primary_function` | string\|null | 功能众数（v3.0.1 平票取先出现者，确定性） |
| `avg_intensity` / `max_intensity` | float\|null | 强度统计 |
| `characters_present` | array | 出场角色（见下） |

`characters_present[]`：`{entity_id, name, mention_count_in_scene}`，按 mention_count 降序。
> v3.0.1 修复（P1-2）：出场角色优先取 `entity.segment_ids`（完整段集合），旧产物回退 `mentions_sample` + 原文别名匹配——不再依赖截断 20 条采样。

---

## 三、character_arcs.json（角色弧线，v2.9 Step 3 / character_arcs.py）

| 键 | 类型 | 说明 |
|----|------|------|
| `total_characters` / `total_trajectory_points` | int | 角色数 / 弧线点数合计 |
| `character_arcs[]` | array | 角色弧线列表（按 coverage_rate 降序） |

`character_arcs[]` 字段：

| 键 | 类型 | 说明 |
|----|------|------|
| `entity_id` / `canonical_name` / `aliases` | string | 实体标识 |
| `gender` | string | 性别（同上） |
| `total_segments_present` | int | 出场段数（= segment_count） |
| `trajectory_length` | int | 弧线点数（v3.0.1 对齐：原名 trajectory_point_count 不存在） |
| `coverage_rate` | float | 出场段数 / 全书段数 |
| `first_segment` / `last_segment` | string | 首末出场段 |
| `avg_intensity` / `max_intensity` / `min_intensity` | float | 强度统计 |
| `avg_polarity` | float | 极性均值（positive=1/negative=-1/neutral=0/mixed=0） |
| `d19_coverage` / `d04_coverage` | float | 有 D19/D04 数据的段占比 |
| `arc_classification` | object | `{arc_type, confidence, description, trend_score, variance, final_polarity, final_intensity}`；arc_type ∈ 波动（起伏弧线）/ 悲剧弧线 / 喜剧弧线 / 稳定 / insufficient_data 等 |
| `key_moments` | array | 关键时刻（首/最高/最低强度点） |
| `trajectory_sample` | array | 弧线点（`{segment_id, segment_index, emotion_source, emotion, intensity, polarity, target, has_arc_shift}`）——v3.0.1 对齐：原名 trajectory（全量点）不存在，只有采样 |

> v3.0.1 修复（P2-1）：出场段优先 `segment_ids`；回退阈值从 `< segment_count * 0.5` 改为 `< segment_count`（原阈值让中等角色采样过半即不回退 → coverage_rate 虚高）。

---

## 四、story_metadata.json（故事类型推断，v2.9 Step 4 / story_type_inference.py）

| 键 | 类型 | 说明 |
|----|------|------|
| `story_metadata` | object | 六维推断结果（见下） |
| `summary` | object | `{one_line}` 一行摘要 |
| `_metadata` | object | method / evidence 说明 |

`story_metadata` 六维：

| 键 | 类型 | 说明 |
|----|------|------|
| `genre` | object | `{primary, secondary[], confidence, evidence, genre_scores{}}`——关键词来自 **GENRE_KEYWORDS（v3.0.1 已去书名化，T-029 P2-4）** |
| `narrative_style` | object | `{type, is_reliable(bool\|null), is_linear, confidence, evidence, perspective_distribution{}}`——v3.0.1 修复：无可靠性标注时 `is_reliable=None`（不再默认 True） |
| `time_structure` | object | 时间结构（顺叙/倒叙/插叙/多线并行等） |
| `emotion_arc` | object | `{pattern, emotion_path[], start_polarity, end_polarity, trend_score, variance, peak_intensity, peak_segment}` |
| `pace` | object | `{type, avg_intensity, variance}`（快慢节奏） |
| `reader_experience` | object | `{primary, secondary[], confidence}`（阅读体验） |

---

## 五、causal_graph.json（因果链，v3.0 Step 4 / causal_graph.py）

| 键 | 类型 | 说明 |
|----|------|------|
| `causal_graph` | object | `{nodes[], edges[], chains[]}` |
| `statistics` | object | `{total_edges, cause_edges, enable_edges, prevent_edges, total_chains, max_chain_length, filtered_edges}` |
| `_metadata` | object | 边生成规则说明 |

- `nodes`：`sorted(set(...))`（v3.0.1 确定性修复）——参与因果的段 ID 列表
- `edges[]`：`{edge_id, edge_type(CAUSE/ENABLE/PREVENT), source{segment_id,chapter,d01_function,anchor_text}, target{...}, confidence, evidence{source_ref_id, relation_type, note}, validation}`
- `chains[]`：`{chain_id, length, start_segment, end_segment, start_d01, end_d01, edge_types[], segments[]}`

> 生成规则：cross_segment 中"因果"→CAUSE、"伏笔-回收"→ENABLE；D01 仅在**校验端**过滤反向边/孤立边（决策 C 修正：D01 不进生成端）。

---

## 六、object_chains.json（物件链，v3.0 Step 5 / object_chains.py）

| 键 | 类型 | 说明 |
|----|------|------|
| `object_chains[]` | array | 物件链列表 |
| `statistics` | object | `{total_chains, total_appearances, top_objects[]}` |
| `_metadata` | object | 聚类方法说明 |

`object_chains[]` 字段：

| 键 | 类型 | 说明 |
|----|------|------|
| `chain_id` | string | `oc_{NNNN}` |
| `object_name` | string | 最高频文本（Counter most_common） |
| `object_type` | string | D15.type 众数 |
| `cluster_labels` | string[] | `sorted(set(...))`（v3.0.1 确定性） |
| `occurrence_count` | int | 出现次数 |
| `first_appearance` / `last_appearance` | object | `{segment_id, chapter, text}` |
| `appearances` | array | 逐条出现记录 |
| `segments` / `chapters` | string[] | 段/章集合（chapters 为 v3.0.1 sorted） |
| `semantic_shift` | object | `{has_shift, distinct_texts[]}`——**已知局限**（P2-8）：`has_shift` 只判 text 是否变化，表述差异≠语义演变，会高报；下游消费需明示 |
| `lifecycle_span` | object | `{start_segment, end_segment, segment_count}` |

---

## 七、story_graph.json（故事图合并，v3.0 Step 6.1 / story_graph.py）

| 键 | 类型 | 说明 |
|----|------|------|
| `doc_id` / `schema_version` / `generated_at` | string | 顶层元数据 |
| `story_graph` | object | 合并后的核心图（见下） |
| `story_metadata` | object\|null | 透传 story_metadata.json 的 `story_metadata` |
| `story_summary` | object\|null | 透传 `summary` |
| `global_statistics` | object | `{subgraphs_loaded, subgraphs_missing[], total_entities, total_scenes, total_characters, total_causal_edges, total_object_chains}` |
| `_metadata` | object | `method=assembly_v3_0` / subgraph_sources |

`story_graph` 内层：

| 键 | 类型 | 来源 |
|----|------|------|
| `entities` + `entity_statistics` | array + object | entity_graph |
| `scenes` + `scene_statistics` | array + object | scene_graph |
| `character_arcs` + `character_arc_statistics` | array + object | character_arcs |
| `causal_edges` / `causal_chains` / `causal_statistics` | array/object | causal_graph（edges/chains/statistics） |
| `object_chains` / `object_chain_statistics` | array/object | object_chains |

---

## 八、适配器产物（v3.0 Step 6.2-6.4 / adapters.py）

三种格式均从 story_graph.json 转换，`schema_version=3.0.0`。

### 8.1 text2story.json（{doc_id}_text2story.json）

| 键 | 类型 | 来源映射 |
|----|------|----------|
| `participants[]` | array | entity_graph.entities → `{id, name, type=PER, aliases, mention_count, segment_count}`——**type 恒 PER**（entity_graph 语义即角色；v3.0.1 修复，不再有 ORG 误标） |
| `events[]` | array | scene_graph.scenes → `{id, class=Event, text="{primary_function}（{start}~{end}）", tense=primary_time‖time_labels[0]‖"未知", participants=characters_present 的 name 列表, start_segment, end_segment, function_sequence}` |
| `times[]` | array | scenes 去重 primary_time → `{id, text, type=DATE, anchored_to}` |
| `places[]` | array | scenes 去重 primary_space → `{id, text, type=LOC, anchored_to}` |
| `statistics` | object | participant_count / event_count / time_count / place_count |

### 8.2 yarn.json（{doc_id}_yarn.json）

| 键 | 类型 | 来源映射 |
|----|------|----------|
| `event_chain[]` | array | scenes → `{event_id, label=primary_function, order, start_segment, end_segment, duration_segments=segment_count, location=primary_space, time=primary_time}` |
| `rhetorical_relations[]` | array | causal_edges → `{relation_id, type(CAUSE→cause/ENABLE→enablement/PREVENT→prevention/其他→elaboration), source_event, target_event, confidence, evidence}` |
| `object_threads[]` | array | object_chains → `{thread_id, object_name, object_type, occurrences, segments}` |
| `statistics` | object | event_count / relation_count / object_thread_count |

### 8.3 ncp.json（{doc_id}_ncp.json）

| 键 | 类型 | 来源映射 |
|----|------|----------|
| `characters[]` | array | character_arcs → `{character_id, name, arc_type=arc_classification.arc_type, trajectory_points=trajectory_length, coverage_rate, first_appearance, last_appearance, emotional_trajectory=trajectory_sample 前10点{segment_id,emotion,intensity,polarity}, gender, d19_coverage}` |
| `events[]` | array | causal_edges → `{event_id, source_segment, target_segment, causal_type, source_function, target_function, confidence}` |
| `settings[]` | array | scenes → `{setting_id, location=primary_space, time=primary_time, start_segment, end_segment, segment_count}` |
| `plot_structure` | object | scenes 按 primary_function 映射七桶：`{exposition(背景铺垫), inciting_incident(激励事件), rising_action(上升行动), climax(高潮), falling_action(下降行动), resolution(结局), transition(过渡)}`——桶内为场景条目；无对应功能的桶合法为空（数据特性） |
| `story_metadata` | object | story_graph.story_metadata → `{genre.primary, narrative_style.type, emotion_arc.pattern, pace.type, reader_experience.primary, one_line_summary}` |
| `statistics` | object | character_count / event_count / setting_count |

---

*聚合层 Schema 唯一真源。改字段先改本文件，再同步 `scripts/aggregation/*.py` 与审计验收脚本。*
