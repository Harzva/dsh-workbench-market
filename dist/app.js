"use strict";

const form = document.querySelector("#filters");
const query = document.querySelector("#query");
const category = document.querySelector("#category");
const source = document.querySelector("#source");
const results = document.querySelector("#results");
const status = document.querySelector("#result-status");
const empty = document.querySelector("#empty");
const template = document.querySelector("#listing");
const date = document.querySelector("#date");
const labels = {
  official: "Dataelem 市场",
  registered: "Dataelem · 注册已核",
  manifest: "Dataelem · 清单候选",
  web: "DSH Web · 已核",
  "deepseek-desktop": "DeepSeek 官方桌面 · 已核",
};
const order = {registered: 0, web: 1, "deepseek-desktop": 2, official: 3, manifest: 4};

function renderListing(item) {
  const node = template.content.cloneNode(true);
  node.querySelector("li").dataset.kind = item.source;
  const title = node.querySelector("[data-title]");
  title.textContent = item.name;
  title.href = item.href;
  const description = node.querySelector("[data-description]");
  description.textContent = item.description;
  description.hidden = !item.description;
  node.querySelector("[data-repo]").textContent = item.repo;
  node.querySelector("[data-source]").textContent = labels[item.source];
  node.querySelector("[data-category]").textContent = item.category;
  node.querySelector("[data-version]").textContent = item.version;
  for (const field of ["manifest", "registration", "workflow"]) {
    const link = node.querySelector(`[data-${field}]`);
    link.hidden = !item[field];
    if (item[field]) link.href = item[field];
  }
  return node;
}

function normalize(value) {
  return value.normalize("NFKC").toLowerCase();
}

function render(entries) {
  const terms = normalize(query.value.trim()).split(/\s+/).filter(Boolean);
  const filtered = entries.filter(item =>
    (!source.value || item.source === source.value) &&
    (!category.value || item.category === category.value) &&
    terms.every(term => item.searchable.includes(term))
  );
  const list = document.createDocumentFragment();
  for (const item of filtered) list.append(renderListing(item));
  results.replaceChildren(list);
  status.textContent = `${filtered.length} / ${entries.length} 个工作台`;
  empty.hidden = filtered.length > 0;
}

const catalog = window.workbenchCatalog;
if (catalog?.entries?.length) {
  const entries = catalog.entries.map(item => ({
    ...item,
    searchable: normalize([
      item.repo, item.name, item.nameEn, item.package, item.category, item.description, labels[item.source],
    ].filter(Boolean).join(" ")),
  })).sort((a, b) => order[a.source] - order[b.source] || a.name.localeCompare(b.name, "zh-CN"));
  for (const name of [...new Set(entries.map(item => item.category))].sort((a, b) => a.localeCompare(b, "zh-CN"))) {
    category.add(new Option(name, name));
  }
  date.dateTime = catalog.checkedAt;
  date.textContent = catalog.checkedAt;
  const refresh = () => render(entries);
  form.addEventListener("submit", event => {
    event.preventDefault();
    refresh();
  });
  query.addEventListener("input", event => {
    if (!event.isComposing) refresh();
  });
  query.addEventListener("compositionend", refresh);
  category.addEventListener("change", refresh);
  source.addEventListener("change", refresh);
  form.addEventListener("reset", () => requestAnimationFrame(() => {
    refresh();
    query.focus();
  }));
  refresh();
} else {
  status.textContent = "目录数据未加载。请刷新页面。";
  form.querySelectorAll("input, select, button").forEach(control => { control.disabled = true; });
}
