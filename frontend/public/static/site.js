(() => {
  const i18n = window.FrequencyI18n;
  if (!i18n) return;
  i18n.captureStatic();
  let locale = i18n.initialLocale();
  const whatsappNumber = "59175443696";
  const savedCountry = (() => { try { return localStorage.getItem("frequency.sales.country"); } catch { return null; } })();
  const countrySelect = document.querySelector("#sales-country");
  const status = document.querySelector("#sales-route-status");
  const planNames = { essencial: "Essencial", profissional: "Profissional", premium: "Premium" };
  const planPrices = {
    essencial: { regular: 350, promo: 250 },
    profissional: { regular: 500, promo: 350 },
    premium: { regular: 650, promo: 500 },
  };
  // Os valores comerciais continuam definidos em BOB. Para BRL e USD, a tela
  // usa uma cotação de referência e arredonda sempre para o próximo múltiplo de 10.
  const BOB_TO_BRL_FALLBACK = 0.4281;
  const BOB_TO_USD_FALLBACK = 0.0839;
  const BOB_TO_BRL_CACHE = "frequency.sales.bob-brl";
  let bobToBrlRate = BOB_TO_BRL_FALLBACK;
  let bobToUsdRate = BOB_TO_USD_FALLBACK;
  const whatsappMessages = {
    "pt-BR": (plan) => `Olá, quero conhecer o plano ${plan} do Frequency.`,
    "es-BO": (plan) => `Hola, quiero conocer el plan ${plan} de Frequency.`,
    "en-US": (plan) => `Hello, I want to learn about the ${plan} plan from Frequency.`,
    "zh-CN": (plan) => `你好，我想了解 Frequency 的${plan}套餐。`,
    "hi-IN": (plan) => `नमस्ते, मुझे Frequency की ${plan} योजना के बारे में जानना है।`,
  };
  const copy = {
    whatsapp: "Falar no WhatsApp",
    checkout: "Contratar este plano",
    bolivia: "Na Bolívia, seguimos pelo WhatsApp para confirmar sua contratação.",
    online: "Para este país, você pode criar sua conta e seguir para o checkout online.",
  };
  const translated = (key) => i18n.translate(locale, copy[key]);
  const roundUpToTen = (value) => Math.ceil(value / 10) * 10;
  const priceInBrl = (value) => roundUpToTen(value * bobToBrlRate);
  const loadBrlRate = async () => {
    const today = new Date().toISOString().slice(0, 10);
    try {
      const cached = JSON.parse(localStorage.getItem(BOB_TO_BRL_CACHE) || "null");
      if (cached?.date === today) {
        if (Number(cached.BRL || cached.rate) > 0) bobToBrlRate = Number(cached.BRL || cached.rate);
        if (Number(cached.USD) > 0) bobToUsdRate = Number(cached.USD);
      }
    } catch { /* A cotação padrão mantém a página disponível offline. */ }
    try {
      const response = await fetch("https://open.er-api.com/v6/latest/BOB", { cache: "no-store" });
      const data = await response.json();
      const brl = Number(data?.rates?.BRL);
      const usd = Number(data?.rates?.USD);
      if (response.ok && Number.isFinite(brl) && brl > 0) {
        bobToBrlRate = brl;
        if (Number.isFinite(usd) && usd > 0) bobToUsdRate = usd;
        try { localStorage.setItem(BOB_TO_BRL_CACHE, JSON.stringify({ date: today, BRL: bobToBrlRate, USD: bobToUsdRate })); } catch { /* Optional cache. */ }
      }
    } catch { /* Keep the last valid rate when the provider is unavailable. */ }
    updateSalesCurrency(countrySelect?.value || "BR");
  };
  const updateSalesCurrency = (country) => {
    const currency = country === "BO" ? "Bs" : country === "BR" ? "R$" : "US$";
    const numberLocale = country === "BO" ? "es-BO" : country === "BR" ? "pt-BR" : "en-US";
    document.querySelectorAll("[data-plan-card]").forEach((card) => {
      const prices = planPrices[card.dataset.planCard];
      if (!prices) return;
      const regular = card.querySelector(".price del");
      const promo = card.querySelector(".price strong");
      const values = country === "BR"
        ? { regular: priceInBrl(prices.regular), promo: priceInBrl(prices.promo) }
        : country === "OTHER"
          ? { regular: roundUpToTen(prices.regular * bobToUsdRate), promo: roundUpToTen(prices.promo * bobToUsdRate) }
          : prices;
      const format = (value) => `${currency} ${new Intl.NumberFormat(numberLocale, { maximumFractionDigits: 0 }).format(value)}`;
      if (regular) regular.textContent = format(values.regular);
      if (promo) promo.textContent = format(values.promo);
    });
  };
  const countryFromLocale = () => locale === "es-BO" ? "BO" : "BR";
  const syncCountryWithLocale = () => {
    if (!countrySelect) return;
    if (locale === "pt-BR") countrySelect.value = "BR";
    if (locale === "es-BO") countrySelect.value = "BO";
  };
  const updateSalesLinks = () => {
    const country = countrySelect?.value || "BR";
    const bolivia = country === "BO";
    updateSalesCurrency(country);
    document.querySelectorAll("[data-plan-link]").forEach((link) => {
      const plan = link.dataset.plan || "profissional";
      if (bolivia) {
        const message = (whatsappMessages[locale] || whatsappMessages["en-US"])(planNames[plan]);
        link.href = `https://web.whatsapp.com/send/?phone=${whatsappNumber}&text=${encodeURIComponent(message)}`;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        link.textContent = translated("whatsapp");
        link.classList.add("is-whatsapp");
      } else {
        link.href = `/app?cadastro=1&plano=${encodeURIComponent(plan)}`;
        link.removeAttribute("target");
        link.removeAttribute("rel");
        link.textContent = translated("checkout");
        link.classList.remove("is-whatsapp");
      }
    });
    if (status) status.textContent = i18n.translate(locale, bolivia ? copy.bolivia : copy.online);
    try { localStorage.setItem("frequency.sales.country", country); } catch { /* Optional preference. */ }
  };
  const render = () => {
    document.documentElement.lang = locale;
    document.title = i18n.translate(locale, "Frequency Gym — Software de gestión para gimnasios");
    i18n.renderStatic((text) => i18n.translate(locale, text));
    const select = document.querySelector("#site-language");
    if (select) select.value = locale;
    updateSalesLinks();
  };
  if (countrySelect) countrySelect.value = ["BR", "BO", "OTHER"].includes(savedCountry) ? savedCountry : countryFromLocale();
  syncCountryWithLocale();
  document.querySelector("#site-language")?.addEventListener("change", (event) => {
    locale = event.target.value;
    i18n.saveLocale(locale);
    syncCountryWithLocale();
    render();
  });
  countrySelect?.addEventListener("change", updateSalesLinks);
  render();
  loadBrlRate();
})();
