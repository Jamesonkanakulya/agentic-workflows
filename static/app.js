/* ── State ────────────────────────────────────────────────────────────────── */
let sessionId = null;
let eventSource = null;

const postStates = { linkedin: 'pending', facebook: 'pending', instagram: 'pending' };
const imageState = { status: 'pending' };

/* ── Auth-aware fetch ────────────────────────────────────────────────────── */
async function authFetch(url, options = {}) {
  const res = await fetch(url, options);
  if (res.status === 401) {
    window.location.href = '/login';
    throw new Error('Session expired');
  }
  return res;
}

async function logout() {
  await fetch('/auth/logout', { method: 'POST' });
  window.location.href = '/login';
}

/* ── Workflow kickoff ─────────────────────────────────────────────────────── */
async function startWorkflow() {
  const topic = document.getElementById('topic-input').value.trim();
  if (!topic) {
    document.getElementById('topic-input').focus();
    return;
  }

  // UI: loading state
  document.getElementById('submit-btn').disabled = true;
  document.getElementById('submit-label').textContent = 'Starting...';
  document.getElementById('submit-spinner').classList.remove('hidden');
  hideError();

  try {
    const res = await authFetch('/api/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ topic }),
    });
    const data = await res.json();
    sessionId = data.session_id;

    // Show workflow chrome
    document.getElementById('topic-section').style.display = 'none';
    document.getElementById('progress-section').classList.remove('hidden');
    document.getElementById('new-workflow-btn').classList.remove('hidden');

    // Subscribe to SSE events
    subscribeToEvents(sessionId);

  } catch (err) {
    showError('Failed to start workflow: ' + err.message);
    resetSubmitBtn();
  }
}

/* ── SSE listener ─────────────────────────────────────────────────────────── */
function subscribeToEvents(sid) {
  if (eventSource) eventSource.close();
  eventSource = new EventSource(`/api/events/${sid}`);

  eventSource.onmessage = (e) => {
    const msg = JSON.parse(e.data);
    if (msg.type === 'ping') return;

    switch (msg.type) {
      case 'status':          handleStatus(msg.data);         break;
      case 'posts_ready':     handlePostsReady(msg.data);     break;
      case 'post_update':     handlePostUpdate(msg.data);     break;
      case 'image_update':    handleImageUpdate(msg.data);    break;
      case 'posting_result':  handlePostingResult(msg.data);  break;
      case 'posting_complete': handlePostingComplete(msg.data); break;
      case 'log':             handleLog(msg.data);            break;
      case 'error':           showError(msg.data.message);    break;
      case 'complete':        handleComplete();               break;
      case 'stopped':         handleStopped();                break;
    }
  };

  eventSource.onerror = () => {
    // Check if auth expired
    fetch(`/api/session/${sid}`).then(res => {
      if (res.status === 401) window.location.href = '/login';
    }).catch(() => {});
  };
}

/* ── Event handlers ───────────────────────────────────────────────────────── */
function handleStatus({ workflow_status }) {
  updateProgressBar(workflow_status);
  const labels = {
    researching:      'Researching current trends...',
    generating:       'Generating platform-specific posts...',
    reviewing_posts:  'Posts ready — please review each one.',
    generating_image: 'Generating image with Flux AI...',
    reviewing_image:  'Image ready — please review.',
    posting:          'Publishing posts to platforms...',
    complete:         'Workflow complete!',
    stopped:          'Workflow stopped.',
    error:            'An error occurred.',
  };
  // Show the posting section when posting starts
  if (workflow_status === 'posting') {
    document.getElementById('posting-section').classList.remove('hidden');
    document.getElementById('posting-section').scrollIntoView({ behavior: 'smooth' });
  }
  // Hide stop button when workflow ends
  if (['complete', 'stopped', 'error'].includes(workflow_status)) {
    document.getElementById('stop-btn').classList.add('hidden');
  }
  const isDone = workflow_status === 'complete' || workflow_status === 'stopped';
  setStatus(labels[workflow_status] || workflow_status, isDone);
}

function handlePostsReady({ posts }) {
  document.getElementById('posts-section').classList.remove('hidden');
  for (const platform of ['linkedin', 'facebook', 'instagram']) {
    renderPost(platform, posts[platform]);
  }
}

function handlePostUpdate({ platform, status, content, hashtags }) {
  postStates[platform] = status;
  if (content !== undefined) {
    renderPost(platform, { content, hashtags: hashtags || [], status });
  } else {
    updateBadge(platform, status);
    updateCardClass(platform, status);
    updateActions(platform, status);
  }
}

function handleImageUpdate({ status, url }) {
  imageState.status = status;
  const section = document.getElementById('image-section');
  section.classList.remove('hidden');

  const placeholder = document.getElementById('image-placeholder');
  const preview     = document.getElementById('image-preview');
  const actions     = document.getElementById('image-actions');
  const badge       = document.getElementById('badge-image');

  if (status === 'generating') {
    placeholder.classList.remove('hidden');
    preview.classList.add('hidden');
    actions.classList.add('hidden');
    setBadge(badge, 'generating', 'Generating...');

  } else if (status === 'ready' || status === 'approved') {
    placeholder.classList.add('hidden');
    preview.classList.remove('hidden');
    preview.src = url;
    actions.classList.remove('hidden');

    if (status === 'approved') {
      setBadge(badge, 'approved', 'Approved');
      document.querySelector('#image-section .btn-approve').disabled = true;
      document.querySelector('#image-section .btn-revise').disabled  = true;
    } else {
      setBadge(badge, 'ready', 'Pending Review');
    }
  }
}

function handleLog({ message }) {
  setStatus(message);
}

function handlePostingResult({ platform, result }) {
  const statusEl = document.getElementById(`posting-status-${platform}`);
  if (!statusEl) return;
  if (result.success) {
    const url = result.url || '#';
    statusEl.innerHTML = `<span style="color:var(--green)">&#10003;</span> Published`;
    if (result.url) {
      statusEl.innerHTML += ` — <a href="${url}" target="_blank">View Post</a>`;
    }
    document.getElementById(`posting-${platform}`).classList.add('posting-success');
  } else {
    statusEl.innerHTML = `<span style="color:var(--red)">&#10007;</span> Failed: ${result.error || 'unknown error'}`;
    document.getElementById(`posting-${platform}`).classList.add('posting-failed');
  }
}

function handlePostingComplete({ results }) {
  const summary = document.getElementById('complete-summary');
  if (!summary) return;
  const total = Object.keys(results).length;
  const ok = Object.values(results).filter(r => r.success).length;
  if (ok === total) {
    summary.innerHTML = `<p class="summary-ok">All ${total} platforms published successfully!</p>`;
  } else {
    summary.innerHTML = `<p class="summary-partial">${ok}/${total} platforms published. Check the results above for details.</p>`;
  }
}

function handleComplete() {
  document.getElementById('complete-section').classList.remove('hidden');
  document.getElementById('complete-section').scrollIntoView({ behavior: 'smooth' });
  if (eventSource) eventSource.close();
}

/* ── Post rendering ───────────────────────────────────────────────────────── */
function renderPost(platform, { content, hashtags = [], status = 'pending' }) {
  const el = document.getElementById(`content-${platform}`);
  el.textContent = content;

  const tagsEl = document.getElementById(`tags-${platform}`);
  tagsEl.innerHTML = (hashtags || []).map(t => `<span class="tag">${t}</span>`).join('');

  const chars = document.getElementById(`chars-${platform}`);
  chars.textContent = `${content.length} / 1900 chars`;

  postStates[platform] = status;
  updateBadge(platform, status);
  updateCardClass(platform, status);
  updateActions(platform, status);
}

function updateBadge(platform, status) {
  const badge = document.getElementById(`badge-${platform}`);
  const map = {
    pending:  ['badge-pending',  'Pending Review'],
    revising: ['badge-revising', 'Revising...'],
    approved: ['badge-approved', 'Approved'],
  };
  const [cls, label] = map[status] || ['badge-pending', status];
  setBadge(badge, status, label);
}

function setBadge(el, status, label) {
  el.className = 'badge';
  const cls = { pending: 'badge-pending', revising: 'badge-revising', approved: 'badge-approved',
                generating: 'badge-generating', ready: 'badge-ready' };
  if (cls[status]) el.classList.add(cls[status]);
  el.textContent = label;
}

function updateCardClass(platform, status) {
  const card = document.getElementById(`card-${platform}`);
  card.classList.remove('status-approved', 'status-revising');
  if (status === 'approved') card.classList.add('status-approved');
  if (status === 'revising') card.classList.add('status-revising');
}

function updateActions(platform, status) {
  const approveBtn = document.querySelector(`#card-${platform} .btn-approve`);
  const reviseBtn  = document.querySelector(`#card-${platform} .btn-revise`);
  if (!approveBtn) return;

  if (status === 'approved') {
    approveBtn.disabled = true;
    reviseBtn.disabled  = false;
  } else if (status === 'revising') {
    approveBtn.disabled = true;
    reviseBtn.disabled  = true;
  } else {
    approveBtn.disabled = false;
    reviseBtn.disabled  = false;
  }
}

/* ── Post actions ─────────────────────────────────────────────────────────── */
async function approvePost(platform) {
  if (postStates[platform] === 'revising') return;

  await authFetch(`/api/posts/${sessionId}/approve/${platform}`, { method: 'POST' });
  postStates[platform] = 'approved';
  updateBadge(platform, 'approved');
  updateCardClass(platform, 'approved');
  updateActions(platform, 'approved');

  const allApproved = Object.values(postStates).every(s => s === 'approved');
  if (allApproved) {
    setStatus('All posts approved. Generating image...');
    document.getElementById('image-section').classList.remove('hidden');
    document.getElementById('image-section').scrollIntoView({ behavior: 'smooth' });
  }
}

async function revisePost(platform) {
  const feedback = document.getElementById(`feedback-${platform}`).value.trim();
  if (!feedback) {
    document.getElementById(`feedback-${platform}`).focus();
    return;
  }

  document.getElementById(`feedback-${platform}`).value = '';

  await authFetch(`/api/posts/${sessionId}/revise/${platform}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ feedback }),
  });
}

/* ── Stop workflow ────────────────────────────────────────────────────────── */
async function stopWorkflow() {
  if (!sessionId) return;
  document.getElementById('stop-btn').disabled = true;
  document.getElementById('stop-btn').textContent = 'Stopping...';
  await authFetch(`/api/stop/${sessionId}`, { method: 'POST' });
}

function handleStopped() {
  document.getElementById('stop-btn').classList.add('hidden');
  if (eventSource) eventSource.close();

  // Show stopped banner
  const section = document.getElementById('complete-section');
  section.classList.remove('hidden');
  section.scrollIntoView({ behavior: 'smooth' });
  const icon = section.querySelector('.complete-icon');
  if (icon) icon.innerHTML = '<svg width="40" height="40" viewBox="0 0 20 20" fill="var(--red, #ef4444)"><rect x="4" y="4" width="12" height="12" rx="2"/></svg>';
  section.querySelector('h2').textContent = 'Workflow Stopped';
  section.querySelector('p').textContent = 'The workflow was stopped. You can start a new one.';
  const summary = document.getElementById('complete-summary');
  if (summary) summary.innerHTML = '';
}

/* ── Image actions ────────────────────────────────────────────────────────── */
async function approveImage() {
  await authFetch(`/api/image/${sessionId}/approve`, { method: 'POST' });
}

async function reviseImage() {
  const feedback = document.getElementById('image-feedback').value.trim();
  if (!feedback) {
    document.getElementById('image-feedback').focus();
    return;
  }
  document.getElementById('image-feedback').value = '';

  // Show generating state immediately
  handleImageUpdate({ status: 'generating', url: null });

  await authFetch(`/api/image/${sessionId}/revise`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ feedback }),
  });
}

/* ── Progress bar ─────────────────────────────────────────────────────────── */
function updateProgressBar(workflowStatus) {
  const stepMap = {
    researching:      { done: [],                              active: 'step-research' },
    generating:       { done: ['step-research'],              active: 'step-generate' },
    reviewing_posts:  { done: ['step-research','step-generate'], active: 'step-review' },
    generating_image: { done: ['step-research','step-generate','step-review'], active: 'step-image' },
    reviewing_image:  { done: ['step-research','step-generate','step-review'], active: 'step-image' },
    posting:          { done: ['step-research','step-generate','step-review','step-image'], active: 'step-publish' },
    complete:         { done: ['step-research','step-generate','step-review','step-image','step-publish'], active: 'step-complete' },
  };

  const { done = [], active = '' } = stepMap[workflowStatus] || {};

  ['step-research','step-generate','step-review','step-image','step-publish','step-complete'].forEach(id => {
    const el = document.getElementById(id);
    el.classList.remove('active', 'done');
    if (done.includes(id)) el.classList.add('done');
    if (id === active)     el.classList.add('active');
  });
}

/* ── Status strip ─────────────────────────────────────────────────────────── */
function setStatus(msg, isDone = false) {
  document.getElementById('status-text').textContent = msg;
  const icon = document.getElementById('status-icon');
  if (isDone) {
    icon.outerHTML = `<span id="status-icon" style="color:var(--green)">&#10003;</span>`;
  } else {
    icon.className = 'spinner';
  }
}

/* ── Error handling ───────────────────────────────────────────────────────── */
function showError(msg) {
  const banner = document.getElementById('error-banner');
  document.getElementById('error-text').textContent = msg;
  banner.classList.remove('hidden');
  setTimeout(() => banner.classList.add('hidden'), 8000);
}

function hideError() {
  document.getElementById('error-banner').classList.add('hidden');
}

/* ── Reset ────────────────────────────────────────────────────────────────── */
function resetWorkflow() {
  if (eventSource) { eventSource.close(); eventSource = null; }
  sessionId = null;
  Object.keys(postStates).forEach(p => postStates[p] = 'pending');
  imageState.status = 'pending';

  // Restore topic section
  document.getElementById('topic-section').style.display = '';
  document.getElementById('topic-input').value = '';
  resetSubmitBtn();

  // Hide all workflow sections
  ['progress-section','posts-section','image-section','posting-section','complete-section'].forEach(id => {
    document.getElementById(id).classList.add('hidden');
  });

  // Reset stop button
  const stopBtn = document.getElementById('stop-btn');
  stopBtn.classList.remove('hidden');
  stopBtn.disabled = false;
  stopBtn.innerHTML = '<svg width="14" height="14" viewBox="0 0 20 20" fill="currentColor"><rect x="4" y="4" width="12" height="12" rx="2"/></svg> Stop';

  // Clear post content
  for (const p of ['linkedin','facebook','instagram']) {
    document.getElementById(`content-${p}`).textContent = '';
    document.getElementById(`tags-${p}`).innerHTML = '';
    document.getElementById(`chars-${p}`).textContent = '';
    updateBadge(p, 'pending');
    updateCardClass(p, 'pending');
    updateActions(p, 'pending');
    document.getElementById(`feedback-${p}`).value = '';
  }

  // Clear image
  document.getElementById('image-preview').classList.add('hidden');
  document.getElementById('image-preview').src = '';
  document.getElementById('image-placeholder').classList.remove('hidden');
  document.getElementById('image-actions').classList.add('hidden');
  document.getElementById('image-feedback').value = '';

  document.getElementById('new-workflow-btn').classList.add('hidden');
  hideError();
  document.getElementById('topic-input').focus();
}

function resetSubmitBtn() {
  document.getElementById('submit-btn').disabled = false;
  document.getElementById('submit-label').textContent = 'Generate Posts';
  document.getElementById('submit-spinner').classList.add('hidden');
}

/* ── Change Password ──────────────────────────────────────────────────────── */
function showChangePassword() {
  document.getElementById('pwd-modal-overlay').classList.remove('hidden');
  document.getElementById('pwd-current').value = '';
  document.getElementById('pwd-new').value = '';
  document.getElementById('pwd-confirm').value = '';
  document.getElementById('pwd-error').style.display = 'none';
  document.getElementById('pwd-success').style.display = 'none';
  document.getElementById('pwd-submit').disabled = false;
  document.getElementById('pwd-submit').textContent = 'Change Password';
  document.getElementById('pwd-current').focus();
}

function closeChangePassword() {
  document.getElementById('pwd-modal-overlay').classList.add('hidden');
}

async function handleChangePassword(e) {
  e.preventDefault();
  const errorEl = document.getElementById('pwd-error');
  const successEl = document.getElementById('pwd-success');
  const btn = document.getElementById('pwd-submit');
  errorEl.style.display = 'none';
  successEl.style.display = 'none';

  const current = document.getElementById('pwd-current').value;
  const newPass = document.getElementById('pwd-new').value;
  const confirm = document.getElementById('pwd-confirm').value;

  if (newPass !== confirm) {
    errorEl.textContent = 'New passwords do not match.';
    errorEl.style.display = 'block';
    return;
  }

  btn.disabled = true;
  btn.textContent = 'Changing...';

  try {
    const res = await authFetch('/auth/change-password', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ current_password: current, new_password: newPass }),
    });
    const data = await res.json();

    if (!res.ok) {
      errorEl.textContent = data.detail || 'Failed to change password.';
      errorEl.style.display = 'block';
      btn.disabled = false;
      btn.textContent = 'Change Password';
      return;
    }

    successEl.textContent = 'Password changed successfully!';
    successEl.style.display = 'block';
    document.getElementById('pwd-form').style.display = 'none';
    setTimeout(() => closeChangePassword(), 2000);
  } catch (err) {
    errorEl.textContent = 'Connection error. Please try again.';
    errorEl.style.display = 'block';
    btn.disabled = false;
    btn.textContent = 'Change Password';
  }
}

/* ── Init ─────────────────────────────────────────────────────────────────── */
window.addEventListener('DOMContentLoaded', () => {
  document.getElementById('topic-input').focus();
});
