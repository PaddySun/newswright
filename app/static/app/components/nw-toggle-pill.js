/*
 * nw-toggle-pill.js — 布尔开关按钮（公共组件层；仅收藏/最高分形态）
 */
export const NwTogglePill = {
  name: "NwTogglePill",
  props: {
    active: { type: Boolean, default: false },
    label: { type: String, required: true },
  },
  emits: ["toggle"],
  template: `
    <button type="button" class="toggle-btn" :class="{ active }"
            :aria-pressed="active" @click="$emit('toggle')">{{ label }}</button>
  `,
};
