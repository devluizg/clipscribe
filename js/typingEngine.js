const LETTER_OR_NUMBER = /[\p{L}\p{N}]/u;
const normalizedLetters = (value) => (value.match(/[\p{L}\p{N}]/gu) ?? []).join("").toLocaleLowerCase();

export function wordDisplayParts(word) {
  let letterIndex = 0;
  return [...word].map((character) => {
    if (LETTER_OR_NUMBER.test(character)) return { type: "slot", character, letterIndex: letterIndex++ };
    return { type: "punctuation", character };
  });
}

export function hintLettersForLength(length, difficulty = "medium") {
  if (difficulty === "easy") return length <= 2 ? 0 : length <= 4 ? 1 : length <= 6 ? 2 : 3;
  if (difficulty === "hard") return length >= 6 ? 1 : 0;
  if (difficulty === "none") return 0;
  return length <= 3 ? 0 : length <= 6 ? 1 : 2;
}

function tokenize(text) {
  const pieces = text.match(/[\p{L}\p{N}]+(?:['’][\p{L}\p{N}]+)*|[^\s]/gu) ?? [];
  const tokens = []; let pendingPrefix = "";
  for (const piece of pieces) {
    if (LETTER_OR_NUMBER.test(piece)) {
      tokens.push({ prefix: pendingPrefix, word: piece, suffix: "", expected: normalizedLetters(piece) }); pendingPrefix = "";
    } else if (tokens.length) tokens[tokens.length - 1].suffix += piece;
    else pendingPrefix += piece;
  }
  return tokens;
}

/** Renders individual letter slots while a single invisible input owns keyboard focus. */
export class TypingEngine {
  constructor(input, wordBank, feedback, { onComplete, onProgress, onWordIssue, onSaveWord, onSelectionChange } = {}) {
    this.input = input; this.wordBank = wordBank; this.feedback = feedback; this.onComplete = onComplete; this.onProgress = onProgress; this.onWordIssue = onWordIssue; this.onSaveWord = onSaveWord; this.onSelectionChange = onSelectionChange;
    this.hintDifficulty = "medium"; this.tokens = []; this.wordIndex = 0; this.letterIndex = 0; this.typed = []; this.errorCounts = []; this.revealed = new Set(); this.firstAttempts = new Set(); this.selectedWords = new Set(); this.selectionMode = false; this.selectionAnchor = null; this.firstCorrect = 0; this.ignoreSpacesUntil = 0; this.done = false;
    input.addEventListener("keydown", (event) => this.onKeydown(event));
  }
  setSegment(segment) { this.tokens = tokenize(segment?.text ?? ""); this.wordIndex = 0; this.letterIndex = 0; this.typed = this.tokens.map(() => []); this.errorCounts = this.tokens.map(() => 0); this.revealed.clear(); this.firstAttempts.clear(); this.selectedWords.clear(); this.selectionMode = false; this.selectionAnchor = null; this.firstCorrect = 0; this.done = false; this.input.value = ""; this.input.disabled = !segment; this.render(); this.emitSelection(); this.setFeedback(segment ? "Ouça e digite letra por letra." : "—"); }
  setHintDifficulty(difficulty) { this.hintDifficulty = difficulty; this.render(); }
  setExpressionMode(enabled) { this.selectionMode = Boolean(enabled); this.selectedWords.clear(); this.selectionAnchor = null; this.wordBank.classList.toggle("is-selecting", this.selectionMode); this.render(); this.emitSelection(); }
  toggleExpressionWord(index) { if (!this.selectionMode) return; if (this.selectionAnchor === null) { this.selectionAnchor = index; this.selectedWords = new Set([index]); } else { const start = Math.min(this.selectionAnchor, index); const end = Math.max(this.selectionAnchor, index); this.selectedWords = new Set(Array.from({ length: end - start + 1 }, (_, offset) => start + offset)); } this.render(); this.emitSelection(); }
  getSelectedExpression() { const indexes = [...this.selectedWords].sort((a, b) => a - b); return { indexes, text: indexes.map((index) => this.tokens[index]?.word).filter(Boolean).join(" ") }; }
  emitSelection() { this.onSelectionChange?.({ active: this.selectionMode, ...this.getSelectedExpression() }); }
  focus() { if (!this.input.disabled) this.input.focus({ preventScroll: true }); }
  revealCurrentWord() { if (!this.done && this.tokens[this.wordIndex]) { this.revealed.add(this.wordIndex); this.onWordIssue?.({ word: this.tokens[this.wordIndex].word, wordIndex: this.wordIndex, errorCount: this.errorCounts[this.wordIndex], type: "reveal" }); this.render(); this.setFeedback("Palavra revelada. Tente escrevê-la agora."); } }
  onKeydown(event) {
    if (this.input.disabled || this.done || this.selectionMode || event.ctrlKey || event.altKey || event.metaKey) return;
    if (event.key === "Backspace") { event.preventDefault(); this.backspace(); return; }
    if (event.key === " ") { event.preventDefault(); if (Date.now() > this.ignoreSpacesUntil) this.setFeedback("Espaço não é necessário — avance pelas letras."); return; }
    if (event.key.length !== 1 || !LETTER_OR_NUMBER.test(event.key)) return;
    event.preventDefault(); this.typeLetter(event.key);
  }
  typeLetter(value) {
    const token = this.tokens[this.wordIndex]; if (!token) return; const expected = token.expected[this.letterIndex]; const typed = value.toLocaleLowerCase();
    const position = `${this.wordIndex}:${this.letterIndex}`; const isFirstAttempt = !this.firstAttempts.has(position);
    if (isFirstAttempt) this.firstAttempts.add(position); if (isFirstAttempt && typed === expected) this.firstCorrect += 1;
    if (typed !== expected) { const wrongWord = this.wordIndex; const wrongLetter = this.letterIndex; this.errorCounts[wrongWord] += 1; this.onWordIssue?.({ word: token.word, wordIndex: wrongWord, errorCount: this.errorCounts[wrongWord], type: "error" }); this.typed[wrongWord][wrongLetter] = { value: typed, wrong: true }; this.render(); this.setFeedback("Tente outra letra."); window.setTimeout(() => { if (!this.done && this.typed[wrongWord]?.[wrongLetter]?.wrong) { this.typed[wrongWord][wrongLetter] = undefined; this.render(); } }, 280); return; }
    this.typed[this.wordIndex][this.letterIndex] = { value: typed, wrong: false }; this.letterIndex += 1; this.render();
    if (this.letterIndex < token.expected.length) return;
    if (this.wordIndex < this.tokens.length - 1) { this.wordIndex += 1; this.letterIndex = 0; this.ignoreSpacesUntil = Date.now() + 350; this.render(); this.setFeedback("Boa. Próxima palavra."); this.onProgress?.(); return; }
    this.complete();
  }
  backspace() { if (this.letterIndex > 0) { this.letterIndex -= 1; this.typed[this.wordIndex][this.letterIndex] = undefined; } else if (this.wordIndex > 0) { this.wordIndex -= 1; this.letterIndex = this.tokens[this.wordIndex].expected.length - 1; this.typed[this.wordIndex][this.letterIndex] = undefined; } this.render(); }
  complete() { this.done = true; this.render(); this.setFeedback("Perfeito — trecho concluído.", true); const totalLetters = this.tokens.reduce((total, token) => total + token.expected.length, 0); this.onComplete?.({ firstCorrect: this.firstCorrect, totalLetters, accuracy: totalLetters ? Math.round((this.firstCorrect / totalLetters) * 100) : 100 }); }
  render() { this.wordBank.classList.toggle("is-complete", this.done); this.wordBank.replaceChildren(...this.tokens.map((token, index) => this.renderToken(token, index))); }
  renderToken(token, wordIndex) {
    const group = document.createElement("span"); group.className = "word-box"; if (wordIndex === this.wordIndex && !this.done) group.classList.add("is-active"); if (wordIndex < this.wordIndex || this.done) group.classList.add("is-complete"); if (this.selectedWords.has(wordIndex)) group.classList.add("is-selected");
    if (token.prefix) group.append(this.punctuation(token.prefix)); const slots = document.createElement("span"); slots.className = "letter-slots";
    const visibleHints = hintLettersForLength(token.expected.length, this.hintDifficulty); wordDisplayParts(token.word).forEach((part) => { if (part.type === "punctuation") { const mark = this.punctuation(part.character); mark.classList.add("contraction-mark"); slots.append(mark); return; } const letterIndex = part.letterIndex; const letter = token.expected[letterIndex]; const slot = document.createElement("span"); const entry = this.typed[wordIndex][letterIndex]; slot.className = "letter-slot"; if (wordIndex === this.wordIndex && letterIndex === this.letterIndex && !this.done) slot.classList.add("is-caret"); if (entry?.wrong) slot.classList.add("text-rose-400", "is-wrong"); if (entry && !entry.wrong) slot.classList.add("text-emerald-400", "is-correct"); const guide = letterIndex < visibleHints && !entry && !this.revealed.has(wordIndex); slot.textContent = entry?.value ?? (this.revealed.has(wordIndex) || guide ? letter : "_"); if (guide) slot.classList.add("is-guide"); if (this.revealed.has(wordIndex) && !entry) slot.classList.add("is-revealed"); slots.append(slot); });
    group.append(slots); if (token.suffix) group.append(this.punctuation(token.suffix)); group.addEventListener("click", (event) => { if (this.selectionMode) { event.preventDefault(); this.toggleExpressionWord(wordIndex); return; } if (event.shiftKey) { event.preventDefault(); this.onSaveWord?.({ word: token.word, wordIndex, errorCount: this.errorCounts[wordIndex] }); } });
    const save = document.createElement("button"); save.type = "button"; save.className = "word-save"; save.textContent = "★"; save.title = `Salvar “${token.word}” no Meu Vocabulário C1`; save.setAttribute("aria-label", save.title); save.addEventListener("click", (event) => { event.stopPropagation(); this.onSaveWord?.({ word: token.word, wordIndex, errorCount: this.errorCounts[wordIndex] }); }); group.append(save);
    return group;
  }
  punctuation(value) { const mark = document.createElement("span"); mark.className = "punctuation"; mark.textContent = value; return mark; }
  setFeedback(message, complete = false) { this.feedback.textContent = message; this.feedback.className = `mono text-sm ${complete ? "text-lime-300" : "text-stone-500"}`; }
}
