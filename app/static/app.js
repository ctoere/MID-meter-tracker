"use strict";
/* Zeres MID Register — UI.
   Descended from the single-file prototype; the layout, colour semantics and copy
   are kept. The difference is that the data comes from the local API instead of
   being parsed in the browser, and edits are written back to the workbook. */

const S = { chargers:[], meters:[], conflicts:[], manifest:[], gaps:[], intake:[], stats:{}, meta:{},
            f:{q:"", st:"all", brand:"", rev:false}, mf:"" };

const $  = s => document.querySelector(s);
const $$ = s => Array.from(document.querySelectorAll(s));
const esc = s => String(s ?? "").replace(/[&<>"']/g, c =>
  ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));

const STATUSES = ["Integrated","Optional","External","None","Unknown"];
const COLOR = {Integrated:"var(--good)", Optional:"var(--warning)", External:"var(--serious)",
               None:"var(--critical)", Unknown:"var(--muted)"};
/* Optional and External are NOT rejections — both mean "eligible, verify the unit".
   Never render either in a way that reads as a no. See CLAUDE.md. */
const ELIGIBLE = {Integrated:"eligible as sold",
                  Optional:"eligible — check the individual unit",
                  External:"eligible if an external MID meter is fitted",
                  None:"not eligible as sold",
                  Unknown:"not established"};

let tT;
function toast(m){ const t=$("#toast"); t.textContent=m; t.classList.add("on");
  clearTimeout(tT); tT=setTimeout(()=>t.classList.remove("on"),2600); }
function badge(v){ const s=STATUSES.includes(v)?v:"Unknown";
  return `<span class="badge b-${s}"><i></i>${esc(v||"Unknown")}</span>`; }
function needsReview(r){ return String(r["Review Needed"]||"").trim() !== ""; }

async function api(path, options){
  const res = await fetch(path, options);
  const body = await res.json().catch(()=>({}));
  if(!res.ok) throw new Error(body.detail || `${res.status} ${res.statusText}`);
  return body;
}

/* ───── load ───── */
async function loadAll(){
  try{
    const d = await api("/api/register");
    Object.assign(S, {chargers:d.chargers, meters:d.meters, conflicts:d.conflicts,
                      manifest:d.manifest, gaps:d.gaps, stats:d.stats, meta:d.meta,
                      conflictStats:d.conflictStats});
    const p=$("#state"); p.classList.add("live");
    p.lastElementChild.textContent = d.meta.path.split(/[\\/]/).pop();
    p.title = d.meta.path;
    renderAll();
  }catch(e){
    const p=$("#state"); p.classList.remove("live"); p.lastElementChild.textContent="Error";
    toast("Could not load the register: "+e.message);
  }
}
$("#reloadBtn").onclick = async () => {
  await api("/api/reload",{method:"POST"}); await loadAll(); toast("Reloaded from disk");
};

/* ───── chrome ───── */
$("#themeBtn").onclick = function(){
  const dark = document.documentElement.getAttribute("data-theme")==="dark";
  document.documentElement.setAttribute("data-theme", dark?"light":"dark");
  this.textContent = dark ? "Dark" : "Light";
  localStorage.setItem("zeres-theme", dark?"light":"dark");
  renderDist();
};
(function(){ const saved = localStorage.getItem("zeres-theme");
  if(saved==="dark"){ document.documentElement.setAttribute("data-theme","dark"); $("#themeBtn").textContent="Light"; }})();

$$(".tab").forEach(t => t.onclick = () => {
  $$(".tab").forEach(x => x.setAttribute("aria-selected", String(x===t)));
  $$(".panel").forEach(p => p.classList.toggle("on", p.id === "p-"+t.dataset.t));
  window.scrollTo({top:0, behavior:"smooth"});
});
function goTab(n){ $$(".tab").find(t=>t.dataset.t===n).click(); }

/* ───── register ───── */
function filtered(){
  const q = S.f.q.toLowerCase();
  return S.chargers.filter(r => {
    if(S.f.st !== "all" && String(r["MID Status"]).trim() !== S.f.st) return false;
    if(S.f.brand && r.Brand !== S.f.brand) return false;
    if(S.f.rev && !needsReview(r)) return false;
    if(!q) return true;
    return Object.values(r).some(v => String(v).toLowerCase().includes(q));
  });
}
function renderTiles(){
  const s = S.stats;
  $("#tTot").textContent  = (s.total||0).toLocaleString();
  $("#tBrands").textContent = (s.brands||0) + " brands";
  $("#tInt").textContent  = s.eligible_as_sold||0;
  $("#tOpt").textContent  = s.eligible_check_unit||0;
  $("#tNone").textContent = s.not_eligible||0;
  $("#tRev").textContent  = s.needs_review||0;
  $("#cReg").textContent  = S.chargers.length;
  $("#cMet").textContent  = S.meters.length;
  $("#cCon").textContent  = S.conflicts.filter(c => !String(c.Decision||"").trim()).length;
  $("#cMan").textContent  = S.manifest.length;
}
function renderDist(){
  const by = S.stats.by_status || {}, n = S.stats.total || 1;
  const bar = $("#dist"), leg = $("#leg");
  bar.innerHTML = ""; leg.innerHTML = "";
  STATUSES.forEach(s => {
    const v = by[s] || 0;
    if(v > 0){
      const el = document.createElement("span");
      el.style.background = COLOR[s]; el.style.flexGrow = v; el.style.flexBasis = "0";
      el.textContent = (v/n > .08) ? `${s} ${v}` : "";
      el.title = `${s}: ${v} (${Math.round(v/n*100)}%) — ${ELIGIBLE[s]}`;
      if(s === "Optional") el.style.color = "#3a2a00";
      bar.appendChild(el);
    }
    leg.insertAdjacentHTML("beforeend",
      `<span><i style="background:${COLOR[s]}"></i>${s} <b style="color:var(--ink)">${v}</b></span>`);
  });
  const el = (by.Integrated||0)+(by.Optional||0)+(by.External||0);
  $("#distNote").textContent = S.stats.total
    ? `${Math.round(el/n*100)}% of the register is ERE-eligible in some form` : "";
}
function renderBrands(){
  const sel = $("#brandSel"), cur = sel.value;
  const brands = [...new Set(S.chargers.map(r=>r.Brand).filter(Boolean))].sort((a,b)=>a.localeCompare(b));
  sel.innerHTML = `<option value="">All brands</option>` +
    brands.map(b=>`<option value="${esc(b)}">${esc(b)}</option>`).join("");
  sel.value = cur;
  $("#brandListHost").innerHTML =
    `<datalist id="brandList">${brands.map(b=>`<option value="${esc(b)}">`).join("")}</datalist>`;
}
function renderTable(){
  const rows = filtered(), cap = 500, tb = $("#tb");
  if(!rows.length){
    tb.innerHTML = `<tr><td colspan="7"><div class="empty">Nothing matches those filters.</div></td></tr>`;
    $("#rowNote").textContent = ""; return;
  }
  tb.innerHTML = rows.slice(0,cap).map(r => {
    const m = [r["Meter Brand"], r["Meter Model"]].filter(Boolean).join(" ");
    return `<tr data-id="${esc(r.ID)}">
      <td><b>${esc(r.Brand)}</b></td><td>${esc(r.Model)}</td>
      <td class="mono" style="color:var(--ink-3)">${esc(r["Max kW"]||"")}</td>
      <td>${badge(r["MID Status"])}${needsReview(r)?'<span class="flag">review</span>':""}</td>
      <td style="font-size:12.5px">${m?esc(m):'<span style="color:var(--ink-3)">—</span>'}</td>
      <td style="font-size:12px;color:var(--ink-2)">${esc(String(r.Source||"").slice(0,40))}</td>
      <td style="font-size:12px;color:var(--ink-2)"><div class="clamp">${esc(r["Notes (EN)"]||r["Notes (NL)"]||"")}</div></td></tr>`;
  }).join("");
  $$("#tb tr").forEach(tr => tr.onclick = () => openCharger(tr.dataset.id));
  $("#rowNote").textContent = rows.length > cap
    ? `Showing first ${cap} of ${rows.length} matches — narrow the search.`
    : `${rows.length} of ${S.chargers.length} rows`;
}

/* ───── drawer ───── */
function openDrawer(){ $("#dr").classList.add("on"); $("#bd").classList.add("on"); }
function closeDrawer(){ $("#dr").classList.remove("on"); $("#bd").classList.remove("on"); $("#drF").style.display="none"; }
$("#drC").onclick = $("#bd").onclick = closeDrawer;
document.addEventListener("keydown", e => { if(e.key === "Escape"){ closeDrawer(); $("#lb").classList.remove("on"); }});

function link(v){ return v
  ? `<a href="${esc(v)}" target="_blank" rel="noopener">${esc(String(v).slice(0,70))}</a>`
  : '<span style="color:var(--ink-3)">—</span>'; }
function kv(k,v){ return `<div class="kv"><dt>${k}</dt><dd>${v}</dd></div>`; }

function statusSelect(cur){
  return `<select data-f="MID Status">${STATUSES.map(v =>
    `<option value="${v}" ${cur===v?"selected":""}>${v} — ${ELIGIBLE[v]}</option>`).join("")}</select>`;
}
function field(label, name, value, opts){
  const o = opts||{};
  return `<div class="field"><label>${label}</label>${
    o.select ? o.select
    : `<input data-f="${esc(name)}" value="${esc(value||"")}" ${o.list?`list="${o.list}"`:""}>`}</div>`;
}

function openCharger(id){
  const r = S.chargers.find(x => x.ID === id); if(!r) return;
  S.editing = {kind:"charger", id};
  $("#drT").textContent = `${r.Brand} — ${r.Model}`;
  $("#drS").innerHTML = `${esc(r.ID)} · ${esc(r["Charge Type"]||"")} ${badge(r["MID Status"])}`;

  $("#drB").innerHTML =
    `<div class="note" style="margin-top:0"><b>${esc(r["MID Status"])}</b> — ${ELIGIBLE[r["MID Status"]]||""}</div>` +
    (needsReview(r) ? `<div class="note warn"><b>Review needed.</b> ${esc(r["Review Needed"])}</div>` : "") +
    (r.Conflict ? `<div class="note crit"><b>Sources disagreed.</b> ${esc(r.Conflict)}</div>` : "") +
    `<div id="drErr"></div>` +
    `<div class="sechead"><h2>MID status</h2><div class="ln"></div></div>` +
    field("MID status", "MID Status", r["MID Status"], {select: statusSelect(r["MID Status"])}) +
    `<div class="field"><label>Why — source or note <b>(required to change the status)</b></label>
       <input id="drReason" placeholder="e.g. datasheet rev 1.1 p.4, 'MID-certified meter fitted as standard'"></div>` +
    `<div class="sechead"><h2>Record</h2><div class="ln"></div></div>` +
    `<div class="grid2">` +
      field("Brand","Brand",r.Brand,{list:"brandList"}) + field("Model","Model",r.Model) +
      field("Charge type","Charge Type",r["Charge Type"]) + field("Max kW","Max kW",r["Max kW"]) +
      field("Meter brand","Meter Brand",r["Meter Brand"]) + field("Meter model","Meter Model",r["Meter Model"]) +
    `</div>` +
    field("Datasheet link","Datasheet Link",r["Datasheet Link"]) +
    field("Certificate link","Certificate Link",r["Certificate Link"]) +
    field("Drive folder","Drive Folder",r["Drive Folder"]) +
    `<div class="grid2">` +
      field("Research status","Research Status",r["Research Status"]) +
      field("Source","Source",r.Source) +
    `</div>` +
    field("Review needed — clear this only when the row is safe to quote","Review Needed",r["Review Needed"]) +
    `<div class="sechead"><h2>Notes</h2><div class="ln"></div></div>` +
    `<div class="note" style="font-size:12.5px">Notes carry quoted source language, so they are
       appended to, never overwritten. Existing text stays as it is.</div>` +
    kv("Notes (EN)", esc(r["Notes (EN)"]||"—")) +
    (r["Notes (NL)"] ? kv("Notes (NL)", esc(r["Notes (NL)"])) : "") +
    `<div class="field"><label>Append a note (EN)</label><textarea id="drNote" rows="3"
       placeholder="Quote the source wording rather than paraphrasing it."></textarea></div>` +
    `<div class="field"><label>Append a note (NL)</label><textarea id="drNoteNl" rows="2"></textarea></div>` +
    `<div class="sechead"><h2>History</h2><div class="ln"></div></div><div id="drHist" class="mono"
       style="font-size:12px;color:var(--ink-3)">loading…</div>`;

  $("#drF").style.display = "";
  $("#drF").innerHTML =
    `<button class="primary" id="drSave">Save changes</button>
     <button class="ghost" id="drCancel">Cancel</button>
     <span class="reqnote">Every change is written to the workbook and the Change Log.</span>`;
  $("#drSave").onclick = saveDrawer;
  $("#drCancel").onclick = closeDrawer;
  loadHistory(id);
  openDrawer();
}

async function loadHistory(id){
  const box = $("#drHist"); if(!box) return;
  try{
    const d = await api(`/api/history/${encodeURIComponent(id)}`);
    box.innerHTML = d.entries.length
      ? d.entries.map(e => `<div class="chg"><span class="t">${esc(e.Timestamp)} · ${esc(e.User)}</span><br>
          <b>${esc(e.Field)}</b>: ${e["Old Value"]?`<span class="was">${esc(e["Old Value"])}</span> → `:""}${esc(e["New Value"])}
          ${e.Reason?`<br><span style="color:var(--ink-2)">${esc(e.Reason)}</span>`:""}</div>`).join("")
      : "No changes recorded yet.";
  }catch(e){ box.textContent = "Could not load history: "+e.message; }
}

async function saveDrawer(){
  const {kind, id} = S.editing || {};
  if(!id) return;
  const fields = {};
  $$("#drB [data-f]").forEach(el => { fields[el.dataset.f] = el.value; });
  const payload = {
    fields,
    reason: ($("#drReason")||{}).value || "",
    appendNote: ($("#drNote")||{}).value || "",
    appendNoteNl: ($("#drNoteNl")||{}).value || "",
  };
  const err = $("#drErr"); if(err) err.innerHTML = "";
  $("#dr").classList.add("saving");
  try{
    const path = kind === "meter" ? `/api/meters/${id}` : `/api/chargers/${id}`;
    const d = await api(path, {method:"PATCH", headers:{"Content-Type":"application/json"},
                              body: JSON.stringify(payload)});
    if(!d.changes.length){ toast("Nothing changed."); $("#dr").classList.remove("saving"); return; }
    const list = kind === "meter" ? S.meters : S.chargers;
    const i = list.findIndex(x => x.ID === id);
    if(i >= 0) list[i] = d.row;
    if(d.stats) S.stats = d.stats;
    renderAll();
    toast(`Saved — ${d.changes.length} change${d.changes.length===1?"":"s"} logged`);
    closeDrawer();
  }catch(e){
    if(err) err.innerHTML = `<div class="err">${esc(e.message)}</div>`;
    else toast(e.message);
  }finally{ $("#dr").classList.remove("saving"); }
}

function openMeter(id){
  const r = S.meters.find(x => x.ID === id); if(!r) return;
  S.editing = {kind:"meter", id};
  $("#drT").textContent = `${r.Brand} — ${r.Model}`;
  $("#drS").innerHTML = `${esc(r.ID)} ${badge(r["MID Status"])}`;
  $("#drB").innerHTML =
    `<div class="note" style="margin-top:0"><b>${esc(r["MID Status"])}</b> — ${ELIGIBLE[r["MID Status"]]||""}</div>` +
    (needsReview(r) ? `<div class="note warn"><b>Review needed.</b> ${esc(r["Review Needed"])}</div>` : "") +
    `<div id="drErr"></div>` +
    field("MID status","MID Status",r["MID Status"],{select: statusSelect(r["MID Status"])}) +
    `<div class="field"><label>Why — source or note <b>(required to change the status)</b></label>
       <input id="drReason" placeholder="e.g. NMi certificate T10402, MI-003"></div>` +
    `<div class="grid2">` + field("Brand","Brand",r.Brand) + field("Model","Model",r.Model) + `</div>` +
    field("Datasheet link","Datasheet Link",r["Datasheet Link"]) +
    field("Certificate link","Certificate Link",r["Certificate Link"]) +
    field("Drive folder","Drive Folder",r["Drive Folder"]) +
    `<div class="grid2">` + field("Research status","Research Status",r["Research Status"]) +
      field("Source","Source",r.Source) + `</div>` +
    field("Review needed","Review Needed",r["Review Needed"]) +
    kv("Notes", esc(r.Notes||"—")) +
    `<div class="field"><label>Append a note</label><textarea id="drNote" rows="3"></textarea></div>` +
    `<div class="sechead"><h2>History</h2><div class="ln"></div></div><div id="drHist" class="mono"
       style="font-size:12px;color:var(--ink-3)">loading…</div>`;
  $("#drF").style.display = "";
  $("#drF").innerHTML =
    `<button class="primary" id="drSave">Save changes</button>
     <button class="ghost" id="drCancel">Cancel</button>
     <span class="reqnote">The meter is what carries certification, not the charger.</span>`;
  $("#drSave").onclick = saveDrawer;
  $("#drCancel").onclick = closeDrawer;
  loadHistory(id);
  openDrawer();
}

/* ───── new rows ───── */
function openNew(kind){
  S.editing = {kind, id:null};
  const isMeter = kind === "meter";
  $("#drT").textContent = isMeter ? "New meter" : "New charger";
  $("#drS").textContent = isMeter ? "mtr_…" : "chg_…";
  $("#drB").innerHTML =
    `<div class="note" style="margin-top:0">A new row starts as <b>Unknown</b> and is flagged for review.
      Absence of evidence is Unknown — never None.</div>` +
    `<div id="drErr"></div>` +
    `<div class="grid2">` +
      field("Brand *","Brand","",{list:"brandList"}) + field("Model *","Model","") + `</div>` +
    (isMeter ? "" : `<div class="grid2">` + field("Charge type","Charge Type","AC") +
                    field("Max kW","Max kW","") + `</div>`) +
    field("MID status","MID Status","Unknown",{select: statusSelect("Unknown")}) +
    `<div class="field"><label>Why — source or note</label>
       <input id="drReason" placeholder="Where does this come from?"></div>` +
    (isMeter ? "" : `<div class="grid2">` + field("Meter brand","Meter Brand","") +
                    field("Meter model","Meter Model","") + `</div>`) +
    field("Datasheet link","Datasheet Link","") +
    field("Certificate link","Certificate Link","") +
    field("Source","Source","") +
    `<div class="field"><label>Notes</label><textarea id="drNote" rows="3"
       placeholder="If this brand resells another manufacturer's hardware, note the relationship rather than duplicating their rows."></textarea></div>`;
  $("#drF").style.display = "";
  $("#drF").innerHTML = `<button class="primary" id="drSave">Create</button>
     <button class="ghost" id="drCancel">Cancel</button>`;
  $("#drSave").onclick = createRow;
  $("#drCancel").onclick = closeDrawer;
  openDrawer();
}

async function createRow(){
  const {kind} = S.editing;
  const fields = {};
  $$("#drB [data-f]").forEach(el => { fields[el.dataset.f] = el.value; });
  const payload = {fields, reason: ($("#drReason")||{}).value || "",
                   appendNote: ($("#drNote")||{}).value || ""};
  const err = $("#drErr"); err.innerHTML = "";
  $("#dr").classList.add("saving");
  try{
    const d = await api(kind === "meter" ? "/api/meters" : "/api/chargers",
      {method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify(payload)});
    (kind === "meter" ? S.meters : S.chargers).push(d.row);
    if(d.stats) S.stats = d.stats;
    renderAll(); closeDrawer();
    toast(`Created ${d.row.ID}`);
  }catch(e){ err.innerHTML = `<div class="err">${esc(e.message)}</div>`; }
  finally{ $("#dr").classList.remove("saving"); }
}
$("#addChargerBtn").onclick = () => openNew("charger");
$("#addMeterBtn").onclick = () => openNew("meter");

/* ───── filters ───── */
$("#q").oninput = e => { S.f.q = e.target.value; renderTable(); };
$("#brandSel").onchange = e => { S.f.brand = e.target.value; renderTable(); };
$("#stChips").onclick = e => {
  const b = e.target.closest(".chip"); if(!b) return;
  S.f.st = b.dataset.s;
  $$("#stChips .chip").forEach(x => x.setAttribute("aria-pressed", String(x===b)));
  renderTable();
};
$("#revBtn").onclick = function(){
  S.f.rev = !S.f.rev; this.setAttribute("aria-pressed", String(S.f.rev));
  this.style.borderColor = S.f.rev ? "var(--accent)" : "";
  this.style.color = S.f.rev ? "var(--accent)" : "";
  renderTable();
};

/* ───── meters ───── */
function renderMeters(){
  const tb = $("#mtb");
  if(!S.meters.length){ tb.innerHTML = `<tr><td colspan="5"><div class="empty">No meter records.</div></td></tr>`; return; }
  tb.innerHTML = S.meters.map(m => `<tr data-id="${esc(m.ID)}">
    <td><b>${esc(m.Brand)}</b></td><td>${esc(m.Model)}</td>
    <td>${badge(m["MID Status"])}${needsReview(m)?'<span class="flag">review</span>':""}</td>
    <td style="font-size:12px;color:var(--ink-2)">${esc(String(m.Source||"").slice(0,50))}</td>
    <td style="font-size:12px;color:var(--ink-2)"><div class="clamp">${esc(m.Notes||"")}</div></td></tr>`).join("");
  $$("#mtb tr").forEach(tr => tr.onclick = () => openMeter(tr.dataset.id));
}

/* ───── conflicts ─────
   Nothing here decides anything on its own. A person picks a side and says why. */
function renderConflicts(){
  const list = $("#cfList");
  const st = S.conflictStats || {total:0, open:0, resolved:0, opposed_open:0};
  $("#cfCount").textContent = st.total
    ? `${st.open} open · ${st.resolved} resolved of ${st.total}${
        st.opposed_open?` · ${st.opposed_open} opposed still open`:""}` : "";
  if(!S.conflicts.length){
    list.innerHTML = `<div class="empty card">No conflict rows in this register.
      The Conflicts sheet exists and is empty — nothing has been auto-resolved.</div>`;
    return;
  }
  list.innerHTML = S.conflicts.map(c => `
    <div class="cf ${c.opposed?"opposed":""} ${c.open?"":"resolved"}" data-id="${esc(c.ID)}">
      <div class="hd"><b>${esc(c.Brand)} — ${esc(c.Model)}</b>
        <span>${c.opposed?'<span class="badge b-None"><i></i>opposed</span> ':""}${
          c.open?"":`<span class="badge b-Integrated"><i></i>resolved: ${esc(c.Decision)}</span>`}</span></div>
      ${c.opposed && c.open ? `<div class="note crit" style="margin:0 0 10px">One source says eligible,
        the other says not. Whichever system the helpdesk opened decided what this client was told.</div>` : ""}
      <div class="opts">
        <div class="opt ${c.Decision===c["Tracker says"]?"sel":""}" data-v="${esc(c["Tracker says"])}">
          <div class="src">Research tracker</div>${badge(c["Tracker says"])}
          <p>${esc(String(c["Tracker note"]||"").slice(0,300))||"no note"}</p></div>
        <div class="opt ${c.Decision===c["Zite says"]?"sel":""}" data-v="${esc(c["Zite says"])}">
          <div class="src">Zite dashboard ${c["Zite original value"]?`<span class="mono">(${esc(c["Zite original value"])})</span>`:""}</div>${badge(c["Zite says"])}
          <p>${esc(String(c["Zite note"]||"").slice(0,300))||"no note"}</p></div>
      </div>
      ${c.open ? `<div class="field" style="margin-top:10px">
          <label>Why this one — required, and recorded in the Change Log</label>
          <input class="cfReason" placeholder="Which source you followed and what settled it">
        </div>
        <div class="acts"><span class="reqnote">Pick a side above, then confirm.</span>
          <button class="primary cfGo" disabled>Resolve</button></div>
        <div class="cfErr"></div>`
      : `<div class="mono" style="font-size:11.5px;color:var(--ink-3);margin-top:8px">
          decided by ${esc(c["Decided By"]||"")} on ${esc(c["Decided At"]||"")}</div>`}
    </div>`).join("");

  list.querySelectorAll(".cf").forEach(card => {
    const go = card.querySelector(".cfGo"); if(!go) return;
    let picked = null;
    card.querySelectorAll(".opt").forEach(opt => opt.onclick = () => {
      picked = opt.dataset.v;
      card.querySelectorAll(".opt").forEach(o => o.classList.toggle("sel", o === opt));
      go.disabled = false;
    });
    go.onclick = async () => {
      const reason = (card.querySelector(".cfReason")||{}).value || "";
      const err = card.querySelector(".cfErr"); err.innerHTML = "";
      go.disabled = true;
      try{
        const d = await api(`/api/conflicts/${encodeURIComponent(card.dataset.id)}/resolve`,
          {method:"POST", headers:{"Content-Type":"application/json"},
           body: JSON.stringify({decision: picked, reason})});
        const ci = S.conflicts.findIndex(x => x.ID === card.dataset.id);
        if(ci >= 0) S.conflicts[ci] = {...d.conflict, opposed: S.conflicts[ci].opposed, open:false};
        const ri = S.chargers.findIndex(x => x.ID === d.charger.ID);
        if(ri >= 0) S.chargers[ri] = d.charger;
        S.conflictStats = d.conflictStats; S.stats = d.stats;
        renderAll(); toast(`Resolved — ${d.charger.Brand} ${d.charger.Model} is ${d.charger["MID Status"]}`);
      }catch(e){ err.innerHTML = `<div class="err">${esc(e.message)}</div>`; go.disabled = false; }
    };
  });
}

/* ───── manifest ───── */
function renderManifest(){
  $("#mTot").textContent = S.manifest.length;
  $("#mGap").textContent = S.gaps.length;
  const noUrl = S.manifest.filter(m => !String(m.Url||"").trim()).length;
  $("#mHave").textContent = S.dl && S.dl.counts
    ? (S.dl.counts.downloaded||0) + (S.dl.counts.skipped||0) : "—";

  $("#gapList").innerHTML = S.gaps.length
    ? S.gaps.slice(0,60).map(g => `
      <div class="qrow">
        <div><div style="font-size:11.5px;color:var(--ink-2)">Brand</div><b>${esc(g.brand)}</b></div>
        <div><div style="font-size:11.5px;color:var(--ink-2)">Model</div>${esc(g.model)}</div>
        <div><div style="font-size:11.5px;color:var(--ink-2)">Type</div>${esc(g.chargeType||"AC")}</div>
        <div style="min-width:0"><div style="font-size:11.5px;color:var(--ink-2)">URL</div>
          <div class="mono" style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(g.url)}</div></div>
        <button class="primary" data-q="${esc(g.id)}" style="height:34px">Queue</button></div>`).join("")
      + (S.gaps.length>60 ? `<div class="mono" style="color:var(--ink-3);font-size:12px">…and ${S.gaps.length-60} more. Use “Queue all gaps”.</div>` : "")
    : `<div class="empty card">No gaps — every datasheet link is queued.</div>`;
  $("#gapList").querySelectorAll("[data-q]").forEach(b =>
    b.onclick = () => queueGaps([b.dataset.q]));

  const q = S.mf.toLowerCase();
  const rows = S.manifest.map((m, i) => ({m, i}))
    .filter(({m}) => !q || Object.values(m).some(v => String(v).toLowerCase().includes(q)));
  $("#mtb2").innerHTML = rows.length
    ? rows.slice(0,400).map(({m, i}) => {
        const r = (S.dlByFile||{})[m.Filename];
        const mark = r
          ? `<span class="badge b-${r.status==="failed"?"None":r.status==="no-url"?"Unknown":"Integrated"}"
               title="${esc(r.detail||"")}"><i></i>${esc(r.status)}</span>` : "";
        return `<tr>
        <td>${esc(m.Brand)}</td><td>${esc(m.Model)}</td>
        <td class="mono" style="font-size:11.5px">${esc(m.SubFolder)}</td>
        <td class="mono" style="font-size:11.5px">${esc(m.Filename)}</td>
        <td class="mono" style="font-size:11.5px;max-width:260px"><div class="clamp">${
          m.Url ? esc(m.Url) : '<span style="color:var(--ink-3)">filed by hand — no public link</span>'}</div></td>
        <td style="white-space:nowrap">${mark}
          <button class="del" data-rm="${i}" title="Remove from the queue">✕</button></td></tr>`;
      }).join("")
    : `<tr><td colspan="6"><div class="empty">Nothing queued.</div></td></tr>`;
  $("#mtb2").querySelectorAll("[data-rm]").forEach(b => b.onclick = () => removeManifest(+b.dataset.rm));
  $("#mNoUrl").textContent = noUrl
    ? `${noUrl} row${noUrl===1?"":"s"} have no public link — filed by hand, not a failure.` : "";
}
$("#mq").oninput = e => { S.mf = e.target.value; renderManifest(); };

async function queueGaps(ids){
  try{
    const d = await api("/api/manifest/queue-gaps", {method:"POST",
      headers:{"Content-Type":"application/json"}, body: JSON.stringify({ids: ids||[]})});
    S.manifest = d.manifest; S.gaps = d.gaps;
    renderManifest(); renderTiles();
    toast(d.added.length ? `Queued ${d.added.length} row${d.added.length===1?"":"s"}` : "Nothing to queue");
  }catch(e){ toast(e.message); }
}
$("#fixGaps").onclick = () => { if(!S.gaps.length) return toast("No gaps to queue."); queueGaps(); };

async function removeManifest(index){
  if(!confirm("Remove this row from the download queue?")) return;
  try{
    const d = await api(`/api/manifest/${index}`, {method:"DELETE"});
    S.manifest = d.manifest;
    const reg = await api("/api/register");
    S.gaps = reg.gaps;
    renderManifest(); renderTiles(); toast("Removed from the queue");
  }catch(e){ toast(e.message); }
}

$("#addManBtn").onclick = async () => {
  const brand = prompt("Brand?"); if(!brand) return;
  const model = prompt("Model?") || "";
  const url = prompt("Datasheet URL (leave blank if filed by hand)") || "";
  const type = (prompt("Charge type — AC, DC or Meter", "AC") || "AC").trim().toUpperCase();
  const sub = type.startsWith("M") ? `Meters\\${brand}`
            : `Chargers\\${type.startsWith("D")?"DC":"AC"} Chargers\\${brand}`;
  const slug = t => String(t).replace(/[^0-9A-Za-z]+/g, "");
  const ext = /\.html?$/i.test(url) ? ".html" : ".pdf";
  try{
    const d = await api("/api/manifest", {method:"POST", headers:{"Content-Type":"application/json"},
      body: JSON.stringify({Brand:brand, Model:model, SubFolder:sub, Url:url,
                            Filename:`${slug(brand)}_${slug(model)}_datasheet${ext}`})});
    S.manifest = d.manifest; renderManifest(); renderTiles(); toast(`Added ${d.row.Filename}`);
  }catch(e){ toast(e.message); }
};

/* ───── downloader ───── */
let dlTimer;
$("#dlBtn").onclick = async () => {
  try{
    const d = await api("/api/download", {method:"POST", headers:{"Content-Type":"application/json"},
                                          body: JSON.stringify({})});
    toast(`Downloading ${d.started} files into ${d.driveRoot}`);
    $("#dlBtn").disabled = true;
    clearInterval(dlTimer); dlTimer = setInterval(pollDownload, 700); pollDownload();
  }catch(e){ toast(e.message); }
};
async function pollDownload(){
  try{
    const d = await api("/api/download/status");
    if(d.idle) return;
    S.dl = d;
    S.dlByFile = {}; (d.results||[]).forEach(r => S.dlByFile[r.filename] = r);
    const c = d.counts || {};
    $("#dlNote").textContent =
      `${d.done}/${d.total} — ${c.downloaded||0} downloaded, ${c.skipped||0} already on disk, ` +
      `${c["no-url"]||0} filed by hand, ${c.failed||0} failed`;
    renderManifest();
    if(!d.running){
      clearInterval(dlTimer); $("#dlBtn").disabled = false;
      const failed = (d.results||[]).filter(r => r.status === "failed");
      toast(failed.length ? `Done — ${failed.length} failed, see the queue` : "Done — all files present");
    }
  }catch(e){ clearInterval(dlTimer); $("#dlBtn").disabled = false; toast(e.message); }
}

/* ───── intake ─────
   Files are stored and read here; the register is only ever changed by a person
   clicking apply on a proposal. */
const KINDS = [["datasheet","Datasheet / product sheet"],["photo","Nameplate photo"],
               ["doc","Declaration of conformity / certificate"],
               ["manual","Installation manual"],["meter","Meter datasheet"],["other","Something else"]];
const SURFACES = [["unsure","Not sure"],["exterior","The outside of the enclosure"],
                  ["meter","The meter itself, cover removed"]];

$("#pick").onclick = () => $("#fInt").click();
$("#fInt").onchange = e => { uploadFiles(Array.from(e.target.files)); e.target.value = ""; };
document.addEventListener("drop", e => {
  if(!e.target.closest(".dz") && !$("#p-intake").classList.contains("on")) return;
  e.preventDefault();
  const files = Array.from(e.dataTransfer.files || []);
  if(files.length){ goTab("intake"); uploadFiles(files); }
});

function guessKind(name){
  if(/\.(jpe?g|png|heic|webp|tiff?)$/i.test(name)) return "photo";
  if(/conform|doc|certif|ce[-_]?verkl|konformit/i.test(name)) return "doc";
  if(/manual|install|handleiding/i.test(name)) return "manual";
  return "datasheet";
}

async function uploadFiles(files){
  for(const f of files){
    const kind = guessKind(f.name);
    const body = new FormData();
    body.append("file", f);
    body.append("kind", kind);
    body.append("brand", "");
    body.append("model", "");
    body.append("surface", kind === "photo" ? "unsure" : "unsure");
    toast(`Reading ${f.name}…`);
    try{
      const res = await fetch("/api/intake", {method:"POST", body});
      const d = await res.json();
      if(!res.ok) throw new Error(d.detail || res.statusText);
      S.intake.push(d);
      renderIntake(); renderTiles();
    }catch(e){ toast(`${f.name}: ${e.message}`); }
  }
}

async function reprocess(id, patch){
  const item = S.intake.find(x => x.id === id); if(!item) return;
  Object.assign(item, patch);
  // Re-run the proposal with the corrected tagging. The file is already stored,
  // so this re-reads the copy in the Drive tree rather than re-uploading.
  const body = new FormData();
  const blob = new Blob([""], {type:"text/plain"});
  toast("Re-reading with the new tagging…");
  try{
    const d = await api(`/api/intake/${id}/reread`, {method:"POST",
      headers:{"Content-Type":"application/json"},
      body: JSON.stringify({kind:item.kind, brand:item.brand, model:item.model,
                            surface:item.surface, chargerId:item.chargerId})});
    Object.assign(item, d);
  }catch(e){ toast(e.message); }
  renderIntake();
}

function evidenceList(list, discounted){
  if(!list.length) return `<div style="color:var(--ink-3);font-size:12.5px">none found</div>`;
  return list.map(m => `<div style="margin-bottom:7px">
      <span class="badge ${discounted?"b-Unknown":"b-Integrated"}"><i></i>${esc(m.matched)}</span>
      <span style="font-size:12px;color:var(--ink-2)"> ${esc(m.detail)}</span>
      ${m.sentence?`<div class="mono" style="font-size:11.5px;color:var(--ink-3);margin-top:3px;
        border-left:2px solid var(--grid);padding-left:8px">“${esc(m.sentence)}”</div>`:""}
    </div>`).join("");
}

function renderIntake(){
  $("#cInt").textContent = S.intake.length;
  $("#intakeEmpty").style.display = S.intake.length ? "none" : "";
  $("#intakeList").innerHTML = S.intake.map(it => {
    const p = it.proposal, ex = it.extraction;
    const diff = p.diff.filter(d => d.changed);
    return `<div class="icard" data-id="${esc(it.id)}">
      <div class="pv">
        <div class="fi"><div style="font-size:26px">▤</div>
          ${esc((it.filename.split(".").pop()||"").toUpperCase())}<br>
          ${ex.characters} chars<br>${esc(ex.method)}</div>
      </div>
      <div class="bd2">
        <div style="display:flex;justify-content:space-between;gap:10px;align-items:flex-start">
          <div class="mono" style="font-size:12px;word-break:break-all">${esc(it.filename)}</div>
          <button class="del" data-rm="${esc(it.id)}" style="height:28px;padding:3px 9px">✕</button></div>

        <div class="note ${p.status==="Unknown"?"warn":""}" style="margin:10px 0">
          <b>Proposed: ${badge(p.status)}</b> — ${esc(p.eligibility)}
          ${p.reasoning.map(r => `<div style="margin-top:6px;font-size:12.5px">${esc(r)}</div>`).join("")}
        </div>

        ${ex.warnings.length ? ex.warnings.map(w =>
          `<div class="note warn" style="font-size:12.5px">${esc(w)}</div>`).join("") : ""}
        ${p.warnings.length ? p.warnings.map(w =>
          `<div class="note" style="font-size:12.5px">${esc(w)}</div>`).join("") : ""}

        <div class="grid3" style="margin-top:10px">
          <div class="field"><label>What is it?</label>
            <select data-k="kind">${KINDS.map(k =>
              `<option value="${k[0]}" ${it.kind===k[0]?"selected":""}>${k[1]}</option>`).join("")}</select></div>
          <div class="field"><label>Brand</label>
            <input data-k="brand" value="${esc(it.brand)}" list="brandList"></div>
          <div class="field"><label>Model</label><input data-k="model" value="${esc(it.model)}"></div>
        </div>
        ${it.kind === "photo" ? `<div class="field" style="margin-top:9px">
          <label>What surface does this photo show? <b>(changes what can be concluded)</b></label>
          <select data-k="surface">${SURFACES.map(sf =>
            `<option value="${sf[0]}" ${it.surface===sf[0]?"selected":""}>${sf[1]}</option>`).join("")}</select>
          </div>` : ""}

        <div class="sechead" style="margin:14px 0 8px"><h2>MID evidence found</h2><div class="ln"></div></div>
        ${evidenceList(p.matched, false)}
        ${p.discounted.length ? `<div class="sechead" style="margin:12px 0 8px">
            <h2>Seen and discounted</h2><div class="ln"></div></div>${evidenceList(p.discounted, true)}` : ""}

        ${p.doc ? `<div class="sechead" style="margin:14px 0 8px"><h2>Declaration of conformity</h2><div class="ln"></div></div>
          <div class="kv"><dt>Certificate</dt><dd>${esc(p.doc.certificate_number||"— not found")}</dd></div>
          <div class="kv"><dt>Issuing body</dt><dd>${esc(p.doc.issuing_body||"— not found")}</dd></div>
          <div class="kv"><dt>Directive cited</dt><dd>${p.doc.directive_cited
            ? '<b style="color:var(--good)">2014/32/EU — this is MID evidence</b>'
            : '<b style="color:var(--critical)">2014/32/EU is NOT cited — this is not MID evidence</b>'}</dd></div>
          <div class="kv"><dt>Models covered</dt><dd>${p.doc.models_covered.length
            ? esc(p.doc.models_covered.join("; ")) : "— not stated"}</dd></div>` : ""}

        <div class="sechead" style="margin:14px 0 8px"><h2>Proposed change</h2><div class="ln"></div></div>
        ${diff.length ? `<table style="font-size:12.5px"><thead><tr><th>Field</th><th>Now</th><th>Proposed</th></tr></thead>
          <tbody>${diff.map(d => `<tr><td><b>${esc(d.field)}</b></td>
            <td class="was">${esc(d.current)||"—"}</td><td>${esc(d.proposed)}</td></tr>`).join("")}</tbody></table>`
          : `<div style="color:var(--ink-3);font-size:12.5px">Nothing would change.</div>`}

        <div class="field" style="margin-top:10px"><label>Link to an existing charger (ID) — leave blank to create a new row</label>
          <input data-k="chargerId" value="${esc(it.chargerId||"")}" placeholder="chg_0006"></div>

        <div class="acts">
          <button class="primary" data-apply="${esc(it.id)}" ${it.applied?"disabled":""}>
            ${it.applied ? "Applied" : "Apply to the register"}</button>
          <span class="reqnote">Stored at <span class="mono">${esc(it.stored.relative)}</span>
            · sha256 ${esc(it.stored.sha256.slice(0,16))}…${it.stored.duplicate_of
              ? ` · identical to a file already filed` : ""}</span>
        </div>
        <div class="applyErr"></div>
      </div></div>`;
  }).join("");

  const wrap = $("#intakeList");
  wrap.querySelectorAll("[data-rm]").forEach(b => b.onclick = async () => {
    await api(`/api/intake/${b.dataset.rm}`, {method:"DELETE"});
    S.intake = S.intake.filter(x => x.id !== b.dataset.rm);
    renderIntake(); renderTiles();
  });
  wrap.querySelectorAll(".icard").forEach(card => {
    const id = card.dataset.id;
    card.querySelectorAll("[data-k]").forEach(el => el.onchange = () => {
      const item = S.intake.find(x => x.id === id);
      item[el.dataset.k] = el.value;
      if(["kind","surface"].includes(el.dataset.k)) reprocess(id, {});
      else renderIntake();
    });
  });
  wrap.querySelectorAll("[data-apply]").forEach(b => b.onclick = async () => {
    const id = b.dataset.apply;
    const item = S.intake.find(x => x.id === id);
    const card = b.closest(".icard");
    const err = card.querySelector(".applyErr"); err.innerHTML = "";
    b.disabled = true;
    try{
      const d = await api(`/api/intake/${id}/apply`, {method:"POST",
        headers:{"Content-Type":"application/json"},
        body: JSON.stringify({chargerId: item.chargerId || "", queueManifest: true})});
      item.applied = true;
      const i = S.chargers.findIndex(x => x.ID === d.row.ID);
      if(i >= 0) S.chargers[i] = d.row; else S.chargers.push(d.row);
      S.stats = d.stats;
      const reg = await api("/api/register");
      S.manifest = reg.manifest; S.gaps = reg.gaps;
      renderAll();
      toast(`Applied to ${d.row.ID}${d.queued.length?" · queued the datasheet":""}`);
    }catch(e){ err.innerHTML = `<div class="err">${esc(e.message)}</div>`; b.disabled = false; }
  });
}
$("#lb").onclick = () => $("#lb").classList.remove("on");

/* ───── boot ───── */
function renderAll(){
  renderTiles(); renderDist(); renderBrands(); renderTable();
  renderMeters(); renderConflicts(); renderManifest(); renderIntake();
}
loadAll();
