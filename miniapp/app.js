const tg = window.Telegram?.WebApp;
const demoData = window.AssistantDemoData;

let state = clone(demoData);
let demoMode = true;
let activeView = "home";
let previousView = "home";
let transactionFilter = "all";
let periodFilter = "today";
let showAllActiveReminders = false;
let showAllCompletedReminders = false;
let showAllTransactions = false;
let cardWheelScrollHandler = null;
let cardWheelRaf = 0;
const FINANCE_ARCHIVED = true;

const TRANSACTIONS_COLLAPSED_LIMIT = 6;

function clone(value) {
  return JSON.parse(JSON.stringify(value ?? {}));
}

function $(id) {
  return document.getElementById(id);
}

function safeNumber(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : 0;
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function formatDateTime(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat("uz-UZ", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function toDatetimeLocal(value) {
  const date = value ? new Date(value) : new Date();
  if (Number.isNaN(date.getTime())) return "";
  const shifted = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
  return shifted.toISOString().slice(0, 16);
}

function fromDatetimeLocal(value) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? new Date().toISOString() : date.toISOString();
}

function formatTimeLeft(value) {
  if (!value) return "";
  const target = new Date(value);
  const diff = target.getTime() - Date.now();
  if (Number.isNaN(target.getTime()) || diff <= 0) return "vaqti kirdi";
  const totalMinutes = Math.ceil(diff / 60000);
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  return hours > 0 ? `${hours} soat ${minutes} daqiqa qoldi` : `${minutes} daqiqa qoldi`;
}

function monthName(value = new Date()) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const text = new Intl.DateTimeFormat("uz-UZ", { month: "long", year: "numeric" }).format(date);
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function normalizeUsernameInput(value) {
  const username = String(value || "")
    .trim()
    .replace(/^https:\/\/t\.me\//i, "")
    .replace(/^t\.me\//i, "")
    .replace(/^@?/, "");
  if (!/^[A-Za-z0-9_]{5,32}$/.test(username)) return "";
  return `@${username}`;
}

function showToast(text) {
  const toast = $("toast");
  if (!toast) return;
  toast.textContent = text;
  toast.classList.add("show");
  window.setTimeout(() => toast.classList.remove("show"), 2400);
}

function setAuthNotice(visible, text = "Real ma'lumotlar faqat bot ichidagi Mini App tugmasida ko'rinadi.") {
  const notice = $("authNotice");
  if (!notice) return;
  const noticeText = $("authNoticeText");
  if (noticeText) noticeText.textContent = text;
  notice.hidden = !visible;
}

function telegramHeaders() {
  return tg?.initData ? { "X-Telegram-Init-Data": tg.initData } : {};
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...telegramHeaders(),
      ...(options.headers || {}),
    },
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(`${response.status}: ${text}`);
  }
  return response.json();
}

function dashboardErrorMessage(error) {
  const message = String(error?.message || error);
  if (message.startsWith("401:")) {
    return "Mini App sessiyasi topilmadi. Bot ichidagi Mini App tugmasidan qayta oching.";
  }
  if (message.startsWith("403:")) {
    return "Bu Telegram ID uchun Mini App ruxsati yo'q yoki bloklangan.";
  }
  if (message.startsWith("500:")) {
    return "Server xatosi tuzatilmoqda. Bir necha soniyadan keyin yangilang.";
  }
  return "Mini App ma'lumot yuklay olmadi";
}

async function loadDashboard() {
  const refresh = $("refreshButton");
  refresh?.classList.add("spin");
  try {
    state = await api("/api/dashboard");
    demoMode = false;
    setAuthNotice(false);
  } catch (error) {
    console.warn(error);
    state = clone(demoData);
    demoMode = true;
    const message = dashboardErrorMessage(error);
    setAuthNotice(true, message);
    showToast(message);
  } finally {
    window.setTimeout(() => refresh?.classList.remove("spin"), 380);
  }
  render();
}

function setView(view) {
  if (!view) return;
  if (FINANCE_ARCHIVED && ["finance", "cards"].includes(view)) {
    view = "home";
  }
  if (view === "admin" && !state.is_admin) {
    view = "home";
  }
  if (activeView !== view) previousView = activeView;
  activeView = view;
  document.body.dataset.activeView = view;
  document.querySelectorAll(".view").forEach((panel) => {
    panel.classList.toggle("active", panel.dataset.view === view);
  });
  document.querySelectorAll(".nav-item").forEach((button) => {
    button.classList.toggle("active", button.dataset.viewTarget === view);
  });
  if (view === "cards") {
    requestAnimationFrame(() => initCardWheel());
  } else {
    teardownCardWheel();
  }
  if (view !== "home") {
    window.scrollTo({ top: 0, behavior: "auto" });
  }
  updateMiniHeaderVisibility();
  if (window.lucide) lucide.createIcons();
}

function setTransactionFilter(filter = "all") {
  transactionFilter = ["income", "expense"].includes(filter) ? filter : "all";
  showAllTransactions = false;
  document.querySelectorAll("[data-transaction-filter]:not(.quick-card)").forEach((button) => {
    button.classList.toggle("active-filter", button.dataset.transactionFilter === transactionFilter);
  });
  document.querySelectorAll(".segment[data-transaction-filter]").forEach((button) => {
    button.classList.toggle("active", button.dataset.transactionFilter === transactionFilter);
  });
  renderTransactions();
  if (window.lucide) lucide.createIcons();
}

function setPeriodFilter(filter = "today") {
  periodFilter = ["today", "week", "month"].includes(filter) ? filter : "today";
  document.querySelectorAll("[data-period-filter]").forEach((button) => {
    button.classList.toggle("active", button.dataset.periodFilter === periodFilter);
  });
  renderFinance();
  if (window.lucide) lucide.createIcons();
}

function currentPeriodData() {
  return state[periodFilter] || state.today || state.month || demoData.today;
}

function periodLabel() {
  const labels = {
    today: "Bugun",
    week: "Hafta",
    month: monthName(state.generated_at),
  };
  return labels[periodFilter] || labels.today;
}

function transactionInPeriod(item) {
  if (!item?.occurred_at) return true;
  const date = new Date(item.occurred_at);
  if (Number.isNaN(date.getTime())) return true;
  const now = new Date(state.generated_at || Date.now());
  const start = new Date(now);
  if (periodFilter === "today") {
    start.setHours(0, 0, 0, 0);
  } else if (periodFilter === "week") {
    const day = (start.getDay() + 6) % 7;
    start.setDate(start.getDate() - day);
    start.setHours(0, 0, 0, 0);
  } else {
    start.setDate(1);
    start.setHours(0, 0, 0, 0);
  }
  return date >= start && date <= now;
}

function applyTheme(mode) {
  const nextMode = mode === "light" ? "light" : "dark";
  document.body.classList.toggle("light", nextMode === "light");
  localStorage.setItem("assistant_theme", nextMode);
  const label = $("themeModeLabel");
  if (label) label.textContent = nextMode === "light" ? "Kunduzgi rejim" : "Tun rejimi";
  if (tg?.setHeaderColor) {
    tg.setHeaderColor(nextMode === "light" ? "#131c30" : "#07080c");
  }
  if (tg?.setBackgroundColor) {
    tg.setBackgroundColor(nextMode === "light" ? "#131c30" : "#07080c");
  }
}

function renderHero() {
  const balances = state.balances || [];
  $("heroBalance").textContent = state.balance_total_text || "0 UZS";
  $("heroMeta").textContent = `${balances.length} ta karta · ${formatDateTime(state.generated_at)}`;
  $("generatedAt").textContent = `Yangilandi: ${formatDateTime(state.generated_at)}`;
  $("homeIncome").textContent = state.month?.income_text || "0 UZS";
  $("homeExpense").textContent = state.month?.expense_text || "0 UZS";
  renderHeroAvatar();
  renderMiniHeader();
}

function renderHeroAvatar() {
  const button = $("heroAvatarButton");
  if (!button) return;
  const user = tg?.initDataUnsafe?.user || state.current_user || {};
  const fullName = [user.first_name, user.last_name].filter(Boolean).join(" ") || "Foydalanuvchi";
  const letter = (fullName.trim().charAt(0) || "F").toUpperCase();

  // Show the user's display name (first + last from Telegram), not the
  // @handle. The user explicitly asked for the nick name, not the username.
  const usernameEl = $("heroUsername");
  if (usernameEl) {
    usernameEl.textContent = fullName;
  }
  button.textContent = "";
  if (user.photo_url) {
    const img = document.createElement("img");
    img.alt = "";
    img.referrerPolicy = "no-referrer";
    img.addEventListener("error", () => {
      const span = document.createElement("span");
      span.className = "hero-avatar-letter";
      span.textContent = letter;
      button.textContent = "";
      button.append(span);
    });
    img.src = user.photo_url;
    button.append(img);
  } else {
    const span = document.createElement("span");
    span.className = "hero-avatar-letter";
    span.textContent = letter;
    button.append(span);
  }
}

function renderMiniHeader() {
  const user = tg?.initDataUnsafe?.user || state.current_user || {};
  const fullName = [user.first_name, user.last_name, user.name].filter(Boolean).join(" ") || "Assistant";
  $("miniTitle").textContent = activeView === "extras" ? "Qo'shimcha" : fullName;
  $("miniSubtitle").textContent = activeView === "extras"
    ? (state.prayer?.city || "Namoz nazorati")
    : "Assistant faol";
  const miniAvatar = $("miniAvatarButton");
  if (!miniAvatar) return;
  const letter = (fullName.trim().charAt(0) || "A").toUpperCase();
  miniAvatar.textContent = "";
  if (user.photo_url) {
    const img = document.createElement("img");
    img.alt = "";
    img.referrerPolicy = "no-referrer";
    img.src = user.photo_url;
    img.addEventListener("error", () => {
      miniAvatar.textContent = "";
      const span = document.createElement("span");
      span.textContent = letter;
      miniAvatar.append(span);
    });
    miniAvatar.append(img);
  } else {
    const span = document.createElement("span");
    span.textContent = letter;
    miniAvatar.append(span);
  }
}

function renderOverview() {
  const next = state.prayer?.next;
  $("nextPrayerName").textContent = next ? `${next.name} ${next.time}` : "Bomdod vaqti topilmadi";
  const timeLeft = next?.iso ? `${formatTimeLeft(next.iso)} · ` : "";
  const dayLabel = next?.day_label ? `${next.day_label} · ` : "";
  $("nextPrayerMeta").textContent = `${dayLabel}${timeLeft}${state.prayer?.city || "Toshkent"} · eslatma ${state.prayer?.enabled ? "yoqilgan" : "o'chirilgan"}`;
  const reminderListLen = (state.active_reminders || state.reminders || []).length;
  $("reminderCount").textContent = `${reminderListLen} ta`;
  renderHomeReminders();
  renderRecentTransactions();
}

function renderHomeReminders() {
  const reminders = $("reminderList");
  const list = state.active_reminders?.length ? state.active_reminders : state.reminders || [];
  reminders.innerHTML = "";
  if (!list.length) {
    reminders.innerHTML = `<div class="empty">Faol eslatmalar yo'q. Telegramga "ertaga 10:00 dori ichish" deb yozing.</div>`;
    return;
  }
  list.slice(0, 4).forEach((item, index) => {
    reminders.insertAdjacentHTML("beforeend", reminderItemHtml(item, index, false));
  });
}

function transactionItemHtml(item, index, manageable = false) {
  const type = item.type === "income" ? "income" : "expense";
  const prefix = type === "income" ? "+" : "−";
  const icon = type === "income" ? "arrow-down-left" : "arrow-up-right";
  const card = item.card_last4 ? ` · *${escapeHtml(item.card_last4)}` : "";
  const actions = manageable
    ? `<div class="item-actions">
        <button class="icon-button small" data-edit-transaction="${item.id}" type="button" aria-label="Tahrirlash">
          <i data-lucide="pencil"></i>
        </button>
        <button class="icon-button danger small" data-delete-transaction="${item.id}" type="button" aria-label="O'chirish">
          <i data-lucide="trash-2"></i>
        </button>
      </div>`
    : "";
  const openAttr = manageable ? "" : ' data-open-finance-transactions="1"';
  return `<article class="list-item transaction-row ${manageable ? "managed" : "clickable"}"${openAttr} style="animation-delay:${index * 28}ms">
    <div class="item-icon ${type}"><i data-lucide="${icon}"></i></div>
    <div>
      <div class="item-title">${escapeHtml(item.description || item.category || "Operatsiya")}</div>
      <div class="item-meta">${escapeHtml(item.category || "Boshqa")} · ${formatDateTime(item.occurred_at)}${card}</div>
    </div>
    <div class="amount ${type}">${prefix}${escapeHtml(item.amount_text || "0")}</div>
    ${actions}
  </article>`;
}

function renderRecentTransactions() {
  const recent = $("recentTransactions");
  const list = state.recent_transactions || [];
  recent.innerHTML = "";
  if (!list.length) {
    recent.innerHTML = `<div class="empty">Hali kirim yoki xarajat yo'q. Bank xabarini botga yuboring.</div>`;
    return;
  }
  list.slice(0, 5).forEach((item, index) => {
    recent.insertAdjacentHTML("beforeend", transactionItemHtml(item, index));
  });
}

function renderFinance() {
  document.querySelectorAll("[data-period-filter]").forEach((button) => {
    button.classList.toggle("active", button.dataset.periodFilter === periodFilter);
  });
  const data = currentPeriodData();
  const label = periodLabel();
  $("reportPeriod").textContent = label;
  $("monthLabel").textContent = label;
  $("reportIncome").textContent = data.income_text || "0 so'm";
  $("reportExpense").textContent = data.expense_text || "0 so'm";
  $("reportNet").textContent = data.net_text || "0 so'm";
  renderFinanceShortcut();

  const dailyLimit = safeNumber(state.settings?.daily_expense_limit);
  $("dailyLimitInput").value = dailyLimit > 0 ? String(dailyLimit) : "";
  $("dailyLimitNote").textContent = dailyLimit > 0
    ? `Bugungi limit: ${state.settings.daily_expense_limit_text}. Sarflangan: ${state.today?.expense_text || "0 so'm"}`
    : "Kunlik limit belgilanmagan.";

  const reportButton = $("dailyReportToggleButton");
  reportButton.classList.toggle("active", Boolean(state.settings?.daily_report_enabled));
  reportButton.querySelector("span").textContent =
    state.settings?.daily_report_enabled ? "Kunlik hisobot yoqilgan" : "Kunlik hisobot o'chirilgan";

  renderTransactions();
  renderCategories();
  renderCategoryLimits();
  renderSavings();
  renderSignals();
}

function renderFinanceShortcut() {
  const balance = $("financeShortBalance");
  if (!balance) return;
  const balances = state.balances || [];
  balance.textContent = state.balance_total_text || "0 so'm";
  const updated = balances
    .map((item) => item.updated_at)
    .filter(Boolean)
    .sort()
    .at(-1);
  $("financeShortMeta").textContent = `${balances.length} ta karta${updated ? ` · ${formatDateTime(updated)}` : ""}`;
}

function renderTransactions() {
  const labelMap = { all: "Barcha operatsiyalar", income: "Kirimlar", expense: "Chiqimlar" };
  $("transactionFilterLabel").textContent = labelMap[transactionFilter] || labelMap.all;

  const list = $("transactionList");
  const expandRow = $("transactionExpandRow");
  const expandButton = $("transactionExpandButton");
  const expandLabel = $("transactionExpandLabel");

  const rows = (state.transactions || []).filter(
    (item) => transactionInPeriod(item) && (transactionFilter === "all" || item.type === transactionFilter),
  );

  list.innerHTML = "";
  if (!rows.length) {
    list.innerHTML = `<div class="empty">${labelMap[transactionFilter]} hali yo'q.</div>`;
    expandRow.hidden = true;
    return;
  }

  const visibleRows = showAllTransactions ? rows : rows.slice(0, TRANSACTIONS_COLLAPSED_LIMIT);
  visibleRows.forEach((item, index) => {
    list.insertAdjacentHTML("beforeend", transactionItemHtml(item, index, true));
  });

  if (rows.length > TRANSACTIONS_COLLAPSED_LIMIT) {
    expandRow.hidden = false;
    expandButton.classList.toggle("is-open", showAllTransactions);
    expandLabel.textContent = showAllTransactions
      ? "Yopish"
      : `Kengaytirish · yana ${rows.length - TRANSACTIONS_COLLAPSED_LIMIT} ta`;
  } else {
    expandRow.hidden = true;
  }
}

function renderCategories() {
  const categories = $("categoryList");
  categories.innerHTML = "";
  const list = state.categories || [];
  const max = Math.max(1, ...list.map((item) => safeNumber(item.amount)));
  if (!list.length) {
    categories.innerHTML = `<div class="empty">Kategoriyalar hali yo'q. Xarajatlar kelganda shu yerda ajraladi.</div>`;
    return;
  }
  list.forEach((item, index) => {
    const width = Math.max(8, Math.round((safeNumber(item.amount) / max) * 100));
    categories.insertAdjacentHTML(
      "beforeend",
      `<article class="category-row" style="animation-delay:${index * 28}ms">
        <div>
          <div class="item-title">${escapeHtml(item.name)}</div>
          <div class="item-meta">${escapeHtml(item.amount_text || "")}</div>
        </div>
        <div class="bar"><span style="width:${width}%"></span></div>
      </article>`,
    );
  });
}

function renderCategoryLimits() {
  const limits = state.category_limits || [];
  $("categoryLimitSummary").textContent = `${limits.length} ta`;
  const list = $("categoryLimitList");
  list.innerHTML = "";
  if (!limits.length) {
    list.innerHTML = `<div class="empty">Kategoriya limiti yo'q. Masalan, Ovqat uchun oylik limit belgilang.</div>`;
    return;
  }
  limits.forEach((item, index) => {
    list.insertAdjacentHTML(
      "beforeend",
      `<article class="list-item compact" style="animation-delay:${index * 28}ms">
        <div class="item-icon"><i data-lucide="gauge"></i></div>
        <div>
          <div class="item-title">${escapeHtml(item.category)}</div>
          <div class="item-meta">Oylik limit: ${escapeHtml(item.amount_text || "")}</div>
        </div>
        <button class="icon-button danger small" data-delete-category-limit="${escapeHtml(item.category)}" type="button" aria-label="Limitni o'chirish">
          <i data-lucide="trash-2"></i>
        </button>
      </article>`,
    );
  });
}

function renderSavings() {
  const income = safeNumber(state.month?.income);
  const expense = safeNumber(state.month?.expense);
  const net = income - expense;
  const percent = income > 0 ? Math.max(0, Math.min(100, Math.round((Math.max(net, 0) / income) * 100))) : 0;
  $("savingNet").textContent = state.month?.net_text || "0 so'm";
  $("savingRing").textContent = `${percent}%`;
  $("savingRing").style.setProperty("--saving", percent);
  $("savingProgress").style.width = `${percent}%`;
  $("savingHint").textContent =
    net >= 0
      ? "Bu oy kirim chiqimdan yuqori. Farqni alohida jamg'arma sifatida ajratib borish mumkin."
      : "Bu oy chiqim kirimdan yuqori. Quyidagi kategoriyalarni tekshirib chiqing.";
}

function renderBalances() {
  const balances = state.balances || [];
  const list = $("balanceList");
  if (!list) return;
  list.innerHTML = "";
  if (!balances.length) {
    list.innerHTML = `<div class="empty">Balanslar hali yo'q. UZCARD/HUMO xabarini botga yuboring.</div>`;
    return;
  }
  balances.forEach((item) => {
    list.insertAdjacentHTML(
      "beforeend",
      `<article class="balance-card">
        <span>${escapeHtml(item.label || "Karta")}</span>
        <strong>${escapeHtml(item.amount_text || "0")}</strong>
        <small>Yangilangan: ${formatDateTime(item.updated_at)}</small>
      </article>`,
    );
  });
}

function renderSignals() {
  const box = $("financeSignals");
  const income = safeNumber(state.month?.income);
  const expense = safeNumber(state.month?.expense);
  const todayExpense = safeNumber(state.today?.expense);
  const dailyLimit = safeNumber(state.settings?.daily_expense_limit);
  const cards = (state.balances || []).length;
  const signals = [];

  if (cards === 0) signals.push(["wallet-cards", "Karta balansi yo'q", "Bank botidan kelgan balans xabarini yuboring."]);
  if (dailyLimit > 0 && todayExpense >= dailyLimit) {
    signals.push(["shield-alert", "Kunlik limit oshdi", `Bugun ${state.today?.expense_text || ""} sarflandi. Limit: ${state.settings.daily_expense_limit_text}.`]);
  } else if (dailyLimit > 0 && todayExpense >= dailyLimit * 0.8) {
    signals.push(["bell-ring", "Limitga yaqin", `Bugungi xarajat limitning katta qismiga yetdi: ${state.today?.expense_text || ""}.`]);
  }
  (state.finance_warnings || []).forEach((item) => {
    signals.push([item.icon || "bell-ring", item.title || "Kategoriya limiti", item.text || "Limitga yaqin."]);
  });
  if (expense > income && income > 0) signals.push(["triangle-alert", "Chiqim yuqori", "Bu oy xarajat kirimdan oshgan."]);
  if (expense === 0) signals.push(["sparkles", "Xarajat yo'q", "Xabarlar kelishi bilan avtomatik tahlil boshlanadi."]);
  if (income > expense && expense > 0) signals.push(["badge-check", "Holat yaxshi", "Kirim chiqimdan yuqori, jamg'arma uchun imkon bor."]);
  if (!signals.length) signals.push(["badge-check", "Boshlashga tayyor", "Bank xabarlari kelishi bilan signal paydo bo'ladi."]);

  box.innerHTML = signals
    .map(
      ([icon, title, text], index) => `<article class="list-item" style="animation-delay:${index * 28}ms">
        <div class="item-icon"><i data-lucide="${icon}"></i></div>
        <div>
          <div class="item-title">${escapeHtml(title)}</div>
          <div class="item-meta">${escapeHtml(text)}</div>
        </div>
        <i data-lucide="chevron-right"></i>
      </article>`,
    )
    .join("");
}

/* ──────────────────────────────────────────────────────────
   Cards drum carousel
   ────────────────────────────────────────────────────────── */

function cardGradientFor(seed) {
  const palette = ["a", "b", "c", "d", "e"];
  const hash = String(seed)
    .split("")
    .reduce((acc, char) => (acc * 31 + char.charCodeAt(0)) >>> 0, 7);
  return `var(--grad-card-${palette[hash % palette.length]})`;
}

function bankCardHtml(item, index) {
  const label = item.label || "Karta";
  const last4 = (item.card_last4 || extractLast4(label) || "••••").slice(-4);
  const brand = detectBrand(label);
  const amount = item.amount_text || "0";
  const updated = formatDateTime(item.updated_at) || "—";
  const gradient = cardGradientFor(`${label}-${last4}-${index}`);
  return `<article class="bank-card" style="--card-bg:${gradient}" data-card-index="${index}">
    <div class="bank-card-row">
      <span class="bank-card-chip" aria-hidden="true"></span>
      <div class="bank-card-info">
        <span class="bank-card-brand">${escapeHtml(brand)}</span>
        <span class="bank-card-label">${escapeHtml(label)}</span>
      </div>
      <button class="icon-button small card-menu-button" data-card-menu="${escapeHtml(last4)}" type="button" aria-label="Karta menyusi" aria-expanded="false">
        <i data-lucide="ellipsis-vertical"></i>
      </button>
      <div class="bank-card-balance">
        <span>Balans</span>
        <strong>${escapeHtml(amount)}</strong>
      </div>
    </div>
    <div class="bank-card-row foot">
      <span class="bank-card-number">•••• ${escapeHtml(last4)}</span>
      <span class="bank-card-meta">${escapeHtml(updated)}</span>
    </div>
  </article>`;
}

function extractLast4(label) {
  const match = String(label || "").match(/(\d{4})(?!.*\d)/);
  return match ? match[1] : "";
}

function detectBrand(label) {
  const text = String(label || "").toUpperCase();
  if (text.includes("VISA")) return "VISA";
  if (text.includes("MASTER")) return "Mastercard";
  if (text.includes("HUMO")) return "HUMO";
  if (text.includes("UZCARD")) return "UZCARD";
  return "Karta";
}

function renderCardWheel() {
  const balances = state.balances || [];
  const list = $("cardWheelList");
  const count = $("cardsCount");
  const total = $("cardsTotal");
  const hint = $("cardWheelHint");
  if (!list) return;

  total.textContent = state.balance_total_text || "0 UZS";
  count.textContent = `${balances.length} ta`;

  if (!balances.length) {
    list.innerHTML = `<div class="cards-empty">Hali karta balansi yo'q.<br/>UZCARD/HUMO botidagi xabarni assistant botga yuboring.</div>`;
    if (hint) hint.hidden = true;
    return;
  }

  if (hint) hint.hidden = balances.length <= 1;
  list.innerHTML = balances.map((item, index) => bankCardHtml(item, index)).join("");
}

function teardownCardWheel() {
  const wheel = $("cardWheel");
  if (wheel && cardWheelScrollHandler) {
    wheel.removeEventListener("scroll", cardWheelScrollHandler);
    cardWheelScrollHandler = null;
  }
  if (cardWheelRaf) {
    cancelAnimationFrame(cardWheelRaf);
    cardWheelRaf = 0;
  }
}

function applyCardWheelTransforms() {
  const wheel = $("cardWheel");
  if (!wheel) return;
  const cards = wheel.querySelectorAll(".bank-card");
  if (!cards.length) return;
  cards.forEach((card) => {
    card.style.transform = "";
    card.style.opacity = "";
    card.style.zIndex = "";
    card.style.filter = "";


    // Gentler curve so the cards directly above and below the centre stay
    // clearly visible — the user wants the deck behind to peek through.
  });
}

function initCardWheel() {
  renderCardWheel();
  if (window.lucide) lucide.createIcons();

  const wheel = $("cardWheel");
  if (!wheel) return;
  teardownCardWheel();

  applyCardWheelTransforms();
}

/* ──────────────────────────────────────────────────────────
   Reminders & extras
   ────────────────────────────────────────────────────────── */

function reminderItemHtml(item, index, removable) {
  const statusText = item.status === "sent" ? "Yakunlangan" : item.status === "cancelled" ? "O'chirilgan" : "Aktiv";
  const dateText = item.status === "sent" && item.sent_at ? formatDateTime(item.sent_at) : formatDateTime(item.due_at);
  const repeatText = item.repeat_label ? ` · ${escapeHtml(item.repeat_label)}` : "";
  const action = removable
    ? `<div class="item-actions">
      <button class="icon-button small" data-edit-reminder="${item.id}" type="button" aria-label="Tahrirlash">
        <i data-lucide="pencil"></i>
      </button>
      <button class="icon-button danger small" data-delete-reminder="${item.id}" type="button" aria-label="O'chirish">
        <i data-lucide="trash-2"></i>
      </button>`
    + `</div>`
    : `<i data-lucide="chevron-right"></i>`;
  return `<article class="list-item" style="animation-delay:${index * 28}ms">
    <div class="item-icon"><i data-lucide="${item.status === "pending" ? "bell-ring" : "check-check"}"></i></div>
    <div>
      <div class="item-title">${escapeHtml(item.text)}</div>
      <div class="item-meta">${statusText} · ${dateText}${repeatText}</div>
    </div>
    ${action}
  </article>`;
}

function renderExtras() {
  const active = state.active_reminders || [];
  const completed = state.completed_reminders || [];
  $("activeReminderCount").textContent = active.length > 4 && !showAllActiveReminders ? `Yana ${active.length - 4} ta` : `${active.length} ta`;
  $("completedReminderCount").textContent = completed.length > 3 && !showAllCompletedReminders ? "Barchasi" : `${completed.length} ta`;

  const activeList = $("activeReminderList");
  activeList.innerHTML = "";
  if (!active.length) {
    activeList.innerHTML = `<div class="empty">Aktiv eslatma yo'q. Telegramga "1 soatdan keyin ..." deb yozing.</div>`;
  } else {
    const visibleActive = showAllActiveReminders ? active : active.slice(0, 4);
    visibleActive.forEach((item, index) => activeList.insertAdjacentHTML("beforeend", reminderItemHtml(item, index, true)));
  }

  const completedList = $("completedReminderList");
  completedList.innerHTML = "";
  if (!completed.length) {
    completedList.innerHTML = `<div class="empty">Yakunlangan eslatmalar tarixi hali bo'sh.</div>`;
  } else {
    const visible = showAllCompletedReminders ? completed : completed.slice(0, 3);
    visible.forEach((item, index) => completedList.insertAdjacentHTML("beforeend", reminderItemHtml(item, index, false)));
  }

  renderPrayer();
}

function renderProfile() {
  const user = tg?.initDataUnsafe?.user || state.current_user || {};
  const fullName = [user.first_name, user.last_name].filter(Boolean).join(" ") || "Foydalanuvchi";
  $("profileName").textContent = fullName;

  const avatar = $("profileAvatar");
  if (avatar) {
    const photo = user.photo_url;
    const letter = (fullName.trim().charAt(0) || "F").toUpperCase();
    avatar.textContent = "";
    if (photo) {
      const img = document.createElement("img");
      img.alt = "";
      img.referrerPolicy = "no-referrer";
      img.src = photo;
      img.addEventListener("error", () => {
        avatar.textContent = letter;
      });
      avatar.append(img);
    } else {
      avatar.textContent = letter;
    }
  }

  $("profileStatus").textContent = demoMode ? "Telegram orqali oching" : "Assistant faol";
  $("profileUsername").textContent = user.username ? `@${user.username}` : "Ko'rsatilmagan";
  $("profileId").textContent = user.id ? String(user.id) : "Telegramda oching";
  $("profilePhone").textContent = user.phone_number || "Botga berilmagan";
  $("profileLanguage").textContent = user.language_code || "uz";
  $("botStatus").textContent = demoMode ? "Telegram orqali oching" : "Online";
  $("connectionStatus").textContent = demoMode ? "Demo ma'lumot" : "Himoyalangan";
}

function renderAdminVisibility() {
  document.querySelectorAll("[data-admin-only]").forEach((element) => {
    element.hidden = !state.is_admin;
  });
  if (!state.is_admin && activeView === "admin") {
    setView("home");
  }
}

function userStatusBadges(item) {
  const badges = [];
  if (item.admin) badges.push(`<span class="status-pill admin">Admin</span>`);
  if (item.allowed) badges.push(`<span class="status-pill allowed">Ruxsat</span>`);
  if (item.blocked) badges.push(`<span class="status-pill blocked">Blok</span>`);
  if (!badges.length) badges.push(`<span class="status-pill">Noma'lum</span>`);
  return badges.join("");
}

function adminUserHtml(item, index) {
  const username = item.username_text || (item.username ? `@${item.username}` : "Ko'rsatilmagan");
  const updated = item.updated_at_text ? formatDateTime(item.updated_at_text) : "Hali ko'rinmagan";
  const avatar = item.photo_url
    ? `<img src="${escapeHtml(item.photo_url)}" alt="" referrerpolicy="no-referrer" />`
    : escapeHtml(item.name || "U").charAt(0).toUpperCase();
  const action = item.admin
    ? `<button class="ghost-action" disabled type="button"><i data-lucide="shield-check"></i><span>Admin</span></button>`
    : item.blocked
      ? `<button class="ghost-action" data-admin-unblock="${item.user_id}" type="button"><i data-lucide="unlock"></i><span>Blokdan chiqarish</span></button>`
      : `<button class="ghost-action danger" data-admin-block="${item.user_id}" type="button"><i data-lucide="ban"></i><span>Bloklash</span></button>`;
  return `<article class="admin-user-card" style="animation-delay:${index * 28}ms">
    <div class="admin-user-head">
      <div class="avatar mini">${avatar}</div>
      <div>
        <div class="item-title">${escapeHtml(item.name || `User ${item.user_id}`)}</div>
        <div class="item-meta">${escapeHtml(username)} · ID ${escapeHtml(item.user_id)}</div>
      </div>
      <div class="status-row">${userStatusBadges(item)}</div>
    </div>
    <div class="admin-user-grid">
      <div><span>Telefon</span><strong>${escapeHtml(item.phone_number || "Berilmagan")}</strong></div>
      <div><span>Nickname</span><strong>${escapeHtml(item.first_name || item.name || "-")}</strong></div>
      <div><span>Operatsiya</span><strong>${escapeHtml(item.transactions || 0)}</strong></div>
      <div><span>Yangilangan</span><strong>${escapeHtml(updated)}</strong></div>
    </div>
    <div class="admin-actions">${action}</div>
  </article>`;
}

function choreMemberHtml(item, index) {
  return `<article class="list-item compact" style="animation-delay:${index * 28}ms">
    <div class="item-icon"><i data-lucide="user-round"></i></div>
    <div>
      <div class="item-title">${escapeHtml(item.name)}</div>
      <div class="item-meta">Musor navbati #${index + 1} · username</div>
    </div>
    <button class="icon-button danger small" data-delete-chore-member="${item.id}" type="button" aria-label="O'chirish">
      <i data-lucide="trash-2"></i>
    </button>
  </article>`;
}

function chorePairHtml(item, index) {
  return `<article class="list-item compact" style="animation-delay:${index * 28}ms">
    <div class="item-icon"><i data-lucide="users-round"></i></div>
    <div>
      <div class="item-title">${escapeHtml(item.first_name)} bilan ${escapeHtml(item.second_name)}</div>
      <div class="item-meta">Yakshanba juftligi #${index + 1}</div>
    </div>
    <button class="icon-button danger small" data-delete-chore-pair="${item.id}" type="button" aria-label="O'chirish">
      <i data-lucide="trash-2"></i>
    </button>
  </article>`;
}

function renderChores() {
  const chores = state.admin?.chores || {};
  const members = chores.members || [];
  const pairs = chores.pairs || [];
  const nextPair = chores.next_cleaning_pair || [];
  const followingPair = chores.following_cleaning_pair || [];
  const summary = $("choreSummary");
  const schedule = $("choreScheduleText");
  const memberList = $("choreMemberList");
  const pairList = $("chorePairList");
  if (!summary || !memberList || !pairList) return;

  summary.textContent = `Bugun: ${chores.today_member || "-"} · Ertaga: ${chores.tomorrow_member || "-"}`;
  if (schedule) {
    const nextCleaning = nextPair.length === 2 ? `${nextPair[0]} + ${nextPair[1]}` : "belgilanmagan";
    const followingCleaning = followingPair.length === 2 ? ` Keyingi: ${followingPair[0]} + ${followingPair[1]}.` : "";
    schedule.textContent = `${chores.schedule_text || "Guruhda /chore_setup buyrug'i bilan yoqiladi."} Kelayotgan yakshanba: ${nextCleaning}.${followingCleaning}`;
  }

  memberList.innerHTML = "";
  if (!members.length) {
    memberList.innerHTML = `<div class="empty">Navbatchilar yo'q. @username qo'shing.</div>`;
  } else {
    members.forEach((item, index) => memberList.insertAdjacentHTML("beforeend", choreMemberHtml(item, index)));
  }

  pairList.innerHTML = "";
  if (!pairs.length) {
    pairList.innerHTML = `<div class="empty">Yakshanba juftliklari yo'q.</div>`;
  } else {
    pairs.forEach((item, index) => pairList.insertAdjacentHTML("beforeend", chorePairHtml(item, index)));
  }
}

function updateChores(chores) {
  state.admin = state.admin || {};
  state.admin.chores = chores || state.admin.chores || {};
  renderChores();
  if (window.lucide) lucide.createIcons();
}

function renderAdmin() {
  renderAdminVisibility();
  if (!state.is_admin) return;
  const users = state.admin?.users || [];
  const audits = state.admin?.audit_logs || [];
  $("adminSummary").textContent = `${state.admin?.allowed_count || 0} ruxsat · ${state.admin?.blocked_count || 0} blok`;
  const list = $("adminUserList");
  list.innerHTML = "";
  if (!users.length) {
    list.innerHTML = `<div class="empty">Hali userlar ko'rinmagan. User botga /start yoki /id yuborganda profili saqlanadi.</div>`;
  } else {
    users.forEach((item, index) => list.insertAdjacentHTML("beforeend", adminUserHtml(item, index)));
  }

  const auditList = $("adminAuditList");
  auditList.innerHTML = "";
  if (!audits.length) {
    auditList.innerHTML = `<div class="empty">Audit tarixi hali bo'sh.</div>`;
  } else {
    audits.forEach((item, index) => {
      const target = item.target_user_id ? ` → ${item.target_user_id}` : "";
      auditList.insertAdjacentHTML(
        "beforeend",
        `<article class="list-item compact" style="animation-delay:${index * 28}ms">
          <div class="item-icon"><i data-lucide="history"></i></div>
          <div>
            <div class="item-title">${escapeHtml(item.action)}${escapeHtml(target)}</div>
            <div class="item-meta">${formatDateTime(item.created_at)} · admin ${escapeHtml(item.actor_user_id)} ${item.details ? "· " + escapeHtml(item.details) : ""}</div>
          </div>
        </article>`,
      );
    });
  }
  renderChores();
}

async function reloadAdminUsers() {
  if (demoMode || !state.is_admin) {
    showToast("Admin panel Telegram ichida ishlaydi");
    return;
  }
  const payload = await api("/api/admin/users", { method: "GET" });
  state.admin = {
    users: payload.users || [],
    audit_logs: payload.audit_logs || [],
    allowed_count: payload.allowed_count || 0,
    blocked_count: payload.blocked_count || 0,
    chores: payload.chores || state.admin?.chores || {},
  };
  renderAdmin();
  if (window.lucide) lucide.createIcons();
}

function renderPrayer() {
  $("prayerCityLabel").textContent = state.prayer?.city || "Toshkent";
  $("prayerSource").textContent = state.prayer?.source || "Offline hisoblash";
  document.querySelectorAll("[data-lead-minutes]").forEach((button) => {
    button.classList.toggle("active", Number(button.dataset.leadMinutes) === safeNumber(state.prayer?.minutes_before));
  });
  const select = $("citySelect");
  select.innerHTML = "";
  (state.cities || []).forEach((city) => {
    const option = document.createElement("option");
    option.value = city;
    option.textContent = city;
    option.selected = city === state.prayer?.city;
    select.append(option);
  });

  const button = $("togglePrayerButton");
  button.classList.toggle("off", state.prayer?.enabled);
  button.querySelector("span").textContent = state.prayer?.enabled ? "Barchasini o'chirish" : "Barchasini yoqish";

  const prayerIcons = {
    fajr: "sunrise",
    sunrise: "sun-medium",
    dhuhr: "sun",
    asr: "cloud-sun",
    maghrib: "sunset",
    isha: "moon-star",
  };
  const grid = $("prayerTimes");
  grid.innerHTML = "";
  (state.prayer?.times || []).forEach((item, index) => {
    const enabled = Boolean(item.enabled);
    const disabled = !item.can_notify;
    const icon = prayerIcons[item.key] || "sun";
    const meta = disabled ? "Ma'lumot uchun" : enabled ? "Eslatma yoqilgan" : "Eslatma o'chirilgan";
    grid.insertAdjacentHTML(
      "beforeend",
      `<article class="prayer-row ${enabled ? "enabled" : ""}" style="animation-delay:${index * 28}ms">
        <div class="item-icon"><i data-lucide="${icon}"></i></div>
        <div>
          <div class="item-title">${escapeHtml(item.name)}</div>
          <div class="item-meta">${meta}</div>
        </div>
        <div class="prayer-row-time">${escapeHtml(item.time)}</div>
        <button class="toggle-mini" data-prayer-key="${item.key}" type="button" ${disabled ? "disabled" : ""}>
          ${disabled ? "—" : enabled ? "Yoqilgan" : "O'chirilgan"}
        </button>
      </article>`,
    );
  });
}

function render() {
  renderAdminVisibility();
  renderHero();
  renderOverview();
  renderFinance();
  renderExtras();
  renderProfile();
  renderAdmin();
  if (activeView === "cards") initCardWheel();
  setTransactionFilter(transactionFilter);
  if (window.lucide) lucide.createIcons();
}

/* ──────────────────────────────────────────────────────────
   Modal helpers
   ────────────────────────────────────────────────────────── */

function openTransactionEditor(item) {
  $("transactionModalTitle").textContent = "Operatsiyani tahrirlash";
  $("transactionIdInput").value = item.id;
  $("transactionTypeInput").value = item.type === "income" ? "income" : "expense";
  $("transactionAmountInput").value = item.amount;
  $("transactionCategoryInput").value = item.category || "Boshqa";
  $("transactionDescriptionInput").value = item.description || item.category || "Operatsiya";
  $("transactionCardInput").value = item.card_last4 || "";
  $("transactionDateInput").value = toDatetimeLocal(item.occurred_at);
  $("transactionModal").hidden = false;
  document.body.classList.add("modal-open");
  window.setTimeout(() => $("transactionAmountInput").focus(), 80);
}

function openNewTransactionEditor() {
  $("transactionModalTitle").textContent = "Operatsiya qo'shish";
  $("transactionIdInput").value = "";
  $("transactionTypeInput").value = "expense";
  $("transactionAmountInput").value = "";
  $("transactionCategoryInput").value = "Boshqa";
  $("transactionDescriptionInput").value = "";
  $("transactionCardInput").value = "";
  $("transactionDateInput").value = toDatetimeLocal(new Date());
  $("transactionModal").hidden = false;
  document.body.classList.add("modal-open");
  window.setTimeout(() => $("transactionAmountInput").focus(), 80);
}

function closeTransactionEditor() {
  $("transactionModal").hidden = true;
  document.body.classList.remove("modal-open");
}

function openReminderEditor(item) {
  $("reminderIdInput").value = item.id;
  $("reminderTextInput").value = item.text || "";
  $("reminderDateInput").value = toDatetimeLocal(item.due_at);
  $("reminderRepeatInput").value = item.repeat_rule || "";
  $("reminderModal").hidden = false;
  document.body.classList.add("modal-open");
  window.setTimeout(() => $("reminderTextInput").focus(), 80);
}

function closeReminderEditor() {
  $("reminderModal").hidden = true;
  document.body.classList.remove("modal-open");
}

function openCardEditor(item) {
  $("cardLast4Input").value = item.card_last4 || "";
  $("cardBankInput").value = item.bank || "";
  $("cardOwnerInput").value = item.owner || "";
  $("cardAmountInput").value = item.amount || "";
  $("cardModal").hidden = false;
  document.body.classList.add("modal-open");
  window.setTimeout(() => $("cardBankInput").focus(), 80);
}

function closeCardEditor() {
  $("cardModal").hidden = true;
  document.body.classList.remove("modal-open");
}

/* ──────────────────────────────────────────────────────────
   Wiring
   ────────────────────────────────────────────────────────── */

document.querySelectorAll(".nav-item").forEach((button) => {
  button.addEventListener("click", () => setView(button.dataset.viewTarget));
});

document.querySelectorAll("[data-open-view]").forEach((button) => {
  button.addEventListener("click", (event) => {
    event.stopPropagation();
    if (button.dataset.transactionFilter) setTransactionFilter(button.dataset.transactionFilter);
    setView(button.dataset.openView);
    if (button.dataset.scrollTarget) {
      requestAnimationFrame(() => {
        $(button.dataset.scrollTarget)?.scrollIntoView({ behavior: "smooth", block: "start" });
      });
    }
  });
});

document.querySelectorAll("[data-transaction-filter]").forEach((button) => {
  button.addEventListener("click", () => {
    setTransactionFilter(button.dataset.transactionFilter);
    if (button.closest("#view-home")) setView("finance");
  });
});

document.querySelectorAll("[data-period-filter]").forEach((button) => {
  button.addEventListener("click", () => setPeriodFilter(button.dataset.periodFilter));
});

$("heroBalanceCard").addEventListener("click", () => {
  setView("cards");
});

$("financeBalanceShortcut")?.addEventListener("click", () => {
  setView("cards");
});

$("nextPrayerCard")?.addEventListener("click", () => {
  setView("extras");
});

$("heroAvatarButton").addEventListener("click", () => {
  setView("profile");
});

$("miniAvatarButton")?.addEventListener("click", () => {
  setView("profile");
});

$("miniRefreshButton")?.addEventListener("click", loadDashboard);

$("cardsBackButton").addEventListener("click", () => {
  setView(previousView && previousView !== "cards" ? previousView : "home");
});

$("transactionExpandButton").addEventListener("click", () => {
  showAllTransactions = !showAllTransactions;
  renderTransactions();
  if (window.lucide) lucide.createIcons();
});

document.addEventListener("click", async (event) => {
  const openFinanceRow = event.target.closest("[data-open-finance-transactions]");
  if (openFinanceRow) {
    setTransactionFilter("all");
    setView("finance");
    return;
  }

  const editReminderButton = event.target.closest("[data-edit-reminder]");
  if (editReminderButton) {
    const id = Number(editReminderButton.dataset.editReminder);
    const item = (state.active_reminders || []).find((row) => Number(row.id) === id);
    if (item) openReminderEditor(item);
    return;
  }

  const cardMenuButton = event.target.closest("[data-card-menu]");
  if (cardMenuButton) {
    const cardLast4 = cardMenuButton.dataset.cardMenu;
    const card = cardMenuButton.closest(".bank-card");
    const isOpen = card?.classList.contains("card-menu-open");

    document.querySelectorAll(".bank-card.card-menu-open").forEach((item) => {
      item.classList.remove("card-menu-open");
      item.querySelector(".card-action-menu")?.remove();
      item.querySelector("[data-card-menu]")?.setAttribute("aria-expanded", "false");
    });

    if (!isOpen && card && cardLast4) {
      card.classList.add("card-menu-open");
      cardMenuButton.setAttribute("aria-expanded", "true");
      cardMenuButton.insertAdjacentHTML(
        "afterend",
        `<div class="card-action-menu" role="menu">
          <button class="card-action-danger" data-delete-card="${escapeHtml(cardLast4)}" type="button" role="menuitem">
            <i data-lucide="trash-2"></i>
            <span>O'chirish</span>
          </button>
        </div>`,
      );
      if (window.lucide) lucide.createIcons();
    }
    return;
  }

  const deleteCardButton = event.target.closest("[data-delete-card]");
  if (deleteCardButton) {
    const cardLast4 = deleteCardButton.dataset.deleteCard;
    if (!cardLast4) return;
    if (demoMode) {
      state.balances = (state.balances || []).filter((item) => String(item.card_last4) !== String(cardLast4));
      render();
      showToast("Telegram orqali ochilganda saqlanadi");
      return;
    }
    await api("/api/cards/delete", { method: "POST", body: JSON.stringify({ card_last4: cardLast4 }) });
    await loadDashboard();
    showToast("Karta o'chirildi");
    return;
  }

  if (!event.target.closest(".card-action-menu")) {
    document.querySelectorAll(".bank-card.card-menu-open").forEach((item) => {
      item.classList.remove("card-menu-open");
      item.querySelector(".card-action-menu")?.remove();
      item.querySelector("[data-card-menu]")?.setAttribute("aria-expanded", "false");
    });
  }

  const deleteButton = event.target.closest("[data-delete-reminder]");
  if (deleteButton) {
    const id = Number(deleteButton.dataset.deleteReminder);
    if (!id) return;
    if (demoMode) {
      state.active_reminders = (state.active_reminders || []).filter((item) => item.id !== id);
      renderExtras();
      showToast("Telegram orqali ochilganda saqlanadi");
      return;
    }
    await api("/api/reminders/delete", { method: "POST", body: JSON.stringify({ id }) });
    await loadDashboard();
    showToast("Eslatma o'chirildi");
    return;
  }

  const editTransactionButton = event.target.closest("[data-edit-transaction]");
  if (editTransactionButton) {
    const id = Number(editTransactionButton.dataset.editTransaction);
    const item = (state.transactions || []).find((row) => Number(row.id) === id);
    if (item) openTransactionEditor(item);
    return;
  }

  const deleteTransactionButton = event.target.closest("[data-delete-transaction]");
  if (deleteTransactionButton) {
    const id = Number(deleteTransactionButton.dataset.deleteTransaction);
    if (!id) return;
    if (!window.confirm("Bu operatsiya o'chirilsinmi?")) return;
    if (demoMode) {
      state.transactions = (state.transactions || []).filter((item) => Number(item.id) !== id);
      state.recent_transactions = (state.recent_transactions || []).filter((item) => Number(item.id) !== id);
      render();
      showToast("Telegram orqali ochilganda saqlanadi");
      return;
    }
    await api("/api/transactions/delete", { method: "POST", body: JSON.stringify({ id }) });
    await loadDashboard();
    showToast("Operatsiya o'chirildi");
    return;
  }

  const clearButton = event.target.closest("[data-clear-scope]");
  if (clearButton) {
    const scope = clearButton.dataset.clearScope;
    const label = scope === "finance" ? "moliya ma'lumotlari" : scope === "reminders" ? "eslatmalar" : "hamma ma'lumotlar";
    if (!window.confirm(`${label} tozalansinmi?`)) return;
    if (demoMode) {
      showToast("Telegram orqali ochilganda bajariladi");
      return;
    }
    await api("/api/data/clear", { method: "POST", body: JSON.stringify({ scope }) });
    await loadDashboard();
    showToast("Ma'lumotlar tozalandi");
    return;
  }

  const deleteCategoryLimitButton = event.target.closest("[data-delete-category-limit]");
  if (deleteCategoryLimitButton) {
    const category = deleteCategoryLimitButton.dataset.deleteCategoryLimit;
    if (!category) return;
    if (demoMode) {
      state.category_limits = (state.category_limits || []).filter((item) => item.category !== category);
      renderFinance();
      showToast("Telegram orqali ochilganda saqlanadi");
      return;
    }
    await api("/api/category-limits/delete", { method: "POST", body: JSON.stringify({ category }) });
    await loadDashboard();
    showToast("Limit o'chirildi");
    return;
  }

  const deleteChoreMemberButton = event.target.closest("[data-delete-chore-member]");
  if (deleteChoreMemberButton) {
    const id = Number(deleteChoreMemberButton.dataset.deleteChoreMember);
    if (!id) return;
    if (demoMode || !state.is_admin) {
      state.admin = state.admin || {};
      const chores = state.admin.chores || {};
      updateChores({ ...chores, members: (chores.members || []).filter((item) => Number(item.id) !== id) });
      showToast("Telegram ichida saqlanadi");
      return;
    }
    const result = await api("/api/admin/chore-members/delete", { method: "POST", body: JSON.stringify({ id }) });
    updateChores(result.chores);
    showToast("Navbatchi olib tashlandi");
    return;
  }

  const deleteChorePairButton = event.target.closest("[data-delete-chore-pair]");
  if (deleteChorePairButton) {
    const id = Number(deleteChorePairButton.dataset.deleteChorePair);
    if (!id) return;
    if (demoMode || !state.is_admin) {
      state.admin = state.admin || {};
      const chores = state.admin.chores || {};
      updateChores({ ...chores, pairs: (chores.pairs || []).filter((item) => Number(item.id) !== id) });
      showToast("Telegram ichida saqlanadi");
      return;
    }
    const result = await api("/api/admin/chore-pairs/delete", { method: "POST", body: JSON.stringify({ id }) });
    updateChores(result.chores);
    showToast("Juftlik olib tashlandi");
    return;
  }

  const blockButton = event.target.closest("[data-admin-block]");
  if (blockButton) {
    const userId = Number(blockButton.dataset.adminBlock);
    if (!userId || !window.confirm(`${userId} bloklansinmi?`)) return;
    await api("/api/admin/block", { method: "POST", body: JSON.stringify({ user_id: userId }) });
    await reloadAdminUsers();
    showToast("User bloklandi");
    return;
  }

  const unblockButton = event.target.closest("[data-admin-unblock]");
  if (unblockButton) {
    const userId = Number(unblockButton.dataset.adminUnblock);
    if (!userId) return;
    await api("/api/admin/unblock", { method: "POST", body: JSON.stringify({ user_id: userId }) });
    await reloadAdminUsers();
    showToast("User blokdan chiqarildi");
  }
});

$("refreshButton").addEventListener("click", loadDashboard);
$("openNewTransactionButton").addEventListener("click", openNewTransactionEditor);
$("adminRefreshButton").addEventListener("click", reloadAdminUsers);

$("adminAllowButton").addEventListener("click", async () => {
  const userId = Number($("adminUserInput").value.trim());
  if (!userId) {
    showToast("User ID yozing");
    return;
  }
  if (demoMode || !state.is_admin) {
    showToast("Admin panel Telegram ichida ishlaydi");
    return;
  }
  const result = await api("/api/admin/allow", { method: "POST", body: JSON.stringify({ user_id: userId }) });
  $("adminUserInput").value = "";
  await reloadAdminUsers();
  showToast(result.message || "User qo'shildi");
});

$("choreMemberAddButton")?.addEventListener("click", async () => {
  const input = $("choreMemberInput");
  const name = normalizeUsernameInput(input.value);
  if (!name) {
    showToast("Navbatchi @username yozing");
    return;
  }
  if (demoMode || !state.is_admin) {
    const chores = state.admin?.chores || {};
    const nextId = Date.now();
    updateChores({ ...chores, members: [...(chores.members || []), { id: nextId, name }] });
    input.value = "";
    showToast("Telegram ichida saqlanadi");
    return;
  }
  try {
    const result = await api("/api/admin/chore-members/add", { method: "POST", body: JSON.stringify({ name }) });
    input.value = "";
    updateChores(result.chores);
    showToast("Navbatchi qo'shildi");
  } catch (error) {
    showToast(dashboardErrorMessage(error));
  }
});

$("chorePairAddButton")?.addEventListener("click", async () => {
  const firstInput = $("chorePairFirstInput");
  const secondInput = $("chorePairSecondInput");
  const firstName = normalizeUsernameInput(firstInput.value);
  const secondName = normalizeUsernameInput(secondInput.value);
  if (!firstName || !secondName) {
    showToast("Juftlikdagi ikkala @username ni yozing");
    return;
  }
  if (demoMode || !state.is_admin) {
    const chores = state.admin?.chores || {};
    updateChores({
      ...chores,
      pairs: [...(chores.pairs || []), { id: Date.now(), first_name: firstName, second_name: secondName }],
    });
    firstInput.value = "";
    secondInput.value = "";
    showToast("Telegram ichida saqlanadi");
    return;
  }
  try {
    const result = await api("/api/admin/chore-pairs/add", {
      method: "POST",
      body: JSON.stringify({ first_name: firstName, second_name: secondName }),
    });
    firstInput.value = "";
    secondInput.value = "";
    updateChores(result.chores);
    showToast("Juftlik qo'shildi");
  } catch (error) {
    showToast(dashboardErrorMessage(error));
  }
});

$("completedToggleButton").addEventListener("click", () => {
  if ((state.completed_reminders || []).length <= 3) return;
  showAllCompletedReminders = !showAllCompletedReminders;
  renderExtras();
  showToast(showAllCompletedReminders ? "Barcha yakunlangan eslatmalar" : "Qisqa ro'yxat");
  if (window.lucide) lucide.createIcons();
});

$("activeToggleButton").addEventListener("click", () => {
  if ((state.active_reminders || []).length <= 4) return;
  showAllActiveReminders = !showAllActiveReminders;
  renderExtras();
  showToast(showAllActiveReminders ? "Barcha aktiv eslatmalar" : "Qisqa ro'yxat");
  if (window.lucide) lucide.createIcons();
});

$("closeTransactionModal").addEventListener("click", closeTransactionEditor);
$("transactionModal").addEventListener("click", (event) => {
  if (event.target.id === "transactionModal") closeTransactionEditor();
});
$("closeReminderModal").addEventListener("click", closeReminderEditor);
$("reminderModal").addEventListener("click", (event) => {
  if (event.target.id === "reminderModal") closeReminderEditor();
});
$("closeCardModal").addEventListener("click", closeCardEditor);
$("cardModal").addEventListener("click", (event) => {
  if (event.target.id === "cardModal") closeCardEditor();
});

$("transactionForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const id = Number($("transactionIdInput").value);
  const body = {
    type: $("transactionTypeInput").value,
    amount: $("transactionAmountInput").value,
    category: $("transactionCategoryInput").value,
    description: $("transactionDescriptionInput").value,
    card_last4: $("transactionCardInput").value,
    occurred_at: fromDatetimeLocal($("transactionDateInput").value),
  };
  if (id) body.id = id;
  if (demoMode) {
    if (id) {
      state.transactions = (state.transactions || []).map((item) =>
        Number(item.id) === id ? { ...item, ...body, amount: Number(body.amount), amount_text: `${body.amount} so'm` } : item,
      );
    } else {
      state.transactions = state.transactions || [];
      state.transactions.unshift({ ...body, id: Date.now(), amount: Number(body.amount), amount_text: `${body.amount} so'm`, currency: "UZS" });
    }
    closeTransactionEditor();
    render();
    showToast("Telegram orqali ochilganda saqlanadi");
    return;
  }
  await api(id ? "/api/transactions/update" : "/api/transactions/create", {
    method: "POST",
    body: JSON.stringify(body),
  });
  closeTransactionEditor();
  await loadDashboard();
  showToast(id ? "Operatsiya yangilandi" : "Operatsiya qo'shildi");
});

$("reminderForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const id = Number($("reminderIdInput").value);
  const body = {
    id,
    text: $("reminderTextInput").value,
    due_at: fromDatetimeLocal($("reminderDateInput").value),
    repeat_rule: $("reminderRepeatInput").value,
  };
  if (!id) return;
  if (demoMode) {
    state.active_reminders = (state.active_reminders || []).map((item) =>
      Number(item.id) === id ? { ...item, ...body } : item,
    );
    closeReminderEditor();
    renderExtras();
    showToast("Telegram orqali ochilganda saqlanadi");
    return;
  }
  await api("/api/reminders/update", { method: "POST", body: JSON.stringify(body) });
  closeReminderEditor();
  await loadDashboard();
  showToast("Eslatma yangilandi");
});

$("cardForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const body = {
    card_last4: $("cardLast4Input").value,
    bank: $("cardBankInput").value,
    owner: $("cardOwnerInput").value,
    amount: $("cardAmountInput").value,
  };
  if (demoMode) {
    state.balances = (state.balances || []).map((item) =>
      String(item.card_last4) === String(body.card_last4)
        ? { ...item, bank: body.bank, owner: body.owner, amount: Number(String(body.amount).replace(/\D/g, "")) || item.amount }
        : item,
    );
    closeCardEditor();
    renderCardWheel();
    showToast("Telegram orqali ochilganda saqlanadi");
    return;
  }
  await api("/api/cards/update", { method: "POST", body: JSON.stringify(body) });
  closeCardEditor();
  await loadDashboard();
  showToast("Karta yangilandi");
});

$("deleteCardButton").addEventListener("click", async () => {
  const cardLast4 = $("cardLast4Input").value;
  if (!cardLast4) return;
  if (!window.confirm(`**** ${cardLast4} kartasi ro'yxatdan olib tashlansinmi?`)) return;
  if (demoMode) {
    state.balances = (state.balances || []).filter((item) => String(item.card_last4) !== String(cardLast4));
    closeCardEditor();
    render();
    showToast("Telegram orqali ochilganda saqlanadi");
    return;
  }
  await api("/api/cards/delete", { method: "POST", body: JSON.stringify({ card_last4: cardLast4 }) });
  closeCardEditor();
  await loadDashboard();
  showToast("Karta olib tashlandi");
});

$("saveDailyLimitButton").addEventListener("click", async () => {
  const amount = $("dailyLimitInput").value.trim();
  if (demoMode) {
    state.settings = state.settings || {};
    state.settings.daily_expense_limit = Number(amount.replace(/\D/g, "")) || 0;
    state.settings.daily_expense_limit_text = state.settings.daily_expense_limit ? `${state.settings.daily_expense_limit} so'm` : "Belgilanmagan";
    renderFinance();
    showToast("Telegram orqali ochilganda saqlanadi");
    return;
  }
  await api("/api/settings/daily-limit", { method: "POST", body: JSON.stringify({ amount }) });
  await loadDashboard();
  showToast("Kunlik limit saqlandi");
});

$("saveCategoryLimitButton").addEventListener("click", async () => {
  const category = $("categoryLimitNameInput").value.trim();
  const amount = $("categoryLimitAmountInput").value.trim();
  if (!category || !amount) {
    showToast("Kategoriya va limit yozing");
    return;
  }
  if (demoMode) {
    const amountText = `${amount.replace(/\D/g, "") || 0} so'm`;
    state.category_limits = [
      ...(state.category_limits || []).filter((item) => item.category.toLowerCase() !== category.toLowerCase()),
      { category, amount: Number(amount.replace(/\D/g, "")) || 0, amount_text: amountText },
    ];
    renderFinance();
    showToast("Telegram orqali ochilganda saqlanadi");
    return;
  }
  await api("/api/category-limits/set", { method: "POST", body: JSON.stringify({ category, amount }) });
  $("categoryLimitNameInput").value = "";
  $("categoryLimitAmountInput").value = "";
  await loadDashboard();
  showToast("Kategoriya limiti saqlandi");
});

$("dailyReportToggleButton").addEventListener("click", async () => {
  const enabled = !Boolean(state.settings?.daily_report_enabled);
  state.settings = state.settings || {};
  state.settings.daily_report_enabled = enabled;
  renderFinance();
  if (window.lucide) lucide.createIcons();
  if (demoMode) {
    showToast("Telegram orqali ochilganda saqlanadi");
    return;
  }
  try {
    await api("/api/settings/daily-report", { method: "POST", body: JSON.stringify({ enabled }) });
    showToast(enabled ? "Kunlik hisobot yoqildi" : "Kunlik hisobot o'chirildi");
  } catch (error) {
    state.settings.daily_report_enabled = !enabled;
    renderFinance();
    showToast(dashboardErrorMessage(error));
  }
});

$("exportCsvButton").addEventListener("click", async () => {
  if (demoMode) {
    showToast("Excel export Telegram ichida ishlaydi");
    return;
  }
  const result = await api("/api/export/transactions.xlsx", {
    method: "POST",
    body: JSON.stringify({ period: periodFilter, type: transactionFilter }),
  });
  showToast(`${result.count || 0} ta operatsiya Excel qilib Telegramga yuborildi`);
});

$("togglePrayerButton").addEventListener("click", async () => {
  const next = !Boolean(state.prayer?.enabled);
  state.prayer.enabled = next;
  state.prayer.times = (state.prayer?.times || []).map((item) => ({
    ...item,
    enabled: item.can_notify ? next : false,
  }));
  renderPrayer();
  if (window.lucide) lucide.createIcons();
  if (demoMode) {
    showToast("Telegram orqali ochilganda saqlanadi");
    return;
  }
  try {
    await api("/api/prayer/toggle", { method: "POST", body: JSON.stringify({ enabled: next }) });
    showToast("Namoz eslatmasi yangilandi");
  } catch (error) {
    await loadDashboard();
    showToast(dashboardErrorMessage(error));
  }
});

$("leadTimeOptions").addEventListener("click", async (event) => {
  const button = event.target.closest("[data-lead-minutes]");
  if (!button) return;
  const minutes = Number(button.dataset.leadMinutes);
  state.prayer.minutes_before = minutes;
  renderPrayer();
  if (window.lucide) lucide.createIcons();
  if (demoMode) {
    showToast("Telegram orqali ochilganda saqlanadi");
    return;
  }
  try {
    await api("/api/prayer/lead-time", { method: "POST", body: JSON.stringify({ minutes }) });
    showToast(`${minutes} daqiqa oldin eslatish saqlandi`);
  } catch (error) {
    await loadDashboard();
    showToast(dashboardErrorMessage(error));
  }
});

$("prayerTimes").addEventListener("click", async (event) => {
  const button = event.target.closest("[data-prayer-key]");
  if (!button || button.disabled) return;
  const key = button.dataset.prayerKey;
  const item = (state.prayer?.times || []).find((row) => row.key === key);
  if (!item) return;
  const enabled = !item.enabled;
  item.enabled = enabled;
  state.prayer.enabled = state.prayer.times.some((row) => row.can_notify && row.enabled);
  renderPrayer();
  if (window.lucide) lucide.createIcons();
  if (demoMode) {
    showToast("Telegram orqali ochilganda saqlanadi");
    return;
  }
  try {
    await api("/api/prayer/key", { method: "POST", body: JSON.stringify({ key, enabled }) });
    showToast(`${item.name} eslatmasi ${enabled ? "yoqildi" : "o'chirildi"}`);
  } catch (error) {
    await loadDashboard();
    showToast(dashboardErrorMessage(error));
  }
});

$("citySelect").addEventListener("change", async (event) => {
  if (demoMode) {
    state.prayer.city = event.target.value;
    renderExtras();
    showToast("Telegram orqali ochilganda saqlanadi");
    return;
  }
  await api("/api/prayer/city", { method: "POST", body: JSON.stringify({ city: event.target.value }) });
  await loadDashboard();
  showToast("Shahar yangilandi");
});

$("themeToggleButton").addEventListener("click", () => {
  const current = localStorage.getItem("assistant_theme") === "light" ? "light" : "dark";
  applyTheme(current === "light" ? "dark" : "light");
});

window.addEventListener("resize", () => {
  if (activeView === "cards") applyCardWheelTransforms();
});

/* Sticky hero collapse with anti-flicker cooldown.
   The collapse changes the hero's height by ~140px which shifts everything
   below it. When the user paused mid-scroll near the boundary, that shift
   would push their scroll position back across the threshold and the state
   would oscillate. Two defences:
     1. Wide hysteresis gap (50→6) so casual scroll noise can't cross both
        boundaries
     2. Time lock equal to the morph duration — once a toggle has fired we
        ignore further scroll events until the layout has had a chance to
        settle. */
let miniHeaderPending = false;
const MINI_HEADER_ENTER = 86;
const MINI_HEADER_EXIT = 24;

function updateMiniHeaderVisibility() {
  const y = window.scrollY || window.pageYOffset || 0;
  const shown = document.body.classList.contains("mini-header-visible");
  const forceShort = ["finance", "extras"].includes(activeView);
  let want = forceShort || shown;
  if (!shown && y > MINI_HEADER_ENTER) want = true;
  else if (shown && y < MINI_HEADER_EXIT && !forceShort) want = false;
  if (want !== shown) {
    document.body.classList.toggle("mini-header-visible", want);
  }
}

window.addEventListener(
  "scroll",
  () => {
    if (miniHeaderPending) return;
    miniHeaderPending = true;
    requestAnimationFrame(() => {
      miniHeaderPending = false;
      updateMiniHeaderVisibility();
    });
  },
  { passive: true },
);

if (tg) {
  tg.ready();
  tg.expand();
}

applyTheme(localStorage.getItem("assistant_theme") || "dark");
document.body.dataset.activeView = activeView;
loadDashboard();
updateMiniHeaderVisibility();
