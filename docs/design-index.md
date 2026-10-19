# 设计条款编号索引（design-index）

> **文件头声明**：完整条文在项目设计文档（外层 `doc/产品设计书-正式-TDD.md`（产品书）与
> `doc/技术设计书-正式-TDD.md`（技术书））；**本索引为仓内唯一编号解析表**——每条编号
> → 一句话摘要 → 所属文档。条文以所属文档为准，本索引只做解析不做裁剪。
> 说明：测试与注释中另见 `W*`/`V*`/`EV*`（Demo 实测里程碑编号）与 `M*`（能力里程碑编号），
> 均非设计条款编号，不在本索引；`Cx-*`/`T1`/`F1` 等批次代称的历史溯源见各文件头追溯注记。

## AC-xx.x（验收标准，产品书 §3）

| 编号 | 一句话摘要 |
|---|---|
| AC-01.1 | 首次部署初始化：初始管理员密码经环境变量注入、无默认值，首登强制改密 |
| AC-01.1b | 正常登录成功返回 200 + 会话 cookie |
| AC-01.2 | 密码错误 401（AUTH_INVALID，规范 4XX）；连续 5 次失败后第 6 次 429 冷却 15 分钟 |
| AC-01.2b | 登录冷却到点即解：`now >= locked_until` 即恢复，计数同步清零 |
| AC-01.3 | 未认证访问受保护端点 → 401（AUTH_REQUIRED） |
| AC-01.4 | 会话保持期限 10 天 |
| AC-01.4b | 会话到期即失效：`expires_at <= now` 一律 401（安全侧） |
| AC-01.5 | 修改密码：旧密码校验 + 新密码生效 + 旧会话处置 |
| AC-02.1 | 隐身模式 A：未登录首页 404，无内容泄露 |
| AC-02.2 | 隐身模式 A：404 响应体为站长自定义 HTML |
| AC-02.3 | 隐身模式 A：robots.txt 返回全站 Disallow |
| AC-03.1 | 创建方向 |
| AC-03.2 | 编辑方向提示词必须升 prompt_version |
| AC-03.3 | 方向软删除（不物理删） |
| AC-03.4 | 临时方向 TTL 到期自动停用 |
| AC-04.1 | 新增 RSS 源 |
| AC-04.2 | 源硬失效判别（连续 404/403/410 ≥3 轮 → hard_failed 停抓） |
| AC-04.3 | 源疑似失效判别（连续空轮 → suspect 低频探测；304/skipDays 豁免计数） |
| AC-04.4 | 暂态故障不标失效（网络/5xx 仅退避计数） |
| AC-04.5 | 停用来源 |
| AC-04.6 | 源级间隔（source_config.interval_minutes）仅对到期源生效 |
| AC-04.7 | 新源首导打分窗口：判定顺序=垃圾规则→窗口（ARCHIVED 全文照存）→sanitize，过期规则对首导不生效 |
| AC-04.8 | RSS 摘要富化开关（enrich_full_text，成本只花在被拒条目上） |
| AC-05.1 | RSS 账目平衡：feed_entries = inserted(含 DUP 行) + dup_blocked(不落行) + rule_rejected + failed(不落行) + archived |
| AC-05.2 | 方向内跨源 URL 指纹近重复：DUP 落行 + duplicate_of + 全文照存 + 不重复打分（作用域=方向内） |
| AC-05.3 | 定点监测变更检测（content_hash/etag；guid=配置URL#v-哈希；无变更 not_modified） |
| AC-05.4 | 搜索额度闸拦截与恢复（blocked 记 search_call_log） |
| AC-05.5 | 429/限流动态降频（间隔倍增，恢复回升） |
| AC-05.6 | 热榜全量落库与提炼；单平台失败不中断；提炼失败 DONE+degraded 分态 |
| AC-06.1 | 零信任过滤强制阶段与统计（sanitize_status/reason/detail） |
| AC-06.2 | 启用演示过滤链（keyword deny 等） |
| AC-06.3 | 被过滤 ≠ 抓取失败（REJECTED 全文照存、账目分列） |
| AC-06.4 | 输入侧注入防线：第三方内容定界组装（`<document id>`）+ 检测登记 |
| AC-07.1 | 打分一次调用与输出契约（quality/relevance/band/reason/prompt_version/model） |
| AC-07.2 | 多方向线性成本（跨方向独立打分，方向间不共享） |
| AC-07.3 | 解析失败重试与终态（JSONParseError 重试一次，耗尽落 FAILED+error） |
| AC-07.4 | 打分突发上限（SCORE_ROUND_MAX_ITEMS/轮，超出下轮幂等续跑） |
| AC-07.5 | 打分幂等（只对无 OK 分条目调用，OK 绝不重复） |
| AC-07.6 | 方向重打分任务（rescore；旧分归档不删） |
| AC-07.7 | 缺发布时间不拒（不适用过期规则） |
| AC-08.1 | 嵌入与计量：按批落行 usage_log（item_count=batch 条数） |
| AC-08.2 | 检索路由：未命中不丢弃（进慢速队列全量打分，零静默漏检） |
| AC-08.3 | 语义近重复关联（阈值 0.92=示例值，按模型标定进 site_config） |
| AC-08.4 | 探索层条目（质量地板+最低相似分位+MMR，默认关） |
| AC-08.5 | 嵌入维度护栏（expected_dims 校验，防静默错位） |
| AC-09.1 | 创建即追踪（临时兴趣追踪方向） |
| AC-09.2 | 追踪到期自动停（TTL/temp 过期） |
| AC-10.1 | author.json 导入 round-trip（导入导出幂等一致） |
| AC-10.2 | 模型不在 JSON（运行时模型由 DB Author.model 绑定） |
| AC-10.3b | 可选 object 字段显式 null = 未写该键（宽松归一不报错） |
| AC-11.1 | 路线按 JSON 执行（outline/draft/passes/think_routing 按配置） |
| AC-11.2 | 门禁拒收与废稿：附违规说明重试 ≤max_attempts，中间稿留痕；同因连续 2 次早停 |
| AC-11.3 | 引用硬校验：item_id 在阅读集内 + quote 逐字子串命中（空白归一化） |
| AC-11.4 | 版权门禁：静态记忆块 n-gram 复述 ≥2 处判违规 |
| AC-11.5 | 不写判定：SKIP + reason/thinking 如实落库 |
| AC-11.6 | single 路线回归（无 author_json 作者行为不变） |
| AC-11.7 | 异步写作：202 + task_id + 前端退避轮询 |
| AC-12.1 | 文章 Markdown 与脚注溯源（[^K] ↔ 条目逐字引用） |
| AC-12.2 | 不写卡可见性（skip 卡与理由展示） |
| AC-12.3 | 热点风向不污染引用（热点段禁止作为引用来源） |
| AC-13.1 | 匿名点赞去重（cookie id 为主，IP+UA 兜底） |
| AC-13.2 | 匿名不可评价（仅点赞，不可评论） |
| AC-13.3 | 反馈回流记忆（feedback 记忆模块） |
| AC-14.1 | 呈现排序与阈值过滤（仅约束常规条目；穿插/探索按 DT-3） |
| AC-14.2 | 防蒙蔽穿插（低分但过最低阈值的条目按概率穿插，真实分数展示） |
| AC-14.3 | 探索标记（explore 条目带标记+真实分数） |
| AC-15.1 | 书签幂等（bookmark/unbookmark + 列表筛选） |
| AC-15.2 | 作者筛选（articles?author_id=） |
| AC-16.1 | 模式 B 降深（登录态完整、访客降深） |
| AC-16.2 | 模式 C AI 标识（AI 生成内容显著标识 + 作者 bio） |
| AC-16.3 | sitemap 与 robots（SEO 契约） |
| AC-16.4 | Feed 默认关 |
| AC-16.5 | 公开页访客可点赞（同 AC-13.1 去重） |
| AC-17.1 | 热点面板（airport-board 形态：关键词×top-scored 检索标题；访客 404） |
| AC-17.2 | 热点→搜索轻量闭环：一键转临时方向，人在环路确认 |
| AC-18.1 | 大模型日志可回溯（usage_log 全量计量） |
| AC-18.2 | 低分正文留存（不进呈现但 DB 可查） |
| AC-18.3 | 管线体检（pipeline stats 可观测） |
| AC-18.4 | 健康自省三态：200/200+degraded（增值层故障不报警）/503（仅基本功能故障） |
| AC-18.5 | 四类失败口径（见 DT-5） |
| AC-19.1 | SMTP 由后台配置（凭据不回显；未配置只落日志） |
| AC-19.2 | 通知触发条件与去重（24h 去重） |
| AC-19.3 | 采集面聚合哨兵（降频/失效聚合进 stats） |
| AC-19.4 | 磁盘阈值告警与清理 |
| AC-20.1 | 无人值守调度节奏（SCHED_*_MINUTES 显式配置） |
| AC-20.2 | 僵死任务回收（RUNNING 超时分档回收，CAS 迁移） |
| AC-20.3 | 失败源退避（连续失败跳过 + 周期探测） |
| AC-20.4 | 全链路幂等复跑（新文章或 topic_dedup 拒收留痕二者其一即通过） |
| AC-21.1 | LLM 全不可用时基本功能正常（D14 验收面） |
| AC-21.2 | 额度耗尽的降级秩序（探索层→嵌入→打分慢速的阶梯） |
| AC-21.3 | 写作异常不影响阅读 |
| AC-21.4 | 恢复自愈（额度恢复后管线自愈，无人工干预） |

## ADR-x（架构决策，技术书 §6）

| 编号 | 一句话摘要 |
|---|---|
| ADR-1 | 生产数据库保留 SQLite（WAL+busy_timeout）；事务边界纪律：外部调用出事务、逐条短事务 |
| ADR-2 | 单进程模块化单体（API + APScheduler 同进程；僵死回收覆盖中断） |
| ADR-3 | 嵌入走 moark API 不本地推理（批量/维度/数量三护栏，计量照记） |
| ADR-4 | 认证 = 服务端 Session + HttpOnly Cookie（argon2id 哈希） |
| ADR-5 | 拓扑 CDN→WAF→应用：响应头契约 + 安全不降级 + 云原生构建（⑤=请求侧 IP 信任契约单一 get_client_ip；⑤b=无对端信息哨兵 "unknown"） |
| ADR-6 | 检索层为路由器非过滤器（hit 优先、miss 慢速、零丢弃） |
| ADR-7 | 呈现形态：公开/登录页 SSR + 登录态与后台 SPA；Markdown 白名单渲染 |
| ADR-8 | 外部调用 provider 统一纪律：重试 ≤2 指数退避/计量落账/报错脱敏/尾斜杠兼容拼接/Bearer+Content-Type 构造/计费月度对账 |
| ADR-9 | 打分突发上限与重打分任务（SCORE_ROUND_MAX_ITEMS 默认 200/轮；rescore 阈值并入 score=60min） |
| ADR-10 | 能力插件化（Notifier/BackupTarget/PublishPort 注册表；SMTP/LocalDir/WordPress 占位首批） |
| ADR-11 | 基本管线与 AI 增值功能故障隔离（双线程池、降级阶梯不含抓取与呈现；hot 提炼降级链入清单） |
| ADR-12 | 结构化系统日志（ERROR/WARN/INFO 纪律；contextvars 上下文注入；账本带指标不带日志） |

## D-x（设计决策，产品书 §0）

| 编号 | 一句话摘要 |
|---|---|
| D1 | 生产数据库 SQLite WAL（对应技术书 ADR-1） |
| D2 | 密码哈希 argon2id（ADR-4） |
| D3 | 呈现形态 SSR+SPA（ADR-7） |
| D4 | SMTP 全由后台配置，凭据不回显 |
| D5 | 部署拓扑 CDN→WAF→应用 + 云原生构建（ADR-5/ADR-10） |
| D6 | WordPress 发布不进正式版（PublishPort 占位） |
| D7 | 匿名反馈去重：cookie id 为主、IP+UA 兜底 |
| D8 | Feed 输出用 feedgen |
| D9 | 备份本地目录轮转 ≥7 份；对象存储为未来插件 |
| D10 | 探索层默认关，参数可配，默认值实测后定 |
| D11 | 前端错误规范 4XX（供 WAF/CDN 识别） |
| D12 | 规范化结构日志（ADR-12） |
| D13 | 429 限流信号自动降频退避 |
| D14 | 价值导向：增值功能故障不伤基本管线（ADR-11/US-21） |
| D15 | 去重作用域=方向内；跨方向独立采集打分 |
| D16 | 时区与日切统一取 site_config timezone（默认 Asia/Shanghai） |
| D17 | 预算闸轮次粒度拦截（透支上限=SCORE_ROUND_MAX_ITEMS×均价） |
| D18 | 凭据纪律：初始密码环境变量注入，文档/git 不记载 |
| D19 | prompt_version 统一 integer |
| D20 | 搜索关键词边际降频（连续 6 轮零新增→间隔倍增，独立于 D13 计数） |

## DT-x（业务规则决策表，产品书 §4）

| 编号 | 一句话摘要 |
|---|---|
| DT-1 | 来源失效三级判别：hard_failed / suspect（304、skipDays 豁免计数）/ none；成功清零 |
| DT-2 | 打分路由：命中优先、未命中慢速队列仍打分、嵌入不可用全慢速、重复不打分——零静默丢弃 |
| DT-3 | 穿插与探索选样：穿插=低分过最低阈值按概率；探索=质量地板+最低分位+配额，默认关 |
| DT-4 | 写作决策：write/skip/重试/耗尽 FAILED 废稿留痕/阅读集为空 SKIP 本地短路零 LLM；引用校验耗尽=违规文章入库+citation_violated 标记 |
| DT-5 | 四类失败口径与记录位置（source.failure_level / payload.stats / item 拒绝列 / score_result.passed） |
| DT-6 | 调度跳过原因优先级表（disabled→direction_expired→rate_limited→keyword_exhausted→hard_failed/suspect_probe→backoff→interval_not_due） |

## R-x（两族，按语境消歧）

**R1-R9（BettaFish 对照评审，产品书/技术书 v1.4 增补）**

| 编号 | 一句话摘要 |
|---|---|
| R1 | 契约合并：OpenAPI YAML 块外散文补丁收编，"本节 YAML 之外无契约" |
| R2 | hot 轮分态：采集成功即 DONE+degraded；提炼失败走标题分词 top-15 兜底，禁固定兜底词 |
| R3 | item.source_keyword 列（逐词新增率归因）+ D20 关键词边际降频 |
| R4 | 热点→搜索轻量闭环（AC-17.2 人在环路）；自动注入列 Out of Scope |
| R5 | JSON 解析链 strict→repair→retry（截断补括号） |
| R6 | 门禁重试附违规历史+同因早停（AC-11.2） |
| R7 | 阅读集多样性约束（域名硬约束+MMR 二期） |
| R8 | source_config.freshness（追踪方向默认 oneDay） |
| R9 | UA 策略 site_config + proxy 参数位预留 |

**R1-R10（morningdeck 运维与排查经验评审，产品书 §7 v1.1 增补；仓内引用多为 R3/R4/R6/R7）**

| 编号 | 一句话摘要 |
|---|---|
| R1 | §1.3 部署矩阵（拓扑 P1/P2+TLS 终止点+源站证书硬条款+systemd 契约） |
| R2 | /healthz no-store + deploy_id + 三态语义（degraded≠503 防报警疲劳） |
| R3 | /healthz 探测源白名单（监控不探测会污染指标的页面） |
| R4 | 磁盘预算与 raw/废稿清理升正式范围 |
| R5 | AC-14.2 概率验证口径 |
| R6 | ADR-12⑤ 日志上下文注入纪律（contextvars + soak JSON 断言） |
| R7 | 降频/失效聚合哨兵进 stats/pipeline 与 US-19 |
| R8 | systemd MemoryMax=600M |
| R9 | probe.sh 四层探测 |
| R10 | site_config 变更审计 |

## B-x（RSS 抓取经验条款，产品书/技术书 v1.3 增补）

| 编号 | 一句话摘要 |
|---|---|
| B1 | 200+非 XML 挑战页内容嗅探（non_xml_response 走失败列） |
| B2 | feedparser 只喂 bytes（禁止 .text，防编码错解） |
| B3 | Retry-After 双形态解析 |
| B4 | 指纹退化链（归一化 link→URL 型 guid→标题兜底）+标题 html.unescape；URL 型 guid 判定 scheme 大小写不敏感 |
| B5 | source_config.enrich_full_text 开关（摘要型源自救） |
| B6 | 瞬态空 feed 计数清零语义（并入 DT-1） |
| B7 | etag 原样存取（≥500 列宽）+ web 监测 guid 用配置 URL；web 单页版本条目豁免指纹链 |

## TR-x（传输脊条款，外部服务治理批（C4）增补；条文正文随外层技术书 C4 变更点落册）

| 编号 | 一句话摘要 |
|---|---|
| TR-1 | 传输脊分层：全部外部服务出网收敛 app/transport/（HTTP 出口/错误分类学/计量/额度闸唯一实现）；能力域保留重试模板方法与计量语义；旧位置（providers.base/search.base/ingest.http）转薄 re-export，新增代码禁止从旧位置出网 |
| TR-2 | 非 2xx 全入错：3xx=可重试 TransportError 带 location（网关 302 营销站漏网=「成功空响应」形态实锤）；429/5xx=可重试 TransportError 挂 Retry-After 解析值；其余 ≥400=不可重试 SemanticError（官方错误码语义映射） |
| TR-3 | 随机化指数退避：2**attempt × uniform(0.5, 1.5) 秒（jitter 治确定性退避的同步踩踏）；RNG 型测试断言区间与分布形态、禁依赖具体随机序列 |
| TR-4 | Retry-After 协商：服务端值优先（delta-seconds/HTTP-date 双形态解析，B3 上提四域共用），采纳夹逼 [0, 60s) 开区间；无服务端值走 TR-3 |
| TR-5 | RetryExhausted 结构化耗尽：reason 两态（max_retries_exceeded / error_not_retryable）+ 逐次尝试 errors 链；必须继承 ProviderError 兼容根（既有 except 面零改动）；域耗尽组合类保域类型（EmbeddingRetryExhausted / SearchRetryExhausted 双类型） |
| TR-6 | 客户端池：(源, 鉴权头, 超时, 生效 UA, 客户端工厂) 进程级复用、线程安全（双检锁）；UA 值入键=site_config 运行时切 UA 即新客户端；工厂身份入键=同进程桩替换不串台；池客户端不跟随重定向（3xx 须在传输层拦截） |

## LR-x（LLM 域抽象与选源条款，外部服务治理批（C4）增补；条文正文随外层技术书 C4 变更点落册）

| 编号 | 一句话摘要 |
|---|---|
| LR-1 | LLM 域基类下沉：chat/chat_json 挂 LLMProvider（tier_request 档位钩子默认零改写；观测面 last_usage/fallback_note/reasoner_available 初始化在基类，管线直写经缓存共享实例跨调用生效）；具体厂商退化为「配置 + 档位钩子 + 兼容阀声明」；注册名是配置面与代码面唯一耦合点（registry 同 embedding/rerank 模式，variant 按模型出变体） |
| LR-2 | 选源层缓存纪律：进程级实例缓存键=(域,名,model)，探测状态（reasoner_available）随实例跨调用存活不逐调用丢失；缓存命中实例的计量归属（db）刷新为当前调用方会话；消费方一律经 resolve 取用、零具体厂商 import（llm 排序经构造注入 + 注册处组装） |
| LR-3 | 候选与冷却语义：有序候选列表（LLM_CANDIDATES 缺省回落 [LLM_PROVIDER] 单候选=行为零变）；TTL 冷却默认不启用（TTL=0 标记 no-op）；单候选永不进入冷却判定（无备源可切）；全部候选冷却 → 选源返回 None、消费方走各自既有降级链（FAILED 终态/回退生成/全量慢速），不在选源层统一吞错 |
| LR-4 | 启动校验与 none 哨兵域：配置的 provider 名不可解析拒绝启动（create_app 内执行，报错含 available() 名单）；none 禁用哨兵仅嵌入域合法（EMBED_PROVIDER=none → 检索层回退全量慢速），chat 域配置 none 即配置错误、不实现 chat 禁用路径 |
| LR-5 | OpenAI 族厂商差异声明：chat_completions_path 路径前缀为厂商差异（deepseek 官方 base 无 /v1、moark OpenAI 网关族带 /v1，误用即触发 TR-2 的 302 漏网形态）；moark chat 默认模型=冒烟锁定的跨厂商同族主备对（deepseek-v4.1-flash ↔ 官方 deepseek-flash），moark 间歇长挂起定位为备源 |
| LR-6 | 计量回显与兼容阀状态判定：usage_log 的 model 以响应回显实况优先落账（请求名兜底——计量空洞治理）；网关兼容阀按错误对象结构化 status 判定（400/422 参数拒绝域）+ gateway_compat_params 声明式剥离重发一次（deepseek=thinking 族参数、moark=response_format），全库禁文案嗅探形态 |
| LR-7 | Jev 决策协议客户端构造期校验：questions 逐项 instructions 必填（服务端对缺失回 400「请求参数缺少必填字段 'questions.q.instructions'」实测锚），缺字段在构造期抛 JevAdapterError 防线前移（消息含字段名与 qid），不烧注定失败的网络调用 |
| LR-8 | 判定类 chat 调用温度 0 确定性：打分（scoring）与检索查询生成（query_gen）两类判定/结构化输出调用 temperature=0 为契约——chat 模板温度缺省 0.0 不得漂移（缺省唯一生产消费方=query_gen），打分显式 0.0 不得漂移；测试形态=桩捕获请求 payload 断言 temperature==0.0（杀灭 0.0→1.0 常量变异）。判例源：C5-2 分诊温度面两条变异站长裁定转 C（2026-10-17），条款正文见外层技术书 v2.3 §6.13 LR-8 |
| LR-9 | chat_json 载荷结构契约（C5-4 分诊 D 类 messages 结构面，站长 2026-10-17 裁定转 C）：凡经 LLMProvider.chat/chat_json 发出的 messages 逐条必须含 role 与 content 二键、content 为 str——载荷结构破坏在真实协议下即 400 形态，属协议契约面而非文案域；测试形态=桩校验载荷结构（逐条断言键集与值类型），组杀 llm_rank 组装面结构类变异；适用全部 chat 调用点（打分/写作/排序/查询生成）。条款正文见外层技术书 v2.4 §6.13 LR-9（C5-5 收官批组杀断言与镜像登记） |

## HR-x（热榜域治理条款，外部服务治理批（C4-3）增补；条文正文随外层技术书 C4 变更点落册）

| 编号 | 一句话摘要 |
|---|---|
| HR-1 | 热榜出网治理（传输脊 GET 面）：hot 取用一律经 transport.get_json——与 post_json 共用客户端池与非 2xx 分类单点（分类不分叉），重定向策略进池键；GET 面 follow_redirects 缺省 True 维持采集通道既有行为，「非 2xx 入错」以重定向终态为准（正常链落 2xx 不入错，裸 302/超限链入可重试 TransportError）；httpx 原生异常（读超时/连接失败/TooManyRedirects）在 GET 面包装为可重试 TransportError 上抛（裸异常零逃逸；POST 面不越权改动，LLM/搜索域重试模板自捕） |
| HR-2 | 热榜域重试与聚合器候选位：域级重试 ≤2 次（仅可重试 TransportError；退避经 retry_delay_ms 协商——429 Retry-After 优先/随机化指数退避自动继承）；ContractError（items 非列表/响应非 JSON 等契约违例，替换治理前裸 ValueError）与 SemanticError 不重试；HOT_AGG_CANDIDATES 有序候选按序取用（缺省 [HOT_AGG_BASE] 单元素=行为零变），首候选失败（重试耗尽或不可重试）→ 次候选，全败抛 RetryExhausted 终态（reason 两态+跨候选尝试链），轮次层单平台失败不中断整轮照旧 |
| HR-3 | HotCallLog 成败都记账：每平台每次取用一行终态（中间重试尝试不逐行——search_call_log 同语义），成败各一行；provider=聚合器 origin、platform、status=HTTP 码或错误类别（RetryExhausted 取末次尝试链状态码，无码则类别名）、latency_ms=整次取用耗时（含重试）、error 脱敏（sk- 形态不落账）；这是新增持久账，不替代任务 payload 的 platform_stats（形态零变） |
| HR-4 | 429 识别与降频边界：429 经传输脊错误对象的结构化 retry_after 字段识别、退避协商自动采纳服务端值，落账 status 如实记录 HTTP 码；动态降频（rate_limited_until 档位语义）记遗留不在治理批做——低流量单聚合器先如实观测 |
| HR-5 | 热榜条目数据卫生：聚合响应仅保留 dict 且 title 非空白的条目——空标题/空白标题/缺键/非 dict 条目必须剔除（热榜面板条目恒有可呈现标题；判例源：C5-3 D 类站长 2026-10-18 裁定转 C） |

## PR-x（公开页渲染条款，引用块可达性修复批（C5-1b）增补）

| 编号 | 一句话摘要 |
|---|---|
| PR-1 | 整篇转义先行的行首标记匹配：白名单渲染器先整篇 HTML 转义再逐行匹配语法，一切行首标记类语法（引用块 > 等）的判定与内容剥离必须以转义后形态（&gt;）做前缀容忍匹配（> / &gt; 双形态），不得按源文字面形态匹配；源文字面实体（&gt;）经二次转义（&amp;gt;）自然不匹配，无需消歧工程；服务端 public_render.py 为规则权威，SPA markdown-client.js 同构镜像（双侧规则形态一致；嵌套标记仅剥一层，白名单未定义嵌套层级）——判例源：引用块判定 ^>\s? 在整篇转义后永不匹配、blockquote 永不产出的生产缺陷（修复批汇报 doc/C5/C5-1b-执行Agent工作汇报.md） |

## SR-x（安全杂项条款，后端完善批 BE-1 增补；条文正文随外层治理文档 doc/BE/BE-1-任务书.md 落册）

| 编号 | 一句话摘要 |
|---|---|
| SR-1 | 反馈频控与记忆闸三道：/feedback 入口 per-IP 小时频控（缺省 30，进程内固定窗，now 可注入）+ per-article 当日聚合上限（缺省 100，ArticleReaction DB 计数、站点时区日切）+ 同作者当日 feedback 记忆回流 cap（缺省 50，超限丢弃回流、reaction 照常入库+WARN）——cookie 身份可轮换（换 cookie 即新身份），IP 桶与 DB 计数是不可伪造维度；already_counted 幂等与 comment 登录要求零变 |
| SR-2 | 改密吊销：改密成功即删除该用户全部 sessions 行（响应含 sessions_revoked）+ 换发新会话当前连接不断（Set-Cookie 与登录同形态）；过期会话行 purge_expired_sessions 每日批量清理（挂 daily_backup 轮，logout 单行删除语义不变） |
| SR-3 | 安全响应头全域中间件：CSP（每请求 secrets.token_urlsafe(16) nonce，request.state 供模板、头与页面属性必然一致；importmap 为全站唯一 inline script）/X-Content-Type-Options/X-Frame-Options/Referrer-Policy/HSTS 五件套，纯函数+常量防漂移；HSTS 在 http 下浏览器忽略（无害） |
| SR-4 | client_ip_header 反代警告：配置头后该值可被客户端伪造绕过一切按 IP 的限速/频控——仅真实部署在可信反代/CDN 后才可配置 |
| SR-5 | SMTP 口令备份擦洗：在线备份为全文件复制、逐行排除不可行，备份完成后对目标备份文件 DELETE site_config.smtp_pass（原库零触碰、轮转逻辑零动）；恢复语义=恢复后 SMTP 需重录 |

## NC-x（通知调度中枢条款，后端完善批 BE-2 增补；条文正文随外层治理文档 doc/BE/BE-2-任务书.md 落册）

| 编号 | 一句话摘要 |
|---|---|
| NC-1 | 通知统管与双闸：全部通知消费方（六类告警触发器+测试邮件端点）一律经 app/notify/hub.enqueue 入队（五关：注册表未知→unknown_category WARN/通道未配置→not_configured 仅落日志/去重预检（持久化时间戳+在队同键）→deduped/digest 族全局开关关拒收→digest_disabled），flush 按 APScheduler job notify_flush（IntervalTrigger 15s，max_instances=1/coalesce，不传 next_run_time=不启动即跑）按入队序投递；账户硬间隔 ACCOUNT_HARD_INTERVAL_S=60 代码常量「硬」不可配+类别最小间隔 site_config notify_category_intervals 覆盖（缺省注册表 default_min_interval_s=0=仅账户闸，行为最接近现状）双闸未到留队冷却缓存；投递失败 WARN 丢弃不重试（告警类下轮触发兜底）；队列操作持 threading.Lock、投递锁外（fetch/score/hot/backup 多 job 并行既有形态）；Notifier.send() 保留为同步直发原语（不经队列不经双闸，新消费方一律 hub.enqueue） |
| NC-2 | 去重落账时序与键治理：去重时间戳仅投递成功才落（入队即落会在 flush 前进程重启时既丢消息又留 24h 抑制）；窗口 site_config notify_dedup_window_hours（缺省 24=DEDUP_WINDOW_HOURS 常量回退）；notify_last_sent_% 键 flush 时惰性清理（距上次清理 >1h 节流；最后发送时间早于窗口+24h 宽限即删，site_config 行数小全扫可接受，坏值不清不炸）；队列与锚点进程内、重启即丢=接受语义（文档性测试 _reset_for_tests 后断言空队钉死，防未来误加持久化而不自知） |
| NC-3 | 缓冲上限与丢弃序：每账户（=通道名，当前唯一 smtp）ACCOUNT_QUEUE_CAP=10 代码常量，溢出按丢弃序逐条挤出——digest 族→priority 数值大者→同级丢最新入队者（丢新留旧），逐条 log.warning（含 category 与原因）+计数；hub.snapshot()={queue_depth,delivered_total,dropped_total(按 category),deduped_total} 进程内计数，pipeline_stats_payload 增 notify_queue_depth/notify_dropped_total 两键（纯增量） |
| NC-4 | 类别注册表：hub.CATEGORY_REGISTRY 十条目（六类现有告警 source_hard_fail/source_suspect/token_budget/collective_degradation/disk_usage priority=1+reconcile priority=2+notify_test priority=2（测试邮件专用，唯一时间戳键不参与抑制）+三骨架位 provider_switched/balance_low/llm_error_rate_high priority=1（BE-7 接线，本批只注册无消费方））；条目字段 {family: alert\|digest, priority, default_min_interval_s}，测试与实现共用防漂移；digest 族本批零条目，仅全局开关 notify_digest_enabled（缺省 False）与 enqueue 拒收分支（D5 接口预留） |
| NC-5 | 五缝隙收口：(a) admin 四通知开关去 disabled 改 v-model（notifySwitches）并入 saveNotify 提交载荷+补第五开关 notify_on_reconcile（i18n 按命名族补 notifyOnReconcile）；(b) _NOTIFY_SWITCH_KEYS/NotifySettingsIn 增 notify_on_reconcile（PUT/GET 同步）；(c) 去重窗口可配（见 NC-2）；(d) 键惰性清理（见 NC-2）；(e) 测试邮件端点 POST /settings/notify/test 改经中枢同步试发（enqueue category=notify_test+flush 一次，响应 {"sent":true} 或 {"sent":false,"reason":account_interval\|deliver_failed\|not_configured} 如实反映，SMTP 未配置仍 502 SMTP_UNREACHABLE）——SMTP 为非 HTTP 独立通道不入出网收口（D9 定性保留） |

## SM-x（采集状态机条款，后端完善批 BE-3 增补；条文正文随外层治理文档 doc/BE/BE-3-任务书.md 落册）

| 编号 | 一句话摘要 |
|---|---|
| SM-1 | hard_failed 复活路径：_update_source_health 成功分支（非空或 304）复位条件由仅 suspect 扩为 suspect/hard_failed——复位 level=none+failure_since=None+last_probe_at=None（hard_failures/empty_rounds 现行已清）；复活通知 notify_source_recovered（category=source_recovered、dedupe_key=source-{id}、开关=notify_on_source_failure 同族不新增键、文案「来源已复活恢复采集」+id/url+时间）只在 hard_failed→none 转换挂、suspect→none 不通知；CATEGORY_REGISTRY 增 source_recovered（alert/priority=2，与 reconcile 同档低紧迫，注册表增至十一条目） |
| SM-2 | 死刑源周探活窗口与配额：纯函数 skip_policy.hard_failed_probe_due(src,*,now)=failure_level==hard_failed 且 failure_since 距 now≥HARD_FAIL_PROBE_EVERY_DAYS（缺省 7 天，进入死刑态满 7 天才首探）且（last_probe_at is None 或距 now≥7 天）；配额放行在 enqueue_fetch_round 层——主循环前预扫描 due 死源按 (last_probe_at or failure_since) 最老优先取前 HARD_FAIL_PROBE_QUOTA（缺省 5）名入放行集强制入队+log.info，配额外的 due 死源照旧 skipped（reason 保持 "hard_failed" 值域零增，skip_reason hard_failed 分支零改、纯函数不知配额）；防探活排满（D6） |
| SM-3 | 探活记账语义：Source.last_probe_at（DATETIME nullable，db.py additions 加列、历史行 NULL=从未探活）=「最近一次死刑探活尝试时刻」——成败都算（尝试即记账，探活失败 404/403/410 也冷却 7 天防同一批死源霸占配额）；enqueue 入队时即记账（worker 崩溃不重探）；复活（SM-1）时一并清空；与 failure_since（「进入当前失效态时间」语义，A4 钉死）严格分置不得挪用——探活判据双钟（failure_since 满 7 天+last_probe_at 满 7 天）缺一不可 |
| SM-4 | 哨兵分母出清与旧账修正：纯函数 skip_policy.is_stale_dead(src,*,now,stale_days)=hard_failed 且 failure_since 距 now>stale_days（严格大于；suspect 与缺 failure_since 的历史行永不出清）；聚合哨兵（check_collective_sentinel，增 now 可注入参数）与体检载荷 degraded_sources_count 两处同构降级桶改为「suspect 或（hard_failed 且非陈旧）或 rate_limited_until（_aware 归一）>now」——rate_limited_until 补 now 比较（过期旧账不再计入）、stale_days 读 site_config sentinel_exclude_stale_days（缺省 30，DEFAULTS 同步）；只动降级分子，enabled 分母与源状态本体不变（死源后台仍可见 hard_failed，_source_out 呈现面零改） |
