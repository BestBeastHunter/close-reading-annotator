---
name: close-reading-annotator
version: 2.7.0
description: 对小说、剧本等叙事文本进行四层精读批注。输出结构层(叙事功能/情绪/节奏/视角/时空/对话功能/描写类型) + 阐释层(信息控制/主题/叙述者可靠性) + 情感层(角色情感/情感对象/段内情感弧，P4 触发式) + 文笔层(佳句/修辞/意象/词汇/句式/人物语言指纹) + 跨段层(伏笔链/段间关系)。支持断点续跑、层粒度重跑、引文子串校验、span 位置断言。适用于：小说精读、故事拆解、叙事分析、文笔拆解。不用于技术文档、论文、代码。
author: BestBeastHunter
license: MIT
---

# 四层精读批注 Skill v2.7

对叙事文本进行**四层结构化批注**（外加 L2.5 情感分析）：Layer 1「语义-结构层」、Layer 2「阐释-判断层」、Layer 2.5「情感分析层」（D19，P4 触发式）、Layer 3「文笔-语言层」、Layer 4「跨段-关系层」。

**核心原则**：每段每层独立落盘 → 断点续跑 → Layer 4 二阶段执行 → 四层合并输出。

> **版本声明（唯一真源同步）**：
> - 本文件 frontmatter `version: 2.7.0` = `references/schema.md` §一 Schema 版本 = 批注 JSON `schema_version` = `_metadata.skill_version`。**四者必须严格一致**。
> - 校验器向后兼容 `schema_version: 2.5.0 / 2.6.0 / 2.7.0`。v2.6.0 新增必填 `D04.polarity`（2.5.0 旧产物豁免）；v2.7.0 新增可选扩展 **D19**（独立 `emotion.jsonl`），L1–L3 零迁移。
> - **枚举真源**：`references/schema.md`（本文件速览 / validate_output.py / templates 均须同步）。**唯一例外**：D19 `emotion` 枚举（44 词）真源为 `references/emotion-lexicon.md`（决策 17 特批）。

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

> **⚠️ 开工前强制**：D04.core 只能从 20 个枚举词里选（见 §4.1），自造词被 validate 直接拒。按 Phase 顺序执行，不要跳步。

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

**关键纪律**：`emotion` 只能选自 `references/emotion-lexicon.md` 44 词（词表没有→选最接近词 + `expression.note` 说明，不造新词）；`target/trigger/arc` 无明确依据一律 null + 顶层 `null_reasons`，**禁止编造情感对象与情感弧**；`expression.key_phrases` 每项必须是原文子串（校验 error 级）。

### 3.6 段采样分层策略（决策 18 新增）

分级策略此前只管「层」不管「段」。`select_segments.py` 读已批全量的 structure，把每段分档，让「20% 深度档」规则化而非人工选段：

```bash
python scripts/select_segments.py --structure <out>/{doc_id}_structure.jsonl
# 产出 {doc_id}_segment_plan.json（tiers: deep/light/skip + per_segment 理由）
```

**默认分档规则**（CLI 可覆盖）：D01 ∈ {激励事件, 上升行动, 高潮, 转折} 或 D04.intensity ≥ 6 或 D07.is_switch_point=true → **deep**（再跑 interpretation/craft…）；D01 ∈ {背景铺垫, 过渡} → **skip**；其余 → **light**。下游 `run_pipeline.py --plan` 消费：structure 全量跑，深度层只跑 deep 段。

---

## 4. 四层输出架构速览 + 最易错点

完整字段定义见 `references/schema.md` §六（**唯一真源**）。本节为速览 + 易错点 + 纯 LLM 模式必备枚举。

| 层 | 维度 | 必做/按需 | 落盘文件 |
|:-:|:----|:--------:|:--------|
| **L1 结构层** | D01 叙事功能 / D04 情绪基调 / D05 叙事节奏 / D07 叙事视角 / D08 时空标记 / D10 对话功能 / D11 描写类型 | ✅ **必做** | `{doc_id}_structure.jsonl` |
| **L2 阐释层** | D06 信息控制 / D09 主题标签(≤3) / narrator_reliability | ⚡ 按需 | `{doc_id}_interpretation.jsonl` |
| **L2.5 情感层** | D19（主情感/复合/对象/触发点/段内弧/表达）| ⚡ P4 触发式 | `{doc_id}_emotion.jsonl` |
| **L3 文笔层** | D13 佳句 / D14 修辞 / D15 意象 / D16 词汇 / D17 句式 / D18 语言指纹 | ⚡ 按需 | `{doc_id}_craft.jsonl` |
| **L4 跨段层** | 伏笔-回收 / 因果 / 时序 / 对比 / 呼应（双引用）| 🔁 二阶段整体一次 | `{doc_id}_cross_segment.jsonl` |

### 4.1 Layer 1 易错点（必做）

| 维度 | 类型 | 关键约束 | 易错点 |
|:--:|:--|:--|:--|
| D01 | 枚举 | 背景铺垫/激励事件/上升行动/转折/高潮/下降行动/结局/过渡/复合功能/无法判断 | 自造词=报错 |
| D04 | 对象 | **core 从下方 20 词选**；modifier 可 null；intensity 1-10 整数；**polarity 必填** ∈ positive/negative/neutral/mixed | `core:"敬仰"`=非法；漏 intensity/polarity=非法 |
| D05 | 整数 | 1 / 2 / 3 / 4 / 5 | 小数/越界=报错 |
| D07 | 对象 | type ∈ 第一人称/第二人称/第三人称有限/第三人称全知/多视角/不可靠叙述者/客观叙事 | is_switch_point 没前后文证据一律 false |
| D08 | 对象 | time/space 均 string\|null | 子字段 null 不写 null_reasons（仅 D08 整体 null 才写）|
| D10 | 枚举\|null | 推动情节/揭示性格/传递信息/制造冲突/营造氛围/复合功能 | 无对话=null + null_reasons.D10 |
| D11 | 数组 | 环境/心理/动作/外貌/感官描写（可多选 ≥1）| **严禁 null / 空数组**；纯议论段写 `["心理描写"]` 给低置信度 |

**D04.core 20 枚举词（必须严格从中选 1）**：平静 / 压抑 / 焦虑 / 悲伤 / 愤怒 / 恐惧 / 喜悦 / 希望 / 绝望 / 孤独 / 信任 / 背叛 / 屈辱 / 尊严 / 嫉妒 / 贪婪 / 复仇 / 宽恕 / 悬疑 / 释然

**D04.polarity（必填）**：positive / negative / neutral / mixed，四值覆盖全部段落；多重情绪交织/反讽张力写 `mixed`；拿不准按 `references/emotion-anchors.md` 的 core→极性缺省映射兜底。极性由**文本语义**判断，不由文风/情节走向推导。

### 4.2 Layer 2 要点

- D06：`type ∈ {揭示/隐藏/误导/复合}`；content 中引号引的**引文必须是 `text_span.text` 子串**（validate 抽引号并校验子串 + 95% 相似度）。
- D09：`string[] | null`，**≤3 个**（超=截断+报错）。
- narrator_reliability：可靠 / 部分不可靠 / 不可靠 / 无法判断。

### 4.3 Layer 2.5（D19）要点

定位：L2 语义扩展——D19 做角色/精细情感（44 词），区别于 L1 D04 段落氛围摘要（20 词粗粒度）；同情绪都产出时**以 D19 为准**（决策 17）。

| 子字段 | 校验要点 |
|:--|:--|
| `primary`（必填）| emotion ∈ 44 词；intensity 1-10；polarity ∈ 四值 |
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
| **Few-shot 完整批注示例** | `references/annotation-examples.md` | 开始批注前看 1–2 条找感觉 |
| **情绪校准锚点完整表** | `references/emotion-anchors.md` | 情绪强度犹豫时 |
| **D19 情感词表（44 词，枚举真源）** | `references/emotion-lexicon.md` | 跑 P4/D19 前必读 |
| **节奏校准锚点完整表** | `references/pace-anchors.md` | 节奏犹豫时 |
| **每层输出模板（可直接填充）** | `templates/*-output.json` | 避免漏字段 |
| **设计决策记录** | `docs/design-decisions.md` | 想改架构前先读 |

---

## 9. 跨平台与快速安装

**脚本跨平台**（纯 stdlib，Windows/Linux/macOS 一致）。安装即复制整个目录到 IDE 的 skills 目录：

```bash
cp -r close-reading-annotator/ ~/.cursor/skills/    # Cursor
cp -r close-reading-annotator/ ~/.claude/skills/    # Claude Code
# TRAE / VS Code Copilot：放 skills 目录或 .copilot/skills/
# 纯手动模式：直接把本文件当 system prompt 喂任意大模型
```

---

## 10. 版本历史

| 版本 | 日期 | 变化 |
|------|------|------|
| **2.8.0** | 2026-09-04 | **数据修复与管道硬化**（v2.8 Gate 0-3 + R1.0）：①Gate 0 冻结侦查——manifest.json（24文件SHA256+mtime）+ contamination_report.json（确认无真实跨书污染，11处专有名词命中全为误报）+ segmentation_version_record.json；②R1.0 根因复盘——`docs/rca/data_quality_rca_v28.md`，4项问题根因定位，**关键修正：上一轮"emotion空壳行"为格式误判**（D19_emotion_analysis多嵌套一层，138行全部有primary）；③Gate 1 数据修复——594行全部修复：craft 152行/emotion 138行格式统一（顶层craft→layers.craft，D19_emotion_analysis嵌套→layers.emotion直接格式），checkpoint重建（moon 89段/345层条目，shanghai 63段/249层条目），删除4个临时文件，_provenance字段全覆盖（run_id/generator/model/generated_at）；④Gate 2 机械验证——新增 `scripts/audit_v27.py`（V2.1引文/V2.2常量/V2.3坐标/V2.4 ID四项校验），运行结果0错误15警告（非强制），`audit_report_v28.json`；⑤Gate 3 D18补齐——shanghai 58/63行有D18（92.1%），新增150条D18覆盖7角色，moon原有83.1%，两书均>80%达标。**schema.md同步升级2.8.0**：新增_provenance全局元字段、emotion格式统一、D18扩展speech_verb_distribution/dialogue_length_avg。v2.9全局聚合器MVP/v3.0生成器就绪为后续版本。 |
| **2.7.0** | 2026-09-04 | 新增 **D19 情感分析**（P4 Pass，Layer 2.5 语义扩展）：独立 `emotion.jsonl` + emotion-output 模板 + `emotion-lexicon.md`（44 词，D19 枚举真源例外）；schema/validate/checkpoint/merge/render 全接入；P4 触发条件四则。L1–L3 schema 不变，旧产物零迁移（决策 17）。**同日工程化修复轮（决策 18，未升版）**：annotate_segment 新增 `--input-json` 非交互注入 + `--all-pending` 批量驱动 + 校验失败自动 span 修复重试 ≤3 次（兑现承诺）+ 幂等 upsert 落盘；span 定位抽公共模块 `span_locator.py`（fill_spans 复用）；新增 `select_segments.py`（段采样分层）与 `run_pipeline.py`（Phase 1–5 一体化 + --plan/--resume）；SKILL.md 定位改写（scripts=核心组件）+ 瘦身；新增 `docs/RUNBOOK.md`。 |
| **2.6.0** | 2026-09-04 | 真实全本（月亮与六便士）打补丁 + 小增强（v2.5.1 合入）：①Windows GBK 打印崩溃修复；②checkpoint 加载路径错位修复；③cross_segment 完成自动回写标记；④MD 报告补 L2/L3 摘要；⑤HTML 报告补 D04 极性列；⑥D04.polarity 必填（旧产物豁免）；⑦cross_segment 锚点清洗 + `--preserve-curated`；⑧checkpoint.py 加 `--dir`；⑨新增 `fill_spans.py`；⑩全脚本升 2.6.0。 |
| 2.5.0 | 2026-09-04 | 3→4 层架构大升级 + 7 项 P0 bug 修复（ID 碰撞/坐标漂移/无边界截断/frontmatter 丢弃/L4 占位/merge 字段/segment_id 前缀）+ schema 单一真源 + 4 层模板 + checkpoint 状态机 + span 段内相对偏移。 |
| ≤2.3.0 | 2026-08-31~09-03 | 早期单片段版。2.2.0（12 维含 D02/D03）**已废弃**。 |

> 版本号 SemVer：主版本=Schema 不兼容；次版本=新增枚举/可选维度（宽松兼容）；修订号=bugfix/锚点校准不改字段。**修复轮不升版本**——frontmatter/schema 保持 2.7.0，四者一致不破坏；本修复轮内容随下个 feature 版本正式记录。

---

*精读批注 Skill v2.7 — "先验证，再声称；每段每层落盘；二阶段跨段；四层合一，情感入轨。从『规格正确』走向『实现可运行』。"*
