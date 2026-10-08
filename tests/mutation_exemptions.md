# 变异测试豁免清单（tests/mutation_exemptions.md）

> T1 分诊批次 1（认证域）登记。类别：A = 等价变异（不改变任何可观察行为）；
> B = 防御分支（正常运行不可触达，设计书明确要求其存在）。
> 依据任务书 `doc/CI0/CI0-分诊批次1-任务书.md` §2；裁决依据为两份正式设计书 v1.4。
> C 类（测试缺口）与 D 类（设计模糊）**不在本清单**：C 类由 `tests/test_mutation_t1.py`
> 补测试击杀，D 类交统筹（见执行汇报 §3）。

## 批次 1：认证域（14 A + 1 B = 15 条）

| mutant 全名 | 类别 | 一句话理由 | 依据条款或推理 |
|---|---|---|---|
| app.api.deps.xǁLoginRateLimiterǁ__init____mutmut_5 | A | `datetime.now(timezone.utc)`→`datetime.now(None)`：naive 本地时间，但锁定期比较两端均出自同一时钟源，自洽无跨时钟比对 | `now` 为唯一时钟源（注入即整体替换）；进程内字典不持久化（ADR-2 单机单进程），重启清零 |
| app.api.deps.xǁLoginRateLimiterǁallow__mutmut_14 | A | `pop(key, None)`→`pop(key,)`：该分支由 `rec = self._store.get(key)` 非 None 保证 key 必在字典，default 参数不可达 | 代码路径推理：`allow` 先 get 后 pop，同 key 无并发删除（单进程 ADR-2） |
| app.api.deps.xǁLoginRateLimiterǁrecord_failure__mutmut_9 | A | 初始 dict 键 `"locked_until"`→`"XXlocked_untilXX"`：初始 None 值从不被读取差异——`allow` 读真实键得 None 即"未锁"，锁定由第 5 次失败对真实键直接赋值 | 行为等价推理：`rec["locked_until"] = ...`（record_failure 内）不受初始 dict 键名影响 |
| app.api.deps.xǁLoginRateLimiterǁrecord_failure__mutmut_10 | A | 同上（`"LOCKED_UNTIL"` 变体） | 同上 |
| app.api.deps.x_require_session__mutmut_18 | A | 401 message 文本 `"未认证"`→`"XX未认证XX"`：设计书只钉 code（`AUTH_REQUIRED`），未规定该字段措辞 | AC-01.3（只钉 code）+ A 类判据"异常消息文本（设计书未规定其措辞）" |
| app.api.deps.x_require_session__mutmut_30 | A | 403 message 文本变体：同上，设计书只钉 code（`PASSWORD_CHANGE_REQUIRED`） | AC-01.1（只钉 code）；措辞无条款 |
| app.auth.x_issue_session__mutmut_8 | A | `token_urlsafe(32)`→`token_urlsafe(None)`：nbytes=None 走库默认值恰为 32 字节，熵与格式完全相同 | 等价：`secrets.token_urlsafe` 签名默认 nbytes=32 |
| app.auth.x_issue_session__mutmut_9 | A | `token_urlsafe(32)`→`token_urlsafe(33)`：33 字节 ≈ 264bit，仍满足"id ≥128bit 随机"；id 为不透明 cookie 值，长度无条款约束 | 函数 docstring 条款「id ≥128bit 随机」仍满足；断言精确长度属与设计书无关的断言（禁写） |
| app.auth.x_verify_password__mutmut_6 | B | `except Exception: return False`→`return True`：哈希格式损坏兜底分支——哈希均由本模块 `hash_password` 产生，损坏仅能由外部篡改 DB 触发，正常运行不可达；且兜底语义 = 一律按校验失败 | 任务书 §2 B 判据原文示例「`except Exception` 兜底（设计书明确按校验失败处理）」+ 产品书 D2 / 技术书 ADR-4（argon2id 校验纪律）；防御分支豁免 |

## 批次 2：providers.base + T1 三条 D 转 C（2026-10-03，C1-1）

> 本批无 B 类；D 类 13 条（HTTPProvider.__init__ m3-m15，URL 拼接/HTTP 头细节）不在本清单，
> 见 C1-1 执行汇报 §3。T1 三条 D 转 C 按设计书 v1.5（AC-01.2b/01.4b/ADR-5⑤b）落测试，亦不在此清单。

| mutant 全名 | 类别 | 一句话理由 | 依据条款或推理 |
|---|---|---|---|
| app.providers.base.x_record_usage__mutmut_6 | A | 缺省值变异（latency_ms/ok）——全部生产调用点（_call/embedding/rerank）显式传参，默认不可达 | 调用点核查：app/providers/base.py:131/156、app/embedding/base.py:111/132、app/rerank/base.py:163 均显式传参 |
| app.providers.base.x_record_usage__mutmut_7 | A | 缺省值变异（latency_ms/ok）——全部生产调用点（_call/embedding/rerank）显式传参，默认不可达 | 调用点核查：app/providers/base.py:131/156、app/embedding/base.py:111/132、app/rerank/base.py:163 均显式传参 |
| app.providers.base.x_record_usage__mutmut_42 | A | error 截断界 [:2000]→[:2001]：实际 error 文本 ≤约 350 字符（响应体截 300 后脱敏拼接），界值不可达且数值无条款 | 推理：error 来源 _call/_post_json 均先截 300 字符；设计书无截断界条款 |
| app.providers.base.xǁLLMProviderǁ_call__mutmut_4 | A | last_err 初始值 None→""：仅在至少一次失败后被赋值读取，初值不可达 | 控制流推理 |
| app.providers.base.xǁLLMProviderǁ_call__mutmut_13 | A | latency *1000→*1001：int 取整后恰等（0.25s→250），0.1% 缩放微差无精确度条款，账本 ms 单位语义不变 | ADR-8 只钉计量含延迟，未钉缩放常数 |
| app.providers.base.xǁLLMProviderǁ_call__mutmut_41 | A | ok=True 移除后落 record_usage 默认 ok=True，行为等价 | 函数签名默认值等价推理 |
| app.providers.base.xǁLLMProviderǁ_call__mutmut_45 | A | payload.get("model", 缺省) 缺省变体——ADR-8 契约调用 payload 恒含 model 键，缺省分支不可达 | 调用点核查：deepseek/moark_jev 构造 payload 恒含 model |
| app.providers.base.xǁLLMProviderǁ_call__mutmut_47 | A | payload.get("model", 缺省) 缺省变体——ADR-8 契约调用 payload 恒含 model 键，缺省分支不可达 | 调用点核查：deepseek/moark_jev 构造 payload 恒含 model |
| app.providers.base.xǁLLMProviderǁ_call__mutmut_50 | A | payload.get("model", 缺省) 缺省变体——ADR-8 契约调用 payload 恒含 model 键，缺省分支不可达 | 调用点核查：deepseek/moark_jev 构造 payload 恒含 model |
| app.providers.base.xǁLLMProviderǁ_call__mutmut_52 | A | meter.get 缺省变体（0→1/None）——meter 契约恒含 5 个 token 键（_meter_from_openai_usage 恒返全键），缺省分支不可达 | _post 抽象 docstring：计量信息含 prompt/completion/billing_units（必含），real 流 _meter_from_openai_usage 恒返 5 键 |
| app.providers.base.xǁLLMProviderǁ_call__mutmut_57 | A | meter.get 缺省变体（0→1/None）——meter 契约恒含 5 个 token 键（_meter_from_openai_usage 恒返全键），缺省分支不可达 | _post 抽象 docstring：计量信息含 prompt/completion/billing_units（必含），real 流 _meter_from_openai_usage 恒返 5 键 |
| app.providers.base.xǁLLMProviderǁ_call__mutmut_59 | A | meter.get 缺省变体（0→1/None）——meter 契约恒含 5 个 token 键（_meter_from_openai_usage 恒返全键），缺省分支不可达 | _post 抽象 docstring：计量信息含 prompt/completion/billing_units（必含），real 流 _meter_from_openai_usage 恒返 5 键 |
| app.providers.base.xǁLLMProviderǁ_call__mutmut_64 | A | meter.get 缺省变体（0→1/None）——meter 契约恒含 5 个 token 键（_meter_from_openai_usage 恒返全键），缺省分支不可达 | _post 抽象 docstring：计量信息含 prompt/completion/billing_units（必含），real 流 _meter_from_openai_usage 恒返 5 键 |
| app.providers.base.xǁLLMProviderǁ_call__mutmut_66 | A | meter.get 缺省变体（0→1/None）——meter 契约恒含 5 个 token 键（_meter_from_openai_usage 恒返全键），缺省分支不可达 | _post 抽象 docstring：计量信息含 prompt/completion/billing_units（必含），real 流 _meter_from_openai_usage 恒返 5 键 |
| app.providers.base.xǁLLMProviderǁ_call__mutmut_71 | A | meter.get 缺省变体（0→1/None）——meter 契约恒含 5 个 token 键（_meter_from_openai_usage 恒返全键），缺省分支不可达 | _post 抽象 docstring：计量信息含 prompt/completion/billing_units（必含），real 流 _meter_from_openai_usage 恒返 5 键 |
| app.providers.base.xǁLLMProviderǁ_call__mutmut_73 | A | meter.get 缺省变体（0→1/None）——meter 契约恒含 5 个 token 键（_meter_from_openai_usage 恒返全键），缺省分支不可达 | _post 抽象 docstring：计量信息含 prompt/completion/billing_units（必含），real 流 _meter_from_openai_usage 恒返 5 键 |
| app.providers.base.xǁLLMProviderǁ_call__mutmut_78 | A | meter.get 缺省变体（0→1/None）——meter 契约恒含 5 个 token 键（_meter_from_openai_usage 恒返全键），缺省分支不可达 | _post 抽象 docstring：计量信息含 prompt/completion/billing_units（必含），real 流 _meter_from_openai_usage 恒返 5 键 |
| app.providers.base.xǁLLMProviderǁ_call__mutmut_80 | A | meter.get 缺省变体（0→1/None）——meter 契约恒含 5 个 token 键（_meter_from_openai_usage 恒返全键），缺省分支不可达 | _post 抽象 docstring：计量信息含 prompt/completion/billing_units（必含），real 流 _meter_from_openai_usage 恒返 5 键 |
| app.providers.base.xǁLLMProviderǁ_call__mutmut_85 | A | meter.get 缺省变体（0→1/None）——meter 契约恒含 5 个 token 键（_meter_from_openai_usage 恒返全键），缺省分支不可达 | _post 抽象 docstring：计量信息含 prompt/completion/billing_units（必含），real 流 _meter_from_openai_usage 恒返 5 键 |
| app.providers.base.xǁLLMProviderǁ_call__mutmut_97 | A | error 路径 latency *1000→*1001：同 m13，0.1% 缩放微差无条款 | 同 m13 |
| app.providers.base.xǁLLMProviderǁ_call__mutmut_109 | A | getattr(e,"retryable",False) 默认值 False→True：httpx 错误被 isinstance 短路、ProviderError 恒有 retryable 类属性，默认不可达 | 控制流推理 |
| app.providers.base.xǁLLMProviderǁ_call__mutmut_129 | A | error 路径 payload.get("model", 缺省) 缺省变体——同 m45 组 | 同 m45 组 |
| app.providers.base.xǁLLMProviderǁ_call__mutmut_131 | A | error 路径 payload.get("model", 缺省) 缺省变体——同 m45 组 | 同 m45 组 |
| app.providers.base.xǁLLMProviderǁ_call__mutmut_134 | A | error 路径 payload.get("model", 缺省) 缺省变体——同 m45 组 | 同 m45 组 |
| app.providers.base.xǁLLMProviderǁ_call__mutmut_136 | A | error 文本前缀 type(e)→type(None)（"NoneType: …"）：仍含完整原因文本，账本 error 落账语义满足，文本格式无条款 | 账本 error 语义=记录原因（DT-5），格式无条款 |
| app.providers.base.xǁLLMProviderǁ_call__mutmut_147 | A | log.warning 文案/实参变异（重试日志行）——D12 未规定该行内容与措辞 | ADR-12 只钉级别纪律与结构化字段，未钉业务日志文案 |
| app.providers.base.xǁLLMProviderǁ_call__mutmut_152 | A | log.warning 文案/实参变异（重试日志行）——D12 未规定该行内容与措辞 | ADR-12 只钉级别纪律与结构化字段，未钉业务日志文案 |
| app.providers.base.xǁLLMProviderǁ_call__mutmut_154 | A | log.warning 文案/实参变异（重试日志行）——D12 未规定该行内容与措辞 | ADR-12 只钉级别纪律与结构化字段，未钉业务日志文案 |
| app.providers.base.xǁLLMProviderǁ_call__mutmut_155 | A | log.warning 文案/实参变异（重试日志行）——D12 未规定该行内容与措辞 | ADR-12 只钉级别纪律与结构化字段，未钉业务日志文案 |
| app.providers.base.xǁHTTPProviderǁ__init____mutmut_1 | A | timeout 默认 120.0→120.1：显式超时语义不变（技术书 §4.2 只要求必填），数值无条款 | 技术书 §4.2「外部调用一律显式超时」——任意有限值均满足 |
| app.providers.base.x_parse_strict_json__mutmut_3 | A | 围栏标记 "```"→"XX```XX"：花括号切片（第一个 { 到最后一个 }）兜底使围栏剥离对一切合法输入冗余，解析结果等价 | 函数契约（docstring）+ R5：切片兜底覆盖围栏场景；输出等价推理 |
| app.providers.base.x_parse_strict_json__mutmut_5 | A | strip("`")→strip(None)：花括号切片（第一个 { 到最后一个 }）兜底使围栏剥离对一切合法输入冗余，解析结果等价 | 函数契约（docstring）+ R5：切片兜底覆盖围栏场景；输出等价推理 |
| app.providers.base.x_parse_strict_json__mutmut_6 | A | strip 字符集变体：花括号切片（第一个 { 到最后一个 }）兜底使围栏剥离对一切合法输入冗余，解析结果等价 | 函数契约（docstring）+ R5：切片兜底覆盖围栏场景；输出等价推理 |
| app.providers.base.x_parse_strict_json__mutmut_8 | A | "json" 标签→XX：花括号切片（第一个 { 到最后一个 }）兜底使围栏剥离对一切合法输入冗余，解析结果等价 | 函数契约（docstring）+ R5：切片兜底覆盖围栏场景；输出等价推理 |
| app.providers.base.x_parse_strict_json__mutmut_9 | A | "json"→"JSON"：花括号切片（第一个 { 到最后一个 }）兜底使围栏剥离对一切合法输入冗余，解析结果等价 | 函数契约（docstring）+ R5：切片兜底覆盖围栏场景；输出等价推理 |
| app.providers.base.x_parse_strict_json__mutmut_11 | A | t[4:]→t[5:]：花括号切片（第一个 { 到最后一个 }）兜底使围栏剥离对一切合法输入冗余，解析结果等价 | 函数契约（docstring）+ R5：切片兜底覆盖围栏场景；输出等价推理 |
| app.providers.base.x_parse_strict_json__mutmut_19 | A | 守卫 or→and：无花括号/边界输入仍以 JSONParseError 终止（经 JSONDecodeError 分支），异常类型不变、解析成功路径不变 | 调用方仅捕 JSONParseError；消息文案无条款 |
| app.providers.base.x_parse_strict_json__mutmut_23 | A | end <= start → end < start：边界（end==start）输入落 JSONDecodeError 分支，仍抛 JSONParseError，等价 | 同 m19 |
| app.providers.base.x_parse_strict_json__mutmut_24 | A | 「未找到 JSON 对象」消息→None：异常消息文案/截断细节，设计书无措辞条款 | A 类判据：异常消息文本（设计书未规定其措辞） |
| app.providers.base.x_parse_strict_json__mutmut_25 | A | 消息预览截断 [:200]→[:201]：异常消息文案/截断细节，设计书无措辞条款 | A 类判据：异常消息文本（设计书未规定其措辞） |
| app.providers.base.x_parse_strict_json__mutmut_30 | A | 「JSON 解析失败」消息→None：异常消息文案/截断细节，设计书无措辞条款 | A 类判据：异常消息文本（设计书未规定其措辞） |
| app.providers.base.x_parse_strict_json__mutmut_31 | A | 消息预览截断变体：异常消息文案/截断细节，设计书无措辞条款 | A 类判据：异常消息文本（设计书未规定其措辞） |
| app.providers.base.x_parse_strict_json__mutmut_33 | A | 「顶层不是对象」消息→None：异常消息文案/截断细节，设计书无措辞条款 | A 类判据：异常消息文本（设计书未规定其措辞） |
| app.providers.base.x_parse_strict_json__mutmut_34 | A | 同消息 XX 变体：异常消息文案/截断细节，设计书无措辞条款 | A 类判据：异常消息文本（设计书未规定其措辞） |
| app.providers.base.x_parse_strict_json__mutmut_35 | A | 同消息大小写变体：异常消息文案/截断细节，设计书无措辞条款 | A 类判据：异常消息文本（设计书未规定其措辞） |

## 批次 3：db / main / scheduler 薄弱带（2026-10-03，C1-2）

> 本批 126 条 = A 62 / B 0 / C 64 / D 0。C 类 64 条由 `tests/test_mutation_c1_2.py`
> 6 测试击杀（缺口根源：旧库升级路径此前无测试，现有测试只走新库 create_all），
> 不在本清单；D 类 0 条。A 类逐条如下；关键等价性均经 venv 内探针实证（非纯推理）：
> SQLite 标识符大小写不敏感、类型名任意（亲和性按子串判定）、关键字大小写不敏感、
> 日志格式化异常被 logging 自吞。生产引擎=SQLite（ADR-1），等价性按生产口径判定。

| mutant 全名 | 类别 | 一句话理由 | 依据条款或推理 |
|---|---|---|---|
| app.main.x_create_app__mutmut_4 | A | 移除 title 实参：同上 | 同 m2 |
| app.main.x_create_app__mutmut_5 | A | 移除 version="0.1.0" 实参：FastAPI 默认 version 恰为 "0.1.0"，精确等价 | 等价：FastAPI 签名默认值 |
| app.main.x_create_app__mutmut_6 | A | title "XXnewswright-demoXX"：同 m2 | 同 m2 |
| app.main.x_create_app__mutmut_7 | A | title 大写变体：同 m2 | 同 m2 |
| app.main.x_create_app__mutmut_8 | A | version "XX0.1.0XX"：同 m3 | 同 m2 |
| app.scheduler.x__reclaim_once__mutmut_5 | A | log.info(n)（msg 换实参）：同上 | 同 m3 |
| app.scheduler.x__reclaim_once__mutmut_6 | A | log.info 丢实参：同上 | 同 m3 |
| app.scheduler.x__reclaim_once__mutmut_7 | A | 日志文案 XX 包裹：同上 | 同 m3 |
| app.scheduler.x__reclaim_once__mutmut_8 | A | 日志文案 "FAILED"→"failed"：同上 | 同 m3 |

## 批次 4：ingest.web 定点监测带（2026-10-03，C1-3）

> 本批 210 条 = A 79 / B 0 / C 131 / D 0。C 类 131 条由 `tests/test_mutation_c1_3.py`
> 11 测试击杀（主链：304 短跳/条件头回传/条目全列/D15 指纹与 DUP/LLM 通道契约/
> 富化成本边界/sanitize 记账），不在本清单；D 类 0 条。A 类判据主轴：抽取形态与
> 请求头细节设计书未钉（任务书 §2 明示）、httpx 头名大小写归一化、SQLite 不强制
> 列宽（C1-2 生产口径）、_ingest 返回值全调用点不消费、现有 sanitizer 链不读 url。

| mutant 全名 | 类别 | 一句话理由 | 依据条款或推理 |
|---|---|---|---|
| app.ingest.web.x__content_hash__mutmut_4 | A | "utf-8"→"UTF-8"：Python codec 别名大小写不敏感，sha256 输出逐位一致（guid/变更检测语义不变） | AC-05.3 依赖哈希值本身——编解码别名恰等价 |
| app.ingest.web.x__html_title__mutmut_4 | A | 无题兜底 ""→"XXXX"：标题内容未钉 | 同上 |
| app.ingest.web.x__html_title__mutmut_11 | A | 空白折叠正则 XX 化（折叠失效）：标题空白形态未钉 | 同上 |
| app.ingest.web.x__published_date__mutmut_3 | A | original_date=True→None（=False）：单日期页面两种取值实测一致；多日期页面的取舍未钉 | 实测探针 + 任务书 §2 抽取细节 |
| app.ingest.web.x__published_date__mutmut_5 | A | 删 original_date 实参（=False）：同上 | 同上 |
| app.ingest.web.x__published_date__mutmut_6 | A | original_date=False 显式化：同上 | 同上 |
| app.ingest.web.x__published_date__mutmut_8 | A | tzinfo=timezone.utc→None（naive）：规则链对 naive/aware 双兼容（apply_rules 内补 tz），存储 tz 未钉（D16 仅钉日切口径） | D16 范围核查 + apply_rules 调用点核查 |
| app.ingest.web.x_extract_page_markdown__mutmut_1 | A | markdown 抽取置 None：纯文本回退兜底，抽取形态（markdown vs 纯文本）设计书未钉 | 任务书 §2「trafilatura 参数、markdown 形态未规定归 A」 |
| app.ingest.web.x_extract_page_markdown__mutmut_2 | A | extract(None)：异常被捕获走回退，正文形态未钉 | 同上 |
| app.ingest.web.x_extract_page_markdown__mutmut_3 | A | output_format=None：同上 | 同上 |
| app.ingest.web.x_extract_page_markdown__mutmut_4 | A | include_comments=None（假值）：同上 | 同上 |
| app.ingest.web.x_extract_page_markdown__mutmut_5 | A | include_tables=None（假值）：同上 | 同上 |
| app.ingest.web.x_extract_page_markdown__mutmut_6 | A | 删 html 实参（TypeError→回退）：同上 | 同上 |
| app.ingest.web.x_extract_page_markdown__mutmut_7 | A | 删 output_format（=txt 默认）：形态未钉 | 同上 |
| app.ingest.web.x_extract_page_markdown__mutmut_8 | A | 删 include_comments（=True 默认）：评论纳入与否形态未钉 | 同上 |
| app.ingest.web.x_extract_page_markdown__mutmut_9 | A | 删 include_tables（=True 默认）：表格纳入与否形态未钉 | 同上 |
| app.ingest.web.x_extract_page_markdown__mutmut_10 | A | "markdown"→"XXmarkdownXX"：非法格式异常→回退兜底 | 同上 |
| app.ingest.web.x_extract_page_markdown__mutmut_11 | A | "MARKDOWN" 大写变体：同上 | 同上 |
| app.ingest.web.x_extract_page_markdown__mutmut_12 | A | include_comments=True：形态未钉 | 同上 |
| app.ingest.web.x_extract_page_markdown__mutmut_13 | A | include_tables=True：形态未钉 | 同上 |
| app.ingest.web.x_extract_page_markdown__mutmut_14 | A | and→or：text=None 时 AttributeError 被 try 捕获走回退，结果等价 | 控制流等价推理 |
| app.ingest.web.x_extract_page_markdown__mutmut_15 | A | 回退路径 extract 置 None：最终返回 ""，正文形态未钉 | 同上 |
| app.ingest.web.x_extract_page_markdown__mutmut_16 | A | 回退 extract(None)：同上 | 同上 |
| app.ingest.web.x_extract_page_markdown__mutmut_17 | A | 回退 include_comments=None：同上 | 同上 |
| app.ingest.web.x_extract_page_markdown__mutmut_18 | A | 回退 include_tables=None：同上 | 同上 |
| app.ingest.web.x_extract_page_markdown__mutmut_19 | A | 回退删 html 实参：同上 | 同上 |
| app.ingest.web.x_extract_page_markdown__mutmut_20 | A | 回退删 include_comments：同上 | 同上 |
| app.ingest.web.x_extract_page_markdown__mutmut_21 | A | 回退删 include_tables：同上 | 同上 |
| app.ingest.web.x_extract_page_markdown__mutmut_22 | A | 回退 include_comments=True：同上 | 同上 |
| app.ingest.web.x_extract_page_markdown__mutmut_23 | A | 回退 include_tables=True：同上 | 同上 |
| app.ingest.web.x_extract_page_markdown__mutmut_24 | A | 回退 and→or：同 m14 | 同 m14 |
| app.ingest.web.x_extract_page_markdown__mutmut_25 | A | 双回退 ""→"XXXX"：四字符内容必被 too_short 规则拒绝（REJECTED 落行），防呆在设计链内；空内容兜底形态未钉 | 模块表 rules（too_short）+ AC-05.1 rule_rejected 桶 |
| app.ingest.web.x_fetch_web_source__mutmut_17 | A | ignore_page_date 置 None：键设计书全档无条款（grep 核查），仅影响未钉的页面日期抽取 | 设计书全文 grep 核查 |
| app.ingest.web.x_fetch_web_source__mutmut_18 | A | bool(None)：同上 | 同上 |
| app.ingest.web.x_fetch_web_source__mutmut_19 | A | cfg.get(None)：同上 | 同上 |
| app.ingest.web.x_fetch_web_source__mutmut_20 | A | 键 XX 变体：同上 | 同上 |
| app.ingest.web.x_fetch_web_source__mutmut_21 | A | 键大写变体：同上 | 同上 |
| app.ingest.web.x_fetch_web_source__mutmut_35 | A | If-Modified-Since 置 None：条件头回传未钉（模块表仅钉 etag 原样回传），断裂由 etag/哈希兜底 | 模块表 ingest/web 硬约束范围核查 |
| app.ingest.web.x_fetch_web_source__mutmut_36 | A | If-Modified-Since 键 XX 化：同上 | 同上 |
| app.ingest.web.x_fetch_web_source__mutmut_78 | A | last-modified 存储跳过（get 键 XX）：last_modified 回传/存储未钉，变更检测由 etag/哈希兜底 | 模块表硬约束范围核查 |
| app.ingest.web.x_fetch_web_source__mutmut_79 | A | get("LAST-MODIFIED")：httpx 大小写不敏感恰等价 | httpx.Headers 语义 |
| app.ingest.web.x_fetch_web_source__mutmut_82 | A | ["LAST-MODIFIED"]：httpx 大小写不敏感恰等价 | httpx.Headers 语义 |
| app.ingest.web.x_fetch_web_source__mutmut_83 | A | last_modified 截断 [:501]：同 m72 | 同 m72 |

## 批次 5：ingest.rss 主带 + 小模块 + C1-1 十三条 D 转 C（2026-10-03，C1-4）

> 本批种子 248 条（rss 199 + sanitize 18 + rules 10 + fingerprint 8 + providers 13
> 〔C1-1 拍板 D 转 C〕）四分类：**C 128 / A 115 / B 0 / D 5**。C 类由
> `tests/test_mutation_c1_4.py`（17 测试）+ 既有测试（test_url_dup /
> test_cross_direction_independent / C1-3 sanitize 链 / M3 parse）关闭；
> D 类 5 条不在本清单，交统筹（见 C1-4 执行汇报 §3）。以下登记 A 类 115 条。

| app.ingest.fingerprint.x_canonical_url__mutmut_11 | A | fragment 分量 ""→"XXXX"：结果随即流经 normalize_url 再剥 fragment，实测恰等价 | 控制流等价 + 实证 |
| app.ingest.fingerprint.x_find_fingerprint_origin__mutmut_7 | A | join(Source, None)：onclause=None 时 SQLAlchemy 依外键推断连接条件，恰等价 | SQLAlchemy 语义 |
| app.ingest.fingerprint.x_find_fingerprint_origin__mutmut_9 | A | join(Source, )：同 m7（尾逗号语法变体） | SQLAlchemy 语义 |
| app.ingest.fingerprint.x_url_fingerprint__mutmut_6 | A | encode("utf-8")→encode("UTF-8")：编解码别名，字节序列相同 | Python 编解码别名 |
| app.ingest.rss.x__entry_published__mutmut_6 | A | updated_parsed 槽位 get(None)：updated 回退取舍无条款（C1-3 _published_date 同域先例：日期形态未钉） | C1-3 先例 |
| app.ingest.rss.x__entry_published__mutmut_7 | A | updated 键 XX：同 m6 | 同 m6 |
| app.ingest.rss.x__entry_published__mutmut_8 | A | updated 键大写：同 m6 | 同 m6 |
| app.ingest.rss.x__entry_published__mutmut_13 | A | *st[:7]：第 7 位=tm_wday(0-6) 落入 datetime 第 7 参 microsecond 位——偏差 ≤6µs，不可观察 | 控制流等价 |
| app.ingest.rss.x__html_to_text__mutmut_1 | A | trafilatura.extract 置 None：抽取失败回退剥标签——正文抽取形态未钉（C1-3 明示先例：trafilatura 参数、markdown 形态未规定归 A） | C1-3 先例（形态未钉） |
| app.ingest.rss.x__html_to_text__mutmut_2 | A | extract(None)：同 m1 | 同 m1 |
| app.ingest.rss.x__html_to_text__mutmut_3 | A | include_comments=None：同 m1 | 同 m1 |
| app.ingest.rss.x__html_to_text__mutmut_4 | A | include_tables=None：同 m1 | 同 m1 |
| app.ingest.rss.x__html_to_text__mutmut_5 | A | extract 删 html 实参：同 m1（TypeError 被捕获回退） | 同 m1 |
| app.ingest.rss.x__html_to_text__mutmut_6 | A | 删 include_comments：同 m1（缺省值语义差异属形态未钉） | 同 m1 |
| app.ingest.rss.x__html_to_text__mutmut_7 | A | 删 include_tables：同 m1 | 同 m1 |
| app.ingest.rss.x__html_to_text__mutmut_8 | A | include_comments=True：同 m1 | 同 m1 |
| app.ingest.rss.x__html_to_text__mutmut_9 | A | include_tables=True：同 m1 | 同 m1 |
| app.ingest.rss.x__html_to_text__mutmut_10 | A | and→or：text=None 时 or 短路求值 text.strip() 抛 AttributeError 被 try 捕获回退——结果等价 | 控制流等价 |
| app.ingest.rss.x__html_to_text__mutmut_16 | A | 回退 _TAG_RE.sub("XX XX")：标签替换占位文本形态未钉（回退链尾部） | 同 m1 |
| app.ingest.rss.x__html_to_text__mutmut_23 | A | 回退 \s+ 正则 XX 化：空白折叠失效——文本形态未钉 | 同 m1 |
| app.ingest.rss.x__html_to_text__mutmut_24 | A | 回退替换串 "XX XX"：同 m16 | 同 m1 |
| app.ingest.rss.x_extract_entry_text__mutmut_1 | A | html 初值 None：content/summary 均缺时返回 ""（html 假值）——与初值 "" 行为等价 | 控制流等价 |
| app.ingest.rss.x_extract_entry_text__mutmut_2 | A | html 初值 "XXXX"：同 m1（content/summary 缺时返回 "XXXX"——正文空值形态无条款） | 无条款域核查 |
| app.ingest.rss.x_extract_entry_text__mutmut_3 | A | content 置 None：回退 summary——content 优先序无条款（模块表 rss 行未钉 entry 正文抽取链） | 抽取链无条款核查 |
| app.ingest.rss.x_extract_entry_text__mutmut_4 | A | content 键 get(None)：同 m3 | 同 m3 |
| app.ingest.rss.x_extract_entry_text__mutmut_5 | A | content 键 XX：同 m3 | 同 m3 |
| app.ingest.rss.x_extract_entry_text__mutmut_6 | A | content 键大写：同 m3 | 同 m3 |
| app.ingest.rss.x_extract_entry_text__mutmut_8 | A | and→or：content 为非 list 真值（dict）时 content[0] KeyError——差异域=畸形 entry（形态无条款），正常 feed 恰等价 | 无条款域核查 |
| app.ingest.rss.x_extract_entry_text__mutmut_9 | A | content[0].get(None)：value 键探测 None——content[0] 无 value 键时行为差异域=畸形 entry（无条款） | 同上 |
| app.ingest.rss.x_extract_entry_text__mutmut_10 | A | 探测 content[1]：单元素 content 时探测失败走 summary——content 多元素形态无条款 | 同上 |
| app.ingest.rss.x_extract_entry_text__mutmut_11 | A | value 键探测 XX：同 m3 域（content→summary 回退） | 同 m3 |
| app.ingest.rss.x_extract_entry_text__mutmut_12 | A | value 键探测大写：同 m3 | 同 m3 |
| app.ingest.rss.x_extract_entry_text__mutmut_13 | A | html=content[0]["value"] 置 None：content 存在时返回 ""——正文抽取形态无条款 | 抽取链无条款核查 |
| app.ingest.rss.x_extract_entry_text__mutmut_14 | A | content[1]["value"]：同 m10 域（多元素形态无条款） | 同 m10 |
| app.ingest.rss.x_extract_entry_text__mutmut_15 | A | 取值键 XX：同 m3 域（KeyError 不可达——探测已失败走 else） | 控制流等价 |
| app.ingest.rss.x_extract_entry_text__mutmut_16 | A | 取值键大写：同 m15 | 同 m15 |
| app.ingest.rss.x_extract_entry_text__mutmut_18 | A | summary or description and ""：差异域=summary 缺而 description 在（返回 description——原实现亦然？核：a or (b and "")——summary 缺→None or (desc and "")→"" vs 原 desc）——仅 description 独存条目正文为空，形态无条款 | 无条款域核查 |
| app.ingest.rss.x_extract_entry_text__mutmut_19 | A | summary and description or ""：差异域=summary 缺而 description 在（变异返回 description）——同 m18 域 | 同上 |
| app.ingest.rss.x_extract_entry_text__mutmut_20 | A | summary 键 get(None)：同 m3 域 | 同 m3 |
| app.ingest.rss.x_extract_entry_text__mutmut_21 | A | summary 键 XX：同 m3 域 | 同 m3 |
| app.ingest.rss.x_extract_entry_text__mutmut_22 | A | summary 键大写：同 m3 域 | 同 m3 |
| app.ingest.rss.x_extract_entry_text__mutmut_23 | A | description 键 get(None)：同 m3 域 | 同 m3 |
| app.ingest.rss.x_extract_entry_text__mutmut_24 | A | description 键 XX：同 m3 域 | 同 m3 |
| app.ingest.rss.x_extract_entry_text__mutmut_25 | A | description 键大写：同 m3 域 | 同 m3 |
| app.ingest.rss.x_extract_entry_text__mutmut_26 | A | or "XXXX"：content/summary 全缺条目正文 "XXXX"——正文空值形态无条款 | 无条款域核查 |
| app.ingest.rss.x_extract_entry_text__mutmut_28 | A | if (html) or True：html 空时 _html_to_text("") 返回 ""——恰等价 | 控制流等价 |
| app.ingest.rss.x_extract_entry_text__mutmut_30 | A | else "XXXX"：同 m26 | 同 m26 |
| app.ingest.rss.x_fetch_source__mutmut_122 | A | SanitizeTarget(url=None)：现有链（passthrough/KeywordDeny）不读 url 字段（C1-3 m187 先例） | sanitize.py 调用点核查 |
| app.ingest.rss.x_normalize_guid__mutmut_3 | A | and→or（id or (link and link_alt)）：差异域=link 与 link_alt 同在时取 link_alt——link_alt 优先序无条款（既有测试仅钉 id>link） | 同上 |
| app.ingest.rss.x_normalize_guid__mutmut_8 | A | link 槽位 entry.get(None)：有 id 或无 link_alt 时经回退分支恰等价；差异域同 m3 | 同上 |
| app.ingest.rss.x_normalize_guid__mutmut_9 | A | link 槽位键 XX：同 m8 | 同上 |
| app.ingest.rss.x_normalize_guid__mutmut_10 | A | link 槽位键大写：同 m8 | 同上 |
| app.ingest.rss.x_normalize_guid__mutmut_11 | A | link_alt 槽位 entry.get(None)：仅 link_alt-only 条目差异（无条款） | B4 链范围核查 |
| app.ingest.rss.x_normalize_guid__mutmut_12 | A | link_alt 槽位键 XX：同 m11 | 同上 |
| app.ingest.rss.x_normalize_guid__mutmut_13 | A | link_alt 槽位键大写：同 m11 | 同上 |
| app.ingest.rss.x_normalize_guid__mutmut_24 | A | 回退 entry.get("link") and ""：同 m23（回退域内恰等价） | 同 m23 |
| app.ingest.rss.x_normalize_guid__mutmut_25 | A | 回退 entry.get(None) or ""：同 m23 | 同 m23 |
| app.ingest.rss.x_normalize_guid__mutmut_26 | A | 回退键 XX：同 m23 | 同 m23 |
| app.ingest.rss.x_normalize_guid__mutmut_27 | A | 回退键大写：同 m23 | 同 m23 |
| app.ingest.rss.x_normalize_guid__mutmut_28 | A | 回退 or "XXXX"：同 m14（bogus guid 形态无条款） | 同 m14 |
| app.ingest.rss.x_normalize_url__mutmut_7 | A | keep_blank_values=None（缺省 False）：空白值查询参数保留与否——归一化微差，无条款（任务书 §2「无条款的归一化微差归 A」） | 归一化条款范围核查 |
| app.ingest.rss.x_normalize_url__mutmut_9 | A | keep_blank_values 实参删除：同 m7 | 同 m7 |
| app.ingest.rss.x_normalize_url__mutmut_10 | A | keep_blank_values=False：同 m7 | 同 m7 |
| app.ingest.rss.x_parse_feed_entries__mutmut_24 | A | url or "XXXX"：缺 link 条目 url "XXXX"——url 空值形态无条款（注：feedparser 对可回填 guid 会注入 link，差异域=不可回填 guid 条目） | 无条款域核查 |
| app.ingest.sanitize.x_run_sanitize__mutmut_2 | A | last_pass 初值 None：初值仅在链为空时返回——build_chain 恒返回非空链（至少 passthrough 一项），循环体必覆写，不可达 | 控制流推理（build_chain 全分支核查） |
| app.ingest.sanitize.x_run_sanitize__mutmut_3 | A | 同 m2（passed=None 形态） | 同 m2 |
| app.ingest.sanitize.x_run_sanitize__mutmut_4 | A | 同 m2（reason=None 形态） | 同 m2 |
| app.ingest.sanitize.x_run_sanitize__mutmut_6 | A | 同 m2（reason 缺省形态） | 同 m2 |
| app.ingest.sanitize.x_run_sanitize__mutmut_7 | A | 同 m2（passed=False 形态） | 同 m2 |
| app.ingest.sanitize.x_run_sanitize__mutmut_8 | A | 同 m2（reason XX 形态） | 同 m2 |
| app.ingest.sanitize.x_run_sanitize__mutmut_9 | A | 同 m2（reason 大写形态） | 同 m2 |
| app.ingest.sanitize.xǁKeywordDenySanitizerǁcheck__mutmut_3 | A | REJECT 结果 passed=None：run_sanitize 与全部调用点按真值判断（not result.passed / if sr.passed），行为等价 | 调用点核查 |
| app.providers.base.xǁHTTPProviderǁ__init____mutmut_12 | A | 键 "content-type" 小写：同 m9 | httpx.Headers 实证 |
| app.providers.base.xǁHTTPProviderǁ__init____mutmut_13 | A | 键 "CONTENT-TYPE" 大写：同 m9 | httpx.Headers 实证 |
## 批次 6：authors.pipeline 执行器核心 PipelineRunner（2026-10-03，C1-5a）

> 种子 580 条四分类：**C 273 / A 307 / B 0 / D 0**。C 类由 `tests/test_mutation_c1_5a.py`
> 27 测试关闭（断言引 AC-11.1/11.2/11.4/12.1/12.3、DT-4、US-10 schema 契约、ADR-8、
> §4.1 write_run、§4.4 记忆回流、搭建记录纪律）；本小节只登记 307 条 A 类。
> D 类变异 0 条；另有两项非变异类设计观察（DT-4 空阅读集 SKIP 语义 vs 实现 FAILED、
> R6 同因早停未实现）见 C1-5a 执行汇报 §3。

| mutant 全名 | 类别 | 一句话理由 | 依据条款或推理 |
|---|---|---|---|
| app.authors.pipeline.xǁPipelineRunnerǁ__init____mutmut_7 | A | cost 初值 1：payload.cost 键未钉（§4.1 write_run payload 仅钉 trace/static_injection/rank），cost 聚合账非设计书条款面 | §4.1 write_run 行核查 |
| app.authors.pipeline.xǁPipelineRunnerǁ__init____mutmut_10 | A | cost 初值 1：payload.cost 键未钉（§4.1 write_run payload 仅钉 trace/static_injection/rank），cost 聚合账非设计书条款面 | §4.1 write_run 行核查 |
| app.authors.pipeline.xǁPipelineRunnerǁ_max_tokens__mutmut_14 | A | NODE_MAX_TOKENS 覆盖全部节点名，缺省参数不可达 | 控制流等价（调用点核查） |
| app.authors.pipeline.xǁPipelineRunnerǁ_max_tokens__mutmut_16 | A | NODE_MAX_TOKENS 覆盖全部节点名，缺省参数不可达 | 控制流等价（调用点核查） |
| app.authors.pipeline.xǁPipelineRunnerǁ_call__mutmut_2 | A | temperature 缺省 0.5→1.5：全部调用点显式传参，缺省不可达 | 调用点核查 |
| app.authors.pipeline.xǁPipelineRunnerǁ_call__mutmut_24 | A | _max_tokens 第二参缺省不可达（NODE_MAX_TOKENS 覆盖全部节点） | 控制流等价 |
| app.authors.pipeline.xǁPipelineRunnerǁ_call__mutmut_27 | A | _max_tokens 第二参缺省不可达（NODE_MAX_TOKENS 覆盖全部节点） | 控制流等价 |
| app.authors.pipeline.xǁPipelineRunnerǁ_call__mutmut_37 | A | fallback_note trace 字段未钉（记录位置/键名无条款） | §4.1 字段范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁ_call__mutmut_38 | A | fallback_note trace 字段未钉（记录位置/键名无条款） | §4.1 字段范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁ_call__mutmut_39 | A | fallback_note trace 字段未钉（记录位置/键名无条款） | §4.1 字段范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁ_call__mutmut_43 | A | fallback_note trace 字段未钉（记录位置/键名无条款） | §4.1 字段范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁ_call__mutmut_44 | A | fallback_note trace 字段未钉（记录位置/键名无条款） | §4.1 字段范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁ_call__mutmut_45 | A | fallback_note trace 字段未钉（记录位置/键名无条款） | §4.1 字段范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁ_call__mutmut_48 | A | input_digest trace 字段未钉（摘要形态/截断长度无条款） | §4.1 字段范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁ_call__mutmut_49 | A | input_digest trace 字段未钉（摘要形态/截断长度无条款） | §4.1 字段范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁ_call__mutmut_50 | A | input_digest trace 字段未钉（摘要形态/截断长度无条款） | §4.1 字段范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁ_call__mutmut_51 | A | input_digest trace 字段未钉（摘要形态/截断长度无条款） | §4.1 字段范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁ_call__mutmut_52 | A | input_digest trace 字段未钉（摘要形态/截断长度无条款） | §4.1 字段范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁ_call__mutmut_55 | A | input_digest trace 字段未钉（摘要形态/截断长度无条款） | §4.1 字段范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁ_call__mutmut_56 | A | input_digest trace 字段未钉（摘要形态/截断长度无条款） | §4.1 字段范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁ_call__mutmut_77 | A | cache_hit_tokens trace 字段未钉 | §4.1 字段范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁ_call__mutmut_78 | A | cache_hit_tokens trace 字段未钉 | §4.1 字段范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁ_call__mutmut_79 | A | cache_hit_tokens trace 字段未钉 | §4.1 字段范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁ_call__mutmut_80 | A | cache_hit_tokens trace 字段未钉 | §4.1 字段范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁ_call__mutmut_81 | A | cache_hit_tokens trace 字段未钉 | §4.1 字段范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁ_call__mutmut_82 | A | cache_hit_tokens trace 字段未钉 | §4.1 字段范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁ_call__mutmut_83 | A | cache_hit_tokens trace 字段未钉 | §4.1 字段范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁ_call__mutmut_84 | A | cache_hit_tokens trace 字段未钉 | §4.1 字段范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁ_call__mutmut_85 | A | cache_hit_tokens trace 字段未钉 | §4.1 字段范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁ_call__mutmut_86 | A | reasoning_tokens trace 字段未钉 | §4.1 字段范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁ_call__mutmut_87 | A | reasoning_tokens trace 字段未钉 | §4.1 字段范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁ_call__mutmut_88 | A | reasoning_tokens trace 字段未钉 | §4.1 字段范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁ_call__mutmut_89 | A | reasoning_tokens trace 字段未钉 | §4.1 字段范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁ_call__mutmut_90 | A | reasoning_tokens trace 字段未钉 | §4.1 字段范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁ_call__mutmut_91 | A | reasoning_tokens trace 字段未钉 | §4.1 字段范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁ_call__mutmut_92 | A | reasoning_tokens trace 字段未钉 | §4.1 字段范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁ_call__mutmut_93 | A | reasoning_tokens trace 字段未钉 | §4.1 字段范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁ_call__mutmut_94 | A | reasoning_tokens trace 字段未钉 | §4.1 字段范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁ_call__mutmut_95 | A | finish_reason trace 字段未钉 | §4.1 字段范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁ_call__mutmut_96 | A | finish_reason trace 字段未钉 | §4.1 字段范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁ_call__mutmut_97 | A | finish_reason trace 字段未钉 | §4.1 字段范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁ_call__mutmut_98 | A | finish_reason trace 字段未钉 | §4.1 字段范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁ_call__mutmut_99 | A | finish_reason trace 字段未钉 | §4.1 字段范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁ_call__mutmut_100 | A | latency_ms trace 字段未钉（NFR 引 usage_log.latency_ms 非 trace） | §4.1 字段范围核查 + NFR 表 |
| app.authors.pipeline.xǁPipelineRunnerǁ_call__mutmut_101 | A | latency_ms trace 字段未钉（NFR 引 usage_log.latency_ms 非 trace） | §4.1 字段范围核查 + NFR 表 |
| app.authors.pipeline.xǁPipelineRunnerǁ_call__mutmut_103 | A | latency_ms trace 字段未钉（NFR 引 usage_log.latency_ms 非 trace） | §4.1 字段范围核查 + NFR 表 |
| app.authors.pipeline.xǁPipelineRunnerǁ_call__mutmut_104 | A | latency_ms trace 字段未钉（NFR 引 usage_log.latency_ms 非 trace） | §4.1 字段范围核查 + NFR 表 |
| app.authors.pipeline.xǁPipelineRunnerǁ_call__mutmut_105 | A | latency_ms trace 字段未钉（NFR 引 usage_log.latency_ms 非 trace） | §4.1 字段范围核查 + NFR 表 |
| app.authors.pipeline.xǁPipelineRunnerǁ_call__mutmut_106 | A | at trace 字段未钉（时间戳形态/tz 无条款） | §4.1 字段范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁ_call__mutmut_107 | A | at trace 字段未钉（时间戳形态/tz 无条款） | §4.1 字段范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁ_call__mutmut_109 | A | at trace 字段未钉（时间戳形态/tz 无条款） | §4.1 字段范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁ_call__mutmut_113 | A | cost 聚合账未钉（payload.cost 键不在 §4.1 钉面） | §4.1 write_run 行核查 |
| app.authors.pipeline.xǁPipelineRunnerǁ_call__mutmut_114 | A | cost 聚合账未钉（payload.cost 键不在 §4.1 钉面） | §4.1 write_run 行核查 |
| app.authors.pipeline.xǁPipelineRunnerǁ_call__mutmut_119 | A | cost 聚合账未钉（payload.cost 键不在 §4.1 钉面） | §4.1 write_run 行核查 |
| app.authors.pipeline.xǁPipelineRunnerǁ_call__mutmut_120 | A | cost 聚合账未钉（payload.cost 键不在 §4.1 钉面） | §4.1 write_run 行核查 |
| app.authors.pipeline.xǁPipelineRunnerǁ_flush__mutmut_4 | A | payload cost 键未钉 | §4.1 write_run 行核查 |
| app.authors.pipeline.xǁPipelineRunnerǁ_flush__mutmut_5 | A | payload cost 键未钉 | §4.1 write_run 行核查 |
| app.authors.pipeline.xǁPipelineRunnerǁrun_gates__mutmut_61 | A | style_anchor 缺省参数（None/""）——键缺省时两值同为假值、gate_echo_check 早退，恰等价 | 控制流等价（gate_echo_check if not anchor 早退核查） |
| app.authors.pipeline.xǁPipelineRunnerǁrun_gates__mutmut_63 | A | style_anchor 缺省参数（None/""）——键缺省时两值同为假值、gate_echo_check 早退，恰等价 | 控制流等价（gate_echo_check if not anchor 早退核查） |
| app.authors.pipeline.xǁPipelineRunnerǁrun_gates__mutmut_66 | A | anchor 缺省 ""→"XXXX" 缺省形态（无锚时门禁早退域，差异无条款） | 缺省形态无条款 |
| app.authors.pipeline.xǁPipelineRunnerǁrun_gates__mutmut_108 | A | recent_n 缺省 5→6 数值无条款 | 数值缺省无条款（任务书§2） |
| app.authors.pipeline.xǁPipelineRunnerǁrun_gates__mutmut_125 | A | threshold 缺省 0.55→1.55 数值无条款 | 数值缺省无条款 |
| app.authors.pipeline.xǁPipelineRunnerǁrun_gates__mutmut_147 | A | rhythm_stddev stats 字段未钉（stats 非 §4.1 钉面） | §4.1 字段范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁrun_gates__mutmut_148 | A | rhythm_stddev stats 字段未钉（stats 非 §4.1 钉面） | §4.1 字段范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁrun_gates__mutmut_149 | A | rhythm_stddev stats 字段未钉（stats 非 §4.1 钉面） | §4.1 字段范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁ_title__mutmut_4 | A | 标题提取规则细节（#/脚注标记清理/40 字阈值/句读截断/无题文案）无条款——§4.1 仅钉 title 列落值 | §4.1 title 列范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁ_title__mutmut_6 | A | 标题提取规则细节（#/脚注标记清理/40 字阈值/句读截断/无题文案）无条款——§4.1 仅钉 title 列落值 | §4.1 title 列范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁ_title__mutmut_12 | A | 标题提取规则细节（#/脚注标记清理/40 字阈值/句读截断/无题文案）无条款——§4.1 仅钉 title 列落值 | §4.1 title 列范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁ_title__mutmut_13 | A | 标题提取规则细节（#/脚注标记清理/40 字阈值/句读截断/无题文案）无条款——§4.1 仅钉 title 列落值 | §4.1 title 列范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁ_title__mutmut_14 | A | 标题提取规则细节（#/脚注标记清理/40 字阈值/句读截断/无题文案）无条款——§4.1 仅钉 title 列落值 | §4.1 title 列范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁ_title__mutmut_15 | A | 标题提取规则细节（#/脚注标记清理/40 字阈值/句读截断/无题文案）无条款——§4.1 仅钉 title 列落值 | §4.1 title 列范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁ_title__mutmut_16 | A | 标题提取规则细节（#/脚注标记清理/40 字阈值/句读截断/无题文案）无条款——§4.1 仅钉 title 列落值 | §4.1 title 列范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁ_title__mutmut_17 | A | 标题提取规则细节（#/脚注标记清理/40 字阈值/句读截断/无题文案）无条款——§4.1 仅钉 title 列落值 | §4.1 title 列范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁ_title__mutmut_18 | A | 标题提取规则细节（#/脚注标记清理/40 字阈值/句读截断/无题文案）无条款——§4.1 仅钉 title 列落值 | §4.1 title 列范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁ_title__mutmut_19 | A | 标题提取规则细节（#/脚注标记清理/40 字阈值/句读截断/无题文案）无条款——§4.1 仅钉 title 列落值 | §4.1 title 列范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁ_title__mutmut_20 | A | 标题提取规则细节（#/脚注标记清理/40 字阈值/句读截断/无题文案）无条款——§4.1 仅钉 title 列落值 | §4.1 title 列范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁ_title__mutmut_21 | A | 标题提取规则细节（#/脚注标记清理/40 字阈值/句读截断/无题文案）无条款——§4.1 仅钉 title 列落值 | §4.1 title 列范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁ_title__mutmut_22 | A | 标题提取规则细节（#/脚注标记清理/40 字阈值/句读截断/无题文案）无条款——§4.1 仅钉 title 列落值 | §4.1 title 列范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁ_title__mutmut_23 | A | 标题提取规则细节（#/脚注标记清理/40 字阈值/句读截断/无题文案）无条款——§4.1 仅钉 title 列落值 | §4.1 title 列范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁ_title__mutmut_24 | A | 标题提取规则细节（#/脚注标记清理/40 字阈值/句读截断/无题文案）无条款——§4.1 仅钉 title 列落值 | §4.1 title 列范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁ_title__mutmut_25 | A | 标题提取规则细节（#/脚注标记清理/40 字阈值/句读截断/无题文案）无条款——§4.1 仅钉 title 列落值 | §4.1 title 列范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁ_title__mutmut_26 | A | 标题提取规则细节（#/脚注标记清理/40 字阈值/句读截断/无题文案）无条款——§4.1 仅钉 title 列落值 | §4.1 title 列范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁ_title__mutmut_27 | A | 标题提取规则细节（#/脚注标记清理/40 字阈值/句读截断/无题文案）无条款——§4.1 仅钉 title 列落值 | §4.1 title 列范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁ_title__mutmut_28 | A | 标题提取规则细节（#/脚注标记清理/40 字阈值/句读截断/无题文案）无条款——§4.1 仅钉 title 列落值 | §4.1 title 列范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁnode_draft__mutmut_4 | A | _draft_task 实参（腹稿/规划/衔接段进提示词）——提示词拼装形态未钉 | 提示词形态（任务书§2） |
| app.authors.pipeline.xǁPipelineRunnerǁnode_draft__mutmut_5 | A | _draft_task 实参（腹稿/规划/衔接段进提示词）——提示词拼装形态未钉 | 提示词形态（任务书§2） |
| app.authors.pipeline.xǁPipelineRunnerǁnode_draft__mutmut_6 | A | _draft_task 实参（腹稿/规划/衔接段进提示词）——提示词拼装形态未钉 | 提示词形态（任务书§2） |
| app.authors.pipeline.xǁPipelineRunnerǁnode_draft__mutmut_7 | A | _draft_task 实参（腹稿/规划/衔接段进提示词）——提示词拼装形态未钉 | 提示词形态（任务书§2） |
| app.authors.pipeline.xǁPipelineRunnerǁnode_draft__mutmut_10 | A | _draft_task 实参（腹稿/规划/衔接段进提示词）——提示词拼装形态未钉 | 提示词形态（任务书§2） |
| app.authors.pipeline.xǁPipelineRunnerǁnode_draft__mutmut_11 | A | _draft_task 实参（腹稿/规划/衔接段进提示词）——提示词拼装形态未钉 | 提示词形态（任务书§2） |
| app.authors.pipeline.xǁPipelineRunnerǁnode_draft__mutmut_12 | A | _draft_task 实参（腹稿/规划/衔接段进提示词）——提示词拼装形态未钉 | 提示词形态（任务书§2） |
| app.authors.pipeline.xǁPipelineRunnerǁnode_draft__mutmut_13 | A | _draft_task 实参（腹稿/规划/衔接段进提示词）——提示词拼装形态未钉 | 提示词形态（任务书§2） |
| app.authors.pipeline.xǁPipelineRunnerǁnode_draft__mutmut_29 | A | user_ctx+task 拼接符变形——措辞 | 提示词形态 |
| app.authors.pipeline.xǁPipelineRunnerǁnode_draft__mutmut_33 | A | temperature 0.9 数值无条款 | 数值无条款 |
| app.authors.pipeline.xǁPipelineRunnerǁnode_draft__mutmut_36 | A | temperature 0.9 数值无条款 | 数值无条款 |
| app.authors.pipeline.xǁPipelineRunnerǁnode_draft__mutmut_39 | A | temperature 0.9 数值无条款 | 数值无条款 |
| app.authors.pipeline.xǁPipelineRunnerǁnode_draft__mutmut_41 | A | discarded 标记键/值形态未钉（trace 字段内部形态） | §4.1 字段范围核查（任务书§2） |
| app.authors.pipeline.xǁPipelineRunnerǁnode_draft__mutmut_44 | A | discarded 标记键/值形态未钉（trace 字段内部形态） | §4.1 字段范围核查（任务书§2） |
| app.authors.pipeline.xǁPipelineRunnerǁnode_draft__mutmut_45 | A | discarded 标记键/值形态未钉（trace 字段内部形态） | §4.1 字段范围核查（任务书§2） |
| app.authors.pipeline.xǁPipelineRunnerǁnode_draft__mutmut_46 | A | discarded 标记键/值形态未钉（trace 字段内部形态） | §4.1 字段范围核查（任务书§2） |
| app.authors.pipeline.xǁPipelineRunnerǁnode_draft__mutmut_47 | A | discarded 标记键/值形态未钉（trace 字段内部形态） | §4.1 字段范围核查（任务书§2） |
| app.authors.pipeline.xǁPipelineRunnerǁnode_draft__mutmut_57 | A | note trace 字段未钉 | §4.1 字段范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁnode_draft__mutmut_60 | A | note trace 字段未钉 | §4.1 字段范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁnode_draft__mutmut_61 | A | note trace 字段未钉 | §4.1 字段范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁnode_draft__mutmut_62 | A | note trace 字段未钉 | §4.1 字段范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁnode_draft__mutmut_63 | A | note trace 字段未钉 | §4.1 字段范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁnode_draft__mutmut_67 | A | 重试调用 temperature 数值无条款 | 数值无条款 |
| app.authors.pipeline.xǁPipelineRunnerǁnode_draft__mutmut_70 | A | 重试调用 temperature 数值无条款 | 数值无条款 |
| app.authors.pipeline.xǁPipelineRunnerǁnode_draft__mutmut_73 | A | 重试调用 temperature 数值无条款 | 数值无条款 |
| app.authors.pipeline.xǁPipelineRunnerǁnode_draft__mutmut_75 | A | 空稿中止文案未钉 | 文案无措辞条款 |
| app.authors.pipeline.xǁPipelineRunnerǁnode_draft__mutmut_76 | A | 空稿中止文案未钉 | 文案无措辞条款 |
| app.authors.pipeline.xǁPipelineRunnerǁnode_revise__mutmut_1 | A | 长度提示 note 提取与拼装（正则/lo/hi 值/方向话术）——全部为提示词措辞与未钉数值 | 提示词形态 + 数值无条款 |
| app.authors.pipeline.xǁPipelineRunnerǁnode_revise__mutmut_2 | A | 长度提示 note 提取与拼装（正则/lo/hi 值/方向话术）——全部为提示词措辞与未钉数值 | 提示词形态 + 数值无条款 |
| app.authors.pipeline.xǁPipelineRunnerǁnode_revise__mutmut_3 | A | 长度提示 note 提取与拼装（正则/lo/hi 值/方向话术）——全部为提示词措辞与未钉数值 | 提示词形态 + 数值无条款 |
| app.authors.pipeline.xǁPipelineRunnerǁnode_revise__mutmut_8 | A | 长度提示 note 提取与拼装（正则/lo/hi 值/方向话术）——全部为提示词措辞与未钉数值 | 提示词形态 + 数值无条款 |
| app.authors.pipeline.xǁPipelineRunnerǁnode_revise__mutmut_9 | A | 长度提示 note 提取与拼装（正则/lo/hi 值/方向话术）——全部为提示词措辞与未钉数值 | 提示词形态 + 数值无条款 |
| app.authors.pipeline.xǁPipelineRunnerǁnode_revise__mutmut_10 | A | 长度提示 note 提取与拼装（正则/lo/hi 值/方向话术）——全部为提示词措辞与未钉数值 | 提示词形态 + 数值无条款 |
| app.authors.pipeline.xǁPipelineRunnerǁnode_revise__mutmut_11 | A | 长度提示 note 提取与拼装（正则/lo/hi 值/方向话术）——全部为提示词措辞与未钉数值 | 提示词形态 + 数值无条款 |
| app.authors.pipeline.xǁPipelineRunnerǁnode_revise__mutmut_12 | A | 长度提示 note 提取与拼装（正则/lo/hi 值/方向话术）——全部为提示词措辞与未钉数值 | 提示词形态 + 数值无条款 |
| app.authors.pipeline.xǁPipelineRunnerǁnode_revise__mutmut_13 | A | 长度提示 note 提取与拼装（正则/lo/hi 值/方向话术）——全部为提示词措辞与未钉数值 | 提示词形态 + 数值无条款 |
| app.authors.pipeline.xǁPipelineRunnerǁnode_revise__mutmut_14 | A | 长度提示 note 提取与拼装（正则/lo/hi 值/方向话术）——全部为提示词措辞与未钉数值 | 提示词形态 + 数值无条款 |
| app.authors.pipeline.xǁPipelineRunnerǁnode_revise__mutmut_15 | A | 长度提示 note 提取与拼装（正则/lo/hi 值/方向话术）——全部为提示词措辞与未钉数值 | 提示词形态 + 数值无条款 |
| app.authors.pipeline.xǁPipelineRunnerǁnode_revise__mutmut_20 | A | 长度提示 note 提取与拼装（正则/lo/hi 值/方向话术）——全部为提示词措辞与未钉数值 | 提示词形态 + 数值无条款 |
| app.authors.pipeline.xǁPipelineRunnerǁnode_revise__mutmut_21 | A | 长度提示 note 提取与拼装（正则/lo/hi 值/方向话术）——全部为提示词措辞与未钉数值 | 提示词形态 + 数值无条款 |
| app.authors.pipeline.xǁPipelineRunnerǁnode_revise__mutmut_22 | A | 长度提示 note 提取与拼装（正则/lo/hi 值/方向话术）——全部为提示词措辞与未钉数值 | 提示词形态 + 数值无条款 |
| app.authors.pipeline.xǁPipelineRunnerǁnode_revise__mutmut_23 | A | 长度提示 note 提取与拼装（正则/lo/hi 值/方向话术）——全部为提示词措辞与未钉数值 | 提示词形态 + 数值无条款 |
| app.authors.pipeline.xǁPipelineRunnerǁnode_revise__mutmut_24 | A | 长度提示 note 提取与拼装（正则/lo/hi 值/方向话术）——全部为提示词措辞与未钉数值 | 提示词形态 + 数值无条款 |
| app.authors.pipeline.xǁPipelineRunnerǁnode_revise__mutmut_25 | A | 长度提示 note 提取与拼装（正则/lo/hi 值/方向话术）——全部为提示词措辞与未钉数值 | 提示词形态 + 数值无条款 |
| app.authors.pipeline.xǁPipelineRunnerǁnode_revise__mutmut_26 | A | 长度提示 note 提取与拼装（正则/lo/hi 值/方向话术）——全部为提示词措辞与未钉数值 | 提示词形态 + 数值无条款 |
| app.authors.pipeline.xǁPipelineRunnerǁnode_revise__mutmut_27 | A | 长度提示 note 提取与拼装（正则/lo/hi 值/方向话术）——全部为提示词措辞与未钉数值 | 提示词形态 + 数值无条款 |
| app.authors.pipeline.xǁPipelineRunnerǁnode_revise__mutmut_28 | A | 长度提示 note 提取与拼装（正则/lo/hi 值/方向话术）——全部为提示词措辞与未钉数值 | 提示词形态 + 数值无条款 |
| app.authors.pipeline.xǁPipelineRunnerǁnode_revise__mutmut_29 | A | 长度提示 note 提取与拼装（正则/lo/hi 值/方向话术）——全部为提示词措辞与未钉数值 | 提示词形态 + 数值无条款 |
| app.authors.pipeline.xǁPipelineRunnerǁnode_revise__mutmut_30 | A | 长度提示 note 提取与拼装（正则/lo/hi 值/方向话术）——全部为提示词措辞与未钉数值 | 提示词形态 + 数值无条款 |
| app.authors.pipeline.xǁPipelineRunnerǁnode_revise__mutmut_31 | A | 长度提示 note 提取与拼装（正则/lo/hi 值/方向话术）——全部为提示词措辞与未钉数值 | 提示词形态 + 数值无条款 |
| app.authors.pipeline.xǁPipelineRunnerǁnode_revise__mutmut_36 | A | 长度提示 note 提取与拼装（正则/lo/hi 值/方向话术）——全部为提示词措辞与未钉数值 | 提示词形态 + 数值无条款 |
| app.authors.pipeline.xǁPipelineRunnerǁnode_revise__mutmut_37 | A | 长度提示 note 提取与拼装（正则/lo/hi 值/方向话术）——全部为提示词措辞与未钉数值 | 提示词形态 + 数值无条款 |
| app.authors.pipeline.xǁPipelineRunnerǁnode_revise__mutmut_38 | A | 长度提示 note 提取与拼装（正则/lo/hi 值/方向话术）——全部为提示词措辞与未钉数值 | 提示词形态 + 数值无条款 |
| app.authors.pipeline.xǁPipelineRunnerǁnode_revise__mutmut_39 | A | 长度提示 note 提取与拼装（正则/lo/hi 值/方向话术）——全部为提示词措辞与未钉数值 | 提示词形态 + 数值无条款 |
| app.authors.pipeline.xǁPipelineRunnerǁnode_revise__mutmut_40 | A | 长度提示 note 提取与拼装（正则/lo/hi 值/方向话术）——全部为提示词措辞与未钉数值 | 提示词形态 + 数值无条款 |
| app.authors.pipeline.xǁPipelineRunnerǁnode_revise__mutmut_41 | A | 长度提示 note 提取与拼装（正则/lo/hi 值/方向话术）——全部为提示词措辞与未钉数值 | 提示词形态 + 数值无条款 |
| app.authors.pipeline.xǁPipelineRunnerǁnode_revise__mutmut_43 | A | 长度提示 note 提取与拼装（正则/lo/hi 值/方向话术）——全部为提示词措辞与未钉数值 | 提示词形态 + 数值无条款 |
| app.authors.pipeline.xǁPipelineRunnerǁnode_revise__mutmut_44 | A | 长度提示 note 提取与拼装（正则/lo/hi 值/方向话术）——全部为提示词措辞与未钉数值 | 提示词形态 + 数值无条款 |
| app.authors.pipeline.xǁPipelineRunnerǁnode_revise__mutmut_45 | A | 长度提示 note 提取与拼装（正则/lo/hi 值/方向话术）——全部为提示词措辞与未钉数值 | 提示词形态 + 数值无条款 |
| app.authors.pipeline.xǁPipelineRunnerǁnode_revise__mutmut_46 | A | 长度提示 note 提取与拼装（正则/lo/hi 值/方向话术）——全部为提示词措辞与未钉数值 | 提示词形态 + 数值无条款 |
| app.authors.pipeline.xǁPipelineRunnerǁnode_revise__mutmut_48 | A | 长度提示 note 提取与拼装（正则/lo/hi 值/方向话术）——全部为提示词措辞与未钉数值 | 提示词形态 + 数值无条款 |
| app.authors.pipeline.xǁPipelineRunnerǁnode_revise__mutmut_49 | A | 长度提示 note 提取与拼装（正则/lo/hi 值/方向话术）——全部为提示词措辞与未钉数值 | 提示词形态 + 数值无条款 |
| app.authors.pipeline.xǁPipelineRunnerǁnode_revise__mutmut_50 | A | 长度提示 note 提取与拼装（正则/lo/hi 值/方向话术）——全部为提示词措辞与未钉数值 | 提示词形态 + 数值无条款 |
| app.authors.pipeline.xǁPipelineRunnerǁnode_revise__mutmut_51 | A | 长度提示 note 提取与拼装（正则/lo/hi 值/方向话术）——全部为提示词措辞与未钉数值 | 提示词形态 + 数值无条款 |
| app.authors.pipeline.xǁPipelineRunnerǁnode_revise__mutmut_68 | A | 【要求】段措辞 | 提示词形态 |
| app.authors.pipeline.xǁPipelineRunnerǁnode_revise__mutmut_69 | A | 提示词内引用纪律段（min_count 进措辞/键变形）——门禁侧 min_count 已由 run_gates C 类覆盖 | 提示词形态 |
| app.authors.pipeline.xǁPipelineRunnerǁnode_revise__mutmut_73 | A | 提示词内引用纪律段（min_count 进措辞/键变形）——门禁侧 min_count 已由 run_gates C 类覆盖 | 提示词形态 |
| app.authors.pipeline.xǁPipelineRunnerǁnode_revise__mutmut_74 | A | 提示词内引用纪律段（min_count 进措辞/键变形）——门禁侧 min_count 已由 run_gates C 类覆盖 | 提示词形态 |
| app.authors.pipeline.xǁPipelineRunnerǁnode_revise__mutmut_75 | A | 提示词内引用纪律段（min_count 进措辞/键变形）——门禁侧 min_count 已由 run_gates C 类覆盖 | 提示词形态 |
| app.authors.pipeline.xǁPipelineRunnerǁnode_revise__mutmut_76 | A | 提示词内引用纪律段（min_count 进措辞/键变形）——门禁侧 min_count 已由 run_gates C 类覆盖 | 提示词形态 |
| app.authors.pipeline.xǁPipelineRunnerǁnode_revise__mutmut_77 | A | 提示词内引用纪律段（min_count 进措辞/键变形）——门禁侧 min_count 已由 run_gates C 类覆盖 | 提示词形态 |
| app.authors.pipeline.xǁPipelineRunnerǁnode_revise__mutmut_78 | A | 提示词内引用纪律段（min_count 进措辞/键变形）——门禁侧 min_count 已由 run_gates C 类覆盖 | 提示词形态 |
| app.authors.pipeline.xǁPipelineRunnerǁnode_revise__mutmut_83 | A | 提示词内引用纪律段（min_count 进措辞/键变形）——门禁侧 min_count 已由 run_gates C 类覆盖 | 提示词形态 |
| app.authors.pipeline.xǁPipelineRunnerǁnode_revise__mutmut_84 | A | 提示词内引用纪律段（min_count 进措辞/键变形）——门禁侧 min_count 已由 run_gates C 类覆盖 | 提示词形态 |
| app.authors.pipeline.xǁPipelineRunnerǁnode_revise__mutmut_85 | A | 提示词内引用纪律段（min_count 进措辞/键变形）——门禁侧 min_count 已由 run_gates C 类覆盖 | 提示词形态 |
| app.authors.pipeline.xǁPipelineRunnerǁnode_revise__mutmut_86 | A | 提示词内引用纪律段（min_count 进措辞/键变形）——门禁侧 min_count 已由 run_gates C 类覆盖 | 提示词形态 |
| app.authors.pipeline.xǁPipelineRunnerǁnode_revise__mutmut_87 | A | 提示词内引用纪律段（min_count 进措辞/键变形）——门禁侧 min_count 已由 run_gates C 类覆盖 | 提示词形态 |
| app.authors.pipeline.xǁPipelineRunnerǁnode_revise__mutmut_88 | A | 拼接符措辞 | 提示词形态 |
| app.authors.pipeline.xǁPipelineRunnerǁnode_revise__mutmut_92 | A | temperature 0.8 数值无条款 | 数值无条款 |
| app.authors.pipeline.xǁPipelineRunnerǁnode_revise__mutmut_95 | A | temperature 0.8 数值无条款 | 数值无条款 |
| app.authors.pipeline.xǁPipelineRunnerǁnode_revise__mutmut_98 | A | temperature 0.8 数值无条款 | 数值无条款 |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_23 | A | 【本期阅读集】段标题措辞 | 提示词形态 |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_73 | A | _slices_block head 调用 position 实参——head 与 else 分支输出恰等价 | 控制流等价 |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_96 | A | tail position 形态仅差尾随换行 | 提示词形态 |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_173 | A | rolling lo/hi 为死变量（赋值后无使用点）——等价 | 控制流等价（死代码） |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_175 | A | rolling lo/hi 为死变量（赋值后无使用点）——等价 | 控制流等价（死代码） |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_176 | A | rolling lo/hi 为死变量（赋值后无使用点）——等价 | 控制流等价（死代码） |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_180 | A | rolling lo/hi 为死变量（赋值后无使用点）——等价 | 控制流等价（死代码） |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_183 | A | rolling lo/hi 为死变量（赋值后无使用点）——等价 | 控制流等价（死代码） |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_184 | A | rolling lo/hi 为死变量（赋值后无使用点）——等价 | 控制流等价（死代码） |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_185 | A | rolling lo/hi 为死变量（赋值后无使用点）——等价 | 控制流等价（死代码） |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_186 | A | rolling lo/hi 为死变量（赋值后无使用点）——等价 | 控制流等价（死代码） |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_188 | A | rolling lo/hi 为死变量（赋值后无使用点）——等价 | 控制流等价（死代码） |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_189 | A | rolling lo/hi 为死变量（赋值后无使用点）——等价 | 控制流等价（死代码） |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_192 | A | rolling lo/hi 为死变量（赋值后无使用点）——等价 | 控制流等价（死代码） |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_193 | A | rolling lo/hi 为死变量（赋值后无使用点）——等价 | 控制流等价（死代码） |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_197 | A | rolling lo/hi 为死变量（赋值后无使用点）——等价 | 控制流等价（死代码） |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_200 | A | rolling lo/hi 为死变量（赋值后无使用点）——等价 | 控制流等价（死代码） |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_201 | A | rolling lo/hi 为死变量（赋值后无使用点）——等价 | 控制流等价（死代码） |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_202 | A | rolling lo/hi 为死变量（赋值后无使用点）——等价 | 控制流等价（死代码） |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_215 | A | rolling node_draft 提示词实参（规划/衔接段）——提示词形态 | 提示词形态 |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_216 | A | rolling node_draft 提示词实参（规划/衔接段）——提示词形态 | 提示词形态 |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_236 | A | 被后继 payload 写回遮蔽——终态恰等价 | 控制流等价（终态核查） |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_238 | A | 被后继 payload 写回遮蔽——终态恰等价 | 控制流等价（终态核查） |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_247 | A | prompt_snapshot 定界符内部形态未钉（§4.1 钉列存在+阅读集/切片可核，不钉分隔符） | §4.1 prompt_snapshot 范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_272 | A | pass_stats 写入目标/键形态未钉 | §4.1 字段范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_273 | A | pass_stats 写入目标/键形态未钉 | §4.1 字段范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_274 | A | pass_stats 写入目标/键形态未钉 | §4.1 字段范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_275 | A | pass_stats 写入目标/键形态未钉 | §4.1 字段范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_276 | A | pass_stats 写入目标/键形态未钉 | §4.1 字段范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_277 | A | pass_stats 数值/键形态未钉 | §4.1 字段范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_278 | A | pass_stats 数值/键形态未钉 | §4.1 字段范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_279 | A | pass_stats 数值/键形态未钉 | §4.1 字段范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_280 | A | pass_stats 数值/键形态未钉 | §4.1 字段范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_281 | A | pass_stats 数值/键形态未钉 | §4.1 字段范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_282 | A | pass_stats 数值/键形态未钉 | §4.1 字段范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_283 | A | pass_stats 数值/键形态未钉 | §4.1 字段范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_284 | A | pass_stats 数值/键形态未钉 | §4.1 字段范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_286 | A | pass_stats 数值/键形态未钉 | §4.1 字段范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_287 | A | pass_stats 数值/键形态未钉 | §4.1 字段范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_289 | A | pass_stats 数值/键形态未钉 | §4.1 字段范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_290 | A | pass_stats 数值/键形态未钉 | §4.1 字段范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_291 | A | pass_stats 数值/键形态未钉 | §4.1 字段范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_292 | A | pass_stats 数值/键形态未钉 | §4.1 字段范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_293 | A | pass_stats 数值/键形态未钉 | §4.1 字段范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_393 | A | payload rewrite/title 键形态未钉 | §4.1 字段范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_394 | A | payload rewrite/title 键形态未钉 | §4.1 字段范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_413 | A | audit_note 文案未钉 | 文案无措辞条款 |

## 批次 7：authors.pipeline 模块级函数（2026-10-03，C1-5b）

> 本批无 B 类、无 D 类变异。C 类 171 条（新增 130 + 既有测试闭合 41）由 `tests/test_mutation_c1_5b.py` 15 测试关闭（另 19 条由既有测试闭合），不在本清单。

| mutant 全名 | 类别 | 一句话理由 | 依据条款或推理 |
|---|---|---|---|
| app.authors.pipeline.x__citation_discipline__mutmut_1 | A | example 初始/sent next 缺省 None/省略——均 falsy 被 if sent 短路跳过示例构造，恰等价（2=XXXX 措辞） | 控制流等价 + 措辞 |
| app.authors.pipeline.x__citation_discipline__mutmut_10 | A | example 初始/sent next 缺省 None/省略——均 falsy 被 if sent 短路跳过示例构造，恰等价（2=XXXX 措辞） | 控制流等价 + 措辞 |
| app.authors.pipeline.x__citation_discipline__mutmut_16 | A | 分句正则/阈值/内容读取变体——动态示例文本形态 | 提示词形态（C1-5a：引用纪律段归 A） |
| app.authors.pipeline.x__citation_discipline__mutmut_17 | A | 分句正则/阈值/内容读取变体——动态示例文本形态 | 提示词形态（C1-5a：引用纪律段归 A） |
| app.authors.pipeline.x__citation_discipline__mutmut_18 | A | 分句正则/阈值/内容读取变体——动态示例文本形态 | 提示词形态（C1-5a：引用纪律段归 A） |
| app.authors.pipeline.x__citation_discipline__mutmut_19 | A | 分句正则/阈值/内容读取变体——动态示例文本形态 | 提示词形态（C1-5a：引用纪律段归 A） |
| app.authors.pipeline.x__citation_discipline__mutmut_2 | A | example 初始/sent next 缺省 None/省略——均 falsy 被 if sent 短路跳过示例构造，恰等价（2=XXXX 措辞） | 控制流等价 + 措辞 |
| app.authors.pipeline.x__citation_discipline__mutmut_20 | A | 分句正则/阈值/内容读取变体——动态示例文本形态 | 提示词形态（C1-5a：引用纪律段归 A） |
| app.authors.pipeline.x__citation_discipline__mutmut_21 | A | 分句正则/阈值/内容读取变体——动态示例文本形态 | 提示词形态（C1-5a：引用纪律段归 A） |
| app.authors.pipeline.x__citation_discipline__mutmut_22 | A | example 文本/截断变体——提示词措辞 | 提示词形态 |
| app.authors.pipeline.x__citation_discipline__mutmut_23 | A | example 文本/截断变体——提示词措辞 | 提示词形态 |
| app.authors.pipeline.x__citation_discipline__mutmut_24 | A | example 文本/截断变体——提示词措辞 | 提示词形态 |
| app.authors.pipeline.x__citation_discipline__mutmut_25 | A | example 文本/截断变体——提示词措辞 | 提示词形态 |
| app.authors.pipeline.x__citation_discipline__mutmut_26 | A | 可用条目 ID 串构造变体——提示词措辞 | 提示词形态 |
| app.authors.pipeline.x__citation_discipline__mutmut_28 | A | 可用条目 ID 串构造变体——提示词措辞 | 提示词形态 |
| app.authors.pipeline.x__citation_discipline__mutmut_29 | A | 可用条目 ID 串构造变体——提示词措辞 | 提示词形态 |
| app.authors.pipeline.x__citation_discipline__mutmut_6 | A | example 初始/sent next 缺省 None/省略——均 falsy 被 if sent 短路跳过示例构造，恰等价（2=XXXX 措辞） | 控制流等价 + 措辞 |
| app.authors.pipeline.x__citation_discipline__mutmut_8 | A | example 初始/sent next 缺省 None/省略——均 falsy 被 if sent 短路跳过示例构造，恰等价（2=XXXX 措辞） | 控制流等价 + 措辞 |
| app.authors.pipeline.x__draft_task__mutmut_10 | A | gates.length 读取旁路——仅影响提示词字数措辞（门禁侧已由 C1-5a 覆盖） | 提示词形态（C1-5a 先例：长度 note 归 A） |
| app.authors.pipeline.x__draft_task__mutmut_12 | A | length.get 变体/缺省 600/1400——输出格式段措辞 | 提示词形态（C1-5a 先例） |
| app.authors.pipeline.x__draft_task__mutmut_13 | A | length.get 变体/缺省 600/1400——输出格式段措辞 | 提示词形态（C1-5a 先例） |
| app.authors.pipeline.x__draft_task__mutmut_14 | A | length.get 变体/缺省 600/1400——输出格式段措辞 | 提示词形态（C1-5a 先例） |
| app.authors.pipeline.x__draft_task__mutmut_15 | A | length.get 变体/缺省 600/1400——输出格式段措辞 | 提示词形态（C1-5a 先例） |
| app.authors.pipeline.x__draft_task__mutmut_16 | A | length.get 变体/缺省 600/1400——输出格式段措辞 | 提示词形态（C1-5a 先例） |
| app.authors.pipeline.x__draft_task__mutmut_17 | A | length.get 变体/缺省 600/1400——输出格式段措辞 | 提示词形态（C1-5a 先例） |
| app.authors.pipeline.x__draft_task__mutmut_18 | A | length.get 变体/缺省 600/1400——输出格式段措辞 | 提示词形态（C1-5a 先例） |
| app.authors.pipeline.x__draft_task__mutmut_19 | A | length.get 变体/缺省 600/1400——输出格式段措辞 | 提示词形态（C1-5a 先例） |
| app.authors.pipeline.x__draft_task__mutmut_20 | A | length.get 变体/缺省 600/1400——输出格式段措辞 | 提示词形态（C1-5a 先例） |
| app.authors.pipeline.x__draft_task__mutmut_21 | A | length.get 变体/缺省 600/1400——输出格式段措辞 | 提示词形态（C1-5a 先例） |
| app.authors.pipeline.x__draft_task__mutmut_22 | A | length.get 变体/缺省 600/1400——输出格式段措辞 | 提示词形态（C1-5a 先例） |
| app.authors.pipeline.x__draft_task__mutmut_23 | A | length.get 变体/缺省 600/1400——输出格式段措辞 | 提示词形态（C1-5a 先例） |
| app.authors.pipeline.x__draft_task__mutmut_24 | A | length.get 变体/缺省 600/1400——输出格式段措辞 | 提示词形态（C1-5a 先例） |
| app.authors.pipeline.x__draft_task__mutmut_25 | A | length.get 变体/缺省 600/1400——输出格式段措辞 | 提示词形态（C1-5a 先例） |
| app.authors.pipeline.x__draft_task__mutmut_27 | A | citation min_count 读取/缺省变体——引用纪律段措辞（门禁侧 C1-5a 已覆盖） | 提示词形态（C1-5a 先例：引用纪律段归 A） |
| app.authors.pipeline.x__draft_task__mutmut_31 | A | citation min_count 读取/缺省变体——引用纪律段措辞（门禁侧 C1-5a 已覆盖） | 提示词形态（C1-5a 先例：引用纪律段归 A） |
| app.authors.pipeline.x__draft_task__mutmut_32 | A | citation min_count 读取/缺省变体——引用纪律段措辞（门禁侧 C1-5a 已覆盖） | 提示词形态（C1-5a 先例：引用纪律段归 A） |
| app.authors.pipeline.x__draft_task__mutmut_33 | A | citation min_count 读取/缺省变体——引用纪律段措辞（门禁侧 C1-5a 已覆盖） | 提示词形态（C1-5a 先例：引用纪律段归 A） |
| app.authors.pipeline.x__draft_task__mutmut_34 | A | citation min_count 读取/缺省变体——引用纪律段措辞（门禁侧 C1-5a 已覆盖） | 提示词形态（C1-5a 先例：引用纪律段归 A） |
| app.authors.pipeline.x__draft_task__mutmut_35 | A | citation min_count 读取/缺省变体——引用纪律段措辞（门禁侧 C1-5a 已覆盖） | 提示词形态（C1-5a 先例：引用纪律段归 A） |
| app.authors.pipeline.x__draft_task__mutmut_36 | A | citation min_count 读取/缺省变体——引用纪律段措辞（门禁侧 C1-5a 已覆盖） | 提示词形态（C1-5a 先例：引用纪律段归 A） |
| app.authors.pipeline.x__draft_task__mutmut_37 | A | citation min_count 读取/缺省变体——引用纪律段措辞（门禁侧 C1-5a 已覆盖） | 提示词形态（C1-5a 先例：引用纪律段归 A） |
| app.authors.pipeline.x__draft_task__mutmut_38 | A | citation min_count 读取/缺省变体——引用纪律段措辞（门禁侧 C1-5a 已覆盖） | 提示词形态（C1-5a 先例：引用纪律段归 A） |
| app.authors.pipeline.x__draft_task__mutmut_39 | A | citation min_count 读取/缺省变体——引用纪律段措辞（门禁侧 C1-5a 已覆盖） | 提示词形态（C1-5a 先例：引用纪律段归 A） |
| app.authors.pipeline.x__draft_task__mutmut_40 | A | citation min_count 读取/缺省变体——引用纪律段措辞（门禁侧 C1-5a 已覆盖） | 提示词形态（C1-5a 先例：引用纪律段归 A） |
| app.authors.pipeline.x__draft_task__mutmut_41 | A | citation min_count 读取/缺省变体——引用纪律段措辞（门禁侧 C1-5a 已覆盖） | 提示词形态（C1-5a 先例：引用纪律段归 A） |
| app.authors.pipeline.x__draft_task__mutmut_42 | A | task = 替换拼接——提示词段落组合形态 | 提示词形态（C1-5a 先例） |
| app.authors.pipeline.x__draft_task__mutmut_44 | A | task = 替换拼接——提示词段落组合形态 | 提示词形态（C1-5a 先例） |
| app.authors.pipeline.x__draft_task__mutmut_47 | A | 腹稿 json.dumps 形态/措辞变体 | 提示词形态 |
| app.authors.pipeline.x__draft_task__mutmut_48 | A | 腹稿 json.dumps 形态/措辞变体 | 提示词形态 |
| app.authors.pipeline.x__draft_task__mutmut_49 | A | 腹稿 json.dumps 形态/措辞变体 | 提示词形态 |
| app.authors.pipeline.x__draft_task__mutmut_50 | A | 腹稿 json.dumps 形态/措辞变体 | 提示词形态 |
| app.authors.pipeline.x__draft_task__mutmut_52 | A | 腹稿 json.dumps 形态/措辞变体 | 提示词形态 |
| app.authors.pipeline.x__draft_task__mutmut_53 | A | 腹稿 json.dumps 形态/措辞变体 | 提示词形态 |
| app.authors.pipeline.x__draft_task__mutmut_54 | A | 腹稿 json.dumps 形态/措辞变体 | 提示词形态 |
| app.authors.pipeline.x__draft_task__mutmut_55 | A | 腹稿 json.dumps 形态/措辞变体 | 提示词形态 |
| app.authors.pipeline.x__draft_task__mutmut_56 | A | outline or section——生产调用点 outline/section 恒成对或恒缺，异或组合不可达 | 调用点核查：node_draft/快照行 572 |
| app.authors.pipeline.x__draft_task__mutmut_62 | A | sections[i-2]——提示词内规划内容错位，行为仍按 JSON 序列 | 提示词形态（C1-5a：rolling 节间拼接符归 A） |
| app.authors.pipeline.x__draft_task__mutmut_63 | A | task = 替换拼接——提示词段落组合形态 | 提示词形态（C1-5a 先例） |
| app.authors.pipeline.x__draft_task__mutmut_65 | A | title/thesis/key/brief get 变体、XX 包裹、join 分隔符——提示词措辞 | 提示词形态（任务书 §2：措辞归 A） |
| app.authors.pipeline.x__draft_task__mutmut_66 | A | title/thesis/key/brief get 变体、XX 包裹、join 分隔符——提示词措辞 | 提示词形态（任务书 §2：措辞归 A） |
| app.authors.pipeline.x__draft_task__mutmut_67 | A | title/thesis/key/brief get 变体、XX 包裹、join 分隔符——提示词措辞 | 提示词形态（任务书 §2：措辞归 A） |
| app.authors.pipeline.x__draft_task__mutmut_68 | A | title/thesis/key/brief get 变体、XX 包裹、join 分隔符——提示词措辞 | 提示词形态（任务书 §2：措辞归 A） |
| app.authors.pipeline.x__draft_task__mutmut_69 | A | title/thesis/key/brief get 变体、XX 包裹、join 分隔符——提示词措辞 | 提示词形态（任务书 §2：措辞归 A） |
| app.authors.pipeline.x__draft_task__mutmut_7 | A | gates.length 读取旁路——仅影响提示词字数措辞（门禁侧已由 C1-5a 覆盖） | 提示词形态（C1-5a 先例：长度 note 归 A） |
| app.authors.pipeline.x__draft_task__mutmut_70 | A | title/thesis/key/brief get 变体、XX 包裹、join 分隔符——提示词措辞 | 提示词形态（任务书 §2：措辞归 A） |
| app.authors.pipeline.x__draft_task__mutmut_71 | A | title/thesis/key/brief get 变体、XX 包裹、join 分隔符——提示词措辞 | 提示词形态（任务书 §2：措辞归 A） |
| app.authors.pipeline.x__draft_task__mutmut_72 | A | title/thesis/key/brief get 变体、XX 包裹、join 分隔符——提示词措辞 | 提示词形态（任务书 §2：措辞归 A） |
| app.authors.pipeline.x__draft_task__mutmut_73 | A | title/thesis/key/brief get 变体、XX 包裹、join 分隔符——提示词措辞 | 提示词形态（任务书 §2：措辞归 A） |
| app.authors.pipeline.x__draft_task__mutmut_74 | A | title/thesis/key/brief get 变体、XX 包裹、join 分隔符——提示词措辞 | 提示词形态（任务书 §2：措辞归 A） |
| app.authors.pipeline.x__draft_task__mutmut_75 | A | title/thesis/key/brief get 变体、XX 包裹、join 分隔符——提示词措辞 | 提示词形态（任务书 §2：措辞归 A） |
| app.authors.pipeline.x__draft_task__mutmut_76 | A | title/thesis/key/brief get 变体、XX 包裹、join 分隔符——提示词措辞 | 提示词形态（任务书 §2：措辞归 A） |
| app.authors.pipeline.x__draft_task__mutmut_77 | A | title/thesis/key/brief get 变体、XX 包裹、join 分隔符——提示词措辞 | 提示词形态（任务书 §2：措辞归 A） |
| app.authors.pipeline.x__draft_task__mutmut_78 | A | title/thesis/key/brief get 变体、XX 包裹、join 分隔符——提示词措辞 | 提示词形态（任务书 §2：措辞归 A） |
| app.authors.pipeline.x__draft_task__mutmut_79 | A | title/thesis/key/brief get 变体、XX 包裹、join 分隔符——提示词措辞 | 提示词形态（任务书 §2：措辞归 A） |
| app.authors.pipeline.x__draft_task__mutmut_8 | A | gates.length 读取旁路——仅影响提示词字数措辞（门禁侧已由 C1-5a 覆盖） | 提示词形态（C1-5a 先例：长度 note 归 A） |
| app.authors.pipeline.x__draft_task__mutmut_80 | A | title/thesis/key/brief get 变体、XX 包裹、join 分隔符——提示词措辞 | 提示词形态（任务书 §2：措辞归 A） |
| app.authors.pipeline.x__draft_task__mutmut_81 | A | title/thesis/key/brief get 变体、XX 包裹、join 分隔符——提示词措辞 | 提示词形态（任务书 §2：措辞归 A） |
| app.authors.pipeline.x__draft_task__mutmut_82 | A | title/thesis/key/brief get 变体、XX 包裹、join 分隔符——提示词措辞 | 提示词形态（任务书 §2：措辞归 A） |
| app.authors.pipeline.x__draft_task__mutmut_83 | A | title/thesis/key/brief get 变体、XX 包裹、join 分隔符——提示词措辞 | 提示词形态（任务书 §2：措辞归 A） |
| app.authors.pipeline.x__draft_task__mutmut_84 | A | title/thesis/key/brief get 变体、XX 包裹、join 分隔符——提示词措辞 | 提示词形态（任务书 §2：措辞归 A） |
| app.authors.pipeline.x__draft_task__mutmut_85 | A | title/thesis/key/brief get 变体、XX 包裹、join 分隔符——提示词措辞 | 提示词形态（任务书 §2：措辞归 A） |
| app.authors.pipeline.x__draft_task__mutmut_86 | A | title/thesis/key/brief get 变体、XX 包裹、join 分隔符——提示词措辞 | 提示词形态（任务书 §2：措辞归 A） |
| app.authors.pipeline.x__draft_task__mutmut_87 | A | title/thesis/key/brief get 变体、XX 包裹、join 分隔符——提示词措辞 | 提示词形态（任务书 §2：措辞归 A） |
| app.authors.pipeline.x__draft_task__mutmut_88 | A | title/thesis/key/brief get 变体、XX 包裹、join 分隔符——提示词措辞 | 提示词形态（任务书 §2：措辞归 A） |
| app.authors.pipeline.x__draft_task__mutmut_89 | A | title/thesis/key/brief get 变体、XX 包裹、join 分隔符——提示词措辞 | 提示词形态（任务书 §2：措辞归 A） |
| app.authors.pipeline.x__draft_task__mutmut_9 | A | gates.length 读取旁路——仅影响提示词字数措辞（门禁侧已由 C1-5a 覆盖） | 提示词形态（C1-5a 先例：长度 note 归 A） |
| app.authors.pipeline.x__draft_task__mutmut_90 | A | title/thesis/key/brief get 变体、XX 包裹、join 分隔符——提示词措辞 | 提示词形态（任务书 §2：措辞归 A） |
| app.authors.pipeline.x__draft_task__mutmut_91 | A | title/thesis/key/brief get 变体、XX 包裹、join 分隔符——提示词措辞 | 提示词形态（任务书 §2：措辞归 A） |
| app.authors.pipeline.x__draft_task__mutmut_92 | A | title/thesis/key/brief get 变体、XX 包裹、join 分隔符——提示词措辞 | 提示词形态（任务书 §2：措辞归 A） |
| app.authors.pipeline.x__draft_task__mutmut_93 | A | task = 替换拼接——提示词段落组合形态 | 提示词形态（C1-5a 先例） |
| app.authors.pipeline.x__draft_task__mutmut_96 | A | title/thesis/key/brief get 变体、XX 包裹、join 分隔符——提示词措辞 | 提示词形态（任务书 §2：措辞归 A） |
| app.authors.pipeline.x__draft_task__mutmut_98 | A | title/thesis/key/brief get 变体、XX 包裹、join 分隔符——提示词措辞 | 提示词形态（任务书 §2：措辞归 A） |
| app.authors.pipeline.x__identity_system__mutmut_14 | A | do 列表 join 分隔符/项目符变体——人格卡措辞（条目内容事实已测） | 提示词形态（措辞归 A；内容事实性归 C 组） |
| app.authors.pipeline.x__identity_system__mutmut_16 | A | do 列表 join 分隔符/项目符变体——人格卡措辞（条目内容事实已测） | 提示词形态（措辞归 A；内容事实性归 C 组） |
| app.authors.pipeline.x__identity_system__mutmut_18 | A | rules.get('do', 默认)——do schema 必填（_str_list required），缺省不可达 | schema._str_list 必填核查 |
| app.authors.pipeline.x__identity_system__mutmut_20 | A | rules.get('do', 默认)——do schema 必填（_str_list required），缺省不可达 | schema._str_list 必填核查 |
| app.authors.pipeline.x__identity_system__mutmut_23 | A | do 列表 join 分隔符/项目符变体——人格卡措辞（条目内容事实已测） | 提示词形态（措辞归 A；内容事实性归 C 组） |
| app.authors.pipeline.x__identity_system__mutmut_27 | A | dont 列表 join/项目符变体——人格卡措辞 | 提示词形态 |
| app.authors.pipeline.x__identity_system__mutmut_29 | A | dont 列表 join/项目符变体——人格卡措辞 | 提示词形态 |
| app.authors.pipeline.x__identity_system__mutmut_31 | A | dont schema 必填，缺省不可达 | schema._str_list 必填核查 |
| app.authors.pipeline.x__identity_system__mutmut_33 | A | dont schema 必填，缺省不可达 | schema._str_list 必填核查 |
| app.authors.pipeline.x__identity_system__mutmut_36 | A | dont 列表 join/项目符变体——人格卡措辞 | 提示词形态 |
| app.authors.pipeline.x__identity_system__mutmut_37 | A | fps join/截断/键变体——人格卡措辞（门禁词表侧 C1-5a 已覆盖） | 提示词形态 |
| app.authors.pipeline.x__identity_system__mutmut_38 | A | fps join/截断/键变体——人格卡措辞（门禁词表侧 C1-5a 已覆盖） | 提示词形态 |
| app.authors.pipeline.x__identity_system__mutmut_40 | A | fps join/截断/键变体——人格卡措辞（门禁词表侧 C1-5a 已覆盖） | 提示词形态 |
| app.authors.pipeline.x__identity_system__mutmut_41 | A | fps join/截断/键变体——人格卡措辞（门禁词表侧 C1-5a 已覆盖） | 提示词形态 |
| app.authors.pipeline.x__identity_system__mutmut_42 | A | fingerprint schema 必填，缺省不可达 | schema._str_list 必填核查 |
| app.authors.pipeline.x__identity_system__mutmut_44 | A | fingerprint schema 必填，缺省不可达 | schema._str_list 必填核查 |
| app.authors.pipeline.x__identity_system__mutmut_45 | A | fps join/截断/键变体——人格卡措辞（门禁词表侧 C1-5a 已覆盖） | 提示词形态 |
| app.authors.pipeline.x__identity_system__mutmut_46 | A | fps join/截断/键变体——人格卡措辞（门禁词表侧 C1-5a 已覆盖） | 提示词形态 |
| app.authors.pipeline.x__identity_system__mutmut_47 | A | fps join/截断/键变体——人格卡措辞（门禁词表侧 C1-5a 已覆盖） | 提示词形态 |
| app.authors.pipeline.x__identity_system__mutmut_48 | A | fps join/截断/键变体——人格卡措辞（门禁词表侧 C1-5a 已覆盖） | 提示词形态 |
| app.authors.pipeline.x__identity_system__mutmut_52 | A | quotes_original join/截断变体——人格卡措辞（条目内容事实已测） | 提示词形态 |
| app.authors.pipeline.x__identity_system__mutmut_54 | A | quotes_original join/截断变体——人格卡措辞（条目内容事实已测） | 提示词形态 |
| app.authors.pipeline.x__identity_system__mutmut_56 | A | quotes_original schema 必填键，缺省不可达 | schema 必填键核查 |
| app.authors.pipeline.x__identity_system__mutmut_58 | A | quotes_original schema 必填键，缺省不可达 | schema 必填键核查 |
| app.authors.pipeline.x__identity_system__mutmut_6 | A | get('style_rules', 缺省)——style_rules schema 必填恒存在，缺省不可达 | schema 必填 + 控制流等价 |
| app.authors.pipeline.x__identity_system__mutmut_61 | A | quotes_original join/截断变体——人格卡措辞（条目内容事实已测） | 提示词形态 |
| app.authors.pipeline.x__identity_system__mutmut_62 | A | quotes_original join/截断变体——人格卡措辞（条目内容事实已测） | 提示词形态 |
| app.authors.pipeline.x__identity_system__mutmut_65 | A | description/personality/values_stance/scenario/style_anchor 读取与（未提供）兜底变体——人格卡措辞 | 提示词形态（任务书 §2） |
| app.authors.pipeline.x__identity_system__mutmut_66 | A | description/personality/values_stance/scenario/style_anchor 读取与（未提供）兜底变体——人格卡措辞 | 提示词形态（任务书 §2） |
| app.authors.pipeline.x__identity_system__mutmut_67 | A | description/personality/values_stance/scenario/style_anchor 读取与（未提供）兜底变体——人格卡措辞 | 提示词形态（任务书 §2） |
| app.authors.pipeline.x__identity_system__mutmut_68 | A | description/personality/values_stance/scenario/style_anchor 读取与（未提供）兜底变体——人格卡措辞 | 提示词形态（任务书 §2） |
| app.authors.pipeline.x__identity_system__mutmut_69 | A | description/personality/values_stance/scenario/style_anchor 读取与（未提供）兜底变体——人格卡措辞 | 提示词形态（任务书 §2） |
| app.authors.pipeline.x__identity_system__mutmut_70 | A | description/personality/values_stance/scenario/style_anchor 读取与（未提供）兜底变体——人格卡措辞 | 提示词形态（任务书 §2） |
| app.authors.pipeline.x__identity_system__mutmut_71 | A | description/personality/values_stance/scenario/style_anchor 读取与（未提供）兜底变体——人格卡措辞 | 提示词形态（任务书 §2） |
| app.authors.pipeline.x__identity_system__mutmut_72 | A | description/personality/values_stance/scenario/style_anchor 读取与（未提供）兜底变体——人格卡措辞 | 提示词形态（任务书 §2） |
| app.authors.pipeline.x__identity_system__mutmut_73 | A | description/personality/values_stance/scenario/style_anchor 读取与（未提供）兜底变体——人格卡措辞 | 提示词形态（任务书 §2） |
| app.authors.pipeline.x__identity_system__mutmut_74 | A | description/personality/values_stance/scenario/style_anchor 读取与（未提供）兜底变体——人格卡措辞 | 提示词形态（任务书 §2） |
| app.authors.pipeline.x__identity_system__mutmut_75 | A | description/personality/values_stance/scenario/style_anchor 读取与（未提供）兜底变体——人格卡措辞 | 提示词形态（任务书 §2） |
| app.authors.pipeline.x__identity_system__mutmut_76 | A | description/personality/values_stance/scenario/style_anchor 读取与（未提供）兜底变体——人格卡措辞 | 提示词形态（任务书 §2） |
| app.authors.pipeline.x__identity_system__mutmut_77 | A | description/personality/values_stance/scenario/style_anchor 读取与（未提供）兜底变体——人格卡措辞 | 提示词形态（任务书 §2） |
| app.authors.pipeline.x__identity_system__mutmut_78 | A | description/personality/values_stance/scenario/style_anchor 读取与（未提供）兜底变体——人格卡措辞 | 提示词形态（任务书 §2） |
| app.authors.pipeline.x__identity_system__mutmut_79 | A | description/personality/values_stance/scenario/style_anchor 读取与（未提供）兜底变体——人格卡措辞 | 提示词形态（任务书 §2） |
| app.authors.pipeline.x__identity_system__mutmut_8 | A | get('style_rules', 缺省)——style_rules schema 必填恒存在，缺省不可达 | schema 必填 + 控制流等价 |
| app.authors.pipeline.x__identity_system__mutmut_80 | A | description/personality/values_stance/scenario/style_anchor 读取与（未提供）兜底变体——人格卡措辞 | 提示词形态（任务书 §2） |
| app.authors.pipeline.x__identity_system__mutmut_81 | A | description/personality/values_stance/scenario/style_anchor 读取与（未提供）兜底变体——人格卡措辞 | 提示词形态（任务书 §2） |
| app.authors.pipeline.x__identity_system__mutmut_82 | A | description/personality/values_stance/scenario/style_anchor 读取与（未提供）兜底变体——人格卡措辞 | 提示词形态（任务书 §2） |
| app.authors.pipeline.x__identity_system__mutmut_83 | A | description/personality/values_stance/scenario/style_anchor 读取与（未提供）兜底变体——人格卡措辞 | 提示词形态（任务书 §2） |
| app.authors.pipeline.x__identity_system__mutmut_84 | A | description/personality/values_stance/scenario/style_anchor 读取与（未提供）兜底变体——人格卡措辞 | 提示词形态（任务书 §2） |
| app.authors.pipeline.x__identity_system__mutmut_85 | A | description/personality/values_stance/scenario/style_anchor 读取与（未提供）兜底变体——人格卡措辞 | 提示词形态（任务书 §2） |
| app.authors.pipeline.x__identity_system__mutmut_86 | A | description/personality/values_stance/scenario/style_anchor 读取与（未提供）兜底变体——人格卡措辞 | 提示词形态（任务书 §2） |
| app.authors.pipeline.x__identity_system__mutmut_87 | A | description/personality/values_stance/scenario/style_anchor 读取与（未提供）兜底变体——人格卡措辞 | 提示词形态（任务书 §2） |
| app.authors.pipeline.x__identity_system__mutmut_88 | A | description/personality/values_stance/scenario/style_anchor 读取与（未提供）兜底变体——人格卡措辞 | 提示词形态（任务书 §2） |
| app.authors.pipeline.x__identity_system__mutmut_89 | A | description/personality/values_stance/scenario/style_anchor 读取与（未提供）兜底变体——人格卡措辞 | 提示词形态（任务书 §2） |
| app.authors.pipeline.x__recent_titles__mutmut_1 | A | n=0 域 limit(0) 恰等价空列表 | 控制流等价 |
| app.authors.pipeline.x__refs_listing__mutmut_12 | A | 正文兜底/相关分/来源/（无正文）兜底/分隔符——阅读集条目展示形态措辞 | 提示词形态（任务书 §2） |
| app.authors.pipeline.x__refs_listing__mutmut_13 | A | 正文兜底/相关分/来源/（无正文）兜底/分隔符——阅读集条目展示形态措辞 | 提示词形态（任务书 §2） |
| app.authors.pipeline.x__refs_listing__mutmut_14 | A | 正文兜底/相关分/来源/（无正文）兜底/分隔符——阅读集条目展示形态措辞 | 提示词形态（任务书 §2） |
| app.authors.pipeline.x__refs_listing__mutmut_18 | A | 正文兜底/相关分/来源/（无正文）兜底/分隔符——阅读集条目展示形态措辞 | 提示词形态（任务书 §2） |
| app.authors.pipeline.x__refs_listing__mutmut_19 | A | 正文兜底/相关分/来源/（无正文）兜底/分隔符——阅读集条目展示形态措辞 | 提示词形态（任务书 §2） |
| app.authors.pipeline.x__refs_listing__mutmut_20 | A | 正文兜底/相关分/来源/（无正文）兜底/分隔符——阅读集条目展示形态措辞 | 提示词形态（任务书 §2） |
| app.authors.pipeline.x__refs_listing__mutmut_22 | A | 正文兜底/相关分/来源/（无正文）兜底/分隔符——阅读集条目展示形态措辞 | 提示词形态（任务书 §2） |
| app.authors.pipeline.x__refs_listing__mutmut_23 | A | 正文兜底/相关分/来源/（无正文）兜底/分隔符——阅读集条目展示形态措辞 | 提示词形态（任务书 §2） |
| app.authors.pipeline.x__refs_listing__mutmut_25 | A | 正文兜底/相关分/来源/（无正文）兜底/分隔符——阅读集条目展示形态措辞 | 提示词形态（任务书 §2） |
| app.authors.pipeline.x__refs_listing__mutmut_27 | A | 正文兜底/相关分/来源/（无正文）兜底/分隔符——阅读集条目展示形态措辞 | 提示词形态（任务书 §2） |
| app.authors.pipeline.x__refs_listing__mutmut_4 | A | 正文兜底/相关分/来源/（无正文）兜底/分隔符——阅读集条目展示形态措辞 | 提示词形态（任务书 §2） |
| app.authors.pipeline.x__refs_listing__mutmut_9 | A | 正文兜底/相关分/来源/（无正文）兜底/分隔符——阅读集条目展示形态措辞 | 提示词形态（任务书 §2） |
| app.authors.pipeline.x__slices_block__mutmut_10 | A | 空切片 XXXX/连接符/tail 条件变体——两分支串仅尾换行之差，注入内容形态措辞（C1-5a 同款先例：两分支同串归 A） | 提示词形态（任务书 §2：注入内容形态归 A） |
| app.authors.pipeline.x__slices_block__mutmut_11 | A | 空切片 XXXX/连接符/tail 条件变体——两分支串仅尾换行之差，注入内容形态措辞（C1-5a 同款先例：两分支同串归 A） | 提示词形态（任务书 §2：注入内容形态归 A） |
| app.authors.pipeline.x__slices_block__mutmut_12 | A | 空切片 XXXX/连接符/tail 条件变体——两分支串仅尾换行之差，注入内容形态措辞（C1-5a 同款先例：两分支同串归 A） | 提示词形态（任务书 §2：注入内容形态归 A） |
| app.authors.pipeline.x__slices_block__mutmut_2 | A | 空切片 XXXX/连接符/tail 条件变体——两分支串仅尾换行之差，注入内容形态措辞（C1-5a 同款先例：两分支同串归 A） | 提示词形态（任务书 §2：注入内容形态归 A） |
| app.authors.pipeline.x__slices_block__mutmut_5 | A | 空切片 XXXX/连接符/tail 条件变体——两分支串仅尾换行之差，注入内容形态措辞（C1-5a 同款先例：两分支同串归 A） | 提示词形态（任务书 §2：注入内容形态归 A） |
| app.authors.pipeline.x__slices_block__mutmut_8 | A | 空切片 XXXX/连接符/tail 条件变体——两分支串仅尾换行之差，注入内容形态措辞（C1-5a 同款先例：两分支同串归 A） | 提示词形态（任务书 §2：注入内容形态归 A） |
| app.authors.pipeline.x__slices_block__mutmut_9 | A | 空切片 XXXX/连接符/tail 条件变体——两分支串仅尾换行之差，注入内容形态措辞（C1-5a 同款先例：两分支同串归 A） | 提示词形态（任务书 §2：注入内容形态归 A） |
| app.authors.pipeline.x__static_injection__mutmut_101 | A | 同 54/59——text 必填不可达 | schema 必填键核查 |
| app.authors.pipeline.x__static_injection__mutmut_103 | A | 同 54/59——text 必填不可达 | schema 必填键核查 |
| app.authors.pipeline.x__static_injection__mutmut_106 | A | 同 54/59——text 必填不可达 | schema 必填键核查 |
| app.authors.pipeline.x__static_injection__mutmut_111 | A | out[].id 键/值变体——out 仅被 _slices_block 消费 text，id 无消费点 | 控制流等价（死键） |
| app.authors.pipeline.x__static_injection__mutmut_112 | A | out[].id 键/值变体——out 仅被 _slices_block 消费 text，id 无消费点 | 控制流等价（死键） |
| app.authors.pipeline.x__static_injection__mutmut_113 | A | out[].id 键/值变体——out 仅被 _slices_block 消费 text，id 无消费点 | 控制流等价（死键） |
| app.authors.pipeline.x__static_injection__mutmut_114 | A | out[].id 键/值变体——out 仅被 _slices_block 消费 text，id 无消费点 | 控制流等价（死键） |
| app.authors.pipeline.x__static_injection__mutmut_115 | A | out[].id 键/值变体——out 仅被 _slices_block 消费 text，id 无消费点 | 控制流等价（死键） |
| app.authors.pipeline.x__static_injection__mutmut_116 | A | out[].id 键/值变体——out 仅被 _slices_block 消费 text，id 无消费点 | 控制流等价（死键） |
| app.authors.pipeline.x__static_injection__mutmut_117 | A | out[].id 键/值变体——out 仅被 _slices_block 消费 text，id 无消费点 | 控制流等价（死键） |
| app.authors.pipeline.x__static_injection__mutmut_118 | A | out[].id 键/值变体——out 仅被 _slices_block 消费 text，id 无消费点 | 控制流等价（死键） |
| app.authors.pipeline.x__static_injection__mutmut_125 | A | b.get('id', 默认)——块 id schema 必填，缺省不可达 | schema 必填键核查 |
| app.authors.pipeline.x__static_injection__mutmut_127 | A | b.get('id', 默认)——块 id schema 必填，缺省不可达 | schema 必填键核查 |
| app.authors.pipeline.x__static_injection__mutmut_130 | A | source 键/值变体——source 记录字段形态未钉（§4.1 只钉 static_injection 明细存在） | §4.1 字段范围核查 |
| app.authors.pipeline.x__static_injection__mutmut_131 | A | source 键/值变体——source 记录字段形态未钉（§4.1 只钉 static_injection 明细存在） | §4.1 字段范围核查 |
| app.authors.pipeline.x__static_injection__mutmut_132 | A | source 键/值变体——source 记录字段形态未钉（§4.1 只钉 static_injection 明细存在） | §4.1 字段范围核查 |
| app.authors.pipeline.x__static_injection__mutmut_133 | A | source 键/值变体——source 记录字段形态未钉（§4.1 只钉 static_injection 明细存在） | §4.1 字段范围核查 |
| app.authors.pipeline.x__static_injection__mutmut_134 | A | source 键/值变体——source 记录字段形态未钉（§4.1 只钉 static_injection 明细存在） | §4.1 字段范围核查 |
| app.authors.pipeline.x__static_injection__mutmut_135 | A | source 键/值变体——source 记录字段形态未钉（§4.1 只钉 static_injection 明细存在） | §4.1 字段范围核查 |
| app.authors.pipeline.x__static_injection__mutmut_136 | A | source 键/值变体——source 记录字段形态未钉（§4.1 只钉 static_injection 明细存在） | §4.1 字段范围核查 |
| app.authors.pipeline.x__static_injection__mutmut_137 | A | source 键/值变体——source 记录字段形态未钉（§4.1 只钉 static_injection 明细存在） | §4.1 字段范围核查 |
| app.authors.pipeline.x__static_injection__mutmut_138 | A | source 键/值变体——source 记录字段形态未钉（§4.1 只钉 static_injection 明细存在） | §4.1 字段范围核查 |
| app.authors.pipeline.x__static_injection__mutmut_141 | A | original_chars 记录键未钉 | §4.1 字段范围核查 |
| app.authors.pipeline.x__static_injection__mutmut_142 | A | original_chars 记录键未钉 | §4.1 字段范围核查 |
| app.authors.pipeline.x__static_injection__mutmut_145 | A | selection 记录键未钉 | §4.1 字段范围核查 |
| app.authors.pipeline.x__static_injection__mutmut_146 | A | selection 记录键未钉 | §4.1 字段范围核查 |
| app.authors.pipeline.x__static_injection__mutmut_25 | A | or 501 缺省——per_block_max_chars schema 必填（lo=1），缺省不可达 | schema._validate_memory 必填键核查 |
| app.authors.pipeline.x__static_injection__mutmut_35 | A | or 缺省字面量——selection schema 必填枚举不可达；且非 recency/relevant 字面量仍落入 else=round_robin 恰等价 | schema 必填 + 控制流恰等价 |
| app.authors.pipeline.x__static_injection__mutmut_36 | A | or 缺省字面量——selection schema 必填枚举不可达；且非 recency/relevant 字面量仍落入 else=round_robin 恰等价 | schema 必填 + 控制流恰等价 |
| app.authors.pipeline.x__static_injection__mutmut_54 | A | b.get('text', 默认)——static_blocks 项 text 为 schema 必填 str，缺省不可达 | schema._validate_memory 项内必填键核查 |
| app.authors.pipeline.x__static_injection__mutmut_56 | A | b.get('text',) 即 get('text')——text 键 schema 必填恒存在，恰等价 | 控制流等价 |
| app.authors.pipeline.x__static_injection__mutmut_59 | A | b.get('text', 默认)——static_blocks 项 text 为 schema 必填 str，缺省不可达 | schema._validate_memory 项内必填键核查 |
| app.authors.pipeline.x__static_injection__mutmut_62 | A | (len>=2) or True——len<2 域两分支均得空集，恰等价 | 控制流等价 |
| app.authors.pipeline.x__static_injection__mutmut_70 | A | max(1,·) 与 max(0,·) 在 len>=2 闸门域（len-1>=1）恒等价 | 控制流等价 |
| app.authors.pipeline.x__static_injection__mutmut_71 | A | 多出的空串/单字 gram 元素不可能属于 2 字标题 gram 集合，交集不变 | 控制流等价 |
| app.authors.pipeline.x__static_injection__mutmut_76 | A | 空集域 len(&) = 0 = 0.0，恰等价 | 控制流等价 |
| app.authors.pipeline.x_assemble_article_text__mutmut_11 | A | XX&lt;XX 包裹——合法实体仍在，转义纪律满足，包裹形态未钉 | 形态无条款 |
| app.authors.pipeline.x_assemble_article_text__mutmut_14 | A | 空白裁剪方向——形态差异 | 形态无条款 |
| app.authors.pipeline.x_assemble_article_text__mutmut_19 | A | sub('XXXX') 残留形态——散落定义行仍被移出定义区 | 形态无条款 |
| app.authors.pipeline.x_assemble_article_text__mutmut_24 | A | or True——空定义域尾部空行差异 | 形态无条款 |
| app.authors.pipeline.x_assemble_article_text__mutmut_26 | A | 分隔符/else 形态——定义行格式（钉）不变 | 形态无条款（[^nK] 行格式本身已测） |
| app.authors.pipeline.x_assemble_article_text__mutmut_28 | A | 分隔符/else 形态——定义行格式（钉）不变 | 形态无条款（[^nK] 行格式本身已测） |
| app.authors.pipeline.x_assemble_article_text__mutmut_29 | A | 分隔符/else 形态——定义行格式（钉）不变 | 形态无条款（[^nK] 行格式本身已测） |
| app.authors.pipeline.x_run_pipeline_write__mutmut_1 | A | 签名缺省 'manual' 变体——全部调用点（writer.run_write/API write_task）显式传参，缺省不可达 | 调用点核查：writer.py:219、routes.py:53 |
| app.authors.pipeline.x_run_pipeline_write__mutmut_10 | A | cfg.get('route', None/)——route 为 schema 必填节恒存在，缺省形态不可达 | schema 必填 + 控制流等价 |
| app.authors.pipeline.x_run_pipeline_write__mutmut_105 | A | reading_window 镜像键名未钉 | §4.1 字段范围核查（C1-5a 同款先例） |
| app.authors.pipeline.x_run_pipeline_write__mutmut_106 | A | reading_window 镜像键名未钉 | §4.1 字段范围核查（C1-5a 同款先例） |
| app.authors.pipeline.x_run_pipeline_write__mutmut_107 | A | 初始值被 execute 写回遮蔽 | 控制流等价（终态写回） |
| app.authors.pipeline.x_run_pipeline_write__mutmut_109 | A | 初始值被终态写回遮蔽 | 控制流等价（终态写回） |
| app.authors.pipeline.x_run_pipeline_write__mutmut_110 | A | 初始值被终态写回遮蔽 | 控制流等价（终态写回） |
| app.authors.pipeline.x_run_pipeline_write__mutmut_128 | A | _ = article→None——article 无后续消费 | 控制流等价（死代码） |
| app.authors.pipeline.x_run_pipeline_write__mutmut_2 | A | 签名缺省 'manual' 变体——全部调用点（writer.run_write/API write_task）显式传参，缺省不可达 | 调用点核查：writer.py:219、routes.py:53 |
| app.authors.pipeline.x_run_pipeline_write__mutmut_24 | A | reading_set_item_ids=None——该列内容未钉（§4.1 关键列不含） | §4.1 字段范围核查 |
| app.authors.pipeline.x_run_pipeline_write__mutmut_25 | A | payload=None——config_error 域 payload 无断言消费点 | 字段形态未钉 |
| app.authors.pipeline.x_run_pipeline_write__mutmut_26 | A | prompt_snapshot=None vs ''——空值形态未钉 | 空值形态无条款 |
| app.authors.pipeline.x_run_pipeline_write__mutmut_32 | A | 构造器缺参——ORM 列级 default（dict/[]/''）恰兜底 | app/models.py WriteRun 列 default 核查 |
| app.authors.pipeline.x_run_pipeline_write__mutmut_33 | A | 构造器缺参——ORM 列级 default（dict/[]/''）恰兜底 | app/models.py WriteRun 列 default 核查 |
| app.authors.pipeline.x_run_pipeline_write__mutmut_34 | A | 构造器缺参——ORM 列级 default（dict/[]/''）恰兜底 | app/models.py WriteRun 列 default 核查 |
| app.authors.pipeline.x_run_pipeline_write__mutmut_38 | A | config_error 键名形态——payload 内部键未钉 | §4.1 字段范围核查 |
| app.authors.pipeline.x_run_pipeline_write__mutmut_39 | A | config_error 键名形态——payload 内部键未钉 | §4.1 字段范围核查 |
| app.authors.pipeline.x_run_pipeline_write__mutmut_40 | A | 错误文本 'None' 形态——文案无措辞条款 | 文案无措辞条款 |
| app.authors.pipeline.x_run_pipeline_write__mutmut_41 | A | [:1000]→[:1001]——错误文本截断界无条款 | 截断界无条款（C1-5a 先例） |
| app.authors.pipeline.x_run_pipeline_write__mutmut_42 | A | XXXX vs ''——未写快照的占位形态未钉 | 空值形态无条款 |
| app.authors.pipeline.x_run_pipeline_write__mutmut_46 | A | error 文案变体——无措辞条款 | 文案无措辞条款 |
| app.authors.pipeline.x_run_pipeline_write__mutmut_47 | A | error 文案变体——无措辞条款 | 文案无措辞条款 |
| app.authors.pipeline.x_run_pipeline_write__mutmut_57 | A | reading_set_item_ids=None——列内容未钉 | §4.1 字段范围核查 |
| app.authors.pipeline.x_run_pipeline_write__mutmut_59 | A | 初始 prompt_snapshot None/缺参——execute 均写回终值，被遮蔽 | 控制流等价（终态写回） |
| app.authors.pipeline.x_run_pipeline_write__mutmut_61 | A | 初始 status None/缺参——execute 终态恒写回 OK/FAILED，被遮蔽 | 控制流等价（终态写回） |
| app.authors.pipeline.x_run_pipeline_write__mutmut_64 | A | 缺参→ORM default=list——值域未钉 | 字段未钉 + ORM default |
| app.authors.pipeline.x_run_pipeline_write__mutmut_66 | A | 初始 prompt_snapshot None/缺参——execute 均写回终值，被遮蔽 | 控制流等价（终态写回） |
| app.authors.pipeline.x_run_pipeline_write__mutmut_68 | A | 初始 status None/缺参——execute 终态恒写回 OK/FAILED，被遮蔽 | 控制流等价（终态写回） |
| app.authors.pipeline.x_run_pipeline_write__mutmut_71 | A | payload.route.outline/draft 键名——payload 内部镜像形态未钉 | §4.1 字段范围核查 |
| app.authors.pipeline.x_run_pipeline_write__mutmut_72 | A | payload.route.outline/draft 键名——payload 内部镜像形态未钉 | §4.1 字段范围核查 |
| app.authors.pipeline.x_run_pipeline_write__mutmut_79 | A | payload.route.outline/draft 键名——payload 内部镜像形态未钉 | §4.1 字段范围核查 |
| app.authors.pipeline.x_run_pipeline_write__mutmut_8 | A | cfg.get('route', None/)——route 为 schema 必填节恒存在，缺省形态不可达 | schema 必填 + 控制流等价 |
| app.authors.pipeline.x_run_pipeline_write__mutmut_80 | A | payload.route.outline/draft 键名——payload 内部镜像形态未钉 | §4.1 字段范围核查 |
| app.authors.pipeline.x_run_pipeline_write__mutmut_87 | A | payload.route.passes 镜像读取/键名——内部形态未钉 | §4.1 字段范围核查 |
| app.authors.pipeline.x_run_pipeline_write__mutmut_88 | A | payload.route.passes 镜像读取/键名——内部形态未钉 | §4.1 字段范围核查 |
| app.authors.pipeline.x_run_pipeline_write__mutmut_91 | A | payload.route.passes 镜像读取/键名——内部形态未钉 | §4.1 字段范围核查 |
| app.authors.pipeline.x_run_pipeline_write__mutmut_92 | A | payload.route.passes 镜像读取/键名——内部形态未钉 | §4.1 字段范围核查 |
| app.authors.pipeline.x_run_pipeline_write__mutmut_94 | A | payload.route.passes 镜像读取/键名——内部形态未钉 | §4.1 字段范围核查 |
| app.authors.pipeline.x_run_pipeline_write__mutmut_97 | A | payload.route.passes 镜像读取/键名——内部形态未钉 | §4.1 字段范围核查 |
| app.authors.pipeline.x_run_pipeline_write__mutmut_98 | A | payload.route.passes 镜像读取/键名——内部形态未钉 | §4.1 字段范围核查 |
| app.authors.pipeline.x_validate_citations_pipeline__mutmut_13 | A | sub('XXXX') 残留不含 [^K]——marks 集合恰等价 | 控制流等价 |
| app.authors.pipeline.x_validate_citations_pipeline__mutmut_3 | A | content_text None 域两形态均落拒收，恰等价 | 控制流等价（拒收域） |
| app.authors.pipeline.x_validate_citations_pipeline__mutmut_36 | A | or True——hint 空域消息形态差异，文案无条款 | 文案无措辞条款 |
| app.authors.pipeline.x_validate_citations_pipeline__mutmut_37 | A | 同上 | 文案无措辞条款 |
| app.authors.pipeline.x_validate_citations_pipeline__mutmut_39 | A | quote[:81]——错误文案形态 | 文案无措辞条款 |

## 批次 8a：authors.schema 五域验证器+入口/缺省（2026-10-03，C1-6 第一段）

> 本批无 B 类。D 类 2 条不在本清单（`x__validate_output__mutmut_44` /
> `x__validate_route__mutmut_256`：可选 object 字段显式 null 的归一语义设计书未钉，
> 同一拍板问题两变异体，见 C1-6 执行汇报 §3）。C 类 352 条（新增测试闭合 349 +
> 既有/前批测试闭合 3：gates m133 由 C1-5a min_count=0 合法性测试、
> default m166/m167 由 C1-5a max_tokens_per_node 键存在性测试闭合）
> 由 `tests/test_mutation_c1_6.py` 闭合，不在本清单。

| mutant 全名 | 类别 | 一句话理由 | 依据条款或推理 |
|---|---|---|---|
| app.authors.schema.x__validate_gates__mutmut_109 | A | 「期望类型」措辞变体（路径保留） | AC-10.1（未钉期望类型措辞） |
| app.authors.schema.x__validate_gates__mutmut_110 | A | 错误文案 None/形态变体（字段路径保留） | AC-10.1（只钉路径+一次报全，未钉措辞） |
| app.authors.schema.x__validate_gates__mutmut_115 | A | 文案 XX 包裹/大写形态变体（字段路径保留） | AC-10.1（只钉路径+一次报全，未钉措辞） |
| app.authors.schema.x__validate_gates__mutmut_116 | A | 文案 XX 包裹/大写形态变体（字段路径保留） | AC-10.1（只钉路径+一次报全，未钉措辞） |
| app.authors.schema.x__validate_gates__mutmut_125 | A | 数值边界变体（lo/hi 移位或移除） | 数值边界无条款（C1-5a 数值缺省先例；唯一钉死边界 max_attempts(1-10) 已由边界测试闭合） |
| app.authors.schema.x__validate_gates__mutmut_130 | A | 数值边界变体（lo/hi 移位或移除） | 数值边界无条款（C1-5a 数值缺省先例；唯一钉死边界 max_attempts(1-10) 已由边界测试闭合） |
| app.authors.schema.x__validate_gates__mutmut_142 | A | 数值边界变体（lo/hi 移位或移除） | 数值边界无条款（C1-5a 数值缺省先例；唯一钉死边界 max_attempts(1-10) 已由边界测试闭合） |
| app.authors.schema.x__validate_gates__mutmut_143 | A | 数值边界变体（lo/hi 移位或移除） | 数值边界无条款（C1-5a 数值缺省先例；唯一钉死边界 max_attempts(1-10) 已由边界测试闭合） |
| app.authors.schema.x__validate_gates__mutmut_148 | A | 数值边界变体（lo/hi 移位或移除） | 数值边界无条款（C1-5a 数值缺省先例；唯一钉死边界 max_attempts(1-10) 已由边界测试闭合） |
| app.authors.schema.x__validate_gates__mutmut_149 | A | 数值边界变体（lo/hi 移位或移除） | 数值边界无条款（C1-5a 数值缺省先例；唯一钉死边界 max_attempts(1-10) 已由边界测试闭合） |
| app.authors.schema.x__validate_gates__mutmut_152 | A | 数值边界变体（lo/hi 移位或移除） | 数值边界无条款（C1-5a 数值缺省先例；唯一钉死边界 max_attempts(1-10) 已由边界测试闭合） |
| app.authors.schema.x__validate_gates__mutmut_153 | A | 数值边界变体（lo/hi 移位或移除） | 数值边界无条款（C1-5a 数值缺省先例；唯一钉死边界 max_attempts(1-10) 已由边界测试闭合） |
| app.authors.schema.x__validate_gates__mutmut_162 | A | 数值边界变体（lo/hi 移位或移除） | 数值边界无条款（C1-5a 数值缺省先例；唯一钉死边界 max_attempts(1-10) 已由边界测试闭合） |
| app.authors.schema.x__validate_gates__mutmut_167 | A | 数值边界变体（lo/hi 移位或移除） | 数值边界无条款（C1-5a 数值缺省先例；唯一钉死边界 max_attempts(1-10) 已由边界测试闭合） |
| app.authors.schema.x__validate_gates__mutmut_170 | A | 数值边界变体（lo/hi 移位或移除） | 数值边界无条款（C1-5a 数值缺省先例；唯一钉死边界 max_attempts(1-10) 已由边界测试闭合） |
| app.authors.schema.x__validate_gates__mutmut_190 | A | 「期望类型」措辞变体（路径保留） | AC-10.1（未钉期望类型措辞） |
| app.authors.schema.x__validate_gates__mutmut_191 | A | 错误文案 None/形态变体（字段路径保留） | AC-10.1（只钉路径+一次报全，未钉措辞） |
| app.authors.schema.x__validate_gates__mutmut_196 | A | 文案 XX 包裹/大写形态变体（字段路径保留） | AC-10.1（只钉路径+一次报全，未钉措辞） |
| app.authors.schema.x__validate_gates__mutmut_197 | A | 文案 XX 包裹/大写形态变体（字段路径保留） | AC-10.1（只钉路径+一次报全，未钉措辞） |
| app.authors.schema.x__validate_gates__mutmut_36 | A | 文案 XX 包裹/大写形态变体（字段路径保留） | AC-10.1（只钉路径+一次报全，未钉措辞） |
| app.authors.schema.x__validate_gates__mutmut_37 | A | 文案/形态变体（字段路径保留） | AC-10.1（只钉路径+一次报全，未钉措辞） |
| app.authors.schema.x__validate_gates__mutmut_46 | A | 数值边界变体（lo/hi 移位或移除） | 数值边界无条款（C1-5a 数值缺省先例；唯一钉死边界 max_attempts(1-10) 已由边界测试闭合） |
| app.authors.schema.x__validate_gates__mutmut_51 | A | 数值边界变体（lo/hi 移位或移除） | 数值边界无条款（C1-5a 数值缺省先例；唯一钉死边界 max_attempts(1-10) 已由边界测试闭合） |
| app.authors.schema.x__validate_gates__mutmut_54 | A | 数值边界变体（lo/hi 移位或移除） | 数值边界无条款（C1-5a 数值缺省先例；唯一钉死边界 max_attempts(1-10) 已由边界测试闭合） |
| app.authors.schema.x__validate_gates__mutmut_59 | A | 数值边界变体（lo/hi 移位或移除） | 数值边界无条款（C1-5a 数值缺省先例；唯一钉死边界 max_attempts(1-10) 已由边界测试闭合） |
| app.authors.schema.x__validate_gates__mutmut_64 | A | 数值边界变体（lo/hi 移位或移除） | 数值边界无条款（C1-5a 数值缺省先例；唯一钉死边界 max_attempts(1-10) 已由边界测试闭合） |
| app.authors.schema.x__validate_gates__mutmut_67 | A | 数值边界变体（lo/hi 移位或移除） | 数值边界无条款（C1-5a 数值缺省先例；唯一钉死边界 max_attempts(1-10) 已由边界测试闭合） |
| app.authors.schema.x__validate_gates__mutmut_79 | A | 错误文案 None/形态变体（字段路径保留） | AC-10.1（只钉路径+一次报全，未钉措辞） |
| app.authors.schema.x__validate_gates__mutmut_91 | A | 数值边界变体（lo/hi 移位或移除） | 数值边界无条款（C1-5a 数值缺省先例；唯一钉死边界 max_attempts(1-10) 已由边界测试闭合） |
| app.authors.schema.x__validate_gates__mutmut_96 | A | 数值边界变体（lo/hi 移位或移除） | 数值边界无条款（C1-5a 数值缺省先例；唯一钉死边界 max_attempts(1-10) 已由边界测试闭合） |
| app.authors.schema.x__validate_identity__mutmut_100 | A | 错误文案 None/形态变体（字段路径保留） | AC-10.1（只钉路径+一次报全，未钉措辞） |
| app.authors.schema.x__validate_identity__mutmut_105 | A | 文案 XX 包裹/大写形态变体（字段路径保留） | AC-10.1（只钉路径+一次报全，未钉措辞） |
| app.authors.schema.x__validate_identity__mutmut_106 | A | 文案 XX 包裹/大写形态变体（字段路径保留） | AC-10.1（只钉路径+一次报全，未钉措辞） |
| app.authors.schema.x__validate_identity__mutmut_112 | A | 错误文案 None/形态变体（字段路径保留） | AC-10.1（只钉路径+一次报全，未钉措辞） |
| app.authors.schema.x__validate_identity__mutmut_116 | A | 文案 XX 包裹/大写形态变体（字段路径保留） | AC-10.1（只钉路径+一次报全，未钉措辞） |
| app.authors.schema.x__validate_identity__mutmut_120 | A | 「期望类型」措辞变体（路径保留） | AC-10.1（未钉期望类型措辞） |
| app.authors.schema.x__validate_identity__mutmut_121 | A | 错误文案 None/形态变体（字段路径保留） | AC-10.1（只钉路径+一次报全，未钉措辞） |
| app.authors.schema.x__validate_identity__mutmut_128 | A | 文案 XX 包裹/大写形态变体（字段路径保留） | AC-10.1（只钉路径+一次报全，未钉措辞） |
| app.authors.schema.x__validate_identity__mutmut_129 | A | 文案 XX 包裹/大写形态变体（字段路径保留） | AC-10.1（只钉路径+一次报全，未钉措辞） |
| app.authors.schema.x__validate_identity__mutmut_137 | A | 错误文案 None/形态变体（字段路径保留） | AC-10.1（只钉路径+一次报全，未钉措辞） |
| app.authors.schema.x__validate_identity__mutmut_141 | A | 文案 XX 包裹/大写形态变体（字段路径保留） | AC-10.1（只钉路径+一次报全，未钉措辞） |
| app.authors.schema.x__validate_identity__mutmut_148 | A | 错误文案 None/形态变体（字段路径保留） | AC-10.1（只钉路径+一次报全，未钉措辞） |
| app.authors.schema.x__validate_identity__mutmut_152 | A | 文案 XX 包裹/大写形态变体（字段路径保留） | AC-10.1（只钉路径+一次报全，未钉措辞） |
| app.authors.schema.x__validate_identity__mutmut_33 | A | 文案 XX 包裹/大写形态变体（字段路径保留） | AC-10.1（只钉路径+一次报全，未钉措辞） |
| app.authors.schema.x__validate_identity__mutmut_37 | A | 「期望类型」措辞变体（路径保留） | AC-10.1（未钉期望类型措辞） |
| app.authors.schema.x__validate_identity__mutmut_38 | A | 错误文案 None/形态变体（字段路径保留） | AC-10.1（只钉路径+一次报全，未钉措辞） |
| app.authors.schema.x__validate_identity__mutmut_43 | A | 文案 XX 包裹/大写形态变体（字段路径保留） | AC-10.1（只钉路径+一次报全，未钉措辞） |
| app.authors.schema.x__validate_identity__mutmut_44 | A | 文案 XX 包裹/大写形态变体（字段路径保留） | AC-10.1（只钉路径+一次报全，未钉措辞） |
| app.authors.schema.x__validate_identity__mutmut_89 | A | get 缺省 None 落归一分支（{}），行为等价 | 控制流等价推理（归一化已存在） |
| app.authors.schema.x__validate_identity__mutmut_91 | A | get 缺省 None 落归一分支（{}），行为等价 | 控制流等价推理（归一化已存在） |
| app.authors.schema.x__validate_identity__mutmut_99 | A | 「期望类型」措辞变体（路径保留） | AC-10.1（未钉期望类型措辞） |
| app.authors.schema.x__validate_memory__mutmut_100 | A | 数值边界变体（lo/hi 移位或移除） | 数值边界无条款（C1-5a 数值缺省先例；唯一钉死边界 max_attempts(1-10) 已由边界测试闭合） |
| app.authors.schema.x__validate_memory__mutmut_105 | A | 数值边界变体（lo/hi 移位或移除） | 数值边界无条款（C1-5a 数值缺省先例；唯一钉死边界 max_attempts(1-10) 已由边界测试闭合） |
| app.authors.schema.x__validate_memory__mutmut_108 | A | 数值边界变体（lo/hi 移位或移除） | 数值边界无条款（C1-5a 数值缺省先例；唯一钉死边界 max_attempts(1-10) 已由边界测试闭合） |
| app.authors.schema.x__validate_memory__mutmut_11 | A | 错误文案 None/形态变体（字段路径保留） | AC-10.1（只钉路径+一次报全，未钉措辞） |
| app.authors.schema.x__validate_memory__mutmut_126 | A | 数值边界变体（lo/hi 移位或移除） | 数值边界无条款（C1-5a 数值缺省先例；唯一钉死边界 max_attempts(1-10) 已由边界测试闭合） |
| app.authors.schema.x__validate_memory__mutmut_131 | A | 数值边界变体（lo/hi 移位或移除） | 数值边界无条款（C1-5a 数值缺省先例；唯一钉死边界 max_attempts(1-10) 已由边界测试闭合） |
| app.authors.schema.x__validate_memory__mutmut_139 | A | 数值边界变体（lo/hi 移位或移除） | 数值边界无条款（C1-5a 数值缺省先例；唯一钉死边界 max_attempts(1-10) 已由边界测试闭合） |
| app.authors.schema.x__validate_memory__mutmut_144 | A | 数值边界变体（lo/hi 移位或移除） | 数值边界无条款（C1-5a 数值缺省先例；唯一钉死边界 max_attempts(1-10) 已由边界测试闭合） |
| app.authors.schema.x__validate_memory__mutmut_147 | A | 数值边界变体（lo/hi 移位或移除） | 数值边界无条款（C1-5a 数值缺省先例；唯一钉死边界 max_attempts(1-10) 已由边界测试闭合） |
| app.authors.schema.x__validate_memory__mutmut_15 | A | 文案 XX 包裹/大写形态变体（字段路径保留） | AC-10.1（只钉路径+一次报全，未钉措辞） |
| app.authors.schema.x__validate_memory__mutmut_179 | A | 错误文案 None/形态变体（字段路径保留） | AC-10.1（只钉路径+一次报全，未钉措辞） |
| app.authors.schema.x__validate_memory__mutmut_183 | A | 文案 XX 包裹/大写形态变体（字段路径保留） | AC-10.1（只钉路径+一次报全，未钉措辞） |
| app.authors.schema.x__validate_memory__mutmut_19 | A | 「期望类型」措辞变体（路径保留） | AC-10.1（未钉期望类型措辞） |
| app.authors.schema.x__validate_memory__mutmut_191 | A | 错误文案 None/形态变体（字段路径保留） | AC-10.1（只钉路径+一次报全，未钉措辞） |
| app.authors.schema.x__validate_memory__mutmut_195 | A | 文案 XX 包裹/大写形态变体（字段路径保留） | AC-10.1（只钉路径+一次报全，未钉措辞） |
| app.authors.schema.x__validate_memory__mutmut_196 | A | 文案/形态变体（字段路径保留） | AC-10.1（只钉路径+一次报全，未钉措辞） |
| app.authors.schema.x__validate_memory__mutmut_20 | A | 错误文案 None/形态变体（字段路径保留） | AC-10.1（只钉路径+一次报全，未钉措辞） |
| app.authors.schema.x__validate_memory__mutmut_25 | A | 文案 XX 包裹/大写形态变体（字段路径保留） | AC-10.1（只钉路径+一次报全，未钉措辞） |
| app.authors.schema.x__validate_memory__mutmut_26 | A | 文案 XX 包裹/大写形态变体（字段路径保留） | AC-10.1（只钉路径+一次报全，未钉措辞） |
| app.authors.schema.x__validate_memory__mutmut_33 | A | 「期望类型」措辞变体（路径保留） | AC-10.1（未钉期望类型措辞） |
| app.authors.schema.x__validate_memory__mutmut_34 | A | 错误文案 None/形态变体（字段路径保留） | AC-10.1（只钉路径+一次报全，未钉措辞） |
| app.authors.schema.x__validate_memory__mutmut_39 | A | 文案 XX 包裹/大写形态变体（字段路径保留） | AC-10.1（只钉路径+一次报全，未钉措辞） |
| app.authors.schema.x__validate_memory__mutmut_40 | A | 文案 XX 包裹/大写形态变体（字段路径保留） | AC-10.1（只钉路径+一次报全，未钉措辞） |
| app.authors.schema.x__validate_output__mutmut_22 | A | 错误文案 None/形态变体（字段路径保留） | AC-10.1（只钉路径+一次报全，未钉措辞） |
| app.authors.schema.x__validate_output__mutmut_38 | A | get 缺省 None 落归一分支（{}），行为等价 | 控制流等价推理（归一化已存在） |
| app.authors.schema.x__validate_output__mutmut_40 | A | get 缺省 None 落归一分支（{}），行为等价 | 控制流等价推理（归一化已存在） |
| app.authors.schema.x__validate_output__mutmut_52 | A | 错误文案 None/形态变体（字段路径保留） | AC-10.1（只钉路径+一次报全，未钉措辞） |
| app.authors.schema.x__validate_output__mutmut_56 | A | 文案 XX 包裹/大写形态变体（字段路径保留） | AC-10.1（只钉路径+一次报全，未钉措辞） |
| app.authors.schema.x__validate_output__mutmut_57 | A | 文案/形态变体（字段路径保留） | AC-10.1（只钉路径+一次报全，未钉措辞） |
| app.authors.schema.x__validate_route__mutmut_100 | A | 数值边界变体（lo/hi 移位或移除） | 数值边界无条款（C1-5a 数值缺省先例；唯一钉死边界 max_attempts(1-10) 已由边界测试闭合） |
| app.authors.schema.x__validate_route__mutmut_104 | A | 数值边界变体（lo/hi 移位或移除） | 数值边界无条款（C1-5a 数值缺省先例；唯一钉死边界 max_attempts(1-10) 已由边界测试闭合） |
| app.authors.schema.x__validate_route__mutmut_112 | A | 兼容字段缺省值变体（实际档位以 think_routing 为准） | docs 字段总表（think 兼容字段）+ 缺省值无条款 |
| app.authors.schema.x__validate_route__mutmut_116 | A | 「期望类型」措辞变体（路径保留） | AC-10.1（未钉期望类型措辞） |
| app.authors.schema.x__validate_route__mutmut_117 | A | 错误文案 None/形态变体（字段路径保留） | AC-10.1（只钉路径+一次报全，未钉措辞） |
| app.authors.schema.x__validate_route__mutmut_122 | A | 文案 XX 包裹/大写形态变体（字段路径保留） | AC-10.1（只钉路径+一次报全，未钉措辞） |
| app.authors.schema.x__validate_route__mutmut_123 | A | 文案 XX 包裹/大写形态变体（字段路径保留） | AC-10.1（只钉路径+一次报全，未钉措辞） |
| app.authors.schema.x__validate_route__mutmut_131 | A | 错误文案 None/形态变体（字段路径保留） | AC-10.1（只钉路径+一次报全，未钉措辞） |
| app.authors.schema.x__validate_route__mutmut_135 | A | 文案 XX 包裹/大写形态变体（字段路径保留） | AC-10.1（只钉路径+一次报全，未钉措辞） |
| app.authors.schema.x__validate_route__mutmut_139 | A | 「期望类型」措辞变体（路径保留） | AC-10.1（未钉期望类型措辞） |
| app.authors.schema.x__validate_route__mutmut_140 | A | 错误文案 None/形态变体（字段路径保留） | AC-10.1（只钉路径+一次报全，未钉措辞） |
| app.authors.schema.x__validate_route__mutmut_145 | A | 文案 XX 包裹/大写形态变体（字段路径保留） | AC-10.1（只钉路径+一次报全，未钉措辞） |
| app.authors.schema.x__validate_route__mutmut_146 | A | 文案 XX 包裹/大写形态变体（字段路径保留） | AC-10.1（只钉路径+一次报全，未钉措辞） |
| app.authors.schema.x__validate_route__mutmut_250 | A | get 缺省 None 落归一分支（{}），行为等价 | 控制流等价推理（归一化已存在） |
| app.authors.schema.x__validate_route__mutmut_252 | A | get 缺省 None 落归一分支（{}），行为等价 | 控制流等价推理（归一化已存在） |
| app.authors.schema.x__validate_route__mutmut_263 | A | 错误文案 None/形态变体（字段路径保留） | AC-10.1（只钉路径+一次报全，未钉措辞） |
| app.authors.schema.x__validate_route__mutmut_267 | A | 文案 XX 包裹/大写形态变体（字段路径保留） | AC-10.1（只钉路径+一次报全，未钉措辞） |
| app.authors.schema.x__validate_route__mutmut_268 | A | 文案/形态变体（字段路径保留） | AC-10.1（只钉路径+一次报全，未钉措辞） |
| app.authors.schema.x__validate_route__mutmut_280 | A | 文案/形态变体（字段路径保留） | AC-10.1（只钉路径+一次报全，未钉措辞） |
| app.authors.schema.x__validate_route__mutmut_34 | A | 错误文案 None/形态变体（字段路径保留） | AC-10.1（只钉路径+一次报全，未钉措辞） |
| app.authors.schema.x__validate_route__mutmut_38 | A | 文案 XX 包裹/大写形态变体（字段路径保留） | AC-10.1（只钉路径+一次报全，未钉措辞） |
| app.authors.schema.x__validate_route__mutmut_42 | A | 「期望类型」措辞变体（路径保留） | AC-10.1（未钉期望类型措辞） |
| app.authors.schema.x__validate_route__mutmut_43 | A | 错误文案 None/形态变体（字段路径保留） | AC-10.1（只钉路径+一次报全，未钉措辞） |
| app.authors.schema.x__validate_route__mutmut_50 | A | 文案 XX 包裹/大写形态变体（字段路径保留） | AC-10.1（只钉路径+一次报全，未钉措辞） |
| app.authors.schema.x__validate_route__mutmut_51 | A | 文案 XX 包裹/大写形态变体（字段路径保留） | AC-10.1（只钉路径+一次报全，未钉措辞） |
| app.authors.schema.x__validate_route__mutmut_93 | A | 数值边界变体（lo/hi 移位或移除） | 数值边界无条款（C1-5a 数值缺省先例；唯一钉死边界 max_attempts(1-10) 已由边界测试闭合） |
| app.authors.schema.x__validate_route__mutmut_94 | A | 数值边界变体（lo/hi 移位或移除） | 数值边界无条款（C1-5a 数值缺省先例；唯一钉死边界 max_attempts(1-10) 已由边界测试闭合） |
| app.authors.schema.x_default_author_config__mutmut_105 | A | 缺省数值变体（600/1400/min_count/recent_n/slices/per_block 等） | 数值缺省无条款（C1-5a recent_n/threshold 先例） |
| app.authors.schema.x_default_author_config__mutmut_127 | A | 缺省配置可选键改名（可选字段形态，校验仍合法、下游行为不变） | 缺省配置可选键形态无条款（任务书§2） |
| app.authors.schema.x_default_author_config__mutmut_128 | A | 缺省配置可选键改名（可选字段形态，校验仍合法、下游行为不变） | 缺省配置可选键形态无条款（任务书§2） |
| app.authors.schema.x_default_author_config__mutmut_137 | A | 缺省数值变体（600/1400/min_count/recent_n/slices/per_block 等） | 数值缺省无条款（C1-5a recent_n/threshold 先例） |
| app.authors.schema.x_default_author_config__mutmut_140 | A | 缺省数值变体（600/1400/min_count/recent_n/slices/per_block 等） | 数值缺省无条款（C1-5a recent_n/threshold 先例） |
| app.authors.schema.x_default_author_config__mutmut_15 | A | 缺省配置可选键改名（可选字段形态，校验仍合法、下游行为不变） | 缺省配置可选键形态无条款（任务书§2） |
| app.authors.schema.x_default_author_config__mutmut_165 | A | 缺省数值变体（600/1400/min_count/recent_n/slices/per_block 等） | 数值缺省无条款（C1-5a recent_n/threshold 先例） |
| app.authors.schema.x_default_author_config__mutmut_18 | A | 缺省配置可选键改名（可选字段形态，校验仍合法、下游行为不变） | 缺省配置可选键形态无条款（任务书§2） |
| app.authors.schema.x_default_author_config__mutmut_21 | A | 缺省配置可选键改名（可选字段形态，校验仍合法、下游行为不变） | 缺省配置可选键形态无条款（任务书§2） |
| app.authors.schema.x_default_author_config__mutmut_24 | A | 缺省配置可选键改名（可选字段形态，校验仍合法、下游行为不变） | 缺省配置可选键形态无条款（任务书§2） |
| app.authors.schema.x_default_author_config__mutmut_27 | A | 缺省配置可选键改名（可选字段形态，校验仍合法、下游行为不变） | 缺省配置可选键形态无条款（任务书§2） |
| app.authors.schema.x_default_author_config__mutmut_36 | A | 缺省配置可选键改名（可选字段形态，校验仍合法、下游行为不变） | 缺省配置可选键形态无条款（任务书§2） |
| app.authors.schema.x_default_author_config__mutmut_37 | A | 缺省配置可选键改名（可选字段形态，校验仍合法、下游行为不变） | 缺省配置可选键形态无条款（任务书§2） |
| app.authors.schema.x_default_author_config__mutmut_42 | A | 缺省配置 provenance 占位文案变体 | 缺省配置内容无条款（任务书§2 未钉→A） |
| app.authors.schema.x_default_author_config__mutmut_64 | A | 缺省配置可选键改名（可选字段形态，校验仍合法、下游行为不变） | 缺省配置可选键形态无条款（任务书§2） |
| app.authors.schema.x_default_author_config__mutmut_65 | A | 缺省配置可选键改名（可选字段形态，校验仍合法、下游行为不变） | 缺省配置可选键形态无条款（任务书§2） |
| app.authors.schema.x_default_author_config__mutmut_66 | A | 缺省 think=False→True：兼容字段，实际档位以 think_routing 为准 | docs 字段总表（think 兼容字段）+ 缺省值无条款 |
| app.authors.schema.x_default_author_config__mutmut_75 | A | 缺省数值变体（600/1400/min_count/recent_n/slices/per_block 等） | 数值缺省无条款（C1-5a recent_n/threshold 先例） |
| app.authors.schema.x_default_author_config__mutmut_78 | A | 缺省数值变体（600/1400/min_count/recent_n/slices/per_block 等） | 数值缺省无条款（C1-5a recent_n/threshold 先例） |
| app.authors.schema.x_default_author_config__mutmut_79 | A | 缺省配置可选键改名（可选字段形态，校验仍合法、下游行为不变） | 缺省配置可选键形态无条款（任务书§2） |
| app.authors.schema.x_default_author_config__mutmut_80 | A | 缺省配置可选键改名（可选字段形态，校验仍合法、下游行为不变） | 缺省配置可选键形态无条款（任务书§2） |
| app.authors.schema.x_default_author_config__mutmut_90 | A | 缺省数值变体（600/1400/min_count/recent_n/slices/per_block 等） | 数值缺省无条款（C1-5a recent_n/threshold 先例） |
| app.authors.schema.x_default_author_config__mutmut_95 | A | 缺省数值变体（600/1400/min_count/recent_n/slices/per_block 等） | 数值缺省无条款（C1-5a recent_n/threshold 先例） |
| app.authors.schema.x_load_author_config__mutmut_5 | A | 异常消息头/分隔符措辞变体：路径与全部错误保留，一次报全不变 | AC-10.1（只钉字段路径+一次报全，未钉文案措辞） |
| app.authors.schema.x_load_author_config__mutmut_6 | A | 异常消息头/分隔符措辞变体：路径与全部错误保留，一次报全不变 | AC-10.1（只钉字段路径+一次报全，未钉文案措辞） |
| app.authors.schema.x_load_author_config__mutmut_8 | A | 异常消息头/分隔符措辞变体：路径与全部错误保留，一次报全不变 | AC-10.1（只钉字段路径+一次报全，未钉文案措辞） |
| app.authors.schema.x_validate_author_json__mutmut_3 | A | 顶层非 dict 错误的「实得类型」回显形态变体（(root) 路径保留） | AC-10.1（只钉字段路径+一次报全，未钉实得类型回显） |

## 批次 8b：authors.schema 原子辅助（2026-10-03，C1-6 第二段）

> 本批无 B 类、无 D 类。C 类 83 条全部由批次 8a 测试（`tests/test_mutation_c1_6.py`，
> 配置级触发面同源：max_attempts 边界/footnote_citations/threshold/topic_dedup 等）
> 闭合，不在本清单。豁免 44 条 A 如下。

| mutant 全名 | 类别 | 一句话理由 | 依据条款或推理 |
|---|---|---|---|
| app.authors.schema.x__bool_field__mutmut_11 | A | 文案 XX 包裹/大写形态变体（字段路径保留） | AC-10.1（只钉路径+一次报全，未钉措辞） |
| app.authors.schema.x__bool_field__mutmut_15 | A | 「期望类型」措辞变体（路径保留） | AC-10.1（未钉期望类型措辞） |
| app.authors.schema.x__bool_field__mutmut_16 | A | 错误文案 None/形态变体（字段路径保留） | AC-10.1（只钉路径+一次报全，未钉措辞） |
| app.authors.schema.x__bool_field__mutmut_21 | A | 文案 XX 包裹/大写形态变体（字段路径保留） | AC-10.1（只钉路径+一次报全，未钉措辞） |
| app.authors.schema.x__bool_field__mutmut_22 | A | 文案 XX 包裹/大写形态变体（字段路径保留） | AC-10.1（只钉路径+一次报全，未钉措辞） |
| app.authors.schema.x__bool_field__mutmut_7 | A | 错误文案 None/形态变体（字段路径保留） | AC-10.1（只钉路径+一次报全，未钉措辞） |
| app.authors.schema.x__enum_field__mutmut_11 | A | 文案 XX 包裹/大写形态变体（字段路径保留） | AC-10.1（只钉路径+一次报全，未钉措辞） |
| app.authors.schema.x__enum_field__mutmut_22 | A | 枚举清单展示分隔符形态（成员判定不变） | 文案无措辞条款（枚举判定面已由枚举测试闭合） |
| app.authors.schema.x__enum_field__mutmut_7 | A | 错误文案 None/形态变体（字段路径保留） | AC-10.1（只钉路径+一次报全，未钉措辞） |
| app.authors.schema.x__float_field__mutmut_10 | A | float 缺失分支死代码：全部调用点 required=False，分支不可达 | 调用点核查：_float_field 仅 gates.threshold 一处且 required=False |
| app.authors.schema.x__float_field__mutmut_11 | A | float 缺失分支死代码：全部调用点 required=False，分支不可达 | 调用点核查：_float_field 仅 gates.threshold 一处且 required=False |
| app.authors.schema.x__float_field__mutmut_16 | A | 「期望类型」措辞变体（路径保留） | AC-10.1（未钉期望类型措辞） |
| app.authors.schema.x__float_field__mutmut_17 | A | 错误文案 None/形态变体（字段路径保留） | AC-10.1（只钉路径+一次报全，未钉措辞） |
| app.authors.schema.x__float_field__mutmut_22 | A | 文案 XX 包裹/大写形态变体（字段路径保留） | AC-10.1（只钉路径+一次报全，未钉措辞） |
| app.authors.schema.x__float_field__mutmut_23 | A | 文案 XX 包裹/大写形态变体（字段路径保留） | AC-10.1（只钉路径+一次报全，未钉措辞） |
| app.authors.schema.x__float_field__mutmut_5 | A | float 缺失分支死代码：全部调用点 required=False，分支不可达 | 调用点核查：_float_field 仅 gates.threshold 一处且 required=False |
| app.authors.schema.x__float_field__mutmut_6 | A | float 缺失分支死代码：全部调用点 required=False，分支不可达 | 调用点核查：_float_field 仅 gates.threshold 一处且 required=False |
| app.authors.schema.x__float_field__mutmut_7 | A | float 缺失分支死代码：全部调用点 required=False，分支不可达 | 调用点核查：_float_field 仅 gates.threshold 一处且 required=False |
| app.authors.schema.x__float_field__mutmut_8 | A | float 缺失分支死代码：全部调用点 required=False，分支不可达 | 调用点核查：_float_field 仅 gates.threshold 一处且 required=False |
| app.authors.schema.x__float_field__mutmut_9 | A | float 缺失分支死代码：全部调用点 required=False，分支不可达 | 调用点核查：_float_field 仅 gates.threshold 一处且 required=False |
| app.authors.schema.x__int_field__mutmut_11 | A | 文案 XX 包裹/大写形态变体（字段路径保留） | AC-10.1（只钉路径+一次报全，未钉措辞） |
| app.authors.schema.x__int_field__mutmut_16 | A | 「期望类型」措辞变体（路径保留） | AC-10.1（未钉期望类型措辞） |
| app.authors.schema.x__int_field__mutmut_17 | A | 错误文案 None/形态变体（字段路径保留） | AC-10.1（只钉路径+一次报全，未钉措辞） |
| app.authors.schema.x__int_field__mutmut_22 | A | 文案 XX 包裹/大写形态变体（字段路径保留） | AC-10.1（只钉路径+一次报全，未钉措辞） |
| app.authors.schema.x__int_field__mutmut_23 | A | 文案 XX 包裹/大写形态变体（字段路径保留） | AC-10.1（只钉路径+一次报全，未钉措辞） |
| app.authors.schema.x__int_field__mutmut_29 | A | 错误文案 None/形态变体（字段路径保留） | AC-10.1（只钉路径+一次报全，未钉措辞） |
| app.authors.schema.x__int_field__mutmut_38 | A | 错误文案 None/形态变体（字段路径保留） | AC-10.1（只钉路径+一次报全，未钉措辞） |
| app.authors.schema.x__int_field__mutmut_7 | A | 错误文案 None/形态变体（字段路径保留） | AC-10.1（只钉路径+一次报全，未钉措辞） |
| app.authors.schema.x__require_dict__mutmut_10 | A | 文案 XX 包裹/大写形态变体（字段路径保留） | AC-10.1（只钉路径+一次报全，未钉措辞） |
| app.authors.schema.x__require_dict__mutmut_14 | A | 「期望类型」措辞变体（路径保留） | AC-10.1（未钉期望类型措辞） |
| app.authors.schema.x__require_dict__mutmut_15 | A | 错误文案 None/形态变体（字段路径保留） | AC-10.1（只钉路径+一次报全，未钉措辞） |
| app.authors.schema.x__require_dict__mutmut_20 | A | 文案 XX 包裹/大写形态变体（字段路径保留） | AC-10.1（只钉路径+一次报全，未钉措辞） |
| app.authors.schema.x__require_dict__mutmut_21 | A | 文案 XX 包裹/大写形态变体（字段路径保留） | AC-10.1（只钉路径+一次报全，未钉措辞） |
| app.authors.schema.x__require_dict__mutmut_6 | A | 错误文案 None/形态变体（字段路径保留） | AC-10.1（只钉路径+一次报全，未钉措辞） |
| app.authors.schema.x__require_str__mutmut_10 | A | 文案 XX 包裹/大写形态变体（字段路径保留） | AC-10.1（只钉路径+一次报全，未钉措辞） |
| app.authors.schema.x__require_str__mutmut_16 | A | 错误文案 None/形态变体（字段路径保留） | AC-10.1（只钉路径+一次报全，未钉措辞） |
| app.authors.schema.x__require_str__mutmut_6 | A | 错误文案 None/形态变体（字段路径保留） | AC-10.1（只钉路径+一次报全，未钉措辞） |
| app.authors.schema.x__str_list__mutmut_11 | A | 文案 XX 包裹/大写形态变体（字段路径保留） | AC-10.1（只钉路径+一次报全，未钉措辞） |
| app.authors.schema.x__str_list__mutmut_18 | A | 错误文案 None/形态变体（字段路径保留） | AC-10.1（只钉路径+一次报全，未钉措辞） |
| app.authors.schema.x__str_list__mutmut_22 | A | 文案 XX 包裹/大写形态变体（字段路径保留） | AC-10.1（只钉路径+一次报全，未钉措辞） |
| app.authors.schema.x__str_list__mutmut_7 | A | 错误文案 None/形态变体（字段路径保留） | AC-10.1（只钉路径+一次报全，未钉措辞） |
| app.authors.schema.x__type_err__mutmut_3 | A | 错误文案 None/形态变体（字段路径保留） | AC-10.1（只钉路径+一次报全，未钉措辞） |
| app.authors.schema.x__type_err__mutmut_7 | A | 错误文案 None/形态变体（字段路径保留） | AC-10.1（只钉路径+一次报全，未钉措辞） |
| app.authors.schema.x__validate_template__mutmut_21 | A | 错误文案 None/形态变体（字段路径保留） | AC-10.1（只钉路径+一次报全，未钉措辞） |

## 批次 9：authors 域收官（writer/gates/memory/importer）（2026-10-04，C1-7）

> 本批无 B 类；D 类 0 条。C 类 255 条由 tests/test_mutation_c1_7.py 25 测试闭合，不在本清单。A 类 222 条逐条如下（分诊依据见 C1-7 执行汇报）。

| mutant 全名 | 类别 | 一句话理由 | 依据条款或推理 |
|---|---|---|---|
| app.authors.gates.x_gate_copyright__mutmut_1 | A | not blocks or ngram<2→and：or→and 仅在「blocks 非空且 ngram<2」组合下分叉——ngram<2 为非法配置（schema 2-64），合法域等价 | 调用点核查：schema:202 ngram 2-64；非法配置防御面无条款 |
| app.authors.gates.x_gate_copyright__mutmut_13 | A | b.get('text',None) 缺省变体：schema 必填块 text（C1-6 块字段逐键报路径），缺省分支不可达 | 调用点核查：_validate_memory 块 text 必填 |
| app.authors.gates.x_gate_copyright__mutmut_15 | A | b.get('text',) 缺省变体：同 m13 | 同 m13 |
| app.authors.gates.x_gate_copyright__mutmut_18 | A | b.get('text','XXXX') 缺省变体：同 m13 | 同 m13 |
| app.authors.gates.x_gate_copyright__mutmut_25 | A | range(len(src)+ngram+1)：越界切片产生短于 ngram 的片段，不可能与 ngram 长的正文 gram 相等——等价 | 切片语义推理：g=len(t[i:i+ngram]) 恒为 ngram（t 足长），短片段不命中 |
| app.authors.gates.x_gate_copyright__mutmut_26 | A | range(len(src)-ngram+2)：仅多一个越界短片段，同 m25 等价 | 同 m25 |
| app.authors.gates.x_gate_copyright__mutmut_29 | A | range(len(t)+ngram+1)：越界短片段惰性，同 m25 | 同 m25 |
| app.authors.gates.x_gate_copyright__mutmut_30 | A | range(len(t)-ngram+2)：同 m26 | 同 m26 |
| app.authors.gates.x_gate_copyright__mutmut_38 | A | stats['copyright_ngram_hits']＝None：stats 记录值无条款 | verdict 统一形态只钉顶层四键 |
| app.authors.gates.x_gate_copyright__mutmut_39 | A | copyright_ngram_hits 键名→XX：stats 键名无条款 | 同上 |
| app.authors.gates.x_gate_copyright__mutmut_40 | A | copyright_ngram_hits 键名→大写：同 m39 | 同上 |
| app.authors.gates.x_gate_copyright__mutmut_46 | A | issue 文案分隔符「 | 」→XX：文案无条款 | AC-11.2/AC-11.4 只钉拒收，未钉 issue 文案 |
| app.authors.gates.x_gate_copyright__mutmut_47 | A | issue 文案 gram 截断 [:24]→[:25]：同上 | 同上 |
| app.authors.gates.x_gate_copyright__mutmut_48 | A | issue 文案 gram 数 [:3]→[:4]：同上 | 同上 |
| app.authors.gates.x_gate_copyright__mutmut_49 | A | warn 文案→None：warn 不改判定，文案无条款 | verdict 统一形态：warns 不参与 passed 判定 |
| app.authors.gates.x_gate_copyright__mutmut_51 | A | warn 文案截断 [:24]→[:25]：文案无条款 | AC-11.2/AC-11.4 文案先例 |
| app.authors.gates.x_gate_fingerprint__mutmut_10 | A | warn 文案→None：warn 仅提示不改判定，文案无条款 | verdict 统一形态：warns 不参与 passed 判定 |
| app.authors.gates.x_gate_fingerprint__mutmut_5 | A | stats['fingerprint_hits']＝None：stats 记录值无条款 | verdict 统一形态只钉顶层四键；stats 明细无条款 |
| app.authors.gates.x_gate_fingerprint__mutmut_6 | A | fingerprint_hits 键名→XX：stats 键名无条款 | 同上 |
| app.authors.gates.x_gate_fingerprint__mutmut_7 | A | fingerprint_hits 键名→大写：同 m6 | 同上 |
| app.authors.gates.x_gate_length__mutmut_10 | A | get('min',) 缺省变体：同 m8 | 同 m8 |
| app.authors.gates.x_gate_length__mutmut_13 | A | get('min',1) 缺省值变体：min 必填使缺省不可达；缺省常数无条款 | 调用点核查：schema min 必填 |
| app.authors.gates.x_gate_length__mutmut_15 | A | get('max',None) 缺省变体：同 m14 | 同 m14 |
| app.authors.gates.x_gate_length__mutmut_17 | A | get('max',) 缺省变体：同 m14 | 同 m14 |
| app.authors.gates.x_gate_length__mutmut_20 | A | max 缺省 1e9→90：max 必填使缺省不可达；缺省常数无条款 | 调用点核查：schema max 必填 |
| app.authors.gates.x_gate_length__mutmut_21 | A | max 缺省 1e9→11**9：同 m20 | 同 m20 |
| app.authors.gates.x_gate_length__mutmut_22 | A | max 缺省 1e9→10**10：同 m20 | 同 m20 |
| app.authors.gates.x_gate_length__mutmut_23 | A | n<lo→n<=lo：恰等于下限的边界语义无条款（沿 C1-5a「数值边界无条款」先例） | docs 未钉 min/max 含等性；唯一钉死边界仅 rewrite.max_attempts |
| app.authors.gates.x_gate_length__mutmut_25 | A | n>hi→n>=hi：同 m23（上边界含等性未钉） | 同 m23 |
| app.authors.gates.x_gate_length__mutmut_8 | A | get('min',None) 缺省变体：schema 必填 min（_validate_gates _int_field min/max），缺省分支不可达 | 调用点核查：authors/schema.py:186 min/max 必填校验 |
| app.authors.gates.x_gate_topic_dedup__mutmut_16 | A | sim>=threshold→>：恰等于阈值的边界含等性无条款（沿数值边界先例） | docs 未钉 threshold 含等性 |
| app.authors.gates.x_gate_topic_dedup__mutmut_5 | A | not t or not r→and：t/r 任一为空的继续条件在结果上等价（dice 空串→0.0 不判重；双空 continue 同原） | 真值表推理：四组合输出全部一致 |
| app.authors.gates.x_gate_topic_dedup__mutmut_8 | A | continue→break：仅近期标题归一为空串（空白标题）时可达，生产标题恒非空（str(...) or 「（无题）」） | 调用点核查：run_write/pipeline 标题构造恒非空 |
| app.authors.gates.x_norm__mutmut_1 | A | norm().lower()→.upper()：比较两侧（正文/块、标题/近期题）均经同一 norm 自洽折叠，匹配结果等价 | 控制流推理：norm 只用于门内两两比较，无跨系统大小写契约 |
| app.authors.gates.xǁVerdictǁfeedback__mutmut_3 | A | 分隔符「；」→XX：违规说明仍完整到达，分隔措辞无条款 | AC-11.2 只钉「附违规摘要」行为，未钉分隔符措辞（沿全系列措辞先例） |
| app.authors.gates.xǁVerdictǁfeedback__mutmut_5 | A | 「（无）」→XX：fallback 仅 issues+warns 全空时可达，gated 重试只在门禁失败（issues 非空）时调用 | 调用点核查：pipeline 仅 on_gate_fail 调 feedback；文案措辞无条款 |
| app.authors.importer.x_import_author_json__mutmut_15 | A | AuthorConfigError(None)：新作者缺 model 仍拒（异常类型不变），文案无条款 | docstring「新作者必须给 model」语义不变；文案措辞先例 |
| app.authors.importer.x_import_author_json__mutmut_18 | A | Author(model=None)：随后 if model: author.model=model 必然回填（新作者 model 已前置强制），等价 | 控制流推理：m15 guard 保证 model 真值 |
| app.authors.importer.x_import_author_json__mutmut_20 | A | Author(name,name) 缺 model 形参：列默认 None 后同 m18 回填，等价 | 同 m18 |
| app.authors.importer.x_import_author_json__mutmut_4 | A | deepcopy→copy：load_author_config 纯校验不改写入参（C1-6 全批验证），共享嵌套无行为差异 | 调用点核查：schema 校验器只读；输入不改写 |
| app.authors.importer.x_render_persona_prompt__mutmut_10 | A | persona 卡渲染文案/取值形态变体（XX 包裹/大写/get 缺省/None 回显/分隔符），渲染文本无条款 | 技术书 §2 模块表 importer「映射[纯]」+ 模块 docstring：persona_prompt=identity 扁平渲染（后台展示兼容），格式无条款 |
| app.authors.importer.x_render_persona_prompt__mutmut_100 | A | persona 卡渲染文案/取值形态变体（XX 包裹/大写/get 缺省/None 回显/分隔符），渲染文本无条款 | 技术书 §2 模块表 importer「映射[纯]」+ 模块 docstring：persona_prompt=identity 扁平渲染（后台展示兼容），格式无条款 |
| app.authors.importer.x_render_persona_prompt__mutmut_101 | A | persona 卡渲染文案/取值形态变体（XX 包裹/大写/get 缺省/None 回显/分隔符），渲染文本无条款 | 技术书 §2 模块表 importer「映射[纯]」+ 模块 docstring：persona_prompt=identity 扁平渲染（后台展示兼容），格式无条款 |
| app.authors.importer.x_render_persona_prompt__mutmut_103 | A | persona 卡渲染文案/取值形态变体（XX 包裹/大写/get 缺省/None 回显/分隔符），渲染文本无条款 | 技术书 §2 模块表 importer「映射[纯]」+ 模块 docstring：persona_prompt=identity 扁平渲染（后台展示兼容），格式无条款 |
| app.authors.importer.x_render_persona_prompt__mutmut_106 | A | persona 卡渲染文案/取值形态变体（XX 包裹/大写/get 缺省/None 回显/分隔符），渲染文本无条款 | 技术书 §2 模块表 importer「映射[纯]」+ 模块 docstring：persona_prompt=identity 扁平渲染（后台展示兼容），格式无条款 |
| app.authors.importer.x_render_persona_prompt__mutmut_107 | A | persona 卡渲染文案/取值形态变体（XX 包裹/大写/get 缺省/None 回显/分隔符），渲染文本无条款 | 技术书 §2 模块表 importer「映射[纯]」+ 模块 docstring：persona_prompt=identity 扁平渲染（后台展示兼容），格式无条款 |
| app.authors.importer.x_render_persona_prompt__mutmut_108 | A | persona 卡渲染文案/取值形态变体（XX 包裹/大写/get 缺省/None 回显/分隔符），渲染文本无条款 | 技术书 §2 模块表 importer「映射[纯]」+ 模块 docstring：persona_prompt=identity 扁平渲染（后台展示兼容），格式无条款 |
| app.authors.importer.x_render_persona_prompt__mutmut_110 | A | persona 卡渲染文案/取值形态变体（XX 包裹/大写/get 缺省/None 回显/分隔符），渲染文本无条款 | 技术书 §2 模块表 importer「映射[纯]」+ 模块 docstring：persona_prompt=identity 扁平渲染（后台展示兼容），格式无条款 |
| app.authors.importer.x_render_persona_prompt__mutmut_12 | A | persona 卡渲染文案/取值形态变体（XX 包裹/大写/get 缺省/None 回显/分隔符），渲染文本无条款 | 技术书 §2 模块表 importer「映射[纯]」+ 模块 docstring：persona_prompt=identity 扁平渲染（后台展示兼容），格式无条款 |
| app.authors.importer.x_render_persona_prompt__mutmut_13 | A | persona 卡渲染文案/取值形态变体（XX 包裹/大写/get 缺省/None 回显/分隔符），渲染文本无条款 | 技术书 §2 模块表 importer「映射[纯]」+ 模块 docstring：persona_prompt=identity 扁平渲染（后台展示兼容），格式无条款 |
| app.authors.importer.x_render_persona_prompt__mutmut_14 | A | persona 卡渲染文案/取值形态变体（XX 包裹/大写/get 缺省/None 回显/分隔符），渲染文本无条款 | 技术书 §2 模块表 importer「映射[纯]」+ 模块 docstring：persona_prompt=identity 扁平渲染（后台展示兼容），格式无条款 |
| app.authors.importer.x_render_persona_prompt__mutmut_15 | A | persona 卡渲染文案/取值形态变体（XX 包裹/大写/get 缺省/None 回显/分隔符），渲染文本无条款 | 技术书 §2 模块表 importer「映射[纯]」+ 模块 docstring：persona_prompt=identity 扁平渲染（后台展示兼容），格式无条款 |
| app.authors.importer.x_render_persona_prompt__mutmut_16 | A | persona 卡渲染文案/取值形态变体（XX 包裹/大写/get 缺省/None 回显/分隔符），渲染文本无条款 | 技术书 §2 模块表 importer「映射[纯]」+ 模块 docstring：persona_prompt=identity 扁平渲染（后台展示兼容），格式无条款 |
| app.authors.importer.x_render_persona_prompt__mutmut_17 | A | persona 卡渲染文案/取值形态变体（XX 包裹/大写/get 缺省/None 回显/分隔符），渲染文本无条款 | 技术书 §2 模块表 importer「映射[纯]」+ 模块 docstring：persona_prompt=identity 扁平渲染（后台展示兼容），格式无条款 |
| app.authors.importer.x_render_persona_prompt__mutmut_18 | A | persona 卡渲染文案/取值形态变体（XX 包裹/大写/get 缺省/None 回显/分隔符），渲染文本无条款 | 技术书 §2 模块表 importer「映射[纯]」+ 模块 docstring：persona_prompt=identity 扁平渲染（后台展示兼容），格式无条款 |
| app.authors.importer.x_render_persona_prompt__mutmut_19 | A | persona 卡渲染文案/取值形态变体（XX 包裹/大写/get 缺省/None 回显/分隔符），渲染文本无条款 | 技术书 §2 模块表 importer「映射[纯]」+ 模块 docstring：persona_prompt=identity 扁平渲染（后台展示兼容），格式无条款 |
| app.authors.importer.x_render_persona_prompt__mutmut_20 | A | persona 卡渲染文案/取值形态变体（XX 包裹/大写/get 缺省/None 回显/分隔符），渲染文本无条款 | 技术书 §2 模块表 importer「映射[纯]」+ 模块 docstring：persona_prompt=identity 扁平渲染（后台展示兼容），格式无条款 |
| app.authors.importer.x_render_persona_prompt__mutmut_21 | A | persona 卡渲染文案/取值形态变体（XX 包裹/大写/get 缺省/None 回显/分隔符），渲染文本无条款 | 技术书 §2 模块表 importer「映射[纯]」+ 模块 docstring：persona_prompt=identity 扁平渲染（后台展示兼容），格式无条款 |
| app.authors.importer.x_render_persona_prompt__mutmut_22 | A | persona 卡渲染文案/取值形态变体（XX 包裹/大写/get 缺省/None 回显/分隔符），渲染文本无条款 | 技术书 §2 模块表 importer「映射[纯]」+ 模块 docstring：persona_prompt=identity 扁平渲染（后台展示兼容），格式无条款 |
| app.authors.importer.x_render_persona_prompt__mutmut_23 | A | persona 卡渲染文案/取值形态变体（XX 包裹/大写/get 缺省/None 回显/分隔符），渲染文本无条款 | 技术书 §2 模块表 importer「映射[纯]」+ 模块 docstring：persona_prompt=identity 扁平渲染（后台展示兼容），格式无条款 |
| app.authors.importer.x_render_persona_prompt__mutmut_24 | A | persona 卡渲染文案/取值形态变体（XX 包裹/大写/get 缺省/None 回显/分隔符），渲染文本无条款 | 技术书 §2 模块表 importer「映射[纯]」+ 模块 docstring：persona_prompt=identity 扁平渲染（后台展示兼容），格式无条款 |
| app.authors.importer.x_render_persona_prompt__mutmut_25 | A | persona 卡渲染文案/取值形态变体（XX 包裹/大写/get 缺省/None 回显/分隔符），渲染文本无条款 | 技术书 §2 模块表 importer「映射[纯]」+ 模块 docstring：persona_prompt=identity 扁平渲染（后台展示兼容），格式无条款 |
| app.authors.importer.x_render_persona_prompt__mutmut_26 | A | persona 卡渲染文案/取值形态变体（XX 包裹/大写/get 缺省/None 回显/分隔符），渲染文本无条款 | 技术书 §2 模块表 importer「映射[纯]」+ 模块 docstring：persona_prompt=identity 扁平渲染（后台展示兼容），格式无条款 |
| app.authors.importer.x_render_persona_prompt__mutmut_27 | A | persona 卡渲染文案/取值形态变体（XX 包裹/大写/get 缺省/None 回显/分隔符），渲染文本无条款 | 技术书 §2 模块表 importer「映射[纯]」+ 模块 docstring：persona_prompt=identity 扁平渲染（后台展示兼容），格式无条款 |
| app.authors.importer.x_render_persona_prompt__mutmut_28 | A | persona 卡渲染文案/取值形态变体（XX 包裹/大写/get 缺省/None 回显/分隔符），渲染文本无条款 | 技术书 §2 模块表 importer「映射[纯]」+ 模块 docstring：persona_prompt=identity 扁平渲染（后台展示兼容），格式无条款 |
| app.authors.importer.x_render_persona_prompt__mutmut_29 | A | persona 卡渲染文案/取值形态变体（XX 包裹/大写/get 缺省/None 回显/分隔符），渲染文本无条款 | 技术书 §2 模块表 importer「映射[纯]」+ 模块 docstring：persona_prompt=identity 扁平渲染（后台展示兼容），格式无条款 |
| app.authors.importer.x_render_persona_prompt__mutmut_30 | A | persona 卡渲染文案/取值形态变体（XX 包裹/大写/get 缺省/None 回显/分隔符），渲染文本无条款 | 技术书 §2 模块表 importer「映射[纯]」+ 模块 docstring：persona_prompt=identity 扁平渲染（后台展示兼容），格式无条款 |
| app.authors.importer.x_render_persona_prompt__mutmut_31 | A | persona 卡渲染文案/取值形态变体（XX 包裹/大写/get 缺省/None 回显/分隔符），渲染文本无条款 | 技术书 §2 模块表 importer「映射[纯]」+ 模块 docstring：persona_prompt=identity 扁平渲染（后台展示兼容），格式无条款 |
| app.authors.importer.x_render_persona_prompt__mutmut_32 | A | persona 卡渲染文案/取值形态变体（XX 包裹/大写/get 缺省/None 回显/分隔符），渲染文本无条款 | 技术书 §2 模块表 importer「映射[纯]」+ 模块 docstring：persona_prompt=identity 扁平渲染（后台展示兼容），格式无条款 |
| app.authors.importer.x_render_persona_prompt__mutmut_33 | A | persona 卡渲染文案/取值形态变体（XX 包裹/大写/get 缺省/None 回显/分隔符），渲染文本无条款 | 技术书 §2 模块表 importer「映射[纯]」+ 模块 docstring：persona_prompt=identity 扁平渲染（后台展示兼容），格式无条款 |
| app.authors.importer.x_render_persona_prompt__mutmut_34 | A | persona 卡渲染文案/取值形态变体（XX 包裹/大写/get 缺省/None 回显/分隔符），渲染文本无条款 | 技术书 §2 模块表 importer「映射[纯]」+ 模块 docstring：persona_prompt=identity 扁平渲染（后台展示兼容），格式无条款 |
| app.authors.importer.x_render_persona_prompt__mutmut_35 | A | persona 卡渲染文案/取值形态变体（XX 包裹/大写/get 缺省/None 回显/分隔符），渲染文本无条款 | 技术书 §2 模块表 importer「映射[纯]」+ 模块 docstring：persona_prompt=identity 扁平渲染（后台展示兼容），格式无条款 |
| app.authors.importer.x_render_persona_prompt__mutmut_36 | A | persona 卡渲染文案/取值形态变体（XX 包裹/大写/get 缺省/None 回显/分隔符），渲染文本无条款 | 技术书 §2 模块表 importer「映射[纯]」+ 模块 docstring：persona_prompt=identity 扁平渲染（后台展示兼容），格式无条款 |
| app.authors.importer.x_render_persona_prompt__mutmut_37 | A | persona 卡渲染文案/取值形态变体（XX 包裹/大写/get 缺省/None 回显/分隔符），渲染文本无条款 | 技术书 §2 模块表 importer「映射[纯]」+ 模块 docstring：persona_prompt=identity 扁平渲染（后台展示兼容），格式无条款 |
| app.authors.importer.x_render_persona_prompt__mutmut_38 | A | persona 卡渲染文案/取值形态变体（XX 包裹/大写/get 缺省/None 回显/分隔符），渲染文本无条款 | 技术书 §2 模块表 importer「映射[纯]」+ 模块 docstring：persona_prompt=identity 扁平渲染（后台展示兼容），格式无条款 |
| app.authors.importer.x_render_persona_prompt__mutmut_39 | A | persona 卡渲染文案/取值形态变体（XX 包裹/大写/get 缺省/None 回显/分隔符），渲染文本无条款 | 技术书 §2 模块表 importer「映射[纯]」+ 模块 docstring：persona_prompt=identity 扁平渲染（后台展示兼容），格式无条款 |
| app.authors.importer.x_render_persona_prompt__mutmut_40 | A | persona 卡渲染文案/取值形态变体（XX 包裹/大写/get 缺省/None 回显/分隔符），渲染文本无条款 | 技术书 §2 模块表 importer「映射[纯]」+ 模块 docstring：persona_prompt=identity 扁平渲染（后台展示兼容），格式无条款 |
| app.authors.importer.x_render_persona_prompt__mutmut_41 | A | persona 卡渲染文案/取值形态变体（XX 包裹/大写/get 缺省/None 回显/分隔符），渲染文本无条款 | 技术书 §2 模块表 importer「映射[纯]」+ 模块 docstring：persona_prompt=identity 扁平渲染（后台展示兼容），格式无条款 |
| app.authors.importer.x_render_persona_prompt__mutmut_42 | A | persona 卡渲染文案/取值形态变体（XX 包裹/大写/get 缺省/None 回显/分隔符），渲染文本无条款 | 技术书 §2 模块表 importer「映射[纯]」+ 模块 docstring：persona_prompt=identity 扁平渲染（后台展示兼容），格式无条款 |
| app.authors.importer.x_render_persona_prompt__mutmut_43 | A | persona 卡渲染文案/取值形态变体（XX 包裹/大写/get 缺省/None 回显/分隔符），渲染文本无条款 | 技术书 §2 模块表 importer「映射[纯]」+ 模块 docstring：persona_prompt=identity 扁平渲染（后台展示兼容），格式无条款 |
| app.authors.importer.x_render_persona_prompt__mutmut_44 | A | persona 卡渲染文案/取值形态变体（XX 包裹/大写/get 缺省/None 回显/分隔符），渲染文本无条款 | 技术书 §2 模块表 importer「映射[纯]」+ 模块 docstring：persona_prompt=identity 扁平渲染（后台展示兼容），格式无条款 |
| app.authors.importer.x_render_persona_prompt__mutmut_45 | A | persona 卡渲染文案/取值形态变体（XX 包裹/大写/get 缺省/None 回显/分隔符），渲染文本无条款 | 技术书 §2 模块表 importer「映射[纯]」+ 模块 docstring：persona_prompt=identity 扁平渲染（后台展示兼容），格式无条款 |
| app.authors.importer.x_render_persona_prompt__mutmut_46 | A | persona 卡渲染文案/取值形态变体（XX 包裹/大写/get 缺省/None 回显/分隔符），渲染文本无条款 | 技术书 §2 模块表 importer「映射[纯]」+ 模块 docstring：persona_prompt=identity 扁平渲染（后台展示兼容），格式无条款 |
| app.authors.importer.x_render_persona_prompt__mutmut_48 | A | persona 卡渲染文案/取值形态变体（XX 包裹/大写/get 缺省/None 回显/分隔符），渲染文本无条款 | 技术书 §2 模块表 importer「映射[纯]」+ 模块 docstring：persona_prompt=identity 扁平渲染（后台展示兼容），格式无条款 |
| app.authors.importer.x_render_persona_prompt__mutmut_5 | A | persona 卡渲染文案/取值形态变体（XX 包裹/大写/get 缺省/None 回显/分隔符），渲染文本无条款 | 技术书 §2 模块表 importer「映射[纯]」+ 模块 docstring：persona_prompt=identity 扁平渲染（后台展示兼容），格式无条款 |
| app.authors.importer.x_render_persona_prompt__mutmut_50 | A | persona 卡渲染文案/取值形态变体（XX 包裹/大写/get 缺省/None 回显/分隔符），渲染文本无条款 | 技术书 §2 模块表 importer「映射[纯]」+ 模块 docstring：persona_prompt=identity 扁平渲染（后台展示兼容），格式无条款 |
| app.authors.importer.x_render_persona_prompt__mutmut_51 | A | persona 卡渲染文案/取值形态变体（XX 包裹/大写/get 缺省/None 回显/分隔符），渲染文本无条款 | 技术书 §2 模块表 importer「映射[纯]」+ 模块 docstring：persona_prompt=identity 扁平渲染（后台展示兼容），格式无条款 |
| app.authors.importer.x_render_persona_prompt__mutmut_52 | A | persona 卡渲染文案/取值形态变体（XX 包裹/大写/get 缺省/None 回显/分隔符），渲染文本无条款 | 技术书 §2 模块表 importer「映射[纯]」+ 模块 docstring：persona_prompt=identity 扁平渲染（后台展示兼容），格式无条款 |
| app.authors.importer.x_render_persona_prompt__mutmut_54 | A | persona 卡渲染文案/取值形态变体（XX 包裹/大写/get 缺省/None 回显/分隔符），渲染文本无条款 | 技术书 §2 模块表 importer「映射[纯]」+ 模块 docstring：persona_prompt=identity 扁平渲染（后台展示兼容），格式无条款 |
| app.authors.importer.x_render_persona_prompt__mutmut_55 | A | persona 卡渲染文案/取值形态变体（XX 包裹/大写/get 缺省/None 回显/分隔符），渲染文本无条款 | 技术书 §2 模块表 importer「映射[纯]」+ 模块 docstring：persona_prompt=identity 扁平渲染（后台展示兼容），格式无条款 |
| app.authors.importer.x_render_persona_prompt__mutmut_56 | A | persona 卡渲染文案/取值形态变体（XX 包裹/大写/get 缺省/None 回显/分隔符），渲染文本无条款 | 技术书 §2 模块表 importer「映射[纯]」+ 模块 docstring：persona_prompt=identity 扁平渲染（后台展示兼容），格式无条款 |
| app.authors.importer.x_render_persona_prompt__mutmut_58 | A | persona 卡渲染文案/取值形态变体（XX 包裹/大写/get 缺省/None 回显/分隔符），渲染文本无条款 | 技术书 §2 模块表 importer「映射[纯]」+ 模块 docstring：persona_prompt=identity 扁平渲染（后台展示兼容），格式无条款 |
| app.authors.importer.x_render_persona_prompt__mutmut_6 | A | persona 卡渲染文案/取值形态变体（XX 包裹/大写/get 缺省/None 回显/分隔符），渲染文本无条款 | 技术书 §2 模块表 importer「映射[纯]」+ 模块 docstring：persona_prompt=identity 扁平渲染（后台展示兼容），格式无条款 |
| app.authors.importer.x_render_persona_prompt__mutmut_60 | A | persona 卡渲染文案/取值形态变体（XX 包裹/大写/get 缺省/None 回显/分隔符），渲染文本无条款 | 技术书 §2 模块表 importer「映射[纯]」+ 模块 docstring：persona_prompt=identity 扁平渲染（后台展示兼容），格式无条款 |
| app.authors.importer.x_render_persona_prompt__mutmut_61 | A | persona 卡渲染文案/取值形态变体（XX 包裹/大写/get 缺省/None 回显/分隔符），渲染文本无条款 | 技术书 §2 模块表 importer「映射[纯]」+ 模块 docstring：persona_prompt=identity 扁平渲染（后台展示兼容），格式无条款 |
| app.authors.importer.x_render_persona_prompt__mutmut_62 | A | persona 卡渲染文案/取值形态变体（XX 包裹/大写/get 缺省/None 回显/分隔符），渲染文本无条款 | 技术书 §2 模块表 importer「映射[纯]」+ 模块 docstring：persona_prompt=identity 扁平渲染（后台展示兼容），格式无条款 |
| app.authors.importer.x_render_persona_prompt__mutmut_64 | A | persona 卡渲染文案/取值形态变体（XX 包裹/大写/get 缺省/None 回显/分隔符），渲染文本无条款 | 技术书 §2 模块表 importer「映射[纯]」+ 模块 docstring：persona_prompt=identity 扁平渲染（后台展示兼容），格式无条款 |
| app.authors.importer.x_render_persona_prompt__mutmut_65 | A | persona 卡渲染文案/取值形态变体（XX 包裹/大写/get 缺省/None 回显/分隔符），渲染文本无条款 | 技术书 §2 模块表 importer「映射[纯]」+ 模块 docstring：persona_prompt=identity 扁平渲染（后台展示兼容），格式无条款 |
| app.authors.importer.x_render_persona_prompt__mutmut_66 | A | persona 卡渲染文案/取值形态变体（XX 包裹/大写/get 缺省/None 回显/分隔符），渲染文本无条款 | 技术书 §2 模块表 importer「映射[纯]」+ 模块 docstring：persona_prompt=identity 扁平渲染（后台展示兼容），格式无条款 |
| app.authors.importer.x_render_persona_prompt__mutmut_68 | A | persona 卡渲染文案/取值形态变体（XX 包裹/大写/get 缺省/None 回显/分隔符），渲染文本无条款 | 技术书 §2 模块表 importer「映射[纯]」+ 模块 docstring：persona_prompt=identity 扁平渲染（后台展示兼容），格式无条款 |
| app.authors.importer.x_render_persona_prompt__mutmut_70 | A | persona 卡渲染文案/取值形态变体（XX 包裹/大写/get 缺省/None 回显/分隔符），渲染文本无条款 | 技术书 §2 模块表 importer「映射[纯]」+ 模块 docstring：persona_prompt=identity 扁平渲染（后台展示兼容），格式无条款 |
| app.authors.importer.x_render_persona_prompt__mutmut_71 | A | persona 卡渲染文案/取值形态变体（XX 包裹/大写/get 缺省/None 回显/分隔符），渲染文本无条款 | 技术书 §2 模块表 importer「映射[纯]」+ 模块 docstring：persona_prompt=identity 扁平渲染（后台展示兼容），格式无条款 |
| app.authors.importer.x_render_persona_prompt__mutmut_72 | A | persona 卡渲染文案/取值形态变体（XX 包裹/大写/get 缺省/None 回显/分隔符），渲染文本无条款 | 技术书 §2 模块表 importer「映射[纯]」+ 模块 docstring：persona_prompt=identity 扁平渲染（后台展示兼容），格式无条款 |
| app.authors.importer.x_render_persona_prompt__mutmut_74 | A | persona 卡渲染文案/取值形态变体（XX 包裹/大写/get 缺省/None 回显/分隔符），渲染文本无条款 | 技术书 §2 模块表 importer「映射[纯]」+ 模块 docstring：persona_prompt=identity 扁平渲染（后台展示兼容），格式无条款 |
| app.authors.importer.x_render_persona_prompt__mutmut_75 | A | persona 卡渲染文案/取值形态变体（XX 包裹/大写/get 缺省/None 回显/分隔符），渲染文本无条款 | 技术书 §2 模块表 importer「映射[纯]」+ 模块 docstring：persona_prompt=identity 扁平渲染（后台展示兼容），格式无条款 |
| app.authors.importer.x_render_persona_prompt__mutmut_76 | A | persona 卡渲染文案/取值形态变体（XX 包裹/大写/get 缺省/None 回显/分隔符），渲染文本无条款 | 技术书 §2 模块表 importer「映射[纯]」+ 模块 docstring：persona_prompt=identity 扁平渲染（后台展示兼容），格式无条款 |
| app.authors.importer.x_render_persona_prompt__mutmut_8 | A | persona 卡渲染文案/取值形态变体（XX 包裹/大写/get 缺省/None 回显/分隔符），渲染文本无条款 | 技术书 §2 模块表 importer「映射[纯]」+ 模块 docstring：persona_prompt=identity 扁平渲染（后台展示兼容），格式无条款 |
| app.authors.importer.x_render_persona_prompt__mutmut_80 | A | persona 卡渲染文案/取值形态变体（XX 包裹/大写/get 缺省/None 回显/分隔符），渲染文本无条款 | 技术书 §2 模块表 importer「映射[纯]」+ 模块 docstring：persona_prompt=identity 扁平渲染（后台展示兼容），格式无条款 |
| app.authors.importer.x_render_persona_prompt__mutmut_81 | A | persona 卡渲染文案/取值形态变体（XX 包裹/大写/get 缺省/None 回显/分隔符），渲染文本无条款 | 技术书 §2 模块表 importer「映射[纯]」+ 模块 docstring：persona_prompt=identity 扁平渲染（后台展示兼容），格式无条款 |
| app.authors.importer.x_render_persona_prompt__mutmut_82 | A | persona 卡渲染文案/取值形态变体（XX 包裹/大写/get 缺省/None 回显/分隔符），渲染文本无条款 | 技术书 §2 模块表 importer「映射[纯]」+ 模块 docstring：persona_prompt=identity 扁平渲染（后台展示兼容），格式无条款 |
| app.authors.importer.x_render_persona_prompt__mutmut_9 | A | persona 卡渲染文案/取值形态变体（XX 包裹/大写/get 缺省/None 回显/分隔符），渲染文本无条款 | 技术书 §2 模块表 importer「映射[纯]」+ 模块 docstring：persona_prompt=identity 扁平渲染（后台展示兼容），格式无条款 |
| app.authors.importer.x_render_persona_prompt__mutmut_95 | A | persona 卡渲染文案/取值形态变体（XX 包裹/大写/get 缺省/None 回显/分隔符），渲染文本无条款 | 技术书 §2 模块表 importer「映射[纯]」+ 模块 docstring：persona_prompt=identity 扁平渲染（后台展示兼容），格式无条款 |
| app.authors.importer.x_render_persona_prompt__mutmut_97 | A | persona 卡渲染文案/取值形态变体（XX 包裹/大写/get 缺省/None 回显/分隔符），渲染文本无条款 | 技术书 §2 模块表 importer「映射[纯]」+ 模块 docstring：persona_prompt=identity 扁平渲染（后台展示兼容），格式无条款 |
| app.authors.importer.x_roundtrip_check__mutmut_11 | A | 「DB 缺失」文案→None：同 m9 | 同 m9 |
| app.authors.importer.x_roundtrip_check__mutmut_14 | A | 递归路径实参 None：diff 路径前缀形态变化，判定不变 | 同 m9（路径措辞） |
| app.authors.importer.x_roundtrip_check__mutmut_19 | A | 叶子差异文案→None：同 m9 | 同 m9 |
| app.authors.importer.x_roundtrip_check__mutmut_22 | A | walk 根路径 None：diff 路径前缀形态，同 m14 | 同 m9 |
| app.authors.importer.x_roundtrip_check__mutmut_26 | A | (root)→XX(root)XX：同上 | 同 m9 |
| app.authors.importer.x_roundtrip_check__mutmut_27 | A | (root)→(ROOT)：同上 | 同 m9 |
| app.authors.importer.x_roundtrip_check__mutmut_4 | A | dict 判定 and→or：单侧非 dict 时仍产出差异（elif a!=b 分支语义在非退化输入下同样报 False），诊断文案差异无条款 | 等价推理：mismatch 必报 diffs → ok=False 保持；diff 文案无条款 |
| app.authors.importer.x_roundtrip_check__mutmut_9 | A | 「DB 多出」文案→None：ok=False 判定不变，诊断文案无条款 | AC-10.1 钉一致性判定，未钉 diff 文案 |
| app.authors.memory.x_module_of_placeholder__mutmut_2 | A | endswith→or True：恒剥后缀——生产 memory_config 键恒带 _memory 后缀（importer 归一+缺省配置），无后缀键不可达 | 调用点核查：import_author_json m35 归一逻辑 + default_author_config 键形态 |
| app.authors.memory.x_render_memory__mutmut_3 | A | 条目 join 分隔符「\n」→XX：渲染文案形态无条款 | 记忆渲染文本格式无条款（占位符注入内容措辞先例） |
| app.authors.writer.x__build_prompt__mutmut_2 | A | read_text(encoding=None)：部署环境（Ubuntu/CI，UTF-8 locale）默认编码即 UTF-8，等价 | 环境口径：模板文件恒 UTF-8；默认编码随环境，CI-0 基线在 UTF-8 环境测得等价 |
| app.authors.writer.x__build_prompt__mutmut_7 | A | encoding 'utf-8'→'UTF-8'：Python codec 名大小写不敏感，等价 | 语言语义：编解码器别名 |
| app.authors.writer.x__hot_brief__mutmut_10 | A | getattr 缺省 False→True：同 m4 | 同 m4 |
| app.authors.writer.x__hot_brief__mutmut_19 | A | keywords 空判反转 or True：空关键词表时渲染空串 vs「（无）」，文案形态无条款 | 热点段文案措辞无条款 |
| app.authors.writer.x__hot_brief__mutmut_21 | A | 关键词分隔符「、」→XX：文案措辞 | 同 m19 |
| app.authors.writer.x__hot_brief__mutmut_22 | A | keywords[:15]→[:16]：关键词截取常数无条款 | 未钉常数 |
| app.authors.writer.x__hot_brief__mutmut_23 | A | 「（无）」→XX 包裹：文案措辞 | 同 m19 |
| app.authors.writer.x__hot_brief__mutmut_25 | A | 「（无）」→XX 包裹：文案措辞 | 同 m19 |
| app.authors.writer.x__hot_brief__mutmut_4 | A | getattr 缺省 False→None：include_hot_brief 为模型列（default=False），缺省不可达 | 调用点核查：app/models.py:154 include_hot_brief 列 |
| app.authors.writer.x__hot_brief__mutmut_7 | A | getattr 缺省形态：同 m4 | 同 m4 |
| app.authors.writer.x__norm__mutmut_1 | A | .lower()→.upper()：quote 与正文两侧同一 _norm 自洽折叠，子串命中结果等价 | AC-11.3 钉「空白归一化+NFKC 后子串命中」，两侧一致变换下大小写折叠方向不影响命中 |
| app.authors.writer.x__norm__mutmut_14 | A | (s or 'XXXX')：仅空正文且 quote 恰归一为 xxxx 的退化组合可观察，合法域等价 | 调用点核查：_validate_citations 前置拦截空 quote；空正文条目无有效引用面 |
| app.authors.writer.x__parse_output__mutmut_10 | A | 缺省 'XXXX'：同 m5 | 同 m5 |
| app.authors.writer.x__parse_output__mutmut_16 | A | JSONParseError(None)：拒绝行为不变，文案无条款 | 文案先例 |
| app.authors.writer.x__parse_output__mutmut_5 | A | get('decision','') 缺省 None：缺 decision 时两者均落 JSONParseError（拒绝），等价 | 结果等价推理：str(None)='None' 同样非法 decision |
| app.authors.writer.x__parse_output__mutmut_7 | A | 缺省形态：同 m5 | 同 m5 |
| app.authors.writer.x__render_reading_set__mutmut_19 | A | 块间分隔符「\n\n」→XX：块间隔措辞无条款（各块内容断言不受影响） | W4 钉条目内容可核，未钉块间分隔形态 |
| app.authors.writer.x__validate_citations__mutmut_13 | A | CitationError(None)：拒收行为不变（仍抛 CitationError），文案无条款 | AC-11.3 钉拒收语义，未钉文案 |
| app.authors.writer.x__validate_citations__mutmut_14 | A | 文案 XX 包裹：同 m13 | 同 m13 |
| app.authors.writer.x__validate_citations__mutmut_15 | A | 文案大写变体：同 m13 | 同 m13 |
| app.authors.writer.x__validate_citations__mutmut_18 | A | bodies 缺省 or 'XXXX'：仅空正文+quote 恰为 xxxx 的退化组合可观察，合法域等价 | 退化输入推理（同 _norm m14） |
| app.authors.writer.x__validate_citations__mutmut_21 | A | 「不是对象」文案→None：拒收不变，文案无条款 | 同 m13 |
| app.authors.writer.x__validate_citations__mutmut_30 | A | quote 缺省 or 'XXXX'：空 quote 仍被拒（后续逐字校验不命中），仅拒收原因文案变化 | AC-11.3 拒收语义不变 |
| app.authors.writer.x__validate_citations__mutmut_34 | A | 「quote 为空」文案→None：拒收不变，文案无条款 | 同 m13 |
| app.authors.writer.x__validate_citations__mutmut_38 | A | 「找不到」文案→None：拒收不变，文案无条款 | 同 m13 |
| app.authors.writer.x__validate_citations__mutmut_39 | A | quote 回显截断 [:80]→[:81]：文案截断界无条款 | 未钉常数 |
| app.authors.writer.x_assemble_ranked_reading_set__mutmut_106 | A | fallback='all_excluded'→None：fallback 诊断标记值形态无条款（回退行为本身不变） | docstring 钉回退行为；标记文案未钉 |
| app.authors.writer.x_assemble_ranked_reading_set__mutmut_107 | A | fallback 键名→XX：同 m106 | 同 m106 |
| app.authors.writer.x_assemble_ranked_reading_set__mutmut_108 | A | fallback 键名→大写：同 m106 | 同 m106 |
| app.authors.writer.x_assemble_ranked_reading_set__mutmut_113 | A | 回退调用 k→None：k=None 落 WRITE_READING_SET_K 缺省，与原 k 同源等价 | 控制流推理：两处 k 均出自同一 k 变量或等价缺省 |
| app.authors.writer.x_assemble_ranked_reading_set__mutmut_116 | A | 回退调用 k 缺省形态：同 m113 | 同 m113 |
| app.authors.writer.x_assemble_ranked_reading_set__mutmut_123 | A | meta ranked 计数→None：计数字段值无条款 | 同 m30 |
| app.authors.writer.x_assemble_ranked_reading_set__mutmut_129 | A | meta excluded 计数→None：同 m123 | 同 m30 |
| app.authors.writer.x_assemble_ranked_reading_set__mutmut_26 | A | k=RANK_POOL_K 形参缺省形态：同 m23 | 同 m23 |
| app.authors.writer.x_assemble_ranked_reading_set__mutmut_85 | A | 耗时 *1000→/1000：数值缩放退化（≈0），耗时仅诊断无精度条款 | 耗时数值精度无条款（providers.base m13 缩放先例） |
| app.authors.writer.x_run_write__mutmut_1 | A | triggered_by 缺省 'manual'→XX：唯一生产调用点（pipeline/runner.py:366）显式传参，缺省不可达 | 调用点核查：grep 全仓唯一调用点 |
| app.authors.writer.x_run_write__mutmut_2 | A | 缺省 'manual'→MANUAL：同 m1 | 同 m1 |
| app.authors.writer.x_run_write__mutmut_27 | A | prompt_snapshot 初值 ''→None：随即被完整快照覆盖，终态等价 | 控制流推理：snapshot 两行后必被赋值 |
| app.authors.writer.x_run_write__mutmut_34 | A | prompt_snapshot 初值行删除：同 m27（随即覆盖） | 同 m27 |
| app.authors.writer.x_run_write__mutmut_37 | A | prompt_snapshot 初值 'XXXX'：同 m27（随即覆盖） | 同 m27 |
| app.authors.writer.x_run_write__mutmut_51 | A | system 提示文案 XX 包裹：提示词措辞无条款 | 提示词措辞先例（ADR-8 未钉文案） |
| app.authors.writer.x_run_write__mutmut_52 | A | system 提示文案大写：同 m51 | 同 m51 |
| app.authors.writer.x_run_write__mutmut_71 | A | 分隔符 XX 包裹：快照分隔措辞无条款（两段内容均仍在） | W4 钉内容可核，未钉分隔形态 |
| app.authors.writer.x_run_write__mutmut_77 | A | last_error 初值 ''→（不变语义）：仅全成功路径可达，error 落库前恒被赋值 | 控制流推理：last_error 只在 data None 分支读取 |


## 批次 10：外部能力家族收官 hot/search/rerank/embedding（2026-10-04，C1-8）

> A 类 174 条（B 0 / D 0）。C 类 404 条由 `tests/test_mutation_c1_8.py`（35 测试）闭合，
> 核验-改判三轮：C 404/404 全杀、A 174/174 全活（判定集 6 文件，problems=0）。
> 分诊与核验详见 doc/CI0/C1-8-执行Agent工作汇报.md。逐条理由如下。

### app.embedding.base.xǁEmbeddingProviderǁ_embed_batch（12 条）

| 变异体 | 类 | 说明 | 依据 |
|---|---|---|---|
| app.embedding.base.xǁEmbeddingProviderǁ_embed_batch__mutmut_3 | A | except 必先赋值 last_err,初值不可达 | 等价/不可达（控制流推理、列缺省承载、类属性兜底或平台语义） |
| app.embedding.base.xǁEmbeddingProviderǁ_embed_batch__mutmut_28 | A | None→列 default 0/True 兜底(SQLAlchemy 实证) | 等价/不可达（控制流推理、列缺省承载、类属性兜底或平台语义） |
| app.embedding.base.xǁEmbeddingProviderǁ_embed_batch__mutmut_32 | A | None→列 default 0/True 兜底(SQLAlchemy 实证) | 等价/不可达（控制流推理、列缺省承载、类属性兜底或平台语义） |
| app.embedding.base.xǁEmbeddingProviderǁ_embed_batch__mutmut_40 | A | completion_tokens/ok kwarg 删除→列缺省承载 0/True | 等价/不可达（控制流推理、列缺省承载、类属性兜底或平台语义） |
| app.embedding.base.xǁEmbeddingProviderǁ_embed_batch__mutmut_44 | A | completion_tokens/ok kwarg 删除→列缺省承载 0/True | 等价/不可达（控制流推理、列缺省承载、类属性兜底或平台语义） |
| app.embedding.base.xǁEmbeddingProviderǁ_embed_batch__mutmut_75 | A | getattr 缺省 None 与 False 同 falsy | 等价/不可达（控制流推理、列缺省承载、类属性兜底或平台语义） |
| app.embedding.base.xǁEmbeddingProviderǁ_embed_batch__mutmut_78 | A | getattr 缺省 None 与 False 同 falsy | 等价/不可达（控制流推理、列缺省承载、类属性兜底或平台语义） |
| app.embedding.base.xǁEmbeddingProviderǁ_embed_batch__mutmut_81 | A | ProviderError.retryable=False 类属性兜底,getattr 缺省分支不可达 | 等价/不可达（控制流推理、列缺省承载、类属性兜底或平台语义） |
| app.embedding.base.xǁEmbeddingProviderǁ_embed_batch__mutmut_114 | A | log.warning 文案/参数无条款 | 文案措辞无条款（C1-7 措辞先例） |
| app.embedding.base.xǁEmbeddingProviderǁ_embed_batch__mutmut_119 | A | log.warning 文案/参数无条款 | 文案措辞无条款（C1-7 措辞先例） |
| app.embedding.base.xǁEmbeddingProviderǁ_embed_batch__mutmut_121 | A | log.warning 文案/参数无条款 | 文案措辞无条款（C1-7 措辞先例） |
| app.embedding.base.xǁEmbeddingProviderǁ_embed_batch__mutmut_122 | A | log.warning 文案/参数无条款 | 文案措辞无条款（C1-7 措辞先例） |

### app.embedding.moark.xǁMoarkEmbeddingProviderǁ__init__（3 条）

| 变异体 | 类 | 说明 | 依据 |
|---|---|---|---|
| app.embedding.moark.xǁMoarkEmbeddingProviderǁ__init____mutmut_1 | A | timeout 120 未钉数值缺省 | 数值缺省/边界无条款（沿数值缺省先例） |
| app.embedding.moark.xǁMoarkEmbeddingProviderǁ__init____mutmut_7 | A | rstrip 是字符集语义,'XX/XX'≡'X/' | 等价/不可达（控制流推理、列缺省承载、类属性兜底或平台语义） |

### app.embedding.registry.x_get_provider（7 条）

| 变异体 | 类 | 说明 | 依据 |
|---|---|---|---|
| app.embedding.registry.x_get_provider__mutmut_2 | A | none/未注册分支仍抛 EmbeddingError,消息措辞无条款 | 文案措辞无条款（C1-7 措辞先例） |
| app.embedding.registry.x_get_provider__mutmut_3 | A | none/未注册分支仍抛 EmbeddingError,消息措辞无条款 | 文案措辞无条款（C1-7 措辞先例） |
| app.embedding.registry.x_get_provider__mutmut_4 | A | none/未注册分支仍抛 EmbeddingError,消息措辞无条款 | 文案措辞无条款（C1-7 措辞先例） |
| app.embedding.registry.x_get_provider__mutmut_5 | A | none/未注册分支仍抛 EmbeddingError,消息措辞无条款 | 文案措辞无条款（C1-7 措辞先例） |
| app.embedding.registry.x_get_provider__mutmut_6 | A | none/未注册分支仍抛 EmbeddingError,消息措辞无条款 | 文案措辞无条款（C1-7 措辞先例） |
| app.embedding.registry.x_get_provider__mutmut_7 | A | none/未注册分支仍抛 EmbeddingError,消息措辞无条款 | 文案措辞无条款（C1-7 措辞先例） |
| app.embedding.registry.x_get_provider__mutmut_11 | A | none/未注册分支仍抛 EmbeddingError,消息措辞无条款 | 文案措辞无条款（C1-7 措辞先例） |

### app.hot.service.x__rank_filter_topics（19 条）

| 变异体 | 类 | 说明 | 依据 |
|---|---|---|---|
| app.hot.service.x__rank_filter_topics__mutmut_8 | A | 开关取值枚举仅钉 true,1/yes/on/大小写变体无条款 | 数值缺省/边界无条款（沿数值缺省先例） |
| app.hot.service.x__rank_filter_topics__mutmut_10 | A | 开关取值枚举仅钉 true,1/yes/on/大小写变体无条款 | 数值缺省/边界无条款（沿数值缺省先例） |
| app.hot.service.x__rank_filter_topics__mutmut_13 | A | 开关取值枚举仅钉 true,1/yes/on/大小写变体无条款 | 数值缺省/边界无条款（沿数值缺省先例） |
| app.hot.service.x__rank_filter_topics__mutmut_14 | A | 开关取值枚举仅钉 true,1/yes/on/大小写变体无条款 | 数值缺省/边界无条款（沿数值缺省先例） |
| app.hot.service.x__rank_filter_topics__mutmut_15 | A | 开关取值枚举仅钉 true,1/yes/on/大小写变体无条款 | 数值缺省/边界无条款（沿数值缺省先例） |
| app.hot.service.x__rank_filter_topics__mutmut_16 | A | 开关取值枚举仅钉 true,1/yes/on/大小写变体无条款 | 数值缺省/边界无条款（沿数值缺省先例） |
| app.hot.service.x__rank_filter_topics__mutmut_25 | A | 缺省 provider 字面量无条款 | 数值缺省/边界无条款（沿数值缺省先例） |
| app.hot.service.x__rank_filter_topics__mutmut_26 | A | 缺省 provider 字面量无条款 | 数值缺省/边界无条款（沿数值缺省先例） |
| app.hot.service.x__rank_filter_topics__mutmut_31 | A | HOT_RANK_MIN_SCORE 键名/缺省 40/含等性无条款 | 数值缺省/边界无条款（沿数值缺省先例） |
| app.hot.service.x__rank_filter_topics__mutmut_32 | A | HOT_RANK_MIN_SCORE 键名/缺省 40/含等性无条款 | 数值缺省/边界无条款（沿数值缺省先例） |
| app.hot.service.x__rank_filter_topics__mutmut_33 | A | HOT_RANK_MIN_SCORE 键名/缺省 40/含等性无条款 | 数值缺省/边界无条款（沿数值缺省先例） |
| app.hot.service.x__rank_filter_topics__mutmut_44 | A | 无方向 error 文案 | 文案措辞无条款（C1-7 措辞先例） |
| app.hot.service.x__rank_filter_topics__mutmut_69 | A | error 截断界 [:200] 无条款 | 数值缺省/边界无条款（沿数值缺省先例） |
| app.hot.service.x__rank_filter_topics__mutmut_76 | A | fake 恒含全部 id 缺省分支不可达 | 等价/不可达（控制流推理、列缺省承载、类属性兜底或平台语义） |
| app.hot.service.x__rank_filter_topics__mutmut_78 | A | fake 恒命中全部 id,get 缺省分支不可达 | 等价/不可达（控制流推理、列缺省承载、类属性兜底或平台语义） |
| app.hot.service.x__rank_filter_topics__mutmut_79 | A | fake 恒含全部 id 缺省分支不可达 | 等价/不可达（控制流推理、列缺省承载、类属性兜底或平台语义） |
| app.hot.service.x__rank_filter_topics__mutmut_80 | A | >=/> 含等性无条款 | 数值缺省/边界无条款（沿数值缺省先例） |

### app.hot.service.x_run_hot_round（56 条）

| 变异体 | 类 | 说明 | 依据 |
|---|---|---|---|
| app.hot.service.x_run_hot_round__mutmut_14 | A | skip reason 文案 | 文案措辞无条款（C1-7 措辞先例） |
| app.hot.service.x_run_hot_round__mutmut_15 | A | skip reason 文案 | 文案措辞无条款（C1-7 措辞先例） |
| app.hot.service.x_run_hot_round__mutmut_37 | A | 认领失败 reason 文案 | 文案措辞无条款（C1-7 措辞先例） |
| app.hot.service.x_run_hot_round__mutmut_38 | A | 认领失败 reason 文案 | 文案措辞无条款（C1-7 措辞先例） |
| app.hot.service.x_run_hot_round__mutmut_46 | A | 平台耗时 ms 计时值无条款 | 数值缺省/边界无条款（沿数值缺省先例） |
| app.hot.service.x_run_hot_round__mutmut_48 | A | 平台耗时 ms 计时值无条款 | 数值缺省/边界无条款（沿数值缺省先例） |
| app.hot.service.x_run_hot_round__mutmut_60 | A | 成功平台统计行键面诊断 | 诊断镜像键面（§4.1 只钉账本行本体，已由 C 测试断言） |
| app.hot.service.x_run_hot_round__mutmut_62 | A | 平台 log 文案 | 文案措辞无条款（C1-7 措辞先例） |
| app.hot.service.x_run_hot_round__mutmut_63 | A | 平台 log 文案 | 文案措辞无条款（C1-7 措辞先例） |
| app.hot.service.x_run_hot_round__mutmut_66 | A | 平台 log 文案 | 文案措辞无条款（C1-7 措辞先例） |
| app.hot.service.x_run_hot_round__mutmut_97 | A | 源间礼貌间隔 0.5s 无条款 | 数值缺省/边界无条款（沿数值缺省先例） |
| app.hot.service.x_run_hot_round__mutmut_131 | A | HotBatch 初值随后被覆写(初始化即覆盖先例) | 等价/不可达（控制流推理、列缺省承载、类属性兜底或平台语义） |
| app.hot.service.x_run_hot_round__mutmut_134 | A | HotBatch 初值随后被覆写(初始化即覆盖先例) | 等价/不可达（控制流推理、列缺省承载、类属性兜底或平台语义） |
| app.hot.service.x_run_hot_round__mutmut_136 | A | HotBatch 初值随后被覆写(初始化即覆盖先例) | 等价/不可达（控制流推理、列缺省承载、类属性兜底或平台语义） |
| app.hot.service.x_run_hot_round__mutmut_145 | A | HotBatch 初值随后被覆写(初始化即覆盖先例) | 等价/不可达（控制流推理、列缺省承载、类属性兜底或平台语义） |

### app.rerank.base.xǁRankProviderǁ_log（1 条）

| 变异体 | 类 | 说明 | 依据 |
|---|---|---|---|
| app.rerank.base.xǁRankProviderǁ_log__mutmut_19 | A | criteria_key 截断界 [:200] 无条款 | 数值缺省/边界无条款（沿数值缺省先例） |

### app.rerank.base.xǁRankProviderǁrank（13 条）

| 变异体 | 类 | 说明 | 依据 |
|---|---|---|---|
| app.rerank.base.xǁRankProviderǁrank__mutmut_8 | A | None→列 default 0 兜底(candidate_count/latency_ms) | 等价/不可达（控制流推理、列缺省承载、类属性兜底或平台语义） |
| app.rerank.base.xǁRankProviderǁrank__mutmut_9 | A | None→列 default 0 兜底(candidate_count/latency_ms) | 等价/不可达（控制流推理、列缺省承载、类属性兜底或平台语义） |
| app.rerank.base.xǁRankProviderǁrank__mutmut_27 | A | blocked log 文案 | 文案措辞无条款（C1-7 措辞先例） |
| app.rerank.base.xǁRankProviderǁrank__mutmut_28 | A | blocked log 文案 | 文案措辞无条款（C1-7 措辞先例） |
| app.rerank.base.xǁRankProviderǁrank__mutmut_29 | A | blocked log 文案 | 文案措辞无条款（C1-7 措辞先例） |
| app.rerank.base.xǁRankProviderǁrank__mutmut_30 | A | blocked log 文案 | 文案措辞无条款（C1-7 措辞先例） |
| app.rerank.base.xǁRankProviderǁrank__mutmut_31 | A | blocked log 文案 | 文案措辞无条款（C1-7 措辞先例） |
| app.rerank.base.xǁRankProviderǁrank__mutmut_41 | A | 候选文本存在时兜底不可达 | 等价/不可达（控制流推理、列缺省承载、类属性兜底或平台语义） |
| app.rerank.base.xǁRankProviderǁrank__mutmut_69 | A | error 截断界 [:500] 无条款 | 数值缺省/边界无条款（沿数值缺省先例） |
| app.rerank.base.xǁRankProviderǁrank__mutmut_78 | A | None→列 default True/'ok' 兜底 | 等价/不可达（控制流推理、列缺省承载、类属性兜底或平台语义） |
| app.rerank.base.xǁRankProviderǁrank__mutmut_79 | A | None→列 default True/'ok' 兜底 | 等价/不可达（控制流推理、列缺省承载、类属性兜底或平台语义） |

### app.rerank.jev_rank.xǁBochaJevRankProviderǁ__init__（4 条）

| 变异体 | 类 | 说明 | 依据 |
|---|---|---|---|
| app.rerank.jev_rank.xǁBochaJevRankProviderǁ__init____mutmut_5 | A | 缺 Key 错误文案 | 文案措辞无条款（C1-7 措辞先例） |

### app.rerank.registry.x_get_provider（7 条）

| 变异体 | 类 | 说明 | 依据 |
|---|---|---|---|
| app.rerank.registry.x_get_provider__mutmut_2 | A | none/未注册分支仍抛 RankError,消息措辞无条款(既有测试已钉类型) | 文案措辞无条款（C1-7 措辞先例） |
| app.rerank.registry.x_get_provider__mutmut_3 | A | none/未注册分支仍抛 RankError,消息措辞无条款(既有测试已钉类型) | 文案措辞无条款（C1-7 措辞先例） |
| app.rerank.registry.x_get_provider__mutmut_4 | A | none/未注册分支仍抛 RankError,消息措辞无条款(既有测试已钉类型) | 文案措辞无条款（C1-7 措辞先例） |
| app.rerank.registry.x_get_provider__mutmut_5 | A | none/未注册分支仍抛 RankError,消息措辞无条款(既有测试已钉类型) | 文案措辞无条款（C1-7 措辞先例） |
| app.rerank.registry.x_get_provider__mutmut_6 | A | none/未注册分支仍抛 RankError,消息措辞无条款(既有测试已钉类型) | 文案措辞无条款（C1-7 措辞先例） |
| app.rerank.registry.x_get_provider__mutmut_7 | A | none/未注册分支仍抛 RankError,消息措辞无条款(既有测试已钉类型) | 文案措辞无条款（C1-7 措辞先例） |
| app.rerank.registry.x_get_provider__mutmut_11 | A | none/未注册分支仍抛 RankError,消息措辞无条款(既有测试已钉类型) | 文案措辞无条款（C1-7 措辞先例） |

### app.search.pipeline.x_fetch_search_source（48 条）

| 变异体 | 类 | 说明 | 依据 |
|---|---|---|---|
| app.search.pipeline.x_fetch_search_source__mutmut_15 | A | 缺省 provider 'bocha' 字面量无条款 | 数值缺省/边界无条款（沿数值缺省先例） |
| app.search.pipeline.x_fetch_search_source__mutmut_16 | A | 缺省 provider 'bocha' 字面量无条款 | 数值缺省/边界无条款（沿数值缺省先例） |
| app.search.pipeline.x_fetch_search_source__mutmut_23 | A | 缺省 group 'default' 字面量无条款 | 数值缺省/边界无条款（沿数值缺省先例） |
| app.search.pipeline.x_fetch_search_source__mutmut_24 | A | 缺省 group 'default' 字面量无条款 | 数值缺省/边界无条款（沿数值缺省先例） |
| app.search.pipeline.x_fetch_search_source__mutmut_55 | A | None→列 default 0 兜底(result_count/latency_ms) | 等价/不可达（控制流推理、列缺省承载、类属性兜底或平台语义） |
| app.search.pipeline.x_fetch_search_source__mutmut_56 | A | None→列 default 0 兜底(result_count/latency_ms) | 等价/不可达（控制流推理、列缺省承载、类属性兜底或平台语义） |
| app.search.pipeline.x_fetch_search_source__mutmut_63 | A | result_count/latency kwarg 删除→列缺省承载 0 | 等价/不可达（控制流推理、列缺省承载、类属性兜底或平台语义） |
| app.search.pipeline.x_fetch_search_source__mutmut_64 | A | result_count/latency kwarg 删除→列缺省承载 0 | 等价/不可达（控制流推理、列缺省承载、类属性兜底或平台语义） |
| app.search.pipeline.x_fetch_search_source__mutmut_79 | A | stats.extra quota_state 诊断键面 | 诊断镜像键面（§4.1 只钉账本行本体，已由 C 测试断言） |
| app.search.pipeline.x_fetch_search_source__mutmut_80 | A | stats.extra quota_state 诊断键面 | 诊断镜像键面（§4.1 只钉账本行本体，已由 C 测试断言） |
| app.search.pipeline.x_fetch_search_source__mutmut_81 | A | stats.extra quota_state 诊断键面 | 诊断镜像键面（§4.1 只钉账本行本体，已由 C 测试断言） |
| app.search.pipeline.x_fetch_search_source__mutmut_83 | A | blocked log 文案 | 文案措辞无条款（C1-7 措辞先例） |
| app.search.pipeline.x_fetch_search_source__mutmut_84 | A | blocked log 文案 | 文案措辞无条款（C1-7 措辞先例） |
| app.search.pipeline.x_fetch_search_source__mutmut_88 | A | blocked log 文案 | 文案措辞无条款（C1-7 措辞先例） |
| app.search.pipeline.x_fetch_search_source__mutmut_89 | A | blocked log 文案 | 文案措辞无条款（C1-7 措辞先例） |
| app.search.pipeline.x_fetch_search_source__mutmut_152 | A | stats.extra/feed_entries 诊断镜像(账本行已断言) | 诊断镜像键面（§4.1 只钉账本行本体，已由 C 测试断言） |
| app.search.pipeline.x_fetch_search_source__mutmut_153 | A | stats.extra/feed_entries 诊断镜像(账本行已断言) | 诊断镜像键面（§4.1 只钉账本行本体，已由 C 测试断言） |
| app.search.pipeline.x_fetch_search_source__mutmut_154 | A | stats.extra/feed_entries 诊断镜像(账本行已断言) | 诊断镜像键面（§4.1 只钉账本行本体，已由 C 测试断言） |
| app.search.pipeline.x_fetch_search_source__mutmut_212 | A | datetime.now(None)=now() | 等价/不可达（控制流推理、列缺省承载、类属性兜底或平台语义） |

### app.search.quota.x__count（1 条）

| 变异体 | 类 | 说明 | 依据 |
|---|---|---|---|
| app.search.quota.x__count__mutmut_6 | A | 分钟/日 period_key 格式永不碰撞,period 过滤冗余 | 等价/不可达（控制流推理、列缺省承载、类属性兜底或平台语义） |

### app.search.quota.x__provider_limits（1 条）

| 变异体 | 类 | 说明 | 依据 |
|---|---|---|---|

### app.search.quota.x_check_and_count（1 条）

| 变异体 | 类 | 说明 | 依据 |
|---|---|---|---|
| app.search.quota.x_check_and_count__mutmut_43 | A | period_key 格式永不碰撞,period 过滤冗余 | 等价/不可达（控制流推理、列缺省承载、类属性兜底或平台语义） |

### app.search.registry.x_get_provider（1 条）

| 变异体 | 类 | 说明 | 依据 |
|---|---|---|---|
| app.search.registry.x_get_provider__mutmut_4 | A | 未注册错误文案 | 文案措辞无条款（C1-7 措辞先例） |

## 批次 11：C1-9a 补扫——pipeline.runner / providers.deepseek / config（96 A + 1 B = 97 条）

> 本批无 D 类；C 类 393 条由 `tests/test_mutation_c1_9a.py` 47 测试闭合（不在本清单）。
> 核验-改判（两轮逐条施加）：R1（C 385 + A 105 逐条施加→跑新测试文件）暴露 C 存活 10 条、
> A 被杀 11 条。归因：①6 条测试场景修正（enqueue skip url 键断言、score 异常/解析计数×2 场景、
> error 类型名 startswith、summary task_id 断言）后 R2 定点复跑全杀；②fetch_round m26/m27
> **C→A 改判**——_finish 内存同步 + 后续 _update_backoff 提交将 ORM 脏值回写，终态恒被修复
> （实证：CAS 迟到写拒绝告警后 DB 终态仍 DONE）；③process m42 **C→B 改判**（CAS 认领竞争防御，
> 单 worker 判定域不可达）；④A 被杀 11 条全部 **A→C 改判**：chat json_mode 缺省被默认路径断言
> 击杀 1、_call max_retries 全参透传 2（C1-8 构造全参透传先例）、_finish payload_extra+stats
> 并传合并 3（DT-5 组合契约——测试即并传场景）、score except 处理器内 log.format 破坏致
> TypeError 中断整轮 5（违反「单条异常不中断」——比 C1-8 日志面板先例更强的处理路径面）。
> 终态：**C 393/393 全杀、A 96/96 全活、B 1 存活（B 不杀）、problems=0**。

| mutant 全名 | 类别 | 一句话理由 | 依据条款或推理 |
|---|---|---|---|
| app.config.x__get_bool__mutmut_10 | A | 开关取值枚举 YES 变体 | 等价/不可达或条款未钉（C1-8 观察 4 列缺省兜底、log 文案组、数值缺省组、KEYSHAPE 组先例沿用） |
| app.config.x__get_bool__mutmut_11 | A | 开关取值枚举 on 变体 | 等价/不可达或条款未钉（C1-8 观察 4 列缺省兜底、log 文案组、数值缺省组、KEYSHAPE 组先例沿用） |
| app.config.x__get_bool__mutmut_12 | A | 开关取值枚举 ON 变体 | 等价/不可达或条款未钉（C1-8 观察 4 列缺省兜底、log 文案组、数值缺省组、KEYSHAPE 组先例沿用） |
| app.config.x__get_bool__mutmut_6 | A | 开关取值枚举 1 变体（仅钉 true，C1-8 数值组先例） | 等价/不可达或条款未钉（C1-8 观察 4 列缺省兜底、log 文案组、数值缺省组、KEYSHAPE 组先例沿用） |
| app.config.x__get_bool__mutmut_9 | A | 开关取值枚举 yes 变体 | 等价/不可达或条款未钉（C1-8 观察 4 列缺省兜底、log 文案组、数值缺省组、KEYSHAPE 组先例沿用） |
| app.config.x__require__mutmut_5 | A | SystemExit 退出码数值（1→None）无条款，类型面已由 D18 测试钉死 | 等价/不可达或条款未钉（C1-8 观察 4 列缺省兜底、log 文案组、数值缺省组、KEYSHAPE 组先例沿用） |
| app.config.x__require__mutmut_6 | A | SystemExit 退出码数值（1→2）无条款 | 等价/不可达或条款未钉（C1-8 观察 4 列缺省兜底、log 文案组、数值缺省组、KEYSHAPE 组先例沿用） |
| app.config.x__tolerant_env_parse__mutmut_3 | A | encoding=None 走 locale 缺省——.env 值域 ASCII 等价（encoding 无条款） | 等价/不可达或条款未钉（C1-8 观察 4 列缺省兜底、log 文案组、数值缺省组、KEYSHAPE 组先例沿用） |
| app.config.x__tolerant_env_parse__mutmut_5 | A | UTF-8 为合法 codec 别名，完全等价 | 等价/不可达或条款未钉（C1-8 观察 4 列缺省兜底、log 文案组、数值缺省组、KEYSHAPE 组先例沿用） |
| app.pipeline.runner.x__claim__mutmut_20 | A | attempts 数值无条款（同 m7） | 等价/不可达或条款未钉（C1-8 观察 4 列缺省兜底、log 文案组、数值缺省组、KEYSHAPE 组先例沿用） |
| app.pipeline.runner.x__claim__mutmut_21 | A | attempts 数值无条款（同 m7） | 等价/不可达或条款未钉（C1-8 观察 4 列缺省兜底、log 文案组、数值缺省组、KEYSHAPE 组先例沿用） |
| app.pipeline.runner.x__claim__mutmut_22 | A | datetime.now(None) naive——updated_at 形态无消费条款（tz 形态无断言面） | 等价/不可达或条款未钉（C1-8 观察 4 列缺省兜底、log 文案组、数值缺省组、KEYSHAPE 组先例沿用） |
| app.pipeline.runner.x__claim__mutmut_7 | A | attempts+1 数值无条款（设计书仅列 attempts 列，未钉认领时增量） | 等价/不可达或条款未钉（C1-8 观察 4 列缺省兜底、log 文案组、数值缺省组、KEYSHAPE 组先例沿用） |
| app.pipeline.runner.x__claim__mutmut_8 | A | updated_at 未显式赋值——列 onupdate=utcnow 兜底（C1-8 观察 4 同款：列钩子承载） | 等价/不可达或条款未钉（C1-8 观察 4 列缺省兜底、log 文案组、数值缺省组、KEYSHAPE 组先例沿用） |
| app.pipeline.runner.x__finish__mutmut_24 | A | error 截断界 [:2000]→[:2001]（截断界数值无条款；last_error 为 Text 列） | 等价/不可达或条款未钉（C1-8 观察 4 列缺省兜底、log 文案组、数值缺省组、KEYSHAPE 组先例沿用） |
| app.pipeline.runner.x__finish__mutmut_27 | A | synchronize_session=None（'auto'）——SQLA 会话同步策略为实现形态（ADR-1 禁形态断言） | 等价/不可达或条款未钉（C1-8 观察 4 列缺省兜底、log 文案组、数值缺省组、KEYSHAPE 组先例沿用） |
| app.pipeline.runner.x__finish__mutmut_6 | A | datetime.now(None) naive——终态行退出 RUNNING 域，P0-1 比较不再触达（tz 形态无消费方） | 等价/不可达或条款未钉（C1-8 观察 4 列缺省兜底、log 文案组、数值缺省组、KEYSHAPE 组先例沿用） |
| app.pipeline.runner.x__new_task__mutmut_3 | A | status=None → 列 default='PENDING' 兜底（C1-8 观察 4：列缺省承载） | 等价/不可达或条款未钉（C1-8 观察 4 列缺省兜底、log 文案组、数值缺省组、KEYSHAPE 组先例沿用） |
| app.pipeline.runner.x__new_task__mutmut_6 | A | status 缺参 → 列 default='PENDING' 兜底（同 m3） | 等价/不可达或条款未钉（C1-8 观察 4 列缺省兜底、log 文案组、数值缺省组、KEYSHAPE 组先例沿用） |
| app.pipeline.runner.x_enqueue_fetch_round__mutmut_1 | A | triggered_by 缺省 'scheduler'（缺省值无条款——C1-8 数值缺省先例） | 等价/不可达或条款未钉（C1-8 观察 4 列缺省兜底、log 文案组、数值缺省组、KEYSHAPE 组先例沿用） |
| app.pipeline.runner.x_enqueue_fetch_round__mutmut_2 | A | 同 m1（大写变体） | 等价/不可达或条款未钉（C1-8 观察 4 列缺省兜底、log 文案组、数值缺省组、KEYSHAPE 组先例沿用） |
| app.pipeline.runner.x_enqueue_fetch_round__mutmut_81 | A | 同 m74 | 等价/不可达或条款未钉（C1-8 观察 4 列缺省兜底、log 文案组、数值缺省组、KEYSHAPE 组先例沿用） |
| app.pipeline.runner.x_fetch_round__mutmut_1 | A | triggered_by 缺省 'manual'（缺省值无条款） | 等价/不可达或条款未钉（C1-8 观察 4 列缺省兜底、log 文案组、数值缺省组、KEYSHAPE 组先例沿用） |
| app.pipeline.runner.x_fetch_round__mutmut_2 | A | 同 m1 | 等价/不可达或条款未钉（C1-8 观察 4 列缺省兜底、log 文案组、数值缺省组、KEYSHAPE 组先例沿用） |
| app.pipeline.runner.x_fetch_round__mutmut_26 | A | task.status='XXRUNNINGXX'：_finish 内存同步+后续 _update_backoff 提交将 ORM 脏值回写，终态恒被修复（实证：CAS 迟到写拒绝后 DB 终态仍 DONE） | 等价/不可达或条款未钉（C1-8 观察 4 列缺省兜底、log 文案组、数值缺省组、KEYSHAPE 组先例沿用） |
| app.pipeline.runner.x_fetch_round__mutmut_27 | A | 同 m26（lowercase 变体，同款回写修复） | 等价/不可达或条款未钉（C1-8 观察 4 列缺省兜底、log 文案组、数值缺省组、KEYSHAPE 组先例沿用） |
| app.pipeline.runner.x_fetch_round__mutmut_28 | A | attempts =1：首次认领恒 1（任务新建 attempts=0），控制流等价 | 等价/不可达或条款未钉（C1-8 观察 4 列缺省兜底、log 文案组、数值缺省组、KEYSHAPE 组先例沿用） |
| app.pipeline.runner.x_fetch_round__mutmut_29 | A | attempts -=1：attempts 数值无条款（同 _claim m7） | 等价/不可达或条款未钉（C1-8 观察 4 列缺省兜底、log 文案组、数值缺省组、KEYSHAPE 组先例沿用） |
| app.pipeline.runner.x_process_fetch_round__mutmut_17 | A | status 过滤移除：_claim 的 WHERE status='PENDING' CAS 复核兜底（双保险，行为面等价） | 等价/不可达或条款未钉（C1-8 观察 4 列缺省兜底、log 文案组、数值缺省组、KEYSHAPE 组先例沿用） |
| app.pipeline.runner.x_process_fetch_round__mutmut_35 | A | any_failed 初值 None：or 链吸收，首轮赋值即覆盖（控制流等价） | 等价/不可达或条款未钉（C1-8 观察 4 列缺省兜底、log 文案组、数值缺省组、KEYSHAPE 组先例沿用） |
| app.pipeline.runner.x_process_fetch_round__mutmut_61 | A | 'source 不存在' 错误文案 XX 包裹（留痕=presence 已钉，文案无条款） | 等价/不可达或条款未钉（C1-8 观察 4 列缺省兜底、log 文案组、数值缺省组、KEYSHAPE 组先例沿用） |
| app.pipeline.runner.x_process_fetch_round__mutmut_62 | A | 'source 不存在' 文案大写变体（同 m61） | 等价/不可达或条款未钉（C1-8 观察 4 列缺省兜底、log 文案组、数值缺省组、KEYSHAPE 组先例沿用） |
| app.pipeline.runner.x_reclaim_stale_tasks__mutmut_11 | A | synchronize_session=None（实现形态，同 _finish m27） | 等价/不可达或条款未钉（C1-8 观察 4 列缺省兜底、log 文案组、数值缺省组、KEYSHAPE 组先例沿用） |
| app.pipeline.runner.x_reclaim_stale_tasks__mutmut_19 | A | updated_at=now 移除——列 onupdate=utcnow 兜底（等价） | 等价/不可达或条款未钉（C1-8 观察 4 列缺省兜底、log 文案组、数值缺省组、KEYSHAPE 组先例沿用） |
| app.pipeline.runner.x_reclaim_stale_tasks__mutmut_3 | A | datetime.now(None) naive local：UTC 判定域（GitHub CI runner）等价——CI-0 实证存活；本地 +08 可杀属判定域外（注记） | 等价/不可达或条款未钉（C1-8 观察 4 列缺省兜底、log 文案组、数值缺省组、KEYSHAPE 组先例沿用） |
| app.pipeline.runner.x_reclaim_stale_tasks__mutmut_41 | A | 同 m39 | 等价/不可达或条款未钉（C1-8 观察 4 列缺省兜底、log 文案组、数值缺省组、KEYSHAPE 组先例沿用） |
| app.pipeline.runner.x_reclaim_stale_tasks__mutmut_42 | A | 同 m39 | 等价/不可达或条款未钉（C1-8 观察 4 列缺省兜底、log 文案组、数值缺省组、KEYSHAPE 组先例沿用） |
| app.pipeline.runner.x_reclaim_stale_tasks__mutmut_43 | A | 同 m39 | 等价/不可达或条款未钉（C1-8 观察 4 列缺省兜底、log 文案组、数值缺省组、KEYSHAPE 组先例沿用） |
| app.pipeline.runner.x_reclaim_stale_tasks__mutmut_44 | A | 同 m39 | 等价/不可达或条款未钉（C1-8 观察 4 列缺省兜底、log 文案组、数值缺省组、KEYSHAPE 组先例沿用） |
| app.pipeline.runner.x_score_round__mutmut_1 | A | triggered_by 缺省 'manual'（缺省值无条款） | 等价/不可达或条款未钉（C1-8 观察 4 列缺省兜底、log 文案组、数值缺省组、KEYSHAPE 组先例沿用） |
| app.pipeline.runner.x_score_round__mutmut_2 | A | 同 m1 | 等价/不可达或条款未钉（C1-8 观察 4 列缺省兜底、log 文案组、数值缺省组、KEYSHAPE 组先例沿用） |
| app.pipeline.runner.x_score_round__mutmut_34 | A | attempts 数值无条款（同 _claim m7） | 等价/不可达或条款未钉（C1-8 观察 4 列缺省兜底、log 文案组、数值缺省组、KEYSHAPE 组先例沿用） |
| app.pipeline.runner.x_score_round__mutmut_35 | A | attempts 数值无条款（同 _claim m7） | 等价/不可达或条款未钉（C1-8 观察 4 列缺省兜底、log 文案组、数值缺省组、KEYSHAPE 组先例沿用） |
| app.providers.deepseek.xǁDeepSeekProviderǁ__init____mutmut_9 | A | last_usage 初值 None——chat 首次调用即整体覆写，初值不可达（初始化即覆盖先例） | 等价/不可达或条款未钉（C1-8 观察 4 列缺省兜底、log 文案组、数值缺省组、KEYSHAPE 组先例沿用） |
| app.providers.deepseek.xǁDeepSeekProviderǁchat__mutmut_110 | A | fallback_note 截断界 [:200]→[:201]（截断界无条款，C1-8 数值组先例） | 等价/不可达或条款未钉（C1-8 观察 4 列缺省兜底、log 文案组、数值缺省组、KEYSHAPE 组先例沿用） |
| app.providers.deepseek.xǁDeepSeekProviderǁchat__mutmut_112 | A | log 文案变体（log 文案组） | 等价/不可达或条款未钉（C1-8 观察 4 列缺省兜底、log 文案组、数值缺省组、KEYSHAPE 组先例沿用） |
| app.providers.deepseek.xǁDeepSeekProviderǁchat__mutmut_113 | A | 同 m112 | 等价/不可达或条款未钉（C1-8 观察 4 列缺省兜底、log 文案组、数值缺省组、KEYSHAPE 组先例沿用） |
| app.providers.deepseek.xǁDeepSeekProviderǁchat__mutmut_114 | A | 同 m112 | 等价/不可达或条款未钉（C1-8 观察 4 列缺省兜底、log 文案组、数值缺省组、KEYSHAPE 组先例沿用） |
| app.providers.deepseek.xǁDeepSeekProviderǁchat__mutmut_115 | A | 同 m112 | 等价/不可达或条款未钉（C1-8 观察 4 列缺省兜底、log 文案组、数值缺省组、KEYSHAPE 组先例沿用） |
| app.providers.deepseek.xǁDeepSeekProviderǁchat__mutmut_13 | A | effective_tier None→''：tier_request 非 'reasoner' 同走 chat 档，判定域等价 | 等价/不可达或条款未钉（C1-8 观察 4 列缺省兜底、log 文案组、数值缺省组、KEYSHAPE 组先例沿用） |
| app.providers.deepseek.xǁDeepSeekProviderǁchat__mutmut_15 | A | fallback_note 文案 XX 包裹（留因=presence 已钉，措辞无条款） | 等价/不可达或条款未钉（C1-8 观察 4 列缺省兜底、log 文案组、数值缺省组、KEYSHAPE 组先例沿用） |
| app.providers.deepseek.xǁDeepSeekProviderǁchat__mutmut_16 | A | fallback_note 文案大写变体 | 等价/不可达或条款未钉（C1-8 观察 4 列缺省兜底、log 文案组、数值缺省组、KEYSHAPE 组先例沿用） |
| app.providers.deepseek.xǁDeepSeekProviderǁchat__mutmut_160 | A | JSONParseError 消息文本 None（异常类型面已钉；消息措辞无条款，分账靠类型名不受影响） | 等价/不可达或条款未钉（C1-8 观察 4 列缺省兜底、log 文案组、数值缺省组、KEYSHAPE 组先例沿用） |
| app.providers.deepseek.xǁDeepSeekProviderǁchat__mutmut_2 | A | temperature 缺省值——全部调用点显式传参（scoring 0.0/hot 0.0/pipeline 显式），缺省不可达 | 等价/不可达或条款未钉（C1-8 观察 4 列缺省兜底、log 文案组、数值缺省组、KEYSHAPE 组先例沿用） |
| app.providers.deepseek.xǁDeepSeekProviderǁchat__mutmut_27 | A | build 的 tier!=='XXreasonerXX'：reasoner 档多加的 response_format 随即被 tier_request pop（双保险兜底，判定域等价） | 等价/不可达或条款未钉（C1-8 观察 4 列缺省兜底、log 文案组、数值缺省组、KEYSHAPE 组先例沿用） |
| app.providers.deepseek.xǁDeepSeekProviderǁchat__mutmut_28 | A | 同 m27（大写变体，pop 兜底等价） | 等价/不可达或条款未钉（C1-8 观察 4 列缺省兜底、log 文案组、数值缺省组、KEYSHAPE 组先例沿用） |
| app.providers.deepseek.xǁDeepSeekProviderǁchat__mutmut_4 | A | fallback_note 初值 ''→真值域与 None 同为 falsy，消费方按真值判（等价） | 等价/不可达或条款未钉（C1-8 观察 4 列缺省兜底、log 文案组、数值缺省组、KEYSHAPE 组先例沿用） |
| app.providers.deepseek.xǁDeepSeekProviderǁchat__mutmut_64 | A | reasoning_effort-only payload 不可达（thinking_params 模式 thinking 恒伴随） | 等价/不可达或条款未钉（C1-8 观察 4 列缺省兜底、log 文案组、数值缺省组、KEYSHAPE 组先例沿用） |
| app.providers.deepseek.xǁDeepSeekProviderǁchat__mutmut_65 | A | 同 m64（大写变体） | 等价/不可达或条款未钉（C1-8 观察 4 列缺省兜底、log 文案组、数值缺省组、KEYSHAPE 组先例沿用） |
| app.providers.deepseek.xǁDeepSeekProviderǁchat__mutmut_66 | A | 同 m64（not in 变体，无 thinking 时双 False 等价） | 等价/不可达或条款未钉（C1-8 观察 4 列缺省兜底、log 文案组、数值缺省组、KEYSHAPE 组先例沿用） |
| app.providers.deepseek.xǁDeepSeekProviderǁchat__mutmut_79 | A | fallback_note 文案 XX 包裹 | 等价/不可达或条款未钉（C1-8 观察 4 列缺省兜底、log 文案组、数值缺省组、KEYSHAPE 组先例沿用） |
| app.providers.deepseek.xǁDeepSeekProviderǁchat__mutmut_80 | A | fallback_note 文案大写变体 | 等价/不可达或条款未钉（C1-8 观察 4 列缺省兜底、log 文案组、数值缺省组、KEYSHAPE 组先例沿用） |
| app.providers.deepseek.xǁDeepSeekProviderǁchat__mutmut_82 | A | log.warning 文案/实参变体（log 文案组先例） | 等价/不可达或条款未钉（C1-8 观察 4 列缺省兜底、log 文案组、数值缺省组、KEYSHAPE 组先例沿用） |
| app.providers.deepseek.xǁDeepSeekProviderǁchat__mutmut_83 | A | 同 m82 | 等价/不可达或条款未钉（C1-8 观察 4 列缺省兜底、log 文案组、数值缺省组、KEYSHAPE 组先例沿用） |
| app.providers.deepseek.xǁDeepSeekProviderǁchat__mutmut_84 | A | 同 m82 | 等价/不可达或条款未钉（C1-8 观察 4 列缺省兜底、log 文案组、数值缺省组、KEYSHAPE 组先例沿用） |
| app.providers.deepseek.xǁDeepSeekProviderǁchat__mutmut_85 | A | 同 m82 | 等价/不可达或条款未钉（C1-8 观察 4 列缺省兜底、log 文案组、数值缺省组、KEYSHAPE 组先例沿用） |
| app.pipeline.runner.x_process_fetch_round__mutmut_42 | B | continue→break 位于 _claim 失败分支（CAS 认领竞争防御）：单 worker 判定域不可达（ADR-2 单机单进程，测试内 claim 恒成功）；设计书明确要求该分支存在 | 技术书 §4.2 状态机 CAS + P0-1 条款面（任务书 §2 B 类候选原案）；_claim docstring「已被其他 worker 抢走则返回 False」 |

## F1⑩ 残余对账补登（2026-10-05，26 条 = import-time 盲区 21 + interleave 死代码 4 + bootstrap 1）

> C1 收官对账口径：seeds ∩ dispatch 幸存 − 豁免清单 = 62 条未登记。本节补登 26 条已归因项；
> 2 条 null 语义（app.authors.schema.x__validate_output__mutmut_44 / x__validate_route__mutmut_256）
> 由 F1⑧ 测试杀灭不豁免；其余 34 条逐条施加复核（结果见 F1 汇报 §4，补测者不在豁免清单）。

| mutant 全名 | 类别 | 一句话理由 | 依据条款或推理 |
|---|---|---|---|
| app.api.routes.x_interleave_low_score__mutmut_10 | A | 穿插低分段的死代码行变异（行 408-409，分支构造上不可达） | 真等价（C1 收官定案：死代码行 408-409） |
| app.api.routes.x_interleave_low_score__mutmut_14 | A | 同上（死代码行变体） | 同上 |
| app.api.routes.x_interleave_low_score__mutmut_22 | A | 同上（死代码行变体） | 同上 |
| app.api.routes.x_interleave_low_score__mutmut_37 | A | 同上（死代码行变体） | 同上 |
| app.embedding.registry.x_register__mutmut_1 | A | 注册表导入期执行：mutmut 运行时激活模型结构性不可杀导入期代码（手工施加已证可杀） | import-time 激活盲区（C1-8 手工验证先例；harness 不可杀=豁免注记） |
| app.rerank.registry.x__fixed__mutmut_1 | A | 同上（导入期执行的固定候选集注册） | 同上 |
| app.rerank.registry.x__fixed__mutmut_2 | A | 同上 | 同上 |
| app.rerank.registry.x__fixed__mutmut_3 | A | 同上 | 同上 |
| app.rerank.registry.x__fixed__mutmut_4 | A | 同上 | 同上 |
| app.rerank.registry.x__fixed_neohorse__mutmut_1 | A | 同上（导入期执行的 NeoHorse 候选集注册） | 同上 |
| app.rerank.registry.x__fixed_neohorse__mutmut_2 | A | 同上 | 同上 |
| app.rerank.registry.x__fixed_neohorse__mutmut_3 | A | 同上 | 同上 |
| app.rerank.registry.x__fixed_neohorse__mutmut_4 | A | 同上 | 同上 |
| app.rerank.registry.x__fixed_neohorse__mutmut_5 | A | 同上 | 同上 |
| app.rerank.registry.x__fixed_neohorse__mutmut_6 | A | 同上 | 同上 |
| app.rerank.registry.x__fixed_neohorse__mutmut_7 | A | 同上 | 同上 |
| app.rerank.registry.x__fixed_neohorse__mutmut_8 | A | 同上 | 同上 |
| app.rerank.registry.x__fixed_neohorse__mutmut_9 | A | 同上 | 同上 |
| app.rerank.registry.x__fixed_neohorse__mutmut_10 | A | 同上 | 同上 |
| app.rerank.registry.x__fixed_neohorse__mutmut_11 | A | 同上 | 同上 |
| app.rerank.registry.x__fixed_neohorse__mutmut_12 | A | 同上 | 同上 |
| app.rerank.registry.x__fixed_neohorse__mutmut_13 | A | 同上 | 同上 |
| app.rerank.registry.x__fixed_neohorse__mutmut_14 | A | 同上 | 同上 |
| app.rerank.registry.x__fixed_neohorse__mutmut_15 | A | 同上 | 同上 |
| app.search.registry.x_register__mutmut_1 | A | 同上（搜索注册表导入期执行） | 同上 |

## F1⑩ 残余复核 A 类补登（2026-10-05，25 条；逐条施加→全量测试→还原定案）

> 复核手法：C1 系列库级重建（0959dc6 源码 mutate_file_contents + 变更对文本施加），
> 每条施加后跑全量 365 测试——全部存活即确认测试域内等价/不可达。数据：
> doc/F1/F1-10-残余复核-施加结果.json（31 条）与 F1-10-C类杀灭验证.json（6 条 C 由
> 本批新测试杀灭，不在本表）。另：rss fetch_source m19/m21/m23（follow_redirects/
> max_redirects 行）已被 F1① 行重写吸收，新行同族变异由客户端契约测试杀灭，不豁免。

| mutant 全名 | 类别 | 一句话理由 | 依据条款或推理 |
|---|---|---|---|
| app.ingest.fingerprint.x_canonical_url__mutmut_9 | A | urlparse 对 scheme 恒输出小写 → lower()/upper() 两侧同为常量变换，指纹相等关系不变 | 变换一致性推理（判定域内全部指纹经同一函数） |
| app.ingest.fingerprint.x_find_fingerprint_origin__mutmut_1 | A | order_by(None)：SQLite 判定域内 (direction_id,fingerprint) 索引扫描序 ≡ rowid 序 ≡ min id，选择结果不变；order_by 为 min id 条款的显式化（本批已落钉死测试） | SQLite 索引序推理 + 钉死测试补强 |
| app.ingest.rss.x__entry_published__mutmut_2 | A | or→and：feedparser 对仅 pubDate 的条目回填 updated=published → and 分支实得 published_parsed，返回值不变 | feedparser 回填判据族（C1 收官方法学；本环境实测复证） |
| app.ingest.rss.x__entry_published__mutmut_3 | A | get(None) 恒 None → st 取 updated_parsed = feedparser 回填值，返回值不变 | 同上 |
| app.ingest.rss.x__entry_published__mutmut_4 | A | 键名 XX 变体 miss → st 取 updated_parsed（回填） | 同上 |
| app.ingest.rss.x__entry_published__mutmut_5 | A | 键名大写变体 miss → 同上 | 同上 |
| app.ingest.rss.x_fetch_source__mutmut_161 | A | httpx.Headers 大小写不敏感：get("ETAG") ≡ get("etag") | httpx.Headers 契约（线缆小写判据族邻域） |
| app.providers.base.x__scrub__mutmut_2 | A | if (text) or True → 恒取 replace 分支：空串 replace 自身仍为空串，两分支等价 | 恒真条件等价推理 |
| app.providers.base.x_parse_strict_json__mutmut_22 | A | start==-2 使无 "{" 场景落入切片解析 → 仍抛 JSONParseError（消息路径不同，文案无条款） | C1-7 文案措辞先例 + 异常类型不变 |
| app.providers.base.xǁLLMProviderǁ_call__mutmut_54 | A | prompt_tokens 缺省值不可达：_post 契约必填键（模块 docstring），deepseek/moark_jev 构造均显式含键 | _post 计量契约（base.py docstring） |
| app.providers.base.xǁLLMProviderǁ_call__mutmut_61 | A | completion_tokens 缺省不可达：同上 | 同上 |
| app.providers.base.xǁLLMProviderǁ_call__mutmut_68 | A | billing_units 缺省不可达：同上 | 同上 |
| app.providers.base.xǁLLMProviderǁ_call__mutmut_75 | A | cache_hit_tokens=None：UsageLog.cache_hit_tokens 列 default=0 兜底（moark_jev meter 缺键场景由列缺省承载） | 列缺省兜底判据族 |
| app.providers.base.xǁLLMProviderǁ_call__mutmut_82 | A | reasoning_tokens=None：同上 | 同上 |
| app.providers.base.xǁLLMProviderǁ_call__mutmut_103 | A | getattr(e,"retryable",False)→None：ProviderError 类属性 retryable=False 恒存在，缺省分支不可达，None/False 同为假 | 类属性兜底（providers/base.py:41） |
| app.providers.base.xǁLLMProviderǁ_call__mutmut_106 | A | 去掉缺省参数：类属性 retryable=False 恒存在 → getattr 两参形态同值 | 同上 |
| app.providers.base.xǁLLMProviderǁ_call__mutmut_26 | A | ok=None：UsageLog.ok 列 default=True 兜底 | 列缺省兜底判据族 |

---

## C2-0 同步记录（2026-10-05，统筹亲执：豁免清单与统一 dispatch 结果再同步）

> 依据 run 37276946376（main @ 8c5f515）逐名核对：表行 1597 条全部可对名，其中 **202 条已转 killed——本节移除**，余 1395 条仍幸存（豁免维持）。
> 方法与数据：`doc/C2/C2-0-数据/`（表行名字全集 + 转killed名单）；核验脚本 `doc/C2/C2-0-核验.py`（豁免⊆当前幸存 + 未登记幸存统计）。
> **口径警示（C2-1~4 分诊须知）**：名字位转 killed ≠ 原等价变异必然消失——G2 改写使同名位可能承载新变异；原等价位若仍存在，应以新编号出现在未登记幸存池（845 条）中，由分诊批次回收判类。

**移除明细（按原批次节 × 202 条）**：
- ## F1⑩ 残余复核 A 类补登（2026-10-05，25 条；逐条施加→全量测试→还原定案）：3 条（app.ingest.rss 3）
- ## 批次 10：外部能力家族收官 hot/search/rerank/embedding（2026-10-04，C1-8）：14 条（app.search.pipeline 7, app.hot.service 3, app.rerank.jev_rank 3, app.search.quota 1）
- ## 批次 11：C1-9a 补扫——pipeline.runner / providers.deepseek / config（96 A + 1 B = 97 条）：21 条（app.pipeline.runner 21）
- ## 批次 1：认证域（14 A + 1 B = 15 条）：2 条（app.api.deps 2）
- ## 批次 2：providers.base + T1 三条 D 转 C（2026-10-03，C1-1）：11 条（app.providers.base 11）
- ## 批次 3：db / main / scheduler 薄弱带（2026-10-03，C1-2）：35 条（app.db 33, app.main 2）
- ## 批次 4：ingest.web 定点监测带（2026-10-03，C1-3）：11 条（app.ingest.web 11）
- ## 批次 5：ingest.rss 主带 + 小模块 + C1-1 十三条 D 转 C（2026-10-03，C1-4）：37 条（app.ingest.rss 29, app.ingest.rules 5, app.providers.base 3）
- ## 批次 6：authors.pipeline 执行器核心 PipelineRunner（2026-10-03，C1-5a）：45 条（app.authors.pipeline 45）
- ## 批次 7：authors.pipeline 模块级函数（2026-10-03，C1-5b）：7 条（app.authors.pipeline 7）
- ## 批次 9：authors 域收官（writer/gates/memory/importer）（2026-10-04，C1-7）：16 条（app.authors.writer 15, app.authors.gates 1）

同步后清单规模：1395 条（1597 − 202）。
## C2-1 分诊批次 1（2026-10-05，pipeline.runner 213 + skip_policy 13）：A 98 + B 2 = 100 条

> 种子=统一 dispatch run 37276946376（main @ 8c5f515）未登记幸存者之 runner/skip_policy 域
> （doc/C2/C2-1-种子.jsonl）。diff 经 mutmut 3.8.0 库级静态重建（app/ 自 8c5f515 零变化，
> 变异体名与当前树 1:1 对名），逐条施加→跑本批判据面测试→还原定案。终态：**C 125/125 全杀**
> （tests/test_source_health_state_machine.py 等 5 文件 39 测试，不在本清单）、**A 98/98 全活**、
> **B 2 存活（B 不杀）**、D 1 条出问题清单（见 doc/C2/C2-1-执行Agent工作汇报.md §三，不豁免）.
> 核验-改判 4 轮共 14 条改判（A→C 13：rescore has_failed 条件位 None/取反×4〔SQLAlchemy where/filter
> 混入 None 即恒假，本版实证〕、scope=None 误路由×1、异常路径 WARNING 级日志格式破坏×5〔pytest 捕获句柄
> 使格式错误可观察，C1-9a 处理路径面先例〕、has_ok 失 status 过滤与 process m6 计数域等价改判 C 后回改 A 另计；
> C→A 1：process_rescore m6 PENDING 过滤移除经 _claim CAS 兜底）。数据：doc/C2/C2-1-重建-diff.json、
> doc/C2/C2-1-核验结果.json、doc/C2/C2-1-核验.py（定案表）.

| mutant 全名 | 类别 | 一句话理由 | 依据条款或推理 |
|---|---|---|---|
| app.pipeline.runner.x__error_stats__mutmut_11 | A | 异常路径最小 stats 的字段缺省变体：消费侧 or/bool/getattr 缺省全部吸收；删键被 getattr 默认兜底（C1 列缺省/兜底判据族） | 等价/不可达或条款未钉（C1 判据族沿用） |
| app.pipeline.runner.x__error_stats__mutmut_12 | A | 异常路径最小 stats 的字段缺省变体：消费侧 or/bool/getattr 缺省全部吸收；删键被 getattr 默认兜底（C1 列缺省/兜底判据族） | 等价/不可达或条款未钉（C1 判据族沿用） |
| app.pipeline.runner.x__error_stats__mutmut_13 | A | 异常路径最小 stats 的字段缺省变体：消费侧 or/bool/getattr 缺省全部吸收；删键被 getattr 默认兜底（C1 列缺省/兜底判据族） | 等价/不可达或条款未钉（C1 判据族沿用） |
| app.pipeline.runner.x__error_stats__mutmut_14 | A | feed_entries/inserted=1：异常轮 error 非 None，entries/inserted 的全部消费分支以 error is None 为前件，不可达 | 等价/不可达或条款未钉（C1 判据族沿用） |
| app.pipeline.runner.x__error_stats__mutmut_15 | A | feed_entries/inserted=1：异常轮 error 非 None，entries/inserted 的全部消费分支以 error is None 为前件，不可达 | 等价/不可达或条款未钉（C1 判据族沿用） |
| app.pipeline.runner.x__error_stats__mutmut_2 | A | 异常路径最小 stats 的字段缺省变体：消费侧 or/bool/getattr 缺省全部吸收；删键被 getattr 默认兜底（C1 列缺省/兜底判据族） | 等价/不可达或条款未钉（C1 判据族沿用） |
| app.pipeline.runner.x__error_stats__mutmut_3 | A | 异常路径最小 stats 的字段缺省变体：消费侧 or/bool/getattr 缺省全部吸收；删键被 getattr 默认兜底（C1 列缺省/兜底判据族） | 等价/不可达或条款未钉（C1 判据族沿用） |
| app.pipeline.runner.x__error_stats__mutmut_4 | A | 异常路径最小 stats 的字段缺省变体：消费侧 or/bool/getattr 缺省全部吸收；删键被 getattr 默认兜底（C1 列缺省/兜底判据族） | 等价/不可达或条款未钉（C1 判据族沿用） |
| app.pipeline.runner.x__error_stats__mutmut_5 | A | 异常路径最小 stats 的字段缺省变体：消费侧 or/bool/getattr 缺省全部吸收；删键被 getattr 默认兜底（C1 列缺省/兜底判据族） | 等价/不可达或条款未钉（C1 判据族沿用） |
| app.pipeline.runner.x__error_stats__mutmut_6 | A | 异常路径最小 stats 的字段缺省变体：消费侧 or/bool/getattr 缺省全部吸收；删键被 getattr 默认兜底（C1 列缺省/兜底判据族） | 等价/不可达或条款未钉（C1 判据族沿用） |
| app.pipeline.runner.x__fetch_stats_dict__mutmut_15 | A | getattr 缺省值变体：SourceFetchStats 数据类字段恒在（rss/web/search 共用），缺省分支不可达 | 等价/不可达或条款未钉（C1 判据族沿用） |
| app.pipeline.runner.x__fetch_stats_dict__mutmut_21 | A | getattr 缺省值变体：SourceFetchStats 数据类字段恒在（rss/web/search 共用），缺省分支不可达 | 等价/不可达或条款未钉（C1 判据族沿用） |
| app.pipeline.runner.x__fetch_stats_dict__mutmut_33 | A | getattr 缺省值变体：SourceFetchStats 数据类字段恒在（rss/web/search 共用），缺省分支不可达 | 等价/不可达或条款未钉（C1 判据族沿用） |
| app.pipeline.runner.x__fetchable_sources__mutmut_6 | A | join onclause None/省略：SQLAlchemy 回退 FK 推断，连接条件不变（实现形态等价） | 等价/不可达或条款未钉（C1 判据族沿用） |
| app.pipeline.runner.x__fetchable_sources__mutmut_8 | A | join onclause None/省略：SQLAlchemy 回退 FK 推断，连接条件不变（实现形态等价） | 等价/不可达或条款未钉（C1 判据族沿用） |
| app.pipeline.runner.x__rescore_candidate_ids__mutmut_16 | A | has_ok/has_current_ok 去方向过滤：item×direction 一一对应（条目行恒带本方向），判定域内集合相同 | 等价/不可达或条款未钉（C1 判据族沿用） |
| app.pipeline.runner.x__rescore_candidate_ids__mutmut_28 | A | join onclause None/省略：FK 推断等价（实现形态） | 等价/不可达或条款未钉（C1 判据族沿用） |
| app.pipeline.runner.x__rescore_candidate_ids__mutmut_30 | A | join onclause None/省略：FK 推断等价（实现形态） | 等价/不可达或条款未钉（C1 判据族沿用） |
| app.pipeline.runner.x__rescore_candidate_ids__mutmut_40 | A | has_failed 方向过滤移除：item×direction 一一对应，跨方向条目 id 不相交，判定域等价 | 等价/不可达或条款未钉（C1 判据族沿用） |
| app.pipeline.runner.x__rescore_candidate_ids__mutmut_41 | A | has_failed status 过滤去/丢：全行 ∩ 无 OK 行 = FAILED-only 行，与原判定等价（status 域仅 OK/FAILED） | 等价/不可达或条款未钉（C1 判据族沿用） |
| app.pipeline.runner.x__rescore_candidate_ids__mutmut_5 | A | has_ok/has_current_ok 去方向过滤：item×direction 一一对应（条目行恒带本方向），判定域内集合相同 | 等价/不可达或条款未钉（C1 判据族沿用） |
| app.pipeline.runner.x__rescore_candidate_ids__mutmut_51 | A | 单连言删除后剩余条件与原判定同集（in(failed) ≡ in(failed)∩~in(ok)，FAILED-only 行无 OK 行） | 等价/不可达或条款未钉（C1 判据族沿用） |
| app.pipeline.runner.x__rescore_candidate_ids__mutmut_78 | A | order_by(None)：SQLite 判定域内索引序 ≡ rowid 序 ≡ min id，批次切分序不变（F1⑩ fingerprint 先例判据族） | 等价/不可达或条款未钉（C1 判据族沿用） |
| app.pipeline.runner.x__update_source_health__mutmut_103 | A | last_error 截断界 [:2000]→[:2001]：截断界数值无条款（C1 _finish m24 判据族；Text 列） | 等价/不可达或条款未钉（C1 判据族沿用） |
| app.pipeline.runner.x__update_source_health__mutmut_179 | A | 退避段 getattr 变体：本段以 error is not None 为前件，判定域内 error 轮 rate_limited 恒 False（429 早返回 error=None），子句恒真等价 | 等价/不可达或条款未钉（C1 判据族沿用） |
| app.pipeline.runner.x__update_source_health__mutmut_7 | A | getattr 缺省 None 被 or {} 吸收（缺省兜底判据族） | 等价/不可达或条款未钉（C1 判据族沿用） |
| app.pipeline.runner.x__update_source_health__mutmut_76 | A | failure_since 时间戳赋 None：时间戳值无条款（仅 failure_level 有钉面），无断言面 | 等价/不可达或条款未钉（C1 判据族沿用） |
| app.pipeline.runner.x_enqueue_fetch_round__mutmut_24 | A | expire_due_temp_directions now=None：函数内兜底 fresh now，与调用侧 now 仅微秒差，TTL 天级判定域等价（datetime 判据族） | 等价/不可达或条款未钉（C1 判据族沿用） |
| app.pipeline.runner.x_enqueue_fetch_round__mutmut_26 | A | expire_due_temp_directions now=None：函数内兜底 fresh now，与调用侧 now 仅微秒差，TTL 天级判定域等价（datetime 判据族） | 等价/不可达或条款未钉（C1 判据族沿用） |
| app.pipeline.runner.x_enqueue_fetch_round__mutmut_32 | A | directions.get 变体：_fetchable_sources 已滤定 direction 恒 active，skip_reason 方向分支判定域不可达（方向上下文等价） | 等价/不可达或条款未钉（C1 判据族沿用） |
| app.pipeline.runner.x_enqueue_fetch_round__mutmut_37 | A | directions.get 变体：_fetchable_sources 已滤定 direction 恒 active，skip_reason 方向分支判定域不可达（方向上下文等价） | 等价/不可达或条款未钉（C1 判据族沿用） |
| app.pipeline.runner.x_enqueue_fetch_round__mutmut_47 | A | 探测放行 INFO 日志文案/实参变体：logger 缺省 WARNING 级不格式化 INFO 记录，判定域不可达（log 文案组判据；m97 对比：WARNING 级格式破坏已被实证杀灭归 C） | 等价/不可达或条款未钉（C1 判据族沿用） |
| app.pipeline.runner.x_enqueue_fetch_round__mutmut_48 | A | 探测放行 INFO 日志文案/实参变体：logger 缺省 WARNING 级不格式化 INFO 记录，判定域不可达（log 文案组判据；m97 对比：WARNING 级格式破坏已被实证杀灭归 C） | 等价/不可达或条款未钉（C1 判据族沿用） |
| app.pipeline.runner.x_enqueue_fetch_round__mutmut_52 | A | 探测放行 INFO 日志文案/实参变体：logger 缺省 WARNING 级不格式化 INFO 记录，判定域不可达（log 文案组判据；m97 对比：WARNING 级格式破坏已被实证杀灭归 C） | 等价/不可达或条款未钉（C1 判据族沿用） |
| app.pipeline.runner.x_enqueue_fetch_round__mutmut_54 | A | 探测放行 INFO 日志文案/实参变体：logger 缺省 WARNING 级不格式化 INFO 记录，判定域不可达（log 文案组判据；m97 对比：WARNING 级格式破坏已被实证杀灭归 C） | 等价/不可达或条款未钉（C1 判据族沿用） |
| app.pipeline.runner.x_enqueue_fetch_round__mutmut_55 | A | 探测放行 INFO 日志文案/实参变体：logger 缺省 WARNING 级不格式化 INFO 记录，判定域不可达（log 文案组判据；m97 对比：WARNING 级格式破坏已被实证杀灭归 C） | 等价/不可达或条款未钉（C1 判据族沿用） |
| app.pipeline.runner.x_enqueue_fetch_round__mutmut_56 | A | 探测放行 INFO 日志文案/实参变体：logger 缺省 WARNING 级不格式化 INFO 记录，判定域不可达（log 文案组判据；m97 对比：WARNING 级格式破坏已被实证杀灭归 C） | 等价/不可达或条款未钉（C1 判据族沿用） |
| app.pipeline.runner.x_expire_due_temp_directions__mutmut_11 | A | expires_at 非空过滤移除：SQL 三值逻辑 NULL <= now 恒假，行不会被匹配 | 等价 |
| app.pipeline.runner.x_expire_due_temp_directions__mutmut_17 | A | <= → < 等号边界：AC-03.4「TTL 到期后停用」未钉等号瞬间，无断言面（断言两档纪律禁造等号断言） | 等价/不可达或条款未钉（C1 判据族沿用） |
| app.pipeline.runner.x_expire_due_temp_directions__mutmut_3 | A | datetime.now(None) naive local：UTC 判定域（CI runner）等价 | C1 reclaim m3 判据族（CI-0 实证存活先例） |
| app.pipeline.runner.x_expire_due_temp_directions__mutmut_9 | A | temp 过滤移除：expires_at 仅 temp 方向可写（routes 恒 temp→expires_at 否则 None），非 temp 恒 NULL 被下一条件滤除 | 不可达 |
| app.pipeline.runner.x_fetch_round__mutmut_25 | A | task.status 字面量变体：_finish 内存同步 + 后续健康提交将 ORM 脏值回写修复，终态恒 DONE/FAILED | 批次11 fetch_round m26/27 同语句判据族（C1-9a 实证） |
| app.pipeline.runner.x_fetch_round__mutmut_77 | A | 异常消息 type 名变体：错误消息措辞无条款（文案组判据——批次11 m61/62 同款） | 等价/不可达或条款未钉（C1 判据族沿用） |
| app.pipeline.runner.x_process_fetch_round__mutmut_116 | A | 同 fetch_round m77 判据（异常消息文案组） | 等价/不可达或条款未钉（C1 判据族沿用） |
| app.pipeline.runner.x_process_rescore_tasks__mutmut_103 | A | 单条异常 WARN 文案/实参变体：格式化不破坏（log 文案组，C1 判据族） | 等价/不可达或条款未钉（C1 判据族沿用） |
| app.pipeline.runner.x_process_rescore_tasks__mutmut_136 | A | out.append 结果字典键/形态变体：返回值唯一调用方 score_round 不接收（无消费方，无断言面） | 等价/不可达或条款未钉（C1 判据族沿用） |
| app.pipeline.runner.x_process_rescore_tasks__mutmut_137 | A | out.append 结果字典键/形态变体：返回值唯一调用方 score_round 不接收（无消费方，无断言面） | 等价/不可达或条款未钉（C1 判据族沿用） |
| app.pipeline.runner.x_process_rescore_tasks__mutmut_138 | A | out.append 结果字典键/形态变体：返回值唯一调用方 score_round 不接收（无消费方，无断言面） | 等价/不可达或条款未钉（C1 判据族沿用） |
| app.pipeline.runner.x_process_rescore_tasks__mutmut_139 | A | out.append 结果字典键/形态变体：返回值唯一调用方 score_round 不接收（无消费方，无断言面） | 等价/不可达或条款未钉（C1 判据族沿用） |
| app.pipeline.runner.x_process_rescore_tasks__mutmut_140 | A | out.append 结果字典键/形态变体：返回值唯一调用方 score_round 不接收（无消费方，无断言面） | 等价/不可达或条款未钉（C1 判据族沿用） |
| app.pipeline.runner.x_process_rescore_tasks__mutmut_141 | A | out.append 结果字典键/形态变体：返回值唯一调用方 score_round 不接收（无消费方，无断言面） | 等价/不可达或条款未钉（C1 判据族沿用） |
| app.pipeline.runner.x_process_rescore_tasks__mutmut_142 | A | out.append 结果字典键/形态变体：返回值唯一调用方 score_round 不接收（无消费方，无断言面） | 等价/不可达或条款未钉（C1 判据族沿用） |
| app.pipeline.runner.x_process_rescore_tasks__mutmut_143 | A | out.append 结果字典键/形态变体：返回值唯一调用方 score_round 不接收（无消费方，无断言面） | 等价/不可达或条款未钉（C1 判据族沿用） |
| app.pipeline.runner.x_process_rescore_tasks__mutmut_144 | A | out.append 结果字典键/形态变体：返回值唯一调用方 score_round 不接收（无消费方，无断言面） | 等价/不可达或条款未钉（C1 判据族沿用） |
| app.pipeline.runner.x_process_rescore_tasks__mutmut_35 | A | 缺省字面量 XXallXX/ALL：走 else 分支与 all 同值（等价） | 等价/不可达或条款未钉（C1 判据族沿用） |
| app.pipeline.runner.x_process_rescore_tasks__mutmut_36 | A | 缺省字面量 XXallXX/ALL：走 else 分支与 all 同值（等价） | 等价/不可达或条款未钉（C1 判据族沿用） |
| app.pipeline.runner.x_process_rescore_tasks__mutmut_50 | A | error 文案变体：presence 已钉（m43 测试），措辞无条款（文案组判据） | 等价/不可达或条款未钉（C1 判据族沿用） |
| app.pipeline.runner.x_process_rescore_tasks__mutmut_51 | A | error 文案变体：presence 已钉（m43 测试），措辞无条款（文案组判据） | 等价/不可达或条款未钉（C1 判据族沿用） |
| app.pipeline.runner.x_process_rescore_tasks__mutmut_52 | A | out.append 结果字典键/形态变体：返回值唯一调用方 score_round 不接收（无消费方，无断言面） | 等价/不可达或条款未钉（C1 判据族沿用） |
| app.pipeline.runner.x_process_rescore_tasks__mutmut_53 | A | out.append 结果字典键/形态变体：返回值唯一调用方 score_round 不接收（无消费方，无断言面） | 等价/不可达或条款未钉（C1 判据族沿用） |
| app.pipeline.runner.x_process_rescore_tasks__mutmut_54 | A | out.append 结果字典键/形态变体：返回值唯一调用方 score_round 不接收（无消费方，无断言面） | 等价/不可达或条款未钉（C1 判据族沿用） |
| app.pipeline.runner.x_process_rescore_tasks__mutmut_55 | A | out.append 结果字典键/形态变体：返回值唯一调用方 score_round 不接收（无消费方，无断言面） | 等价/不可达或条款未钉（C1 判据族沿用） |
| app.pipeline.runner.x_process_rescore_tasks__mutmut_56 | A | out.append 结果字典键/形态变体：返回值唯一调用方 score_round 不接收（无消费方，无断言面） | 等价/不可达或条款未钉（C1 判据族沿用） |
| app.pipeline.runner.x_process_rescore_tasks__mutmut_6 | A | PENDING 过滤移除：非 PENDING 任务被 _claim 的 WHERE status='PENDING' CAS 复核拒绝（双保险，行为面等价） | 批次11 process_fetch_round m17 同款判据 |
| app.pipeline.runner.x_process_rescore_tasks__mutmut_98 | A | 单条异常 WARN 文案/实参变体：格式化不破坏（log 文案组，C1 判据族） | 等价/不可达或条款未钉（C1 判据族沿用） |
| app.pipeline.runner.x_process_rescore_tasks__mutmut_99 | A | 单条异常 WARN 文案/实参变体：格式化不破坏（log 文案组，C1 判据族） | 等价/不可达或条款未钉（C1 判据族沿用） |
| app.pipeline.skip_policy.x__aware__mutmut_1 | A | 恒走 replace(tzinfo=utc) 分支：判定域内 datetime 恒 utc-aware 或 naive，aware 非 UTC 输入不存在（与 else 分支同值） | 等价/不可达或条款未钉（C1 判据族沿用） |
| app.pipeline.skip_policy.x_reset_keyword_backoff__mutmut_13 | A | 返回计数 n 的初值/条件/步进变体：返回值无消费方（routes/hot 均不接收），计数无条款（C1 数值缺省组判据） | 等价/不可达或条款未钉（C1 判据族沿用） |
| app.pipeline.skip_policy.x_reset_keyword_backoff__mutmut_14 | A | 返回计数 n 的初值/条件/步进变体：返回值无消费方（routes/hot 均不接收），计数无条款（C1 数值缺省组判据） | 等价/不可达或条款未钉（C1 判据族沿用） |
| app.pipeline.skip_policy.x_reset_keyword_backoff__mutmut_15 | A | 返回计数 n 的初值/条件/步进变体：返回值无消费方（routes/hot 均不接收），计数无条款（C1 数值缺省组判据） | 等价/不可达或条款未钉（C1 判据族沿用） |
| app.pipeline.skip_policy.x_skip_reason__mutmut_39 | A | or 0→1：falsy 时 0/1 均 < BACKOFF_FAIL_THRESHOLD(3)，判定域等价（批次11 enqueue m51 同款判据） | 等价/不可达或条款未钉（C1 判据族沿用） |
| app.pipeline.runner.x_process_rescore_tasks__mutmut_19 | B | claim 失败 continue → break：CAS 认领竞争防御分支，单 worker 判定域不可达（ADR-2 单机单进程，测试内认领恒成功） | 批次11 process m42 B 判据族 |
| app.pipeline.runner.x_process_rescore_tasks__mutmut_74 | B | 候选条目缺失 continue → break：同批内 db.get 与候选查询同会话，单进程判定域不可达（防御分支，设计要求存在） | 批次11 m42 同款判据 |

## C2-2 分诊批次 2（2026-10-05，authors.pipeline 176 + authors.gates 43）：A 143 条

> 种子=统一 dispatch run 37276946376（main @ 8c5f515）未登记幸存者之 authors 域
> （doc/C2/C2-2-种子.jsonl）。diff 经 mutmut 3.8.0 库级静态重建（app/ 自 8c5f515 零变化，
> 变异体名与当前树 1:1 对名；PipelineRunner 类方法变异体在类体内同缩进对位拼接、
> def 行还原原名），逐条施加→跑本批判据面测试→还原定案。终态：**C 76/76 全杀**
> （tests/test_author_gates_echo_dice.py 6 + tests/test_pipeline_json_node_retry.py 3 +
> tests/test_pipeline_revision_passes.py 4 = 13 测试，C 类不在本清单）、**A 143/143 全活**、
> **B 0 / D 0**。核验-改判 1 轮共 3 条改判（C→A 3：gate_echo_check m9/m11/m15
> find_longest_match 实参 None/缺参经实测为 Python 3.9+ 缺省形参恰等价——首轮误判 C，
> CPython 文档 Changed in version 3.9 定案）。判据族复用：批次 6/7/9 同函数旧条目
> （文案组/数值无条款/截断界/schema 必填缺省不可达/ORM 列缺省兜底/死参数/stats 键形态/
> hint 文案面）；新实证 2 项见 C2-2 执行汇报 §四。数据：doc/C2/C2-2-重建-diff.json、
> doc/C2/C2-2-核验结果.json、doc/C2/C2-2-核验.py（定案表）.

| mutant 全名 | 类别 | 一句话理由 | 依据条款或推理 |
|---|---|---|---|
| app.authors.gates.x__bigram_dice__mutmut_1 | A | or→and：单侧 len<2 时原式 a≠b→0.0、变体侧 gram 集为空→0.0，双短串同名域被调用方 t==r 先行返回拦截——判定域真值表全等价 | 等价/不可达或条款未钉（调用点核查 + AC-20.4 阈值字面未入设计书；batch9 topic_dedup m16 判据族） |
| app.authors.gates.x__bigram_dice__mutmut_25 | A | 守卫 (ga and gb) or True：该点 len(a),len(b)≥2 已由前置守卫保证，ga/gb 恒非空，原守卫恒真——恰等价 | 等价/不可达或条款未钉（调用点核查 + AC-20.4 阈值字面未入设计书；batch9 topic_dedup m16 判据族） |
| app.authors.gates.x__bigram_dice__mutmut_30 | A | and→or：同 m25，ga/gb 恒非空使两形态同值——恰等价 | 等价/不可达或条款未钉（调用点核查 + AC-20.4 阈值字面未入设计书；batch9 topic_dedup m16 判据族） |
| app.authors.gates.x__bigram_dice__mutmut_31 | A | else 0.0→1.0：else 域需 ga 或 gb 为空，前置 len≥2 守卫下不可达——死域 | 等价/不可达或条款未钉（调用点核查 + AC-20.4 阈值字面未入设计书；batch9 topic_dedup m16 判据族） |
| app.authors.gates.x__bigram_dice__mutmut_6 | A | a==b 分支值变体：唯一调用方 gate_topic_dedup 先判 t==r 直接判重返回，a==b 到达本函数为死域（调用点核查） | 等价/不可达或条款未钉（调用点核查 + AC-20.4 阈值字面未入设计书；batch9 topic_dedup m16 判据族） |
| app.authors.gates.x__bigram_dice__mutmut_8 | A | a==b 分支值变体：唯一调用方 gate_topic_dedup 先判 t==r 直接判重返回，a==b 到达本函数为死域（调用点核查） | 等价/不可达或条款未钉（调用点核查 + AC-20.4 阈值字面未入设计书；batch9 topic_dedup m16 判据族） |
| app.authors.gates.x_gate_echo_check__mutmut_11 | A | find_longest_match 实参 None/缺参：Python 3.9+ 该方法 ahi/bhi 缺省形参即 None→len(seq)，三种形态与显式传参恰等价——语言语义判据（CPython 文档 Changed in 3.9；实测同值） | 等价/不可达或条款未钉（语言语义/CPython 3.9+ 缺省形参实测；20 阈值字面与 stats/文案未钉，batch9 判据族） |
| app.authors.gates.x_gate_echo_check__mutmut_15 | A | find_longest_match 实参 None/缺参：Python 3.9+ 该方法 ahi/bhi 缺省形参即 None→len(seq)，三种形态与显式传参恰等价——语言语义判据（CPython 文档 Changed in 3.9；实测同值） | 等价/不可达或条款未钉（语言语义/CPython 3.9+ 缺省形参实测；20 阈值字面与 stats/文案未钉，batch9 判据族） |
| app.authors.gates.x_gate_echo_check__mutmut_18 | A | autojunk=None：None 假值与 False 同 truthiness，SequenceMatcher 行为相同——语言语义恰等价 | 等价/不可达或条款未钉（语言语义/CPython 3.9+ 缺省形参实测；20 阈值字面与 stats/文案未钉，batch9 判据族） |
| app.authors.gates.x_gate_echo_check__mutmut_24 | A | find_longest_match 起点跳 1：判定面仅「匹配起点恰在串首且长度恰等于 20 字符」的界面域——20 阈值字面未入设计书（任务书§2 阈值字面判据；batch9 m16/m23 数值边界先例） | 等价/不可达或条款未钉（语言语义/CPython 3.9+ 缺省形参实测；20 阈值字面与 stats/文案未钉，batch9 判据族） |
| app.authors.gates.x_gate_echo_check__mutmut_25 | A | find_longest_match 起点跳 1：判定面仅「匹配起点恰在串首且长度恰等于 20 字符」的界面域——20 阈值字面未入设计书（任务书§2 阈值字面判据；batch9 m16/m23 数值边界先例） | 等价/不可达或条款未钉（语言语义/CPython 3.9+ 缺省形参实测；20 阈值字面与 stats/文案未钉，batch9 判据族） |
| app.authors.gates.x_gate_echo_check__mutmut_26 | A | stats['echo_max_chars']=None：stats 记录值无条款（verdict 统一形态只钉顶层四键；batch9 gate_fingerprint m5 先例） | 等价/不可达或条款未钉（语言语义/CPython 3.9+ 缺省形参实测；20 阈值字面与 stats/文案未钉，batch9 判据族） |
| app.authors.gates.x_gate_echo_check__mutmut_27 | A | stats 键名变体：stats 键名无条款（batch9 m6/m7 先例） | 等价/不可达或条款未钉（语言语义/CPython 3.9+ 缺省形参实测；20 阈值字面与 stats/文案未钉，batch9 判据族） |
| app.authors.gates.x_gate_echo_check__mutmut_28 | A | stats 键名变体：stats 键名无条款（batch9 m6/m7 先例） | 等价/不可达或条款未钉（语言语义/CPython 3.9+ 缺省形参实测；20 阈值字面与 stats/文案未钉，batch9 判据族） |
| app.authors.gates.x_gate_echo_check__mutmut_29 | A | ≥→>：恰等于 20 字符的边界含等性无条款——echo 阈值字面未入设计书（batch9 topic_dedup m16 数值边界先例；断言两档纪律禁造等号断言） | 等价/不可达或条款未钉（语言语义/CPython 3.9+ 缺省形参实测；20 阈值字面与 stats/文案未钉，batch9 判据族） |
| app.authors.gates.x_gate_echo_check__mutmut_31 | A | issue 文案内 clean 切片 +size→-size：拒收语义不变（issues 仍非空），回显摘录文案形态无条款（batch9 issue 文案先例） | 等价/不可达或条款未钉（语言语义/CPython 3.9+ 缺省形参实测；20 阈值字面与 stats/文案未钉，batch9 判据族） |
| app.authors.gates.x_gate_echo_check__mutmut_32 | A | issue 文案截断 [:40]→[:41]：文案截断界无条款（batch9 m47 先例） | 等价/不可达或条款未钉（语言语义/CPython 3.9+ 缺省形参实测；20 阈值字面与 stats/文案未钉，batch9 判据族） |
| app.authors.gates.x_gate_echo_check__mutmut_9 | A | find_longest_match 实参 None/缺参：Python 3.9+ 该方法 ahi/bhi 缺省形参即 None→len(seq)，三种形态与显式传参恰等价——语言语义判据（CPython 文档 Changed in 3.9；实测同值） | 等价/不可达或条款未钉（语言语义/CPython 3.9+ 缺省形参实测；20 阈值字面与 stats/文案未钉，batch9 判据族） |
| app.authors.pipeline.x__closest_sentence__mutmut_10 | A | 候选句长阈值 ≥12→>12/≥13：hint 候选集边界无条款（batch7 hint 判据族；文案面） | 等价/不可达或条款未钉（hint 文案面无条款；batch7 validate_citations m36/37 判据族） |
| app.authors.pipeline.x__closest_sentence__mutmut_11 | A | 候选句长阈值 ≥12→>12/≥13：hint 候选集边界无条款（batch7 hint 判据族；文案面） | 等价/不可达或条款未钉（hint 文案面无条款；batch7 validate_citations m36/37 判据族） |
| app.authors.pipeline.x__closest_sentence__mutmut_14 | A | quote 截断 [:80]→[:81]：截断界无条款（batch7 m39 先例） | 等价/不可达或条款未钉（hint 文案面无条款；batch7 validate_citations m36/37 判据族） |
| app.authors.pipeline.x__closest_sentence__mutmut_16 | A | best 初值 "XXXX"：返回受 best_ratio>0.5 守卫，初值仅死域——控制流等价 | 等价/不可达或条款未钉（hint 文案面无条款；batch7 validate_citations m36/37 判据族） |
| app.authors.pipeline.x__closest_sentence__mutmut_25 | A | 候选句截断 [:120]→[:121]：相似度计算内截断界无条款（文案/度量细节判据） | 等价/不可达或条款未钉（hint 文案面无条款；batch7 validate_citations m36/37 判据族） |
| app.authors.pipeline.x__closest_sentence__mutmut_26 | A | >→>=：并列时取末句而非首句，hint 文案面无条款（batch7 hint 先例） | 等价/不可达或条款未钉（hint 文案面无条款；batch7 validate_citations m36/37 判据族） |
| app.authors.pipeline.x__closest_sentence__mutmut_29 | A | 守卫 or True：低相似时仍回 hint——hint 空域消息形态差异，文案无条款（batch7 m36 同款先例） | 等价/不可达或条款未钉（hint 文案面无条款；batch7 validate_citations m36/37 判据族） |
| app.authors.pipeline.x__closest_sentence__mutmut_30 | A | >0.5→>=0.5：相似度回退边界含等性无条款（数值边界判据族） | 等价/不可达或条款未钉（hint 文案面无条款；batch7 validate_citations m36/37 判据族） |
| app.authors.pipeline.x__closest_sentence__mutmut_32 | A | else ""→"XXXX"：hint 占位文案形态（batch7 m36/37 先例） | 等价/不可达或条款未钉（hint 文案面无条款；batch7 validate_citations m36/37 判据族） |
| app.authors.pipeline.x__closest_sentence__mutmut_7 | A | 分句正则 XX 包裹/空正文兜底 XXXX：hint 仅进引用失败提示文案（batch7 validate_citations m36/37 hint 文案先例）；XXXX 兜底 len<12 被过滤恰等价 | 等价/不可达或条款未钉（hint 文案面无条款；batch7 validate_citations m36/37 判据族） |
| app.authors.pipeline.x__closest_sentence__mutmut_9 | A | 分句正则 XX 包裹/空正文兜底 XXXX：hint 仅进引用失败提示文案（batch7 validate_citations m36/37 hint 文案先例）；XXXX 兜底 len<12 被过滤恰等价 | 等价/不可达或条款未钉（hint 文案面无条款；batch7 validate_citations m36/37 判据族） |
| app.authors.pipeline.x_run_pipeline_write__mutmut_138 | A | PipelineAbort 轮 error=str(None)：错误落库存在性与 FAILED 状态不变，内嵌文案变「None」——文案无措辞条款（batch7 m40 同款先例） | 等价/不可达或条款未钉（文案组判据族；batch7 m40 同款先例） |
| app.authors.pipeline.xǁPipelineRunnerǁ_call_json__mutmut_1 | A | last_err 初值 None→""：到达 raise 前恒被 except 赋值为异常对象，初值为死域——控制流等价 | 等价/不可达或条款未钉（文案组 + temperature 数值判据族沿用；batch6/7 先例） |
| app.authors.pipeline.xǁPipelineRunnerǁ_call_json__mutmut_12 | A | temperature 实参删除落缺省 0.5：temperature 数值无条款（batch6 m33 判据族） | 等价/不可达或条款未钉（文案组 + temperature 数值判据族沿用；batch6/7 先例） |
| app.authors.pipeline.xǁPipelineRunnerǁ_call_json__mutmut_15 | A | last_err=None：最终中止消息内嵌诊断串变「None」，FAILED 状态与错误落库存在性不变——文案无措辞条款（batch6 空稿文案/batch7 m40 先例） | 等价/不可达或条款未钉（文案组 + temperature 数值判据族沿用；batch6/7 先例） |
| app.authors.pipeline.xǁPipelineRunnerǁ_call_json__mutmut_30 | A | PipelineAbort(None)：同 m15——中止文案无条款，状态面不变 | 等价/不可达或条款未钉（文案组 + temperature 数值判据族沿用；batch6/7 先例） |
| app.authors.pipeline.xǁPipelineRunnerǁ_call_json__mutmut_8 | A | temperature=None：调用参数值形态无条款（batch6 temperature 数值先例；FakeProvider 域无断言面） | 等价/不可达或条款未钉（文案组 + temperature 数值判据族沿用；batch6/7 先例） |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_390 | A | gate_history 条目键名变体：payload 内部形态未钉（batch6 m340/341 先例） | 等价/不可达或条款未钉（schema 必填 + payload 内部形态 + ORM 列缺省 + 文案组判据族；batch6/7 先例） |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_391 | A | gate_history 条目键名变体：payload 内部形态未钉（batch6 m340/341 先例） | 等价/不可达或条款未钉（schema 必填 + payload 内部形态 + ORM 列缺省 + 文案组判据族；batch6/7 先例） |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_396 | A | payload cost 键变体：cost 聚合账非 §4.1 钉面（batch6 m113-120 先例） | 等价/不可达或条款未钉（schema 必填 + payload 内部形态 + ORM 列缺省 + 文案组判据族；batch6/7 先例） |
| app.authors.pipeline.xǁPipelineRunnerǁnode_incubate__mutmut_14 | A | 腹稿输出格式指令 XX 包裹/字段名大写变体：格式指令措辞——提示词形态（batch7 字段名先例） | 等价/不可达或条款未钉（提示词形态 + 数值判据族；batch6/7 先例） |
| app.authors.pipeline.xǁPipelineRunnerǁnode_incubate__mutmut_15 | A | 腹稿输出格式指令 XX 包裹/字段名大写变体：格式指令措辞——提示词形态（batch7 字段名先例） | 等价/不可达或条款未钉（提示词形态 + 数值判据族；batch6/7 先例） |
| app.authors.pipeline.xǁPipelineRunnerǁnode_incubate__mutmut_16 | A | 腹稿输出格式指令 XX 包裹/字段名大写变体：格式指令措辞——提示词形态（batch7 字段名先例） | 等价/不可达或条款未钉（提示词形态 + 数值判据族；batch6/7 先例） |
| app.authors.pipeline.xǁPipelineRunnerǁnode_incubate__mutmut_17 | A | 腹稿输出格式指令 XX 包裹/字段名大写变体：格式指令措辞——提示词形态（batch7 字段名先例） | 等价/不可达或条款未钉（提示词形态 + 数值判据族；batch6/7 先例） |
| app.authors.pipeline.xǁPipelineRunnerǁnode_incubate__mutmut_18 | A | 腹稿输出格式指令 XX 包裹/字段名大写变体：格式指令措辞——提示词形态（batch7 字段名先例） | 等价/不可达或条款未钉（提示词形态 + 数值判据族；batch6/7 先例） |
| app.authors.pipeline.xǁPipelineRunnerǁnode_incubate__mutmut_21 | A | temperature 0.9→None/1.9：数值无条款（batch6 判据族） | 等价/不可达或条款未钉（提示词形态 + 数值判据族；batch6/7 先例） |
| app.authors.pipeline.xǁPipelineRunnerǁnode_incubate__mutmut_27 | A | temperature 0.9→None/1.9：数值无条款（batch6 判据族） | 等价/不可达或条款未钉（提示词形态 + 数值判据族；batch6/7 先例） |
| app.authors.pipeline.xǁPipelineRunnerǁnode_outline__mutmut_1 | A | template 读取/hint 取值变体：hint 仅进提示词措辞（结构提示语缺省空串）——提示词形态判据（batch6/7） | 等价/不可达或条款未钉（提示词形态 + schema 枚举必填 + 数值边界判据族；batch6/7/9 先例） |
| app.authors.pipeline.xǁPipelineRunnerǁnode_outline__mutmut_10 | A | hints 键名/文本 XX 包裹/大写变体：结构提示语措辞——提示词形态（batch6 node_draft m29 措辞先例） | 等价/不可达或条款未钉（提示词形态 + schema 枚举必填 + 数值边界判据族；batch6/7/9 先例） |
| app.authors.pipeline.xǁPipelineRunnerǁnode_outline__mutmut_11 | A | hints 键名/文本 XX 包裹/大写变体：结构提示语措辞——提示词形态（batch6 node_draft m29 措辞先例） | 等价/不可达或条款未钉（提示词形态 + schema 枚举必填 + 数值边界判据族；batch6/7/9 先例） |
| app.authors.pipeline.xǁPipelineRunnerǁnode_outline__mutmut_12 | A | hints 键名/文本 XX 包裹/大写变体：结构提示语措辞——提示词形态（batch6 node_draft m29 措辞先例） | 等价/不可达或条款未钉（提示词形态 + schema 枚举必填 + 数值边界判据族；batch6/7/9 先例） |
| app.authors.pipeline.xǁPipelineRunnerǁnode_outline__mutmut_13 | A | hints 键名/文本 XX 包裹/大写变体：结构提示语措辞——提示词形态（batch6 node_draft m29 措辞先例） | 等价/不可达或条款未钉（提示词形态 + schema 枚举必填 + 数值边界判据族；batch6/7/9 先例） |
| app.authors.pipeline.xǁPipelineRunnerǁnode_outline__mutmut_14 | A | hints 键名/文本 XX 包裹/大写变体：结构提示语措辞——提示词形态（batch6 node_draft m29 措辞先例） | 等价/不可达或条款未钉（提示词形态 + schema 枚举必填 + 数值边界判据族；batch6/7/9 先例） |
| app.authors.pipeline.xǁPipelineRunnerǁnode_outline__mutmut_15 | A | hints 键名/文本 XX 包裹/大写变体：结构提示语措辞——提示词形态（batch6 node_draft m29 措辞先例） | 等价/不可达或条款未钉（提示词形态 + schema 枚举必填 + 数值边界判据族；batch6/7/9 先例） |
| app.authors.pipeline.xǁPipelineRunnerǁnode_outline__mutmut_16 | A | hints 键名/文本 XX 包裹/大写变体：结构提示语措辞——提示词形态（batch6 node_draft m29 措辞先例） | 等价/不可达或条款未钉（提示词形态 + schema 枚举必填 + 数值边界判据族；batch6/7/9 先例） |
| app.authors.pipeline.xǁPipelineRunnerǁnode_outline__mutmut_17 | A | hints 键名/文本 XX 包裹/大写变体：结构提示语措辞——提示词形态（batch6 node_draft m29 措辞先例） | 等价/不可达或条款未钉（提示词形态 + schema 枚举必填 + 数值边界判据族；batch6/7/9 先例） |
| app.authors.pipeline.xǁPipelineRunnerǁnode_outline__mutmut_18 | A | hints 键名/文本 XX 包裹/大写变体：结构提示语措辞——提示词形态（batch6 node_draft m29 措辞先例） | 等价/不可达或条款未钉（提示词形态 + schema 枚举必填 + 数值边界判据族；batch6/7/9 先例） |
| app.authors.pipeline.xǁPipelineRunnerǁnode_outline__mutmut_19 | A | hints 键名/文本 XX 包裹/大写变体：结构提示语措辞——提示词形态（batch6 node_draft m29 措辞先例） | 等价/不可达或条款未钉（提示词形态 + schema 枚举必填 + 数值边界判据族；batch6/7/9 先例） |
| app.authors.pipeline.xǁPipelineRunnerǁnode_outline__mutmut_20 | A | hints 键名/文本 XX 包裹/大写变体：结构提示语措辞——提示词形态（batch6 node_draft m29 措辞先例） | 等价/不可达或条款未钉（提示词形态 + schema 枚举必填 + 数值边界判据族；batch6/7/9 先例） |
| app.authors.pipeline.xǁPipelineRunnerǁnode_outline__mutmut_21 | A | hints 键名/文本 XX 包裹/大写变体：结构提示语措辞——提示词形态（batch6 node_draft m29 措辞先例） | 等价/不可达或条款未钉（提示词形态 + schema 枚举必填 + 数值边界判据族；batch6/7/9 先例） |
| app.authors.pipeline.xǁPipelineRunnerǁnode_outline__mutmut_22 | A | template 读取/hint 取值变体：hint 仅进提示词措辞（结构提示语缺省空串）——提示词形态判据（batch6/7） | 等价/不可达或条款未钉（提示词形态 + schema 枚举必填 + 数值边界判据族；batch6/7/9 先例） |
| app.authors.pipeline.xǁPipelineRunnerǁnode_outline__mutmut_23 | A | template 读取/hint 取值变体：hint 仅进提示词措辞（结构提示语缺省空串）——提示词形态判据（batch6/7） | 等价/不可达或条款未钉（提示词形态 + schema 枚举必填 + 数值边界判据族；batch6/7/9 先例） |
| app.authors.pipeline.xǁPipelineRunnerǁnode_outline__mutmut_24 | A | hints.get 缺省形态：outline.template 为 schema 枚举且 none 模板不进本函数（execute 守卫），四键恒命中缺省不可达——schema 枚举 + 调用点守卫（batch9 gate_length m8 判据族） | 等价/不可达或条款未钉（提示词形态 + schema 枚举必填 + 数值边界判据族；batch6/7/9 先例） |
| app.authors.pipeline.xǁPipelineRunnerǁnode_outline__mutmut_25 | A | hints.get 缺省形态：outline.template 为 schema 枚举且 none 模板不进本函数（execute 守卫），四键恒命中缺省不可达——schema 枚举 + 调用点守卫（batch9 gate_length m8 判据族） | 等价/不可达或条款未钉（提示词形态 + schema 枚举必填 + 数值边界判据族；batch6/7/9 先例） |
| app.authors.pipeline.xǁPipelineRunnerǁnode_outline__mutmut_26 | A | hints.get 缺省形态：outline.template 为 schema 枚举且 none 模板不进本函数（execute 守卫），四键恒命中缺省不可达——schema 枚举 + 调用点守卫（batch9 gate_length m8 判据族） | 等价/不可达或条款未钉（提示词形态 + schema 枚举必填 + 数值边界判据族；batch6/7/9 先例） |
| app.authors.pipeline.xǁPipelineRunnerǁnode_outline__mutmut_27 | A | hints.get 缺省形态：outline.template 为 schema 枚举且 none 模板不进本函数（execute 守卫），四键恒命中缺省不可达——schema 枚举 + 调用点守卫（batch9 gate_length m8 判据族） | 等价/不可达或条款未钉（提示词形态 + schema 枚举必填 + 数值边界判据族；batch6/7/9 先例） |
| app.authors.pipeline.xǁPipelineRunnerǁnode_outline__mutmut_41 | A | 输出 JSON 指令段 XX 包裹/大小写/字段名变体：格式指令措辞（下游按 get 消费、模型遵从概率面）——提示词形态（batch7 draft_task 字段名先例） | 等价/不可达或条款未钉（提示词形态 + schema 枚举必填 + 数值边界判据族；batch6/7/9 先例） |
| app.authors.pipeline.xǁPipelineRunnerǁnode_outline__mutmut_42 | A | 输出 JSON 指令段 XX 包裹/大小写/字段名变体：格式指令措辞（下游按 get 消费、模型遵从概率面）——提示词形态（batch7 draft_task 字段名先例） | 等价/不可达或条款未钉（提示词形态 + schema 枚举必填 + 数值边界判据族；batch6/7/9 先例） |
| app.authors.pipeline.xǁPipelineRunnerǁnode_outline__mutmut_43 | A | 输出 JSON 指令段 XX 包裹/大小写/字段名变体：格式指令措辞（下游按 get 消费、模型遵从概率面）——提示词形态（batch7 draft_task 字段名先例） | 等价/不可达或条款未钉（提示词形态 + schema 枚举必填 + 数值边界判据族；batch6/7/9 先例） |
| app.authors.pipeline.xǁPipelineRunnerǁnode_outline__mutmut_44 | A | 输出 JSON 指令段 XX 包裹/大小写/字段名变体：格式指令措辞（下游按 get 消费、模型遵从概率面）——提示词形态（batch7 draft_task 字段名先例） | 等价/不可达或条款未钉（提示词形态 + schema 枚举必填 + 数值边界判据族；batch6/7/9 先例） |
| app.authors.pipeline.xǁPipelineRunnerǁnode_outline__mutmut_45 | A | 输出 JSON 指令段 XX 包裹/大小写/字段名变体：格式指令措辞（下游按 get 消费、模型遵从概率面）——提示词形态（batch7 draft_task 字段名先例） | 等价/不可达或条款未钉（提示词形态 + schema 枚举必填 + 数值边界判据族；batch6/7/9 先例） |
| app.authors.pipeline.xǁPipelineRunnerǁnode_outline__mutmut_49 | A | temperature 0.7→None/1.7：数值无条款（batch6 判据族） | 等价/不可达或条款未钉（提示词形态 + schema 枚举必填 + 数值边界判据族；batch6/7/9 先例） |
| app.authors.pipeline.xǁPipelineRunnerǁnode_outline__mutmut_55 | A | temperature 0.7→None/1.7：数值无条款（batch6 判据族） | 等价/不可达或条款未钉（提示词形态 + schema 枚举必填 + 数值边界判据族；batch6/7/9 先例） |
| app.authors.pipeline.xǁPipelineRunnerǁnode_outline__mutmut_61 | A | sections 数边界 <2→≤2/<3：大纲最低节数与含等性未入设计书（数值边界判据族；rolling 消费 :3 与 prompt 恰好 3 个均为措辞面）——batch9 m16/m23 先例 | 等价/不可达或条款未钉（提示词形态 + schema 枚举必填 + 数值边界判据族；batch6/7/9 先例） |
| app.authors.pipeline.xǁPipelineRunnerǁnode_outline__mutmut_62 | A | sections 数边界 <2→≤2/<3：大纲最低节数与含等性未入设计书（数值边界判据族；rolling 消费 :3 与 prompt 恰好 3 个均为措辞面）——batch9 m16/m23 先例 | 等价/不可达或条款未钉（提示词形态 + schema 枚举必填 + 数值边界判据族；batch6/7/9 先例） |
| app.authors.pipeline.xǁPipelineRunnerǁnode_outline__mutmut_63 | A | PipelineAbort(None)：中止文案无条款，FAILED 状态面不变（missing_sections 测试只断言状态） | 等价/不可达或条款未钉（提示词形态 + schema 枚举必填 + 数值边界判据族；batch6/7/9 先例） |
| app.authors.pipeline.xǁPipelineRunnerǁnode_outline__mutmut_64 | A | 中止消息 o.get 键变体：中止文案形态无条款（同 m63 判据） | 等价/不可达或条款未钉（提示词形态 + schema 枚举必填 + 数值边界判据族；batch6/7/9 先例） |
| app.authors.pipeline.xǁPipelineRunnerǁnode_outline__mutmut_65 | A | 中止消息 o.get 键变体：中止文案形态无条款（同 m63 判据） | 等价/不可达或条款未钉（提示词形态 + schema 枚举必填 + 数值边界判据族；batch6/7/9 先例） |
| app.authors.pipeline.xǁPipelineRunnerǁnode_outline__mutmut_66 | A | 中止消息 o.get 键变体：中止文案形态无条款（同 m63 判据） | 等价/不可达或条款未钉（提示词形态 + schema 枚举必填 + 数值边界判据族；batch6/7/9 先例） |
| app.authors.pipeline.xǁPipelineRunnerǁnode_outline__mutmut_9 | A | hints 键名/文本 XX 包裹/大写变体：结构提示语措辞——提示词形态（batch6 node_draft m29 措辞先例） | 等价/不可达或条款未钉（提示词形态 + schema 枚举必填 + 数值边界判据族；batch6/7/9 先例） |
| app.authors.pipeline.xǁPipelineRunnerǁnode_pass__mutmut_10 | A | or→and：lo 退缺省 600 仅改指令字数措辞（门禁侧真值由 run_gates 承担）——提示词形态（batch7 m10 判据） | 等价/不可达或条款未钉（提示词形态 + schema 必填 + trace 字段形态未钉；batch6/7 先例） |
| app.authors.pipeline.xǁPipelineRunnerǁnode_pass__mutmut_100 | A | 占位遍 trace 记录键名变体：trace 条目存在且为 dict（pass_stats 可挂），内部键形态未钉——§4.1 trace 钉面之外的字段形态（batch6 discarded/note 键先例） | 等价/不可达或条款未钉（提示词形态 + schema 必填 + trace 字段形态未钉；batch6/7 先例） |
| app.authors.pipeline.xǁPipelineRunnerǁnode_pass__mutmut_11 | A | prune 默认指令 lo 读取键/缺省变体：lo 仅进删节指令措辞且 gates.length min 为 schema 必填（缺省分支不可达）——提示词形态 + schema 必填判据（batch7 draft_task m10 先例） | 等价/不可达或条款未钉（提示词形态 + schema 必填 + trace 字段形态未钉；batch6/7 先例） |
| app.authors.pipeline.xǁPipelineRunnerǁnode_pass__mutmut_16 | A | prune 默认指令 lo 读取键/缺省变体：lo 仅进删节指令措辞且 gates.length min 为 schema 必填（缺省分支不可达）——提示词形态 + schema 必填判据（batch7 draft_task m10 先例） | 等价/不可达或条款未钉（提示词形态 + schema 必填 + trace 字段形态未钉；batch6/7 先例） |
| app.authors.pipeline.xǁPipelineRunnerǁnode_pass__mutmut_17 | A | prune 默认指令 lo 读取键/缺省变体：lo 仅进删节指令措辞且 gates.length min 为 schema 必填（缺省分支不可达）——提示词形态 + schema 必填判据（batch7 draft_task m10 先例） | 等价/不可达或条款未钉（提示词形态 + schema 必填 + trace 字段形态未钉；batch6/7 先例） |
| app.authors.pipeline.xǁPipelineRunnerǁnode_pass__mutmut_18 | A | prune 默认指令 lo 读取键/缺省变体：lo 仅进删节指令措辞且 gates.length min 为 schema 必填（缺省分支不可达）——提示词形态 + schema 必填判据（batch7 draft_task m10 先例） | 等价/不可达或条款未钉（提示词形态 + schema 必填 + trace 字段形态未钉；batch6/7 先例） |
| app.authors.pipeline.xǁPipelineRunnerǁnode_pass__mutmut_19 | A | prune 默认指令 lo 读取键/缺省变体：lo 仅进删节指令措辞且 gates.length min 为 schema 必填（缺省分支不可达）——提示词形态 + schema 必填判据（batch7 draft_task m10 先例） | 等价/不可达或条款未钉（提示词形态 + schema 必填 + trace 字段形态未钉；batch6/7 先例） |
| app.authors.pipeline.xǁPipelineRunnerǁnode_pass__mutmut_20 | A | prune 默认指令 lo 读取键/缺省变体：lo 仅进删节指令措辞且 gates.length min 为 schema 必填（缺省分支不可达）——提示词形态 + schema 必填判据（batch7 draft_task m10 先例） | 等价/不可达或条款未钉（提示词形态 + schema 必填 + trace 字段形态未钉；batch6/7 先例） |
| app.authors.pipeline.xǁPipelineRunnerǁnode_pass__mutmut_21 | A | prune 默认指令 hi 读取键/缺省变体：同 lo 判据（hi 仅进指令措辞、max schema 必填） | 等价/不可达或条款未钉（提示词形态 + schema 必填 + trace 字段形态未钉；batch6/7 先例） |
| app.authors.pipeline.xǁPipelineRunnerǁnode_pass__mutmut_22 | A | prune 默认指令 hi 读取键/缺省变体：同 lo 判据（hi 仅进指令措辞、max schema 必填） | 等价/不可达或条款未钉（提示词形态 + schema 必填 + trace 字段形态未钉；batch6/7 先例） |
| app.authors.pipeline.xǁPipelineRunnerǁnode_pass__mutmut_23 | A | prune 默认指令 hi 读取键/缺省变体：同 lo 判据（hi 仅进指令措辞、max schema 必填） | 等价/不可达或条款未钉（提示词形态 + schema 必填 + trace 字段形态未钉；batch6/7 先例） |
| app.authors.pipeline.xǁPipelineRunnerǁnode_pass__mutmut_24 | A | prune 默认指令 hi 读取键/缺省变体：同 lo 判据（hi 仅进指令措辞、max schema 必填） | 等价/不可达或条款未钉（提示词形态 + schema 必填 + trace 字段形态未钉；batch6/7 先例） |
| app.authors.pipeline.xǁPipelineRunnerǁnode_pass__mutmut_25 | A | or→and（hi 侧）：同 m10 判据 | 等价/不可达或条款未钉（提示词形态 + schema 必填 + trace 字段形态未钉；batch6/7 先例） |
| app.authors.pipeline.xǁPipelineRunnerǁnode_pass__mutmut_26 | A | prune 默认指令 hi 读取键/缺省变体：同 lo 判据（hi 仅进指令措辞、max schema 必填） | 等价/不可达或条款未钉（提示词形态 + schema 必填 + trace 字段形态未钉；batch6/7 先例） |
| app.authors.pipeline.xǁPipelineRunnerǁnode_pass__mutmut_31 | A | prune 默认指令 hi 读取键/缺省变体：同 lo 判据（hi 仅进指令措辞、max schema 必填） | 等价/不可达或条款未钉（提示词形态 + schema 必填 + trace 字段形态未钉；batch6/7 先例） |
| app.authors.pipeline.xǁPipelineRunnerǁnode_pass__mutmut_32 | A | prune 默认指令 hi 读取键/缺省变体：同 lo 判据（hi 仅进指令措辞、max schema 必填） | 等价/不可达或条款未钉（提示词形态 + schema 必填 + trace 字段形态未钉；batch6/7 先例） |
| app.authors.pipeline.xǁPipelineRunnerǁnode_pass__mutmut_33 | A | prune 默认指令 hi 读取键/缺省变体：同 lo 判据（hi 仅进指令措辞、max schema 必填） | 等价/不可达或条款未钉（提示词形态 + schema 必填 + trace 字段形态未钉；batch6/7 先例） |
| app.authors.pipeline.xǁPipelineRunnerǁnode_pass__mutmut_34 | A | prune 默认指令 hi 读取键/缺省变体：同 lo 判据（hi 仅进指令措辞、max schema 必填） | 等价/不可达或条款未钉（提示词形态 + schema 必填 + trace 字段形态未钉；batch6/7 先例） |
| app.authors.pipeline.xǁPipelineRunnerǁnode_pass__mutmut_35 | A | prune 默认指令 hi 读取键/缺省变体：同 lo 判据（hi 仅进指令措辞、max schema 必填） | 等价/不可达或条款未钉（提示词形态 + schema 必填 + trace 字段形态未钉；batch6/7 先例） |
| app.authors.pipeline.xǁPipelineRunnerǁnode_pass__mutmut_36 | A | 自定义 instruction 读取变体：params 指令覆盖进提示词措辞——提示词形态（batch6 execute m268-271 先例） | 等价/不可达或条款未钉（提示词形态 + schema 必填 + trace 字段形态未钉；batch6/7 先例） |
| app.authors.pipeline.xǁPipelineRunnerǁnode_pass__mutmut_37 | A | 自定义 instruction 读取变体：params 指令覆盖进提示词措辞——提示词形态（batch6 execute m268-271 先例） | 等价/不可达或条款未钉（提示词形态 + schema 必填 + trace 字段形态未钉；batch6/7 先例） |
| app.authors.pipeline.xǁPipelineRunnerǁnode_pass__mutmut_38 | A | 自定义 instruction 读取变体：params 指令覆盖进提示词措辞——提示词形态（batch6 execute m268-271 先例） | 等价/不可达或条款未钉（提示词形态 + schema 必填 + trace 字段形态未钉；batch6/7 先例） |
| app.authors.pipeline.xǁPipelineRunnerǁnode_pass__mutmut_39 | A | 自定义 instruction 读取变体：params 指令覆盖进提示词措辞——提示词形态（batch6 execute m268-271 先例） | 等价/不可达或条款未钉（提示词形态 + schema 必填 + trace 字段形态未钉；batch6/7 先例） |
| app.authors.pipeline.xǁPipelineRunnerǁnode_pass__mutmut_40 | A | 自定义 instruction 读取变体：params 指令覆盖进提示词措辞——提示词形态（batch6 execute m268-271 先例） | 等价/不可达或条款未钉（提示词形态 + schema 必填 + trace 字段形态未钉；batch6/7 先例） |
| app.authors.pipeline.xǁPipelineRunnerǁnode_pass__mutmut_45 | A | 默认删节指令文本/占位符替换变体：删节指令措辞与当前字数回显形态——提示词形态（batch6 先例） | 等价/不可达或条款未钉（提示词形态 + schema 必填 + trace 字段形态未钉；batch6/7 先例） |
| app.authors.pipeline.xǁPipelineRunnerǁnode_pass__mutmut_46 | A | 默认删节指令文本/占位符替换变体：删节指令措辞与当前字数回显形态——提示词形态（batch6 先例） | 等价/不可达或条款未钉（提示词形态 + schema 必填 + trace 字段形态未钉；batch6/7 先例） |
| app.authors.pipeline.xǁPipelineRunnerǁnode_pass__mutmut_47 | A | 默认删节指令文本/占位符替换变体：删节指令措辞与当前字数回显形态——提示词形态（batch6 先例） | 等价/不可达或条款未钉（提示词形态 + schema 必填 + trace 字段形态未钉；batch6/7 先例） |
| app.authors.pipeline.xǁPipelineRunnerǁnode_pass__mutmut_48 | A | 默认删节指令文本/占位符替换变体：删节指令措辞与当前字数回显形态——提示词形态（batch6 先例） | 等价/不可达或条款未钉（提示词形态 + schema 必填 + trace 字段形态未钉；batch6/7 先例） |
| app.authors.pipeline.xǁPipelineRunnerǁnode_pass__mutmut_6 | A | prune 默认指令 lo 读取键/缺省变体：lo 仅进删节指令措辞且 gates.length min 为 schema 必填（缺省分支不可达）——提示词形态 + schema 必填判据（batch7 draft_task m10 先例） | 等价/不可达或条款未钉（提示词形态 + schema 必填 + trace 字段形态未钉；batch6/7 先例） |
| app.authors.pipeline.xǁPipelineRunnerǁnode_pass__mutmut_65 | A | prune/rhythm temperature 0.6/0.8 变体：数值无条款（batch6 node_draft m33 判据族） | 等价/不可达或条款未钉（提示词形态 + schema 必填 + trace 字段形态未钉；batch6/7 先例） |
| app.authors.pipeline.xǁPipelineRunnerǁnode_pass__mutmut_68 | A | prune/rhythm temperature 0.6/0.8 变体：数值无条款（batch6 node_draft m33 判据族） | 等价/不可达或条款未钉（提示词形态 + schema 必填 + trace 字段形态未钉；batch6/7 先例） |
| app.authors.pipeline.xǁPipelineRunnerǁnode_pass__mutmut_69 | A | prune/rhythm temperature 0.6/0.8 变体：数值无条款（batch6 node_draft m33 判据族） | 等价/不可达或条款未钉（提示词形态 + schema 必填 + trace 字段形态未钉；batch6/7 先例） |
| app.authors.pipeline.xǁPipelineRunnerǁnode_pass__mutmut_7 | A | prune 默认指令 lo 读取键/缺省变体：lo 仅进删节指令措辞且 gates.length min 为 schema 必填（缺省分支不可达）——提示词形态 + schema 必填判据（batch7 draft_task m10 先例） | 等价/不可达或条款未钉（提示词形态 + schema 必填 + trace 字段形态未钉；batch6/7 先例） |
| app.authors.pipeline.xǁPipelineRunnerǁnode_pass__mutmut_8 | A | prune 默认指令 lo 读取键/缺省变体：lo 仅进删节指令措辞且 gates.length min 为 schema 必填（缺省分支不可达）——提示词形态 + schema 必填判据（batch7 draft_task m10 先例） | 等价/不可达或条款未钉（提示词形态 + schema 必填 + trace 字段形态未钉；batch6/7 先例） |
| app.authors.pipeline.xǁPipelineRunnerǁnode_pass__mutmut_86 | A | 节奏重构指令文本 XX 包裹：指令措辞——提示词形态 | 等价/不可达或条款未钉（提示词形态 + schema 必填 + trace 字段形态未钉；batch6/7 先例） |
| app.authors.pipeline.xǁPipelineRunnerǁnode_pass__mutmut_87 | A | 节奏重构指令文本 XX 包裹：指令措辞——提示词形态 | 等价/不可达或条款未钉（提示词形态 + schema 必填 + trace 字段形态未钉；batch6/7 先例） |
| app.authors.pipeline.xǁPipelineRunnerǁnode_pass__mutmut_9 | A | prune 默认指令 lo 读取键/缺省变体：lo 仅进删节指令措辞且 gates.length min 为 schema 必填（缺省分支不可达）——提示词形态 + schema 必填判据（batch7 draft_task m10 先例） | 等价/不可达或条款未钉（提示词形态 + schema 必填 + trace 字段形态未钉；batch6/7 先例） |
| app.authors.pipeline.xǁPipelineRunnerǁnode_pass__mutmut_91 | A | prune/rhythm temperature 0.6/0.8 变体：数值无条款（batch6 node_draft m33 判据族） | 等价/不可达或条款未钉（提示词形态 + schema 必填 + trace 字段形态未钉；batch6/7 先例） |
| app.authors.pipeline.xǁPipelineRunnerǁnode_pass__mutmut_94 | A | prune/rhythm temperature 0.6/0.8 变体：数值无条款（batch6 node_draft m33 判据族） | 等价/不可达或条款未钉（提示词形态 + schema 必填 + trace 字段形态未钉；batch6/7 先例） |
| app.authors.pipeline.xǁPipelineRunnerǁnode_pass__mutmut_95 | A | prune/rhythm temperature 0.6/0.8 变体：数值无条款（batch6 node_draft m33 判据族） | 等价/不可达或条款未钉（提示词形态 + schema 必填 + trace 字段形态未钉；batch6/7 先例） |
| app.authors.pipeline.xǁPipelineRunnerǁnode_pass__mutmut_97 | A | 占位遍 trace 记录键名变体：trace 条目存在且为 dict（pass_stats 可挂），内部键形态未钉——§4.1 trace 钉面之外的字段形态（batch6 discarded/note 键先例） | 等价/不可达或条款未钉（提示词形态 + schema 必填 + trace 字段形态未钉；batch6/7 先例） |
| app.authors.pipeline.xǁPipelineRunnerǁnode_pass__mutmut_98 | A | 占位遍 trace 记录键名变体：trace 条目存在且为 dict（pass_stats 可挂），内部键形态未钉——§4.1 trace 钉面之外的字段形态（batch6 discarded/note 键先例） | 等价/不可达或条款未钉（提示词形态 + schema 必填 + trace 字段形态未钉；batch6/7 先例） |
| app.authors.pipeline.xǁPipelineRunnerǁnode_pass__mutmut_99 | A | 占位遍 trace 记录键名变体：trace 条目存在且为 dict（pass_stats 可挂），内部键形态未钉——§4.1 trace 钉面之外的字段形态（batch6 discarded/note 键先例） | 等价/不可达或条款未钉（提示词形态 + schema 必填 + trace 字段形态未钉；batch6/7 先例） |

## C2-3 分诊批次 3（2026-10-05，ingest 域收尾：rss 94 + fingerprint 5 + rules 2 + web 4）：A 61 条

> 种子=统一 dispatch run 37276946376（main @ 8c5f515）未登记幸存者之 ingest 域
> （doc/C2/C2-3-种子.jsonl）。diff 经 mutmut 3.8.0 库级静态重建（app/ 自 8c5f515 零变化，
> 变异体名与当前树 1:1 对名），逐条施加→跑本批判据面测试→还原定案。终态：**C 44/44 全杀**
> （tests/test_ingest_xml_sniff.py 等 7 文件 29 测试，不在本清单）、**A 61/61 全活**、
> **B 0 / D 0**。核验-改判 2 轮共 3 条改判（C→A 1：首导窗口缺省 or 7 经 siteconfig.DEFAULTS
> 兜底为死域〔施加实测纠偏〕；A→C 2：首导 apply_rules blacklist 传值破坏×2〔既有契约测试
> 家族已把 fetch_source 直传 blacklist 钉为合法面，首轮误判 or [] 兜底等价〕）。数据：
> doc/C2/C2-3-重建-diff.json、doc/C2/C2-3-核验结果.json、doc/C2/C2-3-核验.py（定案表）。
> 判据实测入册（定案前置，venv 离线）：①SQLAlchemy 显式 None 赋值触发列 default 兜底；
> ②httpx.Headers 赋 None 值在请求构造时抛 AttributeError；③bytes.decode 错误处理器惰性
> 查找 + 字节正则 [A-Za-z]+ 不匹配非 ASCII（decode errors 参数死域）；④siteconfig.get_config
> 代码内 DEFAULTS 兜底使调用点尾字面量缺省成死域；⑤feedparser 对 isPermaLink=false 的
> URL 型 guid 不回填 link。

| mutant 全名 | 类别 | 一句话理由 | 依据条款或推理 |
|---|---|---|---|
| app.ingest.fingerprint.x__normalize_title__mutmut_13 | A | join 分隔符 " "→"XX XX"：归一化函数值变但相等语义保持——split 无空白 token 上两种 join 均单射，判定域（指纹相等性）逐对全等价；ttl 指纹字面值无断言面（B4 钉的是 unescape→NFKC+空白折叠的相等保持语义，既有 unescape/NFKC 测试域不涉分隔符字面） | 等价/不可达或条款未钉（归一化相等语义保持 + ttl 指纹字面值无断言面；batch5 编解码/无条款判据族） |
| app.ingest.fingerprint.x_entry_fingerprint__mutmut_14 | A | 三级皆不可得返回 (None,False)→(None,True)：唯一调用点 fetch_source 以 _low_confidence 丢弃第二返回值（调用点核查），低置信标志无任何消费方——死返回值判据 | 等价/不可达或条款未钉（死返回值/调用点核查判据族） |
| app.ingest.fingerprint.x_title_fingerprint__mutmut_8 | A | encode("utf-8")→("UTF-8")：Python 编解码别名，字节序列相同（batch5 url_fingerprint m6 先例） | 等价/不可达或条款未钉（编解码别名判据；batch5 m6 先例） |
| app.ingest.rss.x__looks_like_xml__mutmut_16 | A | content_type 假值兜底 or ""→or "XXXX"：两形态 "xml" in 均为 False，判定域真值表全等价 | 等价/不可达或条款未钉（bytes 转义语义 + 窗口界面域数值边界判据族 + 假值兜底真值等价；C2-2 m24/25 先例） |
| app.ingest.rss.x__looks_like_xml__mutmut_2 | A | 嗅探窗口 [:512]→[:513]：差异域=起始标记恰在 512 字节界（测量零界面域），窗口数值未入设计书（数值边界判据族；C2-2 gate_echo m24/25 先例） | 等价/不可达或条款未钉（bytes 转义语义 + 窗口界面域数值边界判据族 + 假值兜底真值等价；C2-2 m24/25 先例） |
| app.ingest.rss.x__looks_like_xml__mutmut_5 | A | BOM 字节转义 \xef→\xEF：Python bytes 转义大小写不敏感，字节串逐位一致——恰等价 | 等价/不可达或条款未钉（bytes 转义语义 + 窗口界面域数值边界判据族 + 假值兜底真值等价；C2-2 m24/25 先例） |
| app.ingest.rss.x_channel_skip_days__mutmut_13 | A | decode codec "ascii"→"ASCII"：编解码别名恰等价（batch5 编解码别名判据） | 等价/不可达或条款未钉（窗口界面域数值边界 + 字节正则 ASCII 域致 decode errors 死域〔实测〕+ 编解码别名判据） |
| app.ingest.rss.x_channel_skip_days__mutmut_14 | A | decode errors 处理器名破坏：输入域恒纯 ASCII（同 m9），处理器仅报错时惰性查找（实测）——死域 | 等价/不可达或条款未钉（窗口界面域数值边界 + 字节正则 ASCII 域致 decode errors 死域〔实测〕+ 编解码别名判据） |
| app.ingest.rss.x_channel_skip_days__mutmut_15 | A | decode errors 处理器名破坏：输入域恒纯 ASCII（同 m9），处理器仅报错时惰性查找（实测）——死域 | 等价/不可达或条款未钉（窗口界面域数值边界 + 字节正则 ASCII 域致 decode errors 死域〔实测〕+ 编解码别名判据） |
| app.ingest.rss.x_channel_skip_days__mutmut_3 | A | 扫描窗口 [:65536]→[:65537]：差异域=skipDays 块恰在 64KB 界（测量零界面域），窗口数值未入设计书（数值边界判据族） | 等价/不可达或条款未钉（窗口界面域数值边界 + 字节正则 ASCII 域致 decode errors 死域〔实测〕+ 编解码别名判据） |
| app.ingest.rss.x_channel_skip_days__mutmut_9 | A | decode errors "ignore"→strict：捕获组 [A-Za-z]+ 恒纯 ASCII（字节正则实测不匹配非 ASCII），decode 永不报错——errors 处理器死域（防御缺省不可达判据） | 等价/不可达或条款未钉（窗口界面域数值边界 + 字节正则 ASCII 域致 decode errors 死域〔实测〕+ 编解码别名判据） |
| app.ingest.rss.x_fetch_source__mutmut_121 | A | extra["skip_days"] 列表置 None：唯一消费方 runner 只读 skip_day 布尔（runner.py:247），列表为payload 内部形态未钉（batch6 §4.1 钉面之外判据族） | 等价/不可达或条款未钉（ORM 列缺省兜底〔实测〕+ httpx 头名归一化 + 条件头/UA/last-modified 回写未钉 + tz 存储未钉 + payload 内部形态未钉 + 文案组 + 数值边界判据族；batch4/5 + C2-1 先例） |
| app.ingest.rss.x_fetch_source__mutmut_23 | A | 首导窗口缺省 or 7→or 8：siteconfig.get_config 对 first_ingest_days 键恒返 DEFAULTS["first_ingest_days"]=7（代码内缺省兜底，实测该键永不 None）——尾字面量 or 7 为死域，改判恰等价（DEFAULTS 兜底判据族，SQLAlchemy 列 default 兜底同族；首轮误判 C 经施加实测 7.5 天条目仍 ARCHIVED 纠偏） | 等价/不可达或条款未钉（ORM 列缺省兜底〔实测〕+ httpx 头名归一化 + 条件头/UA/last-modified 回写未钉 + tz 存储未钉 + payload 内部形态未钉 + 文案组 + 数值边界判据族；batch4/5 + C2-1 先例） |
| app.ingest.rss.x_fetch_source__mutmut_319 | A | log.warning e 实参 None：同 m318（占位完整，渲染值变 None） | 等价/不可达或条款未钉（ORM 列缺省兜底〔实测〕+ httpx 头名归一化 + 条件头/UA/last-modified 回写未钉 + tz 存储未钉 + payload 内部形态未钉 + 文案组 + 数值边界判据族；batch4/5 + C2-1 先例） |
| app.ingest.rss.x_fetch_source__mutmut_33 | A | If-Modified-Since 头名 XX 变体：条件头回传未钉（模块表仅钉 etag 原样回传），断裂由 etag 兜底（batch4 m35 先例） | 等价/不可达或条款未钉（ORM 列缺省兜底〔实测〕+ httpx 头名归一化 + 条件头/UA/last-modified 回写未钉 + tz 存储未钉 + payload 内部形态未钉 + 文案组 + 数值边界判据族；batch4/5 + C2-1 先例） |
| app.ingest.rss.x_fetch_source__mutmut_333 | A | etag 截断 [:500]→[:501]：SQLite 不强制 VARCHAR 长度，原样性不受 1 字符影响（batch4 m72 判据；硬约束⑤ 钉原样存取语义非截断界数值） | 等价/不可达或条款未钉（ORM 列缺省兜底〔实测〕+ httpx 头名归一化 + 条件头/UA/last-modified 回写未钉 + tz 存储未钉 + payload 内部形态未钉 + 文案组 + 数值边界判据族；batch4/5 + C2-1 先例） |
| app.ingest.rss.x_fetch_source__mutmut_336 | A | last-modified get 头名大写：httpx 大小写不敏感恰等价（batch4 m79 先例） | 等价/不可达或条款未钉（ORM 列缺省兜底〔实测〕+ httpx 头名归一化 + 条件头/UA/last-modified 回写未钉 + tz 存储未钉 + payload 内部形态未钉 + 文案组 + 数值边界判据族；batch4/5 + C2-1 先例） |
| app.ingest.rss.x_fetch_source__mutmut_337 | A | last_modified 存储置 None：存储未钉（batch4 m80 先例） | 等价/不可达或条款未钉（ORM 列缺省兜底〔实测〕+ httpx 头名归一化 + 条件头/UA/last-modified 回写未钉 + tz 存储未钉 + payload 内部形态未钉 + 文案组 + 数值边界判据族；batch4/5 + C2-1 先例） |
| app.ingest.rss.x_fetch_source__mutmut_338 | A | last-modified 存取头名 XX 变体：同 m335（batch4 m78 先例） | 等价/不可达或条款未钉（ORM 列缺省兜底〔实测〕+ httpx 头名归一化 + 条件头/UA/last-modified 回写未钉 + tz 存储未钉 + payload 内部形态未钉 + 文案组 + 数值边界判据族；batch4/5 + C2-1 先例） |
| app.ingest.rss.x_fetch_source__mutmut_339 | A | last-modified 存取头名大写：httpx 大小写不敏感恰等价（batch4 m82 先例） | 等价/不可达或条款未钉（ORM 列缺省兜底〔实测〕+ httpx 头名归一化 + 条件头/UA/last-modified 回写未钉 + tz 存储未钉 + payload 内部形态未钉 + 文案组 + 数值边界判据族；batch4/5 + C2-1 先例） |
| app.ingest.rss.x_fetch_source__mutmut_340 | A | last_modified 截断 [:500]→[:501]：同 m333 判据（batch4 m83 先例） | 等价/不可达或条款未钉（ORM 列缺省兜底〔实测〕+ httpx 头名归一化 + 条件头/UA/last-modified 回写未钉 + tz 存储未钉 + payload 内部形态未钉 + 文案组 + 数值边界判据族；batch4/5 + C2-1 先例） |
| app.ingest.rss.x_fetch_source__mutmut_94 | A | content-type 头名大写：httpx 大小写不敏感恰等价（batch4 m63 判据族） | 等价/不可达或条款未钉（ORM 列缺省兜底〔实测〕+ httpx 头名归一化 + 条件头/UA/last-modified 回写未钉 + tz 存储未钉 + payload 内部形态未钉 + 文案组 + 数值边界判据族；batch4/5 + C2-1 先例） |
| app.ingest.rss.x_parse_retry_after__mutmut_15 | A | 负值钳 max(0.0)→max(1.0)：差异域=过去时刻 HTTP-date，钳值差 1 秒只进 rate_limited_until 时间戳（时间戳值无条款，C2-1 update_source_health m76 先例），轮次间隔分钟级使 1 秒差不可达判定域 | 等价/不可达或条款未钉（钳值 1 秒差只进时间戳值——时间戳无条款，C2-1 m76 判据族） |
| app.ingest.rules.x_apply_rules__mutmut_24 | A | RuleResult passed=False→None：全部调用点按真值判断（not rule.passed / if rule.passed），行为等价（batch5 sanitize m3 调用点真值判据） | 等价/不可达或条款未钉（调用点真值判断 + 判定域恒 UTC-aware/naive 判据；batch5 m3 + C2-1 m144 先例） |
| app.ingest.rules.x_apply_rules__mutmut_33 | A | tzinfo 守卫恒 replace(tzinfo=utc)：生产判定域 published_at 恒 UTC-aware（rss/web 三通道构造即utc）或 naive（naive 域两形态同为补 tz）——C2-1 update_source_health m144 判据 | 等价/不可达或条款未钉（调用点真值判断 + 判定域恒 UTC-aware/naive 判据；batch5 m3 + C2-1 m144 先例） |
| app.ingest.web.x_fetch_web_source__mutmut_243 | A | apply_fp=False→None：None 与 False 同 falsy，版本条目豁免指纹链语义不变（C2-1 m18 None/False 同falsy 判据） | 等价/不可达或条款未钉（None/False 同 falsy + ignore_page_date 键全档无条款〔batch4 m17-21 先例〕+ tz 存储未钉） |

## C2-4 分诊批次 4A（2026-10-06，收官批段A：embedding.moark 87 + db 76 + models 3 = 166 条）：A 92 条

> 种子=统一 dispatch run 37276946376 未登记幸存者之余量段（doc/C2/C2-4-种子.jsonl；
> C2 收官分诊批两段仪式之一）。diff 经 mutmut 3.8.0 库级静态重建（app/ 自 8c5f515
> 零变化 1:1 对名，orig 体一致性校验 166/166）。终态：**C 74/74 全杀**（
> tests/test_embedding_moark_request.py 7 测试 + tests/test_db_migration.py +3 测试
> 〔g2_older_item_db 四表旧库夹具〕+ tests/test_models_smoke.py +1 测试）、
> **A 92/92 全活**、B/D 0。定案表与施加核验记录见 doc/C2/C2-4-核验.py /
> C2-4-核验结果.json（summary verified=295 ok=295 unexpected=0 之段A 部分）。
> C 类判据主轴：moark 嵌入协议契约（请求体字段/鉴权头/响应 index 还原/usage 计量/
> 429 retryable）经真实 httpx MockTransport 路径补测——既有 M18 测试对该函数全部
> 打桩替身，真实路径零覆盖为本段 87 条幸存主因；db G2 新列枚举精确性/source_keyword
> 补列/D19 库内归一（raw SQL 读——ORM 读被 PromptVersion 双向归一兜底遮蔽，系
> 既有测试未杀的根因）。

### app.embedding.moark.xǁMoarkEmbeddingProviderǁ_embed_request（23 条）

| 变异体 | 类 | 说明 | 依据 |
|---|---|---|---|
| app.embedding.moark.xǁMoarkEmbeddingProviderǁ_embed_request__mutmut_23 | A | Authorization 键小写/大写：HTTP 头名大小写不敏感（RFC 7230），服务端解析等价——httpx 头名归一化判据族（batch4 m29/30 先例） | 历史判据族复用（详见说明列） |
| app.embedding.moark.xǁMoarkEmbeddingProviderǁ_embed_request__mutmut_24 | A | Authorization 键小写/大写：HTTP 头名大小写不敏感（RFC 7230），服务端解析等价——httpx 头名归一化判据族（batch4 m29/30 先例） | 历史判据族复用（详见说明列） |
| app.embedding.moark.xǁMoarkEmbeddingProviderǁ_embed_request__mutmut_25 | A | Content-Type 键 XX：httpx 对 json= 参数自动携带 Content-Type: application/json，显式键名变异被自动头兜底、结果头不变——恰等价（本批 A 轮实测新判例：C 轮施加 16 判据面测试仍全绿，键 XX 化后 httpx 自动补正主头） | 等价/不可达（控制流推理、列缺省承载、平台语义） |
| app.embedding.moark.xǁMoarkEmbeddingProviderǁ_embed_request__mutmut_26 | A | Content-Type 键小写/大写：HTTP 头名大小写不敏感——同 m23 判据族 | 历史判据族复用（详见说明列） |
| app.embedding.moark.xǁMoarkEmbeddingProviderǁ_embed_request__mutmut_27 | A | Content-Type 键小写/大写：HTTP 头名大小写不敏感——同 m23 判据族 | 历史判据族复用（详见说明列） |
| app.embedding.moark.xǁMoarkEmbeddingProviderǁ_embed_request__mutmut_32 | A | EmbeddingError(None)：异常消息文案——消息措辞无条款（batch2 m24-35 先例） | 历史判据族复用（详见说明列） |
| app.embedding.moark.xǁMoarkEmbeddingProviderǁ_embed_request__mutmut_33 | A | _scrub(None)：消息中响应体预览丢失——消息内容细节无条款（batch2 m42 同族） | 等价/不可达（控制流推理、列缺省承载、平台语义） |
| app.embedding.moark.xǁMoarkEmbeddingProviderǁ_embed_request__mutmut_34 | A | 响应体截断 [:300]→[:301]：截断界数值无条款（batch2 m42、批次10 m69 先例） | 历史判据族复用（详见说明列） |
| app.embedding.moark.xǁMoarkEmbeddingProviderǁ_embed_request__mutmut_37 | A | >=400 → >400/>=401：差异域=恰 400 状态码响应，两形态均以 EmbeddingError 终态（400 响应体必无 data 数组→「缺少 data」错误），仅消息细节异——状态码界面域 + 终态同型（C2-3 m247 数值边界族；消息无条款） | 等价/不可达（控制流推理、列缺省承载、平台语义） |
| app.embedding.moark.xǁMoarkEmbeddingProviderǁ_embed_request__mutmut_38 | A | >=400 → >400/>=401：差异域=恰 400 状态码响应，两形态均以 EmbeddingError 终态（400 响应体必无 data 数组→「缺少 data」错误），仅消息细节异——状态码界面域 + 终态同型（C2-3 m247 数值边界族；消息无条款） | 等价/不可达（控制流推理、列缺省承载、平台语义） |
| app.embedding.moark.xǁMoarkEmbeddingProviderǁ_embed_request__mutmut_39 | A | 400 分支消息 None/预览丢失/截断界：消息文案细节——同 m32-34 判据 | 等价/不可达（控制流推理、列缺省承载、平台语义） |
| app.embedding.moark.xǁMoarkEmbeddingProviderǁ_embed_request__mutmut_40 | A | 400 分支消息 None/预览丢失/截断界：消息文案细节——同 m32-34 判据 | 等价/不可达（控制流推理、列缺省承载、平台语义） |
| app.embedding.moark.xǁMoarkEmbeddingProviderǁ_embed_request__mutmut_41 | A | 400 分支消息 None/预览丢失/截断界：消息文案细节——同 m32-34 判据 | 等价/不可达（控制流推理、列缺省承载、平台语义） |
| app.embedding.moark.xǁMoarkEmbeddingProviderǁ_embed_request__mutmut_50 | A | 「缺少 data」消息 None：消息文案（batch2 m24 先例） | 历史判据族复用（详见说明列） |
| app.embedding.moark.xǁMoarkEmbeddingProviderǁ_embed_request__mutmut_58 | A | index 缺省 None：差异域=缺 index 键的违约响应（协议恒含 index〔EV1 实测〕），缺省分支域=违约形态——防御缺省不可达判据族（C2-3 m75 先例） | 历史判据族复用（详见说明列） |
| app.embedding.moark.xǁMoarkEmbeddingProviderǁ_embed_request__mutmut_60 | A | get("index",) 单参：缺省 None——同 m58 判据（违约响应域缺省不可达） | 等价/不可达（控制流推理、列缺省承载、平台语义） |
| app.embedding.moark.xǁMoarkEmbeddingProviderǁ_embed_request__mutmut_63 | A | index 缺省 0→1：差异域=缺 index 键的违约响应——同 m58 判据 | 等价/不可达（控制流推理、列缺省承载、平台语义） |
| app.embedding.moark.xǁMoarkEmbeddingProviderǁ_embed_request__mutmut_72 | A | 「空/非法向量」消息 None/XX/大写：消息文案（batch2 m24 先例） | 历史判据族复用（详见说明列） |
| app.embedding.moark.xǁMoarkEmbeddingProviderǁ_embed_request__mutmut_73 | A | 「空/非法向量」消息 None/XX/大写：消息文案（batch2 m24 先例） | 历史判据族复用（详见说明列） |
| app.embedding.moark.xǁMoarkEmbeddingProviderǁ_embed_request__mutmut_74 | A | 「空/非法向量」消息 None/XX/大写：消息文案（batch2 m24 先例） | 历史判据族复用（详见说明列） |
| app.embedding.moark.xǁMoarkEmbeddingProviderǁ_embed_request__mutmut_88 | A | or 0→or 1：差异域=缺 prompt_tokens 键的违约响应（正常响应恒含〔EV1 实测〕），兜底数值无条款——防御缺省不可达 + 数值缺省族（C2-3 m75/m15 先例） | 历史判据族复用（详见说明列） |
| app.embedding.moark.xǁMoarkEmbeddingProviderǁ_embed_request__mutmut_89 | A | meter "item_count" 键 XX/大写：死返回值——base 层 item_count=len(inputs) 落账（embedding/base.py:119 调用点核查），meter 键无消费方（C2-3 EF m14 死返回值判据） | 等价/不可达（控制流推理、列缺省承载、平台语义） |
| app.embedding.moark.xǁMoarkEmbeddingProviderǁ_embed_request__mutmut_90 | A | meter "item_count" 键 XX/大写：死返回值——base 层 item_count=len(inputs) 落账（embedding/base.py:119 调用点核查），meter 键无消费方（C2-3 EF m14 死返回值判据） | 等价/不可达（控制流推理、列缺省承载、平台语义） |

### app.db.x__migrate_added_columns（67 条）

| 变异体 | 类 | 说明 | 依据 |
|---|---|---|---|

### app.models（Direction.apply_status / PromptVersion 双向归一）（2 条）

| 变异体 | 类 | 说明 | 依据 |
|---|---|---|---|
| app.models.xǁPromptVersionǁprocess_bind_param__mutmut_1 | A | bind None 分支恒假化：写入端 None 由列 default=1 先行兜底（C2-3 实证：显式 None 触发列 default；default 替换先于类型 bind），None 不可达——防御缺省不可达 | 等价/不可达（控制流推理、列缺省承载、平台语义） |

## C2-4 分诊批次 4B（2026-10-06，收官批段B：schema 23 + hot 21 + writer 19 + providers 23 + api.routes 16 + rerank/search 34 = 129 条）：A 77 条

> 段B 同上（同批种子、同款重建与核验）。终态：**C 52/52 全杀**（
> tests/test_author_schema_pass_entries.py 4 + tests/test_hot_fallback_keywords.py 5 +
> tests/test_provider_post_json_contract.py 5 + tests/test_rerank_provider_construction.py
> 5 + tests/test_author.py 既有违规标记测试 +1 断言 + tests/test_directions.py +3 +
> tests/test_sources_crud.py +1）、**A 77/77 全活**、B/D 0。C 类判据主轴：
> schema passes 条目校验路径（AC-10.1）/ 热榜分词兜底统计纪律（docstring 钉）/
> _post_json 协议请求体与官方错误码语义映射 + chat_json json_mode 缺省 /
> rerank 装配契约（D-A 尾斜杠 + D-B Bearer 头 + §4.2 有限超时）/ routes 序列化
> 字段（OpenAPI name/prompt/url）。本段关键等价发现：run_hot_round 全平台失败
> 提前 return 使 task_status 计算与 error 条件成死条件域（8 条）；错误体结构契约
> 由 main.coded_error_handler 重组承载（routes 侧 detail 键名变异被吸收）。

（其余全域） A 类 77 条

### app.authors.schema.x__validate_pass_entry（10 条）

| 变异体 | 类 | 说明 | 依据 |
|---|---|---|---|
| app.authors.schema.x__validate_pass_entry__mutmut_11 | A | entry 非 dict 错误的实得值/期望类型措辞变体（路径保留）：AC-10.1 未钉措辞——批次 8a 文案判据族 | 历史判据族复用（详见说明列） |
| app.authors.schema.x__validate_pass_entry__mutmut_12 | A | entry 非 dict 错误的实得值/期望类型措辞变体（路径保留）：AC-10.1 未钉措辞——批次 8a 文案判据族 | 历史判据族复用（详见说明列） |
| app.authors.schema.x__validate_pass_entry__mutmut_27 | A | params get 缺省 None/单参：params 键存在时返回值不变，键缺失时 None/{} 两形态均跳过校验（is not None / isinstance({},dict)）——缺省变体控制流等价 | 等价/不可达（控制流推理、列缺省承载、平台语义） |
| app.authors.schema.x__validate_pass_entry__mutmut_29 | A | params get 缺省 None/单参：params 键存在时返回值不变，键缺失时 None/{} 两形态均跳过校验（is not None / isinstance({},dict)）——缺省变体控制流等价 | 等价/不可达（控制流推理、列缺省承载、平台语义） |
| app.authors.schema.x__validate_pass_entry__mutmut_37 | A | params 类型错误的实得值/期望类型措辞变体（路径保留）：同上判据族 | 历史判据族复用（详见说明列） |
| app.authors.schema.x__validate_pass_entry__mutmut_38 | A | params 类型错误的实得值/期望类型措辞变体（路径保留）：同上判据族 | 历史判据族复用（详见说明列） |
| app.authors.schema.x__validate_pass_entry__mutmut_43 | A | params 类型错误的实得值/期望类型措辞变体（路径保留）：同上判据族 | 历史判据族复用（详见说明列） |
| app.authors.schema.x__validate_pass_entry__mutmut_44 | A | params 类型错误的实得值/期望类型措辞变体（路径保留）：同上判据族 | 历史判据族复用（详见说明列） |
| app.authors.schema.x__validate_pass_entry__mutmut_5 | A | entry 非 dict 错误的实得值/期望类型措辞变体（路径保留）：AC-10.1 未钉措辞——批次 8a 文案判据族 | 历史判据族复用（详见说明列） |
| app.authors.schema.x__validate_pass_entry__mutmut_6 | A | entry 非 dict 错误的实得值/期望类型措辞变体（路径保留）：AC-10.1 未钉措辞——批次 8a 文案判据族 | 历史判据族复用（详见说明列） |

### app.hot.service（_fallback_keywords_from_titles / run_hot_round）（16 条）

| 变异体 | 类 | 说明 | 依据 |
|---|---|---|---|
| app.hot.service.x__fallback_keywords_from_titles__mutmut_12 | A | len(w)>1 与 or/>=：差异域=长度 1 的 ASCII 词计入——docstring 只钉「去停用词与纯数字段」，单字母过滤未钉——分词细节无条款（数值边界族） | 等价/不可达（控制流推理、列缺省承载、平台语义） |
| app.hot.service.x__fallback_keywords_from_titles__mutmut_13 | A | len(w)>1 与 or/>=：差异域=长度 1 的 ASCII 词计入——docstring 只钉「去停用词与纯数字段」，单字母过滤未钉——分词细节无条款（数值边界族） | 等价/不可达（控制流推理、列缺省承载、平台语义） |
| app.hot.service.x__fallback_keywords_from_titles__mutmut_28 | A | 2-gram 计数 +=2：全部计数同比放大，most_common 排序不变、返回只取 w 序——计数值无消费方（返回值死计数判据；C2-3 EF m14 同族） | 等价/不可达（控制流推理、列缺省承载、平台语义） |
| app.hot.service.x_run_hot_round__mutmut_213 | A | _rank_filter_topics db 实参 None：HOT_RANK_FILTER 默认关（模块 docstring）→ 首分支 return 不触 db——缺省分支 db 死参（生产开关默认关核查） | 等价/不可达（控制流推理、列缺省承载、平台语义） |
| app.hot.service.x_run_hot_round__mutmut_228 | A | 降级 log.warning 文案 XX：日志措辞无条款——批次 10 m225-227 先例 | 历史判据族复用（详见说明列） |
| app.hot.service.x_run_hot_round__mutmut_243 | A | task_status 计算与 error 条件死域（8 条）：全平台失败在行 194-198 提前 return FAILED，行 253 not ok_platforms 恒 False（task_status 恒 DONE、"FAILED" 值恒不取）、行 262 条件恒 False（error 恒 None）——控制流不可达（提前 return 域核查；kw_error 实际经 stats.kw_error 呈现） | 等价/不可达（控制流推理、列缺省承载、平台语义） |
| app.hot.service.x_run_hot_round__mutmut_279 | A | task_status 计算与 error 条件死域（8 条）：全平台失败在行 194-198 提前 return FAILED，行 253 not ok_platforms 恒 False（task_status 恒 DONE、"FAILED" 值恒不取）、行 262 条件恒 False（error 恒 None）——控制流不可达（提前 return 域核查；kw_error 实际经 stats.kw_error 呈现） | 等价/不可达（控制流推理、列缺省承载、平台语义） |

### app.authors.writer.x_run_write（18 条）

| 变异体 | 类 | 说明 | 依据 |
|---|---|---|---|
| app.authors.writer.x_run_write__mutmut_100 | A | temperature None/缺参/1.3：写作温度数值无条款（批次 10 数值缺省族；调用形态语义不变） | 等价/不可达（控制流推理、列缺省承载、平台语义） |
| app.authors.writer.x_run_write__mutmut_113 | A | 成功路径 last_error None→""：读取点仅 FAILED 分支（该处必为失败消息），成功路径后不读——初值/成功复位不可达（批次 9 m77 先例） | 历史判据族复用（详见说明列） |
| app.authors.writer.x_run_write__mutmut_114 | A | citation_violated False→None（初值/成功复位）：落 Article 时列 default=False 兜底（C2-3 实证显式 None 触发列 default）——ORM 列缺省族 | 等价/不可达（控制流推理、列缺省承载、平台语义） |
| app.authors.writer.x_run_write__mutmut_129 | A | 拒收重试提示词文案/大小写：提示词措辞无条款——批次 9 m51/m52 先例（语义指令保留于 W4 条款面非措辞面） | 历史判据族复用（详见说明列） |
| app.authors.writer.x_run_write__mutmut_136 | A | 拒收重试提示词文案/大小写：提示词措辞无条款——批次 9 m51/m52 先例（语义指令保留于 W4 条款面非措辞面） | 历史判据族复用（详见说明列） |
| app.authors.writer.x_run_write__mutmut_137 | A | 拒收重试提示词文案/大小写：提示词措辞无条款——批次 9 m51/m52 先例（语义指令保留于 W4 条款面非措辞面） | 历史判据族复用（详见说明列） |
| app.authors.writer.x_run_write__mutmut_138 | A | 拒收重试提示词文案/大小写：提示词措辞无条款——批次 9 m51/m52 先例（语义指令保留于 W4 条款面非措辞面） | 历史判据族复用（详见说明列） |
| app.authors.writer.x_run_write__mutmut_139 | A | 拒收重试提示词文案/大小写：提示词措辞无条款——批次 9 m51/m52 先例（语义指令保留于 W4 条款面非措辞面） | 历史判据族复用（详见说明列） |
| app.authors.writer.x_run_write__mutmut_140 | A | 拒收重试提示词文案/大小写：提示词措辞无条款——批次 9 m51/m52 先例（语义指令保留于 W4 条款面非措辞面） | 历史判据族复用（详见说明列） |
| app.authors.writer.x_run_write__mutmut_141 | A | 拒收重试提示词文案/大小写：提示词措辞无条款——批次 9 m51/m52 先例（语义指令保留于 W4 条款面非措辞面） | 历史判据族复用（详见说明列） |
| app.authors.writer.x_run_write__mutmut_180 | A | Article status None/行删除：列 default="PUBLISHED_TO_C" 兜底（models.py:271）——ORM 列缺省族（C2-3 实证） | 等价/不可达（控制流推理、列缺省承载、平台语义） |
| app.authors.writer.x_run_write__mutmut_186 | A | Article status None/行删除：列 default="PUBLISHED_TO_C" 兜底（models.py:271）——ORM 列缺省族（C2-3 实证） | 等价/不可达（控制流推理、列缺省承载、平台语义） |
| app.authors.writer.x_run_write__mutmut_193 | A | 无题兜底 "XX（无题）XX"：无题文案无条款（batch4 m4 html_title 先例） | 历史判据族复用（详见说明列） |
| app.authors.writer.x_run_write__mutmut_221 | A | 收尾 run.error None→""：成功收尾 error 清空形态（None vs 空串）无条款——批次 9 m77 同族 | 等价/不可达（控制流推理、列缺省承载、平台语义） |
| app.authors.writer.x_run_write__mutmut_78 | A | citation_violated False→None（初值/成功复位）：落 Article 时列 default=False 兜底（C2-3 实证显式 None 触发列 default）——ORM 列缺省族 | 等价/不可达（控制流推理、列缺省承载、平台语义） |
| app.authors.writer.x_run_write__mutmut_79 | A | citation_violated 初值 True：全路径等价——成功 break 必经行 266 复位 False、except 路径经 or-累积（True or X 与 False or X 在 isinstance 域同值）、两次全败路径不落 article（FAILED return 不读取）——控制流全路径枚举核查（既有 test_citation_normal_path_flag_false 断言 False 与 dispatch 幸存自洽的旁证；初判 C 经路径枚举复核改判） | 等价/不可达（控制流推理、列缺省承载、平台语义） |
| app.authors.writer.x_run_write__mutmut_88 | A | temperature None/缺参/1.3：写作温度数值无条款（批次 10 数值缺省族；调用形态语义不变） | 等价/不可达（控制流推理、列缺省承载、平台语义） |
| app.authors.writer.x_run_write__mutmut_94 | A | temperature None/缺参/1.3：写作温度数值无条款（批次 10 数值缺省族；调用形态语义不变） | 等价/不可达（控制流推理、列缺省承载、平台语义） |

### app.providers.base.xǁHTTPProviderǁ_post_json（7 条）

| 变异体 | 类 | 说明 | 依据 |
|---|---|---|---|
| app.providers.base.xǁHTTPProviderǁ_post_json__mutmut_11 | A | retryable 分支 e=ProviderError(None)/_scrub(None)/[:301] 与 FATAL 分支预览丢失/截断界：消息文案细节无条款——batch2 m24/m25/m42 先例（错误语义=类型+重试性已由 C 断言承载） | 历史判据族复用（详见说明列） |
| app.providers.base.xǁHTTPProviderǁ_post_json__mutmut_12 | A | retryable 分支 e=ProviderError(None)/_scrub(None)/[:301] 与 FATAL 分支预览丢失/截断界：消息文案细节无条款——batch2 m24/m25/m42 先例（错误语义=类型+重试性已由 C 断言承载） | 历史判据族复用（详见说明列） |
| app.providers.base.xǁHTTPProviderǁ_post_json__mutmut_13 | A | retryable 分支 e=ProviderError(None)/_scrub(None)/[:301] 与 FATAL 分支预览丢失/截断界：消息文案细节无条款——batch2 m24/m25/m42 先例（错误语义=类型+重试性已由 C 断言承载） | 历史判据族复用（详见说明列） |
| app.providers.base.xǁHTTPProviderǁ_post_json__mutmut_20 | A | msg 缺省 None/空：差异域=非映射表内 4xx（403/404 等未知态）的兜底文案（"HTTP 403" vs None:），官方语义只钉 400/401/402/422 四态——未知态兜底文案无条款 | 等价/不可达（控制流推理、列缺省承载、平台语义） |
| app.providers.base.xǁHTTPProviderǁ_post_json__mutmut_22 | A | msg 缺省 None/空：差异域=非映射表内 4xx（403/404 等未知态）的兜底文案（"HTTP 403" vs None:），官方语义只钉 400/401/402/422 四态——未知态兜底文案无条款 | 等价/不可达（控制流推理、列缺省承载、平台语义） |
| app.providers.base.xǁHTTPProviderǁ_post_json__mutmut_24 | A | retryable 分支 e=ProviderError(None)/_scrub(None)/[:301] 与 FATAL 分支预览丢失/截断界：消息文案细节无条款——batch2 m24/m25/m42 先例（错误语义=类型+重试性已由 C 断言承载） | 历史判据族复用（详见说明列） |
| app.providers.base.xǁHTTPProviderǁ_post_json__mutmut_25 | A | retryable 分支 e=ProviderError(None)/_scrub(None)/[:301] 与 FATAL 分支预览丢失/截断界：消息文案细节无条款——batch2 m24/m25/m42 先例（错误语义=类型+重试性已由 C 断言承载） | 历史判据族复用（详见说明列） |

### app.rerank.moark_reranker.xǁMoarkRerankerProviderǁ__init__（3 条）

| 变异体 | 类 | 说明 | 依据 |
|---|---|---|---|
| app.rerank.moark_reranker.xǁMoarkRerankerProviderǁ__init____mutmut_1 | A | timeout 缺省 121.0：任意有限值满足 §4.2——数值缺省族（批次 10 embedding __init__ m1 先例） | 历史判据族复用（详见说明列） |
| app.rerank.moark_reranker.xǁMoarkRerankerProviderǁ__init____mutmut_13 | A | _query_max_chars=None：构造缺省即 None（签名 int|None=None），显式实验路径外的缺省恒等——缺省恒等判据 | 等价/不可达（控制流推理、列缺省承载、平台语义） |
| app.rerank.moark_reranker.xǁMoarkRerankerProviderǁ__init____mutmut_7 | A | rstrip("XX/XX")：字符集语义 {X,/}，URL 尾部无 X——恰等价（批次 10 m7 先例） | 历史判据族复用（详见说明列） |

### app.rerank.base.xǁHTTPRankProviderǁ__init__（1 条）

| 变异体 | 类 | 说明 | 依据 |
|---|---|---|---|
| app.rerank.base.xǁHTTPRankProviderǁ__init____mutmut_5 | A | rstrip("XX/XX")：字符集语义恰等价——批次 10 m7 先例 | 历史判据族复用（详见说明列） |

### app.search.base.xǁHTTPSearchProviderǁ__init__（1 条）

| 变异体 | 类 | 说明 | 依据 |
|---|---|---|---|
| app.search.base.xǁHTTPSearchProviderǁ__init____mutmut_1 | A | timeout 缺省 31.0：任意有限值满足 §4.2——数值缺省族 | 等价/不可达（控制流推理、列缺省承载、平台语义） |

### app.search.bocha.xǁBochaSearchProviderǁ__init__（5 条）

| 变异体 | 类 | 说明 | 依据 |
|---|---|---|---|
| app.search.bocha.xǁBochaSearchProviderǁ__init____mutmut_1 | A | timeout 缺省 31.0：数值缺省族（§4.2 有限值语义不变） | 等价/不可达（控制流推理、列缺省承载、平台语义） |
| app.search.bocha.xǁBochaSearchProviderǁ__init____mutmut_9 | A | 缺 Key 错误文案变体：文案措辞无条款——批次 10 BochaJevRankProvider m5 先例 | 历史判据族复用（详见说明列） |

### app.search.pipeline.x_fetch_search_source（7 条）

| 变异体 | 类 | 说明 | 依据 |
|---|---|---|---|
| app.search.pipeline.x_fetch_search_source__mutmut_252 | A | SanitizeTarget url=None/实参删除：现有 sanitizer 链不读 url——batch5 m122/批次 10 m250 先例 | 历史判据族复用（详见说明列） |

### app.api.routes（序列化/错误体/TTL 辅助函数）（9 条）

| 变异体 | 类 | 说明 | 依据 |
|---|---|---|---|
| app.api.routes.x__get_live_direction__mutmut_16 | A | 404 detail "message" 键 XX/大写：错误体结构契约由 main.coded_error_handler 承载（main.py:29 自行重组 {code, message=detail.get("message", "")}），routes 侧 detail 键名变异被 handler.get 缺省吸收，可观察面只剩 message 值（"方向不存在"→""）——值措辞无条款（初判 C 经 C 轮施加实测纠偏改判；OpenAPI required 只钉响应字段存在，handler 重组后恒在） | 等价/不可达（控制流推理、列缺省承载、平台语义） |
| app.api.routes.x__get_live_direction__mutmut_17 | A | 404 detail "message" 键 XX/大写：错误体结构契约由 main.coded_error_handler 承载（main.py:29 自行重组 {code, message=detail.get("message", "")}），routes 侧 detail 键名变异被 handler.get 缺省吸收，可观察面只剩 message 值（"方向不存在"→""）——值措辞无条款（初判 C 经 C 轮施加实测纠偏改判；OpenAPI required 只钉响应字段存在，handler 重组后恒在） | 等价/不可达（控制流推理、列缺省承载、平台语义） |
| app.api.routes.x__get_live_direction__mutmut_18 | A | message 值 XX 包裹：措辞值无条款（required 只钉字段存在）——batch2 异常消息族；与 m16 族同一 handler 重组承载面 | 等价/不可达（控制流推理、列缺省承载、平台语义） |
| app.api.routes.x__get_live_direction__mutmut_29 | A | 404 detail "message" 键 XX/大写：错误体结构契约由 main.coded_error_handler 承载（main.py:29 自行重组 {code, message=detail.get("message", "")}），routes 侧 detail 键名变异被 handler.get 缺省吸收，可观察面只剩 message 值（"方向不存在"→""）——值措辞无条款（初判 C 经 C 轮施加实测纠偏改判；OpenAPI required 只钉响应字段存在，handler 重组后恒在） | 等价/不可达（控制流推理、列缺省承载、平台语义） |
| app.api.routes.x__get_live_direction__mutmut_30 | A | 404 detail "message" 键 XX/大写：错误体结构契约由 main.coded_error_handler 承载（main.py:29 自行重组 {code, message=detail.get("message", "")}），routes 侧 detail 键名变异被 handler.get 缺省吸收，可观察面只剩 message 值（"方向不存在"→""）——值措辞无条款（初判 C 经 C 轮施加实测纠偏改判；OpenAPI required 只钉响应字段存在，handler 重组后恒在） | 等价/不可达（控制流推理、列缺省承载、平台语义） |
| app.api.routes.x__get_live_direction__mutmut_31 | A | message 值 XX 包裹：措辞值无条款（required 只钉字段存在）——batch2 异常消息族；与 m16 族同一 handler 重组承载面 | 等价/不可达（控制流推理、列缺省承载、平台语义） |

---

## C2-5 收官再同步记录（2026-10-06，统筹亲执）

> 收官统一 dispatch（run 37410775426 @ main 2f9824d）逐名核对：豁免位中 **5 条转 killed**（C2 各批新测试顺带杀灭：pipeline.execute m268 / rss m91 / moark __init__ m12 / rss.parse_feed_entries m29 / gates.topic_dedup m17）——本节移除，清单 1868 → **1863**。
> 同批收官处置：interleave m17（Random(seed)→Random(None)）系 **RNG 依赖型 flaky 变异**（两轮 dispatch 映射与代码零变化下判定翻转）——已补确定性杀灭测试（同 seed 两次调用必一致），非豁免；D1（暂态轮 last_error）经用户拍板①落册产品书 v1.8 并补测试杀灭。


## C3-1 分诊批次 1（2026-10-07，通知触发与通道族 251 条）：A 124 条

> 种子 251 = C 87（补测杀灭：tests/test_smtp_delivery_contract.py + tests/test_notify_trigger_guards.py）+ A 139（本节）+ D 25（呈统筹，不在本清单：通知邮件内容承载/MIME 头形态/部分凭据登录门槛未落条款）。B 0。核验-改判循环：C 逐条施加必杀、A 逐条施加必活至零意外（doc/C3/C3-1-核验结果.json）。

### app.notify.smtp.xǁSMTPNotifierǁ_deliver（19 条）

| 变异体 | 类 | 说明 | 依据 |
|---|---|---|---|
| app.notify.smtp.xǁSMTPNotifierǁ_deliver__mutmut_12 | A | 端口缺省回退 465→466：差异域=port 未设——configured 门槛（send 与 /notify/test 双入口先查 configured）使缺省域不可达（防御缺省不可达族） | 设计书条款/实证推理（详见说明列） |
| app.notify.smtp.xǁSMTPNotifierǁ_deliver__mutmut_31 | A | 收件备用键 to_addrs 变体：routes PUT 实证 to_addrs 落 smtp_to 键，smtp_to_addrs 无生产写入口——备用键域不可达（调用点核查先例） | 设计书条款/实证推理（详见说明列） |
| app.notify.smtp.xǁSMTPNotifierǁ_deliver__mutmut_32 | A | 收件备用键 to_addrs 变体：routes PUT 实证 to_addrs 落 smtp_to 键，smtp_to_addrs 无生产写入口——备用键域不可达（调用点核查先例） | 设计书条款/实证推理（详见说明列） |
| app.notify.smtp.xǁSMTPNotifierǁ_deliver__mutmut_33 | A | 收件备用键 to_addrs 变体：routes PUT 实证 to_addrs 落 smtp_to 键，smtp_to_addrs 无生产写入口——备用键域不可达（调用点核查先例） | 设计书条款/实证推理（详见说明列） |
| app.notify.smtp.xǁSMTPNotifierǁ_deliver__mutmut_34 | A | 字符串收件配置归一分支 None 化：差异域=手写字符串形态 smtp_to——API 写入口恒 list（PUT schema 实证），兼容域正常运行不可达 | 设计书条款/实证推理（详见说明列） |
| app.notify.smtp.xǁSMTPNotifierǁ_deliver__mutmut_37 | A | MIME 子类型变体（None/utf-8/XX/大写）：正文仍在位、邮件仍发出——MIME 子类型细节无条款（实测不抛异常；内容承载未钉） | 设计书条款/实证推理（详见说明列） |
| app.notify.smtp.xǁSMTPNotifierǁ_deliver__mutmut_38 | A | 字符集变体（None/缺省/UTF-8）：实测输出与原形全同（charset None/缺省即 utf-8）——恰等价（venv 实测） | 设计书条款/实证推理（详见说明列） |
| app.notify.smtp.xǁSMTPNotifierǁ_deliver__mutmut_40 | A | MIME 子类型变体（None/utf-8/XX/大写）：正文仍在位、邮件仍发出——MIME 子类型细节无条款（实测不抛异常；内容承载未钉） | 设计书条款/实证推理（详见说明列） |
| app.notify.smtp.xǁSMTPNotifierǁ_deliver__mutmut_41 | A | 字符集变体（None/缺省/UTF-8）：实测输出与原形全同（charset None/缺省即 utf-8）——恰等价（venv 实测） | 设计书条款/实证推理（详见说明列） |
| app.notify.smtp.xǁSMTPNotifierǁ_deliver__mutmut_42 | A | MIME 子类型变体（None/utf-8/XX/大写）：正文仍在位、邮件仍发出——MIME 子类型细节无条款（实测不抛异常；内容承载未钉） | 设计书条款/实证推理（详见说明列） |
| app.notify.smtp.xǁSMTPNotifierǁ_deliver__mutmut_43 | A | MIME 子类型变体（None/utf-8/XX/大写）：正文仍在位、邮件仍发出——MIME 子类型细节无条款（实测不抛异常；内容承载未钉） | 设计书条款/实证推理（详见说明列） |
| app.notify.smtp.xǁSMTPNotifierǁ_deliver__mutmut_45 | A | 字符集变体（None/缺省/UTF-8）：实测输出与原形全同（charset None/缺省即 utf-8）——恰等价（venv 实测） | 设计书条款/实证推理（详见说明列） |
| app.notify.smtp.xǁSMTPNotifierǁ_deliver__mutmut_48 | A | Subject/From/To 头名小写/大写：RFC 5322 头字段名大小写不敏感——HTTP 头名不敏感先例族（EMB m23-27 同构） | 设计书条款/实证推理（详见说明列） |
| app.notify.smtp.xǁSMTPNotifierǁ_deliver__mutmut_49 | A | Subject/From/To 头名小写/大写：RFC 5322 头字段名大小写不敏感——HTTP 头名不敏感先例族（EMB m23-27 同构） | 设计书条款/实证推理（详见说明列） |
| app.notify.smtp.xǁSMTPNotifierǁ_deliver__mutmut_52 | A | Subject/From/To 头名小写/大写：RFC 5322 头字段名大小写不敏感——HTTP 头名不敏感先例族（EMB m23-27 同构） | 设计书条款/实证推理（详见说明列） |
| app.notify.smtp.xǁSMTPNotifierǁ_deliver__mutmut_53 | A | Subject/From/To 头名小写/大写：RFC 5322 头字段名大小写不敏感——HTTP 头名不敏感先例族（EMB m23-27 同构） | 设计书条款/实证推理（详见说明列） |
| app.notify.smtp.xǁSMTPNotifierǁ_deliver__mutmut_56 | A | Subject/From/To 头名小写/大写：RFC 5322 头字段名大小写不敏感——HTTP 头名不敏感先例族（EMB m23-27 同构） | 设计书条款/实证推理（详见说明列） |
| app.notify.smtp.xǁSMTPNotifierǁ_deliver__mutmut_57 | A | Subject/From/To 头名小写/大写：RFC 5322 头字段名大小写不敏感——HTTP 头名不敏感先例族（EMB m23-27 同构） | 设计书条款/实证推理（详见说明列） |
| app.notify.smtp.xǁSMTPNotifierǁ_deliver__mutmut_66 | A | timeout 30→31：任意有限值满足 §4.2——数值缺省族（批次 10 先例） | 设计书条款/实证推理（详见说明列） |

### app.notify.smtp.xǁSMTPNotifierǁconfigured（3 条）

| 变异体 | 类 | 说明 | 依据 |
|---|---|---|---|
| app.notify.smtp.xǁSMTPNotifierǁconfigured__mutmut_6 | A | 收件备用键 to_addrs 变体：smtp_to_addrs 无生产写入口（PUT 实证存 smtp_to）——备用键域不可达（调用点核查先例） | 设计书条款/实证推理（详见说明列） |
| app.notify.smtp.xǁSMTPNotifierǁconfigured__mutmut_7 | A | 收件备用键 to_addrs 变体：smtp_to_addrs 无生产写入口（PUT 实证存 smtp_to）——备用键域不可达（调用点核查先例） | 设计书条款/实证推理（详见说明列） |
| app.notify.smtp.xǁSMTPNotifierǁconfigured__mutmut_8 | A | 收件备用键 to_addrs 变体：smtp_to_addrs 无生产写入口（PUT 实证存 smtp_to）——备用键域不可达（调用点核查先例） | 设计书条款/实证推理（详见说明列） |

### app.notify.triggers.x__dispatch（24 条）

| 变异体 | 类 | 说明 | 依据 |
|---|---|---|---|
| app.notify.triggers.x__dispatch__mutmut_13 | A | 开关关闭 log.info 文案/实参变体（格式化仍合法）：日志措辞无条款、格式化正常完成——批次 3 文案先例 | 设计书条款/实证推理（详见说明列） |
| app.notify.triggers.x__dispatch__mutmut_18 | A | switch_off 返回字典 reason 键/值变体：诊断文案无消费方——诊断镜像键面判据（HR m296/297 先例；sent 布尔已另判 C，reason 字符串无条款） | 设计书条款/实证推理（详见说明列） |
| app.notify.triggers.x__dispatch__mutmut_19 | A | switch_off 返回字典 reason 键/值变体：诊断文案无消费方——诊断镜像键面判据（HR m296/297 先例；sent 布尔已另判 C，reason 字符串无条款） | 设计书条款/实证推理（详见说明列） |
| app.notify.triggers.x__dispatch__mutmut_20 | A | switch_off 返回字典 reason 键/值变体：诊断文案无消费方——诊断镜像键面判据（HR m296/297 先例；sent 布尔已另判 C，reason 字符串无条款） | 设计书条款/实证推理（详见说明列） |
| app.notify.triggers.x__dispatch__mutmut_21 | A | switch_off 返回字典 reason 键/值变体：诊断文案无消费方——诊断镜像键面判据（HR m296/297 先例；sent 布尔已另判 C，reason 字符串无条款） | 设计书条款/实证推理（详见说明列） |
| app.notify.triggers.x__dispatch__mutmut_25 | A | 无通道 log.info 文案/实参变体：日志措辞无条款——同上文案先例 | 设计书条款/实证推理（详见说明列） |
| app.notify.triggers.x__dispatch__mutmut_26 | A | 无通道 log.info 文案/实参变体：日志措辞无条款——同上文案先例 | 设计书条款/实证推理（详见说明列） |
| app.notify.triggers.x__dispatch__mutmut_27 | A | 无通道 log.info 文案/实参变体：日志措辞无条款——同上文案先例 | 设计书条款/实证推理（详见说明列） |
| app.notify.triggers.x__dispatch__mutmut_28 | A | 无通道 log.info 文案/实参变体：日志措辞无条款——同上文案先例 | 设计书条款/实证推理（详见说明列） |
| app.notify.triggers.x__dispatch__mutmut_29 | A | 无通道 log.info 文案/实参变体：日志措辞无条款——同上文案先例 | 设计书条款/实证推理（详见说明列） |
| app.notify.triggers.x__dispatch__mutmut_30 | A | 无通道 log.info 文案/实参变体：日志措辞无条款——同上文案先例 | 设计书条款/实证推理（详见说明列） |
| app.notify.triggers.x__dispatch__mutmut_31 | A | 无通道 log.info 文案/实参变体：日志措辞无条款——同上文案先例 | 设计书条款/实证推理（详见说明列） |
| app.notify.triggers.x__dispatch__mutmut_32 | A | 无通道 log.info 文案/实参变体：日志措辞无条款——同上文案先例 | 设计书条款/实证推理（详见说明列） |
| app.notify.triggers.x__dispatch__mutmut_33 | A | 无通道 log.info 文案/实参变体：日志措辞无条款——同上文案先例 | 设计书条款/实证推理（详见说明列） |
| app.notify.triggers.x__dispatch__mutmut_34 | A | 无通道 log.info 文案/实参变体：日志措辞无条款——同上文案先例 | 设计书条款/实证推理（详见说明列） |
| app.notify.triggers.x__dispatch__mutmut_35 | A | not_configured 返回字典键/值/文案变体：同 m15 族判据（诊断镜像键面） | 设计书条款/实证推理（详见说明列） |
| app.notify.triggers.x__dispatch__mutmut_36 | A | not_configured 返回字典键/值/文案变体：同 m15 族判据（诊断镜像键面） | 设计书条款/实证推理（详见说明列） |
| app.notify.triggers.x__dispatch__mutmut_37 | A | not_configured 返回字典键/值/文案变体：同 m15 族判据（诊断镜像键面） | 设计书条款/实证推理（详见说明列） |
| app.notify.triggers.x__dispatch__mutmut_38 | A | not_configured 返回字典键/值/文案变体：同 m15 族判据（诊断镜像键面） | 设计书条款/实证推理（详见说明列） |
| app.notify.triggers.x__dispatch__mutmut_39 | A | not_configured 返回字典键/值/文案变体：同 m15 族判据（诊断镜像键面） | 设计书条款/实证推理（详见说明列） |
| app.notify.triggers.x__dispatch__mutmut_40 | A | not_configured 返回字典键/值/文案变体：同 m15 族判据（诊断镜像键面） | 设计书条款/实证推理（详见说明列） |
| app.notify.triggers.x__dispatch__mutmut_41 | A | not_configured 返回字典键/值/文案变体：同 m15 族判据（诊断镜像键面） | 设计书条款/实证推理（详见说明列） |
| app.notify.triggers.x__dispatch__mutmut_8 | A | 开关关闭 log.info 文案/实参变体（格式化仍合法）：日志措辞无条款、格式化正常完成——批次 3 文案先例 | 设计书条款/实证推理（详见说明列） |
| app.notify.triggers.x__dispatch__mutmut_9 | A | 开关关闭 log.info 文案/实参变体（格式化仍合法）：日志措辞无条款、格式化正常完成——批次 3 文案先例 | 设计书条款/实证推理（详见说明列） |

### app.notify.triggers.x_check_collective_sentinel（15 条）

| 变异体 | 类 | 说明 | 依据 |
|---|---|---|---|
| app.notify.triggers.x_check_collective_sentinel__mutmut_10 | A | no_sources 返回字典键/值/文案变体：返回值汇入轮次 summary 无行为消费方——诊断镜像键面判据（HR m296/297 先例） | 设计书条款/实证推理（详见说明列） |
| app.notify.triggers.x_check_collective_sentinel__mutmut_11 | A | no_sources 返回字典键/值/文案变体：返回值汇入轮次 summary 无行为消费方——诊断镜像键面判据（HR m296/297 先例） | 设计书条款/实证推理（详见说明列） |
| app.notify.triggers.x_check_collective_sentinel__mutmut_12 | A | no_sources 返回字典键/值/文案变体：返回值汇入轮次 summary 无行为消费方——诊断镜像键面判据（HR m296/297 先例） | 设计书条款/实证推理（详见说明列） |
| app.notify.triggers.x_check_collective_sentinel__mutmut_13 | A | no_sources 返回字典键/值/文案变体：返回值汇入轮次 summary 无行为消费方——诊断镜像键面判据（HR m296/297 先例） | 设计书条款/实证推理（详见说明列） |
| app.notify.triggers.x_check_collective_sentinel__mutmut_14 | A | no_sources 返回字典键/值/文案变体：返回值汇入轮次 summary 无行为消费方——诊断镜像键面判据（HR m296/297 先例） | 设计书条款/实证推理（详见说明列） |
| app.notify.triggers.x_check_collective_sentinel__mutmut_15 | A | no_sources 返回字典键/值/文案变体：返回值汇入轮次 summary 无行为消费方——诊断镜像键面判据（HR m296/297 先例） | 设计书条款/实证推理（详见说明列） |
| app.notify.triggers.x_check_collective_sentinel__mutmut_69 | A | 标题文案 XX 包裹/前缀大写：事件名「采集面整体降级」仍在位、标题整体措辞无条款——文案先例（钉名断言为子串在位非全文精确） | 设计书条款/实证推理（详见说明列） |
| app.notify.triggers.x_check_collective_sentinel__mutmut_70 | A | 标题文案 XX 包裹/前缀大写：事件名「采集面整体降级」仍在位、标题整体措辞无条款——文案先例（钉名断言为子串在位非全文精确） | 设计书条款/实证推理（详见说明列） |
| app.notify.triggers.x_check_collective_sentinel__mutmut_71 | A | 正文时间戳 datetime.now(None) naive：正文展示用途、形态无条款——datetime.now(None) 族先例 | 设计书条款/实证推理（详见说明列） |
| app.notify.triggers.x_check_collective_sentinel__mutmut_78 | A | 恢复清零存 None：None/0 同 falsy，后续读取 int(None or 0) 恒等——存储值 falsy 等价判据 | 设计书条款/实证推理（详见说明列） |
| app.notify.triggers.x_check_collective_sentinel__mutmut_86 | A | healthy 返回字典 reason 键/值变体：诊断文案无消费方——诊断镜像键面判据（同 m9 族；sent 布尔已另判 C） | 设计书条款/实证推理（详见说明列） |
| app.notify.triggers.x_check_collective_sentinel__mutmut_87 | A | healthy 返回字典 reason 键/值变体：诊断文案无消费方——诊断镜像键面判据（同 m9 族；sent 布尔已另判 C） | 设计书条款/实证推理（详见说明列） |
| app.notify.triggers.x_check_collective_sentinel__mutmut_88 | A | healthy 返回字典 reason 键/值变体：诊断文案无消费方——诊断镜像键面判据（同 m9 族；sent 布尔已另判 C） | 设计书条款/实证推理（详见说明列） |
| app.notify.triggers.x_check_collective_sentinel__mutmut_89 | A | healthy 返回字典 reason 键/值变体：诊断文案无消费方——诊断镜像键面判据（同 m9 族；sent 布尔已另判 C） | 设计书条款/实证推理（详见说明列） |
| app.notify.triggers.x_check_collective_sentinel__mutmut_9 | A | no_sources 返回字典键/值/文案变体：返回值汇入轮次 summary 无行为消费方——诊断镜像键面判据（HR m296/297 先例） | 设计书条款/实证推理（详见说明列） |

### app.notify.triggers.x_check_disk_usage（13 条）

| 变异体 | 类 | 说明 | 依据 |
|---|---|---|---|
| app.notify.triggers.x_check_disk_usage__mutmut_2 | A | 盘符/路径回退变体：conftest/生产库路径恒绝对（DEFAULTS 形态核查+venv 实测 absolute 同盘同值），回退域（内存库/相对路径）两形态等价或不可达 | 设计书条款/实证推理（详见说明列） |
| app.notify.triggers.x_check_disk_usage__mutmut_27 | A | 代码内缺省回退破坏/变体：siteconfig DEFAULTS 实证 disk_usage_warn_percent=80 恒回退，raw is None 域不可达——防御缺省不可达族（DEFAULTS 核查） | 设计书条款/实证推理（详见说明列） |
| app.notify.triggers.x_check_disk_usage__mutmut_29 | A | 代码内缺省回退破坏/变体：siteconfig DEFAULTS 实证 disk_usage_warn_percent=80 恒回退，raw is None 域不可达——防御缺省不可达族（DEFAULTS 核查） | 设计书条款/实证推理（详见说明列） |
| app.notify.triggers.x_check_disk_usage__mutmut_3 | A | 盘符/路径回退变体：conftest/生产库路径恒绝对（DEFAULTS 形态核查+venv 实测 absolute 同盘同值），回退域（内存库/相对路径）两形态等价或不可达 | 设计书条款/实证推理（详见说明列） |
| app.notify.triggers.x_check_disk_usage__mutmut_35 | A | below_threshold 返回字典 reason 键/值变体：诊断文案无消费方——诊断镜像键面判据（HR m296/297 先例；sent 布尔已另判 C） | 设计书条款/实证推理（详见说明列） |
| app.notify.triggers.x_check_disk_usage__mutmut_36 | A | below_threshold 返回字典 reason 键/值变体：诊断文案无消费方——诊断镜像键面判据（HR m296/297 先例；sent 布尔已另判 C） | 设计书条款/实证推理（详见说明列） |
| app.notify.triggers.x_check_disk_usage__mutmut_37 | A | below_threshold 返回字典 reason 键/值变体：诊断文案无消费方——诊断镜像键面判据（HR m296/297 先例；sent 布尔已另判 C） | 设计书条款/实证推理（详见说明列） |
| app.notify.triggers.x_check_disk_usage__mutmut_38 | A | below_threshold 返回字典 reason 键/值变体：诊断文案无消费方——诊断镜像键面判据（HR m296/297 先例；sent 布尔已另判 C） | 设计书条款/实证推理（详见说明列） |
| app.notify.triggers.x_check_disk_usage__mutmut_6 | A | 盘符/路径回退变体：conftest/生产库路径恒绝对（DEFAULTS 形态核查+venv 实测 absolute 同盘同值），回退域（内存库/相对路径）两形态等价或不可达 | 设计书条款/实证推理（详见说明列） |
| app.notify.triggers.x_check_disk_usage__mutmut_60 | A | 正文剩余 MB 计算变体（整除→浮点/除数变体）：正文诊断文案细节无条款——文案先例（HR m228 族） | 设计书条款/实证推理（详见说明列） |
| app.notify.triggers.x_check_disk_usage__mutmut_61 | A | 正文剩余 MB 计算变体（整除→浮点/除数变体）：正文诊断文案细节无条款——文案先例（HR m228 族） | 设计书条款/实证推理（详见说明列） |
| app.notify.triggers.x_check_disk_usage__mutmut_62 | A | 正文剩余 MB 计算变体（整除→浮点/除数变体）：正文诊断文案细节无条款——文案先例（HR m228 族） | 设计书条款/实证推理（详见说明列） |
| app.notify.triggers.x_check_disk_usage__mutmut_63 | A | 正文剩余 MB 计算变体（整除→浮点/除数变体）：正文诊断文案细节无条款——文案先例（HR m228 族） | 设计书条款/实证推理（详见说明列） |

### app.notify.triggers.x_notify_source_failure（26 条）

| 变异体 | 类 | 说明 | 依据 |
|---|---|---|---|
| app.notify.triggers.x_notify_source_failure__mutmut_10 | A | 非失效态返回字典键/值/文案变体：level 防御分支（调用点恒传两级态）+返回值无消费方——诊断镜像+防御域判据 | 设计书条款/实证推理（详见说明列） |
| app.notify.triggers.x_notify_source_failure__mutmut_11 | A | 非失效态返回字典键/值/文案变体：level 防御分支（调用点恒传两级态）+返回值无消费方——诊断镜像+防御域判据 | 设计书条款/实证推理（详见说明列） |
| app.notify.triggers.x_notify_source_failure__mutmut_12 | A | 非失效态返回字典键/值/文案变体：level 防御分支（调用点恒传两级态）+返回值无消费方——诊断镜像+防御域判据 | 设计书条款/实证推理（详见说明列） |
| app.notify.triggers.x_notify_source_failure__mutmut_23 | A | 正文 label 文案/条件变体：通知正文措辞无条款——文案先例（批次 3/HR m228 族） | 设计书条款/实证推理（详见说明列） |
| app.notify.triggers.x_notify_source_failure__mutmut_24 | A | 正文 label 文案/条件变体：通知正文措辞无条款——文案先例（批次 3/HR m228 族） | 设计书条款/实证推理（详见说明列） |
| app.notify.triggers.x_notify_source_failure__mutmut_25 | A | 正文 label 文案/条件变体：通知正文措辞无条款——文案先例（批次 3/HR m228 族） | 设计书条款/实证推理（详见说明列） |
| app.notify.triggers.x_notify_source_failure__mutmut_26 | A | 正文 label 文案/条件变体：通知正文措辞无条款——文案先例（批次 3/HR m228 族） | 设计书条款/实证推理（详见说明列） |
| app.notify.triggers.x_notify_source_failure__mutmut_27 | A | 正文 label 文案/条件变体：通知正文措辞无条款——文案先例（批次 3/HR m228 族） | 设计书条款/实证推理（详见说明列） |
| app.notify.triggers.x_notify_source_failure__mutmut_28 | A | 正文 label 文案/条件变体：通知正文措辞无条款——文案先例（批次 3/HR m228 族） | 设计书条款/实证推理（详见说明列） |
| app.notify.triggers.x_notify_source_failure__mutmut_29 | A | 正文 label 文案/条件变体：通知正文措辞无条款——文案先例（批次 3/HR m228 族） | 设计书条款/实证推理（详见说明列） |
| app.notify.triggers.x_notify_source_failure__mutmut_30 | A | 正文 label 文案/条件变体：通知正文措辞无条款——文案先例（批次 3/HR m228 族） | 设计书条款/实证推理（详见说明列） |
| app.notify.triggers.x_notify_source_failure__mutmut_32 | A | 标题内状态词条件/文案变体：标题整体措辞无条款——文案先例 | 设计书条款/实证推理（详见说明列） |
| app.notify.triggers.x_notify_source_failure__mutmut_33 | A | 标题内状态词条件/文案变体：标题整体措辞无条款——文案先例 | 设计书条款/实证推理（详见说明列） |
| app.notify.triggers.x_notify_source_failure__mutmut_34 | A | 标题内状态词条件/文案变体：标题整体措辞无条款——文案先例 | 设计书条款/实证推理（详见说明列） |
| app.notify.triggers.x_notify_source_failure__mutmut_35 | A | 标题内状态词条件/文案变体：标题整体措辞无条款——文案先例 | 设计书条款/实证推理（详见说明列） |
| app.notify.triggers.x_notify_source_failure__mutmut_36 | A | 标题内状态词条件/文案变体：标题整体措辞无条款——文案先例 | 设计书条款/实证推理（详见说明列） |
| app.notify.triggers.x_notify_source_failure__mutmut_37 | A | 标题内状态词条件/文案变体：标题整体措辞无条款——文案先例 | 设计书条款/实证推理（详见说明列） |
| app.notify.triggers.x_notify_source_failure__mutmut_38 | A | 标题内状态词条件/文案变体：标题整体措辞无条款——文案先例 | 设计书条款/实证推理（详见说明列） |
| app.notify.triggers.x_notify_source_failure__mutmut_39 | A | URL 截断界 [:80]→[:81]：截断界数值无条款——batch2 m42/批次 10 先例族 | 设计书条款/实证推理（详见说明列） |
| app.notify.triggers.x_notify_source_failure__mutmut_54 | A | 正文最近错误回退/文案变体：正文诊断细节无条款——文案先例 | 设计书条款/实证推理（详见说明列） |
| app.notify.triggers.x_notify_source_failure__mutmut_55 | A | 正文最近错误回退/文案变体：正文诊断细节无条款——文案先例 | 设计书条款/实证推理（详见说明列） |
| app.notify.triggers.x_notify_source_failure__mutmut_56 | A | 正文时间戳 datetime.now(None) naive：正文展示形态无条款——datetime.now(None) 族 | 设计书条款/实证推理（详见说明列） |
| app.notify.triggers.x_notify_source_failure__mutmut_6 | A | 非失效态返回字典键/值/文案变体：level 防御分支（调用点恒传两级态）+返回值无消费方——诊断镜像+防御域判据 | 设计书条款/实证推理（详见说明列） |
| app.notify.triggers.x_notify_source_failure__mutmut_7 | A | 非失效态返回字典键/值/文案变体：level 防御分支（调用点恒传两级态）+返回值无消费方——诊断镜像+防御域判据 | 设计书条款/实证推理（详见说明列） |
| app.notify.triggers.x_notify_source_failure__mutmut_8 | A | 非失效态返回字典键/值/文案变体：level 防御分支（调用点恒传两级态）+返回值无消费方——诊断镜像+防御域判据 | 设计书条款/实证推理（详见说明列） |
| app.notify.triggers.x_notify_source_failure__mutmut_9 | A | 非失效态返回字典键/值/文案变体：level 防御分支（调用点恒传两级态）+返回值无消费方——诊断镜像+防御域判据 | 设计书条款/实证推理（详见说明列） |

### app.notify.triggers.x_notify_usage_reconcile_deviation（1 条）

| 变异体 | 类 | 说明 | 依据 |
|---|---|---|---|
| app.notify.triggers.x_notify_usage_reconcile_deviation__mutmut_17 | A | 正文时间戳 datetime.now(None) naive：正文展示形态无条款——datetime.now(None) 族 | 设计书条款/实证推理（详见说明列） |

### app.notify.x_get_notifier（1 条）

| 变异体 | 类 | 说明 | 依据 |
|---|---|---|---|
| app.notify.x_get_notifier__mutmut_4 | A | 未注册名返回 None→恒实例化：调用点核查——default_notifier 取注册表键、routes/get 测试恒传已注册名，未知名域生产不可达（record_usage 缺省先例族） | 设计书条款/实证推理（详见说明列） |

### app.notify.xǁNotifierǁ_recently_sent（4 条）

| 变异体 | 类 | 说明 | 依据 |
|---|---|---|---|
| app.notify.xǁNotifierǁ_recently_sent__mutmut_15 | A | 损坏时间戳（非 ISO）兜底 True：差异域=手工损坏 site_config 时间戳——去重时间戳唯一写入口 _record_sent 恒写 aware ISO（实证），损坏域正常运行不可达 | 设计书条款/实证推理（详见说明列） |
| app.notify.xǁNotifierǁ_recently_sent__mutmut_16 | A | tzinfo 判定取反：aware 时间戳（唯一写入形态）上 replace(tzinfo=utc) 恒等no-op；naive 差异域不可达——同上判据 | 设计书条款/实证推理（详见说明列） |
| app.notify.xǁNotifierǁ_recently_sent__mutmut_17 | A | naive 归一分支体破坏（last=None / tzinfo=None）：仅 naive 时间戳触达——写入形态恒 aware，分支域不可达（同上判据） | 设计书条款/实证推理（详见说明列） |
| app.notify.xǁNotifierǁ_recently_sent__mutmut_18 | A | naive 归一分支体破坏（last=None / tzinfo=None）：仅 naive 时间戳触达——写入形态恒 aware，分支域不可达（同上判据） | 设计书条款/实证推理（详见说明列） |

### app.notify.xǁNotifierǁsend（18 条）

| 变异体 | 类 | 说明 | 依据 |
|---|---|---|---|
| app.notify.xǁNotifierǁsend__mutmut_14 | A | 未配置分支 log.info 文案/实参变体：日志措辞无条款、格式化异常 logging 自吞——批次 3 m3-m9 文案先例 | 设计书条款/实证推理（详见说明列） |
| app.notify.xǁNotifierǁsend__mutmut_30 | A | 去重命中分支 log.info 文案/实参变体：同上判据 | 设计书条款/实证推理（详见说明列） |
| app.notify.xǁNotifierǁsend__mutmut_31 | A | 去重命中分支 log.info 文案/实参变体：同上判据 | 设计书条款/实证推理（详见说明列） |
| app.notify.xǁNotifierǁsend__mutmut_35 | A | 去重命中分支 log.info 文案/实参变体：同上判据 | 设计书条款/实证推理（详见说明列） |
| app.notify.xǁNotifierǁsend__mutmut_49 | A | 投递失败 WARN 日志文案/实参变体：D12 未钉该行业务文案（错误语义已由返回值 deliver_failed 承载）——批次 3 文案先例 | 设计书条款/实证推理（详见说明列） |
| app.notify.xǁNotifierǁsend__mutmut_5 | A | 未配置分支 log.info 文案/实参变体：日志措辞无条款、格式化异常 logging 自吞——批次 3 m3-m9 文案先例 | 设计书条款/实证推理（详见说明列） |
| app.notify.xǁNotifierǁsend__mutmut_50 | A | 投递失败 WARN 日志文案/实参变体：D12 未钉该行业务文案（错误语义已由返回值 deliver_failed 承载）——批次 3 文案先例 | 设计书条款/实证推理（详见说明列） |
| app.notify.xǁNotifierǁsend__mutmut_51 | A | 投递失败 WARN 日志文案/实参变体：D12 未钉该行业务文案（错误语义已由返回值 deliver_failed 承载）——批次 3 文案先例 | 设计书条款/实证推理（详见说明列） |
| app.notify.xǁNotifierǁsend__mutmut_56 | A | 投递失败 WARN 日志文案/实参变体：D12 未钉该行业务文案（错误语义已由返回值 deliver_failed 承载）——批次 3 文案先例 | 设计书条款/实证推理（详见说明列） |
| app.notify.xǁNotifierǁsend__mutmut_58 | A | 投递失败 WARN 日志文案/实参变体：D12 未钉该行业务文案（错误语义已由返回值 deliver_failed 承载）——批次 3 文案先例 | 设计书条款/实证推理（详见说明列） |
| app.notify.xǁNotifierǁsend__mutmut_6 | A | 未配置分支 log.info 文案/实参变体：日志措辞无条款、格式化异常 logging 自吞——批次 3 m3-m9 文案先例 | 设计书条款/实证推理（详见说明列） |
| app.notify.xǁNotifierǁsend__mutmut_7 | A | 未配置分支 log.info 文案/实参变体：日志措辞无条款、格式化异常 logging 自吞——批次 3 m3-m9 文案先例 | 设计书条款/实证推理（详见说明列） |
| app.notify.xǁNotifierǁsend__mutmut_73 | A | 已发送 log.info 文案/实参变体：同上判据 | 设计书条款/实证推理（详见说明列） |
| app.notify.xǁNotifierǁsend__mutmut_74 | A | 已发送 log.info 文案/实参变体：同上判据 | 设计书条款/实证推理（详见说明列） |
| app.notify.xǁNotifierǁsend__mutmut_75 | A | 已发送 log.info 文案/实参变体：同上判据 | 设计书条款/实证推理（详见说明列） |
| app.notify.xǁNotifierǁsend__mutmut_76 | A | 已发送 log.info 文案/实参变体：同上判据 | 设计书条款/实证推理（详见说明列） |
| app.notify.xǁNotifierǁsend__mutmut_8 | A | 未配置分支 log.info 文案/实参变体：日志措辞无条款、格式化异常 logging 自吞——批次 3 m3-m9 文案先例 | 设计书条款/实证推理（详见说明列） |
| app.notify.xǁNotifierǁsend__mutmut_82 | A | 已发送 log.info 文案/实参变体：同上判据 | 设计书条款/实证推理（详见说明列） |

## C3-2 分诊批次 2（2026-10-07，可观测/日志/时区/备份族 212 条）：A 83 条

> 种子 212 = C 124（补测杀灭：tests/test_observability_meters.py 等 7 文件）+ A 83（本节）+ D 5（呈统筹，不在本清单：日切时钟取值形态/astimezone 时区标签形态未落条款）。B 0。核验-改判循环：C 逐条施加必杀、A 逐条施加必活至零意外（doc/C3/C3-2-核验结果.json；ENV_WHITELIST 2 条为平台差异白名单，详见汇报偏离记录）。

### x__aware（3 条）

| 变异体 | 类 | 说明 | 依据 |
|---|---|---|---|
| app.timeline.x__aware__mutmut_1 | A | _aware 归一分支变体：aware-UTC 域 replace(tzinfo=utc) 恒等 no-op、naive 域调用点核查不可达（四消费点恒传 aware UTC 或 None→now(utc)）——恰等价/不可达域（C3-1 _recently_sent m16-18 判例） | 设计书条款/实证推理（详见说明列） |
| app.timeline.x__aware__mutmut_2 | A | _aware 归一分支变体：aware-UTC 域 replace(tzinfo=utc) 恒等 no-op、naive 域调用点核查不可达（四消费点恒传 aware UTC 或 None→now(utc)）——恰等价/不可达域（C3-1 _recently_sent m16-18 判例） | 设计书条款/实证推理（详见说明列） |
| app.timeline.x__aware__mutmut_3 | A | _aware 归一分支变体：aware-UTC 域 replace(tzinfo=utc) 恒等 no-op、naive 域调用点核查不可达（四消费点恒传 aware UTC 或 None→now(utc)）——恰等价/不可达域（C3-1 _recently_sent m16-18 判例） | 设计书条款/实证推理（详见说明列） |

### x__db_size_mb（5 条）

| 变异体 | 类 | 说明 | 依据 |
|---|---|---|---|
| app.observability.x__db_size_mb__mutmut_5 | A | PRAGMA 关键字大小写变体：SQLite pragma 大小写不敏感——恰等价 | 设计书条款/实证推理（详见说明列） |
| app.observability.x__db_size_mb__mutmut_6 | A | PRAGMA 关键字大小写变体：SQLite pragma 大小写不敏感——恰等价 | 设计书条款/实证推理（详见说明列） |
| app.observability.x__db_size_mb__mutmut_11 | A | PRAGMA 关键字大小写变体：SQLite pragma 大小写不敏感——恰等价 | 设计书条款/实证推理（详见说明列） |
| app.observability.x__db_size_mb__mutmut_12 | A | PRAGMA 关键字大小写变体：SQLite pragma 大小写不敏感——恰等价 | 设计书条款/实证推理（详见说明列） |
| app.observability.x__db_size_mb__mutmut_13 | A | or→and：差异域=page_count=0 且 page_size>0 组合（真实 SQLite page_size 恒>0），该域计算结果同为 0.0——恰等价 | 设计书条款/实证推理（详见说明列） |

### x__db_writable（2 条）

| 变异体 | 类 | 说明 | 依据 |
|---|---|---|---|
| app.observability.x__db_writable__mutmut_3 | A | BEGIN IMMEDIATE/ROLLBACK 关键字小写：SQLite 关键字大小写不敏感——恰等价 | 设计书条款/实证推理（详见说明列） |
| app.observability.x__db_writable__mutmut_6 | A | BEGIN IMMEDIATE/ROLLBACK 关键字小写：SQLite 关键字大小写不敏感——恰等价 | 设计书条款/实证推理（详见说明列） |

### x__degraded_levels（7 条）

| 变异体 | 类 | 说明 | 依据 |
|---|---|---|---|
| app.observability.x__degraded_levels__mutmut_21 | A | query(None).count()：渲染 SELECT count(*) FROM (SELECT NULL … WHERE …) 行数语义（venv echo 实证），attempted/done 仅作 >0 与 ==0 判定——与 query(id).count() 恰等价 | 设计书条款/实证推理（详见说明列） |
| app.observability.x__degraded_levels__mutmut_24 | A | attempted 状态元组去 DONE（XX/小写）：degraded 条件=attempted>0 且 done==0；去 DONE 后 attempted=FAILED 计数，FAILED>0⟺attempted>0 恒成立——恰等价（恒等式推演） | 设计书条款/实证推理（详见说明列） |
| app.observability.x__degraded_levels__mutmut_25 | A | attempted 状态元组去 DONE（XX/小写）：degraded 条件=attempted>0 且 done==0；去 DONE 后 attempted=FAILED 计数，FAILED>0⟺attempted>0 恒成立——恰等价（恒等式推演） | 设计书条款/实证推理（详见说明列） |
| app.observability.x__degraded_levels__mutmut_28 | A | attempted/done 窗 >=→>：恰 24h 边界含等性无条款钉死（任务书仅钉 90 分钟宽限与 pending 500 两边界；窗口主体语义由 m4 族承载）——自定边界域 | 设计书条款/实证推理（详见说明列） |
| app.observability.x__degraded_levels__mutmut_37 | A | attempted/done 窗 >=→>：恰 24h 边界含等性无条款钉死（任务书仅钉 90 分钟宽限与 pending 500 两边界；窗口主体语义由 m4 族承载）——自定边界域 | 设计书条款/实证推理（详见说明列） |
| app.observability.x__degraded_levels__mutmut_38 | A | query(None).count()：渲染 SELECT count(*) FROM (SELECT NULL … WHERE …) 行数语义（venv echo 实证），attempted/done 仅作 >0 与 ==0 判定——与 query(id).count() 恰等价 | 设计书条款/实证推理（详见说明列） |
| app.observability.x__degraded_levels__mutmut_43 | A | attempted/done 窗 >=→>：恰 24h 边界含等性无条款钉死（任务书仅钉 90 分钟宽限与 pending 500 两边界；窗口主体语义由 m4 族承载）——自定边界域 | 设计书条款/实证推理（详见说明列） |

### x__disk_free_mb（1 条）

| 变异体 | 类 | 说明 | 依据 |
|---|---|---|---|
| app.observability.x__disk_free_mb__mutmut_3 | A | 回退 "."→"XX.XX"：差异域=url.database 为空的引擎（生产恒文件路径），回退域生产不可达——防御缺省不可达族（C3-1 磁盘路径回退 m2/3/6 判例） | 设计书条款/实证推理（详见说明列） |

### x__ensure_parent（1 条）

| 变异体 | 类 | 说明 | 依据 |
|---|---|---|---|
| app.logging_setup.x__ensure_parent__mutmut_1 | A | parent=None 跳过 makedirs：差异域=日志父目录缺失，可达域（tmp_path/部署路径）父目录恒存在；父目录自创建健壮性无条款——防御域等价 | 设计书条款/实证推理（详见说明列） |

### x__llm_error_rate_24h（5 条）

| 变异体 | 类 | 说明 | 依据 |
|---|---|---|---|
| app.observability.x__llm_error_rate_24h__mutmut_9 | A | count(None)：带 filter 的 query(func.count(None)) 渲染 SELECT count(*) FROM … WHERE … 行数语义（venv echo 实证——初判 EXISTS 系裸查询无 FROM 常量形态误读），id 恒非 NULL 与 count(id) 恰等价 | 设计书条款/实证推理（详见说明列） |
| app.observability.x__llm_error_rate_24h__mutmut_10 | A | total/errors 窗 >=→>：恰 24h 边界含等性无条款钉死——自定边界域（同 degraded m28 判据） | 设计书条款/实证推理（详见说明列） |
| app.observability.x__llm_error_rate_24h__mutmut_11 | A | total or 0→or 1：total=0 时 errors 亦必为 0（同窗子集），0/1=0.0 恒等——恰等价 | 设计书条款/实证推理（详见说明列） |
| app.observability.x__llm_error_rate_24h__mutmut_21 | A | count(None)：带 filter 的 query(func.count(None)) 渲染 SELECT count(*) FROM … WHERE … 行数语义（venv echo 实证——初判 EXISTS 系裸查询无 FROM 常量形态误读），id 恒非 NULL 与 count(id) 恰等价 | 设计书条款/实证推理（详见说明列） |
| app.observability.x__llm_error_rate_24h__mutmut_22 | A | total/errors 窗 >=→>：恰 24h 边界含等性无条款钉死——自定边界域（同 degraded m28 判据） | 设计书条款/实证推理（详见说明列） |

### x__minutes_ago（1 条）

| 变异体 | 类 | 说明 | 依据 |
|---|---|---|---|
| app.observability.x__minutes_ago__mutmut_15 | A | max 下界 0→1：1s/60<0.05 舍入后恒 0.0 与原形全同（负值域/亚秒域均同）——恰等价 | 设计书条款/实证推理（详见说明列） |

### x_get_backup_target（1 条）

| 变异体 | 类 | 说明 | 依据 |
|---|---|---|---|
| app.backup.x_get_backup_target__mutmut_4 | A | or True 使未知名恒实例化（None(db) 崩溃）：调用点核查——default_backup_target 取注册表键、测试恒传已注册名，未知名域生产不可达——C3-1 get_notifier m4 判例 | 设计书条款/实证推理（详见说明列） |

### x_health_payload（5 条）

| 变异体 | 类 | 说明 | 依据 |
|---|---|---|---|
| app.observability.x_health_payload__mutmut_4 | A | _db_writable(None)：实现忽略形参（取 _current_engine 动态 engine）——恰等价 | 设计书条款/实证推理（详见说明列） |
| app.observability.x_health_payload__mutmut_31 | A | pending count(None)：带 filter 渲染 SELECT count(*) 行数语义（venv echo 实证），id 恒非 NULL 与 count(id) 恰等价——同 llm m9 判据 | 设计书条款/实证推理（详见说明列） |
| app.observability.x_health_payload__mutmut_71 | A | _disk_free_mb(None)：实现忽略形参——恰等价 | 设计书条款/实证推理（详见说明列） |
| app.observability.x_health_payload__mutmut_95 | A | 缺省阈值 90→91/500→501：siteconfig DEFAULTS 实证 healthz_fetch_stale_minutes=90/healthz_pending_stale_count=500 恒回退，or 分支不可达（DEFAULTS 判例+任务书缺省键回退自定） | 设计书条款/实证推理（详见说明列） |
| app.observability.x_health_payload__mutmut_112 | A | 缺省阈值 90→91/500→501：siteconfig DEFAULTS 实证 healthz_fetch_stale_minutes=90/healthz_pending_stale_count=500 恒回退，or 分支不可达（DEFAULTS 判例+任务书缺省键回退自定） | 设计书条款/实证推理（详见说明列） |

### x_pipeline_stats_payload（14 条）

| 变异体 | 类 | 说明 | 依据 |
|---|---|---|---|
| app.observability.x_pipeline_stats_payload__mutmut_11 | A | pending count(None)：带 filter 渲染 SELECT count(*) 行数语义（venv echo 实证），id 恒非 NULL 与 count(id) 恰等价——同 llm m9 判据 | 设计书条款/实证推理（详见说明列） |
| app.observability.x_pipeline_stats_payload__mutmut_32 | A | stale count(None)：带 filter 渲染 SELECT count(*) 行数语义（venv echo 实证），id 恒非 NULL 与 count(id) 恰等价——同 llm m9 判据 | 设计书条款/实证推理（详见说明列） |
| app.observability.x_pipeline_stats_payload__mutmut_38 | A | like "STALE_RECLAIM:%"：SQLite LIKE ASCII 大小写不敏感（venv 实证）——恰等价（HTTP 头名不敏感先例族） | 设计书条款/实证推理（详见说明列） |
| app.observability.x_pipeline_stats_payload__mutmut_39 | A | stale 窗 >=→>：自定边界域（同 degraded m28 判据） | 设计书条款/实证推理（详见说明列） |
| app.observability.x_pipeline_stats_payload__mutmut_41 | A | per_source 初值 None 化：紧随其后的整体再赋值使初值为死赋值——恰等价 | 设计书条款/实证推理（详见说明列） |
| app.observability.x_pipeline_stats_payload__mutmut_46 | A | rows kind 过滤删除：DONE score/write payload 无 source_id 键（runner.py:627 实证score payload 仅 direction_id/prompt_version），sid 不命中 per_source——调用点核查等价 | 设计书条款/实证推理（详见说明列） |
| app.observability.x_pipeline_stats_payload__mutmut_70 | A | updated_at None 守卫破坏：updated_at 恒有 default=utcnow（模型实证），None 域生产不可达——防御域不可达（C3-1 损坏时间戳判例） | 设计书条款/实证推理（详见说明列） |
| app.observability.x_pipeline_stats_payload__mutmut_88 | A | items/scored/passed count(None)：带 filter 渲染 SELECT count(*) 行数语义（venv echo 实证），id 恒非 NULL 与 count(id) 恰等价——同 llm m9 判据 | 设计书条款/实证推理（详见说明列） |
| app.observability.x_pipeline_stats_payload__mutmut_89 | A | items/scored/passed 窗 >=→>：自定边界域（同 degraded m28 判据） | 设计书条款/实证推理（详见说明列） |
| app.observability.x_pipeline_stats_payload__mutmut_98 | A | items/scored/passed count(None)：带 filter 渲染 SELECT count(*) 行数语义（venv echo 实证），id 恒非 NULL 与 count(id) 恰等价——同 llm m9 判据 | 设计书条款/实证推理（详见说明列） |
| app.observability.x_pipeline_stats_payload__mutmut_99 | A | items/scored/passed 窗 >=→>：自定边界域（同 degraded m28 判据） | 设计书条款/实证推理（详见说明列） |
| app.observability.x_pipeline_stats_payload__mutmut_113 | A | items/scored/passed count(None)：带 filter 渲染 SELECT count(*) 行数语义（venv echo 实证），id 恒非 NULL 与 count(id) 恰等价——同 llm m9 判据 | 设计书条款/实证推理（详见说明列） |
| app.observability.x_pipeline_stats_payload__mutmut_114 | A | items/scored/passed 窗 >=→>：自定边界域（同 degraded m28 判据） | 设计书条款/实证推理（详见说明列） |
| app.observability.x_pipeline_stats_payload__mutmut_154 | A | _disk_free_mb(None)：实现忽略形参——恰等价 | 设计书条款/实证推理（详见说明列） |

### x_resolve_zone（3 条）

| 变异体 | 类 | 说明 | 依据 |
|---|---|---|---|
| app.timeline.x_resolve_zone__mutmut_6 | A | WARN 文案实参化/XX 包裹：格式化均合法、caplog 断言（非法名 in message 子串在位）仍命中——文案先例族 | 设计书条款/实证推理（详见说明列） |
| app.timeline.x_resolve_zone__mutmut_8 | A | WARN 文案实参化/XX 包裹：格式化均合法、caplog 断言（非法名 in message 子串在位）仍命中——文案先例族 | 设计书条款/实证推理（详见说明列） |
| app.timeline.x_resolve_zone__mutmut_9 | A | WARN 文案 "utc" 小写：回退目标仍是 _FALLBACK_ZONE(UTC)、文案措辞无条款——文案先例 | 设计书条款/实证推理（详见说明列） |

### x_rotate_backups（5 条）

| 变异体 | 类 | 说明 | 依据 |
|---|---|---|---|
| app.backup.x_rotate_backups__mutmut_10 | A | len>keep 守卫 or True/>→>=：切片语义 files[:-keep] 在 len<=keep 时恒空，守卫冗余——恰等价（venv 可推演） | 设计书条款/实证推理（详见说明列） |
| app.backup.x_rotate_backups__mutmut_12 | A | len>keep 守卫 or True/>→>=：切片语义 files[:-keep] 在 len<=keep 时恒空，守卫冗余——恰等价（venv 可推演） | 设计书条款/实证推理（详见说明列） |
| app.backup.x_rotate_backups__mutmut_13 | A | missing_ok=None/False：falsy 等价；差异域=列出后消失的竞态域，可达域文件恒存在——防御域等价 | 设计书条款/实证推理（详见说明列） |
| app.backup.x_rotate_backups__mutmut_14 | A | missing_ok=None/False：falsy 等价；差异域=列出后消失的竞态域，可达域文件恒存在——防御域等价 | 设计书条款/实证推理（详见说明列） |
| app.backup.x_rotate_backups__mutmut_15 | A | removed.append(None)：返回列表元素无消费方（run_backup 仅 len() 计数）——诊断镜像键面判据（C3-1 reason 键面先例） | 设计书条款/实证推理（详见说明列） |

### x_setup_logging（14 条）

| 变异体 | 类 | 说明 | 依据 |
|---|---|---|---|
| app.logging_setup.x_setup_logging__mutmut_5 | A | force_console 判定 and False 恒走 env 路径：生产/测试无 force_console=False 调用点（grep 实证），force=None/True 域两形态等价——调用点核查先例 | 设计书条款/实证推理（详见说明列） |
| app.logging_setup.x_setup_logging__mutmut_9 | A | console 开关键/取值域变体（键 XX/小写、元组项 XX/大写、lower→upper）：关闭开关取值域仅模块文档串自赋、无设计条款——自定开关域（大小写细节先例族） | 设计书条款/实证推理（详见说明列） |
| app.logging_setup.x_setup_logging__mutmut_14 | A | console 开关键/取值域变体（键 XX/小写、元组项 XX/大写、lower→upper）：关闭开关取值域仅模块文档串自赋、无设计条款——自定开关域（大小写细节先例族） | 设计书条款/实证推理（详见说明列） |
| app.logging_setup.x_setup_logging__mutmut_15 | A | console 开关键/取值域变体（键 XX/小写、元组项 XX/大写、lower→upper）：关闭开关取值域仅模块文档串自赋、无设计条款——自定开关域（大小写细节先例族） | 设计书条款/实证推理（详见说明列） |
| app.logging_setup.x_setup_logging__mutmut_16 | A | 缺省 "1"→"XX1XX"：两者均不在关闭元组内、env 未设域行为恒等——恰等价 | 设计书条款/实证推理（详见说明列） |
| app.logging_setup.x_setup_logging__mutmut_18 | A | console 开关键/取值域变体（键 XX/小写、元组项 XX/大写、lower→upper）：关闭开关取值域仅模块文档串自赋、无设计条款——自定开关域（大小写细节先例族） | 设计书条款/实证推理（详见说明列） |
| app.logging_setup.x_setup_logging__mutmut_19 | A | console 开关键/取值域变体（键 XX/小写、元组项 XX/大写、lower→upper）：关闭开关取值域仅模块文档串自赋、无设计条款——自定开关域（大小写细节先例族） | 设计书条款/实证推理（详见说明列） |
| app.logging_setup.x_setup_logging__mutmut_20 | A | console 开关键/取值域变体（键 XX/小写、元组项 XX/大写、lower→upper）：关闭开关取值域仅模块文档串自赋、无设计条款——自定开关域（大小写细节先例族） | 设计书条款/实证推理（详见说明列） |
| app.logging_setup.x_setup_logging__mutmut_21 | A | console 开关键/取值域变体（键 XX/小写、元组项 XX/大写、lower→upper）：关闭开关取值域仅模块文档串自赋、无设计条款——自定开关域（大小写细节先例族） | 设计书条款/实证推理（详见说明列） |
| app.logging_setup.x_setup_logging__mutmut_22 | A | console 开关键/取值域变体（键 XX/小写、元组项 XX/大写、lower→upper）：关闭开关取值域仅模块文档串自赋、无设计条款——自定开关域（大小写细节先例族） | 设计书条款/实证推理（详见说明列） |
| app.logging_setup.x_setup_logging__mutmut_24 | A | StreamHandler(None)：stream 缺省即 sys.stderr——恰等价；本机重定向 stdio 的测试夹具形态差异属施加面伪差——ENV_WHITELIST | 设计书条款/实证推理（详见说明列） |
| app.logging_setup.x_setup_logging__mutmut_39 | A | 文件 handler encoding=None/删除：部署平台（Linux）缺省即 UTF-8 两形态等价（本机venv 实测 preferred encoding=utf-8 全同）——平台等价 | 设计书条款/实证推理（详见说明列） |
| app.logging_setup.x_setup_logging__mutmut_43 | A | 文件 handler encoding=None/删除：部署平台（Linux）缺省即 UTF-8 两形态等价（本机venv 实测 preferred encoding=utf-8 全同）——平台等价 | 设计书条款/实证推理（详见说明列） |
| app.logging_setup.x_setup_logging__mutmut_45 | A | encoding "utf-8"→"UTF-8"：Python 编码名归一化——恰等价 | 设计书条款/实证推理（详见说明列） |

### x_teardown_logging（1 条）

| 变异体 | 类 | 说明 | 依据 |
|---|---|---|---|
| app.logging_setup.x_teardown_logging__mutmut_1 | A | removeHandler(None)：root handler 清理卫生面无条款（close/_installed 清空仍执行，残留 closed handler 不再合法输出）——内部卫生域等价 | 设计书条款/实证推理（详见说明列） |

### xǁLocalDirectoryBackupǁrun_backup（15 条）

| 变异体 | 类 | 说明 | 依据 |
|---|---|---|---|
| app.backup.localdir.xǁLocalDirectoryBackupǁrun_backup__mutmut_11 | A | backup_dir 缺省回退变体：siteconfig DEFAULTS 实证 backup_dir="backups" 恒回退，or 分支不可达——DEFAULTS 核查判例族（C3-1 disk m27/29 同判） | 设计书条款/实证推理（详见说明列） |
| app.backup.localdir.xǁLocalDirectoryBackupǁrun_backup__mutmut_12 | A | backup_dir 缺省回退变体：siteconfig DEFAULTS 实证 backup_dir="backups" 恒回退，or 分支不可达——DEFAULTS 核查判例族（C3-1 disk m27/29 同判） | 设计书条款/实证推理（详见说明列） |
| app.backup.localdir.xǁLocalDirectoryBackupǁrun_backup__mutmut_13 | A | mkdir parents 形参变体（None/缺省/False 均 falsy 等价）：差异域=父目录缺失的嵌套创建健壮性，可达域（tmp_path/生产 CWD）父目录恒存在——防御域等价，无条款 | 设计书条款/实证推理（详见说明列） |
| app.backup.localdir.xǁLocalDirectoryBackupǁrun_backup__mutmut_15 | A | mkdir parents 形参变体（None/缺省/False 均 falsy 等价）：差异域=父目录缺失的嵌套创建健壮性，可达域（tmp_path/生产 CWD）父目录恒存在——防御域等价，无条款 | 设计书条款/实证推理（详见说明列） |
| app.backup.localdir.xǁLocalDirectoryBackupǁrun_backup__mutmut_17 | A | mkdir parents 形参变体（None/缺省/False 均 falsy 等价）：差异域=父目录缺失的嵌套创建健壮性，可达域（tmp_path/生产 CWD）父目录恒存在——防御域等价，无条款 | 设计书条款/实证推理（详见说明列） |
| app.backup.localdir.xǁLocalDirectoryBackupǁrun_backup__mutmut_22 | A | 文件名时间戳形态变体（XX 包裹/纳秒模数 1000001）：文件名形态无条款，轮转按修改时间 glob 前缀不依赖名字典序（F2 追认形态；同秒内尾缀仍单调） | 设计书条款/实证推理（详见说明列） |
| app.backup.localdir.xǁLocalDirectoryBackupǁrun_backup__mutmut_23 | A | 文件名小写指示符变体（%y%h%m%s）：Linux CI/生产平台（glibc）指示符合法、文件名形态无条款；Windows 本机 strftime 拒绝 %s（venv 实测 ValueError）属平台差异假阳性——ENV_WHITELIST | 设计书条款/实证推理（详见说明列） |
| app.backup.localdir.xǁLocalDirectoryBackupǁrun_backup__mutmut_26 | A | 文件名时间戳形态变体（XX 包裹/纳秒模数 1000001）：文件名形态无条款，轮转按修改时间 glob 前缀不依赖名字典序（F2 追认形态；同秒内尾缀仍单调） | 设计书条款/实证推理（详见说明列） |
| app.backup.localdir.xǁLocalDirectoryBackupǁrun_backup__mutmut_39 | A | 轮转/完成日志文案与实参变体（格式化均合法）：日志措辞无条款——文案先例族（C3-1 批次 3 m3-m9 同判） | 设计书条款/实证推理（详见说明列） |
| app.backup.localdir.xǁLocalDirectoryBackupǁrun_backup__mutmut_40 | A | 日志占位符缺实参：logging 对空实参静默跳过格式化（LogRecord.getMessage 的 if self.args 门——venv 实证 getMessage 不抛、占位符字面残留），属消息文本失真无条款——文案先例族（非 C3-1「格式错误零容忍」域：该域=非空实参下 format 抛错） | 设计书条款/实证推理（详见说明列） |
| app.backup.localdir.xǁLocalDirectoryBackupǁrun_backup__mutmut_41 | A | 轮转/完成日志文案与实参变体（格式化均合法）：日志措辞无条款——文案先例族（C3-1 批次 3 m3-m9 同判） | 设计书条款/实证推理（详见说明列） |
| app.backup.localdir.xǁLocalDirectoryBackupǁrun_backup__mutmut_44 | A | 轮转/完成日志文案与实参变体（格式化均合法）：日志措辞无条款——文案先例族（C3-1 批次 3 m3-m9 同判） | 设计书条款/实证推理（详见说明列） |
| app.backup.localdir.xǁLocalDirectoryBackupǁrun_backup__mutmut_45 | A | 轮转/完成日志文案与实参变体（格式化均合法）：日志措辞无条款——文案先例族（C3-1 批次 3 m3-m9 同判） | 设计书条款/实证推理（详见说明列） |
| app.backup.localdir.xǁLocalDirectoryBackupǁrun_backup__mutmut_46 | A | 日志占位符缺实参：logging 对空实参静默跳过格式化（LogRecord.getMessage 的 if self.args 门——venv 实证 getMessage 不抛、占位符字面残留），属消息文本失真无条款——文案先例族（非 C3-1「格式错误零容忍」域：该域=非空实参下 format 抛错） | 设计书条款/实证推理（详见说明列） |
| app.backup.localdir.xǁLocalDirectoryBackupǁrun_backup__mutmut_47 | A | 轮转/完成日志文案与实参变体（格式化均合法）：日志措辞无条款——文案先例族（C3-1 批次 3 m3-m9 同判） | 设计书条款/实证推理（详见说明列） |

## C3-3 分诊批次 3（2026-10-07，API 守卫与管线调度族 310 + suspicious 首案 14）：A 209 + B 1 = 210 条

> 种子=统一 dispatch run 37474801690 幸存者之 api.routes 81 + pipeline.runner 147 +
> pipeline.budget 14 + scheduler 68（doc/C3/C3-3-种子.txt）+ suspicious 首案 14
> （api.deps.require_session m18-m29 + providers.base.LLMProvider._call m157/158）。
> diff 经 mutmut 3.8.0 库级静态重建（app/ 自 890a345 零变化），逐条施加→跑判据面
> 测试→还原定案。终态：**C 103/103 全杀**（tests/test_month_range_window.py 等 11 文件
> 28 测试 + 既有面）**、A 210/210 全活、B 1 存活（B 不杀）**、D 10 条出问题清单
> （见 doc/C3/C3-3-执行Agent工作汇报.md §四）。核验-改判四轮（C 轮 99→17 意外→改判
> 11 A+修测杀 4+1 改判；C 轮 2 87/87 零意外；A 轮 226→20 意外→16 改判 C+4 测试弱化；
> R2 复验 20/20）：313/313 零意外（C 必杀/A 必活；D 不施加）。新判例：m135/136 id 键=
> 注入对象辨识承载（C）、m149/153 值 None 化=检查调用整体跳过（C，非面板值域）、
> job id 变体=可寻址标识契约（C，test_score_schedule 先例）、query(None).filter()
> .first() 行存在性等价（A）、DEFAULTS 恒回退致 or 分支不可达（A）、diff 概览行文本
> 双匹配陷阱（变异行位必查 body 行号）。数据：doc/C3/C3-3-重建-diff.json、
> C3-3-核验结果.json、C3-3-核验.py（定案表）。
### 本节统计
A 210 条 + B 1 条（suspicious 定案 m18 = 批次 1 在册条目保留，不重复登记）

#### app.api.routes.x__inject_explore_items（A 27）

| mutant 全名 | 类别 | 一句话理由 | 依据条款或推理 |
|---|---|---|---|
| app.api.routes.x__inject_explore_items__mutmut_2 | A | meta 初始键/值变体：enabled 键紧随被 params 覆写、inserted 由注入路径计数，初始死赋值差异——初值吸收（C3-2 per_source m41 判例） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.api.routes.x__inject_explore_items__mutmut_3 | A | meta 初始键/值变体：enabled 键紧随被 params 覆写、inserted 由注入路径计数，初始死赋值差异——初值吸收（C3-2 per_source m41 判例） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.api.routes.x__inject_explore_items__mutmut_4 | A | meta enabled False→True 初始：同上被覆写吸收——死赋值 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.api.routes.x__inject_explore_items__mutmut_27 | A | WARN 消息 None：logging None 消息+空 args 合法格式化（venv 实证），文案域 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.api.routes.x__inject_explore_items__mutmut_28 | A | getLogger(None) 返回 root logger（venv 实证），warning 照常输出——日志器名域 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.api.routes.x__inject_explore_items__mutmut_29 | A | 日志器名/文案 XX/大小写变体：格式化合法、无断言条款——文案先例族 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.api.routes.x__inject_explore_items__mutmut_30 | A | 日志器名/文案 XX/大小写变体：格式化合法、无断言条款——文案先例族 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.api.routes.x__inject_explore_items__mutmut_31 | A | 日志器名/文案 XX/大小写变体：格式化合法、无断言条款——文案先例族 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.api.routes.x__inject_explore_items__mutmut_32 | A | 日志器名/文案 XX/大小写变体：格式化合法、无断言条款——文案先例族 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.api.routes.x__inject_explore_items__mutmut_33 | A | 日志器名/文案 XX/大小写变体：格式化合法、无断言条款——文案先例族 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.api.routes.x__inject_explore_items__mutmut_40 | A | not mv or mv==none → and 化：差异域内 rows 恒空/提前 return 两形态 meta 全同（inserted=0、enabled 已覆写）——恰等价 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.api.routes.x__inject_explore_items__mutmut_49 | A | none 字符串 XX/NONE：差异域=模型键恰为 none 时走空查询 vs 提前 return，两形态 meta 全同——恰等价（域内 rows 恒空） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.api.routes.x__inject_explore_items__mutmut_50 | A | none 字符串 XX/NONE：差异域=模型键恰为 none 时走空查询 vs 提前 return，两形态 meta 全同——恰等价（域内 rows 恒空） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.api.routes.x__inject_explore_items__mutmut_64 | A | join ItemVec onclause None/省略：单 FK 回退推断等价（C2-1 join 判据族） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.api.routes.x__inject_explore_items__mutmut_66 | A | join ItemVec onclause None/省略：单 FK 回退推断等价（C2-1 join 判据族） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.api.routes.x__inject_explore_items__mutmut_68 | A | join ScoreResult onclause None/省略：单 FK（item_id）回退推断等价——同上 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.api.routes.x__inject_explore_items__mutmut_70 | A | join ScoreResult onclause None/省略：单 FK（item_id）回退推断等价——同上 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.api.routes.x__inject_explore_items__mutmut_139 | A | 注入条目键变体（title/url/band/reason/source_id）：条目契约钉 flag=explore+真实分数（relevance/quality 断言在位）+id（辨识注入对象），该五键无断言——键面无断言先例 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.api.routes.x__inject_explore_items__mutmut_140 | A | 注入条目键变体（title/url/band/reason/source_id）：条目契约钉 flag=explore+真实分数（relevance/quality 断言在位）+id（辨识注入对象），该五键无断言——键面无断言先例 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.api.routes.x__inject_explore_items__mutmut_143 | A | 注入条目键变体（title/url/band/reason/source_id）：条目契约钉 flag=explore+真实分数（relevance/quality 断言在位）+id（辨识注入对象），该五键无断言——键面无断言先例 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.api.routes.x__inject_explore_items__mutmut_144 | A | 注入条目键变体（title/url/band/reason/source_id）：条目契约钉 flag=explore+真实分数（relevance/quality 断言在位）+id（辨识注入对象），该五键无断言——键面无断言先例 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.api.routes.x__inject_explore_items__mutmut_155 | A | 注入条目键变体（title/url/band/reason/source_id）：条目契约钉 flag=explore+真实分数（relevance/quality 断言在位）+id（辨识注入对象），该五键无断言——键面无断言先例 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.api.routes.x__inject_explore_items__mutmut_156 | A | 注入条目键变体（title/url/band/reason/source_id）：条目契约钉 flag=explore+真实分数（relevance/quality 断言在位）+id（辨识注入对象），该五键无断言——键面无断言先例 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.api.routes.x__inject_explore_items__mutmut_159 | A | 注入条目键变体（title/url/band/reason/source_id）：条目契约钉 flag=explore+真实分数（relevance/quality 断言在位）+id（辨识注入对象），该五键无断言——键面无断言先例 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.api.routes.x__inject_explore_items__mutmut_160 | A | 注入条目键变体（title/url/band/reason/source_id）：条目契约钉 flag=explore+真实分数（relevance/quality 断言在位）+id（辨识注入对象），该五键无断言——键面无断言先例 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.api.routes.x__inject_explore_items__mutmut_163 | A | 注入条目键变体（title/url/band/reason/source_id）：条目契约钉 flag=explore+真实分数（relevance/quality 断言在位）+id（辨识注入对象），该五键无断言——键面无断言先例 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.api.routes.x__inject_explore_items__mutmut_164 | A | 注入条目键变体（title/url/band/reason/source_id）：条目契约钉 flag=explore+真实分数（relevance/quality 断言在位）+id（辨识注入对象），该五键无断言——键面无断言先例 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |

#### app.api.routes.x__month_range（A 11）

| mutant 全名 | 类别 | 一句话理由 | 依据条款或推理 |
|---|---|---|---|
| app.api.routes.x__month_range__mutmut_8 | A | tzinfo None/缺参：SQLite DATETIME 绑定渲染不含 tz（strftime 无 %z），naive 与 aware UTC 渲染同串——恰等价（实现形态） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.api.routes.x__month_range__mutmut_12 | A | tzinfo None/缺参：SQLite DATETIME 绑定渲染不含 tz（strftime 无 %z），naive 与 aware UTC 渲染同串——恰等价（实现形态） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.api.routes.x__month_range__mutmut_23 | A | mon 上界 <=13：13 月放行后 start 行（try 内）datetime(2026,13,1) 先抛 ValueError 被 except 捕获返回 None——守卫上界冗余，恰等价（施加实证；核验 C 轮实锤改判 A——try 兜底判据族） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.api.routes.x__month_range__mutmut_43 | A | tzinfo None/缺参：SQLite DATETIME 绑定渲染不含 tz（strftime 无 %z），naive 与 aware UTC 渲染同串——恰等价（实现形态） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.api.routes.x__month_range__mutmut_47 | A | tzinfo None/缺参：SQLite DATETIME 绑定渲染不含 tz（strftime 无 %z），naive 与 aware UTC 渲染同串——恰等价（实现形态） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |

#### app.api.routes.x__unscored_entries（A 14）

| mutant 全名 | 类别 | 一句话理由 | 依据条款或推理 |
|---|---|---|---|
| app.api.routes.x__unscored_entries__mutmut_5 | A | 窗宽 24→25h：窗口数字未落条款（AC-21.1 仅说「近期」）——自定窗口域 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.api.routes.x__unscored_entries__mutmut_13 | A | query(None)：venv 实证 filter 照常渲染、命中行返回 (None,) 元组非 None——first() is not None 的行存在性判定与 query(id) 恰等价（count(None) 行数判例的 first 版；核验 C 轮实锤改判） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.api.routes.x__unscored_entries__mutmut_20 | A | 窗 >=→>：恰 24h 边界含等性无条款——自定边界域（C3-2 degraded m28 判例） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.api.routes.x__unscored_entries__mutmut_59 | A | 附带条目键/值变体（title/url/flag 键、unscored 值）：断言面=id+note==「暂未评分」（AC-21.1 钉标注语），其余键无断言——键面无断言先例族 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.api.routes.x__unscored_entries__mutmut_60 | A | 附带条目键/值变体（title/url/flag 键、unscored 值）：断言面=id+note==「暂未评分」（AC-21.1 钉标注语），其余键无断言——键面无断言先例族 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.api.routes.x__unscored_entries__mutmut_61 | A | 附带条目键/值变体（title/url/flag 键、unscored 值）：断言面=id+note==「暂未评分」（AC-21.1 钉标注语），其余键无断言——键面无断言先例族 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.api.routes.x__unscored_entries__mutmut_62 | A | 附带条目键/值变体（title/url/flag 键、unscored 值）：断言面=id+note==「暂未评分」（AC-21.1 钉标注语），其余键无断言——键面无断言先例族 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.api.routes.x__unscored_entries__mutmut_63 | A | 附带条目键/值变体（title/url/flag 键、unscored 值）：断言面=id+note==「暂未评分」（AC-21.1 钉标注语），其余键无断言——键面无断言先例族 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.api.routes.x__unscored_entries__mutmut_64 | A | 附带条目键/值变体（title/url/flag 键、unscored 值）：断言面=id+note==「暂未评分」（AC-21.1 钉标注语），其余键无断言——键面无断言先例族 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.api.routes.x__unscored_entries__mutmut_65 | A | 附带条目键/值变体（title/url/flag 键、unscored 值）：断言面=id+note==「暂未评分」（AC-21.1 钉标注语），其余键无断言——键面无断言先例族 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.api.routes.x__unscored_entries__mutmut_66 | A | 附带条目键/值变体（title/url/flag 键、unscored 值）：断言面=id+note==「暂未评分」（AC-21.1 钉标注语），其余键无断言——键面无断言先例族 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.api.routes.x__unscored_entries__mutmut_70 | A | limit 10→None/11、order_by None：附带上限与顺序无条款（自定上限；顺序无断言面——C2-1 fingerprint order_by 判据族） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.api.routes.x__unscored_entries__mutmut_71 | A | limit 10→None/11、order_by None：附带上限与顺序无条款（自定上限；顺序无断言面——C2-1 fingerprint order_by 判据族） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.api.routes.x__unscored_entries__mutmut_72 | A | limit 10→None/11、order_by None：附带上限与顺序无条款（自定上限；顺序无断言面——C2-1 fingerprint order_by 判据族） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |

#### app.api.deps.x_require_session（A 1）

| mutant 全名 | 类别 | 一句话理由 | 依据条款或推理 |
|---|---|---|---|

#### app.pipeline.runner.x__execute_write_task（A 19）

| mutant 全名 | 类别 | 一句话理由 | 依据条款或推理 |
|---|---|---|---|
| app.pipeline.runner.x__execute_write_task__mutmut_12 | A | or "manual"→XX/MANUAL：创建路径 payload 恒带 triggered_by（routes 恒 api、write_task 恒传参），缺省分支不可达——缺省不可达族 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.pipeline.runner.x__execute_write_task__mutmut_13 | A | or "manual"→XX/MANUAL：创建路径 payload 恒带 triggered_by（routes 恒 api、write_task 恒传参），缺省分支不可达——缺省不可达族 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.pipeline.runner.x__execute_write_task__mutmut_21 | A | run_kwargs 排除键变体：write_task 生产调用点（仅测试）不带额外 kwargs，排除键失效域=透传域且 run_write **kw 吸收——调用点核查等价 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.pipeline.runner.x__execute_write_task__mutmut_22 | A | run_kwargs 排除键变体：write_task 生产调用点（仅测试）不带额外 kwargs，排除键失效域=透传域且 run_write **kw 吸收——调用点核查等价 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.pipeline.runner.x__execute_write_task__mutmut_25 | A | run_kwargs 排除键变体：write_task 生产调用点（仅测试）不带额外 kwargs，排除键失效域=透传域且 run_write **kw 吸收——调用点核查等价 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.pipeline.runner.x__execute_write_task__mutmut_26 | A | run_kwargs 排除键变体：write_task 生产调用点（仅测试）不带额外 kwargs，排除键失效域=透传域且 run_write **kw 吸收——调用点核查等价 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.pipeline.runner.x__execute_write_task__mutmut_62 | A | 预算确认 note 键/文案变体：note=人读提示字段，无断言/契约面（钉的是 executed/budget_confirmation_required 两键，已在位）——诊断镜像键面先例 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.pipeline.runner.x__execute_write_task__mutmut_63 | A | 预算确认 note 键/文案变体：note=人读提示字段，无断言/契约面（钉的是 executed/budget_confirmation_required 两键，已在位）——诊断镜像键面先例 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.pipeline.runner.x__execute_write_task__mutmut_64 | A | 预算确认 note 键/文案变体：note=人读提示字段，无断言/契约面（钉的是 executed/budget_confirmation_required 两键，已在位）——诊断镜像键面先例 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.pipeline.runner.x__execute_write_task__mutmut_65 | A | 预算确认 note 键/文案变体：note=人读提示字段，无断言/契约面（钉的是 executed/budget_confirmation_required 两键，已在位）——诊断镜像键面先例 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.pipeline.runner.x__execute_write_task__mutmut_66 | A | 预算确认 note 键/文案变体：note=人读提示字段，无断言/契约面（钉的是 executed/budget_confirmation_required 两键，已在位）——诊断镜像键面先例 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.pipeline.runner.x__execute_write_task__mutmut_74 | A | **run_kwargs 删除：生产调用点不带额外 kwargs（调用点核查），差异域不可达 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.pipeline.runner.x__execute_write_task__mutmut_115 | A | payload decision 键变体（核验 C 轮行位实锤：变异位=decision 而非 write_run_id，后者断言在位不受影响）：decision 镜像键无断言面——键面无断言先例 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.pipeline.runner.x__execute_write_task__mutmut_116 | A | decision/article_id 键变体：payload 镜像键无断言面（消费方 tasks 端点人读） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.pipeline.runner.x__execute_write_task__mutmut_117 | A | decision/article_id 键变体：payload 镜像键无断言面（消费方 tasks 端点人读） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.pipeline.runner.x__execute_write_task__mutmut_118 | A | decision/article_id 键变体：payload 镜像键无断言面（消费方 tasks 端点人读） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.pipeline.runner.x__execute_write_task__mutmut_128 | A | error 条件 or True：OK 域 run.error 恒 None（写作管线 OK 不设 error），两形态同传 None——恰等价（调用点核查） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.pipeline.runner.x__execute_write_task__mutmut_130 | A | error 行 OK 字符串变体（核验 C 轮行位实锤：变异位=error 实参三元而非 status 三元）：run.status 恒!=XXOKXX/ok → error=run.error 恒传，OK 域 run.error 恒 None 与原 else None 同值——恰等价（调用点核查：status=OK ⟹ error=None） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.pipeline.runner.x__execute_write_task__mutmut_131 | A | error 行 OK 字符串变体（核验 C 轮行位实锤：变异位=error 实参三元而非 status 三元）：run.status 恒!=XXOKXX/ok → error=run.error 恒传，OK 域 run.error 恒 None 与原 else None 同值——恰等价（调用点核查：status=OK ⟹ error=None） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |

#### app.pipeline.runner.x__finish（A 4）

| mutant 全名 | 类别 | 一句话理由 | 依据条款或推理 |
|---|---|---|---|
| app.pipeline.runner.x__finish__mutmut_53 | A | WARN 实参 None 化：格式化合法（test_reclaim 断言子串「迟到完成被拒」仍在）——文案值域 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.pipeline.runner.x__finish__mutmut_54 | A | WARN 实参 None 化：格式化合法（test_reclaim 断言子串「迟到完成被拒」仍在）——文案值域 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.pipeline.runner.x__finish__mutmut_58 | A | WARN 文案 XX/小写：子串断言仍命中——文案先例族（C2-1 enqueue m47 组判据：WARNING 级格式破坏才是杀面，文案值变体不是） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.pipeline.runner.x__finish__mutmut_59 | A | WARN 文案 XX/小写：子串断言仍命中——文案先例族（C2-1 enqueue m47 组判据：WARNING 级格式破坏才是杀面，文案值变体不是） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |

#### app.pipeline.runner.x__route_candidates（A 32）

| mutant 全名 | 类别 | 一句话理由 | 依据条款或推理 |
|---|---|---|---|
| app.pipeline.runner.x__route_candidates__mutmut_2 | A | 预算闸回退 stats 键/值变体：budget_embed_paused/embed_disabled 键不在变异位（test_budget_2 断言在位），routed_hits/misses 面板值无契约——键面无断言先例 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.pipeline.runner.x__route_candidates__mutmut_3 | A | 预算闸回退 stats 键/值变体：budget_embed_paused/embed_disabled 键不在变异位（test_budget_2 断言在位），routed_hits/misses 面板值无契约——键面无断言先例 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.pipeline.runner.x__route_candidates__mutmut_4 | A | 预算闸回退 stats 键/值变体：budget_embed_paused/embed_disabled 键不在变异位（test_budget_2 断言在位），routed_hits/misses 面板值无契约——键面无断言先例 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.pipeline.runner.x__route_candidates__mutmut_5 | A | 预算闸回退 stats 键/值变体：budget_embed_paused/embed_disabled 键不在变异位（test_budget_2 断言在位），routed_hits/misses 面板值无契约——键面无断言先例 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.pipeline.runner.x__route_candidates__mutmut_6 | A | 预算闸回退 stats 键/值变体：budget_embed_paused/embed_disabled 键不在变异位（test_budget_2 断言在位），routed_hits/misses 面板值无契约——键面无断言先例 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.pipeline.runner.x__route_candidates__mutmut_18 | A | 空候选回退 stats 键/值变体：空域无断言面（score_round 空 direction stats 未钉）——面板键值域 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.pipeline.runner.x__route_candidates__mutmut_19 | A | 空候选回退 stats 键/值变体：空域无断言面（score_round 空 direction stats 未钉）——面板键值域 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.pipeline.runner.x__route_candidates__mutmut_20 | A | 空候选回退 stats 键/值变体：空域无断言面（score_round 空 direction stats 未钉）——面板键值域 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.pipeline.runner.x__route_candidates__mutmut_21 | A | 空候选回退 stats 键/值变体：空域无断言面（score_round 空 direction stats 未钉）——面板键值域 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.pipeline.runner.x__route_candidates__mutmut_22 | A | 空候选回退 stats 键/值变体：空域无断言面（score_round 空 direction stats 未钉）——面板键值域 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.pipeline.runner.x__route_candidates__mutmut_23 | A | 空候选回退 stats 键/值变体：空域无断言面（score_round 空 direction stats 未钉）——面板键值域 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.pipeline.runner.x__route_candidates__mutmut_24 | A | 空候选回退 stats 键/值变体：空域无断言面（score_round 空 direction stats 未钉）——面板键值域 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.pipeline.runner.x__route_candidates__mutmut_25 | A | 空候选回退 stats 键/值变体：空域无断言面（score_round 空 direction stats 未钉）——面板键值域 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.pipeline.runner.x__route_candidates__mutmut_26 | A | 空候选回退 stats 键/值变体：空域无断言面（score_round 空 direction stats 未钉）——面板键值域 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.pipeline.runner.x__route_candidates__mutmut_33 | A | not mv or→and：query_ready=False（mv falsy 域 ensure 恒 False）承载同一return——冗余子句恰等价（test_embed_disabled 两形态同走 return） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.pipeline.runner.x__route_candidates__mutmut_34 | A | query_ready and 化：差异域=query 失败+mv 真值——不 return 后 partition(query_vec=None) 仍输出 embed_disabled（partition 内部承载，test 226 行断言）——恰等价（回退形态同构） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.pipeline.runner.x__route_candidates__mutmut_38 | A | none 字符串 XX/NONE：mv==none 域与 not mv/not query_ready 子句重合（ensure 在 none 域恒 False）——冗余子句恰等价 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.pipeline.runner.x__route_candidates__mutmut_39 | A | none 字符串 XX/NONE：mv==none 域与 not mv/not query_ready 子句重合（ensure 在 none 域恒 False）——冗余子句恰等价 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.pipeline.runner.x__route_candidates__mutmut_40 | A | 查询未就绪回退 stats 键/值变体：embed_disabled 断言在位（键不在变异位），routed_hits/misses 面板值无契约——键面无断言先例 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.pipeline.runner.x__route_candidates__mutmut_41 | A | 查询未就绪回退 stats 键/值变体：embed_disabled 断言在位（键不在变异位），routed_hits/misses 面板值无契约——键面无断言先例 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.pipeline.runner.x__route_candidates__mutmut_42 | A | 查询未就绪回退 stats 键/值变体：embed_disabled 断言在位（键不在变异位），routed_hits/misses 面板值无契约——键面无断言先例 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.pipeline.runner.x__route_candidates__mutmut_43 | A | 查询未就绪回退 stats 键/值变体：embed_disabled 断言在位（键不在变异位），routed_hits/misses 面板值无契约——键面无断言先例 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.pipeline.runner.x__route_candidates__mutmut_44 | A | 查询未就绪回退 stats 键/值变体：embed_disabled 断言在位（键不在变异位），routed_hits/misses 面板值无契约——键面无断言先例 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.pipeline.runner.x__route_candidates__mutmut_73 | A | 回退 WARN 文案/实参变体：格式化合法（e 值/文案域）——文案先例族 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.pipeline.runner.x__route_candidates__mutmut_74 | A | 回退 WARN 文案/实参变体：格式化合法（e 值/文案域）——文案先例族 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.pipeline.runner.x__route_candidates__mutmut_75 | A | 回退 WARN 文案/实参变体：格式化合法（e 值/文案域）——文案先例族 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.pipeline.runner.x__route_candidates__mutmut_76 | A | 回退 WARN 文案/实参变体：格式化合法（e 值/文案域）——文案先例族 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.pipeline.runner.x__route_candidates__mutmut_78 | A | embed_fallback 回退 stats 键/值变体：test_query_gen_failure 弱断言（get embed_disabled or embed_fallback），routed_hits/misses 面板值无契约——键面无断言先例 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.pipeline.runner.x__route_candidates__mutmut_79 | A | embed_fallback 回退 stats 键/值变体：test_query_gen_failure 弱断言（get embed_disabled or embed_fallback），routed_hits/misses 面板值无契约——键面无断言先例 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.pipeline.runner.x__route_candidates__mutmut_80 | A | embed_fallback 回退 stats 键/值变体：test_query_gen_failure 弱断言（get embed_disabled or embed_fallback），routed_hits/misses 面板值无契约——键面无断言先例 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.pipeline.runner.x__route_candidates__mutmut_81 | A | embed_fallback 回退 stats 键/值变体：test_query_gen_failure 弱断言（get embed_disabled or embed_fallback），routed_hits/misses 面板值无契约——键面无断言先例 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.pipeline.runner.x__route_candidates__mutmut_82 | A | embed_fallback 回退 stats 键/值变体：test_query_gen_failure 弱断言（get embed_disabled or embed_fallback），routed_hits/misses 面板值无契约——键面无断言先例 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |

#### app.pipeline.runner.x__update_source_health（A 15）

| mutant 全名 | 类别 | 一句话理由 | 依据条款或推理 |
|---|---|---|---|
| app.pipeline.runner.x__update_source_health__mutmut_98 | A | last_error 截断 [:2000]→[:2001]：截断界数值无条款（Text 列——C2-1 m103 同语句判例） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.pipeline.runner.x__update_source_health__mutmut_102 | A | failure_level != XX 变体：已 hard_failed 源重复设置同值+通知重发被 24h 去重吸收，failure_since 重置为时间戳值域——防御幂等域等价 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.pipeline.runner.x__update_source_health__mutmut_119 | A | last_error 截断 [:2000]→[:2001]：截断界数值无条款（Text 列——C2-1 m103 同语句判例） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.pipeline.runner.x__update_source_health__mutmut_122 | A | getattr rate_limited 缺省 False→None/True：stats 恒带该字段（数据类/_error_stats 构造域），缺省不可达——缺省不可达族 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.pipeline.runner.x__update_source_health__mutmut_128 | A | getattr rate_limited 缺省 False→None/True：stats 恒带该字段（数据类/_error_stats 构造域），缺省不可达——缺省不可达族 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.pipeline.runner.x__update_source_health__mutmut_145 | A | getattr retry_after 缺省删：字段恒在（SourceFetchStats 构造域）——同上 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.pipeline.runner.x__update_source_health__mutmut_160 | A | until tzinfo 条件 and False：SQLite 读回 datetime 恒 naive（tzinfo 恒 None），replace 分支本就恒走——恰等价（C3-2 _aware naive 域判例） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.pipeline.runner.x__update_source_health__mutmut_195 | A | 退避 if 段 stats→None（核验 C 轮实锤：段位=递增段非清零段）：本段以 error is not None 为前件，判定域内 429 轮 error 恒 None 前件短路——C2-1 m179 同语句判据族（子句恒真等价） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.pipeline.runner.x__update_source_health__mutmut_197 | A | rate_limited 键/缺省变体（elif/搜索段）：缺省域=stats 缺字段（恒带——不可达）；键变体绕过真值 True 的 429 域仅退避段可达（m195/m201/m202 已承载）——缺省不可达/冗余域 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.pipeline.runner.x__update_source_health__mutmut_201 | A | 退避 if 段 rate_limited 键变体（核验实锤：同 m195 段位）：429 轮 error 恒 None 前件短路，键取值不影响判定——C2-1 m179 判据族 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.pipeline.runner.x__update_source_health__mutmut_202 | A | 退避 if 段 rate_limited 键变体（核验实锤：同 m195 段位）：429 轮 error 恒 None 前件短路，键取值不影响判定——C2-1 m179 判据族 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.pipeline.runner.x__update_source_health__mutmut_215 | A | rate_limited 键/缺省变体（elif/搜索段）：缺省域=stats 缺字段（恒带——不可达）；键变体绕过真值 True 的 429 域仅退避段可达（m195/m201/m202 已承载）——缺省不可达/冗余域 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.pipeline.runner.x__update_source_health__mutmut_240 | A | 搜索段缺省 None：not None 恒 True 但缺省域不可达（字段恒带）——缺省不可达 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.pipeline.runner.x__update_source_health__mutmut_243 | A | rate_limited 键/缺省变体（elif/搜索段）：缺省域=stats 缺字段（恒带——不可达）；键变体绕过真值 True 的 429 域仅退避段可达（m195/m201/m202 已承载）——缺省不可达/冗余域 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.pipeline.runner.x__update_source_health__mutmut_246 | A | rate_limited 键/缺省变体（elif/搜索段）：缺省域=stats 缺字段（恒带——不可达）；键变体绕过真值 True 的 429 域仅退避段可达（m195/m201/m202 已承载）——缺省不可达/冗余域 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |

#### app.pipeline.runner.x_process_fetch_round（A 10）

| mutant 全名 | 类别 | 一句话理由 | 依据条款或推理 |
|---|---|---|---|
| app.pipeline.runner.x_process_fetch_round__mutmut_150 | A | sentinel/disk 键变体：检查仍执行、summary 面板键无消费断言（_tick_fetch 不读，API 响应镜像）——键面无断言先例 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.pipeline.runner.x_process_fetch_round__mutmut_151 | A | sentinel/disk 键变体：检查仍执行、summary 面板键无消费断言（_tick_fetch 不读，API 响应镜像）——键面无断言先例 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.pipeline.runner.x_process_fetch_round__mutmut_154 | A | sentinel/disk 键变体：检查仍执行、summary 面板键无消费断言（_tick_fetch 不读，API 响应镜像）——键面无断言先例 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.pipeline.runner.x_process_fetch_round__mutmut_155 | A | sentinel/disk 键变体：检查仍执行、summary 面板键无消费断言（_tick_fetch 不读，API 响应镜像）——键面无断言先例 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.pipeline.runner.x_process_fetch_round__mutmut_157 | A | 通知异常 WARN 文案/实参变体：格式化合法（含 %S printf 合法指示符）——文案先例族 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.pipeline.runner.x_process_fetch_round__mutmut_158 | A | 通知异常 WARN 文案/实参变体：格式化合法（含 %S printf 合法指示符）——文案先例族 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.pipeline.runner.x_process_fetch_round__mutmut_159 | A | 通知异常 WARN 文案/实参变体：格式化合法（含 %S printf 合法指示符）——文案先例族 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.pipeline.runner.x_process_fetch_round__mutmut_160 | A | 通知异常 WARN 文案/实参变体：格式化合法（含 %S printf 合法指示符）——文案先例族 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.pipeline.runner.x_process_fetch_round__mutmut_161 | A | 通知异常 WARN 文案/实参变体：格式化合法（含 %S printf 合法指示符）——文案先例族 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.pipeline.runner.x_process_fetch_round__mutmut_162 | A | 通知异常 WARN 文案/实参变体：格式化合法（含 %S printf 合法指示符）——文案先例族 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |

#### app.pipeline.runner.x_process_write_tasks（A 1 + B 1）

| mutant 全名 | 类别 | 一句话理由 | 依据条款或推理 |
|---|---|---|---|
| app.pipeline.runner.x_process_write_tasks__mutmut_6 | A | status==PENDING 过滤删除：非 PENDING 任务被 _claim 的 WHERE status=PENDING CAS 复核拒绝——双保险等价（C2-1 m6/batch11 m17 判据族） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.pipeline.runner.x_process_write_tasks__mutmut_19 | B | claim 失败 continue→break：CAS 认领竞争防御分支，单 worker 判定域不可达（ADR-2 单机单进程）——C2-1 m19 B 判据族 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |

#### app.pipeline.runner.x_score_round（A 14）

| mutant 全名 | 类别 | 一句话理由 | 依据条款或推理 |
|---|---|---|---|
| app.pipeline.runner.x_score_round__mutmut_21 | A | 预算通知实参/键变体（used/budget 值）：通知正文值域（C3-1 notify 判例：sent 布尔=C、正文值=A） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.pipeline.runner.x_score_round__mutmut_22 | A | 预算通知实参/键变体（used/budget 值）：通知正文值域（C3-1 notify 判例：sent 布尔=C、正文值=A） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.pipeline.runner.x_score_round__mutmut_28 | A | 预算通知实参/键变体（used/budget 值）：通知正文值域（C3-1 notify 判例：sent 布尔=C、正文值=A） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.pipeline.runner.x_score_round__mutmut_30 | A | 预算通知实参/键变体（used/budget 值）：通知正文值域（C3-1 notify 判例：sent 布尔=C、正文值=A） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.pipeline.runner.x_score_round__mutmut_33 | A | 预算通知实参/键变体（used/budget 值）：通知正文值域（C3-1 notify 判例：sent 布尔=C、正文值=A） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.pipeline.runner.x_score_round__mutmut_52 | A | task.attempts 变体：attempts 数值无条款（C1-9a m34/35 判据族） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.pipeline.runner.x_score_round__mutmut_53 | A | task.attempts 变体：attempts 数值无条款（C1-9a m34/35 判据族） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.pipeline.runner.x_score_round__mutmut_54 | A | task.attempts 变体：attempts 数值无条款（C1-9a m34/35 判据族） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.pipeline.runner.x_score_round__mutmut_115 | A | 单条异常 WARN 文案/实参变体：格式化合法——文案先例族 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.pipeline.runner.x_score_round__mutmut_116 | A | 单条异常 WARN 文案/实参变体：格式化合法——文案先例族 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.pipeline.runner.x_score_round__mutmut_120 | A | 单条异常 WARN 文案/实参变体：格式化合法——文案先例族 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.pipeline.runner.x_score_round__mutmut_146 | A | candidates_total 键变体：stats[candidates] 断言在位（scheduler_rounds m142），total 键无断言——键面无断言先例 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.pipeline.runner.x_score_round__mutmut_147 | A | candidates_total 键变体：stats[candidates] 断言在位（scheduler_rounds m142），total 键无断言——键面无断言先例 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.pipeline.runner.x_score_round__mutmut_174 | A | _error 公式 failed+parse→failed-parse：错误留痕=presence 钉（含解析失败计数），算术细节=诊断文案值域——文案组判据（C2-1 process m50） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |

#### app.pipeline.runner.x_write_task（A 14）

| mutant 全名 | 类别 | 一句话理由 | 依据条款或推理 |
|---|---|---|---|
| app.pipeline.runner.x_write_task__mutmut_1 | A | triggered_by 缺省变体：生产调用点（仅测试，均显式传参）缺省不可达——缺省不可达族 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.pipeline.runner.x_write_task__mutmut_2 | A | triggered_by 缺省变体：生产调用点（仅测试，均显式传参）缺省不可达——缺省不可达族 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.pipeline.runner.x_write_task__mutmut_10 | A | ValueError(None)：异常消息文本无条款（C2-1 m77 文案组判据） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.pipeline.runner.x_write_task__mutmut_27 | A | task.status=RUNNING 变体：_finish 内存同步+后续 commit ORM 回写修复，终态恒 DONE/FAILED（C2-1 fetch_round m26/27 判据族） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.pipeline.runner.x_write_task__mutmut_28 | A | task.status=RUNNING 变体：_finish 内存同步+后续 commit ORM 回写修复，终态恒 DONE/FAILED（C2-1 fetch_round m26/27 判据族） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.pipeline.runner.x_write_task__mutmut_29 | A | task.attempts 变体：attempts 数值无条款——C1-9a 判据族 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.pipeline.runner.x_write_task__mutmut_30 | A | task.attempts 变体：attempts 数值无条款——C1-9a 判据族 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.pipeline.runner.x_write_task__mutmut_31 | A | task.attempts 变体：attempts 数值无条款——C1-9a 判据族 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.pipeline.runner.x_write_task__mutmut_42 | A | 预算确认早返回的 status 键变体（核验 C 轮行位实锤：变异位=早返回而非正常返回，正常路径断言不受影响）：早返回消费面仅 budget_confirmation_required/executed 两键（budget_4 断言在位），status 键无断言——键面无断言先例 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.pipeline.runner.x_write_task__mutmut_43 | A | 预算确认早返回的 status 键变体（核验 C 轮行位实锤：变异位=早返回而非正常返回，正常路径断言不受影响）：早返回消费面仅 budget_confirmation_required/executed 两键（budget_4 断言在位），status 键无断言——键面无断言先例 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.pipeline.runner.x_write_task__mutmut_54 | A | 返回 payload/last_error 键变体：out 镜像键无测试消费（grep 实证零断言）——键面无断言先例 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.pipeline.runner.x_write_task__mutmut_55 | A | 返回 payload/last_error 键变体：out 镜像键无测试消费（grep 实证零断言）——键面无断言先例 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.pipeline.runner.x_write_task__mutmut_56 | A | 返回 payload/last_error 键变体：out 镜像键无测试消费（grep 实证零断言）——键面无断言先例 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.pipeline.runner.x_write_task__mutmut_57 | A | 返回 payload/last_error 键变体：out 镜像键无测试消费（grep 实证零断言）——键面无断言先例 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |

#### app.pipeline.budget.x_score_slow_cap（A 1）

| mutant 全名 | 类别 | 一句话理由 | 依据条款或推理 |
|---|---|---|---|
| app.pipeline.budget.x_score_slow_cap__mutmut_9 | A | 回退 20→21：siteconfig DEFAULTS 实证 score_slow_round_max_items=20 恒回退，or 分支不可达——DEFAULTS 判例族（C3-1 disk m27/29 同判；核验 C 轮实锤改判） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |

#### app.pipeline.budget.x_tokens_used_today（A 5）

| mutant 全名 | 类别 | 一句话理由 | 依据条款或推理 |
|---|---|---|---|
| app.pipeline.budget.x_tokens_used_today__mutmut_10 | A | coalesce 缺省 0→None：列 default=0+调用点恒传 int（record_usage meter.get 域），NULL 行生产不可达——防御缺省不可达族 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.pipeline.budget.x_tokens_used_today__mutmut_13 | A | coalesce 缺省 0→None：列 default=0+调用点恒传 int（record_usage meter.get 域），NULL 行生产不可达——防御缺省不可达族 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.pipeline.budget.x_tokens_used_today__mutmut_15 | A | coalesce 缺省 0→None：列 default=0+调用点恒传 int（record_usage meter.get 域），NULL 行生产不可达——防御缺省不可达族 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.pipeline.budget.x_tokens_used_today__mutmut_18 | A | coalesce 缺省 0→None：列 default=0+调用点恒传 int（record_usage meter.get 域），NULL 行生产不可达——防御缺省不可达族 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.pipeline.budget.x_tokens_used_today__mutmut_19 | A | 日切窗 >=→>：恰 day_start 瞬间归属无条款——自定边界域 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |

#### app.scheduler.x__register_jobs（A 28）

| mutant 全名 | 类别 | 一句话理由 | 依据条款或推理 |
|---|---|---|---|
| app.scheduler.x__register_jobs__mutmut_6 | A | coalesce None/False 变体：APScheduler 行为参数（错过触发合并策略）无设计条款——参数形态域 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.scheduler.x__register_jobs__mutmut_7 | A | next_run_time None/挪位/删除/naive：启动首跑时机无条款（AC-20.1 钉的是运行期间隔，启动即跑仅为代码注释自述）——启动时机自定域 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.scheduler.x__register_jobs__mutmut_12 | A | max_instances/coalesce 参数删除：APScheduler 缺省值即 1/True——恰等价（缺省承载） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.scheduler.x__register_jobs__mutmut_13 | A | next_run_time None/挪位/删除/naive：启动首跑时机无条款（AC-20.1 钉的是运行期间隔，启动即跑仅为代码注释自述）——启动时机自定域 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.scheduler.x__register_jobs__mutmut_14 | A | next_run_time None/挪位/删除/naive：启动首跑时机无条款（AC-20.1 钉的是运行期间隔，启动即跑仅为代码注释自述）——启动时机自定域 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.scheduler.x__register_jobs__mutmut_18 | A | max_instances 1→2：同 kind 重叠防护由 round_busy DB 级防重叠承载（双保险另一翼，G3 裁定③），可观察行为（无重叠）不变——双保险冗余翼等价（C2-1 m17 判据族） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.scheduler.x__register_jobs__mutmut_19 | A | coalesce None/False 变体：APScheduler 行为参数（错过触发合并策略）无设计条款——参数形态域 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.scheduler.x__register_jobs__mutmut_20 | A | next_run_time None/挪位/删除/naive：启动首跑时机无条款（AC-20.1 钉的是运行期间隔，启动即跑仅为代码注释自述）——启动时机自定域 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.scheduler.x__register_jobs__mutmut_26 | A | coalesce None/False 变体：APScheduler 行为参数（错过触发合并策略）无设计条款——参数形态域 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.scheduler.x__register_jobs__mutmut_31 | A | max_instances/coalesce 参数删除：APScheduler 缺省值即 1/True——恰等价（缺省承载） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.scheduler.x__register_jobs__mutmut_32 | A | max_instances/coalesce 参数删除：APScheduler 缺省值即 1/True——恰等价（缺省承载） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.scheduler.x__register_jobs__mutmut_36 | A | max_instances 1→2：同 kind 重叠防护由 round_busy DB 级防重叠承载（双保险另一翼，G3 裁定③），可观察行为（无重叠）不变——双保险冗余翼等价（C2-1 m17 判据族） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.scheduler.x__register_jobs__mutmut_37 | A | coalesce None/False 变体：APScheduler 行为参数（错过触发合并策略）无设计条款——参数形态域 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.scheduler.x__register_jobs__mutmut_43 | A | coalesce None/False 变体：APScheduler 行为参数（错过触发合并策略）无设计条款——参数形态域 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.scheduler.x__register_jobs__mutmut_48 | A | max_instances/coalesce 参数删除：APScheduler 缺省值即 1/True——恰等价（缺省承载） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.scheduler.x__register_jobs__mutmut_49 | A | max_instances/coalesce 参数删除：APScheduler 缺省值即 1/True——恰等价（缺省承载） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.scheduler.x__register_jobs__mutmut_53 | A | max_instances 1→2：同 kind 重叠防护由 round_busy DB 级防重叠承载（双保险另一翼，G3 裁定③），可观察行为（无重叠）不变——双保险冗余翼等价（C2-1 m17 判据族） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.scheduler.x__register_jobs__mutmut_54 | A | coalesce None/False 变体：APScheduler 行为参数（错过触发合并策略）无设计条款——参数形态域 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.scheduler.x__register_jobs__mutmut_60 | A | coalesce None/False 变体：APScheduler 行为参数（错过触发合并策略）无设计条款——参数形态域 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.scheduler.x__register_jobs__mutmut_65 | A | max_instances/coalesce 参数删除：APScheduler 缺省值即 1/True——恰等价（缺省承载） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.scheduler.x__register_jobs__mutmut_66 | A | max_instances/coalesce 参数删除：APScheduler 缺省值即 1/True——恰等价（缺省承载） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.scheduler.x__register_jobs__mutmut_71 | A | max_instances 1→2：同 kind 重叠防护由 round_busy DB 级防重叠承载（双保险另一翼，G3 裁定③），可观察行为（无重叠）不变——双保险冗余翼等价（C2-1 m17 判据族） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.scheduler.x__register_jobs__mutmut_72 | A | coalesce None/False 变体：APScheduler 行为参数（错过触发合并策略）无设计条款——参数形态域 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.scheduler.x__register_jobs__mutmut_78 | A | coalesce None/False 变体：APScheduler 行为参数（错过触发合并策略）无设计条款——参数形态域 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.scheduler.x__register_jobs__mutmut_83 | A | max_instances/coalesce 参数删除：APScheduler 缺省值即 1/True——恰等价（缺省承载） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.scheduler.x__register_jobs__mutmut_84 | A | max_instances/coalesce 参数删除：APScheduler 缺省值即 1/True——恰等价（缺省承载） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.scheduler.x__register_jobs__mutmut_89 | A | max_instances 1→2：同 kind 重叠防护由 round_busy DB 级防重叠承载（双保险另一翼，G3 裁定③），可观察行为（无重叠）不变——双保险冗余翼等价（C2-1 m17 判据族） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.scheduler.x__register_jobs__mutmut_90 | A | coalesce None/False 变体：APScheduler 行为参数（错过触发合并策略）无设计条款——参数形态域 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |

#### app.scheduler.x__tick_backup（A 11）

| mutant 全名 | 类别 | 一句话理由 | 依据条款或推理 |
|---|---|---|---|
| app.scheduler.x__tick_backup__mutmut_4 | A | 跳过分支 info 文案 None/XX：有注册目标的判据域不触达该分支——不可达域 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.scheduler.x__tick_backup__mutmut_5 | A | 跳过分支 info 文案 None/XX：有注册目标的判据域不触达该分支——不可达域 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.scheduler.x__tick_backup__mutmut_7 | A | 完成 log msg=None+args 非空：INFO 级记录在 root WARNING 级下不格式化直接丢弃（logger 层级门），格式错误不可达——C2-1 m47 判据族（核验 C 轮实锤改判 A） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.scheduler.x__tick_backup__mutmut_8 | A | 完成 log 值/文案变体：格式化合法或静默门——文案先例族（C3-2 run_backup m40/46 判例） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.scheduler.x__tick_backup__mutmut_9 | A | 完成 log 值/文案变体：格式化合法或静默门——文案先例族（C3-2 run_backup m40/46 判例） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.scheduler.x__tick_backup__mutmut_10 | A | 完成 log 值/文案变体：格式化合法或静默门——文案先例族（C3-2 run_backup m40/46 判例） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.scheduler.x__tick_backup__mutmut_11 | A | 完成 log 值/文案变体：格式化合法或静默门——文案先例族（C3-2 run_backup m40/46 判例） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.scheduler.x__tick_backup__mutmut_12 | A | 完成 log 值/文案变体：格式化合法或静默门——文案先例族（C3-2 run_backup m40/46 判例） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.scheduler.x__tick_backup__mutmut_14 | A | 异常 WARN traceback 实参 None/删除/文案 XX：格式化合法/静默门/子串断言（备份 in message）仍命中——文案先例族 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.scheduler.x__tick_backup__mutmut_16 | A | 异常 WARN traceback 实参 None/删除/文案 XX：格式化合法/静默门/子串断言（备份 in message）仍命中——文案先例族 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.scheduler.x__tick_backup__mutmut_17 | A | 异常 WARN traceback 实参 None/删除/文案 XX：格式化合法/静默门/子串断言（备份 in message）仍命中——文案先例族 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |

#### app.scheduler.x__tick_score（A 3）

| mutant 全名 | 类别 | 一句话理由 | 依据条款或推理 |
|---|---|---|---|
| app.scheduler.x__tick_score__mutmut_7 | A | 防重叠 info 文案 None/XX/大小写：格式化合法，无断言面——文案先例族 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.scheduler.x__tick_score__mutmut_8 | A | 防重叠 info 文案 None/XX/大小写：格式化合法，无断言面——文案先例族 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.scheduler.x__tick_score__mutmut_9 | A | 防重叠 info 文案 None/XX/大小写：格式化合法，无断言面——文案先例族 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |

> 注：app.api.deps.x_require_session__mutmut_18（suspicious 定案=A 文案域）为批次 1
> 在册条目，保留原登记不重复。生产缺陷呈报：_month_range 12 月分支 year+1 对 str
> 拼接抛 TypeError（12 月对账 500）——12 月契约测试 xfail(strict) 占位（任务书 §0
> 零生产改动铁律），修复后由修复批测试自然杀灭相关 6 条 12 月域变异（已判 A 等价崩）。


## 批次 4：检索与打分族（C3-4，2026-10-07）

> 分诊执行 Agent 依 `doc/C3/C3-4-任务书.md` 出具；C 类 165 条由六个新测试
> 文件杀灭（test_scoring_validate_contract / test_scoring_user_message_context /
> test_retrieval_embedder_guard / test_retrieval_query_gen_contract /
> test_retrieval_router_domain / test_explore_config_and_pick），D 类 8 条呈
> 统筹拍板（见 doc/C3/C3-4-执行Agent工作汇报.md §3），均不在本清单。核验
> 数据：doc/C3/C3-4-核验结果.json（施加必杀/必活循环）。

#### retrieval.embedder.cosine_similarity（余弦相似度）（B 1）

| mutant 全名 | 类别 | 一句话理由 | 依据条款或推理 |
|---|---|---|---|
| app.retrieval.embedder.x_cosine_similarity__mutmut_8 | B | 零向量兜底 0.0→1.0：嵌入护栏保证非零输入（AC-08.5），docstring 明示「仅防御性兜底」——防御分支正常运行不可达；设计书要求护栏存在（B 豁免） | 防御分支豁免（正常运行不可达、设计书要求其存在——任务书 §2 B 判据） |

#### retrieval.embedder.embed_input_text（嵌入输入组装）（A 3）

| mutant 全名 | 类别 | 一句话理由 | 依据条款或推理 |
|---|---|---|---|
| app.retrieval.embedder.x_embed_input_text__mutmut_2 | A | 覆写判定 and False 恒假：limit 恒=config——生产调用恒传 None 恰等价；显式覆写域=测试隔离面（生产调用点核查 ensure_item_vectors 恒透传 None） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.retrieval.embedder.x_embed_input_text__mutmut_7 | A | title or ""→or "XXXX"：item.title 列 NOT NULL default=""（models 实证），None 分支不可达——死码域 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.retrieval.embedder.x_embed_input_text__mutmut_10 | A | content_text or ""→or "XXXX"：content_text 列 NOT NULL default=""（models 实证），None 分支不可达——死码域 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |

#### retrieval.embedder.ensure_item_vectors（批量嵌入补齐）（A 42 + B 1）

| mutant 全名 | 类别 | 一句话理由 | 依据条款或推理 |
|---|---|---|---|
| app.retrieval.embedder.x_ensure_item_vectors__mutmut_4 | A | dims 覆写 and False 恒假：恒=config——生产调用（runner）恒不传 expected_dims，恰等价（生产调用点核查；显式覆写域=测试隔离面） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.retrieval.embedder.x_ensure_item_vectors__mutmut_8 | A | 禁用态早退 stats 键名/值变体：runner 不消费 ensure_item_vectors 返回值、测试仅断言 disabled 键（键不在变异位）、stats 键面无条款——payload.stats 面板域判例（任务书 §2 A 类兜底形态） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.retrieval.embedder.x_ensure_item_vectors__mutmut_9 | A | 禁用态早退 stats 键名/值变体：runner 不消费 ensure_item_vectors 返回值、测试仅断言 disabled 键（键不在变异位）、stats 键面无条款——payload.stats 面板域判例（任务书 §2 A 类兜底形态） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.retrieval.embedder.x_ensure_item_vectors__mutmut_10 | A | 禁用态早退 stats 键名/值变体：runner 不消费 ensure_item_vectors 返回值、测试仅断言 disabled 键（键不在变异位）、stats 键面无条款——payload.stats 面板域判例（任务书 §2 A 类兜底形态） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.retrieval.embedder.x_ensure_item_vectors__mutmut_11 | A | 禁用态早退 stats 键名/值变体：runner 不消费 ensure_item_vectors 返回值、测试仅断言 disabled 键（键不在变异位）、stats 键面无条款——payload.stats 面板域判例（任务书 §2 A 类兜底形态） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.retrieval.embedder.x_ensure_item_vectors__mutmut_12 | A | 禁用态早退 stats 键名/值变体：runner 不消费 ensure_item_vectors 返回值、测试仅断言 disabled 键（键不在变异位）、stats 键面无条款——payload.stats 面板域判例（任务书 §2 A 类兜底形态） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.retrieval.embedder.x_ensure_item_vectors__mutmut_13 | A | 禁用态早退 stats 键名/值变体：runner 不消费 ensure_item_vectors 返回值、测试仅断言 disabled 键（键不在变异位）、stats 键面无条款——payload.stats 面板域判例（任务书 §2 A 类兜底形态） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.retrieval.embedder.x_ensure_item_vectors__mutmut_14 | A | 禁用态早退 stats 键名/值变体：runner 不消费 ensure_item_vectors 返回值、测试仅断言 disabled 键（键不在变异位）、stats 键面无条款——payload.stats 面板域判例（任务书 §2 A 类兜底形态） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.retrieval.embedder.x_ensure_item_vectors__mutmut_15 | A | 禁用态早退 stats 键名/值变体：runner 不消费 ensure_item_vectors 返回值、测试仅断言 disabled 键（键不在变异位）、stats 键面无条款——payload.stats 面板域判例（任务书 §2 A 类兜底形态） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.retrieval.embedder.x_ensure_item_vectors__mutmut_16 | A | 禁用态早退 stats 键名/值变体：runner 不消费 ensure_item_vectors 返回值、测试仅断言 disabled 键（键不在变异位）、stats 键面无条款——payload.stats 面板域判例（任务书 §2 A 类兜底形态） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.retrieval.embedder.x_ensure_item_vectors__mutmut_17 | A | 禁用态早退 stats 键名/值变体：runner 不消费 ensure_item_vectors 返回值、测试仅断言 disabled 键（键不在变异位）、stats 键面无条款——payload.stats 面板域判例（任务书 §2 A 类兜底形态） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.retrieval.embedder.x_ensure_item_vectors__mutmut_18 | A | 禁用态早退 stats 键名/值变体：runner 不消费 ensure_item_vectors 返回值、测试仅断言 disabled 键（键不在变异位）、stats 键面无条款——payload.stats 面板域判例（任务书 §2 A 类兜底形态） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.retrieval.embedder.x_ensure_item_vectors__mutmut_25 | B | provider is None or not items → and 化：差异域=provider None 且 items 非空——embed_enabled 时注册表恒解析出 moark，provider None 不可达；即便触达亦由ADR-6 回退兜住（异常→embed_fallback 全慢速）——防御分支豁免 | 防御分支豁免（正常运行不可达、设计书要求其存在——任务书 §2 B 判据） |
| app.retrieval.embedder.x_ensure_item_vectors__mutmut_28 | A | provider None 短路返回 stats 键名/值变体：同禁用态 stats——runner 不消费返回值、键面无断言（面板域判例；m41 disabled 反转亦在域内） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.retrieval.embedder.x_ensure_item_vectors__mutmut_29 | A | provider None 短路返回 stats 键名/值变体：同禁用态 stats——runner 不消费返回值、键面无断言（面板域判例；m41 disabled 反转亦在域内） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.retrieval.embedder.x_ensure_item_vectors__mutmut_30 | A | provider None 短路返回 stats 键名/值变体：同禁用态 stats——runner 不消费返回值、键面无断言（面板域判例；m41 disabled 反转亦在域内） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.retrieval.embedder.x_ensure_item_vectors__mutmut_31 | A | provider None 短路返回 stats 键名/值变体：同禁用态 stats——runner 不消费返回值、键面无断言（面板域判例；m41 disabled 反转亦在域内） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.retrieval.embedder.x_ensure_item_vectors__mutmut_32 | A | provider None 短路返回 stats 键名/值变体：同禁用态 stats——runner 不消费返回值、键面无断言（面板域判例；m41 disabled 反转亦在域内） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.retrieval.embedder.x_ensure_item_vectors__mutmut_33 | A | provider None 短路返回 stats 键名/值变体：同禁用态 stats——runner 不消费返回值、键面无断言（面板域判例；m41 disabled 反转亦在域内） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.retrieval.embedder.x_ensure_item_vectors__mutmut_34 | A | provider None 短路返回 stats 键名/值变体：同禁用态 stats——runner 不消费返回值、键面无断言（面板域判例；m41 disabled 反转亦在域内） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.retrieval.embedder.x_ensure_item_vectors__mutmut_35 | A | provider None 短路返回 stats 键名/值变体：同禁用态 stats——runner 不消费返回值、键面无断言（面板域判例；m41 disabled 反转亦在域内） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.retrieval.embedder.x_ensure_item_vectors__mutmut_36 | A | provider None 短路返回 stats 键名/值变体：同禁用态 stats——runner 不消费返回值、键面无断言（面板域判例；m41 disabled 反转亦在域内） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.retrieval.embedder.x_ensure_item_vectors__mutmut_37 | A | provider None 短路返回 stats 键名/值变体：同禁用态 stats——runner 不消费返回值、键面无断言（面板域判例；m41 disabled 反转亦在域内） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.retrieval.embedder.x_ensure_item_vectors__mutmut_38 | A | provider None 短路返回 stats 键名/值变体：同禁用态 stats——runner 不消费返回值、键面无断言（面板域判例；m41 disabled 反转亦在域内） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.retrieval.embedder.x_ensure_item_vectors__mutmut_39 | A | provider None 短路返回 stats 键名/值变体：同禁用态 stats——runner 不消费返回值、键面无断言（面板域判例；m41 disabled 反转亦在域内） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.retrieval.embedder.x_ensure_item_vectors__mutmut_40 | A | provider None 短路返回 stats 键名/值变体：同禁用态 stats——runner 不消费返回值、键面无断言（面板域判例；m41 disabled 反转亦在域内） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.retrieval.embedder.x_ensure_item_vectors__mutmut_41 | A | provider None 短路返回 stats 键名/值变体：同禁用态 stats——runner 不消费返回值、键面无断言（面板域判例；m41 disabled 反转亦在域内） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.retrieval.embedder.x_ensure_item_vectors__mutmut_51 | A | 正常路径 stats 初始 model_version 键变体：后续无重写但消费面（runner/测试）不断言该键——面板域（payload.stats 消费方=诊断面板） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.retrieval.embedder.x_ensure_item_vectors__mutmut_52 | A | 正常路径 stats 初始 model_version 键变体：后续无重写但消费面（runner/测试）不断言该键——面板域（payload.stats 消费方=诊断面板） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.retrieval.embedder.x_ensure_item_vectors__mutmut_58 | A | 正常路径 stats failed/disabled 键名/值变体：m58/59 失败路径重写正确键吸收；m60-63 无断言面——面板域判例（stats 键值=诊断面板消费） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.retrieval.embedder.x_ensure_item_vectors__mutmut_59 | A | 正常路径 stats failed/disabled 键名/值变体：m58/59 失败路径重写正确键吸收；m60-63 无断言面——面板域判例（stats 键值=诊断面板消费） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.retrieval.embedder.x_ensure_item_vectors__mutmut_60 | A | 正常路径 stats failed/disabled 键名/值变体：m58/59 失败路径重写正确键吸收；m60-63 无断言面——面板域判例（stats 键值=诊断面板消费） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.retrieval.embedder.x_ensure_item_vectors__mutmut_61 | A | 正常路径 stats failed/disabled 键名/值变体：m58/59 失败路径重写正确键吸收；m60-63 无断言面——面板域判例（stats 键值=诊断面板消费） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.retrieval.embedder.x_ensure_item_vectors__mutmut_62 | A | 正常路径 stats failed/disabled 键名/值变体：m58/59 失败路径重写正确键吸收；m60-63 无断言面——面板域判例（stats 键值=诊断面板消费） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.retrieval.embedder.x_ensure_item_vectors__mutmut_63 | A | 正常路径 stats failed/disabled 键名/值变体：m58/59 失败路径重写正确键吸收；m60-63 无断言面——面板域判例（stats 键值=诊断面板消费） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.retrieval.embedder.x_ensure_item_vectors__mutmut_75 | A | truncate_chars 实参 None 化/移除：生产调用链 runner→ensure 恒不传 → 形参恒 None，变异与原值恰等价（生产调用点核查——实参变异恒替换判例） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.retrieval.embedder.x_ensure_item_vectors__mutmut_77 | A | truncate_chars 实参 None 化/移除：生产调用链 runner→ensure 恒不传 → 形参恒 None，变异与原值恰等价（生产调用点核查——实参变异恒替换判例） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.retrieval.embedder.x_ensure_item_vectors__mutmut_86 | A | call_point kwarg 移除：EmbeddingProvider.embed 签名 call_point 缺省恰="embed"（base.py 实证）——缺省值等价族 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.retrieval.embedder.x_ensure_item_vectors__mutmut_92 | A | failed = missing-embedded → +：失败态 stats 值（runner 不消费、test_per_batch 不断言 failed）——面板值域 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.retrieval.embedder.x_ensure_item_vectors__mutmut_96 | A | WARN 实参 None/移除/文案 XX/单参：logging 缺参静默门+文案子串无断言——文案先例族（C2-1 enqueue m47 组判据） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.retrieval.embedder.x_ensure_item_vectors__mutmut_97 | A | WARN 实参 None/移除/文案 XX/单参：logging 缺参静默门+文案子串无断言——文案先例族（C2-1 enqueue m47 组判据） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.retrieval.embedder.x_ensure_item_vectors__mutmut_98 | A | WARN 实参 None/移除/文案 XX/单参：logging 缺参静默门+文案子串无断言——文案先例族（C2-1 enqueue m47 组判据） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.retrieval.embedder.x_ensure_item_vectors__mutmut_99 | A | WARN 实参 None/移除/文案 XX/单参：logging 缺参静默门+文案子串无断言——文案先例族（C2-1 enqueue m47 组判据） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |

#### retrieval.embedder.missing_vector_items（缺失向量过滤）（A 1）

| mutant 全名 | 类别 | 一句话理由 | 依据条款或推理 |
|---|---|---|---|
| app.retrieval.embedder.x_missing_vector_items__mutmut_7 | A | item_id.in_(ids) 过滤删除：have 超集仅含 items 外 id，不在 items 的 id 不影响 [i for i in items if i.id not in have] 结果——返回列表恰等价（查询量差异非可观察行为） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |

#### retrieval.explore.explore_params（探索参数合成）（A 2）

| mutant 全名 | 类别 | 一句话理由 | 依据条款或推理 |
|---|---|---|---|
| app.retrieval.explore.x_explore_params__mutmut_47 | A | direction is not None → or True 恒真：direction None 时 getattr(None,...)→None→or {} 恰等价——冗余守卫等价族 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.retrieval.explore.x_explore_params__mutmut_53 | A | getattr 缺省值移除：direction 恒为 ORM 实例（explore_config 列恒存在），缺省分支不可达——列存在性等价 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |

#### retrieval.explore.explore_pick（探索选样 MMR）（A 6 + B 5）

| mutant 全名 | 类别 | 一句话理由 | 依据条款或推理 |
|---|---|---|---|
| app.retrieval.explore.x_explore_pick__mutmut_1 | A | 首两守卫 or→and 化：quota≤0 时 while len(picked)<quota 恒假仍返回空——两形态返回值恰等价 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.retrieval.explore.x_explore_pick__mutmut_2 | B | 首两守卫 and 化：query_vec None 且 quota>0 时不再早退→cosine(None,·) 崩——生产注入端恒有 query_vec 守卫（routes d.query_vec is None 前置），纯函数签名契约的防御短路——防御分支豁免 | 防御分支豁免（正常运行不可达、设计书要求其存在——任务书 §2 B 判据） |
| app.retrieval.explore.x_explore_pick__mutmut_4 | A | quota <= 0 → < 0：quota=0 时循环不执行仍返回空——恰等价 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.retrieval.explore.x_explore_pick__mutmut_16 | B | vec is not None → or True 恒真：vec=None 条目进 cosine 崩——生产 pool 由 join ItemVec 构造恒带向量（routes 实证），防御短路豁免 | 防御分支豁免（正常运行不可达、设计书要求其存在——任务书 §2 B 判据） |
| app.retrieval.explore.x_explore_pick__mutmut_32 | A | percentile 数组 dtype float64→None/移除：known 为 float 列表，asarray dtype=None 推断恒 float64——恰等价 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.retrieval.explore.x_explore_pick__mutmut_34 | A | percentile 数组 dtype float64→None/移除：known 为 float 列表，asarray dtype=None 推断恒 float64——恰等价 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.retrieval.explore.x_explore_pick__mutmut_41 | B | it.get("passed", True) 缺省 None/移除/False：缺 passed 键的条目纳入候选——生产 pool 恒带 passed 键（routes 构造实证），缺省分支不可达——防御缺省豁免 | 防御分支豁免（正常运行不可达、设计书要求其存在——任务书 §2 B 判据） |
| app.retrieval.explore.x_explore_pick__mutmut_43 | B | it.get("passed", True) 缺省 None/移除/False：缺 passed 键的条目纳入候选——生产 pool 恒带 passed 键（routes 构造实证），缺省分支不可达——防御缺省豁免 | 防御分支豁免（正常运行不可达、设计书要求其存在——任务书 §2 B 判据） |
| app.retrieval.explore.x_explore_pick__mutmut_46 | B | it.get("passed", True) 缺省 None/移除/False：缺 passed 键的条目纳入候选——生产 pool 恒带 passed 键（routes 构造实证），缺省分支不可达——防御缺省豁免 | 防御分支豁免（正常运行不可达、设计书要求其存在——任务书 §2 B 判据） |
| app.retrieval.explore.x_explore_pick__mutmut_51 | A | quality or 0 → or 1：0/None 哨兵与 floor 整数比较 (0>=f) ⇔ (1>=f) 对整数 f 恒同真假——数学恰等价 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.retrieval.explore.x_explore_pick__mutmut_88 | A | MMR sim_sel 缺省 0.0→1.0：picked 为空时全体候选分数同平移 (1-λ)，argmax 不变；picked 非空时生成器非空缺省不可达——等价 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |

#### retrieval.query.ensure_direction_query_vec（方向查询向量）（A 19 + B 2）

| mutant 全名 | 类别 | 一句话理由 | 依据条款或推理 |
|---|---|---|---|
| app.retrieval.query.x_ensure_direction_query_vec__mutmut_7 | B | query_vec_version or 0 → or 1：差异域=vec 落列而 version None 的不一致态（commit 双写恒一致，生产不可达）且 prompt_version=1 时误判缓存命中——防御分支豁免 | 防御分支豁免（正常运行不可达、设计书要求其存在——任务书 §2 B 判据） |
| app.retrieval.query.x_ensure_direction_query_vec__mutmut_16 | A | call_point="query_gen" 值 None/XX/大写：query_gen 非嵌入计量口径（生产配置表仅钉 embed/embed_query），账本归因值域无行为消费方（budget 按日总量聚合）——账本值域 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.retrieval.query.x_ensure_direction_query_vec__mutmut_17 | A | ref_type 值 None/移除/XX/大写：ref_type 缺省 None（chat 签名实证），归因列无行为消费方——账本值域 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.retrieval.query.x_ensure_direction_query_vec__mutmut_18 | A | ref_id 值 None/移除：同 ref_type——账本归因值域 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.retrieval.query.x_ensure_direction_query_vec__mutmut_19 | A | max_tokens 500→None/移除：生成上限护栏数值（chat 签名缺省 None），「200 字以内」由提示词文本承载——护栏数值无条款 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.retrieval.query.x_ensure_direction_query_vec__mutmut_22 | A | ref_type 值 None/移除/XX/大写：ref_type 缺省 None（chat 签名实证），归因列无行为消费方——账本值域 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.retrieval.query.x_ensure_direction_query_vec__mutmut_23 | A | ref_id 值 None/移除：同 ref_type——账本归因值域 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.retrieval.query.x_ensure_direction_query_vec__mutmut_24 | A | max_tokens 500→None/移除：生成上限护栏数值（chat 签名缺省 None），「200 字以内」由提示词文本承载——护栏数值无条款 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.retrieval.query.x_ensure_direction_query_vec__mutmut_31 | A | system 短句 XX 包裹：LLM-facing 文案变体（消息协议形态完整、user 内容不变）——文案先例族（措辞无条款，断言面=协议形态非内容） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.retrieval.query.x_ensure_direction_query_vec__mutmut_39 | A | call_point="query_gen" 值 None/XX/大写：query_gen 非嵌入计量口径（生产配置表仅钉 embed/embed_query），账本归因值域无行为消费方（budget 按日总量聚合）——账本值域 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.retrieval.query.x_ensure_direction_query_vec__mutmut_40 | A | call_point="query_gen" 值 None/XX/大写：query_gen 非嵌入计量口径（生产配置表仅钉 embed/embed_query），账本归因值域无行为消费方（budget 按日总量聚合）——账本值域 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.retrieval.query.x_ensure_direction_query_vec__mutmut_41 | A | ref_type 值 None/移除/XX/大写：ref_type 缺省 None（chat 签名实证），归因列无行为消费方——账本值域 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.retrieval.query.x_ensure_direction_query_vec__mutmut_42 | A | ref_type 值 None/移除/XX/大写：ref_type 缺省 None（chat 签名实证），归因列无行为消费方——账本值域 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.retrieval.query.x_ensure_direction_query_vec__mutmut_43 | A | max_tokens 500→501：同上护栏数值域 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.retrieval.query.x_ensure_direction_query_vec__mutmut_46 | A | ProviderError 文案 None/XX：异常被捕获落 log（文案无断言）——文案先例族 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.retrieval.query.x_ensure_direction_query_vec__mutmut_47 | A | ProviderError 文案 None/XX：异常被捕获落 log（文案无断言）——文案先例族 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.retrieval.query.x_ensure_direction_query_vec__mutmut_52 | B | embed_provider None → return True 误报就绪：差异域=embed_enabled 且注册表解析失败（moark 恒注册不可达）——防御分支豁免 | 防御分支豁免（正常运行不可达、设计书要求其存在——任务书 §2 B 判据） |
| app.retrieval.query.x_ensure_direction_query_vec__mutmut_54 | A | dims 覆写 and False 恒假：不传时恒=config 与原等价（生产调用形态；显式覆写域=测试隔离面） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.retrieval.query.x_ensure_direction_query_vec__mutmut_68 | A | WARN 实参 None 化/文案 XX：logging 合法格式化、无断言——文案先例族 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.retrieval.query.x_ensure_direction_query_vec__mutmut_69 | A | WARN 实参 None 化/文案 XX：logging 合法格式化、无断言——文案先例族 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.retrieval.query.x_ensure_direction_query_vec__mutmut_73 | A | WARN 实参 None 化/文案 XX：logging 合法格式化、无断言——文案先例族 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |

#### retrieval.router._load_direction_vectors（方向向量加载）（A 4）

| mutant 全名 | 类别 | 一句话理由 | 依据条款或推理 |
|---|---|---|---|
| app.retrieval.router.x__load_direction_vectors__mutmut_7 | A | join onclause None/省略：ItemVec→Item→Source 均单 FK，SQLAlchemy 回退 FK 推断恰等价（C2-1/C3-3 join 判据族） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.retrieval.router.x__load_direction_vectors__mutmut_9 | A | join onclause None/省略：ItemVec→Item→Source 均单 FK，SQLAlchemy 回退 FK 推断恰等价（C2-1/C3-3 join 判据族） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.retrieval.router.x__load_direction_vectors__mutmut_11 | A | join onclause None/省略：ItemVec→Item→Source 均单 FK，SQLAlchemy 回退 FK 推断恰等价（C2-1/C3-3 join 判据族） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.retrieval.router.x__load_direction_vectors__mutmut_13 | A | join onclause None/省略：ItemVec→Item→Source 均单 FK，SQLAlchemy 回退 FK 推断恰等价（C2-1/C3-3 join 判据族） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |

#### retrieval.router.is_version_item（版本条目判定）（A 1）

| mutant 全名 | 类别 | 一句话理由 | 依据条款或推理 |
|---|---|---|---|
| app.retrieval.router.x_is_version_item__mutmut_3 | A | guid or ""→or "XXXX"：guid 列 NOT NULL（models 实证），None 分支不可达；"XXXX" 亦不含 #v- 判定恒同——死码等价 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |

#### retrieval.router.mark_semantic_duplicates（语义判重标记）（A 4）

| mutant 全名 | 类别 | 一句话理由 | 依据条款或推理 |
|---|---|---|---|
| app.retrieval.router.x_mark_semantic_duplicates__mutmut_1 | A | 守卫 or→and 化：model_version None 时 vecs 查询恒空→循环全跳过→返回 []；items 空时循环体不执行——两形态返回值恰等价 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.retrieval.router.x_mark_semantic_duplicates__mutmut_14 | A | 兜底 0.92→1.92：DEFAULTS 恒回退（semantic_dedup_threshold=0.92 实证在册），or 右支仅 falsy set 域可达——DEFAULTS 判例族（同 explore m22 域；set 0 的falsy 语义无条款但此处与 or→and 值域不同属等价域边缘——施加必活验证） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.retrieval.router.x_mark_semantic_duplicates__mutmut_61 | A | INFO 实参 None/文案 XX：logging 合法格式化、无断言——文案先例族 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.retrieval.router.x_mark_semantic_duplicates__mutmut_67 | A | INFO 实参 None/文案 XX：logging 合法格式化、无断言——文案先例族 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |

#### retrieval.router.partition_items（打分路由分桶）（A 7）

| mutant 全名 | 类别 | 一句话理由 | 依据条款或推理 |
|---|---|---|---|
| app.retrieval.router.x_partition_items__mutmut_5 | A | stats 初始 routed_misses/embed_disabled 键名/值变体：embed_disabled 分支重写吸收（正确键恒在）；正常路径暴露域仅面板值（无断言）——初值吸收+面板域判例 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.retrieval.router.x_partition_items__mutmut_6 | A | stats 初始 routed_misses/embed_disabled 键名/值变体：embed_disabled 分支重写吸收（正确键恒在）；正常路径暴露域仅面板值（无断言）——初值吸收+面板域判例 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.retrieval.router.x_partition_items__mutmut_7 | A | stats 初始 routed_misses/embed_disabled 键名/值变体：embed_disabled 分支重写吸收（正确键恒在）；正常路径暴露域仅面板值（无断言）——初值吸收+面板域判例 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.retrieval.router.x_partition_items__mutmut_8 | A | stats 初始 routed_misses/embed_disabled 键名/值变体：embed_disabled 分支重写吸收（正确键恒在）；正常路径暴露域仅面板值（无断言）——初值吸收+面板域判例 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.retrieval.router.x_partition_items__mutmut_9 | A | stats 初始 routed_misses/embed_disabled 键名/值变体：embed_disabled 分支重写吸收（正确键恒在）；正常路径暴露域仅面板值（无断言）——初值吸收+面板域判例 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.retrieval.router.x_partition_items__mutmut_10 | A | embed_disabled 初始 False→True：正常路径不写该键、初始值直接透出——面板误标域（runner 落 payload.stats 诊断消费、无断言与条款）——面板域判例 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.retrieval.router.x_partition_items__mutmut_42 | A | top_k 兜底 or 5→or 6：DEFAULTS 恒回退（retrieval_top_k=5 实证在册），or 右支仅 falsy set 域可达——DEFAULTS 判例族（同 explore m22 域形态，此处 set 0 的 falsy 语义同域但分诊从 A——施加必活验证实证；若核验意外改判） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |

#### scoring._host（来源域名抽取）（A 4）

| mutant 全名 | 类别 | 一句话理由 | 依据条款或推理 |
|---|---|---|---|
| app.scoring.service.x__host__mutmut_2 | A | urlparse(item.url or "")→urlparse(None)：url 列 NOT NULL default=""（models 实证），None 分支不可达——死码域 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.scoring.service.x__host__mutmut_4 | A | or ""→or "XXXX"：url None 态 urlparse("XXXX") netloc 恒空 → 「未知」同值——恰等价（且 None 分支本身死码） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.scoring.service.x__host__mutmut_5 | A | 「未知」→XX未知XX：prompt 上下文段文案（LLM-facing 文案先例族——任务书 _host 先例域） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.scoring.service.x__host__mutmut_6 | A | except ValueError 文案 XX：防御分支文案变体——文案先例族 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |

#### scoring._render_user_message（user 消息组装）（A 8）

| mutant 全名 | 类别 | 一句话理由 | 依据条款或推理 |
|---|---|---|---|
| app.scoring.service.x__render_user_message__mutmut_3 | A | or ""→or "XXXX"：content_text 列 NOT NULL default=""（models 实证），None 分支不可达——死码域 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.scoring.service.x__render_user_message__mutmut_4 | A | 发布日期段 None 化/恒「未知」：prompt 上下文段细节（日期格式与占位语义无条款——任务书 _host「无条款细节」先例域；LLM-facing 文案先例族） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.scoring.service.x__render_user_message__mutmut_5 | A | 发布日期段 None 化/恒「未知」：prompt 上下文段细节（日期格式与占位语义无条款——任务书 _host「无条款细节」先例域；LLM-facing 文案先例族） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.scoring.service.x__render_user_message__mutmut_8 | A | 日期格式串 XX/%y/%M-%D 变体：日期段格式细节（格式无条款；strftime(None) 崩溃域已单列 C）——文案先例族 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.scoring.service.x__render_user_message__mutmut_9 | A | 日期格式串 XX/%y/%M-%D 变体：日期段格式细节（格式无条款；strftime(None) 崩溃域已单列 C）——文案先例族 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.scoring.service.x__render_user_message__mutmut_10 | A | 日期格式串 XX/%y/%M-%D 变体：日期段格式细节（格式无条款；strftime(None) 崩溃域已单列 C）——文案先例族 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.scoring.service.x__render_user_message__mutmut_11 | A | 「未知」「（无正文）」占位文案 XX：占位措辞无条款——文案先例族 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.scoring.service.x__render_user_message__mutmut_14 | A | 「未知」「（无正文）」占位文案 XX：占位措辞无条款——文案先例族 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |

#### scoring._validate（打分 strict JSON 校验）（A 12）

| mutant 全名 | 类别 | 一句话理由 | 依据条款或推理 |
|---|---|---|---|
| app.scoring.service.x__validate__mutmut_18 | A | JSONParseError 文案/got 截断变体（None/键序/ensure_ascii 缺省/True/[:201]）：异常类型不变、构造合法——异常文案域（调用方按类型处理不计文案）——文案先例族 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.scoring.service.x__validate__mutmut_19 | A | JSONParseError 文案/got 截断变体（None/键序/ensure_ascii 缺省/True/[:201]）：异常类型不变、构造合法——异常文案域（调用方按类型处理不计文案）——文案先例族 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.scoring.service.x__validate__mutmut_20 | A | JSONParseError 文案/got 截断变体（None/键序/ensure_ascii 缺省/True/[:201]）：异常类型不变、构造合法——异常文案域（调用方按类型处理不计文案）——文案先例族 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.scoring.service.x__validate__mutmut_22 | A | JSONParseError 文案/got 截断变体（None/键序/ensure_ascii 缺省/True/[:201]）：异常类型不变、构造合法——异常文案域（调用方按类型处理不计文案）——文案先例族 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.scoring.service.x__validate__mutmut_23 | A | JSONParseError 文案/got 截断变体（None/键序/ensure_ascii 缺省/True/[:201]）：异常类型不变、构造合法——异常文案域（调用方按类型处理不计文案）——文案先例族 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.scoring.service.x__validate__mutmut_24 | A | JSONParseError 文案/got 截断变体（None/键序/ensure_ascii 缺省/True/[:201]）：异常类型不变、构造合法——异常文案域（调用方按类型处理不计文案）——文案先例族 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.scoring.service.x__validate__mutmut_35 | A | raise 文案 None/XX：同上异常文案域——文案先例族 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.scoring.service.x__validate__mutmut_38 | A | raise 文案 None/XX：同上异常文案域——文案先例族 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.scoring.service.x__validate__mutmut_40 | A | raise 文案 None/XX：同上异常文案域——文案先例族 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.scoring.service.x__validate__mutmut_41 | A | raise 文案 None/XX：同上异常文案域——文案先例族 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.scoring.service.x__validate__mutmut_42 | A | raise 文案 None/XX：同上异常文案域——文案先例族 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.scoring.service.x__validate__mutmut_51 | A | reason 截断界 [:300]→[:301]：截断界数值无条款（providers.base m42 [:2000]→[:2001] A 先例同族）——界值域 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |

#### scoring.load_prompt_template（提示词模板加载）（A 2 + B 3）

| mutant 全名 | 类别 | 一句话理由 | 依据条款或推理 |
|---|---|---|---|
| app.scoring.service.x_load_prompt_template__mutmut_2 | B | 版本串 lower→upper：差异域=历史 'v1' 字符串形态入参（D19 生产恒 int→"1" 对 lower/upper 恒等）——历史形态兼容=防御域豁免 | 防御分支豁免（正常运行不可达、设计书要求其存在——任务书 §2 B 判据） |
| app.scoring.service.x_load_prompt_template__mutmut_6 | B | startswith("v")→XXvXX：同 m2 历史形态域（int 形态恒补 v 前缀等价）——防御豁免 | 防御分支豁免（正常运行不可达、设计书要求其存在——任务书 §2 B 判据） |
| app.scoring.service.x_load_prompt_template__mutmut_7 | B | startswith("V") 大写：同上（lower 后恒小写 v，大写判定恒 False 与 not startswith("v") 在 int 形态恒同）——防御豁免 | 防御分支豁免（正常运行不可达、设计书要求其存在——任务书 §2 B 判据） |
| app.scoring.service.x_load_prompt_template__mutmut_11 | A | encoding="utf-8"→None：dispatch/CI 目标平台 Ubuntu locale 恒 utf-8——目标运行环境恰等价（本机 Windows gbk 差异为开发环境形态，已备案） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.scoring.service.x_load_prompt_template__mutmut_13 | A | encoding="UTF-8"：Python 编码别名大小写不敏感——恰等价 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |

#### scoring.score_item（打分调用编排）（A 18）

| mutant 全名 | 类别 | 一句话理由 | 依据条款或推理 |
|---|---|---|---|
| app.scoring.service.x_score_item__mutmut_47 | A | last_error 初始 ""：失败路径恒先赋值（两分支均 last_error=...），初始值不可达读——初值吸收判例 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.scoring.service.x_score_item__mutmut_52 | A | chat_json model=model None 化/移除：生产调用点（runner 两处）恒不传 model →形参恒 None，变异与原值恰等价（实参变异恒替换判例） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.scoring.service.x_score_item__mutmut_54 | A | ref_type="item" None/移除/XX/大写：ref_type 缺省 None（chat 签名实证），归因列无行为消费方——账本值域 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.scoring.service.x_score_item__mutmut_55 | A | ref_id=None/移除：同 ref_type——账本归因值域 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.scoring.service.x_score_item__mutmut_56 | A | temperature=0.0 None/移除/1.0：温度数值无条款（移除时 chat 签名缺省恰 0.0 等价；None/1.0 为 LLM 参数域）——护栏数值域 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.scoring.service.x_score_item__mutmut_58 | A | chat_json model=model None 化/移除：生产调用点（runner 两处）恒不传 model →形参恒 None，变异与原值恰等价（实参变异恒替换判例） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.scoring.service.x_score_item__mutmut_60 | A | ref_type="item" None/移除/XX/大写：ref_type 缺省 None（chat 签名实证），归因列无行为消费方——账本值域 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.scoring.service.x_score_item__mutmut_61 | A | ref_id=None/移除：同 ref_type——账本归因值域 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.scoring.service.x_score_item__mutmut_62 | A | temperature=0.0 None/移除/1.0：温度数值无条款（移除时 chat 签名缺省恰 0.0 等价；None/1.0 为 LLM 参数域）——护栏数值域 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.scoring.service.x_score_item__mutmut_65 | A | ref_type="item" None/移除/XX/大写：ref_type 缺省 None（chat 签名实证），归因列无行为消费方——账本值域 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.scoring.service.x_score_item__mutmut_66 | A | ref_type="item" None/移除/XX/大写：ref_type 缺省 None（chat 签名实证），归因列无行为消费方——账本值域 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.scoring.service.x_score_item__mutmut_67 | A | temperature=0.0 None/移除/1.0：温度数值无条款（移除时 chat 签名缺省恰 0.0 等价；None/1.0 为 LLM 参数域）——护栏数值域 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.scoring.service.x_score_item__mutmut_87 | A | status="OK"→None：ScoreResult.status 列 default="OK"（models.py 实证），ORM flush 对显式 None 省略列使 default 落库恰等原值——列 default 吸收恰等价（m36 同族判例；施加实证 28 passed） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.scoring.service.x_score_item__mutmut_90 | A | 成功行 error=None→""：成功路径 error 值域（面板/诊断域，无断言与条款）——值域 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.scoring.service.x_score_item__mutmut_93 | A | last_error=str(None)：失败原因文案变体（error 载体仍在——文案先例族） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.scoring.service.x_score_item__mutmut_102 | A | 追加 assistant content 值 XX 包裹：重试附加说明措辞（自定形态域，协议形态完整——文案先例族） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.scoring.service.x_score_item__mutmut_112 | A | error 赋值守卫 !=OK 字面量 XX/ok：比较恒 False→error 赋值恒执行——成功行 error=last_error=None 与原等价、失败行照常（恰等价推理） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.scoring.service.x_score_item__mutmut_113 | A | error 赋值守卫 !=OK 字面量 XX/ok：比较恒 False→error 赋值恒执行——成功行 error=last_error=None 与原等价、失败行照常（恰等价推理） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |

## 批次 5：外部能力族（C3-5，2026-10-08）

> 分诊执行 Agent 依 `doc/C3/C3-5-任务书.md` 出具；本族种子 242 条（moark_reranker
> 90 + search.base 20 + search.bocha 106 + search.pipeline 25 + search.registry 1）
> 四分类 = C 130 / A 112 / B 0 / D 0。C 类 130 条由三个新测试文件杀灭
> （test_search_provider_contract / test_moark_rerank_contract /
> test_search_pipeline_assembly），不在本清单。核验-改判循环三轮：①C 轮 2 条
> 意外（moark _rank_chunk m25 / bocha _search m48——httpx 对 json= 自动携带
> Content-Type 主头，C2-4 embedding.moark m25 判例同构）沿判例改判 A；②B 轮
> 1 条意外（moark m76——and 化破坏越界跳过全部功能，落任务书 §2「失效条目过滤」
> C 地形）改判 C 并补恰边界条目、同守卫 m78 一并改 C；终态 C 130/130 全杀、
> A 112/112 全活零意外。核验数据：doc/C3/C3-5-核验结果.json。

### app.rerank.moark_reranker

#### rerank.moark_reranker._rank_chunk（单批请求与响应解析）（A 65）

| mutant 全名 | 类别 | 一句话理由 | 依据条款或推理 |
|---|---|---|---|
| app.rerank.moark_reranker.xǁMoarkRerankerProviderǁ_rank_chunk__mutmut_2 | A | query_max_chars 覆写判定 and False/or True/is not None：生产构造缺省恒 None（__init__ m13 豁免判例——None=不截断 8K 直吃口径），三形态与原恒等；整数截断域=对照实验用（docstring 明示）——生产调用形态等价 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.rerank.moark_reranker.xǁMoarkRerankerProviderǁ_rank_chunk__mutmut_3 | A | query_max_chars 覆写判定 and False/or True/is not None：生产构造缺省恒 None（__init__ m13 豁免判例——None=不截断 8K 直吃口径），三形态与原恒等；整数截断域=对照实验用（docstring 明示）——生产调用形态等价 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.rerank.moark_reranker.xǁMoarkRerankerProviderǁ_rank_chunk__mutmut_4 | A | query_max_chars 覆写判定 and False/or True/is not None：生产构造缺省恒 None（__init__ m13 豁免判例——None=不截断 8K 直吃口径），三形态与原恒等；整数截断域=对照实验用（docstring 明示）——生产调用形态等价 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.rerank.moark_reranker.xǁMoarkRerankerProviderǁ_rank_chunk__mutmut_23 | A | Authorization 键小写/大写：httpx Headers 大小写不敏感（RFC 头名不分区），线格式恒等——HTTP 头形态等价（任务书 A 形态明示） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.rerank.moark_reranker.xǁMoarkRerankerProviderǁ_rank_chunk__mutmut_24 | A | Authorization 键小写/大写：httpx Headers 大小写不敏感（RFC 头名不分区），线格式恒等——HTTP 头形态等价（任务书 A 形态明示） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.rerank.moark_reranker.xǁMoarkRerankerProviderǁ_rank_chunk__mutmut_25 | A | Content-Type 键 XX：httpx 对 json= 参数自动携带 Content-Type: application/json，显式键名变异被自动头兜底、结果头不变——恰等价（C2-4 embedding.moark m25 实测新判例同构：本批 C 轮施加杀灭面测试仍全绿实证） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.rerank.moark_reranker.xǁMoarkRerankerProviderǁ_rank_chunk__mutmut_26 | A | Content-Type 键小写/大写：同 m23 域——头形态等价 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.rerank.moark_reranker.xǁMoarkRerankerProviderǁ_rank_chunk__mutmut_27 | A | Content-Type 键小写/大写：同 m23 域——头形态等价 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.rerank.moark_reranker.xǁMoarkRerankerProviderǁ_rank_chunk__mutmut_32 | A | 429 错误消息 RankError(None)/scrub(None)/[:301]：异常类型与 retryable 标记不变，消息文案/截断界无条款——异常文案域（文案先例族） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.rerank.moark_reranker.xǁMoarkRerankerProviderǁ_rank_chunk__mutmut_33 | A | 429 错误消息 RankError(None)/scrub(None)/[:301]：异常类型与 retryable 标记不变，消息文案/截断界无条款——异常文案域（文案先例族） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.rerank.moark_reranker.xǁMoarkRerankerProviderǁ_rank_chunk__mutmut_34 | A | 429 错误消息 RankError(None)/scrub(None)/[:301]：异常类型与 retryable 标记不变，消息文案/截断界无条款——异常文案域（文案先例族） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.rerank.moark_reranker.xǁMoarkRerankerProviderǁ_rank_chunk__mutmut_35 | A | e.retryable=None/False：rank 链无重试环（rerank.base.rank 捕获 RankError 落账即raise、writer/hot 捕获回退，全链无 retryable 消费方——grep 实证）——标记无消费方等价（报错脱敏/重试纪律的消费面在 LLM/search 底座非 rank） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.rerank.moark_reranker.xǁMoarkRerankerProviderǁ_rank_chunk__mutmut_36 | A | e.retryable=None/False：rank 链无重试环（rerank.base.rank 捕获 RankError 落账即raise、writer/hot 捕获回退，全链无 retryable 消费方——grep 实证）——标记无消费方等价（报错脱敏/重试纪律的消费面在 LLM/search 底座非 rank） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.rerank.moark_reranker.xǁMoarkRerankerProviderǁ_rank_chunk__mutmut_39 | A | ≥400 错误消息 RankError(None)/scrub(None)/[:301]：异常类型不变——异常文案域（文案先例族） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.rerank.moark_reranker.xǁMoarkRerankerProviderǁ_rank_chunk__mutmut_40 | A | ≥400 错误消息 RankError(None)/scrub(None)/[:301]：异常类型不变——异常文案域（文案先例族） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.rerank.moark_reranker.xǁMoarkRerankerProviderǁ_rank_chunk__mutmut_41 | A | ≥400 错误消息 RankError(None)/scrub(None)/[:301]：异常类型不变——异常文案域（文案先例族） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.rerank.moark_reranker.xǁMoarkRerankerProviderǁ_rank_chunk__mutmut_44 | A | usage 读取 and 化/键 None/XX/大写：usage_flat 仅入 RankedResult.raw 存档域（rank_call_log 不携带 token——base._log 无 token 列），缺 usage 键域=协议恒返（V10 实测）——存档值域无行为消费方 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.rerank.moark_reranker.xǁMoarkRerankerProviderǁ_rank_chunk__mutmut_45 | A | usage 读取 and 化/键 None/XX/大写：usage_flat 仅入 RankedResult.raw 存档域（rank_call_log 不携带 token——base._log 无 token 列），缺 usage 键域=协议恒返（V10 实测）——存档值域无行为消费方 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.rerank.moark_reranker.xǁMoarkRerankerProviderǁ_rank_chunk__mutmut_46 | A | usage 读取 and 化/键 None/XX/大写：usage_flat 仅入 RankedResult.raw 存档域（rank_call_log 不携带 token——base._log 无 token 列），缺 usage 键域=协议恒返（V10 实测）——存档值域无行为消费方 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.rerank.moark_reranker.xǁMoarkRerankerProviderǁ_rank_chunk__mutmut_47 | A | usage 读取 and 化/键 None/XX/大写：usage_flat 仅入 RankedResult.raw 存档域（rank_call_log 不携带 token——base._log 无 token 列），缺 usage 键域=协议恒返（V10 实测）——存档值域无行为消费方 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.rerank.moark_reranker.xǁMoarkRerankerProviderǁ_rank_chunk__mutmut_49 | A | usage_flat prompt_tokens 键 XX/大写：raw 存档键面（无行为消费方）——存档键面 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.rerank.moark_reranker.xǁMoarkRerankerProviderǁ_rank_chunk__mutmut_50 | A | usage_flat prompt_tokens 键 XX/大写：raw 存档键面（无行为消费方）——存档键面 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.rerank.moark_reranker.xǁMoarkRerankerProviderǁ_rank_chunk__mutmut_52 | A | prompt_tokens 值 and 0/读取键变体/or 1：真值域差异仅 raw 存档值；缺键域 or 0兜底=防御缺省（usage 协议恒返）——存档值域 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.rerank.moark_reranker.xǁMoarkRerankerProviderǁ_rank_chunk__mutmut_53 | A | prompt_tokens 值 and 0/读取键变体/or 1：真值域差异仅 raw 存档值；缺键域 or 0兜底=防御缺省（usage 协议恒返）——存档值域 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.rerank.moark_reranker.xǁMoarkRerankerProviderǁ_rank_chunk__mutmut_54 | A | prompt_tokens 值 and 0/读取键变体/or 1：真值域差异仅 raw 存档值；缺键域 or 0兜底=防御缺省（usage 协议恒返）——存档值域 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.rerank.moark_reranker.xǁMoarkRerankerProviderǁ_rank_chunk__mutmut_55 | A | prompt_tokens 值 and 0/读取键变体/or 1：真值域差异仅 raw 存档值；缺键域 or 0兜底=防御缺省（usage 协议恒返）——存档值域 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.rerank.moark_reranker.xǁMoarkRerankerProviderǁ_rank_chunk__mutmut_56 | A | prompt_tokens 值 and 0/读取键变体/or 1：真值域差异仅 raw 存档值；缺键域 or 0兜底=防御缺省（usage 协议恒返）——存档值域 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.rerank.moark_reranker.xǁMoarkRerankerProviderǁ_rank_chunk__mutmut_57 | A | prompt_tokens 值 and 0/读取键变体/or 1：真值域差异仅 raw 存档值；缺键域 or 0兜底=防御缺省（usage 协议恒返）——存档值域 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.rerank.moark_reranker.xǁMoarkRerankerProviderǁ_rank_chunk__mutmut_58 | A | usage_flat total_tokens 键 XX/大写：同 m49 域——存档键面 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.rerank.moark_reranker.xǁMoarkRerankerProviderǁ_rank_chunk__mutmut_59 | A | usage_flat total_tokens 键 XX/大写：同 m49 域——存档键面 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.rerank.moark_reranker.xǁMoarkRerankerProviderǁ_rank_chunk__mutmut_61 | A | total_tokens 值 and 0/读取键变体/or 1：同 m52 域——存档值域 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.rerank.moark_reranker.xǁMoarkRerankerProviderǁ_rank_chunk__mutmut_62 | A | total_tokens 值 and 0/读取键变体/or 1：同 m52 域——存档值域 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.rerank.moark_reranker.xǁMoarkRerankerProviderǁ_rank_chunk__mutmut_63 | A | total_tokens 值 and 0/读取键变体/or 1：同 m52 域——存档值域 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.rerank.moark_reranker.xǁMoarkRerankerProviderǁ_rank_chunk__mutmut_64 | A | total_tokens 值 and 0/读取键变体/or 1：同 m52 域——存档值域 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.rerank.moark_reranker.xǁMoarkRerankerProviderǁ_rank_chunk__mutmut_65 | A | total_tokens 值 and 0/读取键变体/or 1：同 m52 域——存档值域 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.rerank.moark_reranker.xǁMoarkRerankerProviderǁ_rank_chunk__mutmut_66 | A | total_tokens 值 and 0/读取键变体/or 1：同 m52 域——存档值域 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.rerank.moark_reranker.xǁMoarkRerankerProviderǁ_rank_chunk__mutmut_90 | A | band 三档判定/阈值/字面量全变体（None/and/or/XX/大写/边界/越界）：拍板「只用排序不用 band」（M18-M20 官方 band 与 rubric 分带不对齐）——band 无生产行为消费方（writer 仅消费 rank_score 与阈值明细；inject band 键面无断言先例）——明细值域 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.rerank.moark_reranker.xǁMoarkRerankerProviderǁ_rank_chunk__mutmut_91 | A | band 三档判定/阈值/字面量全变体（None/and/or/XX/大写/边界/越界）：拍板「只用排序不用 band」（M18-M20 官方 band 与 rubric 分带不对齐）——band 无生产行为消费方（writer 仅消费 rank_score 与阈值明细；inject band 键面无断言先例）——明细值域 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.rerank.moark_reranker.xǁMoarkRerankerProviderǁ_rank_chunk__mutmut_92 | A | band 三档判定/阈值/字面量全变体（None/and/or/XX/大写/边界/越界）：拍板「只用排序不用 band」（M18-M20 官方 band 与 rubric 分带不对齐）——band 无生产行为消费方（writer 仅消费 rank_score 与阈值明细；inject band 键面无断言先例）——明细值域 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.rerank.moark_reranker.xǁMoarkRerankerProviderǁ_rank_chunk__mutmut_93 | A | band 三档判定/阈值/字面量全变体（None/and/or/XX/大写/边界/越界）：拍板「只用排序不用 band」（M18-M20 官方 band 与 rubric 分带不对齐）——band 无生产行为消费方（writer 仅消费 rank_score 与阈值明细；inject band 键面无断言先例）——明细值域 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.rerank.moark_reranker.xǁMoarkRerankerProviderǁ_rank_chunk__mutmut_94 | A | band 三档判定/阈值/字面量全变体（None/and/or/XX/大写/边界/越界）：拍板「只用排序不用 band」（M18-M20 官方 band 与 rubric 分带不对齐）——band 无生产行为消费方（writer 仅消费 rank_score 与阈值明细；inject band 键面无断言先例）——明细值域 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.rerank.moark_reranker.xǁMoarkRerankerProviderǁ_rank_chunk__mutmut_95 | A | band 三档判定/阈值/字面量全变体（None/and/or/XX/大写/边界/越界）：拍板「只用排序不用 band」（M18-M20 官方 band 与 rubric 分带不对齐）——band 无生产行为消费方（writer 仅消费 rank_score 与阈值明细；inject band 键面无断言先例）——明细值域 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.rerank.moark_reranker.xǁMoarkRerankerProviderǁ_rank_chunk__mutmut_96 | A | band 三档判定/阈值/字面量全变体（None/and/or/XX/大写/边界/越界）：拍板「只用排序不用 band」（M18-M20 官方 band 与 rubric 分带不对齐）——band 无生产行为消费方（writer 仅消费 rank_score 与阈值明细；inject band 键面无断言先例）——明细值域 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.rerank.moark_reranker.xǁMoarkRerankerProviderǁ_rank_chunk__mutmut_97 | A | band 三档判定/阈值/字面量全变体（None/and/or/XX/大写/边界/越界）：拍板「只用排序不用 band」（M18-M20 官方 band 与 rubric 分带不对齐）——band 无生产行为消费方（writer 仅消费 rank_score 与阈值明细；inject band 键面无断言先例）——明细值域 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.rerank.moark_reranker.xǁMoarkRerankerProviderǁ_rank_chunk__mutmut_98 | A | band 三档判定/阈值/字面量全变体（None/and/or/XX/大写/边界/越界）：拍板「只用排序不用 band」（M18-M20 官方 band 与 rubric 分带不对齐）——band 无生产行为消费方（writer 仅消费 rank_score 与阈值明细；inject band 键面无断言先例）——明细值域 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.rerank.moark_reranker.xǁMoarkRerankerProviderǁ_rank_chunk__mutmut_99 | A | band 三档判定/阈值/字面量全变体（None/and/or/XX/大写/边界/越界）：拍板「只用排序不用 band」（M18-M20 官方 band 与 rubric 分带不对齐）——band 无生产行为消费方（writer 仅消费 rank_score 与阈值明细；inject band 键面无断言先例）——明细值域 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.rerank.moark_reranker.xǁMoarkRerankerProviderǁ_rank_chunk__mutmut_100 | A | band 三档判定/阈值/字面量全变体（None/and/or/XX/大写/边界/越界）：拍板「只用排序不用 band」（M18-M20 官方 band 与 rubric 分带不对齐）——band 无生产行为消费方（writer 仅消费 rank_score 与阈值明细；inject band 键面无断言先例）——明细值域 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.rerank.moark_reranker.xǁMoarkRerankerProviderǁ_rank_chunk__mutmut_101 | A | band 三档判定/阈值/字面量全变体（None/and/or/XX/大写/边界/越界）：拍板「只用排序不用 band」（M18-M20 官方 band 与 rubric 分带不对齐）——band 无生产行为消费方（writer 仅消费 rank_score 与阈值明细；inject band 键面无断言先例）——明细值域 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.rerank.moark_reranker.xǁMoarkRerankerProviderǁ_rank_chunk__mutmut_102 | A | band 三档判定/阈值/字面量全变体（None/and/or/XX/大写/边界/越界）：拍板「只用排序不用 band」（M18-M20 官方 band 与 rubric 分带不对齐）——band 无生产行为消费方（writer 仅消费 rank_score 与阈值明细；inject band 键面无断言先例）——明细值域 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.rerank.moark_reranker.xǁMoarkRerankerProviderǁ_rank_chunk__mutmut_103 | A | band 三档判定/阈值/字面量全变体（None/and/or/XX/大写/边界/越界）：拍板「只用排序不用 band」（M18-M20 官方 band 与 rubric 分带不对齐）——band 无生产行为消费方（writer 仅消费 rank_score 与阈值明细；inject band 键面无断言先例）——明细值域 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.rerank.moark_reranker.xǁMoarkRerankerProviderǁ_rank_chunk__mutmut_104 | A | band 三档判定/阈值/字面量全变体（None/and/or/XX/大写/边界/越界）：拍板「只用排序不用 band」（M18-M20 官方 band 与 rubric 分带不对齐）——band 无生产行为消费方（writer 仅消费 rank_score 与阈值明细；inject band 键面无断言先例）——明细值域 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.rerank.moark_reranker.xǁMoarkRerankerProviderǁ_rank_chunk__mutmut_108 | A | band=None：同上拍板域——band 明细值域 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.rerank.moark_reranker.xǁMoarkRerankerProviderǁ_rank_chunk__mutmut_109 | A | provider=None：RankedResult.provider 归因值域（writer/hot 只读 id/score/band；rank_call_log.provider 出自 self.name 非该字段）——归因值域 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.rerank.moark_reranker.xǁMoarkRerankerProviderǁ_rank_chunk__mutmut_110 | A | raw=None/raw 实参移除（default_factory=dict 兜底）：RankedResult.raw 不落库（writer/hot 均不持久化 rank raw）——内存存档值域 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.rerank.moark_reranker.xǁMoarkRerankerProviderǁ_rank_chunk__mutmut_116 | A | raw=None/raw 实参移除（default_factory=dict 兜底）：RankedResult.raw 不落库（writer/hot 均不持久化 rank raw）——内存存档值域 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.rerank.moark_reranker.xǁMoarkRerankerProviderǁ_rank_chunk__mutmut_118 | A | round(norm,1)→None/单参/2：舍入位数无条款（×100 归一化已发生；int/float 数值在阈值比较与明细域等价——施加必活验证）——数值形态域 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.rerank.moark_reranker.xǁMoarkRerankerProviderǁ_rank_chunk__mutmut_120 | A | round(norm,1)→None/单参/2：舍入位数无条款（×100 归一化已发生；int/float 数值在阈值比较与明细域等价——施加必活验证）——数值形态域 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.rerank.moark_reranker.xǁMoarkRerankerProviderǁ_rank_chunk__mutmut_121 | A | round(norm,1)→None/单参/2：舍入位数无条款（×100 归一化已发生；int/float 数值在阈值比较与明细域等价——施加必活验证）——数值形态域 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.rerank.moark_reranker.xǁMoarkRerankerProviderǁ_rank_chunk__mutmut_122 | A | raw dict relevance_score/model 键值变体：同 m110 域——内存存档键值域 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.rerank.moark_reranker.xǁMoarkRerankerProviderǁ_rank_chunk__mutmut_123 | A | raw dict relevance_score/model 键值变体：同 m110 域——内存存档键值域 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.rerank.moark_reranker.xǁMoarkRerankerProviderǁ_rank_chunk__mutmut_124 | A | raw dict relevance_score/model 键值变体：同 m110 域——内存存档键值域 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.rerank.moark_reranker.xǁMoarkRerankerProviderǁ_rank_chunk__mutmut_125 | A | raw dict relevance_score/model 键值变体：同 m110 域——内存存档键值域 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.rerank.moark_reranker.xǁMoarkRerankerProviderǁ_rank_chunk__mutmut_126 | A | raw dict relevance_score/model 键值变体：同 m110 域——内存存档键值域 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.rerank.moark_reranker.xǁMoarkRerankerProviderǁ_rank_chunk__mutmut_127 | A | raw dict relevance_score/model 键值变体：同 m110 域——内存存档键值域 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.rerank.moark_reranker.xǁMoarkRerankerProviderǁ_rank_chunk__mutmut_128 | A | raw dict relevance_score/model 键值变体：同 m110 域——内存存档键值域 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |

### app.search.base

#### search.base.HTTPSearchProvider._post_json（传输层）（A 7）

| mutant 全名 | 类别 | 一句话理由 | 依据条款或推理 |
|---|---|---|---|
| app.search.base.xǁHTTPSearchProviderǁ_post_json__mutmut_14 | A | 429 错误消息 SearchError(None)/scrub(None)/[:301]：异常类型与 retryable 不变，消息文案/截断界无条款——异常文案域（文案先例族） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.search.base.xǁHTTPSearchProviderǁ_post_json__mutmut_15 | A | 429 错误消息 SearchError(None)/scrub(None)/[:301]：异常类型与 retryable 不变，消息文案/截断界无条款——异常文案域（文案先例族） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.search.base.xǁHTTPSearchProviderǁ_post_json__mutmut_16 | A | 429 错误消息 SearchError(None)/scrub(None)/[:301]：异常类型与 retryable 不变，消息文案/截断界无条款——异常文案域（文案先例族） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.search.base.xǁHTTPSearchProviderǁ_post_json__mutmut_21 | A | ≥400 错误消息 None/scrub(None)/[:301]：同 m14 域——异常文案域 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.search.base.xǁHTTPSearchProviderǁ_post_json__mutmut_22 | A | ≥400 错误消息 None/scrub(None)/[:301]：同 m14 域——异常文案域 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.search.base.xǁHTTPSearchProviderǁ_post_json__mutmut_23 | A | ≥400 错误消息 None/scrub(None)/[:301]：同 m14 域——异常文案域 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.search.base.xǁHTTPSearchProviderǁ_post_json__mutmut_24 | A | 非 JSON 错误消息 None：异常类型不变（SearchError 照抛）——异常文案域 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |

### app.search.bocha

#### search.bocha.BochaSearchProvider.__init__（构造）（A 3）

| mutant 全名 | 类别 | 一句话理由 | 依据条款或推理 |
|---|---|---|---|
| app.search.bocha.xǁBochaSearchProviderǁ__init____mutmut_10 | A | 缺 Key 错误文案 XX/小写/大写：文案措辞无条款（C1-7/jev_rank m5 先例——test_bocha_missing_api_key_rejected 仅断言类型化 SearchError） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.search.bocha.xǁBochaSearchProviderǁ__init____mutmut_11 | A | 缺 Key 错误文案 XX/小写/大写：文案措辞无条款（C1-7/jev_rank m5 先例——test_bocha_missing_api_key_rejected 仅断言类型化 SearchError） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.search.bocha.xǁBochaSearchProviderǁ__init____mutmut_12 | A | 缺 Key 错误文案 XX/小写/大写：文案措辞无条款（C1-7/jev_rank m5 先例——test_bocha_missing_api_key_rejected 仅断言类型化 SearchError） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |

#### search.bocha.BochaSearchProvider._search（请求构造与响应解析）（A 16）

| mutant 全名 | 类别 | 一句话理由 | 依据条款或推理 |
|---|---|---|---|
| app.search.bocha.xǁBochaSearchProviderǁ_search__mutmut_20 | A | summary 读取键 None/XX/大写：生产调用链（pipeline）恒不传 summary → 恒走缺省 True 恰等价（实参变异恒替换判例；显式 summary 覆写域=opts 契约测试隔离面） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.search.bocha.xǁBochaSearchProviderǁ_search__mutmut_24 | A | summary 读取键 None/XX/大写：生产调用链（pipeline）恒不传 summary → 恒走缺省 True 恰等价（实参变异恒替换判例；显式 summary 覆写域=opts 契约测试隔离面） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.search.bocha.xǁBochaSearchProviderǁ_search__mutmut_25 | A | summary 读取键 None/XX/大写：生产调用链（pipeline）恒不传 summary → 恒走缺省 True 恰等价（实参变异恒替换判例；显式 summary 覆写域=opts 契约测试隔离面） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.search.bocha.xǁBochaSearchProviderǁ_search__mutmut_30 | A | freshness 缺省值 None/单参/XX/小写/大写：仅 opts 缺键域可达，freshness 服务端生效实测无效已备案（M8-M13 备案——配置传入契约只锚配置值透传非缺省值）——服务端忽略域参数缺省（任务书 A 形态明示） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.search.bocha.xǁBochaSearchProviderǁ_search__mutmut_32 | A | freshness 缺省值 None/单参/XX/小写/大写：仅 opts 缺键域可达，freshness 服务端生效实测无效已备案（M8-M13 备案——配置传入契约只锚配置值透传非缺省值）——服务端忽略域参数缺省（任务书 A 形态明示） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.search.bocha.xǁBochaSearchProviderǁ_search__mutmut_35 | A | freshness 缺省值 None/单参/XX/小写/大写：仅 opts 缺键域可达，freshness 服务端生效实测无效已备案（M8-M13 备案——配置传入契约只锚配置值透传非缺省值）——服务端忽略域参数缺省（任务书 A 形态明示） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.search.bocha.xǁBochaSearchProviderǁ_search__mutmut_36 | A | freshness 缺省值 None/单参/XX/小写/大写：仅 opts 缺键域可达，freshness 服务端生效实测无效已备案（M8-M13 备案——配置传入契约只锚配置值透传非缺省值）——服务端忽略域参数缺省（任务书 A 形态明示） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.search.bocha.xǁBochaSearchProviderǁ_search__mutmut_37 | A | freshness 缺省值 None/单参/XX/小写/大写：仅 opts 缺键域可达，freshness 服务端生效实测无效已备案（M8-M13 备案——配置传入契约只锚配置值透传非缺省值）——服务端忽略域参数缺省（任务书 A 形态明示） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.search.bocha.xǁBochaSearchProviderǁ_search__mutmut_46 | A | Authorization 键小写/大写：httpx 头名大小写不敏感线格式恒等——HTTP 头形态等价 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.search.bocha.xǁBochaSearchProviderǁ_search__mutmut_47 | A | Authorization 键小写/大写：httpx 头名大小写不敏感线格式恒等——HTTP 头形态等价 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.search.bocha.xǁBochaSearchProviderǁ_search__mutmut_48 | A | Content-Type 键 XX：http_client 出口 post 同走 json= 自动头（httpx 对 json= 自动携带 Content-Type: application/json），显式键名变异被自动头兜底——恰等价（C2-4 embedding.moark m25 实测新判例同构） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.search.bocha.xǁBochaSearchProviderǁ_search__mutmut_49 | A | Content-Type 键小写/大写：同 m46 域——头形态等价 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.search.bocha.xǁBochaSearchProviderǁ_search__mutmut_50 | A | Content-Type 键小写/大写：同 m46 域——头形态等价 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.search.bocha.xǁBochaSearchProviderǁ_search__mutmut_60 | A | 响应异常 SearchError(None)/str(None)/[:301]：异常类型不变（pipeline 按类型走 error 账行）——异常文案域（文案先例族） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.search.bocha.xǁBochaSearchProviderǁ_search__mutmut_61 | A | 响应异常 SearchError(None)/str(None)/[:301]：异常类型不变（pipeline 按类型走 error 账行）——异常文案域（文案先例族） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.search.bocha.xǁBochaSearchProviderǁ_search__mutmut_62 | A | 响应异常 SearchError(None)/str(None)/[:301]：异常类型不变（pipeline 按类型走 error 账行）——异常文案域（文案先例族） | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |

### app.search.pipeline

#### search.pipeline.fetch_search_source（搜索通道装配）（A 21）

| mutant 全名 | 类别 | 一句话理由 | 依据条款或推理 |
|---|---|---|---|
| app.search.pipeline.x_fetch_search_source__mutmut_112 | A | error 账行 result_count/latency_ms None/实参移除：列 default=0 兜底（models 实证；C1-8 m55/56/63/64 同函数同列判据族）——列缺省承载恰等价 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.search.pipeline.x_fetch_search_source__mutmut_113 | A | error 账行 result_count/latency_ms None/实参移除：列 default=0 兜底（models 实证；C1-8 m55/56/63/64 同函数同列判据族）——列缺省承载恰等价 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.search.pipeline.x_fetch_search_source__mutmut_120 | A | error 账行 result_count/latency_ms None/实参移除：列 default=0 兜底（models 实证；C1-8 m55/56/63/64 同函数同列判据族）——列缺省承载恰等价 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.search.pipeline.x_fetch_search_source__mutmut_121 | A | error 账行 result_count/latency_ms None/实参移除：列 default=0 兜底（models 实证；C1-8 m55/56/63/64 同函数同列判据族）——列缺省承载恰等价 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.search.pipeline.x_fetch_search_source__mutmut_131 | A | error 截断界 [:500]→[:501]：截断界数值无条款（rank.base m69/providers m42 界值先例族）——界值域 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.search.pipeline.x_fetch_search_source__mutmut_139 | A | ok 账行 ok=None/status=None/实参移除：列 default=True/"ok" 兜底（models 实证；rerank.base m78/79 先例）——列缺省承载恰等价 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.search.pipeline.x_fetch_search_source__mutmut_140 | A | ok 账行 ok=None/status=None/实参移除：列 default=True/"ok" 兜底（models 实证；rerank.base m78/79 先例）——列缺省承载恰等价 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.search.pipeline.x_fetch_search_source__mutmut_146 | A | ok 账行 ok=None/status=None/实参移除：列 default=True/"ok" 兜底（models 实证；rerank.base m78/79 先例）——列缺省承载恰等价 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.search.pipeline.x_fetch_search_source__mutmut_147 | A | ok 账行 ok=None/status=None/实参移除：列 default=True/"ok" 兜底（models 实证；rerank.base m78/79 先例）——列缺省承载恰等价 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.search.pipeline.x_fetch_search_source__mutmut_155 | A | stats.extra["latency_ms"] 值/键变体：stats.extra 诊断镜像键面（账本行本体已由 C 测试断言；C1-8 m152-154 同函数判据族）——诊断镜像键面 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.search.pipeline.x_fetch_search_source__mutmut_156 | A | stats.extra["latency_ms"] 值/键变体：stats.extra 诊断镜像键面（账本行本体已由 C 测试断言；C1-8 m152-154 同函数判据族）——诊断镜像键面 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.search.pipeline.x_fetch_search_source__mutmut_157 | A | stats.extra["latency_ms"] 值/键变体：stats.extra 诊断镜像键面（账本行本体已由 C 测试断言；C1-8 m152-154 同函数判据族）——诊断镜像键面 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.search.pipeline.x_fetch_search_source__mutmut_182 | A | fp 三元 or True 恒真：guid 非空 ⇔ url 非空 ⇔ fingerprint 恒非空（normalize_url/url_fingerprint 实证链），else 死分支不可达——死分支等价 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.search.pipeline.x_fetch_search_source__mutmut_201 | A | fetched_at=None：Item.fetched_at 列 default=utcnow 兜底（models 实证；C3-4 m87 列缺省吸收判例族）——列缺省承载恰等价 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.search.pipeline.x_fetch_search_source__mutmut_216 | A | guid[:1000]/url[:2000]/title[:2000] 截断界 +1：截断界数值无条款（providers m42/scoring m51 界值先例族；SQLite 不强制 VARCHAR 界）——界值域 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.search.pipeline.x_fetch_search_source__mutmut_217 | A | guid[:1000]/url[:2000]/title[:2000] 截断界 +1：截断界数值无条款（providers m42/scoring m51 界值先例族；SQLite 不强制 VARCHAR 界）——界值域 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.search.pipeline.x_fetch_search_source__mutmut_218 | A | guid[:1000]/url[:2000]/title[:2000] 截断界 +1：截断界数值无条款（providers m42/scoring m51 界值先例族；SQLite 不强制 VARCHAR 界）——界值域 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.search.pipeline.x_fetch_search_source__mutmut_220 | A | datetime.now(None)（naive 本地时钟）：存储 tz 形态未钉（web __published_date m112「存储 tz 未钉（D16 仅钉日切口径）」先例+C1-8 m212 同函数孪生判据；CI/部署矩阵 TZ=UTC 宿主墙钟同值）——时钟形态域沿先例 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.search.pipeline.x_fetch_search_source__mutmut_227 | A | apply_rules title 实参 None：apply_rules 内 title 仅参与黑名单 joined 串，管线调用恒不传 blacklist（恒 []）→ title 不可观察（调用点核查）——实参死参等价 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.search.pipeline.x_fetch_search_source__mutmut_241 | A | fetch_status="FETCHED"→None：Item.fetch_status 列 default="FETCHED" 兜底（models 实证；C2-3 实证显式 None 触发列 default 判例族）——列缺省承载恰等价 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |
| app.search.pipeline.x_fetch_search_source__mutmut_255 | A | SanitizeTarget url 实参移除：sanitize 链两阶段（注入特征/关键词拒绝）均只扫 title+content（build_chain 实证），url 无阶段消费方——死参等价 | 等价/不可达或条款未钉（C1/C2/C3 判据族沿用） |

## C3 D 类拍板登记（2026-10-08 用户拍板·6 条 A）

| mutant 全名 | 类别 | 一句话理由 | 依据条款或推理 |
|---|---|---|---|
| app.retrieval.embedder.x_embed_input_text__mutmut_12 | A | 空标题（合法值）嵌入输入多前导换行——标题保留条款不钉空标题形态，输入文本差异无条款 | 探索/嵌入输入形态无条款（D 类拍板 #6 判 A） |
| app.retrieval.explore.x_explore_params__mutmut_22 | A | floor 兜底 or 50→51 仅显式 set 0 的 falsy 域可达，生产恒回退 DEFAULTS 域等价 | falsy 配置语义无条款（拍板 #6 判 A；DEFAULTS 恒回退判例族） |
| app.retrieval.explore.x_explore_params__mutmut_33 | A | percentile 兜底 or 5→6 同上 | 同上 |
| app.retrieval.explore.x_explore_params__mutmut_44 | A | quota 兜底 or 3→4 同上 | 同上 |
| app.retrieval.explore.x_explore_pick__mutmut_94 | A | MMR 权重 (1-λ)→(1+λ)——λ 已 site_config 化（管理员可调调试位，默认 0.3），常量缺省变体属回退值域 | 拍板 #7 判 A + λ 配置位化（本批落地） |
| app.retrieval.explore.x_explore_pick__mutmut_95 | A | (1-λ)→(2-λ) 同上 | 同上 |
