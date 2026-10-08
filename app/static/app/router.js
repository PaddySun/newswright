/*
 * router.js — 轻量 hash 路由（裁定①免构建形态，自研 ≤100 行）
 *
 * 路由表 path → 视图组件；hash 变更 → 匹配渲染。视图按对象命名。
 * 免构建形态下不做按需加载（单进程内少量视图，一次引入）。
 */
import { reactive, markRaw } from "../vendor/vue.esm-browser.prod.js";
import StreamBrowseView from "./views/stream-browse-view.js";

// 路由表：W2 段收录 B 流浏览；C 流文章与后台四页视图随 W3/W4 段入表
const routes = [
  { path: "/stream", component: markRaw(StreamBrowseView) },
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
