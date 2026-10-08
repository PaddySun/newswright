/*
 * admin-directions-view.js — 方向与来源管理（US-03/US-04 呈现面）
 *
 * 消费既有契约（技术书 §3）：方向 CRUD（/api/directions*）、rescore 202、
 * refresh-keyword、来源 CRUD（/api/directions/{id}/sources、/api/sources/{id}）。
 * 失效三级徽标（failure_level：none/suspect/hard_failed 色彩语义）+ 降频状态
 * （rate_limited_until）呈现。
 */
import { api } from "../api.js";

export default {
  name: "AdminDirectionsView",
  data() {
    return {
      loading: false,
      error: "",
      notice: "",
      directions: [],
      sources: {}, // direction_id → 来源数组
      creatingDirection: false,
      newDirection: { name: "", prompt: "", threshold: 60 },
      sourceFormFor: null,
      newSource: { url: "", type: "rss" },
      confirmDelete: null, // {kind, id, name}
    };
  },
  computed: {
    directionColumns() {
      return [
        { key: "name", label: this.$t("adminDirections.directionName") },
        { key: "threshold", label: this.$t("adminDirections.directionThreshold"), width: "80px" },
        { key: "status", label: this.$t("adminDirections.directionStatus"), width: "90px" },
        { key: "temp", label: this.$t("adminDirections.directionTemp"), width: "90px" },
        { key: "actions", label: "", width: "260px" },
      ];
    },
  },
  mounted() { this.load(); },
  methods: {
    async load() {
      this.loading = true;
      this.error = "";
      try {
        this.directions = await api.get("/api/directions");
        for (const direction of this.directions) {
          this.loadSources(direction.id);
        }
      } catch (err) {
        this.error = err.message || this.$t("common.errorGeneric");
      } finally {
        this.loading = false;
      }
    },
    async loadSources(directionId) {
      try {
        this.sources = { ...this.sources, [directionId]: await api.get(`/api/directions/${directionId}/sources`) };
      } catch { this.sources = { ...this.sources, [directionId]: [] }; }
    },
    statusTone(status) {
      return { active: "ok", disabled: "neutral", expired: "warn", deleted: "danger" }[status] || "neutral";
    },
    failureTone(level) {
      return { none: "ok", suspect: "warn", hard_failed: "danger" }[level] || "neutral";
    },
    failureLabel(level) {
      return {
        none: this.$t("adminDirections.failureNone"),
        suspect: this.$t("adminDirections.failureSuspect"),
        hard_failed: this.$t("adminDirections.failureHard"),
      }[level] || level;
    },
    isRateLimited(source) {
      return Boolean(source.rate_limited_until);
    },
    async createDirection() {
      this.error = "";
      this.notice = "";
      try {
        await api.post("/api/directions", this.newDirection);
        this.newDirection = { name: "", prompt: "", threshold: 60 };
        this.creatingDirection = false;
        await this.load();
      } catch (err) {
        // 409 DIRECTION_NAME_EXISTS / 400 VALIDATION_ERROR 规范错误直呈
        this.error = err.message || this.$t("common.errorGeneric");
      }
    },
    async rescore(direction) {
      this.error = "";
      this.notice = "";
      try {
        await api.post(`/api/directions/${direction.id}/rescore`, {});
        this.notice = this.$t("adminDirections.rescoreQueued");
      } catch (err) {
        this.error = err.message || this.$t("common.errorGeneric");
      }
    },
    async refreshKeyword(direction) {
      this.error = "";
      this.notice = "";
      try {
        const result = await api.post(`/api/directions/${direction.id}/refresh-keyword`);
        this.notice = this.$t("adminDirections.refreshKeywordDone", { reset: result.reset });
      } catch (err) {
        this.error = err.message || this.$t("common.errorGeneric");
      }
    },
    async submitDelete() {
      const target = this.confirmDelete;
      if (!target) return;
      this.confirmDelete = null;
      try {
        if (target.kind === "direction") {
          await api.delete(`/api/directions/${target.id}`);
        } else {
          await api.delete(`/api/sources/${target.id}`);
        }
        await this.load();
      } catch (err) {
        this.error = err.message || this.$t("common.errorGeneric");
      }
    },
    async createSource(direction) {
      this.error = "";
      try {
        await api.post(`/api/directions/${direction.id}/sources`, this.newSource);
        this.newSource = { url: "", type: "rss" };
        this.sourceFormFor = null;
        await this.loadSources(direction.id);
      } catch (err) {
        this.error = err.message || this.$t("common.errorGeneric");
      }
    },
  },
  template: `
    <section>
      <div class="view-heading">
        <p class="eyebrow">ADMIN / {{ $t("nav.adminDirections") }}</p>
        <div class="view-heading-row">
          <h1 class="page-serif-headline" style="font-size:44px;">{{ $t("adminDirections.heading") }}</h1>
          <span class="toolbar-spacer"></span>
          <nw-button size="sm" @click="creatingDirection = !creatingDirection">{{ $t("adminDirections.createDirection") }}</nw-button>
        </div>
      </div>

      <nw-alert-bar v-if="error" tone="danger">{{ error }}</nw-alert-bar>
      <nw-alert-bar v-if="notice" tone="ok">{{ notice }}</nw-alert-bar>

      <div v-if="creatingDirection" class="card-base" style="margin-bottom:24px;">
        <div class="inline-form">
          <nw-form-field :label="$t('adminDirections.directionName')">
            <input class="form-input" v-model="newDirection.name"
                   :placeholder="$t('adminDirections.directionNamePlaceholder')">
          </nw-form-field>
          <nw-form-field :label="$t('adminDirections.directionThreshold')"
                         :hint="$t('adminDirections.thresholdHint')">
            <input class="form-input" type="number" v-model="newDirection.threshold">
          </nw-form-field>
          <nw-button size="sm" @click="createDirection">{{ $t("common.create") }}</nw-button>
        </div>
        <nw-form-field :label="$t('adminDirections.directionPrompt')">
          <textarea class="comment-textarea" v-model="newDirection.prompt"
                    :placeholder="$t('adminDirections.directionPromptPlaceholder')"></textarea>
        </nw-form-field>
      </div>

      <nw-table :columns="directionColumns" :rows="directions">
        <template v-slot:cell-status="{ row }">
          <nw-badge :tone="statusTone(row.status)">{{ row.status }}</nw-badge>
        </template>
        <template v-slot:cell-temp="{ row }">
          <span v-if="row.temp" class="mono-text">{{ row.expires_at || 'TTL' }}</span>
          <span v-else class="muted-note">—</span>
        </template>
        <template v-slot:cell-actions="{ row }">
          <div style="display:flex;gap:8px;flex-wrap:wrap;">
            <nw-button variant="ghost" size="sm" @click="rescore(row)">{{ $t("adminDirections.rescore") }}</nw-button>
            <nw-button variant="ghost" size="sm" @click="refreshKeyword(row)">{{ $t("adminDirections.refreshKeyword") }}</nw-button>
            <nw-button variant="ghost" size="sm" @click="sourceFormFor = sourceFormFor === row.id ? null : row.id">{{ $t("adminDirections.createSource") }}</nw-button>
            <nw-button variant="danger-ghost" size="sm"
                       @click="confirmDelete = { kind: 'direction', id: row.id }">{{ $t("common.delete") }}</nw-button>
          </div>
        </template>
      </nw-table>

      <template v-for="direction in directions" :key="direction.id">
        <div class="admin-section" style="margin-top:32px;">
          <p class="admin-section-title">{{ $t("adminDirections.sourcesOf") }} · {{ direction.name }}</p>
          <div v-if="sourceFormFor === direction.id" class="inline-form">
            <nw-form-field :label="$t('adminDirections.sourceUrl')">
              <input class="form-input" v-model="newSource.url" style="min-width:280px;">
            </nw-form-field>
            <nw-form-field :label="$t('adminDirections.sourceType')">
              <select class="select-pill" v-model="newSource.type">
                <option value="rss">rss</option><option value="web">web</option><option value="search">search</option>
              </select>
            </nw-form-field>
            <nw-button size="sm" @click="createSource(direction)">{{ $t("common.create") }}</nw-button>
          </div>
          <nw-table :columns="[
            { key: 'url', label: $t('adminDirections.sourceUrl') },
            { key: 'type', label: $t('adminDirections.sourceType'), width: '80px' },
            { key: 'failure_level', label: $t('adminDirections.sourceFailure'), width: '120px' },
            { key: 'rate', label: $t('adminDirections.sourceRateLimited'), width: '90px' },
            { key: 'actions', label: '', width: '90px' }]" :rows="sources[direction.id] || []">
            <template v-slot:cell-failure_level="{ row }">
              <nw-badge :tone="failureTone(row.failure_level)">{{ failureLabel(row.failure_level) }}</nw-badge>
            </template>
            <template v-slot:cell-rate="{ row }">
              <nw-badge v-if="isRateLimited(row)" tone="warn">{{ $t("adminDirections.sourceRateLimited") }}</nw-badge>
              <span v-else class="muted-note">—</span>
            </template>
            <template v-slot:cell-actions="{ row }">
              <nw-button variant="danger-ghost" size="sm"
                         @click="confirmDelete = { kind: 'source', id: row.id }">{{ $t("common.delete") }}</nw-button>
            </template>
          </nw-table>
        </div>
      </template>

      <nw-modal :open="Boolean(confirmDelete)"
                :title="$t('common.confirm')"
                :confirm-text="$t('common.confirm')" :cancel-text="$t('common.cancel')"
                @confirm="submitDelete" @cancel="confirmDelete = null">
        <p>{{ confirmDelete && confirmDelete.kind === 'direction'
              ? $t('adminDirections.confirmDeleteDirection')
              : $t('adminDirections.confirmDeleteSource') }}</p>
      </nw-modal>
    </section>
  `,
};
