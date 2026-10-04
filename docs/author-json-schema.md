# author.json Schema（可配置写作管线，M14 定稿）

> 版本：`2026-09-29-a`。依据：任务书《作者写作管线-启动提示词.md》§3、选型草稿 §3.2.4、persona-writing-lab 实证。
> 代码级校验：`app/authors/schema.py`（`validate_author_json` / `load_author_config`），缺字段/类型错/非法枚举导入即报错，字段可增不可减。
> 分层原则：**author.json = 作者全量身份与管线配置；模型不在 JSON 中**——运行时模型由 DB `Author.model`（后台作者配置页）绑定。JSON 是可导出、可版本管理、可复制的"身份资产"。

## 存储与迁移策略

- 导入：`app/authors/importer.py::import_author_json`——按 `identity.name` upsert DB `Author`，整份 JSON 存 `Author.author_json` 列（round-trip 的 DB 侧权威），并派生 `persona_prompt`（identity 扁平渲染）与 `memory_config`（dynamic_modules）。
- 执行分派：`writer.run_write` 检测 `author.author_json`——有 JSON 走管线执行器（`app/authors/pipeline.py`）；无 JSON 走现行 single 路线，行为不变。
- 运行时绑定参数（导入时显式传入、不入 JSON）：`model`、`readable_directions`、`rank_provider`。

## 字段总表

### 顶层

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `id` | string | ✓ | 与 DB Author 关联键（JSON 侧 id；DB 侧按 identity.name upsert） |
| `template` | string | ✓ | `single` \| `custom` \| `lab:<人格>`（lab 移植来源标注） |
| `identity` | object | ✓ | 身份层，见下 |
| `route` | object | ✓ | 管线层，见下 |
| `memory` | object | ✓ | 记忆层，见下 |
| `output` | object | ✓ | 输出契约，见下 |
| `version` | string | ✓ | JSON 自身版本号，改结构必须升版本 |

### identity（身份层，渲染进系统提示词）

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `name` | string | ✓ | 作者名（= DB Author.name） |
| `description` / `personality` / `values_stance` / `scenario` / `style_anchor` | string | ✓ | 传记事实 / 人格思维 / 价值立场 / 场景 / **声音示范非内容示范**（lab 结论3） |
| `style_rules.do` / `.dont` / `.fingerprint` | string[] | ✓ | 文风规则；fingerprint 为门禁指纹词表 |
| `style_rules.extra_checks` | object | （可选） | 附加检查参数（本阶段未挂接，预留） |
| `quotes_original` | string[] | ✓ | 自我引句（少量声音锚） |
| `provenance` | string[] | ✓ | 来源标注（角色卡/原著/自创） |

### route（管线层）

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `outline.template` | enum | ✓ | `pyramid`（金字塔）/ `variation`（乐章变奏）/ `sectional`（剖层）/ `formula`（轶事→nut graf→kicker）/ `none`；`params` object 必填（可空） |
| `draft.mode` | enum | ✓ | `single`（单次）/ `rolling`（逐节滚动+前文重注入）/ `incubate`（腹稿→落笔）/ `dictate`（口授一次成文） |
| `draft.params.max_tokens` | int | （可选） | 默认 4000 |
| `draft.params.think` | bool | （可选） | 兼容字段（实际档位以 think_routing 为准） |
| `passes` | array | ✓ | 修订遍列表：`{type, params}`；type ∈ `prune`（删节，params.target_ratio/instruction）/ `rhythm`（节奏）/ `distort`/`callback`/`selfrev`（**接口占位，本阶段 passthrough 并记 trace**） |
| `gates.length` | `{min,max,unit:"chars"}` | ✓ | 字数门禁（clean 口径：去脚注标记+空白归一化） |
| `gates.fingerprint` | `{min_hits}` | ✓ | 风格指纹命中下限 |
| `gates.echo_check` | bool | ✓ | 锚回显检查（最长公共子串 ≥20 字符判复制，lab 仪器级口径） |
| `gates.citation` | `{min_count}` | ✓ | 脚注引用条数下限 + 逐字溯源硬校验 |
| `gates.copyright` | `{ngram}` | ✓ | 正文对静态记忆块 n 连续字符复述 ≥2 处判违规（1 处容忍级 warn） |
| `gates.topic_dedup` | `{recent_n, threshold?}` | ✓ | **L1 选题去重前置门禁**：标题与近期文章字符 bigram Dice（默认阈值 0.55） |
| `gates.custom` | array | ✓ | 自定义断言占位（可扩展，本阶段不执行） |
| `rewrite.mode` | enum | ✓ | `gated_retry`（附违规说明重试）/ `zero_revision`（违规只记审计工件，不重写仍入库） |
| `rewrite.max_attempts` | int(1-10) | ✓ | gated 重试上限（每次重试的中间稿都是废稿，trace 可查） |
| `rewrite.on_gate_fail` | enum | ✓ | `revise` / `record` |
| `think_routing.default` | enum | ✓ | `chat` \| `reasoner`（provider 层档位；**JSON 节点恒为 chat**——lab studio A/B 结论） |
| `think_routing.per_node` | object | （可选） | 调用点→档位，键限 `w_*`/`writing`；reasoner 档实测不可用时自动回退 chat 并记 trace |

### memory（记忆层）

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `static_blocks` | array | ✓ | `{id, text(≤500字逐字原文), source(文件+行号定位), injection:{max_chars}}`——大段原著片段等身份资产（谭雅实测落点） |
| `injection.max_slices_per_run` | int | ✓ | **硬预算**：每次执行最多注入段数（本次实测=3） |
| `injection.per_block_max_chars` | int | ✓ | 每段最多字数（本次实测=500；超长截断并记录） |
| `injection.selection` | enum | ✓ | `round_robin`（按历史 WriteRun 数轮转）/ `recency`（列表尾）/ `relevant`（与阅读集标题 bigram 重叠） |
| `injection.position` | enum | ✓ | `head`（首部风格示范区）/ `tail`（尾部上下文区）/ `u`（U 形：第一片在前其余在后，lab 结论4） |
| `dynamic_modules` | object | ✓ | DB 动态条目载入量，键=模块名（feedback/topic），导入时派生为 `{k}_memory` 占位符配置 |

### output（输出契约）

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `format` | string | ✓ | 本阶段仅 `markdown` |
| `footnote_citations` | bool | ✓ | 正文 `[^K]` 脚注 + 文末定义行 `[^K]: [条目 <id>] <逐字原句>`；执行器解析定义行→结构化 citations（item_id + quote 逐字校验不变）落 `article.citations` |
| `max_tokens_per_node` | object | （可选） | 调用点→max_tokens 覆写 |

> **可选 object 字段的显式 null 口径**：`max_tokens_per_node`、`think_routing.per_node` 等
> 可选 object 字段写显式 `null` 视为"未写该键"（宽松归一，不报类型错）。

## 与任务书骨架的差异（偏离记录）

1. **`memory.injection.position` 枚举为 `head|tail|u`**（任务书示例为中文描述"首部风格示范区/尾部上下文区"）——语义一致，机器可判定。
2. **`gates.topic_dedup` 增加 `threshold` 可选参数**（默认 0.55，Dice 相似度）——L1 治理需要可标定阈值，任务书未覆盖，保守默认。
3. **`style_rules.extra_checks` 本阶段不挂接执行**（lab 的感叹号/虚词等专属检查）——作为 fingerprint 门禁的扩展位保留，luxun 用 fingerprint(≥4) 覆盖虚词检查；感叹号纪律经 style_rules.dont 提示词约束。
4. **`output.format` 仅支持 markdown**——任务书骨架即 markdown，JSON 中保留字段做显式声明。
5. `route.draft.params.think` 保留但实际档位由 `think_routing` 决定（避免两处配置打架）。
