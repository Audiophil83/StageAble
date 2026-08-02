(function () {
  const TABS = ["home", "features", "guides", "download", "faq", "source", "contact"];
  const navButtons = document.querySelectorAll(".btn-nav-tab");
  const panels = document.querySelectorAll(".tab-panel");

  function showTab(tabId) {
    const id = TABS.includes(tabId) ? tabId : "home";

    navButtons.forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.tab === id);
    });

    panels.forEach((panel) => {
      panel.classList.toggle("active", panel.id === `tab-${id}`);
    });

    if (location.hash !== `#${id}`) {
      history.replaceState(null, "", `#${id}`);
    }

    document.title =
      id === "home"
        ? "StageAble — Live Show Control for Ableton"
        : `StageAble — ${id.charAt(0).toUpperCase() + id.slice(1)}`;
  }

  navButtons.forEach((btn) => {
    btn.addEventListener("click", () => showTab(btn.dataset.tab));
  });

  document.querySelectorAll("[data-goto]").forEach((el) => {
    el.addEventListener("click", (e) => {
      e.preventDefault();
      showTab(el.dataset.goto);
    });
  });

  window.addEventListener("hashchange", () => {
    showTab(location.hash.replace("#", ""));
  });

  document.querySelectorAll(".faq-question").forEach((btn) => {
    btn.addEventListener("click", () => {
      const item = btn.closest(".faq-item");
      const wasOpen = item.classList.contains("open");
      document.querySelectorAll(".faq-item.open").forEach((el) => {
        el.classList.remove("open");
      });
      if (!wasOpen) {
        item.classList.add("open");
      }
    });
  });

  showTab(location.hash.replace("#", "") || "home");
})();
