export const STOPWORDS = new Set(["the", "and", "for", "that", "with", "you", "are", "was", "but", "not", "have", "this", "from"]);
export const normalizeWord = (word) => (word.match(/[\p{L}\p{N}]/gu) ?? []).join("").toLocaleLowerCase();

export function isCriticalWord(word, errors) {
  const normalized = normalizeWord(word);
  return errors >= 2 && normalized.length > 3 && !STOPWORDS.has(normalized);
}

export function buildAnkiClozeCsv(entries) {
  const quote = (value) => `"${String(value).replaceAll('"', '""')}"`;
  return entries.map((entry) => {
    const hint = `${normalizeWord(entry.word).slice(0, 3)}...`;
    const escaped = entry.word.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const cloze = `{{c1::${entry.word}::${hint}}}`;
    const front = entry.sentence.replace(new RegExp(`\\b${escaped}\\b`, "i"), cloze);
    const back = [entry.clipTitle, entry.timestamp, entry.note].filter(Boolean).join(" · ");
    return `${quote(front)};${quote(back)}`;
  }).join("\n");
}

export class VocabularyStore {
  constructor(storage, vocabularyKey = "clipscribe.vocabulary.v1", weakKey = "clipscribe.weak-words.v1") { this.storage = storage; this.vocabularyKey = vocabularyKey; this.weakKey = weakKey; this.entries = this.read(vocabularyKey, []); this.weak = this.read(weakKey, {}); }
  read(key, fallback) { try { const value = JSON.parse(this.storage.getItem(key) || "null"); return value ?? fallback; } catch { return fallback; } }
  save() { this.storage.setItem(this.vocabularyKey, JSON.stringify(this.entries)); this.storage.setItem(this.weakKey, JSON.stringify(this.weak)); }
  add(entry) { const existing = this.entries.find((item) => item.id === entry.id); if (existing) Object.assign(existing, entry, { note: entry.note || existing.note || "", createdAt: existing.createdAt }); else this.entries.unshift({ ...entry, createdAt: new Date().toISOString() }); this.save(); return this.entries.find((item) => item.id === entry.id); }
  remove(id) { this.entries = this.entries.filter((entry) => entry.id !== id); this.save(); }
  recordIssue(context, type) { const key = `${context.clipId || "local"}|${context.startTime}|${normalizeWord(context.word)}`; const record = this.weak[key] ?? { ...context, errors: 0, reveals: 0 }; if (type === "error") record.errors += 1; if (type === "reveal") record.reveals += 1; this.weak[key] = record; this.save(); return { ...record, critical: isCriticalWord(record.word, record.errors) }; }
}
