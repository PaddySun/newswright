/*
 * nw-tag.js — 标签 chip（公共组件层）
 */
export const NwTag = {
  name: "NwTag",
  props: {
    active: { type: Boolean, default: false },
  },
  emits: ["click"],
  computed: {
    classes() { return ["tag-chip-base", this.active ? "tag-chip-active" : ""]; },
  },
  template: `
    <span :class="classes" @click="$emit('click', $event)"><slot></slot></span>
  `,
};
