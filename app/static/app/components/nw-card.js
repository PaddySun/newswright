/*
 * nw-card.js — 卡片容器（公共组件层）
 *
 * 视觉来源：设计稿卡片（4px 圆角、1px 描边、无阴影、可选 6px 主色左缘）提炼。
 */
export const NwCard = {
  name: "NwCard",
  props: {
    accent: { type: String, default: "" }, // "" | primary | accent
  },
  computed: {
    classes() {
      return [
        "card-base",
        this.accent === "primary" ? "accent-left-primary" : "",
        this.accent === "accent" ? "accent-left-accent" : "",
      ];
    },
  },
  template: `
    <div :class="classes">
      <slot></slot>
    </div>
  `,
};
