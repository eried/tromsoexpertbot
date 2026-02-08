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
  let hideTimer = null;

  const setQuiet = (quiet) => {
    // Don't hide if user is hovering a control (desktop convenience)
    if (quiet && viewer.querySelector('.viewer__close:hover, .viewer__nav:hover')) {
      scheduleHide(); // Check again later
      return;
    }
    viewer.classList.toggle('viewer--quiet', quiet);
  };

  const scheduleHide = () => {
    if (hideTimer) window.clearTimeout(hideTimer);
    hideTimer = window.setTimeout(() => setQuiet(true), 2000);
  };

  const showControls = () => {
    setQuiet(false);
    scheduleHide();
  };

  const setIndex = (nextIndex) => {
    index = (nextIndex + shots.length) % shots.length;
    viewerImg.src = shots[index].src;
    viewerImg.alt = shots[index].alt;
  };

  const open = (startIndex) => {
    lastFocus = document.activeElement;
    viewer.hidden = false;
    setIndex(startIndex);

    showControls();

    // Focus close button for keyboard users.
    const closeBtn = viewer.querySelector('[data-action="close"]');
    if (closeBtn instanceof HTMLButtonElement) closeBtn.focus();
  };

  const close = () => {
    viewer.hidden = true;
    viewerImg.removeAttribute('src');
    viewerImg.alt = '';
    setQuiet(false);
    if (hideTimer) window.clearTimeout(hideTimer);
    hideTimer = null;
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

    // If user taps/clicks inside the viewer (even not on controls), bring controls back.
    if (!action) showControls();
  });

  // Re-show controls on activity, then auto-hide.
  viewer.addEventListener('pointermove', () => {
    if (viewer.hidden) return;
    showControls();
  });

  viewer.addEventListener('touchstart', () => {
    if (viewer.hidden) return;
    showControls();
  }, { passive: true });

  document.addEventListener('keydown', (e) => {
    if (viewer.hidden) return;

    showControls();

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
