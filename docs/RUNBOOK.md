# RUNBOOK — close-reading-annotator 最小操作契约

> **定位**：给 Agent / 新运行者的速查手册。比 SKILL.md 短，只记"怎么跑、报错怎么修、常见坑"。
> 完整 schema / 枚举 / 设计决策见 `references/schema.md`（批注层）、`references/aggregation-schema.md`（聚合层）、`SKILL.md`、工作区 `docs/design-decisions.md`。
> 版本：skill v3.17.1 / annotation schema 2.10.0 / aggregation schema 3.5.0（决策 22 三域解耦）

---

## 0. 5 分钟跑通全流程（冒烟测试）

> **v3.17.0 流程架构**：连续 Phase 1–8，**无任何可选步骤**。聚合层/精确切分/校准均为必须阶段；报告是最后一步。

```bash
# 假设 skill 目录为 ./close-reading-annotator，输出目录为 ./out
SKILL=./close-reading-annotator
OUT=./out
DOC=my_book

# 一条命令全流程（推荐）：质量门→粗切→LumberChunker→四层批注→跨段→聚合→合并→校准→报告
python $SKILL/scripts/run_pipeline.py --input book.txt --doc-id $DOC \
    --output-dir $OUT --llm-cmd "python $SKILL/examples/llm_wrapper.py --mock" --report-format md
# 断点续跑是默认行为（读 checkpoint 跳过已完成阶段/片段）；--force 强制重跑

# === 手动分步执行（等价，便于观察每步输出） ===

# Phase 1：输入预处理（1a 质量门硬门槛 + 1b 粗切分）
python $SKILL/scripts/quality_gate.py --input book.txt --out $OUT/${DOC}_quality_report.json --fail-on-error
# 检查 verdict：fail 项必须修复原文后重跑（不允许带病进入切分）
python $SKILL/scripts/preprocess.py --input book.txt --doc-id $DOC --output-dir $OUT

# Phase 2：LumberChunker 场景语义精确切分（必须，不允许跳过）
# 2a 场景边界判断（主流程：Agent 按 SKILL.md §3.2 的 Prompt 逐对判断，产出 scene_boundary.json，无需 API key；命令行替代：wrapper）
export SCENE_BOUNDARY_API_KEY="your-api-key"   # 兼容 OpenAI/DeepSeek 等
python $SKILL/examples/scene_boundary_wrapper.py \
    --segments $OUT/${DOC}_segments.jsonl --output $OUT/${DOC}_scene_boundary.json --doc-id $DOC
# 2b 重排为场景级 segments
python $SKILL/scripts/reshape_segments.py \
    --segments $OUT/${DOC}_segments.jsonl \
    --boundaries $OUT/${DOC}_scene_boundary.json \
    --original book.txt \
    --doc-id $DOC --output-dir $OUT
# 产出 ${DOC}_final_segments.jsonl（场景级）+ ${DOC}_segment_id_mapping.json（新旧ID映射）
# 后续 Phase 3-8 全部使用 final_segments.jsonl（run_pipeline 自动切换）

# Phase 3：逐段批注（四层全量 × 全部 segment，无采样）
python $SKILL/scripts/annotate_segment.py \
    --segments $OUT/${DOC}_final_segments.jsonl \
    --doc-id $DOC --output-dir $OUT \
    --layers structure,interpretation,craft,emotion --all-pending \
    --llm-cmd "python $SKILL/examples/llm_wrapper.py --mock"

# Phase 4：跨段分析（Layer 4 规则启发式）
python $SKILL/scripts/cross_segment.py --doc-id $DOC \
    --segments $OUT/${DOC}_final_segments.jsonl --structure $OUT/${DOC}_structure.jsonl \
    --interpretation $OUT/${DOC}_interpretation.jsonl --craft $OUT/${DOC}_craft.jsonl \
    --output-dir $OUT

# Phase 5：聚合层（必须，12 脚本全跑；也可用 run_pipeline --phases 5）
# 全部命令见 §2.7；产物在 $OUT/aggregation/

# Phase 6：合并
python $SKILL/scripts/merge_layers.py --doc-id $DOC \
    --segments $OUT/${DOC}_final_segments.jsonl --output-dir $OUT

# Phase 7：后处理校准（必须，位于报告之前）
python $SKILL/scripts/calibrate_quality.py --dir $OUT --doc-id $DOC --in-place
python $SKILL/scripts/recalibrate_confidence.py --dir $OUT --doc-id $DOC --all-layers --in-place
python $SKILL/scripts/cross_validate_emotion.py --dir $OUT --doc-id $DOC --in-place

# Phase 8：报告渲染（最后一步，含全部四层 + 跨段 + 聚合 12 模块）
python $SKILL/scripts/render_report.py --doc-id $DOC --output-dir $OUT --format md \
    --agg-dir $OUT/aggregation
```

HTML 报告含：TOC / 聚合分析 12 模块（故事概览/叙事结构/实体图谱/场景图/角色弧线/关系网络/因果图/物件链/人物传记/叙事技法/故事图/适配器三格式）/ 3 张 SVG 图 / L1-L4 摘要 / 全量逐段详情（`<details>` 折叠，每段四层全字段）。
MD 报告含：聚合分析 12 模块摘要 + L1-L4 摘要（不含 SVG）。

**验证**：`python $SKILL/scripts/checkpoint.py status --doc-id $DOC --dir $OUT` 全部 100%。

> **骨架模式**（批注已就绪，只跑跨段→聚合→合并→校准→报告）：`python $SKILL/scripts/run_pipeline.py --doc-id $DOC --output-dir $OUT --phases 4,5,6,7,8`

---

## 1. 三种批注模式（Phase 2 核心选择）

| 模式 | 命令 | 适用场景 | 交互性 |
|------|------|---------|--------|
| **手动粘贴** | `--segment X --layers structure`（无 --llm-cmd） | 人在终端操作，复制 prompt 给 LLM 再粘贴 JSON 回来 | 交互式（需 Ctrl+Z+回车 / Ctrl+D） |
| **非交互注入** | `--input-json 批注行.jsonl` | Agent 已自备批注 JSON（自己生成或从别处导入），只需要校验+落盘+checkpoint | 非交互，一行命令 |
| **全自动批量** | `--all-pending --llm-cmd "python wrapper.py"` | 接了真实 LLM wrapper，一次性跑完所有未完成段 | 非交互，批量 |

### 模式选择决策树

```
有外部 LLM API 可用？
├─ 是 → 写 wrapper（参考 examples/llm_wrapper.py）→ --all-pending --llm-cmd
└─ 否 → Agent 自己生成批注 JSON？
        ├─ 是 → --input-json 注入
        └─ 否 → 手动模式（人 + 另开 LLM 对话窗口）
```

---

## 2. CLI 速查表

> **输出参数统一约定（v3.15.0，T-126）**：所有产出型脚本统一用 `--output-dir` 指定输出位置；其中 `merge_layers.py` / `cross_segment.py` / `render_report.py` 的 `--output-dir` 同时兼容旧别名 `--output`（两者等价）。**注意：这 3 个脚本的 `--output-dir` 接收的是"输出文件路径"**（不是目录），不传时默认写到当前目录的 `{doc_id}_<产物名>`。聚合层 12 脚本的 `--output-dir` 才是真正的"输出目录"。

### 2.1 preprocess.py（Phase 1）

```bash
python scripts/preprocess.py --input <原文.txt> --doc-id <doc_id> --output-dir <out>
```
- 产出：`{doc_id}_segments.jsonl` + `{doc_id}_checkpoint.json`
- 每段 ≈2000 token，前后 200 字符上下文锚点（`--overlap-chars` 可改）
- 无章节边界时全书不截断，打 `pollution_warning`

### 2.2 annotate_segment.py（Phase 2 核心）

```bash
# 通用参数
--segments <segments.jsonl>    # 必填
--doc-id <doc_id>               # 必填
--output-dir <out>              # 层 JSONL 输出目录
--checkpoint <ckpt.json>        # ⚠️ 强烈建议显式指定，否则默认 cwd（见坑点#1）
--layers structure,interpretation,craft   # 默认三层；emotion 需显式加
--force                         # 忽略 checkpoint 强制重跑（幂等 upsert，不产生重复行）

# 三种模式三选一（见 §1）
--segment <seg_id>              # 单段模式（手动或 --llm-cmd）
--input-json <file.jsonl>       # 非交互注入（支持单 JSON / JSON 数组 / JSONL）
--all-pending                    # 批量模式（需配合 --llm-cmd 或 --input-json）
--llm-cmd "python wrapper.py"   # 外部 LLM 命令（stdin 收 JSON，stdout 返 JSON）
```

**自动行为**：
- 校验失败 → craft 层 span 自动回算修正并重试 ≤3 次（决策 18 兑现）
- 落盘 → 幂等 upsert（同 segment 同层旧行被替换，不重复）
- checkpoint → 自动 `mark_layer_completed`

### 2.3 checkpoint.py（状态查询 / 重置）

```bash
python scripts/checkpoint.py status --doc-id <doc_id> --dir <out>     # 查看进度
python scripts/checkpoint.py reset-layer --doc-id <doc_id> --layer structure --dir <out>  # 重置某层
```

### 2.4 select_segments.py（v3.17.0 起不在正式流程内）

> **已从工作流移除**（v3.17.0 Owner 指令：无任何可选步骤、全量深度为唯一正式流程）。`--plan` 参数已从 run_pipeline 删除；正式执行不得使用段采样。脚本文件保留仅用于个人实验/资源受限场景，不属于本 skill 的流程。

### 2.5 run_pipeline.py（Phase 1-8 一体化，决策 18 新增 / v3.17.0 重构）

```bash
# 一条命令全流程：质量门→粗切→LumberChunker→四层批注→跨段→聚合→合并→校准→报告
python scripts/run_pipeline.py --input <原文.txt> --doc-id <doc_id> --output-dir <out> \
    --llm-cmd "python wrapper.py" --report-format md

# 骨架模式（批注已就绪，只跑跨段→聚合→合并→校准→报告）
python scripts/run_pipeline.py --doc-id <doc_id> --output-dir <out> --phases 4,5,6,7,8

# 只跑聚合层（批注+跨段已就绪）
python scripts/run_pipeline.py --doc-id <doc_id> --output-dir <out> --phases 5

# 断点续跑是默认行为（读 checkpoint 跳过已完成阶段/片段）；--force 强制重跑
```

**Phase 2 边界判断两种方式**：主流程为 Agent 按 SKILL.md §3.2 的 Prompt 逐对判断产出 `scene_boundary.json`（无需 API key）；命令行替代为 wrapper（需 `SCENE_BOUNDARY_API_KEY`，可选 `SCENE_BOUNDARY_BASE_URL` / `SCENE_BOUNDARY_MODEL`）。若已生成 `{doc_id}_scene_boundary.json`，可用 `--scene-boundary <file>` 直接走 reshape 重排（跳过边界判断调用）。

### 2.6 其他脚本

| 脚本 | 用途 |
|------|------|
| `cross_segment.py` | Phase 3：Layer 4 跨段关系（启发式规则，`--preserve-curated` 默认开） |
| `merge_layers.py` | Phase 4：同段 L1/L2/L2.5/L3 + cross_refs 投影嵌套 |
| `render_report.py` | Phase 5：MD / HTML 报告（零第三方依赖，内联样式） |
| `validate_output.py` | 单文件校验（`--json <file> --layer-type structure`） |
| `fill_spans.py` | 存量 craft 产物 span 回补（决策 18 后生成期已自动修复，此脚本仅用于旧产物迁移） |
| `export_dataset.py` | 训练数据导出脱敏（版权合规） |
| `span_locator.py` | 公共模块：`text.find` 定位 + 相似度回算（annotate_segment / fill_spans 共用） |
| `lexicon_crosscheck.py`（v3.3） | DLUT ↔ D19 覆盖度对照 + 候选词生成。**默认读仓库内清洗子集 `--subset`**（无外部数据即可跑）；子集缺失回退本地全量 `--dlut`；NRC 缺失自动跳过抽样。输出报告 `--out` |
| `collect_lexicon_candidates.py`（v3.2） | WikiSkill 经验回写：产物自由情感词 ≥3 次 → 候选（`--dir` / `--files`；`--sop` 输出 RUNBOOK 修复表行） |
| `build_dlut_subset.py`（v3.3） | 仅维护者：本地 DLUT 全量 xlsx → 清洗子集 `references/lexicon-dlut-subset.json`（`--dlut --out`） |
| `quality_gate.py`（v3.4） | **数据质量看门狗（Phase 0，粗切前必须跑）**：五维检测（中文占比/引号闭合/乱码/段落结构/重复性），产出 quality_report.json（pass/warn/fail + 修复建议）。`--input <txt|jsonl> --out <report.json>`；`--fail-on-error` CI 用 |
| `quant_analyzer.py`（v3.4） | **计算文学分析（批注前辅助）**：逐 segment 计算句长/TTR/词性/对话占比/标点/情感词频（DLUT 子集）/五感密度，产出 quant_metrics.jsonl。`--segments <segments.jsonl> --out <quant.jsonl>`；jieba 可选，缺失自动降级为 DLUT 最大正向匹配 |
| `reshape_segments.py`（v3.5） | **场景语义精确切分（Phase 2b，必须）**：读粗切 segments + scene_boundary.json（Agent 场景边界判断）+ 原始文本 → final_segments.jsonl（场景级，scene_NNN 编号）+ 新旧 ID 映射表。`--segments --boundaries --original --doc-id --output-dir`；章节边界自动识别，无 boundary 文件时仅按章节合并 |

### 2.7 aggregation/ 聚合层 12 脚本（v2.9/v3.0/v3.7/v3.8；v3.17.0 升级为必须，位于 Phase 5）

> **v3.17.0 定位：必须阶段**，位于跨段分析（Phase 4）与合并（Phase 6）之间；产物全部进入 Phase 8 报告展示。全链路 <2s/本，纯规则零依赖。Schema 真源：`references/aggregation-schema.md`。建议按 ①→⑫ 顺序跑；缺输入时各脚本自行报错，可逐脚本重跑（覆盖写，幂等）。run_pipeline Phase 5 按此顺序自动全跑。

| # | 脚本 | 必填参数 | 产出 |
|:-:|------|---------|------|
| ① | `entity_resolution.py` | `--segments --emotion --craft --structure --doc-id --output-dir` | `{doc}_entity_graph.json` |
| ② | `character_network.py` | `--entity-graph --doc-id --output-dir [--emotion] [--craft]` | `{doc}_character_network.json` |
| ③ | `scene_graph.py` | `--segments --structure --doc-id --output-dir --entity-graph` | `{doc}_scene_graph.json` |
| ④ | `character_arcs.py` | `--segments --structure --emotion --entity-graph --doc-id --output-dir` | `{doc}_character_arcs.json` |
| ⑤ | `story_type_inference.py` | `--segments --structure [--interpretation] [--emotion] --doc-id --output-dir` | `{doc}_story_metadata.json` |
| ⑥ | `narrative_structure.py` | `--structure --doc-id --output-dir` | `{doc}_narrative_structure.json`（弗雷塔格五幕+热奈特聚焦+叙事时间线+救猫咪节拍） |
| ⑦ | `writing_techniques.py` | `--structure --interpretation [--cross-segment] --doc-id --output-dir` | `{doc}_writing_techniques.json`（转场+悬念+蒙太奇+钩子） |
| ⑧ | `causal_graph.py` | `--cross-segment --structure --doc-id --output-dir` | `{doc}_causal_graph.json` |
| ⑨ | `object_chains.py` | `--craft --doc-id --output-dir [--include-all-types]` | `{doc}_object_chains.json` |
| ⑩ | `character_biographies.py` | `--segments --structure --interpretation --craft --emotion --cross-segment --entity-graph --character-arcs --character-network --narrative-structure --doc-id --output-dir` | `{doc}_character_biographies.json` |
| ⑪ | `story_graph.py` | `--aggregation-dir --doc-id --output-dir` | `{doc}_story_graph.json`（合并①-⑩） |
| ⑫ | `adapters.py` | `--story-graph --doc-id --output-dir [--formats text2story,yarn,ncp]` | `{doc}_{text2story,yarn,ncp}.json` |

**依赖顺序**：①→②（人物网络依赖实体图）→③④⑤⑥（依赖批注层+实体图）→⑦⑧⑨（依赖批注层+cross_segment）→⑩（依赖①-⑦ 产物）→⑪（依赖全部子图谱）→⑫（依赖故事图）。

**典型一条链**（`AGG=scripts/aggregation`，全部命令见 SKILL.md §3.5）：

```bash
python $AGG/entity_resolution.py --segments $OUT/${DOC}_segments.jsonl --doc-id $DOC \
    --output-dir $OUT/aggregation --emotion $OUT/${DOC}_emotion.jsonl \
    --craft $OUT/${DOC}_craft.jsonl --structure $OUT/${DOC}_structure.jsonl
# ... ②-⑫ 按 §3.5 顺序执行（或直接用 run_pipeline --phases 5）
python $AGG/adapters.py --story-graph $OUT/aggregation/${DOC}_story_graph.json \
    --doc-id $DOC --output-dir $OUT/aggregation
```

**常见坑**：① ⑧缺 `--cross-segment`（需先跑 Phase 4）会直接报错退出；② ⑩的 `participants` 为空≠bug——frontmatter/过渡段无角色出场是合法数据特性（占全部场景 ≤10%）；③ 聚合产物含 `generated_at` 时间戳，字节级对比产物时先排除该字段；④ ⑥narrative_structure 对旧产物自动降级为从 D08.time 文本关键词推断，输出中标注 derivation_method；⑤ ⑦writing_techniques 的转场/蒙太奇/场景钩子使用提取的地点关键词而非完整 D08.space 文本；时间转场阈值为年份差≥2 或季节变化；⑥ ⑦⑧ 为规则粗筛，后续可自行叠加外部 LLM 后处理（不属于本 skill 流程）。

### 2.8 数据契约与元数据说明（v3.15.0 新增，T-131）

- **`_pad_metadata` 自动补齐（注入时无需携带原文）**：`annotate_segment.py --input-json` / `--llm-cmd` 模式在落盘前自动从 `segments.jsonl` 对应行补齐 `text_span`（含 text/start_char/end_char/hash），因此 Agent 生成批注 JSON 时**不必把 2000 字原文塞进每行**，只需 `segment_id` + 批注主体（layers.<layer> 或顶层 craft）。
- **`text_span.hash` 算法**：`sha256(原文 .strip() 且 CRLF/CR→LF 归一化后的 UTF-8 编码)[:16]`（即 `preprocess.compute_hash`）。用于段文本完整性校验；validator 不强校验 hash 值本身。
- **兜底切分（无章节边界文本）**：原文无独立成行的章节标题时触发"按字符数粗切"，每段行内标记 `pollution_warning: "v3.8.5兜底切分(章节边界识别不足)"`。**这不是错误**——报告会单列"切分质量"小节提示；若原文确有标题但未被识别，检查标题是否为独立成行的纯文本行（≤20 字）或数字/中文数字序列。

---

## 3. 校验错误快速修复表

> annotate_segment 自动执行校验；以下是常见错误及修复方法。

| 错误信息 | 原因 | 修复 |
|---------|------|------|
| `缺失必填顶层字段：annotation_id` | 注入的 JSON 缺字段 | 从 `templates/<layer>-output.json` 复制模板填充 |
| `D04.core 不在 20 词枚举内` | 自造了情绪词 / 写了 v2.9.0 已删旧词 | 只能从 v2.9.0 新 20 词选：平静/压抑/焦虑/悲伤/愤怒/恐惧/喜悦/希望/绝望/孤独/信任/屈辱/嫉妒/复仇/悬疑/释然/羞耻/惊讶/渴望/厌恶（旧词 尊严/背叛/贪婪/宽恕 仅 2.8.0 及更早产物合法） |
| `D01 不在枚举内` | 自造了叙事功能词 | 只能从：背景铺垫/激励事件/上升行动/转折/高潮/下降行动/结局/过渡/复合功能/无法判断 中选 |
| `引文不是 text_span.text 子串` | craft/interpretation 的引文含原文注释标记或被改写 | 用 `text.find(引文)` 精确定位；去掉①②等注释标记 |
| `span 切片相似度 <85%` | span 位置漂移 | craft 层会自动回算重试；仍失败则手动用 `text.find` 修正 |
| `span start >= end` 或 `span 越界` | span 坐标非法 | 确保 `0 ≤ start < end ≤ len(text)` |
| `status=confirmed 但 overall<0.8` | 置信度与状态不一致 | overall≥0.8 才能 confirmed；<0.8 改 tentative |
| `D19.emotion 不在 50 词白名单` | 情感词自造 | 查 `references/emotion-lexicon.md`（50 词），选最接近词 + expression.note 说明 |
| `key_phrases 不是原文子串` | D19 表达短语不在原文里 | 每项必须是 `text_span.text` 的精确子串 |
| `schema_version 不在允许集合` | 版本号错 | 当前允许 2.6.0 / 2.7.0 |
| D19 用了白名单外词（自动生成行） | 自由情感词，validate 拒收 | 跑 `scripts/collect_lexicon_candidates.py --dir <产物目录>`——**经验回写管道（WikiSkill，T-031-③）**：对频率 ≥3 的自由词，normalizer 有映射 → 替换为既有词；无映射 → 记入候选，按词表演化协议随版本入表。生成行会追加到本表（来源列=collect_lexicon_candidates 经验回写） |

---

## 4. 常见坑点（踩过的坑）

### 坑点 #1：checkpoint 路径默认 cwd，不是 output-dir

**现象**：annotate_segment 显示"落盘成功"，但 `checkpoint.py status` 显示 0%。

**原因**：不传 `--checkpoint` 时，annotate_segment 从 **cwd** 找 `{doc_id}_checkpoint.json`，而 preprocess 把 checkpoint 写到了 **output-dir**。两个目录不一致 → annotate 在 cwd 新建了一个空 checkpoint。

**修复**：**始终显式传 `--checkpoint <output-dir>/{doc_id}_checkpoint.json`**，或从 output-dir 目录运行命令。

### 坑点 #2：Windows 控制台 GBK 编码崩溃

**现象**：脚本打印中文时 `UnicodeEncodeError`。

**原因**：Windows 控制台默认 GBK，Python print 中文时编码失败。

**修复**：所有脚本已在 v2.5.1/v2.7.0 修复（`sys.stdout.reconfigure(encoding='utf-8')` + 子进程显式 UTF-8）。如果你写自己的 wrapper，记得也加这行。

### 坑点 #3：手动模式多层时第二次 EOF 退出

**现象**：手动模式跑 `--layers structure,interpretation`，第一层粘贴完 JSON 后，第二层直接报"没粘贴 JSON"退出。

**原因**：手动模式每层各读一次 stdin，第一次读完后 stdin 已到 EOF。

**修复**：手动模式**一次只跑一层**。多层分多次调用，或改用 `--input-json` / `--llm-cmd` 非交互模式。

### 坑点 #4：PowerShell 吞子进程 stdin

**现象**：`--llm-cmd` 外部 LLM 收不到输入，报"无 stdin 输入"。

**原因**：`shell=True` 在 PowerShell 环境下会把 JSON 当命令解析，吞掉 stdin。

**修复**：annotate_segment 已在 v2.7.0 修复（`shlex.split(posix=True)` + `shell=False`）。wrapper 路径含空格时用双引号包裹，建议用正斜杠。

### 坑点 #5：craft 条目 span 是高频失误点

**现象**：LLM 产出的 craft 批注 span 位置经常漂移（数错字符偏移）。

**修复**：决策 18 后 annotate_segment 校验失败时**自动用 `text.find` 回算 span 并重试 ≤3 次**。存量旧产物用 `fill_spans.py` 回补。Agent 自写批注时建议直接用 `text.find(引文)` 计算 span，不要手数。

### 坑点 #6：emotion 层不能和其他层混跑

**现象**：`--layers structure,emotion` 时 emotion 层找不到 structure 触发上下文。

**原因**：emotion 层需要读同段 structure.jsonl 的 D01/D04/D10 做 P4 触发判定。如果 structure 还没落盘，触发判定会失败。

**修复**：先跑完 structure 全量，再单独跑 emotion 层（`--layers emotion`）。

---

## 5. 断点续跑指南

1. **查询进度**：`python scripts/checkpoint.py status --doc-id <doc> --dir <out>`
2. **续跑**：直接重跑同样的命令，annotate_segment 会自动跳过已完成的 (segment, layer)
3. **强制重跑某段**：加 `--force`（幂等 upsert，不产生重复行）
4. **重置某层全部**：`python scripts/checkpoint.py reset-layer --doc-id <doc> --layer craft --dir <out>`
5. **批量失败不阻塞**：`--all-pending` 模式下单条失败记入 failed 清单，其余继续；失败的段下次重跑会自动重试

---

## 6. 产物文件清单（output-dir 内）

| 文件 | 产生阶段 | 说明 |
|------|---------|------|
| `{doc}_segments.jsonl` | Phase 1 | 切分后的片段（含 text_span / context_prev / context_next） |
| `{doc}_checkpoint.json` | Phase 1 | 进度状态机（各层完成情况 / cross_segment / merged / report 标记） |
| `{doc}_structure.jsonl` | Phase 2 | L1 结构层批注 |
| `{doc}_interpretation.jsonl` | Phase 2 | L2 阐释层批注 |
| `{doc}_craft.jsonl` | Phase 2 | L3 文笔层批注 |
| `{doc}_emotion.jsonl` | Phase 3 | L2.5 情感层批注（P4 触发式，属于逐段批注） |
| `{doc}_cross_segment.jsonl` | Phase 3 | L4 跨段关系 |
| `{doc}_merged.jsonl` | Phase 4 | 四层合并 + cross_refs 投影 |
| `{doc}_report.md` / `.html` | Phase 5 | 最终报告 |
| `{doc}_scene_boundary.json` | Phase 2a | 场景边界判断结果（LumberChunker） |
| `{doc}_final_segments.jsonl` | Phase 2b | 场景级精确切分 segments（后续 Phase 3-8 使用） |
| `{doc}_segment_id_mapping.json` | Phase 2b | 新旧段 ID 映射表 |

---

## 7. 官方 LLM Wrapper 接入指南

`examples/llm_wrapper.py` 是 `--llm-cmd` 协议的官方参考模板（零第三方依赖）。

### 协议

```
stdin  ← {"segment": {...}, "request_layers": ["structure"], "schema_version": "2.7.0",
           "structure_trigger_block": {...}|null}   # 仅 emotion 层注入
stdout → 一行动 JSON（批注行对象，见 templates/<layer>-output.json）
退出码 0 = 成功；非 0 = 失败（annotate 记入 failed，不写 checkpoint）
```

### 步骤

1. 复制 `examples/llm_wrapper.py` 到你的工作目录
2. 编辑 `_call_model(payload)` 函数：
   - 从 `payload["segment"]["text_span"]["text"]` 取原文
   - 把 SKILL.md / references/schema.md / 对应模板拼进 system prompt
   - 调你的 API（OpenAI 兼容 `/api/chat` 可直接用 stdlib `urllib`）
   - 解析返回 JSON 并 return
3. 运行：`--llm-cmd "python your_wrapper.py"`

### Mock 冒烟（不调 API）

```bash
python examples/llm_wrapper.py --mock
# 从 templates/structure-output.json 生成合法 structure 行，仅用于跑通链路
```

---

*RUNBOOK v2.7 — "5 分钟跑通，报错查表，踩坑看 §4。"*



---

## 八、产物目录清理（v3.14.1 新增）

### 8.1 临时文件清理

分批生成批注时（如 `_batch_structure_01.jsonl`、`_batch_craft_02.jsonl` 等），中间文件合并到正式产物后应及时清理，避免污染产物目录。

**常见临时文件模式**：
- `_batch_*.jsonl` — 分批生成批注的中间文件
- `*_input.json` / `*_craft_input.json` — 注入用的临时输入
- `*.tmp` — 原子写的临时文件（正常会自动清理，异常残留时手动删）
- `*_debug.json` / `*_test.json` — 调试用临时文件

**清理命令**（在产物目录下执行）：
```bash
# 删除所有 _batch_ 开头的临时文件
rm _batch_*.jsonl

# 或用 PowerShell
Remove-Item _batch_*.jsonl -Force
```

### 8.2 必留产物清单

清理后应保留以下正式产物：
- `{doc_id}_segments.jsonl` — 切分结果
- `{doc_id}_structure.jsonl` — 结构层批注
- `{doc_id}_interpretation.jsonl` — 阐释层批注（全量深度）
- `{doc_id}_craft.jsonl` — 技法层批注（全量深度）
- `{doc_id}_emotion.jsonl` — 情感层批注（P4 触发段）
- `{doc_id}_cross_segment.jsonl` — 跨段关系
- `{doc_id}_merged.jsonl` — 全层合并
- `{doc_id}_report.md` / `{doc_id}_report.html` — 报告
- `{doc_id}_checkpoint.json` — 断点续跑状态
- `{doc_id}_segment_plan.json` — 分档计划（如有）
- `{doc_id}_quality_report.json` — 质量门报告（v3.4）
- `{doc_id}_quant_metrics.jsonl` — 计算文学指标（v3.4；v3.16.2 起每行含 `tokenizer` 字段：jieba / dlut_fmm_fallback）
- `aggregation/` — 聚合层产物目录


---

## 九、PowerShell 编码与 batch 合并工作流（v3.14.1 新增）

### 9.1 PowerShell 中文 doc_id 编码注意事项

Windows PowerShell 下命令行传中文 doc_id 可能出现乱码。解决方案：

1. **推荐使用英文 doc_id**：如 `qiuzhuang` 而非 `球状闪电`
2. **使用 Python 包装**：将命令写入 .py 脚本文件再执行
3. **设置控制台编码**：`chcp 65001` 切换到 UTF-8
4. **annotate_segment.py v3.14.1 起会自动警告**：doc_id 包含非 ASCII 字符时打印提醒

### 9.2 多 Agent 并行批注 batch 合并工作流

多个 Agent 并行批注同一层时，避免写同一 JSONL 文件冲突：

```bash
# 1. 每个 Agent 各自写 batch 文件
# Agent A: 输出 novel_batch_01_craft.jsonl
# Agent B: 输出 novel_batch_02_craft.jsonl

# 2. 全部完成后，用官方 merge_batch.py 合并
python scripts/merge_batch.py     --batch-dir outputs/annotations/novel     --layer craft     --doc-id novel

# 3. 合并后删除 batch 文件
rm outputs/annotations/novel/_batch_*.jsonl
```

merge_batch.py 自动按 segment_id 去重（幂等 upsert），后出现的覆盖先出现的。

## Runtime Scratchpad（v3.14.1 新增）

**启用/关闭**：
```bash
# 默认启用
python scripts/annotate_segment.py --segments ... --doc-id ... --output-dir ... --input-json batch.jsonl

# 显式关闭
python scripts/annotate_segment.py --segments ... --doc-id ... --output-dir ... --input-json batch.jsonl --no-scratchpad
```

**查看 Scratchpad 状态**：
```bash
python scripts/scratchpad.py --load outputs/annotations/xxx/xxx_scratchpad.json --stats
python scripts/scratchpad.py --load outputs/annotations/xxx/xxx_scratchpad.json --summary
```

**持久化位置**：
- 独立文件：`{output-dir}/{doc_id}_scratchpad.json`
- checkpoint 快照：`{output-dir}/{doc_id}_checkpoint.json` → `scratchpad_snapshot`

## 附录：路径解析约定（v3.16.3 统一）

> **一切产物以 `--output-dir` / segments 文件所在目录为权威，不依赖 cwd**。

| 脚本 | checkpoint/输出定位 |
|------|------|
| `preprocess.py` | checkpoint 写入 `--output-dir` |
| `annotate_segment.py` | checkpoint 与层文件同在 `--output-dir`（v3.16.3 起不再默认 cwd）；`--checkpoint` 可显式指定 |
| `cross_segment.py` / `merge_layers.py` / `render_report.py` | 输入输出默认 segments 同目录（v3.16.3 起不再默认 cwd） |
| `checkpoint.py status` | `--dir` 指向 checkpoint 所在目录 |

> **Windows（PowerShell）提示**：命令语法与 Linux bash 相同（`python scripts/xxx.py --args`），仅注意：①中文路径用双引号包裹；②`&&` 连接符不可用，改用分号 `;` 或分条执行；③脚本输出 UTF-8，控制台乱码时先 `$OutputEncoding = [Console]::OutputEncoding = [System.Text.Encoding]::UTF8`。
