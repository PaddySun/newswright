# frontend — Vue3 SPA 工作区（G0 骨架占位）

按技术设计书 ADR-7（D3 呈现形态）：**登录态浏览页（B 流/C 流）与后台管理为 Vue3 SPA**；公开页/登录页为 Jinja2 SSR（见 `app/templates/`）。

- 构建工具 **Vite**；构建产物 `dist/` 由 FastAPI 静态托管（同一进程，不引入 Node 运行时部署依赖——构建期产物提交形态由 UI 里程碑定）。
- **契约 = 技术设计书 §3 OpenAPI**（`/api/**` 端点，前后端单一事实来源）；错误体统一 `{"code","message"}`。
- 本目录 G0 期间为零依赖骨架（无 package.json、无 node_modules）；脚手架初始化属后续 UI 里程碑。
- `main.py` 的根 JSON 提示页保持不动，路由挂载在 UI 里程碑处理。
