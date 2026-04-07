import { sbGet, sbPost, sbPatch, sbDelete, sbRpc, esc } from './config.js';

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
        <td class="td-artist">${esc(a.artist)}</td>
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

// ── Init ──────────────────────────────────────────────────────────────────────
loadAll();
