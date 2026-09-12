const $ = (s) => document.querySelector(s);
const $$ = (s) => document.querySelectorAll(s);

let recognition = null;
let listening = false;

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[c]));
}

function openModal(id) {
  const modal = document.getElementById(id);
  if (!modal) return;
  modal.classList.add('open');
  modal.setAttribute('aria-hidden', 'false');
}

function closeModal(id) {
  const modal = document.getElementById(id);
  if (!modal) return;
  modal.classList.remove('open');
  modal.setAttribute('aria-hidden', 'true');
}

$$('[data-close]').forEach((button) => {
  button.addEventListener('click', () => closeModal(button.dataset.close));
});

$$('.modal-backdrop').forEach((modal) => {
  modal.addEventListener('click', (event) => {
    if (event.target === modal) closeModal(modal.id);
  });
});

document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape') {
    $$('.modal-backdrop.open').forEach((modal) => closeModal(modal.id));
  }
});

function scrollMessages() {
  const box = $('#messages');
  if (box) box.scrollTop = box.scrollHeight;
}

// Switches the chat stage from the centered "empty" welcome layout
// into the normal docked-composer chat layout — happens the moment
// the first message is sent or a past conversation is opened.
function leaveEmptyState() {
  const stage = $('#chatStage');
  if (stage && stage.classList.contains('is-empty')) {
    stage.classList.remove('is-empty');
  }
  $('#welcomeBlock')?.remove();
  $('#chipsBlock')?.remove();
}

function protectMathSegments(text) {
  // Markdown parsing (marked.js) treats backslash as an escape
  // character, so it silently strips the backslash out of LaTeX
  // delimiters like \( \) and \[ \] before KaTeX ever sees them —
  // \( becomes ( with the backslash gone, breaking math rendering.
  // To avoid this, pull every math segment out into a plain-text
  // placeholder token BEFORE markdown parsing runs, then put the
  // original LaTeX back afterward, untouched, once markdown is done.
  const placeholders = [];
  const patterns = [
    /\$\$[\s\S]+?\$\$/g,
    /\\\[[\s\S]+?\\\]/g,
    /\\\([\s\S]+?\\\)/g,
    /\$[^\n$]+?\$/g,
  ];

  let protectedText = text;
  patterns.forEach((pattern) => {
    protectedText = protectedText.replace(pattern, (match) => {
      const token = `@@MATH${placeholders.length}@@`;
      placeholders.push(match);
      return token;
    });
  });

  return { protectedText, placeholders };
}

function restoreMathSegments(html, placeholders) {
  let result = html;
  placeholders.forEach((original, index) => {
    const token = `@@MATH${index}@@`;
    result = result.split(token).join(original);
  });
  return result;
}

function fixLatexSpacing(text) {
  let fixed = text;

  // KaTeX does not support the \cdotp command at all (it's a rarer
  // AMS command) — always convert it to \cdot, which KaTeX fully
  // supports, with a trailing space so it can't merge into the next
  // word either.
  fixed = fixed.replace(/\\cdotp/g, '\\cdot ');

  // LaTeX reads a command name until the first non-letter character.
  // If the model writes "\timesatm" (no space), "atm" gets swallowed
  // into the command name, producing an invalid command and a red
  // KaTeX error instead of rendering. Insert a space after these
  // common commands whenever they're immediately followed by a
  // letter, so this can't happen no matter what the model outputs.
  const commands = ['cdot', 'times', 'div', 'pm', 'mp', 'circ', 'ldots', 'cdots'];
  commands.forEach((cmd) => {
    const re = new RegExp(`\\\\${cmd}(?=[a-zA-Z])`, 'g');
    fixed = fixed.replace(re, `\\${cmd} `);
  });

  return fixed;
}

function renderMarkdown(text) {
  // Assistant answers come back in Markdown (from the LLM), so render
  // them properly (bold, headings, tables, lists) instead of showing
  // the raw # ** | symbols as plain text. Falls back to plain escaped
  // text if the marked/DOMPurify libraries fail to load for any reason.
  if (typeof marked === 'undefined' || typeof DOMPurify === 'undefined') {
    return escapeHtml(text).replace(/\n/g, '<br>');
  }
  const safeText = fixLatexSpacing(text);
  const { protectedText, placeholders } = protectMathSegments(safeText);
  const rawHtml = marked.parse(protectedText, { breaks: true });
  const restoredHtml = restoreMathSegments(rawHtml, placeholders);
  return DOMPurify.sanitize(restoredHtml);
}

function renderMath(element) {
  // Turns LaTeX math delimiters (\( \), \[ \], $ $, $$ $$) that the
  // LLM outputs into properly rendered equations, instead of showing
  // the raw backslashes/brackets as plain text.
  if (typeof renderMathInElement === 'undefined') return;
  renderMathInElement(element, {
    delimiters: [
      { left: '$$', right: '$$', display: true },
      { left: '\\[', right: '\\]', display: true },
      { left: '\\(', right: '\\)', display: false },
      { left: '$', right: '$', display: false },
    ],
    throwOnError: false,
  });
}

function addMessage(role, text) {
  const box = $('#messages');
  if (!box) return;

  const wrapper = document.createElement('div');
  wrapper.className = `message ${role}`;
  const bubble = document.createElement('div');
  bubble.className = 'bubble';

  if (role === 'assistant') {
    bubble.innerHTML = renderMarkdown(text);
    renderMath(bubble);
  } else {
    bubble.innerHTML = escapeHtml(text).replace(/\n/g, '<br>');
  }

  wrapper.appendChild(bubble);
  box.appendChild(wrapper);
  scrollMessages();
}

function addFileMessage(filename) {
  const box = $('#messages');
  if (!box) return;

  const wrapper = document.createElement('div');
  wrapper.className = 'message user file-message';
  const bubble = document.createElement('div');
  bubble.className = 'bubble';
  bubble.innerHTML = `<div class="file-badge">📄 File uploaded</div><div>${escapeHtml(filename)}</div>`;
  wrapper.appendChild(bubble);
  box.appendChild(wrapper);
  scrollMessages();
}

function addSummaryMessage(filename, summary) {
  const box = $('#messages');
  if (!box) return;
  const wrapper = document.createElement('div');
  wrapper.className = 'message assistant';
  const bubble = document.createElement('div');
  bubble.className = 'bubble';
  bubble.innerHTML = `<div class="summary-heading">Summary</div>${renderMarkdown(summary)}`;
  renderMath(bubble);
  wrapper.appendChild(bubble);
  box.appendChild(wrapper);
  scrollMessages();
}

function addTypingIndicator() {
  const box = $('#messages');
  if (!box) return;
  const wrapper = document.createElement('div');
  wrapper.className = 'message assistant';
  wrapper.id = 'typingIndicator';
  const bubble = document.createElement('div');
  bubble.className = 'bubble typing-bubble';
  bubble.innerHTML = '<span class="dot"></span><span class="dot"></span><span class="dot"></span>';
  wrapper.appendChild(bubble);
  box.appendChild(wrapper);
  scrollMessages();
}

function removeTypingIndicator() {
  $('#typingIndicator')?.remove();
}

async function sendMessage(inputType = 'text') {
  const input = $('#messageInput');
  const question = input.value.trim();
  if (!question) return;

  leaveEmptyState();

  input.value = '';
  input.style.height = 'auto';
  addMessage('user', question);
  $('#sendBtn').disabled = true;
  addTypingIndicator();

  try {
    const response = await fetch('/api/chat', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({message: question, input_type: inputType})
    });
    const data = await response.json();
    if (!data.ok) throw new Error(data.error || 'Something went wrong.');
    removeTypingIndicator();
    addMessage('assistant', data.answer);
    loadChatHistory();
  } catch (error) {
    removeTypingIndicator();
    addMessage('assistant', `Error: ${error.message}`);
  } finally {
    $('#sendBtn').disabled = false;
    input.focus();
  }
}

$('#sendBtn').addEventListener('click', () => sendMessage());

$('#messageInput').addEventListener('keydown', (event) => {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault();
    sendMessage();
  }
});

$('#messageInput').addEventListener('input', (event) => {
  event.target.style.height = 'auto';
  event.target.style.height = Math.min(event.target.scrollHeight, 160) + 'px';
});

document.addEventListener('click', (event) => {
  const chip = event.target.closest('#chipsBlock button');
  if (!chip) return;
  $('#messageInput').value = chip.textContent.trim();
  sendMessage();
});

async function createNewChat() {
  await fetch('/api/new-chat', {method: 'POST'});
  window.location.reload();
}

$('#newChat').addEventListener('click', createNewChat);

$('#exportCurrent').addEventListener('click', () => {
  window.location.href = '/api/export/current';
});

let activeChatId = window.CURRENT_SESSION_ID || null;

async function loadChatHistory() {
  const box = $('#chatHistory');
  if (!box) return;

  try {
    const response = await fetch('/api/history');
    const data = await response.json();

    if (!data.length) {
      box.innerHTML = '<div class="empty-history">Your conversations will appear here.</div>';
      return;
    }

    box.innerHTML = data.map((chat) => `
      <div class="chat-history-item${chat.id === activeChatId ? ' active' : ''}" data-id="${chat.id}" role="button" tabindex="0">
        <span class="chat-dot"></span>
        <span class="chat-title">${escapeHtml(chat.title)}</span>
        <button class="delete-chat" title="Delete chat" data-delete="${chat.id}">×</button>
      </div>
    `).join('');

    box.querySelectorAll('.chat-history-item').forEach((item) => {
      item.addEventListener('click', (event) => {
        if (event.target.closest('.delete-chat')) return;
        openHistory(Number(item.dataset.id));
      });
      item.addEventListener('keydown', (event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          openHistory(Number(item.dataset.id));
        }
      });
    });

    box.querySelectorAll('[data-delete]').forEach((button) => {
      button.addEventListener('click', async (event) => {
        event.stopPropagation();
        if (!confirm('Delete this conversation?')) return;
        const deletedId = Number(button.dataset.delete);
        await fetch('/api/history/' + deletedId, {method: 'DELETE'});

        if (deletedId === activeChatId) {
          // The chat we just deleted is the one currently open — the
          // backend already switched the session to a fresh empty
          // one, so reload to show that empty/welcome state, just
          // like ChatGPT does after deleting your current chat.
          window.location.reload();
        } else {
          loadChatHistory();
        }
      });
    });
  } catch (error) {
    box.innerHTML = '<div class="empty-history">Could not load chats.</div>';
  }
}

async function openHistory(id) {
  try {
    const response = await fetch('/api/history/' + id);
    const data = await response.json();
    activeChatId = id;
    leaveEmptyState();
    const box = $('#messages');
    box.innerHTML = '';
    data.messages.forEach((message) => addMessage(message.role, message.content));
    loadChatHistory();
    scrollMessages();
  } catch (error) {
    addMessage('assistant', `Error: ${error.message}`);
  }
}

$('#refreshChats').addEventListener('click', loadChatHistory);

async function loadAnalytics() {
  const data = await fetch('/api/analytics').then((response) => response.json());
  $('#aChats').textContent = data.total_chats ?? 0;
  $('#aQuestions').textContent = data.total_questions ?? 0;
  $('#aVoice').textContent = data.voice_questions ?? 0;
  $('#aFiles').textContent = data.files_uploaded ?? 0;
  renderBars($('#analyticsDomains'), data.domains || []);
}

function renderBars(box, items) {
  if (!items.length) {
    box.innerHTML = '<p style="color:var(--muted)">No activity yet.</p>';
    return;
  }
  const max = Math.max(...items.map((item) => item.count), 1);
  box.innerHTML = items.map((item) => `
    <div class="bar-row">
      <div class="bar-label"><span>${escapeHtml(item.domain)}</span><strong>${item.count}</strong></div>
      <div class="bar-track"><div class="bar-fill" style="width:${(item.count / max) * 100}%"></div></div>
    </div>
  `).join('');
}

$('#analyticsBtn').addEventListener('click', async () => {
  openModal('analyticsModal');
  try {
    await loadAnalytics();
  } catch (error) {
    $('#analyticsDomains').innerHTML = '<p style="color:var(--muted)">Analytics are temporarily unavailable.</p>';
  }
});

function startVoice() {
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRecognition) {
    leaveEmptyState();
    addMessage('assistant', 'Voice input is not supported by this browser. Please use Chrome or Edge.');
    return;
  }

  if (listening) {
    recognition.stop();
    return;
  }

  recognition = new SpeechRecognition();
  recognition.lang = 'en-US';
  recognition.interimResults = false;
  recognition.continuous = false;

  recognition.onstart = () => {
    listening = true;
    $('#micBtn').classList.add('listening');
    $('#fileStatus').textContent = 'Listening...';
  };

  recognition.onresult = (event) => {
    const text = event.results[0][0].transcript;
    $('#messageInput').value = text;
    $('#messageInput').style.height = 'auto';
    $('#fileStatus').textContent = '';
    sendMessage('voice');
  };

  recognition.onerror = () => {
    $('#fileStatus').textContent = 'Voice input failed. Please try again.';
  };

  recognition.onend = () => {
    listening = false;
    $('#micBtn').classList.remove('listening');
    setTimeout(() => { if (!listening) $('#fileStatus').textContent = ''; }, 800);
  };

  recognition.start();
}

$('#micBtn').addEventListener('click', startVoice);

$('#attachBtn').addEventListener('click', () => $('#fileInput').click());

$('#fileInput').addEventListener('change', async (event) => {
  const file = event.target.files[0];
  if (!file) return;

  leaveEmptyState();

  const formData = new FormData();
  formData.append('file', file);
  $('#fileStatus').textContent = 'Uploading and reading...';
  $('#attachBtn').disabled = true;

  try {
    const response = await fetch('/api/upload', {method: 'POST', body: formData});
    const data = await response.json();
    if (!data.ok) throw new Error(data.error || 'File upload failed.');

    addFileMessage(data.filename);
    addSummaryMessage(data.filename, data.summary);
    $('#fileStatus').textContent = '✓ File ready — ask me anything about it';
    loadChatHistory();
    setTimeout(() => { $('#fileStatus').textContent = ''; }, 3000);
  } catch (error) {
    addMessage('assistant', `File error: ${error.message}`);
    $('#fileStatus').textContent = '';
  } finally {
    $('#attachBtn').disabled = false;
    event.target.value = '';
  }
});

async function loadProfile() {
  const profile = await fetch('/api/profile').then((response) => response.json());
  $('#pName').value = profile.name || '';
  $('#pAge').value = profile.age || '';
  $('#pStudies').value = profile.studies || '';
  $('#pUniversity').value = profile.university || '';
  $('#pInterests').value = Array.isArray(profile.interests) ? profile.interests.join(', ') : '';
}

$('#profileBtn').addEventListener('click', async () => {
  openModal('profileModal');
  try { await loadProfile(); } catch (_) {}
});

$('#saveProfile').addEventListener('click', async () => {
  const interests = $('#pInterests').value.split(',').map((value) => value.trim()).filter(Boolean);
  const payload = {
    name: $('#pName').value.trim(),
    age: $('#pAge').value ? Number($('#pAge').value) : '',
    studies: $('#pStudies').value.trim(),
    university: $('#pUniversity').value.trim(),
    interests
  };

  const response = await fetch('/api/profile', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(payload)
  });
  const data = await response.json();

  if (data.ok) {
    $('#profileStatus').textContent = 'Profile saved successfully.';
    setTimeout(() => closeModal('profileModal'), 700);
  } else {
    $('#profileStatus').textContent = 'Could not save the profile.';
  }
});

$('#themeBtn').addEventListener('click', () => document.body.classList.toggle('dark'));

// Sidebar open/close, like ChatGPT's collapsible sidebar. Remembers
// the user's choice across visits via localStorage.
function applySidebarState(closed) {
  $('#appShell')?.classList.toggle('sidebar-closed', closed);
}

const savedSidebarState = localStorage.getItem('sidebarClosed') === 'true';
applySidebarState(savedSidebarState);

$('#sidebarToggle').addEventListener('click', () => {
  const isClosed = !$('#appShell').classList.contains('sidebar-closed');
  applySidebarState(isClosed);
  localStorage.setItem('sidebarClosed', String(isClosed));
});

loadChatHistory();
scrollMessages();
