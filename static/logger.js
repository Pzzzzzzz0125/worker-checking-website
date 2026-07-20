const state = { bootstrap: null, worker: null, record: null, dirty: false };
const $ = selector => document.querySelector(selector);

function localISO(day = new Date()) {
  const offset = day.getTimezoneOffset();
  return new Date(day.getTime() - offset * 60000).toISOString().slice(0, 10);
}
function escapeHTML(value = "") { return String(value).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"}[c])); }
function compact(value) { return Number(value || 0).toFixed(2).replace(/\.00$/, "").replace(/(\.\d)0$/, "$1"); }
function displayDate(value) { return new Date(`${value}T12:00:00`).toLocaleDateString("en-US", { weekday:"long", month:"long", day:"numeric", year:"numeric" }); }
function centerLabel(center) { return `${center.name} · ${center.id}`; }
async function api(path, options = {}) {
  const response = await fetch(path, options);
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || "Request failed");
  return body;
}
function toast(message, kind = "") {
  const node = document.createElement("div"); node.className = `toast ${kind}`; node.textContent = message;
  $("#toasts").append(node); setTimeout(() => node.remove(), 3800);
}
function resolveWorker(value) {
  const query = value.trim().toLowerCase();
  if (!query) return null;
  return state.bootstrap.workers.find(item => item.name.toLowerCase() === query)
    || state.bootstrap.workers.find(item => item.name.toLowerCase().includes(query));
}
function resolveCenter(value) {
  const query = value.trim().toLowerCase();
  return state.bootstrap.cost_centers.find(item => centerLabel(item).toLowerCase() === query)
    || state.bootstrap.cost_centers.find(item => item.id.toLowerCase() === query)
    || state.bootstrap.cost_centers.find(item => item.name.toLowerCase() === query);
}
function draftKey() { return state.worker ? `speed-log:${$("#logDate").value}:${state.worker.id}` : ""; }
function saveDraft() {
  if (!state.record || !state.worker) return;
  state.dirty = true;
  try { localStorage.setItem(draftKey(), JSON.stringify(state.record)); } catch {}
  $("#saveState").textContent = "Unsaved changes · draft protected";
  updatePreview();
}
function clearDraft() { try { localStorage.removeItem(draftKey()); } catch {} }

function normalizeRecord(record) {
  const output = {
    status: record.status || "worked",
    total_hours: Number(record.total_hours ?? 8),
    extra_pay: Number(record.extra_pay || 0),
    start_time: record.start_time || "08:30",
    end_time: record.end_time || "16:30",
    notes: record.notes || "",
    locations: (record.locations || []).map(item => ({
      name: item.name || "", hours: item.hours == null ? null : Number(item.hours),
      cost_centers: (item.cost_centers || []).map(center => ({ id:center.id, name:center.name })), suggestions: []
    }))
  };
  const explicit = output.locations.length && output.locations.every(item => item.hours != null);
  const regular = explicit ? output.locations.reduce((sum,item) => sum + item.hours, 0) : Math.min(output.total_hours, 8);
  output.regular_hours = regular || 8;
  output.overtime_hours = Math.max(output.total_hours - regular, 0);
  if (!output.locations.length && output.status === "worked") output.locations.push({ name:"", hours:null, cost_centers:[], suggestions:[] });
  return output;
}

async function loadBootstrap(workerId = 0) {
  state.bootstrap = await api(`/api/logger/bootstrap?worker_id=${workerId}`);
  $("#loggerWorkers").innerHTML = state.bootstrap.workers.map(item => `<option value="${escapeHTML(item.name)}"></option>`).join("");
  $("#loggerLocations").innerHTML = state.bootstrap.locations.map(item => `<option value="${escapeHTML(item.name)}"></option>`).join("");
  $("#loggerCostCenters").innerHTML = state.bootstrap.cost_centers.map(item => `<option value="${escapeHTML(centerLabel(item))}"></option>`).join("");
}

async function openWorker() {
  const worker = resolveWorker($("#workerSearch").value);
  if (!worker) { toast("Choose a worker from the list.", "error"); return; }
  const button = $("#openEntry"); button.disabled = true;
  try {
    await loadBootstrap(worker.id);
    state.worker = state.bootstrap.workers.find(item => item.id === worker.id) || worker;
    const data = await api(`/api/logger/day?worker_id=${worker.id}&date=${encodeURIComponent($("#logDate").value)}`);
    state.record = normalizeRecord(data.record);
    try {
      const draft = JSON.parse(localStorage.getItem(draftKey()) || "null");
      if (draft) { state.record = normalizeRecord(draft); state.dirty = true; }
      else state.dirty = false;
    } catch { state.dirty = false; }
    $("#workerSearch").value = state.worker.name;
    $("#entryEmpty").hidden = true; $("#logForm").hidden = false;
    renderForm();
    await Promise.all(state.record.locations.map((_, index) => loadCenterSuggestions(index, false)));
    renderLocations();
  } catch (error) { toast(error.message, "error"); }
  finally { button.disabled = false; }
}

function renderForm() {
  const record = state.record;
  $("#selectedWorker").textContent = state.worker.name;
  $("#selectedDate").textContent = displayDate($("#logDate").value);
  document.querySelectorAll("[data-status]").forEach(button => button.classList.toggle("active", button.dataset.status === record.status));
  $("#workedFields").hidden = record.status !== "worked";
  $("#regularHours").value = compact(record.regular_hours);
  $("#overtimeHours").value = compact(record.overtime_hours);
  $("#extraPay").value = compact(record.extra_pay);
  $("#startTime").value = record.start_time;
  $("#endTime").value = record.end_time;
  $("#logNotes").value = record.notes;
  $("#saveState").textContent = state.dirty ? "Unsaved changes · draft protected" : "Ready to save";
  renderLocations(); updatePreview();
}

function renderLocations() {
  $("#locationList").innerHTML = state.record.locations.map((location, index) => {
    const selected = location.cost_centers.map((center, centerIndex) => `<button type="button" class="center-chip" data-remove-center="${centerIndex}">${escapeHTML(centerLabel(center))}<i>×</i></button>`).join("");
    const suggestions = (location.suggestions?.length ? location.suggestions : state.bootstrap.cost_centers.slice(0,5))
      .filter(center => !location.cost_centers.some(item => item.id === center.id))
      .slice(0,5).map(center => `<button type="button" class="quick-chip" data-add-center="${escapeHTML(center.id)}">＋ ${escapeHTML(center.name)}</button>`).join("");
    return `<article class="location-card card" data-location-index="${index}">
      <div class="location-top">
        <label><span>Location ${index + 1}</span><input data-location-name list="loggerLocations" value="${escapeHTML(location.name)}" placeholder="Search or type location" autocomplete="off"></label>
        <label><span>Hours <small>(optional)</small></span><input data-location-hours type="number" min="0" max="24" step=".25" value="${location.hours == null ? "" : compact(location.hours)}" placeholder="Auto"></label>
        <button type="button" class="remove-location" data-remove-location aria-label="Remove location">×</button>
      </div>
      <div class="cost-area"><span>Cost center(s) for this location <small>(optional)</small></span>
        <div class="selected-centers">${selected || '<small>No cost center selected</small>'}</div>
        <input class="cost-search" data-center-search list="loggerCostCenters" placeholder="Search cost center name or ID" autocomplete="off">
        <div class="quick-centers">${suggestions ? '<span class="quick-label">Frequently used here</span>' + suggestions : ""}</div>
      </div>
    </article>`;
  }).join("");
}

async function loadCenterSuggestions(index, rerender = true) {
  const location = state.record.locations[index];
  if (!location?.name) return;
  try {
    const data = await api(`/api/logger/cost-centers?worker_id=${state.worker.id}&location=${encodeURIComponent(location.name)}`);
    location.suggestions = data.cost_centers;
    if (rerender) renderLocations();
  } catch {}
}

function addCenter(index, center) {
  const location = state.record.locations[index];
  if (!location.cost_centers.some(item => item.id === center.id)) location.cost_centers.push({ id:center.id, name:center.name });
  saveDraft(); renderLocations();
}
function syncRegularFromLocations() {
  const locations = state.record.locations;
  if (locations.length && locations.every(item => item.hours != null)) {
    state.record.regular_hours = locations.reduce((sum,item) => sum + Number(item.hours), 0);
    $("#regularHours").value = compact(state.record.regular_hours);
  }
}

function normalizedPreview() {
  const record = state.record;
  if (record.status === "off") return "off";
  const locations = record.locations.filter(item => item.name.trim());
  if (!locations.length) return "—";
  const explicit = locations.every(item => item.hours != null);
  const regular = Number(record.regular_hours || 0);
  let parts;
  if (explicit) parts = locations.map(item => `${item.name}(${compact(item.hours)})`);
  else if (regular < 8) {
    const share = Math.round(regular / locations.length * 100) / 100;
    parts = locations.map((item,index) => `${item.name}(${compact(index === locations.length - 1 ? regular - share * (locations.length - 1) : share)})`);
  } else parts = locations.map(item => item.name);
  let value = parts.join(";");
  if (Number(record.overtime_hours)) value += `, ot ${compact(record.overtime_hours)}h`;
  if (Number(record.extra_pay)) value += `, ex $${compact(record.extra_pay)}`;
  return value;
}
function updatePreview() {
  if (!state.record) return;
  const filledLocations = state.record.locations.filter(item => item.name.trim());
  if (filledLocations.length && filledLocations.every(item => item.hours != null)) {
    state.record.regular_hours = filledLocations.reduce(
      (sum, item) => sum + Number(item.hours), 0
    );
    if ($("#regularHours")) $("#regularHours").value = compact(state.record.regular_hours);
  }
  state.record.total_hours = Number(state.record.regular_hours || 0) + Number(state.record.overtime_hours || 0);
  $("#totalHoursLabel").textContent = `${compact(state.record.total_hours)}h total`;
  $("#cellPreview").textContent = normalizedPreview();
}

async function useLastEntry() {
  try {
    const data = await api(`/api/logger/recent?worker_id=${state.worker.id}&before=${encodeURIComponent($("#logDate").value)}`);
    if (!data.record) { toast("No earlier worked day found for this worker.", "error"); return; }
    state.record = normalizeRecord(data.record); state.record.status = "worked"; state.dirty = true;
    saveDraft(); renderForm();
    await Promise.all(state.record.locations.map((_, index) => loadCenterSuggestions(index, false)));
    renderLocations(); toast(`Copied the entry from ${displayDate(data.record.work_date)}.`);
  } catch (error) { toast(error.message, "error"); }
}

function validate() {
  if (state.record.status === "off") return "";
  const locations = state.record.locations.filter(item => item.name.trim());
  if (!locations.length) return "Add at least one location.";
  const explicit = locations.filter(item => item.hours != null).length;
  if (explicit && explicit !== locations.length) return "Enter hours for every location, or leave every location hour blank.";
  return "";
}

async function saveLog(event) {
  event.preventDefault();
  const error = validate(); if (error) { toast(error, "error"); return; }
  const button = $("#saveLog"); button.disabled = true; button.textContent = "Saving…";
  try {
    updatePreview();
    const record = { ...state.record, locations: state.record.status === "worked" ? state.record.locations.filter(item => item.name.trim()).map(item => ({ name:item.name.trim(), hours:item.hours, cost_centers:item.cost_centers })) : [] };
    await api("/api/logger/day", { method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({ worker_id:state.worker.id, date:$("#logDate").value, record }) });
    clearDraft(); state.dirty = false; $("#saveState").textContent = "Saved successfully";
    toast(`${state.worker.name} saved for ${displayDate($("#logDate").value)}.`);
    await loadBootstrap(state.worker.id);
  } catch (error) { toast(error.message, "error"); }
  finally { button.disabled = false; button.textContent = "Save worker day"; }
}

function bindEvents() {
  $("#openEntry").addEventListener("click", openWorker);
  $("#workerSearch").addEventListener("keydown", event => { if (event.key === "Enter") { event.preventDefault(); openWorker(); } });
  $("#logDate").addEventListener("change", () => { if (state.worker) openWorker(); });
  document.querySelectorAll("[data-status]").forEach(button => button.addEventListener("click", () => { state.record.status = button.dataset.status; saveDraft(); renderForm(); }));
  $("#addLocation").addEventListener("click", () => { state.record.locations.push({ name:"", hours:null, cost_centers:[], suggestions:[] }); saveDraft(); renderLocations(); });
  $("#useLast").addEventListener("click", useLastEntry);
  $("#locationList").addEventListener("input", event => {
    const card = event.target.closest("[data-location-index]"); if (!card) return;
    const location = state.record.locations[Number(card.dataset.locationIndex)];
    if (event.target.matches("[data-location-name]")) location.name = event.target.value;
    if (event.target.matches("[data-location-hours]")) { location.hours = event.target.value === "" ? null : Number(event.target.value); syncRegularFromLocations(); }
    saveDraft();
  });
  $("#locationList").addEventListener("change", event => {
    const card = event.target.closest("[data-location-index]"); if (!card) return;
    const index = Number(card.dataset.locationIndex);
    if (event.target.matches("[data-location-name]")) loadCenterSuggestions(index);
    if (event.target.matches("[data-center-search]")) { const center = resolveCenter(event.target.value); if (center) addCenter(index, center); else if (event.target.value) toast("Choose a cost center from the list.", "error"); }
  });
  $("#locationList").addEventListener("click", event => {
    const card = event.target.closest("[data-location-index]"); if (!card) return;
    const index = Number(card.dataset.locationIndex); const location = state.record.locations[index];
    if (event.target.closest("[data-remove-location]")) { state.record.locations.splice(index,1); if (!state.record.locations.length) state.record.locations.push({ name:"", hours:null, cost_centers:[], suggestions:[] }); saveDraft(); renderLocations(); return; }
    const remove = event.target.closest("[data-remove-center]"); if (remove) { location.cost_centers.splice(Number(remove.dataset.removeCenter),1); saveDraft(); renderLocations(); return; }
    const add = event.target.closest("[data-add-center]"); if (add) { const center = state.bootstrap.cost_centers.find(item => item.id === add.dataset.addCenter); if (center) addCenter(index, center); }
  });
  [["regularHours","regular_hours"],["overtimeHours","overtime_hours"],["extraPay","extra_pay"],["startTime","start_time"],["endTime","end_time"],["logNotes","notes"]].forEach(([id,key]) => $("#"+id).addEventListener("input", event => { state.record[key] = ["regular_hours","overtime_hours","extra_pay"].includes(key) ? Number(event.target.value || 0) : event.target.value; saveDraft(); }));
  $("#logForm").addEventListener("submit", saveLog);
}

async function start() {
  $("#logDate").value = localISO();
  await loadBootstrap(); bindEvents();
}
start().catch(error => toast(error.message, "error"));
