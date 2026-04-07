// ── Configuração compartilhada do Supabase ──────────────────────────────────
export const SUPABASE_URL  = "https://suzcbyzidnzzahwrkveh.supabase.co";
export const SUPABASE_ANON = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InN1emNieXppZG56emFod3JrdmVoIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzUwNTE0OTgsImV4cCI6MjA5MDYyNzQ5OH0.78EgRoCBydInVGZNlTOmUzlNjcJhgu04VtKrzN9TSyQ";

export const SB_HEADERS = {
  "Content-Type":  "application/json",
  "apikey":        SUPABASE_ANON,
  "Authorization": `Bearer ${SUPABASE_ANON}`,
  "Prefer":        "return=representation",
};

// ── Helpers de API ──────────────────────────────────────────────────────────
export async function sbGet(path) {
  const r = await fetch(`${SUPABASE_URL}/rest/v1/${path}`, { headers: SB_HEADERS });
  if (!r.ok) { const e = await r.json().catch(() => ({})); throw new Error(e.message || `HTTP ${r.status}`); }
  return r.json();
}

export async function sbPost(path, body) {
  const r = await fetch(`${SUPABASE_URL}/rest/v1/${path}`, {
    method: "POST", headers: SB_HEADERS, body: JSON.stringify(body),
  });
  if (!r.ok) { const e = await r.json().catch(() => ({})); throw new Error(e.message || `HTTP ${r.status}`); }
  return r.json();
}

export async function sbPatch(path, body) {
  const r = await fetch(`${SUPABASE_URL}/rest/v1/${path}`, {
    method: "PATCH", headers: SB_HEADERS, body: JSON.stringify(body),
  });
  if (!r.ok) { const e = await r.json().catch(() => ({})); throw new Error(e.message || `HTTP ${r.status}`); }
  return r.json();
}

export async function sbDelete(path) {
  const r = await fetch(`${SUPABASE_URL}/rest/v1/${path}`, { method: "DELETE", headers: SB_HEADERS });
  if (!r.ok) { const e = await r.json().catch(() => ({})); throw new Error(e.message || `HTTP ${r.status}`); }
}

export async function sbRpc(fn, params) {
  const r = await fetch(`${SUPABASE_URL}/rest/v1/rpc/${fn}`, {
    method: "POST", headers: SB_HEADERS, body: JSON.stringify(params),
  });
  if (!r.ok) { const e = await r.json().catch(() => ({})); throw new Error(e.message || `HTTP ${r.status}`); }
  const txt = await r.text();
  return txt ? JSON.parse(txt) : null;
}

// ── Utilitário de escape HTML ───────────────────────────────────────────────
export function esc(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
