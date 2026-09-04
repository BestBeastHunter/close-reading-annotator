---
name: close-reading-annotator
version: 2.7.0
description: 对小说、剧本等叙事文本进行四层精读批注。输出结构层(叙事功能/情绪/节奏/视角/时空/对话功能/描写类型) + 阐释层(信息控制/主题/叙述者可靠性) + 情感层(角色情感/情感对象/段内情感弧，P4 触发式) + 文笔层(佳句/修辞/意象/词汇/句式/人物语言指纹) + 跨段层(伏笔链/段间关系)。支持断点续跑、层粒度重跑、引文子串校验、span 位置断言。适用于：小说精读、故事拆解、叙事分析、文笔拆解。不用于技术文档、论文、代码。
author: BestBeastHunter
license: MIT
---

# 四层精读批注 Skill v2.7

对叙事文本进行**四层结构化批注**（外加 L2.5 情感分析）：Layer 1「语义-结构层」、Layer 2「阐释-判断层」、Layer 2.5「情感分析层」（D19，v2.7 新增，P4 触发式）、Layer 3「文笔-语言层」、Layer 4「跨段-关系层」。

**核心原则**：每段每层独立落盘 → 支持断点续跑 → Layer 4 二阶段执行 → 四层合并输出。

> **版本声明（唯一真源同步）**：
> - 本文件 frontmatter `version: 2.7.0` = `references/schema.md` §一 声明的 Schema 版本 = 所有批注 JSON `schema_version` 字段 = `_metadata.skill_version`。**四者必须严格一致**。
> - 校验器向后兼容：`schema_version: 2.5.0` / `2.6.0` / `2.7.0` 均被 validate_output.py 接受。v2.6.0 新增必填子字段 `D04.polarity`，对 2.5.0 旧产物豁免放行（历史数据豁免，非可选）；v2.7.0 新增可选扩展 **D19 情感分析**（P4 Pass、独立 `emotion.jsonl`）——L1–L3 文件 schema 不变，旧产物零迁移。
> - **枚举真源**：`references/schema.md` 是唯一真源（本文件速览表 / validate_output.py 校验枚举 / templates/*.json 均须同步）。**唯一例外**：D19 的 `emotion` 枚举（44 词）真源为 `references/emotion-lexicon.md`（随语料演化的词表，决策 17 特批），validate_output 白名单须逐词同步该文件。

---

## 激活条件

**触发**（用户说以下任一即可）：
- 中文：「精读这段文本」/「拆解这个故事」/「分析这段的叙事」/「批注这段：xxx」/「做精读」/「精读+文笔拆解」/「拆伏笔链」
- 英文："close reading" / "annotate this narrative" / "close-read this segment" / "analyze craft"

**不触发**（请礼貌拒绝）：
- 技术文档、论文、代码、API 文档、纯数据表格分析（这类不需要叙事维度）
- 纯诗歌体（提示用户维度覆盖可能不足，请确认是否仍要批注）
- 单条片段字数 < 30 字的极短片段（请用户提供更长上下文，否则节奏/情绪/叙事功能无法判断）

---

## 内联校准锚点（关键摘要，无需翻 references）

### D04 情绪强度锚点（唯一真源见 `references/emotion-anchors.md`）

| 强度范围 | 外显行为/文学描述对照（摘要） |
|:--------:|:---------------------------|
| 1-3 | 他微微皱眉 / 她感到一丝不安 / 语气略带不满 / 环境描写微冷 |
| 4-6 | 他深吸一口气 / 她感到一阵失落 / 声音在发抖 / 眼眶微湿但忍住 |
| 7-8 | 他绝望地瘫坐 / 她歇斯底里地大笑 / 胸口像被重锤击中 / 失声呜咽 |
| 9-10 | 他撕心裂肺地嚎哭 / 感觉整个世界崩塌 / 血液凝固 / 万念俱灰的死志 |

### D05 叙事节奏锚点（唯一真源见 `references/pace-anchors.md`）

| 节奏 | 特征（摘要） |
|:----:|:-----------|
| 1 | 大段环境/心理描写，几乎没有动作推进，对话 ≤1 句或无 |
| 2 | 以描写+静态交互为主，小步信息推进 |
| **3** | 描写与动作交替，叙事平稳推进（基线） |
| 4 | 以动作和对话为主，事件进展快，切场景 |
| 5 | 主要是对话和快速动作，信息密度极高，句子短、频繁换行 |

---

## 分层总览（四层体系，速览表）

| 层 | 别名 | 维度 | 必做/按需 | 落盘文件 |
|:-:|:-:|:----|:--------:|:--------|
| **L1 结构层** | 语义-结构 | D01 叙事功能 / D04 情绪基调 / D05 叙事节奏 / D07 叙事视角 / D08 时空标记 / D10 对话功能 / D11 描写类型 | ✅ **必做** | `{doc_id}_structure.jsonl` |
| **L2 阐释层** | 阐释-判断 | D06 信息控制 / D09 主题标签 / narrator_reliability 叙述者可靠性 | ⚡ 按需（标准档/深度档开启） | `{doc_id}_interpretation.jsonl` |
| **L2.5 情感层** | 情感分析（v2.7 新增）| D19 情感分析（主情感/复合/对象/触发点/段内弧/表达）| ⚡ P4 触发式（见 Phase 2.5 触发条件）| `{doc_id}_emotion.jsonl` |
| **L3 文笔层** | 文笔-语言 | D13 佳句 / D14 修辞 / D15 意象 / D16 词汇 / D17 句式 / D18 人物语言指纹 | ⚡ 按需（深度档开启） | `{doc_id}_craft.jsonl` |
| **L4 跨段层** | 跨段-关系 | 伏笔-回收 / 因果 / 时序 / 对比 / 呼应（双引用） | 🔁 **二阶段**（L1-L3 全部完后整体一次） | `{doc_id}_cross_segment.jsonl` |

---

## 工作流（AI 自动执行 Phase 1–5）

> **⚠️ 开工前强制指令**：开始前必须确认 `references/schema.md` 中的 D01/D04/D07/D10/D11 枚举值与本文件速览表一致——**D04.core 只能从 20 个枚举词里选**（写"敬仰""敬畏"等非枚举词会被 validate_output.py 直接拒）。每次批注按 Phase 顺序，不要跳步。

### Phase 1：输入预处理（切分 + 初始化 checkpoint）

调用 `scripts/preprocess.py`：

```bash
python scripts/preprocess.py --input <原文文件路径> --doc-id <文档ID> --output-dir <输出目录>
```

**产出**：
- `{doc_id}_segments.jsonl`：每行一个片段，含 `segment_id` / `chapter` / `section_type` / `text_span`（见 schema.md §三）/ `context_prev` / `context_next`
- `{doc_id}_checkpoint.json`：断点续跑状态文件（见 schema.md §七）

**关键约束（v2.5 P0 修复）**：
1. 章节边界识别：支持「第X章」「Chapter X」「一二…单独成行（含行首空白）」「序章/楔子/尾声/后记/Prologue/Epilogue」
2. frontmatter：显式检测并输出为 `section_type="frontmatter"` 的 seg（不静默丢弃、不截断）
3. 无章节边界：退化到按段落+句子智能长度切分，**全书不截断**，`pollution_warning` 字段打印显式警告
4. 每段 ≈2000 token（`estimate_tokens`：中文 1:1，英文按词）。超长段落自动按句子边界子切
5. 每段前后 200 字符上下文锚点（`context_prev` / `context_next`）
6. `segment_id` 统一格式：`{doc_id}_seg_{4位十进制序号}`（**携带 doc_id 前缀**，防多文档合并碰撞）
7. 所有片段坐标经过 `_assert_text_slice_matches(original, start, end, text)` 自校验（坐标漂移 = 直接抛异常，不产出损坏数据）

**验证命令（Phase 1 后立即跑）**：
```bash
python scripts/checkpoint.py status --doc-id <doc_id>
# 确认 total_segments 与 segments.jsonl 行数一致
wc -l <输出目录>/{doc_id}_segments.jsonl
```

---

### Phase 2：逐片段四层批注（核心循环）

对每个片段按层调用，**每层独立调用、每层独立落盘、每层独立校验**：

```bash
# 单片段 + 单层（手动模式：脚本打印 LLM 输入，让你/AI 输出 JSON 后粘贴回去）
python scripts/annotate_segment.py \
  --segments <输出目录>/{doc_id}_segments.jsonl \
  --doc-id <doc_id> \
  --segment <doc_id>_seg_0001 \
  --layers structure \
  --output-dir <输出目录>
```

`--layers` 可选组合：`structure` / `structure,interpretation` / `structure,interpretation,craft`。

**每层的具体批注维度（详见下一节「四层输出架构」+ references/schema.md §六）**：

- Structure 必做：D01 / D04 / D05 / D07 / D08 / D10 / D11（七维全填，null 维度必须写 `null_reasons`）
- Interpretation 按需：D06 信息控制（引文必须是原文子串）/ D09 主题标签（≤3）/ narrator_reliability
- Craft 按需：D13–D18 六维（所有条目必须带 `span` 段内相对偏移 + 过引文校验）

**状态机（断点续跑）**：
- 每完成一个 `(segment_id, layer)` 组合，annotate_segment 会调 `mark_layer_completed` 更新 checkpoint。
- 加上 `--resume`（默认开启）后，annotate_segment 会自动跳过 checkpoint 中已完成的 `(segment, layer)` 对。
- 强制重跑某层：`python scripts/checkpoint.py reset-layer --doc-id <doc_id> --layer structure`（连带把依赖此层的 cross_segment/merged/report 阶段一起重置）。

**每层校验（annotate_segment 自动调用，用户也可手动）**：
```bash
python scripts/validate_output.py --jsonl <输出目录>/{doc_id}_structure.jsonl
# 校验失败 → 最多自动重试 3 次，失败则退出码 1，不写入 checkpoint
```

---

### Phase 2.5：P4 情感分析 Pass（Layer 2.5 · D19 · v2.7.0 新增，触发式）

在 Phase 2 批注产出 D04/D01/D10 后可判定后，**按需**对**触发段**执行 P4 情感分析。**不是每个段都要做 D19**——纯议论/静态背景且情绪强度低时不触发，登记 `emotion_skipped`（区别于"没批"，防下游误判）。

**P4 触发条件（任一命中 = 触发）**：

| # | 条件 | 依据（structure 层）|
|:--:|:--|:--|
| 1 | 本段情绪强度 ≥ 4 | `D04.intensity ≥ 4` |
| 2 | 本段为叙事关键段 | `D01 ∈ {激励事件, 上升行动, 高潮, 转折}` |
| 3 | 本段含对话 | `D10` 非 null |
| 4 | 用户显式要求深度情感分析 | 调用指令 |

**产出**：`{doc_id}_emotion.jsonl`（P4 独立 pass、独立校验、append-only），每行结构见「Layer 2.5 输出架构」+ `references/schema.md` §六 Layer 2.5 + `templates/emotion-output.json`。校验命令：

```bash
python scripts/validate_output.py --jsonl <输出目录>/{doc_id}_emotion.jsonl
```

**命令行入口（v2.7.0 起 annotate_segment 已支持 emotion 层）**：

```bash
# 手动模式：脚本自动打印该段原文 + structure(D01/D04/D10) 判定上下文 + P4 纪律，产出 JSON 后粘贴
python scripts/annotate_segment.py \
  --segments <输出目录>/{doc_id}_segments.jsonl \
  --doc-id <doc_id> \
  --segment <doc_id>_seg_0091 \
  --layers emotion \
  --output-dir <输出目录>

# 或注入外部 LLM（payload 额外携带 structure_trigger_block）
python scripts/annotate_segment.py --segments <输出目录>/{doc_id}_segments.jsonl \
  --doc-id <doc_id> --segment <doc_id>_seg_0091 --layers emotion \
  --output-dir <输出目录> --llm-cmd "python your_p4_wrapper.py"
```

> emotion 层复用同一「校验 → 落盘 → checkpoint 登记」流程：validate 通过才写 `emotion.jsonl` 并登记 `emotion`；未命中触发条件 1–3 时脚本**仅提示不阻断**（对应条件 4「用户显式要求」）；structure 行缺失时跳过上下文注入，需人工确认触发。

**关键纪律（防过度批注）**：`emotion` 只能选自 `references/emotion-lexicon.md` 44 词，词表没有 → 选最接近词 + `expression.note` 说明，不造新词；`target` / `trigger` / `arc` 无明确依据一律 null + 顶层 `null_reasons`，**禁止编造情感对象与情感弧**；`expression.key_phrases` 每项必须是原文子串（校验 error 级）。

---

### Phase 3：二阶段跨段分析（Layer 4，独立一次）

**⚠️ Layer 4 绝对不能在逐片段中混跑**——它需要看到整本书的 Layer 1/2 完整图景才能判断伏笔-回收链。

```bash
python scripts/cross_segment.py \
  --doc-id <doc_id> \
  --segments   <输出目录>/{doc_id}_segments.jsonl \
  --structure  <输出目录>/{doc_id}_structure.jsonl \
  --interpretation <输出目录>/{doc_id}_interpretation.jsonl \
  --craft      <输出目录>/{doc_id}_craft.jsonl \
  --window-size 15 --overlap 3
```

**产出**：`{doc_id}_cross_segment.jsonl`（见 schema.md §六 Layer 4）——每条 `cross_ref` 都是**双引用**：
- `segment_id`：位置 ID（精确但易漂移）
- `anchor_text`：内容锚点（原文摘录短语，防漂移后可重定位；v2.6.0 起规则版尽可能回算段内 `span`）

落地版本做的是**启发式规则**（情绪强度突变点=因果候选、视角切换点=时序候选、D09 主题复用=呼应候选、D06 埋设-揭露=伏笔-回收候选）。高精度 LLM 二分类打标可留给调用方自建批量管线叠加。规则产出的候选列表直接可用（cross_refs 非空），`_metadata.method = "rule_based_heuristic_v2_6"`。

**v2.6.0 行为增强**：
- **`--preserve-curated`（默认开）**：规则重跑时**保留既有文件中人工/LLM 核验过的关系**（`_source != "rule"` 的条目），只重新生成 `_source = "rule"` 的候选，避免重跑覆盖掉已核验/已微调的内容。要完全用规则结果覆盖请加 `--no-preserve-curated`。
- **checkpoint 回写**：跨段完成后自动标记 `cross_segment_completed = true`（原版本此标记只在 merge 时补写）。
- **锚点清洗**：`anchor_text` 做空白归一、可回算 span 时回算（不再把整段原文当锚点）。

---

### Phase 4：四层合并（嵌套文档）

```bash
python scripts/merge_layers.py \
  --doc-id <doc_id> \
  --segments <输出目录>/{doc_id}_segments.jsonl
```

**产出**：`{doc_id}_merged.jsonl`——每行对应一个 segment，把同一段的 L1/L2/L3 + cross_refs 投影（以该段为 source/target 的 ref_id 列表）嵌套在一起。结构见 schema.md §六「Merged 嵌套文档」。

**关键 bug 修复（评审审计）**：merge 优先从 seg["text_span"] 读原文，不再假设 annotation 会带平铺字段；同时兼容 annotation 自身带 text_span 的模式。

---

### Phase 5：渲染人类可读报告（可选）

```bash
python scripts/render_report.py --doc-id <doc_id> --format html
python scripts/render_report.py --doc-id <doc_id> --format md
```

**产出**：`{doc_id}_report.html` 或 `{doc_id}_report.md`，含：
- 结构全景：章节/片段数、叙事功能分布饼（HTML）、情绪强度折线、节奏条形
- Layer 2/3 摘要：Top 主题、佳句 Top 10、修辞手法统计（v2.6.0 起 **Markdown 报告同样包含** Layer 2/3 摘要，此前只有 HTML 有）
- Layer 4 跨段列表：伏笔链 / 因果链 / 呼应对清单

零第三方依赖：HTML 纯手写内联样式，可直接打开。

---

## 四层输出架构（速览 + 易错点）

完整字段定义见 `references/schema.md` §六（唯一真源）。本节只给速览 + 最容易写错的点。

### Layer 1：语义-结构层（`structure.jsonl`，必做）

| 维度 | 类型 | 枚举（关键） | 易错点 |
|:----:|:----|:----|:----|
| D01 叙事功能 | 枚举 | 背景铺垫/激励事件/上升行动/转折/高潮/下降行动/结局/过渡/复合功能/无法判断 | 自造词 = 校验报错 |
| D04 情绪基调 | 对象 | **core 只能从 20 个里选**（见下），modifier 可 null，intensity 1-10 整数，`polarity` **必填**（v2.6.0）∈ positive/negative/neutral/mixed | 写 `core:"敬仰"`= 非法；漏 intensity / 漏 polarity = 非法（v2.6.0 起） |
| D05 叙事节奏 | 整数 | 1 / 2 / 3 / 4 / 5 | 写小数 / 超出范围 = 报错 |
| D07 叙事视角 | 对象 | **type 枚举（7 个）**：第一人称/第二人称/第三人称有限/第三人称全知/多视角/不可靠叙述者/客观叙事 | is_switch_point 没看到前后文一律 `false` |
| D08 时空标记 | 对象 | `time: string\|null`, `space: string\|null` | 子字段 null 不需填 `null_reasons`（仅 D08 整体为 null 时填） |
| D10 对话功能 | 枚举\|null | 推动情节/揭示性格/传递信息/制造冲突/营造氛围/复合功能 | 无对话 = `null` + `null_reasons.D10` 写理由 |
| D11 描写类型 | 数组（非空） | 环境描写/心理描写/动作描写/外貌描写/感官描写（可多选） | **严禁 null / 空数组**；即使纯议论段也写 `["心理描写"]`，置信度给低即可 |

**D04.core 20 枚举词（必须严格从中选 1）**：
平静 / 压抑 / 焦虑 / 悲伤 / 愤怒 / 恐惧 / 喜悦 / 希望 / 绝望 / 孤独 / 信任 / 背叛 / 屈辱 / 尊严 / 嫉妒 / 贪婪 / 复仇 / 宽恕 / 悬疑 / 释然

**D04.polarity（v2.6.0 新增，必填）**：对核心情绪做**情感极性**标注——`positive / negative / neutral / mixed`。四值覆盖全部段落，不存在「无法判断」：主调清晰直接写；多重情绪交织/反讽张力写 `mixed`；仍拿不准按 emotion-anchors.md 的「core → 极性」缺省映射兜底。**不得省略**（v2.6.0 校验必填，省略=非法）。情绪极性由**文本语义**判断，不由文风/情节走向推导。2.5.0 旧产物无此字段，校验豁免。

---

### Layer 2：阐释-判断层（`interpretation.jsonl`，按需）

| 维度 | 类型 | 校验规则 |
|:----:|:----|:----|
| D06 信息控制 | 对象\|null | `type ∈ {揭示/隐藏/误导/复合}`。`content` 中任何「」/"" /《》引号引的**引文必须是 `text_span.text` 子串**——validate_output 会提取并校验子串命中 + 95% 相似度（§五引文校验）|
| D09 主题标签 | `string[] \| null` | **≤ 3 个**，超过直接截断，校验器报错 |
| narrator_reliability | 枚举\|null | 可靠 / 部分不可靠 / 不可靠 / 无法判断 |

---

### Layer 2.5：情感分析层（`emotion.jsonl`，v2.7.0 新增，P4 触发式）

**定位**：阐释层（Layer 2）的语义扩展——D19 做**角色/精细情感**分析（44 词）；区别于 L1 的 D04「段落氛围摘要」（20 词粗粒度）。两者允许词面重叠（基元共有），语义粒度不同；对同一情绪都产出判断时**以 D19 为准**（决策 17）。非独立架构层。

| 维度 | 子字段 | 校验要点 |
|:----:|:----|:----|
| **D19_emotion_analysis** | `primary`（emotion/intensity/polarity，必填）| emotion ∈ emotion-lexicon.md 44 词；intensity 1–10 整数；polarity ∈ positive/negative/neutral/mixed（词表极性=缺省映射，以文本语义为准）|
| | `secondary`（复合情感，null 或 ≤2 项）| 已固化复合词（悲欣交集/爱恨交织/苦乐参半）直接作 primary，不拆 secondary |
| | `target`（情感对象，null-合法）| 非 null 时 `name` 必填；`entity_id` 为分析侧映射预留，本 skill 内可 null |
| | `trigger`（触发点，null-合法）| 非 null 时 `description` 必填非空 |
| | `arc`（段内情感弧，null-合法）| 仅真实位移才填 `has_shift: true` + `before`/`after`；无位移一律 null |
| | `expression`（direct/indirect/key_phrases/note，必填）| `key_phrases` 每项过原文子串校验（error 级）|

> 触发条件与"不触发即跳过"纪律见 **Phase 2.5**。

---

### Layer 3：文笔-语言层（`craft.jsonl`，按需）

**所有 Craft 条目必须带 `span: {start, end}` 段内相对偏移（见 schema.md §3.2）。** merge 时自动换算为全局偏移。校验器做三层断言：子串命中 → span 边界合法 → 切片相似度 ≥ 95%。

| 维度 | 条目字段（含 text+span） | 额外字段 |
|:----:|:----|:----|
| D13 佳句提取 | text+span | `reason`, `quality_score` (1-5) |
| D14 修辞手法 | text+span | `type ∈ {比喻/拟人/排比/反讽/通感/夸张/对比/象征}`, `detail` |
| D15 意象提取 | text+span | `type ∈ {自然意象/器物意象/人体意象/色彩意象/抽象意象}`, `cluster\|null` |
| D16 词汇精讲 | text+span | `pos ∈ {动词/形容词/副词/名词}`, `reason`, `alternatives: string[]` |
| D17 句式分析 | text+span | `type ∈ {排比/长短交替/倒装/独词句/对偶/设问}`, `effect` |
| D18 人物语言指纹 | 视情况 span 可 null | `character`, `pattern`（习语/口癖）, `occurrence_count`（跨段聚合后填）|

**D18 放宽**：引文可以不在本段内（校验器 warning 级别、允许），因为人物口癖天然跨段聚合。

---

### Layer 4：跨段-关系层（`cross_segment.jsonl`，二阶段）

| 关系类型 | 含义 |
|:----:|:----|
| 伏笔-回收 | 段 A 埋设伏笔 → 段 B 回收 |
| 因果 | 段 A 事件导致段 B 事件 |
| 时序 | 段 A 事件在段 B 之前 / 之后 |
| 对比 | 段 A 与段 B 形成显著对照 |
| 呼应 | 段 A 与段 B 相互呼应（意象/句式/主题再现）|

每条 `cross_ref` **source/target 必须同时带**：
- `segment_id`：位置 ID
- `anchor_text`：内容锚点（原文摘录短语）

（如果后续切分版本重排导致 segment_id 漂移，`anchor_text` 可以在原文中检索重新定位，关系不会静默失效。）

---

## 校验规则（validate_output.py 核心）

### 引文校验（Layer 2 D06 + L2.5 D19.key_phrases + Layer 3 D13–D17 强制）

1. **引文抽取**：从自由文本中抽取引号 `「」""《》` 包裹的内容，或直接读 Craft 条目 `text`。
2. **子串验证（归一化后）**：`" ".join(quote.split())` 必须是 `" ".join(text_span.text.split())` 的子串。未命中 → error（强制修复）。
2.5. **D19.expression.key_phrases（v2.7.0 新增）**：数组**每一项**归一化后都必须是 `text_span.text` 子串，未命中 = error（与 D06 同级强校验）。
3. **span 位置断言**（带 span 时）：
   - `0 ≤ span.start < span.end ≤ len(text_span.text)`
   - 切片与 `text` 相似度：
     - ≥ 95% → 通过
     - 85–95% → warning（建议微调 span 边界）
     - < 85% → error（span 严重漂移）

### 置信度 + status 自动推导

- `confidence.overall ∈ [0, 1]`，精确到 0.01 即可。
- `confidence.confidence_method ∈ {model_self_report, consistency_check, human_review}`
- **必填维度置信度（Structure 七维）**：即使主值 null（如 D10 无对话），`per_dimension.D10` 也必须是 0–1 数字（表示「我确定没值」）。可选维度（Interpretation/Craft）可 null。
- **P4 触发段（emotion 层）**：`confidence.per_dimension.D19` 必填 0–1 数字（v2.7.0 校验硬性要求）。
- **status 自动对齐规则**（`status != superseded` 时）：
  - `overall ≥ 0.8` → `status: confirmed`。打 tentative 校验器会 warning。
  - `overall < 0.8` → `status: tentative`。打 confirmed 校验器会 **error**。
  - `status = superseded`：生命周期标记，跳过自动推导。

---

## 断点续跑（checkpoint 状态机）

状态文件：`{doc_id}_checkpoint.json`（完整结构见 schema.md §七）。

```json
{
  "doc_id": "sample_novel_zh",
  "schema_version": "2.7.0",
  "total_segments": 58,
  "completed": [
    { "segment": "sample_novel_zh_seg_0001", "layers": ["structure", "interpretation", "craft", "emotion"] },
    { "segment": "sample_novel_zh_seg_0002", "layers": ["structure"] }
  ],
  "emotion_skipped": ["sample_novel_zh_seg_0002"],
  "cross_segment_completed": false,
  "merged_completed": false,
  "render_report_completed": false,
  "last_updated": "ISO8601",
  "created_at": "ISO8601"
}
```

> v2.7.0：`completed[].layers` 新增合法层名 `"emotion"`（P4 触发段完成 D19 后登记）；`emotion_skipped` 登记判定不触发的段。reset-layer / status 已支持 emotion。

**常用命令**：
```bash
# 看进度（各层完成百分比 + Phase 3–5 状态）
python scripts/checkpoint.py status --doc-id <doc_id>

# 强制重跑 structure 层（会连带重置 cross_segment / merged / report）
python scripts/checkpoint.py reset-layer --doc-id <doc_id> --layer structure

# 整体重置（仅保留 total_segments）
python scripts/checkpoint.py reset-all --doc-id <doc_id>
```

写盘是**原子写**（temp + rename），避免中途崩溃损坏 checkpoint。

**Phase 3–5 自动回写（v2.6.0 起完备）**：
- Phase 3 跨段完成 → `cross_segment_completed: true`（此前漏写，需等 Phase 4 才补齐）
- Phase 4 合并完成 → `merged_completed: true`
- Phase 5 报告生成 → `render_report_completed: true`
- 各脚本按产物路径定位 checkpoint：`annotate_segment.py` 用 `--checkpoint <路径>` 指定，`cross_segment.py` / `merge_layers.py` / `render_report.py` 从 segments 所在目录推断；`checkpoint.py` 子命令均支持 `--dir <目录>` 显式指定。

---

## 输出落盘约定

> Skill 本体是 Prompt 包，不自带文件 IO。但不同运行环境下，落盘路径必须统一——避免运行时产物污染 skill 分发包。

| 运行环境 | 落盘方式 | 推荐路径 |
|---------|---------|---------|
| 纯 LLM（无工具）| 对话里输出 JSON，用户手动保存 | 用户自选 |
| Agentic（TRAE/Cursor/Claude Code）| Write/Shell 直接写 | `<调用方工作区>/outputs/annotations/<doc_id>/` 下 7 个文件（segments / structure / interpretation / emotion / craft / cross_segment / merged）+ checkpoint + report |
| 自建批量管线 | 管线代码循环调用 LLM API，自动追加 | `<调用方>/outputs/annotations/<doc_id>/`（路径自定义）|

**`examples/` 角色**：仅放打包自带的输入样例（`examples/sample_input.txt`，公版重述文本）。**运行时批注结果严禁写入 `examples/` 或 skill 包内任何目录**——污染分发包。

**路径约定理由**：
- 输出目录与 skill 包隔离；
- `<doc_id>/` 子目录保证每份文档所有 Phase 产物聚在一起，不会散落在目录下和其他 doc 混；
- JSONL 每行一条，增量追加 + 中途断点不丢。

---

## 质量约束（每条都必须满足）

| 约束 | 含义 | 不满足怎么办 |
|------|------|------------|
| **先验证再声称** | 任何声称「Phase N 完成」前，validate_output 或 checkpoint status 必须通过 | 校验不通过 = 不写入 checkpoint + 最多重试 3 次，失败显式退出 |
| **客观性（L1 D08/D10/D11）** | 仅基于字面明确信息，禁止脑补 | 信息不足写 null + `null_reasons` 填理由 |
| **完整性** | 必填层所有键要么有有效值要么 null + 理由 | 缺键 = validate_output 直接报错 |
| **多义性承载** | 两种以上合理解读，主值取最信的一个，其余写 `alternatives` | 不要在主值上纠结半天 |
| **锚点对齐** | D04 强度 + D05 节奏对齐内联锚点 / references 详细锚点 | 强度锚点错位 ≥2 档 / 节奏特征明显错位 → `confidence.overall` 降到 ≤ 0.7 |
| **引文必真源** | Layer 2 / 3 所有引的文本必须是原文子串 + span 位置对得上 | validate_output 引文校验 = 硬 fail 项 |
| **版权合规** | `text_span.text` 只能携带公版/授权/用户自有内容 | 训练数据入库前先跑 `scripts/export_dataset.py` 脱敏——训练数据严禁携带原文 |

---

## 分级策略

| 档级 | 跑哪些层 | 典型用户 | 单篇成本预估 |
|:----:|:--------|:--------|:-----------|
| 轻量档 | Phase 1 + 2（仅 structure）+ 4 | 大规模批量扩充基数（80% 文档）| ~$0.3 |
| **标准档**（默认）| Phase 1 + 2（structure + interpretation）+ 3 + 4 | 普通精读 / 拆解 | ~$1.0 |
| 深度档 | Phase 1–5 全跑（含 craft + report）| 金标准样本 / 训练集样本池核心 | ~$5–15 |

> 【成本红线】严禁把全量深度维度跑应用到百万级文本——20% 深度档提供 80% 价值，80% 轻量档扩充基数。

---

## 降级策略（环境不支持工具调用、或文本不长时）

1. **单片段模式（默认）**：每次只批注一个片段（500–3000 字最合适），用户分段提供，Skill 按 Layer 逐段输出 JSON。
2. **长文本模式**：先跑 `scripts/preprocess.py` 切分，得到 `segments.jsonl`，然后逐段粘贴给 Skill 批注，每层输出追加到对应层 JSONL；最后手动跑 Phase 3–5。
3. **纯 LLM（无工具）模式**：不跑 scripts，本 SKILL.md 直接作为 system prompt——你手动分段+按序输出。效果等价（这也是为什么 Skill 本身零第三方依赖）。

---

## 跨平台兼容性

此 Skill 是**纯 Prompt 包（frontmatter + 正文）**——没有任何平台专有 API 依赖。scripts/ 目录是可选的辅助工具，不影响 Skill 本身工作。

| 平台 | 支持程度 | 安装方式 |
|------|---------|---------|
| **TRAE** | ✅ 完全支持 | 把本包目录放到 skills 目录（如 `skills/close-reading-annotator/`），TRAE 自动读取 SKILL.md |
| **Cursor Skills** | ✅ 完全支持 | 复制整个目录到 `~/.cursor/skills/close-reading-annotator/` |
| **Claude Code** | ✅ 完全支持 | 复制到 `~/.claude/skills/close-reading-annotator/` |
| **VS Code Copilot** | ✅ 完全支持 | 复制到 `~/.copilot/skills/` |
| **纯手动模式** | ✅ 降级 | 直接把本 SKILL.md 作为 system prompt 喂给任意大模型，效果等价 |

---

## 快速安装 / 升级

```bash
# 方式一：本仓库即完整 Skill 包——复制到 IDE 的 skills 目录即可
#   Cursor / Claude Code / TRAE 等 IDE 会自动读取 SKILL.md
#   纯手动模式：直接把本 SKILL.md 作为 system prompt 注入任意大模型，效果等价

# 方式二：安装到 IDE 的 skills 目录
cp -r close-reading-annotator/ ~/.cursor/skills/   # Cursor
cp -r close-reading-annotator/ ~/.claude/skills/   # Claude Code
```

---

## 参考文档索引（按需查阅）

> ⚠️ Schema 真源原则：**枚举只认 `references/schema.md`**；SKILL.md / validate_output.py / templates 下游三处是副本。改枚举 = 先改 schema.md 再同步三者。

| 文档 | 位置 | 什么时候要读 |
|------|------|------------|
| **四层 Schema 完整定义（唯一真源）** | `references/schema.md` | 每次写 D01/D04/D07/D10/D11/关系类型 等枚举不确定时 |
| **Few-shot 示例（多种场景的完整批注 JSON）** | `references/annotation-examples.md` | 刚开始批注前，先看 1–2 条示例找格式和内容感觉 |
| **情绪校准锚点完整表（20+ 文学描写 × 强度分档）** | `references/emotion-anchors.md` | 情绪强度判断犹豫时（锚点比主观判断靠谱） |
| **D19 情感词表（44 词，D19.emotion 枚举真源）** | `references/emotion-lexicon.md` | 跑 P4/D19 前必读；emotion 只能从词表选 |
| **节奏校准锚点完整表（10+ 段落 × 节奏分档+原因）** | `references/pace-anchors.md` | 节奏判断犹豫时 |
| **每层输出模板（可直接填充）** | `templates/structure-output.json` / `interpretation-output.json` / `craft-output.json` / `emotion-output.json` / `cross-segment-output.json` / `merged-output.json` | 直接套用格式，避免漏字段 |
| **设计决策记录（为什么这么设计）** | `docs/design-decisions.md` | 对架构选择有疑问 / 想改前先读历史决策 |

---

## 版本历史

| 版本 | 日期 | 变化 |
|------|------|------|
| **2.7.0** | 2026-09-04 | 新增 **D19 情感分析**（P4 Pass，阐释层 Layer 2.5 语义扩展、非独立架构层）：新增独立产物 `{doc_id}_emotion.jsonl` + `templates/emotion-output.json`；新建 `references/emotion-lexicon.md`（Plutchik 8 基元 + 文学扩展 36 词 = 44 词，D19.emotion 枚举真源——schema「枚举唯一真源」规则的唯一例外）；schema.md / validate_output（接受集 + `validate_emotion_layer` + key_phrases 原文子串校验）/ checkpoint（`emotion` 层 + `emotion_skipped`）/ merge_layers（并入 merged.emotion）/ render_report（MD 新增情感摘要表）全部接入；P4 触发条件（D04.intensity≥4 / D01∈关键叙事 / D10 含对话 / 用户显式要求）。L1–L3 schema 不变，2.5/2.6 旧产物零迁移。详见 docs/design-decisions.md 决策 17。 |
| **2.6.0** | 2026-09-04 | 在真实全本运行（《月亮与六便士》）基础上打补丁 + 小增强（v2.5.1 修订内容一并合入）。修复：① Windows GBK 控制台打印崩溃（stdout/stderr reconfigure utf-8）；② annotate_segment checkpoint 加载路径错位（--checkpoint 目录未生效）；③ Phase 3 cross_segment 完成后未回写 `cross_segment_completed`（现自动标记）；④ Markdown 报告缺失 Layer 2/3 摘要（补齐 Top 主题 / 叙述者可靠性 / 佳句 Top10 / 修辞统计）；⑤ HTML 报告缺 D04 极性列。增强：⑥ D04 新增 `polarity` 字段（positive/negative/neutral/mixed，v2.6.0 产物**必填**：四值覆盖全段落、拿不准按 core→极性缺省映射兜底、不得省略；validate_output 版本分支校验，2.5.0 旧产物豁免放行，无需迁移）；⑦ cross_segment 规则版锚点清洗（空白归一 + 回算 span）并加 `--preserve-curated`（默认开，保留人工/LLM 核验关系不被重跑覆盖，规则条目标记 `_source:'rule'`）；⑧ checkpoint.py 子命令加 `--dir`；⑨ 新增 `scripts/fill_spans.py`（对存量 craft/cross_segment 产物回补/校正段内 span）；⑩ 全脚本 schema_version / skill_version 升 2.6.0。 |
| 2.5.0 | 2026-09-04 | 架构大升级：3 层 → 4 层（L1 结构 / L2 阐释 / L3 文笔 / L4 跨段二阶段）。关键修复：章节正则匹配「一」、frontmatter 显式处理、Craft span 段内相对偏移定义 + merge 换算、Layer 4 从占位改为规则可运行（cross_refs 非空）、恢复轻量级 checkpoint 状态机、引文校验升级为"抽取+子串+span位置+95%相似度"四层、内联锚点恢复、置信度 ≥0.8↔confirmed 自动对齐规则上线、schema 统一为 `references/schema.md` 单一真源、新增 4 层 templates、新增 merge_layers/render_report、上传模块按架构要求移除。同步修复评审指出的 7 项 P0 bug：#1 ID 碰撞（全局计数器）、#2 坐标漂移（自校验断言）、#3 无边界截断（退化长度切分）、#4 frontmatter 丢弃（作为 seg 输出）、#5 Layer4 占位（规则实现）、#6 merge 读错字段（兼容两种形态）、#7 segment_id 无 doc_id 前缀（统一格式）。 |
| 2.3.0 | 2026-09-03 | 9 维单片段正式版。同日修订：修复 6 处实测暴露的 Prompt 缺陷、新增输出落盘约定章节。 |
| 2.2.0 | 2026-09-02 | 早期设计版（12 维含 D02/D03）。**已废弃。** |
| 2.1.0 | 2026-09-01 | 内部草稿。多 Pass 分层思路。 |
| 2.0.0 | 2026-08-31 | 从"设计文档"转为"Skill"。 |

> 版本号遵循 SemVer。**主版本升级 = Schema 不兼容变更**，下游解析器必须升级。v2.5.x 修订号仅 bugfix / 锚点校准，不改字段；v2.x.0 次版本可新增枚举值 / 可选维度（宽松兼容）——若新增**必填**字段，须对旧版本产物豁免放行（见 `D04.polarity`）。本 v2.6.0 已把真实全本运行暴露的 v2.5.1 补丁内容一并合入，向后兼容 2.5.0 产物。v2.7.0 仅新增可选扩展 D19（emotion 文件产物必为 2.7.0，L1–L3 续批可写 2.7.0 或保持 2.6.0），无必填字段新增，向后兼容 2.5.0 / 2.6.0。

---

*精读批注 Skill v2.7 — "先验证，再声称；每段每层落盘；二阶段跨段；四层合一，情感入轨。从『规格正确』走向『实现可运行』。"*
