/*
 * store.js — SPA 轻量会话状态（免构建形态，reactive 单例）
 *
 * 只承载跨视图的少量状态（当前用户名等）；页面数据一律视图内拉取，
 * 不进全局 store。
 */
import { reactive } from "../vendor/vue.esm-browser.prod.js";

export const store = reactive({
  username: "",
});

export function setSessionUser(username) {
  store.username = username || "";
}
