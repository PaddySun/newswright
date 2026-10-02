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
