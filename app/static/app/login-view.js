/*
 * login-view.js — 登录页交互模块（SSR 页挂载，裁定③登录页=SSR）
 *
 * 消费既有契约：POST /api/auth/login（AC-01.1b/01.2）与
 * POST /api/auth/password（AC-01.5）。错误呈现吃透 AC-01 呈现面：
 * - 401 AUTH_INVALID → 表单警告（文案来自模板 data-* 注入）
 * - 429 AUTH_RATE_LIMITED → 锁定提示
 * - 403 PASSWORD_CHANGE_REQUIRED → 切换首登改密表单
 * 界面文案全部来自 SSR 文案块经 data-i18n-* 属性注入——本模块零硬编码
 * 界面字符串（裁定⑦）。
 */
(function () {
  "use strict";

  var view = document.getElementById("login-view");
  var loginForm = document.getElementById("login-form");
  var changeForm = document.getElementById("password-change-form");
  if (!view || !loginForm || !changeForm) return;

  var loginAlert = document.getElementById("login-alert");
  var changeAlert = document.getElementById("change-alert");
  var copy = view.dataset;

  function showAlert(element, message) {
    element.textContent = message;
    element.hidden = false;
  }

  function hideAlert(element) {
    element.hidden = true;
  }

  loginForm.addEventListener("submit", function (event) {
    event.preventDefault();
    hideAlert(loginAlert);
    var username = document.getElementById("login-username").value.trim();
    var password = document.getElementById("login-password").value;
    if (!username || !password) {
      showAlert(loginAlert, copy.i18nErrorGeneric);
      return;
    }
    fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: username, password: password })
    })
      .then(function (response) {
        if (response.ok) {
          window.location.href = "/app/";
          return null;
        }
        return response.json().then(function (body) {
          return { status: response.status, code: body && body.code };
        }, function () {
          return { status: response.status, code: "" };
        });
      })
      .then(function (failure) {
        if (!failure) return;
        if (failure.status === 403) {
          // 首登强制改密：切换改密表单（会话已建立，改密端点豁免门禁）
          loginForm.hidden = true;
          changeForm.hidden = false;
          return;
        }
        if (failure.status === 429) {
          showAlert(loginAlert, copy.i18nLockedHint);
          return;
        }
        showAlert(loginAlert, copy.i18nErrorGeneric);
      })
      .catch(function () {
        showAlert(loginAlert, copy.i18nErrorGeneric);
      });
  });

  changeForm.addEventListener("submit", function (event) {
    event.preventDefault();
    hideAlert(changeAlert);
    var oldPassword = document.getElementById("change-old").value;
    var newPassword = document.getElementById("change-new").value;
    var confirmPassword = document.getElementById("change-confirm").value;
    if (newPassword !== confirmPassword) {
      showAlert(changeAlert, copy.i18nMismatch);
      return;
    }
    fetch("/api/auth/password", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ old_password: oldPassword, new_password: newPassword })
    })
      .then(function (response) {
        if (!response.ok) throw new Error("password change failed");
        window.location.href = "/app/";
      })
      .catch(function () {
        showAlert(changeAlert, copy.i18nErrorGeneric);
      });
  });
})();
