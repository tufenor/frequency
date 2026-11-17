(() => {
  "use strict";
  const root = document.getElementById("app-aluno");
  if (!root) return;
  const base = "/static/app-aluno/";
  const tabs = Array.from(root.querySelectorAll('[role="tab"]'));
  const panels = Array.from(root.querySelectorAll('[role="tabpanel"]'));
  const photo = root.querySelector(".sa-photo");
  const [imgA, imgB] = photo.querySelectorAll("img");

  function showExercise(btn) {
    const panel = btn.closest('[role="tabpanel"]');
    panel.querySelectorAll(".sa-ex").forEach((b) => b.setAttribute("aria-pressed", String(b === btn)));
    const id = btn.dataset.img;
    imgA.src = base + id + "-0.jpg";
    imgB.src = base + id + "-1.jpg";
    syncAlt();
    photo.classList.remove("is-swap"); void photo.offsetWidth; photo.classList.add("is-swap");
  }
  function currentButton() {
    const panel = panels.find((p) => !p.hidden);
    return panel && panel.querySelector('.sa-ex[aria-pressed="true"]');
  }
  function syncAlt() {
    const b = currentButton();
    const name = b ? b.querySelector(".sa-ex-name").textContent.trim() : "";
    imgA.alt = name; imgB.alt = "";
  }
  function selectTab(tab, focus) {
    tabs.forEach((t) => { const on = t === tab; t.setAttribute("aria-selected", String(on)); t.tabIndex = on ? 0 : -1; });
    panels.forEach((p) => { p.hidden = p.id !== tab.getAttribute("aria-controls"); });
    if (focus) tab.focus();
    const b = currentButton();
    if (b) showExercise(b);
  }
  tabs.forEach((tab, i) => {
    tab.addEventListener("click", () => selectTab(tab, false));
    tab.addEventListener("keydown", (e) => {
      const k = e.key;
      if (k !== "ArrowRight" && k !== "ArrowLeft" && k !== "Home" && k !== "End") return;
      e.preventDefault();
      const n = k === "Home" ? 0 : k === "End" ? tabs.length - 1 : (i + (k === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length;
      selectTab(tabs[n], true);
    });
  });
  root.querySelectorAll(".sa-ex").forEach((b) => b.addEventListener("click", () => showExercise(b)));

  // O movimento só roda enquanto a seção está visível (e nunca com "reduzir movimento").
  if ("IntersectionObserver" in window) {
    new IntersectionObserver((es) => es.forEach((e) => root.classList.toggle("is-live", e.isIntersecting)), { threshold: 0.25 }).observe(root);
  } else root.classList.add("is-live");

  // Mantém o texto alternativo no idioma escolhido.
  const sel = document.getElementById("site-language");
  if (sel) sel.addEventListener("change", () => setTimeout(syncAlt, 120));
  setTimeout(syncAlt, 400);
})();
