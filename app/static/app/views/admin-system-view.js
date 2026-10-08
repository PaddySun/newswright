/*
 * admin-system-view.js — 系统管理（US-17/18/19/06 呈现面）
 *
 * 消费既有契约：/healthz（三态）、/api/stats/pipeline（体检+聚合哨兵）、
 * /api/usage/summary（Token 用量）、/api/settings/notify GET/PUT/test（凭据
 * 只写不读）、/api/settings/usage/reconcile（月度对账）、/api/hot/board（热点
 * 面板）、/api/hot/to-direction（一键转方向——确认弹窗呈现"创建即确认"语义，
 * AC-17.2）、/api/stats/filters（过滤统计，AC-06.1）。
 */
import { api } from "../api.js";

export default {
  name: "AdminSystemView",
  data() {
    return {
      error: "",
      notice: "",
      health: null,        // {status: 200|503, payload}
      pipeline: null,
      usage: null,
      filters: null,
      hot: null,           // {direction_id, keywords, hot_trends}
      hotDirectionId: "",
      notifyForm: { smtp_host: "", smtp_port: 465, smtp_user: "", smtp_pass: "", from_addr: "", to_addrs: "" },
      notifyState: null,   // GET 回显（smtp_configured + 开关们）
      notifyTest: "",      // ok | failed | ""
      reconcile: { month: "", platform_billed_units: null },
      reconcileResult: null,
    };
  },
  mounted() { this.loadAll(); },
  methods: {
    async loadAll() {
      await Promise.all([
        this.loadHealth(), this.loadPipeline(), this.loadUsage(),
        this.loadNotify(), this.loadFilters(),
      ]);
    },
    async loadHealth() {
      try {
        const response = await fetch("/healthz");
        this.health = { status: response.status, payload: await response.json() };
      } catch {
        this.health = { status: 0, payload: null };
      }
    },
    async loadPipeline() {
      try { this.pipeline = await api.get("/api/stats/pipeline"); }
      catch { this.pipeline = null; }
    },
    async loadUsage() {
      try { this.usage = await api.get("/api/usage/summary"); }
      catch { this.usage = null; }
    },
    async loadFilters() {
      try { this.filters = await api.get("/api/stats/filters"); }
      catch { this.filters = null; }
    },
    async loadNotify() {
      try { this.notifyState = await api.get("/api/settings/notify"); }
      catch { this.notifyState = null; }
    },
    async loadHot() {
      this.error = "";
      const id = Number(this.hotDirectionId);
      if (!id) {
        this.error = this.$t("common.requiredMissing");
        return;
      }
      try {
        this.hot = await api.get(`/api/hot/board?direction_id=${id}`);
      } catch (err) {
        this.error = err.message || this.$t("common.errorGeneric");
        this.hot = null;
      }
    },
    healthTone() {
      if (!this.health) return "neutral";
      if (this.health.status === 503) return "danger";
      const degraded = this.health.payload && this.health.payload.degraded;
      return degraded && degraded.length ? "warn" : "ok";
    },
    healthLabel() {
      if (!this.health) return this.$t("common.loadFailed");
      if (this.health.status === 503) return this.$t("adminSystem.healthDown");
      const degraded = this.health.payload && this.health.payload.degraded;
      return degraded && degraded.length ? this.$t("adminSystem.healthDegraded") : this.$t("adminSystem.healthOk");
    },
    async saveNotify() {
      this.error = "";
      this.notice = "";
      try {
        const payload = {
          smtp_host: this.notifyForm.smtp_host,
          smtp_port: Number(this.notifyForm.smtp_port),
          smtp_user: this.notifyForm.smtp_user || undefined,
          smtp_pass: this.notifyForm.smtp_pass || undefined,
          from_addr: this.notifyForm.from_addr,
          to_addrs: this.notifyForm.to_addrs.split(/[,，]/).map((s) => s.trim()).filter(Boolean),
        };
        await api.put("/api/settings/notify", payload);
        this.notice = this.$t("common.saved");
        await this.loadNotify();
      } catch (err) {
        this.error = err.message || this.$t("common.errorGeneric");
      }
    },
    async testNotify() {
      this.notifyTest = "";
      try {
        await api.post("/api/settings/notify/test");
        this.notifyTest = "ok";
      } catch {
        this.notifyTest = "failed";
      }
    },
    async submitReconcile() {
      this.error = "";
      this.notice = "";
      this.reconcileResult = null;
      try {
        this.reconcileResult = await api.post("/api/settings/usage/reconcile", {
          month: this.reconcile.month,
          platform_billed_units: Number(this.reconcile.platform_billed_units),
        });
      } catch (err) {
        this.error = err.message || this.$t("common.errorGeneric");
      }
    },
    async toDirection(keyword) {
      // AC-17.2 人在环路：确认弹窗语义在此呈现（创建即确认，无自动触发路径）
      if (!window.confirm(this.$t("adminSystem.hotToDirectionConfirm"))) return;
      try {
        const result = await api.post("/api/hot/to-direction", { keyword });
        this.notice = this.$t("adminSystem.hotToDirectionDone", { id: result.direction_id });
      } catch (err) {
        this.error = err.message || this.$t("common.errorGeneric");
      }
    },
    fmt(value) {
      return value === null || value === undefined || value === "" ? "—" : value;
    },
  },
  template: `
    <section>
      <div class="view-heading">
        <p class="eyebrow">ADMIN / {{ $t("nav.adminSystem") }}</p>
        <h1 class="page-serif-headline" style="font-size:44px;">{{ $t("adminSystem.heading") }}</h1>
      </div>

      <nw-alert-bar v-if="error" tone="danger">{{ error }}</nw-alert-bar>
      <nw-alert-bar v-if="notice" tone="ok">{{ notice }}</nw-alert-bar>

      <div class="admin-section">
        <p class="admin-section-title">{{ $t("adminSystem.healthTitle") }}</p>
        <div class="card-base">
          <p>
            <nw-badge :tone="healthTone()">{{ healthLabel() }}</nw-badge>
            <span v-if="health && health.payload && health.payload.degraded && health.payload.degraded.length"
                  class="muted-note" style="margin-left:12px;">
              {{ $t("adminSystem.degradedList") }}：{{ (health.payload.degraded || []).join(", ") }}</span>
          </p>
        </div>
      </div>

      <div class="admin-section" v-if="pipeline">
        <p class="admin-section-title">{{ $t("adminSystem.pipelineTitle") }}</p>
        <div class="card-base">
          <div class="stat-grid">
            <div class="stat-cell"><div class="stat-value">{{ fmt(pipeline.oldest_running_task_min) }}</div><div class="stat-label">{{ $t("adminSystem.pipelineOldestRunning") }}</div></div>
            <div class="stat-cell"><div class="stat-value">{{ fmt(pipeline.stale_count_24h) }}</div><div class="stat-label">{{ $t("adminSystem.pipelineStale") }}</div></div>
            <div class="stat-cell"><div class="stat-value">{{ fmt(pipeline.pending_count) }}</div><div class="stat-label">{{ $t("adminSystem.pipelinePending") }}</div></div>
            <div class="stat-cell"><div class="stat-value">{{ fmt(pipeline.llm_error_rate_24h) }}</div><div class="stat-label">{{ $t("adminSystem.pipelineLlmError") }}</div></div>
            <div class="stat-cell"><div class="stat-value">{{ fmt(pipeline.items_24h) }}</div><div class="stat-label">{{ $t("adminSystem.pipelineItems") }}</div></div>
            <div class="stat-cell"><div class="stat-value">{{ fmt(pipeline.scored_24h) }}</div><div class="stat-label">{{ $t("adminSystem.pipelineScored") }}</div></div>
            <div class="stat-cell"><div class="stat-value">{{ fmt(pipeline.passed_24h) }}</div><div class="stat-label">{{ $t("adminSystem.pipelinePassed") }}</div></div>
            <div class="stat-cell"><div class="stat-value">{{ fmt(pipeline.db_size_mb) }}</div><div class="stat-label">{{ $t("adminSystem.pipelineDbSize") }}</div></div>
            <div class="stat-cell"><div class="stat-value">{{ fmt(pipeline.disk_free_mb) }}</div><div class="stat-label">{{ $t("adminSystem.pipelineDiskFree") }}</div></div>
          </div>
          <div style="display:flex;gap:16px;flex-wrap:wrap;">
            <nw-badge tone="warn">{{ $t("adminSystem.rateLimitedSources") }} {{ fmt(pipeline.rate_limited_sources) }}</nw-badge>
            <nw-badge tone="danger">{{ $t("adminSystem.hardFailedSources") }} {{ fmt(pipeline.hard_failed_sources) }}</nw-badge>
            <nw-badge tone="warn">{{ $t("adminSystem.suspectSources") }} {{ fmt(pipeline.suspect_sources) }}</nw-badge>
          </div>
        </div>
      </div>

      <div class="admin-section" v-if="filters">
        <p class="admin-section-title">{{ $t("adminSystem.filtersTitle") }}</p>
        <div class="card-base">
          <pre class="mono-text" style="white-space:pre-wrap;margin:0;">{{ JSON.stringify(filters, null, 2) }}</pre>
        </div>
      </div>

      <div class="admin-section">
        <p class="admin-section-title">{{ $t("adminSystem.hotTitle") }}</p>
        <div class="card-base">
          <div class="inline-form">
            <nw-form-field :label="$t('adminWrite.authorIdLabel')">
              <input class="form-input" type="number" v-model="hotDirectionId" style="min-width:120px;">
            </nw-form-field>
            <nw-button size="sm" @click="loadHot">{{ $t("common.search") }}</nw-button>
          </div>
          <nw-empty-state v-if="hot && !(hot.keywords && hot.keywords.length)"
                          :title="$t('adminSystem.hotEmpty')"></nw-empty-state>
          <div v-for="group in (hot && hot.keywords) || []" :key="group.keyword" style="margin-bottom:16px;">
            <p style="margin:0 0 6px;">
              <strong>{{ group.keyword }}</strong>
              <button type="button" class="btn-pill btn-ghost btn-sm" style="margin-left:8px;"
                      @click="toDirection(group.keyword)">{{ $t("adminSystem.hotToDirection") }}</button>
            </p>
            <ul class="muted-note" style="margin:0;padding-left:20px;">
              <li v-for="item in (group.top_items || [])" :key="item.url">
                <a :href="item.url" target="_blank" rel="noopener noreferrer nofollow">{{ item.title }}</a>
                <span class="score-badge" style="margin-left:6px;">{{ item.relevance }}</span>
              </li>
            </ul>
          </div>
        </div>
      </div>

      <div class="admin-section" v-if="usage">
        <p class="admin-section-title">{{ $t("adminSystem.usageTitle") }}</p>
        <div class="card-base">
          <nw-table :columns="[
            { key: 'label', label: 'call_point / model' },
            { key: 'calls', label: $t('adminSystem.usageCalls'), width: '100px' },
            { key: 'tokens', label: $t('adminSystem.usageTokens'), width: '140px' }]"
            :rows="Object.values(usage || {}).map((row) => ({
              label: (row.call_point || row.model || '—'),
              calls: fmt(row.calls !== undefined ? row.calls : row.call_count),
              tokens: fmt(row.prompt_tokens !== undefined ? (row.prompt_tokens + '/' + row.completion_tokens) : row.tokens) }))">
          </nw-table>
        </div>
      </div>

      <div class="admin-section">
        <p class="admin-section-title">{{ $t("adminSystem.notifyTitle") }}</p>
        <div class="card-base">
          <p>
            <nw-badge :tone="notifyState && notifyState.smtp_configured ? 'ok' : 'neutral'">
              {{ notifyState && notifyState.smtp_configured ? $t("adminSystem.smtpConfigured") : $t("adminSystem.smtpNotConfigured") }}</nw-badge>
            <button type="button" class="btn-pill btn-ghost btn-sm" style="margin-left:8px;"
                    @click="testNotify">{{ $t("adminSystem.smtpTest") }}</button>
          </p>
          <nw-alert-bar v-if="notifyTest === 'ok'" tone="ok">{{ $t("adminSystem.smtpTestOk") }}</nw-alert-bar>
          <nw-alert-bar v-if="notifyTest === 'failed'" tone="danger">{{ $t("adminSystem.smtpTestFailed") }}</nw-alert-bar>
          <div class="inline-form">
            <nw-form-field :label="$t('adminSystem.smtpHost')"><input class="form-input" v-model="notifyForm.smtp_host"></nw-form-field>
            <nw-form-field :label="$t('adminSystem.smtpPort')"><input class="form-input" type="number" v-model="notifyForm.smtp_port" style="width:90px;"></nw-form-field>
            <nw-form-field :label="$t('adminSystem.smtpUser')"><input class="form-input" v-model="notifyForm.smtp_user"></nw-form-field>
            <nw-form-field :label="$t('adminSystem.smtpPass')"><input class="form-input" type="password" v-model="notifyForm.smtp_pass"></nw-form-field>
            <nw-form-field :label="$t('adminSystem.smtpFrom')"><input class="form-input" v-model="notifyForm.from_addr"></nw-form-field>
            <nw-form-field :label="$t('adminSystem.smtpTo')"><input class="form-input" v-model="notifyForm.to_addrs" style="min-width:240px;"></nw-form-field>
            <nw-button size="sm" @click="saveNotify">{{ $t("common.save") }}</nw-button>
          </div>
          <p class="muted-note" v-if="notifyState">
            <label style="margin-right:12px;"><input type="checkbox" :checked="notifyState.notify_on_source_failure" disabled> {{ $t("adminSystem.notifyOnSourceFailure") }}</label>
            <label style="margin-right:12px;"><input type="checkbox" :checked="notifyState.notify_on_token_budget" disabled> {{ $t("adminSystem.notifyOnTokenBudget") }}</label>
            <label style="margin-right:12px;"><input type="checkbox" :checked="notifyState.notify_on_collective" disabled> {{ $t("adminSystem.notifyOnCollective") }}</label>
            <label><input type="checkbox" :checked="notifyState.notify_on_disk" disabled> {{ $t("adminSystem.notifyOnDisk") }}</label>
          </p>
        </div>
      </div>

      <div class="admin-section">
        <p class="admin-section-title">{{ $t("adminSystem.reconcileTitle") }}</p>
        <div class="card-base">
          <div class="inline-form">
            <nw-form-field :label="$t('adminSystem.reconcileMonth')">
              <input class="form-input" v-model="reconcile.month" placeholder="2026-10" style="width:140px;">
            </nw-form-field>
            <nw-form-field :label="$t('adminSystem.reconcileUnits')">
              <input class="form-input" type="number" v-model="reconcile.platform_billed_units" style="width:160px;">
            </nw-form-field>
            <nw-button size="sm" @click="submitReconcile">{{ $t("adminSystem.reconcileSubmit") }}</nw-button>
          </div>
          <template v-if="reconcileResult">
            <p class="mono-text">
              {{ $t("adminSystem.reconcileResult", {
                ledger: reconcileResult.ledger_units,
                platform: reconcileResult.platform_units,
                deviation: reconcileResult.deviation_pct }) }}
            </p>
            <nw-alert-bar v-if="reconcileResult.alerted" tone="warn">{{ $t("adminSystem.reconcileAlerted") }}</nw-alert-bar>
          </template>
        </div>
      </div>
    </section>
  `,
};
