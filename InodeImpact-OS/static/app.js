/* InodeImpact OS: small standalone dashboard, no build step or dependencies. */
"use strict";
const $ = (s, root = document) => root.querySelector(s);
const $$ = (s, root = document) => Array.from(root.querySelectorAll(s));
const content = $("#content");
const app = {
  page: "overview", snapshot: null, selected: "config/settings.json", operation: "delete",
  destination: "", replacement: "", plan: null, search: "", type: "all", history: [], diff: null, audits: [], insights: null,
};
const escapeHTML = (s) => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"})[c]);
const num = n => Number(n || 0).toLocaleString();
const size = n => n < 1024 ? `${num(n)} B` : n < 1048576 ? `${(n / 1024).toFixed(1)} KB` : `${(n / 1048576).toFixed(1)} MB`;
const short = (s, limit=31) => s.length > limit ? "…" + s.slice(-limit + 1) : s;
const node = path => app.snapshot?.nodes.find(n => n.path === path);
const kindLabel = n => n.kind === "directory" ? "DIR" : n.kind === "symlink" ? "LINK" : (n.extension || "FILE").replace(".", "").toUpperCase();
let toastTimer;
function notify(message, error=false) {
  const el = $("#toast"); el.textContent = message; el.classList.toggle("error", error);
  el.classList.add("visible"); clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove("visible"), 4500);
}
async function request(url, data) {
  const options = data === undefined ? {} : { method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify(data) };
  let response;
  try { response = await fetch(url, options); }
  catch { throw new Error("Dashboard server is not reachable. Is run.py still running?"); }
  let result;
  try { result = await response.json(); } catch { throw new Error(`Unexpected server response (${response.status})`); }
  if (!response.ok) throw new Error(result.error || `Request failed: ${response.status}`);
  return result;
}
const descriptions = {
  overview: ["System Overview", "Understand what depends on what — before a file operation changes your system."],
  explorer: ["File Explorer", "Inspect real inode metadata, file signatures, and dependency evidence."],
  impact: ["Impact Studio", "Simulate a file operation before deciding whether to execute it."],
  insights: ["Dependency Insights", "Identify central resources, cyclical references, and structural exposure."],
  history: ["Snapshot History", "Track file changes and graph evolution between scans."],
  audit: ["Audit & Recovery", "Review sandbox operations and restore recoverable changes."],
};
function navigate(page) {
  if (!descriptions[page]) return;
  app.page = page;
  $$(".nav-item").forEach(btn => btn.classList.toggle("active", btn.dataset.page === page));
  const [name, desc] = descriptions[page];
  $("#page-title").innerHTML = escapeHTML(name) + '<span class="title-period">.</span>';
  $("#page-description").textContent = desc;
  $("#crumb").textContent = name.toUpperCase();
  render();
  if (page === "history") loadHistory();
  if (page === "audit") loadAudit();
}
function setSnapshot(snapshot) {
  app.snapshot = snapshot;
  app.insights = null;
  $("#workspace-input").value = snapshot.root;
  $("#mode-label").textContent = snapshot.managed ? "MANAGED SANDBOX" : "EXTERNAL READ-ONLY";
  if (!node(app.selected)) app.selected = snapshot.nodes.find(n => n.path === "config/settings.json")?.path || snapshot.nodes.find(n => n.kind === "file")?.path || snapshot.nodes[0]?.path || "";
  app.plan = null;
  render();
  loadInsights(snapshot.snapshot_id);
}
function render() {
  if (!app.snapshot) return;
  if (app.page === "overview") renderOverview();
  else if (app.page === "explorer") renderExplorer();
  else if (app.page === "impact") renderImpact();
  else if (app.page === "insights") renderInsights();
  else if (app.page === "history") renderHistory();
  else if (app.page === "audit") renderAudit();
}
function metric(label, value, caption, symbol) {
  return `<div class="metric"><div class="metric-top"><span class="metric-label">${label}</span><span class="metric-symbol">${symbol}</span></div><div class="metric-number">${value}</div><div class="metric-caption">${caption}</div></div>`;
}
function dependencyCounts() {
  const counts = new Map();
  app.snapshot.nodes.forEach(n => counts.set(n.path, 0));
  app.snapshot.edges.forEach(e => counts.set(e.target, (counts.get(e.target) || 0) + 1));
  return counts;
}
function renderOverview() {
  const snapshot = app.snapshot; const m = snapshot.summary; const counts = dependencyCounts();
  const hot = [...counts.entries()].sort((a,b) => b[1]-a[1]).filter(([p,count]) => count > 0).slice(0,5);
  const hotRows = hot.length ? hot.map(([p,n],i) => `<button class="hot-row" data-open="${escapeHTML(p)}"><span class="hot-rank">0${i+1}</span><span class="hot-details"><div class="hot-name">${escapeHTML(p.split('/').pop())}</div><div class="hot-path">${escapeHTML(p)}</div></span><span class="hot-badge">${n} refs</span></button>`).join("") : '<div class="empty-state">No internal references detected.</div>';
  content.innerHTML = `<div class="metric-grid">
    ${metric("SCANNED NODES",num(m.nodes),`${num(m.files)} files · ${num(m.folders)} folders`,"▤")}
    ${metric("DEPENDENCY EDGES",num(m.dependencies),"Directed source → target links","◇")}
    ${metric("DATA FOOTPRINT",size(m.bytes),"Total scanned regular-file size","◫")}
    ${metric("UNREFERENCED FILES",num(m.orphan_files),"No inbound references found","◌")}
  </div>
  <div class="dash-grid">
    <section class="panel"><div class="panel-head"><div><h2>File dependency network</h2><p class="panel-subtitle">Interactive sample of the current reference graph</p></div><span class="label-tag">LIVE GRAPH</span></div>
      <div class="graph-wrap">${graphMarkup(snapshot)}</div><div class="graph-footer"><span>Click a node to inspect its metadata</span><span class="legend"><span>Linked file</span><span>Selected</span></span></div></section>
    <section class="panel"><div class="panel-head"><div><h2>Dependency hot spots</h2><p class="panel-subtitle">Most referenced paths within this scan</p></div><span class="label-tag">TOP ${hot.length}</span></div><div class="hot-list">${hotRows}</div></section>
  </div>
  <div class="two-panels">
    <div class="panel insight-box"><h3>▰&nbsp; Predict before you operate</h3><p>Selected target: <strong class="code-inline">${escapeHTML(short(app.selected,55))}</strong>. Simulate a delete, move, copy or content modification and see the downstream blast radius. <button class="subtle-link" data-page-link="impact">Open Impact Studio →</button></p></div>
    <div class="panel insight-box"><h3>◈&nbsp; Read-only by default</h3><p>${snapshot.managed ? "You are viewing the disposable demo lab. Operations need confirmation and can be reversed through the audit trail." : "You are viewing a user-selected folder. All operations remain simulation-only; real files cannot be modified from this dashboard."} ${snapshot.warnings.length ? `<strong>${snapshot.warnings.length} scanner warning(s).</strong>` : "No scan errors were reported."}</p></div>
  </div>`;
}
function graphMarkup(snapshot) {
  const counts = dependencyCounts();
  const chosen = [...snapshot.nodes].sort((a,b) => (counts.get(b.path)||0)-(counts.get(a.path)||0)).slice(0,32);
  const paths = new Set(chosen.map(n => n.path));
  const edges = snapshot.edges.filter(e => paths.has(e.source) && paths.has(e.target));
  if (!chosen.length) return '<div class="empty-state">No nodes to visualize.</div>';
  const width=760,height=320,cx=380,cy=155;
  let points = new Map();
  chosen.forEach((n,i) => {
    if (i === 0) points.set(n.path,{x:cx,y:cy});
    else {
      const sector = i <= 12 ? 1 : 2;
      const ringIndex = sector === 1 ? i-1 : i-13;
      const ringTotal = sector === 1 ? Math.min(12, chosen.length-1) : Math.max(1,chosen.length-13);
      const angle = -Math.PI/2 + 2*Math.PI * ringIndex / ringTotal + (sector===2?.09:0);
      points.set(n.path,{x:cx+Math.cos(angle)*(sector===1?112:232),y:cy+Math.sin(angle)*(sector===1?91:137)});
    }
  });
  const lines = edges.map(e => { const a=points.get(e.source),b=points.get(e.target);const sel=e.source===app.selected||e.target===app.selected;return `<line x1="${a.x}" y1="${a.y}" x2="${b.x}" y2="${b.y}" class="${sel?'strong':''}" />`; }).join("");
  const nodes = chosen.map((n,i) => {const p=points.get(n.path), selected=app.selected===n.path, hub=i===0;
    const label = n.path.split('/').pop();
    return `<g class="graph-node ${hub?'hub':''} ${selected?'selected':''}" data-graphpath="${escapeHTML(n.path)}" transform="translate(${p.x} ${p.y})"><title>${escapeHTML(n.path)} · inode ${n.inode}</title><circle r="${hub?15:selected?11:8}"/><text x="0" y="${hub?-23:21}" text-anchor="middle">${escapeHTML(short(label,hub?19:14))}</text></g>`;
  }).join("");
  return `<svg class="graph" role="img" aria-label="Interactive file dependency network" viewBox="0 0 ${width} ${height}" preserveAspectRatio="xMidYMid meet">${lines}${nodes}</svg>`;
}
function renderExplorer() {
  content.innerHTML = `<div class="table-layout"><section class="panel"><div class="panel-head"><div><h2>Indexed file system</h2><p class="panel-subtitle">${num(app.snapshot.nodes.length)} inspected paths · static evidence only</p></div><span class="label-tag">FILE INDEX</span></div><div class="table-tools"><input id="file-search" class="search" placeholder="Search path or extension..." value="${escapeHTML(app.search)}" aria-label="Search files"><select id="file-filter" class="field mini-select"><option value="all">All types</option><option value="file">Files</option><option value="directory">Folders</option><option value="symlink">Links</option></select></div><div class="table-scroll"><table class="data-table"><thead><tr><th>PATH</th><th>TYPE</th><th>SIZE</th><th>INODE</th></tr></thead><tbody id="file-rows"></tbody></table></div></section><section class="panel" id="inspector"></section></div>`;
  $("#file-filter").value=app.type;
  updateRows(); updateInspector();
}
function updateRows() {
  const tbody=$("#file-rows"); if (!tbody) return;
  const terms=app.search.toLowerCase().trim();
  const matches=app.snapshot.nodes.filter(n=>(app.type==="all"||n.kind===app.type)&&n.path.toLowerCase().includes(terms));
  tbody.innerHTML=matches.slice(0,600).map(n=>`<tr data-open="${escapeHTML(n.path)}" class="${app.selected===n.path?'active':''}"><td><span class="file-symbol">${n.kind==='directory'?'▣':n.kind==='symlink'?'↗':'▤'}</span><span class="file-name mono">${escapeHTML(n.path)}</span></td><td><span class="type-pill">${escapeHTML(kindLabel(n))}</span></td><td class="mono">${size(n.size)}</td><td class="mono">${n.inode}</td></tr>`).join("")||'<tr><td colspan="4" class="empty-state">No files matched the filter.</td></tr>';
}
function refList(edges, side) {
  if (!edges.length) return '<p class="muted small">No references found by static analysis.</p>';
  return edges.slice(0,18).map(e=>`<div class="ref-item mono">${escapeHTML(e[side])}<small>${escapeHTML(e.reason)} · ${escapeHTML(short(e.evidence,65))}</small></div>`).join("");
}
function updateInspector() {
  const panel=$("#inspector");if(!panel)return;
  const n=node(app.selected);
  if(!n){panel.innerHTML='<div class="empty-state">Select a path to inspect.</div>';return;}
  const incoming=app.snapshot.edges.filter(e=>e.target===n.path),outgoing=app.snapshot.edges.filter(e=>e.source===n.path);
  const meta=[["INODE ID",n.inode],["HARD LINKS",n.links],["FILE SIZE",size(n.size)],["PERMISSIONS",n.mode],["DEVICE ID",n.device],["MODIFIED",new Date(n.modified*1000).toLocaleDateString()],["KIND",n.kind],["EXTENSION",n.extension||"—"]];
  panel.innerHTML=`<div class="detail-label">NODE INSPECTOR / LIVE METADATA</div><div class="detail-title mono">${escapeHTML(n.path)}</div><div class="action-row"><button class="button button-primary" data-simulate="${escapeHTML(n.path)}">Simulate impact ↗</button>${n.kind==='file'?`<button class="button button-outline" data-preview="${escapeHTML(n.path)}">Preview file</button>`:''}</div><div class="detail-meta">${meta.map(([k,v])=>`<div><small>${k}</small><strong>${escapeHTML(v)}</strong></div>`).join('')}</div><div class="section-kicker">INBOUND DEPENDENCIES (${incoming.length})</div>${refList(incoming,'source')}<div class="section-kicker">OUTBOUND REFERENCES (${outgoing.length})</div>${refList(outgoing,'target')}<div class="section-kicker">CONTENT FINGERPRINT</div><div class="ref-item mono">${n.sha256||'Not hashed (large, non-regular, or unreadable)'}</div><div id="preview-container"></div>`;
}
function selectFile(path, page="explorer") { app.selected=path;app.plan=null;navigate(page); }
function operationButton(op,label,icon) {return `<button class="operation-option ${app.operation===op?'active':''}" data-operation="${op}">${icon}&nbsp; ${label}</button>`;}
function renderImpact() {
  const fileOptions=app.snapshot.nodes.filter(n=>["file","directory","symlink"].includes(n.kind)).map(n=>`<option value="${escapeHTML(n.path)}" ${app.selected===n.path?'selected':''}>${escapeHTML(n.path)}</option>`).join('');
  content.innerHTML=`<div class="impact-grid"><div class="panel form-panel"><h2>Operation preflight</h2><p>Choose a hypothetical operation. Nothing changes during simulation.</p><div class="form-label">OPERATION TYPE</div><div class="operation-options">${operationButton('delete','Delete','⌫')}${operationButton('move','Move / Rename','↗')}${operationButton('copy','Copy','▧')}${operationButton('modify','Modify','✎')}</div><label class="form-label" for="source-select">SOURCE PATH</label><select class="field" id="source-select">${fileOptions}</select>${["move","copy"].includes(app.operation)?`<label class="form-label" for="destination-input">DESTINATION (RELATIVE PATH)</label><input class="field mono" id="destination-input" placeholder="e.g. archive/settings.json" value="${escapeHTML(app.destination)}">`:''}${app.operation==='modify'?`<label class="form-label" for="replacement-input">REPLACEMENT FILE CONTENT (FOR APPLY)</label><textarea class="field textarea" id="replacement-input" placeholder="Enter replacement UTF-8 text...">${escapeHTML(app.replacement)}</textarea>`:''}<div class="form-hint">Dependencies include Python imports, document links, web resources, path literals and symlinks. Scores are explainable heuristics, not proof of safety.</div><button class="button button-primary form-submit" data-action="analyze">Analyze impact ↗</button></div><div class="panel" id="prediction">${app.plan?renderPlan(app.plan):`<div class="prediction-placeholder"><div class="big-icon">◎</div><h3>Ready to predict</h3><p>Select a source and operation, then run the preflight engine to inspect dependent files and a risk assessment.</p></div>`}</div></div>`;
}
function renderInsights() {
  const d = app.insights;
  if (!d) { content.innerHTML = '<section class="panel"><div class="loading"><div class="spinner"></div> Computing reverse graph reachability...</div></section>'; return; }
  const items = d.hotspots;
  const rows = items.map((x, i) => `<tr data-open="${escapeHTML(x.path)}"><td><span class="hot-rank">${String(i+1).padStart(2,'0')}</span> <span class="file-name mono">${escapeHTML(x.path)}</span></td><td>${num(x.direct_consumers)}</td><td>${num(x.transitive_consumers)}</td><td><div class="meter"><span style="width:${x.centrality_index}%"></span></div><small class="meter-label">${x.centrality_index} / 100</small></td><td><button class="button button-outline" data-simulate="${escapeHTML(x.path)}">Preflight</button></td></tr>`).join('');
  const cycleList = d.cycles.length ? d.cycles.map(group => `<li class="insight-item"><span class="cycle-icon">↻</span><span class="mono">${group.map(escapeHTML).join(' → ')}</span></li>`).join('') : '<li class="insight-item">No cyclic dependency groups found in the scanned graph.</li>';
  const hardlinks = d.hardlinks.length ? d.hardlinks.map(group => `<li class="insight-item mono">${group.map(escapeHTML).join(' ⇄ ')}</li>`).join('') : '<li class="insight-item">No shared-inode file groups detected within this workspace.</li>';
  content.innerHTML = `<div class="insight-hero"><div><div class="eyebrow">GRAPH INTELLIGENCE / CURRENT SNAPSHOT</div><h2>Find the files that hold everything together.</h2><p>Rank resources by distinct dependent paths, inspect dependency cycles and export a reproducible analysis for a technical review or viva.</p></div><div class="export-actions"><a class="button button-primary" href="/api/report?format=html" download="inodeimpact-report.html">Export HTML report ↓</a><a class="button button-outline" href="/api/report?format=json" download="inodeimpact-report.json">Export JSON ↓</a></div></div>
  <div class="metric-grid insight-metrics">
    ${metric('REFERENCED RESOURCES',num(d.summary.resources_with_consumers),'Resources with at least one consumer','◇')}
    ${metric('ISOLATED FILES',num(d.summary.isolated_files),'No incoming or outgoing references','◌')}
    ${metric('CYCLIC GROUPS',num(d.summary.cyclic_groups),'Strongly connected components','↻')}
    ${metric('HARDLINK GROUPS',num(d.summary.hardlink_groups),'Shared inode and device identity','⌁')}
  </div>
  <section class="panel"><div class="panel-head"><div><h2>High-leverage dependency hotspots</h2><p class="panel-subtitle">Sorted by total reachable consumers · static graph</p></div><span class="label-tag">TOP ${items.length}</span></div><div class="table-scroll"><table class="data-table insight-table"><thead><tr><th>RESOURCE PATH</th><th>DIRECT</th><th>INDIRECT</th><th>CENTRALITY</th><th>OPERATION</th></tr></thead><tbody>${rows||'<tr><td colspan="5" class="empty-state">No dependency hotspots identified.</td></tr>'}</tbody></table></div></section>
  <div class="insight-columns"><section class="panel insight-detail"><h2>Reference cycles</h2><p class="muted small">Files in the same cyclic group can depend on each other.</p><ul class="insight-items">${cycleList}</ul></section><section class="panel insight-detail"><h2>Hardlink relationships</h2><p class="muted small">Different paths may share an underlying inode and device.</p><ul class="insight-items">${hardlinks}</ul></section></div>
  <div class="insight-footnote"><strong>Interpretation.</strong> ${escapeHTML(d.method)} ${escapeHTML(d.limitations)} ${d.summary.warnings?`<strong>${d.summary.warnings} scanner warning(s).</strong>`:'No scanner warnings were reported.'}</div>`;
}
async function loadInsights(snapshotId) {
  try {
    const result = await request('/api/insights');
    if (!app.snapshot || app.snapshot.snapshot_id !== snapshotId) return;
    app.insights = result;
    if (app.page === 'insights') renderInsights();
  } catch (e) {
    if (app.page === 'insights') content.innerHTML = `<div class="empty-state">Could not load insights: ${escapeHTML(e.message)}</div>`;
  }
}
function renderPlan(plan) {
  const color={CRITICAL:'#f07b83',HIGH:'#efac75',MODERATE:'#eacc74',LOW:'#55d8bf'}[plan.risk_level];
  const files=plan.affected.slice(0,24);
  const summaries=plan.notes.map(x=>`<li>${escapeHTML(x)}</li>`).join("");
  const canApply=plan.can_apply && node(plan.source)?.kind !== "symlink" && (plan.operation!=="modify" || node(plan.source)?.kind==="file");
  return `<div class="prediction-body"><div class="detail-label">PREFLIGHT RESULT / STATIC ANALYSIS</div><div class="risk-top"><div class="risk-ring" style="--risk-color:${color};--risk-score:${plan.risk_score}"><div class="risk-inner"><strong>${plan.risk_score}</strong><small>RISK / 100</small></div></div><div><div class="risk-name" style="--risk-color:${color}">${escapeHTML(plan.risk_level)} RISK</div><div class="risk-summary">${escapeHTML(plan.operation.toUpperCase())} · ${escapeHTML(short(plan.source,44))}<br>${num(plan.files_in_scope)} path(s) in scope · ${size(plan.bytes_in_scope)}</div></div></div>
  <div class="risk-metrics"><div><strong>${plan.direct_dependents.length}</strong><small>Direct dependents</small></div><div><strong>${plan.transitive_dependents.length}</strong><small>Transitive</small></div><div><strong>${plan.incoming_edges.length}</strong><small>Inbound edges</small></div></div>
  <div class="divider"></div><div class="section-kicker">PREDICTED IMPACT / ${plan.affected.length} EXTERNAL PATHS</div>${files.length?`<ul class="impact-list">${files.map(p=>`<li class="mono">${escapeHTML(p)}<span>${(plan.impact_levels[p]||1)===1?'DIRECT CONSUMER':'INDIRECT / '+plan.impact_levels[p]+' HOPS'}</span></li>`).join('')}</ul>`:'<p class="muted small">No existing consumers are expected to lose their reference to the original path.</p>'}
  <details class="details-disclosure"><summary>How this risk score was calculated</summary><div class="factor-list">${Object.entries(plan.risk_factors||{}).map(([key,value])=>`<div><span>${escapeHTML(key.replace(/_/g,' '))}</span><strong>+${value}</strong></div>`).join('')}</div><p class="muted small">Factor totals are capped at 100 and are not probabilities.</p></details>
  ${(plan.dependency_paths||[]).length?`<details class="details-disclosure" open><summary>Trace why files are affected (${plan.dependency_paths.length} examples)</summary><div class="trace-list">${plan.dependency_paths.slice(0,8).map(entry=>`<div class="trace-item"><div class="mono trace-chain">${entry.chain.map(escapeHTML).join(' <span>→</span> ')}</div><small>${entry.evidence.map(e=>`${escapeHTML(e.reason)}: ${escapeHTML(short(e.evidence,60))}`).join(' · ')}</small></div>`).join('')}</div></details>`:''}
  <div class="section-kicker">ANALYSIS NOTES</div><ul class="bullet-list">${summaries}</ul><div class="section-kicker">RECOMMENDED SAFEGUARDS</div><ul class="bullet-list">${plan.recommendations.map(x=>`<li>${escapeHTML(x)}</li>`).join('')}</ul>
  <div class="warning-banner ${canApply?'success-banner':''}">${canApply?'Execution is limited to the disposable managed demo workspace. A recovery record is created for applicable actions.':'Simulation only for this location or file type. External scan roots cannot be mutated.'}</div>
  <button class="button ${plan.risk_score>=50?'button-danger':'button-primary'}" style="width:100%" data-action="apply" ${canApply?'':'disabled'}>${plan.destructive?'Confirm sandbox deletion':'Apply in sandbox'} ↗</button><p class="muted small">${escapeHTML(plan.confidence)}</p></div>`;
}
function renderHistory() {
  const h=app.history;
  const opts=(selected)=>h.map(item=>`<option value="${item.id}" ${selected===item.id?'selected':''}>#${item.id} · ${escapeHTML(new Date(item.scanned_at).toLocaleString())} · ${item.nodes} nodes</option>`).join("");
  const old=app.diff?.old_id??h[1]?.id??h[0]?.id,newer=app.diff?.new_id??h[0]?.id;
  content.innerHTML=`<section class="panel"><div class="panel-head"><div><h2>Compare file-system states</h2><p class="panel-subtitle">Snapshots saved locally with SQLite · current root only</p></div><span class="label-tag">${h.length} VERSIONS</span></div><div class="history-controls"><div><label>BASELINE SNAPSHOT</label><select id="old-select" class="field">${opts(old)}</select></div><div><label>NEW SNAPSHOT</label><select id="new-select" class="field">${opts(newer)}</select></div><button class="button button-secondary" data-action="compare" ${h.length<2?'disabled':''}>Compare ↗</button></div><p class="history-note">Scan again after editing a monitored folder to compare file additions, deletions, changed content and dependency edges.</p></section><div style="height:18px"></div>${app.diff?diffMarkup(app.diff):'<section class="panel"><div class="empty-state">At least two snapshots are needed for comparison. Click “Rescan” to add one.</div></section>'}`;
}
function diffMarkup(diff) {
  const cols=[["ADDED PATHS",diff.added,'#63d7b6'],["REMOVED PATHS",diff.removed,'#f29c91'],["CHANGED PATHS",diff.changed,'#f0c27a']];
  return `<section class="panel"><div class="panel-head"><div><h2>Change summary</h2><p class="panel-subtitle">Snapshot #${diff.old_id} → #${diff.new_id}</p></div><span class="label-tag">+${diff.new_edges} / −${diff.removed_edges} EDGES</span></div><div class="changes-grid">${cols.map(([title,files,color])=>`<div class="change-column"><h3>${title}<span class="change-number" style="color:${color}">${files.length}</span></h3>${files.length?files.slice(0,35).map(p=>`<div class="change-path mono">${escapeHTML(p)}</div>`).join(''):'<div class="muted small">No changes</div>'}</div>`).join('')}</div></section>`;
}
function renderAudit() {
  const undone=new Set(app.audits.filter(a=>a.action==='undo').map(a=>a.details.undo_of));
  const html=app.audits.map(e=>{
    const applicable=e.action.startsWith('apply:') && !undone.has(e.id) && app.snapshot.managed;
    return `<div class="audit-row"><div class="audit-main"><strong>${escapeHTML(e.action.toUpperCase())}</strong><span class="status-pill">${escapeHTML(e.risk)}</span><div class="audit-meta mono">${escapeHTML(e.source)}${e.destination?' → '+escapeHTML(e.destination):''} · ${escapeHTML(new Date(e.created_at).toLocaleString())}</div></div><div class="audit-actions"><span class="audit-id">#${e.id}</span>${applicable?`<button class="button button-outline" data-undo="${e.id}">Undo</button>`:''}${undone.has(e.id)?'<span class="status-pill">REVERSED</span>':''}</div></div>`;
  }).join('');
  content.innerHTML=`<section class="panel"><div class="panel-head"><div><h2>Sandbox operation ledger</h2><p class="panel-subtitle">Recorded state changes and recovery actions · newest first</p></div><span class="label-tag">${app.audits.length} EVENTS</span></div>${app.audits.length?html:'<div class="empty-state">No operations have been applied. Try the Impact Studio on the demo workspace.</div>'}</section><div style="height:18px"></div><section class="panel insight-box"><h3>Recovery behavior and limitations</h3><p><strong>Delete</strong> moves demo objects into a recoverable backing store; <strong>Modify</strong> backs up text files; <strong>Move</strong> reverses the rename; and <strong>Copy</strong> removes its new destination. Undo can fail safely if another file now occupies a required path. Undo refuses to overwrite modified content. The history is a teaching tool, not a production filesystem transaction log.</p></section>`;
}
async function loadHistory() {
  try {
    app.history=(await request('/api/history')).snapshots;
    app.diff=app.history.length>1?await request('/api/diff'):null;
    if(app.page==='history')renderHistory();
  }catch(e){notify(e.message,true);}
}
async function loadAudit() {
  try {app.audits=(await request('/api/audit')).events;if(app.page==='audit')renderAudit();}
  catch(e){notify(e.message,true);}
}
async function scanWorkspace(root) {
  const btn=$("#scan-button"),quick=$("#scan-quick");btn.disabled=true;quick.disabled=true;
  try {const result=await request('/api/scan',{root});setSnapshot(result);notify(`Scan complete: ${result.summary.nodes} nodes, ${result.summary.dependencies} dependencies.`);}
  catch(e){notify(e.message,true);}
  finally{btn.disabled=false;quick.disabled=false;}
}
async function analyzePlan() {
  try {
    if(!app.selected)throw new Error('Select a source file first');
    app.plan=await request('/api/simulate',{operation:app.operation,source:app.selected,destination:app.destination});
    $('#prediction').innerHTML=renderPlan(app.plan);
    notify(`Impact estimate: ${app.plan.risk_level} (${app.plan.risk_score}/100).`);
  }catch(e){app.plan=null;notify(e.message,true);}
}
async function applyPlan() {
  if(!app.plan||!app.plan.can_apply)return;
  const label=`${app.plan.operation.toUpperCase()} ${app.plan.source}`;
  if(!window.confirm(`Apply ${label} inside the managed demo workspace?\n\nRisk: ${app.plan.risk_level} (${app.plan.risk_score}/100).\nThis may break demo references; use Audit & Recovery to undo.`))return;
  try {
    const p=app.plan;
    const data=await request('/api/apply',{operation:p.operation,source:p.source,destination:p.destination,content:app.replacement,confirm:true});
    setSnapshot(data.snapshot);
    notify(`Sandbox operation applied. Audit #${data.audit_id} can be reversed.`);
    navigate('audit');
  } catch(e){notify(e.message,true);}
}
async function undo(id) {
  if(!window.confirm(`Undo recorded sandbox operation #${id}?`))return;
  try {const data=await request('/api/undo',{audit_id:id,confirm:true});setSnapshot(data.snapshot);await loadAudit();notify(`Reversed operation #${id}.`);}
  catch(e){notify(e.message,true);}
}
async function resetDemo() {
  if(!window.confirm('Reset the managed demo folder to its original 20 sample files?\n\nThis erases modifications made within demo_workspace. External folders are untouched.'))return;
  try {const data=await request('/api/demo/reset',{confirm:true});setSnapshot(data.snapshot);navigate('overview');notify('Demo workspace restored.');}
  catch(e){notify(e.message,true);}
}
async function viewFile(path) {
  try {const data=await request(`/api/view?path=${encodeURIComponent(path)}`);const target=$('#preview-container');if(target)target.innerHTML=`<div class="section-kicker">TEXT PREVIEW (FIRST 16,000 CHARACTERS)</div><pre class="preview">${escapeHTML(data.text)}</pre>`;}
  catch(e){notify(e.message,true);}
}
// Event delegation avoids rebinding listeners after each page render.
content.addEventListener('click', e=>{
  const btn=e.target.closest('[data-page-link],[data-open],[data-graphpath],[data-simulate],[data-preview],[data-operation],[data-action],[data-undo]');
  if(!btn)return;
  if(btn.dataset.pageLink){navigate(btn.dataset.pageLink);return;}
  if(btn.dataset.open!==undefined||btn.dataset.graphpath!==undefined){selectFile(btn.dataset.open??btn.dataset.graphpath);return;}
  if(btn.dataset.simulate!==undefined){selectFile(btn.dataset.simulate,'impact');return;}
  if(btn.dataset.preview!==undefined){viewFile(btn.dataset.preview);return;}
  if(btn.dataset.operation){app.operation=btn.dataset.operation;app.plan=null;renderImpact();return;}
  if(btn.dataset.undo){undo(Number(btn.dataset.undo));return;}
  if(btn.dataset.action==='analyze')analyzePlan();
  if(btn.dataset.action==='apply')applyPlan();
  if(btn.dataset.action==='compare'){
    const a=Number($('#old-select').value),b=Number($('#new-select').value);
    request(`/api/diff?old=${a}&new=${b}`).then(diff=>{app.diff=diff;renderHistory();}).catch(e=>notify(e.message,true));
  }
});
content.addEventListener('input', e=>{
  if(e.target.id==='file-search'){app.search=e.target.value;updateRows();}
  if(e.target.id==='destination-input'){app.destination=e.target.value;app.plan=null;}
  if(e.target.id==='replacement-input'){app.replacement=e.target.value;}
});
content.addEventListener('change', e=>{
  if(e.target.id==='file-filter'){app.type=e.target.value;updateRows();}
  if(e.target.id==='source-select'){app.selected=e.target.value;app.plan=null;}
});
$$('.nav-item').forEach(button=>button.addEventListener('click',()=>navigate(button.dataset.page)));
$('#scan-button').addEventListener('click',()=>scanWorkspace($('#workspace-input').value));
$('#scan-quick').addEventListener('click',()=>scanWorkspace($('#workspace-input').value));
$('#demo-button').addEventListener('click',resetDemo);
$('#workspace-input').addEventListener('keydown',e=>{if(e.key==='Enter')scanWorkspace(e.target.value);});
$('#clock').textContent=new Date().toLocaleDateString(undefined,{month:'short',day:'numeric',year:'numeric'}).toUpperCase();
request('/api/overview').then(snapshot=>{setSnapshot(snapshot);}).catch(e=>{content.innerHTML=`<div class="empty-state">Failed to load the engine: ${escapeHTML(e.message)}</div>`;notify(e.message,true);});
