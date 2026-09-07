# references/aggregation-schema.md — 全局聚合层产物 Schema 定义 v3.6.0

> **本文件是聚合层产物的唯一真源**（对应审计 P2-12 / 决策 22）。
> 批注四层 Schema 的真源是 `references/schema.md`（v2.10.0）；聚合层（v2.9/v3.0/v3.7）产物 Schema 以本文件为准。
> 聚合脚本 `scripts/aggregation/*.py` 的 `SCHEMA_VERSION`：entity/scene/story_type/object/story_graph/adapters = `3.0.0`；narrative_structure = `3.1.0`（v3.7 新增）；causal_graph/character_arcs = `3.5.0`（v3.13.1 新增事件/人物分析增强字段）。
> 字段以两本实测书（月亮与六便士 / 上海堡垒）的真实产物为基准整理，修订字段必须先改本文件再改脚本。

---

## 〇、版本与命名约定

- 聚合产物文件名：`{doc_id}_{entity_graph|scene_graph|character_arcs|story_metadata|narrative_structure|writing_techniques|causal_graph|object_chains|event_sequence|character_network|character_biographies|story_graph}.json`，适配器产物 `{doc_id}_{text2story|yarn|ncp}.json`。
- 所有产物顶层含 `doc_id` / `schema_version` / `generated_at`（ISO8601）。
- 确定性纪律（v3.0.1）：任何集合转列表必须 `sorted(set(...))`；平票取先出现者——禁止依赖 `set()` 迭代顺序（PYTHONHASHSEED 漂移，审计 P2-3）。
- **v3.1.0 变更（ADR-014，T-036/T-037）**：新增 `narrative_structure.json`（叙事结构分析，v3.7）和 `writing_techniques.json`（叙事技法分析，v3.8）两个产物。其余 8 个聚合产物 schema 不变（3.0.0）。
- **v3.6.0 变更（v3.18.0，事件序列产物 + 文档补齐）**：①新增 `event_sequence.json`（全书事件表，event_sequence.py）——以运行时便签本 scratchpad.events 为主序，对齐因果图（hierarchy/salience/causal_structure/因果边）、场景图（scene_id）、结构层（D01/D08）、实体图（在场人物）；含按段序事件列表 + statistics（核心/卫星/转折统计 + top 显赫度）；②补齐 `character_network.json`（§十二，schema 3.2.0）与 `character_biographies.json`（§十三，schema 3.3.0）两章文档（此两产物自 v3.17.0 起纳入必须链，文档此前缺失）。其余聚合产物 schema 不变。
- **v3.5.0 变更（ADR-029，T-111/T-112）**：`causal_graph.json` 新增 event_hierarchy（核心/卫星事件+salience_score显赫度评分）、causal_structure（causal_type直接/间接/条件+is_turning_point）、event_attributes（时间/空间/情感/参与者/叙事功能/强度）；`character_arcs.json` 新增 character_type（扁平/圆形/尖形+complexity_score复杂度评分）、character_depth（不可还原特质+文本空白数）、agency_curve（能动性曲线+agency_distribution+agency_trend）、density_distribution（出现密度分布+peak_interval+peak_density）、dialogue_dominance（对话主导权+dominance_ratio+dominance_level+言说动词分布）。其余聚合产物 schema 不变。

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

## 九、narrative_structure.json（叙事结构分析，v3.7 新增 / narrative_structure.py）

> **定位**：基于逐段 structure 批注的全局叙事结构推导，纯规则引擎零 LLM 调用。依赖 v3.6 原子化扩展字段（D08._time_type / D08._narrative_level / D07._narrator_identity），旧产物缺失时自动降级为从 D01/D07/D08 原始字段推断，输出中标注 `derivation_method`。

| 键 | 类型 | 说明 |
|----|------|------|
| `doc_id` / `schema_version` / `generated_at` / `generator` / `total_segments` | 顶层元数据 | schema_version=3.1.0 |
| `freytag_pyramid` | object | 弗雷塔格五幕结构（见 9.1） |
| `genette_focalization` | object | 热奈特聚焦分析（见 9.2） |
| `narrative_timeline` | object | 叙事时间线重建（见 9.3） |
| `save_the_cat_beats` | object | 救猫咪节拍定位（简化 14 节拍，见 9.4） |
| `narrative_levels` | object | 叙事层级图（见 9.5） |

### 9.1 freytag_pyramid（弗雷塔格五幕）

| 键 | 类型 | 说明 |
|----|------|------|
| `total_segments` | int | 输入 segment 总数 |
| `act_ranges` | object | 六幕区间：`exposition` / `inciting_incident` / `rising_action` / `climax` / `falling_action` / `resolution`，每幕含 `start_segment` / `end_segment` / `segment_count_in_range` / `segment_count_labeled` / `percentage` |
| `key_turning_points` | object | `inciting_incident_segment` / `climax_segment` / `resolution_segment`（首次出现位置） |
| `missing_acts` | string[] | 缺失的幕（如 `["inciting_incident"]`） |
| `structure_health` | string | `healthy` / `needs_review`（上升行动占比≥20% 且缺失幕≤1 为 healthy） |
| `derivation_method` | string | `D01_sequence_mapping + act_transition_points` |
| `note` | string | 区间按幕转换点定义（非连续块统计）；segment_count_labeled 是该幕标签实际出现次数 |

### 9.2 genette_focalization（热奈特聚焦）

| 键 | 类型 | 说明 |
|----|------|------|
| `dominant_d07_type` | string | 主导 D07 视角类型（如 "第一人称"） |
| `dominant_focalization` | string | 热奈特聚焦类型：`first_person_focalization` / `second_person_focalization` / `internal_focalization` / `zero_focalization` / `variable_focalization` / `unreliable_focalization` / `external_focalization` |
| `d07_type_distribution` | object | D07.type 统计分布 |
| `focalization_switch_count` / `focalization_switch_rate` | int / float | 视角切换次数 / 切换率（switch_count/total） |
| `complexity` | string | `simple_single_focalization`（主导占比≥95%且无切换）/ `moderate_occasional_shift`（主导占比≥80%且切换率≤10%）/ `complex_multiple_focalization` |
| `narrator_reliability` | string | `unreliable`（不可靠叙述者占比>10%）/ `reliable_or_not_marked` |
| `narrator_identity_distribution` / `narrator_identity_count` | object / int | **v3.6 新字段**：叙述者身份分布（仅当 _narrator_identity 填充时存在） |
| `narrator_identity_note` | string | 旧产物缺失 _narrator_identity 时的降级说明 |
| `derivation_method` | string | `D07_type_statistics` 或 `D07_type_statistics+_narrator_identity` |

### 9.3 narrative_timeline（叙事时间线）

| 键 | 类型 | 说明 |
|----|------|------|
| `dominant_time_type` | string | 主导时间类型：`linear` / `flashback` / `flashforward` / `analepsis` / `prolepsis` / `unknown` |
| `time_type_distribution` | object | time_type 统计分布 |
| `time_structure` | string | `linear_simple`（无非线性且无跳跃）/ `linear_with_occasional_flashback`（非线性占比≤15%且跳跃≤2）/ `complex_nonlinear` |
| `time_jump_count` / `time_jumps` | int / array | 时间跳跃次数 / 跳跃详情（`from_segment` / `to_segment` / `year_span` / `from_year` / `to_year`，最多 10 条） |
| `timeline_nodes` | array | 时间线节点列表（每段一个：`segment_index` / `segment_id` / `time_text` / `time_type` / `time_marker{year,season,period,relative}`） |
| `derivation_method` | string | `_time_type_field`（新字段填充时）/ `D08.time_text_keyword_inference（降级：_time_type 字段未填充）` |

### 9.4 save_the_cat_beats（救猫咪节拍，简化 14 节拍）

| 键 | 类型 | 说明 |
|----|------|------|
| `beats` | array | 14 节拍列表：`opening_image` / `theme_stated` / `setup` / `catalyst` / `debate` / `break_into_two` / `fun_and_games` / `midpoint` / `bad_guys_close_in` / `all_is_lost` / `dark_night_of_soul` / `break_into_three` / `finale` / `final_image`，每拍含 `beat_id` / `beat_name` / `start_segment` / `end_segment` / `percentage_range` / `dominant_d01` / `avg_d05_pace` / `segment_count` |
| `key_beats_with_strong_signal` | string[] | 关键节拍（catalyst/midpoint/all_is_lost/finale）中区间内存在对应 D01 信号的节拍 ID |
| `key_beats_total` | int | 关键节拍总数（恒为 4） |
| `beat_completeness` | float | 关键节拍信号匹配率（0-100%） |
| `derivation_method` | string | `position_percentage_mapping + D01_signal_verification` |
| `note` | string | 救猫咪节拍为基于位置百分比的粗略定位，非精确节拍检测；需结合 D01 信号验证 |

### 9.5 narrative_levels（叙事层级图）

| 键 | 类型 | 说明 |
|----|------|------|
| `level_distribution` | object | 叙事层级分布：`"1"`（故事层）/ `"2"`（元叙事）/ `"3+"`（多层嵌套）/ `unknown` |
| `dominant_level` | string | 主导叙事层级 |
| `derivation_method` | string | `_narrative_level_field`（新字段填充时）/ `field_not_filled（降级：_narrative_level 未填充，无法分析叙事层级）` |
| `note` | string | 旧产物缺失 _narrative_level 时的降级说明；建议用 v3.6+ 重新批注后再分析 |

---

## 十、writing_techniques.json（叙事技法分析，v3.8 新增 / writing_techniques.py）

> **定位**：基于逐段 structure/interpretation 批注 + cross_segment 关系的全局叙事技法模式识别，纯规则引擎零 LLM 调用（同因果链"规则粗筛+LLM精排"架构）。4 子模块：转场技巧 / 悬念设置 / 蒙太奇手法 / 钩子类型，加综合技法评估。

| 键 | 类型 | 说明 |
|----|------|------|
| `doc_id` / `schema_version` / `generated_at` / `generator` / `total_segments` | 顶层元数据 | schema_version=3.1.0 |
| `transitions` | object | 转场技巧分析（见 10.1） |
| `suspense` | object | 悬念设置分析（见 10.2） |
| `montage` | object | 蒙太奇手法分析（见 10.3） |
| `hooks` | object | 钩子类型分析（见 10.4） |
| `overall_assessment` | object | 综合技法评估（见 10.5） |

### 10.1 transitions（转场技巧）

| 键 | 类型 | 说明 |
|----|------|------|
| `total_transitions` | int | 转场总次数 |
| `time_transitions` | int | 时间转场次数（年份差≥2 或季节变化） |
| `space_transitions` | int | 空间转场次数（地点关键词变化） |
| `detail_transitions` | int | 细节过渡次数（背景铺垫→过渡→上升行动） |
| `suspense_transitions` | int | 悬念转场次数（高潮/转折→下降/背景硬切） |
| `transition_density` | float | 转场密度（total/(segments-1)） |
| `transitions` | array | 转场详情（最多 50 条，每条含 from/to segment_id + transition_types[]） |
| `truncated` | bool | 详情是否被截断 |

### 10.2 suspense（悬念设置）

| 键 | 类型 | 说明 |
|----|------|------|
| `total_hidden_segments` | int | D06 隐藏段总数 |
| `setup_questions_count` | int | 设疑法次数（D06 隐藏 + content 含疑问词） |
| `serial_suspense_count` | int | 连环设悬次数（连续≥3 段隐藏） |
| `unresolved_suspense_count` | int | 悬念留白次数（隐藏后 5 段内无揭示） |
| `foreshadow_payoff_pairs` | int | 伏笔-回收对数（cross_refs relation_type=伏笔-回收） |
| `suspense_intensity` | string | `low` / `moderate` / `high` |
| `setup_questions` | array | 设疑法详情（最多 20 条） |
| `serial_suspense_runs` | array | 连环设悬详情（最多 10 条） |
| `unresolved_suspense` | array | 悬念留白详情（最多 20 条） |
| `foreshadow_pairs_detail` | array | 伏笔-回收对详情（最多 20 条） |
| `derivation_method` | string | `D06_hide_pattern_sequence + cross_refs_foreshadow_payoff` |

### 10.3 montage（蒙太奇手法）

| 键 | 类型 | 说明 |
|----|------|------|
| `parallel_montage_count` | int | 平行蒙太奇次数（5 段窗口内地点变化≥3） |
| `cross_montage_count` | int | 交叉蒙太奇次数（D05≥4 且 D01 在上升/高潮/转折间≤3 段内切换≥2） |
| `contrast_montage_count` | int | 对比蒙太奇次数（相邻段 D04 polarity 相反且 intensity≥5） |
| `total_montage_instances` | int | 蒙太奇总次数 |
| `montage_density` | float | 蒙太奇密度（total/segments） |
| `parallel_montage` | array | 平行蒙太奇详情（最多 20 条，含 start/end segment_index + location_changes） |
| `cross_montage` | array | 交叉蒙太奇详情（最多 20 条） |
| `contrast_montage` | array | 对比蒙太奇详情（最多 20 条） |
| `derivation_method` | string | `sliding_window_location_change + D01_D05_sequence_pattern + D04_polarity_contrast` |

### 10.4 hooks（钩子类型）

| 键 | 类型 | 说明 |
|----|------|------|
| `total_hooked_segments` | int | 含钩子的段总数（去重） |
| `suspense_hooks_count` | int | 悬念钩子数（段尾 D06 隐藏 或 D01=转折） |
| `action_hooks_count` | int | 行动钩子数（D05≥4 或 D01=高潮） |
| `emotion_hooks_count` | int | 情感钩子数（D04 intensity≥7） |
| `scene_hooks_count` | int | 场景钩子数（段首地点关键词与上段不同） |
| `hook_density` | float | 钩子密度（total/segments） |
| `suspense_hook_segments` / `action_hook_segments` / `emotion_hook_segments` / `scene_hook_segments` | array | 各类钩子的段 ID 列表（各最多 30 条） |
| `derivation_method` | string | `segment_tail_D01_D04_D05_D06 + segment_head_location_keyword_change` |

### 10.5 overall_assessment（综合技法评估）

| 键 | 类型 | 说明 |
|----|------|------|
| `total_technique_instances` | int | 技法实例总数（transitions + suspense + montage + hooks） |
| `technique_density_per_segment` | float | 每段技法密度（total/segments） |
| `writing_style` | string | `技法密集型（高技巧写作）`（密度≥3.0）/ `技法均衡型（标准叙事）`（密度≥1.5）/ `技法简约型（白描风格）`（密度<1.5） |
| `dominant_techniques` | array | 主导技法排序（按实例数降序，如 `["hooks", "transitions", "montage", "suspense"]`） |
| `note` | string | 规则粗筛结果，后续可用 LLM 精排（同因果链架构） |

---

*聚合层 Schema 唯一真源。改字段先改本文件，再同步 `scripts/aggregation/*.py` 与审计验收脚本。*


---

## 十一、event_sequence.json（全书事件序列，v3.6.0 新增 / event_sequence.py）

> **定位**：把散落在批注层与 scratchpad 的事件碎片按段序组装成**全书事件表**——每事件含叙事层级（核心/卫星）、显赫度、因果边、场景归属、参与者与在场人物，供报告"事件序列"章节与下游消费。主数据源为运行时便签本 `{doc_id}_scratchpad.json` 的 events（真实事件描述/参与者/类型/状态）；scratchpad 缺失或为空时降级用 `causal_graph.json` 的段级事件节点。

### 11.1 顶层结构

```json
{
  "doc_id": "my_novel_01",
  "schema_version": "3.6.0",
  "generated_at": "2026-09-07T10:00:00+08:00",
  "total_events": 19,
  "event_sequence": [ { "event_id": "evt_001", "..." : "..." } ],
  "statistics": { "...": "..." },
  "_metadata": { "skill_version": "3.18.0", "event_source": "scratchpad" }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `doc_id` | string | 文档 ID |
| `schema_version` | string | `3.6.0` |
| `generated_at` | string | ISO8601 生成时间 |
| `total_events` | int | 事件总数（= event_sequence 长度） |
| `event_sequence` | array | 事件列表，按 `segment_id` 段序排列 |
| `statistics` | object | 聚合统计（见 11.3） |
| `_metadata` | object | 生成元信息：`skill_version` / `event_source`（`scratchpad` 或 `causal_graph_nodes_fallback`） |

### 11.2 单个事件（event_sequence[] 元素）

| 字段 | 类型 | 说明 |
|------|------|------|
| `event_id` | string | 事件 ID（来自 scratchpad：`evt_001` 递增；降级模式：`evt_<segment>_<idx>`） |
| `segment_id` | string | 事件所在段 ID（场景级 `{doc_id}_scene_NNN` 或段级 `{doc_id}_seg_NNNN`） |
| `description` | string | 一句话事件描述（scratchpad 原文；降级模式由段内事件节点拼装） |
| `event_type` | string | 事件类型（scratchpad 记录；降级模式从 D01 映射） |
| `status` | string | `open`（未闭合）/ `closed`（已闭合），来自 scratchpad |
| `d01_function` | string | 叙事功能（优先 structure 层 D01；回落 causal_graph 节点 d01_function） |
| `time` | string / null | 事件时间（structure 层 D08.time） |
| `space` | string / null | 事件空间（structure 层 D08.space） |
| `scene_id` | string / null | 场景归属（scene_graph 反查：事件段所属场景） |
| `participants` | array | 参与者规范名列表（scratchpad involved_characters 经 entity_graph 别名→规范名归一） |
| `present_characters` | array | 段内在场人物规范名（entity_graph 的 segment_ids 反推，补 scratchpad 参与者覆盖不足） |
| `hierarchy` | object | 叙事层级（见 11.2.1；causal_graph 对齐） |
| `causal` | object | 因果结构（见 11.2.2；causal_graph 对齐） |
| `source` | string | 数据来源：`scratchpad` / `causal_graph_nodes_fallback` |

#### 11.2.1 hierarchy（叙事层级）

```json
"hierarchy": {
  "level": "卫星事件",
  "salience_score": 0.42,
  "salience_breakdown": { "d01_weight": 0.2, "length_weight": 0.15, "position_weight": 0.07 }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `level` | string | `核心事件` / `卫星事件`（causal_graph event_hierarchy.level 对齐） |
| `salience_score` | float | 事件显赫度 0-1（causal_graph event_hierarchy.salience_score 对齐） |
| `salience_breakdown` | object | 显赫度分项（可选）：d01_weight / length_weight / position_weight |

#### 11.2.2 causal（因果结构）

```json
"causal": {
  "causal_type": "直接因果",
  "is_turning_point": true,
  "in_edges": ["evt_001"],
  "out_edges": ["evt_005"]
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `causal_type` | string / null | 因果类型：`直接因果` / `间接因果` / `条件因果`（causal_graph 对齐） |
| `is_turning_point` | bool / null | 是否转折事件（causal_graph is_turning_point 对齐） |
| `in_edges` | array | 前驱事件 ID 列表（causal_graph 因果边入边） |
| `out_edges` | array | 后继事件 ID 列表（causal_graph 因果边出边） |

### 11.3 statistics（统计）

| 字段 | 类型 | 说明 |
|------|------|------|
| `core_event_count` | int | 核心事件数（hierarchy.level == 核心事件） |
| `satellite_event_count` | int | 卫星事件数 |
| `hierarchy_levels` | object | 各层级计数（如 `{"卫星事件": 11}`） |
| `turning_point_count` | int | 转折事件数（causal.is_turning_point == true） |
| `by_event_type` | object | 按事件类型计数 |
| `by_d01_function` | object | 按叙事功能计数 |
| `top_salience_events` | array | 显赫度 Top 10：`{event_id, description, segment_id, salience_score}` |

### 11.4 与上下游的关系

- 上游：scratchpad.events（主源）、structure 层（D01/D08）、causal_graph（层级/显赫度/因果边）、scene_graph（场景归属）、entity_graph（参与者归一 + 在场人物）。
- 下游：render_report 报告"事件序列"章节（MD `### 📅 事件序列` / HTML `h3 id="agg-events"`，前 15-20 条 + 统计）；story_graph 合并。
- 确定性纪律：participants / present_characters / in_edges / out_edges 均 `sorted(set(...))`；top_salience_events 按 salience_score 降序，平票按 event_id 字典序。

---

## 十二、character_network.json（人物关系网络，schema 3.2.0 / character_network.py）

> **定位**：基于 entity_graph 共现矩阵 + D19.target（情感对象）+ D18（对话关系），构建带关系类型和强度的人物关系网络。v3.17.0 起为必须链 ②（紧接 entity_resolution 之后）。纯规则引擎，零第三方依赖。

### 12.1 顶层结构

```json
{
  "doc_id": "my_novel_01",
  "schema_version": "3.2.0",
  "generated_at": "2026-09-07T10:00:00+08:00",
  "total_nodes": 41,
  "total_edges": 7,
  "nodes": [ { "id": "entity_001", "name": "亚历克斯", "centrality": 0.9, "occurrence_count": 6, "segment_count": 5 } ],
  "edges": [ { "edge_id": "rel_0001", "source": "entity_001", "target": "entity_002", "relation": "友情", "strength": 0.2, "cooccurrence": 5, "dialogue_count": 0, "emotion_mentions": 0 } ],
  "communities": [ { "community_id": "comm_001", "label": "友情", "members": ["亚历克斯", "丁姆"] } ],
  "generator": "character_network",
  "_metadata": { "method": "cooccurrence+D19+D18" }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `doc_id` | string | 文档 ID |
| `schema_version` | string | `3.2.0` |
| `generated_at` | string | ISO8601 生成时间 |
| `total_nodes` / `total_edges` | int | 节点/边总数 |
| `nodes` | array | 人物节点（见 12.2） |
| `edges` | array | 关系边（见 12.3） |
| `communities` | array | 社区分组（按关系类型聚类，见 12.4） |
| `generator` | string | 生成器标识 |
| `_metadata` | object | 生成元信息 |

### 12.2 nodes[]（人物节点）

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | string | 实体 ID（= entity_graph 实体 ID，如 `entity_001`） |
| `name` | string | 规范名 |
| `centrality` | float | 中心度 0-1（度数中心性归一） |
| `occurrence_count` | int | 提及总次数（来自 entity_graph occurrence） |
| `segment_count` | int | 出场段数 |

### 12.3 edges[]（关系边）

关系类型枚举（10 类）：`亲情` / `爱情` / `友情` / `战友` / `敌对` / `上下级` / `师徒` / `暗恋` / `合作` / `陌生`。

| 字段 | 类型 | 说明 |
|------|------|------|
| `edge_id` | string | 边 ID（`rel_0001` 递增） |
| `source` / `target` | string | 两端实体 ID |
| `source_name` / `target_name` | string | 两端规范名（便于阅读） |
| `relation` | string | 关系类型（枚举 10 类） |
| `strength` | float | 关系强度 0-1 = 共现频次(0.4) + 情感指向强度(0.3) + 对话频次(0.3) |
| `cooccurrence` | int | 共现次数（entity_graph 共现矩阵） |
| `dialogue_count` | int | 对话共现次数（D18） |
| `emotion_mentions` | int | 情感指向次数（D19.target 指向对方） |

### 12.4 communities[]（社区分组）

| 字段 | 类型 | 说明 |
|------|------|------|
| `community_id` | string | 社区 ID（`comm_001` 递增） |
| `label` | string | 社区标签（主导关系类型） |
| `members` | array | 成员规范名列表（`sorted(set(...))` 确定性排序） |

### 12.5 与上下游的关系

- 上游：entity_graph（节点/共现）、emotion 层 D19.target（情感指向）、craft 层 D18（对话关系）。
- 下游：character_biographies（关系维度）、story_graph 合并、报告"人物网络"章节。

---

## 十三、character_biographies.json（人物传记聚合，schema 3.3.0 / character_biographies.py）

> **定位**：把按时间顺序的逐段批注重新组织为以人物为中心的传记式分析——时间线/关键时刻/关键决策/关系/情感弧/性格/语言指纹/金句/综合评价，供报告与下游消费（如生成器角色设定）。v3.17.0 起为必须链 ⑪。纯规则引擎，零第三方依赖；`--max-biographies` 控制传记上限（默认 15）。

### 13.1 顶层结构

```json
{
  "doc_id": "my_novel_01",
  "schema_version": "3.3.0",
  "generated_at": "2026-09-07T10:00:00+08:00",
  "total_biographies": 5,
  "total_segments": 50,
  "biographies": [ { "character_id": "entity_001", "name": "亚历克斯", "..." : "..." } ],
  "generator": "character_biographies",
  "_metadata": { "method": "rule_based_v3_12", "main_character_threshold": 0.05, "max_biographies": 15 }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `doc_id` | string | 文档 ID |
| `schema_version` | string | `3.3.0` |
| `generated_at` | string | ISO8601 生成时间 |
| `total_biographies` | int | 传记数 |
| `total_segments` | int | 全书段数 |
| `biographies` | array | 传记列表（按人物出场段数降序，见 13.2） |
| `generator` | string | 生成器标识 |
| `_metadata` | object | 元信息：`main_character_threshold`（主要人物出场阈值，默认 0.05 = 出场段数 ≥ max(3, total*5%)）/ `max_biographies`（传记上限） |

### 13.2 biographies[]（单个人物传记）

| 字段 | 类型 | 说明 |
|------|------|------|
| `character_id` | string | 实体 ID（= entity_graph 实体 ID） |
| `name` | string | 规范名 |
| `aliases` | array | 别名列表（entity_graph 别名） |
| `biography` | object | 概要（见 13.2.1） |
| `timeline` | array | 时间线（见 13.2.2） |
| `key_moments` | array | 关键时刻（见 13.2.3） |
| `decision_points` | array | 关键决策（决策关键词规则，见 13.2.4） |
| `relationships` | array | 人物关系（character_network 对齐，见 13.2.5） |
| `emotional_arc` | object | 情感弧线（character_arcs 对齐） |
| `character_traits` | array | 性格特征（character_arcs.character_depth 对齐） |
| `voice_fingerprint` | object | 语言指纹（D18 聚合） |
| `key_quotes` | array | 金句（D13_golden_lines 按人物绑定） |
| `appearance_stats` | object | 出场统计（见 13.2.6） |
| `agency_curve` | array | 能动性曲线（character_arcs 对齐） |
| `dialogue_dominance` | object | 对话主导权（character_arcs 对齐） |
| `character_depth` | object | 人物深度（character_arcs 对齐：不可还原特质/文本空白） |
| `appreciation` | string | 规则生成的人物综合评价（见 13.2.7） |

#### 13.2.1 biography（人物概要）

| 字段 | 类型 | 说明 |
|------|------|------|
| `summary` | string | 一句话概括（规则模板："{name}，{role_in_story}，全书出场{N}段"） |
| `first_appearance` / `last_appearance` | string | 首现/末现段 ID |
| `total_segments` | int | 出场段数 |
| `role_in_story` | string | 角色定位（主角/配角等，按出场占比推断） |
| `character_type` | string | 扁平/圆形（character_arcs 对齐） |
| `complexity_score` | float | 复杂度 0-1 |
| `dynamic_static` | string | 动态/静态 |

#### 13.2.2 timeline（时间线）

按段序排列的人物事件序列，每项含：`segment_id` / `segment_index` / `chapter` / `event`（"{章节}：{D01 功能}"）/ `d01_function` / `emotion`（D19）/ `intensity` / `key_quote`（D13 绑定）/ `significance`（`high`/`medium`/`low`，按 D01 功能与情感强度映射）/ `has_dialogue`。

#### 13.2.3 key_moments（关键时刻）

| 字段 | 说明 |
|------|------|
| `type` | `climax` / `turning_point` / `inciting_incident` / `resolution` 等（按 D01 功能映射） |
| `segment_id` / `chapter` | 位置 |
| `description` | "{章节}：{D01 功能}" |
| `emotion` / `intensity` / `key_quote` | 该段情感/强度/绑定金句 |

#### 13.2.4 decision_points（关键决策）

规则识别：含决策关键词（决定/选择/必须/放弃/答应/拒绝 等）的段，标注 `segment_id` / `description` / `source`（`rule_keyword`）。

#### 13.2.5 relationships（人物关系）

| 字段 | 说明 |
|------|------|
| `target` | 关系对象规范名 |
| `relation` | 关系类型（10 类枚举） |
| `strength` | 强度 0-1（character_network 对齐） |
| `evidence_segments` | 证据段 ID 列表 |

#### 13.2.6 appearance_stats（出场统计）

| 字段 | 说明 |
|------|------|
| `segment_count` | 出场段数 |
| `presence_ratio` | 出场占比（= 出场段数 / 全书段数） |
| `first_appearance` / `last_appearance` | 首现/末现段 |

#### 13.2.7 appreciation（综合评价）

规则模板生成（v3.12.0 起为规则版，未来可升级 LLM 版）：

```
{name}是故事的{role_in_story}，{character_type}人物、{dynamic_static}发展。
全书出场{total_segments}段，情感轨迹由{起始情感}走向{终点情感}（{强度区间}）。
与{主要关系对象}的关系以{关系类型}为主（强度 {strength}）。
```

### 13.3 与上下游的关系

- 上游：segments / structure / interpretation / craft / emotion / cross_segment 批注层 + entity_graph（实体/别名）+ character_arcs（类型/弧线/深度/能动性/对话主导权）+ character_network（关系）+ narrative_structure（结构位置）。
- 下游：render_report 报告"人物传记"章节；story_graph 合并；V4 生成器"角色设定"输入。
- 确定性纪律：aliases / evidence_segments / relationships 均 `sorted(set(...))`；biographies 按出场段数降序，平票按 character_id 字典序。


---
