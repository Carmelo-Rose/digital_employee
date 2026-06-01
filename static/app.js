// 前端逻辑：上传 → 分析 → 展示 → 推送。原生 JS，无构建。
const $ = (id) => document.getElementById(id);

let fileId = null;
let reportMarkdown = "";

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

// ① 上传
$("uploadBtn").onclick = async () => {
  const f = $("fileInput").files[0];
  if (!f) return toast("请先选择文件", true);
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
      file_id: fileId, use_llm: useLlm, force_mock: forceMock,
    });
    reportMarkdown = data.report_markdown || "";
    await playSteps(data.steps || []);
    if (reportMarkdown) {
      renderSummary(data.summary);
      renderReport(reportMarkdown);
      $("resultCard").hidden = false;
      $("analyzeStatus").textContent = `✅ 完成（${MODE_LABEL[data.report_mode] || data.report_mode}）`;
      $("resultCard").scrollIntoView({ behavior: "smooth" });
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

// ④ 人工确认 → 推送企业微信
$("pushBtn").onclick = async () => {
  if (!reportMarkdown) return toast("请先分析生成日报", true);
  $("pushBtn").disabled = true;
  $("pushStatus").textContent = "推送中…";
  try {
    const r = await postJSON("/api/send-wecom", { report_markdown: reportMarkdown });
    if (r.ok) {
      const msg = r.mock
        ? "未配置 WECOM_WEBHOOK_URL，已模拟推送（配置后即可真推）"
        : "已推送到企业微信";
      $("pushStatus").textContent = r.mock ? "🟡 " + msg : "✅ 已推送到企业微信";
      toast(msg);
      markConfirmDone(!!r.mock);
    } else {
      $("pushStatus").textContent = "❌ 推送失败：" + (r.error || "未知错误");
      toast("推送失败：" + (r.error || "未知错误"), true);
      $("pushBtn").disabled = false;
    }
  } catch (e) {
    $("pushStatus").textContent = "❌ 推送失败";
    toast(e.message, true);
    $("pushBtn").disabled = false;
  }
};
