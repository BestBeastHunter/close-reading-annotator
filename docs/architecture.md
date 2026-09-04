# docs/architecture.md — 架构说明

> 本文是精读批注 Skill 的架构层说明：它是什么、内部如何分层、数据如何流动、每个模块的职责边界、以及未来如何扩展。面向想理解设计、修改 Schema、或把它接入自己管线的读者。

---

## 一、定位

精读批注 Skill 把"一段叙事文本 → 一组结构化批注"这件原子能力做扎实：

- **核心载体是一个 Prompt 包（SKILL.md）**，不捆绑任何 IDE、模型或 API；
- 附带的 `scripts/` 是**可选工具**：负责切分、断点续跑、校验、合并、渲染报告、脱敏导出等确定性工作；
- 大模型只做它擅长的事——判断与产出结构化批注 JSON；脚本只做确定性的事——文件 IO、校验、状态管理。

这一分工来自一次根本性教训：**Skill 是「一段 System Prompt + 参考资料包」，它天然不适合在对话中途像 Python 程序一样循环读 1000 行 JSONL 并写回文件。** 因此确定性工作全部下沉到脚本，Skill 本体保持纯净、可移植。

### 设计原则

| 原则 | 含义 |
|------|------|
| 纯 Prompt 包 | SKILL.md 零依赖，任何能读 Markdown 的平台都能用 |
| 每段每层独立落盘 | 一段一层一个 JSONL 行，天然支持增量、断点续跑 |
| 四层分离 | 结构 / 阐释 / 文笔 / 跨段，各自独立产出与消费 |
| Schema 单一真源 | `references/schema.md` 定义一切枚举与约束，下游三处副本同步 |
| 坐标自校验 | 切分与 span 全部断言切片相似度，漂移即报错而非静默产出坏数据 |
| 版权合规 | 「分析即销毁」：入库/分发前必须脱敏，不携带原文 |
| 脚本可选、零依赖 | Python 标准库即可运行 |

---

## 二、分层模型

批注按"同一段文字从几个视角看"分成四层 + 一个跨段层：

```
单片段（一次 LLM 调用逐段产出）
├── L1 结构层（structure）      D01 叙事功能 / D04 情绪基调 / D05 节奏 /
│                               D07 视角 / D08 时空 / D10 对话功能 / D11 描写类型
├── L2 阐释层（interpretation） D06 信息控制 / D09 主题 / narrator_reliability
├── D19 情感层（emotion，v2.7） 角色情感主/次/对象/诱因/段内情感弧/直间接表达
│                               （P4 独立 Pass，读取 L1 的 D01/D04/D10 作为触发上下文）
└── L3 文笔层（craft）          D13 佳句 / D14 修辞 / D15 意象 / D16 词汇 / D17 句式 / D18 人物语言指纹

跨段（全书一次，二阶段）
└── L4 跨段层（cross-segment）  伏笔-回收 / 因果 / 时序 / 对比 / 呼应（双引用关系）
```

- **为什么 D19 单独一个 Pass（P4）**：情感对象/诱因/情感弧是"角色级"判断，需要结构层结论做上下文；先有 L1 再判断情感，避免在结构未定时就做细粒度情感归属。且情感层只对"值得触发"的片段跑，控制成本。
- **为什么跨段不能混在逐段批注里**：伏笔-回收、呼应需要看到全书完整图景才成立。因此跨段是独立的二阶段产出，且每条关系用 `segment_id + anchor_text` 双引用，防序号漂移。

---

## 三、数据流

```
原始文本
   │  Phase 1  scripts/preprocess.py（确定性）
   ▼
segments.jsonl（按章/按长度切分，含 text_span + context 前后锚点）
checkpoint.json（断点续跑状态）
   │  Phase 2  scripts/annotate_segment.py（调度壳）+ LLM
   ▼
structure.jsonl / interpretation.jsonl / craft.jsonl （emotion.jsonl，若跑 P4）
   │  （每层产出后自动跑 validate_output.py，通过才落盘）
   │  Phase 3  scripts/cross_segment.py（启发式规则，全书一次）
   ▼
cross_segment.jsonl
   │  Phase 4  scripts/merge_layers.py
   ▼
merged.jsonl（段轴嵌套文档）← 下游消费首选入口
   │  Phase 5（可选）scripts/render_report.py
   ▼
report.html / report.md
   │  export_dataset.py（入库前强制脱敏）
   ▼
dataset.json（完全剥离原文，仅结构化字段）
```

LLM 出现在唯一的箭头处（Phase 2）。`annotate_segment.py` 是**调度壳**：
- 不传 `--llm-cmd` → 手动模式：打印标准 Prompt 输入片段，AI 输出的 JSON 粘贴回；
- 传 `--llm-cmd "<命令>"` → 自动模式：脚本构造输入 JSON 喂给外部命令，命令返回批注 JSON；
- 校验通过 → 写 JSONL + 更新 checkpoint；失败重试最多 3 次。

这样 API 厂商、模型、批量调度方式全部由调用方决定，Skill 本身不捆绑任何一家。

---

## 四、模块职责

| 模块 | 职责 | 边界（不做） |
|------|------|--------------|
| SKILL.md | Prompt 包：模式、判定指引、约束、流程 | 不 IO、不调 API |
| references/schema.md | 枚举/字段/坐标系唯一真源 | — |
| references/*-anchors.md | 校准锚点（情绪强度、节奏分档） | 不覆盖全部文学场景 |
| references/emotion-lexicon.md | D19 情感词枚举（44 词） | 词表随语料演化的特例见 design-decisions |
| references/annotation-examples.md | Few-shot 示例 | — |
| templates/*.json | 各层输出模板 | 字段请勿输出（仅开发参考） |
| preprocess.py | 切分 + checkpoint 初始化 | 不做语种判定、不清理噪声文本 |
| annotate_segment.py | 单片段调度壳 | 不内嵌任何 API |
| cross_segment.py | 跨段启发式规则 | 不做 LLM 二分类（留给调用方管线） |
| merge_layers.py | 合并嵌套 + cross_refs 投影 | — |
| render_report.py | HTML/MD 报告 | 零第三方依赖（不引图表库） |
| validate_output.py | 全产物统一校验 | — |
| checkpoint.py | checkpoint 读写 + CLI | — |
| fill_spans.py | 回补存量批注 span | 仅历史迁移用 |
| export_dataset.py | 脱敏导出 | 不判断版权归属 |

---

## 五、Schema 版本治理

**版本声明四者严格一致**：`SKILL.md` frontmatter version = `schema.md` Schema 版本 = 批注 JSON `schema_version` = `_metadata.skill_version`（L1–L3 产物向后兼容 `2.6.0`，`validate_output.py` 按版本分支豁免旧字段）。

**枚举变更流程**（防止"三处手抄"分叉）：
1. 改 `references/schema.md`（唯一真源）；
2. 同步 templates / validate_output.py 中的枚举副本；
3. 升版本号（四者同步），更新 SKILL.md 版本历史。

校验器是最后一道防线：枚举合法性、引文子串、span 位置断言、置信度↔status 对齐、必填维度置信度非 null，任一不过则该层不落盘。

---

## 六、质量与可测试性

- 每个脚本都是可独立运行的 CLI，`python xxx.py` 即可验证；
- `preprocess.py` 输出带坐标自校验断言；`validate_output.py` 可对任何产物零配置校验；
- 模板文件本身通过校验器 0 error 验证（防止模板与校验器漂移）；
- 回归纪律：Schema/Prompt/锚点升级后，建议在同一批"金标准"文本上重跑一遍 self-consistency（同片段多采样投票率 ≥85% 视为合格），与上一版对比后再合入。

---

## 七、扩展边界

Skill 之外的能力**刻意不内置**，由调用方/配套模块承担：

| 能力 | 归属 |
|------|------|
| 批量调度多本书 | 调用方批量管线（循环调 API + annotate_segment） |
| 高精度跨段 LLM 二分类 | 调用方管线叠加在 cross_segment 候选之上 |
| 角色情感轨迹跨段聚合（D19 下游） | 下游聚合模块（需实体/指代消解，超出单片段 Skill 边界） |
| 骨架/风格指纹等更上层抽象 | 下游独立模块 |
| 数据收集上传 | 不内置网络调用（v2.5 起按设计移除） |

**已知设计边界**：
- D19 与 D04 同段并存时以 D19 的角色级判断为准（角色情感 vs 段级氛围是两轨）；
- D19 的 target/trigger/arc 无明确值时写 `null` + `null_reasons`，禁止编造；跨段实体合并（他称/代词归并）不在 Skill 内实现。
