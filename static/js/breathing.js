document.addEventListener('DOMContentLoaded', () => {
  const circle = document.getElementById('breath-circle');
  const label = document.getElementById('breath-label');
  const startBtn = document.getElementById('breath-start');
  const soundBtn = document.getElementById('breath-sound');
  const cyclesEl = document.getElementById('breath-cycles');
  if (!circle) return;

  let running = false, cycles = 0, soundOn = true, timeoutId = null;
  let audioCtx = null;

  soundBtn.addEventListener('click', () => {
    soundOn = !soundOn;
    soundBtn.innerHTML = soundOn ? '<i class="fa-solid fa-volume-high"></i>' : '<i class="fa-solid fa-volume-xmark"></i>';
  });

  function beep(freq, duration) {
    if (!soundOn) return;
    try {
      audioCtx = audioCtx || new (window.AudioContext || window.webkitAudioContext)();
      const osc = audioCtx.createOscillator();
      const gain = audioCtx.createGain();
      osc.frequency.value = freq;
      gain.gain.setValueAtTime(0.05, audioCtx.currentTime);
      osc.connect(gain); gain.connect(audioCtx.destination);
      osc.start(); osc.stop(audioCtx.currentTime + duration);
    } catch {}
  }

  function phase(name, seconds, scale, next) {
    label.textContent = name;
    circle.style.transitionDuration = `${seconds * 1000}ms`;
    circle.style.transform = `scale(${scale})`;
    beep(name === 'Inhale' ? 440 : name === 'Exhale' ? 330 : 380, 0.15);
    timeoutId = setTimeout(() => { if (running) next(); }, seconds * 1000);
  }

  function cycle() {
    phase('Inhale', 4, 1.3, () => {
      phase('Hold', 4, 1.3, () => {
        phase('Exhale', 6, 0.85, () => {
          cycles += 1;
          cyclesEl.textContent = cycles;
          if (running) cycle();
        });
      });
    });
  }

  startBtn.addEventListener('click', () => {
    running = !running;
    startBtn.textContent = running ? 'Stop' : 'Start';
    if (running) { cycle(); } else { clearTimeout(timeoutId); circle.style.transform = 'scale(1)'; label.textContent = 'Ready'; }
  });
});
