"use strict";
const $ = (s) => document.querySelector(s);
const $$ = (s) => Array.from(document.querySelectorAll(s));
const api = async (path, body, method) => {
  const opt = { method: method || (body ? "POST" : "GET") };
  if (body) { opt.headers = { "Content-Type": "application/json" }; opt.body = JSON.stringify(body); }
  const r = await fetch(path, opt);
  return r.json();
};

/* 设备列表、后台任务状态全部来自后端的统一管理器（经 SSE 推送）。
   前端不再自己定时轮询 adb —— 开几个窗口、刷新几次页面，后台都只有一份任务。 */
const S = {
  items: [], devices: [], settings: {}, apps: [], selected: new Set(), scanning: false,
  sup: null, job: null, tab: "queue",
};

function escapeHtml(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, c =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function fmtSize(n) {
  if (!n) return "";
  const u = ["B", "KB", "MB", "GB"]; let i = 0, f = n;
  while (f >= 1024 && i < 3) { f /= 1024; i++; }
  return (i === 0 ? f.toFixed(0) : f.toFixed(1)) + " " + u[i];
}
function fmtTime(ts) {
  if (!ts) return "—";
  const d = new Date(ts * 1000);
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
}
function fmtAgo(ts) {
  if (!ts) return "—";
  const s = Math.max(0, Math.round(Date.now() / 1000 - ts));
  if (s < 60) return t("agoSec", { n: s });
  if (s < 3600) return t("agoMin", { n: Math.round(s / 60) });
  return fmtTime(ts);
}
/* 后端返回的错误代码 → 当前语言的说明 */
function errText(r) {
  if (!r) return "";
  if (r.code && I18N.zh["e_" + r.code] !== undefined) return t("e_" + r.code, { v: r.arg || "" });
  return r.error || r.message || r.code || "";
}

/* ---------------- 提示 ---------------- */
function toast(title, body, kind) {
  const el = document.createElement("div");
  el.className = "toast " + (kind || "");
  el.innerHTML = `<div class="tt"></div><div class="tb"></div>`;
  el.querySelector(".tt").textContent = title;
  el.querySelector(".tb").textContent = body || "";
  $("#toasts").appendChild(el);
  setTimeout(() => { el.style.opacity = "0"; el.style.transition = ".4s"; }, 5200);
  setTimeout(() => el.remove(), 5700);
}
function closeModal() { $("#modal").classList.add("hidden"); }
function modal(title, html) {
  $("#modalTitle").textContent = title;
  $("#modalBody").innerHTML = html;
  $("#modalFoot").innerHTML = `<button class="primary small" id="modalOk">OK</button>`;
  $("#modalOk").onclick = closeModal;
  $("#modal").classList.remove("hidden");
}
/* 多按钮弹窗，返回所点按钮的 key（取消为 null） */
function modalChoice(title, html, buttons) {
  return new Promise(resolve => {
    $("#modalTitle").textContent = title;
    $("#modalBody").innerHTML = html;
    const foot = $("#modalFoot");
    foot.innerHTML = "";
    buttons.forEach(b => {
      const el = document.createElement("button");
      el.className = (b.primary ? "primary" : "ghost") + " small" + (b.danger ? " danger" : "");
      el.textContent = b.label;
      el.disabled = !!b.disabled;
      el.onclick = () => { closeModal(); resolve(b.key); };
      foot.appendChild(el);
    });
    $("#modal").classList.remove("hidden");
  });
}

/* ---------------- 语言 ---------------- */
function applyLang(code) {
  setLang(code);
  $("#langSel").value = LANG;
  applyStatic();
  $("#sortDir").textContent = t($("#sortDir").dataset.desc === "1" ? "desc" : "asc");
  const ph = $("#profileSel") && $("#profileSel").querySelector('option[value=""]');
  if (ph) ph.textContent = t("profilePlaceholder");
  $("#btnRefresh").textContent = t("cCheck");
  renderQueue();
  renderApps();
  renderSupAll();
  const ok = S.settings && S.settings.__adbOk;
  $("#adbState").textContent = ok === undefined ? "" : t(ok ? "adbReady" : "adbMissing");
}
$("#langSel").onchange = async () => {
  const code = $("#langSel").value;
  localStorage.setItem("lang", code);
  applyLang(code);
  await api("/api/settings", { lang: code });   // 通知中心文案也跟着换
};

/* ---------------- 标签页 ---------------- */
function showTab(name) {
  S.tab = name;
  $$(".tab").forEach(x => x.classList.toggle("active", x.dataset.tab === name));
  $$(".page").forEach(x => x.classList.toggle("active", x.id === "page-" + name));
  if (name === "console") { renderConsole(); loadCmdLog(); }
}
$$(".tab").forEach(tab => tab.onclick = () => showTab(tab.dataset.tab));
$("#bgChip").onclick = () => showTab("console");

/* ---------------- 队列 ---------------- */
function letterIcon(name) {
  const ch = (name || "?").trim()[0] || "?";
  return `<div class="icon">${escapeHtml(ch.toUpperCase())}</div>`;
}
function statusText(it) {
  if (it.status === "pending") return t("stPending");
  if (it.status === "waiting") return t("stWaiting");
  if (it.status === "installing") return t("stInstalling");
  const txt = codeText(it.code, it.arg);
  if (it.status === "success") return "✓ " + txt;
  if (it.status === "skipped") return "– " + txt;
  if (it.status === "failed") return "✕ " + txt;
  if (it.status === "unverified") return "⚠ " + txt;
  if (it.status === "cancelled" || it.status === "cancel_installed") return "■ " + txt;
  if (it.status === "pending_verify") return "⏳ " + txt;
  return it.status || "";
}
function installedTag(ins) {
  if (!ins || !ins.state) return "";
  const v = ins.versionName ? "v" + escapeHtml(ins.versionName) : "";
  const map = {
    same: ["insSame", "tag-ins-same"], update: ["insUpdate", "tag-ins-upd"],
    downgrade: ["insDown", "tag-ins-down"], unknown: ["insUnknown", "tag-ins-same"],
    none: ["insNone", "tag-ins-new"],
  };
  const [key, cls] = map[ins.state] || map.unknown;
  return `<span class="tag ${cls}">${escapeHtml(t(key, { v }))}</span>`;
}
function renderQueue() {
  const list = $("#list");
  if (!list) return;
  list.innerHTML = "";
  $("#queueCount").textContent = S.items.length;
  $("#emptyHint").classList.toggle("hidden", S.items.length > 0);
  S.items.forEach((it, i) => {
    const li = document.createElement("li");
    li.className = "row " + (it.status || "pending");
    li.draggable = true;
    li.dataset.id = it.id;
    const tags = [installedTag(it.installed)];
    if (it.splitCount) tags.push(`<span class="tag">${escapeHtml(t("tagSplit", { n: it.splitCount }))}</span>`);
    if (it.duplicate) tags.push(`<span class="tag warn">${escapeHtml(t("tagDup"))}</span>`);
    if (it.error) tags.push(`<span class="tag warn">${escapeHtml(it.error)}</span>`);
    if (it.minSdk) tags.push(`<span class="tag">${escapeHtml(t("tagMinSdk", { n: it.minSdk }))}</span>`);
    const hint = (it.status === "failed" || it.status === "unverified" || it.status === "cancelled"
      || it.status === "pending_verify") ? codeHint(it.code, it.arg) : "";
    // 「卸载」只在已安装检测确认这台（当前选中的）设备上装着时出现
    const curSerial = ($("#deviceSel") || {}).value || "";
    const installed = it.installed && it.installed.state && it.installed.state !== "none"
      && (!it.installed.serial || it.installed.serial === curSerial);
    const busyRow = !!(S.job && S.job.running) || it.status === "installing";
    li.innerHTML = `
      <span class="handle">⠿</span>
      <span class="idx">${i + 1}</span>
      ${it.icon ? `<img class="icon" src="${it.icon}" alt="">` : letterIcon(it.label)}
      <div class="meta">
        <div class="name">${escapeHtml(it.label || it.file)}</div>
        <div class="sub">${escapeHtml(it.package || it.file)} · ${it.versionName ? "v" + escapeHtml(it.versionName) + " · " : ""}${it.sizeText || ""}</div>
        <div class="tagline">${tags.join("")}</div>
      </div>
      <div class="row-actions">
        <button class="ghost small in1" ${busyRow ? "disabled" : ""} title="${escapeHtml(t("installOneTip"))}">${escapeHtml(t("installOne"))}</button>
        ${installed ? `<button class="ghost small un1" ${busyRow ? "disabled" : ""} title="${escapeHtml(t("uninstallOneTip"))}">${escapeHtml(t("uninstall"))}</button>` : ""}
      </div>
      <div class="status ${it.status || "pending"}">
        <div>${escapeHtml(statusText(it))}</div>
        ${hint ? `<div class="hintline">${escapeHtml(hint)}</div>` : ""}
      </div>
      <button class="rm" title="${escapeHtml(t("removeFromQueue"))}">✕</button>`;
    li.querySelector(".rm").onclick = async () => {
      await api("/api/queue/remove", { ids: [it.id] });
      refreshState();
    };
    li.querySelector(".in1").onclick = () => installOne(it);
    const ub = li.querySelector(".un1");
    if (ub) ub.onclick = () => uninstall([it.package], { [it.package]: it.label });
    list.appendChild(li);
  });
  wireDrag();
}

/* 版本 / 制作者 / GitHub 地址 */
function renderAbout() {
  const a = S.about || {};
  const v = a.version || S.version || "";
  const badge = $("#appVerBadge");
  if (badge) badge.textContent = v ? "v" + v : "";
  if (v) document.title = t("appName") + " v" + v;
  const link = a.homepage ? `<a href="${escapeHtml(a.homepage)}" target="_blank" rel="noopener">${escapeHtml(a.homepage.replace(/^https?:\/\//, ""))}</a>` : "";
  const line = $("#aboutLine");
  if (line) line.innerHTML = (a.author ? escapeHtml(t("madeBy", { a: a.author })) : "") + (link ? " · " + link : "");
  const box = $("#aboutBox");
  if (box) box.innerHTML =
    `<span class="k">${escapeHtml(t("aboutVersion"))}</span><span>${escapeHtml(v ? "v" + v : "—")}</span>` +
    `<span class="k">${escapeHtml(t("aboutAuthor"))}</span><span>${escapeHtml(a.author || "—")}</span>` +
    `<span class="k">GitHub</span><span>${link || "—"}</span>` +
    `<span class="k">${escapeHtml(t("aboutLicense"))}</span><span>MIT</span>`;
}

/* 拖拽排序 */
let dragId = null;
function wireDrag() {
  $$("#list .row").forEach(row => {
    row.addEventListener("dragstart", e => {
      dragId = row.dataset.id;
      row.classList.add("dragging");
      e.dataTransfer.effectAllowed = "move";
      e.dataTransfer.setData("text/plain", "row:" + dragId);
    });
    row.addEventListener("dragend", () => {
      row.classList.remove("dragging");
      $$("#list .row").forEach(r => r.classList.remove("over"));
      dragId = null;
    });
    row.addEventListener("dragover", e => {
      if (!dragId) return;
      e.preventDefault(); e.stopPropagation();
      row.classList.add("over");
    });
    row.addEventListener("dragleave", () => row.classList.remove("over"));
    row.addEventListener("drop", async e => {
      if (!dragId) return;
      e.preventDefault(); e.stopPropagation();
      row.classList.remove("over");
      const ids = S.items.map(x => x.id);
      const from = ids.indexOf(dragId);
      const to = ids.indexOf(row.dataset.id);
      if (from < 0 || to < 0 || from === to) return;
      ids.splice(to, 0, ids.splice(from, 1)[0]);
      S.items = ids.map(id => S.items.find(x => x.id === id));
      renderQueue();
      await api("/api/queue/reorder", { ids });
      $("#sortKey").value = "";
    });
  });
}

/* ---------------- 文件拖入 ---------------- */
let dragDepth = 0;
window.addEventListener("dragenter", e => {
  if (dragId) return;
  if (!e.dataTransfer || !Array.from(e.dataTransfer.types || []).includes("Files")) return;
  dragDepth++; $("#dropveil").classList.add("on");
});
window.addEventListener("dragover", e => {
  if (e.dataTransfer && Array.from(e.dataTransfer.types || []).includes("Files")) e.preventDefault();
});
window.addEventListener("dragleave", () => {
  dragDepth = Math.max(0, dragDepth - 1);
  if (!dragDepth) $("#dropveil").classList.remove("on");
});
window.addEventListener("drop", async e => {
  if (!e.dataTransfer) return;
  const hasFiles = (e.dataTransfer.files && e.dataTransfer.files.length) ||
    (e.dataTransfer.items && e.dataTransfer.items.length);
  if (!hasFiles) return;
  e.preventDefault();
  dragDepth = 0; $("#dropveil").classList.remove("on");
  let files = [];
  const entries = [];
  if (e.dataTransfer.items) {
    for (const it of Array.from(e.dataTransfer.items)) {
      const entry = it.webkitGetAsEntry && it.webkitGetAsEntry();
      if (entry) entries.push(entry);
    }
  }
  if (entries.length && entries.some(en => en.isDirectory)) {
    toast(t("tExpanding"), t("tExpandingSub"), "");
    for (const en of entries) files = files.concat(await walkEntry(en));
  } else {
    files = Array.from(e.dataTransfer.files);
  }
  await uploadFiles(files);
});

function walkEntry(entry, depth) {
  depth = depth || 0;
  return new Promise(resolve => {
    if (entry.isFile) {
      entry.file(f => resolve([f]), () => resolve([]));
    } else if (entry.isDirectory && depth < 6) {
      const reader = entry.createReader();
      const all = [];
      const readBatch = () => reader.readEntries(async ents => {
        if (!ents.length) {
          const nested = await Promise.all(all.map(en => walkEntry(en, depth + 1)));
          resolve([].concat.apply([], nested));
          return;
        }
        all.push(...ents);
        readBatch();
      }, () => resolve([]));
      readBatch();
    } else resolve([]);
  });
}

async function uploadFiles(files) {
  const apks = files.filter(f => /\.(apk|xapk|apks|apkm)$/i.test(f.name));
  const skipped = files.length - apks.length;
  if (!apks.length) { toast(t("tNoApk"), t("tNoApkSub"), "warn"); return; }
  let ok = 0, fail = 0;
  for (let i = 0; i < apks.length; i++) {
    const f = apks[i];
    $("#progressWrap").classList.remove("hidden");
    $("#progressText").textContent = t("tReading", { f: f.name, i: i + 1, n: apks.length });
    try {
      const res = await uploadOne(f, p => {
        $("#progressBar").style.width = ((i + p) / apks.length * 100).toFixed(1) + "%";
      });
      if (res && res.ok) ok++; else { fail++; toast(t("tAddFail"), (res && res.error) || f.name, "err"); }
    } catch (err) { fail++; toast(t("tAddFail"), f.name + " — " + err, "err"); }
  }
  $("#progressWrap").classList.add("hidden");
  $("#progressBar").style.width = "0";
  await refreshState();
  toast(t("tQueueAdded"),
    t("tAdded", { n: ok }) + (fail ? t("tAddedFail", { n: fail }) : "") +
    (skipped ? t("tAddedSkip", { n: skipped }) : ""), fail ? "warn" : "ok");
}
function uploadOne(file, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/upload");
    xhr.setRequestHeader("X-File-Name", encodeURIComponent(file.name));
    xhr.upload.onprogress = e => { if (e.lengthComputable && onProgress) onProgress(e.loaded / e.total); };
    xhr.onload = () => { try { resolve(JSON.parse(xhr.responseText)); } catch (e) { reject("bad response"); } };
    xhr.onerror = () => reject("network error");
    xhr.send(file);
  });
}

async function importPath() {
  const p = $("#pathInput").value.trim();
  if (!p) return;
  const r = await api("/api/import", { path: p });
  if (r.ok) {
    $("#pathInput").value = "";
    await refreshState();
    toast(t("tImported"), r.added !== undefined ? t("tAdded", { n: r.added })
      : (r.item ? r.item.label : ""), "ok");
  } else toast(t("tImportFail"), r.error || "", "err");
}
$("#btnImport").onclick = importPath;
$("#pathInput").addEventListener("keydown", e => { if (e.key === "Enter") importPath(); });

/* ---------------- 排序 / 方案 ---------------- */
$("#sortKey").onchange = async () => {
  const key = $("#sortKey").value;
  if (!key) return;
  await api("/api/queue/sort", { key, desc: $("#sortDir").dataset.desc === "1" });
  refreshState();
};
$("#sortDir").onclick = async () => {
  const b = $("#sortDir");
  const desc = b.dataset.desc === "1" ? "0" : "1";
  b.dataset.desc = desc;
  b.textContent = t(desc === "1" ? "desc" : "asc");
  if ($("#sortKey").value) {
    await api("/api/queue/sort", { key: $("#sortKey").value, desc: desc === "1" });
    refreshState();
  }
};
$("#btnProfSave").onclick = async () => {
  const name = prompt(t("tProfPrompt"), t("tProfDefault") + " " + new Date().toLocaleDateString());
  if (!name) return;
  const r = await api("/api/profile/save", { name });
  if (r.ok) { toast(t("tProfSaved"), `${r.name} · ${r.count}`, "ok"); refreshState(); }
  else toast(t("tSaveFail"), r.error || "", "err");
};
$("#btnProfLoad").onclick = async () => {
  const name = $("#profileSel").value;
  if (!name) { toast(t("tSelectProfile"), "", "warn"); return; }
  const r = await api("/api/profile/load", { name });
  await refreshState();
  if (r.ok) {
    const miss = (r.missing || []).length;
    toast(t("tProfLoaded"), t("tProfLoadedSub", { n: r.loaded }) +
      (miss ? t("tProfMissing", { n: miss }) : ""), miss ? "warn" : "ok");
    if (miss) modal(t("tProfMissTitle"), `<p class='muted'>${escapeHtml(t("tProfMissBody"))}</p>` +
      r.missing.map(m => `<div class="res"><span class="r-err">✕</span><span class="r-name">${escapeHtml(m)}</span></div>`).join(""));
  } else toast(t("tLoadFail"), r.error || "", "err");
};
$("#btnProfDel").onclick = async () => {
  const name = $("#profileSel").value;
  if (!name) return;
  if (!confirm(t("tConfirmDelProfile", { n: name }))) return;
  await api("/api/profile/delete", { name });
  refreshState();
};
$("#btnClear").onclick = async () => {
  if (!S.items.length) return;
  if ((S.job || {}).running) { toast(t("tCantStart"), t("e_busy_install"), "warn"); return; }
  if (!confirm(t("tConfirmClear"))) return;
  await api("/api/queue/clear", {});
  refreshState();
};

/* ---------------- 安装 ---------------- */
function currentDevice() {
  return S.devices.find(d => d.serial === $("#deviceSel").value);
}
async function startInstall(mode, ids) {
  const serial = $("#deviceSel").value;
  if (!serial) { toast(t("tNoDevice"), t("tNoDeviceSub"), "warn"); return; }
  if (!S.items.length) { toast(t("tQueueEmpty"), t("tQueueEmptySub"), "warn"); return; }
  const r = await api("/api/install", { serial, mode: mode || null, ids: ids || null });
  if (r.ok) {
    $("#log").textContent = "";
    $("#logBox").open = true;
    return;
  }
  if (r.code === "choose_mode") {
    // 这台设备上已经装成功过一部分：不盲目从头重装
    const c = await modalChoice(t("chooseTitle"),
      `<p>${escapeHtml(t("chooseBody", { d: r.done, n: r.remaining }))}</p>` +
      (r.pending ? `<p class="muted">${escapeHtml(t("choosePending", { n: r.pending }))}</p>` : ""), [
        { key: "remaining", label: t("chooseRemaining", { n: r.remaining }), primary: true, disabled: !r.remaining },
        { key: "all", label: t("chooseAll") },
        { key: null, label: t("cancel") },
      ]);
    if (c) return startInstall(c, ids);
    return;
  }
  toast(t("tCantStart"), errText(r), "err");
}
$("#btnInstall").onclick = () => startInstall(null);
/* 只安装这一项（显式操作：即使这台设备上已装过也重新安装这一个） */
async function installOne(it) {
  const j = S.job || {};
  if (j.paused && ((j.remaining || 0) > 0 || (j.pending || 0) > 0)) {
    if (!confirm(t("installOneEndsPaused", { n: it.label || it.file }))) return;
  }
  return startInstall("all", [it.id]);
}
$("#btnInstallNew").onclick = () => {
  const ids = S.items.filter(i => !i.installed ||
    ["none", "update", "unknown"].includes(i.installed.state)).map(i => i.id);
  if (!ids.length) { toast(t("tNothingNew"), t("tNothingNewSub"), "warn"); return; }
  startInstall("all", ids);
};
$("#btnPauseAfter").onclick = async () => {
  const r = await api("/api/install/pause", {});
  if (r.ok) toast(t("tPauseAfterSet"), t("tPauseAfterSetSub"), "warn");
  else toast(t("tCantStart"), errText(r), "err");
};
$("#btnContinue").onclick = () => continueInstall(null);
async function continueInstall(rebind) {
  const r = await api("/api/install/continue", { rebind });
  if (r.ok) {
    toast(t("tContinued"), t("tStartInstallSub", { n: r.remaining }) +
      (r.pending ? " · " + t("tStillPending", { n: r.pending }) : ""), "ok");
    return;
  }
  if (r.code === "nothing_remaining" && r.pending) {
    toast(t("tCantStart"), t("tStillPending", { n: r.pending }), "warn"); return;
  }
  if (r.code === "bound_target_lost" || r.code === "bound_target_mismatch") {
    const cur = currentDevice();
    const job = S.job || {};
    const canRebind = cur && cur.state === "device" && cur.serial !== job.serial;
    const c = await modalChoice(t("reboundTitle"),
      `<p>${escapeHtml(errText(r))}</p>` +
      (canRebind ? `<p class="muted">${escapeHtml(t("reboundBody", { a: job.name || job.serial, b: cur.name || cur.serial }))}</p>` : ""),
      [
        { key: "rebind", label: t("reboundGo", { b: canRebind ? (cur.name || cur.serial) : "" }), primary: true, disabled: !canRebind },
        { key: null, label: t("cancel") },
      ]);
    if (c === "rebind") return continueInstall(cur.serial);
    return;
  }
  toast(t("tCantStart"), errText(r), "err");
}
$("#btnCancelCur").onclick = async () => {
  if (!confirm(t("cancelWarn"))) return;
  const r = await api("/api/install/cancel-current", {});
  if (!r.ok) toast(t("tCantStart"), errText(r), "err");
};
$("#btnMark").onclick = async () => {
  const serial = $("#deviceSel").value;
  if (!serial) { toast(t("tNoDevice"), t("tNoDeviceSub"), "warn"); return; }
  $("#btnMark").disabled = true;
  const r = await api("/api/mark", { serial });
  $("#btnMark").disabled = false;
  await refreshState();
  if (r.ok) {
    const c = r.counts || {};
    toast(t("tMarkDone"), t("tMarkMsg", { n: r.count }) +
      (c.update ? t("tMarkUpd", { n: c.update }) : ""), "ok");
  } else toast(t("tMarkFail"), errText(r), "err");
};
$("#btnQuit").onclick = async () => {
  if (!confirm(t("tQuit"))) return;
  let r = await api("/api/quit", {});
  if (!r.ok && (r.code === "busy_install" || r.code === "busy_extract")) {
    if (!confirm(t(r.code === "busy_install" ? "tQuitBusy" : "tQuitBusyExtract"))) return;
    r = await api("/api/quit", { force: true });
  }
  if (!r.ok) { toast(t("tCantStart"), errText(r), "err"); return; }
  document.body.innerHTML = `<div class="empty" style="padding-top:120px">${escapeHtml(t("tQuitDone"))}</div>`;
};

/* 安装按钮组 + 暂停原因横幅 */
function renderJobControls() {
  const j = S.job || {};
  const running = !!j.running;
  const paused = !!j.paused && ((j.remaining || 0) > 0 || (j.pending || 0) > 0);
  $("#btnInstall").classList.toggle("hidden", running);
  $("#btnPauseAfter").classList.toggle("hidden", !running);
  $("#btnCancelCur").classList.toggle("hidden", !running || !j.current);
  $("#btnPauseAfter").disabled = !!j.pauseAfterCurrent;
  $("#btnPauseAfter").textContent = t(j.pauseAfterCurrent ? "pauseAfterSet" : "pauseAfterCurrent");
  $("#btnContinue").classList.toggle("hidden", running || !paused);
  $("#btnContinue").textContent = t("continueN", { n: j.remaining || 0 });
  $("#btnInstall").classList.toggle("ghost", paused);
  $("#btnInstall").classList.toggle("primary", !paused);
  const b = $("#jobBanner");
  if (paused) {
    b.textContent = t("jp_" + (j.pauseReason || "user"), { d: j.name || j.serial || "", n: j.remaining || 0 }) +
      (j.pending ? " " + t("tStillPending", { n: j.pending }) : "");
    b.className = "banner " + (["target_lost", "target_mismatch"].includes(j.pauseReason) ? "err" : "");
  } else if (running && j.pauseAfterCurrent) {
    b.textContent = t("jp_pending", { c: j.currentLabel || "" });
    b.className = "banner";
  } else {
    b.className = "banner hidden";
  }
}

/* ---------------- 卸载 ---------------- */
async function uninstall(pkgs, labels) {
  const serial = $("#deviceSel").value;
  if (!serial) { toast(t("tNoDevice"), t("tNoDeviceSub"), "warn"); return; }
  const names = pkgs.map(p => (labels && labels[p]) || p);
  const keep = !!S.settings.keepDataOnUninstall;
  const dev = (S.devices || []).find(d => d.serial === serial);
  const devLine = t("tUninstallOn", { d: dev ? deviceLabel(dev) : serial });
  const tip = pkgs.length === 1
    ? t("tConfirmUn1", { n: names[0] })
    : t("tConfirmUnN", { n: pkgs.length }) + "\n\n" + names.slice(0, 12).join("\n") +
      (pkgs.length > 12 ? "\n…" : "");
  if (!confirm(tip + "\n" + devLine + "\n\n" + (keep ? t("tKeepNote") : t("tDataNote")))) return;
  const r = await api("/api/uninstall", { serial, packages: pkgs, labels: labels || {}, keepData: keep });
  if (!r.ok) { toast(t("tUninstallFail"), errText(r), "err"); return; }
  toast(t("tUninstallStart"), String(pkgs.length), "warn");
}

/* ---------------- 设备（来自统一管理器的缓存，不触发 adb） ---------------- */
function stateText(d) {
  if (d.state === "device") return t("dsOnline");
  if (d.state === "unauthorized") return t("dsUnauthorized");
  if (d.state === "offline") return t("dsOffline");
  return d.state;
}
function deviceLabel(d) {
  const tag = d.wireless ? t("wTagWiFi") : t("wTagUSB");
  const sub = d.state === "device"
    ? (d.android ? `Android ${d.android} · ${d.abi || "?"}` : t("dsOnline"))
    : stateText(d);
  const peer = d.duplicate ? " · " + t("dSameAs") : "";
  return `[${tag}] ${d.name || d.serial} — ${sub}${peer}`;
}
function refreshDeviceSelect() {
  const sel = $("#deviceSel");
  if (!sel) return;
  const sup = S.sup || {};
  sel.innerHTML = "";
  if (!S.devices.length) {
    sel.innerHTML = `<option value="">${escapeHtml(t("noDevice"))}</option>`;
    return;
  }
  const uo = sup.usbOnly;
  S.devices.forEach(d => {
    const o = document.createElement("option");
    o.value = d.state === "device" ? d.serial : "";
    o.textContent = (sup.stale ? "⏸ " : "") + deviceLabel(d);
    o.disabled = d.state !== "device" || (uo && d.serial !== uo.serial);
    sel.appendChild(o);
  });
  // USB 优先（后台也是这样选的；这里只是后台还没选时的兜底）
  const usable = S.devices.filter(d => d.state === "device" && (!uo || d.serial === uo.serial))
    .sort((a, b) => (a.wireless ? 1 : 0) - (b.wireless ? 1 : 0));
  if (sup.selected && S.devices.some(d => d.serial === sup.selected && d.state === "device")) {
    sel.value = sup.selected;
  } else if (!sup.selected && usable.length) {
    sel.value = usable[0].serial;
    api("/api/supervisor/select", { serial: usable[0].serial });   // 只在还没选时自动选第一台
  } else if (sup.selected) {
    // 选中的设备不见了：保持空，不自动换成别的设备
    const o = document.createElement("option");
    o.value = ""; o.textContent = t("dSelectedGone"); o.selected = true;
    sel.insertBefore(o, sel.firstChild);
  }
  updateWirelessHint();
}
function updateWirelessHint() {
  const d = currentDevice();
  const box = $("#wirelessHint");
  const dup = S.devices.some(x => x.duplicate);
  if (d && d.wireless) {
    box.textContent = dup ? t("wDup") : t("wSlowHint");
    box.classList.remove("hidden");
  } else if (dup) {
    box.textContent = t("wDup");
    box.classList.remove("hidden");
  } else box.classList.add("hidden");
}
$("#btnRefresh").onclick = () => checkOnce();
async function checkOnce() {
  $("#btnRefresh").disabled = true; $("#cCheck").disabled = true;
  const r = await api("/api/supervisor/check", {});
  $("#btnRefresh").disabled = false; $("#cCheck").disabled = false;
  if (r.ok) {
    const n = S.devices.filter(d => d.state === "device").length;
    toast(t("tDevDone"), n ? t("tDevFound", { n }) : t("tDevNone"), n ? "ok" : "warn");
  } else toast(t("tCheckFail"), errText(r), "err");
}
$("#deviceSel").onchange = async () => {
  const serial = $("#deviceSel").value;
  const r = await api("/api/supervisor/select", { serial: serial || null });
  if (!r.ok) { toast(t("tCantStart"), errText(r), "warn"); refreshDeviceSelect(); }
  updateWirelessHint();
};

/* 后台状态：顶栏标签 + 队列页横幅 */
function renderChip() {
  const sup = S.sup;
  const chip = $("#bgChip");
  if (!sup) { chip.textContent = ""; return; }
  const disc = sup.tasks.discovery;
  let text, cls;
  if (sup.bgPaused) { text = t("chipPaused"); cls = "warn"; }
  else if (disc.state === "waiting") { text = t("chipFailWait"); cls = "err"; }
  else { text = t("chipRunning"); cls = "ok"; }
  const extra = [];
  if (!sup.bgPaused && sup.wifiPaused) extra.push(t("chipWifiPaused"));
  if (sup.usbOnly) extra.push(t("chipUsbOnly"));
  chip.textContent = text + (extra.length ? " · " + extra.join(" · ") : "");
  chip.className = "bg-chip " + cls;
  chip.title = t("cLastCheck") + " " + fmtTime(sup.devicesAt);
}
function renderStale() {
  const sup = S.sup;
  const b = $("#staleBanner");
  if (!sup) { b.classList.add("hidden"); return; }
  const disc = sup.tasks.discovery;
  if (sup.bgPaused) {
    b.innerHTML = `${escapeHtml(t("staleBanner", { at: fmtTime(sup.devicesAt) }))}
      <button class="ghost small" data-act="resume">${escapeHtml(t("cResumeAll"))}</button>
      <button class="ghost small" data-act="check">${escapeHtml(t("cCheck"))}</button>`;
    b.classList.remove("hidden");
  } else if (disc.state === "waiting") {
    b.innerHTML = `${escapeHtml(t("failWaitBanner", { at: fmtTime(disc.lastOk) }))}
      <button class="ghost small" data-act="check">${escapeHtml(t("cCheck"))}</button>`;
    b.classList.remove("hidden");
  } else {
    b.classList.add("hidden");
    return;
  }
  b.querySelectorAll("button").forEach(x => x.onclick = () =>
    x.dataset.act === "resume" ? supAct("/api/supervisor/resume") : checkOnce());
}
function renderSupAll() {
  refreshDeviceSelect();
  renderWireless();
  renderChip();
  renderStale();
  renderJobControls();
  if (S.tab === "console") renderConsole();
}
function applySup(st) {
  if (!st) return;
  S.sup = st;
  S.devices = st.devices || [];
  if (st.install && Object.keys(st.install).length && st.install.serial !== undefined) {
    S.job = Object.assign({}, S.job || {}, st.install);
  }
  renderSupAll();
  if (S._lastSel !== st.selected) { S._lastSel = st.selected; renderQueue(); }   // 「卸载」按钮跟着当前设备变
}
async function loadSup() {
  const r = await api("/api/supervisor");
  if (r.booting) { setTimeout(loadSup, 300); return; }
  applySup(r.state);
}
async function supAct(path, body) {
  const r = await api(path, body || {});
  if (!r.ok) toast(t("tCantStart"), errText(r), "err");
  return r;
}

/* ---------------- ADB 控制台 ---------------- */
const TASK_KEYS = ["discovery", "status", "wifi_connect", "wifi_reconnect"];
function badge(state) {
  return `<span class="badge b-${state}">${escapeHtml(t("ts_" + state))}</span>`;
}
function renderConsole() {
  const sup = S.sup;
  if (!sup) return;
  // 控制按钮
  $("#cPauseAll").textContent = t(sup.bgPaused ? "cResumeAll" : "cPauseAll");
  $("#cPauseAll").className = "small " + (sup.bgPaused ? "primary" : "ghost");
  $("#cPauseWifi").textContent = t(sup.wifiPaused ? "cResumeWifi" : "cPauseWifi");
  $("#cPauseWifi").className = "small " + (sup.wifiPaused ? "primary" : "ghost");
  $("#cPauseWifi").disabled = sup.bgPaused;
  const uoSel = $("#cUsbOnlySel");
  const uo = sup.usbOnly;
  uoSel.innerHTML = `<option value="">${escapeHtml(t("cUsbOff"))}</option>` +
    S.devices.filter(d => !d.wireless && d.state === "device")
      .map(d => `<option value="${escapeHtml(d.serial)}">${escapeHtml(d.name || d.serial)} (${escapeHtml(d.serial)})</option>`).join("");
  if (uo && !uoSel.querySelector(`option[value="${CSS.escape(uo.serial)}"]`)) {
    uoSel.insertAdjacentHTML("beforeend", `<option value="${escapeHtml(uo.serial)}">${escapeHtml(uo.name)} — ${escapeHtml(t("dsGone"))}</option>`);
  }
  uoSel.value = uo ? uo.serial : "";
  uoSel.disabled = !!(S.job || {}).running;
  $("#cUsbOnlyNote").textContent = uo ? t("cUsbOnlyOn", { d: uo.name }) : t("cUsbOnlyOffNote");

  let sum;
  if (sup.bgPaused) sum = t("sumPaused", { at: fmtTime(sup.devicesAt) });
  else if (sup.tasks.discovery.state === "waiting") sum = t("sumFailWait");
  else sum = t("sumRunning", { at: fmtTime(sup.devicesAt) });
  if (sup.wifiPaused && !sup.bgPaused) sum += " " + t("sumWifiPaused");
  if ((sup.bgPaused || sup.wifiPaused) && S.devices.some(d => d.wireless && d.origin === "unknown"))
    sum += " " + t("sumExternalConn");
  $("#cSummary").textContent = sum;
  $("#cSummary").className = "ctl-summary " + (sup.bgPaused ? "warn" : "");

  // ADB 服务
  const sv = sup.server;
  if (!sv) {
    $("#cServer").innerHTML = `<p class="muted">${escapeHtml(t("cNoServerInfo"))}</p>`;
  } else {
    const procs = (sv.processes || []).map(p => `
      <tr><td>${p.pid}</td><td>${escapeHtml(t("po_" + p.owner))}</td><td class="mono">${escapeHtml(p.args)}</td></tr>`).join("");
    $("#cServer").innerHTML = `
      <div class="kv"><span>${escapeHtml(t("cAppVer"))}</span><b>${escapeHtml(S.version || "—")} · Python ${escapeHtml((S.runtime || {}).pythonVersion || "?")} <span class="mono">${escapeHtml((S.runtime || {}).python || "")}</span></b></div>
      <div class="kv"><span>${escapeHtml(t("cAdbPath"))}</span><b class="mono">${escapeHtml(sv.path || "—")}</b></div>
      <div class="kv"><span>${escapeHtml(t("cAdbVer"))}</span><b>${escapeHtml(sv.version || "—")}</b></div>
      <div class="kv"><span>${escapeHtml(t("cAdbPort"))}</span><b>${sv.port} · ${escapeHtml(t(sv.listening ? "cListening" : "cNotListening"))}</b></div>
      ${procs ? `<table class="tbl"><tr><th>PID</th><th>${escapeHtml(t("cOwner"))}</th><th>${escapeHtml(t("cCmd"))}</th></tr>${procs}</table>`
              : `<p class="muted">${escapeHtml(t("cNoProc"))}</p>`}
      <p class="muted small-note">${escapeHtml(t("cServerNote"))}</p>
      <p class="muted small-note">${escapeHtml(t("cMdnsNote"))}</p>
      ${sup.bgPaused ? `<p class="muted small-note">${escapeHtml(t("cServerStale", { at: fmtTime(sup.devicesAt) }))}</p>` : ""}`;
  }

  // 设备连接（按核验过的物理序号合并）
  const groups = {};
  S.devices.forEach(d => { const k = d.physical || ("~" + d.serial); (groups[k] = groups[k] || []).push(d); });
  const gHtml = Object.keys(groups).map(k => {
    const list = groups[k];
    const head = list[0];
    const verified = !k.startsWith("~");
    const rows = list.map(d => `
      <div class="conn">
        <span class="tag ${d.wireless ? "tag-wifi" : "tag-usb"}">${escapeHtml(d.wireless ? t("wTagWiFi") : t("wTagUSB"))}</span>
        <span class="mono">${escapeHtml(d.serial)}</span>
        <span class="ds ds-${d.state}">${escapeHtml(stateText(d))}</span>
        ${d.detailPaused ? `<span class="muted">${escapeHtml(t("dDetailPaused"))}</span>` : ""}
        ${d.wireless && d.origin === "unknown" ? `<span class="tag warn">${escapeHtml(t("dOriginUnknown"))}</span>` : ""}
        ${d.wireless ? `<button class="ghost small danger" data-dis="${escapeHtml(d.serial)}">${escapeHtml(t("cDisconnectThis"))}</button>` : ""}
      </div>`).join("");
    return `<div class="dgroup">
        <div class="dhead"><b>${escapeHtml(head.name || head.serial)}</b>
          <span class="muted">${escapeHtml(verified ? t("dPhysical", { s: k }) : t("dPhysicalUnknown"))}</span>
          ${list.length > 1 ? `<span class="tag">${escapeHtml(t("dMerged", { n: list.length }))}</span>` : ""}
        </div>${rows}</div>`;
  }).join("");
  $("#cDevices").innerHTML = (gHtml || `<p class="muted">${escapeHtml(t("noDevice"))}</p>`) +
    (sup.stale ? `<p class="muted small-note">${escapeHtml(t("cStaleNote", { at: fmtTime(sup.devicesAt) }))}</p>` : "");
  $$("#cDevices [data-dis]").forEach(b => b.onclick = async () => {
    const target = b.dataset.dis;
    if (!confirm(t("cDisconnectConfirm", { t: target }))) return;
    const r = await supAct("/api/wireless/disconnect", { hostPort: target });
    if (r.ok) toast(t("wDisconnected"), target, "ok");
  });

  // 后台任务
  const now = Date.now() / 1000;
  const rows = TASK_KEYS.map(k => {
    const tk = sup.tasks[k];
    const next = tk.next && tk.state === "idle" && !sup.bgPaused
      ? t("cNextIn", { n: Math.max(0, Math.round(tk.next - now)) }) : "—";
    const note = tk.note ? t("tn_" + tk.note) : (tk.lastError ? tk.lastError : "");
    return `<tr><td>${escapeHtml(t("tk_" + k))}</td><td>${badge(tk.state)}</td>
      <td>${escapeHtml(fmtTime(tk.lastOk))}</td><td>${escapeHtml(next)}</td>
      <td class="muted">${escapeHtml(note)}</td></tr>`;
  }).join("");
  $("#cTasks").innerHTML = `<table class="tbl"><tr><th>${escapeHtml(t("cTask"))}</th><th>${escapeHtml(t("cState"))}</th>
    <th>${escapeHtml(t("cLastOk"))}</th><th>${escapeHtml(t("cNext"))}</th><th>${escapeHtml(t("cNote"))}</th></tr>${rows}</table>
    <p class="muted small-note">${escapeHtml(t("cNoKeepalive"))}</p>`;
  const rec = sup.reconnect || [];
  $("#cReconnect").innerHTML = rec.length ? `<h4>${escapeHtml(t("cReconnectQ"))}</h4>` + rec.map(r => `
    <div class="conn"><span class="mono">${escapeHtml(r.target)}</span>
      <span>${escapeHtml(r.gaveUp ? t("rcGaveUp") : r.protected ? t("rcProtected")
        : t("rcNext", { a: r.attempts, n: Math.max(0, Math.round((r.next || now) - now)) }))}</span>
      ${r.lastError ? `<span class="muted">${escapeHtml(r.lastError)}</span>` : ""}
      <button class="ghost small" data-retry="${escapeHtml(r.target)}">${escapeHtml(t("cRetryOnce"))}</button></div>`).join("") : "";
  $$("#cReconnect [data-retry]").forEach(b => b.onclick = async () => {
    b.disabled = true;
    const r = await api("/api/supervisor/retry", { target: b.dataset.retry });
    b.disabled = false;
    toast(r.ok ? t("wConnOk", { t: r.target }) : t("wConnFail"), r.ok ? "" : (r.message || errText(r)), r.ok ? "ok" : "err");
  });

  // 安装任务
  const j = S.job || {};
  if (!j.serial) {
    $("#cInstall").innerHTML = `<p class="muted">${escapeHtml(t("cNoJob"))}</p>`;
  } else {
    const state = j.running ? (j.pauseAfterCurrent ? "jsPausing" : "jsRunning")
      : j.paused ? "jsPaused" : j.finished ? "jsDone" : "jsIdle";
    $("#cInstall").innerHTML = `
      <div class="kv"><span>${escapeHtml(t("cBound"))}</span><b>${escapeHtml(j.name || "")} <span class="mono">${escapeHtml(j.serial)}</span></b></div>
      <div class="kv"><span>${escapeHtml(t("cBoundPhys"))}</span><b class="mono">${escapeHtml(j.physical || t("dPhysicalUnknown"))}</b></div>
      <div class="kv"><span>${escapeHtml(t("cState"))}</span><b>${escapeHtml(t(state))}${j.paused ? " — " + escapeHtml(t("pr_" + (j.pauseReason || "user"))) : ""}</b></div>
      <div class="kv"><span>${escapeHtml(t("cCurrentApk"))}</span><b>${escapeHtml(j.currentLabel || "—")}</b></div>
      <div class="kv"><span>${escapeHtml(t("cProgress"))}</span><b>${j.done || 0}/${j.total || 0} · ${escapeHtml(t("cCounts", { o: j.ok || 0, f: j.failed || 0, u: j.unverified || 0 }))}${j.pending ? " · " + escapeHtml(t("cPendingN", { n: j.pending })) : ""}</b></div>
      <div class="kv"><span>${escapeHtml(t("cRemaining"))}</span><b>${j.remaining || 0}</b></div>
      <div class="ctl-row">
        ${j.running ? `<button class="ghost small" data-j="pause" ${j.pauseAfterCurrent ? "disabled" : ""}>${escapeHtml(t(j.pauseAfterCurrent ? "pauseAfterSet" : "pauseAfterCurrent"))}</button>
          <button class="ghost small danger" data-j="cancel">${escapeHtml(t("cancelCurrent"))}</button>` : ""}
        ${!j.running && j.paused && (j.remaining || j.pending) ? `<button class="primary small" data-j="continue">${escapeHtml(t("continueN", { n: j.remaining }))}</button>` : ""}
      </div>
      <p class="muted small-note">${escapeHtml(t("cInstallNote"))}</p>`;
    $$("#cInstall [data-j]").forEach(b => b.onclick = () => ({
      pause: () => $("#btnPauseAfter").click(),
      cancel: () => $("#btnCancelCur").click(),
      continue: () => continueInstall(null),
    })[b.dataset.j]());
  }

  // 最近结果 + 正在执行的 adb 命令
  const lf = sup.lastFailure;
  $("#cRecent").innerHTML = `
    <div class="kv"><span>${escapeHtml(t("cLastCheck"))}</span><b>${escapeHtml(fmtTime(sup.lastCheck))} (${escapeHtml(fmtAgo(sup.lastCheck))})</b></div>
    <div class="kv"><span>${escapeHtml(t("cLastFail"))}</span><b>${lf ? escapeHtml(`${fmtTime(lf.ts)} · ${t("tk_" + lf.stage) || lf.stage} · ${lf.reason}`) : "—"}</b></div>`;
  const act = sup.active || [];
  $("#cActive").innerHTML = act.length ? `<h4>${escapeHtml(t("cActiveCmds"))}</h4>` + act.map(a => `
    <div class="conn"><span class="tag">${escapeHtml(t("src_" + a.source.replace(":", "_")) || a.source)}</span>
      <span class="mono">${escapeHtml(a.cmd)}</span><span class="muted">${(a.ms / 1000).toFixed(1)}s · PID ${a.pid}</span></div>`).join("") : "";
}
$("#cCheck").onclick = () => checkOnce();
$("#cPauseAll").onclick = () => supAct(S.sup && S.sup.bgPaused ? "/api/supervisor/resume" : "/api/supervisor/pause");
$("#cPauseWifi").onclick = () => supAct(S.sup && S.sup.wifiPaused ? "/api/supervisor/resume-wifi" : "/api/supervisor/pause-wifi");
$("#cUsbOnlySel").onchange = async () => {
  const serial = $("#cUsbOnlySel").value || null;
  const r = await supAct("/api/supervisor/usb-only", { serial });
  if (r.ok) toast(serial ? t("tUsbOnlyOn") : t("tUsbOnlyOff"), serial ? (r.usbOnly || {}).name : "", "ok");
  else renderConsole();
};
async function loadCmdLog() {
  const r = await api("/api/supervisor/log?n=150");
  if (!r.ok) return;
  const rows = r.log.slice().reverse().map((x, i) => `
    <div class="cl-row ${x.rc ? "bad" : ""}" data-i="${i}">
      <span>${escapeHtml(fmtTime(x.ended))}</span>
      <span class="tag">${escapeHtml(t("src_" + (x.source || "ui").replace(":", "_")))}</span>
      <span class="mono">${escapeHtml(x.cmd)}</span>
      <span>${x.timeout ? "timeout" : "rc=" + x.rc}</span><span>${x.ms}ms</span>
    </div>
    <pre class="cl-out hidden">${escapeHtml(x.out || "")}</pre>`).join("");
  $("#cLog").innerHTML = rows || `<p class="muted">—</p>`;
  $$("#cLog .cl-row").forEach(row => row.onclick = () => row.nextElementSibling.classList.toggle("hidden"));
}
$("#cLogBox").addEventListener("toggle", () => { if ($("#cLogBox").open) loadCmdLog(); });

/* ---------------- 无线 ---------------- */
function renderWireless() {
  const box = $("#wDevices");
  if (!box) return;
  if (!S.devices.length) {
    box.innerHTML = `<div class="muted">${escapeHtml(t("noDevice"))}</div>`;
  } else {
    box.innerHTML = S.devices.map(d => `
      <div class="wdev">
        <span class="tag ${d.wireless ? "tag-wifi" : "tag-usb"}">${escapeHtml(d.wireless ? t("wTagWiFi") : t("wTagUSB"))}</span>
        <span class="wdev-name">${escapeHtml(d.name || d.serial)}</span>
        <span class="muted">${escapeHtml(d.serial)} · ${escapeHtml(stateText(d))}</span>
        ${d.wireless && d.origin === "unknown" ? `<span class="tag warn">${escapeHtml(t("dOriginUnknown"))}</span>` : ""}
        ${d.duplicate && d.wireless ? `<span class="tag warn">${escapeHtml(t("wDup"))}</span>` : ""}
        ${d.wireless ? `<button class="ghost small danger wd-dis" data-s="${escapeHtml(d.serial)}">${escapeHtml(t("cDisconnectThis"))}</button>` : ""}
      </div>`).join("");
    box.querySelectorAll(".wd-dis").forEach(b => b.onclick = async () => {
      if (!confirm(t("cDisconnectConfirm", { t: b.dataset.s }))) return;
      const r = await supAct("/api/wireless/disconnect", { hostPort: b.dataset.s });
      if (r.ok) toast(t("wDisconnected"), b.dataset.s, "ok");
    });
  }
  const hb = $("#wHistoryBox");
  const hist = S.settings.wirelessHistory || [];
  hb.innerHTML = hist.length
    ? `<div class="muted" style="margin:8px 0 4px">${escapeHtml(t("wHistory"))}</div>` +
      hist.map(h => `<span class="chip" data-h="${escapeHtml(h)}">${escapeHtml(h)}
        <b class="chip-x" data-h="${escapeHtml(h)}">✕</b></span>`).join("")
    : "";
  hb.querySelectorAll(".chip").forEach(c => c.onclick = e => {
    if (e.target.classList.contains("chip-x")) return;
    $("#connAddr").value = c.dataset.h;
  });
  hb.querySelectorAll(".chip-x").forEach(x => x.onclick = async e => {
    e.stopPropagation();
    await api("/api/wireless/forget", { hostPort: x.dataset.h });
    refreshState();
  });
}
$("#btnPair").onclick = async () => {
  const addr = $("#pairAddr").value.trim(), code = $("#pairCode").value.trim();
  if (!addr || !code) return;
  $("#btnPair").disabled = true;
  const r = await api("/api/wireless/pair", { hostPort: addr, code });
  $("#btnPair").disabled = false;
  if (r.ok) {
    toast(t("wPairOk"), r.connected ? t("wConnOk", { t: r.target || "" }) : "", "ok");
    $("#pairCode").value = "";
    refreshState();
  } else toast(t("wPairFail"), r.error || "", "err");
};
$("#btnConnect").onclick = async () => {
  const addr = $("#connAddr").value.trim();
  if (!addr) return;
  $("#btnConnect").disabled = true;
  const r = await api("/api/wireless/connect", { hostPort: addr });
  $("#btnConnect").disabled = false;
  if (r.ok) { toast(t("wConnOk", { t: r.target }), "", "ok"); refreshState(); }
  else toast(t("wConnFail"), r.error || r.message || "", "err");
};
$("#btnSwitchWifi").onclick = async () => {
  // 当前选中的是用线连着的设备就用它；否则用正用线连着的那台（不用先去上面选）
  let d = currentDevice();
  if (!d || d.wireless || d.state !== "device") {
    d = (S.devices || []).find(x => !x.wireless && x.state === "device");
  }
  if (!d) { toast(t("wNeedUsb"), "", "warn"); return; }
  $("#btnSwitchWifi").disabled = true;
  let r = await api("/api/wireless/switch", { serial: d.serial });
  if (!r.ok && r.code === "usb_only_blocks_tcpip") {
    if (confirm(t("wConfirmExitUsbOnly", { d: r.arg || deviceLabel(d) }))) {
      r = await api("/api/wireless/switch", { serial: d.serial, exitUsbOnly: true });
    } else { $("#btnSwitchWifi").disabled = false; return; }
  }
  $("#btnSwitchWifi").disabled = false;
  if (r.ok) {
    toast(t("wSwitchOk", { t: r.target }), r.usbOnlyOff ? t("wUsbOnlyTurnedOff") : "", "ok");
    refreshState();
  } else toast(t("wSwitchFail"), errText(r), "err");
};

/* ---------------- 设备应用 / 提取 ---------------- */
$("#btnScan").onclick = async () => {
  const serial = $("#deviceSel").value;
  if (!serial) { toast(t("tNoDevice"), t("tNoDeviceSub"), "warn"); return; }
  S.apps = []; S.selected.clear(); renderApps();
  const r = await api("/api/apps/scan", { serial, scope: $("#scopeSel").value, icons: true });
  if (!r.ok) { toast(t("tScanFail"), errText(r), "err"); return; }
  S.scanning = true;
  $("#btnScan").disabled = true; $("#btnScanStop").classList.remove("hidden");
  $("#scanProgress").classList.remove("hidden");
  $("#appsEmpty").classList.add("hidden");
};
$("#btnScanStop").onclick = async () => { await api("/api/apps/stop", {}); };
$("#appSearch").oninput = renderApps;

function renderApps() {
  const list = $("#appList");
  if (!list) return;
  const kw = $("#appSearch").value.trim().toLowerCase();
  const apps = S.apps
    .filter(a => !kw || (a.label || "").toLowerCase().includes(kw) || a.package.toLowerCase().includes(kw))
    .sort((a, b) => (a.label || a.package).localeCompare(b.label || b.package));
  list.innerHTML = "";
  apps.forEach(a => {
    const li = document.createElement("li");
    li.className = "row";
    li.innerHTML = `
      <input type="checkbox" ${S.selected.has(a.package) ? "checked" : ""}>
      ${a.icon ? `<img class="icon" src="${a.icon}" alt="">` : letterIcon(a.label)}
      <div class="meta">
        <div class="name">${escapeHtml(a.label || a.package)}</div>
        <div class="sub">${escapeHtml(a.package)}${a.versionName ? " · v" + escapeHtml(a.versionName) : ""}${a.size ? " · " + fmtSize(a.size) : ""}${a.splitCount ? " · " + escapeHtml(t("tagSplit", { n: a.splitCount + 1 })) : ""}</div>
      </div>
      <button class="ghost small extract-btn">${escapeHtml(t("extract"))}</button>
      <button class="ghost small danger uninstall-btn">${escapeHtml(t("uninstall"))}</button>`;
    li.querySelector("input").onchange = e => {
      if (e.target.checked) S.selected.add(a.package); else S.selected.delete(a.package);
      updateSelCount();
    };
    li.querySelector(".extract-btn").onclick = () => extract([a.package]);
    li.querySelector(".uninstall-btn").onclick = () =>
      uninstall([a.package], { [a.package]: a.label });
    list.appendChild(li);
  });
  $("#appsEmpty").classList.toggle("hidden", S.apps.length > 0 || S.scanning);
  updateSelCount();
}
function updateSelCount() {
  const n = S.selected.size;
  $("#btnExtractSel").textContent = t("extractSel", { n });
  $("#btnExtractSel").disabled = n === 0;
  $("#btnUninstallSel").textContent = t("uninstallSel", { n });
  $("#btnUninstallSel").disabled = n === 0;
}
$("#btnUninstallSel").onclick = () => {
  const pkgs = Array.from(S.selected);
  const labels = {};
  S.apps.forEach(a => { if (S.selected.has(a.package)) labels[a.package] = a.label; });
  uninstall(pkgs, labels);
};
$("#btnSelAll").onclick = () => {
  const kw = $("#appSearch").value.trim().toLowerCase();
  const shown = S.apps.filter(a => !kw ||
    (a.label || "").toLowerCase().includes(kw) || a.package.toLowerCase().includes(kw));
  const allOn = shown.length && shown.every(a => S.selected.has(a.package));
  shown.forEach(a => allOn ? S.selected.delete(a.package) : S.selected.add(a.package));
  renderApps();
};
async function extract(pkgs) {
  const serial = $("#deviceSel").value;
  if (!serial) { toast(t("tNoDevice"), t("tNoDeviceSub"), "warn"); return; }
  const apps = S.apps.filter(a => pkgs.includes(a.package));
  const r = await api("/api/extract", { serial, packages: pkgs, apps });
  if (!r.ok) { toast(t("tCantStart"), errText(r), "err"); return; }
  toast(t("tExtractStart"), t("tExtractStartSub", { n: pkgs.length }), "ok");
}
$("#btnExtractSel").onclick = () => extract(Array.from(S.selected));
$("#btnOpenOut").onclick = async () => {
  const dir = (S.settings.extractDir || "") + "/提取APP";
  const r = await api("/api/reveal", { path: dir });
  if (!r.ok) toast(t("tOpenFail"), t("tOpenFailSub"), "warn");
};

/* ---------------- 设置 ---------------- */
$$("[data-set]").forEach(el => {
  el.onchange = async () => {
    const patch = {}; patch[el.dataset.set] = el.checked;
    await api("/api/settings", patch);
    S.settings[el.dataset.set] = el.checked;
    toast(t("tSetSaved"), "", "ok");
  };
});
$("#btnSaveDir").onclick = async () => {
  await api("/api/settings", { extractDir: $("#extractDir").value.trim() });
  S.settings.extractDir = $("#extractDir").value.trim();
  toast(t("tOutSaved"), "", "ok");
};
$("#btnAdbDl").onclick = async () => {
  $("#btnAdbDl").disabled = true;
  $("#adbLog").textContent = "";
  await api("/api/adb/download", {});
};
$("#btnAdbSet").onclick = async () => {
  const r = await api("/api/adb/set", { path: $("#adbPath").value.trim() });
  if (r.ok) { toast(t("tAdbSet"), r.path, "ok"); refreshState(); checkOnce(); }
  else toast(t("tAdbBad"), r.error || "", "err");
};

/* ---------------- 状态同步 ---------------- */
async function refreshState() {
  const st = await api("/api/state");
  if (st.booting) {
    $("#adbState").textContent = t("booting");
    $("#adbState").className = "adb-state";
    setTimeout(refreshState, 300);
    return st;
  }
  S.items = st.items || [];
  S.settings = st.settings || {};
  S.settings.__adbOk = !!(st.adb && st.adb.available);
  S.job = st.job || null;
  S.version = st.version; S.runtime = st.runtime; S.about = st.about || S.about;
  renderAbout();
  renderQueue();
  const sel = $("#profileSel");
  const cur = sel.value;
  sel.innerHTML = `<option value="">${escapeHtml(t("profilePlaceholder"))}</option>` +
    (st.profiles || []).map(p => `<option value="${escapeHtml(p)}">${escapeHtml(p)}</option>`).join("");
  if (cur) sel.value = cur;
  $$("[data-set]").forEach(el => { el.checked = !!S.settings[el.dataset.set]; });
  $("#extractDir").value = S.settings.extractDir || st.baseDir || "";
  const ok = S.settings.__adbOk;
  $("#adbState").textContent = t(ok ? "adbReady" : "adbMissing");
  $("#adbState").className = "adb-state " + (ok ? "good" : "bad");
  $("#adbPathText").textContent = ok ? st.adb.path : "";
  applySup(st.sup);
  return st;
}

/* ---------------- 事件流 ---------------- */
function connectEvents() {
  const es = new EventSource("/api/events");
  es.onmessage = ev => {
    let e; try { e = JSON.parse(ev.data); } catch (_) { return; }
    handleEvent(e);
  };
  es.onerror = () => { };
}
function summaryText(e) {
  let s = t("tSummary", { o: e.ok, f: e.failed, s: e.skipped });
  if (e.unverified) s += t("tSummaryUnv", { n: e.unverified });
  if (e.pending) s += " · " + t("cPendingN", { n: e.pending });
  return s;
}
function handleEvent(e) {
  switch (e.type) {
    case "supervisor":
      applySup(e.state);
      break;
    case "device_autoselect":
      toast(t("tAutoSelUsb"), t("tAutoSelUsbMsg", { d: e.name || e.serial }), "ok");
      break;
    case "usb_only_follow":
      toast(t("tUsbOnlyFollow"), t("tUsbOnlyFollowMsg", { d: e.name || e.serial, o: e.previousName || e.previous || "—" }), "ok");
      break;
    case "job": {
      const wasRunning = !!(S.job && S.job.running);
      S.job = e.job;
      renderJobControls();
      if (wasRunning !== !!(S.job && S.job.running)) renderQueue();   // 安装进行中时禁用每行的按钮
      if (S.tab === "console") renderConsole();
      break;
    }
    case "install_start":
      $("#progressWrap").classList.remove("hidden");
      $("#progressBar").style.width = "0";
      $("#progressText").textContent = t("tPrepare", { n: e.total });
      break;
    case "item": {
      const it = S.items.find(x => x.id === e.id);
      if (it) {
        it.status = e.status; it.code = e.code; it.arg = e.arg;
        if (e.installed !== undefined) it.installed = e.installed;
      }
      renderQueue();
      if (e.progress) {
        const p = e.progress;
        $("#progressBar").style.width = (p.done / p.total * 100).toFixed(1) + "%";
        $("#progressText").textContent = t("tProgress", { d: p.done, t: p.total, o: p.ok, f: p.failed }) +
          (p.skipped ? t("tProgressSkip", { s: p.skipped }) : "");
      }
      const name = it ? (it.label || it.file) : "";
      if (e.status === "success")
        toast(t("tInstalled"), name + " · " + codeText(e.code, e.arg) +
          (e.seconds ? " · " + t("tTook", { n: e.seconds }) : ""), "ok");
      if (e.status === "failed") {
        const hint = codeHint(e.code);
        toast(t("tFailed", { name }), codeText(e.code, e.arg) + (hint ? " — " + hint : ""), "err");
      }
      if (e.status === "unverified") toast(t("tUnverified", { name }), codeText(e.code, e.arg), "warn");
      if (e.status === "cancelled" || e.status === "cancel_installed")
        toast(t("tCancelled", { name }), codeText(e.code, e.arg), "warn");
      if (e.status === "skipped") toast(t("tSkipped"), name + " — " + codeText(e.code, e.arg), "warn");
      if (e.status === "pending_verify") toast(t("tPendingVerify", { name }), codeText(e.code, e.arg), "warn");
      break;
    }
    case "install_paused":
      S.job = e.job;
      renderJobControls();
      toast(t("tPausedTitle"), t("jp_" + (e.reason || "user"), { d: (e.job || {}).name || "", n: (e.job || {}).remaining || 0 }),
        ["target_lost", "target_mismatch"].includes(e.reason) ? "err" : "warn");
      refreshState();
      break;
    case "log":
      $("#log").textContent += e.text + "\n";
      $("#log").scrollTop = $("#log").scrollHeight;
      break;
    case "install_done": {
      const sum = summaryText(e);
      $("#progressBar").style.width = "100%";
      $("#progressText").textContent = t("tAllDoneLine", { s: sum, sec: e.seconds });
      toast(t("tAllDone"), sum, e.failed || e.unverified ? "warn" : "ok");
      const rows = (e.results || []).map(r => {
        const cls = r.status === "success" ? "r-ok" : (r.status === "skipped" || r.status === "unverified" ? "r-skip" : "r-err");
        const mark = r.status === "success" ? "✓" : (r.status === "skipped" ? "–" : r.status === "unverified" ? "⚠" : "✕");
        const hint = r.status === "failed" ? codeHint(r.code) : "";
        return `<div class="res"><span class="${cls}">${mark}</span>
          <span class="r-name">${escapeHtml(r.label || "")}</span>
          <span class="muted">${escapeHtml(codeText(r.code, r.arg))}${hint ? " · " + escapeHtml(hint) : ""}</span></div>`;
      }).join("");
      modal(t("tDoneTitle", { s: sum }),
        `<p class="muted">${escapeHtml(t("tDoneBody", { n: e.total, sec: e.seconds }))}</p>${rows}`);
      refreshState();
      break;
    }
    case "scan_start":
      $("#scanText").textContent = t("scanReading", { n: e.total });
      break;
    case "scan_item": {
      S.apps.push(e.app);
      $("#scanBar").style.width = (e.done / Math.max(1, e.total) * 100).toFixed(1) + "%";
      $("#scanText").textContent = `${e.done}/${e.total} · ${e.app.label || e.app.package}`;
      $("#scanInfo").textContent = t("scanned", { a: e.done, b: e.total });
      if (e.done % 3 === 0 || e.done === e.total) renderApps();
      break;
    }
    case "scan_done":
      S.scanning = false;
      $("#btnScan").disabled = false;
      $("#btnScanStop").classList.add("hidden");
      $("#scanProgress").classList.add("hidden");
      renderApps();
      if (e.error) toast(t("tScanFail"), e.error, "err");
      else toast(e.cancelled ? t("tScanStopped") : t("tScanDone"),
        t("tScanTotal", { n: S.apps.length }), "ok");
      break;
    case "extract_start":
      toast(t("tExtracting"), e.dir, "ok");
      break;
    case "extract_done": {
      if (e.blocked) break;
      const rows = (e.results || []).map(r =>
        `<div class="res"><span class="${r.ok ? "r-ok" : "r-err"}">${r.ok ? "✓" : "✕"}</span>
         <span class="r-name">${escapeHtml(r.label)}</span>
         <span class="muted">${r.ok ? escapeHtml(t("tFiles", { n: r.files.length })) : escapeHtml(r.error || "")}</span></div>`).join("");
      toast(t("tExtractDone"), t("tExtractDoneSub", { a: e.ok, b: e.total }),
        e.ok === e.total ? "ok" : "warn");
      modal(t("tExtractDone"), `<p class="muted">${escapeHtml(t("tExtractSaved", { d: e.dir }))}</p>${rows}`);
      break;
    }
    case "uninstall_item":
      toast(e.ok ? t("tUninstalled") : t("tUninstallFail"),
        e.label + " — " + codeText(e.code, e.arg), e.ok ? "ok" : "err");
      if (e.ok) {
        S.apps = S.apps.filter(a => a.package !== e.package);
        S.selected.delete(e.package);
        renderApps();
      }
      break;
    case "uninstall_done":
      refreshState();
      if (e.total > 1) {
        const rows = (e.results || []).map(r =>
          `<div class="res"><span class="${r.ok ? "r-ok" : "r-err"}">${r.ok ? "✓" : "✕"}</span>
           <span class="r-name">${escapeHtml(r.label)}</span>
           <span class="muted">${escapeHtml(codeText(r.code, r.arg))}</span></div>`).join("");
        modal(t("tUninstallDone", { a: e.ok, b: e.total }), rows);
      }
      break;
    case "marked":
      refreshState();
      break;
    case "adb":
      $("#adbLog").textContent += e.text + "\n";
      if (e.done) {
        $("#btnAdbDl").disabled = false;
        toast(e.ok ? t("tAdbReady") : t("tAdbFail"), e.ok ? t("tAdbReadySub") : e.text,
          e.ok ? "ok" : "err");
        refreshState(); checkOnce();
      }
      break;
    case "queue":
      if (["add", "remove", "clear", "sort", "reorder", "reset"].includes(e.action)) refreshState();
      break;
  }
}

/* ---------------- 启动 ---------------- */
(function () {
  applyLang(detectLang(localStorage.getItem("lang")));
  connectEvents();
  refreshState();
  loadSup();
  // 只刷新控制台上的「N 秒后」倒计时，纯界面渲染，不发任何 adb 请求
  setInterval(() => { if (S.tab === "console") renderConsole(); }, 1000);
})();
