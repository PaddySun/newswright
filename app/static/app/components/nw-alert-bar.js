/*
 * nw-alert-bar.js — 警示条（公共组件层）
 *
 * tone: danger | warn | info | ok——左侧色缘 + 软底色，与登录页 form-alert 同语言。
 */
export const NwAlertBar = {
  name: "NwAlertBar",
  props: {
    tone: { type: String, default: "warn" },
  },
  computed: {
    classes() { return ["alert-bar", `alert-${this.tone}`]; },
  },
  template: `
    <div :class="classes" role="alert"><slot></slot></div>
  `,
};
