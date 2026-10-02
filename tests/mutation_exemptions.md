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
