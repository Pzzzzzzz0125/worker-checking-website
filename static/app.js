const state = {
  bootstrap: null,
  records: [],
  daily: [],
  dailyDirty: false,
  payroll: null,
  locationDetail: null,
  aiReview: [],
  aiWarnings: [],
  workerMonth: null,
  activeImport: null,
  conflicts: []
};

const $ = (selector, parent = document) => parent.querySelector(selector);
const $$ = (selector, parent = document) => [...parent.querySelectorAll(selector)];

function localISO(day = new Date()) {
  const offset = day.getTimezoneOffset();
  return new Date(day.getTime() - offset * 60000).toISOString().slice(0, 10);
}

function escapeHTML(value = "") {
  return String(value).replace(/[&<>"']/g, char => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;"
  }[char]));
}

function initials(name) {
  return name.split(/\s+/).slice(0, 2).map(part => part[0]).join("").toUpperCase();
}

function displayDate(value, options = {}) {
  if (!value) return "—";
  const day = new Date(`${value}T12:00:00`);
  return new Intl.DateTimeFormat("en-US", {
    month: "short", day: "numeric", ...(options.year ? { year: "numeric" } : {})
  }).format(day);
}

function number(value, digits = 1) {
  const numeric = Number(value || 0);
  return numeric.toLocaleString(undefined, {
    minimumFractionDigits: Number.isInteger(numeric) ? 0 : digits,
    maximumFractionDigits: digits
  });
}

function compactNumber(value) {
  return Number(value || 0).toFixed(2).replace(/\.00$/, "").replace(/(\.\d)0$/, "$1");
}

function parseNormalizedLocations(value) {
  const raw = String(value || "");
  const overtimeMatch = raw.match(/(?:^|,)\s*(?:ot|overtime)\s*(\d+(?:\.\d+)?)\s*h?/i);
  const extraMatch = raw.match(/(?:^|,)\s*(?:ex|extra)\s*\$?\s*(\d+(?:\.\d+)?)/i);
  const locationText = raw
    .replace(/(?:^|,)\s*(?:ot|overtime)\s*\d+(?:\.\d+)?\s*h?/ig, "")
    .replace(/(?:^|,)\s*(?:ex|extra)\s*\$?\s*\d+(?:\.\d+)?/ig, "")
    .replace(/^\s*,|,\s*$/g, "")
    .trim();
  const locations = locationText.split(";").map(part => part.trim()).filter(Boolean).map(part => {
    const match = part.match(/^(.*?)\(\s*(\d+(?:\.\d+)?)\s*(?:h(?:ou)?r?s?)?\s*\)$/i);
    return match
      ? { name: match[1].trim(), hours: Number(match[2]) }
      : { name: part, hours: null };
  }).filter(item => item.name);
  const explicit = locations.filter(item => item.hours != null).length;
  let error = explicit > 0 && explicit < locations.length
    ? "Give hours for every location, or leave hours blank for every location."
    : "";
  if (!error && /[\/+]/.test(locationText)) {
    error = "Use a semicolon (;) between locations; slash and plus are not location separators.";
  }
  if (!error && locationText.includes(",")) {
    error = "Use semicolons between locations. Commas are reserved for OT and extra pay.";
  }
  return {
    locations,
    overtime_hours: overtimeMatch ? Number(overtimeMatch[1]) : null,
    extra_pay: extraMatch ? Number(extraMatch[1]) : null,
    error
  };
}

function locationEditorValue(record) {
  return (record.locations || []).map(item =>
    `${item.name}${item.hours != null ? `(${compactNumber(item.hours)})` : ""}`
  ).join(";");
}

function derivedOvertime(record) {
  if (record.status !== "worked") return 0;
  const locations = record.locations || [];
  const explicit = locations.length && locations.every(item => item.hours != null);
  const regular = explicit
    ? locations.reduce((sum, item) => sum + Number(item.hours || 0), 0)
    : Math.min(Number(record.total_hours || 0), 8);
  return Math.max(Number(record.total_hours || 0) - regular, 0);
}

function normalizedWorkCell(record) {
  if (record.status === "off") return "off";
  if (record.status !== "worked" || !(record.locations || []).length) return "—";
  const total = Number(record.total_hours || 0);
  const locations = record.locations || [];
  const explicit = locations.filter(item => item.hours != null).length;
  if (explicit > 0 && explicit < locations.length) return "Fix the location-hour split";
  let regular = 8;
  let parts;
  if (explicit === locations.length) {
    regular = locations.reduce((sum, item) => sum + Number(item.hours || 0), 0);
    parts = locations.map(item => `${item.name}(${compactNumber(item.hours)})`);
  } else if (total < 8) {
    regular = total;
    const share = Math.round((regular / locations.length) * 100) / 100;
    const allocations = locations.map((_, index) =>
      index === locations.length - 1
        ? Math.round((regular - share * (locations.length - 1)) * 100) / 100
        : share
    );
    parts = locations.map((item, index) => `${item.name}(${compactNumber(allocations[index])})`);
  } else {
    parts = locations.map(item => item.name);
  }
  let value = parts.join(";");
  const overtime = Math.max(total - regular, 0);
  if (overtime) value += `, ot ${compactNumber(overtime)}h`;
  if (Number(record.extra_pay || 0)) value += `, ex $${compactNumber(record.extra_pay)}`;
  return value;
}

function locationValidationError(record) {
  if (record.location_error) return record.location_error;
  const locations = record.locations || [];
  const explicit = locations.filter(item => item.hours != null).length;
  return explicit > 0 && explicit < locations.length
    ? "Give hours for every location, or leave hours blank for every location."
    : "";
}

function costCenterDisplay(center) {
  if (!center?.id || !center?.name) return "";
  return `${center.name} · ${center.id}`;
}

function resolveCostCenter(value) {
  const query = String(value || "").trim().toLowerCase();
  if (!query) return null;
  return state.bootstrap.cost_centers.find(center => costCenterDisplay(center).toLowerCase() === query)
    || state.bootstrap.cost_centers.find(center => center.id.toLowerCase() === query);
}

function recordCostCenters(record) {
  if (!Array.isArray(record.cost_centers)) {
    record.cost_centers = record.cost_center_id && record.cost_center_name
      ? [{ id: record.cost_center_id, name: record.cost_center_name }]
      : [];
  }
  return record.cost_centers;
}

function addRecordCostCenter(record, value) {
  const center = resolveCostCenter(value);
  if (!center) return false;
  const centers = recordCostCenters(record);
  if (!centers.some(item => item.id === center.id)) centers.push({ ...center });
  return true;
}

function renderCostCenterPicker(record, fieldAttribute, disabled) {
  const chips = recordCostCenters(record).map((center, index) => `
    <span class="cost-center-chip">${escapeHTML(costCenterDisplay(center))}<button type="button" data-remove-cost-center="${index}" aria-label="Remove ${escapeHTML(center.name)}" ${disabled ? "disabled" : ""}>×</button></span>
  `).join("");
  return `<div class="cost-center-picker ${disabled ? "disabled" : ""}">
    <div class="cost-center-chips">${chips}</div>
    <input ${fieldAttribute}="cost_center_add" list="costCenterSuggestions" placeholder="Search and select another cost center" autocomplete="off" ${disabled ? "disabled" : ""}>
  </div>`;
}

async function api(path, options = {}) {
  const response = await fetch(path, options);
  const type = response.headers.get("content-type") || "";
  const body = type.includes("application/json") ? await response.json() : await response.text();
  if (!response.ok) throw new Error(body.error || body || "Request failed");
  return body;
}

function toast(message, kind = "") {
  const node = document.createElement("div");
  node.className = `toast ${kind}`;
  node.textContent = message;
  $("#toasts").append(node);
  setTimeout(() => node.remove(), 3800);
}

function setLoading(element, loading) {
  element.classList.toggle("loading", loading);
  if ("disabled" in element) element.disabled = loading;
}

const viewMeta = {
  overview: ["WORKFORCE OVERVIEW", "Hours at a glance"],
  payroll: ["HALF-MONTH PAYROLL", "Payroll check"],
  locations: ["LOCATION HISTORY", "Location check"],
  ai: ["GEMINI ASSISTED ENTRY", "AI text entry"],
  daily: ["DAILY WORK LOG", "Record a work day"],
  worker: ["WORKER MONTH LOG", "Worker entry"],
  transfer: ["WORKBOOK TOOLS", "Import & export"],
  review: ["CONFIRMATION QUEUE", "Needs your review"]
};

async function navigate(view) {
  $$(".nav-item").forEach(item => item.classList.toggle("active", item.dataset.view === view));
  $$(".view").forEach(item => item.classList.toggle("active", item.id === `${view}View`));
  $("#eyebrow").textContent = viewMeta[view][0];
  $("#pageTitle").textContent = viewMeta[view][1];
  $(".sidebar").classList.remove("open");
  if (view === "daily") await loadDaily();
  if (view === "worker" && state.workerMonth) renderWorkerMonth();
  if (view === "payroll") await loadPayroll();
  if (view === "locations" && state.locationDetail) renderLocationDetail();
  if (view === "transfer") await loadImports();
  if (view === "review") await loadReview();
}

function setPreset(kind) {
  const today = new Date(`${localISO()}T12:00:00`);
  let start = new Date(today);
  if (kind === "pay1") {
    start = new Date(today.getFullYear(), today.getMonth(), 1, 12);
    today.setDate(15);
  }
  else if (kind === "pay2") {
    start = new Date(today.getFullYear(), today.getMonth(), 16, 12);
    today.setDate(new Date(today.getFullYear(), today.getMonth() + 1, 0).getDate());
  }
  else if (kind === "month") start = new Date(today.getFullYear(), today.getMonth(), 1, 12);
  else if (kind === "year") start = new Date(today.getFullYear(), 0, 1, 12);
  else start.setDate(start.getDate() - Number(kind) + 1);
  $("#rangeFrom").value = localISO(start);
  $("#rangeTo").value = localISO(today);
}

async function bootstrap() {
  state.bootstrap = await api("/api/bootstrap");
  $("#reviewBadge").textContent = state.bootstrap.review_count;
  $("#lastRecorded").textContent = displayDate(state.bootstrap.last_recorded_date, { year: true });
  $("#importYear").value = state.bootstrap.workbook_year;
  $("#workerSuggestions").innerHTML = state.bootstrap.workers.map(worker =>
    `<option value="${escapeHTML(worker.name)}"></option>`
  ).join("");
  $("#costCenterSuggestions").innerHTML = state.bootstrap.cost_centers.map(center =>
    `<option value="${escapeHTML(costCenterDisplay(center))}"></option>`
  ).join("");
  $("#locationSuggestions").innerHTML = state.bootstrap.locations.map(location =>
    `<option value="${escapeHTML(location)}"></option>`
  ).join("");

  const today = localISO();
  $("#dailyDate").value = today;
  if (!$("#workerMonth").value) $("#workerMonth").value = today.slice(0, 7);
  $("#payrollMonth").value = today.slice(0, 7);
  if (!$("#aiEntryYear").value) $("#aiEntryYear").value = today.slice(0, 4);
  if (!$("#locationFrom").value) $("#locationFrom").value = `${today.slice(0, 4)}-01-01`;
  if (!$("#locationTo").value) $("#locationTo").value = today;
  const currentHalf = Number(today.slice(8, 10)) <= 15 ? "1" : "2";
  $$("[data-half]").forEach(button => button.classList.toggle("active", button.dataset.half === currentHalf));
  $("#exportFrom").value = `${state.bootstrap.workbook_year}-01-01`;
  $("#exportTo").value = today;
  updateAIAnalyzeState();
  if (!state.bootstrap.ai_configured) {
    $("#analyzeWithAI").title = "Gemini API key is not configured";
  }
  setPreset("month");
  await loadSummary();
}

async function loadSummary() {
  const button = $("#applyFilter");
  setLoading(button, true);
  try {
    const workerQuery = $("#workerFilter").value.trim().toLowerCase();
    const matchingWorker = workerQuery
      ? state.bootstrap.workers.find(worker =>
          worker.name.toLowerCase() === workerQuery
        ) || state.bootstrap.workers.find(worker =>
          worker.name.toLowerCase().includes(workerQuery)
        )
      : null;
    if (workerQuery && !matchingWorker) {
      toast(`No worker matches “${$("#workerFilter").value.trim()}”.`, "error");
      return;
    }
    const params = new URLSearchParams({
      from: $("#rangeFrom").value,
      to: $("#rangeTo").value
    });
    if (matchingWorker) params.set("worker_id", matchingWorker.id);
    const data = await api(`/api/summary?${params}`);
    state.records = data.records;
    $("#totalHours").textContent = number(data.totals.hours);
    $("#activeWorkers").textContent = number(data.totals.active_workers, 0);
    $("#workedDays").textContent = number(data.totals.worked_days, 0);
    $("#extraPay").textContent = `$${number(data.totals.extra_pay)}`;
    renderChart(data.daily);
    renderSnapshot(data);
    renderRecords();
  } catch (error) {
    toast(error.message, "error");
  } finally {
    setLoading(button, false);
  }
}

function renderChart(daily) {
  const chart = $("#hoursChart");
  if (!daily.length) {
    chart.innerHTML = `<div class="empty-state small"><p>No records in this range.</p></div>`;
    return;
  }
  const max = Math.max(...daily.map(item => Number(item.hours)), 1);
  chart.innerHTML = daily.map(item => {
    const height = Math.max(3, Number(item.hours) / max * 100);
    return `<div class="bar" style="--height:${height}%" data-tip="${displayDate(item.date)} · ${number(item.hours)} hrs"></div>`;
  }).join("");
}

function renderSnapshot(data) {
  const worked = Number(data.totals.worked_days || 0);
  const off = Number(data.totals.off_days || 0);
  const total = worked + off || 1;
  const hours = Number(data.totals.hours || 0);
  $("#snapshotWorked").textContent = `${worked} ${worked === 1 ? "day" : "days"}`;
  $("#snapshotOff").textContent = `${off} ${off === 1 ? "day" : "days"}`;
  $("#averageHours").innerHTML = `${number(worked ? hours / worked : 0)}<small>avg hrs</small>`;
  $("#workDonut").style.setProperty("--pct", `${worked / total * 100}%`);
  $("#snapshotTitle").textContent = `${displayDate(data.range.from, { year: true })} – ${displayDate(data.range.to, { year: true })}`;
}

function renderRecords() {
  const query = $("#recordSearch").value.trim().toLowerCase();
  const records = state.records.filter(item =>
    !query || [item.worker_name, item.locations, (item.cost_centers || []).map(costCenterDisplay).join(" "), item.original_text, item.notes, item.work_date]
      .some(value => String(value || "").toLowerCase().includes(query))
  );
  $("#recordsEmpty").hidden = records.length > 0;
  $("#recordsBody").innerHTML = records.map(item => `
    <tr>
      <td>${displayDate(item.work_date, { year: true })}</td>
      <td><span class="worker-cell"><i class="avatar">${initials(item.worker_name)}</i>${escapeHTML(item.worker_name)}</span></td>
      <td><span class="status-pill ${item.status}">${item.status === "worked" ? "Worked" : item.status === "off" ? "Off" : "Review"}</span></td>
      <td>${escapeHTML(item.locations || "—")}</td>
      <td>${item.status === "worked" ? `${escapeHTML(item.start_time || "08:30")}–${escapeHTML(item.end_time || "16:30")}` : "—"}</td>
      <td>${item.status === "worked" ? escapeHTML((item.cost_centers || []).map(costCenterDisplay).join(" / ") || "—") : "—"}</td>
      <td class="hours-cell">${item.total_hours == null ? "—" : number(item.total_hours)}</td>
      <td class="original-cell" title="${escapeHTML(item.original_text)}">${escapeHTML(item.original_text || "—")}</td>
    </tr>
  `).join("");
}

async function loadPayroll() {
  const month = $("#payrollMonth").value || localISO().slice(0, 7);
  const half = $(".payroll-half button.active")?.dataset.half || "1";
  const card = $(".payroll-card");
  card.classList.add("loading");
  try {
    state.payroll = await api(`/api/payroll?month=${encodeURIComponent(month)}&half=${half}`);
    const data = state.payroll;
    $("#payrollHours").textContent = number(data.totals.hours);
    $("#payrollWorkers").textContent = number(data.totals.workers, 0);
    $("#payrollChecked").textContent = `${data.totals.checked} / ${data.workers.length}`;
    const label = `${displayDate(data.period.from, { year: true })} – ${displayDate(data.period.to, { year: true })}`;
    $("#payrollPeriodLabel").textContent = label;
    $("#payrollTableTitle").textContent = label;
    $("#payrollWorkerDetail").hidden = true;
    renderPayroll();
  } catch (error) {
    toast(error.message, "error");
  } finally {
    card.classList.remove("loading");
  }
}

function renderPayroll() {
  if (!state.payroll) return;
  const search = $("#payrollWorkerSearch").value.trim().toLowerCase();
  const workers = state.payroll.workers.filter(worker =>
    !search || worker.worker_name.toLowerCase().includes(search)
  );
  $("#payrollEmpty").hidden = workers.length > 0;
  $("#payrollBody").innerHTML = workers.map(worker => `
    <tr class="payroll-worker-row ${worker.checked ? "checked" : ""}" data-payroll-worker="${worker.worker_id}" tabindex="0" title="Click for location and cost-center details">
      <td><input class="pay-check" type="checkbox" data-pay-check ${worker.checked ? "checked" : ""} aria-label="Mark ${escapeHTML(worker.worker_name)} checked"></td>
      <td><span class="worker-cell"><i class="avatar">${initials(worker.worker_name)}</i>${escapeHTML(worker.worker_name)}</span></td>
      <td><span class="priority-hours">${number(worker.hours)}<small>hrs</small></span></td>
      <td>${number(worker.overtime_hours)}</td>
      <td><strong>${worker.worked_days}</strong><div class="pay-detail">${worker.off_days} off</div></td>
      <td>$${number(worker.extra_pay)}</td>
    </tr>
  `).join("");
}

async function loadPayrollWorkerDetail(workerId) {
  if (!state.payroll) return;
  const card = $("#payrollWorkerDetail");
  card.hidden = false;
  card.classList.add("loading");
  try {
    const params = new URLSearchParams({
      worker_id: workerId,
      month: state.payroll.period.month,
      half: state.payroll.period.half
    });
    const data = await api(`/api/payroll/worker-detail?${params}`);
    $("#payrollDetailTitle").textContent = data.worker.name;
    $("#payrollDetailPeriod").textContent = `${displayDate(data.period.from, { year: true })} – ${displayDate(data.period.to, { year: true })}`;
    $("#payrollDetailSummary").innerHTML = `<strong>${number(data.totals.hours)} hours</strong><span>${data.totals.days} worked ${data.totals.days === 1 ? "day" : "days"}</span>`;
    $("#payrollLocationDetailEmpty").hidden = data.locations.length > 0;
    $("#payrollLocationDetailBody").innerHTML = data.locations.map(item => `
      <tr><td><strong>${escapeHTML(item.name)}</strong></td><td class="hours-cell">${number(item.hours, 2)}</td><td>${item.days}</td><td>${displayDate(item.first_date, { year: true })} – ${displayDate(item.last_date, { year: true })}</td></tr>
    `).join("");
    $("#payrollCostCenterDetailEmpty").hidden = data.cost_centers.length > 0;
    $("#payrollCostCenterDetailBody").innerHTML = data.cost_centers.map(item => `
      <tr><td><strong>${escapeHTML(item.name)}</strong><small>${escapeHTML(item.id)}</small></td><td class="hours-cell">${number(item.hours, 2)}</td><td>${item.days}</td><td>${item.worker_count}</td></tr>
    `).join("");
    card.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) {
    card.hidden = true;
    toast(error.message, "error");
  } finally {
    card.classList.remove("loading");
  }
}

function resolveLocation(value) {
  const query = String(value || "").trim().toLowerCase();
  if (!query) return "";
  return state.bootstrap.locations.find(location => location.toLowerCase() === query)
    || state.bootstrap.locations.find(location => location.toLowerCase().includes(query))
    || "";
}

async function loadLocationDetail() {
  const location = resolveLocation($("#locationSearch").value);
  if (!location) {
    toast("Choose a location from the suggestions.", "error");
    return;
  }
  const button = $("#loadLocationDetail");
  setLoading(button, true);
  try {
    const params = new URLSearchParams({
      location,
      from: $("#locationFrom").value,
      to: $("#locationTo").value
    });
    state.locationDetail = await api(`/api/location-detail?${params}`);
    $("#locationSearch").value = state.locationDetail.location;
    renderLocationDetail();
  } catch (error) {
    toast(error.message, "error");
  } finally {
    setLoading(button, false);
  }
}

function renderLocationDetail() {
  const data = state.locationDetail;
  if (!data) return;
  $("#locationStats").hidden = false;
  $("#locationResults").hidden = false;
  $("#locationWorkerCount").textContent = number(data.totals.workers, 0);
  $("#locationHours").textContent = number(data.totals.hours, 2);
  $("#locationDays").textContent = number(data.totals.days, 0);
  $("#locationDateRange").textContent = data.totals.first_date
    ? `${displayDate(data.totals.first_date, { year: true })} – ${displayDate(data.totals.last_date, { year: true })}`
    : "—";
  $("#locationResultTitle").textContent = data.location;
  $("#locationResultRange").textContent = `${displayDate(data.range.from, { year: true })} – ${displayDate(data.range.to, { year: true })}`;
  $("#locationWorkersEmpty").hidden = data.workers.length > 0;
  $("#locationWorkersBody").innerHTML = data.workers.map(worker => `
    <tr>
      <td><span class="worker-cell"><i class="avatar">${initials(worker.worker_name)}</i>${escapeHTML(worker.worker_name)}</span></td>
      <td><span class="priority-hours">${number(worker.hours, 2)}<small>hrs</small></span></td>
      <td>${worker.days}</td>
      <td>${displayDate(worker.first_date, { year: true })}</td>
      <td>${displayDate(worker.last_date, { year: true })}</td>
    </tr>
  `).join("");
}

function splitReviewValues(value) {
  return String(value || "").split(/\s*[;|]+\s*/).map(item => item.trim()).filter(Boolean);
}

async function analyzeAIText() {
  const text = $("#aiSourceText").value.trim();
  if (!text) {
    toast("Paste work information first.", "error");
    return;
  }
  if (!$("#aiConsent").checked) {
    toast("Confirm the Gemini data-sharing notice before analyzing.", "error");
    return;
  }
  const button = $("#analyzeWithAI");
  setLoading(button, true);
  button.textContent = "Gemini is reading…";
  try {
    const result = await api("/api/ai/parse", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, year: Number($("#aiEntryYear").value), consent: true })
    });
    state.aiWarnings = result.warnings || [];
    state.aiReview = result.records.map(record => ({
      ...record,
      locations: [...(record.locations || [])],
      cost_centers: [...(record.cost_centers || [])],
      cost_center_text: record.cost_center_text || (record.cost_centers || []).map(costCenterDisplay).join(" ; "),
      selected: Boolean(record.ready && record.confidence !== "low"),
      saved: false
    }));
    $("#aiReviewCard").hidden = false;
    $("#aiReviewSummary").textContent = result.summary || `${state.aiReview.length} records extracted by Gemini.`;
    renderAIReview();
    $("#aiReviewCard").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) {
    toast(error.message, "error");
  } finally {
    setLoading(button, false);
    button.textContent = "Analyze with Gemini";
    updateAIAnalyzeState();
  }
}

function updateAIAnalyzeState() {
  if (!state.bootstrap) return;
  $("#analyzeWithAI").disabled = !state.bootstrap.ai_configured || !$("#aiConsent").checked;
}

function renderAIReview() {
  const warnings = state.aiWarnings.filter(Boolean);
  $("#aiGlobalWarnings").hidden = !warnings.length;
  $("#aiGlobalWarnings").innerHTML = warnings.map(item => `<p>${escapeHTML(item)}</p>`).join("");
  $("#aiReviewList").innerHTML = state.aiReview.length ? state.aiReview.map((record, index) => {
    const issues = record.issues || [];
    const confidence = record.confidence || "low";
    return `
      <article class="ai-review-item ${record.saved ? "saved" : ""} ${issues.length ? "has-issues" : ""}" data-ai-index="${index}">
        <div class="ai-review-top">
          <label class="ai-record-check"><input type="checkbox" data-ai-select ${record.selected ? "checked" : ""} ${record.saved ? "disabled" : ""}><span>${record.saved ? "Saved" : "Include"}</span></label>
          <div class="ai-source"><small>Source</small><span>${escapeHTML(record.source_excerpt || "No source excerpt")}</span></div>
          <span class="confidence-badge ${confidence}">${escapeHTML(confidence)} confidence</span>
          ${record.existing ? `<span class="existing-badge">Updates existing day</span>` : ""}
        </div>
        <div class="ai-fields-grid">
          <label class="field"><span>Date</span><input type="date" data-ai-field="date" value="${escapeHTML(record.date)}" ${record.saved ? "disabled" : ""}></label>
          <label class="field"><span>Worker</span><input type="search" data-ai-field="worker_name" list="workerSuggestions" value="${escapeHTML(record.worker_name)}" autocomplete="off" ${record.saved ? "disabled" : ""}></label>
          <label class="field"><span>Status</span><select data-ai-field="status" ${record.saved ? "disabled" : ""}><option value="worked" ${record.status === "worked" ? "selected" : ""}>Worked</option><option value="off" ${record.status === "off" ? "selected" : ""}>Off</option></select></label>
          <label class="field ai-location-field"><span>Location(s) · separate with ;</span><input data-ai-field="locations" value="${escapeHTML(record.locations.join(" ; "))}" placeholder="444 Pocatello ; 111 Main St" ${record.saved ? "disabled" : ""}></label>
          <label class="field"><span>Total hours</span><input type="number" min="0" max="24" step=".25" data-ai-field="total_hours" value="${number(record.total_hours, 2)}" ${record.saved ? "disabled" : ""}></label>
          <label class="field"><span>Overtime</span><input type="number" min="0" max="16" step=".25" data-ai-field="overtime_hours" value="${number(record.overtime_hours, 2)}" ${record.saved ? "disabled" : ""}></label>
          <label class="field"><span>Extra $</span><input type="number" min="0" step="1" data-ai-field="extra_pay" value="${number(record.extra_pay, 2)}" ${record.saved ? "disabled" : ""}></label>
          <label class="field"><span>Start</span><input type="time" data-ai-field="start_time" value="${escapeHTML(record.start_time)}" ${record.saved ? "disabled" : ""}></label>
          <label class="field"><span>End</span><input type="time" data-ai-field="end_time" value="${escapeHTML(record.end_time)}" ${record.saved ? "disabled" : ""}></label>
          <label class="field ai-cost-field"><span>Cost center(s) · separate with ;</span><input data-ai-field="cost_center_text" list="costCenterSuggestions" value="${escapeHTML(record.cost_center_text)}" placeholder="Optional" ${record.saved ? "disabled" : ""}></label>
          <label class="field ai-notes-field"><span>Notes</span><input data-ai-field="notes" value="${escapeHTML(record.notes)}" placeholder="Optional" ${record.saved ? "disabled" : ""}></label>
        </div>
        ${issues.length ? `<div class="ai-issues">${issues.map(issue => `<span>${escapeHTML(issue)}</span>`).join("")}</div>` : ""}
      </article>`;
  }).join("") : `<div class="empty-state"><h3>No records extracted</h3><p>Adjust the pasted text and analyze it again.</p></div>`;
  updateAISelectionLabel();
}

function updateAISelectionLabel() {
  const count = state.aiReview.filter(record => record.selected && !record.saved).length;
  $("#aiSelectedLabel").textContent = count
    ? `${count} selected ${count === 1 ? "record" : "records"} ready for confirmation`
    : "No records selected";
  $("#confirmAIRecords").disabled = count === 0;
}

async function confirmAIRecords() {
  const selected = state.aiReview.filter(record => record.selected && !record.saved);
  if (!selected.length) return;
  const button = $("#confirmAIRecords");
  setLoading(button, true);
  try {
    const records = selected.map(record => ({
      worker_name: record.worker_name,
      date: record.date,
      status: record.status,
      locations: record.locations,
      regular_hours: record.regular_hours,
      overtime_hours: record.overtime_hours,
      total_hours: record.total_hours,
      extra_pay: record.extra_pay,
      start_time: record.start_time,
      end_time: record.end_time,
      cost_centers: splitReviewValues(record.cost_center_text),
      notes: record.notes
    }));
    const result = await api("/api/ai/apply", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ records })
    });
    selected.forEach(record => {
      record.saved = true;
      record.selected = false;
    });
    renderAIReview();
    toast(`Confirmed and saved ${result.saved} AI ${result.saved === 1 ? "record" : "records"}.`);
    await bootstrap();
  } catch (error) {
    toast(error.message, "error");
  } finally {
    setLoading(button, false);
    updateAISelectionLabel();
  }
}

function stepPayrollMonth(amount) {
  const value = $("#payrollMonth").value || localISO().slice(0, 7);
  const [year, month] = value.split("-").map(Number);
  const next = new Date(year, month - 1 + amount, 1, 12);
  $("#payrollMonth").value = `${next.getFullYear()}-${String(next.getMonth() + 1).padStart(2, "0")}`;
  loadPayroll();
}

async function togglePayrollCheck(row, input) {
  try {
    await api("/api/payroll/check", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        worker_id: Number(row.dataset.payrollWorker),
        period_start: state.payroll.period.from,
        checked: input.checked
      })
    });
    row.classList.toggle("checked", input.checked);
    const worker = state.payroll.workers.find(item => item.worker_id === Number(row.dataset.payrollWorker));
    if (worker) worker.checked = input.checked ? 1 : 0;
    state.payroll.totals.checked = state.payroll.workers.filter(item => item.checked).length;
    $("#payrollChecked").textContent = `${state.payroll.totals.checked} / ${state.payroll.workers.length}`;
  } catch (error) {
    input.checked = !input.checked;
    toast(error.message, "error");
  }
}

function resolveWorkerName(value) {
  const query = value.trim().toLowerCase();
  if (!query) return null;
  return state.bootstrap.workers.find(worker => worker.name.toLowerCase() === query)
    || state.bootstrap.workers.find(worker => worker.name.toLowerCase().includes(query));
}

function workerMonthDraftKey() {
  if (!state.workerMonth) return "";
  return `fieldledger-worker-month:${state.workerMonth.worker.id}:${state.workerMonth.month}`;
}

function syncWorkerMonthDraft() {
  if (!state.workerMonth) return;
  const drafts = state.workerMonth.days.filter(day => day.dirty).map(day => ({
    work_date: day.work_date,
    status: day.status,
    total_hours: day.total_hours,
    overtime_hours: day.overtime_hours,
    extra_pay: day.extra_pay,
    start_time: day.start_time,
    end_time: day.end_time,
    cost_centers: recordCostCenters(day).map(center => ({ ...center })),
    notes: day.notes,
    locations: day.locations
  }));
  try {
    if (drafts.length) localStorage.setItem(workerMonthDraftKey(), JSON.stringify(drafts));
    else localStorage.removeItem(workerMonthDraftKey());
  } catch {}
  updateWorkerMonthSummary();
}

async function loadWorkerMonth() {
  const worker = resolveWorkerName($("#workerMonthSearch").value);
  if (!worker) {
    toast("Choose a worker from the name suggestions.", "error");
    return;
  }
  const month = $("#workerMonth").value || localISO().slice(0, 7);
  const button = $("#loadWorkerMonth");
  setLoading(button, true);
  try {
    const data = await api(`/api/worker-month?worker_id=${worker.id}&month=${encodeURIComponent(month)}`);
    data.days = data.days.map(day => ({
      ...day,
      worker_id: worker.id,
      start_time: day.start_time || "08:30",
      end_time: day.end_time || "16:30",
      status: day.status || "worked",
      cost_centers: (day.cost_centers || []).map(center => ({ ...center })),
      overtime_hours: derivedOvertime(day),
      dirty: false
    }));
    state.workerMonth = data;
    try {
      const drafts = JSON.parse(localStorage.getItem(workerMonthDraftKey()) || "[]");
      drafts.forEach(draft => {
        const day = data.days.find(item => item.work_date === draft.work_date);
        if (day) {
          Object.assign(day, draft, { dirty: true });
          day.status = day.status || "worked";
          if (day.status === "worked") day.total_hours = day.total_hours || 8;
          if (day.overtime_hours == null) day.overtime_hours = derivedOvertime(day);
        }
      });
    } catch {}
    $("#workerMonthSearch").value = data.worker.name;
    renderWorkerMonth();
  } catch (error) {
    toast(error.message, "error");
  } finally {
    setLoading(button, false);
  }
}

function renderWorkerMonth() {
  const data = state.workerMonth;
  if (!data) return;
  $("#workerMonthPrompt").hidden = true;
  $("#workerMonthTable").hidden = false;
  $("#workerMonthSummary").hidden = false;
  $("#workerMonthSaveBar").hidden = false;
  $("#workerMonthName").textContent = data.worker.name;
  $("#workerMonthBody").innerHTML = data.days.map((day, index) => {
    const worked = day.status === "worked";
    const weekday = new Date(`${day.work_date}T12:00:00`).toLocaleDateString("en-US", { weekday: "short" });
    const weekend = ["Sat", "Sun"].includes(weekday);
    const location = locationEditorValue(day);
    return `
      <tr data-month-index="${index}" class="${weekend ? "weekend " : ""}${day.status === "off" ? "off-row" : ""}">
        <td class="date-label"><strong>${displayDate(day.work_date)}</strong><span>${weekday}</span></td>
        <td><select data-month-field="status"><option value="" ${!day.status ? "selected" : ""}>Not set</option><option value="worked" ${worked ? "selected" : ""}>Worked</option><option value="off" ${day.status === "off" ? "selected" : ""}>Off</option></select></td>
        <td><input class="month-location" data-month-field="location" value="${escapeHTML(location)}" placeholder="444;111 or 432(3);1151(5)" title="Use semicolons between locations. Put optional hours in parentheses." ${worked ? "" : "disabled"}><code class="month-normalized">${escapeHTML(normalizedWorkCell(day))}</code></td>
        <td><input class="month-time" data-month-field="start_time" type="time" value="${escapeHTML(day.start_time)}" ${worked ? "" : "disabled"}></td>
        <td><input class="month-time" data-month-field="end_time" type="time" value="${escapeHTML(day.end_time)}" ${worked ? "" : "disabled"}></td>
        <td class="month-cost-center">${renderCostCenterPicker(day, "data-month-field", !worked)}</td>
        <td><input class="month-number" data-month-field="total_hours" type="number" min="0" max="24" step=".25" value="${number(day.total_hours, 2)}" ${worked ? "" : "disabled"}></td>
        <td><input class="month-number" data-month-field="overtime_hours" type="number" min="0" max="16" step=".25" value="${number(day.overtime_hours, 2)}" ${worked ? "" : "disabled"}></td>
        <td><input class="month-number" data-month-field="extra_pay" type="number" min="0" step="1" value="${number(day.extra_pay)}" ${worked ? "" : "disabled"}></td>
        <td><button class="row-save" data-save-month-day ${day.dirty && day.status ? "" : "disabled"}>Save</button></td>
      </tr>`;
  }).join("");
  updateWorkerMonthSummary();
}

function updateWorkerMonthSummary() {
  if (!state.workerMonth) return;
  const worked = state.workerMonth.days.filter(day => day.status === "worked");
  const dirty = state.workerMonth.days.filter(day => day.dirty);
  $("#workerMonthWorked").textContent = worked.length;
  $("#workerMonthHours").textContent = number(worked.reduce((sum, day) => sum + Number(day.total_hours || 0), 0));
  $("#workerMonthUnsaved").textContent = dirty.length;
  $("#workerMonthSaveLabel").textContent = dirty.length
    ? `${dirty.length} edited ${dirty.length === 1 ? "day" : "days"} · draft protected`
    : "No unsaved changes";
}

function workerMonthPayload(day) {
  return { date: day.work_date, ...dailyRecordPayload(day) };
}

async function saveWorkerMonthDays(days, button) {
  const ready = days.filter(day => day.status);
  const missing = ready.find(day => day.status === "worked" && !(day.locations || []).length);
  if (missing) {
    toast(`Enter a location for ${displayDate(missing.work_date)}.`, "error");
    return;
  }
  const invalid = ready.find(day => locationValidationError(day));
  if (invalid) {
    toast(`${displayDate(invalid.work_date)}: ${locationValidationError(invalid)}`, "error");
    return;
  }
  if (!ready.length) return;
  setLoading(button, true);
  try {
    await api("/api/worker-days", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        worker_id: state.workerMonth.worker.id,
        records: ready.map(workerMonthPayload)
      })
    });
    ready.forEach(day => { day.dirty = false; });
    syncWorkerMonthDraft();
    toast(`Saved ${ready.length} ${ready.length === 1 ? "day" : "days"} for ${state.workerMonth.worker.name}.`);
    renderWorkerMonth();
  } catch (error) {
    toast(error.message, "error");
    setLoading(button, false);
  }
}

function stepWorkerMonth(amount) {
  const value = $("#workerMonth").value || localISO().slice(0, 7);
  const [year, month] = value.split("-").map(Number);
  const next = new Date(year, month - 1 + amount, 1, 12);
  $("#workerMonth").value = `${next.getFullYear()}-${String(next.getMonth() + 1).padStart(2, "0")}`;
  if ($("#workerMonthSearch").value) loadWorkerMonth();
}

async function loadDaily() {
  const date = $("#dailyDate").value || localISO();
  const list = $("#dailyList");
  list.classList.add("loading");
  try {
    const data = await api(`/api/day?date=${encodeURIComponent(date)}`);
    state.daily = data.workers.map(worker => ({
      worker_id: worker.worker_id,
      worker_name: worker.worker_name,
      status: worker.status || "worked",
      total_hours: worker.total_hours ?? 8,
      overtime_hours: derivedOvertime({ ...worker, status: worker.status || "worked", total_hours: worker.total_hours ?? 8 }),
      extra_pay: worker.extra_pay || 0,
      start_time: worker.start_time || "08:30",
      end_time: worker.end_time || "16:30",
      cost_centers: (worker.cost_centers || []).map(center => ({ ...center })),
      locations: worker.locations || [],
      notes: worker.notes || "",
      existing: Boolean(worker.day_id),
      dirty: false
    }));
    state.daily.forEach(record => { record.saved = dailyRecordSnapshot(record); });
    const drafts = readDailyDraft(date);
    drafts.forEach(draft => {
      const record = state.daily.find(item => item.worker_id === draft.worker_id);
      if (record) {
        Object.assign(record, draft, { dirty: true });
        record.status = record.status || "worked";
        if (record.status === "worked") record.total_hours = record.total_hours || 8;
        if (record.overtime_hours == null) record.overtime_hours = derivedOvertime(record);
      }
    });
    state.dailyDirty = state.daily.some(item => item.dirty);
    renderDaily();
  } catch (error) {
    toast(error.message, "error");
  } finally {
    list.classList.remove("loading");
  }
}

function dailyLocation(record) {
  return locationEditorValue(record);
}

function dailyDraftKey(dateValue = $("#dailyDate").value) {
  return `fieldledger-daily-draft:${dateValue}`;
}

function readDailyDraft(dateValue) {
  try {
    return JSON.parse(localStorage.getItem(dailyDraftKey(dateValue)) || "[]");
  } catch {
    return [];
  }
}

function copyDailyWorker(record) {
  const copied = {
    source_date: $("#dailyDate").value,
    source_worker: record.worker_name,
    values: dailyRecordSnapshot(record)
  };
  try {
    localStorage.setItem("fieldledger-copied-worker", JSON.stringify(copied));
    toast(`Copied ${record.worker_name}. Click Paste on another worker.`);
  } catch {
    toast("This browser blocked copied-worker storage.", "error");
  }
}

function pasteDailyWorker(record) {
  let copied;
  try {
    copied = JSON.parse(localStorage.getItem("fieldledger-copied-worker") || "null");
  } catch {}
  if (!copied?.values) {
    toast("Copy a worker first.", "error");
    return;
  }
  const values = JSON.parse(JSON.stringify(copied.values));
  Object.assign(record, values, { dirty: true });
  markRecordDirty(record);
  renderDaily();
  toast(`Pasted ${copied.source_worker}'s information to ${record.worker_name}. Review, then save.`);
}

function syncDailyDraft() {
  const drafts = state.daily.filter(item => item.dirty).map(item => ({
    worker_id: item.worker_id,
    status: item.status,
    total_hours: item.total_hours,
    overtime_hours: item.overtime_hours,
    extra_pay: item.extra_pay,
    start_time: item.start_time,
    end_time: item.end_time,
    cost_centers: recordCostCenters(item).map(center => ({ ...center })),
    locations: item.locations,
    notes: item.notes
  }));
  state.dailyDirty = drafts.length > 0;
  try {
    if (drafts.length) localStorage.setItem(dailyDraftKey(), JSON.stringify(drafts));
    else localStorage.removeItem(dailyDraftKey());
  } catch {
    // Database saves still work if private browsing blocks local storage.
  }
  updateDailyTotals();
}

function markRecordDirty(record) {
  record.dirty = true;
  syncDailyDraft();
}

function dailyRecordPayload(item) {
  return {
    worker_id: item.worker_id,
    status: item.status,
    total_hours: item.status === "worked" ? Number(item.total_hours || 8) : 0,
    extra_pay: item.status === "worked" ? Number(item.extra_pay || 0) : 0,
    start_time: item.status === "worked" ? (item.start_time || "08:30") : "",
    end_time: item.status === "worked" ? (item.end_time || "16:30") : "",
    cost_centers: item.status === "worked"
      ? recordCostCenters(item).map(center => ({ id: center.id, name: center.name }))
      : [],
    locations: item.status === "worked"
      ? item.locations.map(location => ({ name: location.name, hours: location.hours }))
      : [],
    notes: item.notes
  };
}

function dailyRecordSnapshot(item) {
  return {
    status: item.status,
    total_hours: item.total_hours,
    overtime_hours: item.overtime_hours,
    extra_pay: item.extra_pay,
    start_time: item.start_time,
    end_time: item.end_time,
    cost_centers: recordCostCenters(item).map(center => ({ ...center })),
    locations: item.locations.map(location => ({ ...location })),
    notes: item.notes
  };
}

function renderDaily() {
  const search = $("#dailyWorkerSearch").value.trim().toLowerCase();
  const visible = state.daily
    .map((record, index) => ({ record, index }))
    .filter(({ record }) =>
      !search ||
      record.worker_name.toLowerCase().includes(search)
    );
  $("#dailyList").innerHTML = visible.length ? visible.map(({ record, index }) => {
    const disabled = record.status !== "worked";
    return `
      <article class="worker-entry" data-index="${index}">
        <div class="worker-identity">
          <i class="avatar">${initials(record.worker_name)}</i>
          <span><strong>${escapeHTML(record.worker_name)}</strong></span>
        </div>
        <div class="segmented" aria-label="Work status">
          <button class="${record.status === "worked" ? "active worked" : ""}" data-status="worked">Worked</button>
          <button class="${record.status === "off" ? "active off" : ""}" data-status="off">Off</button>
        </div>
        <label class="entry-field location-field"><span>Location split *</span><input data-field="location" list="locationSuggestions" value="${escapeHTML(dailyLocation(record))}" placeholder="444;111 or 432(3);1151(5)" title="Use semicolons between locations. Put optional hours in parentheses." ${disabled ? "disabled" : ""}></label>
        <div class="entry-actions">
          <button class="row-save" data-save-worker ${record.dirty && record.status ? "" : "disabled"}>Save</button>
          <button class="row-copy" data-copy-worker>Copy</button>
          <button class="row-copy" data-paste-worker>Paste</button>
          <button class="remove-row" data-clear aria-label="${record.existing ? "Discard unsaved changes" : "Clear this worker"}"><svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6 6 18"/></svg></button>
        </div>
        <div class="entry-details">
          <label class="entry-field"><span>Start time</span><input data-field="start_time" type="time" value="${escapeHTML(record.start_time)}" ${disabled ? "disabled" : ""}></label>
          <label class="entry-field"><span>End time</span><input data-field="end_time" type="time" value="${escapeHTML(record.end_time)}" ${disabled ? "disabled" : ""}></label>
          <div class="entry-field kind-field"><span>Cost centers</span>${renderCostCenterPicker(record, "data-field", disabled)}</div>
          <label class="entry-field"><span>Total hours</span><input data-field="total_hours" type="number" min="0" max="24" step=".25" value="${number(record.total_hours, 2)}" ${disabled ? "disabled" : ""}></label>
          <label class="entry-field"><span>OT hours</span><input data-field="overtime_hours" type="number" min="0" max="16" step=".25" value="${number(record.overtime_hours, 2)}" ${disabled ? "disabled" : ""}></label>
          <label class="entry-field"><span>Extra $</span><input data-field="extra_pay" type="number" min="0" step="1" value="${number(record.extra_pay)}" ${disabled ? "disabled" : ""}></label>
          <label class="entry-field notes-field"><span>Notes</span><input data-field="notes" value="${escapeHTML(record.notes)}" placeholder="Optional" ${disabled ? "disabled" : ""}></label>
          <div class="normalized-preview"><span>Excel cell</span><code>${escapeHTML(normalizedWorkCell(record))}</code></div>
        </div>
      </article>`;
  }).join("") : `
    <div class="card empty-state">
      <div class="empty-icon"><svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/></svg></div>
      <h3>No worker found</h3>
      <p>Try another worker name.</p>
    </div>`;
  updateDailyTotals();
}

function updateDailyTotals() {
  const worked = state.daily.filter(item => item.status === "worked");
  const off = state.daily.filter(item => item.status === "off");
  $("#dailyWorkedCount").textContent = worked.length;
  $("#dailyOffCount").textContent = off.length;
  $("#dailyHoursCount").textContent = number(worked.reduce((sum, item) => sum + Number(item.total_hours || 0), 0));
  const dirtyCount = state.daily.filter(item => item.dirty).length;
  $("#unsavedLabel").textContent = dirtyCount
    ? `${dirtyCount} unsaved ${dirtyCount === 1 ? "worker" : "workers"} · draft protected`
    : "No unsaved changes";
}

async function saveOneDaily(index, button) {
  const record = state.daily[index];
  if (!record.status) {
    toast(`Choose Worked or Off for ${record.worker_name}.`, "error");
    return;
  }
  if (record.status === "worked" && !dailyLocation(record).trim()) {
    toast(`Enter a location for ${record.worker_name}.`, "error");
    return;
  }
  const locationError = locationValidationError(record);
  if (locationError) {
    toast(`${record.worker_name}: ${locationError}`, "error");
    return;
  }
  setLoading(button, true);
  try {
    await api("/api/day", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        date: $("#dailyDate").value,
        records: [dailyRecordPayload(record)]
      })
    });
    record.dirty = false;
    record.existing = true;
    record.saved = dailyRecordSnapshot(record);
    syncDailyDraft();
    toast(`${record.worker_name} saved.`);
    renderDaily();
  } catch (error) {
    toast(error.message, "error");
    setLoading(button, false);
  }
}

async function saveDaily() {
  const records = state.daily.filter(item => item.status);
  const missing = records.find(item => item.status === "worked" && !dailyLocation(item).trim());
  if (missing) {
    toast(`Enter a location for ${missing.worker_name}.`, "error");
    return;
  }
  const invalid = records.find(item => locationValidationError(item));
  if (invalid) {
    toast(`${invalid.worker_name}: ${locationValidationError(invalid)}`, "error");
    return;
  }
  const button = $("#saveDay");
  setLoading(button, true);
  try {
    await api("/api/day", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        date: $("#dailyDate").value,
        records: records.map(dailyRecordPayload)
      })
    });
    const savedDate = $("#dailyDate").value;
    state.daily.forEach(item => { item.dirty = false; });
    syncDailyDraft();
    toast(`Saved ${records.length} records for ${displayDate(savedDate, { year: true })}.`);
    await bootstrap();
    $("#dailyDate").value = savedDate;
    await loadDaily();
  } catch (error) {
    toast(error.message, "error");
  } finally {
    setLoading(button, false);
  }
}

async function loadImports() {
  try {
    const data = await api("/api/imports");
    $("#importHistory").innerHTML = data.imports.length ? data.imports.map(item => `
      <div class="history-row">
        <div><strong>${escapeHTML(item.filename)}</strong><small>${new Date(`${item.created_at}Z`).toLocaleString()}</small></div>
        <span>${item.added_count} added · ${item.changed_count} changed</span>
        <span class="status-pill ${item.status === "applied" ? "worked" : "unknown"}">${escapeHTML(item.status)}</span>
      </div>
    `).join("") : `<div class="empty-state small"><p>No workbook imports yet.</p></div>`;
  } catch (error) {
    toast(error.message, "error");
  }
}

async function analyzeImport() {
  const file = $("#workbookFile").files[0];
  if (!file) {
    toast("Choose an Excel workbook first.", "error");
    return;
  }
  const button = $("#analyzeImport");
  setLoading(button, true);
  const form = new FormData();
  form.append("workbook", file);
  form.append("year", $("#importYear").value);
  try {
    const result = await api("/api/import", { method: "POST", body: form });
    state.activeImport = result.import_id;
    const data = await api(`/api/imports/${result.import_id}/conflicts`);
    state.conflicts = data.conflicts;
    renderConflicts(result);
    await loadImports();
    toast("Workbook compared. Review the differences below.");
  } catch (error) {
    toast(error.message, "error");
  } finally {
    setLoading(button, false);
  }
}

function compactValue(value) {
  if (!value) return "No app record";
  return value.original_text || `${value.status} · ${value.total_hours ?? "?"}h`;
}

function renderConflicts(summary) {
  $("#comparisonCard").hidden = false;
  $("#comparisonSummary").textContent = `${summary.added} new, ${summary.changed} changed, and ${summary.review} uncertain entries.`;
  $("#comparisonList").innerHTML = state.conflicts.length ? state.conflicts.map(item => `
    <label class="comparison-item">
      <input type="checkbox" data-conflict="${item.id}" ${item.action !== "review" ? "checked" : ""}>
      <span class="comparison-person"><strong>${escapeHTML(item.worker_name)}</strong><span>${displayDate(item.work_date, { year: true })}</span></span>
      <span class="comparison-value"><strong>Current app</strong><code>${escapeHTML(compactValue(item.current))}</code></span>
      <span class="change-arrow">→</span>
      <span class="comparison-value"><strong>Uploaded sheet</strong><code>${escapeHTML(compactValue(item.proposed))}</code></span>
      <span class="action-tag ${item.action}">${item.action}</span>
    </label>
  `).join("") : `<div class="empty-state small"><p>The workbook matches the app. No changes found.</p></div>`;
  $("#comparisonCard").scrollIntoView({ behavior: "smooth", block: "start" });
}

async function applyImport() {
  const selected = $$("[data-conflict]:checked").map(input => Number(input.dataset.conflict));
  if (!selected.length) {
    toast("Select at least one change to apply.", "error");
    return;
  }
  const button = $("#applySelected");
  setLoading(button, true);
  try {
    const result = await api(`/api/imports/${state.activeImport}/apply`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ conflict_ids: selected })
    });
    toast(`Applied ${result.applied} workbook changes.`);
    await bootstrap();
    const data = await api(`/api/imports/${state.activeImport}/conflicts`);
    state.conflicts = data.conflicts.filter(item => item.status === "pending");
    renderConflicts({ added: 0, changed: state.conflicts.length, review: state.conflicts.filter(item => item.action === "review").length });
    await loadImports();
  } catch (error) {
    toast(error.message, "error");
  } finally {
    setLoading(button, false);
  }
}

async function loadReview() {
  try {
    const data = await api("/api/review");
    $("#reviewList").innerHTML = data.items.length ? data.items.map(item => `
      <article class="review-item" data-review-id="${item.id}">
        <div class="source-warning"><strong>${escapeHTML(item.worker_name)}</strong><span>${displayDate(item.work_date, { year: true })}</span><code>${escapeHTML(item.original_text || "(blank)")}</code></div>
        <label class="entry-field"><span>Status</span><select data-review="status"><option value="worked" ${item.status === "worked" ? "selected" : ""}>Worked</option><option value="off" ${item.status === "off" ? "selected" : ""}>Off</option></select></label>
        <label class="entry-field"><span>Hours</span><input data-review="hours" type="number" min="0" max="24" step=".5" value="${item.total_hours ?? 8}"></label>
        <label class="entry-field"><span>Extra $</span><input data-review="extra" type="number" min="0" step="1" value="${item.extra_pay || 0}"></label>
        <label class="entry-field"><span>Location</span><input data-review="location" value="${escapeHTML(item.locations || "")}" placeholder="Confirm location"></label>
        <button class="primary-button" data-confirm-review>Confirm</button>
      </article>
    `).join("") : `<div class="empty-state"><div class="empty-icon">✓</div><h3>Everything is confirmed</h3><p>No uncertain source entries remain.</p></div>`;
  } catch (error) {
    toast(error.message, "error");
  }
}

async function confirmReview(card) {
  const status = $('[data-review="status"]', card).value;
  const location = $('[data-review="location"]', card).value.trim();
  if (status === "worked" && !location) {
    toast("Enter the confirmed location.", "error");
    return;
  }
  const button = $("[data-confirm-review]", card);
  setLoading(button, true);
  try {
    await api(`/api/review/${card.dataset.reviewId}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        status,
        total_hours: status === "worked" ? Number($('[data-review="hours"]', card).value || 8) : 0,
        extra_pay: Number($('[data-review="extra"]', card).value || 0),
        locations: status === "worked" ? [{ name: location, hours: null }] : [],
        notes: "Confirmed from review queue"
      })
    });
    toast("Entry confirmed.");
    await bootstrap();
    await loadReview();
  } catch (error) {
    toast(error.message, "error");
  } finally {
    setLoading(button, false);
  }
}

async function addWorker(event) {
  event.preventDefault();
  const name = $("#newWorkerName").value.trim();
  if (!name) return;
  try {
    await api("/api/workers", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name
      })
    });
    $("#workerDialog").close();
    $("#workerForm").reset();
    toast(`${name} was added.`);
    await bootstrap();
    if ($("#dailyView").classList.contains("active")) await loadDaily();
  } catch (error) {
    toast(error.message, "error");
  }
}

function bindEvents() {
  $$(".nav-item").forEach(item => item.addEventListener("click", () => navigate(item.dataset.view)));
  $$("[data-go]").forEach(item => item.addEventListener("click", () => navigate(item.dataset.go)));
  $("#mobileMenu").addEventListener("click", () => $(".sidebar").classList.toggle("open"));
  $("#applyFilter").addEventListener("click", loadSummary);
  $("#workerFilter").addEventListener("change", loadSummary);
  $("#workerFilter").addEventListener("search", loadSummary);
  $("#workerFilter").addEventListener("keydown", event => {
    if (event.key === "Enter") {
      event.preventDefault();
      loadSummary();
    }
  });
  $("#recordSearch").addEventListener("input", renderRecords);
  $("#payrollMonth").addEventListener("change", loadPayroll);
  $$('[data-pay-month]').forEach(button => button.addEventListener("click", () => {
    stepPayrollMonth(Number(button.dataset.payMonth));
  }));
  $("#payrollWorkerSearch").addEventListener("input", renderPayroll);
  $$("[data-half]").forEach(button => button.addEventListener("click", () => {
    $$("[data-half]").forEach(item => item.classList.toggle("active", item === button));
    loadPayroll();
  }));
  $("#payrollBody").addEventListener("change", event => {
    const row = event.target.closest("[data-payroll-worker]");
    if (!row) return;
    if (event.target.matches("[data-pay-check]")) togglePayrollCheck(row, event.target);
  });
  $("#payrollBody").addEventListener("click", event => {
    if (event.target.closest("[data-pay-check]")) return;
    const row = event.target.closest("[data-payroll-worker]");
    if (row) loadPayrollWorkerDetail(Number(row.dataset.payrollWorker));
  });
  $("#payrollBody").addEventListener("keydown", event => {
    if (event.key !== "Enter") return;
    const row = event.target.closest("[data-payroll-worker]");
    if (row) loadPayrollWorkerDetail(Number(row.dataset.payrollWorker));
  });
  $("#closePayrollDetail").addEventListener("click", () => {
    $("#payrollWorkerDetail").hidden = true;
  });
  $("#loadLocationDetail").addEventListener("click", loadLocationDetail);
  $("#locationSearch").addEventListener("keydown", event => {
    if (event.key === "Enter") {
      event.preventDefault();
      loadLocationDetail();
    }
  });
  $("#analyzeWithAI").addEventListener("click", analyzeAIText);
  $("#aiConsent").addEventListener("change", updateAIAnalyzeState);
  $("#selectReadyAI").addEventListener("click", () => {
    state.aiReview.forEach(record => {
      if (!record.saved) record.selected = Boolean(record.ready && record.confidence !== "low");
    });
    renderAIReview();
  });
  $("#clearAISelection").addEventListener("click", () => {
    state.aiReview.forEach(record => { record.selected = false; });
    renderAIReview();
  });
  $("#confirmAIRecords").addEventListener("click", confirmAIRecords);
  $("#aiReviewList").addEventListener("change", event => {
    const item = event.target.closest("[data-ai-index]");
    if (!item) return;
    const record = state.aiReview[Number(item.dataset.aiIndex)];
    if (event.target.matches("[data-ai-select]")) {
      record.selected = event.target.checked;
      updateAISelectionLabel();
    }
  });
  $("#aiReviewList").addEventListener("input", event => {
    const item = event.target.closest("[data-ai-index]");
    const field = event.target.dataset.aiField;
    if (!item || !field) return;
    const record = state.aiReview[Number(item.dataset.aiIndex)];
    if (field === "locations") {
      record.locations = splitReviewValues(event.target.value);
    } else if (field === "total_hours" || field === "overtime_hours" || field === "extra_pay") {
      record[field] = Number(event.target.value || 0);
      if (field === "overtime_hours") {
        record.regular_hours = record.regular_hours || 8;
        record.total_hours = Math.max(record.total_hours || 0, record.regular_hours + record.overtime_hours);
        const totalInput = item.querySelector('[data-ai-field="total_hours"]');
        if (totalInput) totalInput.value = record.total_hours;
      } else if (field === "total_hours") {
        record.regular_hours = Math.min(record.total_hours, 8);
        record.overtime_hours = Math.max(record.total_hours - 8, 0);
        const overtimeInput = item.querySelector('[data-ai-field="overtime_hours"]');
        if (overtimeInput) overtimeInput.value = record.overtime_hours;
      }
    } else {
      record[field] = event.target.value;
    }
  });
  $("#loadWorkerMonth").addEventListener("click", loadWorkerMonth);
  $("#workerMonthSearch").addEventListener("keydown", event => {
    if (event.key === "Enter") {
      event.preventDefault();
      loadWorkerMonth();
    }
  });
  $$('[data-worker-month]').forEach(button => button.addEventListener("click", () => {
    stepWorkerMonth(Number(button.dataset.workerMonth));
  }));
  $("#saveWorkerMonth").addEventListener("click", event => {
    if (!state.workerMonth) return;
    saveWorkerMonthDays(state.workerMonth.days.filter(day => day.dirty), event.currentTarget);
  });
  $("#workerMonthBody").addEventListener("change", event => {
    const row = event.target.closest("[data-month-index]");
    const field = event.target.dataset.monthField;
    if (!row || !field || !state.workerMonth) return;
    const day = state.workerMonth.days[Number(row.dataset.monthIndex)];
    if (field === "status") {
      day.status = event.target.value;
      if (day.status === "worked") {
        day.total_hours = day.total_hours || 8;
        day.start_time = day.start_time || "08:30";
        day.end_time = day.end_time || "16:30";
      } else if (day.status === "off") {
        day.total_hours = 0;
        day.overtime_hours = 0;
        day.extra_pay = 0;
        day.locations = [];
      }
      day.dirty = true;
      syncWorkerMonthDraft();
      renderWorkerMonth();
    }
  });
  $("#workerMonthBody").addEventListener("input", event => {
    const row = event.target.closest("[data-month-index]");
    const field = event.target.dataset.monthField;
    if (!row || !field || field === "status" || !state.workerMonth) return;
    const day = state.workerMonth.days[Number(row.dataset.monthIndex)];
    if (field === "cost_center_add") {
      if (!addRecordCostCenter(day, event.target.value)) return;
      day.dirty = true;
      syncWorkerMonthDraft();
      renderWorkerMonth();
      return;
    }
    if (field === "location") {
      const parsed = parseNormalizedLocations(event.target.value);
      day.locations = parsed.locations;
      day.location_error = parsed.error;
      if (parsed.overtime_hours != null) day.overtime_hours = parsed.overtime_hours;
      if (parsed.extra_pay != null) day.extra_pay = parsed.extra_pay;
      const overtime = Number(day.overtime_hours || 0);
      if (day.locations.length && day.locations.every(item => item.hours != null)) {
        day.total_hours = day.locations.reduce((sum, item) => sum + Number(item.hours), 0) + overtime;
      }
    } else if (field === "overtime_hours") {
      const regular = day.locations?.length && day.locations.every(item => item.hours != null)
        ? day.locations.reduce((sum, item) => sum + Number(item.hours), 0)
        : Math.min(Number(day.total_hours || 0), 8);
      day.overtime_hours = Number(event.target.value || 0);
      day.total_hours = regular + day.overtime_hours;
    } else if (field === "total_hours" || field === "extra_pay") {
      day[field] = Number(event.target.value || 0);
      if (field === "total_hours") day.overtime_hours = derivedOvertime(day);
    } else {
      day[field] = event.target.value;
    }
    const totalInput = row.querySelector('[data-month-field="total_hours"]');
    const overtimeInput = row.querySelector('[data-month-field="overtime_hours"]');
    const extraInput = row.querySelector('[data-month-field="extra_pay"]');
    if (field !== "total_hours" && totalInput) totalInput.value = compactNumber(day.total_hours);
    if (field !== "overtime_hours" && overtimeInput) overtimeInput.value = compactNumber(day.overtime_hours);
    if (field !== "extra_pay" && extraInput) extraInput.value = compactNumber(day.extra_pay);
    day.dirty = true;
    row.querySelector("[data-save-month-day]").disabled = !day.status;
    const preview = row.querySelector(".month-normalized");
    if (preview) preview.textContent = normalizedWorkCell(day);
    syncWorkerMonthDraft();
  });
  $("#workerMonthBody").addEventListener("click", event => {
    const row = event.target.closest("[data-month-index]");
    if (!row || !state.workerMonth) return;
    const day = state.workerMonth.days[Number(row.dataset.monthIndex)];
    const removeButton = event.target.closest("[data-remove-cost-center]");
    if (removeButton) {
      recordCostCenters(day).splice(Number(removeButton.dataset.removeCostCenter), 1);
      day.dirty = true;
      syncWorkerMonthDraft();
      renderWorkerMonth();
      return;
    }
    const button = event.target.closest("[data-save-month-day]");
    if (!button) return;
    saveWorkerMonthDays([day], button);
  });
  $$(".preset-row button").forEach(button => button.addEventListener("click", () => {
    $$(".preset-row button").forEach(item => item.classList.toggle("active", item === button));
    setPreset(button.dataset.range);
    loadSummary();
  }));
  $("#dailyDate").addEventListener("change", loadDaily);
  $("#dailyWorkerSearch").addEventListener("input", renderDaily);
  $("#saveDay").addEventListener("click", saveDaily);
  $("#markAllOff").addEventListener("click", () => {
    state.daily.forEach(item => {
      if (!item.existing) {
        item.status = "off";
        item.total_hours = 0;
        item.overtime_hours = 0;
        item.locations = [];
        item.dirty = true;
      }
    });
    syncDailyDraft();
    renderDaily();
  });
  $("#dailyList").addEventListener("click", event => {
    const card = event.target.closest(".worker-entry");
    if (!card) return;
    const record = state.daily[Number(card.dataset.index)];
    if (event.target.closest("[data-copy-worker]")) {
      copyDailyWorker(record);
      return;
    }
    if (event.target.closest("[data-paste-worker]")) {
      pasteDailyWorker(record);
      return;
    }
    const removeCenterButton = event.target.closest("[data-remove-cost-center]");
    if (removeCenterButton) {
      recordCostCenters(record).splice(Number(removeCenterButton.dataset.removeCostCenter), 1);
      markRecordDirty(record);
      renderDaily();
      return;
    }
    const saveButton = event.target.closest("[data-save-worker]");
    if (saveButton) {
      saveOneDaily(Number(card.dataset.index), saveButton);
      return;
    }
    const statusButton = event.target.closest("[data-status]");
    if (statusButton) {
      record.status = statusButton.dataset.status;
      if (record.status === "worked" && !record.total_hours) record.total_hours = 8;
      if (record.status === "off") {
        record.total_hours = 0;
        record.overtime_hours = 0;
        record.extra_pay = 0;
        record.locations = [];
      }
      markRecordDirty(record);
      renderDaily();
    }
    if (event.target.closest("[data-clear]")) {
      if (record.existing && record.saved) {
        Object.assign(record, dailyRecordSnapshot(record.saved));
      } else {
        record.status = "worked";
        record.total_hours = 8;
        record.overtime_hours = 0;
        record.extra_pay = 0;
        record.start_time = "08:30";
        record.end_time = "16:30";
        record.cost_centers = [];
        record.locations = [];
        record.notes = "";
      }
      record.dirty = false;
      syncDailyDraft();
      renderDaily();
    }
  });
  $("#dailyList").addEventListener("input", event => {
    const card = event.target.closest(".worker-entry");
    const field = event.target.dataset.field;
    if (!card || !field) return;
    const record = state.daily[Number(card.dataset.index)];
    if (field === "cost_center_add") {
      if (!addRecordCostCenter(record, event.target.value)) return;
      markRecordDirty(record);
      renderDaily();
      return;
    }
    if (field === "location") {
      const parsed = parseNormalizedLocations(event.target.value);
      record.locations = parsed.locations;
      record.location_error = parsed.error;
      if (parsed.overtime_hours != null) record.overtime_hours = parsed.overtime_hours;
      if (parsed.extra_pay != null) record.extra_pay = parsed.extra_pay;
      const overtime = Number(record.overtime_hours || 0);
      if (record.locations.length && record.locations.every(item => item.hours != null)) {
        record.total_hours = record.locations.reduce((sum, item) => sum + Number(item.hours), 0) + overtime;
      }
    } else if (field === "overtime_hours") {
      const regular = record.locations?.length && record.locations.every(item => item.hours != null)
        ? record.locations.reduce((sum, item) => sum + Number(item.hours), 0)
        : Math.min(Number(record.total_hours || 0), 8);
      record.overtime_hours = Number(event.target.value || 0);
      record.total_hours = regular + record.overtime_hours;
    } else if (field === "total_hours" || field === "extra_pay") {
      record[field] = Number(event.target.value || 0);
      if (field === "total_hours") record.overtime_hours = derivedOvertime(record);
    } else {
      record[field] = event.target.value;
    }
    const totalInput = card.querySelector('[data-field="total_hours"]');
    const overtimeInput = card.querySelector('[data-field="overtime_hours"]');
    const extraInput = card.querySelector('[data-field="extra_pay"]');
    if (field !== "total_hours" && totalInput) totalInput.value = compactNumber(record.total_hours);
    if (field !== "overtime_hours" && overtimeInput) overtimeInput.value = compactNumber(record.overtime_hours);
    if (field !== "extra_pay" && extraInput) extraInput.value = compactNumber(record.extra_pay);
    card.querySelector("[data-save-worker]").disabled = !record.status;
    const preview = card.querySelector(".normalized-preview code");
    if (preview) preview.textContent = normalizedWorkCell(record);
    markRecordDirty(record);
  });
  $("#addWorkerSidebar")?.addEventListener("click", () => $("#workerDialog").showModal());
  $("#workerForm").addEventListener("submit", addWorker);
  $$("[data-close-dialog]").forEach(button => button.addEventListener("click", () => $("#workerDialog").close()));

  const fileInput = $("#workbookFile");
  fileInput.addEventListener("change", () => {
    $("#selectedFile").textContent = fileInput.files[0]?.name || "No file selected";
  });
  ["dragenter", "dragover"].forEach(type => $("#dropZone").addEventListener(type, event => {
    event.preventDefault(); $("#dropZone").classList.add("dragging");
  }));
  ["dragleave", "drop"].forEach(type => $("#dropZone").addEventListener(type, event => {
    event.preventDefault(); $("#dropZone").classList.remove("dragging");
  }));
  $("#dropZone").addEventListener("drop", event => {
    fileInput.files = event.dataTransfer.files;
    $("#selectedFile").textContent = fileInput.files[0]?.name || "No file selected";
  });
  $("#analyzeImport").addEventListener("click", analyzeImport);
  $("#applySelected").addEventListener("click", applyImport);
  $("#selectSafe").addEventListener("click", () => {
    $$("[data-conflict]").forEach(input => {
      const conflict = state.conflicts.find(item => item.id === Number(input.dataset.conflict));
      input.checked = conflict?.action !== "review";
    });
  });
  $("#downloadExport").addEventListener("click", () => {
    const params = new URLSearchParams({ from: $("#exportFrom").value, to: $("#exportTo").value });
    window.location.href = `/api/export?${params}`;
  });
  $("#reviewList").addEventListener("click", event => {
    const button = event.target.closest("[data-confirm-review]");
    if (button) confirmReview(button.closest(".review-item"));
  });
}

bindEvents();
bootstrap().catch(error => toast(error.message, "error"));
