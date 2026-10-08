/*
 * nw-score-badge.js — 评分胶囊（等宽字体灰底，设计稿 score-badge 提炼）
 */
export const NwScoreBadge = {
  name: "NwScoreBadge",
  props: {
    value: { type: [Number, String], default: null },
    label: { type: String, default: "" },
  },
  template: `
    <span class="score-badge"><span v-if="label">{{ label }}</span>{{ value === null || value === '' ? '—' : value }}</span>
  `,
};
