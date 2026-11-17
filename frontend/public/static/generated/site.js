"use strict";
const translations = window.FrequencyI18n;
if (translations) {
    const service = translations;
    service.captureStatic();
    let locale = service.initialLocale();
    const whatsappNumber = "59175443696";
    const planNames = {
        essencial: "Essencial",
        profissional: "Profissional",
        premium: "Premium",
    };
    const planPrices = {
        essencial: { regular: 350, promo: 250 },
        profissional: { regular: 500, promo: 350 },
        premium: { regular: 650, promo: 500 },
    };
    const copy = {
        whatsapp: "Falar no WhatsApp",
        checkout: "Contratar este plano",
        bolivia: "Na Bolívia, seguimos pelo WhatsApp para confirmar sua contratação.",
        online: "Para este país, você pode criar sua conta e seguir para o checkout online.",
    };
    const whatsappMessages = {
        "pt-BR": (plan) => `Olá, quero conhecer o plano ${plan} do Frequency.`,
        "es-BO": (plan) => `Hola, quiero conocer el plan ${plan} de Frequency.`,
        "en-US": (plan) => `Hello, I want to learn about the ${plan} plan from Frequency.`,
        "zh-CN": (plan) => `你好，我想了解 Frequency 的${plan}套餐。`,
        "hi-IN": (plan) => `नमस्ते, मुझे Frequency की ${plan} योजना के बारे में जानना है।`,
    };
    const BOB_TO_BRL_FALLBACK = 0.4281;
    const BOB_TO_USD_FALLBACK = 0.0839;
    const BOB_TO_BRL_CACHE = "frequency.sales.bob-brl";
    let bobToBrlRate = BOB_TO_BRL_FALLBACK;
    let bobToUsdRate = BOB_TO_USD_FALLBACK;
    const query = (selector) => document.querySelector(selector);
    const savedCountry = readStorage("frequency.sales.country");
    const countrySelect = query("#sales-country");
    const status = query("#sales-route-status");
    function readStorage(key) {
        try {
            return localStorage.getItem(key);
        }
        catch {
            return null;
        }
    }
    function writeStorage(key, value) {
        try {
            localStorage.setItem(key, value);
        }
        catch {
            // Storage is an optional enhancement; the page must remain usable offline.
        }
    }
    function asCountry(value) {
        return value === "BR" || value === "BO" || value === "OTHER" ? value : null;
    }
    function asPlanKey(value) {
        return value === "essencial" || value === "profissional" || value === "premium" ? value : "profissional";
    }
    function roundUpToTen(value) {
        return Math.ceil(value / 10) * 10;
    }
    function formatPrice(value, country) {
        const currency = country === "BO" ? "Bs" : country === "BR" ? "R$" : "US$";
        const numberLocale = country === "BO" ? "es-BO" : country === "BR" ? "pt-BR" : "en-US";
        return `${currency} ${new Intl.NumberFormat(numberLocale, { maximumFractionDigits: 0 }).format(value)}`;
    }
    function updateSalesCurrency(country) {
        document.querySelectorAll("[data-plan-card]").forEach((card) => {
            const plan = asPlanKey(card.dataset.planCard);
            const prices = planPrices[plan];
            const regular = card.querySelector(".price del");
            const promo = card.querySelector(".price strong");
            const values = country === "BR"
                ? { regular: roundUpToTen(prices.regular * bobToBrlRate), promo: roundUpToTen(prices.promo * bobToBrlRate) }
                : country === "OTHER"
                    ? { regular: roundUpToTen(prices.regular * bobToUsdRate), promo: roundUpToTen(prices.promo * bobToUsdRate) }
                    : prices;
            if (regular)
                regular.textContent = formatPrice(values.regular, country);
            if (promo)
                promo.textContent = formatPrice(values.promo, country);
        });
    }
    function countryFromLocale() {
        return locale === "es-BO" ? "BO" : "BR";
    }
    function syncCountryWithLocale() {
        if (!countrySelect)
            return;
        if (locale === "pt-BR")
            countrySelect.value = "BR";
        if (locale === "es-BO")
            countrySelect.value = "BO";
    }
    function translated(key) {
        return service.translate(locale, copy[key]);
    }
    function updateSalesLinks() {
        const country = asCountry(countrySelect?.value ?? null) ?? "BR";
        const bolivia = country === "BO";
        updateSalesCurrency(country);
        document.querySelectorAll("[data-plan-link]").forEach((link) => {
            const plan = asPlanKey(link.dataset.plan);
            if (bolivia) {
                const message = whatsappMessages[locale](planNames[plan]);
                link.href = `https://web.whatsapp.com/send/?phone=${whatsappNumber}&text=${encodeURIComponent(message)}`;
                link.target = "_blank";
                link.rel = "noopener noreferrer";
                link.textContent = translated("whatsapp");
                link.classList.add("is-whatsapp");
            }
            else {
                link.href = `/app?cadastro=1&plano=${encodeURIComponent(plan)}`;
                link.removeAttribute("target");
                link.removeAttribute("rel");
                link.textContent = translated("checkout");
                link.classList.remove("is-whatsapp");
            }
        });
        if (status)
            status.textContent = service.translate(locale, bolivia ? copy.bolivia : copy.online);
        writeStorage("frequency.sales.country", country);
    }
    function render() {
        document.documentElement.lang = locale;
        document.title = service.translate(locale, "Frequency Gym — Software de gestión para gimnasios");
        service.renderStatic((text) => service.translate(locale, text));
        const languageSelect = query("#site-language");
        if (languageSelect)
            languageSelect.value = locale;
        updateSalesLinks();
    }
    async function loadExchangeRates() {
        const today = new Date().toISOString().slice(0, 10);
        try {
            const cached = JSON.parse(readStorage(BOB_TO_BRL_CACHE) ?? "null");
            if (cached?.date === today) {
                if (Number(cached.BRL ?? cached.rate) > 0)
                    bobToBrlRate = Number(cached.BRL ?? cached.rate);
                if (Number(cached.USD) > 0)
                    bobToUsdRate = Number(cached.USD);
            }
        }
        catch {
            // The fallback rate keeps the public page available without storage.
        }
        try {
            const response = await fetch("https://open.er-api.com/v6/latest/BOB", { cache: "no-store" });
            const data = await response.json();
            if (!response.ok || typeof data !== "object" || data === null || !("rates" in data))
                return;
            const rates = data.rates;
            if (typeof rates !== "object" || rates === null)
                return;
            const brl = Number(Reflect.get(rates, "BRL"));
            const usd = Number(Reflect.get(rates, "USD"));
            if (!Number.isFinite(brl) || brl <= 0)
                return;
            bobToBrlRate = brl;
            if (Number.isFinite(usd) && usd > 0)
                bobToUsdRate = usd;
            writeStorage(BOB_TO_BRL_CACHE, JSON.stringify({ date: today, BRL: bobToBrlRate, USD: bobToUsdRate }));
        }
        catch {
            // Keep the last valid rate when the provider is unavailable.
        }
        updateSalesCurrency(asCountry(countrySelect?.value ?? null) ?? "BR");
    }
    const initialCountry = asCountry(savedCountry) ?? countryFromLocale();
    if (countrySelect)
        countrySelect.value = initialCountry;
    syncCountryWithLocale();
    query("#site-language")?.addEventListener("change", (event) => {
        const nextLocale = event.target.value;
        if (!(nextLocale in whatsappMessages))
            return;
        locale = nextLocale;
        service.saveLocale(locale);
        syncCountryWithLocale();
        render();
    });
    countrySelect?.addEventListener("change", updateSalesLinks);
    render();
    // Exchange rates never block first paint or interaction.
    const schedule = (callback) => {
        if ("requestIdleCallback" in window) {
            window.requestIdleCallback(() => callback(), { timeout: 1800 });
        }
        else {
            setTimeout(callback, 1200);
        }
    };
    schedule(() => void loadExchangeRates());
}
