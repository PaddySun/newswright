/*
 * nw-empty-state.js — 空态（公共组件层）
 */
export const NwEmptyState = {
  name: "NwEmptyState",
  props: {
    title: { type: String, required: true },
    hint: { type: String, default: "" },
  },
  template: `
    <div class="empty-state">
      <h3 class="card-serif-title">{{ title }}</h3>
      <p v-if="hint" class="muted-note">{{ hint }}</p>
      <slot></slot>
    </div>
  `,
};
