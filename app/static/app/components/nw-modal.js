/*
 * nw-modal.js — 确认弹窗（公共组件层；slot 承载正文文案）
 */
export const NwModal = {
  name: "NwModal",
  props: {
    open: { type: Boolean, required: true },
    title: { type: String, default: "" },
    confirmText: { type: String, default: "" },
    cancelText: { type: String, default: "" },
  },
  emits: ["confirm", "cancel"],
  template: `
    <div v-if="open" class="modal-backdrop" @click.self="$emit('cancel')">
      <div class="modal-panel" role="dialog" aria-modal="true">
        <h3 class="modal-title">{{ title }}</h3>
        <div class="modal-body"><slot></slot></div>
        <div class="modal-actions">
          <nw-button variant="ghost" size="sm" @click="$emit('cancel')">{{ cancelText }}</nw-button>
          <nw-button size="sm" @click="$emit('confirm')">{{ confirmText }}</nw-button>
        </div>
      </div>
    </div>
  `,
};
