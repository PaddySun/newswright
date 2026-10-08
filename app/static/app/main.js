/*
 * main.js — SPA 装配入口（裁定①免构建 Vue3 ESM）
 *
 * 形态：import map 解析 "vue"/"vue-i18n" → app/static/vendor/；hash 路由；
 * 公共组件全局注册（模板字符串组件）。宿主页面 /app 由 Jinja2 渲染
 * （app.html.j2），本模块挂载 #app。
 */
import { createApp } from "../vendor/vue.esm-browser.prod.js";
import Root from "./root-component.js";
import { i18n } from "./i18n.js";
import { installRouter } from "./router.js";
import {
  NwButton, NwCard, NwTag, NwBadge, NwAlertBar, NwModal, NwFormField,
  NwTable, NwEmptyState, NwPagination, NwScoreBadge, NwTabBar, NwTogglePill,
} from "./components/index.js";

const app = createApp(Root);
app.use(i18n);
for (const component of [
  NwButton, NwCard, NwTag, NwBadge, NwAlertBar, NwModal, NwFormField,
  NwTable, NwEmptyState, NwPagination, NwScoreBadge, NwTabBar, NwTogglePill,
]) {
  app.component(component.name, component);
}
installRouter(app);
app.mount("#app");
