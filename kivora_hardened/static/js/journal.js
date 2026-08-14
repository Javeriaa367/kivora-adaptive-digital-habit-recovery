// ---- Voice Journal (Feature 5) --------------------------------------------
// Transcription happens entirely client-side via the browser's
// SpeechRecognition API. No audio is recorded, uploaded, or stored -- we
// only ever send the resulting text to /api/journal, so this reuses the
// existing analyze -> save -> memory pipeline untouched. `window.voiceInputState`
// tracks whether the current textarea content originated from voice, and
// whether the user hand-edited it afterward, purely for the input_method tag.
const voiceInputState = { active: false, usedVoice: false, editedAfterVoice: false };

function initVoiceJournal() {
  const micBtn = document.getElementById('voice-mic-btn');
  const textarea = document.getElementById('entry-text');
  const statusEl = document.getElementById('voice-status');
  const unsupportedEl = document.getElementById('voice-unsupported');
  const errorEl = document.getElementById('voice-error');
  if (!micBtn || !textarea) return;

  const SpeechRecognitionAPI = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRecognitionAPI) {
    micBtn.disabled = true;
    micBtn.classList.add('opacity-40', 'cursor-not-allowed');
    unsupportedEl.classList.remove('hidden');
    return;
  }

  const recognition = new SpeechRecognitionAPI();
  recognition.lang = 'en-US';
  recognition.continuous = true;
  recognition.interimResults = true;

  // Anchor text present in the box *before* this recording session started,
  // so interim results replace only what this session has produced so far
  // rather than duplicating/clobbering earlier typed or dictated content.
  let baseText = '';
  let finalizedThisSession = '';

  function setListening(isListening) {
    voiceInputState.active = isListening;
    micBtn.classList.toggle('bg-teal-600', isListening);
    micBtn.classList.toggle('text-white', isListening);
    micBtn.classList.toggle('bg-teal-50', !isListening);
    micBtn.classList.toggle('text-teal-600', !isListening);
    micBtn.querySelector('i').className = isListening ? 'fa-solid fa-stop' : 'fa-solid fa-microphone';
    statusEl.classList.toggle('hidden', !isListening);
    statusEl.classList.toggle('flex', isListening);
    if (isListening) errorEl.classList.add('hidden');
  }

  micBtn.addEventListener('click', () => {
    if (voiceInputState.active) {
      recognition.stop();
      return;
    }
    baseText = textarea.value ? textarea.value.trim() + ' ' : '';
    finalizedThisSession = '';
    try {
      recognition.start();
      setListening(true);
    } catch (err) {
      errorEl.textContent = 'Could not start the microphone. Check your browser permissions.';
      errorEl.classList.remove('hidden');
    }
  });

  recognition.addEventListener('result', (event) => {
    let interim = '';
    for (let i = event.resultIndex; i < event.results.length; i++) {
      const transcript = event.results[i][0].transcript;
      if (event.results[i].isFinal) {
        finalizedThisSession += transcript + ' ';
      } else {
        interim += transcript;
      }
    }
    textarea.value = (baseText + finalizedThisSession + interim).trim();
    document.getElementById('char-count').textContent = textarea.value.length;
    voiceInputState.usedVoice = true;
    voiceInputState.editedAfterVoice = false;
  });

  recognition.addEventListener('error', (event) => {
    setListening(false);
    if (event.error === 'not-allowed' || event.error === 'permission-denied') {
      errorEl.textContent = "Mic access was blocked. Allow microphone permission in your browser's site settings to use voice journaling.";
    } else if (event.error === 'no-speech') {
      errorEl.textContent = "Didn't catch any speech — tap the mic and try again.";
    } else {
      errorEl.textContent = 'Voice input hit a snag. You can keep typing instead.';
    }
    errorEl.classList.remove('hidden');
  });

  recognition.addEventListener('end', () => setListening(false));

  // Any manual keystroke after a voice pass means the user reviewed/edited
  // the transcript -- worth distinguishing from a raw, unedited dictation.
  textarea.addEventListener('input', () => {
    if (voiceInputState.usedVoice && !voiceInputState.active) {
      voiceInputState.editedAfterVoice = true;
    }
  });
}

document.addEventListener('DOMContentLoaded', () => {
  const form = document.getElementById('journal-form');
  const textarea = document.getElementById('entry-text');
  const charCount = document.getElementById('char-count');
  const resultEl = document.getElementById('journal-result');
  const crisisEl = document.getElementById('crisis-banner');
  const historyEl = document.getElementById('journal-history');
  const submitBtn = document.getElementById('journal-submit');

  initVoiceJournal();

  textarea.addEventListener('input', () => { charCount.textContent = textarea.value.length; });

  const EMOJI = { Happy: '😊', Calm: '🙂', Neutral: '😐', Stressed: '😫', Anxious: '😰', Sad: '😢', Angry: '😠' };
  const COLOR = {
    Happy: 'teal', Calm: 'teal', Neutral: 'slate', Stressed: 'amber',
    Anxious: 'amber', Sad: 'coral', Angry: 'coral',
  };

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const text = textarea.value.trim();
    if (!text) return;
    submitBtn.disabled = true;
    crisisEl.classList.add('hidden');

    const inputMethod = !voiceInputState.usedVoice
      ? 'text'
      : (voiceInputState.editedAfterVoice ? 'voice_edited' : 'voice');

    try {
      const res = await fetch('/api/journal', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ entry_text: text, input_method: inputMethod }),
      });
      const data = await res.json();
      if (!data.ok) throw new Error(data.error || 'Could not save entry');

      const color = COLOR[data.entry.emotion_label] || 'slate';
      const secondary = data.entry.secondary_emotion;
      const breakdown = data.entry.sentiment_breakdown;
      const breakdownSource = data.entry.sentiment_breakdown_source;
      const confidencePct = Math.round(data.entry.confidence * 100);
      // Student-facing wording, not a raw model probability -- see
      // ml/emotion_analyzer_hybrid.py:confidence_label() for why. The
      // exact number is still there for anyone curious (title tooltip).
      const confidenceText = data.entry.confidence_label || 'Signal detected';

      const secondaryHtml = secondary
        ? `<span class="ml-2 inline-flex items-center text-xs font-medium text-slate-500 bg-slate-100 rounded-full px-2.5 py-1">
             also detected: ${secondary}${EMOJI[secondary] ? ' ' + EMOJI[secondary] : ''}
           </span>`
        : '';

      const confidenceNote = data.entry.low_confidence
        ? `<p class="text-xs text-slate-400 mt-1">Short entry — this is a loose read, not a precise one.</p>`
        : '';

      const breakdownHtml = breakdown ? `
        <div class="mt-4">
          <p class="text-xs font-semibold text-slate-500 mb-1.5">${breakdownSource === 'vader_auxiliary' ? 'VADER polarity distribution (auxiliary)' : 'Sentiment breakdown'}</p>
          <div class="flex h-2.5 rounded-full overflow-hidden bg-slate-100">
            <div class="bg-teal-500" style="width:${(breakdown.positive*100).toFixed(0)}%" title="Positive ${(breakdown.positive*100).toFixed(0)}%"></div>
            <div class="bg-slate-300" style="width:${(breakdown.neutral*100).toFixed(0)}%" title="Neutral ${(breakdown.neutral*100).toFixed(0)}%"></div>
            <div class="bg-coral-400" style="width:${(breakdown.negative*100).toFixed(0)}%" title="Negative ${(breakdown.negative*100).toFixed(0)}%"></div>
          </div>
          <div class="flex justify-between text-[11px] text-slate-400 mt-1">
            <span>Positive ${(breakdown.positive*100).toFixed(0)}%</span>
            <span>Neutral ${(breakdown.neutral*100).toFixed(0)}%</span>
            <span>Negative ${(breakdown.negative*100).toFixed(0)}%</span>
          </div>
        </div>` : '';

      resultEl.innerHTML = `
        <div class="bg-${color}-100 border border-${color}-500/30 rounded-2xl p-5">
          <div class="flex items-center gap-4">
            <span class="text-4xl">${EMOJI[data.entry.emotion_label] || '🙂'}</span>
            <div>
              <p class="font-display font-bold text-ink">${data.entry.emotion_label}${secondaryHtml}</p>
              <p class="text-sm text-slate-600">Overall sentiment: ${data.entry.overall_sentiment} · <span title="Raw score: ${confidencePct}%">${confidenceText}</span></p>
              ${confidenceNote}
            </div>
          </div>
          ${breakdownHtml}
          ${data.explanation ? `<p class="text-sm text-slate-600 mt-4 italic">"${data.explanation}"</p>` : ''}
        </div>`;
      resultEl.classList.remove('hidden');

      const onboardParams = new URLSearchParams(location.search);
      if (onboardParams.get('onboard') === '1') {
        const done = document.createElement('div');
        done.className = 'mt-6 bg-teal-50 border border-teal-200 rounded-2xl p-5 text-center';
        done.innerHTML = `
          <p class="font-display font-semibold text-teal-700 mb-1"><i class="fa-solid fa-circle-check mr-1"></i>That's it — you're all set!</p>
          <p class="text-sm text-slate-600 mb-3">Your first entry is saved. Your dashboard now has your snapshot, trends and recovery plan.</p>
          <a href="/dashboard" class="inline-flex items-center gap-2 bg-teal-500 hover:bg-teal-400 text-ink font-semibold text-sm px-6 py-2.5 rounded-xl transition-colors">Go to my dashboard <i class="fa-solid fa-arrow-right"></i></a>`;
        resultEl.appendChild(done);
      }

      if (data.crisis) {
        crisisEl.innerHTML = `
          <div class="bg-coral-100 border-2 border-coral-500/40 rounded-2xl p-6">
            <p class="font-display font-bold text-coral-600 mb-2"><i class="fa-solid fa-heart-crack mr-2"></i>You're not alone</p>
            <p class="text-sm text-slate-700 mb-4">${data.crisis.message}</p>
            <div class="space-y-2">
              ${data.crisis.resources.map(r => `
                <div class="bg-white rounded-lg px-4 py-2.5 text-sm flex items-center justify-between">
                  <span class="font-medium text-slate-700">${r.name}</span>
                  <span class="font-mono-data text-coral-600">${r.contact}</span>
                </div>`).join('')}
            </div>
            <p class="text-xs text-slate-500 mt-4">This app is not a substitute for professional mental health care.</p>
          </div>`;
        crisisEl.classList.remove('hidden');
      }

      const item = document.createElement('div');
      item.className = 'bg-white rounded-xl border border-slate-200 p-4 flex items-start gap-3';
      const micBadge = inputMethod !== 'text'
        ? '<i class="fa-solid fa-microphone text-teal-400 text-xs" title="Captured by voice"></i>' : '';
      item.innerHTML = `
        <span class="text-2xl leading-none">${EMOJI[data.entry.emotion_label] || '🙂'}</span>
        <div class="flex-1 min-w-0">
          <div class="flex items-center gap-2 mb-1">
            <span class="text-sm font-semibold text-ink">${data.entry.emotion_label}</span>
            ${micBadge}
            <span class="text-xs text-slate-400">just now</span>
          </div>
          <p class="text-sm text-slate-500">${text}</p>
        </div>`;
      if (historyEl.firstElementChild && historyEl.firstElementChild.tagName === 'P') {
        historyEl.innerHTML = '';
      }
      historyEl.prepend(item);

      textarea.value = '';
      charCount.textContent = '0';
      voiceInputState.usedVoice = false;
      voiceInputState.editedAfterVoice = false;
    } catch (err) {
      resultEl.innerHTML = `<div class="bg-coral-100 border border-coral-500/30 text-coral-600 rounded-xl px-4 py-3 text-sm">${err.message}</div>`;
      resultEl.classList.remove('hidden');
    } finally {
      submitBtn.disabled = false;
    }
  });
});

document.addEventListener('DOMContentLoaded', async () => {
  const cloudEl = document.getElementById('word-cloud');
  if (!cloudEl) return;
  const res = await fetch('/api/journal/word-frequencies');
  const data = await res.json();
  if (!data.ok || !data.words.length) {
    cloudEl.innerHTML = '<p class="text-sm text-slate-400">Write a few more entries to see your common words.</p>';
    return;
  }
  const max = Math.max(...data.words.map(w => w.count));
  const colors = ['text-teal-600','text-teal-500','text-slate-500','text-amber-500','text-coral-500'];
  cloudEl.innerHTML = data.words.map((w, i) => {
    const size = 12 + Math.round((w.count / max) * 26);
    const color = colors[i % colors.length];
    return `<span class="${color} font-display font-semibold" style="font-size:${size}px">${w.word}</span>`;
  }).join(' ');
});

// ---- Memory panel ------------------------------------------------------
document.addEventListener('DOMContentLoaded', async () => {
  const insightEl = document.getElementById('memory-insight-text');
  const toggleBtn = document.getElementById('memory-facts-toggle');
  const factsEl = document.getElementById('memory-facts-list');
  if (!insightEl) return;

  try {
    const res = await fetch('/api/memory/insights');
    const data = await res.json();
    insightEl.textContent = data.ok
      ? data.insight
      : "Couldn't load your memory insight right now.";
  } catch {
    insightEl.textContent = "Couldn't load your memory insight right now.";
  }

  toggleBtn.addEventListener('click', async () => {
    if (!factsEl.classList.contains('hidden')) {
      factsEl.classList.add('hidden');
      toggleBtn.textContent = 'Show what I remember';
      return;
    }
    toggleBtn.textContent = 'Loading...';
    try {
      const res = await fetch('/api/memory/facts');
      const data = await res.json();
      if (!data.ok || data.total_active_facts === 0) {
        factsEl.innerHTML = '<p class="text-xs text-slate-400">Nothing stored yet — keep journaling.</p>';
      } else {
        factsEl.innerHTML = Object.entries(data.facts_by_type).map(([type, items]) => `
          <div class="text-xs">
            <span class="uppercase tracking-wide text-teal-600 font-semibold">${type.replace('_', ' ')}</span>
            ${items.map(i => `<div class="text-slate-600 pl-2">• ${i.text} <span class="text-slate-400">(${i.occurrences}x)</span></div>`).join('')}
          </div>`).join('');
      }
    } catch {
      factsEl.innerHTML = '<p class="text-xs text-coral-500">Could not load.</p>';
    }
    factsEl.classList.remove('hidden');
    toggleBtn.textContent = 'Hide';
  });
});
