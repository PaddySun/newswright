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
