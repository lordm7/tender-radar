// The matches page: filters, and selecting a tender from the list or the radar.
// It only reads what is already in the page (data-* attributes and the embedded
// JSON), so it works the same in the live app and the static GitHub Pages demo.
// Without JavaScript the page still works: rows are normal links.
(function () {
  const dataEl = document.getElementById("tr-data");
  if (!dataEl) return;
  const tenders = JSON.parse(dataEl.textContent);
  const byRef = new Map(tenders.map((t) => [t.ref, t]));
  const rows = Array.from(document.querySelectorAll("#results .row"));
  const dots = Array.from(document.querySelectorAll(".radar .dot[data-ref]"));
  const $ = (id) => document.getElementById(id);

  function select(ref) {
    const t = byRef.get(ref);
    if (!t || !$("sel-title")) return;
    $("sel-score").textContent = t.score === null ? "—" : t.score;
    $("sel-ring").style.setProperty("--p", t.score || 0);
    const title = $("sel-title");
    title.textContent = t.title;
    if (t.title_orig) { title.setAttribute("lang", "ar"); title.setAttribute("dir", "rtl"); }
    else { title.removeAttribute("lang"); title.removeAttribute("dir"); }
    $("sel-reason").textContent = t.reason;
    $("sel-closes").textContent = t.closes + " · " + t.days_label;
    $("sel-booklet").textContent = t.booklet;
    $("sel-inquiries").textContent = t.inquiries;
    $("sel-open").href = t.url;
    rows.forEach((r) => r.classList.toggle("sel", r.dataset.reference === ref));
    dots.forEach((d) => d.classList.toggle("sel", d.dataset.ref === ref));
  }

  // On a phone the layout is stacked and the "Selected tender" panel is off-screen,
  // so a tap simply opens the tender.
  const stacked = window.matchMedia("(max-width: 960px)");
  rows.forEach((row) => {
    row.addEventListener("click", (e) => {
      if (e.ctrlKey || e.metaKey || e.shiftKey || e.button !== 0) return; // let "open in new tab" work
      const keyboard = e.detail === 0; // Enter on a focused row: open it, like any link
      const again = row.classList.contains("sel"); // a second click on the selected row opens it
      if (keyboard || again || stacked.matches) return;
      e.preventDefault();
      select(row.dataset.reference);
    });
    row.addEventListener("dblclick", () => { window.location.href = row.href; });
  });
  dots.forEach((dot) => {
    dot.addEventListener("click", () => select(dot.dataset.ref));
    dot.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); select(dot.dataset.ref); }
    });
  });

  // Filters
  const score = $("f-score"), agency = $("f-agency"), days = $("f-days"), count = $("f-count");
  if (!score) return;
  function apply() {
    const minScore = Number(score.value);
    const maxDays = days.value === "" ? null : Number(days.value);
    let shown = 0;
    for (const row of rows) {
      const left = row.dataset.daysLeft;
      const ok =
        Number(row.dataset.score) >= minScore &&
        (agency.value === "" || row.dataset.agency === agency.value) &&
        (maxDays === null || (left !== "" && Number(left) >= 0 && Number(left) <= maxDays));
      row.parentElement.style.display = ok ? "" : "none";
      const dot = dots.find((d) => d.dataset.ref === row.dataset.reference);
      if (dot) dot.style.opacity = ok ? "" : "0.15";
      if (ok) shown++;
    }
    count.textContent = count.dataset.template.replace("{shown}", shown).replace("{total}", rows.length);
  }
  [score, agency, days].forEach((el) => el.addEventListener("change", apply));
  apply();
})();
