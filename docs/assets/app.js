(() => {
  "use strict";

  const DATA = window.PAIR_DATA;
  if (!DATA) {
    document.body.innerHTML = "<main style='padding:2rem;font-family:sans-serif'>Chybí data: docs/data/pairs.js</main>";
    return;
  }

  const options = DATA.options || [];
  const resorts = DATA.resorts || {};
  const resortNames = Object.keys(resorts);
  const state = {
    resort: "all",
    provider: "all",
    split: "all",
    sort: "recommended",
    budget: 3000,
    maxResort: 25,
    maxUnits: 60,
    minRating: 0,
    minReviews: 0,
    requireReviews: false,
    only5k: false,
    selectedId: null,
  };

  const $ = (id) => document.getElementById(id);
  const eur = new Intl.NumberFormat("cs-CZ", { maximumFractionDigits: 0 });
  const num = new Intl.NumberFormat("cs-CZ", { maximumFractionDigits: 1 });

  const formatEur = (value) => `${eur.format(Math.round(value))} €`;
  const formatCzk = (value) => `${eur.format(Math.round(value))} Kč`;
  const formatKm = (value) => value == null ? "—" : `${num.format(value)} km`;
  const formatDate = (value) => {
    const [year, month, day] = String(value).split("-");
    return `${Number(day)}. ${Number(month)}. ${year}`;
  };
  const escapeHtml = (value) => String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");

  const optionById = new Map(options.map((option) => [option.id, option]));
  const optionByShare = new Map(options.filter((option) => option.share).map((option) => [option.share, option]));
  const colorFor = (area) => (resorts[area] && resorts[area].color) || "#0f766e";

  const optionFromLocation = () => {
    const params = new URLSearchParams(window.location.search);
    const share = params.get("share");
    if (share && optionByShare.has(share)) return optionByShare.get(share);
    const id = params.get("option");
    if (id && optionById.has(id)) return optionById.get(id);
    return null;
  };

  const shareUrlFor = (option) => {
    if (!option) return window.location.href;
    const url = new URL(window.location.href);
    if (option.share) {
      url.searchParams.set("share", option.share);
      url.searchParams.delete("option");
    } else {
      url.searchParams.set("option", option.id);
    }
    url.hash = "";
    return url.toString();
  };

  const syncShareUrl = (option) => {
    const url = new URL(window.location.href);
    if (option && option.share) {
      url.searchParams.set("share", option.share);
      url.searchParams.delete("option");
    } else if (option) {
      url.searchParams.set("option", option.id);
    } else {
      url.searchParams.delete("share");
      url.searchParams.delete("option");
    }
    window.history.replaceState(null, "", url);
  };

  const normalizeRating = (unit) => {
    if (unit.rating == null) return null;
    return unit.provider === "Booking" ? Number(unit.rating) / 2 : Number(unit.rating);
  };

  const ratingLabel = (unit) => {
    if (unit.rating == null) return "bez hodnocení";
    const scale = unit.provider === "Booking" ? "/10" : "/5";
    const reviews = unit.reviews ? ` · ${eur.format(Number(unit.reviews))} recenzí` : "";
    return `${num.format(Number(unit.rating))}${scale}${reviews}`;
  };

  const reviewFilterActive = () => state.minRating > 0 || state.minReviews > 0 || state.requireReviews;

  const reviewPass = (units) => {
    if (!reviewFilterActive()) return true;
    return units.every((unit) => {
      const rating = normalizeRating(unit);
      const reviews = unit.reviews == null ? null : Number(unit.reviews);
      if (state.requireReviews && rating == null) return false;
      if (state.minRating > 0 && (rating == null || rating < state.minRating)) return false;
      if (state.minReviews > 0 && (reviews == null || reviews < state.minReviews)) return false;
      return true;
    });
  };

  const minNormalizedRating = (option) => {
    const ratings = option.units.map(normalizeRating).filter((value) => value != null);
    return ratings.length ? Math.min(...ratings) : null;
  };

  function filteredOptions() {
    const result = options.filter((option) => {
      if (state.resort !== "all" && option.area !== state.resort) return false;
      if (state.provider !== "all" && option.provider !== state.provider) return false;
      if (state.split !== "all" && option.split !== state.split) return false;
      if (option.total > state.budget) return false;
      if (state.maxResort < 25 && (option.max_resort_km == null || option.max_resort_km > state.maxResort)) return false;
      if (state.maxUnits < 60 && (option.max_unit_km == null || option.max_unit_km > state.maxUnits)) return false;
      if (state.only5k && option.czk_per_person > 5000) return false;
      if (!reviewPass(option.units)) return false;
      return true;
    });
    result.sort((a, b) => {
      if (state.sort === "price") return a.total - b.total || a.score - b.score;
      if (state.sort === "resort") {
        return (a.max_resort_km ?? 999) - (b.max_resort_km ?? 999) || a.total - b.total;
      }
      if (state.sort === "units") {
        return (a.max_unit_km ?? 999) - (b.max_unit_km ?? 999) || a.total - b.total;
      }
      if (state.sort === "rating") {
        return (minNormalizedRating(b) ?? -1) - (minNormalizedRating(a) ?? -1) || a.total - b.total;
      }
      return a.score - b.score;
    });
    return result;
  }

  function unitThumb(unit) {
    if (unit.image) {
      return `<div class="thumb"><img src="${escapeHtml(unit.image)}" alt="" loading="lazy" onerror="this.style.display='none'"></div>`;
    }
    return `<div class="thumb" aria-hidden="true"></div>`;
  }

  function unitRow(unit) {
    return `
      <div class="unit-row">
        ${unitThumb(unit)}
        <div class="unit-body">
          <span class="unit-role">${escapeHtml(unit.role)} osob</span>
          <h3 class="unit-title" title="${escapeHtml(unit.title)}">${escapeHtml(unit.title)}</h3>
          <div class="unit-meta">${unit.bedrooms} ložnice · ${formatEur(unit.price)} · ${escapeHtml(ratingLabel(unit))}</div>
          <div class="unit-meta">${escapeHtml(unit.location || "")} · ${formatKm(unit.resort_km)} od areálu</div>
          <div class="unit-links"><a href="${escapeHtml(unit.url)}" target="_blank" rel="noopener">Otevřít nabídku</a></div>
        </div>
      </div>`;
  }

  function detailHtml(option) {
    if (!option) {
      return "<h2>Žádná varianta</h2><p class='detail-meta'>Pro zvolené filtry není výsledek.</p>";
    }
    const missingCoords = option.units.some((unit) => unit.lat == null || unit.lng == null);
    const budgetClass = option.total <= 2400 ? "budget-ok" : option.total <= 3000 ? "budget-ok" : "budget-over";
    return `
      <div class="card-top" style="justify-content:flex-start">
        <span class="badge" style="--resort-color:${colorFor(option.area)}">${escapeHtml(option.area)}</span>
        <span class="provider-tag">${escapeHtml(option.provider)}</span>
      </div>
      <h2>${formatEur(option.total)} celkem</h2>
      <div class="detail-meta">${escapeHtml(option.split)} · ${formatDate(option.check_in)} → ${formatDate(option.check_out)} · ${option.nights} noci · ${option.units.length} jednotky</div>
      <div class="detail-total">
        <div><strong>${formatEur(option.total)}</strong><span>za všechny jednotky</span></div>
        <div class="${budgetClass}">${formatCzk(option.czk_per_person)} / os.<br><small>${option.total <= 3000 ? "do 3 000 €" : "mírně nad 3 000 €"}</small></div>
      </div>
      <div class="detail-metrics">
        <div class="metric"><span>Max. od areálu</span><strong>${formatKm(option.max_resort_km)}</strong></div>
        <div class="metric"><span>Max. mezi jednotkami</span><strong>${formatKm(option.max_unit_km)}</strong></div>
        <div class="metric"><span>Ložnic celkem</span><strong>${option.total_bedrooms}</strong></div>
      </div>
      <div class="detail-units">${option.units.map(unitRow).join("")}</div>
      ${missingCoords ? "<p class='detail-meta' style='margin-top:12px'>Booking u některých jednotek neuvádí souřadnice; mapa je proto neukáže a vzdálenost může být „—“.</p>" : ""}
      <div class="share-row">
        <button type="button" id="copyOptionLink">Kopírovat odkaz na kombinaci</button>
        <span id="copyFeedback" class="unit-meta"></span>
      </div>
      <p class="detail-meta" style="margin-top:12px">Ověřit simultánní dostupnost, daně a konečnou cenu.</p>`;
  }

  function cardHtml(option) {
    const budgetClass = option.total > 3000 ? "over-budget" : "";
    return `
      <article class="pair-card ${option.id === state.selectedId ? "selected" : ""}" data-id="${escapeHtml(option.id)}" tabindex="0" role="button" aria-label="Vybrat ${escapeHtml(option.area)} za ${formatEur(option.total)}">
        <div class="card-top">
          <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap">
            <span class="badge" style="--resort-color:${colorFor(option.area)}">${escapeHtml(option.area)}</span>
            <span class="provider-tag">${escapeHtml(option.provider)}</span>
            <span class="provider-tag">${escapeHtml(option.split)}</span>
          </div>
          <span class="card-price ${budgetClass}">${formatEur(option.total)}</span>
        </div>
        <div class="card-units">
          ${option.units.map((unit) => `
            <div class="mini-unit">
              ${unitThumb(unit)}
              <h3 title="${escapeHtml(unit.title)}">${escapeHtml(unit.role)} · ${escapeHtml(unit.title)}</h3>
              <p>${unit.bedrooms} ložnice · ${formatEur(unit.price)} · ${escapeHtml(ratingLabel(unit))}</p>
            </div>`).join("")}
        </div>
        <div class="card-foot">
          <span><strong>${option.units.length}</strong> jednotky</span>
          <span>od sebe <strong>${formatKm(option.max_unit_km)}</strong></span>
          <span>areál <strong>${formatKm(option.max_resort_km)}</strong></span>
          <span><strong>${formatCzk(option.czk_per_person)}</strong> / os.</span>
        </div>
      </article>`;
  }

  function renderCards(list) {
    const cards = $("cards");
    const empty = $("empty");
    cards.innerHTML = list.map(cardHtml).join("");
    if (!list.length) {
      empty.hidden = false;
      empty.textContent = "Pro zvolené filtry není žádná varianta. Zvyš rozpočet, vzdálenosti nebo sniž požadavky na recenze.";
    } else {
      empty.hidden = true;
      empty.textContent = "";
    }
    cards.querySelectorAll(".pair-card").forEach((card) => {
      const select = () => selectOption(card.dataset.id);
      card.addEventListener("click", select);
      card.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          select();
        }
      });
    });
  }

  let map;
  let resortLayer;
  let selectionLayer;

  function midpoint(a, b) {
    return [(a.lat + b.lat) / 2, (a.lng + b.lng) / 2];
  }

  function distanceLabel(a, b, text) {
    L.marker(midpoint(a, b), {
      interactive: false,
      icon: L.divIcon({ className: "distance-label", html: escapeHtml(text), iconSize: null }),
    }).addTo(selectionLayer);
  }

  function initMap() {
    if (!window.L) {
      $("map").innerHTML = "<p style='padding:1rem;color:#5f6f82'>Mapu nelze načíst: chybí Leaflet.</p>";
      return;
    }
    map = L.map("map", { scrollWheelZoom: true }).setView([47.5, 13.8], 8);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 18,
      attribution: "&copy; OpenStreetMap přispěvatelé",
    }).addTo(map);
    resortLayer = L.layerGroup().addTo(map);
    selectionLayer = L.layerGroup().addTo(map);

    for (const [name, resort] of Object.entries(resorts)) {
      for (const point of resort.points) {
        L.circleMarker([point.lat, point.lng], {
          radius: 7,
          color: "#ffffff",
          weight: 2,
          fillColor: resort.color,
          fillOpacity: 0.95,
        })
          .bindTooltip(`${escapeHtml(name)} · ${escapeHtml(point.name)}`, { direction: "top" })
          .addTo(resortLayer);
      }
    }
    $("mapLegend").innerHTML = Object.entries(resorts)
      .map(([name, resort]) => `<span><span class="legend-dot" style="background:${resort.color}"></span>${escapeHtml(name)}</span>`)
      .join("");
  }

  function drawSelection(option) {
    if (!map || !selectionLayer) return;
    selectionLayer.clearLayers();
    if (!option) {
      map.setView([47.5, 13.8], 8);
      return;
    }
    const color = colorFor(option.area);
    const coordUnits = option.units.filter((unit) => unit.lat != null && unit.lng != null);
    const resortPoints = new Map();
    for (const unit of option.units) {
      const point = unit.resort_point || (resorts[option.area] || {}).points?.[0];
      if (point) resortPoints.set(`${point.lat},${point.lng}`, point);
    }
    if (!coordUnits.length) {
      const point = [...resortPoints.values()][0];
      if (point) {
        L.circleMarker([point.lat, point.lng], { radius: 9, color, fillColor: color, fillOpacity: 0.2 }).addTo(selectionLayer);
        map.setView([point.lat, point.lng], 10);
      }
      return;
    }

    for (const unit of coordUnits) {
      L.marker([unit.lat, unit.lng], {
        icon: L.divIcon({
          className: `unit-marker role-${unit.role}`,
          html: escapeHtml(unit.role),
          iconSize: [34, 34],
          iconAnchor: [17, 17],
        }),
      })
        .bindTooltip(`${escapeHtml(unit.role)} osob · ${escapeHtml(unit.title)}`, { direction: "top", offset: [0, -12] })
        .addTo(selectionLayer);
    }

    for (let i = 0; i < coordUnits.length; i += 1) {
      for (let j = i + 1; j < coordUnits.length; j += 1) {
        L.polyline([[coordUnits[i].lat, coordUnits[i].lng], [coordUnits[j].lat, coordUnits[j].lng]], {
          color: "#132238",
          weight: 2,
          opacity: 0.35,
        }).addTo(selectionLayer);
      }
      const point = coordUnits[i].resort_point;
      if (point) {
        L.polyline([[coordUnits[i].lat, coordUnits[i].lng], [point.lat, point.lng]], {
          color,
          weight: 2,
          opacity: 0.6,
          dashArray: "7 6",
        }).addTo(selectionLayer);
        distanceLabel(coordUnits[i], point, `areál ${formatKm(coordUnits[i].resort_km)}`);
      }
    }

    if (coordUnits.length > 1) {
      const first = coordUnits[0];
      const last = coordUnits[coordUnits.length - 1];
      distanceLabel(first, last, `max. ${formatKm(option.max_unit_km)}`);
    }

    for (const point of resortPoints.values()) {
      L.circle([point.lat, point.lng], {
        radius: 25000,
        color,
        weight: 1.5,
        opacity: 0.45,
        dashArray: "5 8",
        fillColor: color,
        fillOpacity: 0.025,
      }).addTo(selectionLayer);
    }

    const bounds = L.latLngBounds(coordUnits.map((unit) => [unit.lat, unit.lng]));
    for (const point of resortPoints.values()) bounds.extend([point.lat, point.lng]);
    map.fitBounds(bounds, { padding: [45, 45], maxZoom: 12 });
  }

  let chart;

  function initChart() {
    if (!window.Chart) {
      $("chart").closest(".chart-panel").hidden = true;
      return;
    }
    const context = $("chart").getContext("2d");
    chart = new Chart(context, {
      type: "scatter",
      data: { datasets: [] },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        interaction: { mode: "nearest", intersect: true },
        scales: {
          x: { title: { display: true, text: "Max. vzdálenost od areálu (km)" }, min: 0, max: 26, grid: { color: "rgba(19,34,56,0.07)" } },
          y: { title: { display: true, text: "Celková cena (€)" }, beginAtZero: false, suggestedMin: 500, grid: { color: "rgba(19,34,56,0.07)" } },
        },
        plugins: {
          legend: { position: "bottom", labels: { boxWidth: 10, usePointStyle: true } },
          tooltip: {
            callbacks: {
              label: (context) => {
                const raw = context.raw || {};
                if (raw.budgetLine) return raw.label;
                return `${raw.resort}: ${formatEur(raw.y)} · ${formatKm(raw.x)} · ${raw.split}`;
              },
            },
          },
        },
        onClick: (event, elements) => {
          if (!elements.length) return;
          const element = elements[0];
          const dataset = chart.data.datasets[element.datasetIndex];
          if (!dataset || !dataset.optionIds) return;
          const id = dataset.optionIds[element.index];
          if (id) selectOption(id);
        },
      },
    });
  }

  function renderChart(list) {
    if (!chart) return;
    const datasets = [];
    for (const [name, resort] of Object.entries(resorts)) {
      const points = list.filter((option) => option.area === name && option.max_resort_km != null);
      if (!points.length) continue;
      datasets.push({
        label: name,
        type: "scatter",
        data: points.map((option) => ({ x: option.max_resort_km, y: option.total, resort: option.area, split: option.split })),
        optionIds: points.map((option) => option.id),
        backgroundColor: resort.color,
        borderColor: "#ffffff",
        borderWidth: 1.5,
        pointRadius: 6,
        pointHoverRadius: 9,
      });
    }
    datasets.push({
      label: "5 000 Kč/os. (cca 2 400 €)",
      type: "line",
      data: [{ x: 0, y: 2400, budgetLine: true, label: "5 000 Kč/os. (cca 2 400 €)" }, { x: 25, y: 2400, budgetLine: true, label: "5 000 Kč/os. (cca 2 400 €)" }],
      borderColor: "#0f766e",
      borderDash: [6, 6],
      borderWidth: 1.5,
      pointRadius: 0,
    });
    datasets.push({
      label: "3 000 €",
      type: "line",
      data: [{ x: 0, y: 3000, budgetLine: true, label: "3 000 €" }, { x: 25, y: 3000, budgetLine: true, label: "3 000 €" }],
      borderColor: "#b45309",
      borderDash: [4, 5],
      borderWidth: 1.5,
      pointRadius: 0,
    });
    chart.data.datasets = datasets;
    chart.update();
  }

  function attachDetailActions(option) {
    const button = $("copyOptionLink");
    const feedback = $("copyFeedback");
    if (!button) return;
    button.addEventListener("click", async () => {
      const url = shareUrlFor(option);
      try {
        await navigator.clipboard.writeText(url);
        if (feedback) feedback.textContent = "Odkaz zkopírován.";
      } catch (error) {
        window.prompt("Zkopíruj odkaz na kombinaci:", url);
      }
    });
  }

  function selectOption(id) {
    if (!optionById.has(id)) return;
    state.selectedId = id;
    const option = optionById.get(id);
    $("detailPanel").innerHTML = detailHtml(option);
    attachDetailActions(option);
    syncShareUrl(option);
    document.querySelectorAll(".pair-card").forEach((card) => {
      card.classList.toggle("selected", card.dataset.id === id);
    });
    drawSelection(option);
    if (window.matchMedia("(max-width: 1050px)").matches) {
      $("map").scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }

  function render() {
    const list = filteredOptions();
    if (!state.selectedId || !list.some((option) => option.id === state.selectedId)) {
      state.selectedId = list.length ? list[0].id : null;
    }
    const selected = state.selectedId ? optionById.get(state.selectedId) : null;
    $("detailPanel").innerHTML = detailHtml(selected);
    attachDetailActions(selected);
    syncShareUrl(selected);
    const airbnb = list.filter((option) => option.provider === "Airbnb").length;
    const booking = list.filter((option) => option.provider === "Booking").length;
    const mix = list.filter((option) => option.provider === "Mix").length;
    $("resultCount").textContent = `Zobrazeno ${list.length} z ${options.length} variant (Airbnb ${airbnb}, Booking ${booking}, Mix ${mix}).`;
    renderCards(list);
    renderChart(list);
    drawSelection(selected);
  }

  function initControls() {
    const resortSelect = $("resort");
    resortSelect.innerHTML = `<option value="all">Všechna střediska</option>` +
      resortNames.map((name) => `<option value="${escapeHtml(name)}">${escapeHtml(name)}</option>`).join("");
    resortSelect.addEventListener("change", () => {
      state.resort = resortSelect.value;
      render();
    });

    const splitSelect = $("split");
    const splits = [...new Set(options.map((option) => option.split))].sort((a, b) => a.split("+").length - b.split("+").length || a.localeCompare(b));
    splitSelect.innerHTML = `<option value="all">Všechna rozdělení</option>` +
      splits.map((split) => `<option value="${escapeHtml(split)}">${escapeHtml(split)}${split.includes("+") ? "" : ""}</option>`).join("");
    splitSelect.addEventListener("change", () => {
      state.split = splitSelect.value;
      render();
    });

    $("provider").addEventListener("change", (event) => {
      state.provider = event.target.value;
      render();
    });

    const budget = $("budget");
    const budgetOut = $("budgetOut");
    budget.addEventListener("input", () => {
      state.budget = Number(budget.value);
      budgetOut.textContent = formatEur(state.budget);
      render();
    });
    budgetOut.textContent = formatEur(state.budget);

    const maxResort = $("maxResort");
    const maxResortOut = $("maxResortOut");
    maxResort.addEventListener("input", () => {
      state.maxResort = Number(maxResort.value);
      maxResortOut.textContent = formatKm(state.maxResort);
      render();
    });
    maxResortOut.textContent = formatKm(state.maxResort);

    const maxUnits = $("maxUnits");
    const maxUnitsOut = $("maxUnitsOut");
    maxUnits.addEventListener("input", () => {
      state.maxUnits = Number(maxUnits.value);
      maxUnitsOut.textContent = formatKm(state.maxUnits);
      render();
    });
    maxUnitsOut.textContent = formatKm(state.maxUnits);

    const minRating = $("minRating");
    const minRatingOut = $("minRatingOut");
    minRating.addEventListener("input", () => {
      state.minRating = Number(minRating.value);
      minRatingOut.textContent = `${num.format(state.minRating)} / 5`;
      render();
    });
    minRatingOut.textContent = `${num.format(state.minRating)} / 5`;

    const minReviews = $("minReviews");
    const minReviewsOut = $("minReviewsOut");
    minReviews.addEventListener("input", () => {
      state.minReviews = Number(minReviews.value);
      minReviewsOut.textContent = eur.format(state.minReviews);
      render();
    });
    minReviewsOut.textContent = eur.format(state.minReviews);

    $("requireReviews").addEventListener("change", (event) => {
      state.requireReviews = event.target.checked;
      render();
    });
    $("only5k").addEventListener("change", (event) => {
      state.only5k = event.target.checked;
      render();
    });
    $("sort").addEventListener("change", (event) => {
      state.sort = event.target.value;
      render();
    });

    document.querySelectorAll("[data-budget]").forEach((button) => {
      button.addEventListener("click", () => {
        state.budget = Number(button.dataset.budget);
        budget.value = String(state.budget);
        budgetOut.textContent = formatEur(state.budget);
        render();
      });
    });

    $("reset").addEventListener("click", () => {
      state.resort = "all";
      state.provider = "all";
      state.split = "all";
      state.budget = 3000;
      state.maxResort = 25;
      state.maxUnits = 60;
      state.minRating = 0;
      state.minReviews = 0;
      state.requireReviews = false;
      state.only5k = false;
      state.sort = "recommended";
      resortSelect.value = "all";
      splitSelect.value = "all";
      $("provider").value = "all";
      budget.value = "3000";
      budgetOut.textContent = formatEur(3000);
      maxResort.value = "25";
      maxResortOut.textContent = formatKm(25);
      maxUnits.value = "60";
      maxUnitsOut.textContent = formatKm(60);
      minRating.value = "0";
      minRatingOut.textContent = "0 / 5";
      minReviews.value = "0";
      minReviewsOut.textContent = "0";
      $("requireReviews").checked = false;
      $("only5k").checked = false;
      $("sort").value = "recommended";
      render();
    });
  }

  initControls();

  const sharedOption = optionFromLocation();
  if (sharedOption) {
    state.selectedId = sharedOption.id;
    state.resort = "all";
    state.provider = "all";
    state.split = "all";
    state.budget = 3500;
    state.maxResort = 25;
    state.maxUnits = 60;
    state.minRating = 0;
    state.minReviews = 0;
    state.requireReviews = false;
    state.only5k = false;
    state.sort = "recommended";
    $("resort").value = "all";
    $("provider").value = "all";
    $("split").value = "all";
    $("budget").value = "3500";
    $("budgetOut").textContent = formatEur(3500);
    $("maxResort").value = "25";
    $("maxResortOut").textContent = formatKm(25);
    $("maxUnits").value = "60";
    $("maxUnitsOut").textContent = formatKm(60);
    $("minRating").value = "0";
    $("minRatingOut").textContent = "0 / 5";
    $("minReviews").value = "0";
    $("minReviewsOut").textContent = "0";
    $("requireReviews").checked = false;
    $("only5k").checked = false;
    $("sort").value = "recommended";
  }

  window.addEventListener("popstate", () => {
    const option = optionFromLocation();
    if (option) selectOption(option.id);
  });

  initMap();
  initChart();
  render();
})();
