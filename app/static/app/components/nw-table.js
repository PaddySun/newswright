/*
 * nw-table.js — 数据表（公共组件层：columns 配置 + 单元格 slot）
 *
 * columns: [{key, label, width?}]；rows: [对象数组]；单元格默认取 row[key]，
 * 命名 slot（cell-<key>）可整体替换单元格内容。
 */
export const NwTable = {
  name: "NwTable",
  props: {
    columns: { type: Array, required: true },
    rows: { type: Array, required: true },
  },
  template: `
    <table class="data-table">
      <thead>
        <tr><th v-for="col in columns" :key="col.key" :style="col.width ? {width: col.width} : {}">{{ col.label }}</th></tr>
      </thead>
      <tbody>
        <tr v-for="(row, rowIndex) in rows" :key="rowIndex">
          <td v-for="col in columns" :key="col.key">
            <slot :name="'cell-' + col.key" :row="row">{{ row[col.key] }}</slot>
          </td>
        </tr>
      </tbody>
    </table>
  `,
};
