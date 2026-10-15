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

  audio.preload = 'auto';

  commentItems.forEach(item => {
    item.addEventListener('click', () => {
      const src = item.dataset.src;
      if (!src) return;

      audio.pause();
      audio.src = src;
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
    const format = s => {
      const m = Math.floor(s / 60).toString().padStart(2, '0');
      const sec = Math.floor(s % 60).toString().padStart(2, '0');
      return `${m}:${sec}`;
    };
    timeDisplay.textContent =
      `${format(audio.currentTime)} / ${isNaN(audio.duration) ? '00:00' : format(audio.duration)}`;
  }
});

document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll(".error-circle").forEach(el => {
    const v = parseInt(el.textContent.trim());
    if (v >= 1) el.classList.add("red-bg");
  });
});

window.addEventListener('DOMContentLoaded', () => {
  document.body.classList.add('page-loaded');
});
