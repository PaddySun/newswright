/*
 * nw-form-field.js — 表单字段壳（公共组件层：label + 控件 slot + 提示/错误）
 */
export const NwFormField = {
  name: "NwFormField",
  props: {
    label: { type: String, required: true },
    hint: { type: String, default: "" },
    error: { type: String, default: "" },
  },
  template: `
    <div class="form-field">
      <label>{{ label }}</label>
      <slot></slot>
      <p v-if="hint" class="field-hint">{{ hint }}</p>
      <p v-if="error" class="field-error">{{ error }}</p>
    </div>
  `,
};
