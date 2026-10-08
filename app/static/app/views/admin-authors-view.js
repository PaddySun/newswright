/*
 * admin-authors-view.js — 作者配置（US-10 呈现面 / AC-10.1 round-trip 前端）
 *
 * 消费技术书 §3 在册契约：POST /api/authors/import（201 新建 / 200 同名更新 /
 * 400 AUTHOR_JSON_INVALID）、GET /api/authors/{id}/export（下载）。
 *
 * ⚠ 契约缺口（已呈报统筹，执行侧不自改后端）：两端点在技术书 §3 在册但后端
 * 尚未实现（authors/importer.py 库函数已就绪、HTTP 层未接线）；作者列表/
 * 模型绑定/bio 编辑无任何在册契约，本视图不做越界实现。运行时导入/导出
 * 将 404/405，直至后端补齐。
 */
import { api, ApiError } from "../api.js";

export default {
  name: "AdminAuthorsView",
  data() {
    return {
      error: "",
      notice: "",
      importBusy: false,
      exportId: "",
    };
  },
  methods: {
    async importJson(event) {
      const file = event.target.files && event.target.files[0];
      event.target.value = "";
      if (!file) return;
      this.error = "";
      this.notice = "";
      this.importBusy = true;
      try {
        const text = await file.text();
        const payload = JSON.parse(text);
        if (payload && Object.prototype.hasOwnProperty.call(payload, "model")) {
          // AC-10.2 呈现面：JSON 内出现 model 键=前置拦截提示（服务端校验同样拒绝）
          this.error = this.$t("adminAuthors.modelKeyForbidden");
          return;
        }
        const result = await api.post("/api/authors/import", payload);
        this.notice = result && result.updated
          ? this.$t("adminAuthors.importUpdated")
          : this.$t("adminAuthors.importCreated");
      } catch (err) {
        if (err instanceof SyntaxError) {
          this.error = this.$t("adminAuthors.importInvalid");
        } else if (err instanceof ApiError && err.status === 400) {
          this.error = `${this.$t("adminAuthors.importInvalid")}：${err.message}`;
        } else {
          this.error = err.message || this.$t("common.errorGeneric");
        }
      } finally {
        this.importBusy = false;
      }
    },
    async exportJson() {
      this.error = "";
      this.notice = "";
      const id = Number(this.exportId);
      if (!id) {
        this.error = this.$t("common.requiredMissing");
        return;
      }
      try {
        const payload = await api.get(`/api/authors/${id}/export`);
        const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
        const link = document.createElement("a");
        link.href = URL.createObjectURL(blob);
        link.download = `author-${id}.json`;
        link.click();
        URL.revokeObjectURL(link.href);
      } catch {
        this.error = this.$t("adminAuthors.exportFailed");
      }
    },
  },
  template: `
    <section>
      <div class="view-heading">
        <p class="eyebrow">ADMIN / {{ $t("nav.adminAuthors") }}</p>
        <h1 class="page-serif-headline" style="font-size:44px;">{{ $t("adminAuthors.heading") }}</h1>
      </div>

      <nw-alert-bar v-if="error" tone="danger">{{ error }}</nw-alert-bar>
      <nw-alert-bar v-if="notice" tone="ok">{{ notice }}</nw-alert-bar>

      <div class="admin-section">
        <div class="card-base" style="margin-bottom:24px;">
          <p class="admin-section-title">{{ $t("adminAuthors.importTitle") }}</p>
          <p class="muted-note" style="margin-top:0;">{{ $t("adminAuthors.importHint") }}</p>
          <input type="file" accept=".json,application/json" @change="importJson" :disabled="importBusy">
        </div>
        <div class="card-base">
          <p class="admin-section-title">{{ $t("adminAuthors.exportTitle") }}</p>
          <p class="muted-note" style="margin-top:0;">{{ $t("adminAuthors.exportHint") }}</p>
          <div class="inline-form">
            <nw-form-field :label="$t('adminAuthors.exportAuthorId')">
              <input class="form-input" type="number" v-model="exportId" style="min-width:120px;">
            </nw-form-field>
            <nw-button size="sm" @click="exportJson">{{ $t("adminAuthors.exportSubmit") }}</nw-button>
          </div>
        </div>
      </div>
    </section>
  `,
};
