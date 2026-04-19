/**
 * المساعد القانوني الذكي — Frontend App
 * SSE Streaming + Markdown rendering + Source Drawer
 */

'use strict';

// ═══════════════════════════════════════════════
// State
// ═══════════════════════════════════════════════
const STATE = {
  sessionId:    null,
  model:        'openai',   // 'openai' | 'claude' | 'gemini' | 'ollama'
  mode:         'expert',   // 'expert' | 'general'
  isStreaming:  false,
  history:      [],         // [{q, ts}] for sidebar
  cotData:      null,
  sources:      [],
};

// ═══════════════════════════════════════════════
// UI Display Settings — Clean Mode (default ON)
// ═══════════════════════════════════════════════
// CLEAN_MODE hides: source drawer button, confidence meter,
// citations panel, follow-up suggestions, and any metadata badges.
// The answer alone is shown — sources are already inlined by the
// answer builder as "(المصدر: ...)".
const UI = {
  CLEAN_MODE:           true,
  SHOW_SOURCES_BUTTON:  false,
  SHOW_CONFIDENCE:      false,
  SHOW_CITATIONS_PANEL: false,
  SHOW_FOLLOWUPS:       false,
  SHOW_METADATA:        false,
};

// ═══════════════════════════════════════════════
// Marked.js Configuration
// ═══════════════════════════════════════════════
marked.setOptions({
  breaks:    true,
  gfm:       true,
  pedantic:  false,
  highlight: function(code, lang) {
    if (lang && hljs.getLanguage(lang)) {
      return hljs.highlight(code, { language: lang }).value;
    }
    return hljs.highlightAuto(code).value;
  },
});

// ═══════════════════════════════════════════════
// Init
// ═══════════════════════════════════════════════
function init() {
  STATE.sessionId = generateSessionId();
  document.getElementById('sessionIdDisplay').textContent = 'جلسة: ' + STATE.sessionId.slice(0,8);
  loadHistory();
}

function generateSessionId() {
  return crypto.randomUUID
    ? crypto.randomUUID()
    : Math.random().toString(36).slice(2) + Date.now().toString(36);
}

// ═══════════════════════════════════════════════
// Mode / Model Selectors
// ═══════════════════════════════════════════════
function setMode(m) {
  STATE.mode = m;
  document.querySelectorAll('.mode-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.mode === m);
  });
}

function setModel(m) {
  STATE.model = m;
  document.querySelectorAll('.model-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.model === m);
  });
  const badge = document.getElementById('modelBadge');
  const labels = {
    'openai': 'ChatGPT — GPT-4o 🤖',
    'claude': 'Claude Sonnet',
    'gemini': 'Gemini 2.0 Flash',
    'ollama': 'Ollama (محلي) ⚡',
  };
  badge.textContent = labels[m] || m;
}

// ═══════════════════════════════════════════════
// Chat Controls
// ═══════════════════════════════════════════════
function newChat() {
  STATE.sessionId = generateSessionId();
  STATE.cotData   = null;
  STATE.sources   = [];
  document.getElementById('sessionIdDisplay').textContent = 'جلسة: ' + STATE.sessionId.slice(0,8);

  // Show welcome, hide messages
  document.getElementById('welcomeScreen').style.display  = '';
  document.getElementById('messagesList').style.display   = 'none';
  document.getElementById('messagesList').innerHTML       = '';

  // Hide CoT panel
  document.getElementById('cotPanel').style.display = 'none';

  setStatus('online');
}

function useSuggestion(btn) {
  const text = btn.querySelector('span:last-child').textContent;
  document.getElementById('queryInput').value = text;
  sendQuery();
}

function toggleSidebar() {
  document.getElementById('sidebar').classList.toggle('collapsed');
}

// ═══════════════════════════════════════════════
// Input Handling
// ═══════════════════════════════════════════════
function handleKeyDown(e) {
  if (e.key === 'Enter' && e.ctrlKey) {
    e.preventDefault();
    sendQuery();
  }
}

function autoResize(el) {
  el.style.height = 'auto';
  el.style.height = Math.min(el.scrollHeight, 160) + 'px';
  // Word counter
  const counter = document.getElementById('wordCounter');
  if (counter) {
    const len = el.value.length;
    counter.textContent = len + '/2000';
    counter.classList.toggle('word-counter-warn', len > 1800);
    counter.classList.toggle('word-counter-over', len > 2000);
  }
}

// ═══════════════════════════════════════════════
// Send Query (SSE)
// ═══════════════════════════════════════════════
async function sendQuery() {
  if (STATE.isStreaming) return;

  const input = document.getElementById('queryInput');
  const q = input.value.trim();
  if (!q) return;

  input.value = '';
  input.style.height = 'auto';

  // Switch to messages view
  showMessagesView();

  // Append user message
  appendUserMessage(q);

  // Save to history
  saveToHistory(q);

  // Start streaming
  STATE.isStreaming = true;
  setStatus('loading');
  disableSend(true);

  // Status message placeholder
  const statusMsgEl = appendStatusMessage('🔍 جارٍ التحليل...');

  // Create assistant bubble placeholder
  const assistantEl = appendAssistantBubble();

  let fullText = '';
  let finalSources = [];
  let finalCitations = [];
  let finalConfidence = null;
  let finalConfidenceLabel = '';
  let finalConfidenceColor = '';
  let logId = 0;

  try {
    const _apiKey = window.APP_API_KEY || '';
    const response = await fetch('/api/v1/stream/', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(_apiKey ? { 'X-API-Key': _apiKey } : {}),
      },
      body: JSON.stringify({
        query:      q,
        session_id: STATE.sessionId,
        model:      STATE.model,
        mode:       STATE.mode,
      }),
    });

    if (!response.ok) throw new Error('HTTP ' + response.status);

    const reader  = response.body.getReader();
    const decoder = new TextDecoder('utf-8');
    let   buffer  = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop(); // keep incomplete line

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        const raw = line.slice(6).trim();
        if (!raw || raw === '[DONE]') continue;

        let event;
        try { event = JSON.parse(raw); } catch { continue; }

        switch (event.type) {
          case 'status':
            updateStatusMessage(statusMsgEl, event.text);
            break;

          case 'start':
            // Backend بدأ البث — احذف رسالة الحالة
            removeStatusMessage(statusMsgEl);
            break;

          case 'chunk':          // ← الحدث الصحيح من الـ backend
          case 'token':          // ← دعم قديم للتوافقية
            removeStatusMessage(statusMsgEl);
            fullText += event.text || '';
            updateAssistantBubble(assistantEl, fullText, true);
            scrollToBottom();
            break;

          case 'done':
            finalSources        = event.sources   || [];
            finalCitations      = event.citations || [];
            finalConfidence     = (typeof event.confidence === 'number') ? event.confidence : null;
            finalConfidenceLabel = event.confidence_label || '';
            finalConfidenceColor = event.confidence_color || '';
            logId = event.log_id || 0;
            if (event.cot) handleCOT(event.cot);
            if (event.from_cache) showToast('⚡ إجابة من الذاكرة الذكية', 2000);
            break;

          case 'error':
            removeStatusMessage(statusMsgEl);
            updateAssistantBubble(assistantEl,
              '⚠️ ' + (event.text || 'حدث خطأ. يرجى المحاولة مرة أخرى.'), false);
            break;
        }
      }
    }

    // Finalize — only overwrite bubble if we actually got text (don't clear error messages)
    removeStatusMessage(statusMsgEl);
    if (fullText.trim()) {
      updateAssistantBubble(assistantEl, fullText, false);
    }

    // 1. تظليل الاستشهادات [1][2][3] مع tooltip
    if (finalCitations.length > 0) {
      highlightCitationRefs(assistantEl, finalCitations);
    }

    const msgParent = assistantEl.parentElement;

    // 2. شريط مستوى الثقة (hidden in CLEAN_MODE)
    if (UI.SHOW_CONFIDENCE && finalConfidence !== null) {
      addConfidenceMeter(msgParent, finalConfidence, finalConfidenceLabel, finalConfidenceColor, finalSources.length);
    }

    // 3. لوحة الاستشهادات (hidden in CLEAN_MODE)
    if (UI.SHOW_CITATIONS_PANEL && finalCitations.length > 0) {
      addCitationsPanel(msgParent, finalCitations);
    } else if (UI.SHOW_SOURCES_BUTTON && finalSources.length > 0) {
      STATE.sources = finalSources;
      addSourcesButton(assistantEl, finalSources);
    }

    // 4. أسئلة المتابعة المقترحة (hidden in CLEAN_MODE)
    if (UI.SHOW_FOLLOWUPS && fullText && fullText.length > 100) {
      loadFollowupQuestions(msgParent, q, fullText);
    }

    // 5. زر تصدير PDF (الخطوة 24)
    if (fullText && fullText.length > 50) {
      addExportPdfButton(msgParent, q, fullText, finalSources);
    }

    // أضف أزرار التقييم (فقط للإجابات القانونية)
    if (fullText && fullText.length > 50) {
      addFeedbackButtons(assistantEl, logId, q, fullText, finalSources);
    }

  } catch (err) {
    console.error('Stream error:', err);
    removeStatusMessage(statusMsgEl);
    updateAssistantBubble(assistantEl, '⚠️ تعذّر الاتصال بالخادم. يرجى المحاولة مرة أخرى.', false);
    // Retry button
    const retryBtn = document.createElement('button');
    retryBtn.className   = 'retry-btn';
    retryBtn.textContent = '🔄 إعادة المحاولة';
    retryBtn.onclick = () => {
      retryBtn.remove();
      document.getElementById('queryInput').value = q;
      sendQuery();
    };
    assistantEl.parentElement.appendChild(retryBtn);
  }

  STATE.isStreaming = false;
  setStatus('online');
  disableSend(false);
  scrollToBottom();
}

// ═══════════════════════════════════════════════
// DOM Helpers
// ═══════════════════════════════════════════════
function showMessagesView() {
  document.getElementById('welcomeScreen').style.display  = 'none';
  document.getElementById('messagesList').style.display   = 'flex';
}

function appendUserMessage(text) {
  const list = document.getElementById('messagesList');
  const msg  = document.createElement('div');
  msg.className = 'message user';
  msg.innerHTML = `
    <div class="msg-meta">
      <span class="msg-avatar">👤</span>
      <span>${formatTime()}</span>
    </div>
    <div class="msg-bubble">${escapeHtml(text)}</div>
  `;
  list.appendChild(msg);
  scrollToBottom();
}

function appendAssistantBubble() {
  const list  = document.getElementById('messagesList');
  const msg   = document.createElement('div');
  msg.className = 'message assistant';
  msg.innerHTML = `
    <div class="msg-meta">
      <span class="msg-avatar">⚖️</span>
      <span>${formatTime()}</span>
    </div>
    <div class="msg-bubble streaming-cursor" id="currentBubble"></div>
  `;
  list.appendChild(msg);
  scrollToBottom();
  return msg.querySelector('#currentBubble');
}

function updateAssistantBubble(el, text, streaming) {
  // Render markdown
  el.innerHTML = marked.parse(text || '');
  if (streaming) {
    el.classList.add('streaming-cursor');
  } else {
    el.classList.remove('streaming-cursor');
    el.removeAttribute('id'); // Clean up id
    // Re-run syntax highlighting
    el.querySelectorAll('pre code').forEach(block => hljs.highlightElement(block));
    // Add copy buttons after streaming ends
    if (text && text.trim().length > 30) {
      addCopyButton(el);
      addCodeBlockCopyButtons(el);
    }
  }
}

function addSourcesButton(bubbleEl, sources) {
  const parent = bubbleEl.parentElement; // message div
  const btn    = document.createElement('button');
  btn.className = 'btn-sources';
  btn.onclick   = () => openDrawer(sources);
  btn.innerHTML = `📚 المصادر (${sources.length})`;
  parent.appendChild(btn);
}

// مراحل التقدم — كل status event يرفع النسبة
const _PROGRESS_STAGES = [
  { text: 'تحليل النية',            pct: 15 },
  { text: 'تحويل السؤال',           pct: 25 },
  { text: 'تحليل السؤال',           pct: 35 },
  { text: 'البحث في قاعدة',         pct: 55 },
  { text: 'تحليل المصادر',          pct: 75 },
  { text: 'صياغة الإجابة',          pct: 90 },
];

function appendStatusMessage(text) {
  const list = document.getElementById('messagesList');
  const el   = document.createElement('div');
  el.className = 'status-message';
  el.innerHTML = `
    <div class="status-spinner"></div>
    <span class="status-text">${text}</span>
    <div class="status-progress-bar"><div class="status-progress-fill" style="width:5%"></div></div>
  `;
  list.appendChild(el);
  scrollToBottom();
  return el;
}

function updateStatusMessage(el, text) {
  if (!el || !el.parentNode) return;
  const span = el.querySelector('.status-text');
  if (span) span.textContent = text;
  // حساب نسبة التقدم بناءً على مرحلة التقدم
  const fill = el.querySelector('.status-progress-fill');
  if (fill) {
    const stage = _PROGRESS_STAGES.find(s => text.includes(s.text));
    if (stage) fill.style.width = stage.pct + '%';
  }
}

function removeStatusMessage(el) {
  if (el && el.parentNode) el.parentNode.removeChild(el);
}

// ═══════════════════════════════════════════════
// Chain of Thought
// ═══════════════════════════════════════════════
function handleCOT(data) {
  STATE.cotData = data;
  if (!data) return;

  const panel = document.getElementById('cotPanel');
  const body  = document.getElementById('cotBody');

  panel.style.display = '';

  const rows = [];
  if (data.understanding) rows.push({ label:'الفهم', val: data.understanding });
  if (data.law_areas)     rows.push({ label:'مجالات القانون', val: Array.isArray(data.law_areas) ? data.law_areas.join('، ') : data.law_areas });
  if (data.search_queries) rows.push({ label:'استعلامات البحث', val: Array.isArray(data.search_queries) ? data.search_queries.join(' | ') : data.search_queries });
  if (data.complexity)    rows.push({ label:'مستوى التعقيد', val: data.complexity });

  body.innerHTML = rows.map(r =>
    `<div class="cot-row">
      <span class="cot-label">${r.label}:</span>
      <span class="cot-value">${escapeHtml(String(r.val))}</span>
     </div>`
  ).join('');
}

function toggleCOT() {
  document.getElementById('cotPanel').classList.toggle('collapsed');
  const body = document.getElementById('cotBody');
  const icon = document.getElementById('cotToggleIcon');
  const collapsed = document.getElementById('cotPanel').classList.contains('collapsed');
  body.style.display = collapsed ? 'none' : '';
  icon.textContent   = collapsed ? '▶' : '▼';
}

// ═══════════════════════════════════════════════
// Source Drawer
// ═══════════════════════════════════════════════
function openDrawer(sources) {
  const body    = document.getElementById('drawerBody');
  const drawer  = document.getElementById('sourceDrawer');
  const overlay = document.getElementById('drawerOverlay');

  body.innerHTML = sources.map(s => buildSourceCard(s)).join('');

  drawer.style.display  = 'flex';
  overlay.style.display = '';
}

function closeDrawer() {
  document.getElementById('sourceDrawer').style.display  = 'none';
  document.getElementById('drawerOverlay').style.display = 'none';
}

function buildSourceCard(s) {
  // الـ API يرسل: title, law_num, law_year, article, source, score, excerpt, mizan_link
  const scoreNum  = typeof s.score === 'number' ? s.score : parseFloat(s.score) || 0;
  const scorePct  = scoreNum > 0 ? `${Math.round(scoreNum * 100)}%` : '';
  const title     = escapeHtml(s.title    || 'تشريع');
  const lawNum    = escapeHtml(s.law_num  || '');
  const lawYear   = escapeHtml(s.law_year || '');
  const article   = escapeHtml(String(s.article || ''));
  const excerpt   = escapeHtml((s.excerpt || '').slice(0, 350));
  const mizanUrl  = s.mizan_link || '';           // رابط جاهز من الـ backend
  const isAttach  = s.source === 'attachment';
  const attachBadge = isAttach ? `<span class="source-tag source-tag-attach" title="مرفق رسمي من الجريدة الرسمية">📎 مرفق رسمي</span>` : '';

  // شريط النجوم بحسب النسبة
  const stars = scoreNum >= 0.85 ? '★★★' : scoreNum >= 0.70 ? '★★☆' : '★☆☆';

  return `
    <div class="source-card${isAttach ? ' source-card-attach' : ''}">
      <div class="source-card-header">
        <div class="source-card-title">${title}</div>
        ${scorePct ? `<div class="source-card-score" title="نسبة الصلة">${stars} ${scorePct}</div>` : ''}
      </div>
      <div class="source-card-meta">
        ${attachBadge}
        ${lawNum   ? `<span class="source-tag">قانون رقم ${lawNum}</span>` : ''}
        ${lawYear  ? `<span class="source-tag">لسنة ${lawYear}</span>`     : ''}
        ${article  ? `<span class="source-tag">المادة ${article}</span>`   : ''}
      </div>
      ${excerpt ? `<div class="source-card-excerpt">${excerpt}</div>` : ''}
      ${mizanUrl
        ? `<a class="source-card-link" href="${mizanUrl}" target="_blank" rel="noopener noreferrer">
             🔗 عرض في بوابة الميزان القانونية
           </a>`
        : ''}
    </div>
  `;
}

// ═══════════════════════════════════════════════
// History
// ═══════════════════════════════════════════════
function saveToHistory(q) {
  const item = { q: q.slice(0, 80), ts: Date.now() };
  STATE.history.unshift(item);
  if (STATE.history.length > 20) STATE.history.pop();
  try { localStorage.setItem('legalAssistantHistory', JSON.stringify(STATE.history)); } catch {}
  renderHistory();
}

function loadHistory() {
  try {
    const raw = localStorage.getItem('legalAssistantHistory');
    if (raw) STATE.history = JSON.parse(raw);
  } catch {}
  renderHistory();
}

function renderHistory() {
  const list = document.getElementById('historyList');
  if (!STATE.history.length) {
    list.innerHTML = '<p class="history-empty">لا توجد محادثات سابقة</p>';
    return;
  }
  list.innerHTML = STATE.history.map((item, i) =>
    `<div class="history-item" title="${escapeHtml(item.q)}" onclick="loadHistoryItem(${i})">
       ${escapeHtml(item.q)}
     </div>`
  ).join('');
}

function loadHistoryItem(idx) {
  const item = STATE.history[idx];
  if (!item) return;
  document.getElementById('queryInput').value = item.q;
  document.getElementById('queryInput').focus();
}

// ═══════════════════════════════════════════════
// Utilities
// ═══════════════════════════════════════════════
function setStatus(s) {
  const dot = document.getElementById('statusDot');
  dot.className = 'status-dot ' + s;
}

function disableSend(disabled) {
  const btn  = document.getElementById('sendBtn');
  const icon = document.getElementById('sendIcon');
  btn.disabled = disabled;
  icon.textContent = disabled ? '⏳' : '➤';
}

function scrollToBottom() {
  const c = document.getElementById('chatContainer');
  c.scrollTop = c.scrollHeight;
}

function escapeHtml(str) {
  if (!str) return '';
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function formatTime() {
  return new Date().toLocaleTimeString('ar-QA', { hour:'2-digit', minute:'2-digit' });
}

function showToast(msg, duration = 3000) {
  const t = document.getElementById('statusToast');
  t.textContent = msg;
  t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), duration);
}

// ═══════════════════════════════════════════════
// نظام التغذية الراجعة (التعلم التراكمي)
// ═══════════════════════════════════════════════
function addFeedbackButtons(bubbleEl, logId, query, answer, sources) {
  const parent = bubbleEl.parentElement;
  // لا تكرر إذا كانت الأزرار موجودة
  if (parent.querySelector('.feedback-bar')) return;

  const bar = document.createElement('div');
  bar.className = 'feedback-bar';
  bar.innerHTML = `
    <span class="feedback-label">هل كانت الإجابة مفيدة؟</span>
    <button class="feedback-btn like"   onclick="submitFeedback(this, ${logId}, 1,  '${escJs(query)}', '${escJs(answer)}', ${JSON.stringify(sources)})" title="مفيدة">👍</button>
    <button class="feedback-btn dislike" onclick="submitFeedback(this, ${logId}, -1, '${escJs(query)}', '${escJs(answer)}', ${JSON.stringify(sources)})" title="غير مفيدة">👎</button>
  `;
  parent.appendChild(bar);
}

async function submitFeedback(btn, logId, value, query, answer, sources) {
  const bar = btn.closest('.feedback-bar');

  // إذا تقييم سلبي — اسأل عن تعليق
  let comment = '';
  if (value === -1) {
    comment = prompt('ما المشكلة في الإجابة؟ (اختياري)') || '';
  }

  try {
    // 1. قديم: query_logs (للتوافقية)
    fetch('/api/v1/feedback/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        log_id: logId, value, query, answer,
        note: comment, sources: sources || [], model: STATE.model,
      }),
    }).catch(() => {});

    // 2. جديد: جدول feedback المخصص
    fetch('/api/v1/feedback', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        rating:      value,
        query_id:    logId || 0,
        session_id:  STATE.sessionId || '',
        comment:     comment,
        query_text:  (query  || '').slice(0, 300),
        answer_text: (answer || '').slice(0, 800),
      }),
    }).catch(() => {});

    bar.innerHTML = value === 1
      ? '<span class="feedback-thanks">شكراً! سيساعد تقييمك في تحسين النظام ⭐</span>'
      : '<span class="feedback-thanks">شكراً على ملاحظتك، سنعمل على التحسين</span>';
  } catch {
    bar.innerHTML = '<span class="feedback-thanks">تم التسجيل</span>';
  }
}

function escJs(str) {
  if (!str) return '';
  return str.slice(0, 200).replace(/\\/g, '\\\\').replace(/'/g, "\\'").replace(/\n/g, '\\n');
}

// ═══════════════════════════════════════════════
// إحصائيات التعلم
// ═══════════════════════════════════════════════
async function loadLearningStats() {
  try {
    const r = await fetch('/api/v1/learning/stats');
    const s = await r.json();
    if (!s || s.error) return;

    // تحديث الـ sidebar
    const el = document.getElementById('learningStats');
    if (!el) return;
    el.innerHTML = `
      <div class="learn-stat"><span>${s.total_queries || 0}</span><small>محادثة مسجّلة</small></div>
      <div class="learn-stat"><span>${s.found_rate || 0}%</span><small>معدل الإجابة</small></div>
      <div class="learn-stat"><span>${s.satisfaction_rate || 0}%</span><small>رضا المستخدمين</small></div>
      <div class="learn-stat"><span>${s.cache_size || 0}</span><small>إجابة في الذاكرة</small></div>
    `;
  } catch {}
}

// ═══════════════════════════════════════════════
// زر نسخ الإجابة
// ═══════════════════════════════════════════════
function addCopyButton(bubbleEl) {
  const parent = bubbleEl.parentElement;
  if (parent.querySelector('.copy-btn')) return;   // لا تكرار

  const btn = document.createElement('button');
  btn.className   = 'copy-btn';
  btn.title       = 'نسخ الإجابة';
  btn.textContent = '📋 نسخ';
  btn.onclick = () => {
    const text = bubbleEl.innerText || bubbleEl.textContent || '';
    if (!text.trim()) return;
    navigator.clipboard.writeText(text.trim()).then(() => {
      btn.textContent = '✅ تم النسخ';
      setTimeout(() => { btn.textContent = '📋 نسخ'; }, 2000);
    }).catch(() => {
      // fallback للمتصفحات القديمة
      const ta = document.createElement('textarea');
      ta.value = text;
      ta.style.position = 'fixed';
      ta.style.opacity  = '0';
      document.body.appendChild(ta);
      ta.select();
      document.execCommand('copy');
      document.body.removeChild(ta);
      btn.textContent = '✅ تم النسخ';
      setTimeout(() => { btn.textContent = '📋 نسخ'; }, 2000);
    });
  };
  parent.appendChild(btn);
}

// ═══════════════════════════════════════════════
// مؤشر مستوى الثقة
// ═══════════════════════════════════════════════
function renderConfidenceIndicator(score) {
  if (!score && score !== 0) return '';
  const pct   = Math.round(Math.min(100, Math.max(0, score)));
  const color = pct >= 80 ? '#10b981' : pct >= 60 ? '#f59e0b' : '#ef4444';
  const label = pct >= 80 ? 'ثقة عالية' : pct >= 60 ? 'ثقة متوسطة' : 'ثقة منخفضة';
  return `<span class="confidence-badge" style="color:${color};border-color:${color};"
    title="${label}: ${pct}%">
    ${pct >= 80 ? '🟢' : pct >= 60 ? '🟡' : '🔴'} ${pct}%
  </span>`;
}

function addConfidenceBadge(parent, score) {
  if (!score && score !== 0) return;
  if (parent.querySelector('.confidence-badge')) return;
  const html = renderConfidenceIndicator(score);
  if (!html) return;
  const el = document.createElement('span');
  el.innerHTML = html;
  const badge = el.firstElementChild;
  if (badge) parent.appendChild(badge);
}

// ═══════════════════════════════════════════════
// Mobile Menu — Hamburger Toggle
// ═══════════════════════════════════════════════
function initMobileMenu() {
  const sidebar = document.getElementById('sidebar');
  if (!sidebar) return;

  // إنشاء زر الهامبرغر إذا لم يكن موجوداً
  let toggle = document.getElementById('mobile-toggle');
  if (!toggle) {
    toggle = document.createElement('button');
    toggle.id        = 'mobile-toggle';
    toggle.className = 'mobile-toggle-btn';
    toggle.title     = 'القائمة';
    toggle.innerHTML = '<span class="hamburger-icon">☰</span>';
    toggle.setAttribute('aria-label', 'تبديل القائمة الجانبية');
    document.body.appendChild(toggle);
  }

  toggle.addEventListener('click', () => {
    sidebar.classList.toggle('mobile-open');
    toggle.innerHTML = sidebar.classList.contains('mobile-open')
      ? '<span class="hamburger-icon">✕</span>'
      : '<span class="hamburger-icon">☰</span>';
  });

  // إغلاق القائمة عند النقر خارجها على الموبايل
  document.addEventListener('click', (e) => {
    if (window.innerWidth < 768
        && sidebar.classList.contains('mobile-open')
        && !sidebar.contains(e.target)
        && e.target !== toggle) {
      sidebar.classList.remove('mobile-open');
      toggle.innerHTML = '<span class="hamburger-icon">☰</span>';
    }
  });

  // إغلاق عند تغيير الحجم للـ desktop
  window.addEventListener('resize', () => {
    if (window.innerWidth >= 768) {
      sidebar.classList.remove('mobile-open');
      toggle.innerHTML = '<span class="hamburger-icon">☰</span>';
    }
  });
}


// ═══════════════════════════════════════════════
// تظليل الاستشهادات [1][2][3] + Tooltip
// ═══════════════════════════════════════════════
function highlightCitationRefs(bubbleEl, citations) {
  if (!bubbleEl || !citations || citations.length === 0) return;
  let html = bubbleEl.innerHTML;

  // بناء خريطة رقم → نص للـ tooltip
  const citeMap = {};
  citations.forEach(cite => {
    const num = cite.number;
    if (!num) return;
    const src = cite.source || '';
    const art = cite.article ? `المادة ${cite.article}` : '';
    const txt = (cite.text || '').slice(0, 160);
    citeMap[num] = `${src}${art ? ' — ' + art : ''}${txt ? ': ' + txt + '…' : ''}`;
  });

  // استبدال [N] بـ <span class="cite-ref">
  html = html.replace(/\[(\d+)\]/g, (match, num) => {
    const n = parseInt(num, 10);
    const tooltip = citeMap[n]
      ? escapeHtml(citeMap[n])
      : `المصدر ${n}`;
    return `<span class="cite-ref" title="${tooltip}">[${n}]</span>`;
  });

  bubbleEl.innerHTML = html;
}

// ═══════════════════════════════════════════════
// شريط مستوى الثقة (Confidence Meter)
// ═══════════════════════════════════════════════
function addConfidenceMeter(parentEl, score, label, color, sourcesCount) {
  if (!parentEl || parentEl.querySelector('.confidence-meter')) return;

  const pct = Math.round(Math.min(100, Math.max(0, score || 0)));

  // حدد الـ class من color أو من score
  let colorClass = 'low';
  if (color === 'green' || pct >= 80)  colorClass = 'high';
  else if (color === 'yellow' || pct >= 60) colorClass = 'medium';

  const displayLabel = label || (pct >= 80 ? 'عالية' : pct >= 60 ? 'متوسطة' : 'منخفضة');
  const icon  = pct >= 80 ? '🟢' : pct >= 60 ? '🟡' : '🔴';
  const srcTxt = sourcesCount > 0
    ? `الثقة بناءً على ${sourcesCount} مصادر قانونية`
    : 'مستوى الثقة في الإجابة';

  const meter = document.createElement('div');
  meter.className = 'confidence-meter';
  meter.title     = srcTxt;
  meter.innerHTML = `
    <div class="confidence-meter-label">
      <span>${icon}</span>
      <span>مستوى الثقة: <strong>${displayLabel}</strong></span>
      <span class="confidence-pct">${pct}%</span>
    </div>
    <div class="confidence-bar">
      <div class="confidence-fill ${colorClass}" style="width:0%"></div>
    </div>
  `;

  parentEl.appendChild(meter);

  // تحريك الشريط
  requestAnimationFrame(() => {
    setTimeout(() => {
      const fill = meter.querySelector('.confidence-fill');
      if (fill) fill.style.width = pct + '%';
    }, 50);
  });
}

// ═══════════════════════════════════════════════
// لوحة الاستشهادات (Citations Accordion)
// ═══════════════════════════════════════════════
function addCitationsPanel(parentEl, citations) {
  if (!parentEl || !citations || citations.length === 0) return;
  if (parentEl.querySelector('.citations-panel')) return;

  const panel  = document.createElement('div');
  panel.className = 'citations-panel';

  const header = document.createElement('div');
  header.className = 'citations-panel-header';
  header.innerHTML = `
    <span>📋 المصادر القانونية (${citations.length})</span>
    <span class="citations-toggle-icon">▼</span>
  `;

  const body   = document.createElement('div');
  body.className  = 'citations-panel-body';
  body.innerHTML  = citations.map(c => buildCitationItem(c)).join('');

  header.addEventListener('click', () => {
    const collapsed = panel.classList.toggle('collapsed');
    header.querySelector('.citations-toggle-icon').textContent = collapsed ? '▶' : '▼';
  });

  panel.appendChild(header);
  panel.appendChild(body);
  parentEl.appendChild(panel);
}

function buildCitationItem(cite) {
  const num     = cite.number  || '?';
  const source  = escapeHtml(cite.source  || '');
  const article = cite.article ? `المادة ${escapeHtml(String(cite.article))}` : '';
  const text    = escapeHtml((cite.text || '').slice(0, 280));
  const url     = cite.url || '';
  const title   = [source, article].filter(Boolean).join(' — ');

  return `
    <div class="citation-item">
      <div class="citation-num">[${num}]</div>
      <div class="citation-content">
        ${title  ? `<div class="citation-title">${title}</div>` : ''}
        ${text   ? `<div class="citation-text">${text}</div>` : ''}
        ${url    ? `<a class="citation-link" href="${url}" target="_blank" rel="noopener noreferrer">اقرأ النص الكامل ↗</a>` : ''}
      </div>
    </div>
  `;
}

// ═══════════════════════════════════════════════
// أسئلة المتابعة المقترحة (Follow-up Chips)
// ═══════════════════════════════════════════════
async function loadFollowupQuestions(parentEl, query, answer) {
  if (!parentEl || parentEl.querySelector('.followup-section')) return;

  const section = document.createElement('div');
  section.className = 'followup-section';
  section.innerHTML = '<div class="followup-loading">⏳ جارٍ إعداد أسئلة مقترحة…</div>';
  parentEl.appendChild(section);

  try {
    const resp = await fetch('/api/v1/followup', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        query,
        answer: answer.slice(0, 600),
        model:  STATE.model,
      }),
    });

    if (!resp.ok) throw new Error('HTTP ' + resp.status);

    const data      = await resp.json();
    const questions = (data.questions || []).filter(Boolean).slice(0, 3);

    if (questions.length === 0) { section.remove(); return; }

    section.innerHTML = `
      <div class="followup-label">💡 أسئلة مقترحة:</div>
      <div class="followup-chips">
        ${questions.map(qText =>
          `<button class="followup-chip" onclick="useFollowup(this)">${escapeHtml(qText)}</button>`
        ).join('')}
      </div>
    `;
  } catch (_err) {
    section.remove(); // فشل صامت — لا تُعطّل الواجهة
  }
}

function useFollowup(btn) {
  const text = btn.textContent || btn.innerText || '';
  if (!text.trim()) return;
  document.getElementById('queryInput').value = text.trim();
  sendQuery();
}

// ═══════════════════════════════════════════════
// الخطوة 24 — Voice Input (Web Speech API)
// ═══════════════════════════════════════════════
function initVoiceInput() {
  const actions = document.querySelector('.input-actions');
  if (!actions || document.getElementById('micBtn')) return;

  const btn = document.createElement('button');
  btn.id        = 'micBtn';
  btn.className = 'mic-btn';
  btn.title     = 'إدخال صوتي';
  btn.innerHTML = '🎤';
  btn.type      = 'button';
  btn.onclick   = startVoice;

  // أضف الزر قبل زر الإرسال
  actions.insertBefore(btn, actions.firstChild);
}

function startVoice() {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) {
    showToast('المتصفح لا يدعم الإدخال الصوتي. استخدم Chrome أو Edge.', 3500);
    return;
  }
  const rec   = new SR();
  const btn   = document.getElementById('micBtn');
  const input = document.getElementById('queryInput');

  rec.lang           = 'ar-QA';
  rec.interimResults = false;
  rec.maxAlternatives = 1;

  rec.onstart = () => {
    btn.innerHTML = '🔴';
    btn.classList.add('mic-active');
    showToast('جارٍ الاستماع...', 60000);
  };

  rec.onresult = (e) => {
    const transcript = e.results[0][0].transcript;
    input.value = transcript;
    autoResize(input);
    input.focus();
  };

  rec.onerror = () => {
    showToast('تعذّر التعرف على الصوت. حاول مجدداً.', 2500);
  };

  rec.onend = () => {
    btn.innerHTML = '🎤';
    btn.classList.remove('mic-active');
    // إخفاء toast الاستماع
    const t = document.getElementById('statusToast');
    if (t && t.textContent.includes('الاستماع')) {
      t.classList.remove('show');
    }
  };

  rec.start();
}

// ═══════════════════════════════════════════════
// الخطوة 24 — PDF Export (jsPDF)
// ═══════════════════════════════════════════════
function addExportPdfButton(parentEl, question, answer, sources) {
  if (parentEl.querySelector('.pdf-btn')) return;

  const btn = document.createElement('button');
  btn.className   = 'pdf-btn';
  btn.title       = 'تصدير الإجابة كـ PDF';
  btn.textContent = '📄 تصدير';
  btn.type        = 'button';
  btn.onclick     = () => exportToPdf(question, answer, sources);
  parentEl.appendChild(btn);
}

function exportToPdf(question, answer, sources) {
  try {
    const { jsPDF } = window.jspdf;
    if (!jsPDF) { showToast('مكتبة PDF لم تُحمَّل بعد.', 2500); return; }

    const doc   = new jsPDF({ orientation: 'portrait', unit: 'mm', format: 'a4' });
    const W     = doc.internal.pageSize.getWidth();
    const margin = 15;
    const maxW   = W - margin * 2;
    let y        = 20;

    // ── دالة مساعدة لإضافة سطر ──
    const addLine = (text, size = 11, bold = false, color = [30, 30, 30]) => {
      doc.setFontSize(size);
      doc.setFont('helvetica', bold ? 'bold' : 'normal');
      doc.setTextColor(...color);
      const lines = doc.splitTextToSize(text, maxW);
      lines.forEach(line => {
        if (y > 270) { doc.addPage(); y = 20; }
        // jsPDF: x from right edge for RTL visual
        doc.text(line, W - margin, y, { align: 'right' });
        y += size * 0.5 + 2;
      });
      y += 3;
    };

    // ── رأس الصفحة ──
    addLine('المساعد القانوني القطري — الميزان', 16, true, [30, 60, 120]);
    addLine(new Date().toLocaleDateString('ar-QA', { year:'numeric', month:'long', day:'numeric' }), 9, false, [100, 100, 100]);
    y += 4;

    // ── السؤال ──
    addLine('السؤال:', 12, true, [50, 80, 160]);
    addLine(question || '', 11);
    y += 2;

    // ── الإجابة ──
    addLine('الإجابة:', 12, true, [50, 80, 160]);
    // تنظيف Markdown بسيط
    const cleanAnswer = (answer || '')
      .replace(/#{1,6}\s*/g, '')
      .replace(/\*\*(.*?)\*\*/g, '$1')
      .replace(/\*(.*?)\*/g, '$1')
      .replace(/\[(\d+)\]/g, '[$1]')
      .trim();
    addLine(cleanAnswer, 10);

    // ── المصادر ──
    if (sources && sources.length > 0) {
      y += 4;
      addLine('المصادر:', 12, true, [50, 80, 160]);
      sources.slice(0, 5).forEach((s, i) => {
        const label = s.law_name || s.source || s.title || `مصدر ${i + 1}`;
        const art   = s.article_number ? ` — المادة ${s.article_number}` : '';
        addLine(`${i + 1}. ${label}${art}`, 9);
      });
    }

    // ── تذييل ──
    y = doc.internal.pageSize.getHeight() - 12;
    doc.setFontSize(8);
    doc.setTextColor(150, 150, 150);
    doc.text('تم الإنشاء بواسطة المساعد القانوني الذكي — الميزان القطري', W / 2, y, { align: 'center' });

    const ts = new Date().toISOString().slice(0, 10);
    doc.save(`legal-answer-${ts}.pdf`);
    showToast('✅ تم تصدير الإجابة كـ PDF', 2500);
  } catch (err) {
    console.error('PDF export error:', err);
    showToast('تعذّر إنشاء PDF. تأكد من تحميل الصفحة كاملاً.', 3000);
  }
}

// ═══════════════════════════════════════════════
// الخطوة 23 — Compare Modal
// ═══════════════════════════════════════════════
function openCompareModal() {
  document.getElementById('compareModal').style.display   = 'flex';
  document.getElementById('compareOverlay').style.display = 'block';
  document.getElementById('compareResult').style.display  = 'none';
  document.getElementById('compareLawA').focus();
}

function closeCompareModal() {
  document.getElementById('compareModal').style.display   = 'none';
  document.getElementById('compareOverlay').style.display = 'none';
}

async function runCompare() {
  const lawA   = (document.getElementById('compareLawA').value || '').trim();
  const lawB   = (document.getElementById('compareLawB').value || '').trim();
  const aspect = (document.getElementById('compareAspect').value || '').trim();

  if (!lawA || !lawB) {
    showToast('يجب تحديد اسم القانونين', 2500);
    return;
  }

  const runBtn    = document.getElementById('compareRunBtn');
  const resultEl  = document.getElementById('compareResult');

  runBtn.disabled   = true;
  runBtn.textContent = '⏳ جارٍ المقارنة...';
  resultEl.style.display = 'none';

  try {
    const res = await fetch('/api/v1/compare', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ law_a: lawA, law_b: lawB, aspect }),
    });
    const data = await res.json();

    if (data.error) {
      resultEl.innerHTML     = `<p class="compare-error">⚠️ ${escapeHtml(data.error)}</p>`;
      resultEl.style.display = 'block';
      return;
    }

    resultEl.innerHTML     = buildCompareTable(data, lawA, lawB);
    resultEl.style.display = 'block';
  } catch (err) {
    resultEl.innerHTML     = `<p class="compare-error">⚠️ تعذّر الاتصال بالخادم.</p>`;
    resultEl.style.display = 'block';
  } finally {
    runBtn.disabled   = false;
    runBtn.textContent = '🔍 قارن الآن';
  }
}

function buildCompareTable(data, lawA, lawB) {
  const a = data.law_a || {};
  const b = data.law_b || {};
  const esc = escapeHtml;

  const row = (label, valA, valB) => `
    <tr>
      <td class="compare-label">${esc(label)}</td>
      <td class="compare-cell">${esc(valA || '—')}</td>
      <td class="compare-cell">${esc(valB || '—')}</td>
    </tr>`;

  return `
    <h4 class="compare-aspect-title">📋 ${esc(data.aspect || 'مقارنة عامة')}</h4>
    <div class="compare-table-wrap">
      <table class="compare-table">
        <thead>
          <tr>
            <th>الجانب</th>
            <th>${esc(lawA)}</th>
            <th>${esc(lawB)}</th>
          </tr>
        </thead>
        <tbody>
          ${row('المادة المرجعية', a.article, b.article)}
          ${row('الملخص', a.summary, b.summary)}
          ${row('النص', a.text, b.text)}
        </tbody>
      </table>
    </div>
    ${data.difference ? `<div class="compare-diff">💡 <strong>الفرق الجوهري:</strong> ${esc(data.difference)}</div>` : ''}`;
}

// ═══════════════════════════════════════════════
// الخطوة 39 — i18n Localization
// ═══════════════════════════════════════════════

const I18N = { ar: null, en: null };
let _currentLang = localStorage.getItem('app_lang') || 'ar';

async function loadI18n(lang) {
  if (I18N[lang]) return I18N[lang];
  try {
    const res = await fetch(`/static/i18n/${lang}.json`);
    I18N[lang] = await res.json();
  } catch {
    I18N[lang] = {};
  }
  return I18N[lang];
}

function t(key) {
  const strings = I18N[_currentLang] || {};
  return strings[key] || key;
}

function applyLanguage(lang) {
  const strings = I18N[lang] || {};
  _currentLang  = lang;
  localStorage.setItem('app_lang', lang);

  // dir + lang on <html>
  document.documentElement.lang = lang;
  document.documentElement.dir  = strings.dir || (lang === 'ar' ? 'rtl' : 'ltr');

  // Map of element selectors to translation keys
  const patches = [
    ['#langToggleBtn',               lang === 'ar' ? 'EN' : 'ع'],
    ['.welcome-title',               'welcome'],
    ['.welcome-sub',                 'welcomeSub'],
    ['#queryInput',                  'inputPlaceholder', 'placeholder'],
    ['.btn-new-chat',                'newChat'],
    ['.topbar-title',                'topbar'],
    ['.logo-title',                  'appName'],
    ['.logo-sub',                    'appSub'],
    ['.history-empty',               'noHistory'],
    ['.settings-title',              'settings'],
  ];

  patches.forEach(([sel, key, attr]) => {
    const el = document.querySelector(sel);
    if (!el) return;
    const val = (typeof key === 'string' && key.length <= 3) ? key : (strings[key] || '');
    if (!val) return;
    if (attr) el.setAttribute(attr, val);
    else el.textContent = val;
  });

  // Nav labels
  const navLabels = document.querySelectorAll('.nav-section-label');
  const labelKeys = ['mode', 'model', 'tools', 'prevChats'];
  navLabels.forEach((el, i) => {
    if (labelKeys[i] && strings[labelKeys[i]]) el.textContent = strings[labelKeys[i]];
  });

  // Login prompt
  const loginLink = document.querySelector('.btn-login-link');
  if (loginLink && strings.login) loginLink.textContent = strings.login;

  // Stat labels
  const statLabels = document.querySelectorAll('.stat-label');
  if (statLabels[0] && strings.laws) statLabels[0].textContent = strings.laws;
  if (statLabels[1] && strings.words) statLabels[1].textContent = strings.words;
}

async function toggleLanguage() {
  const next = _currentLang === 'ar' ? 'en' : 'ar';
  await loadI18n(next);
  applyLanguage(next);
}

async function initI18n() {
  await loadI18n('ar');
  await loadI18n('en');
  applyLanguage(_currentLang);
}

// ═══════════════════════════════════════════════
// الخطوة 37 — User Auth + Settings
// ═══════════════════════════════════════════════

function initUserAuth() {
  const email = localStorage.getItem('user_email');
  const role  = localStorage.getItem('user_role');
  const box   = document.getElementById('userAccountBox');
  const prompt= document.getElementById('userLoginPrompt');
  if (email && box && prompt) {
    document.getElementById('userEmailDisplay').textContent = email;
    document.getElementById('userRoleDisplay').textContent  = role === 'admin' ? 'مدير' : 'مستخدم';
    document.getElementById('userAvatar').textContent       = email[0].toUpperCase();
    box.style.display    = 'flex';
    prompt.style.display = 'none';
  } else if (box && prompt) {
    box.style.display    = 'none';
    prompt.style.display = 'block';
  }
}

function logoutUser() {
  localStorage.removeItem('access_token');
  localStorage.removeItem('refresh_token');
  localStorage.removeItem('user_email');
  localStorage.removeItem('user_id');
  localStorage.removeItem('user_role');
  initUserAuth();
}

function saveSettings() {
  const detail = document.getElementById('detailLevel')?.value  || 'detailed';
  const domain = document.getElementById('legalDomain')?.value  || '';
  localStorage.setItem('setting_detail', detail);
  localStorage.setItem('setting_domain', domain);
}

function loadSettings() {
  const detail = localStorage.getItem('setting_detail') || 'detailed';
  const domain = localStorage.getItem('setting_domain') || '';
  const detailEl = document.getElementById('detailLevel');
  const domainEl = document.getElementById('legalDomain');
  if (detailEl) detailEl.value = detail;
  if (domainEl) domainEl.value = domain;
}

// ═══════════════════════════════════════════════
// الخطوة 43 — Dark Mode
// ═══════════════════════════════════════════════
function toggleDarkMode() {
  const isDark = document.documentElement.getAttribute('data-theme') !== 'light';
  const next   = isDark ? 'light' : 'dark';
  document.documentElement.setAttribute('data-theme', next);
  localStorage.setItem('theme', next);
  const btn = document.getElementById('darkModeBtn');
  if (btn) btn.textContent = next === 'dark' ? '🌙' : '☀️';
}

function initDarkMode() {
  const saved = localStorage.getItem('theme') || 'dark';
  document.documentElement.setAttribute('data-theme', saved);
  const btn = document.getElementById('darkModeBtn');
  if (btn) btn.textContent = saved === 'dark' ? '🌙' : '☀️';
}

// ═══════════════════════════════════════════════
// الخطوة 43 — Global Keyboard Shortcuts
// ═══════════════════════════════════════════════
function initKeyboardShortcuts() {
  document.addEventListener('keydown', (e) => {
    // Ctrl+K → محادثة جديدة
    if (e.ctrlKey && e.key === 'k') {
      e.preventDefault();
      newChat();
      document.getElementById('queryInput')?.focus();
    }
    // Escape → إغلاق أي modal/drawer مفتوح
    if (e.key === 'Escape') {
      const overlay = document.getElementById('compareOverlay');
      if (overlay && overlay.style.display !== 'none') { closeCompareModal(); return; }
      const drawer  = document.getElementById('sourceDrawer');
      if (drawer  && drawer.style.display  !== 'none') { closeDrawer();        return; }
    }
  });
}

// ═══════════════════════════════════════════════
// الخطوة 43 — Copy Buttons on Code Blocks
// ═══════════════════════════════════════════════
function addCodeBlockCopyButtons(bubbleEl) {
  if (!bubbleEl) return;
  bubbleEl.querySelectorAll('pre').forEach(pre => {
    if (pre.querySelector('.code-copy-btn')) return; // already added
    const btn = document.createElement('button');
    btn.className   = 'code-copy-btn';
    btn.title       = 'نسخ الكود';
    btn.textContent = '📋';
    btn.onclick = (e) => {
      e.stopPropagation();
      const code = pre.querySelector('code');
      const text = code ? (code.innerText || code.textContent) : (pre.innerText || pre.textContent);
      navigator.clipboard.writeText(text.trim()).then(() => {
        btn.textContent = '✅';
        setTimeout(() => { btn.textContent = '📋'; }, 2000);
      }).catch(() => {});
    };
    pre.style.position = 'relative';
    pre.appendChild(btn);
  });
}

// ═══════════════════════════════════════════════
// Boot
// ═══════════════════════════════════════════════
document.addEventListener('DOMContentLoaded', () => {
  init();
  initDarkMode();
  initKeyboardShortcuts();
  initMobileMenu();
  initVoiceInput();
  initUserAuth();
  loadSettings();
  initI18n();
  // تحميل إحصائيات التعلم بعد ثانيتين
  setTimeout(loadLearningStats, 2000);
});
