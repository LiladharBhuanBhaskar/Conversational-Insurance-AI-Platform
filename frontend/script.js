const API_BASE = window.location.origin;

const storage = {
  token: "insurance_token",
  policyNumber: "insurance_policy_number",
  user: "insurance_user",
};
const chatStorageKeys = [
  "insurance_chat_history",
  "chat_history",
  "chat_messages",
];
const welcomeMessage =
  "Hello, I am your insurance assistant. Login for account-linked help, or provide policy number to continue.";

const PRODUCT_SKELETON_COUNT = 3;

const currencyFormatter = new Intl.NumberFormat(undefined, {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 0,
});

const timeFormatter = new Intl.DateTimeFormat(undefined, {
  hour: "numeric",
  minute: "2-digit",
});

const state = {
  token: localStorage.getItem(storage.token) || "",
  policyNumber: localStorage.getItem(storage.policyNumber) || "",
  user: (() => {
    try {
      return JSON.parse(localStorage.getItem(storage.user) || "null");
    } catch {
      return null;
    }
  })(),
  products: [],
  loadingProducts: false,
};

const el = {
  chatWindow: document.getElementById("chatWindow"),
  chatForm: document.getElementById("chatForm"),
  chatInput: document.getElementById("chatInput"),
  policyInput: document.getElementById("policyInput"),
  policyHint: document.getElementById("policyHint"),
  sessionStatus: document.getElementById("sessionStatus"),
  activePolicyBadge: document.getElementById("activePolicyBadge"),
  productsList: document.getElementById("productsList"),

  openAuthBtn: document.getElementById("openAuthBtn"),
  profileBtn: document.getElementById("profileBtn"),
  logoutBtn: document.getElementById("logoutBtn"),
  refreshProductsBtn: document.getElementById("refreshProductsBtn"),
  showPlansChatBtn: document.getElementById("showPlansChatBtn"),

  authModal: document.getElementById("authModal"),
  showLoginBtn: document.getElementById("showLoginBtn"),
  showSignupBtn: document.getElementById("showSignupBtn"),
  closeModalBtn: document.getElementById("closeModalBtn"),
  loginForm: document.getElementById("loginForm"),
  signupForm: document.getElementById("signupForm"),

  profileModal: document.getElementById("profileModal"),
  closeProfileModalBtn: document.getElementById("closeProfileModalBtn"),
  profileInfoName: document.getElementById("profileInfoName"),
  profileInfoEmail: document.getElementById("profileInfoEmail"),
  editProfileForm: document.getElementById("editProfileForm"),
  changePasswordForm: document.getElementById("changePasswordForm"),
  profileNameInput: document.getElementById("profileNameInput"),
  profileEmailInput: document.getElementById("profileEmailInput"),
  currentPasswordInput: document.getElementById("currentPasswordInput"),
  newPasswordInput: document.getElementById("newPasswordInput"),
};

function setState(partial) {
  Object.assign(state, partial);
  persistState();
  renderGlobalUI();
}

function persistState() {
  if (state.token) {
    localStorage.setItem(storage.token, state.token);
  } else {
    localStorage.removeItem(storage.token);
  }

  if (state.policyNumber) {
    localStorage.setItem(storage.policyNumber, state.policyNumber);
  } else {
    localStorage.removeItem(storage.policyNumber);
  }

  if (state.user) {
    localStorage.setItem(storage.user, JSON.stringify(state.user));
  } else {
    localStorage.removeItem(storage.user);
  }
}

function parseError(payload, fallback) {
  if (!payload) {
    return fallback;
  }
  if (typeof payload.detail === "string") {
    return payload.detail;
  }
  return fallback;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function formatMoney(value) {
  const num = Number(value);
  if (!Number.isFinite(num)) {
    return String(value ?? "-");
  }
  return currencyFormatter.format(num);
}

function timeLabel() {
  return timeFormatter.format(new Date());
}

function scrollChatToBottom() {
  el.chatWindow.scrollTop = el.chatWindow.scrollHeight;
}

async function apiFetch(path, options = {}) {
  const headers = options.headers || {};
  if (options.auth && state.token) {
    headers.Authorization = `Bearer ${state.token}`;
  }
  if (options.json) {
    headers["Content-Type"] = "application/json";
  }

  const response = await fetch(`${API_BASE}${path}`, {
    method: options.method || "GET",
    headers,
    body: options.body,
  });

  let payload = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }

  if (!response.ok) {
    throw new Error(parseError(payload, `${options.method || "GET"} ${path} failed`));
  }
  return payload;
}

function openModal() {
  el.authModal.classList.remove("hidden");
}

function closeModal() {
  el.authModal.classList.add("hidden");
}

function openProfileModal() {
  if (el.profileModal) {
    el.profileModal.classList.remove("hidden");
  }
}

function closeProfileModal() {
  if (el.profileModal) {
    el.profileModal.classList.add("hidden");
  }
}

function showLoginTab() {
  el.showLoginBtn.classList.add("active");
  el.showSignupBtn.classList.remove("active");
  el.loginForm.classList.remove("hidden");
  el.signupForm.classList.add("hidden");
}

function showSignupTab() {
  el.showSignupBtn.classList.add("active");
  el.showLoginBtn.classList.remove("active");
  el.signupForm.classList.remove("hidden");
  el.loginForm.classList.add("hidden");
}

function initials(name) {
  if (!name) {
    return "U";
  }
  return name
    .trim()
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part[0].toUpperCase())
    .join("");
}

function avatarLabel(type) {
  if (type === "user") {
    return initials(state.user?.name || "You");
  }
  if (type === "error") {
    return "!";
  }
  return "AI";
}

function addMessage(type, text) {
  const row = document.createElement("div");
  row.className = `message-row ${type}`;

  const avatar = document.createElement("div");
  avatar.className = "message-avatar";
  avatar.textContent = avatarLabel(type);

  const card = document.createElement("div");
  card.className = `message ${type}`;

  const content = document.createElement("p");
  content.className = "message-text";
  content.textContent = text;

  const meta = document.createElement("span");
  meta.className = "message-meta";
  meta.textContent = timeLabel();

  card.append(content, meta);
  row.append(avatar, card);

  el.chatWindow.appendChild(row);
  scrollChatToBottom();
  return row;
}

function addTypingIndicator() {
  const row = document.createElement("div");
  row.className = "message-row bot typing-row";

  const avatar = document.createElement("div");
  avatar.className = "message-avatar";
  avatar.textContent = "AI";

  const card = document.createElement("div");
  card.className = "message bot";
  card.setAttribute("role", "status");
  card.setAttribute("aria-live", "polite");

  const dots = document.createElement("div");
  dots.className = "typing";
  dots.innerHTML = "<span></span><span></span><span></span>";

  const label = document.createElement("span");
  label.className = "typing-label";
  label.textContent = "InsureAssist is typing";

  card.append(dots, label);
  row.append(avatar, card);

  el.chatWindow.appendChild(row);
  scrollChatToBottom();
  return row;
}

function resetChatSessionUI() {
  el.chatWindow.innerHTML = "";
}

function clearClientChatHistory() {
  const storages = [localStorage, sessionStorage];
  for (const store of storages) {
    for (const key of chatStorageKeys) {
      store.removeItem(key);
    }
    const keys = Object.keys(store);
    for (const key of keys) {
      if (key.startsWith("insurance_chat_") || key.startsWith("chat_")) {
        store.removeItem(key);
      }
    }
  }
}

function hydrateProfileModal(user) {
  const safeUser = user || {};
  const name = safeUser.name || "-";
  const email = safeUser.email || "-";

  if (el.profileInfoName) {
    el.profileInfoName.textContent = `Name: ${name}`;
  }
  if (el.profileInfoEmail) {
    el.profileInfoEmail.textContent = `Email: ${email}`;
  }
  if (el.profileNameInput) {
    el.profileNameInput.value = safeUser.name || "";
  }
  if (el.profileEmailInput) {
    el.profileEmailInput.value = safeUser.email || "";
  }
  if (el.currentPasswordInput) {
    el.currentPasswordInput.value = "";
  }
  if (el.newPasswordInput) {
    el.newPasswordInput.value = "";
  }
}

async function refreshProfileState() {
  if (!state.token) {
    return null;
  }

  const payload = await apiFetch("/profile", {
    method: "GET",
    auth: true,
  });

  if (payload?.user) {
    setState({ user: payload.user });
    hydrateProfileModal(payload.user);
    return payload.user;
  }
  return null;
}

function showFreshWelcomeMessage() {
  addMessage("bot", welcomeMessage);
}

async function logout() {
  const hadToken = Boolean(state.token);

  if (hadToken) {
    try {
      await apiFetch("/logout", {
        method: "POST",
        auth: true,
      });
    } catch {
      // Ignore backend failure, still logout locally
    }
  }

  // Clear all client session data
  clearClientChatHistory();
  closeProfileModal();
  resetChatSessionUI();

  // Reset app state
  setState({ token: "", user: null, policyNumber: "" });
  hydrateProfileModal(null);

  // FORCE full fresh session (important for security + demo)
  window.location.reload();
}

function renderAuthUI() {
  const isAuthed = Boolean(state.token);
  el.openAuthBtn.classList.toggle("hidden", isAuthed);
  el.profileBtn.classList.toggle("hidden", !isAuthed);
  el.logoutBtn.classList.toggle("hidden", !isAuthed);

  if (isAuthed) {
    const name = state.user?.name || "Authenticated User";
    el.profileBtn.textContent = `${initials(name)}  ${name}`;
    el.profileBtn.setAttribute("aria-label", `Profile: ${name}`);
    el.sessionStatus.textContent = `Authenticated as ${name}`;
  } else {
    el.sessionStatus.textContent = "Not authenticated";
    el.profileBtn.textContent = "";
    el.profileBtn.removeAttribute("aria-label");
  }
}

function renderPolicyUI() {
  el.policyInput.value = (state.policyNumber || "").toUpperCase();
  el.policyHint.textContent = state.policyNumber
    ? `Active policy: ${state.policyNumber}`
    : "Login or provide a valid policy number.";
  el.activePolicyBadge.textContent = state.policyNumber
    ? `Policy: ${state.policyNumber}`
    : "No policy selected";
}

function renderProductSkeletons() {
  return Array.from({ length: PRODUCT_SKELETON_COUNT })
    .map(
      () => `
        <article class="product-item skeleton-card" aria-hidden="true">
          <div class="product-head">
            <div>
              <div class="skeleton-line w70"></div>
              <div class="skeleton-line w52"></div>
              <div class="skeleton-line w45"></div>
            </div>
            <div class="skeleton-pill"></div>
          </div>
          <div class="skeleton-addon"></div>
          <div class="skeleton-addon"></div>
          <div class="skeleton-button"></div>
        </article>
      `
    )
    .join("");
}

function renderProducts() {
  el.productsList.setAttribute("aria-busy", state.loadingProducts ? "true" : "false");

  if (state.loadingProducts) {
    el.productsList.innerHTML = renderProductSkeletons();
    return;
  }

  if (!state.products.length) {
    el.productsList.innerHTML = "<p class='product-empty'>No products available right now.</p>";
    return;
  }

  const cards = state.products
    .map((product) => {
      const productCode = escapeHtml(product.product_code);
      const productName = escapeHtml(product.name);
      const productType = escapeHtml(product.insurance_type);
      const coverageLimit = formatMoney(product.coverage_limit);
      const premium = formatMoney(product.premium);

      const addons = (product.addons || [])
        .map((addon) => {
          const addonCode = escapeHtml(addon.addon_code);
          const addonName = escapeHtml(addon.name);
          const addonPremium = formatMoney(addon.addon_premium);
          return `
            <label class="addon-pill">
              <input type="checkbox" data-addon-code="${addonCode}" />
              <span>${addonName} (${addonCode}) +${addonPremium}</span>
            </label>
          `;
        })
        .join("");

      return `
        <article class="product-item" data-product-code="${productCode}">
          <div class="product-head">
            <div>
              <div class="product-title">${productName}</div>
              <div class="product-meta">
                ${productCode}<br/>
                Coverage: ${coverageLimit}<br/>
                Premium: ${premium}
              </div>
            </div>
            <span class="badge">${productType}</span>
          </div>
          <div class="addon-list">${addons || "<div class='product-meta'>No add-ons.</div>"}</div>
          <button class="btn btn-primary buy-btn" data-buy-product="${productCode}">Buy Policy</button>
        </article>
      `;
    })
    .join("");

  el.productsList.innerHTML = cards;
}

function renderGlobalUI() {
  renderAuthUI();
  renderPolicyUI();
  renderProducts();
}

async function loadProducts() {
  setState({ loadingProducts: true });
  try {
    const payload = await apiFetch("/products");
    setState({ products: payload.products || [], loadingProducts: false });
  } catch (error) {
    setState({ loadingProducts: false });
    addMessage("error", `Unable to load products: ${error.message}`);
  }
}

async function verifyPolicy(policyNumber) {
  if (!policyNumber) {
    return;
  }

  try {
    const policy = await apiFetch(`/policy/${encodeURIComponent(policyNumber)}`, {
      auth: Boolean(state.token),
    });
    setState({ policyNumber: policy.policy_number });
    addMessage(
      "bot",
      `Policy verified: ${policy.policy_number} (${policy.insurance_type}, status: ${policy.status}).`
    );
  } catch (error) {
    addMessage("error", `Policy verification failed: ${error.message}`);
  }
}

async function sendChatMessage(message) {
  const typing = addTypingIndicator();
  try {
    const payload = await apiFetch("/chat", {
      method: "POST",
      auth: Boolean(state.token),
      json: true,
      body: JSON.stringify({
        message,
        policy_number: state.policyNumber || null,
      }),
    });

    typing.remove();

    if (payload.policy_number) {
      setState({ policyNumber: payload.policy_number });
    }

    if (payload.booking_intent) {
      loadProducts();
    }

    addMessage("bot", payload.response || "No response generated.");
  } catch (error) {
    typing.remove();
    addMessage("error", error.message);
  }
}

async function buyPolicyFromCard(button) {
  const productCode = button.getAttribute("data-buy-product");
  if (!state.token) {
    addMessage("error", "Please login to buy a policy.");
    openModal();
    return;
  }

  const card = button.closest(".product-item");
  const addonCodes = Array.from(card.querySelectorAll("input[data-addon-code]:checked")).map((input) =>
    input.getAttribute("data-addon-code")
  );

  button.disabled = true;
  const original = button.textContent;
  button.textContent = "Processing...";

  try {
    const payload = await apiFetch("/buy-policy", {
      method: "POST",
      auth: true,
      json: true,
      body: JSON.stringify({
        product_code: productCode,
        addon_codes: addonCodes,
      }),
    });

    const policy = payload.policy;
    setState({ policyNumber: policy.policy_number });
    addMessage(
      "bot",
      `Purchase completed. New policy ${policy.policy_number} is now active under ${policy.insurance_type} insurance.`
    );
  } catch (error) {
    addMessage("error", `Purchase failed: ${error.message}`);
  } finally {
    button.disabled = false;
    button.textContent = original;
  }
}

function bindEvents() {
  el.openAuthBtn.addEventListener("click", openModal);
  el.closeModalBtn.addEventListener("click", closeModal);
  el.showLoginBtn.addEventListener("click", showLoginTab);
  el.showSignupBtn.addEventListener("click", showSignupTab);

  el.profileBtn.addEventListener("click", () => {
    if (!state.token) {
      openModal();
      return;
    }

    refreshProfileState()
      .catch(() => {
        hydrateProfileModal(state.user);
      })
      .finally(() => {
        openProfileModal();
      });
  });

  if (el.closeProfileModalBtn) {
    el.closeProfileModalBtn.addEventListener("click", closeProfileModal);
  }

  el.logoutBtn.addEventListener("click", () => {
    logout();
  });

  el.refreshProductsBtn.addEventListener("click", loadProducts);

  el.showPlansChatBtn.addEventListener("click", async () => {
    const prompt = "show available plans";
    addMessage("user", prompt);
    await sendChatMessage(prompt);
  });

  el.chatForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const message = el.chatInput.value.trim();
    if (!message) {
      return;
    }

    const submitButton = el.chatForm.querySelector("button[type='submit']");
    addMessage("user", message);
    el.chatInput.value = "";
    el.chatInput.disabled = true;
    submitButton.disabled = true;

    try {
      await sendChatMessage(message);
    } finally {
      el.chatInput.disabled = false;
      submitButton.disabled = false;
      el.chatInput.focus();
    }
  });

  document.getElementById("setPolicyBtn").addEventListener("click", async () => {
    const policyNumber = el.policyInput.value.trim().toUpperCase();
    if (!policyNumber) {
      addMessage("error", "Enter a policy number first.");
      return;
    }
    await verifyPolicy(policyNumber);
  });

  el.loginForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const email = document.getElementById("loginEmail").value.trim();
    const password = document.getElementById("loginPassword").value.trim();

    try {
      const payload = await apiFetch("/login", {
        method: "POST",
        json: true,
        body: JSON.stringify({ email, password }),
      });
      setState({ token: payload.access_token, user: payload.user });
      closeModal();
      addMessage("bot", `Welcome back, ${payload.user.name}. You can ask about policy, plans, or add-ons.`);
    } catch (error) {
      addMessage("error", error.message);
    }
  });

  el.signupForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const name = document.getElementById("signupName").value.trim();
    const email = document.getElementById("signupEmail").value.trim();
    const password = document.getElementById("signupPassword").value.trim();

    try {
      const payload = await apiFetch("/signup", {
        method: "POST",
        json: true,
        body: JSON.stringify({ name, email, password }),
      });
      setState({ token: payload.access_token, user: payload.user });
      closeModal();
      addMessage("bot", `Account created for ${payload.user.name}. Start by selecting a policy or buying one.`);
    } catch (error) {
      addMessage("error", error.message);
    }
  });

  if (el.editProfileForm) {
    el.editProfileForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (!state.token) {
        addMessage("error", "Please login first.");
        return;
      }

      const name = (el.profileNameInput?.value || "").trim();
      const email = (el.profileEmailInput?.value || "").trim();
      if (!name || !email) {
        addMessage("error", "Name and email are required.");
        return;
      }

      const submitButton = el.editProfileForm.querySelector("button[type='submit']");
      if (submitButton) {
        submitButton.disabled = true;
      }

      try {
        const payload = await apiFetch("/profile", {
          method: "PUT",
          auth: true,
          json: true,
          body: JSON.stringify({ name, email }),
        });
        if (payload?.user) {
          setState({ user: payload.user });
          hydrateProfileModal(payload.user);
        }
        addMessage("bot", payload?.message || "Profile updated successfully.");
      } catch (error) {
        addMessage("error", `Profile update failed: ${error.message}`);
      } finally {
        if (submitButton) {
          submitButton.disabled = false;
        }
      }
    });
  }

  if (el.changePasswordForm) {
    el.changePasswordForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (!state.token) {
        addMessage("error", "Please login first.");
        return;
      }

      const currentPassword = (el.currentPasswordInput?.value || "").trim();
      const newPassword = (el.newPasswordInput?.value || "").trim();
      if (!currentPassword || !newPassword) {
        addMessage("error", "Both current and new password are required.");
        return;
      }

      const submitButton = el.changePasswordForm.querySelector("button[type='submit']");
      if (submitButton) {
        submitButton.disabled = true;
      }

      try {
        const payload = await apiFetch("/change-password", {
          method: "POST",
          auth: true,
          json: true,
          body: JSON.stringify({
            current_password: currentPassword,
            new_password: newPassword,
          }),
        });
        if (el.currentPasswordInput) {
          el.currentPasswordInput.value = "";
        }
        if (el.newPasswordInput) {
          el.newPasswordInput.value = "";
        }
        addMessage("bot", payload?.message || "Password changed successfully.");
      } catch (error) {
        addMessage("error", `Password change failed: ${error.message}`);
      } finally {
        if (submitButton) {
          submitButton.disabled = false;
        }
      }
    });
  }

  el.productsList.addEventListener("click", async (event) => {
    const button = event.target.closest("button[data-buy-product]");
    if (!button) {
      return;
    }
    await buyPolicyFromCard(button);
  });
}

window.addEventListener("DOMContentLoaded", async () => {
  bindEvents();
  renderGlobalUI();

  addMessage(
    "bot",
    welcomeMessage
  );

  if (!state.token) {
    openModal();
  } else {
    addMessage("bot", "Authenticated session detected. Ask anything about claims, coverage, plans, or add-ons.");
  }

  if (state.policyNumber) {
    addMessage("bot", `Using active policy number: ${state.policyNumber}`);
  }

  if (state.token) {
    refreshProfileState().catch(() => {
      hydrateProfileModal(state.user);
    });
  } else {
    hydrateProfileModal(null);
  }

  await loadProducts();
});
