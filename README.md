# 精读批注 Skill v3.5.0

> 对叙事文本做 **四层结构化精读批注** 的完整 Skill 包：结构层（叙事功能/情绪/节奏/视角/时空/对话功能/描写类型）、阐释层（信息控制/主题/叙述者可靠性）、情感层（角色情感/情感对象/段内情感弧）、文笔层（佳句/修辞/意象/词汇/句式/人物语言指纹），外加跨段层（伏笔链/段间关系）与**全局聚合层**（实体/场景/角色弧线/故事类型/因果链/物件链/故事图/适配器）。
> 适合：小说精读、故事拆解、叙事分析、文笔拆解、结构化语料构建。
> 本仓库即**完整可运行的 Skill 包**——放到 TRAE / Cursor / Claude Code 的 skills 目录即可使用，也支持纯手动模式（把 `SKILL.md` 注入任意大模型）。
> **版本（决策 22 三域解耦）**：skill_version = `3.5.0` / annotation schema_version = `2.9.0` / aggregation schema_version = `3.0.0`。批注 JSON 向后兼容 `2.5.0`/`2.6.0`/`2.7.0`/`2.8.0`/`2.9.0`。

---

## 一、快速安装

### 方式 1：作为 IDE Skill（推荐）

```bash
# Cursor
cp -r close-reading-annotator/ ~/.cursor/skills/

# Claude Code
cp -r close-reading-annotator/ ~/.claude/skills/

# TRAE 等其他 IDE：把整个目录放到 skills/ 下即可（会自动读取 SKILL.md）
```

然后直接说：「精读这段：粘贴文本」或「精读 + 文笔拆解：」或「拆伏笔链：」。

### 方式 2：纯手动（任何大模型都能用）

直接把 [SKILL.md](SKILL.md) 作为 System Prompt 注入，效果完全等价；`scripts/` 里的工具按需手动运行。

---

## 二、快速上手：拿自带样例跑一遍

仓库自带公版样例 [examples/sample_input.txt](examples/sample_input.txt)（《基督山伯爵》公版开头重述，约 1850 字），可用于验证完整管线：

```bash
# 在仓库根目录执行

# Phase 1：切分 + 初始化 checkpoint
python scripts/preprocess.py \
  --input examples/sample_input.txt \
  --doc-id sample_novel_zh \
  --output-dir outputs/annotations/sample_novel_zh \
  --max-tokens 800

# Phase 2：逐片段批注（先只跑结构层，进入"手动模式"体验流程）
python scripts/annotate_segment.py \
  --segments outputs/annotations/sample_novel_zh/sample_novel_zh_segments.jsonl \
  --doc-id sample_novel_zh \
  --segment sample_novel_zh_seg_0000 \
  --layers structure \
  --output-dir outputs/annotations/sample_novel_zh

# 校验
python scripts/validate_output.py \
  --jsonl outputs/annotations/sample_novel_zh/sample_novel_zh_structure.jsonl

# 断点续跑进度
python scripts/checkpoint.py status --doc-id sample_novel_zh
```

> ⚠️ `annotate_segment.py` 不内嵌任何大模型调用（**调度壳**）：不传 `--llm-cmd` 时进入手动模式——打印标准 Prompt 输入片段，你把 LLM 输出的 JSON 粘贴回来即可；传 `--llm-cmd "<命令>"` 时自动流水（命令接收 stdin JSON、返回 stdout JSON）。
> ⚠️ **运行时产物严禁写入 `examples/`**（避免污染分发包），统一落在 `--output-dir`。

---

## 三、完整流水线（Phase 1–5）

**设计原则**：每段每层独立落盘 → 支持断点续跑 → 跨段分析二阶段独立一次 → 各层合并。任何环境都能只跑其中一部分（纯 LLM 环境可跳过 scripts 手动批注）。

### Phase 1：输入预处理（切分 + 初始化 checkpoint）

```bash
python scripts/preprocess.py \
  --input path/to/novel.txt \
  --doc-id my_novel_01 \
  --output-dir outputs/annotations/my_novel_01 \
  --max-tokens 2000
```

产出：`<doc_id>_segments.jsonl`（每行一个片段，含 `segment_id`/`chapter`/`section_type`/`text_span`/`context_prev`/`context_next`）+ `<doc_id>_checkpoint.json`。

切分能力：
- 章节边界识别：「第X章」「Chapter X」「「　　一」单独成行（兼容行首空白）」「序章/楔子/尾声/后记/Prologue/Epilogue」
- frontmatter 显式输出为 `section_type="frontmatter"` 片段（不静默丢弃）
- 无章节边界时退化为按段落 + 句子边界的长度智能切分，**全书不截断**
- 坐标自校验断言：每个片段 `start_char/end_char` 切片与原文比对，漂移即抛异常
- 全局 segment 计数器：`segment_id = {doc_id}_seg_{4位十进制}`（跨子切不回零，防 ID 碰撞）
- 每段自动注入前后 200 字符上下文锚点；中文 token 估算 = `cn_char + en_words` 组合

### Phase 2：逐片段批注（L1 结构 / L2 阐释 / L3 文笔 / P4 情感）

```bash
python scripts/annotate_segment.py \
  --segments outputs/annotations/my_novel_01/my_novel_01_segments.jsonl \
  --doc-id my_novel_01 \
  --segment my_novel_01_seg_0001 \
  --layers structure,interpretation,craft \
  --output-dir outputs/annotations/my_novel_01
```

- `--layers` 组合：`structure` / `structure,interpretation` / `structure,interpretation,craft`，可加 `emotion`（P4，D19 情感分析）
- **P4 情感层（v2.7）**：`--layers emotion` 时脚本自动读取该段 structure 的 D01/D04/D10 作为触发判定上下文并注入原文；情感词枚举 50 词见 [references/emotion-lexicon.md](references/emotion-lexicon.md)；`target/trigger/arc` 无明确值必须写 `null` + `null_reasons`，禁止编造
- 断点续跑：`--resume`（默认开启）自动跳过 checkpoint 中已完成的 `(segment, layer)`
- 每层产出自动跑 validate_output，通过才写 checkpoint + JSONL，失败最多重试 3 次

### Phase 3：跨段分析（Layer 4，整体一次）

跨段关系必须看到整本书的完整图景才能判断（伏笔-回收/呼应），不能混在逐段批注里：

```bash
python scripts/cross_segment.py \
  --doc-id my_novel_01 \
  --segments outputs/annotations/my_novel_01/my_novel_01_segments.jsonl \
  --structure outputs/annotations/my_novel_01/my_novel_01_structure.jsonl \
  --interpretation outputs/annotations/my_novel_01/my_novel_01_interpretation.jsonl \
  --craft outputs/annotations/my_novel_01/my_novel_01_craft.jsonl \
  --window-size 15 --overlap 3
```

产出 `cross_segment.jsonl`。每条 `cross_ref` 是**双引用**（`segment_id` 位置 ID + `anchor_text` 内容锚点）——将来切分版本变化导致序号漂移时，`anchor_text` 仍可在原文检索重定位，关系链不静默失效。
实现为**启发式规则先行**（情绪强度突变=因果候选、视角切换=时序候选、D09 主题复用=呼应候选、D06 埋设-揭露=伏笔-回收候选），保证首次运行就产出可用列表；高精度 LLM 二分类可留给你自己的批量管线叠加。重跑默认 `--preserve-curated` 保留人工核验过的条目（规则条目带 `_source:'rule'` 标记）。

### Phase 4：合并（嵌套文档）

```bash
python scripts/merge_layers.py \
  --doc-id my_novel_01 \
  --segments outputs/annotations/my_novel_01/my_novel_01_segments.jsonl
```

产出 `merged.jsonl`——每行一个 segment，把该段 L1/L2/L3 + 情感层 + 该段作为 source/target 的 cross_refs ID 嵌套在一起。优先从 segments 读 `text_span`（兼容 annotation 自带 `text_span` 的形态）。

### Phase 5（可选）：人类可读报告

```bash
python scripts/render_report.py --doc-id my_novel_01 --format html
python scripts/render_report.py --doc-id my_novel_01 --format md
```

产出 `report.html` / `report.md`（零第三方依赖，HTML 内联 CSS 直接浏览器打开）。含结构全景（章节/片段数、叙事功能分布、情绪强度折线、节奏条形）、主题/佳句 Top/修辞统计、跨段关系列表。

### 校验（任意 Phase 后均可跑）

```bash
python scripts/validate_output.py --jsonl <某层>.jsonl
# --layer-type 可选：auto(默认) / structure / interpretation / emotion / craft / cross_segment / merged
```

校验内容：
- Schema 字段存在性 + 枚举合法性（枚举只认 `references/schema.md` 唯一真源）
- 引文抽取 + 子串验证（D06 / D13–D17 引文必须是 `text_span.text` 子串）
- span 位置断言（`0 ≤ start < end ≤ len`，切片相似度 ≥95%；85–95% warning，<85% error）
- 置信度 ↔ status 自动对齐（overall ≥0.8 才允许 `confirmed`）
- 必填维度置信度不可为 null；emotion 层额外校验 50 词枚举与情感弧端点

### 脱敏导出（入库前必须跑）

```bash
python scripts/export_dataset.py \
  --input outputs/annotations/my_novel_01/my_novel_01_merged.jsonl \
  --output outputs/annotations/my_novel_01/my_novel_01_dataset.json
```

把所有可能携带原文的字段（`text_span.text`/引文/anchor_text 等）替换为 `【已脱敏】` + 长度/哈希，仅保留抽象结构化字段。**训练入库必须用脱敏版。**

### 其他工具

```bash
python scripts/checkpoint.py status --doc-id my_novel_01            # 查询进度
python scripts/checkpoint.py reset-layer --doc-id my_novel_01 --layer structure  # 重置某层
python scripts/checkpoint.py reset-all --doc-id my_novel_01         # 整体重置
python scripts/fill_spans.py ...   # 回补存量批注缺失的 span（历史产物迁移用）
```

---

## 四、目录结构（v2.8）

```
close-reading-annotator/
├── SKILL.md                         # [核心入口] Skill 本体（Prompt 包），任何平台都读它
├── README.md                        # 本文件
├── LICENSE                          # MIT
│
├── references/                      # Schema / 参考文档
│   ├── schema.md                    # 【唯一真源】Schema 完整定义（枚举/字段约束/span 坐标系/引文校验/置信度/版本声明）
│   ├── annotation-examples.md       # Few-shot 完整批注示例
│   ├── emotion-anchors.md           # 情绪强度校准锚点（文学描写分档）
│   ├── emotion-lexicon.md           # D19 情感词枚举表（50 词，含触发式判定指引）
│   ├── function-anchors.md            # D01 叙事功能判别锚点（v3.1 新增，Freytag+Labov）
│   └── pace-anchors.md              # 叙事节奏校准锚点
│
├── templates/                       # 每层输出模板（均通过 validate_output.py 0 error 校验）
│   ├── structure-output.json        # L1 结构层
│   ├── interpretation-output.json   # L2 阐释层
│   ├── emotion-output.json          # D19 情感层（v2.7 新增，P4；v2.8 格式统一）
│   ├── craft-output.json            # L3 文笔层（v2.8 格式统一 layers.craft）
│   ├── cross-segment-output.json    # L4 跨段层
│   └── merged-output.json           # Phase 4 合并嵌套文档
│
├── scripts/                         # 可选辅助脚本（零第三方依赖，Python 3.10+）
│   ├── preprocess.py                # Phase 1：切分 + checkpoint 初始化
│   ├── annotate_segment.py          # Phase 2：单片段调度壳（手动 / --llm-cmd / --input-json / --all-pending）
│   ├── cross_segment.py             # Phase 3：跨段启发式规则
│   ├── merge_layers.py              # Phase 4：合并 + cross_refs 投影
│   ├── render_report.py             # Phase 5：HTML/MD 报告
│   ├── validate_output.py           # 统一校验器
│   ├── checkpoint.py                # checkpoint 读写 + CLI（status/reset-layer/reset-all）
│   ├── fill_spans.py                # 回补存量批注 span
│   ├── export_dataset.py            # 脱敏导出训练数据
│   ├── span_locator.py              # v2.7 新增：span 定位公共模块（fill_spans/annotate 复用）
│   ├── select_segments.py           # v2.7 新增：段采样分层（deep/light/skip 分档）
│   ├── run_pipeline.py              # v2.7 新增：Phase 1–5 一体化驱动 + 断点续跑 + --plan
│   ├── quality_gate.py              # v3.4 新增：Phase 0 数据质量看门狗（五维检测，粗切前硬门槛）
│   ├── quant_analyzer.py            # v3.4 新增：Phase 1.5 计算文学分析（逐 segment 量化指标，jieba 可选）
│   ├── reshape_segments.py          # v3.5 新增：Phase 1.25 精细化切分重排（场景边界判断后按字符区间重切）
│   │
│   └── aggregation/                 # v2.9/v3.0 新增：全局聚合器（批注完成后运行，独立后处理）
│       ├── entity_resolution.py     # v2.9 Step 1：实体消解（→ entity_graph.json）
│       ├── scene_graph.py           # v2.9 Step 2：场景图重建（→ scene_graph.json）
│       ├── character_arcs.py        # v2.9 Step 3：角色弧线重建（→ character_arcs.json）
│       ├── story_type_inference.py  # v2.9 Step 4：故事类型推断（→ story_metadata.json）
│       ├── causal_graph.py          # v3.0 Step 4：因果链生成（→ causal_graph.json）
│       ├── object_chains.py         # v3.0 Step 5：物件链追踪（→ object_chains.json）
│       ├── story_graph.py           # v3.0 Step 6：故事图合并（→ story_graph.json）
│       └── adapters.py              # v3.0：text2story / YARN / NCP 适配器
│
├── docs/
│   └── RUNBOOK.md                   # v2.7 新增：Agent 最小操作契约（CLI 速查 + 校验错误修复表）
│
└── examples/
    ├── sample_input.txt             # 公版示例输入：《基督山伯爵》开头片段重述
    └── llm_wrapper.py               # v2.7 新增：官方 LLM 适配模板（零依赖，--mock 冒烟）
```

---

## 五、版本治理（决策 22：三版本域解耦）

| 版本域 | 声明点 | 值 |
|--------|--------|-----|
| **skill version** | `SKILL.md` frontmatter `version` / README / RUNBOOK | `3.5.0` |
| **annotation schema_version** | `references/schema.md` §一 / 批注 JSON `schema_version` / annotate_segment.py / examples/llm_wrapper.py | `2.9.0` |
| **aggregation schema_version** | `references/aggregation-schema.md` / `scripts/aggregation/*.py` | `3.0.0` |

> 三域独立演进（决策 22）：skill 能力升级不再强绑定批注字段变更；批注 JSON 向后兼容 `2.5.0`/`2.6.0`/`2.7.0`/`2.8.0`/`2.9.0`（旧产物版本分支豁免，不迁移）。
> 修改批注层枚举/字段约束：**先改 `references/schema.md`，再同步 templates / validate_output.py / SKILL.md 速览**。修改聚合层产物字段：**先改 `references/aggregation-schema.md`，再改 `scripts/aggregation/*.py`**。完整历史见 [SKILL.md](SKILL.md) 底部「版本历史」。

主要里程碑：
- **v3.5.0**：精细化切分器/重排（T-034，ADR-014）——SKILL.md 新增 Phase 1.5 场景边界判断 Prompt（LumberChunker 思想 Skill 化，四维度：地点/时间/视角/主题）+ `reshape_segments.py` 后处理重排（读粗切 segments + scene_boundary + 原文 → final_segments 场景级 + 新旧 ID 映射，按字符区间重切，章节边界自动识别）。annotation/aggregation schema 不变（纯预处理增强）
- **v3.4.0**：前置双模块（T-033，ADR-014）——`quality_gate.py` 数据质量看门狗（五维检测：中文占比/引号闭合/乱码/段落结构/重复性，粗切前硬门槛）+ `quant_analyzer.py` 计算文学分析（逐 segment 句长/TTR/词性/对话占比/标点/情感词频(DLUT子集)/五感密度，jieba 可选自动降级）。annotation/aggregation schema 不变（纯前置脚本）
- **v3.3.0**：DLUT 完整引入（T-032，ADR-013）——清洗子集 `references/lexicon-dlut-subset.json`（27,465→9,924 词）随包分发、`emotion-taxonomy.md` 三级映射表（21 小类→8 基元→D19 词位）、`build_dlut_subset.py` 生成器、crosscheck 默认读子集（一般使用者无需外部数据）
- **v3.2.0**：一致性基础设施（T-031，ADR-012）——lexicon_crosscheck（DLUT/NRC 对照）、collect_lexicon_candidates（WikiSkill 经验回写）、Trace2Skill SoP、llm_wrapper 枚举约束
- **v3.0.1**：聚合层修复轮（T-029）——adapters 字段名对齐（text2story/YARN/NCP 内容性字段全部非占位）、entity_resolution 输出 segment_ids 完整段集合（修复出场角色截断）、全脚本确定性（sorted + 平票 tie-break，复现性验证通过）、题材词表去书名化、is_reliable=None、文档收编（aggregation-schema.md 真源 + 决策 19-22）、版本号解耦 ADR
- **v3.0.0**：生成器就绪——causal_graph（因果链）、object_chains（物件链）、story_graph（故事图合并）、adapters（text2story/YARN/NCP）
- **v2.9.0**：全局聚合器 MVP——entity_resolution、scene_graph、character_arcs、story_type_inference
- **v2.8.0**：数据修复与管道硬化（Gate 0-3 + R1.0）——594行格式统一（craft顶层→layers.craft，emotion D19嵌套→直接格式）、_provenance溯源字段全覆盖、checkpoint重建、D18补齐（shanghai 92.1%）、机械审计脚本audit_v27.py、schema.md同步升级
- **v2.7.0**：新增 D19 情感层（P4 独立产物 `emotion.jsonl`）、`emotion-lexicon.md`、`emotion-output.json` 模板、P4 触发式流程；同日工程化修复轮（决策18）：--input-json/--all-pending批量驱动、校验失败自动span修复重试、select_segments段采样、run_pipeline一体化、RUNBOOK.md
- **v2.6.0**：真实全本运行补丁（Windows GBK 编码/checkpoint 回写/报告增强）+ D04 `polarity` 必填 + `--preserve-curated` + `fill_spans.py`
- **v2.5.0**：架构大升级 3 层 → 4 层（每层独立 JSONL、二阶段跨段、merged、7 项 P0 修复）
- **v2.0–v2.3**：单 JSONL 时代（已废弃，数据需迁移）

---

## 六、分级策略（成本与质量权衡）

| 档级 | 跑哪些层 | 适用场景 |
|:----:|:---------|:---------|
| 轻量档 | Phase 1 + 2（仅 structure）+ 4 | 大规模批量、先扫描全貌（约 80% 文档） |
| 标准档 | Phase 1 + 2（structure + interpretation）+ 3 + 4 | 普通精读 / 拆解 |
| 深度档 | Phase 1–5 全跑（含 craft + cross_segment + report） | 深度研究 / 训练样本核心池 |

> 【成本纪律】请勿把全量深度维度跑应用到百万级文本——20% 深度档提供 80% 价值，80% 轻量档扩充基数。

---

## 七、环境要求

| 组件 | 必需？ | 要求 |
|------|:------:|------|
| SKILL.md（Prompt 包） | ✅ | 零依赖，纯 Markdown |
| scripts/ | ❌ 可选 | Python 3.10+，仅标准库，无需任何第三方包 |
| IDE Skill 生态 | ❌ 可选 | TRAE / Cursor / Claude Code 任一；纯手动模式不需要 |

刻意保持零第三方 Python 依赖——任何"裸"环境都能直接跑。若将来需要 tokenizer/模型调用等重依赖，会单独放 `scripts/optional/`，不影响现有脚本。

---

## 八、版权合规（重要）

1. **输入**：只批注公版作品、明确授权作品、或你自己的文本。对在版权期内的商业作品做批量批注仅供个人研究，不要分发原文片段。
2. **输出**：`text_span.text` 会携带原文片段——公开发布批注产物前请谨慎；训练入库前必须跑 `export_dataset.py` 脱敏（「分析即销毁」：只留抽象结构化字段）。
3. **外部词库数据（v3.3 / ADR-013，DLUT 清洗子集已随包分发）**：
   > **一般使用者无需下载任何外部词库**——批注主链路（validate/annotate/checkpoint/merge）自包含，直接用内置 D19 50 词表与 D04 20 词枚举；词表演化工具（`lexicon_crosscheck.py`）也已默认读仓库内 DLUT 清洗子集（`references/lexicon-dlut-subset.json`，9,924 词），开箱即用。
   - **DLUT 大连理工《情感词汇本体》**（27,466 词，7 大类 21 小类，强度 1/3/5/7/9 五档）：本仓库已附**清洗子集**（词性 adj/verb/noun/adv + 词长 ≤2，含来源/许可/引用声明，由 `scripts/build_dlut_subset.py` 从官方 xlsx 生成）。**仅词表维护者（Owner）**需自行从大连理工信息检索研究室（ir.dlut.edu.cn）下载全量 xlsx 以重新生成子集；学术使用请引用论文《情感词汇本体的构造》（徐琳宏、林鸿飞等）。许可：仅供科研及教学使用、未经允许不得用于商业用途。
   - **NRC EmoLex**（14,182 词，8 基元+2 极性，40 语言）：从作者官网 https://www.saifmohammad.com/WebPages/AccessResource.htm 申请下载；**许可明文禁止再分发（Do not redistribute）**——本仓库不打包任何 NRC 数据；中文单语场景下仅作体系参照（ADR-012/013），**一般使用者无需下载**。
   - 建议放置位置（仅维护者需要）：调用方工作区 `datasets/`（`lexicon_crosscheck.py` 的 `--dlut`/`--nrc` 默认从该处寻找）。
   - 相关工具：`scripts/lexicon_crosscheck.py`（DLUT ↔ D19 覆盖度对照 + 候选词生成，默认子集模式）、`scripts/build_dlut_subset.py`（全量 → 清洗子集生成器）、`scripts/collect_lexicon_candidates.py`（产物自由情感词 ≥3 次 → 候选，WikiSkill 经验回写）、`references/emotion-taxonomy.md`（21 小类三级映射表）。

---

## 九、常见问题

### Q1：Skill 为什么不自动调 scripts/？
A1：刻意设计。SKILL.md 本体是**纯 Prompt 包**——任何能读 Markdown 的平台都能用，不捆绑任何脚本/API。在 Agentic 环境（TRAE/Cursor/Claude Code）下 AI 会按 Phase 1–5 工作流自动调用；纯 LLM 聊天里按第三节命令手动启动。

### Q2：我只想在 500 字片段上做一次批注，也要跑 5-Phase 吗？
A2：不用。5-Phase 是长文本/批处理的最完整走法。小片段直接对 AI 说「精读这段：粘贴文本」，AI 按 `templates/` 输出对齐即可。

### Q3：validate_output.py 报「引文不在原文中」但我觉得是对的？
A3：校验器先做空白归一化（`" ".join(s.split())`）再判子串。常见原因：(a) 引文 copy 回写时多了/少了前后标点；(b) 换行合并多了字。若为标点差异，相似度 ≥95% 会降级为 warning——把 `span` 边界补齐精确即可。

### Q4：checkpoint 显示某阶段完成但我想重跑？
A4：`reset-layer` 重置 structure 会连带清掉依赖它的 cross_segment / merged / report；只想重置后者可直接把 `{doc_id}_checkpoint.json` 中对应字段（`cross_segment_completed` / `merged_completed` / `render_report_completed`）改回 `false`。

### Q5：老版本（v2.3 单 JSONL）产物能直接进新管线吗？
A5：不能，需要按新 Schema 迁移（结构层字段大改，需逐字段映射并回补 span）。建议对原文重新走一遍 v2.7 管线，迁移成本通常更低。

---

## 十、参考文档索引

| 文档 | 什么时候读 |
|------|-----------|
| [references/schema.md](references/schema.md) | 改枚举/校验/字段前必读（唯一真源） |
| [references/annotation-examples.md](references/annotation-examples.md) | 开始批注前看 1–2 条找格式感觉 |
| [references/emotion-anchors.md](references/emotion-anchors.md) | 情绪强度判断犹豫时 |
| [references/emotion-lexicon.md](references/emotion-lexicon.md) | D19 情感层标注前（50 词枚举） |
| [references/function-anchors.md](references/function-anchors.md) | D01 叙事功能标注前（每词 2 示例 + 边界判定，v3.1） |
| [references/pace-anchors.md](references/pace-anchors.md) | 节奏判断犹豫时 |

> 架构与设计决策记录（`docs/architecture.md`、`docs/design-decisions.md`）已移至项目工作区 `docs/` 归档（T-028 起，skill 分发包只保留运行必需文档）。

---

## License

MIT，见 [LICENSE](LICENSE)。
