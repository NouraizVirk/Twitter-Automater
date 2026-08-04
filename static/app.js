/* ─────────────────────────────────────────────────
   Twitter Autopilot Dashboard — JavaScript
   Handles API calls, UI updates, live polling
───────────────────────────────────────────────── */

// ── State ──────────────────────────────────────────
let currentView   = 'dashboard';
let allLogs       = [];
let refreshTimer  = null;

// ── View Navigation ─────────────────────────────────
function showView(view) {
  document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));

  document.getElementById(`view-${view}`)?.classList.add('active');
  document.getElementById(`nav-${view}`)?.classList.add('active');

  currentView = view;

  // Load data for the active view
  switch (view) {
    case 'dashboard': loadDashboard(); break;
    case 'queue':     loadQueue();     break;
    case 'history':   loadHistory();   break;
    case 'logs':      loadLogs();      break;
    case 'settings':  loadSettings();  break;
  }
}

// ── API Helpers ─────────────────────────────────────
async function api(path, method = 'GET', body = null) {
  const opts = { method, headers: { 'Content-Type': 'application/json' } };
  if (body) opts.body = JSON.stringify(body);
  try {
    const res = await fetch(path, opts);
    return await res.json();
  } catch (e) {
    console.error('API error:', path, e);
    return null;
  }
}

// ── Toast Notifications ─────────────────────────────
function showToast(msg, type = '') {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.className = `toast ${type} show`;
  setTimeout(() => { t.classList.remove('show'); }, 3500);
}

// ── Status Bar ──────────────────────────────────────
async function updateStatus() {
  const data = await api('/api/status');
  if (!data) return;

  // Chrome dot
  const chromeDot = document.getElementById('chrome-dot');
  chromeDot.className = 'status-dot ' + (data.chrome_connected ? 'online' : 'offline');

  // Scheduler dot
  const schedDot = document.getElementById('sched-dot');
  schedDot.className = 'status-dot ' + (data.scheduler_running ? 'online' : 'offline');

  // API key dot
  const apiDot = document.getElementById('api-dot');
  apiDot.className = 'status-dot ' + (data.api_key_configured ? 'online' : 'warning');

  // Queue badge
  document.getElementById('queue-badge').textContent = data.queue_count || 0;

  // Dashboard stats
  if (currentView === 'dashboard') {
    document.getElementById('stat-today-posts').textContent = data.today?.posts_published ?? 0;
    document.getElementById('stat-queue').textContent        = data.queue_count ?? 0;
    document.getElementById('stat-replies').textContent     = data.today?.replies_sent ?? 0;
    document.getElementById('stat-total').textContent       = data.totals?.total_published ?? 0;

    // Show/hide banners
    const setupBanner  = document.getElementById('setup-banner');
    const chromeBanner = document.getElementById('chrome-banner');
    if (setupBanner)  setupBanner.style.display  = data.api_key_configured  ? 'none' : 'flex';
    if (chromeBanner) chromeBanner.style.display = data.chrome_connected     ? 'none' : 'flex';
  }
}

// ── Dashboard ───────────────────────────────────────
async function loadDashboard() {
  await updateStatus();
  await loadNextPosts();
  await loadRecentLogs();
}

async function loadNextPosts() {
  const posts = await api('/api/queue');
  const el = document.getElementById('next-posts-list');
  if (!el) return;

  if (!posts || posts.length === 0) {
    el.innerHTML = '<div class="empty-state">No posts queued. Click "Scrape Now" to fill the queue.</div>';
    return;
  }

  const html = posts.slice(0, 4).map(p => `
    <div class="post-preview-item">
      ${p.image_url
        ? `<img class="post-preview-img" src="${p.image_url}" alt="preview" onerror="this.style.display='none'" />`
        : `<div class="post-preview-img" style="display:flex;align-items:center;justify-content:center;font-size:24px;">🖼️</div>`
      }
      <div class="post-preview-meta">
        <div style="margin-bottom:4px;">
          ${p.is_thread
            ? '<span class="post-badge badge-thread">🧵 Thread</span>'
            : '<span class="post-badge badge-single">💬 Single</span>'}
          <span class="post-badge badge-queued">⏰ Queued</span>
        </div>
        <div class="post-preview-text">${escHtml(p.tweet_text)}</div>
        <div class="post-preview-time">📅 ${formatDate(p.scheduled_at)} · ${p.source_type || 'unknown'}</div>
      </div>
    </div>
  `).join('');

  el.innerHTML = html;
}

async function loadRecentLogs() {
  const logs = await api('/api/logs?limit=15');
  const el = document.getElementById('recent-logs');
  if (!el || !logs) return;
  el.innerHTML = logs.map(renderLog).join('');
  el.scrollTop = 0;
}

// ── Queue ───────────────────────────────────────────
async function loadQueue() {
  const posts = await api('/api/queue');
  const el = document.getElementById('queue-list');
  if (!el) return;

  if (!posts || posts.length === 0) {
    el.innerHTML = '<div class="empty-state">Queue is empty. Click "Refill Queue" to scrape and generate posts.</div>';
    return;
  }

  el.innerHTML = posts.map(p => renderPostCard(p, true)).join('');
}

// ── History ─────────────────────────────────────────
async function loadHistory() {
  const posts = await api('/api/history');
  const el = document.getElementById('history-list');
  if (!el) return;

  if (!posts || posts.length === 0) {
    el.innerHTML = '<div class="empty-state">No posts published yet.</div>';
    return;
  }

  el.innerHTML = posts.map(p => renderPostCard(p, false)).join('');
}

// ── Logs ────────────────────────────────────────────
async function loadLogs() {
  const logs = await api('/api/logs?limit=300');
  if (!logs) return;
  allLogs = logs;
  filterLogs();
}

function filterLogs() {
  const filter = document.getElementById('log-filter')?.value || 'ALL';
  const el = document.getElementById('logs-list');
  if (!el) return;
  const filtered = filter === 'ALL' ? allLogs : allLogs.filter(l => l.level === filter);
  el.innerHTML = filtered.length ? filtered.map(renderLog).join('') : '<div class="empty-state">No logs found.</div>';
}

// ── Settings ────────────────────────────────────────
async function loadSettings() {
  const cfg = await api('/api/settings');
  if (!cfg) return;

  setVal('s-groq-key',       cfg.ai?.groq_api_key    || '');
  setVal('s-model',          cfg.ai?.model           || 'llama-3.3-70b-versatile');
  setVal('s-temp',           cfg.ai?.temperature     || 0.85);
  setVal('s-posts-per-day',  cfg.schedule?.posts_per_day || 6);
  setVal('s-jitter',         cfg.schedule?.randomize_minutes || 18);

  const threadPct = Math.round((cfg.posting?.thread_ratio || 0.65) * 100);
  setVal('s-thread-ratio',   threadPct);
  document.getElementById('s-thread-ratio-val').textContent = threadPct + '%';

  setCheck('s-reply-enabled',    cfg.reply_guy?.enabled);
  setVal('s-replies-per-day',    cfg.reply_guy?.replies_per_day || 25);
  setCheck('s-images-enabled',   cfg.media?.images?.enabled);
  setCheck('s-videos-enabled',   cfg.media?.videos?.enabled);
  setCheck('s-affiliate-enabled', cfg.monetization?.affiliate_links_enabled);
  setVal('s-inject-freq',        cfg.monetization?.inject_frequency || 5);
  setVal('s-daily-cap',          cfg.stealth?.daily_post_cap || 10);
  setVal('s-min-gap',            cfg.stealth?.min_gap_between_posts_minutes || 45);

  document.getElementById('s-temp').addEventListener('input', function() {
    document.getElementById('s-temp-val') && (document.getElementById('s-temp-val').textContent = (+this.value).toFixed(2));
  });
  document.getElementById('s-thread-ratio').addEventListener('input', function() {
    document.getElementById('s-thread-ratio-val').textContent = this.value + '%';
  });
}

async function saveSettings() {
  const cfg = {
    ai: {
      groq_api_key: getVal('s-groq-key'),
      model:        getVal('s-model'),
      temperature:  +getVal('s-temp'),
    },
    schedule: {
      posts_per_day:      +getVal('s-posts-per-day'),
      randomize_minutes:  +getVal('s-jitter'),
    },
    posting: {
      thread_ratio: +getVal('s-thread-ratio') / 100,
    },
    reply_guy: {
      enabled:         getCheck('s-reply-enabled'),
      replies_per_day: +getVal('s-replies-per-day'),
    },
    media: {
      images: { enabled: getCheck('s-images-enabled') },
      videos: { enabled: getCheck('s-videos-enabled') },
    },
    monetization: {
      affiliate_links_enabled: getCheck('s-affiliate-enabled'),
      inject_frequency:        +getVal('s-inject-freq'),
    },
    stealth: {
      daily_post_cap:               +getVal('s-daily-cap'),
      min_gap_between_posts_minutes: +getVal('s-min-gap'),
    },
  };
  const res = await api('/api/settings', 'POST', cfg);
  if (res?.ok) showToast('✅ Settings saved!', 'success');
  else showToast('❌ Failed to save settings', 'error');
}

async function saveApiKey() {
  const key = document.getElementById('api-key-input')?.value?.trim();
  if (!key) { showToast('Please enter your Groq API key', 'error'); return; }
  const res = await api('/api/settings/api-key', 'POST', { key });
  if (res?.ok) {
    showToast('✅ API key saved! AI engine is ready.', 'success');
    document.getElementById('setup-banner').style.display = 'none';
    await updateStatus();
  } else {
    showToast('❌ Failed to save key', 'error');
  }
}

function toggleKeyVisibility() {
  const input = document.getElementById('s-groq-key');
  if (!input) return;
  input.type = input.type === 'password' ? 'text' : 'password';
}

// ── Actions ─────────────────────────────────────────
async function triggerScrape() {
  const btn = document.getElementById('scrape-btn');
  if (btn) { btn.disabled = true; btn.innerHTML = '<span class="spinner"></span> Scraping...'; }
  showToast('🔍 Scraping content... this may take 30–60 seconds');
  const res = await api('/api/scrape-now', 'POST');
  if (res?.ok) showToast('✅ Scrape started in background!', 'success');
  else showToast('❌ Failed to trigger scrape', 'error');
  setTimeout(() => {
    if (btn) { btn.disabled = false; btn.innerHTML = '🔍 Scrape Now'; }
    loadDashboard();
  }, 5000);
}

async function triggerPublishNext() {
  showToast('🚀 Publishing next post...');
  const res = await api('/api/queue/0/publish', 'POST');
  if (res?.ok) showToast('🚀 Publishing started!', 'success');
  else showToast('❌ Publish failed', 'error');
}

async function publishPost(postId) {
  showToast(`🚀 Publishing post #${postId}...`);
  const res = await api(`/api/queue/${postId}/publish`, 'POST');
  if (res?.ok) {
    showToast('🚀 Publishing in background!', 'success');
    setTimeout(loadQueue, 3000);
  } else {
    showToast('❌ Failed to publish', 'error');
  }
}

async function deletePost(postId) {
  if (!confirm(`Delete post #${postId} from queue?`)) return;
  const res = await api(`/api/queue/${postId}`, 'DELETE');
  if (res?.ok) {
    showToast('🗑️ Post deleted', '');
    loadQueue();
  }
}

async function retryPost(postId) {
  showToast(`🔄 Re-queueing post #${postId}...`);
  const res = await api(`/api/history/${postId}/retry`, 'POST');
  if (res?.ok) {
    showToast('✅ Post moved back to Queue!', 'success');
    loadHistory(); // Refresh history view
  } else {
    showToast('❌ Failed to retry', 'error');
  }
}

// ── Renderers ───────────────────────────────────────
function renderPostCard(p, showActions) {
  const statusBadge = {
    queued:     '<span class="post-badge badge-queued">⏰ Queued</span>',
    published:  '<span class="post-badge badge-published">✅ Published</span>',
    failed:     '<span class="post-badge badge-failed">❌ Failed</span>',
    publishing: '<span class="post-badge badge-queued">🔄 Publishing</span>',
  }[p.status] || '';

  const threadBadge = p.is_thread
    ? '<span class="post-badge badge-thread">🧵 Thread</span>'
    : '<span class="post-badge badge-single">💬 Single</span>';

  const mediaBadge = (p.video_path || p.video_url)
    ? '<span class="post-badge" style="background:rgba(6,182,212,0.15);color:#67e8f9">🎬 Video</span>'
    : (p.image_path || p.image_url)
      ? '<span class="post-badge" style="background:rgba(139,92,246,0.15);color:#a78bfa">🖼️ Image</span>'
      : '';

  const imgHtml = p.image_url
    ? `<img class="post-card-img" src="${p.image_url}" alt="post image" onerror="this.style.display='none'" />`
    : `<div class="post-card-img" style="display:flex;align-items:center;justify-content:center;font-size:28px;color:var(--text-muted)">🖼️</div>`;

  let actions = '';
  if (showActions) {
    actions = `
    <div class="post-card-actions">
      <button class="btn btn-sm btn-success" onclick="publishPost(${p.id})">🚀 Now</button>
      <button class="btn btn-sm btn-danger"  onclick="deletePost(${p.id})">🗑️ Del</button>
    </div>`;
  } else if (p.status === 'failed') {
    actions = `
    <div class="post-card-actions">
      <button class="btn btn-sm btn-success" onclick="retryPost(${p.id})">🔄 Retry</button>
    </div>`;
  }

  const scheduledAt = p.scheduled_at ? `📅 ${formatDate(p.scheduled_at)}` : '';
  const publishedAt = p.published_at ? `✅ ${formatDate(p.published_at)}` : '';
  const source = p.source_type ? `📡 ${p.source_type}` : '';
  const error = p.error_msg ? `<div style="color:var(--red);font-size:11px;margin-top:4px;">⚠️ ${escHtml(p.error_msg)}</div>` : '';

  return `
    <div class="post-card">
      ${imgHtml}
      <div class="post-card-content">
        <div class="post-card-badges">${threadBadge}${statusBadge}${mediaBadge}</div>
        <div class="post-card-text">${escHtml(p.tweet_text)}</div>
        <div class="post-card-meta">
          ${scheduledAt ? `<span>${scheduledAt}</span>` : ''}
          ${publishedAt ? `<span>${publishedAt}</span>` : ''}
          ${source ? `<span>${source}</span>` : ''}
        </div>
        ${error}
      </div>
      ${actions}
    </div>`;
}

function renderLog(l) {
  const time = l.created_at ? l.created_at.slice(11, 19) : '';
  return `
    <div class="log-entry level-${l.level}">
      <span class="log-time">${time}</span>
      <span class="log-level">${l.level}</span>
      <span class="log-module">${l.module}</span>
      <span class="log-msg">${escHtml(l.message)}</span>
    </div>`;
}

// ── Utils ────────────────────────────────────────────
function escHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function formatDate(isoStr) {
  if (!isoStr) return '—';
  try {
    const d = new Date(isoStr);
    return d.toLocaleString('en-US', {
      month: 'short', day: 'numeric',
      hour: '2-digit', minute: '2-digit', hour12: true
    });
  } catch { return isoStr; }
}

function setVal(id, val) {
  const el = document.getElementById(id);
  if (el) el.value = val;
}

function getVal(id) {
  return document.getElementById(id)?.value || '';
}

function setCheck(id, val) {
  const el = document.getElementById(id);
  if (el) el.checked = Boolean(val);
}

function getCheck(id) {
  return document.getElementById(id)?.checked || false;
}

// ── Auto-refresh ─────────────────────────────────────
function startAutoRefresh() {
  updateStatus(); // immediate
  setInterval(async () => {
    await updateStatus();
    if (currentView === 'dashboard') {
      await loadRecentLogs();
    }
  }, 15000); // every 15 seconds
}

// ── Init ─────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  showView('dashboard');
  startAutoRefresh();
});
