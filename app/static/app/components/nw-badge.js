/*
 * nw-badge.js — 状态徽标（公共组件层）
 *
 * tone 语义：ok=正常/启用、warn=降频/疑似、danger=硬失效/失败、info=处理中、
 * neutral=停用/未知——四级色彩语义与设计稿 badge 族对应。
 */
export const NwBadge = {
  name: "NwBadge",
  props: {
    tone: { type: String, default: "neutral" }, // ok | warn | danger | info | neutral
  },
  computed: {
    classes() { return ["status-badge", this.tone]; },
  },
  template: `
    <span :class="classes"><slot></slot></span>
  `,
};
