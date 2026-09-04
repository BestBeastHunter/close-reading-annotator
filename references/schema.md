# references/schema.md — 四层精读批注 Schema 完整定义 v2.7.0

> **⚠️ 本文件是唯一真源。** 所有枚举值、字段格式、span 坐标系、引文校验规则，**只以本文件为准**。
> SKILL.md、`scripts/validate_output.py`、`templates/*.json` 下游三者的定义必须完全同步于本文件。
> 版本号 `2.7.0` 必须与 SKILL.md frontmatter、新批注 JSON 的 `schema_version`、`_metadata.skill_version` 一致。
> 校验器向后兼容：`2.5.0` / `2.6.0` 旧产物仍被接受（版本分支豁免，见 §八）。
> **唯一例外**：D19 的 `emotion` 枚举（44 词）因需随语料演化，真源为 `references/emotion-lexicon.md`——本文件只声明引用，validate_output.py 白名单须逐词同步 emotion-lexicon.md。

---

## 一、版本与真源声明

- Schema 版本：`2.7.0`（SemVer）
- **v2.7.0 变更摘要（宽松兼容）**：新增 **D19 情感分析（阐释层语义扩展，P4 Pass，独立产物 `{doc_id}_emotion.jsonl`）**。不改不删任何既有字段；L1–L3 文件 schema 与 2.6.0 完全相同，2.5/2.6 旧产物零迁移。详见决策 17。
- 版本升级规则：
  - 修订号（2.5.x）：锚点校准、示例补充、校验器 bugfix——**不影响字段兼容**
  - 次版本（2.x.0）：新增枚举值 / 新增可选子字段 / 新增校验规则（宽松化）——若新增**必填**子字段，须对旧版本产物做豁免放行（见 §八 版本兼容矩阵）
  - 主版本（x.0.0）：删除/重命名字段 / 枚举值收敛（不兼容）
- **唯一真源承诺**：任何枚举值的增删改，**先改本文件，再同步下游三件套**（SKILL.md 速览表 / validate_output.py 校验逻辑 / templates/*.json）。**禁止下游三件套私自改枚举值而本文件不同步。**

---

## 二、全局元字段（所有层通用）

每条批注 JSON 行（无论哪层），**必须包含以下顶层字段**：

| 根键 | 类型 | 是否必填 | 说明 |
|------|------|:--------:|------|
| `schema_version` | string | ✅ | 新产物固定为 `"2.7.0"`（emotion 文件必为 2.7.0；L1–L3 续批可写 2.7.0 或保持 2.6.0，均合法，见 §八）。validate_output 接受 `"2.5.0"` / `"2.6.0"` / `"2.7.0"`：2.6 新增必填子字段 `D04.polarity`（对 2.5.0 版本分支豁免）；2.7 新增可选扩展 D19（emotion 文件，2.5/2.6 产物无此层，不校验）；下游读到未知主号直接报错。 |
| `annotation_id` | string | ✅ | 全局唯一 ID。格式：`<doc_id>_seg_<segment序号>_<layer>_<annotation序号>`，如 `moon_sixpence_seg_0001_structure_ann_0`。 |
| `document_id` | string | ✅ | 用户自定义文档 ID。同一文档所有片段/所有层共享此 ID。 |
| `segment_id` | string | ✅ | 片段 ID，格式：`<doc_id>_seg_<4位十进制序号>`，如 `moon_sixpence_seg_0001`。**必须带 doc_id 前缀**——避免多文档合并时 ID 碰撞。 |
| `chapter` | string \| null | ✅ | 此片段所属章节名（preprocess 自动注入）。无章节时填 `"未知章节"`。 |
| `section_type` | string | ✅ | `"frontmatter"` / `"body"` / `"epilogue"`。preprocess 自动注入。 |
| `text_span` | object | ✅ | 原文定位 + 全文，见 §三。 |
| `confidence` | object | ✅ | 整体置信度 + 每维置信度 + 置信度方法。见 §四。 |
| `null_reasons` | object | ✅ | 所有取 null 的维度（必填层+可选层），维度编号为键，人类可读理由为值。无 null 填 `{}`。 |
| `alternatives` | array | ✅ | 替代解释方案数组。空填 `[]`。结构同 v2.3。 |
| `status` | string | ✅ | `"tentative"`（草稿/未审核）/ `"confirmed"`（已审核）/ `"superseded"`（已被新条替代）。**必须与 `confidence.overall` 对齐**——见 §四 C。 |
| `_metadata` | object | ✅ | 元数据（skill_version / model / 时间戳 / 层名 / 批注 pass）。 |

---

## 三、`text_span` 与 span 坐标系（v2.5 精确定义）

### 3.1 顶层 `text_span`（原文段引用）

```typescript
{
  "hash": string,       // 标准化后原文 sha256 截断 16 位（strip + \r\n/\r → \n）
  "start_char": number, // 片段在【原始全文】中的字符偏移（0-indexed 含，Unicode 码点）
  "end_char": number,   // 片段在【原始全文】中的字符偏移（0-indexed 不含）
  "text": string        // 原文片段全文（脱敏导出会移除）
}
```

- 不变量：`text_span.text.length === text_span.end_char - text_span.start_char`（校验器会查）。
- 不变量：`hash === sha256(normalize_text(text_span.text)).hexdigest[:16]`。

### 3.2 Craft Layer 的 span 坐标系（**段内相对偏移**，v2.5 关键修复）

Layer 3（文笔层）所有引用子串的 `span`（D13/D14/D15/D16/D17），**必须使用段内相对偏移**（以当前 `text_span.text` 为基准，0-indexed）。

```typescript
// 在 craft 维度条目中
{
  "text": string,          // 从原文摘录的子串
  "span": {
    "start": number,       // 相对 text_span.text 的开始偏移（0-indexed 含）
    "end": number          // 相对 text_span.text 的结束偏移（0-indexed 不含）
  }
}
```

**不变量（校验器强断言）**：

1. `text_span.text[span.start:span.end]`（标准化前后空白归一）与 `"text"`（标准化前后空白归一）**相似度 ≥ 95%**。
2. `0 ≤ span.start < span.end ≤ len(text_span.text)`。

**跨段 merge 时的换算**：`global_start = text_span.start_char + span.start`，`global_end = text_span.start_char + span.end`。`merge_layers.py` 负责换算。

**原因（设计评审意见）**：如果 span 直接用全局偏移，合并会让所有已完成的 span 在后续修订中失效（比如后来发现 frontmatter 被漏插一段，全文坐标整体漂移，所有 span 全部作废）。段内相对偏移 + merge 时换算 = 锚定片段内部，不会被上游修订所污染。

---

## 四、置信度（`confidence`）+ 置信度规则

```typescript
{
  "overall": number,          // 0.0 ~ 1.0。精确到 0.01 即可。
  "confidence_method": string,// "model_self_report" | "consistency_check" | "human_review"
  "per_dimension": {
    // Layer 1 Structure：D01/D04/D05/D07/D08/D10/D11（必填，0-1 数字，不能 null）
    "D01": number, "D04": number, "D05": number, "D07": number,
    "D08": number, "D10": number, "D11": number,
    // Layer 2 Interpretation：D06/D09（可选，启用时为 number，未启用为 null）
    "D06": number | null,
    "D09": number | null,
    // Layer 2.5 Emotion：D19（P4 触发段产出 emotion 文件时为 number，未触发/未跑 P4 为 null）
    "D19": number | null,
    // Layer 3 Craft：D13~D18（可选，启用时为 number，未启用为 null）
    "D13": number | null, "D14": number | null, "D15": number | null,
    "D16": number | null, "D17": number | null, "D18": number | null
  }
}
```

### 4.A 每维置信度规则

- **必填维度**（Structure 七维）：`per_dimension` 必须是 `[0.0, 1.0]` 数字。即使主值为 null（如 D10 无对话）也要填数字——表示"我确定没值"。
- **可选维度**（Interpretation/Craft）：如果主值为 null（因为此层未启用），对应维度置信度为 null；如果启用了但该条具体维度写不出有效值，置信度仍须是数字（表示"我确定没有此类内容"）。

### 4.B 置信度锚点

| 置信度 | 含义 |
|:------:|------|
| ≥0.95 | 毫无疑问——事实层明确枚举、结构层上下文充分、Craft 引文 100% 对得上 |
| 0.80-0.94 | 比较确定——可能有 1-2 处小犹豫，但主判断正确概率很高 |
| 0.70-0.79 | 基本靠谱——有模糊地带，有替代方案 |
| 0.60-0.69 | 较大不确定性——建议写 full alternatives |
| <0.60 | 很不确定——标注者不要轻易给最终值，若必须标注请补 null_reason |

### 4.C 置信度 ↔ status 自动推导规则（校验器会强制对齐）

| `confidence.overall` | `status` 应当为 | 说明 |
|:--------------------:|:--------------:|:-----|
| ≥ 0.8 | `confirmed` | 高置信度自动标记为 confirmed（可被人工再标为 superseded/保留 tentative——但反过来 `overall≥0.8` 且 `status=tentative` 校验器会 warning） |
| < 0.8 | `tentative` | 低于 0.8 禁止标 confirmed（否则校验器报 error） |
| 任何值 | `superseded` | 此条被新条替代，校验器不推导此规则（由 merge/human 标记） |

> 【区分生命周期规则 vs 生成规则】：早期设计曾混淆两者。**校验器只在"批注刚生成、status 还不是 superseded"的前提下做 §4.C 自动推导**。`status=superseded` 视为生命周期标记，跳过 §4.C。

---

## 五、引文校验规则（validate_output.py 核心）

### 5.A 哪些条目必须过引文校验

- **Layer 2 Interpretation 的 D06（信息控制）**：其 `content` 字段中任何引号（「」/"" /《》）夹取的引文，必须是 `text_span.text` 子串。
- **Layer 2.5 Emotion 的 D19.expression.key_phrases（v2.7.0 新增）**：数组**每一项**都必须是 `text_span.text` 子串（归一化后），未命中 = error（与 D06 同规则，强制）。
- **Layer 3 Craft 的 D13/D14/D15/D16/D17**：每条的 `"text"` 字段，必须是 `text_span.text` 子串（或相似度 ≥ 95%）。
- **Layer 3 Craft 的 D18（人物语言指纹）**：跨段聚合，段内相对偏移校验不适用——只需确保 `text` 在【某个 seg 的 text_span】中出现（校验器放宽 + warning）。

### 5.B 校验流程（validate_output.py 实现）

1. **引文抽取**：从自由文本中提取引号 `[「」""《》]` 包裹的内容，或直接读 Craft 条目的 `text`。
2. **子串验证（归一化后）**：`normalize(quote)` 应该是 `normalize(text_span.text)` 的子串。
   - `normalize(s) = " ".join(s.split())`（所有空白统一为单空格、去首尾空格）。
3. **位置验证（如果带 span）**：
   - `0 ≤ span.start < span.end ≤ len(text_span.text)`。
   - `" ".join(text_span.text[span.start:span.end].split())` 与 `normalize(text)` 相似度 ≥ 0.95（SequenceMatcher.ratio）。
4. **失败分档**：
   - 子串未命中 → error（强制修复）。
   - 子串命中但 span 相似度 85%-95% → warning（建议修 span）。
   - 子串命中但 span 相似度 < 85% → error（span 显然漂移）。

---

## 六、四层批注结构

---

### Layer 1：语义-结构层（`structure.jsonl`）必做

#### D01 叙事功能（枚举，必填）
**枚举值**：背景铺垫 / 激励事件 / 上升行动 / 转折 / 高潮 / 下降行动 / 结局 / 过渡 / 复合功能 / 无法判断

#### D04 情绪基调（对象，必填）
```typescript
"D04": {
  "core": string,   // 枚举 20 个：平静/压抑/焦虑/悲伤/愤怒/恐惧/喜悦/希望/绝望/孤独/信任/背叛/屈辱/尊严/嫉妒/贪婪/复仇/宽恕/悬疑/释然
  "modifier": string | null,  // 情绪修饰词（不能比 core 更长）
  "intensity": number, // 1-10 整数，与 emotion-anchors.md 对齐
  "polarity": "positive" | "negative" | "neutral" | "mixed"  // v2.6.0 新增，必填（省略=非法）
}
```
> **v2.6.0 新增 `polarity`（必填）**：情感极性——positive / negative / neutral / mixed，四值覆盖全部段落，**不得省略**（校验必填）。
> - 判断依据是**段落文本语义**（喜悦/希望/信任→positive；悲伤/愤怒/恐惧/绝望/背叛/屈辱→negative；平静→neutral；多情绪交织或反讽张力→mixed），不由情节走向或文风推导。
> - 拿不准时回到「core → 极性」缺省映射（emotion-anchors.md），宁用 `neutral`/`mixed` 兜底也**不要省略**。
> - 旧产物 `schema_version: "2.5.0"`（无 polarity）由校验器**版本分支豁免**放行（历史数据豁免，不是"可选"），无需迁移。

#### D05 叙事节奏（1-5 整数，必填）：1极慢 → 5极快。

#### D07 叙事视角（对象，必填）
**type 枚举**：第一人称 / 第二人称 / 第三人称有限 / 第三人称全知 / 多视角 / 不可靠叙述者 / 客观叙事
```typescript
"D07": {
  "type": string,
  "is_switch_point": boolean,
  "switch_from": string | null,
  "switch_to": string | null
}
```

#### D08 时空标记（对象，必填）
```typescript
"D08": { "time": string | null, "space": string | null }
```

#### D10 对话功能（可 null）
**枚举值（有对话时必填）**：推动情节 / 揭示性格 / 传递信息 / 制造冲突 / 营造氛围 / 复合功能

#### D11 描写类型（字符串数组，必填，非空）
**枚举值（可多选 ≥ 1）**：环境描写 / 心理描写 / 动作描写 / 外貌描写 / 感官描写

**Structure 层输出根结构**：
```json
{
  "schema_version": "2.6.0",
  "annotation_id": "<doc_id>_seg_0001_structure_ann_0",
  "document_id": "<doc_id>",
  "segment_id": "<doc_id>_seg_0001",
  "chapter": "string|null",
  "section_type": "frontmatter|body|epilogue",
  "text_span": { "hash": "...", "start_char": 0, "end_char": 0, "text": "..." },
  "layers": {
    "structure": {
      "D01": "背景铺垫",
      "D04": { "core": "平静", "modifier": null, "intensity": 3, "polarity": "neutral" },
      "D05": 3,
      "D07": { "type": "第三人称有限", "is_switch_point": false, "switch_from": null, "switch_to": null },
      "D08": { "time": null, "space": null },
      "D10": null,
      "D11": ["心理描写"]
    }
  },
  "confidence": { "overall": 0.85, "confidence_method": "model_self_report", "per_dimension": { "D01": 0.9, "...": 0.9 } },
  "null_reasons": {},
  "alternatives": [],
  "status": "confirmed",
  "_metadata": { "skill_version": "2.6.0", "model": "deepseek-r1", "generated_at": "ISO8601", "layer": "structure" }
}
```

---

### Layer 2：阐释-判断层（`interpretation.jsonl`）按需

#### D06 信息控制（可 null）
```typescript
"D06_information_control": {
  "type": "揭示|隐藏|误导|复合",
  "content": string   // 引文必须来自原文子串（过 §五 引文校验）
} | null
```

#### D09 主题标签（≤3 的字符串数组，可 null）

#### 叙述者可靠性（枚举，v2.5 新）
```typescript
"narrator_reliability": "可靠 | 部分不可靠 | 不可靠 | 无法判断 | null"
```

**Interpretation 层输出根结构**：`annotation_id` 后缀 `_interpretation_ann_0`，`layers.interpretation` 里放上述三维，其他字段同 Layer 1。

---

### Layer 2.5：情感分析——D19_emotion_analysis（`emotion.jsonl`）阐释层扩展，v2.7.0 新增

> **定位**：D19 是**阐释层（Layer 2）的语义扩展，不是独立架构层**（决策 17）。区别于 L1 的 D04「段落氛围摘要」（20 词粗粒度），D19 做**角色/精细情感分析**（44 词）：复合情感、情感对象、触发点、段内情感弧、表达方式。两者若对同一情绪都产出判断，**以 D19 为准**。
> **P4 Pass 独立产物**：D19 走独立 P4 Pass，落**独立文件 `{doc_id}_emotion.jsonl`**（append-only，独立校验），不回写 interpretation 行；`merge_layers` 时并入 `merged.emotion`。
> **词表演化例外**：`emotion` 枚举真源为 `references/emotion-lexicon.md`（44 词，validate 白名单逐词同步该文件）。

#### D19 触发条件（P4 是否对本段执行；任一命中 = 触发）

| # | 条件 | 依据字段 |
|:--:|:--|:--|
| 1 | 本段情绪强度 ≥ 4 | structure 层 `D04.intensity` |
| 2 | 本段是叙事关键段 | structure 层 `D01 ∈ {激励事件, 上升行动, 高潮, 转折}` |
| 3 | 本段含对话 | structure 层 `D10` 非 null |
| 4 | 用户显式要求深度情感分析 | 调用指令 |

> 不触发 → 该段不产出 emotion 行，登记 checkpoint `emotion_skipped`（区别于"没批"）。**纯议论/静态背景段且 intensity < 4 时几乎总是不触发**——不要强行编造情感。

#### D19 字段定义

```typescript
"layers": {
  "emotion": {
    "D19_emotion_analysis": {
      // 1. 主情感（必填）
      "primary": {
        "emotion": string,       // 枚举：references/emotion-lexicon.md 44 词（如 "冷峻中的悲悯"）
        "intensity": number,     // 1-10 整数，与 emotion-anchors.md 强度档对齐
        "polarity": "positive" | "negative" | "neutral" | "mixed"  // 文本语义判定；词表有极性缺省兜底
      },
      // 2. 复合情感（可 null：无独立次要情感时合法为 null，不要为凑数硬写）
      "secondary": [
        { "emotion": string, "intensity": number, "polarity": "positive" | "negative" | "neutral" | "mixed" }
      ] | null,
      // 3. 情感对象（可 null：议论段/无明确对象时合法为 null）
      "target": {
        "entity_id": string | null,  // 分析侧 entity 映射表的角色 ID；skill 内未建映射时填 null
        "name": string,              // 段内实指称呼（如 "思特里克兰德"）
        "relation": string | null    // 情感关系类型（如 "admiration"/"contempt"/"grief-for"，自由文本）
      } | null,
      // 4. 情感触发点（可 null：非事件触发/无法定位时合法为 null）
      "trigger": {
        "description": string,       // 触发源描述（事件/言行/回忆等）
        "source_segment": string | null  // 触发源若在别段则给 segment_id，本段内触发填 null
      } | null,
      // 5. 段内情感弧（可 null：整段基调无位移时合法为 null，不强行编造）
      "arc": {
        "has_shift": true,
        "shift_point": string,       // 位移发生的文本位置描述（可用原文短语）
        "before": { "emotion": string, "intensity": number, "polarity": string },  // 位移前主位
        "after":  { "emotion": string, "intensity": number, "polarity": string }    // 位移后主位
      } | null,
      // 6. 情感表达方式（必填）
      "expression": {
        "direct": boolean,           // 是否有直接情感词（"他愤怒了"）
        "indirect": boolean,         // 是否通过动作/环境/隐喻间接表达
        "key_phrases": string[],     // 情感承载短语（原文摘录，每项必须过 §五 子串校验；可直接由 D13/D15 精选）
        "note": string | null        // 补充（如 "本段为议论性文字，情感含蓄"）
      }
    }
  }
}
```

#### 字段约束速查

| 字段 | 约束 |
|:--|:--|
| `primary.emotion` / `secondary[].emotion` / `arc.before.after.emotion` | 必须 ∈ emotion-lexicon.md 44 词；词表无对应 → 用最接近词 + `expression.note` 说明，**不造新词** |
| `primary.intensity` 等 | 1-10 整数（emotion-anchors.md 档位） |
| `polarity` | 四值全覆盖；词表极性为缺省映射，明显张力/复合可偏离写 mixed |
| `target` / `trigger` / `arc` | 三者均 null-合法——无对象/无事件触发/无位移时写 null + `null_reasons`（顶层）注明，禁止强行编造（对应方案前置 C3：arc 可选即场景边界问题的等价出口） |
| `secondary` | 建议 ≤ 2 项；已固化复合词（悲欣交集/爱恨交织/苦乐参半）直接做主情感，不再拆 secondary |
| `expression.key_phrases` | 数组每项必须是 `text_span.text` 子串（归一化），未命中 = 校验 error |
| `confidence.per_dimension.D19` | P4 触发段必填 0-1 数字 |

#### Emotion 层输出根结构

```json
{
  "schema_version": "2.7.0",
  "annotation_id": "<doc_id>_seg_0051_emotion_ann_0",
  "document_id": "<doc_id>",
  "segment_id": "<doc_id>_seg_0051",
  "chapter": "第四十六章",
  "section_type": "body",
  "text_span": { "hash": "...", "start_char": 0, "end_char": 0, "text": "..." },
  "layers": {
    "emotion": {
      "D19_emotion_analysis": {
        "primary": { "emotion": "冷峻中的悲悯", "intensity": 6, "polarity": "mixed" },
        "secondary": null,
        "target": { "entity_id": null, "name": "叙述者", "relation": "pity" },
        "trigger": { "description": "叙述者冷眼描述思特里克兰德之死的平庸", "source_segment": null },
        "arc": null,
        "expression": {
          "direct": false,
          "indirect": true,
          "key_phrases": ["他的一生都是这样安排的", "死亡是毫无意义的"],
          "note": "叙述性冷漠包裹下的悲悯"
        }
      }
    }
  },
  "confidence": { "overall": 0.82, "confidence_method": "model_self_report", "per_dimension": { "D19": 0.85 } },
  "null_reasons": {},
  "alternatives": [],
  "status": "confirmed",
  "_metadata": { "skill_version": "2.7.0", "model": "deepseek-r1", "generated_at": "ISO8601", "layer": "emotion", "annotation_pass": "P4" }
}
```

---

### Layer 3：文笔-语言层（`craft.jsonl`）按需

**所有条目必须带段内相对偏移 span，且过 §五 引文校验。**

#### D13 佳句提取（数组条目）
```typescript
"D13_golden_lines": [
  {
    "text": string,                 // 原文摘录（必须是子串）
    "span": { "start": number, "end": number },  // 段内相对偏移
    "reason": string,               // 为什么这个句子精彩
    "quality_score": number         // 1-5，段内横向比较（5=本段最佳）
  }
]
```

#### D14 修辞手法（数组条目）
```typescript
"D14_rhetoric": [
  {
    "text": string, "span": {...},
    "type": "比喻|拟人|排比|反讽|通感|夸张|对比|象征",
    "detail": string   // 说明本体/喻体等
  }
]
```

#### D15 意象提取（数组条目）
```typescript
"D15_imagery": [
  {
    "text": string, "span": {...},
    "type": "自然意象|器物意象|人体意象|色彩意象|抽象意象",
    "cluster": string | null   // 跨段聚合时的聚类标签（段内时可 null）
  }
]
```

#### D16 词汇精讲（数组条目）
```typescript
"D16_diction": [
  {
    "text": string, "span": {...},
    "pos": "动词|形容词|副词|名词",
    "reason": string,           // 为什么选这个词、它的特别之处
    "alternatives": string[]    // 可替换的普通词（对比用）
  }
]
```

#### D17 句式分析（数组条目）
```typescript
"D17_syntax": [
  {
    "text": string, "span": {...},
    "type": "排比|长短交替|倒装|独词句|对偶|设问",
    "effect": string             // 产生的表达效果
  }
]
```

#### D18 人物语言指纹（数组，可跨段聚合）
```typescript
"D18_character_voice": [
  {
    "character": string,          // 说话者名
    "pattern": string,            // 习语/口癖
    "span": { "start": number, "end": number } | null,  // 如果在本段内则带
    "occurrence_count": number    // 出现次数（整本书聚合后填）
  }
]
```

**Craft 层输出根结构**：`annotation_id` 后缀 `_craft_ann_0`，`craft` 顶层键放上述 6 个数组，其余字段同 Layer 1。

---

### Layer 4：跨段-关系层（`cross_segment.jsonl`）二阶段

Layer 4 **不在逐片段中执行**——等 Layer 1-3 全部完成后，独立调用 `cross_segment.py`。

```typescript
{
  "schema_version": "2.6.0",
  "doc_id": "<doc_id>",
  "cross_refs": [
    {
      "ref_id": string,      // 唯一 ID，如 "cf_0001"
      "relation_type": "伏笔-回收 | 因果 | 时序 | 对比 | 呼应",
      "source": {                            // 关系起点
        "segment_id": "<doc_id>_seg_0003",
        "chapter": string | null,
        "anchor_text": string,              // 内容锚点：原文摘录的关键短语
        "span": { "start": number, "end": number } | null  // 段内相对偏移
      },
      "target": {                            // 关系终点
        "segment_id": "<doc_id>_seg_0027",
        "chapter": string | null,
        "anchor_text": string,
        "span": { "start": number, "end": number } | null
      },
      "confidence": number,     // 0-1，单条关系的置信度
      "note": string | null     // 为什么判定为这种关系
    }
  ],
  "_metadata": {
    "skill_version": "2.6.0",
    "generated_at": "ISO8601",
    "window_size": 15,
    "overlap": 3,
    "method": "rule_based_or_llm_batched"
  }
}
```

**引用方式（双引用）**：设计评审要求——跨段关系**既要带 `segment_id`（位置 ID），也要带 `anchor_text`（内容锚点）**。如果后续某段被重切导致 segment_id 序号漂移，`anchor_text` 可以重新定位原文，保证关系不失效。

---

### Merged 嵌套文档（`merged.jsonl`）

`merge_layers.py` 以 segment 为轴心，把同一段的各层合并：

```typescript
{
  "segment_id": "<doc_id>_seg_0001",
  "chapter": string | null,
  "section_type": "frontmatter|body|epilogue",
  "text_span": { "...": "..." },       // 直接从 segments.jsonl 的对应行取
  "structure":        { "...": "..." }, // 该段 structure 层 layers.structure
  "interpretation": { "...": "..." } | null,   // 如果跑了 interpretation
  "emotion":          { "...": "..." } | null, // 如果跑了 P4 emotion（D19，v2.7.0）
  "craft":            { "...": "..." } | null, // 如果跑了 craft
  "cross_refs_sources": string[],   // 此段作为 source 的 cross_refs.ref_id 列表
  "cross_refs_targets": string[]    // 此段作为 target 的 cross_refs.ref_id 列表
}
```

---

## 七、Checkpoint 状态机（断点续跑）

`{doc_id}_checkpoint.json`：

```json
{
  "doc_id": "...",
  "schema_version": "2.7.0",
  "total_segments": 58,
  "completed": [
    { "segment": "<doc_id>_seg_0001", "layers": ["structure", "interpretation", "craft", "emotion"] },
    { "segment": "<doc_id>_seg_0002", "layers": ["structure"] }
  ],
  "emotion_skipped": ["<doc_id>_seg_0002"],   // P4 判定不触发（D04.intensity<4 且非关键叙事段且无对话）的段——与"没批"区分
  "cross_segment_completed": false,
  "merged_completed": false,
  "render_report_completed": false,
  "last_updated": "ISO8601",
  "created_at": "ISO8601"
}
```

> **v2.7.0 checkpoint 扩展**：`completed[].layers` 新增合法层名 `"emotion"`（P4 触发段完成 D19 后由 annotate/人工登记）；`emotion_skipped` 登记未触发段。层依赖：cross_segment（Phase 3）不依赖 emotion；merge/report（Phase 4/5）读取 emotion.jsonl（缺失则跳过 emotion 区）。

**续跑逻辑**：
1. 读 checkpoint；
2. 对 `completed` 中已存在的 `(segment, layer)` 组合直接跳过；
3. 从第一个 `(segment, layer)` 未完成组合开始续跑。

---

## 八、版本兼容矩阵

| 版本 | 与 v2.7.0 兼容 | 迁移说明 |
|------|:---------------:|---------|
| v2.3.0 | ❌ 大改 | 3 层 → 4 层，字段层级重构（structure/interpretation 从 `layers` 提升到层级 JSONL），新增 narrator_reliability / craft 6 维 / cross_refs / checkpoint。需逐字段迁移或对原文重跑 v2.7 管线（见 README 常见问题 Q5）。 |
| v2.5.0 | ✅ | 校验器接受 2.5.0（2.6 新增必填子字段 `D04.polarity`，但对 2.5.0 旧产物**版本分支豁免**；2.7 的 D19 对 2.5.0 产物完全不适用）。旧产物无需迁移。 |
| v2.5.x | ✅ | 修订号，纯 bugfix，不破坏字段。 |
| v2.6.0 | ✅ | 新增必填子字段 `D04.polarity`（旧 2.5.0 产物豁免）；跨段规则版补 span / 锚点清洗；Markdown 报告补 L2/L3 摘要。v2.7.0 不改动 L1–L3 字段，2.6.0 产物零迁移。 |
| v2.7.0 | ✅ 当前 | 新增 **D19 情感分析**（阐释层语义扩展，P4 Pass，独立 `emotion.jsonl`）：emotion 枚举见 `references/emotion-lexicon.md`（44 词）；`arc`/`target`/`trigger` null-合法；`key_phrases` 过原文子串校验。L1–L3 文件 schema 不变（续批可写 2.7.0 或保持 2.6.0）。下游解析器：emotion 文件字段一定齐全；旧产物按无 emotion 处理即可。 |
| v3.0.0（未来） | ❌ | 破坏性升级。 |

---

> **Schema 唯一真源原则的执行细则**：当你发现自己在改 SKILL.md 里的枚举、改 validate_output.py 里的枚举、或改 templates/*.json 里的枚举——**立刻先改本文件**，然后再同步下游三个。禁止直接改下游文件而本文件不动。
