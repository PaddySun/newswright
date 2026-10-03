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
