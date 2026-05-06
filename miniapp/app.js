const tg = window.Telegram?.WebApp;
const demoData = window.AssistantDemoData;
let activeView = "home";
let transactionFilter = "all";
let periodFilter = "today";
let showAllCompletedReminders = false;

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function $(id) {
  return document.getElementById(id);
}

function safeNumber(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : 0;
}

function formatDateTime(value) {
  if (!value) return "";
  const date = new Date(value);
  return new Intl.DateTimeFormat("uz-UZ", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function monthName(value = new Date()) {
  const date = new Date(value);
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

function showToast(text) {
  const toast = $("toast");
  toast.textContent = text;
  toast.classList.add("show");
  window.setTimeout(() => toast.classList.remove("show"), 2400);
}

function setAuthNotice(visible) {
  const notice = $("authNotice");
  if (!notice) return;
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

async function loadDashboard() {
  $("refreshButton").classList.add("spin");
  try {
    state = await api("/api/dashboard");
    demoMode = false;
    setAuthNotice(false);
  } catch (error) {
    console.warn(error);
    state = clone(demoData);
    demoMode = true;
    setAuthNotice(true);
    showToast(String(error.message || error).includes("401") ? "Telegram Mini App auth topilmadi" : "Mini App ma'lumot yuklay olmadi");
  } finally {
    window.setTimeout(() => $("refreshButton").classList.remove("spin"), 380);
  }
  render();
}

function setView(view) {
  if (!view) return;
  if (view === "admin" && !state.is_admin) {
    view = "home";
  }
  activeView = view;
  document.querySelectorAll(".view").forEach((panel) => {
    panel.classList.toggle("active", panel.dataset.view === view);
  });
  document.querySelectorAll(".nav-item").forEach((button) => {
    button.classList.toggle("active", button.dataset.viewTarget === view);
  });
  if (window.lucide) lucide.createIcons();
}

function setTransactionFilter(filter = "all") {
  transactionFilter = ["income", "expense"].includes(filter) ? filter : "all";
  document.querySelectorAll("[data-transaction-filter]").forEach((button) => {
    button.classList.toggle("active-filter", button.dataset.transactionFilter === transactionFilter);
  });
  document.querySelectorAll(".segment[data-transaction-filter]").forEach((button) => {
    button.classList.toggle("active", button.dataset.transactionFilter === transactionFilter);
  });
  renderTransactions();
}

function setPeriodFilter(filter = "today") {
  periodFilter = ["today", "week", "month"].includes(filter) ? filter : "today";
  document.querySelectorAll("[data-period-filter]").forEach((button) => {
    button.classList.toggle("active", button.dataset.periodFilter === periodFilter);
  });
  renderFinance();
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
  $("themeModeLabel").textContent = nextMode === "light" ? "Kunduzgi rejim" : "Tun rejimi";
  if (tg?.setHeaderColor) {
    tg.setHeaderColor(nextMode === "light" ? "#f6f8fb" : "#111217");
  }
}

function renderHero() {
  $("heroBalance").textContent = state.balance_total_text;
  $("heroMeta").textContent = `${state.balances.length} ta karta - ${formatDateTime(state.generated_at)}`;
  $("generatedAt").textContent = `Yangilandi: ${formatDateTime(state.generated_at)}`;
  $("homeIncome").textContent = state.month.income_text;
  $("homeExpense").textContent = state.month.expense_text;
}

function renderOverview() {
  const next = state.prayer.next;
  $("nextPrayerName").textContent = next ? `${next.name} ${next.time}` : "Bugungi vaqtlar tugadi";
  $("nextPrayerMeta").textContent = `${state.prayer.city} - eslatma ${state.prayer.enabled ? "yoqilgan" : "o'chirilgan"}`;
  $("reminderCount").textContent = `${state.active_reminders?.length || state.reminders.length} ta`;
  renderHomeReminders();
  renderRecentTransactions();
}

function renderHomeReminders() {
  const reminders = $("reminderList");
  const list = state.active_reminders?.length ? state.active_reminders : state.reminders;
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
  const prefix = type === "income" ? "+" : "-";
  const icon = type === "income" ? "arrow-down-left" : "arrow-up-right";
  const card = item.card_last4 ? ` - *${escapeHtml(item.card_last4)}` : "";
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
  return `<article class="list-item ${manageable ? "managed" : ""}" style="animation-delay:${index * 35}ms">
    <div class="item-icon ${type}"><i data-lucide="${icon}"></i></div>
    <div>
      <div class="item-title">${escapeHtml(item.description || item.category || "Operatsiya")}</div>
      <div class="item-meta">${escapeHtml(item.category || "Boshqa")} - ${formatDateTime(item.occurred_at)}${card}</div>
    </div>
    <div class="amount ${type}">${prefix}${item.amount_text}</div>
    ${actions}
  </article>`;
}

function renderRecentTransactions() {
  const recent = $("recentTransactions");
  recent.innerHTML = "";
  if (!state.recent_transactions.length) {
    recent.innerHTML = `<div class="empty">Hali kirim yoki xarajat yo'q. Bank xabarini botga yuboring.</div>`;
    return;
  }

  state.recent_transactions.slice(0, 5).forEach((item, index) => {
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
  const dailyLimit = safeNumber(state.settings?.daily_expense_limit);
  $("dailyLimitInput").value = dailyLimit > 0 ? String(dailyLimit) : "";
  $("dailyLimitNote").textContent = dailyLimit > 0
    ? `Bugungi limit: ${state.settings.daily_expense_limit_text}. Sarflangan: ${state.today?.expense_text || "0 so'm"}`
    : "Kunlik limit belgilanmagan.";
  $("dailyReportToggleButton").classList.toggle("active", Boolean(state.settings?.daily_report_enabled));
  $("dailyReportToggleButton").querySelector("span").textContent =
    state.settings?.daily_report_enabled ? "Kunlik hisobot yoqilgan" : "Kunlik hisobot o'chirilgan";
  renderTransactions();
  renderCategories();
  renderCategoryLimits();
  renderSavings();
  renderBalances();
  renderSignals();
}

function renderTransactions() {
  const labelMap = { all: "Barcha operatsiyalar", income: "Kirimlar", expense: "Chiqimlar" };
  $("transactionFilterLabel").textContent = labelMap[transactionFilter] || labelMap.all;
  const list = $("transactionList");
  const rows = (state.transactions || []).filter(
    (item) => transactionInPeriod(item) && (transactionFilter === "all" || item.type === transactionFilter),
  );
  list.innerHTML = "";
  if (!rows.length) {
    list.innerHTML = `<div class="empty">${labelMap[transactionFilter]} hali yo'q.</div>`;
    return;
  }
  rows.forEach((item, index) => {
    list.insertAdjacentHTML("beforeend", transactionItemHtml(item, index, true));
  });
}

function renderCategories() {
  const categories = $("categoryList");
  categories.innerHTML = "";
  const max = Math.max(1, ...state.categories.map((item) => safeNumber(item.amount)));
  if (!state.categories.length) {
    categories.innerHTML = `<div class="empty">Kategoriyalar hali yo'q. Xarajatlar kelganda shu yerda ajraladi.</div>`;
    return;
  }

  state.categories.forEach((item, index) => {
    const width = Math.max(8, Math.round((safeNumber(item.amount) / max) * 100));
    categories.insertAdjacentHTML(
      "beforeend",
      `<article class="category-row" style="animation-delay:${index * 35}ms">
        <div>
          <div class="item-title">${escapeHtml(item.name)}</div>
          <div class="item-meta">${item.amount_text}</div>
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
      `<article class="list-item compact" style="animation-delay:${index * 35}ms">
        <div class="item-icon"><i data-lucide="gauge"></i></div>
        <div>
          <div class="item-title">${escapeHtml(item.category)}</div>
          <div class="item-meta">Oylik limit: ${escapeHtml(item.amount_text)}</div>
        </div>
        <button class="icon-button danger small" data-delete-category-limit="${escapeHtml(item.category)}" type="button" aria-label="Limitni o'chirish">
          <i data-lucide="trash-2"></i>
        </button>
      </article>`,
    );
  });
}

function renderSavings() {
  const income = safeNumber(state.month.income);
  const expense = safeNumber(state.month.expense);
  const net = income - expense;
  const percent = income > 0 ? Math.max(0, Math.min(100, Math.round((Math.max(net, 0) / income) * 100))) : 0;
  $("savingNet").textContent = state.month.net_text;
  $("savingRing").textContent = `${percent}%`;
  $("savingRing").style.setProperty("--saving", percent);
  $("savingProgress").style.width = `${percent}%`;
  $("savingHint").textContent =
    net >= 0
      ? "Bu oy kirim chiqimdan yuqori. Farqni alohida jamg'arma sifatida ajratib borish mumkin."
      : "Bu oy chiqim kirimdan yuqori. Quyidagi kategoriyalarni tekshirib chiqing.";
}

function renderBalances() {
  $("cardUpdatedLabel").textContent = `${state.balances.length} ta karta`;
  const list = $("balanceList");
  list.innerHTML = "";
  if (!state.balances.length) {
    list.innerHTML = `<div class="empty">Balanslar hali yo'q. UZCARD/HUMO xabarini botga yuboring.</div>`;
    return;
  }

  state.balances.forEach((item) => {
    list.insertAdjacentHTML(
      "beforeend",
      `<article class="balance-card">
        <span>${escapeHtml(item.label)}</span>
        <strong>${item.amount_text}</strong>
        <small>Yangilangan: ${formatDateTime(item.updated_at)}</small>
      </article>`,
    );
  });
}

function renderSignals() {
  const box = $("financeSignals");
  const income = safeNumber(state.month.income);
  const expense = safeNumber(state.month.expense);
  const todayExpense = safeNumber(state.today?.expense);
  const dailyLimit = safeNumber(state.settings?.daily_expense_limit);
  const cards = state.balances.length;
  const signals = [];

  if (cards === 0) signals.push(["wallet-cards", "Karta balansi yo'q", "Bank botidan kelgan balans xabarini yuboring."]);
  if (dailyLimit > 0 && todayExpense >= dailyLimit) {
    signals.push(["shield-alert", "Kunlik limit oshdi", `Bugun ${state.today.expense_text} sarflandi. Limit: ${state.settings.daily_expense_limit_text}.`]);
  } else if (dailyLimit > 0 && todayExpense >= dailyLimit * 0.8) {
    signals.push(["bell-ring", "Limitga yaqin", `Bugungi xarajat limitning katta qismiga yetdi: ${state.today.expense_text}.`]);
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
      ([icon, title, text], index) => `<article class="list-item" style="animation-delay:${index * 35}ms">
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

function reminderItemHtml(item, index, removable) {
  const statusText = item.status === "sent" ? "Yakunlangan" : item.status === "cancelled" ? "O'chirilgan" : "Aktiv";
  const dateText = item.status === "sent" && item.sent_at ? formatDateTime(item.sent_at) : formatDateTime(item.due_at);
  const repeatText = item.repeat_label ? ` - ${escapeHtml(item.repeat_label)}` : "";
  const action = removable
    ? `<button class="icon-button danger small" data-delete-reminder="${item.id}" type="button" aria-label="O'chirish">
        <i data-lucide="trash-2"></i>
      </button>`
    : `<i data-lucide="chevron-right"></i>`;
  return `<article class="list-item" style="animation-delay:${index * 35}ms">
    <div class="item-icon"><i data-lucide="${item.status === "pending" ? "bell-ring" : "check-check"}"></i></div>
    <div>
      <div class="item-title">${escapeHtml(item.text)}</div>
      <div class="item-meta">${statusText} - ${dateText}${repeatText}</div>
    </div>
    ${action}
  </article>`;
}

function renderExtras() {
  const active = state.active_reminders || [];
  const completed = state.completed_reminders || [];
  $("activeReminderCount").textContent = `${active.length} ta`;
  $("completedReminderCount").textContent = completed.length > 3 && !showAllCompletedReminders ? "Barchasi" : `${completed.length} ta`;

  const activeList = $("activeReminderList");
  activeList.innerHTML = "";
  if (!active.length) {
    activeList.innerHTML = `<div class="empty">Aktiv eslatma yo'q. Telegramga "1 soatdan keyin ..." deb yozing.</div>`;
  } else {
    active.forEach((item, index) => activeList.insertAdjacentHTML("beforeend", reminderItemHtml(item, index, true)));
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
  const user = tg?.initDataUnsafe?.user || {};
  const fullName = [user.first_name, user.last_name].filter(Boolean).join(" ") || "Foydalanuvchi";
  $("profileName").textContent = fullName;
  document.querySelector(".avatar").textContent = fullName.trim().charAt(0).toUpperCase() || "F";
  $("profileStatus").textContent = demoMode ? "Telegram orqali oching" : "Assistant faol";
  $("profileUsername").textContent = user.username ? `@${user.username}` : "Ko'rsatilmagan";
  $("profileId").textContent = user.id ? String(user.id) : "Telegramda oching";
  $("profilePhone").textContent = "Botga berilmagan";
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
  if (!badges.length) badges.push(`<span class="status-pill muted">Noma'lum</span>`);
  return badges.join("");
}

function adminUserHtml(item, index) {
  const username = item.username_text || (item.username ? `@${item.username}` : "Ko'rsatilmagan");
  const updated = item.updated_at_text ? formatDateTime(item.updated_at_text) : "Hali ko'rinmagan";
  const action = item.admin
    ? `<button class="ghost-action" disabled type="button"><i data-lucide="shield-check"></i><span>Admin</span></button>`
    : item.blocked
      ? `<button class="ghost-action" data-admin-unblock="${item.user_id}" type="button"><i data-lucide="unlock"></i><span>Blokdan chiqarish</span></button>`
      : `<button class="ghost-action danger" data-admin-block="${item.user_id}" type="button"><i data-lucide="ban"></i><span>Bloklash</span></button>`;
  return `<article class="admin-user-card" style="animation-delay:${index * 35}ms">
    <div class="admin-user-head">
      <div class="avatar mini">${escapeHtml(item.name || "U").charAt(0).toUpperCase()}</div>
      <div>
        <div class="item-title">${escapeHtml(item.name || `User ${item.user_id}`)}</div>
        <div class="item-meta">${escapeHtml(username)} - ID ${escapeHtml(item.user_id)}</div>
      </div>
      <div class="status-row">${userStatusBadges(item)}</div>
    </div>
    <div class="admin-user-grid">
      <div><span>Balans</span><strong>${escapeHtml(item.balance_text || "0 so'm")}</strong></div>
      <div><span>Chiqim</span><strong>${escapeHtml(item.expense_text || "0 so'm")}</strong></div>
      <div><span>Operatsiya</span><strong>${escapeHtml(item.transactions || 0)}</strong></div>
      <div><span>Yangilangan</span><strong>${escapeHtml(updated)}</strong></div>
    </div>
    <div class="admin-actions">${action}</div>
  </article>`;
}

function renderAdmin() {
  renderAdminVisibility();
  if (!state.is_admin) return;
  const users = state.admin?.users || [];
  const audits = state.admin?.audit_logs || [];
  $("adminSummary").textContent = `${state.admin?.allowed_count || 0} ruxsat, ${state.admin?.blocked_count || 0} blok`;
  const list = $("adminUserList");
  list.innerHTML = "";
  if (!users.length) {
    list.innerHTML = `<div class="empty">Hali userlar ko'rinmagan. User botga /start yoki /id yuborganda profili saqlanadi.</div>`;
  } else {
    users.forEach((item, index) => {
      list.insertAdjacentHTML("beforeend", adminUserHtml(item, index));
    });
  }

  const auditList = $("adminAuditList");
  auditList.innerHTML = "";
  if (!audits.length) {
    auditList.innerHTML = `<div class="empty">Audit tarixi hali bo'sh.</div>`;
  } else {
    audits.forEach((item, index) => {
      const target = item.target_user_id ? ` -> ${item.target_user_id}` : "";
      auditList.insertAdjacentHTML(
        "beforeend",
        `<article class="list-item compact" style="animation-delay:${index * 35}ms">
          <div class="item-icon"><i data-lucide="history"></i></div>
          <div>
            <div class="item-title">${escapeHtml(item.action)}${escapeHtml(target)}</div>
            <div class="item-meta">${formatDateTime(item.created_at)} - admin ${escapeHtml(item.actor_user_id)} ${item.details ? "- " + escapeHtml(item.details) : ""}</div>
          </div>
        </article>`,
      );
    });
  }
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
  };
  renderAdmin();
  if (window.lucide) lucide.createIcons();
}

function renderPrayer() {
  $("prayerCityLabel").textContent = state.prayer.city;
  $("prayerSource").textContent = state.prayer.source || "Offline hisoblash";
  document.querySelectorAll("[data-lead-minutes]").forEach((button) => {
    button.classList.toggle("active", Number(button.dataset.leadMinutes) === safeNumber(state.prayer.minutes_before));
  });
  const select = $("citySelect");
  select.innerHTML = "";
  state.cities.forEach((city) => {
    const option = document.createElement("option");
    option.value = city;
    option.textContent = city;
    option.selected = city === state.prayer.city;
    select.append(option);
  });

  const button = $("togglePrayerButton");
  button.classList.toggle("off", state.prayer.enabled);
  button.querySelector("span").textContent = state.prayer.enabled ? "Barchasini o'chirish" : "Barchasini yoqish";

  const grid = $("prayerTimes");
  grid.innerHTML = "";
  state.prayer.times.forEach((item) => {
    const enabled = Boolean(item.enabled);
    const disabled = !item.can_notify;
    grid.insertAdjacentHTML(
      "beforeend",
      `<article class="prayer-time ${enabled ? "enabled" : ""}">
        <span>${escapeHtml(item.name)}</span>
        <strong>${item.time}</strong>
        <button class="toggle-mini" data-prayer-key="${item.key}" type="button" ${disabled ? "disabled" : ""}>
          ${disabled ? "Ma'lumot" : enabled ? "Yoqilgan" : "O'chirilgan"}
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
  setTransactionFilter(transactionFilter);
  if (window.lucide) lucide.createIcons();
}

function openTransactionEditor(item) {
  $("transactionModalTitle").textContent = "Operatsiyani tahrirlash";
  $("transactionIdInput").value = item.id;
  $("transactionTypeInput").value = item.type === "income" ? "income" : "expense";
  $("transactionAmountInput").value = item.amount;
  $("transactionCategoryInput").value = item.category || "Boshqa";
  $("transactionDescriptionInput").value = item.description || item.category || "Operatsiya";
  $("transactionCardInput").value = item.card_last4 || "";
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
  $("transactionModal").hidden = false;
  document.body.classList.add("modal-open");
  window.setTimeout(() => $("transactionAmountInput").focus(), 80);
}

function closeTransactionEditor() {
  $("transactionModal").hidden = true;
  document.body.classList.remove("modal-open");
}

document.querySelectorAll(".nav-item").forEach((button) => {
  button.addEventListener("click", () => setView(button.dataset.viewTarget));
});

document.querySelectorAll("[data-open-view]").forEach((button) => {
  button.addEventListener("click", () => {
    if (button.dataset.transactionFilter) setTransactionFilter(button.dataset.transactionFilter);
    setView(button.dataset.openView);
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

document.addEventListener("click", async (event) => {
  const deleteButton = event.target.closest("[data-delete-reminder]");
  if (deleteButton) {
    const id = Number(deleteButton.dataset.deleteReminder);
    if (!id) return;
    if (demoMode) {
      state.active_reminders = state.active_reminders.filter((item) => item.id !== id);
      renderExtras();
      showToast("Telegram orqali ochilganda saqlanadi");
      return;
    }
    await api("/api/reminders/delete", {
      method: "POST",
      body: JSON.stringify({ id }),
    });
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
      state.transactions = state.transactions.filter((item) => Number(item.id) !== id);
      state.recent_transactions = state.recent_transactions.filter((item) => Number(item.id) !== id);
      render();
      showToast("Telegram orqali ochilganda saqlanadi");
      return;
    }
    await api("/api/transactions/delete", {
      method: "POST",
      body: JSON.stringify({ id }),
    });
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
    await api("/api/data/clear", {
      method: "POST",
      body: JSON.stringify({ scope }),
    });
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
    await api("/api/category-limits/delete", {
      method: "POST",
      body: JSON.stringify({ category }),
    });
    await loadDashboard();
    showToast("Limit o'chirildi");
    return;
  }

  const blockButton = event.target.closest("[data-admin-block]");
  if (blockButton) {
    const userId = Number(blockButton.dataset.adminBlock);
    if (!userId || !window.confirm(`${userId} bloklansinmi?`)) return;
    await api("/api/admin/block", {
      method: "POST",
      body: JSON.stringify({ user_id: userId }),
    });
    await reloadAdminUsers();
    showToast("User bloklandi");
    return;
  }

  const unblockButton = event.target.closest("[data-admin-unblock]");
  if (unblockButton) {
    const userId = Number(unblockButton.dataset.adminUnblock);
    if (!userId) return;
    await api("/api/admin/unblock", {
      method: "POST",
      body: JSON.stringify({ user_id: userId }),
    });
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
  const result = await api("/api/admin/allow", {
    method: "POST",
    body: JSON.stringify({ user_id: userId }),
  });
  $("adminUserInput").value = "";
  await reloadAdminUsers();
  showToast(result.message || "User qo'shildi");
});

$("completedToggleButton").addEventListener("click", () => {
  if ((state.completed_reminders || []).length <= 3) return;
  showAllCompletedReminders = !showAllCompletedReminders;
  renderExtras();
  showToast(showAllCompletedReminders ? "Barcha yakunlangan eslatmalar" : "Qisqa ro'yxat");
  if (window.lucide) lucide.createIcons();
});

$("closeTransactionModal").addEventListener("click", closeTransactionEditor);
$("transactionModal").addEventListener("click", (event) => {
  if (event.target.id === "transactionModal") closeTransactionEditor();
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
  };
  if (id) body.id = id;
  body.occurred_at = id
    ? (state.transactions || []).find((row) => Number(row.id) === id)?.occurred_at
    : new Date().toISOString();
  if (demoMode) {
    if (id) {
      state.transactions = state.transactions.map((item) => (Number(item.id) === id ? { ...item, ...body, amount: Number(body.amount), amount_text: `${body.amount} so'm` } : item));
    } else {
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

$("saveDailyLimitButton").addEventListener("click", async () => {
  const amount = $("dailyLimitInput").value.trim();
  if (demoMode) {
    state.settings.daily_expense_limit = Number(amount.replace(/\D/g, "")) || 0;
    state.settings.daily_expense_limit_text = state.settings.daily_expense_limit ? `${state.settings.daily_expense_limit} so'm` : "Belgilanmagan";
    renderFinance();
    showToast("Telegram orqali ochilganda saqlanadi");
    return;
  }
  await api("/api/settings/daily-limit", {
    method: "POST",
    body: JSON.stringify({ amount }),
  });
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
  await api("/api/category-limits/set", {
    method: "POST",
    body: JSON.stringify({ category, amount }),
  });
  $("categoryLimitNameInput").value = "";
  $("categoryLimitAmountInput").value = "";
  await loadDashboard();
  showToast("Kategoriya limiti saqlandi");
});

$("dailyReportToggleButton").addEventListener("click", async () => {
  const enabled = !Boolean(state.settings?.daily_report_enabled);
  if (demoMode) {
    state.settings.daily_report_enabled = enabled;
    renderFinance();
    showToast("Telegram orqali ochilganda saqlanadi");
    return;
  }
  await api("/api/settings/daily-report", {
    method: "POST",
    body: JSON.stringify({ enabled }),
  });
  await loadDashboard();
  showToast(enabled ? "Kunlik hisobot yoqildi" : "Kunlik hisobot o'chirildi");
});

$("exportCsvButton").addEventListener("click", async () => {
  if (demoMode) {
    showToast("CSV export Telegram ichida ishlaydi");
    return;
  }
  const response = await fetch("/api/export/transactions.csv", { headers: telegramHeaders() });
  if (!response.ok) throw new Error(await response.text());
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "assistant-transactions.csv";
  document.body.append(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
  showToast("CSV tayyor");
});

$("togglePrayerButton").addEventListener("click", async () => {
  if (demoMode) {
    const next = !state.prayer.enabled;
    state.prayer.enabled = next;
    state.prayer.times = state.prayer.times.map((item) => ({
      ...item,
      enabled: item.can_notify ? next : false,
    }));
    renderExtras();
    showToast("Telegram orqali ochilganda saqlanadi");
    return;
  }
  await api("/api/prayer/toggle", {
    method: "POST",
    body: JSON.stringify({ enabled: !state.prayer.enabled }),
  });
  await loadDashboard();
  showToast("Namoz eslatmasi yangilandi");
});

$("leadTimeOptions").addEventListener("click", async (event) => {
  const button = event.target.closest("[data-lead-minutes]");
  if (!button) return;
  const minutes = Number(button.dataset.leadMinutes);
  if (demoMode) {
    state.prayer.minutes_before = minutes;
    renderPrayer();
    showToast("Telegram orqali ochilganda saqlanadi");
    return;
  }
  await api("/api/prayer/lead-time", {
    method: "POST",
    body: JSON.stringify({ minutes }),
  });
  await loadDashboard();
  showToast(`${minutes} daqiqa oldin eslatish saqlandi`);
});

$("prayerTimes").addEventListener("click", async (event) => {
  const button = event.target.closest("[data-prayer-key]");
  if (!button || button.disabled) return;
  const key = button.dataset.prayerKey;
  const item = state.prayer.times.find((row) => row.key === key);
  if (!item) return;
  const enabled = !item.enabled;
  if (demoMode) {
    item.enabled = enabled;
    state.prayer.enabled = state.prayer.times.some((row) => row.can_notify && row.enabled);
    renderExtras();
    showToast("Telegram orqali ochilganda saqlanadi");
    return;
  }
  await api("/api/prayer/key", {
    method: "POST",
    body: JSON.stringify({ key, enabled }),
  });
  await loadDashboard();
  showToast(`${item.name} eslatmasi ${enabled ? "yoqildi" : "o'chirildi"}`);
});

$("citySelect").addEventListener("change", async (event) => {
  if (demoMode) {
    state.prayer.city = event.target.value;
    renderExtras();
    showToast("Telegram orqali ochilganda saqlanadi");
    return;
  }
  await api("/api/prayer/city", {
    method: "POST",
    body: JSON.stringify({ city: event.target.value }),
  });
  await loadDashboard();
  showToast("Shahar yangilandi");
});

$("themeToggleButton").addEventListener("click", () => {
  const current = localStorage.getItem("assistant_theme") === "light" ? "light" : "dark";
  applyTheme(current === "light" ? "dark" : "light");
});

if (tg) {
  tg.ready();
  tg.expand();
}

applyTheme(localStorage.getItem("assistant_theme") || "dark");
loadDashboard();
