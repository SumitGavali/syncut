/** Generates a placeholder WAV (speech-like bursts of noise) so WaveSurfer has something to draw. */
export function makeDummyWavUrl(seconds = 90, rate = 8000): string {
  const n = seconds * rate;
  const buf = new ArrayBuffer(44 + n * 2);
  const v = new DataView(buf);
  const str = (o: number, s: string) => [...s].forEach((c, i) => v.setUint8(o + i, c.charCodeAt(0)));
  str(0, 'RIFF'); v.setUint32(4, 36 + n * 2, true); str(8, 'WAVE'); str(12, 'fmt ');
  v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true);
  v.setUint32(24, rate, true); v.setUint32(28, rate * 2, true); v.setUint16(32, 2, true);
  v.setUint16(34, 16, true); str(36, 'data'); v.setUint32(40, n * 2, true);
  for (let i = 0; i < n; i++) {
    const t = i / rate;
    const env = 0.12 + 0.88 * Math.abs(Math.sin(t * 0.9) * Math.sin(t * 0.23 + 0.5));
    v.setInt16(44 + i * 2, (Math.random() * 2 - 1) * env * 0.8 * 32767, true);
  }
  return URL.createObjectURL(new Blob([buf], { type: 'audio/wav' }));
}
