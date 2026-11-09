const mode = document.querySelector('meta[name="clipscribe-mode"]')?.content || "auto";
const localHosts = new Set(["localhost", "127.0.0.1", "::1"]);

export const PUBLIC_MODE = mode === "public" || (mode === "auto" && !localHosts.has(window.location.hostname));

export function applyAppMode() {
  document.body.classList.toggle("public-mode", PUBLIC_MODE);
  document.querySelectorAll("[data-admin-only]").forEach((element) => { element.hidden = PUBLIC_MODE; });
  document.getElementById("app-mode-badge")?.classList.toggle("hidden", !PUBLIC_MODE);
}
