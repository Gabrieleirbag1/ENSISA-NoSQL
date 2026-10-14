"use strict";

const PAGE_SIZE = 20;

const banner = document.getElementById("error-banner");
const bannerText = document.getElementById("error-banner-text");
const btnBannerClose = document.getElementById("btn-banner-close");
const btnAdd = document.getElementById("btn-add");
const formPanel = document.getElementById("form-panel");
const formTitle = document.getElementById("form-title");
const form = document.getElementById("product-form");
const formError = document.getElementById("form-error");
const btnCancel = document.getElementById("btn-cancel");
const tbody = document.getElementById("products-body");
const emptyMessage = document.getElementById("empty-message");
const categorySuggestions = document.getElementById("category-suggestions");
const brandSuggestions = document.getElementById("brand-suggestions");
const pageInfo = document.getElementById("page-info");
const btnPrev = document.getElementById("btn-prev");
const btnNext = document.getElementById("btn-next");

const state = { page: 1, totalPages: 0, editingId: null };

const priceFormatter = new Intl.NumberFormat("fr-FR", { style: "currency", currency: "EUR" });

const NUMBER_FIELDS = ["price", "stock", "rating", "units_sold"];

/* --- error banner --- */
function showError(message) {
  bannerText.textContent = message;
  banner.hidden = false;
}

function clearBanner() {
  banner.hidden = true;
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

/* --- table --- */
function addTextCell(row, text) {
  const cell = document.createElement("td");
  cell.textContent = text;
  row.appendChild(cell);
}

function formatDate(iso) {
  const dt = new Date(iso);
  if (Number.isNaN(dt.getTime())) {
    return iso;
  }
  return dt.toLocaleDateString("fr-FR");
}

function renderTable(items) {
  tbody.replaceChildren();
  emptyMessage.hidden = items.length > 0;
  for (const item of items) {
    const row = document.createElement("tr");
    addTextCell(row, item.name);
    addTextCell(row, item.brand ? item.brand.name : "");
    addTextCell(row, item.category ? item.category.name : "");
    addTextCell(row, priceFormatter.format(item.price));
    addTextCell(row, String(item.stock));
    addTextCell(row, item.rating.toFixed(1));
    addTextCell(row, String(item.units_sold));
    addTextCell(row, formatDate(item.created_at));

    const actions = document.createElement("td");
    actions.className = "row-actions";

    const editBtn = document.createElement("button");
    editBtn.type = "button";
    editBtn.className = "btn btn-small";
    editBtn.textContent = "Modifier";
    editBtn.addEventListener("click", () => openForm(item));

    const deleteBtn = document.createElement("button");
    deleteBtn.type = "button";
    deleteBtn.className = "btn btn-small btn-danger";
    deleteBtn.textContent = "Supprimer";
    deleteBtn.addEventListener("click", () => removeProduct(item));

    actions.append(editBtn, deleteBtn);
    row.appendChild(actions);
    tbody.appendChild(row);
  }
}

/* --- pagination --- */
function renderPagination(data) {
  state.page = Math.max(1, data.page);
  state.totalPages = data.total_pages;
  const displayedPages = Math.max(1, state.totalPages);
  pageInfo.textContent = `Page ${state.page} sur ${displayedPages} — ${data.total} produits`;
  btnPrev.disabled = state.page <= 1;
  btnNext.disabled = state.page >= state.totalPages;
}

/* Fills the free-text suggestion lists (add/edit form) from the API.
   Suggestions only: free input remains allowed. */
async function loadSuggestions() {
  for (const [endpoint, target] of [
    ["/api/categories", categorySuggestions],
    ["/api/brands", brandSuggestions],
  ]) {
    let resp;
    try {
      resp = await fetch(endpoint);
    } catch {
      return; // the lists stay empty: free input still works
    }
    if (!resp.ok) {
      return;
    }
    let items;
    try {
      items = await resp.json();
    } catch {
      return;
    }
    target.replaceChildren();
    for (const item of items) {
      const option = document.createElement("option");
      option.value = item.name;
      option.textContent = item.name;
      target.appendChild(option);
    }
  }
}

/* --- data loading --- */
async function loadPage() {
  const query = new URLSearchParams({ page: String(state.page), page_size: String(PAGE_SIZE) });
  let resp;
  try {
    resp = await fetch(`/api/products?${query.toString()}`);
  } catch {
    showError("Impossible de contacter le serveur.");
    return;
  }
  if (!resp.ok) {
    showError(await extractError(resp, "Erreur lors du chargement des produits."));
    return;
  }
  clearBanner();
  let data;
  try {
    data = await resp.json();
  } catch {
    showError("Réponse du serveur invalide.");
    return;
  }
  renderTable(data.items);
  renderPagination(data);
}

/* Re-loads the list after a mutation; steps back a page if it is empty. */
async function refreshAfterMutation() {
  await loadPage();
  if (tbody.children.length === 0 && state.page > 1) {
    state.page -= 1;
    await loadPage();
  }
}

/* --- form (add + edit) --- */
function openForm(product) {
  state.editingId = product ? product.id : null;
  formTitle.textContent = product ? "Modifier le produit" : "Ajouter un produit";
  form.reset();
  const els = form.elements;
  if (product) {
    els["name"].value = product.name ?? "";
    els["description"].value = product.description ?? "";
    els["category"].value = product.category?.name ?? "";
    els["brand"].value = product.brand?.name ?? "";
    for (const field of NUMBER_FIELDS) {
      els[field].value = String(product[field]);
    }
  } else {
    els["stock"].value = "0";
    els["rating"].value = "0";
    els["units_sold"].value = "0";
  }
  formError.hidden = true;
  formPanel.hidden = false;
  els["name"].focus();
}

function closeForm() {
  formPanel.hidden = true;
  formError.hidden = true;
  state.editingId = null;
}

function buildPayload() {
  const els = form.elements;
  return {
    name: els["name"].value,
    description: els["description"].value,
    category: els["category"].value,
    brand: els["brand"].value,
    price: Number(els["price"].value),
    stock: Number(els["stock"].value),
    rating: Number(els["rating"].value),
    units_sold: Number(els["units_sold"].value),
  };
}

function showFormError(message) {
  formError.textContent = message;
  formError.hidden = false;
}

async function submitForm(event) {
  event.preventDefault();
  const payload = buildPayload();
  const method = state.editingId ? "PUT" : "POST";
  const url = state.editingId
    ? `/api/products/${encodeURIComponent(state.editingId)}`
    : "/api/products";
  let resp;
  try {
    resp = await fetch(url, {
      method: method,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  } catch {
    showFormError("Impossible de contacter le serveur.");
    return;
  }
  if (!resp.ok) {
    showFormError(await extractError(resp, "Impossible d'enregistrer le produit."));
    return;
  }
  const wasAdd = state.editingId === null;
  closeForm();
  if (wasAdd) {
    state.page = 1;
  }
  await refreshAfterMutation();
}

/* --- delete --- */
async function removeProduct(product) {
  if (!window.confirm(`Supprimer « ${product.name} » ?`)) {
    return;
  }
  let resp;
  try {
    resp = await fetch(`/api/products/${encodeURIComponent(product.id)}`, { method: "DELETE" });
  } catch {
    showError("Impossible de contacter le serveur.");
    return;
  }
  if (!resp.ok) {
    showError(await extractError(resp, "Impossible de supprimer le produit."));
    return;
  }
  await refreshAfterMutation();
}

/* --- events --- */
btnAdd.addEventListener("click", () => openForm(null));
btnCancel.addEventListener("click", closeForm);
form.addEventListener("submit", submitForm);
btnBannerClose.addEventListener("click", clearBanner);
btnPrev.addEventListener("click", () => {
  if (state.page > 1) {
    state.page -= 1;
    loadPage();
  }
});
btnNext.addEventListener("click", () => {
  if (state.page < state.totalPages) {
    state.page += 1;
    loadPage();
  }
});

loadSuggestions();
loadPage();
