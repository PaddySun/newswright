/*
 * nw-tab-bar.js — 胶囊 Tab 组（公共组件层；设计稿 toggle-group 提炼）
 */
export const NwTabBar = {
  name: "NwTabBar",
  props: {
    tabs: { type: Array, required: true }, // [{value, label}]
    modelValue: { type: [String, Number], required: true },
  },
  emits: ["update:modelValue"],
  template: `
    <div class="toggle-group" role="tablist">
      <button v-for="tab in tabs" :key="tab.value" type="button" role="tab"
              class="toggle-btn" :class="{ active: tab.value === modelValue }"
              :aria-selected="tab.value === modelValue"
              @click="$emit('update:modelValue', tab.value)">{{ tab.label }}</button>
    </div>
  `,
};
