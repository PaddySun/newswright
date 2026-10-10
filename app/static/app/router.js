/*
 * router.js — 轻量 hash 路由（裁定①免构建形态，自研 ≤100 行）
 *
 * 路由表 path → 视图组件；hash 变更 → 匹配渲染。视图按对象命名。
 * 免构建形态下不做按需加载（单进程内少量视图，一次引入）。
 */
import { reactive, markRaw } from "../vendor/vue.esm-browser.prod.js";
import StreamBrowseView from "./views/stream-browse-view.js";
import ArticleListView from "./views/article-list-view.js";
import ArticleDetailView from "./views/article-detail-view.js";
import AdminDirectionsView from "./views/admin-directions-view.js";
import AdminAuthorsView from "./views/admin-authors-view.js";
import AdminWriteView from "./views/admin-write-view.js";
import AdminSystemView from "./views/admin-system-view.js";

// 路由表：B 流浏览 + C 流文章列表/详情 + 后台四页（方向与来源/作者配置/
// 写作面板/系统管理）——admin hash 曾漏注册致全部回退浏览视图，浏览器亲测抓出
const routes = [
  { path: "/stream", component: markRaw(StreamBrowseView) },
  { path: "/articles", component: markRaw(ArticleListView) },
  { path: "/articles/:id", component: markRaw(ArticleDetailView) },
  { path: "/admin/directions", component: markRaw(AdminDirectionsView) },
  { path: "/admin/authors", component: markRaw(AdminAuthorsView) },
  { path: "/admin/write", component: markRaw(AdminWriteView) },
  { path: "/admin/system", component: markRaw(AdminSystemView) },
];

export const route = reactive({ path: "/", params: {}, component: null });

function currentHash() {
  const raw = window.location.hash.replace(/^#/, "");
  return raw.startsWith("/") ? raw : "/stream";
}

function match(path) {
  for (const candidate of routes) {
    const pathParts = candidate.path.split("/").filter(Boolean);
    const givenParts = path.split("/").filter(Boolean);
    if (pathParts.length !== givenParts.length) continue;
    const params = {};
    let ok = true;
    for (let i = 0; i < pathParts.length; i++) {
      if (pathParts[i].startsWith(":")) {
        params[pathParts[i].slice(1)] = decodeURIComponent(givenParts[i]);
      } else if (pathParts[i] !== givenParts[i]) {
        ok = false;
        break;
      }
    }
    if (ok) return { component: candidate.component, params };
  }
  return null;
}

export function navigate(path) {
  window.location.hash = path;
}

export function installRouter(app) {
  function apply() {
    const path = currentHash();
    const found = match(path) || match("/stream");
    route.path = path;
    route.params = found.params;
    route.component = found.component;
  }
  window.addEventListener("hashchange", apply);
  apply();
  app.provide("route", route);
  app.provide("navigate", navigate);
}
