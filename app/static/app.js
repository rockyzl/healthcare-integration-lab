const $ = selector => document.querySelector(selector);
const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
}[char]));
let selected = '';
let currentPreview = null;
try { selected = localStorage.getItem('lab-selected-record') || ''; } catch {}

function rememberSelection() {
  try { localStorage.setItem('lab-selected-record', selected); } catch {}
}

async function api(path, body) {
  const response = await fetch('/api' + path, {
    method: body === undefined ? 'GET' : 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Lab-Request': 'demo' },
    ...(body === undefined ? {} : { body: JSON.stringify(body) })
  });
  let data;
  try { data = await response.json(); }
  catch { throw Error('The local service could not complete this request. Check the database connections and try again.'); }
  if (!response.ok) throw Error(typeof data.detail === 'string' ? data.detail : 'Check the selected record and enter a question of 5–700 characters.');
  return data;
}

async function busy(button, action) {
  button.disabled = true;
  try { await action(); }
  catch (error) { $('#notice').textContent = error.message; }
  finally { button.disabled = false; }
}

function reveal(element, focusTarget) {
  element.scrollIntoView({ behavior: 'auto', block: 'start' });
  focusTarget?.focus({ preventScroll: true });
}

function date(value) {
  if (!value) return 'Not provided';
  const parsed = new Date(value.slice(0, 10) + 'T12:00:00Z');
  return Number.isNaN(parsed.getTime()) ? esc(value) : parsed.toLocaleDateString('en-US', {
    month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC'
  });
}

function money(fact) {
  if (!fact) return 'Not provided';
  if (!/^[A-Z]{3}$/.test(fact.currency)) return esc(fact.value + ' ' + fact.currency);
  return esc(new Intl.NumberFormat('en-US', { style: 'currency', currency: fact.currency }).format(Number(fact.value)));
}

function visitTable(visits) {
  return `<div class="table-scroll"><table class="records-table"><thead><tr><th>Visit date</th><th>End date</th><th>Status</th><th>Record ID</th></tr></thead><tbody>${visits.map(visit => `
    <tr><td>${date(visit.period.start)}</td><td>${date(visit.period.end)}</td><td>${esc(visit.status || 'Not provided')}</td><td><code title="${esc(visit.id)}">${esc(visit.id.slice(0, 8))}…</code></td></tr>`).join('')}</tbody></table></div>`;
}

function renderPreview(preview) {
  const visits = preview.visits;
  const visitContent = visits.length ? visitTable(visits.slice(0, 5)) + (visits.length > 5 ?
    `<details><summary>Show ${visits.length - 5} more visit records</summary>${visitTable(visits.slice(5))}</details>` : '') :
    '<p class="empty-records">No visit records were returned for this test patient.</p>';
  const insuranceContent = preview.insurance.length ? `<div class="insurance-list">${preview.insurance.map((record, index) => {
    const submitted = record.financial_facts.find(f => f.kind === 'EOB total' && f.category === 'submitted');
    const payment = record.financial_facts.find(f => f.kind === 'EOB payment');
    return `<article class="insurance-record"><div class="case-top"><b>Insurance record ${index + 1}</b><span class="small">${date(record.period.start)}</span></div>
      <dl><div><dt>Submitted amount</dt><dd>${money(submitted)}</dd></div><div><dt>Recorded payment</dt><dd>${money(payment)}</dd></div></dl>
      <p class="small">Status: ${esc(record.status || 'Not provided')} · Outcome: ${esc(record.outcome || 'Not provided')}<br>Record ID: <code>${esc(record.id)}</code></p></article>`;
  }).join('')}</div><p class="small">These are recorded insurance amounts, not a calculation of what the patient owes.</p>` :
    '<div class="empty-records"><b>No insurance records returned</b><p>The import worked. This test patient has no insurance records in this snapshot, so there are no insurance amounts to display.</p><button class="secondary" id="load-example-from-results">Load the example with insurance amounts</button></div>';
  $('#record-preview').innerHTML = `<div class="patient-record"><b>Test patient</b><span>Patient ID: <code>${esc(preview.patient_id)}</code></span><span class="small">Names and other personal details are not retained in this demo.</span></div>
    <h3>Visit records</h3>${visitContent}<h3>Insurance records <span class="small">Explanation of Benefit · EOB</span></h3>${insuranceContent}`;
  const exampleButton = $('#load-example-from-results');
  if (exampleButton) exampleButton.onclick = () => importSource('fixture', exampleButton);
}

async function refresh() {
  const data = await api('/status');
  $('#connections').innerHTML = Object.entries(data.systems).map(([name, system]) => `<span class="connection ${system.connected ? 'good' : 'bad'}"><b>${name === 'sqlserver' ? 'SQL Server' : 'Oracle'}</b> · ${system.connected ? 'Connected · ' + esc(system.version) : 'Not connected'}</span>`).join('');
  $('#record-panel').hidden = !data.patients.length;
  $('#agent-panel').hidden = !data.patients.length;
  $('#patient').innerHTML = data.patients.map(patient => `<option value="${esc(patient.patient_key)}">${esc(patient.source_label)} · ${esc(patient.patient_id.slice(0, 8))}</option>`).join('');
  if (data.patients.length) {
    if (!data.patients.some(patient => patient.patient_key === selected)) selected = data.patients[0].patient_key;
    $('#patient').value = selected;
    rememberSelection();
    await showRecord();
    await showCases();
  }
}

async function showRecord() {
  const key = selected;
  const data = await api('/records/' + key);
  if (key !== selected) return;
  const comparison = data.comparison, preview = data.preview;
  currentPreview = preview;
  $('#import-summary').textContent = `${preview.source_label} · Last imported ${new Date(preview.imported_at).toLocaleString('en-US')}`;
  $('#record-counts').innerHTML = [['Test patient', preview.counts.patients], ['Visit records', preview.counts.visits], ['Insurance records', preview.counts.insurance]].map(([label, value]) => `<div class="metric">${label}<strong>${esc(value)}</strong></div>`).join('');
  renderPreview(preview);
  $('#comparison').innerHTML = [['SQL Server records', comparison.sql_count], ['Oracle records', comparison.oracle_count], ['Content hashes', comparison.hashes_match ? 'Match' : 'Mismatch']].map(([label, value]) => `<div class="metric">${label}<strong>${esc(value)}</strong></div>`).join('');
  $('#provenance').textContent = data.record.source_note + (data.record.truncated ? ' This is a bounded, incomplete snapshot.' : '') + ' A final personal bill balance is not available.';
  $('#record-json').textContent = JSON.stringify(data, null, 2);
}

async function showCases() {
  const key = selected;
  const { cases } = await api('/cases');
  if (key !== selected) return;
  $('#cases').innerHTML = cases.filter(caseData => caseData.patient_key === key).map(c => `<article class="case"><div class="case-top"><span class="tag">${esc(c.status.replaceAll('_', ' '))}</span><span class="small">${esc(new Date(c.created_at).toLocaleString('en-US'))}</span></div><h3>${esc(c.question)}</h3><details><summary>Agent tools and evidence checks</summary><pre>${esc(JSON.stringify({ model: c.model, checks: c.checks, tools: c.trace }, null, 2))}</pre></details>${c.status === 'awaiting_review' ? `<label for="draft-${c.id}">Staff draft — review before approving</label><textarea id="draft-${c.id}" rows="5">${esc(c.draft.response)}</textarea><div class="case-actions"><button data-id="${c.id}" data-decision="approve" ${Object.values(c.checks).every(Boolean) ? '' : 'disabled'}>Approve reply</button><button class="reject" data-id="${c.id}" data-decision="reject">Reject draft</button></div>` : ''}<div class="${c.response ? 'reply' : 'pending'}"><b>Patient-view preview</b><br>${c.response ? esc(c.response) : c.status === 'rejected' ? 'No reply published. Staff needs to investigate further.' : 'No reply published. The draft is waiting for staff review.'}</div></article>`).join('');
  document.querySelectorAll('[data-decision]').forEach(button => button.onclick = () => busy(button, async () => {
    await api('/cases/' + button.dataset.id + '/review', { decision: button.dataset.decision, reply: $('#draft-' + button.dataset.id).value });
    $('#notice').textContent = 'Review decision saved in SQL Server. No message was sent to a real patient.';
    await showCases();
  }));
}

async function importSource(source, button) {
  const sourceButtons = [...document.querySelectorAll('[data-import]')];
  const status = $(`[data-source-status="${source}"]`);
  const originalLabel = button.textContent;
  sourceButtons.forEach(item => item.disabled = true);
  button.disabled = true;
  button.textContent = 'Loading records…';
  status.hidden = false;
  status.textContent = 'Reading records. Results will open automatically below.';
  $('#notice').textContent = 'Reading the source and saving the records…';
  try {
    const result = await api('/import/' + source, {});
    selected = result.patient.patient_key;
    rememberSelection();
    await refresh();
    const counts = currentPreview.counts;
    const summary = `Loaded ${counts.patients} patient, ${counts.visits} visit records and ${counts.insurance} insurance records.`;
    status.innerHTML = `${esc(summary)} <a href="#record-panel">View records ↓</a>`;
    $('#notice').textContent = result.comparison.hashes_match ? 'Imported successfully. ' + summary : 'Imported, but the database copies differ. See technical details.';
    reveal($('#record-panel'), $('#record-title'));
  } catch (error) {
    status.textContent = error.message;
    $('#notice').textContent = error.message;
  } finally {
    sourceButtons.forEach(item => item.disabled = false);
    button.disabled = false;
    button.textContent = originalLabel;
  }
}

document.querySelectorAll('[data-import]').forEach(button => button.onclick = () => importSource(button.dataset.import, button));
$('#patient').onchange = async () => {
  selected = $('#patient').value;
  rememberSelection();
  try { await showRecord(); await showCases(); }
  catch (error) { $('#notice').textContent = error.message; }
};
$('#go-to-agent').onclick = () => reveal($('#agent-panel'), $('#question'));
$('#run-agent').onclick = () => busy($('#run-agent'), async () => {
  $('#notice').textContent = 'The agent is reading both databases and preparing a draft…';
  await api('/cases', { patient_key: selected, message: $('#question').value });
  await showCases();
  $('#notice').textContent = 'Draft ready. Review the evidence below, then approve or reject.';
  reveal($('#cases'));
});
refresh().catch(error => $('#notice').textContent = error.message);
