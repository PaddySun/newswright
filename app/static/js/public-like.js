/*
 * public-like.js — 公开文章页访客点赞（AC-16.5）
 *
 * 消费既有匿名反馈端点 POST /feedback（同 AC-13.1 去重链：服务端 cookie
 * 身份去重，重复点赞返回 already_counted）。界面文案从模板注入的 data-*
 * 属性取（SSR 文案块承载，裁定⑦）——本脚本零硬编码界面字符串。
 */
(function () {
  "use strict";

  var button = document.getElementById("public-like");
  if (!button) return;

  function setLabel(text) {
    button.textContent = text;
  }

  button.addEventListener("click", function () {
    button.disabled = true;
    fetch("/feedback", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      // 请求体刻意不含任何身份字段（访客身份由服务端 cookie 提取，P1-6）
      body: JSON.stringify({
        article_id: Number(button.dataset.articleId),
        verdict: "like"
      })
    })
      .then(function (response) {
        if (!response.ok) throw new Error("feedback failed");
        return response.json();
      })
      .then(function (data) {
        // counted=false 且 reason=already_counted 同样视为已支持（幂等呈现）
        setLabel(button.dataset.labelLiked);
        button.setAttribute("aria-pressed", "true");
        if (data && data.counted === false && data.reason !== "already_counted") {
          setLabel(button.dataset.labelFailed);
          button.disabled = false;
        }
      })
      .catch(function () {
        setLabel(button.dataset.labelFailed);
        button.disabled = false;
      });
  });
})();
