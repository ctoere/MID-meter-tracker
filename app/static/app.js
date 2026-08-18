"use strict";
/* Zeres MID Register — UI.
   Descended from the single-file prototype; the layout, colour semantics and copy
   are kept. The difference is that the data comes from the local API instead of
   being parsed in the browser, and edits are written back to the workbook. */

const S = { chargers:[], meters:[], conflicts:[], manifest:[], gaps:[], stats:{}, meta:{},
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
                      manifest:d.manifest, gaps:d.gaps, stats:d.stats, meta:d.meta});
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

/* ───── conflicts ───── */
function opposed(c){
  const el = v => ["Integrated","Optional","External"].includes(v);
  return (el(c["Tracker says"]) && c["Zite says"]==="None") ||
         (el(c["Zite says"]) && c["Tracker says"]==="None");
}
function renderConflicts(){
  const list = $("#cfList");
  const open = S.conflicts.filter(c => !String(c.Decision||"").trim()).length;
  $("#cfCount").textContent = S.conflicts.length
    ? `${open} open · ${S.conflicts.length-open} resolved of ${S.conflicts.length}` : "";
  if(!S.conflicts.length){
    list.innerHTML = `<div class="empty card">No conflict rows in this register.
      The Conflicts sheet exists and is empty — nothing has been auto-resolved.</div>`;
    return;
  }
  list.innerHTML = S.conflicts.map(c => `
    <div class="cf ${opposed(c)?"opposed":""} ${c.Decision?"resolved":""}" data-id="${esc(c.ID)}">
      <div class="hd"><b>${esc(c.Brand)} — ${esc(c.Model)}</b>
        <span>${opposed(c)?'<span class="badge b-None"><i></i>opposed</span> ':""}${
          c.Decision?`<span class="badge b-Integrated"><i></i>resolved: ${esc(c.Decision)}</span>`:""}</span></div>
      <div class="opts">
        <div class="opt ${c.Decision===c["Tracker says"]?"sel":""}" data-v="${esc(c["Tracker says"])}">
          <div class="src">Research tracker</div>${badge(c["Tracker says"])}
          <p>${esc(String(c["Tracker note"]||"").slice(0,240))||"no note"}</p></div>
        <div class="opt ${c.Decision===c["Zite says"]?"sel":""}" data-v="${esc(c["Zite says"])}">
          <div class="src">Zite dashboard <span class="mono">(${esc(c["Zite original value"]||"")})</span></div>${badge(c["Zite says"])}
          <p>${esc(String(c["Zite note"]||"").slice(0,240))||"no note"}</p></div>
      </div></div>`).join("");
}

/* ───── manifest ───── */
function renderManifest(){
  $("#mTot").textContent = S.manifest.length;
  $("#mGap").textContent = S.gaps.length;
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

  const q = S.mf.toLowerCase();
  const all = S.manifest.filter(m => !q || Object.values(m).some(v => String(v).toLowerCase().includes(q)));
  $("#mtb2").innerHTML = all.length
    ? all.slice(0,400).map(m => `<tr>
        <td>${esc(m.Brand)}</td><td>${esc(m.Model)}</td>
        <td class="mono" style="font-size:11.5px">${esc(m.SubFolder)}</td>
        <td class="mono" style="font-size:11.5px">${esc(m.Filename)}</td>
        <td class="mono" style="font-size:11.5px;max-width:280px"><div class="clamp">${
          m.Url ? esc(m.Url) : '<span style="color:var(--ink-3)">filed by hand — no public link</span>'}</div></td>
        <td></td></tr>`).join("")
    : `<tr><td colspan="6"><div class="empty">Nothing queued.</div></td></tr>`;
}
$("#mq").oninput = e => { S.mf = e.target.value; renderManifest(); };

/* ───── intake (staging only until phase 5) ───── */
$("#pick").onclick = () => $("#fInt").click();
["dragenter","dragover"].forEach(e => document.addEventListener(e, ev => {
  ev.preventDefault(); const t = ev.target.closest(".dz"); if(t) t.classList.add("hot"); }));
["dragleave","drop"].forEach(e => document.addEventListener(e, ev => {
  const t = ev.target.closest(".dz"); if(t) t.classList.remove("hot"); }));
$("#lb").onclick = () => $("#lb").classList.remove("on");

/* ───── boot ───── */
function renderAll(){
  renderTiles(); renderDist(); renderBrands(); renderTable();
  renderMeters(); renderConflicts(); renderManifest();
}
loadAll();
