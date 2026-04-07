import { SUPABASE_URL, SB_HEADERS, sbGet, sbPost, sbPatch, sbDelete, sbRpc, esc } from './config.js';

// ── Estado ─────────────────────────────────────────────────────────────────────
let allArtists    = [];
let allGenres     = [];  // [{id: number, name: string}]
let genreCounts   = {};
let currentView   = "all";
let searchTerm    = "";
let editingArtist = null;
let editingGenreId = null;

// ── Erros ──────────────────────────────────────────────────────────────────────
function showError(msg) {
  document.getElementById("error-msg").textContent = msg;
  document.getElementById("error-banner").classList.remove("hidden");
}
window.dismissError = () => document.getElementById("error-banner").classList.add("hidden");

// ── Carregamento inicial ───────────────────────────────────────────────────────
async function loadAll() {
  try {
    const [genresData, artistsData] = await Promise.all([
      sbGet("genres?select=id,name&order=name"),
      sbGet("artists_with_genres?select=name,track_count,genres&order=name"),
    ]);
    allGenres  = genresData;
    allArtists = artistsData.map(r => ({
      artist:      r.name,
      track_count: r.track_count,
      genres:      r.genres || [],
    }));
    computeGenreCounts();
    renderSidebar();
    renderTable();
  } catch (e) {
    showError(`Falha ao carregar dados: ${e.message}`);
    document.getElementById("genre-list").innerHTML   = '<div class="state-msg">Erro ao carregar</div>';
    document.getElementById("artist-tbody").innerHTML = '<tr><td colspan="4" class="state-msg">Erro ao conectar ao Supabase.</td></tr>';
  }
}

function computeGenreCounts() {
  genreCounts = {};
  for (const a of allArtists)
    for (const g of a.genres)
      genreCounts[g] = (genreCounts[g] || 0) + 1;
}

// ── Sidebar ────────────────────────────────────────────────────────────────────
function renderSidebar() {
  const list = document.getElementById("genre-list");
  if (!allGenres.length) {
    list.innerHTML = '<div class="state-msg">Nenhum gênero</div>';
    return;
  }
  list.innerHTML = allGenres.map(g => {
    if (editingGenreId === g.id) {
      return `<div class="genre-chip editing">
        <input class="genre-edit-input"
               data-genre-id="${g.id}"
               value="${esc(g.name)}"
               maxlength="40"
               autocomplete="off" />
        <div class="genre-chip-btns" style="opacity:1">
          <button class="btn-icon" data-action="save-genre" data-genre-id="${g.id}" title="Salvar">✓</button>
          <button class="btn-icon" data-action="cancel-genre" title="Cancelar">✕</button>
        </div>
      </div>`;
    }
    const count = genreCounts[g.name] || 0;
    return `<div class="genre-chip">
      <span class="genre-chip-name">${esc(g.name)}</span>
      <div class="genre-chip-right">
        <span class="genre-chip-count">${count}</span>
        <div class="genre-chip-btns">
          <button class="btn-icon" data-action="edit-genre" data-genre-id="${g.id}" data-genre-name="${esc(g.name)}" title="Renomear">✎</button>
          <button class="btn-icon danger" data-action="delete-genre" data-genre-id="${g.id}" data-genre-name="${esc(g.name)}" title="Excluir">✕</button>
        </div>
      </div>
    </div>`;
  }).join("");
}

// ── Delegação de eventos da sidebar (editar/excluir gênero) ───────────────────
document.getElementById("genre-list").addEventListener("click", async e => {
  const btn = e.target.closest("[data-action]");
  if (!btn) return;
  const action   = btn.dataset.action;
  const genreId  = parseInt(btn.dataset.genreId, 10);

  if (action === "edit-genre") {
    editingGenreId = genreId;
    renderSidebar();
    document.querySelector(".genre-edit-input")?.focus();
    return;
  }

  if (action === "cancel-genre") {
    editingGenreId = null;
    renderSidebar();
    return;
  }

  if (action === "save-genre") {
    const input   = document.querySelector(`.genre-edit-input[data-genre-id="${genreId}"]`);
    const newName = input?.value.trim();
    if (!newName) return;
    const g = allGenres.find(x => x.id === genreId);
    if (g && newName === g.name) { editingGenreId = null; renderSidebar(); return; }
    btn.disabled = true;
    try {
      await sbPatch(`genres?id=eq.${genreId}`, { name: newName });
      if (g) {
        const oldName = g.name;
        g.name = newName;
        for (const a of allArtists) {
          const idx = a.genres.indexOf(oldName);
          if (idx !== -1) a.genres[idx] = newName;
        }
        if (oldName in genreCounts) {
          genreCounts[newName] = genreCounts[oldName];
          delete genreCounts[oldName];
        }
      }
      editingGenreId = null;
      renderSidebar();
      renderTable();
    } catch (err) { showError(`Erro ao renomear: ${err.message}`); btn.disabled = false; }
    return;
  }

  if (action === "delete-genre") {
    const genreName = btn.dataset.genreName;
    const count     = genreCounts[genreName] || 0;
    const msg = count > 0
      ? `Excluir o gênero "${genreName}"?\n\nEle está vinculado a ${count} artista${count !== 1 ? "s" : ""}. Os vínculos serão removidos automaticamente.`
      : `Excluir o gênero "${genreName}"?`;
    if (!confirm(msg)) return;
    btn.disabled = true;
    try {
      await sbDelete(`genres?id=eq.${genreId}`);
      allGenres = allGenres.filter(x => x.id !== genreId);
      for (const a of allArtists) {
        a.genres = a.genres.filter(x => x !== genreName);
      }
      delete genreCounts[genreName];
      if (editingGenreId === genreId) editingGenreId = null;
      renderSidebar();
      renderTable();
    } catch (err) { showError(`Erro ao excluir: ${err.message}`); btn.disabled = false; }
  }
});

// Enter/Escape no input inline da sidebar
document.getElementById("genre-list").addEventListener("keydown", e => {
  if (!e.target.classList.contains("genre-edit-input")) return;
  if (e.key === "Enter") {
    e.preventDefault();
    document.querySelector(`[data-action="save-genre"][data-genre-id="${editingGenreId}"]`)?.click();
  }
  if (e.key === "Escape") {
    editingGenreId = null;
    renderSidebar();
  }
});

// ── Tabela de artistas ─────────────────────────────────────────────────────────
function filteredArtists() {
  let list = allArtists;
  if (currentView === "unclassified") list = list.filter(a => !a.genres.length);
  if (searchTerm) {
    const q = searchTerm.toLowerCase();
    list = list.filter(a => a.artist.toLowerCase().includes(q));
  }
  return list;
}

function renderTable() {
  const tbody = document.getElementById("artist-tbody");
  const list  = filteredArtists();
  document.getElementById("artist-count").textContent =
    `${list.length} artista${list.length !== 1 ? "s" : ""}`;

  if (!list.length) {
    tbody.innerHTML = '<tr><td colspan="4" class="state-msg">Nenhum artista encontrado.</td></tr>';
    return;
  }

  tbody.innerHTML = list.map(a => {
    const isEditing = editingArtist === a.artist;
    const genresCurrent = a.genres.length
      ? a.genres.map(g => `<span class="genre-tag">${esc(g)}</span>`).join("")
      : '<span class="no-genre">sem gênero</span>';

    const mainRow = `
      <tr>
        <td class="td-artist"><a class="td-artist-link" data-action="open-artist" data-artist="${esc(a.artist)}">${esc(a.artist)}</a></td>
        <td class="td-count">${a.track_count}</td>
        <td class="td-genres">${genresCurrent}</td>
        <td class="td-actions">
          <button class="btn-edit" data-action="edit" data-artist="${esc(a.artist)}">
            ${isEditing ? "Editando…" : "Editar"}
          </button>
        </td>
      </tr>`;

    if (!isEditing) return mainRow;

    const checkboxes = allGenres.map(g => {
      const checked = a.genres.includes(g.name);
      return `<label class="genre-check-label${checked ? " checked" : ""}">
        <input type="checkbox" value="${esc(g.name)}"${checked ? " checked" : ""}>
        ${esc(g.name)}
      </label>`;
    }).join("");

    const editRow = `
      <tr class="edit-row">
        <td colspan="4">
          <div class="edit-row-inner">
            <span class="edit-label">Gêneros:</span>
            <div class="genre-checkboxes">${checkboxes}</div>
            <div class="edit-actions">
              <button class="btn-save"   data-action="save"   data-artist="${esc(a.artist)}">Salvar</button>
              <button class="btn-cancel" data-action="cancel">Cancelar</button>
              <button class="btn-remove" data-action="remove" data-artist="${esc(a.artist)}">Remover vínculos</button>
            </div>
          </div>
        </td>
      </tr>`;
    return mainRow + editRow;
  }).join("");
}

// ── Event delegation — tabela de artistas ─────────────────────────────────────
const artistTbody = document.getElementById("artist-tbody");

artistTbody.addEventListener("change", e => {
  if (e.target.type === "checkbox") {
    e.target.closest(".genre-check-label")?.classList.toggle("checked", e.target.checked);
  }
});

artistTbody.addEventListener("click", async e => {
  const btn = e.target.closest("[data-action]");
  if (!btn) return;
  const action = btn.dataset.action;
  const artist = btn.dataset.artist;

  if (action === "edit") {
    editingArtist = artist;
    renderTable();
    document.querySelector(".edit-row")?.scrollIntoView({ block: "nearest" });
    return;
  }

  if (action === "cancel") {
    editingArtist = null;
    renderTable();
    return;
  }

  if (action === "save") {
    const container = document.querySelector(".edit-row .genre-checkboxes");
    const checked   = [...container.querySelectorAll("input:checked")].map(i => i.value);
    btn.disabled = true;
    try {
      await sbRpc("set_artist_genres", { p_artist_name: artist, p_genre_names: checked });
      const a = allArtists.find(x => x.artist === artist);
      if (a) a.genres = checked;
      editingArtist = null;
      computeGenreCounts();
      renderSidebar();
      renderTable();
    } catch (err) { showError(`Erro ao salvar: ${err.message}`); btn.disabled = false; }
    return;
  }

  if (action === "remove") {
    btn.disabled = true;
    try {
      await sbRpc("set_artist_genres", { p_artist_name: artist, p_genre_names: [] });
      const a = allArtists.find(x => x.artist === artist);
      if (a) a.genres = [];
      editingArtist = null;
      computeGenreCounts();
      renderSidebar();
      renderTable();
    } catch (err) { showError(`Erro ao remover: ${err.message}`); btn.disabled = false; }
  }
});

// ── Criar gênero ───────────────────────────────────────────────────────────────
const newGenreInput = document.getElementById("new-genre-input");
const btnAddGenre   = document.getElementById("btn-add-genre");

newGenreInput.addEventListener("input",   () => { btnAddGenre.disabled = !newGenreInput.value.trim(); });
newGenreInput.addEventListener("keydown", e  => { if (e.key === "Enter" && !btnAddGenre.disabled) addGenre(); });
btnAddGenre.addEventListener("click", addGenre);

async function addGenre() {
  const genre = newGenreInput.value.trim();
  if (!genre) return;
  btnAddGenre.disabled = true;
  try {
    const result = await sbPost("genres?on_conflict=name", { name: genre });
    const newG   = Array.isArray(result) ? result[0] : result;
    if (newG && !allGenres.find(x => x.id === newG.id)) {
      allGenres.push({ id: newG.id, name: newG.name });
      allGenres.sort((a, b) => a.name.localeCompare(b.name));
    }
    newGenreInput.value = "";
    renderSidebar();
    renderTable();
  } catch (e) { showError(`Erro ao criar gênero: ${e.message}`); }
  finally { btnAddGenre.disabled = !newGenreInput.value.trim(); }
}

// ── Filtros ────────────────────────────────────────────────────────────────────
document.querySelector(".filter-toggle").addEventListener("click", e => {
  const btn = e.target.closest(".ftoggle-btn");
  if (!btn) return;
  document.querySelectorAll(".ftoggle-btn").forEach(b => b.classList.remove("active"));
  btn.classList.add("active");
  currentView   = btn.dataset.view;
  editingArtist = null;
  renderTable();
});

document.getElementById("search-input").addEventListener("input", e => {
  searchTerm    = e.target.value;
  editingArtist = null;
  renderTable();
});

// ── Artist Detail Panel ──────────────────────────────────────────────────────
let currentArtistDetail = null;

const spIconSvg = `<svg viewBox="0 0 24 24"><path d="M12 0C5.4 0 0 5.4 0 12s5.4 12 12 12 12-5.4 12-12S18.66 0 12 0zm5.521 17.34c-.24.359-.66.48-1.021.24-2.82-1.74-6.36-2.101-10.561-1.141-.418.122-.779-.179-.899-.539-.12-.421.18-.78.54-.9 4.56-1.021 8.52-.6 11.64 1.32.42.18.479.659.301 1.02zm1.44-3.3c-.301.42-.841.6-1.262.3-3.239-1.98-8.159-2.58-11.939-1.38-.479.12-1.02-.12-1.14-.6-.12-.48.12-1.021.6-1.141C9.6 9.9 15 10.561 18.72 12.84c.361.181.54.78.241 1.2zm.12-3.36C15.24 8.4 8.82 8.16 5.16 9.301c-.6.179-1.2-.181-1.38-.721-.18-.601.18-1.2.72-1.381 4.26-1.26 11.28-1.02 15.721 1.621.539.3.719 1.02.419 1.56-.299.421-1.02.599-1.559.3z"/></svg>`;

function openArtistDetail(artistName) {
  currentArtistDetail = artistName;
  const overlay = document.getElementById("artist-detail-overlay");
  overlay.classList.add("open");
  document.getElementById("artist-detail-title").textContent = artistName;
  document.getElementById("artist-detail-count").textContent = "";
  document.getElementById("artist-detail-body").innerHTML = '<div class="state-msg">Carregando discografia...</div>';
  loadArtistTracks(artistName);
}

function closeArtistDetail() {
  currentArtistDetail = null;
  document.getElementById("artist-detail-overlay").classList.remove("open");
}

async function loadArtistTracks(artistName) {
  const body = document.getElementById("artist-detail-body");
  const countEl = document.getElementById("artist-detail-count");
  try {
    const tracks = await sbGet(
      `artist_tracks?artist_name=eq.${encodeURIComponent(artistName)}&select=*&order=popularity.desc`
    );
    if (!tracks || tracks.length === 0) {
      body.innerHTML = '<div class="state-msg">Nenhuma discografia sincronizada.<br>Clique em "Sincronizar" para buscar.</div>';
      countEl.textContent = "";
      return;
    }
    countEl.textContent = `${tracks.length} músicas`;
    renderArtistTracks(tracks);
  } catch (e) {
    body.innerHTML = `<div class="state-msg">Erro: ${esc(e.message)}</div>`;
  }
}

function formatDuration(ms) {
  if (!ms) return "";
  const m = Math.floor(ms / 60000);
  const s = Math.floor((ms % 60000) / 1000);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

function formatDate(d) {
  if (!d) return "";
  if (d.length === 4) return d;
  if (d.length === 7) return d.split("-").reverse().slice(0, 2).join("/");
  const parts = d.split("-");
  return `${parts[2]}/${parts[1]}/${parts[0]}`;
}

function copyToClipboard(url, btn) {
  navigator.clipboard.writeText(url).then(() => {
    const orig = btn.textContent;
    btn.textContent = "✓";
    setTimeout(() => { btn.textContent = orig; }, 1200);
  });
}

function renderArtistTracks(tracks) {
  const body = document.getElementById("artist-detail-body");
  const rows = tracks.map((t, i) => {
    const rank = i + 1;
    const rankCls = rank === 1 ? "rank-gold" : rank === 2 ? "rank-silver" : rank === 3 ? "rank-bronze" : "";
    const popWidth = Math.max(2, t.popularity * 0.6);
    const spLink = t.spotify_url
      ? `<span class="copy-cell"><a class="sp-link-small" href="${esc(t.spotify_url)}" target="_blank" rel="noopener">${spIconSvg} Ouvir</a><button class="btn-copy-link" data-url="${esc(t.spotify_url)}" title="Copiar link">📋</button></span>`
      : "";
    return `<tr>
      <td class="col-rank ${rankCls}">${rank}</td>
      <td>${esc(t.track_name)}</td>
      <td style="color:var(--muted);font-size:12px">${esc(t.album_name || "")}</td>
      <td class="col-date">${formatDate(t.release_date)}</td>
      <td class="col-pop"><span class="pop-bar" style="width:${popWidth}px"></span><span class="pop-num">${t.popularity}</span></td>
      <td>${spLink}</td>
    </tr>`;
  }).join("");

  body.innerHTML = `<table class="artist-tracks-table">
    <thead><tr><th>#</th><th>Música</th><th>Álbum</th><th>Lançamento</th><th>Popularidade</th><th>Spotify</th></tr></thead>
    <tbody>${rows}</tbody>
  </table>`;
}

// Open artist from table click
artistTbody.addEventListener("click", e => {
  const link = e.target.closest("[data-action='open-artist']");
  if (link) {
    e.preventDefault();
    openArtistDetail(link.dataset.artist);
    return;
  }
});

// Close overlay
document.getElementById("btn-close-detail").addEventListener("click", closeArtistDetail);
document.getElementById("artist-detail-overlay").addEventListener("click", e => {
  if (e.target === e.currentTarget) closeArtistDetail();
});
document.addEventListener("keydown", e => {
  if (e.key === "Escape" && currentArtistDetail) closeArtistDetail();
});

// Copy link in artist detail
document.getElementById("artist-detail-body").addEventListener("click", e => {
  const btn = e.target.closest(".btn-copy-link");
  if (btn) copyToClipboard(btn.dataset.url, btn);
});

// Sync artist discography
document.getElementById("btn-sync-artist").addEventListener("click", async () => {
  if (!currentArtistDetail) return;
  const btn = document.getElementById("btn-sync-artist");
  const label = document.getElementById("sync-artist-label");
  const body = document.getElementById("artist-detail-body");

  btn.disabled = true;
  btn.classList.add("syncing");
  label.textContent = "Buscando...";

  try {
    const res = await fetch(`${SUPABASE_URL}/functions/v1/sync-artist-discography`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${SB_HEADERS.apikey}`,
      },
      body: JSON.stringify({ artist_name: currentArtistDetail }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);

    label.textContent = `${data.total_tracks} músicas!`;
    document.getElementById("artist-detail-count").textContent = `${data.total_tracks} músicas`;
    await loadArtistTracks(currentArtistDetail);
  } catch (e) {
    label.textContent = "Erro!";
    body.innerHTML = `<div class="state-msg">Erro ao sincronizar: ${esc(e.message)}</div>`;
  }

  setTimeout(() => {
    btn.classList.remove("syncing");
    label.textContent = "Sincronizar";
    btn.disabled = false;
  }, 3000);
});

// ── Init ──────────────────────────────────────────────────────────────────────
loadAll();
