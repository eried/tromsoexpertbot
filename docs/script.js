(() => {
  const audio = document.getElementById('bgAudio');
  const toggle = document.getElementById('soundToggle');

  if (!(audio instanceof HTMLAudioElement) || !(toggle instanceof HTMLButtonElement)) return;

  audio.volume = 0.18;
  audio.muted = false;

  let hasAudioFile = true;

  const updateToggle = () => {
    const on = !audio.muted && !audio.paused;
    toggle.setAttribute('aria-pressed', on ? 'true' : 'false');
    toggle.setAttribute('aria-label', on ? 'Sound on' : 'Sound off');
    toggle.classList.toggle('sound--on', on);
  };

  const showToggle = () => {
    toggle.hidden = false;
    updateToggle();
  };

  const tryStartEnabled = async () => {
    try {
      await audio.play();
      showToggle();
    } catch {
      // Autoplay is commonly blocked unless the user has interacted.
      audio.muted = true;
      showToggle();
    }
  };

  const enableSound = async () => {
    if (!hasAudioFile) return;
    audio.muted = false;
    try {
      await audio.play();
    } catch {
      // If play fails, keep muted and let user try again.
      audio.muted = true;
    }
    updateToggle();
  };

  const disableSound = () => {
    audio.muted = true;
    audio.pause();
    updateToggle();
  };

  toggle.addEventListener('click', async () => {
    if (audio.muted || audio.paused) {
      await enableSound();
    } else {
      disableSound();
    }
  });

  audio.addEventListener('error', () => {
    hasAudioFile = false;
    toggle.hidden = true;
  }, { once: true });

  // Try to start enabled; fall back to muted if blocked.
  void tryStartEnabled();
})();

(() => {
  const viewer = document.getElementById('viewer');
  const viewerImg = document.getElementById('viewerImg');
  const shotButtons = Array.from(document.querySelectorAll('[data-shot]'));

  if (!(viewer instanceof HTMLDivElement)) return;
  if (!(viewerImg instanceof HTMLImageElement)) return;

  const shots = [
    { src: 'screenshot-1.jpg', alt: 'Report screenshot 1' },
    { src: 'screenshot-2.jpg', alt: 'Report screenshot 2' },
  ];

  let index = 0;
  let lastFocus = null;

  const setIndex = (nextIndex) => {
    index = (nextIndex + shots.length) % shots.length;
    viewerImg.src = shots[index].src;
    viewerImg.alt = shots[index].alt;
  };

  const open = (startIndex) => {
    lastFocus = document.activeElement;
    viewer.hidden = false;
    setIndex(startIndex);

    // Focus close button for keyboard users.
    const closeBtn = viewer.querySelector('[data-action="close"]');
    if (closeBtn instanceof HTMLButtonElement) closeBtn.focus();
  };

  const close = () => {
    viewer.hidden = true;
    viewerImg.removeAttribute('src');
    viewerImg.alt = '';
    if (lastFocus instanceof HTMLElement) lastFocus.focus();
    lastFocus = null;
  };

  const prev = () => setIndex(index - 1);
  const next = () => setIndex(index + 1);

  for (const btn of shotButtons) {
    btn.addEventListener('click', () => {
      const raw = btn.getAttribute('data-shot');
      const parsed = raw ? Number.parseInt(raw, 10) : 0;
      open(Number.isFinite(parsed) ? parsed : 0);
    });
  }

  viewer.addEventListener('click', (e) => {
    const target = e.target;
    if (!(target instanceof Element)) return;

    const actionEl = target.closest('[data-action]');
    const action = actionEl?.getAttribute('data-action');

    if (action === 'close') close();
    if (action === 'prev') prev();
    if (action === 'next') next();
  });

  document.addEventListener('keydown', (e) => {
    if (viewer.hidden) return;

    if (e.key === 'Escape') {
      e.preventDefault();
      close();
      return;
    }

    if (e.key === 'ArrowLeft') {
      e.preventDefault();
      prev();
      return;
    }

    if (e.key === 'ArrowRight') {
      e.preventDefault();
      next();
    }
  });
})();
