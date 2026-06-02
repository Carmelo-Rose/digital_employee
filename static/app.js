// 前端逻辑：上传 → 分析 → 展示 → 推送 → 历史 / 环比。原生 JS，无构建。
const $ = (id) => document.getElementById(id);

let fileId = null;
let fileName = "";
let reportMarkdown = "";
let currentReportId = null;
let currentAnalysis = null;   // 保存最新 analysis_result，推送时传给后端构建卡片
let currentThreadId = null;   // HITL：当前图的 thread_id，resume 时使用

const CATEGORY_TITLES = {
  paid_not_shipped: "已付款未发货",
  logistics_abnormal: "物流异常/超时",
  refund_abnormal: "退款状态异常",
  low_stock: "库存不足",
  cs_keyword: "客服备注预警",
  amount_anomaly: "订单金额异常",
};

function toast(msg, isErr = false) {
  const t = $("toast");
  t.textContent = msg;
  t.className = "toast" + (isErr ? " err" : "");
  t.hidden = false;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => (t.hidden = true), 3200);
}

async function postJSON(url, body) {
  const resp = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!resp.ok) throw new Error((await resp.json()).detail || resp.statusText);
  return resp.json();
}

// 当前选中的业务域
let currentDomain = "ecommerce";

// 渲染业务域选择器
function renderDomainBox(data) {
  const box = $("domainBox");
  const sel = $("domainSelect");
  const badge = $("domainInferBadge");
  const domains = data.available_domains || { ecommerce: "电商运营" };
  sel.innerHTML = Object.entries(domains)
    .map(([k, v]) => `<option value="${k}">${v}</option>`)
    .join("");
  currentDomain = data.inferred_domain || "ecommerce";
  sel.value = currentDomain;
  badge.textContent = data.infer_method === "llm" ? "🤖 AI 推断" : "🔤 关键词推断";
  box.hidden = false;
  sel.onchange = () => {
    currentDomain = sel.value;
    loadMemory(currentDomain);   // 切换 domain 后刷新字段下拉
    renderTeachUI();
  };
}

// ① 上传
$("uploadBtn").onclick = async () => {
  const f = $("fileInput").files[0];
  if (!f) return toast("请先选择文件", true);
  fileName = f.name;
  const fd = new FormData();
  fd.append("file", f);
  $("uploadBtn").disabled = true;
  try {
    const resp = await fetch("/api/upload", { method: "POST", body: fd });
    if (!resp.ok) throw new Error((await resp.json()).detail || "上传失败");
    const data = await resp.json();
    fileId = data.file_id;
    const cols = Object.keys(data.recognized_columns);
    const previewN = (data.preview && data.preview.length) || Math.min(5, data.rows);
    $("uploadInfo").innerHTML =
      `✅ 已上传 <b>${data.filename}</b>，预览 ${previewN} 行，共 ${data.rows} 行数据。<br>` +
      `识别到 ${cols.length} 个标准字段：${cols.join("、") || "无"}` +
      (data.unrecognized_columns.length
        ? `<br>未识别列：${data.unrecognized_columns.join("、")}` : "");
    // 业务域选择器
    renderDomainBox(data);
    // 刷新 memory（带新 domain），等字段列表拿回来再渲染教学 UI
    lastUnrecognized = data.unrecognized_columns || [];
    await loadMemory(currentDomain);
    renderTeachUI();
    $("analyzeBtn").disabled = false;
    toast("上传成功，可以开始分析");
  } catch (e) {
    toast(e.message, true);
  } finally {
    $("uploadBtn").disabled = false;
  }
};

// 「强制 mock」只在勾选了「AI 日报」时可用
$("useLlm").onchange = () => {
  const fm = $("forceMock");
  fm.disabled = !$("useLlm").checked;
  if (fm.disabled) fm.checked = false;
};

const MODE_LABEL = { rule: "规则版", llm: "AI·真实模型", mock: "AI·mock" };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// 把后端 LangGraph 各节点返回的真实 steps 逐条「播放」出来
async function playSteps(steps) {
  const ol = $("steps");
  ol.innerHTML = "";
  for (const st of steps) {
    const status = st.status || "done";
    const li = document.createElement("li");
    if (status === "done") {
      li.className = "step running";
      li.innerHTML = `<span class="ico">⏳</span><span class="txt"><b>${st.name}</b> …</span>`;
      ol.appendChild(li);
      await sleep(380);
      li.className = "step done";
      li.innerHTML = `<span class="ico">✅</span><span class="txt"><b>${st.name}</b> <i>${st.detail || ""}</i></span>`;
    } else if (status === "waiting") {
      li.className = "step waiting";
      li.id = "stepConfirm";
      li.innerHTML = `<span class="ico">🕓</span><span class="txt"><b>${st.name}</b> ${st.detail || ""}</span>`;
      ol.appendChild(li);
    } else {
      li.className = "step err";
      li.innerHTML = `<span class="ico">❌</span><span class="txt"><b>${st.name}</b> ${st.detail || ""}</span>`;
      ol.appendChild(li);
    }
  }
}

function markConfirmDone(mock) {
  const li = $("stepConfirm");
  if (li) {
    li.className = "step done";
    li.innerHTML = `<span class="ico">✅</span><span class="txt"><b>人工确认完成</b></span>`;
  }
  const done = document.createElement("li");
  done.className = "step done";
  done.innerHTML = `<span class="ico">🎉</span><span class="txt"><b>已完成</b> ${mock ? "（模拟推送）" : "已推送企业微信"}</span>`;
  $("steps").appendChild(done);
}

// ② 分析（驱动执行步骤）
$("analyzeBtn").onclick = async () => {
  if (!fileId) return;
  const useLlm = $("useLlm").checked;
  const forceMock = $("forceMock").checked;
  $("analyzeBtn").disabled = true;
  $("analyzeStatus").textContent = "执行中…";
  $("resultCard").hidden = true;
  $("pushStatus").textContent = "";
  $("pushBtn").disabled = false;
  $("stepsCard").hidden = false;
  $("steps").innerHTML = `<li class="step running"><span class="ico">⏳</span><span class="txt">数字员工启动中…</span></li>`;
  $("stepsCard").scrollIntoView({ behavior: "smooth" });
  try {
    const data = await postJSON("/api/analyze", {
      file_id: fileId, file_name: fileName, use_llm: useLlm, force_mock: forceMock,
      domain_name: currentDomain,
    });
    reportMarkdown = data.report_markdown || "";
    currentReportId = data.report_id || null;
    currentAnalysis = data.analysis_result || data.summary || null;
    currentThreadId = data.thread_id || null;   // 保存 HITL thread_id
    await playSteps(data.steps || []);
    if (reportMarkdown) {
      renderSummary(data.summary);
      renderReport(reportMarkdown);
      $("resultCard").hidden = false;
      $("analyzeStatus").textContent = `✅ 完成（${MODE_LABEL[data.report_mode] || data.report_mode}）`;
      // 重置审核区状态
      setHitlState("waiting");
      $("resultCard").scrollIntoView({ behavior: "smooth" });
      // 自动拉取环比
      if (currentReportId) fetchCompare(currentReportId);
      loadHistory();
    } else {
      $("analyzeStatus").textContent = "❌ 失败";
      toast((data.errors && data.errors[0]) || "分析失败", true);
    }
  } catch (e) {
    toast(e.message, true);
    $("analyzeStatus").textContent = "❌ 失败";
    $("steps").innerHTML += `<li class="step err"><span class="ico">❌</span><span class="txt">${e.message}</span></li>`;
  } finally {
    $("analyzeBtn").disabled = false;
  }
};

function renderSummary(summary) {
  const s = summary.summary || {};
  const titles = summary.category_titles || CATEGORY_TITLES;  // 优先用后端标签
  const chips = [
    `<span class="chip">订单总数 ${summary.total_orders}</span>`,
    `<span class="chip warn">异常订单 ${summary.anomaly_orders ?? summary.anomaly_total}</span>`,
  ];
  for (const [k, v] of Object.entries(s)) {
    chips.push(`<span class="chip${v > 0 ? " warn" : ""}">${titles[k] || CATEGORY_TITLES[k] || k} ${v}</span>`);
  }
  $("summary").innerHTML = chips.join("");
}

function renderReport(md) {
  const el = $("report");
  if (window.marked) {
    el.innerHTML = window.marked.parse(md);
  } else {
    el.innerHTML = `<pre>${md.replace(/</g, "&lt;")}</pre>`; // CDN 失败回退
  }
}

// 复制报告 / 下载 Markdown
$("copyBtn").onclick = async () => {
  if (!reportMarkdown) return toast("请先生成日报", true);
  try {
    await navigator.clipboard.writeText(reportMarkdown);
    toast("报告已复制到剪贴板");
  } catch {
    toast("复制失败，请手动选择文本复制", true);
  }
};

$("downloadBtn").onclick = () => {
  if (!reportMarkdown) return toast("请先生成日报", true);
  const blob = new Blob([reportMarkdown], { type: "text/markdown;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `运营日报_${new Date().toISOString().slice(0, 10)}.md`;
  a.click();
  URL.revokeObjectURL(a.href);
};

// ── 环比 ─────────────────────────────────────────────────────────────────────

async function fetchCompare(reportId) {
  const panel = $("comparePanel");
  panel.hidden = true;
  try {
    const resp = await fetch(`/api/reports/${reportId}/compare`);
    if (!resp.ok) return;
    const data = await resp.json();
    if (!data.has_prev) return;   // 第一条报告，无对比
    panel.innerHTML = renderCompare(data);
    panel.hidden = false;
  } catch (_) { /* 静默失败，不阻断主流程 */ }
}

function renderCompare(data) {
  const m = data.metrics;
  const prevDate = data.prev_date || "上次";

  // neutral=true 表示增加不算恶化（如总订单数）
  function arrow(delta, pct, neutral = false) {
    if (delta === 0) return `<span class="cmp-flat">— 持平</span>`;
    const up = delta > 0;
    const cls = neutral ? "cmp-neutral" : (up ? "cmp-up" : "cmp-dn");
    const icon = up ? "▲" : "▼";
    const pctStr = pct !== null ? `${Math.abs(pct)}%` : "";
    return `<span class="${cls}">${icon} ${Math.abs(delta)} ${pctStr}</span>`;
  }

  function metricRow(label, m, neutral = false) {
    return `<div class="cmp-row">
      <span class="cmp-label">${label}</span>
      <span class="cmp-val">${m.current}</span>
      <span class="cmp-prev">（上次 ${m.prev}）</span>
      ${arrow(m.delta, m.pct, neutral)}
    </div>`;
  }

  const cats = m.categories || {};
  const catRows = Object.entries(cats).map(([k, v]) =>
    metricRow(CATEGORY_TITLES[k] || k, v)
  ).join("");

  return `
    <div class="cmp-header">📊 环比对比（对比日期：${prevDate}）</div>
    <div class="cmp-grid">
      ${metricRow("总订单数", m.total_orders, true)}
      ${metricRow("异常项总数", m.anomaly_total)}
      ${metricRow("异常订单数", m.anomaly_orders)}
      ${catRows}
    </div>`;
}

// ── 历史报告 ──────────────────────────────────────────────────────────────────

async function loadHistory() {
  const el = $("historyList");
  el.innerHTML = `<span class="info">加载中…</span>`;
  try {
    const resp = await fetch("/api/reports?limit=20");
    if (!resp.ok) throw new Error("请求失败");
    const data = await resp.json();
    const rows = data.reports || [];
    if (!rows.length) {
      el.innerHTML = `<span class="info">暂无历史记录</span>`;
      return;
    }
    el.innerHTML = rows.map((r) => `
      <div class="history-row" data-id="${r.id}">
        <div class="hist-main">
          <span class="hist-name">${escHtml(r.file_name)}</span>
          <span class="hist-date">${r.report_date}</span>
        </div>
        <div class="hist-chips">
          <span class="chip">共 ${r.total_orders} 单</span>
          <span class="chip${r.anomaly_orders > 0 ? " warn" : ""}">异常 ${r.anomaly_orders} 单</span>
          <span class="chip">${r.report_mode}</span>
        </div>
        <span class="hist-time">${r.created_at}</span>
      </div>
    `).join("");

    // 点击历史条目，拉取完整报告展示
    el.querySelectorAll(".history-row").forEach((row) => {
      row.onclick = () => loadHistoryReport(Number(row.dataset.id));
    });
  } catch (e) {
    el.innerHTML = `<span class="info">加载失败：${e.message}</span>`;
  }
}

async function loadHistoryReport(id) {
  try {
    const resp = await fetch(`/api/reports/${id}`);
    if (!resp.ok) throw new Error("报告不存在");
    const data = await resp.json();
    reportMarkdown = data.report_markdown || "";
    currentReportId = data.id;
    if (data.analysis_result) renderSummary({ ...data.analysis_result, summary: data.summary });
    if (reportMarkdown) renderReport(reportMarkdown);
    $("resultCard").hidden = false;
    $("analyzeStatus").textContent = `✅ 历史报告（${data.report_date}）`;
    $("resultCard").scrollIntoView({ behavior: "smooth" });
    fetchCompare(id);
  } catch (e) {
    toast(e.message, true);
  }
}

function escHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );
}

$("refreshHistory").onclick = loadHistory;

// 页面加载时拉一次历史
loadHistory();

// ── HITL 审核区状态管理 ────────────────────────────────────────────────────────

function setHitlState(state) {
  // state: "waiting" | "done" | "rejected" | "reset"
  const badge = $("hitlBadge");
  const actionBtns = ["pushBtn", "editBtn", "reviseBtn", "rejectBtn"].map($);
  const setBtns = (disabled) => actionBtns.forEach((b) => b && (b.disabled = disabled));
  if (state === "done") {
    badge.className = "hitl-badge done";
    badge.textContent = "✅ 已批准推送";
    setBtns(true);
  } else if (state === "rejected") {
    badge.className = "hitl-badge rejected";
    badge.textContent = "🚫 已拒绝推送";
    setBtns(true);
  } else {
    // waiting / reset：回到等待复审
    badge.className = "hitl-badge";
    badge.textContent = "⏸ 等待人工审核";
    setBtns(false);
    $("pushStatus").textContent = "";
    // 收起编辑/反馈输入区
    $("editBox").hidden = true;
    $("reviseBox").hidden = true;
    $("report").hidden = false;
  }
}

// ④-A 确认推送 → resume approve
$("pushBtn").onclick = async () => {
  if (!reportMarkdown) return toast("请先分析生成日报", true);
  $("pushBtn").disabled = true;
  $("rejectBtn").disabled = true;
  $("pushStatus").textContent = "推送中…";
  try {
    let r;
    if (currentThreadId) {
      // HITL 单图：resume 恢复图继续执行 wecom_push
      r = await postJSON("/api/resume", {
        thread_id: currentThreadId,
        decision: "approve",
      });
      const wr = r.wecom_result || {};
      r = { ok: r.wecom_ok, mock: r.wecom_mock, error: wr.error, steps: r.steps };
    } else {
      // 兼容历史报告查看场景（无 thread_id，直接推送）
      r = await postJSON("/api/send-wecom", {
        report_markdown: reportMarkdown,
        analysis_result: currentAnalysis,
      });
    }
    if (r.ok) {
      const msg = r.mock
        ? "未配置 WECOM_WEBHOOK_URL，已模拟推送（配置后即可真推）"
        : "已推送到企业微信";
      $("pushStatus").textContent = r.mock ? "🟡 " + msg : "✅ 已推送到企业微信";
      toast(msg);
      setHitlState("done");
      markConfirmDone(!!r.mock);
    } else {
      $("pushStatus").textContent = "❌ 推送失败：" + (r.error || "未知错误");
      toast("推送失败：" + (r.error || "未知错误"), true);
      setHitlState("waiting");
    }
  } catch (e) {
    $("pushStatus").textContent = "❌ 推送失败";
    toast(e.message, true);
    setHitlState("waiting");
  }
};

// ④-B 拒绝推送 → resume reject
$("rejectBtn").onclick = async () => {
  if (!reportMarkdown) return toast("请先分析生成日报", true);
  $("pushBtn").disabled = true;
  $("rejectBtn").disabled = true;
  $("pushStatus").textContent = "处理中…";
  try {
    if (currentThreadId) {
      await postJSON("/api/resume", {
        thread_id: currentThreadId,
        decision: "reject",
      });
    }
    $("pushStatus").textContent = "📁 已保存，未推送企业微信";
    toast("已保存报告，跳过推送");
    setHitlState("rejected");
    // 步骤列表追加一条
    const li = document.createElement("li");
    li.className = "step done";
    li.innerHTML = `<span class="ico">📁</span><span class="txt"><b>人工拒绝推送</b> <i>报告已保存，未发送企业微信</i></span>`;
    $("steps").appendChild(li);
  } catch (e) {
    toast(e.message, true);
    setHitlState("waiting");
  }
};

// ④-C 编辑后推送：展开 textarea
$("editBtn").onclick = () => {
  if (!reportMarkdown) return toast("请先分析生成日报", true);
  $("reviseBox").hidden = true;
  $("editArea").value = reportMarkdown;
  $("editBox").hidden = false;
  $("report").hidden = true;
  $("editArea").focus();
};
$("editCancelBtn").onclick = () => {
  $("editBox").hidden = true;
  $("report").hidden = false;
};
$("editSaveBtn").onclick = async () => {
  const edited = $("editArea").value.trim();
  if (!edited) return toast("日报内容不能为空", true);
  if (!currentThreadId) return toast("当前为历史报告，无法走审核恢复", true);
  $("editSaveBtn").disabled = true;
  $("pushStatus").textContent = "推送编辑后的日报中…";
  try {
    const r = await postJSON("/api/resume", {
      thread_id: currentThreadId,
      decision: "edit",
      edited_markdown: edited,
      report_id: currentReportId,
    });
    reportMarkdown = r.report_markdown || edited;
    renderReport(reportMarkdown);
    $("editBox").hidden = true;
    $("report").hidden = false;
    if (r.wecom_ok) {
      const mock = r.wecom_mock;
      $("pushStatus").textContent = mock ? "🟡 已模拟推送（编辑版）" : "✅ 已推送编辑后的日报";
      toast(mock ? "未配置 webhook，已模拟推送编辑版" : "已推送编辑后的日报");
      setHitlState("done");
      markConfirmDone(!!mock);
    } else {
      $("pushStatus").textContent = "❌ 推送失败：" + ((r.wecom_result || {}).error || "未知");
      setHitlState("waiting");
    }
  } catch (e) {
    toast(e.message, true);
    setHitlState("waiting");
  } finally {
    $("editSaveBtn").disabled = false;
  }
};

// ④-D 反馈重写：把意见交回图，report_generation 重写后再次复审
$("reviseBtn").onclick = () => {
  if (!reportMarkdown) return toast("请先分析生成日报", true);
  if (!currentThreadId) return toast("当前为历史报告，无法反馈重写", true);
  $("editBox").hidden = true;
  $("reviseInput").value = "";
  $("reviseBox").hidden = false;
  $("reviseInput").focus();
};
$("reviseCancelBtn").onclick = () => ($("reviseBox").hidden = true);
$("reviseSendBtn").onclick = async () => {
  const feedback = $("reviseInput").value.trim();
  if (!feedback) return toast("请填写修改意见", true);
  $("reviseSendBtn").disabled = true;
  $("pushStatus").textContent = "AI 重写中…";
  try {
    const r = await postJSON("/api/resume", {
      thread_id: currentThreadId,
      decision: "revise",
      feedback,
      report_id: currentReportId,
    });
    reportMarkdown = r.report_markdown || reportMarkdown;
    renderReport(reportMarkdown);
    $("reviseBox").hidden = true;
    // revise 后图再次 interrupt，回到等待复审
    setHitlState("waiting");
    $("pushStatus").textContent = "✏️ 已按意见重写，请复审后再决定";
    toast("已重写日报，请复审");
    const li = document.createElement("li");
    li.className = "step done";
    li.innerHTML = `<span class="ico">🔁</span><span class="txt"><b>人工反馈重写</b> <i>${escHtml(feedback)}</i></span>`;
    $("steps").appendChild(li);
  } catch (e) {
    toast(e.message, true);
    setHitlState("waiting");
  } finally {
    $("reviseSendBtn").disabled = false;
  }
};

// ── 业务规则记忆 ──────────────────────────────────────────────────────────────

let memoryState = { available_fields: [], threshold_defs: [], thresholds: {}, field_overrides: {} };

function fieldOptions(selected) {
  const opts = ['<option value="">（忽略此列）</option>'];
  for (const f of memoryState.available_fields) {
    const sel = f.canonical === selected ? " selected" : "";
    opts.push(`<option value="${f.canonical}"${sel}>${escHtml(f.label)} (${f.canonical})</option>`);
  }
  return opts.join("");
}

async function loadMemory(domain) {
  const q = (domain || currentDomain) ? `?domain=${encodeURIComponent(domain || currentDomain)}` : "";
  try {
    const resp = await fetch(`/api/memory${q}`);
    if (!resp.ok) throw new Error("请求失败");
    memoryState = await resp.json();
    renderThresholdForm();
    renderOverrideList();
  } catch (e) {
    $("overrideList").innerHTML = `<span class="info">记忆加载失败：${e.message}</span>`;
  }
}

function renderThresholdForm() {
  const cur = memoryState.thresholds || {};
  $("thresholdForm").innerHTML = memoryState.threshold_defs.map((d) => `
    <label class="th-row">
      <span class="th-label">${escHtml(d.label)}</span>
      <input type="number" min="1" class="th-input" data-key="${d.key}"
             value="${cur[d.key] ?? ""}" placeholder="默认" />
    </label>`).join("");
}

function renderOverrideList() {
  const ov = memoryState.field_overrides || {};
  const entries = Object.entries(ov);
  if (!entries.length) {
    $("overrideList").innerHTML = `<span class="info">暂无。上传文件后，可在「未识别列」处教数字员工识别。</span>`;
    return;
  }
  $("overrideList").innerHTML = entries.map(([raw, canon]) => {
    const label = (memoryState.available_fields.find((f) => f.canonical === canon) || {}).label || canon;
    return `<div class="override-row">
      <span class="chip">${escHtml(raw)}</span> →
      <span class="chip warn">${escHtml(label)} (${canon})</span>
      <button class="link-del" data-raw="${escHtml(raw)}">删除</button>
    </div>`;
  }).join("");
  $("overrideList").querySelectorAll(".link-del").forEach((b) => {
    b.onclick = () => saveFieldOverride(b.dataset.raw, "");
  });
}

async function saveFieldOverride(rawColumn, canonical) {
  try {
    const r = await postJSON("/api/memory/field-override", {
      raw_column: rawColumn, canonical, domain_name: currentDomain || null,
    });
    memoryState.field_overrides = r.field_overrides;
    renderOverrideList();
    renderTeachUI();   // 同步刷新上传区的「未识别列」教学块
    toast(canonical ? `已记住：${rawColumn} → ${canonical}` : `已删除映射：${rawColumn}`);
  } catch (e) {
    toast(e.message, true);
  }
}

$("saveThresholds").onclick = async () => {
  const payload = {};
  $("thresholdForm").querySelectorAll(".th-input").forEach((inp) => {
    payload[inp.dataset.key] = inp.value === "" ? null : inp.value;
  });
  try {
    const r = await postJSON("/api/memory/thresholds", { thresholds: payload });
    memoryState.thresholds = r.thresholds;
    $("memStatus").textContent = "✅ 已保存，下次分析生效";
    toast("阈值已持久化");
  } catch (e) {
    $("memStatus").textContent = "❌ " + e.message;
    toast(e.message, true);
  }
};

$("refreshMemory").onclick = loadMemory;

// 上传后若有未识别列，渲染「教数字员工识别」下拉
let lastUnrecognized = [];
function renderTeachUI() {
  const box = $("teachBox");
  if (!box) return;
  const learned = memoryState.field_overrides || {};
  const pending = lastUnrecognized.filter((c) => !(String(c).trim().toLowerCase() in learned));
  if (!pending.length) {
    box.hidden = true;
    return;
  }
  box.hidden = false;
  box.innerHTML = `<div class="teach-hint">💡 有未识别列，可教数字员工记住（下次自动识别）：</div>` +
    pending.map((c) => `
      <div class="teach-row">
        <span class="chip">${escHtml(c)}</span> →
        <select class="teach-select" data-raw="${escHtml(c)}">${fieldOptions("")}</select>
        <button class="teach-save" data-raw="${escHtml(c)}">记住</button>
      </div>`).join("");
  box.querySelectorAll(".teach-save").forEach((b) => {
    b.onclick = () => {
      const sel = box.querySelector(`.teach-select[data-raw="${CSS.escape(b.dataset.raw)}"]`);
      if (!sel.value) return toast("请先选择对应的标准字段", true);
      saveFieldOverride(b.dataset.raw, sel.value);
    };
  });
}

// 页面加载拉一次记忆
loadMemory();
