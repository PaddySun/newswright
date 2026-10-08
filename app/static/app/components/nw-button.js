/*
 * nw-button.js — 胶囊按钮（公共组件层，裁定⑧：props 驱动、零页面逻辑）
 *
 * 视觉来源：设计稿胶囊按钮（border-radius 999px、三主色变体）提炼。
 * variant: primary | secondary | ghost | danger-ghost；size: md | sm。
 */
export const NwButton = {
  name: "NwButton",
  props: {
    variant: { type: String, default: "primary" },
    size: { type: String, default: "md" },
    type: { type: String, default: "button" },
    disabled: { type: Boolean, default: false },
    block: { type: Boolean, default: false },
  },
  emits: ["click"],
  computed: {
    classes() {
      const tone = {
        primary: "btn-primary",
        secondary: "btn-secondary",
        ghost: "btn-ghost",
        "danger-ghost": "btn-danger-ghost",
      }[this.variant] || "btn-primary";
      return ["btn-pill", tone, this.size === "sm" ? "btn-sm" : "", this.block ? "btn-block" : ""];
    },
  },
  template: `
    <button :type="type" :class="classes" :disabled="disabled"
            @click="$emit('click', $event)"><slot></slot></button>
  `,
};
