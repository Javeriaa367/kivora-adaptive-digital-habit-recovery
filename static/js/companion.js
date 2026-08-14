document.addEventListener('DOMContentLoaded', () => {
  const scrollEl = document.getElementById('chat-scroll');
  const form = document.getElementById('companion-form');
  const input = document.getElementById('companion-input');
  const sendBtn = document.getElementById('companion-send');
  const clearBtn = document.getElementById('clear-chat');

  function scrollToBottom() { scrollEl.scrollTop = scrollEl.scrollHeight; }

  function addUserMessage(text) {
    const div = document.createElement('div');
    div.className = 'flex gap-3 justify-end';
    div.innerHTML = `<div class="bg-teal-500 text-ink rounded-2xl rounded-tr-sm px-4 py-3 text-sm max-w-[80%] whitespace-pre-wrap">${text.replace(/</g,'&lt;')}</div>`;
    scrollEl.appendChild(div);
    scrollToBottom();
  }

  function addBotMessage(text, isCrisis, status = '') {
    const html = window.marked ? marked.parse(text) : text;
    const div = document.createElement('div');
    div.className = 'flex gap-3';
    div.innerHTML = `
      <span class="w-8 h-8 rounded-full ${isCrisis ? 'bg-coral-500' : 'bg-teal-500'} flex items-center justify-center text-ink text-xs flex-shrink-0"><i class="fa-solid ${isCrisis ? 'fa-heart-crack' : 'fa-wave-square'}"></i></span>
      <div class="flex flex-col gap-1 max-w-[80%]">
        <div class="msg-bubble ${isCrisis ? 'bg-coral-500/15 border-coral-500/30' : 'bg-white/5 border-white/10'} border rounded-2xl rounded-tl-sm px-4 py-3 text-sm text-slate-200">${html}</div>
        ${status ? `<p class="text-[10px] text-slate-500 px-1">${status}</p>` : ''}
        <button class="copy-btn self-start text-[10px] text-slate-500 hover:text-slate-300"><i class="fa-regular fa-copy mr-1"></i>Copy</button>
      </div>`;
    scrollEl.appendChild(div);
    div.querySelector('.copy-btn').addEventListener('click', () => {
      navigator.clipboard.writeText(text);
    });
    scrollToBottom();
  }

  function addTypingIndicator() {
    const div = document.createElement('div');
    div.id = 'typing-indicator';
    div.className = 'flex gap-3';
    div.innerHTML = `
      <span class="w-8 h-8 rounded-full bg-teal-500 flex items-center justify-center text-ink text-xs flex-shrink-0"><i class="fa-solid fa-wave-square"></i></span>
      <div class="bg-white/5 border border-white/10 rounded-2xl rounded-tl-sm px-4 py-3 flex gap-1">
        <span class="typing-dot w-1.5 h-1.5 rounded-full bg-slate-400"></span>
        <span class="typing-dot w-1.5 h-1.5 rounded-full bg-slate-400"></span>
        <span class="typing-dot w-1.5 h-1.5 rounded-full bg-slate-400"></span>
      </div>`;
    scrollEl.appendChild(div);
    scrollToBottom();
  }

  function removeTypingIndicator() {
    document.getElementById('typing-indicator')?.remove();
  }

  async function sendMessage(text) {
    addUserMessage(text);
    sendBtn.disabled = true;
    addTypingIndicator();
    try {
      const res = await fetch('/api/companion/send', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text }),
      });
      const data = await res.json();
      removeTypingIndicator();
      if (data.ok) {
        let status = '';
        if (data.daily_cap_reached) {
          status = 'Daily live-AI limit reached — this is a local companion response.';
        } else if (data.stubbed && data.error) {
          status = 'Gemini is unavailable — this is a local companion response.';
        } else if (data.stubbed) {
          status = 'Local companion response.';
        } else if (!data.crisis) {
          status = 'Gemini response.';
        }
        addBotMessage(data.reply, data.crisis, status);
      }
      else addBotMessage(data.error || 'Something went wrong.', false);
    } catch {
      removeTypingIndicator();
      addBotMessage('Could not reach the companion. Try again.', false);
    } finally {
      sendBtn.disabled = false;
    }
  }

  form.addEventListener('submit', (e) => {
    e.preventDefault();
    const text = input.value.trim();
    if (!text) return;
    input.value = '';
    input.style.height = 'auto';
    sendMessage(text);
  });

  input.addEventListener('input', () => {
    input.style.height = 'auto';
    input.style.height = Math.min(input.scrollHeight, 120) + 'px';
  });
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); form.requestSubmit(); }
  });

  document.querySelectorAll('.suggested-prompt').forEach(btn => {
    btn.addEventListener('click', () => sendMessage(btn.textContent.trim()));
  });

  clearBtn.addEventListener('click', async () => {
    await fetch('/api/companion/clear', { method: 'POST' });
    scrollEl.innerHTML = scrollEl.firstElementChild.outerHTML; // keep the intro message
  });
});
