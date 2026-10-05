"use strict";
const $ = (s) => document.querySelector(s);
const $$ = (s) => Array.from(document.querySelectorAll(s));
const api = async (path, body, method) => {
  const opt = { method: method || (body ? "POST" : "GET") };
  if (body) { opt.headers = { "Content-Type": "application/json" }; opt.body = JSON.stringify(body); }
  const r = await fetch(path, opt);
  return r.json();
};

const S = { items: [], devices: [], settings: {}, apps: [], selected: new Set(), scanning: false };

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
function modal(title, html) {
  $("#modalTitle").textContent = title;
  $("#modalBody").innerHTML = html;
  $("#modal").classList.remove("hidden");
}
$("#modalOk").onclick = () => $("#modal").classList.add("hidden");

/* ---------------- 语言 ---------------- */
function applyLang(code) {
  setLang(code);
  $("#langSel").value = LANG;
  applyStatic();
  $("#sortDir").textContent = t($("#sortDir").dataset.desc === "1" ? "desc" : "asc");
  const ph = $("#profileSel") && $("#profileSel").querySelector('option[value=""]');
  if (ph) ph.textContent = t("profilePlaceholder");
  renderQueue();
  renderApps();
  renderWireless();
  refreshDeviceSelect();
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
$$(".tab").forEach(tab => tab.onclick = () => {
  $$(".tab").forEach(x => x.classList.remove("active"));
  $$(".page").forEach(x => x.classList.remove("active"));
  tab.classList.add("active");
  $("#page-" + tab.dataset.tab).classList.add("active");
});

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
    const hint = it.status === "failed" ? codeHint(it.code) : "";
    const installed = it.installed && it.installed.state && it.installed.state !== "none";
    li.innerHTML = `
      <span class="handle">⠿</span>
      <span class="idx">${i + 1}</span>
      ${it.icon ? `<img class="icon" src="${it.icon}" alt="">` : letterIcon(it.label)}
      <div class="meta">
        <div class="name">${escapeHtml(it.label || it.file)}</div>
        <div class="sub">${escapeHtml(it.package || it.file)} · ${it.versionName ? "v" + escapeHtml(it.versionName) + " · " : ""}${it.sizeText || ""}</div>
        <div class="tagline">${tags.join("")}</div>
      </div>
      <div class="status ${it.status || "pending"}">
        <div>${escapeHtml(statusText(it))}</div>
        ${hint ? `<div class="hintline">${escapeHtml(hint)}</div>` : ""}
      </div>
      ${installed ? `<button class="ghost small uninst">${escapeHtml(t("uninstall"))}</button>` : ""}
      <button class="rm" title="${escapeHtml(t("removeFromQueue"))}">✕</button>`;
    li.querySelector(".rm").onclick = async () => {
      await api("/api/queue/remove", { ids: [it.id] });
      refreshState();
    };
    const ub = li.querySelector(".uninst");
    if (ub) ub.onclick = () => uninstall([it.package], { [it.package]: it.label });
    list.appendChild(li);
  });
  wireDrag();
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
  if (!confirm(t("tConfirmClear"))) return;
  await api("/api/queue/clear", {});
  refreshState();
};

/* ---------------- 安装 ---------------- */
function currentDevice() {
  return S.devices.find(d => d.serial === $("#deviceSel").value);
}
$("#btnInstall").onclick = async () => {
  const serial = $("#deviceSel").value;
  if (!serial) { toast(t("tNoDevice"), t("tNoDeviceSub"), "warn"); return; }
  if (!S.items.length) { toast(t("tQueueEmpty"), t("tQueueEmptySub"), "warn"); return; }
  await api("/api/queue/reset", {});
  const r = await api("/api/install", { serial });
  if (!r.ok) { toast(t("tCantStart"), r.error || "", "err"); return; }
  $("#log").textContent = "";
  $("#logBox").open = true;
};
$("#btnStop").onclick = async () => {
  await api("/api/install/stop", {});
  toast(t("tStopping"), t("tStoppingSub"), "warn");
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
  } else toast(t("tMarkFail"), r.error || "", "err");
};
$("#btnInstallNew").onclick = async () => {
  const serial = $("#deviceSel").value;
  if (!serial) { toast(t("tNoDevice"), t("tNoDeviceSub"), "warn"); return; }
  const ids = S.items.filter(i => !i.installed ||
    ["none", "update", "unknown"].includes(i.installed.state)).map(i => i.id);
  if (!ids.length) { toast(t("tNothingNew"), t("tNothingNewSub"), "warn"); return; }
  await api("/api/queue/reset", {});
  const r = await api("/api/install", { serial, ids });
  if (!r.ok) { toast(t("tCantStart"), r.error || "", "err"); return; }
  toast(t("tStartInstall"), t("tStartInstallSub", { n: ids.length }), "ok");
  $("#log").textContent = ""; $("#logBox").open = true;
};
$("#btnQuit").onclick = async () => {
  if (!confirm(t("tQuit"))) return;
  await api("/api/quit", {});
  document.body.innerHTML = `<div class="empty" style="padding-top:120px">${escapeHtml(t("tQuitDone"))}</div>`;
};

/* ---------------- 卸载 ---------------- */
async function uninstall(pkgs, labels) {
  const serial = $("#deviceSel").value;
  if (!serial) { toast(t("tNoDevice"), t("tNoDeviceSub"), "warn"); return; }
  const names = pkgs.map(p => (labels && labels[p]) || p);
  const keep = !!S.settings.keepDataOnUninstall;
  const tip = pkgs.length === 1
    ? t("tConfirmUn1", { n: names[0] })
    : t("tConfirmUnN", { n: pkgs.length }) + "\n\n" + names.slice(0, 12).join("\n") +
      (pkgs.length > 12 ? "\n…" : "");
  if (!confirm(tip + "\n\n" + (keep ? t("tKeepNote") : t("tDataNote")))) return;
  await api("/api/uninstall", { serial, packages: pkgs, labels: labels || {}, keepData: keep });
  toast(t("tUninstallStart"), String(pkgs.length), "warn");
}

/* ---------------- 设备 ---------------- */
let lastMarkedSerial = null;
function deviceLabel(d) {
  const tag = d.wireless ? t("wTagWiFi") : t("wTagUSB");
  let sub;
  if (d.stateCode === "ok") sub = `Android ${d.android || "?"} · ${d.abi || "?"}`;
  else if (d.stateCode === "unauthorized") sub = t("sUnauthorized");
  else if (d.stateCode === "offline") sub = t("sOffline");
  else sub = d.state;
  return `[${tag}] ${d.name || d.serial} — ${sub}`;
}
function refreshDeviceSelect() {
  const sel = $("#deviceSel");
  if (!sel) return;
  const old = sel.value;
  sel.innerHTML = "";
  if (!S.devices.length) {
    sel.innerHTML = `<option value="">${escapeHtml(t("noDevice"))}</option>`;
    return;
  }
  S.devices.forEach(d => {
    const o = document.createElement("option");
    o.value = d.state === "device" ? d.serial : "";
    o.textContent = deviceLabel(d);
    o.disabled = d.state !== "device";
    sel.appendChild(o);
  });
  const usable = S.devices.filter(d => d.state === "device");
  if (old && usable.some(d => d.serial === old)) sel.value = old;
  else if (usable.length) sel.value = usable[0].serial;
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
async function refreshDevices() {
  const r = await api("/api/devices");
  if (r.booting) { setTimeout(refreshDevices, 400); return r; }
  S.devices = r.devices || [];
  refreshDeviceSelect();
  renderWireless();
  const sel = $("#deviceSel");
  if (sel.value !== lastMarkedSerial) {
    lastMarkedSerial = sel.value;
    if (S.settings.autoMark !== false) {
      api("/api/mark", { serial: sel.value || null }).then(() => refreshState());
    }
  }
  return r;
}
$("#btnRefresh").onclick = async () => {
  $("#btnRefresh").disabled = true;
  const r = await refreshDevices();
  $("#btnRefresh").disabled = false;
  const n = (r.devices || []).filter(d => d.state === "device").length;
  toast(t("tDevDone"), n ? t("tDevFound", { n }) : t("tDevNone"), n ? "ok" : "warn");
};
$("#deviceSel").onchange = async () => {
  lastMarkedSerial = $("#deviceSel").value;
  updateWirelessHint();
  if (S.settings.autoMark !== false) {
    await api("/api/mark", { serial: lastMarkedSerial || null });
    refreshState();
  }
};

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
        <span class="muted">${escapeHtml(d.serial)}</span>
        ${d.duplicate && d.wireless ? `<span class="tag warn">${escapeHtml(t("wDup"))}</span>` : ""}
        ${d.wireless ? `<button class="ghost small danger wd-dis" data-s="${escapeHtml(d.serial)}">${escapeHtml(t("wForget"))}</button>` : ""}
      </div>`).join("");
    box.querySelectorAll(".wd-dis").forEach(b => b.onclick = async () => {
      const r = await api("/api/wireless/disconnect", { hostPort: b.dataset.s });
      toast(t("wDisconnected"), b.dataset.s, "ok");
      refreshDevices();
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
    refreshDevices(); refreshState();
  } else toast(t("wPairFail"), r.error || "", "err");
};
$("#btnConnect").onclick = async () => {
  const addr = $("#connAddr").value.trim();
  if (!addr) return;
  $("#btnConnect").disabled = true;
  const r = await api("/api/wireless/connect", { hostPort: addr });
  $("#btnConnect").disabled = false;
  if (r.ok) { toast(t("wConnOk", { t: r.target }), "", "ok"); refreshDevices(); refreshState(); }
  else toast(t("wConnFail"), r.error || r.message || "", "err");
};
$("#btnDisconnectAll").onclick = async () => {
  await api("/api/wireless/disconnect", {});
  toast(t("wDisconnected"), "", "ok");
  refreshDevices();
};
$("#btnSwitchWifi").onclick = async () => {
  const d = currentDevice();
  if (!d || d.wireless) { toast(t("wNeedUsb"), "", "warn"); return; }
  $("#btnSwitchWifi").disabled = true;
  const r = await api("/api/wireless/switch", { serial: d.serial });
  $("#btnSwitchWifi").disabled = false;
  if (r.ok) {
    toast(t("wSwitchOk", { t: r.target }), "", "ok");
    refreshDevices(); refreshState();
  } else toast(t("wSwitchFail"), r.error || r.message || "", "err");
};

/* ---------------- 设备应用 / 提取 ---------------- */
$("#btnScan").onclick = async () => {
  const serial = $("#deviceSel").value;
  if (!serial) { toast(t("tNoDevice"), t("tNoDeviceSub"), "warn"); return; }
  S.apps = []; S.selected.clear(); renderApps();
  const r = await api("/api/apps/scan", { serial, scope: $("#scopeSel").value, icons: true });
  if (!r.ok) { toast(t("tScanFail"), r.error || "", "err"); return; }
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
  await api("/api/extract", { serial, packages: pkgs, apps });
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
  if (r.ok) { toast(t("tAdbSet"), r.path, "ok"); refreshState(); refreshDevices(); }
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
  renderQueue();
  renderWireless();
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
  const running = st.job && st.job.running;
  $("#btnInstall").classList.toggle("hidden", !!running);
  $("#btnStop").classList.toggle("hidden", !running);
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
  return t("tSummary", { o: e.ok, f: e.failed, s: e.skipped });
}
function handleEvent(e) {
  switch (e.type) {
    case "install_start":
      $("#progressWrap").classList.remove("hidden");
      $("#progressBar").style.width = "0";
      $("#progressText").textContent = t("tPrepare", { n: e.total });
      $("#btnInstall").classList.add("hidden");
      $("#btnStop").classList.remove("hidden");
      break;
    case "item": {
      const it = S.items.find(x => x.id === e.id);
      if (it) { it.status = e.status; it.code = e.code; it.arg = e.arg; }
      renderQueue();
      if (e.progress) {
        const p = e.progress;
        $("#progressBar").style.width = (p.done / p.total * 100).toFixed(1) + "%";
        $("#progressText").textContent = t("tProgress", { d: p.done, t: p.total, o: p.ok, f: p.failed }) +
          (p.skipped ? t("tProgressSkip", { s: p.skipped }) : "");
      }
      const name = it ? (it.label || it.file) : "";
      if (e.status === "success")
        toast(t("tInstalled"), name + (e.seconds ? " · " + t("tTook", { n: e.seconds }) : ""), "ok");
      if (e.status === "failed") {
        const hint = codeHint(e.code);
        toast(t("tFailed", { name }), codeText(e.code, e.arg) + (hint ? " — " + hint : ""), "err");
      }
      if (e.status === "skipped") toast(t("tSkipped"), name + " — " + codeText(e.code, e.arg), "warn");
      break;
    }
    case "log":
      $("#log").textContent += e.text + "\n";
      $("#log").scrollTop = $("#log").scrollHeight;
      break;
    case "install_done": {
      const sum = summaryText(e);
      $("#progressBar").style.width = "100%";
      $("#progressText").textContent = t("tAllDoneLine", { s: sum, sec: e.seconds });
      $("#btnInstall").classList.remove("hidden");
      $("#btnStop").classList.add("hidden");
      toast(t("tAllDone"), sum, e.failed ? "warn" : "ok");
      const rows = (e.results || []).map(r => {
        const cls = r.status === "success" ? "r-ok" : (r.status === "skipped" ? "r-skip" : "r-err");
        const mark = r.status === "success" ? "✓" : (r.status === "skipped" ? "–" : "✕");
        const hint = r.status === "failed" ? codeHint(r.code) : "";
        return `<div class="res"><span class="${cls}">${mark}</span>
          <span class="r-name">${escapeHtml(r.label || "")}</span>
          <span class="muted">${escapeHtml(codeText(r.code, r.arg))}${hint ? " · " + escapeHtml(hint) : ""}</span></div>`;
      }).join("");
      modal(t("tDoneTitle", { s: sum }),
        `<p class="muted">${escapeHtml(t("tDoneBody", { n: e.total, sec: e.seconds }))}</p>${rows}`);
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
    case "wireless":
      if (e.action === "reconnected") toast(t("wReconnected", { t: e.target }), "", "ok");
      refreshDevices();
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
        refreshState(); refreshDevices();
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
  refreshDevices();
  setInterval(refreshDevices, 8000);
  window.addEventListener("focus", () => refreshDevices());
})();
