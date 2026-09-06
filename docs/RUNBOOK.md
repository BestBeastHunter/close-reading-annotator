# RUNBOOK — close-reading-annotator 最小操作契约

> **定位**：给 Agent / 新运行者的速查手册。比 SKILL.md 短，只记"怎么跑、报错怎么修、常见坑"。
> 完整 schema / 枚举 / 设计决策见 `references/schema.md`（批注层）、`references/aggregation-schema.md`（聚合层）、`SKILL.md`、工作区 `docs/design-decisions.md`。
> 版本：skill v3.8.6 / annotation schema 2.10.0 / aggregation schema 3.1.0（决策 22 三域解耦）

---

## 0. 5 分钟跑通全流程（冒烟测试）

```bash
# 假设 skill 目录为 ./close-reading-annotator，输出目录为 ./out
SKILL=./close-reading-annotator
OUT=./out
DOC=my_book

# Phase 0：数据质量看门狗（v3.4 新增，粗切前必须跑）
python $SKILL/scripts/quality_gate.py --input book.txt --out $OUT/quality_report.json
# 检查 verdict：fail 项需修复原文后再进入 Phase 1；warn 可继续但需留意

# Phase 1：切分
python $SKILL/scripts/preprocess.py --input book.txt --doc-id $DOC --output-dir $OUT

# Phase 1.25：精细化切分重排（v3.5 新增，可选但推荐；冒烟测试可跳过）
# 步骤A：Agent 用自身 LLM 逐对判断相邻段场景边界，输出 scene_boundary.json（Prompt 见 SKILL.md §3.1.5）
# 步骤B：重排脚本按边界点从原文重切，输出场景级 final_segments
python $SKILL/scripts/reshape_segments.py \
    --segments $OUT/${DOC}_segments.jsonl \
    --boundaries $OUT/${DOC}_scene_boundary.json \
    --original book.txt \
    --doc-id $DOC --output-dir $OUT
# 产出 ${DOC}_final_segments.jsonl（场景级）+ ${DOC}_segment_id_mapping.json（新旧ID映射）
# 跳过本阶段则后续用 ${DOC}_segments.jsonl（粗切）即可

# Phase 1.5：计算文学分析（v3.4 新增，重排后/批注前，逐 segment 量化指标）
python $SKILL/scripts/quant_analyzer.py --segments $OUT/${DOC}_final_segments.jsonl --out $OUT/${DOC}_quant_metrics.jsonl
# 产出可注入 annotate_segment 的 Prompt 作为 LLM 批注的硬证据

# Phase 2：全自动批量批注（用官方 mock wrapper 跑通链路，structure 层）
python $SKILL/scripts/annotate_segment.py \
    --segments $OUT/${DOC}_final_segments.jsonl \
    --doc-id $DOC --output-dir $OUT \
    --checkpoint $OUT/${DOC}_checkpoint.json \
    --layers structure --all-pending \
    --llm-cmd "python $SKILL/examples/llm_wrapper.py --mock"

# Phase 3-5：跨段 → 合并 → 报告
python $SKILL/scripts/cross_segment.py --doc-id $DOC --segments $OUT/${DOC}_segments.jsonl \
    --structure $OUT/${DOC}_structure.jsonl --output-dir $OUT
python $SKILL/scripts/merge_layers.py --doc-id $DOC --segments $OUT/${DOC}_segments.jsonl --output-dir $OUT
python $SKILL/scripts/render_report.py --doc-id $DOC --output-dir $OUT --format md
```

**验证**：`python $SKILL/scripts/checkpoint.py status --doc-id $DOC --dir $OUT` 全部 100%。

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

### 2.4 select_segments.py（段采样分层，决策 18 新增）

```bash
python scripts/select_segments.py --structure <out>/{doc}_structure.jsonl --output <out>/{doc}_segment_plan.json
# 产出 {doc}_segment_plan.json（tiers: deep/light/skip + per_segment 理由）
```
- 默认规则：D01 ∈ {激励事件,上升行动,高潮,转折} 或 D04.intensity≥6 或 D07.is_switch_point → **deep**
- D01 ∈ {背景铺垫,过渡} → **skip**；其余 → **light**
- 配合 `run_pipeline.py --plan`：structure 全量跑，深度层只跑 deep 段

### 2.5 run_pipeline.py（Phase 1-5 一体化，决策 18 新增）

```bash
python scripts/run_pipeline.py --input <原文.txt> --doc-id <doc_id> --output-dir <out> \
    --plan <out>/{doc}_segment_plan.json --llm-cmd "python wrapper.py" --report-format md
# --phases 3,4,5   # 只跑跨段→合并→报告（批注已就绪时）
# 断点续跑是默认行为（读 checkpoint 跳过已完成阶段/片段）；--force 强制重跑
```

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
| `quant_analyzer.py`（v3.4） | **计算文学分析（Phase 1.5，批注前）**：逐 segment 计算句长/TTR/词性/对话占比/标点/情感词频（DLUT 子集）/五感密度，产出 quant_metrics.jsonl。`--segments <segments.jsonl> --out <quant.jsonl>`；jieba 可选，缺失自动降级为 DLUT 最大正向匹配 |
| `reshape_segments.py`（v3.5） | **精细化切分重排（Phase 1.25，可选）**：读粗切 segments + scene_boundary.json（Agent 场景边界判断）+ 原始文本 → final_segments.jsonl（场景级，scene_NNN 编号）+ 新旧 ID 映射表。`--segments --boundaries --original --doc-id --output-dir`；章节边界自动识别，无 boundary 文件时仅按章节合并 |

### 2.7 aggregation/ 聚合层 10 脚本（v2.9/v3.0/v3.7/v3.8，批注完成后运行）

> 全链路 <2s/本，纯规则零依赖。Schema 真源：`references/aggregation-schema.md`。建议按 ①→⑩ 顺序跑；缺输入时各脚本自行报错，可逐脚本重跑（覆盖写，幂等）。

| # | 脚本 | 必填参数 | 产出 |
|:-:|------|---------|------|
| ① | `entity_resolution.py` | `--segments --emotion --craft --structure --doc-id --output-dir` | `{doc}_entity_graph.json` |
| ② | `scene_graph.py` | `--segments --structure --doc-id --output-dir --entity-graph` | `{doc}_scene_graph.json` |
| ③ | `character_arcs.py` | `--segments --structure --emotion --entity-graph --doc-id --output-dir` | `{doc}_character_arcs.json` |
| ④ | `story_type_inference.py` | `--segments --structure [--interpretation] [--emotion] --doc-id --output-dir` | `{doc}_story_metadata.json` |
| ⑤ | `narrative_structure.py`（v3.7 新增） | `--structure --doc-id --output-dir` | `{doc}_narrative_structure.json`（弗雷塔格五幕+热奈特聚焦+叙事时间线+救猫咪节拍） |
| ⑥ | `writing_techniques.py`（v3.8 新增） | `--structure --interpretation [--cross-segment] --doc-id --output-dir` | `{doc}_writing_techniques.json`（转场+悬念+蒙太奇+钩子） |
| ⑦ | `causal_graph.py` | `--cross-segment --structure --doc-id --output-dir` | `{doc}_causal_graph.json` |
| ⑧ | `object_chains.py` | `--craft --doc-id --output-dir` | `{doc}_object_chains.json` |
| ⑨ | `story_graph.py` | `--aggregation-dir --doc-id --output-dir` | `{doc}_story_graph.json`（合并①-⑧） |
| ⑩ | `adapters.py` | `--story-graph --doc-id --output-dir [--formats text2story,yarn,ncp]` | `{doc}_{text2story,yarn,ncp}.json` |

**典型一条链**（moon 示例，`AGG=scripts/aggregation`）：

```bash
python $AGG/entity_resolution.py --segments $OUT/${DOC}_segments.jsonl --doc-id $DOC \
    --output-dir $OUT/aggregation --emotion $OUT/${DOC}_emotion.jsonl \
    --craft $OUT/${DOC}_craft.jsonl --structure $OUT/${DOC}_structure.jsonl
python $AGG/scene_graph.py --segments $OUT/${DOC}_segments.jsonl --structure $OUT/${DOC}_structure.jsonl \
    --doc-id $DOC --output-dir $OUT/aggregation --entity-graph $OUT/aggregation/${DOC}_entity_graph.json
python $AGG/character_arcs.py --segments $OUT/${DOC}_segments.jsonl --structure $OUT/${DOC}_structure.jsonl \
    --emotion $OUT/${DOC}_emotion.jsonl --entity-graph $OUT/aggregation/${DOC}_entity_graph.json \
    --doc-id $DOC --output-dir $OUT/aggregation
python $AGG/story_type_inference.py --segments $OUT/${DOC}_segments.jsonl --structure $OUT/${DOC}_structure.jsonl \
    --interpretation $OUT/${DOC}_interpretation.jsonl --emotion $OUT/${DOC}_emotion.jsonl \
    --doc-id $DOC --output-dir $OUT/aggregation
python $AGG/narrative_structure.py --structure $OUT/${DOC}_structure.jsonl \
    --doc-id $DOC --output-dir $OUT/aggregation
python $AGG/writing_techniques.py --structure $OUT/${DOC}_structure.jsonl \
    --interpretation $OUT/${DOC}_interpretation.jsonl \
    --cross-segment $OUT/${DOC}_cross_segment.jsonl \
    --doc-id $DOC --output-dir $OUT/aggregation
python $AGG/causal_graph.py --cross-segment $OUT/${DOC}_cross_segment.jsonl --structure $OUT/${DOC}_structure.jsonl \
    --doc-id $DOC --output-dir $OUT/aggregation
python $AGG/object_chains.py --craft $OUT/${DOC}_craft.jsonl --doc-id $DOC --output-dir $OUT/aggregation
python $AGG/story_graph.py --aggregation-dir $OUT/aggregation --doc-id $DOC --output-dir $OUT/aggregation
python $AGG/adapters.py --story-graph $OUT/aggregation/${DOC}_story_graph.json \
    --doc-id $DOC --output-dir $OUT/aggregation/adapters
```

**常见坑**：① ⑦缺 `--cross-segment`（需先跑 Phase 3）会直接报错退出；② ⑩的 `participants` 为空≠bug——frontmatter/过渡段无角色出场是合法数据特性（占全部场景 ≤10%）；③ 聚合产物含 `generated_at` 时间戳，字节级对比产物时先排除该字段；④ ⑤narrative_structure 对旧产物（无 v3.6 新字段 _time_type/_narrative_level/_narrator_identity）自动降级为从 D08.time 文本关键词推断，输出中标注 derivation_method；⑤ ⑥writing_techniques 的转场/蒙太奇/场景钩子使用提取的地点关键词（extract_location_keyword）而非完整 D08.space 文本，避免文本微变化导致虚高；时间转场阈值为年份差≥2 或季节变化；⑥writing_techniques 为规则粗筛，后续可用 LLM 精排（同因果链架构）。

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
| `{doc}_emotion.jsonl` | Phase 2.5 | L2.5 情感层批注（P4 触发式） |
| `{doc}_cross_segment.jsonl` | Phase 3 | L4 跨段关系 |
| `{doc}_merged.jsonl` | Phase 4 | 四层合并 + cross_refs 投影 |
| `{doc}_report.md` / `.html` | Phase 5 | 最终报告 |
| `{doc}_segment_plan.json` | select_segments | 段采样分层计划（deep/light/skip） |

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

## 八、产物目录清理（v3.8.6 新增）

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
- `{doc_id}_interpretation.jsonl` — 阐释层批注（深度档）
- `{doc_id}_craft.jsonl` — 技法层批注（深度档）
- `{doc_id}_emotion.jsonl` — 情感层批注（P4 触发段）
- `{doc_id}_cross_segment.jsonl` — 跨段关系
- `{doc_id}_merged.jsonl` — 全层合并
- `{doc_id}_report.md` / `{doc_id}_report.html` — 报告
- `{doc_id}_checkpoint.json` — 断点续跑状态
- `{doc_id}_segment_plan.json` — 分档计划（如有）
- `{doc_id}_quality_report.json` — 质量门报告（v3.4）
- `{doc_id}_quant_metrics.jsonl` — 计算文学指标（v3.4）
- `aggregation/` — 聚合层产物目录


---

## 九、PowerShell 编码与 batch 合并工作流（v3.8.6 新增）

### 9.1 PowerShell 中文 doc_id 编码注意事项

Windows PowerShell 下命令行传中文 doc_id 可能出现乱码。解决方案：

1. **推荐使用英文 doc_id**：如 `qiuzhuang` 而非 `球状闪电`
2. **使用 Python 包装**：将命令写入 .py 脚本文件再执行
3. **设置控制台编码**：`chcp 65001` 切换到 UTF-8
4. **annotate_segment.py v3.8.6 起会自动警告**：doc_id 包含非 ASCII 字符时打印提醒

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
