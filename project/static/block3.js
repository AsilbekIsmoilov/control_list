document.addEventListener('DOMContentLoaded', () => {
  const audio = document.getElementById('audio-player');
  const commentItems = document.querySelectorAll('.comment-item');

  const playPauseBtn = document.querySelector('.play-pause');
  const playPauseIcon = playPauseBtn.querySelector('img');
  const backwardBtn = document.querySelector('.backward');
  const forwardBtn = document.querySelector('.forward');
  const seekBar = document.querySelector('.seek-bar');
  const timeDisplay = document.querySelector('.time-display');
  const speedSelect = document.querySelector('.speed-select');
  const volumeRange = document.querySelector('.volume-range');

  let activeComment = null;
  let isSeeking = false;
  let hls = null;

  audio.preload = 'auto';

  // Audio shifrlangan HLS bo'laklari ko'rinishida keladi: playlist, AES kaliti
  // va seg_NNN.ts. hls.js kalitni alohida so'rab, bo'laklarni xotirada
  // deshifrlaydi va Media Source Extensions orqali <audio> ga uzatadi.
  function load(src) {
    if (hls) { hls.destroy(); hls = null; }

    // Tartib muhim: avval Hls.isSupported(). Chrome `canPlayType('…mpegurl')`
    // ga ba'zan 'maybe' deydi, aslida esa HLS'ni o'ynata olmaydi — native
    // yo'lni oldin tekshirsak, audio umuman eshitilmaydi.
    if (!Hls.isSupported()) {
      audio.src = src;                 // Safari / eski iOS — native HLS
      return;
    }
    hls = new Hls();
    hls.loadSource(src);
    hls.attachMedia(audio);
  }

  commentItems.forEach(item => {
    item.addEventListener('click', () => {
      const src = item.dataset.src;
      if (!src) return;

      audio.pause();
      load(src);
      audio.volume = volumeRange.value;
      audio.play();

      playPauseIcon.src = '/static/img/pause.png';

      if (activeComment) activeComment.classList.remove('active');
      item.classList.add('active');
      activeComment = item;

      item.scrollIntoView({ behavior: 'smooth', block: 'center' });
    });
  });

  playPauseBtn.addEventListener('click', () => {
    if (audio.paused) {
      audio.play();
      playPauseIcon.src = '/static/img/pause.png';
    } else {
      audio.pause();
      playPauseIcon.src = '/static/img/play.png';
    }
  });

  backwardBtn.addEventListener('click', () => {
    if (!isNaN(audio.duration)) {
      audio.currentTime = Math.max(0, audio.currentTime - 10);
    }
  });

  forwardBtn.addEventListener('click', () => {
    if (!isNaN(audio.duration)) {
      audio.currentTime = Math.min(audio.duration, audio.currentTime + 10);
    }
  });

  volumeRange.addEventListener('input', () => {
    audio.volume = volumeRange.value;
  });

  speedSelect.addEventListener('change', () => {
    audio.playbackRate = speedSelect.value;
  });

  audio.addEventListener('loadedmetadata', () => {
    seekBar.max = Math.floor(audio.duration);
    updateTime();
  });

  audio.addEventListener('timeupdate', () => {
    if (!isSeeking) {
      seekBar.value = Math.floor(audio.currentTime);
      updateTime();
    }
  });

  seekBar.addEventListener('input', () => {
    isSeeking = true;
    audio.currentTime = seekBar.value;
  });

  seekBar.addEventListener('change', () => {
    isSeeking = false;
  });

  audio.addEventListener('ended', () => {
    playPauseIcon.src = '/static/img/play.png';
    if (activeComment) activeComment.classList.remove('active');
    activeComment = null;
  });

  function updateTime() {
    const format = (t) => {
      if (isNaN(t)) return '00:00';
      const m = String(Math.floor(t / 60)).padStart(2, '0');
      const sec = String(Math.floor(t % 60)).padStart(2, '0');
      return `${m}:${sec}`;
    };
    timeDisplay.textContent =
      `${format(audio.currentTime)} / ${isNaN(audio.duration) ? '00:00' : format(audio.duration)}`;
  }
});
