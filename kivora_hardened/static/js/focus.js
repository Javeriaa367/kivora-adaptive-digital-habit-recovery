document.addEventListener('DOMContentLoaded', () => {
  const FOCUS_SECONDS = 25 * 60, BREAK_SECONDS = 5 * 60;
  let secondsLeft = FOCUS_SECONDS, isFocus = true, running = false, intervalId = null, pomoCount = 0;

  const display = document.getElementById('timer-display');
  const modeEl = document.getElementById('timer-mode');
  const startBtn = document.getElementById('timer-start');
  const resetBtn = document.getElementById('timer-reset');
  const countEl = document.getElementById('pomo-count');

  function render() {
    const m = Math.floor(secondsLeft / 60), s = secondsLeft % 60;
    display.textContent = `${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;
    modeEl.textContent = isFocus ? 'Focus' : 'Break';
  }

  function tick() {
    secondsLeft -= 1;
    if (secondsLeft < 0) {
      if (isFocus) { pomoCount += 1; countEl.textContent = pomoCount; }
      isFocus = !isFocus;
      secondsLeft = isFocus ? FOCUS_SECONDS : BREAK_SECONDS;
    }
    render();
  }

  startBtn.addEventListener('click', () => {
    running = !running;
    startBtn.textContent = running ? 'Pause' : 'Start';
    if (running) intervalId = setInterval(tick, 1000);
    else clearInterval(intervalId);
  });

  resetBtn.addEventListener('click', () => {
    clearInterval(intervalId);
    running = false; isFocus = true; secondsLeft = FOCUS_SECONDS;
    startBtn.textContent = 'Start';
    render();
  });

  render();
});
