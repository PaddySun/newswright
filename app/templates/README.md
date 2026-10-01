# app/templates — SSR 模板位（G0 骨架占位）

按技术设计书 ADR-7（D3 呈现形态）：**公开页/登录页使用 Jinja2 SSR**（meta/sitemap/robots/Feed 天然满足 SEO 需求）；登录态浏览页与后台为 Vue3 SPA（见 `frontend/`）。

- `base.html.j2` 为唯一占位文件——正式 UI 里程碑在此扩展公开页模板（模式 A 404 / 模式 B 降深列表 / 模式 C 文章页，见产品书 US-02/US-16）。
- 页面实现属后续 UI 里程碑，G0 只建目录骨架，不含任何页面代码。
- SSR 与 SPA 共享同一 OpenAPI 契约（技术书 §3）：SSR 服务端消费、SPA 浏览器消费。
