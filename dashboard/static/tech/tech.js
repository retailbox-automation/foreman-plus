/* Foreman+ — technician seat (/tech).
   Three screens in one page: before -> capture -> result.
   Everything shown here comes from the workspace API; nothing is invented. */
(function () {
  'use strict';

  var $ = function (id) { return document.getElementById(id); };
  var PROPS_URL = '/api/properties';
  var POLL_MS = 1500;

  var LABELS = {
    manufacture_date: 'Manufacture date', serial_number: 'Serial number',
    equipment_model: 'Model', equipment_type: 'Type', capacity: 'Capacity',
    refrigerant: 'Refrigerant', access_location: 'Location', issue: 'Issue',
    estimate: 'Estimate', property: 'Property', technician: 'Technician', client: 'Client'
  };

  var S = {
    screen: 'before',
    properties: [], detail: null, propertyId: '', address: '', newAddress: '',
    technician: localStorage.getItem('foreman.tech') || 'Alicia Reyes',
    photo: null, photoUrl: '', audio: null, audioUrl: '', audioSeconds: 0, notes: '',
    recording: false, arming: false, recStart: 0, recTick: null, micError: '',
    sending: false, sendNote: null, clarify: '',
    job: null, poll: null, err: '', leftAsIs: {}
  };

  /* ---------------- helpers ---------------- */
  function esc(v) {
    return String(v === null || v === undefined ? '' : v)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }
  // Same rule as the server: lowercase, non-alphanumerics -> "-", trimmed.
  function slugify(s) {
    return String(s || '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
  }
  function label(pred) {
    if (LABELS[pred]) return LABELS[pred];
    var t = String(pred || '').replace(/_/g, ' ').trim();
    return t ? t.charAt(0).toUpperCase() + t.slice(1) : 'Fact';
  }
  function hhmm(ts) {
    if (!ts) return '';
    var d = new Date(ts);
    if (isNaN(d.getTime())) return String(ts).slice(11, 16);
    return String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0');
  }
  function mmss(sec) {
    sec = Math.max(0, Math.round(sec));
    return Math.floor(sec / 60) + ':' + String(sec % 60).padStart(2, '0');
  }
  function gateChip(id) { return id ? ' <span class="g">· gate entry #' + esc(id) + '</span>' : ''; }
  function byline(source, agent, ts, gateId) {
    var bits = [];
    if (source) bits.push(esc(source));
    if (agent && agent !== source) bits.push(esc(agent));
    if (ts) bits.push(esc(hhmm(ts)));
    if (!bits.length && !gateId) return '';
    return '<span class="byline">' + bits.join(' · ') + gateChip(gateId) + '</span>';
  }
  function getJSON(url) {
    return fetch(url, { headers: { Accept: 'application/json' } }).then(function (r) {
      if (!r.ok) throw new Error('HTTP ' + r.status + ' for ' + url);
      return r.json();
    });
  }

  /* ---------------- data ---------------- */
  function loadProperties() {
    return getJSON(PROPS_URL).then(function (body) {
      S.properties = (body && body.properties) || [];
      var wanted = new URLSearchParams(location.search).get('property');
      var pick = null;
      if (wanted) {
        pick = S.properties.filter(function (p) {
          return p.id === wanted || p.id === slugify(wanted) ||
            (p.address + ', ' + p.city) === wanted || p.address === wanted;
        })[0];
      }
      if (!pick) pick = S.properties[0];
      if (pick) return selectProperty(pick.id);
      render();
    }).catch(function (e) { S.err = e.message; render(); });
  }

  function fullAddress(p) {
    if (!p) return '';
    return p.city ? p.address + ', ' + p.city : p.address;
  }

  function selectProperty(id) {
    S.propertyId = id; S.detail = null; S.err = '';
    if (id === '__new__') { S.address = S.newAddress; render(); return Promise.resolve(); }
    var row = S.properties.filter(function (p) { return p.id === id; })[0];
    S.address = fullAddress(row);
    render();
    return getJSON('/api/property/' + encodeURIComponent(id)).then(function (d) {
      if (S.propertyId !== id) return;
      S.detail = d;
      if (d && d.property) S.address = fullAddress(d.property);
      render();
    }).catch(function (e) { S.err = e.message; render(); });
  }

  /* ---------------- screen 1: before the visit ---------------- */
  function headBefore() {
    var p = S.detail && S.detail.property;
    var addr = S.address || 'Pick a property';
    var sub = [];
    if (p && p.client) sub.push('Client: ' + p.client);
    if (p && p.last_visit) sub.push('Last visit ' + p.last_visit);
    var tags = '';
    if (p) {
      var pills = String(p.equipment_summary || '').split('·').map(function (s) { return s.trim(); })
        .filter(Boolean).map(function (t) { return '<span class="tag">' + esc(t) + '</span>'; });
      if (p.open_questions) {
        pills.push('<span class="tag warn">' + esc(p.open_questions) + ' open question' +
          (p.open_questions === 1 ? '' : 's') + '</span>');
      }
      if (pills.length) tags = '<div class="tags">' + pills.join('') + '</div>';
    }
    var asOf = S.detail && S.detail.record_as_of
      ? '<div class="m3">Property record as of ' + esc(hhmm(S.detail.record_as_of)) + '</div>' : '';
    return '<span class="lab wk">Ridgeline Mechanical · sample workspace</span>' +
      '<h2>' + esc(addr) + '</h2>' +
      (sub.length ? '<div class="m">' + esc(sub.join(' · ')) + '</div>' : '') + asOf + tags;
  }

  function bodyBefore() {
    var opts = S.properties.map(function (p) {
      return '<option value="' + esc(p.id) + '"' + (p.id === S.propertyId ? ' selected' : '') + '>' +
        esc(fullAddress(p)) + '</option>';
    }).join('');
    var h = '<div class="ph-sec">' +
      '<label class="field"><span class="lab">Property</span>' +
      '<select class="inp" id="propSel" aria-label="Property">' + opts +
      '<option value="__new__"' + (S.propertyId === '__new__' ? ' selected' : '') + '>New address…</option>' +
      '</select></label>' +
      (S.propertyId === '__new__'
        ? '<label class="field"><span class="lab">New address</span>' +
          '<input class="inp" id="newAddr" placeholder="1187 Lakeshore Dr, Orlando FL 32806" ' +
          'value="' + esc(S.newAddress) + '"></label>'
        : '') +
      '<label class="field"><span class="lab">Technician</span>' +
      '<input class="inp" id="techName" value="' + esc(S.technician) + '" autocomplete="name"></label>' +
      '</div>';

    if (S.err) h += '<div class="note err">' + esc(S.err) + '</div>';

    if (S.propertyId === '__new__') {
      h += '<div class="note info">New address — no property record yet. What you capture starts one.</div>';
      return h;
    }
    if (!S.detail) return h + '<div class="empty">Loading the property record…</div>';

    var d = S.detail;
    h += '<div class="ph-sec"><span class="lab">What we know</span>';
    if (d.briefing && d.briefing.length) {
      h += '<ul class="ph-brief">' + d.briefing.map(function (b) {
        return '<li>' + esc(b.text) + byline(b.source, b.agent, b.ts, b.gate_entry_id) + '</li>';
      }).join('') + '</ul>';
    } else {
      h += '<div class="empty">Nothing on record yet — this is the first visit.</div>';
    }
    h += '</div>';

    var unknowns = (d.open_questions || []).filter(function (q) { return q.kind === 'unknown'; });
    if (unknowns.length) {
      h += '<div class="ph-sec"><span class="lab">Unknown</span>' + unknowns.map(function (q) {
        return '<button class="unkrow" data-sayit="' + esc(q.predicate) + '">' +
          esc(label(q.predicate)) + ' — ' + esc(q.reason || 'not on record') +
          '<span class="chev">›</span></button>';
      }).join('') + '</div>';
    }

    if (d.deferred && d.deferred.length) {
      h += '<div class="ph-sec"><span class="lab">Noticed last time</span><ul class="ph-brief">' +
        d.deferred.map(function (x) {
          return '<li>' + esc(x.text) +
            '<span class="byline">' + esc([x.technician, hhmm(x.ts), x.job_id].filter(Boolean).join(' · ')) +
            gateChip(x.gate_entry_id) + '</span></li>';
        }).join('') + '</ul></div>';
    }
    return h;
  }

  /* ---------------- screen 2: capture ---------------- */
  function bodyCapture() {
    var h = '';
    if (S.clarify) h += '<div class="note warn">' + esc(S.clarify) + '</div>';

    h += '<button type="button" class="shot' + (S.photoUrl ? ' has' : '') + '" id="shotBox" ' +
      'aria-label="' + (S.photoUrl ? 'Retake the photo' : 'Take a photo of the nameplate') + '">' +
      (S.photoUrl
        ? '<img src="' + esc(S.photoUrl) + '" alt="The photo you just took"><div class="guide"></div>' +
          '<div class="hint">Tap to retake</div>'
        : '<div class="guide"></div><div class="cue"><b>Point at the nameplate</b>' +
          'Tap here or the shutter to open the camera.</div>') +
      '</button>';

    h += '<div class="shotrow">' +
      '<button type="button" class="shutter" id="shutter" aria-label="Open the camera"></button>' +
      '<button type="button" class="mic' + (S.recording ? ' on' : '') + '" id="micBtn" ' +
      'aria-pressed="' + (S.recording ? 'true' : 'false') + '"' +
      (S.arming ? ' aria-busy="true"' : '') + '>' +
      (S.recording ? '<i></i>Recording… ' + mmss((Date.now() - S.recStart) / 1000)
        : S.arming ? 'Asking for the microphone…'
        : (S.audioUrl ? 'Hold to talk again' : 'Hold to talk')) +
      '</button></div>';

    var caps = [];
    if (S.photo) caps.push('<span>1 photo ready</span>');
    if (S.audioUrl) {
      caps.push('<span>' + esc(mmss(S.audioSeconds)) + ' of voice</span>' +
        '<span class="r"><button type="button" class="linkbtn" id="playAudio">Play</button></span>');
    }
    if (caps.length) h += '<div class="captions">' + caps.join('') + '</div>';
    if (S.micError) h += '<div class="note unk">' + esc(S.micError) + '</div>';

    h += '<label class="field" style="margin-top:16px"><span class="lab">Typed notes (optional)</span>' +
      '<textarea class="inp" id="notes" placeholder="Anything the photo and your voice missed.">' +
      esc(S.notes) + '</textarea></label>';

    var bits = [];
    bits.push(S.photo ? '1 photo' : 'no photo yet');
    bits.push(S.audioUrl ? mmss(S.audioSeconds) + ' of voice' : 'no voice');
    h += '<div class="willsend">' + esc(bits.join(' + ')) + ' → <b>' +
      esc(S.address || 'no property picked') + '</b></div>';

    if (!navigator.onLine) {
      h += '<div class="note unk">No signal — kept on the phone; tap Send when back online.</div>';
    }
    if (S.sendNote) {
      h += '<div class="note ' + esc(S.sendNote.tone) + '">' + esc(S.sendNote.text) + '</div>';
    }
    return h;
  }

  /* ---------------- screen 3: result ---------------- */
  function stepsList() {
    var j = S.job, facts = j.facts || 0, done = j.status === 'done';
    var li = function (cls, tick, text, t) {
      return '<li class="' + cls + '"><span class="tick">' + tick + '</span>' + text +
        (t === null || t === undefined ? '' : '<span class="t">' + esc(t) + 's</span>') + '</li>';
    };
    var out = li('done', '✓', j.hadAudio ? 'Photo and voice sent' : 'Photo sent', 0);
    out += facts >= 1
      ? li('done', '✓', 'Foreman read the nameplate', j.firstFactAt)
      : li('now', '·', 'Foreman reading the nameplate…', j.elapsed);
    out += facts >= 1
      ? li('done', '✓', 'Facts recorded (' + esc(facts) + ')', j.elapsed)
      : li('wait', '·', 'Facts recorded', null);
    out += done
      ? li('done', '✓', 'Done in ' + esc(j.elapsed) + 's', null)
      : li('now', '·', 'Estimator working…', j.elapsed);
    return '<ul class="steps">' + out + '</ul>';
  }

  function factRow(f) {
    var unknown = f.status === 'unknown' || String(f.value).toUpperCase() === 'UNKNOWN';
    var v = unknown ? 'Unknown' : String(f.value === null || f.value === undefined ? '' : f.value);
    var mono = /serial|model/.test(f.predicate || '') ? ' mono' : '';
    var h = '<div class="factrow' + (unknown ? ' unknown' : '') + '">' +
      '<div class="fl"><span class="tick">' + (unknown ? '—' : '✓') + '</span>' +
      '<span class="fp">' + esc(f.label || label(f.predicate)) + '</span>' +
      '<span class="fv' + mono + '">' + esc(v) + '</span></div>' +
      '<div class="fs">' + esc([f.source, f.agent === f.source ? '' : f.agent, hhmm(f.ts)]
        .filter(Boolean).join(' · ')) +
      (f.gate_entry_id ? ' · gate entry #' + esc(f.gate_entry_id) : '') + '</div></div>';
    if (unknown) {
      h += '<button class="unkrow" data-sayit="' + esc(f.predicate) + '">' +
        esc(label(f.predicate)) + ' — say it<span class="chev">›</span></button>';
    }
    return h;
  }

  function rejectedRows(journal) {
    return (journal || []).filter(function (r) {
      return r.verdict === 'rejected' &&
        !String(r.reason || '').toLowerCase().startsWith('verifier error:');
    });
  }

  function plaque(r, i) {
    var prop = r.proposal || {};
    var pred = r.predicate || prop.predicate || '';
    var proposed = r.proposed;
    if (proposed === undefined) {
      var o = prop.object;
      proposed = o && typeof o === 'object' ? o.value : o;
    }
    if (S.leftAsIs[i]) {
      return '<div class="factrow"><div class="fl"><span class="tick">—</span>' +
        '<span class="fp">' + esc(label(pred)) + '</span>' +
        '<span class="fv">Left as is</span></div>' +
        '<div class="fs">The property record is unchanged — nothing was written.</div></div>';
    }
    var c = r.contradicts;
    return '<div class="factrow"><div class="fl">' +
      '<span class="tick" style="color:var(--warn-tx)">!</span>' +
      '<span class="fp">' + esc(label(pred)) + '</span>' +
      '<span class="fv">' + esc(proposed) + '</span></div>' +
      '<div class="fs">Refused by the write-gate' +
      (r.proposed_by ? ' · proposed by ' + esc(r.proposed_by) : '') +
      (r.verifier_model ? ' · ' + esc(r.verifier_model) : '') + '</div>' +
      '<div class="plaque"><span class="said">“' + esc(r.reason) + '”</span>' +
      (c ? '<div class="meta">Contradicts <span class="mono">' + esc(pred) + ' = ' + esc(c.value) +
        '</span>' + (c.gate_entry_id ? ' · gate entry #' + esc(c.gate_entry_id) : '') + '</div>' : '') +
      '<div class="oq-act">' +
      '<button class="btn" data-sayit="' + esc(pred) + '">Clarify by voice</button>' +
      '<button class="btn" data-leave="' + esc(i) + '">Leave as is</button>' +
      '</div></div></div>';
  }

  function bodyResult() {
    var j = S.job;
    if (j.status === 'error') {
      return '<div class="note err"><b>The fleet could not finish this intake.</b><br>' +
        esc(j.error || 'Unknown error') + '</div>' +
        '<div class="empty">Your photo and voice are still on this phone.</div>';
    }
    var h = stepsList();
    if (j.status !== 'done') {
      h += '<div class="empty">Foreman+ is reading the photo, transcribing your voice and checking ' +
        'both against the property record. This normally takes 15–40 seconds.</div>';
      return h;
    }
    if (j.reply) h += '<div class="note info">' + esc(j.reply) + '</div>';
    if (!j.detail) return h + '<div class="empty">Loading the facts that were recorded…</div>';

    var d = j.detail, f = d.facts || {};
    var rows = [].concat(f.equipment || [], f.other || [], f.money || [], f.deferred || []);
    h += '<div class="ph-sec"><span class="lab">Facts recorded</span>' +
      (rows.length ? rows.map(factRow).join('') : '<div class="empty">No facts were recorded.</div>') +
      '</div>';

    var rej = rejectedRows(d.journal);
    if (rej.length) {
      h += '<div class="ph-sec"><span class="lab">Needs confirmation</span>' +
        rej.map(function (r, i) { return plaque(r, i); }).join('') + '</div>';
    }

    h += '<div class="ph-sec">' +
      '<a class="unkrow" href="/doc/' + encodeURIComponent(j.id) + '" target="_blank" rel="noopener">' +
      'Open homeowner document<span class="chev">›</span></a>' +
      '<a class="unkrow" href="/#/property/' + encodeURIComponent(propertySlug()) + '">' +
      'Open the property record<span class="chev">›</span></a></div>';

    h += '<div class="summary">Property updated: +' + esc(j.facts || 0) + ' fact' +
      ((j.facts || 0) === 1 ? '' : 's') + ' on ' + esc(S.address) + '.</div>';
    return h;
  }

  function propertySlug() {
    var d = S.job && S.job.detail && S.job.detail.property;
    if (d && d.id) return d.id;
    if (S.propertyId && S.propertyId !== '__new__') return S.propertyId;
    return slugify(S.address);
  }

  /* ---------------- render ---------------- */
  function render() {
    var head = $('phHead'), body = $('phBody'), foot = $('phFoot'), step = $('phStep');
    if (S.screen === 'before') {
      step.textContent = 'Before visit';
      head.innerHTML = headBefore();
      body.innerHTML = bodyBefore();
      var can = !!(S.address && S.technician.trim());
      foot.innerHTML = '<button class="btn pri" id="toCapture"' + (can ? '' : ' aria-disabled="true"') +
        '>Start capture</button>';
    } else if (S.screen === 'capture') {
      step.textContent = 'Capture';
      head.innerHTML = '<h2>' + esc(S.address) + '</h2><div class="m">' + esc(S.technician) + '</div>';
      body.innerHTML = bodyCapture();
      foot.innerHTML = '<button class="btn" id="backBefore">Back</button>' +
        '<button class="btn pri" id="sendBtn"' + ((S.photo && !S.sending) ? '' : ' aria-disabled="true"') +
        '>' + (S.sending ? 'Sending…' : 'Send') + '</button>';
    } else {
      step.textContent = 'Result';
      head.innerHTML = '<h2>' + esc(S.address) + '</h2><div class="m">Job ' + esc(S.job.id) + ' · ' +
        esc(S.technician) + '</div>';
      body.innerHTML = bodyResult();
      foot.innerHTML = S.job.status === 'error'
        ? '<button class="btn" id="backCapture">Back</button>' +
          '<button class="btn pri" id="retry">Try again</button>'
        : '<button class="btn" id="captureMore">Capture more</button>' +
          '<a class="btn pri" href="/#/property/' + encodeURIComponent(propertySlug()) + '">' +
          'Back to the property</a>';
    }
  }

  /* ---------------- voice ---------------- */
  function pickMime() {
    if (window.MediaRecorder && MediaRecorder.isTypeSupported &&
        MediaRecorder.isTypeSupported('audio/webm')) return 'audio/webm';
    return 'audio/mp4';
  }

  var recorder = null, chunks = [], asking = false, wantStop = false, askTimer = null;
  var MIC_DENIED = 'Microphone unavailable — allow it in the browser, or type the notes below. ' +
    'The photo alone is still enough to send.';

  function micFailed(msg) {
    asking = false; wantStop = false; clearTimeout(askTimer);
    S.arming = false; S.recording = false;
    S.micError = msg || MIC_DENIED;
    render();
  }

  function startRecording() {
    if (S.recording || asking) return;
    if (!navigator.mediaDevices || !window.MediaRecorder) {
      micFailed('This browser cannot record audio. Type the notes below instead.'); return;
    }
    asking = true; wantStop = false; S.arming = true; S.micError = '';
    render();
    // A permission prompt can hang forever on a device with no microphone.
    askTimer = setTimeout(function () { if (asking) micFailed(); }, 6000);
    navigator.mediaDevices.getUserMedia({ audio: true }).then(function (stream) {
      asking = false; clearTimeout(askTimer);
      S.arming = false;
      if (wantStop) {                       // released before the mic was ready
        stream.getTracks().forEach(function (t) { t.stop(); });
        wantStop = false; render(); return;
      }
      var mime = pickMime();
      recorder = new MediaRecorder(stream, { mimeType: mime });
      chunks = [];
      recorder.ondataavailable = function (e) { if (e.data && e.data.size) chunks.push(e.data); };
      recorder.onstop = function () {
        stream.getTracks().forEach(function (t) { t.stop(); });
        var blob = new Blob(chunks, { type: mime });
        if (S.audioUrl) URL.revokeObjectURL(S.audioUrl);
        S.audio = blob; S.audioUrl = URL.createObjectURL(blob);
        S.audioSeconds = (Date.now() - S.recStart) / 1000;
        S.recording = false; clearInterval(S.recTick); S.recTick = null;
        render();
      };
      recorder.start();
      S.recording = true; S.recStart = Date.now();
      S.recTick = setInterval(render, 250);
      render();
    }).catch(function () { micFailed(); });
  }

  function stopRecording() {
    if (asking) { wantStop = true; return; }   // stop arrives before the mic is ready
    if (!S.recording || !recorder) return;
    try { recorder.stop(); } catch (e) { S.recording = false; render(); }
  }

  /* ---------------- send + poll ---------------- */
  function send() {
    if (!S.photo || S.sending) return;
    S.sending = true; S.sendNote = null; render();
    var fd = new FormData();
    fd.append('property', S.address);
    fd.append('technician', S.technician);
    fd.append('client', '');
    fd.append('notes', S.notes);
    fd.append('photo', S.photo, S.photo.name || 'nameplate.jpg');
    if (S.audio) {
      fd.append('audio', S.audio, 'voice.' + (S.audio.type.indexOf('mp4') > -1 ? 'mp4' : 'webm'));
    }
    fetch('/api/intake', { method: 'POST', body: fd }).then(function (r) {
      return r.json().then(function (b) { return { status: r.status, body: b }; });
    }).then(function (res) {
      S.sending = false;
      if (res.status === 429 || (res.body && res.body.ok === false)) {
        S.sendNote = { tone: 'warn', text: (res.body && res.body.why) || 'Not accepted — try again shortly.' };
        render(); return;
      }
      if (res.status >= 400 || !res.body || !res.body.job_id) {
        S.sendNote = { tone: 'err', text: 'The server rejected the upload (HTTP ' + res.status + ').' };
        render(); return;
      }
      S.job = { id: res.body.job_id, status: 'running', facts: 0, elapsed: 0, firstFactAt: null,
                reply: '', error: '', detail: null, hadAudio: !!S.audio };
      S.leftAsIs = {};
      S.screen = 'result';
      render();
      poll();
    }).catch(function () {
      S.sending = false;
      S.sendNote = navigator.onLine
        ? { tone: 'err', text: 'Could not reach Foreman+. Your photo and voice are still on this phone — tap Send again.' }
        : { tone: 'unk', text: 'No signal — kept on the phone; tap Send when back online.' };
      render();
    });
  }

  function poll() {
    clearTimeout(S.poll);
    getJSON('/api/intake/status?job_id=' + encodeURIComponent(S.job.id)).then(function (st) {
      var j = S.job;
      j.status = st.status; j.elapsed = st.elapsed; j.reply = st.reply || '';
      j.error = st.error || '';
      if (j.firstFactAt === null && st.facts >= 1) j.firstFactAt = st.elapsed;
      j.facts = st.facts;
      render();
      if (st.status === 'running') { S.poll = setTimeout(poll, POLL_MS); return; }
      if (st.status === 'done') {
        getJSON('/api/job/' + encodeURIComponent(j.id)).then(function (d) {
          j.detail = d; render();
        }).catch(function (e) { j.detail = { facts: {}, journal: [] }; j.reply = j.reply || e.message; render(); });
      }
    }).catch(function (e) {
      S.job.status = 'error'; S.job.error = e.message; render();
    });
  }

  /* ---------------- events ---------------- */
  function goCapture(clarifyMsg) {
    S.clarify = clarifyMsg || '';
    S.sendNote = null;
    clearTimeout(S.poll);
    S.screen = 'capture';
    render();
    $('phBody').focus();
  }

  document.addEventListener('click', function (e) {
    var t = e.target.closest('button, a');
    if (!t) return;
    var id = t.id;
    if (id === 'toCapture') { goCapture(''); return; }
    if (id === 'backBefore') { S.screen = 'before'; render(); return; }
    if (id === 'shotBox' || id === 'shutter') { $('photoInput').click(); return; }
    if (id === 'playAudio') { new Audio(S.audioUrl).play(); return; }
    if (id === 'sendBtn') { send(); return; }
    if (id === 'captureMore' || id === 'backCapture') { goCapture(''); return; }
    if (id === 'retry') { S.screen = 'capture'; S.sendNote = null; render(); send(); return; }
    if (t.dataset.sayit) {
      goCapture('Say it out loud: ' + label(t.dataset.sayit) +
        '. Photograph the plate again if you can read it.');
      return;
    }
    if (t.dataset.leave) { S.leftAsIs[t.dataset.leave] = true; render(); return; }
  });

  document.addEventListener('change', function (e) {
    if (e.target.id === 'propSel') { S.newAddress = ''; selectProperty(e.target.value); }
  });
  document.addEventListener('input', function (e) {
    if (e.target.id === 'techName') {
      S.technician = e.target.value;
      localStorage.setItem('foreman.tech', S.technician);
      var b = $('phFoot').querySelector('#toCapture');
      if (b) b.setAttribute('aria-disabled', S.address && S.technician.trim() ? 'false' : 'true');
    }
    if (e.target.id === 'newAddr') {
      S.newAddress = e.target.value; S.address = e.target.value;
      var h = $('phHead').querySelector('h2');
      if (h) h.textContent = S.address || 'Pick a property';
      var b2 = $('phFoot').querySelector('#toCapture');
      if (b2) b2.removeAttribute('aria-disabled');
    }
    if (e.target.id === 'notes') S.notes = e.target.value;
  });

  ['pointerdown'].forEach(function (ev) {
    document.addEventListener(ev, function (e) {
      if (e.target.closest && e.target.closest('#micBtn')) { e.preventDefault(); startRecording(); }
    });
  });
  ['pointerup', 'pointercancel', 'pointerleave'].forEach(function (ev) {
    document.addEventListener(ev, function (e) {
      if (S.recording && e.target.closest && e.target.closest('#micBtn')) stopRecording();
    });
  });
  document.addEventListener('keydown', function (e) {
    if (e.target.id === 'micBtn' && (e.key === ' ' || e.key === 'Enter') && !e.repeat) {
      e.preventDefault(); startRecording();
    }
  });
  document.addEventListener('keyup', function (e) {
    if (e.target.id === 'micBtn' && (e.key === ' ' || e.key === 'Enter')) stopRecording();
  });

  window.addEventListener('online', function () { if (S.screen === 'capture') render(); });
  window.addEventListener('offline', function () { if (S.screen === 'capture') render(); });

  $('photoInput').addEventListener('change', function (e) {
    var f = e.target.files && e.target.files[0];
    if (!f) return;
    if (S.photoUrl) URL.revokeObjectURL(S.photoUrl);
    S.photo = f; S.photoUrl = URL.createObjectURL(f);
    if (S.screen !== 'capture') S.screen = 'capture';
    render();
  });

  render();
  loadProperties();
})();
