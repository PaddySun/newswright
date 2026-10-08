/*
 * admin-write-view.js — 写作面板（US-11 / AC-11.7 前端退避轮询）
 *
 * 消费既有契约：POST /api/pipeline/write/{author_id}（202+task_id）→
 * GET /api/tasks 轮询任务态（2s/4s/8s 退避序列，至终态停止）；终态后经
 * GET /api/write-runs/{id} 拉 run 详情（decision/skip_reason/prompt_snapshot/
 * article_id）；FAILED 显示失败原因+手动重试入口（禁止静默无反馈）。
 */
import { api } from "../api.js";

const BACKOFF_SEQUENCE_MS = [2000, 4000, 8000]; // AC-11.7 前端句：2s/4s/8s 退避

export default {
  name: "AdminWriteView",
  data() {
    return {
      error: "",
      notice: "",
      authorId: "",
      polling: false,
      pollStep: 0,
      pollTimer: null,
      task: null,       // 终态任务行
      writeRun: null,   // run 详情
      recentTasks: [],
    };
  },
  mounted() { this.loadRecent(); },
  beforeUnmount() { this.stopPolling(); },
  methods: {
    async loadRecent() {
      try {
        this.recentTasks = (await api.get("/api/tasks?kind=write&limit=10")) || [];
      } catch { this.recentTasks = []; }
    },
    async triggerWrite() {
      this.error = "";
      this.notice = "";
      const id = Number(this.authorId);
      if (!id) {
        this.error = this.$t("common.requiredMissing");
        return;
      }
      try {
        const result = await api.post(`/api/pipeline/write/${id}`);
        this.notice = `${this.$t("adminWrite.writeQueued")} — ${this.$t("adminWrite.taskId")} ${result.task_id}`;
        this.startPolling(result.task_id);
      } catch (err) {
        this.error = err.message || this.$t("common.errorGeneric");
      }
    },
    startPolling(taskId) {
      this.stopPolling();
      this.polling = true;
      this.pollStep = 0;
      this.pollOnce(taskId);
    },
    scheduleNext(taskId) {
      // 退避序列 2s/4s/8s，8s 后维持 8s 至终态（AC-11.7 轮询间隔序列）
      const delay = BACKOFF_SEQUENCE_MS[Math.min(this.pollStep, BACKOFF_SEQUENCE_MS.length - 1)];
      this.pollStep += 1;
      this.pollTimer = setTimeout(() => this.pollOnce(taskId), delay);
    },
    stopPolling() {
      if (this.pollTimer) clearTimeout(this.pollTimer);
      this.pollTimer = null;
      this.polling = false;
    },
    async pollOnce(taskId) {
      try {
        const tasks = await api.get("/api/tasks?kind=write&limit=50");
        const row = (tasks || []).find((task) => task.id === taskId);
        if (!row) {
          this.scheduleNext(taskId);
          return;
        }
        this.task = row;
        if (row.status === "RUNNING" || row.status === "PENDING") {
          this.scheduleNext(taskId);
          return;
        }
        // 终态：停止轮询并拉 run 详情（终态反馈明确，AC-11.7）
        this.stopPolling();
        await this.loadWriteRun(row);
        await this.loadRecent();
      } catch (err) {
        this.stopPolling();
        this.error = err.message || this.$t("common.errorGeneric");
      }
    },
    async loadWriteRun(task) {
      const runId = task && task.payload && task.payload.write_run_id;
      if (!runId) return;
      try {
        this.writeRun = await api.get(`/api/write-runs/${runId}`);
      } catch { this.writeRun = null; }
    },
    runStatusTone(status) {
      return { DONE: "ok", FAILED: "danger", RUNNING: "info", PENDING: "neutral" }[status] || "neutral";
    },
  },
  template: `
    <section>
      <div class="view-heading">
        <p class="eyebrow">ADMIN / {{ $t("nav.adminWrite") }}</p>
        <h1 class="page-serif-headline" style="font-size:44px;">{{ $t("adminWrite.heading") }}</h1>
      </div>

      <nw-alert-bar v-if="error" tone="danger">{{ error }}</nw-alert-bar>
      <nw-alert-bar v-if="notice" tone="ok">{{ notice }}</nw-alert-bar>
      <nw-alert-bar v-if="polling" tone="info">{{ $t("adminWrite.pollRunning") }}（{{ $t("adminWrite.taskId") }} {{ task ? task.id : "…" }}）</nw-alert-bar>

      <div class="admin-section">
        <div class="card-base" style="max-width:560px;">
          <div class="inline-form">
            <nw-form-field :label="$t('adminWrite.authorIdLabel')">
              <input class="form-input" type="number" v-model="authorId" style="min-width:140px;">
            </nw-form-field>
            <nw-button :disabled="polling" @click="triggerWrite">{{ $t("adminWrite.triggerWrite") }}</nw-button>
          </div>
        </div>
      </div>

      <div class="admin-section" v-if="task">
        <p class="admin-section-title">{{ $t("adminWrite.runDetail") }}</p>
        <div class="card-base">
          <p>
            <nw-badge :tone="runStatusTone(task.status)">{{ task.status }}</nw-badge>
            <span class="mono-text" style="margin-left:12px;">{{ $t("adminWrite.taskId") }} {{ task.id }}</span>
          </p>
          <template v-if="task.status === 'FAILED'">
            <nw-alert-bar tone="danger">
              {{ $t("adminWrite.pollFailed") }} — {{ $t("adminWrite.failedReason") }}：{{ task.last_error || "—" }}
            </nw-alert-bar>
            <nw-button size="sm" @click="triggerWrite">{{ $t("adminWrite.manualRetry") }}</nw-button>
          </template>
          <template v-if="task.status === 'DONE' && writeRun">
            <p v-if="writeRun.decision === 'WRITE' && writeRun.article_id">
              <a class="btn-pill btn-ghost btn-sm" :href="'#/articles/' + writeRun.article_id">{{ $t("adminWrite.openArticle") }}</a>
            </p>
            <p v-if="writeRun.decision === 'SKIP'">
              <nw-badge tone="warn">{{ $t("adminWrite.decisionSkip") }}</nw-badge>
              <span class="muted-note" style="margin-left:8px;">{{ writeRun.skip_reason || "—" }}</span>
            </p>
            <details style="margin-top:12px;">
              <summary class="reason-toggle" style="display:inline-block;">{{ $t("adminWrite.promptSnapshot") }}</summary>
              <pre class="reason-block" style="white-space:pre-wrap;">{{ writeRun.prompt_snapshot }}</pre>
            </details>
          </template>
        </div>
      </div>

      <div class="admin-section">
        <p class="admin-section-title">{{ $t("adminWrite.recentTasks") }}</p>
        <nw-table :columns="[
          { key: 'id', label: 'ID', width: '70px' },
          { key: 'kind', label: $t('adminWrite.taskKind'), width: '110px' },
          { key: 'status', label: $t('adminWrite.taskStatus'), width: '110px' },
          { key: 'created_at', label: 'created_at' }]" :rows="recentTasks">
          <template v-slot:cell-status="{ row }">
            <nw-badge :tone="runStatusTone(row.status)">{{ row.status }}</nw-badge>
          </template>
        </nw-table>
      </div>
    </section>
  `,
};
