/*
 * article-detail-view.js — C 流文章详情视图（AC-12.x 呈现面 / C1 拍板违规提示 /
 * AC-13.x 反馈前端 / ADR-7②）
 *
 * 消费既有契约 GET /api/articles/{id}（body markdown + citations）与
 * POST /feedback（like/dislike 匿名可、comment 登录态）。
 * - Markdown 客户端白名单渲染（与服务端同规则，脚注转链接）；
 * - citation_violated 违规标记 → 显著警示条且不藏匿文章（标记不删除语义；
 *   数据面依赖 API 响应携带该字段——缺口呈报统筹，字段到位即呈现）；
 * - already_counted 提示（AC-13.1 幂等呈现）。
 */
import { api } from "../api.js";
import { renderMarkdownClient } from "../lib/markdown-client.js";

export default {
  name: "ArticleDetailView",
  inject: { route: { from: "route" } },
  data() {
    return {
      loading: false,
      error: "",
      article: null,
      bodyHtml: "",
      feedbackState: "", // counted | already | failed | ""
      commentOpen: false,
      commentText: "",
      commentState: "", // done | failed | ""
    };
  },
  computed: {
    articleId() { return Number(this.route.params.id); },
    citations() {
      return (this.article && this.article.citations) || [];
    },
  },
  async mounted() { await this.load(); },
  methods: {
    async load() {      this.loading = true;
      this.error = "";
      try {
        this.article = await api.get(`/api/articles/${this.articleId}`);
        this.bodyHtml = renderMarkdownClient(this.article.body || "");
      } catch (err) {
        this.error = err.message || this.$t("common.errorGeneric");
      } finally {
        this.loading = false;
      }
    },
    async react(verdict) {
      try {
        const result = await api.post("/feedback", {
          article_id: this.articleId, verdict,
        });
        this.feedbackState = result && result.counted === false ? "already" : "counted";
      } catch {
        this.feedbackState = "failed";
      }
    },
    async submitComment() {
      if (!this.commentText.trim()) return;
      try {
        await api.post("/feedback", {
          article_id: this.articleId, verdict: "comment", text: this.commentText.trim(),
        });
        this.commentState = "done";
        this.commentText = "";
        this.commentOpen = false;
      } catch (err) {
        // 403 AUTH_REQUIRED_COMMENT（匿名）与其他错误同面呈现（登录态页面内理论不达）
        this.commentState = "failed";
        this.commentOpen = true;
      }
    },
  },
  template: `
    <section class="article-view">
      <nw-alert-bar v-if="error" tone="danger">{{ error }} —
        <a href="#/articles" style="text-decoration:underline;">{{ $t("articles.backToList") }}</a></nw-alert-bar>

      <template v-if="article">
        <p class="eyebrow">
          <span>{{ $t("articles.authorColumn") }} #{{ article.author_id }}</span>
        </p>

        <nw-alert-bar v-if="article.citation_violated" tone="danger">
          {{ $t("articles.violationBanner") }}
        </nw-alert-bar>

        <h1 class="article-headline">{{ article.title }}</h1>

        <div class="article-body rich-text" v-html="bodyHtml"></div>

        <div class="article-actions-row">
          <nw-button variant="ghost" size="sm" @click="react('like')">{{ $t("articles.feedbackLike") }} ▲</nw-button>
          <nw-button variant="ghost" size="sm" @click="react('dislike')">{{ $t("articles.feedbackDislike") }} ▽</nw-button>
          <nw-button variant="ghost" size="sm" @click="commentOpen = !commentOpen">{{ $t("articles.feedbackComment") }}</nw-button>
        </div>
        <nw-alert-bar v-if="feedbackState === 'counted'" tone="ok">{{ $t("articles.feedbackCounted") }}</nw-alert-bar>
        <nw-alert-bar v-if="feedbackState === 'already'" tone="info">{{ $t("articles.feedbackAlready") }}</nw-alert-bar>
        <nw-alert-bar v-if="feedbackState === 'failed'" tone="warn">{{ $t("common.errorGeneric") }}</nw-alert-bar>

        <div v-if="commentOpen" class="feedback-panel">
          <textarea class="comment-textarea" v-model="commentText"
                    :placeholder="$t('articles.feedbackCommentPlaceholder')"></textarea>
          <div class="article-actions-row">
            <nw-button size="sm" @click="submitComment">{{ $t("articles.feedbackSubmit") }}</nw-button>
            <nw-alert-bar v-if="commentState === 'failed'" tone="warn" style="margin:0;">{{ $t("common.errorGeneric") }}</nw-alert-bar>
          </div>
        </div>

        <div v-if="citations.length" class="admin-section" style="margin-top:48px;">
          <p class="admin-section-title">{{ $t("articles.citationsColumn") }}（{{ citations.length }}）</p>
          <ul class="rich-text" style="font-size:14px;">
            <li v-for="(citation, index) in citations" :key="index">
              <span class="mono-text">#{{ citation.item_id }}</span> — {{ citation.quote }}
            </li>
          </ul>
        </div>
      </template>
    </section>
  `,
};
