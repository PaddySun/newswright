# 变异测试豁免清单（tests/mutation_exemptions.md）

> T1 分诊批次 1（认证域）登记。类别：A = 等价变异（不改变任何可观察行为）；
> B = 防御分支（正常运行不可触达，设计书明确要求其存在）。
> 依据任务书 `doc/CI0/CI0-分诊批次1-任务书.md` §2；裁决依据为两份正式设计书 v1.4。
> C 类（测试缺口）与 D 类（设计模糊）**不在本清单**：C 类由 `tests/test_mutation_t1.py`
> 补测试击杀，D 类交统筹（见执行汇报 §3）。

## 批次 1：认证域（14 A + 1 B = 15 条）

| mutant 全名 | 类别 | 一句话理由 | 依据条款或推理 |
|---|---|---|---|
| app.api.deps.x_get_client_ip__mutmut_16 | A | `"unknown"`→`"XXunknownXX"`：该返回值仅作限速器内部 key，不出现在任何响应/持久化中，全体一致即可 | 返回值不跨出进程内字典；限速行为（AC-01.2）不受 key 字面影响 |
| app.api.deps.x_get_client_ip__mutmut_17 | A | 同上（`"UNKNOWN"` 大写变体） | 同上 |
| app.api.deps.xǁLoginRateLimiterǁ__init____mutmut_5 | A | `datetime.now(timezone.utc)`→`datetime.now(None)`：naive 本地时间，但锁定期比较两端均出自同一时钟源，自洽无跨时钟比对 | `now` 为唯一时钟源（注入即整体替换）；进程内字典不持久化（ADR-2 单机单进程），重启清零 |
| app.api.deps.xǁLoginRateLimiterǁallow__mutmut_14 | A | `pop(key, None)`→`pop(key,)`：该分支由 `rec = self._store.get(key)` 非 None 保证 key 必在字典，default 参数不可达 | 代码路径推理：`allow` 先 get 后 pop，同 key 无并发删除（单进程 ADR-2） |
| app.api.deps.xǁLoginRateLimiterǁrecord_failure__mutmut_9 | A | 初始 dict 键 `"locked_until"`→`"XXlocked_untilXX"`：初始 None 值从不被读取差异——`allow` 读真实键得 None 即"未锁"，锁定由第 5 次失败对真实键直接赋值 | 行为等价推理：`rec["locked_until"] = ...`（record_failure 内）不受初始 dict 键名影响 |
| app.api.deps.xǁLoginRateLimiterǁrecord_failure__mutmut_10 | A | 同上（`"LOCKED_UNTIL"` 变体） | 同上 |
| app.api.deps.x_require_session__mutmut_18 | A | 401 message 文本 `"未认证"`→`"XX未认证XX"`：设计书只钉 code（`AUTH_REQUIRED`），未规定该字段措辞 | AC-01.3（只钉 code）+ A 类判据"异常消息文本（设计书未规定其措辞）" |
| app.api.deps.x_require_session__mutmut_30 | A | 403 message 文本变体：同上，设计书只钉 code（`PASSWORD_CHANGE_REQUIRED`） | AC-01.1（只钉 code）；措辞无条款 |
| app.auth.x_issue_session__mutmut_8 | A | `token_urlsafe(32)`→`token_urlsafe(None)`：nbytes=None 走库默认值恰为 32 字节，熵与格式完全相同 | 等价：`secrets.token_urlsafe` 签名默认 nbytes=32 |
| app.auth.x_issue_session__mutmut_9 | A | `token_urlsafe(32)`→`token_urlsafe(33)`：33 字节 ≈ 264bit，仍满足"id ≥128bit 随机"；id 为不透明 cookie 值，长度无条款约束 | 函数 docstring 条款「id ≥128bit 随机」仍满足；断言精确长度属与设计书无关的断言（禁写） |
| app.auth.x_bootstrap_admin__mutmut_9 | A | 删除 `must_change_password=True,` 行：SQLAlchemy 列级 `default=True` 在 flush 时补齐，落库值不变（已实证：flush 后读回 True） | app/models.py User.must_change_password `default=True`（AC-01.1 语义由列默认承载） |
| app.auth.x_bootstrap_admin__mutmut_15 | A | `log.info(...)`→`log.info(None)`：日志行内容变化，设计书未规定该行存在与文案 | ADR-12 规定日志格式/级别纪律，未规定此 INFO 行文案；INFO=轮次里程碑非错误契约 |
| app.auth.x_bootstrap_admin__mutmut_16 | A | log 文本 XX 包裹变体：同上 | 同上 |
| app.auth.x_bootstrap_admin__mutmut_17 | A | log 文本 `"admin"`→`"ADMIN"` 变体：同上 | 同上 |
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
| app.providers.base.xǁLLMProviderǁ_call__mutmut_98 | A | 最终 ProviderError 消息中 last_err→None：异常消息文本无措辞条款，失败原因已由账本 error 字段承载 | ProviderError 消息内容无条款；账本 error 列另有测试锁定 |
| app.providers.base.xǁLLMProviderǁ_call__mutmut_109 | A | getattr(e,"retryable",False) 默认值 False→True：httpx 错误被 isinstance 短路、ProviderError 恒有 retryable 类属性，默认不可达 | 控制流推理 |
| app.providers.base.xǁLLMProviderǁ_call__mutmut_129 | A | error 路径 payload.get("model", 缺省) 缺省变体——同 m45 组 | 同 m45 组 |
| app.providers.base.xǁLLMProviderǁ_call__mutmut_130 | A | error 路径 payload.get("model", 缺省) 缺省变体——同 m45 组 | 同 m45 组 |
| app.providers.base.xǁLLMProviderǁ_call__mutmut_131 | A | error 路径 payload.get("model", 缺省) 缺省变体——同 m45 组 | 同 m45 组 |
| app.providers.base.xǁLLMProviderǁ_call__mutmut_134 | A | error 路径 payload.get("model", 缺省) 缺省变体——同 m45 组 | 同 m45 组 |
| app.providers.base.xǁLLMProviderǁ_call__mutmut_135 | A | error 路径 getattr 默认值变体——同 m109 | 同 m109 |
| app.providers.base.xǁLLMProviderǁ_call__mutmut_136 | A | error 文本前缀 type(e)→type(None)（"NoneType: …"）：仍含完整原因文本，账本 error 落账语义满足，文本格式无条款 | 账本 error 语义=记录原因（DT-5），格式无条款 |
| app.providers.base.xǁLLMProviderǁ_call__mutmut_144 | A | log.warning 文案/实参变异（重试日志行）——D12 未规定该行内容与措辞 | ADR-12 只钉级别纪律与结构化字段，未钉业务日志文案 |
| app.providers.base.xǁLLMProviderǁ_call__mutmut_145 | A | log.warning 文案/实参变异（重试日志行）——D12 未规定该行内容与措辞 | ADR-12 只钉级别纪律与结构化字段，未钉业务日志文案 |
| app.providers.base.xǁLLMProviderǁ_call__mutmut_146 | A | log.warning 文案/实参变异（重试日志行）——D12 未规定该行内容与措辞 | ADR-12 只钉级别纪律与结构化字段，未钉业务日志文案 |
| app.providers.base.xǁLLMProviderǁ_call__mutmut_147 | A | log.warning 文案/实参变异（重试日志行）——D12 未规定该行内容与措辞 | ADR-12 只钉级别纪律与结构化字段，未钉业务日志文案 |
| app.providers.base.xǁLLMProviderǁ_call__mutmut_148 | A | log.warning 文案/实参变异（重试日志行）——D12 未规定该行内容与措辞 | ADR-12 只钉级别纪律与结构化字段，未钉业务日志文案 |
| app.providers.base.xǁLLMProviderǁ_call__mutmut_149 | A | log.warning 文案/实参变异（重试日志行）——D12 未规定该行内容与措辞 | ADR-12 只钉级别纪律与结构化字段，未钉业务日志文案 |
| app.providers.base.xǁLLMProviderǁ_call__mutmut_150 | A | log.warning 文案/实参变异（重试日志行）——D12 未规定该行内容与措辞 | ADR-12 只钉级别纪律与结构化字段，未钉业务日志文案 |
| app.providers.base.xǁLLMProviderǁ_call__mutmut_151 | A | log.warning 文案/实参变异（重试日志行）——D12 未规定该行内容与措辞 | ADR-12 只钉级别纪律与结构化字段，未钉业务日志文案 |
| app.providers.base.xǁLLMProviderǁ_call__mutmut_152 | A | log.warning 文案/实参变异（重试日志行）——D12 未规定该行内容与措辞 | ADR-12 只钉级别纪律与结构化字段，未钉业务日志文案 |
| app.providers.base.xǁLLMProviderǁ_call__mutmut_153 | A | log.warning 文案/实参变异（重试日志行）——D12 未规定该行内容与措辞 | ADR-12 只钉级别纪律与结构化字段，未钉业务日志文案 |
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
| app.db.x__migrate_added_columns__mutmut_5 | A | additions 表键 "source"→"SOURCE"：SQLite 标识符大小写不敏感（实测 has_table/get_columns/ALTER 全部照常命中），补列行为等价 | ADR-1（生产引擎=SQLite）+ 实测探针 |
| app.db.x__migrate_added_columns__mutmut_23 | A | 表键 "author"→"AUTHOR"：同上 | 同 m5 |
| app.db.x__migrate_added_columns__mutmut_42 | A | 表键 "write_run"→"WRITE_RUN"：同上 | 同 m5 |
| app.db.x__migrate_added_columns__mutmut_48 | A | 表键 "usage_log"→"USAGE_LOG"：同上 | 同 m5 |
| app.db.x__migrate_added_columns__mutmut_9 | A | DDL "INTEGER NOT NULL DEFAULT 0"→全小写：SQLite 关键字/类型名大小写不敏感（实测默认值 0 照常生效） | 同 m5 |
| app.db.x__migrate_added_columns__mutmut_13 | A | DDL 小写变体（backoff_skips）：同上 | 同 m5 |
| app.db.x__migrate_added_columns__mutmut_17 | A | 类型 "JSON"→"json"：类型名大小写不敏感，同为 NUMERIC 亲和 | 同 m5 |
| app.db.x__migrate_added_columns__mutmut_21 | A | DDL "varchar(64)" 小写：同上，TEXT 亲和不变 | 同 m5 |
| app.db.x__migrate_added_columns__mutmut_27 | A | DDL "varchar(30) not null default 'none'" 小写：关键字不敏感且默认值 'none' 原样保留 | 同 m5 |
| app.db.x__migrate_added_columns__mutmut_32 | A | DDL "integer not null default 30" 小写：同上 | 同 m5 |
| app.db.x__migrate_added_columns__mutmut_36 | A | DDL "boolean not null default 0" 小写：BOOLEAN 与 boolean 同为 NUMERIC 亲和 | 同 m5 |
| app.db.x__migrate_added_columns__mutmut_40 | A | 类型 "author_json": "json" 小写：同 m17 | 同 m5 |
| app.db.x__migrate_added_columns__mutmut_46 | A | 类型 "payload": "json" 小写：同 m17 | 同 m5 |
| app.db.x__migrate_added_columns__mutmut_52 | A | DDL 小写（cache_hit_tokens）：同 m9 | 同 m5 |
| app.db.x__migrate_added_columns__mutmut_56 | A | DDL 小写（reasoning_tokens）：同 m9 | 同 m5 |
| app.db.x__migrate_added_columns__mutmut_60 | A | DDL "varchar(40)" 小写（finish_reason）：同 m21 | 同 m5 |
| app.db.x__migrate_added_columns__mutmut_64 | A | 类型 "item_count": "integer" 小写：同 m9 | 同 m5 |
| app.db.x__migrate_added_columns__mutmut_70 | A | DDL "varchar(20) not null default 'pending'" 小写：关键字小写等价且默认值 'PENDING' 原样保留（值大小写敏感项未变） | 同 m5 |
| app.db.x__migrate_added_columns__mutmut_74 | A | DDL "varchar(500)" 小写（sanitize_reason）：同 m21 | 同 m5 |
| app.db.x__migrate_added_columns__mutmut_78 | A | 类型 "sanitize_detail": "json" 小写：同 m17 | 同 m5 |
| app.db.x__migrate_added_columns__mutmut_82 | A | 类型 "raw": "json" 小写：同 m17 | 同 m5 |
| app.db.x__migrate_added_columns__mutmut_86 | A | 类型 "direction_id": "integer" 小写：同 m9 | 同 m5 |
| app.db.x__migrate_added_columns__mutmut_90 | A | DDL "varchar(64)" 小写（fingerprint）：同 m21 | 同 m5 |
| app.db.x__migrate_added_columns__mutmut_94 | A | 类型 "duplicate_of": "integer" 小写：同 m9 | 同 m5 |
| app.db.x__migrate_added_columns__mutmut_16 | A | 类型 "JSON"→"XXJSONXX"：SQLite 接受任意类型名，"XXJSONXX" 与 "JSON" 同为 NUMERIC 亲和（实测 JSON 序列化存取无差）；带括号/带约束的 XX 变体属语法错误归 C | 同 m5 + 亲和性实测 |
| app.db.x__migrate_added_columns__mutmut_39 | A | 类型 "author_json": "XXJSONXX"：同 m16 | 同 m16 |
| app.db.x__migrate_added_columns__mutmut_45 | A | 类型 "payload": "XXJSONXX"：同 m16 | 同 m16 |
| app.db.x__migrate_added_columns__mutmut_77 | A | 类型 "sanitize_detail": "XXJSONXX"：同 m16 | 同 m16 |
| app.db.x__migrate_added_columns__mutmut_81 | A | 类型 "raw": "XXJSONXX"：同 m16 | 同 m16 |
| app.db.x__migrate_added_columns__mutmut_63 | A | 类型 "item_count": "XXINTEGERXX"：类型名含 "INT" 仍判 INTEGER 亲和，等价 | 同 m16 |
| app.db.x__migrate_added_columns__mutmut_85 | A | 类型 "direction_id": "XXINTEGERXX"：同 m63 | 同 m63 |
| app.db.x__migrate_added_columns__mutmut_93 | A | 类型 "duplicate_of": "XXINTEGERXX"：同 m63 | 同 m63 |
| app.db.x__migrate_added_columns__mutmut_95 | A | backfill_sanitize 初始 False→None：同为假值，触发路径仍由 `=True` 置位，回填行为等价 | 控制流等价推理 |
| app.db.x__migrate_added_columns__mutmut_99 | A | 缺表 continue→break：唯一调用点 init_db 中 create_all 先行保证五表全存在，`not has_table` 恒假，分支不可达 | 调用点核查（同 C1-1 不可达缺省判据） |
| app.db.x__migrate_added_columns__mutmut_117 | A | log.info(None, table, col)：消息文案/实参变异，格式化异常被 logging 自吞不崩溃；ADR-12 未规定该行文案 | ADR-12（只钉级别纪律与结构化字段） |
| app.db.x__migrate_added_columns__mutmut_118 | A | log.info 实参 table→None：同上 | 同 m117 |
| app.db.x__migrate_added_columns__mutmut_119 | A | log.info 实参 col→None：同上 | 同 m117 |
| app.db.x__migrate_added_columns__mutmut_120 | A | log.info(table, col)（msg 换实参）：同上 | 同 m117 |
| app.db.x__migrate_added_columns__mutmut_121 | A | log.info 丢实参：同上 | 同 m117 |
| app.db.x__migrate_added_columns__mutmut_122 | A | log.info 丢实参变体：同上 | 同 m117 |
| app.db.x__migrate_added_columns__mutmut_123 | A | 日志文案 XX 包裹：同上 | 同 m117 |
| app.db.x__migrate_added_columns__mutmut_124 | A | 日志文案大小写变体：同上 | 同 m117 |
| app.db.x__migrate_added_columns__mutmut_127 | A | 索引分支 has_table("item")→has_table("ITEM")：SQLite 大小写不敏感（实测恒真），索引照建 | 同 m5 |
| app.db.x__migrate_added_columns__mutmut_131 | A | "CREATE INDEX IF NOT EXISTS"→小写：SQL 关键字大小写不敏感，索引名与列组合不变 | 同 m5 |
| app.db.x__migrate_added_columns__mutmut_134 | A | "ON item (direction_id, fingerprint)"→小写：同上 | 同 m5 |
| app.db.x__migrate_added_columns__mutmut_135 | A | "ON ITEM (DIRECTION_ID, FINGERPRINT)"：标识符大小写不敏感（实测 pragma_index_info 返回规范列名），索引名不变 | 同 m5 |
| app.db.x__migrate_added_columns__mutmut_139 | A | 回填 UPDATE 关键字小写：同 m131，历史行照常回填（实测） | 同 m5 |
| app.db.x__migrate_added_columns__mutmut_140 | A | "UPDATE ITEM SET SANITIZE_STATUS='PASSED'"：标识符大小写不敏感，写入值不变（实测） | 同 m5 |
| app.main.x_create_app__mutmut_2 | A | FastAPI(title=None)：§4.2 OpenAPI 契约=路径/Schema（R1「YAML 之外无契约」），info.title 为信息性元数据无条款 | R1 契约边界 + A 类判据（元数据措辞） |
| app.main.x_create_app__mutmut_3 | A | version=None：同上（info.version 元数据） | 同 m2 |
| app.main.x_create_app__mutmut_4 | A | 移除 title 实参：同上 | 同 m2 |
| app.main.x_create_app__mutmut_5 | A | 移除 version="0.1.0" 实参：FastAPI 默认 version 恰为 "0.1.0"，精确等价 | 等价：FastAPI 签名默认值 |
| app.main.x_create_app__mutmut_6 | A | title "XXnewswright-demoXX"：同 m2 | 同 m2 |
| app.main.x_create_app__mutmut_7 | A | title 大写变体：同 m2 | 同 m2 |
| app.main.x_create_app__mutmut_8 | A | version "XX0.1.0XX"：同 m3 | 同 m2 |
| app.scheduler.x__reclaim_once__mutmut_3 | A | log.info(None, n)：日志文案/实参变异，格式化异常被 logging 自吞；ADR-12 未规定该行文案 | ADR-12（只钉级别纪律与结构化字段） |
| app.scheduler.x__reclaim_once__mutmut_4 | A | log.info 实参 n→None：同上 | 同 m3 |
| app.scheduler.x__reclaim_once__mutmut_5 | A | log.info(n)（msg 换实参）：同上 | 同 m3 |
| app.scheduler.x__reclaim_once__mutmut_6 | A | log.info 丢实参：同上 | 同 m3 |
| app.scheduler.x__reclaim_once__mutmut_7 | A | 日志文案 XX 包裹：同上 | 同 m3 |
| app.scheduler.x__reclaim_once__mutmut_8 | A | 日志文案 "FAILED"→"failed"：同上 | 同 m3 |
| app.scheduler.x__reclaim_once__mutmut_9 | A | "%d"→"%D"：格式化异常被 logging 自吞，行为不变 | 同 m3 |

## 批次 4：ingest.web 定点监测带（2026-10-03，C1-3）

> 本批 210 条 = A 79 / B 0 / C 131 / D 0。C 类 131 条由 `tests/test_mutation_c1_3.py`
> 11 测试击杀（主链：304 短跳/条件头回传/条目全列/D15 指纹与 DUP/LLM 通道契约/
> 富化成本边界/sanitize 记账），不在本清单；D 类 0 条。A 类判据主轴：抽取形态与
> 请求头细节设计书未钉（任务书 §2 明示）、httpx 头名大小写归一化、SQLite 不强制
> 列宽（C1-2 生产口径）、_ingest 返回值全调用点不消费、现有 sanitizer 链不读 url。

| mutant 全名 | 类别 | 一句话理由 | 依据条款或推理 |
|---|---|---|---|
| app.ingest.web.x__content_hash__mutmut_4 | A | "utf-8"→"UTF-8"：Python codec 别名大小写不敏感，sha256 输出逐位一致（guid/变更检测语义不变） | AC-05.3 依赖哈希值本身——编解码别名恰等价 |
| app.ingest.web.x__html_title__mutmut_1 | A | 标题抽取失效（恒 ""）：item.title 来源为页面 <title> 属抽取细节，设计书未钉标题抽取形态 | 任务书 §2「抽取细节设计书未规定归 A」+ §4.1 仅钉 title 列存在 |
| app.ingest.web.x__html_title__mutmut_3 | A | if 翻转（有题返回 ""/无题 AttributeError）：同上，标题形态未钉 | 同上 |
| app.ingest.web.x__html_title__mutmut_4 | A | 无题兜底 ""→"XXXX"：标题内容未钉 | 同上 |
| app.ingest.web.x__html_title__mutmut_11 | A | 空白折叠正则 XX 化（折叠失效）：标题空白形态未钉 | 同上 |
| app.ingest.web.x__html_title__mutmut_12 | A | 折叠替换串 "XX XX"：同上 | 同上 |
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
| app.ingest.web.x_fetch_web_source__mutmut_8 | A | extraction_prompt 置 None：键未列于 §4.1 source_config（仅列 llm_extract 等），提示词内容无条款；llm_extract 关闭时不可达 | §4.1 source_config 键清单核查 + 提示词内容无条款 |
| app.ingest.web.x_fetch_web_source__mutmut_9 | A | cfg.get(None)：同上 | 同上 |
| app.ingest.web.x_fetch_web_source__mutmut_10 | A | 键 XX 变体：同上 | 同上 |
| app.ingest.web.x_fetch_web_source__mutmut_11 | A | 键大写变体：同上 | 同上 |
| app.ingest.web.x_fetch_web_source__mutmut_17 | A | ignore_page_date 置 None：键设计书全档无条款（grep 核查），仅影响未钉的页面日期抽取 | 设计书全文 grep 核查 |
| app.ingest.web.x_fetch_web_source__mutmut_18 | A | bool(None)：同上 | 同上 |
| app.ingest.web.x_fetch_web_source__mutmut_19 | A | cfg.get(None)：同上 | 同上 |
| app.ingest.web.x_fetch_web_source__mutmut_20 | A | 键 XX 变体：同上 | 同上 |
| app.ingest.web.x_fetch_web_source__mutmut_21 | A | 键大写变体：同上 | 同上 |
| app.ingest.web.x_fetch_web_source__mutmut_28 | A | "XXUser-AgentXX"：UA 请求头内容无条款（R9 UA 策略为 site_config 预留，未钉抓取头） | R9 范围核查 |
| app.ingest.web.x_fetch_web_source__mutmut_29 | A | 键 "user-agent" 小写：httpx 头名大小写归一化，线上请求恰等价 | httpx.Headers 语义 |
| app.ingest.web.x_fetch_web_source__mutmut_30 | A | 键大写变体：同上 | 同上 |
| app.ingest.web.x_fetch_web_source__mutmut_35 | A | If-Modified-Since 置 None：条件头回传未钉（模块表仅钉 etag 原样回传），断裂由 etag/哈希兜底 | 模块表 ingest/web 硬约束范围核查 |
| app.ingest.web.x_fetch_web_source__mutmut_36 | A | If-Modified-Since 键 XX 化：同上 | 同上 |
| app.ingest.web.x_fetch_web_source__mutmut_37 | A | 键小写变体：同上 | 同上 |
| app.ingest.web.x_fetch_web_source__mutmut_38 | A | 键大写变体：同上 | 同上 |
| app.ingest.web.x_fetch_web_source__mutmut_43 | A | timeout 60.0→61.0：显式超时语义不变，任意有限值满足 §4.2（同 C1-2 m1 先例） | 技术书 §4.2（只要求显式） |
| app.ingest.web.x_fetch_web_source__mutmut_55 | A | 304 路径 last_fetched_at naive（now(None)）：存储 tz 未钉（D16 仅日切） | D16 范围核查 |
| app.ingest.web.x_fetch_web_source__mutmut_58 | A | error 前缀 type(e)→type(None)：判据子串（状态码等）保留于 {e} 部分，AC-04.2 last_error 判据不受影响 | AC-04.2 判据为子串包含 |
| app.ingest.web.x_fetch_web_source__mutmut_63 | A | resp.headers.get("ETAG")：httpx.Headers 大小写不敏感，恰等价 | httpx.Headers 语义 |
| app.ingest.web.x_fetch_web_source__mutmut_66 | A | resp.headers["ETAG"]：同上 | 同上 |
| app.ingest.web.x_fetch_web_source__mutmut_72 | A | etag 截断 [:500]→[:501]：SQLite 不强制 VARCHAR 长度（C1-2 生产口径），etag 原样性不受 1 字符影响 | ADR-1（生产=SQLite）+ C1-2 先例 |
| app.ingest.web.x_fetch_web_source__mutmut_78 | A | last-modified 存储跳过（get 键 XX）：last_modified 回传/存储未钉，变更检测由 etag/哈希兜底 | 模块表硬约束范围核查 |
| app.ingest.web.x_fetch_web_source__mutmut_79 | A | get("LAST-MODIFIED")：httpx 大小写不敏感恰等价 | httpx.Headers 语义 |
| app.ingest.web.x_fetch_web_source__mutmut_80 | A | last_modified 置 None：存储未钉，条件头缺失由 etag/哈希兜底 | 同 m78 |
| app.ingest.web.x_fetch_web_source__mutmut_82 | A | ["LAST-MODIFIED"]：httpx 大小写不敏感恰等价 | httpx.Headers 语义 |
| app.ingest.web.x_fetch_web_source__mutmut_83 | A | last_modified 截断 [:501]：同 m72 | 同 m72 |
| app.ingest.web.x_fetch_web_source__mutmut_84 | A | change_type 初始 None→""：初始值必被重赋或先于读取返回，不可达 | 控制流推理 |
| app.ingest.web.x_fetch_web_source__mutmut_86 | A | etag 短跳路径 last_fetched_at naive：同 m55 | 同 m55 |
| app.ingest.web.x_fetch_web_source__mutmut_117 | A | guid 冲突分支 return False→True：_ingest 返回值所有调用点均不消费（调用点核查） | 控制流等价 |
| app.ingest.web.x_fetch_web_source__mutmut_127 | A | dup_blocked 分支 return 翻转：同上 | 同上 |
| app.ingest.web.x_fetch_web_source__mutmut_154 | A | Item title 实参删除（ORM default ""）：标题内容未钉（同 _html_title 组） | 任务书 §2 抽取细节 |
| app.ingest.web.x_fetch_web_source__mutmut_160 | A | Item fetched_at naive（now(None)）：存储 tz 未钉 | 同 m55 |
| app.ingest.web.x_fetch_web_source__mutmut_167 | A | apply_rules(title=None)：网页路径调用点 blacklist 恒空（未传），title 仅进 blacklist joined → 等价 | apply_rules 调用点核查 |
| app.ingest.web.x_fetch_web_source__mutmut_187 | A | SanitizeTarget(url=None)：现有 sanitizer 链（passthrough/KeywordDeny）不读 url 字段 | sanitize.py 调用点核查 |
| app.ingest.web.x_fetch_web_source__mutmut_190 | A | SanitizeTarget url 实参删除：同上 | 同上 |
| app.ingest.web.x_fetch_web_source__mutmut_212 | A | _ingest 成功 return True→False：返回值不消费 | 同 m117 |
| app.ingest.web.x_fetch_web_source__mutmut_223 | A | stats.failed +=1→=1：单次 fetch 内 llm 失败分支至多执行一次且 stats 每轮新建（初值 0），每轮记账等价 | 控制流等价 + 实测（failed 桶按轮） |
| app.ingest.web.x_fetch_web_source__mutmut_227 | A | 抽取失败文案 XX 包裹："web_extract: LLM 抽取两次失败" 文案无条款，内容子串保留 | 失败原因如实记录——文案无措辞条款 |
| app.ingest.web.x_fetch_web_source__mutmut_228 | A | 文案 "LLM"→"llm"：同上 | 同上 |
| app.ingest.web.x_fetch_web_source__mutmut_229 | A | 文案前缀大写变体：同上 | 同上 |
| app.ingest.web.x_fetch_web_source__mutmut_241 | A | apply_fp=False→None：假值，单页调用点显式传 False，豁免语义不变 | G1 先例（B7 豁免）语义不变 |
| app.ingest.web.x_fetch_web_source__mutmut_255 | A | ignore_page_date and False：键未钉（同 m17 组）且配置缺省时恰等价 | 同 m17 |
| app.ingest.web.x_fetch_web_source__mutmut_259 | A | 成功路径 last_fetched_at naive：同 m55 | 同 m55 |

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
| app.ingest.rss.x__entry_published__mutmut_10 | A | tzinfo=None（naive）：存储 tz 未钉，规则链 naive/aware 双兼容（replace 补 UTC）——C1-3 m55 先例 | D16 范围核查 + C1-3 先例 |
| app.ingest.rss.x__entry_published__mutmut_12 | A | tzinfo 实参删除：同 m10 | 同 m10 |
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
| app.ingest.rss.x_fetch_source__mutmut_7 | A | UA 键 XX：UA 内容无条款（R9 UA 策略为 site_config 预留，未钉抓取头——C1-3 m28 先例） | R9 范围核查 |
| app.ingest.rss.x_fetch_source__mutmut_8 | A | UA 键小写：httpx 线缆统一小写恰等价 | httpx.Headers 实证 |
| app.ingest.rss.x_fetch_source__mutmut_9 | A | UA 键大写：同 m8 | 同 m8 |
| app.ingest.rss.x_fetch_source__mutmut_14 | A | If-Modified-Since 置 None：条件头回传未钉，etag/哈希兜底（C1-3 m35 先例） | 模块表硬约束范围核查 |
| app.ingest.rss.x_fetch_source__mutmut_15 | A | If-Modified-Since 键 XX：同 m14 | 同 m14 |
| app.ingest.rss.x_fetch_source__mutmut_16 | A | If-Modified-Since 键小写：同 m14（键形态未钉） | 同 m14 |
| app.ingest.rss.x_fetch_source__mutmut_17 | A | If-Modified-Since 键大写：同 m14 | 同 m14 |
| app.ingest.rss.x_fetch_source__mutmut_22 | A | timeout 60.0→61.0：显式超时语义不变，任意有限值满足 §4.2（C1-3 m43 先例） | 技术书 §4.2 |
| app.ingest.rss.x_fetch_source__mutmut_88 | A | fetched_at 实参删除：ORM default=utcnow 兜底（models.py Item.fetched_at），恰等价 | 模型默认值核查 |
| app.ingest.rss.x_fetch_source__mutmut_91 | A | fetched_at naive（now(None)）：存储 tz 未钉（C1-3 m160 先例） | D16 范围核查 |
| app.ingest.rss.x_fetch_source__mutmut_122 | A | SanitizeTarget(url=None)：现有链（passthrough/KeywordDeny）不读 url 字段（C1-3 m187 先例） | sanitize.py 调用点核查 |
| app.ingest.rss.x_fetch_source__mutmut_125 | A | SanitizeTarget url 实参删除：同 m122 | 同 m122 |
| app.ingest.rss.x_fetch_source__mutmut_149 | A | log.warning(None,...)：日志文案无条款（AC-04.2 last_error 证据由 stats.error 承载） | 文案无措辞条款 |
| app.ingest.rss.x_fetch_source__mutmut_150 | A | log 参数 source.id→None：同 m149 | 同 m149 |
| app.ingest.rss.x_fetch_source__mutmut_151 | A | log 参数 e→None：同 m149 | 同 m149 |
| app.ingest.rss.x_fetch_source__mutmut_152 | A | log 参数形态变化：同 m149 | 同 m149 |
| app.ingest.rss.x_fetch_source__mutmut_153 | A | log 缺 source.id 参数：同 m149 | 同 m149 |
| app.ingest.rss.x_fetch_source__mutmut_154 | A | log 缺 e 参数：同 m149 | 同 m149 |
| app.ingest.rss.x_fetch_source__mutmut_155 | A | log 文案 XX 包裹：同 m149 | 同 m149 |
| app.ingest.rss.x_fetch_source__mutmut_156 | A | log 文案大写变体：同 m149 | 同 m149 |
| app.ingest.rss.x_fetch_source__mutmut_164 | A | resp.headers["ETAG"]：httpx.Headers 大小写不敏感，恰等价 | httpx.Headers 实证 |
| app.ingest.rss.x_fetch_source__mutmut_165 | A | etag 截断 [:500]→[:501]：SQLite 不强制 VARCHAR 长度（C1-2/C1-3 先例） | ADR-1 + C1-3 m72 先例 |
| app.ingest.rss.x_fetch_source__mutmut_167 | A | last-modified 存储跳过（get 键 XX）：last_modified 回传/存储未钉，etag 兜底（C1-3 m78 先例） | 模块表硬约束范围核查 |
| app.ingest.rss.x_fetch_source__mutmut_168 | A | get("LAST-MODIFIED")：httpx 大小写不敏感恰等价 | httpx.Headers 实证 |
| app.ingest.rss.x_fetch_source__mutmut_169 | A | last_modified 置 None：存储未钉（C1-3 m80 先例） | 同 m167 |
| app.ingest.rss.x_fetch_source__mutmut_170 | A | 取值键 XX：同 m167 | 同 m167 |
| app.ingest.rss.x_fetch_source__mutmut_171 | A | 取值键大写：httpx 大小写不敏感恰等价 | httpx.Headers 实证 |
| app.ingest.rss.x_fetch_source__mutmut_172 | A | last_modified 截断 [:501]：同 m165 | 同 m165 |
| app.ingest.rss.x_normalize_guid__mutmut_2 | A | or→and（link 与 link_alt）：差异域=仅 link_alt 无 id/link 的条目被丢弃——link_alt 回退不在 B4 设计链（归一化 link → URL 型 guid）内 | B4 链范围核查 |
| app.ingest.rss.x_normalize_guid__mutmut_3 | A | and→or（id or (link and link_alt)）：差异域=link 与 link_alt 同在时取 link_alt——link_alt 优先序无条款（既有测试仅钉 id>link） | 同上 |
| app.ingest.rss.x_normalize_guid__mutmut_8 | A | link 槽位 entry.get(None)：有 id 或无 link_alt 时经回退分支恰等价；差异域同 m3 | 同上 |
| app.ingest.rss.x_normalize_guid__mutmut_9 | A | link 槽位键 XX：同 m8 | 同上 |
| app.ingest.rss.x_normalize_guid__mutmut_10 | A | link 槽位键大写：同 m8 | 同上 |
| app.ingest.rss.x_normalize_guid__mutmut_11 | A | link_alt 槽位 entry.get(None)：仅 link_alt-only 条目差异（无条款） | B4 链范围核查 |
| app.ingest.rss.x_normalize_guid__mutmut_12 | A | link_alt 槽位键 XX：同 m11 | 同上 |
| app.ingest.rss.x_normalize_guid__mutmut_13 | A | link_alt 槽位键大写：同 m11 | 同上 |
| app.ingest.rss.x_normalize_guid__mutmut_14 | A | or "XXXX"：id/link/link_alt 全空条目由丢弃变异为收录 bogus guid——guid 缺失条目处理形态无条款 | 无条款域核查 |
| app.ingest.rss.x_normalize_guid__mutmut_23 | A | 回退 normalize_url(None)：回退仅在 raw 为空（三者全空）时可达，此时 entry.get("link") 亦为空——normalize_url(None)→None 与 "" 同为假值，条目均被 parse 跳过，恰等价 | 控制流等价 |
| app.ingest.rss.x_normalize_guid__mutmut_24 | A | 回退 entry.get("link") and ""：同 m23（回退域内恰等价） | 同 m23 |
| app.ingest.rss.x_normalize_guid__mutmut_25 | A | 回退 entry.get(None) or ""：同 m23 | 同 m23 |
| app.ingest.rss.x_normalize_guid__mutmut_26 | A | 回退键 XX：同 m23 | 同 m23 |
| app.ingest.rss.x_normalize_guid__mutmut_27 | A | 回退键大写：同 m23 | 同 m23 |
| app.ingest.rss.x_normalize_guid__mutmut_28 | A | 回退 or "XXXX"：同 m14（bogus guid 形态无条款） | 同 m14 |
| app.ingest.rss.x_normalize_url__mutmut_7 | A | keep_blank_values=None（缺省 False）：空白值查询参数保留与否——归一化微差，无条款（任务书 §2「无条款的归一化微差归 A」） | 归一化条款范围核查 |
| app.ingest.rss.x_normalize_url__mutmut_9 | A | keep_blank_values 实参删除：同 m7 | 同 m7 |
| app.ingest.rss.x_normalize_url__mutmut_10 | A | keep_blank_values=False：同 m7 | 同 m7 |
| app.ingest.rss.x_parse_feed_entries__mutmut_24 | A | url or "XXXX"：缺 link 条目 url "XXXX"——url 空值形态无条款（注：feedparser 对可回填 guid 会注入 link，差异域=不可回填 guid 条目） | 无条款域核查 |
| app.ingest.rss.x_parse_feed_entries__mutmut_29 | A | title or "XXXX"：缺标题条目 title "XXXX"——标题空值形态无条款 | 无条款域核查 |
| app.ingest.rules.x_apply_rules__mutmut_15 | A | too_short 返回 passed=None：全部调用点按真值判断（fetch_source if rule.passed / 单测 not r.passed），None≡False | 调用点核查 |
| app.ingest.rules.x_apply_rules__mutmut_21 | A | kw and→or：差异域=blacklist 含空串（原跳过/变异全拒）——blacklist 内容形态无条款，空串 kw 处理属信息性防御 | 无条款域核查 |
| app.ingest.rules.x_apply_rules__mutmut_23 | A | blacklist 返回 passed=None：同 m15 | 调用点核查 |
| app.ingest.rules.x_apply_rules__mutmut_30 | A | aware 判定 and False：aware 非 UTC 时钟面替换——D16 仅钉日切口径，规则链 naive/aware 双兼容（C1-3 先例） | D16 范围核查 |
| app.ingest.rules.x_apply_rules__mutmut_38 | A | expired 返回 passed=None：同 m15 | 调用点核查 |
| app.ingest.sanitize.x_run_sanitize__mutmut_2 | A | last_pass 初值 None：初值仅在链为空时返回——build_chain 恒返回非空链（至少 passthrough 一项），循环体必覆写，不可达 | 控制流推理（build_chain 全分支核查） |
| app.ingest.sanitize.x_run_sanitize__mutmut_3 | A | 同 m2（passed=None 形态） | 同 m2 |
| app.ingest.sanitize.x_run_sanitize__mutmut_4 | A | 同 m2（reason=None 形态） | 同 m2 |
| app.ingest.sanitize.x_run_sanitize__mutmut_6 | A | 同 m2（reason 缺省形态） | 同 m2 |
| app.ingest.sanitize.x_run_sanitize__mutmut_7 | A | 同 m2（passed=False 形态） | 同 m2 |
| app.ingest.sanitize.x_run_sanitize__mutmut_8 | A | 同 m2（reason XX 形态） | 同 m2 |
| app.ingest.sanitize.x_run_sanitize__mutmut_9 | A | 同 m2（reason 大写形态） | 同 m2 |
| app.ingest.sanitize.xǁKeywordDenySanitizerǁcheck__mutmut_3 | A | REJECT 结果 passed=None：run_sanitize 与全部调用点按真值判断（not result.passed / if sr.passed），行为等价 | 调用点核查 |
| app.providers.base.xǁHTTPProviderǁ__init____mutmut_5 | A | base_url.lstrip("/")：合法绝对 URL 配置以 scheme 开头，域内恒等价；ADR-8 条款域=尾斜杠有无（不覆盖前导斜杠配置，httpx 亦不接受相对 base_url） | ADR-8 条款域核查 + 实证 |
| app.providers.base.xǁHTTPProviderǁ__init____mutmut_9 | A | 键 "authorization" 小写：httpx 发送前统一小写头名（MockTransport 实测捕获），线缆形态恰等价 | httpx.Headers 实证 |
| app.providers.base.xǁHTTPProviderǁ__init____mutmut_10 | A | 键 "AUTHORIZATION" 大写：同 m9（线缆统一小写） | httpx.Headers 实证 |
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
| app.authors.pipeline.xǁPipelineRunnerǁrun_gates__mutmut_144 | A | min_count 缺省 2→3 数值无条款（AC-11.2 的 2 是配置示例非缺省钉法） | 数值缺省无条款 |
| app.authors.pipeline.xǁPipelineRunnerǁrun_gates__mutmut_146 | A | CitationError 文案 str(None)——issues 文案未钉（靠非空性拒收仍成立） | 文案无措辞条款 |
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
| app.authors.pipeline.xǁPipelineRunnerǁnode_draft__mutmut_42 | A | discarded 标记键/值形态未钉（trace 字段内部形态） | §4.1 字段范围核查（任务书§2） |
| app.authors.pipeline.xǁPipelineRunnerǁnode_draft__mutmut_43 | A | discarded 标记键/值形态未钉（trace 字段内部形态） | §4.1 字段范围核查（任务书§2） |
| app.authors.pipeline.xǁPipelineRunnerǁnode_draft__mutmut_44 | A | discarded 标记键/值形态未钉（trace 字段内部形态） | §4.1 字段范围核查（任务书§2） |
| app.authors.pipeline.xǁPipelineRunnerǁnode_draft__mutmut_45 | A | discarded 标记键/值形态未钉（trace 字段内部形态） | §4.1 字段范围核查（任务书§2） |
| app.authors.pipeline.xǁPipelineRunnerǁnode_draft__mutmut_46 | A | discarded 标记键/值形态未钉（trace 字段内部形态） | §4.1 字段范围核查（任务书§2） |
| app.authors.pipeline.xǁPipelineRunnerǁnode_draft__mutmut_47 | A | discarded 标记键/值形态未钉（trace 字段内部形态） | §4.1 字段范围核查（任务书§2） |
| app.authors.pipeline.xǁPipelineRunnerǁnode_draft__mutmut_57 | A | note trace 字段未钉 | §4.1 字段范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁnode_draft__mutmut_58 | A | note trace 字段未钉 | §4.1 字段范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁnode_draft__mutmut_59 | A | note trace 字段未钉 | §4.1 字段范围核查 |
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
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_6 | A | reading_window 参数行为无条款（技术书/产品书均未钉该批跑参数） | 无条款域核查 |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_7 | A | reading_window 参数行为无条款（技术书/产品书均未钉该批跑参数） | 无条款域核查 |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_8 | A | reading_window 参数行为无条款（技术书/产品书均未钉该批跑参数） | 无条款域核查 |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_9 | A | reading_window 参数行为无条款（技术书/产品书均未钉该批跑参数） | 无条款域核查 |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_10 | A | reading_window 参数行为无条款（技术书/产品书均未钉该批跑参数） | 无条款域核查 |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_11 | A | reading_window 参数行为无条款（技术书/产品书均未钉该批跑参数） | 无条款域核查 |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_12 | A | reading_window 参数行为无条款（技术书/产品书均未钉该批跑参数） | 无条款域核查 |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_13 | A | reading_window 参数行为无条款（技术书/产品书均未钉该批跑参数） | 无条款域核查 |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_14 | A | reading_window 参数行为无条款（技术书/产品书均未钉该批跑参数） | 无条款域核查 |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_15 | A | reading_window 参数行为无条款（技术书/产品书均未钉该批跑参数） | 无条款域核查 |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_16 | A | reading_window 参数行为无条款（技术书/产品书均未钉该批跑参数） | 无条款域核查 |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_19 | A | 空阅读集中止文案未钉（状态语义属 run_pipeline_write 层，本变异不改状态与 LLM 计数） | 文案无措辞条款 |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_20 | A | 空阅读集中止文案未钉（状态语义属 run_pipeline_write 层，本变异不改状态与 LLM 计数） | 文案无措辞条款 |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_23 | A | 【本期阅读集】段标题措辞 | 提示词形态 |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_70 | A | _slices_block head 调用 position 实参——head 与 else 分支输出恰等价 | 控制流等价 |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_73 | A | _slices_block head 调用 position 实参——head 与 else 分支输出恰等价 | 控制流等价 |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_74 | A | _slices_block head 调用 position 实参——head 与 else 分支输出恰等价 | 控制流等价 |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_79 | A | u+len==1 域 slices[1:] 为空、_slices_block([]) 返回空串——恰等价 | 控制流等价 |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_84 | A | tail position None→else 分支仅差尾随换行——措辞级 | 提示词形态 |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_88 | A | tail 键变形仅差尾随换行——措辞级 | 提示词形态 |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_89 | A | tail 键变形仅差尾随换行——措辞级 | 提示词形态 |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_93 | A | tail position 形态仅差尾随换行 | 提示词形态 |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_96 | A | tail position 形态仅差尾随换行 | 提示词形态 |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_97 | A | tail position 形态仅差尾随换行 | 提示词形态 |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_113 | A | recent_n 缺省 5→6 数值无条款 | 数值缺省无条款 |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_124 | A | 近期标题段措辞/拼接符 | 提示词形态 |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_126 | A | 近期标题段措辞/拼接符 | 提示词形态 |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_170 | A | rolling lo/hi 为死变量（赋值后无使用点）——等价 | 控制流等价（死代码） |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_171 | A | rolling lo/hi 为死变量（赋值后无使用点）——等价 | 控制流等价（死代码） |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_172 | A | rolling lo/hi 为死变量（赋值后无使用点）——等价 | 控制流等价（死代码） |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_173 | A | rolling lo/hi 为死变量（赋值后无使用点）——等价 | 控制流等价（死代码） |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_174 | A | rolling lo/hi 为死变量（赋值后无使用点）——等价 | 控制流等价（死代码） |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_175 | A | rolling lo/hi 为死变量（赋值后无使用点）——等价 | 控制流等价（死代码） |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_176 | A | rolling lo/hi 为死变量（赋值后无使用点）——等价 | 控制流等价（死代码） |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_177 | A | rolling lo/hi 为死变量（赋值后无使用点）——等价 | 控制流等价（死代码） |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_178 | A | rolling lo/hi 为死变量（赋值后无使用点）——等价 | 控制流等价（死代码） |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_179 | A | rolling lo/hi 为死变量（赋值后无使用点）——等价 | 控制流等价（死代码） |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_180 | A | rolling lo/hi 为死变量（赋值后无使用点）——等价 | 控制流等价（死代码） |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_181 | A | rolling lo/hi 为死变量（赋值后无使用点）——等价 | 控制流等价（死代码） |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_182 | A | rolling lo/hi 为死变量（赋值后无使用点）——等价 | 控制流等价（死代码） |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_183 | A | rolling lo/hi 为死变量（赋值后无使用点）——等价 | 控制流等价（死代码） |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_184 | A | rolling lo/hi 为死变量（赋值后无使用点）——等价 | 控制流等价（死代码） |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_185 | A | rolling lo/hi 为死变量（赋值后无使用点）——等价 | 控制流等价（死代码） |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_186 | A | rolling lo/hi 为死变量（赋值后无使用点）——等价 | 控制流等价（死代码） |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_187 | A | rolling lo/hi 为死变量（赋值后无使用点）——等价 | 控制流等价（死代码） |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_188 | A | rolling lo/hi 为死变量（赋值后无使用点）——等价 | 控制流等价（死代码） |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_189 | A | rolling lo/hi 为死变量（赋值后无使用点）——等价 | 控制流等价（死代码） |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_190 | A | rolling lo/hi 为死变量（赋值后无使用点）——等价 | 控制流等价（死代码） |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_191 | A | rolling lo/hi 为死变量（赋值后无使用点）——等价 | 控制流等价（死代码） |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_192 | A | rolling lo/hi 为死变量（赋值后无使用点）——等价 | 控制流等价（死代码） |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_193 | A | rolling lo/hi 为死变量（赋值后无使用点）——等价 | 控制流等价（死代码） |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_194 | A | rolling lo/hi 为死变量（赋值后无使用点）——等价 | 控制流等价（死代码） |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_195 | A | rolling lo/hi 为死变量（赋值后无使用点）——等价 | 控制流等价（死代码） |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_196 | A | rolling lo/hi 为死变量（赋值后无使用点）——等价 | 控制流等价（死代码） |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_197 | A | rolling lo/hi 为死变量（赋值后无使用点）——等价 | 控制流等价（死代码） |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_198 | A | rolling lo/hi 为死变量（赋值后无使用点）——等价 | 控制流等价（死代码） |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_199 | A | rolling lo/hi 为死变量（赋值后无使用点）——等价 | 控制流等价（死代码） |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_200 | A | rolling lo/hi 为死变量（赋值后无使用点）——等价 | 控制流等价（死代码） |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_201 | A | rolling lo/hi 为死变量（赋值后无使用点）——等价 | 控制流等价（死代码） |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_202 | A | rolling lo/hi 为死变量（赋值后无使用点）——等价 | 控制流等价（死代码） |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_207 | A | enumerate 起始 0/2——节次编号进提示词措辞 | 提示词形态 |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_208 | A | enumerate 起始 0/2——节次编号进提示词措辞 | 提示词形态 |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_211 | A | rolling node_draft 提示词实参（规划/衔接段）——提示词形态 | 提示词形态 |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_212 | A | rolling node_draft 提示词实参（规划/衔接段）——提示词形态 | 提示词形态 |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_213 | A | rolling node_draft 提示词实参（规划/衔接段）——提示词形态 | 提示词形态 |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_215 | A | rolling node_draft 提示词实参（规划/衔接段）——提示词形态 | 提示词形态 |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_216 | A | rolling node_draft 提示词实参（规划/衔接段）——提示词形态 | 提示词形态 |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_217 | A | rolling node_draft 提示词实参（规划/衔接段）——提示词形态 | 提示词形态 |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_221 | A | 节间拼接符措辞 | 提示词形态 |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_231 | A | 腹稿实参——提示词形态 | 提示词形态 |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_233 | A | 腹稿实参——提示词形态 | 提示词形态 |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_235 | A | 被后继 payload 写回遮蔽——终态恰等价 | 控制流等价（终态核查） |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_236 | A | 被后继 payload 写回遮蔽——终态恰等价 | 控制流等价（终态核查） |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_237 | A | 被后继 payload 写回遮蔽——终态恰等价 | 控制流等价（终态核查） |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_238 | A | 被后继 payload 写回遮蔽——终态恰等价 | 控制流等价（终态核查） |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_244 | A | prompt_snapshot 定界符内部形态未钉（§4.1 钉列存在+阅读集/切片可核，不钉分隔符） | §4.1 prompt_snapshot 范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_245 | A | prompt_snapshot 定界符内部形态未钉（§4.1 钉列存在+阅读集/切片可核，不钉分隔符） | §4.1 prompt_snapshot 范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_246 | A | prompt_snapshot 定界符内部形态未钉（§4.1 钉列存在+阅读集/切片可核，不钉分隔符） | §4.1 prompt_snapshot 范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_247 | A | prompt_snapshot 定界符内部形态未钉（§4.1 钉列存在+阅读集/切片可核，不钉分隔符） | §4.1 prompt_snapshot 范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_258 | A | before None 被 if before 守卫——仅 stats 形态 | pass_stats 字段未钉 |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_268 | A | pass params 读取——自定义 instruction 进提示词措辞 | 提示词形态 |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_269 | A | pass params 读取——自定义 instruction 进提示词措辞 | 提示词形态 |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_270 | A | pass params 读取——自定义 instruction 进提示词措辞 | 提示词形态 |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_271 | A | pass params 读取——自定义 instruction 进提示词措辞 | 提示词形态 |
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
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_288 | A | pass_stats 数值/键形态未钉 | §4.1 字段范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_289 | A | pass_stats 数值/键形态未钉 | §4.1 字段范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_290 | A | pass_stats 数值/键形态未钉 | §4.1 字段范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_291 | A | pass_stats 数值/键形态未钉 | §4.1 字段范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_292 | A | pass_stats 数值/键形态未钉 | §4.1 字段范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_293 | A | pass_stats 数值/键形态未钉 | §4.1 字段范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_340 | A | gate_history attempt/verdict 键形态未钉（payload 内部形态） | §4.1 字段范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_341 | A | gate_history attempt/verdict 键形态未钉（payload 内部形态） | §4.1 字段范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_360 | A | node_revise 稿件实参 None——fake 输出下终态等价、差异仅进提示词 | 提示词形态 |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_377 | A | gate_history attempt/verdict 键形态未钉（payload 内部形态） | §4.1 字段范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_378 | A | gate_history attempt/verdict 键形态未钉（payload 内部形态） | §4.1 字段范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_379 | A | gate_history attempt/verdict 键形态未钉（payload 内部形态） | §4.1 字段范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_380 | A | gate_history attempt/verdict 键形态未钉（payload 内部形态） | §4.1 字段范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_381 | A | gate_history attempt/verdict 键形态未钉（payload 内部形态） | §4.1 字段范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_383 | A | 被后续终态写回遮蔽——终态恰等价 | 控制流等价（终态核查） |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_384 | A | 被后续终态写回遮蔽——终态恰等价 | 控制流等价（终态核查） |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_385 | A | 被后续终态写回遮蔽——终态恰等价 | 控制流等价（终态核查） |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_386 | A | 被后续终态写回遮蔽——终态恰等价 | 控制流等价（终态核查） |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_393 | A | payload rewrite/title 键形态未钉 | §4.1 字段范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_394 | A | payload rewrite/title 键形态未钉 | §4.1 字段范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_399 | A | payload rewrite/title 键形态未钉 | §4.1 字段范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_400 | A | payload rewrite/title 键形态未钉 | §4.1 字段范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_401 | A | payload rewrite/title 键形态未钉 | §4.1 字段范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_402 | A | payload rewrite/title 键形态未钉 | §4.1 字段范围核查 |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_409 | A | error 截断 [:501]——文案形态 | 文案无措辞条款 |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_413 | A | audit_note 文案未钉 | 文案无措辞条款 |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_414 | A | audit_note 文案未钉 | 文案无措辞条款 |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_425 | A | 孤儿脚注过滤域——差异域为门禁已拒稿域（zero_revision 孤儿引用形态无条款） | 差异域核查 |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_427 | A | assemble_article_text 首参为死参数 | 控制流等价（死代码） |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_444 | A | status=None 实参——Article.status 列级 default=PUBLISHED_TO_C 在 None 时兜底（实测落库 PUBLISHED_TO_C） | 模型默认值核查（实证） |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_449 | A | status 实参脱落——ORM default=PUBLISHED_TO_C 恰等价 | 模型默认值核查 |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_460 | A | run.error None vs 空串——空值形态未钉 | 空值形态无条款 |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_461 | A | memory 条目 content 措辞 | 文案无措辞条款 |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_462 | A | memory 条目 content 措辞 | 文案无措辞条款 |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_464 | A | memory 条目 content 措辞 | 文案无措辞条款 |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_479 | A | source_event 值未钉枚举 | 字段形态无条款 |
| app.authors.pipeline.xǁPipelineRunnerǁexecute__mutmut_480 | A | source_event 值未钉枚举 | 字段形态无条款 |

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
| app.authors.pipeline.x_run_pipeline_write__mutmut_100 | A | overrides 镜像键名未钉 | §4.1 字段范围核查 |
| app.authors.pipeline.x_run_pipeline_write__mutmut_103 | A | payload.batch_id 键名未钉（§4.1 钉的是列） | §4.1 字段范围核查 |
| app.authors.pipeline.x_run_pipeline_write__mutmut_104 | A | payload.batch_id 键名未钉（§4.1 钉的是列） | §4.1 字段范围核查 |
| app.authors.pipeline.x_run_pipeline_write__mutmut_105 | A | reading_window 镜像键名未钉 | §4.1 字段范围核查（C1-5a 同款先例） |
| app.authors.pipeline.x_run_pipeline_write__mutmut_106 | A | reading_window 镜像键名未钉 | §4.1 字段范围核查（C1-5a 同款先例） |
| app.authors.pipeline.x_run_pipeline_write__mutmut_107 | A | 初始值被 execute 写回遮蔽 | 控制流等价（终态写回） |
| app.authors.pipeline.x_run_pipeline_write__mutmut_109 | A | 初始值被终态写回遮蔽 | 控制流等价（终态写回） |
| app.authors.pipeline.x_run_pipeline_write__mutmut_110 | A | 初始值被终态写回遮蔽 | 控制流等价（终态写回） |
| app.authors.pipeline.x_run_pipeline_write__mutmut_128 | A | _ = article→None——article 无后续消费 | 控制流等价（死代码） |
| app.authors.pipeline.x_run_pipeline_write__mutmut_133 | A | error='None' 形态——原因留痕仍非空，文案无条款 | 文案无措辞条款 |
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
| app.authors.pipeline.x_run_pipeline_write__mutmut_69 | A | payload.route.outline/draft 键名——payload 内部镜像形态未钉 | §4.1 字段范围核查 |
| app.authors.pipeline.x_run_pipeline_write__mutmut_70 | A | payload.route.outline/draft 键名——payload 内部镜像形态未钉 | §4.1 字段范围核查 |
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
| app.authors.pipeline.x_run_pipeline_write__mutmut_99 | A | overrides 镜像键名未钉 | §4.1 字段范围核查 |
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
| app.authors.gates.x_gate_length__mutmut_26 | A | issue 文案→None：issues 非空→不通过的判定语义不变，文案无条款 | AC-11.2 只钉拒收行为；文案措辞先例 |
| app.authors.gates.x_gate_length__mutmut_8 | A | get('min',None) 缺省变体：schema 必填 min（_validate_gates _int_field min/max），缺省分支不可达 | 调用点核查：authors/schema.py:186 min/max 必填校验 |
| app.authors.gates.x_gate_topic_dedup__mutmut_16 | A | sim>=threshold→>：恰等于阈值的边界含等性无条款（沿数值边界先例） | docs 未钉 threshold 含等性 |
| app.authors.gates.x_gate_topic_dedup__mutmut_17 | A | issue 文案→None：拒收语义不变，文案无条款 | AC-20.4 文案先例 |
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
| app.authors.writer.x__build_prompt__mutmut_57 | A | 空阅读集文案 XX 包裹：空阅读集语义属 F1 域（DT-4 随 F1 改实现），本批不钉 | 任务书 §4 边界：空阅读集语义不写断言 |
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
| app.authors.writer.x_assemble_ranked_reading_set__mutmut_104 | A | rank_score>=threshold→>：排除阈值含等性无条款 | 未钉 rank_exclude_below 含等性 |
| app.authors.writer.x_assemble_ranked_reading_set__mutmut_106 | A | fallback='all_excluded'→None：fallback 诊断标记值形态无条款（回退行为本身不变） | docstring 钉回退行为；标记文案未钉 |
| app.authors.writer.x_assemble_ranked_reading_set__mutmut_107 | A | fallback 键名→XX：同 m106 | 同 m106 |
| app.authors.writer.x_assemble_ranked_reading_set__mutmut_108 | A | fallback 键名→大写：同 m106 | 同 m106 |
| app.authors.writer.x_assemble_ranked_reading_set__mutmut_109 | A | 'all_excluded'→XX 包裹：同 m106 | 同 m106 |
| app.authors.writer.x_assemble_ranked_reading_set__mutmut_110 | A | 'all_excluded'→大写：同 m106 | 同 m106 |
| app.authors.writer.x_assemble_ranked_reading_set__mutmut_113 | A | 回退调用 k→None：k=None 落 WRITE_READING_SET_K 缺省，与原 k 同源等价 | 控制流推理：两处 k 均出自同一 k 变量或等价缺省 |
| app.authors.writer.x_assemble_ranked_reading_set__mutmut_116 | A | 回退调用 k 缺省形态：同 m113 | 同 m113 |
| app.authors.writer.x_assemble_ranked_reading_set__mutmut_123 | A | meta ranked 计数→None：计数字段值无条款 | 同 m30 |
| app.authors.writer.x_assemble_ranked_reading_set__mutmut_124 | A | ranked 键名→XX：同 m30 | 同 m30 |
| app.authors.writer.x_assemble_ranked_reading_set__mutmut_125 | A | ranked 键名→大写：同 m30 | 同 m30 |
| app.authors.writer.x_assemble_ranked_reading_set__mutmut_129 | A | meta excluded 计数→None：同 m123 | 同 m30 |
| app.authors.writer.x_assemble_ranked_reading_set__mutmut_130 | A | excluded 键名→XX：同 m30 | 同 m30 |
| app.authors.writer.x_assemble_ranked_reading_set__mutmut_131 | A | excluded 键名→大写：同 m30 | 同 m30 |
| app.authors.writer.x_assemble_ranked_reading_set__mutmut_132 | A | excluded=ranked-kept→+：计数值无条款 | 同 m30 |
| app.authors.writer.x_assemble_ranked_reading_set__mutmut_23 | A | 池 k=RANK_POOL_K→None：候选池 50 常数无条款（k=None 落 WRITE_READING_SET_K），小数据域等价 | 未钉常数 |
| app.authors.writer.x_assemble_ranked_reading_set__mutmut_26 | A | k=RANK_POOL_K 形参缺省形态：同 m23 | 同 m23 |
| app.authors.writer.x_assemble_ranked_reading_set__mutmut_30 | A | meta pool 键名→XX：rank_meta 诊断键名无条款 | §4.1 只钉 rank 明细（details 候选 id/score）与 provider/耗时；计数字段键名无条款 |
| app.authors.writer.x_assemble_ranked_reading_set__mutmut_31 | A | meta pool 键名→大写：同 m30 | 同 m30 |
| app.authors.writer.x_assemble_ranked_reading_set__mutmut_52 | A | direction None→break：方向行缺失为数据不一致防御面，单方向 Demo 不可达 | 调用点核查：Demo 单方向；防御分支无条款 |
| app.authors.writer.x_assemble_ranked_reading_set__mutmut_70 | A | 明细缺失 continue→break：部分明细缺失的容错顺序细节无条款（全缺时两形态同走 fallback） | docstring 只钉「明细缺失回退」总语义；部分缺失逐条跳过 vs 中断未钉 |
| app.authors.writer.x_assemble_ranked_reading_set__mutmut_80 | A | rank_error 截断 [:300]→[:301]：截断界无条款 | 未钉常数（错误文本截断界先例：providers.base [:2000] 判 A） |
| app.authors.writer.x_assemble_ranked_reading_set__mutmut_85 | A | 耗时 *1000→/1000：数值缩放退化（≈0），耗时仅诊断无精度条款 | 耗时数值精度无条款（providers.base m13 缩放先例） |
| app.authors.writer.x_assemble_ranked_reading_set__mutmut_86 | A | -t0→+t0：数值失真同 m85，无精度条款 | 同 m85 |
| app.authors.writer.x_assemble_ranked_reading_set__mutmut_87 | A | *1000→*1001：0.1% 缩放微差，同 m85 | 同 m85 |
| app.authors.writer.x_assemble_reading_set__mutmut_11 | A | fetch_status=='FETCHED' 过滤删除：合法数据域（FETCHED 条目）等价，非 FETCHED 行防御面无条款 | 调用点核查：正常管线仅 FETCHED 条目有 score |
| app.authors.writer.x_assemble_reading_set__mutmut_13 | A | join(None)：SQLAlchemy 由外键推断连接条件，等价 | ORM 语义推理：Item→ScoreResult 外键 item_id |
| app.authors.writer.x_assemble_reading_set__mutmut_15 | A | join 缺 onclause 形态：同 m13 | 同 m13 |
| app.authors.writer.x_assemble_reading_set__mutmut_29 | A | .limit(201)：同 m4 常数缺省变体 | 未钉常数 |
| app.authors.writer.x_assemble_reading_set__mutmut_4 | A | .limit(None)：候选池预上限 200 常数无条款，k 截断在小数据域下结果等价 | 未钉常数（沿数值缺省先例） |
| app.authors.writer.x_assemble_reading_set__mutmut_42 | A | or 60→or 61：阈值缺省 60 常数无条款（threshold 缺失时才可达） | 未钉缺省常数（沿数值缺省先例） |
| app.authors.writer.x_assemble_reading_set__mutmut_43 | A | relevance>=th→>：阈值含等性边界无条款（沿数值边界先例） | docs 未钉阈值含等性 |
| app.authors.writer.x_assemble_reading_set__mutmut_9 | A | status=='OK' 过滤行删除：passed=True 且 status≠OK 的非法数据行才可观察，合法数据域等价 | 调用点核查：score_result 合法行 status=OK ⟺ 记录有效（技术书 §4.1 score_result 行）；防御面无条款 |
| app.authors.writer.x_run_write__mutmut_1 | A | triggered_by 缺省 'manual'→XX：唯一生产调用点（pipeline/runner.py:366）显式传参，缺省不可达 | 调用点核查：grep 全仓唯一调用点 |
| app.authors.writer.x_run_write__mutmut_111 | A | 成功路径 last_error=None→''：该值仅 data None 分支读取（成功即 break），不可达 | 控制流推理 |
| app.authors.writer.x_run_write__mutmut_123 | A | 「（上次输出被拒收）」文案 XX：提示词措辞无条款 | 措辞先例 |
| app.authors.writer.x_run_write__mutmut_130 | A | 重试指令文案 XX 包裹：提示词措辞无条款 | 措辞先例 |
| app.authors.writer.x_run_write__mutmut_131 | A | 指令文案 json 小写：同 m130 | 同 m130 |
| app.authors.writer.x_run_write__mutmut_132 | A | 指令文案字段名大写：同 m130 | 同 m130 |
| app.authors.writer.x_run_write__mutmut_133 | A | 引用纪律句 XX 包裹：同 m130 | 同 m130 |
| app.authors.writer.x_run_write__mutmut_134 | A | ID→id：同 m130 | 同 m130 |
| app.authors.writer.x_run_write__mutmut_135 | A | 引用纪律句大写：同 m130 | 同 m130 |
| app.authors.writer.x_run_write__mutmut_174 | A | article status=None：Article.status 列缺省 default='PUBLISHED_TO_C' 在 flush 时补齐，落库值不变（已实证） | app/models.py Article.status default（T1 bootstrap_admin m9 列缺省承载同款先例） |
| app.authors.writer.x_run_write__mutmut_179 | A | status 行删除：同 m174（列缺省承载） | 同 m174 |
| app.authors.writer.x_run_write__mutmut_185 | A | 无题兜底 '（无题）'→XX：兜底文案无条款（正常成文路径恒有 title） | 措辞先例 |
| app.authors.writer.x_run_write__mutmut_2 | A | 缺省 'manual'→MANUAL：同 m1 | 同 m1 |
| app.authors.writer.x_run_write__mutmut_206 | A | 成功路径 error=None→''：error 列语义=失败留痕，None/空串均为「无错误」形态 | §4.1 error 列语义（失败留痕）；空值形态未钉 |
| app.authors.writer.x_run_write__mutmut_27 | A | prompt_snapshot 初值 ''→None：随即被完整快照覆盖，终态等价 | 控制流推理：snapshot 两行后必被赋值 |
| app.authors.writer.x_run_write__mutmut_34 | A | prompt_snapshot 初值行删除：同 m27（随即覆盖） | 同 m27 |
| app.authors.writer.x_run_write__mutmut_37 | A | prompt_snapshot 初值 'XXXX'：同 m27（随即覆盖） | 同 m27 |
| app.authors.writer.x_run_write__mutmut_51 | A | system 提示文案 XX 包裹：提示词措辞无条款 | 提示词措辞先例（ADR-8 未钉文案） |
| app.authors.writer.x_run_write__mutmut_52 | A | system 提示文案大写：同 m51 | 同 m51 |
| app.authors.writer.x_run_write__mutmut_71 | A | 分隔符 XX 包裹：快照分隔措辞无条款（两段内容均仍在） | W4 钉内容可核，未钉分隔形态 |
| app.authors.writer.x_run_write__mutmut_77 | A | last_error 初值 ''→（不变语义）：仅全成功路径可达，error 落库前恒被赋值 | 控制流推理：last_error 只在 data None 分支读取 |
| app.authors.writer.x_run_write__mutmut_86 | A | temperature=0.3→None：采样常数无条款 | 未钉采样温度（沿数值缺省先例） |
| app.authors.writer.x_run_write__mutmut_92 | A | temperature 行删除：采样常数无条款 | 同 m86 |
| app.authors.writer.x_run_write__mutmut_98 | A | temperature=1.3：采样常数无条款 | 同 m86 |
