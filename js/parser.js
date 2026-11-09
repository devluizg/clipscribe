/** Utilities for parsing WebVTT/SubRip captions into short dictation segments. */
const TIMESTAMP = /(?:(\d{1,2}):)?(\d{2}):(\d{2})([,.]\d{1,3})?/;

export function parseTimestamp(value) {
  const match = value.trim().match(TIMESTAMP);
  if (!match) throw new Error(`Timestamp inválido: ${value}`);
  const [, hours = "0", minutes, seconds, fraction = ".0"] = match;
  return Number(hours) * 3600 + Number(minutes) * 60 + Number(seconds) + Number(`0${fraction.replace(",", ".")}`);
}

export function cleanCaptionText(text) {
  return text
    .replace(/<[^>]*>/g, " ")
    .replace(/\[[^\]]*\]/g, " ")
    .replace(/\([^)]*\)/g, " ")
    .replace(/\{[^}]*\}/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

export function getWords(text) {
  return text.match(/[\p{L}\p{N}]+(?:['’][\p{L}\p{N}]+)*/gu) ?? [];
}

function rawCues(source) {
  const normalized = source.replace(/^\uFEFF/, "").replace(/\r\n?/g, "\n").trim();
  const blocks = normalized.split(/\n\s*\n/);
  const cues = [];
  for (const block of blocks) {
    const lines = block.split("\n").map((line) => line.trim()).filter(Boolean);
    if (!lines.length || /^WEBVTT(?:\s|$)/i.test(lines[0]) || /^(NOTE|STYLE|REGION)(?:\s|$)/i.test(lines[0])) continue;
    const timingIndex = lines.findIndex((line) => line.includes("-->"));
    if (timingIndex < 0) continue;
    const [from, to] = lines[timingIndex].split("-->");
    try {
      const startTime = parseTimestamp(from);
      const endTime = parseTimestamp(to.trim().split(/\s+/)[0]);
      const text = cleanCaptionText(lines.slice(timingIndex + 1).join(" "));
      if (text && endTime > startTime) cues.push({ startTime, endTime, text });
    } catch { /* Ignores malformed individual cue while preserving the file. */ }
  }
  return cues;
}

/**
 * Pipeline-generated cues are authoritative. Only exceptionally large cues
 * are split, first on sentence endings and then with a 22-word safety limit.
 */
export function makeNaturalSegments(cues, { maxWords = 22, splitShortSegments = true } = {}) {
  const segments = [];
  for (const cue of cues) {
    const cueWords = getWords(cue.text);
    const safetyLimit = Math.max(22, maxWords);
    const pieces = splitShortSegments && cueWords.length > safetyLimit
      ? cue.text.match(/[^.!?…]+[.!?…]+|[^.!?…]+$/g) ?? [cue.text]
      : [cue.text];
    const expanded = pieces.flatMap((piece) => {
      const words = getWords(piece);
      if (words.length <= safetyLimit) return [{ text: piece.trim(), words }];
      const chunks = [];
      for (let cursor = 0; cursor < words.length;) {
        const remaining = words.length - cursor;
        const size = remaining <= safetyLimit ? remaining : Math.min(safetyLimit, remaining - 5);
        const slice = words.slice(cursor, cursor + size);
        chunks.push({ text: slice.join(" "), words: slice });
        cursor += size;
      }
      return chunks;
    }).filter((piece) => piece.words.length);
    const totalWords = expanded.reduce((sum, part) => sum + part.words.length, 0);
    let cursor = cue.startTime;
    expanded.forEach((part, index) => {
      const isLast = index === expanded.length - 1;
      const duration = cue.endTime - cue.startTime;
      const endTime = isLast ? cue.endTime : cursor + duration * (part.words.length / totalWords);
      segments.push({ id: segments.length + 1, startTime: cursor, endTime, text: part.text, words: part.words });
      cursor = endTime;
    });
  }
  return segments;
}

export function parseSubtitles(source, options) {
  if (typeof source !== "string" || !source.trim()) throw new Error("A legenda está vazia.");
  return makeNaturalSegments(rawCues(source), options);
}
