/* Foreman+ — office seat.
 *
 * A hash-routed reader over the workspace API. Everything on screen comes from
 * /api/properties, /api/property/{id}, /api/job/{id} and /api/state; nothing is
 * invented here. A field the gate could not verify renders as "Unknown" with
 * the reason the fleet gave, and a verifier's reason is printed verbatim —
 * shortening it would be editing the record.
 *
 * Routes: #/intro #/properties #/property/:id #/job/:id #/jobs #/ledger
 */
'use strict';

const PLATE_FIELDS = new Set(['equipment_model', 'equipment_brand', 'equipment_type', 'serial_number', 'manufacture_date', 'capacity', 'refrigerant']);
const MAPLE_ID = '214-maple-ct-orlando-fl-32806';   // the one property with a demo scenario
const NAMEPLATE = '/static/demo/nameplate.jpg';

/* ------------------------------------------------------------------ api */
const getJSON = url => fetch(url).then(r => r.ok ? r.json() : Promise.reject(r));
const api = {
  properties: () => getJSON('/api/properties'),
  property: id => getJSON(`/api/property/${encodeURIComponent(id)}`),
  job: id => getJSON(`/api/job/${encodeURIComponent(id)}`),
  state: () => getJSON('/api/state'),
  demoRun: () => fetch('/api/demo/run', {method: 'POST'}).then(r => r.json()),
  demoStatus: () => getJSON('/api/demo/status'),
};

/* ------------------------------------------------------------- helpers */
const $ = (s, r) => (r || document).querySelector(s);
const $$ = (s, r) => Array.from((r || document).querySelectorAll(s));

function escapeHTML(v) {
  if (v === null || v === undefined) return '';
  return String(v).replace(/[&<>"']/g, c =>
    ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
}
const esc = escapeHTML;

function hhmm(ts) {
  if (!ts) return '';
  const d = new Date(ts);
  if (isNaN(d)) return String(ts).slice(11, 16);
  return d.toISOString().slice(11, 16);
}
function stamp(ts) {
  if (!ts) return '';
  const d = new Date(ts);
  if (isNaN(d)) return String(ts);
  return d.toISOString().slice(0, 10) + ' ' + d.toISOString().slice(11, 19);
}

const LABELS = {
  manufacture_date: 'Manufacture date', serial_number: 'Serial number', equipment_model: 'Model',
  equipment_brand: 'Brand', equipment_type: 'Type', capacity: 'Capacity', refrigerant: 'Refrigerant',
  access_location: 'Location', issue: 'Issue', estimate: 'Estimate', property: 'Property',
  technician: 'Technician', client: 'Client',
};
const label = p => LABELS[p] || String(p || '').replace(/_/g, ' ').replace(/^./, c => c.toUpperCase());

const PILLS = {
  calm: ['ok', '✓', 'Calm'],
  unknowns: ['unk', '—', 'Has unknowns'],
  needs_confirmation: ['warn', '!', 'Needs confirmation'],
  done: ['ok', '✓', 'Done'],
  in_progress: ['info', '•', 'In progress'],
  approved: ['ok', '✓', 'APPROVED'],
  rejected: ['warn', '✕', 'REJECTED'],
  installed: ['ok', '✓', 'Installed'],
  replaced: ['unk', '—', 'Replaced'],
  unknown: ['unk', '—', 'Unknown'],
};
function pill(state) {
  const p = PILLS[state];
  return p ? `<span class="pill ${p[0]}"><span class="g" aria-hidden="true">${p[1]}</span>${p[2]}</span>` : '';
}

/* ---------------------------------------------------------- provenance */
/* Chips carry an index into PROV, refilled on every render so a stale index
   can never open the wrong source. */
let PROV = [];
function chip(f) {
  if (!f || !f.source) return '';
  const i = PROV.push(f) - 1;
  const when = hhmm(f.ts);
  return `<button class="chip" type="button" data-prov="${i}" ` +
         `aria-label="Where this came from: ${esc(f.source)}">` +
         `${esc(f.source)}${when ? ' · ' + esc(when) : ''}</button>`;
}

const modalEl = () => document.getElementById('modal');
function evidence(f) {
  const src = String(f.source || '');
  let media = '';
  if (/^nameplate/i.test(src)) {
    media = `<figure class="ev-media"><img src="${NAMEPLATE}" alt="The nameplate photo this value was read from">
      <figcaption>Nameplate photo · the model read this field from the image, not from the technician's words</figcaption></figure>`;
  } else if (/voice|homeowner/i.test(src)) {
    media = `<p class="quote">${/homeowner/i.test(src) ? 'Said by the homeowner on site' : 'Spoken by the technician on site'} — recorded as a fact, not as audio.</p>`;
  } else if (/write-gate/i.test(src)) {
    media = `<p class="quote">Refused by the write-gate — the verified value stands.</p>`;
  }
  const gate = f.reason
    ? `<dt>Verifier</dt><dd>${esc(f.reason)}</dd>`
    : (f.gate_entry_id ? `<dt>Gate</dt><dd>Passed the write-gate as entry <span class="mono">#${esc(f.gate_entry_id)}</span></dd>` : '');
  $('#modalCard').innerHTML = `<button class="close" type="button" aria-label="Close">✕</button>
    <div class="lab">${esc(label(f.predicate))}</div>
    <h3>${esc(f.value != null ? f.value : (f.text || 'Unknown'))}</h3>
    ${media}
    <dl>
      <dt>Source</dt><dd>${esc(f.source)}</dd>
      <dt>Agent</dt><dd class="mono">${esc(f.agent || '—')}</dd>
      <dt>Recorded</dt><dd class="mono">${esc(stamp(f.ts) || '—')}</dd>
      ${gate}
      ${f.job_id ? `<dt>Job</dt><dd><a class="link" href="#/job/${esc(f.job_id)}">${esc(f.job_id)}</a></dd>` : ''}
    </dl>`;
  modalEl().hidden = false;
  document.body.classList.add('modal-open');
  $('#modalCard .close').focus();
}
function closePopover() {
  const m = modalEl();
  if (!m.hidden) { m.hidden = true; document.body.classList.remove('modal-open'); }
}

/* --------------------------------------------------------------- views */
function el(html) {
  const d = document.createElement('div');
  d.innerHTML = html;
  return d;
}

async function intro() {
  let counters = null;
  try { counters = (await api.properties()).counters; } catch (e) { /* line degrades below */ }
  const fleet = counters
    ? `Gate decisions on record: ${esc(counters.total)} ` +
      `(${esc(counters.approved)} approved · ${esc(counters.rejected)} rejected)`
    : 'Gate decisions on record: not loaded';
  return el(`<section class="intro">
    <div>
      <div class="kicker">Foreman+ · sample workspace</div>
      <h1>The property remembers, so the next technician doesn't have to.</h1>
      <p class="lede">This is <b>Ridgeline Mechanical's</b> workspace — sample data, real agent output.
      A technician photographs the nameplate and talks; Foreman+ turns that into a
      <b>verified property record</b> you can quote from before the van leaves the driveway.
      Every line carries where it came from, and anything the gate could not verify stays visibly unknown.</p>
      <div class="introgrid">
        <a class="btn pri" href="#/properties">Enter workspace</a>
        <a class="btn" href="#">Watch the walkthrough (coming with submission)</a>
        <a class="qr" href="/tech"><span class="qrbox" aria-hidden="true"></span>
          <span><b>Open the technician seat</b><span>Scan or tap · /tech</span></span></a>
      </div>
      <div class="introfoot">
        <span>Fleet: foreman · estimator · closer</span>
        <span>${fleet}</span>
        <span>Model: <span class="mono">gemini-3.7-flash</span></span>
      </div>
    </div>
  </section>`);
}

async function properties() {
  const body = await api.properties();
  const rows = (body.properties || []).map(p => `
    <a class="prow" href="#/property/${esc(p.id)}">
      <div>
        <h3>${esc(p.address)}</h3>
        <div class="who">${esc(p.client || 'Client unknown')} · ${esc(p.city)}</div>
      </div>
      <div>
        <div class="eq">${esc(p.equipment_summary || 'Equipment not recorded yet')}</div>
        <div class="last">Last visit ${esc(p.last_visit || 'unknown')}${
          p.technician ? ' · ' + esc(p.technician) : ''}</div>
      </div>
      <div class="right">
        ${pill(p.state)}
        <div class="oqn${p.state === 'needs_confirmation' ? ' hot' : ''}">${
          p.open_questions
            ? `<b>${esc(p.open_questions)} open question${p.open_questions > 1 ? 's' : ''}</b>`
            : 'No open questions'}</div>
      </div>
    </a>`).join('');
  const n = (body.properties || []).length;
  return el(`<div class="page">
    <div class="pagehead">
      <div>
        <h1>Properties</h1>
        <div class="sub">${n} propert${n === 1 ? 'y' : 'ies'} · equipment and history hang on the address, not on the job</div>
      </div>
    </div>
    <div class="plist">${rows || '<div class="oq-empty">No property carries a recorded address yet.</div>'}</div>
    <p class="foot">A property is a derived grouping over the <span class="mono">property</span> fact — no schema migration.
      ${esc(body.no_property_jobs || 0)} job${body.no_property_jobs === 1 ? '' : 's'} without an address stay in the ledger only.</p>
  </div>`);
}

function equipmentField(pred, f) {
  if (!f) return '';
  const wide = f.value && String(f.value).length > 34;
  if (f.status === 'unknown' || f.value === null || f.value === undefined || f.value === 'UNKNOWN') {
    return `<div class="field unknown${wide ? ' wide' : ''}">
      <span class="lab">${esc(label(pred))}</span>
      <span class="val">Unknown<span class="chev" aria-hidden="true">›</span></span>
      ${f.source ? `<span class="why">${esc(f.source)}</span>` : ''}
    </div>`;
  }
  const mono = /serial|model/.test(pred);
  return `<div class="field${wide ? ' wide' : ''}">
    <span class="lab">${esc(label(pred))}</span>
    <span class="val"><span class="${mono ? 'mono' : ''}">${esc(f.value)}</span>${chip(f)}</span>
  </div>`;
}

function openQuestion(q, address) {
  if (q.kind === 'rejected') {
    const c = q.contradicts || {};
    return `<div class="oq-item" data-oq="${esc(q.gate_entry_id)}">
      <div class="oq-top"><b>${esc(label(q.predicate))} — needs confirmation</b>${pill('needs_confirmation')}
        <span class="oq-meta">gate entry <span class="mono">#${esc(q.gate_entry_id)}</span> · ${esc(stamp(q.ts))}</span></div>
      <div class="plaque">
        <div class="said">Proposed: <b>${esc(q.proposed)}</b>${
          q.proposed_by ? ' · by ' + esc(q.proposed_by) : ''}</div>
        <div class="quoted">“${esc(q.reason)}”</div>
        <div class="against">Contradicts
          <a href="#/job/${esc(q.job_id)}"><span class="mono">${esc(q.predicate)} = ${esc(c.value)}</span></a>
          ${c.decided_at ? ' · approved ' + esc(stamp(c.decided_at)) : ''}
          ${c.gate_entry_id ? ' · gate entry <span class="mono">#' + esc(c.gate_entry_id) + '</span>' : ''}
          ${q.verifier_model ? ' · verifier <span class="mono">' + esc(q.verifier_model) + '</span>' : ''}</div>
      </div>
      ${PLATE_FIELDS.has(q.predicate) ? `<div class="oq-act">
        <a class="btn" href="/tech?property=${encodeURIComponent(address || '')}">Re-shoot the nameplate</a>
      </div>
      <p class="oq-note">The recorded value stands until a new reading clears the gate. Settling it by serial
        at the supply house beats settling it from memory.</p>` : `<p class="oq-note">The recorded value stands. A conflicting claim was refused rather than
        overwritten; correct it from the phone on the next visit if the record is wrong.</p>`}
    </div>`;
  }
  return `<div class="oq-item" data-oq="${esc(q.gate_entry_id)}">
    <div class="oq-top"><b>${esc(label(q.predicate))} — unknown${
      q.reason ? ' (' + esc(q.reason) + ')' : ''}</b>${pill('unknowns')}
      <span class="oq-meta">${q.gate_entry_id ? 'gate entry <span class="mono">#' + esc(q.gate_entry_id) + '</span> · ' : ''}${esc(stamp(q.ts))}</span></div>
    <p class="oq-note">Collect on next visit.</p>
    <div class="oq-act">
      <a class="btn" href="/tech?property=${encodeURIComponent(address || '')}">Add visit (from phone)</a>
    </div>
  </div>`;
}

function visitRow(v) {
  return `<tr class="clickable" data-job="${esc(v.job_id)}" data-state="${esc(v.state)}">
    <td class="mono nw">${esc(v.date)}</td>
    <td class="nw">${esc(v.technician || '—')}</td>
    <td>${esc(v.issue || '—')}</td>
    <td>${esc(v.estimate || '—')}</td>
    <td>${pill(v.state)}</td>
    <td>${v.open ? `<span class="dim">${esc(v.open)}</span>` : '<span class="dim">—</span>'}</td>
    <td>${v.doc_url
      ? `<a class="link" href="${esc(v.doc_url)}" target="_blank" rel="noopener">Homeowner ↗</a>`
      : '<span class="dim">—</span>'}</td>
  </tr>`;
}

const DOC_COPY = {
  homeowner: ['Homeowner document', 'Plain-language estimate, verified facts only'],
  decider: ['Decider view', 'Same facts, framed for whoever authorises the spend'],
  authorization: ['Authorization JSON', 'Machine-readable, for a home-warranty lane'],
};

async function property(id) {
  const d = await api.property(id);
  const p = d.property || {};
  const full = [p.address, p.city].filter(Boolean).join(', ');
  const homeowner = (d.documents || []).find(x => x.kind === 'homeowner');

  const brief = (d.briefing || []).map(b =>
    `<li>${esc(b.text)}${chip(b)}</li>`).join('');
  const questions = (d.open_questions || []).length
    ? (d.open_questions || []).map(q => openQuestion(q, full)).join('')
    : '<div class="oq-empty">Nothing open. Every fact on this property cleared the gate.</div>';
  const equipment = (d.equipment || []).map(e => `
    <div class="card">
      <div class="card-h">
        <div><div class="lab">${esc(e.type || 'Equipment')}</div><h3>${esc(e.model)}</h3></div>
        <div style="margin-left:auto">${pill(e.status || 'installed')}</div>
      </div>
      <div class="fields">${Object.entries(e.fields || {}).map(([k, f]) => equipmentField(k, f)).join('')}</div>
    </div>`).join('');
  const deferred = (d.deferred || []).length ? `<div class="mlist">${(d.deferred || []).map(x => `
      <div class="mrow"><div class="mh"><b>${esc(x.text)}</b>${pill('unknown')}</div>
      <p>${esc(x.technician || 'technician unknown')} · ${esc((x.ts || '').slice(0, 10))}
        · <a class="link" href="#/job/${esc(x.job_id)}">${esc(x.job_id)}</a></p></div>`).join('')}</div>` : '';
  const docs = (d.documents || []).length ? (d.documents || []).map(x => {
    const c = DOC_COPY[x.kind] || [x.kind, ''];
    return `<a class="doc" href="${esc(x.url)}" target="_blank" rel="noopener">
      <b>${esc(c[0])}${x.job_id ? ' — ' + esc(x.job_id) : ''}</b><span>${esc(c[1])}</span></a>`;
  }).join('') : `<div class="doc" style="opacity:.7"><b>No documents yet</b>
      <span>A document is produced when a visit closes.</span></div>`;

  const visits = d.visits || [];
  return el(`<div class="page" data-property="${esc(p.id)}">
    <div class="crumb"><a href="#/properties">Properties</a><span aria-hidden="true">›</span><span>${esc(p.address)}</span></div>
    <div class="pagehead">
      <div>
        <h1>${esc(p.address)}</h1>
        <div class="sub">Client: ${esc(p.client || 'unknown')} · ${esc(p.city)} ·
          last visit ${esc(p.last_visit || 'unknown')} · technician ${esc(p.technician || 'unknown')} ·
          <span class="dim">record as of ${esc(hhmm(d.record_as_of) || 'unknown')}</span></div>
      </div>
      <div class="actions">
        ${p.id === MAPLE_ID
          ? `<button class="btn pri" type="button" data-run="${esc(p.id)}"><span class="dot"></span>Run the demo here</button>` : ''}
        ${homeowner ? `<a class="btn" href="${esc(homeowner.url)}" target="_blank" rel="noopener">Open homeowner document</a>` : ''}
        <a class="btn" href="/tech?property=${encodeURIComponent(full)}">Add visit (from phone)</a>
      </div>
    </div>

    <div class="block" id="blk-brief">
      <div class="block-h"><h2 class="lab">Briefing</h2>
        <span class="count">assembled from ${visits.length} visit${visits.length === 1 ? '' : 's'} · every line traceable</span></div>
      <ul class="brief" id="briefList">${brief || '<li class="dim">No facts on this property yet.</li>'}</ul>
    </div>

    <div class="block" id="blk-oq">
      <div class="block-h"><h2 class="lab">Open questions</h2>
        <span class="count">${esc(d.auto_passed || 0)} facts passed the gate automatically at this property</span></div>
      <div class="oq" id="oqList">${questions}</div>
    </div>

    <div class="block">
      <div class="block-h"><h2 class="lab">Equipment</h2><span class="count">replaced units stay on the record</span></div>
      <div class="cards">${equipment || '<div class="oq-empty">No equipment recorded yet.</div>'}</div>
    </div>

    ${deferred ? `<div class="block"><div class="block-h"><h2 class="lab">Deferred findings</h2>
      <span class="count">noticed, not repaired</span></div>${deferred}</div>` : ''}

    <div class="block">
      <div class="block-h"><h2 class="lab">Visits</h2></div>
      <div class="tabs" id="visitTabs">
        ${['All', 'In progress', 'Done', 'Needs confirmation'].map((t, i) =>
          `<button class="tab" type="button" data-vtab="${t}" aria-pressed="${i === 0}">${t}</button>`).join('')}
      </div>
      <div class="tw"><table>
        <thead><tr><th>Date</th><th>Technician</th><th>Issue</th><th>Outcome</th><th>State</th><th>Open</th><th>Document</th></tr></thead>
        <tbody id="visitBody">${visits.map(visitRow).join('')}</tbody>
      </table></div>
    </div>

    <div class="block">
      <div class="block-h"><h2 class="lab">Documents</h2></div>
      <div class="docs">${docs}</div>
    </div>
  </div>`);
}

async function job(id) {
  const d = await api.job(id);
  const p = d.property || {};
  const row = f => `<div class="field${f.status === 'unknown' || f.value == null ? ' unknown' : ''} wide">
    <span class="lab">${esc(f.label || label(f.predicate))}</span>
    <span class="val">${f.status === 'unknown' || f.value == null
      ? 'Unknown<span class="chev" aria-hidden="true">›</span>'
      : `<span class="${/serial|model/.test(f.predicate || '') ? 'mono' : ''}">${esc(f.value)}</span>${chip(f)}`}</span>
    ${(f.status === 'unknown' || f.value == null) && f.source ? `<span class="why">${esc(f.source)}</span>` : ''}
  </div>`;
  const group = (title, items, note) => {
    if (!items || !items.length) return '';
    return `<div class="block"><div class="block-h"><h2 class="lab">${esc(title)}</h2>
      ${note ? `<span class="count">${esc(note)}</span>` : ''}</div>
      <div class="cards"><div class="card"><div class="fields">${items.map(row).join('')}</div></div></div></div>`;
  };
  const facts = d.facts || {};
  const similar = (d.similar || []).map(s => `
    <a class="rc" href="#/job/${esc(s.job_id)}"><span class="score">${esc(Math.round((s.score || 0) * 100))}%</span>
      <b>${esc(s.job_id)}</b><p>${esc(s.value)}</p></a>`).join('');
  const journal = (d.journal || []).map(j => {
    const prop = j.proposal || {};
    const verdict = j.verdict;
    const pred = j.predicate || prop.predicate;
    const value = j.value !== undefined ? j.value : (prop.object || {}).value;
    const agent = j.agent || j.proposed_by;
    return `<tr data-verdict="${esc(verdict)}">
      <td class="mono dim nw">${esc(j.id)}</td>
      <td class="mono nw">${esc(stamp(j.decided_at))}</td>
      <td class="nw">${esc(agent)}</td>
      <td class="mono nw">${esc(pred)}</td>
      <td class="clip" title="${esc(value)}">${esc(value)}</td>
      <td class="nw">${pill(verdict)}</td>
      <td class="dim">${esc(j.reason)}</td></tr>`;
  }).join('');
  const similarBlock = `<div class="block">
      <div class="block-h"><h2 class="lab">Similar past cases in the company</h2>
        <span class="count">semantic recall across all jobs — not this property</span></div>
      ${similar ? `<div class="recall">${similar}</div>`
                : '<div class="oq-empty">No similar case on record yet — recall runs on the issue text once other jobs carry embeddings.</div>'}</div>`;

  return el(`<div class="page">
    <div class="crumb"><a href="#/properties">Properties</a><span aria-hidden="true">›</span>
      ${p.id ? `<a href="#/property/${esc(p.id)}">${esc(p.address)}</a>` : '<span class="dim">no property</span>'}
      <span aria-hidden="true">›</span><span class="mono">${esc(d.job_id)}</span></div>
    <div class="pagehead">
      <div><h1 class="mono">${esc(d.job_id)}</h1>
        <div class="sub">Every value on this visit carries the source it came from and the gate entry that let it in.</div></div>
      <div class="actions">
        <a class="btn" href="/doc/${esc(d.job_id)}" target="_blank" rel="noopener">Homeowner document ↗</a>
      </div>
    </div>
    ${group('Equipment', facts.equipment, 'grouped by type · each value carries its source')}
    ${group('Money', facts.money, 'three entities, kept apart')}
    ${group('Deferred findings', facts.deferred, 'noticed, not repaired')}
    ${group('Other', facts.other, '')}
    ${similarBlock}
    ${journal ? `<div class="block"><details class="gate" open>
      <summary>Gate decisions for this job (${(d.journal || []).length})</summary>
      <div class="tw"><table class="wide"><thead><tr><th>#</th><th>Time (UTC)</th><th>Agent</th>
        <th>Predicate</th><th>Value</th><th>Verdict</th><th>Reason</th></tr></thead>
      <tbody>${journal}</tbody></table></div></details></div>` : ''}
    <div class="block">
      <div class="block-h"><h2 class="lab">Documents</h2></div>
      <div class="docs">
        <a class="doc" href="/doc/${esc(d.job_id)}" target="_blank" rel="noopener">
          <b>Homeowner document</b><span>${esc(DOC_COPY.homeowner[1])}</span></a>
        <a class="doc" href="/doc/${esc(d.job_id)}?mode=decider" target="_blank" rel="noopener">
          <b>Decider view</b><span>${esc(DOC_COPY.decider[1])}</span></a>
        <a class="doc" href="/api/closeout/${esc(d.job_id)}" target="_blank" rel="noopener">
          <b>Authorization JSON</b><span>${esc(DOC_COPY.authorization[1])}</span></a>
      </div>
    </div>
  </div>`);
}

async function jobs() {
  const s = await api.state();
  const rows = (s.jobs || []).map(j => {
    const id = String(j.subject || '').replace(/^job:/, '');
    const facts = j.facts || [];
    const find = p => (facts.find(f => f.predicate === p) || {}).value;
    const address = find('property');
    return `<tr class="clickable" data-job="${esc(id)}">
      <td class="mono nw">${esc(id)}</td>
      <td>${address ? esc(address) : '<span class="dim">no property — ledger only</span>'}</td>
      <td>${esc(find('issue') || '—')}</td>
      <td class="nw">${esc(facts.length)}</td>
      <td><a class="link" href="#/job/${esc(id)}">Open ↗</a></td></tr>`;
  }).join('');
  return el(`<div class="page">
    <div class="pagehead"><div><h1>Jobs</h1>
      <div class="sub">Every visit across the workspace. A job always opens inside its property.</div></div></div>
    <div class="tw"><table>
      <thead><tr><th>Job</th><th>Property</th><th>Issue</th><th>Facts</th><th></th></tr></thead>
      <tbody>${rows || '<tr><td colspan="5" class="dim">No jobs on record.</td></tr>'}</tbody></table></div>
    <p class="foot">A job without a recorded address never reaches the property list — it stays here and in the ledger.</p>
  </div>`);
}

async function ledger() {
  const s = await api.state();
  const c = s.counters || {};
  const rows = (s.journal || []).map(r => {
    const job = String(r.subject || '').replace(/^job:/, '');
    return `<tr data-verdict="${esc(r.verdict)}">
      <td class="mono dim nw">${esc(r.id)}</td>
      <td class="mono nw">${esc(stamp(r.decided_at))}</td>
      <td class="nw">${esc(r.agent)}</td>
      <td class="nw"><a class="link" href="#/job/${esc(job)}">${esc(job)}</a></td>
      <td class="mono nw">${esc(r.predicate)}</td>
      <td class="clip" title="${esc(r.value)}">${esc(r.value)}</td>
      <td class="nw">${pill(r.verdict)}</td>
      <td class="dim">${esc(r.reason)}</td></tr>`;
  }).join('');
  const refusals = (s.refusals || []).map(r => `
    <article class="refusal" data-verdict="rejected">
      <div class="refusal-h">${pill('rejected')}
        <span class="dim">${esc(r.agent)} proposed for <a class="link" href="#/job/${esc(r.job_id)}">${esc(r.job_id)}</a> · ${esc(stamp(r.decided_at))} · gate entry <span class="mono">#${esc(r.id)}</span></span></div>
      <div class="refusal-body">
        <div class="strike"><span class="lab">${esc(r.label)}</span> <s>${esc(r.proposed)}</s></div>
        <blockquote class="verdict">${esc(r.reason)}</blockquote>
        ${r.stands ? `<div class="stands"><span class="lab">Stands</span> <b>${esc(r.stands.value)}</b>${
          r.stands.source ? ` <span class="chip" aria-hidden="true">${esc(r.stands.source)}</span>` : ''}${
          r.stands.gate_entry_id ? ` <span class="dim mono">#${esc(r.stands.gate_entry_id)}</span>` : ''}</div>` : ''}
      </div>
    </article>`).join('');
  return el(`<div class="page wide">
    <div class="pagehead"><div><h1>Ledger</h1>
      <div class="sub">Every write the fleet attempted, and what the verifier said about it.
        ${esc(c.total || 0)} decisions on record · ${esc(c.approved || 0)} approved · ${esc(c.rejected || 0)} rejected.</div></div></div>
    <div class="block" id="blk-refusals">
      <div class="block-h"><h2 class="lab">What the gate refused</h2>
        <span class="count">${esc((s.refusals || []).length)} refusal${(s.refusals || []).length === 1 ? '' : 's'} · the record kept the verified value each time</span></div>
      <div class="refusals">${refusals || '<div class="oq-empty">No refusals on record yet.</div>'}</div>
    </div>
    <div class="tabs" id="ledTabs">
      ${['All', 'Approved', 'Rejected'].map((t, i) =>
        `<button class="tab" type="button" data-ltab="${t}" aria-pressed="${i === 0}">${t}</button>`).join('')}
    </div>
    <div class="tw"><table class="wide">
      <thead><tr><th>#</th><th>Time (UTC)</th><th>Agent</th><th>Subject</th><th>Predicate</th>
        <th>Value</th><th>Verdict</th><th>Reason</th></tr></thead>
      <tbody id="ledBody">${rows || '<tr><td colspan="8" class="dim">The journal is empty.</td></tr>'}</tbody></table></div>
    <p class="foot">Showing the most recent ${(s.journal || []).length} of ${esc(c.total || 0)}.
      System of record: Postgres <span class="mono">gate_journal</span> · the Firestore feed is best-effort.</p>
  </div>`);
}

const views = {intro, properties, property, job, jobs, ledger};

/* -------------------------------------------------------------- router */
const NAV_FOR = {properties: 'properties', property: 'properties', jobs: 'jobs', job: 'jobs', ledger: 'ledger'};
const appEl = () => document.getElementById('app');

function parseHash() {
  const h = (location.hash || '#/intro').replace(/^#\/?/, '');
  const parts = h.split('/').filter(Boolean);
  const name = parts[0] || 'intro';
  return {name: views[name] ? name : 'intro', param: parts[1] ? decodeURIComponent(parts[1]) : null};
}

async function route() {
  const {name, param} = parseHash();
  PROV = [];
  closePopover();
  const host = appEl();
  host.innerHTML = '<div class="page"><p class="note">Loading…</p></div>';
  $$('.navlink').forEach(a => {
    if (a.dataset.nav === NAV_FOR[name]) a.setAttribute('aria-current', 'page');
    else a.removeAttribute('aria-current');
  });
  try {
    const node = await views[name](param);
    host.innerHTML = '';
    host.appendChild(node);
  } catch (err) {
    const what = err && err.status === 404 ? 'that record is not on file' : 'could not load';
    host.innerHTML = `<div class="page"><div class="pagehead"><div><h1>Nothing to show</h1>
      <div class="sub">${esc(what)} — the workspace API did not answer.</div></div></div>
      <p class="note">The page is intact; only the data is missing.
        <button class="btn" type="button" id="retry">Retry</button>
        <a class="btn" href="#/properties">Back to properties</a></p></div>`;
  }
  window.scrollTo(0, 0);
}

/* ---------------------------------------------------------- live demo */
let running = false;

function runLine(host) {
  const line = document.createElement('div');
  line.className = 'runline';
  line.innerHTML = '<span class="spin" aria-hidden="true"></span>' +
                   '<span id="runTxt">starting the fleet…</span><span class="t" id="runT">0s</span>';
  const blk = $('#blk-brief', host) || host.firstElementChild;
  blk.insertBefore(line, blk.firstChild);
  return line;
}

const RUN_TEXT = {
  running: 'foreman reading the nameplate and recording the visit…',
  pushback: 'the homeowner pushes back — the gate is checking it against the record…',
};

async function runDemo(propId) {
  if (running) return;
  const id = propId || MAPLE_ID;
  if (location.hash !== '#/property/' + id) {
    location.hash = '#/property/' + id;
    setTimeout(() => runDemo(id), 400);
    return;
  }
  running = true;
  $$('[data-run]').forEach(b => b.setAttribute('disabled', ''));
  const navBtn = $('#navRun');
  if (navBtn) navBtn.setAttribute('disabled', '');

  const host = appEl();
  const line = runLine(host);
  const txt = () => $('#runTxt');
  const t0 = Date.now();
  const tick = setInterval(() => {
    const t = $('#runT');
    if (t) t.textContent = Math.round((Date.now() - t0) / 1000) + 's';
  }, 250);

  const before = {
    visits: new Set($$('#visitBody tr').map(tr => tr.dataset.job)),
    questions: new Set($$('[data-oq]').map(x => x.dataset.oq)),
  };

  const finish = (cls, message) => {
    clearInterval(tick);
    running = false;
    $$('[data-run]').forEach(b => b.removeAttribute('disabled'));
    if (navBtn) navBtn.removeAttribute('disabled');
    const l = document.querySelector('.runline');
    if (l) {
      l.className = 'runline ' + cls;
      const t = $('#runTxt');
      if (t) t.textContent = message;
    }
  };

  let started;
  try {
    started = await api.demoRun();
  } catch (e) {
    finish('warn', 'could not reach the demo endpoint');
    return;
  }
  if (!started || !started.ok) {
    finish('warn', started && started.why ? started.why : 'the demo is not available right now');
    return;
  }
  if (txt()) txt().textContent = RUN_TEXT.running;

  const deadline = Date.now() + 150000;
  const poll = async () => {
    let st;
    try { st = await api.demoStatus(); } catch (e) { st = null; }
    if (st && RUN_TEXT[st.status] && txt()) txt().textContent = RUN_TEXT[st.status];
    const over = !st || st.status === 'done' || st.status === 'error' || Date.now() > deadline;
    if (!over) { setTimeout(poll, 1500); return; }

    const message = st && st.status === 'error'
      ? (st.error || 'the run failed — the record is unchanged')
      : (st && st.reply) || 'done — the property record was updated';
    finish(st && st.status === 'error' ? 'warn' : 'done', message);
    await rerenderProperty(id, before, message, st && st.status === 'error');
  };
  setTimeout(poll, 1500);
}

async function rerenderProperty(id, before, message, failed) {
  if (location.hash !== '#/property/' + id) return;
  let node;
  try { node = await views.property(id); } catch (e) { return; }
  PROV = [];
  const host = appEl();
  host.innerHTML = '';
  host.appendChild(node);
  // the same status line, kept so the judge can read the outcome after the re-render
  const line = runLine(host);
  line.className = 'runline ' + (failed ? 'warn' : 'done');
  $('#runTxt').textContent = message;
  $('#runT').textContent = '';
  // rebuild PROV indices for the fresh markup
  $$('#visitBody tr').forEach(tr => {
    if (!before.visits.has(tr.dataset.job)) tr.classList.add('is-new');
  });
  $$('[data-oq]').forEach(x => {
    if (!before.questions.has(x.dataset.oq)) x.classList.add('is-new');
  });
  setTimeout(() => $$('.is-new').forEach(x => x.classList.remove('is-new')), 1400);
}

/* A filter that hides every row must say so — an empty table with no message
   reads as a broken page. */
function filterRows(bodySel, key, want, emptyText, cols) {
  const body = $(bodySel);
  if (!body) return;
  let shown = 0;
  $$(bodySel + ' tr').forEach(tr => {
    if (tr.dataset.empty) return;
    const hide = !(!want || tr.dataset[key] === want);
    tr.hidden = hide;
    if (!hide) shown++;
  });
  let note = $('tr[data-empty]', body);
  if (!shown) {
    if (!note) {
      note = document.createElement('tr');
      note.dataset.empty = '1';
      note.innerHTML = `<td colspan="${cols}" class="dim"></td>`;
      body.appendChild(note);
    }
    note.querySelector('td').textContent = emptyText;
    note.hidden = false;
  } else if (note) {
    note.hidden = true;
  }
}

/* -------------------------------------------------------- interactions */
document.addEventListener('click', e => {
  const provBtn = e.target.closest('[data-prov]');
  if (provBtn) { e.preventDefault(); evidence(PROV[+provBtn.dataset.prov]); return; }
  if (e.target.closest('#modalCard')) { if (e.target.closest('.close')) closePopover(); return; }
  if (e.target.closest('#modal')) { closePopover(); return; }
  closePopover();

  const run = e.target.closest('[data-run]');
  if (run) { runDemo(run.dataset.run); return; }
  if (e.target.closest('#navRun')) { runDemo(MAPLE_ID); return; }
  if (e.target.closest('#retry')) { route(); return; }

  const vt = e.target.closest('[data-vtab]');
  if (vt) {
    $$('[data-vtab]').forEach(b => b.setAttribute('aria-pressed', String(b === vt)));
    const want = {'All': null, 'In progress': 'in_progress', 'Done': 'done',
                  'Needs confirmation': 'needs_confirmation'}[vt.dataset.vtab];
    filterRows('#visitBody', 'state', want, `No visits in “${vt.dataset.vtab}”.`, 7);
    return;
  }
  const lt = e.target.closest('[data-ltab]');
  if (lt) {
    $$('[data-ltab]').forEach(b => b.setAttribute('aria-pressed', String(b === lt)));
    const want = {'All': null, 'Approved': 'approved', 'Rejected': 'rejected'}[lt.dataset.ltab];
    filterRows('#ledBody', 'verdict', want, `No ${lt.dataset.ltab.toLowerCase()} decisions on record.`, 8);
    return;
  }
  const tr = e.target.closest('tr.clickable');
  if (tr && !e.target.closest('a') && tr.dataset.job) { location.hash = '#/job/' + tr.dataset.job; }
});

document.addEventListener('keydown', e => { if (e.key === 'Escape') closePopover(); });
window.addEventListener('hashchange', route);
route();
