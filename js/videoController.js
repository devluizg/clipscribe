/** Precise segment playback controller. It never seeks while a user is dragging native controls. */
export class VideoController {
  constructor(video, { onSegmentEnded, onStateChange } = {}) {
    this.video = video; this.segments = []; this.currentIndex = 0; this.isSegmentPlayback = false;
    this.onSegmentEnded = onSegmentEnded; this.onStateChange = onStateChange; this.frameId = null;
    this.tick = this.tick.bind(this);
    video.addEventListener("play", () => this.watch());
    video.addEventListener("pause", () => { this.stopWatch(); this.onStateChange?.(false); });
    video.addEventListener("ended", () => { this.isSegmentPlayback = false; this.stopWatch(); this.onStateChange?.(false); });
  }
  setSegments(segments) { this.segments = segments; this.currentIndex = 0; }
  setPlaybackRate(rate) { this.video.playbackRate = Number(rate); }
  get currentSegment() { return this.segments[this.currentIndex] ?? null; }
  async playCurrentSegment() {
    const segment = this.currentSegment; if (!segment) return;
    await this.waitForMetadata();
    this.isSegmentPlayback = true;
    this.video.currentTime = segment.startTime;
    await this.waitForSeek();
    try { await this.video.play(); this.watch(); return true; } catch { this.isSegmentPlayback = false; this.onStateChange?.(false); return false; }
  }
  togglePlayPause() {
    if (!this.currentSegment) return;
    if (this.video.paused) {
      if (this.video.currentTime < this.currentSegment.startTime || this.video.currentTime >= this.currentSegment.endTime) return this.playCurrentSegment();
      this.isSegmentPlayback = true; this.video.play().then(() => this.watch());
    } else this.video.pause();
  }
  goToSegment(index) {
    if (index < 0 || index >= this.segments.length) return;
    this.currentIndex = index; this.onStateChange?.(false); return this.playCurrentSegment();
  }
  waitForSeek(timeout = 5000) {
    if (!this.video.seeking) return Promise.resolve();
    return new Promise((resolve, reject) => {
      const cleanup = () => { clearTimeout(timer); this.video.removeEventListener("seeked", ready); this.video.removeEventListener("error", failed); };
      const ready = () => { cleanup(); resolve(); };
      const failed = () => { cleanup(); reject(this.video.error || new Error("Falha ao posicionar o vídeo.")); };
      const timer = setTimeout(() => { cleanup(); reject(new Error("O vídeo demorou demais para posicionar a primeira frase.")); }, timeout);
      this.video.addEventListener("seeked", ready, { once: true });
      this.video.addEventListener("error", failed, { once: true });
    });
  }
  waitForMetadata(timeout = 10000) {
    if (this.video.readyState >= HTMLMediaElement.HAVE_METADATA) return Promise.resolve();
    return new Promise((resolve, reject) => {
      const cleanup = () => { clearTimeout(timer); this.video.removeEventListener("loadedmetadata", ready); this.video.removeEventListener("error", failed); };
      const ready = () => { cleanup(); resolve(); };
      const failed = () => { cleanup(); reject(this.video.error || new Error("Falha ao carregar vídeo.")); };
      const timer = setTimeout(() => { cleanup(); reject(new Error("O navegador não recebeu os metadados do vídeo.")); }, timeout);
      this.video.addEventListener("loadedmetadata", ready, { once: true });
      this.video.addEventListener("error", failed, { once: true });
    });
  }
  watch() { this.stopWatch(); this.frameId = requestAnimationFrame(this.tick); this.onStateChange?.(true); }
  stopWatch() { if (this.frameId) cancelAnimationFrame(this.frameId); this.frameId = null; }
  tick() {
    const segment = this.currentSegment;
    if (!this.video.paused && this.isSegmentPlayback && segment && this.video.currentTime >= segment.endTime - 0.008) {
      this.video.currentTime = segment.endTime; this.isSegmentPlayback = false; this.video.pause(); this.onSegmentEnded?.(this.currentIndex); return;
    }
    if (!this.video.paused) this.frameId = requestAnimationFrame(this.tick);
  }
}
