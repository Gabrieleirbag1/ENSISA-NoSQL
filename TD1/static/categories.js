"use strict";

const banner = document.getElementById("error-banner");
const bannerText = document.getElementById("error-banner-text");
const btnBannerClose = document.getElementById("btn-banner-close");
const tbody = document.getElementById("categories-body");
const emptyMessage = document.getElementById("empty-message");
const statusMessage = document.getElementById("status-message");

const API = "/api/categories";

/* --- messages --- */
function showError(message) {
  bannerText.textContent = message;
  banner.hidden = false;
  showStatus("");
}

function clearBanner() {
  banner.hidden = true;
}

function showStatus(message) {
  statusMessage.textContent = message;
  statusMessage.hidden = message.length === 0;
}

/* Returns the "error" field of an API error body, with a French fallback. */
async function extractError(resp, fallback) {
  try {
    const body = await resp.json();
    if (body && typeof body.error === "string" && body.error.length > 0) {
      return body.error;
    }
  } catch {
    /* Body is not JSON: keep the fallback message. */
  }
  return fallback;
}

/* --- data loading --- */
async function fetchCategories() {
  let resp;
  try {
    resp = await fetch(API);
  } catch {
    showError("Impossible de contacter le serveur.");
    return null;
  }
  if (!resp.ok) {
    showError(await extractError(resp, "Erreur lors du chargement des catégories."));
    return null;
  }
  let items;
  try {
    items = await resp.json();
  } catch {
    showError("Réponse du serveur invalide.");
    return null;
  }
  clearBanner();
  return items;
}

async function loadCategories() {
  const categories = await fetchCategories();
  if (categories === null) {
    return;
  }
  renderTable(categories);
}

/* --- table --- */
function renderTable(categories) {
  tbody.replaceChildren();
  emptyMessage.hidden = categories.length > 0;
  for (const category of categories) {
    const row = document.createElement("tr");

    const nameCell = document.createElement("td");
    nameCell.textContent = category.name;
    row.appendChild(nameCell);

    const inputCell = document.createElement("td");
    const input = document.createElement("input");
    input.type = "text";
    input.className = "entity-input";
    input.value = category.name;
    inputCell.appendChild(input);
    row.appendChild(inputCell);

    const actions = document.createElement("td");
    actions.className = "row-actions";

    const renameBtn = document.createElement("button");
    renameBtn.type = "button";
    renameBtn.className = "btn btn-small btn-primary";
    renameBtn.textContent = "OK";
    renameBtn.addEventListener("click", () => renameCategory(category.id, input, nameCell));

    const deleteBtn = document.createElement("button");
    deleteBtn.type = "button";
    deleteBtn.className = "btn btn-small btn-danger";
    deleteBtn.textContent = "Supprimer";
    deleteBtn.addEventListener("click", () => deleteCategory(category.id, category.name));

    actions.append(renameBtn, deleteBtn);
    row.appendChild(actions);
    tbody.appendChild(row);
  }
}

/* --- rename (PUT) --- */
async function renameCategory(id, input, nameCell) {
  clearBanner();
  showStatus("");
  let resp;
  try {
    resp = await fetch(`${API}/${encodeURIComponent(id)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: input.value }),
    });
  } catch {
    showError("Impossible de contacter le serveur.");
    return;
  }
  if (!resp.ok) {
    showError(await extractError(resp, "Impossible de renommer la catégorie."));
    return;
  }
  // Successful rename: refresh the list so every row carries the current
  // ids (a rename may re-issue the id of the renamed entity).
  await loadCategories();
}

/* --- delete (DELETE) --- */
async function deleteCategory(id, name) {
  const message = "Supprimer la catégorie « " + name + " » ? Les produits associés perdront cette catégorie.";
  if (!window.confirm(message)) {
    return;
  }
  let resp;
  try {
    resp = await fetch(`${API}/${encodeURIComponent(id)}`, { method: "DELETE" });
  } catch {
    showError("Impossible de contacter le serveur.");
    return;
  }
  if (!resp.ok) {
    showError(await extractError(resp, "Impossible de supprimer la catégorie."));
    return;
  }
  const data = await resp.json();
  clearBanner();
  const affected = data.removed_from;
  showStatus(
    affected === 1
      ? "Catégorie supprimée — 1 produit affecté."
      : "Catégorie supprimée — " + affected + " produits affectés."
  );
  await loadCategories();
}

/* --- events --- */
btnBannerClose.addEventListener("click", clearBanner);

loadCategories();
