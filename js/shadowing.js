/** Browser-native recording for shadowing; no speech-recognition service required. */
export class ShadowingRecorder {
  constructor(onStateChange = () => {}) { this.onStateChange = onStateChange; this.recorder = null; this.stream = null; this.chunks = []; this.recordingUrl = null; }
  get hasRecording() { return Boolean(this.recordingUrl); }
  async toggle() { return this.recorder?.state === "recording" ? this.stop() : this.start(); }
  async start() {
    if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) throw new Error("O gravador não é suportado neste navegador.");
    this.stream = await navigator.mediaDevices.getUserMedia({ audio: true }); this.chunks = [];
    const types = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg"].filter((type) => MediaRecorder.isTypeSupported(type));
    this.recorder = new MediaRecorder(this.stream, types[0] ? { mimeType: types[0] } : undefined);
    this.recorder.addEventListener("dataavailable", (event) => { if (event.data.size) this.chunks.push(event.data); });
    this.recorder.addEventListener("stop", () => { if (this.recordingUrl) URL.revokeObjectURL(this.recordingUrl); this.recordingUrl = URL.createObjectURL(new Blob(this.chunks, { type: this.recorder?.mimeType || "audio/webm" })); this.stream?.getTracks().forEach((track) => track.stop()); this.onStateChange({ recording: false, recorded: true }); });
    this.recorder.start(); this.onStateChange({ recording: true, recorded: this.hasRecording });
  }
  stop() { if (this.recorder?.state === "recording") this.recorder.stop(); }
  async play() { if (!this.recordingUrl) throw new Error("Grave sua voz antes de comparar."); const audio = new Audio(this.recordingUrl); await audio.play(); return new Promise((resolve) => audio.addEventListener("ended", resolve, { once: true })); }
}
