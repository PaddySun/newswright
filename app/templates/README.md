# app/templates — SSR 模板（公开页 + 登录页，UI 里程碑落地）

按技术设计书 ADR-7（D3 呈现形态）：**公开页/登录页使用 Jinja2 SSR**；登录态
浏览页与后台为 Vue3 SPA（`app/static/app/`，免构建 ESM 形态）。

文件按页面命名（Gx 纪律三）：

| 文件 | 页面对象 |
|---|---|
| `base.html.j2` | 公共骨架（头部导航/页脚/OG 注入位/静态版本引用） |
| `_copy.html.j2` | SSR 界面文案块（键名与 SPA 语言包 zh-CN.js 对齐，裁定⑦） |
| `compliance-404.html.j2` | 404 合规页（模式 A 一切公开路由落点，AC-02.1/02.2） |
| `public-home.html.j2` | 公开首页（模式 B 降深列表 / 模式 C 文章卡片流） |
| `public-article.html.j2` | 公开文章页（白名单渲染 + AI 标识 + 访客点赞） |
| `public-author.html.j2` | 作者公开页（public_visible 过滤） |
| `login.html.j2` | 登录页（全模式可达；交互由 `static/app/login-view.js` 挂载） |
| `sitemap.xml.j2` | sitemap（AC-16.3） |

路由与模式分发在 `app/api/public.py`；Markdown 白名单渲染器（纯逻辑）在
`app/api/public_render.py`。SSR 与 SPA 共享同一契约（技术书 §3）：SSR 服务端
消费、SPA 浏览器消费。
