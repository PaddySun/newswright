/*
 * nw-pagination.js — 分页条（公共组件层）
 */
export const NwPagination = {
  name: "NwPagination",
  props: {
    page: { type: Number, required: true },
    pages: { type: Number, required: true },
    prevText: { type: String, default: "" },
    nextText: { type: String, default: "" },
  },
  emits: ["change"],
  template: `
    <div class="pager-row">
      <button class="pager-btn" :disabled="page <= 1" @click="$emit('change', page - 1)">{{ prevText || '‹' }}</button>
      <span class="pager-info">{{ page }} / {{ pages }}</span>
      <button class="pager-btn" :disabled="page >= pages" @click="$emit('change', page + 1)">{{ nextText || '›' }}</button>
    </div>
  `,
};
