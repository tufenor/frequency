type Locale = "pt-BR" | "es-BO" | "en-US" | "zh-CN" | "hi-IN";
type Country = "BR" | "BO" | "OTHER";
type PlanKey = "essencial" | "profissional" | "premium";

interface TranslationService {
  captureStatic(): void;
  initialLocale(): Locale;
  translate(locale: Locale, text: string): string;
  saveLocale(locale: Locale): void;
  renderStatic(transform: (text: string) => string): void;
}

interface Window {
  FrequencyI18n?: TranslationService;
}

interface PlanPrice {
  regular: number;
  promo: number;
}

interface ExchangeCache {
  date: string;
  BRL?: number;
  USD?: number;
  rate?: number;
}

const translations = window.FrequencyI18n;
if (translations) {
  const service: TranslationService = translations;
  service.captureStatic();

  let locale: Locale = service.initialLocale();
  const whatsappNumber = "59175443696";
  const planNames: Record<PlanKey, string> = {
    essencial: "Essencial",
    profissional: "Profissional",
    premium: "Premium",
  };
  const planPrices: Record<PlanKey, PlanPrice> = {
    essencial: { regular: 350, promo: 250 },
    profissional: { regular: 500, promo: 350 },
    premium: { regular: 650, promo: 500 },
  };
  const copy = {
    whatsapp: "Falar no WhatsApp",
    checkout: "Contratar este plano",
    bolivia: "Na Bolívia, seguimos pelo WhatsApp para confirmar sua contratação.",
    online: "Para este país, você pode criar sua conta e seguir para o checkout online.",
  } as const;
  const whatsappMessages: Record<Locale, (plan: string) => string> = {
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

  const query = <T extends Element>(selector: string): T | null => document.querySelector<T>(selector);
  const savedCountry = readStorage("frequency.sales.country");
  const countrySelect = query<HTMLSelectElement>("#sales-country");
  const status = query<HTMLElement>("#sales-route-status");

  function readStorage(key: string): string | null {
    try {
      return localStorage.getItem(key);
    } catch {
      return null;
    }
  }

  function writeStorage(key: string, value: string): void {
    try {
      localStorage.setItem(key, value);
    } catch {
      // Storage is an optional enhancement; the page must remain usable offline.
    }
  }

  function asCountry(value: string | null): Country | null {
    return value === "BR" || value === "BO" || value === "OTHER" ? value : null;
  }

  function asPlanKey(value: string | undefined): PlanKey {
    return value === "essencial" || value === "profissional" || value === "premium" ? value : "profissional";
  }

  function roundUpToTen(value: number): number {
    return Math.ceil(value / 10) * 10;
  }

  function formatPrice(value: number, country: Country): string {
    const currency = country === "BO" ? "Bs" : country === "BR" ? "R$" : "US$";
    const numberLocale = country === "BO" ? "es-BO" : country === "BR" ? "pt-BR" : "en-US";
    return `${currency} ${new Intl.NumberFormat(numberLocale, { maximumFractionDigits: 0 }).format(value)}`;
  }

  function updateSalesCurrency(country: Country): void {
    document.querySelectorAll<HTMLElement>("[data-plan-card]").forEach((card) => {
      const plan = asPlanKey(card.dataset.planCard);
      const prices = planPrices[plan];
      const regular = card.querySelector<HTMLElement>(".price del");
      const promo = card.querySelector<HTMLElement>(".price strong");
      const values = country === "BR"
        ? { regular: roundUpToTen(prices.regular * bobToBrlRate), promo: roundUpToTen(prices.promo * bobToBrlRate) }
        : country === "OTHER"
          ? { regular: roundUpToTen(prices.regular * bobToUsdRate), promo: roundUpToTen(prices.promo * bobToUsdRate) }
          : prices;
      if (regular) regular.textContent = formatPrice(values.regular, country);
      if (promo) promo.textContent = formatPrice(values.promo, country);
    });
  }

  function countryFromLocale(): Country {
    return locale === "es-BO" ? "BO" : "BR";
  }

  function syncCountryWithLocale(): void {
    if (!countrySelect) return;
    if (locale === "pt-BR") countrySelect.value = "BR";
    if (locale === "es-BO") countrySelect.value = "BO";
  }

  function translated(key: keyof typeof copy): string {
    return service.translate(locale, copy[key]);
  }

  function updateSalesLinks(): void {
    const country = asCountry(countrySelect?.value ?? null) ?? "BR";
    const bolivia = country === "BO";
    updateSalesCurrency(country);
    document.querySelectorAll<HTMLAnchorElement>("[data-plan-link]").forEach((link) => {
      const plan = asPlanKey(link.dataset.plan);
      if (bolivia) {
        const message = whatsappMessages[locale](planNames[plan]);
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
    if (status) status.textContent = service.translate(locale, bolivia ? copy.bolivia : copy.online);
    writeStorage("frequency.sales.country", country);
  }

  function render(): void {
    document.documentElement.lang = locale;
    document.title = service.translate(locale, "Frequency Gym — Software de gestión para gimnasios");
    service.renderStatic((text) => service.translate(locale, text));
    const languageSelect = query<HTMLSelectElement>("#site-language");
    if (languageSelect) languageSelect.value = locale;
    updateSalesLinks();
  }

  async function loadExchangeRates(): Promise<void> {
    const today = new Date().toISOString().slice(0, 10);
    try {
      const cached = JSON.parse(readStorage(BOB_TO_BRL_CACHE) ?? "null") as ExchangeCache | null;
      if (cached?.date === today) {
        if (Number(cached.BRL ?? cached.rate) > 0) bobToBrlRate = Number(cached.BRL ?? cached.rate);
        if (Number(cached.USD) > 0) bobToUsdRate = Number(cached.USD);
      }
    } catch {
      // The fallback rate keeps the public page available without storage.
    }
    try {
      const response = await fetch("https://open.er-api.com/v6/latest/BOB", { cache: "no-store" });
      const data: unknown = await response.json();
      if (!response.ok || typeof data !== "object" || data === null || !("rates" in data)) return;
      const rates = data.rates;
      if (typeof rates !== "object" || rates === null) return;
      const brl = Number(Reflect.get(rates, "BRL"));
      const usd = Number(Reflect.get(rates, "USD"));
      if (!Number.isFinite(brl) || brl <= 0) return;
      bobToBrlRate = brl;
      if (Number.isFinite(usd) && usd > 0) bobToUsdRate = usd;
      writeStorage(BOB_TO_BRL_CACHE, JSON.stringify({ date: today, BRL: bobToBrlRate, USD: bobToUsdRate } satisfies ExchangeCache));
    } catch {
      // Keep the last valid rate when the provider is unavailable.
    }
    updateSalesCurrency(asCountry(countrySelect?.value ?? null) ?? "BR");
  }

  const initialCountry = asCountry(savedCountry) ?? countryFromLocale();
  if (countrySelect) countrySelect.value = initialCountry;
  syncCountryWithLocale();
  query<HTMLSelectElement>("#site-language")?.addEventListener("change", (event) => {
    const nextLocale = (event.target as HTMLSelectElement).value;
    if (!(nextLocale in whatsappMessages)) return;
    locale = nextLocale as Locale;
    service.saveLocale(locale);
    syncCountryWithLocale();
    render();
  });
  countrySelect?.addEventListener("change", updateSalesLinks);
  render();

  // Exchange rates never block first paint or interaction.
  const schedule = (callback: () => void): void => {
    if ("requestIdleCallback" in window) {
      window.requestIdleCallback(() => callback(), { timeout: 1800 });
    } else {
      setTimeout(callback, 1200);
    }
  };
  schedule(() => void loadExchangeRates());
}

