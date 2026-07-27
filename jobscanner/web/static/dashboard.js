// progressive enhancement, kein Feature hängt hiervon ab
document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("[data-tab-target]").forEach((tabBtn) => {
    tabBtn.addEventListener("click", () => {
      const target = tabBtn.dataset.tabTarget;
      document.querySelectorAll("[data-tab-target]").forEach((t) => {
        t.classList.toggle("active", t === tabBtn);
      });
      document.querySelectorAll("[data-tab-panel]").forEach((panel) => {
        panel.classList.toggle("panel-hidden", panel.dataset.tabPanel !== target);
      });
    });
  });

  // Vote-/Favoriten-Form-Listener — als Funktion, damit sie nach einem
  // AJAX-Ergebnis-Swap erneut an die frischen Cards gebunden werden koennen.
  function bindCardForms(root) {
    root.querySelectorAll("[data-vote-form]").forEach((form) => {
      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const btn = event.submitter;
        if (!btn || btn.disabled) return;
        const card = form.closest(".job-card");
        const buttons = card.querySelectorAll("[data-vote-btn]");
        buttons.forEach((b) => { b.disabled = true; });
        try {
          const resp = await fetch(form.action, {
            method: "POST",
            headers: { "Accept": "application/json" },
            body: new URLSearchParams({
              vote: btn.value,
              csrf_token: document.querySelector('meta[name="csrf-token"]').content,
            }),
          });
          if (!resp.ok) return;
          const data = await resp.json();
          buttons.forEach((b) => {
            b.classList.toggle("active-up", data.vote === "up" && b.dataset.voteBtn === "up");
            b.classList.toggle("active-down", data.vote === "down" && b.dataset.voteBtn === "down");
          });
          const badge = card.querySelector("[data-feedback-badge]");
          if (badge && data.vote === "up") {
            badge.textContent = "✓ bewertet 👍";
            badge.className = "feedback-badge feedback-badge-up";
          } else if (badge && data.vote === "down") {
            badge.textContent = "✓ bewertet 👎";
            badge.className = "feedback-badge feedback-badge-down";
          }
        } finally {
          buttons.forEach((b) => { b.disabled = false; });
        }
      });
    });

    root.querySelectorAll("[data-fav-form]").forEach((form) => {
      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const btn = event.submitter;
        if (!btn || btn.disabled) return;
        btn.disabled = true;
        try {
          const resp = await fetch(form.action, {
            method: "POST",
            headers: { "Accept": "application/json" },
            body: new URLSearchParams({
              csrf_token: document.querySelector('meta[name="csrf-token"]').content,
            }),
          });
          if (!resp.ok) return;
          const data = await resp.json();
          btn.classList.toggle("fav-active", data.favorite);
          btn.textContent = data.favorite ? "★" : "☆";
        } finally {
          btn.disabled = false;
        }
      });
    });
  }
  bindCardForms(document);

  // Suche: kein Full-Page-Reload (der zerstoert das Input -> Android schliesst
  // die Tastatur). Stattdessen die gefilterte Ergebnisliste per fetch holen und
  // nur [data-dash-results] austauschen; das Suchfeld bleibt erhalten.
  const dashSearch = document.querySelector("[data-dash-search]");
  if (dashSearch) {
    const searchForm = dashSearch.form;
    const runSearch = () => {
      const url = searchForm.action + "?"
        + new URLSearchParams(new FormData(searchForm)).toString();
      fetch(url, { headers: { "X-Requested-With": "fetch" } })
        .then((r) => r.text())
        .then((html) => {
          const doc = new DOMParser().parseFromString(html, "text/html");
          const fresh = doc.querySelector("[data-dash-results]");
          const cur = document.querySelector("[data-dash-results]");
          if (fresh && cur) {
            cur.innerHTML = fresh.innerHTML;
            bindCardForms(cur);
          }
          const freshCount = doc.querySelector("[data-search-count]");
          const curCount = document.querySelector("[data-search-count]");
          if (freshCount && curCount) curCount.textContent = freshCount.textContent;
          history.replaceState(null, "", url);
        })
        .catch(() => { /* transient — native Submit bleibt als Fallback */ });
    };
    let timer;
    dashSearch.addEventListener("input", () => {
      clearTimeout(timer);
      timer = setTimeout(runSearch, 400);
    });
    searchForm.addEventListener("submit", (event) => {
      event.preventDefault();   // Enter loest auch nur den AJAX-Filter aus
      clearTimeout(timer);
      runSearch();
    });
    // Fokus/Cursor ans Ende bei frischem Full-Page-Load mit q (kein AJAX-Pfad)
    if (dashSearch.value) {
      dashSearch.focus();
      const end = dashSearch.value.length;
      dashSearch.setSelectionRange(end, end);
    }
  }

  // Lernen: Status pollen, bei Wechsel neu laden (Karten sind server-rendered)
  const lernenPanel = document.querySelector("[data-analysis-status]");
  if (lernenPanel) {
    const status = lernenPanel.dataset.analysisStatus;
    if (status === "analyzing" || status === "synthesizing") {
      const poll = setInterval(async () => {
        try {
          const resp = await fetch(lernenPanel.dataset.analysisBase + "/analysis",
                                   { headers: { "Accept": "application/json" } });
          if (!resp.ok) return;
          const data = await resp.json();
          if (data.status !== status) { clearInterval(poll); window.location.reload(); }
        } catch (e) { /* transient */ }
      }, 3000);
    }
  }

  // Widerspruchs-Antworten vor dem Finalize als JSON speichern
  const answersForm = document.querySelector("[data-answers-form]");
  if (answersForm) {
    answersForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      const answers = {};
      answersForm.querySelectorAll('input[type="text"]').forEach((inp) => {
        answers[inp.name] = inp.value;
      });
      const base = answersForm.closest("[data-analysis-base]").dataset.analysisBase;
      try {
        await fetch(base + "/analysis/answers", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-CSRF-Token": document.querySelector('meta[name="csrf-token"]').content,
          },
          body: JSON.stringify({ analysis_id: Number(answersForm.dataset.analysisId), answers }),
        });
      } catch (e) { /* answers optional */ }
      const finalize = document.createElement("form");
      finalize.method = "post";
      finalize.action = base + "/finalize";
      const csrfInput = document.createElement("input");
      csrfInput.type = "hidden";
      csrfInput.name = "csrf_token";
      csrfInput.value = document.querySelector('meta[name="csrf-token"]').content;
      finalize.appendChild(csrfInput);
      document.body.appendChild(finalize);
      finalize.submit();
    });
  }

  const hash = window.location.hash.replace("#", "");
  if (hash) {
    const btn = document.querySelector(`[data-tab-target="${hash}"]`);
    if (btn) btn.click();
  }
});
