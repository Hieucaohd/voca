// Voca API client for pages: cookie auth + CSRF header + transparent token refresh.
window.voca = (() => {
  const cookie = (name) => {
    const hit = document.cookie.split("; ").find((c) => c.startsWith(name + "="));
    return hit ? decodeURIComponent(hit.slice(name.length + 1)) : "";
  };

  let refreshing = null;
  function refresh() {
    if (!refreshing) {
      refreshing = fetch("/api/v1/auth/refresh", {
        method: "POST",
        credentials: "same-origin",
        headers: { "X-CSRF-TOKEN": cookie("csrf_refresh_token") },
      })
        .then((r) => r.ok)
        .catch(() => false)
        .finally(() => setTimeout(() => (refreshing = null), 0));
    }
    return refreshing;
  }

  function errorMessage(data, status) {
    const err = data && data.error;
    if (err && Array.isArray(err.details) && err.details.length) {
      return err.details.map((d) => String(d.message).replace(/^Value error, /, "")).join(" · ");
    }
    if (err && err.message) return err.message;
    return status >= 500 ? "Máy chủ gặp lỗi, vui lòng thử lại" : "Không thể kết nối máy chủ";
  }

  async function request(method, url, body, retry = true) {
    const headers = { Accept: "application/json" };
    if (body !== undefined) headers["Content-Type"] = "application/json";
    const csrf = cookie("csrf_access_token");
    if (csrf) headers["X-CSRF-TOKEN"] = csrf;

    let res;
    try {
      res = await fetch(url, {
        method,
        headers,
        credentials: "same-origin",
        body: body === undefined ? undefined : JSON.stringify(body),
      });
    } catch (e) {
      throw Object.assign(new Error("Mất kết nối mạng"), { status: 0 });
    }

    if (res.status === 401 && retry) {
      const data = await res.clone().json().catch(() => ({}));
      const code = data && data.error && data.error.code;
      if (["TOKEN_EXPIRED", "UNAUTHORIZED", "CSRF_ERROR", "INVALID_TOKEN"].includes(code) && (await refresh())) {
        return request(method, url, body, false);
      }
      location.href = "/login?next=" + encodeURIComponent(location.pathname + location.search);
      throw Object.assign(new Error("Phiên đăng nhập đã hết hạn"), { status: 401 });
    }
    if (res.status === 204) return null;
    const data = await res.json().catch(() => null);
    if (!res.ok) throw Object.assign(new Error(errorMessage(data, res.status)), { status: res.status, data });
    return data;
  }

  function toast(message, kind = "info", ms = 3200) {
    let box = document.querySelector(".toasts");
    if (!box) {
      box = document.createElement("div");
      box.className = "toasts";
      box.setAttribute("role", "status");
      document.body.appendChild(box);
    }
    const el = document.createElement("div");
    el.className = "toast " + kind;
    el.textContent = message;
    box.appendChild(el);
    setTimeout(() => el.remove(), ms);
  }

  return {
    get: (url) => request("GET", url),
    post: (url, body = {}) => request("POST", url, body),
    put: (url, body) => request("PUT", url, body),
    patch: (url, body) => request("PATCH", url, body),
    del: (url) => request("DELETE", url),
    toast,
    uuid: () => (crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) + Math.random().toString(16).slice(2)),
  };
})();
