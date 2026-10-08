/*
 * i18n.js — vue-i18n 装配（裁定⑦）
 *
 * 单一 zh-CN 语言包挂载；不引入语言切换机制、不建其他语言包（结构留空
 * 为将来翻译位）。组件内一律 t("key")。
 */
import { createI18n } from "../vendor/vue-i18n.esm-browser.prod.js";
import zhCN from "./locales/zh-CN.js";

export const i18n = createI18n({
  legacy: false,
  locale: "zh-CN",
  fallbackLocale: "zh-CN",
  messages: { "zh-CN": zhCN },
});
