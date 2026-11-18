(() => {
  "use strict";

  const DATA = window.PAIR_DATA;
  if (!DATA) {
    document.body.innerHTML = "<main style='padding:2rem;font-family:sans-serif'>Chybí data: docs/data/pairs.js</main>";
    return;
  }

  const pairs = DATA.pairs || [];
  const resorts = DATA.resorts || {};
  const resortNames = Object.keys(resorts);
  const state = {
    resort: "all",
    provider: "all",
    budget: 3500,
    maxResort: 25,
    maxUnits: 60,
    only5k: false,
    minRating: 0,
    minReviews: 0,
    requireReviews: false,
    sort: "price",
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

  const pairById = new Map(pairs.map((pair) => [pair.id, pair]));

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

  function colorFor(resort) {
    return (resorts[resort] && resorts[resort].color) || "#0f766e";
  }

  function filteredPairs() {
    const result = pairs.filter((pair) => {
      if (state.resort !== "all" && pair.resort !== state.resort) return false;
      if (state.provider !== "all" && pair.provider !== state.provider) return false;
      if (pair.total > state.budget) return false;
      if (pair.max_resort_km > state.maxResort) return false;
      if (pair.distance_units_km > state.maxUnits) return false;
      if (state.only5k && pair.czk_per_person > 5000) return false;
      if (!reviewPass(pair.units)) return false;
      return true;
    });
    result.sort((a, b) => {
      if (state.sort === "resort") {
        return a.max_resort_km - b.max_resort_km || a.total - b.total;
      }
      if (state.sort === "units") {
        return a.distance_units_km - b.distance_units_km || a.total - b.total;
      }
      return a.total - b.total || a.max_resort_km - b.max_resort_km;
    });
    return result;
  }

  function unitThumb(unit, className = "thumb") {
    if (unit.image) {
      return `<div class="${className}"><img src="${escapeHtml(unit.image)}" alt="" loading="lazy" onerror="this.style.display='none'"></div>`;
    }
    return `<div class="${className}" aria-hidden="true"></div>`;
  }

  function unitRow(unit) {
    const rating = unit.rating ? `${num.format(unit.rating)} / 5` : "bez hodnocení";
    const reviews = unit.reviews ? ` · ${eur.format(unit.reviews)} recenzí` : "";
    return `
      <div class="unit-row">
        ${unitThumb(unit)}
        <div class="unit-body">
          <span class="unit-role">${escapeHtml(unit.role)} osob</span>
          <h3 class="unit-title" title="${escapeHtml(unit.title)}">${escapeHtml(unit.title)}</h3>
          <div class="unit-meta">${unit.capacity} osob · ${unit.bedrooms} ložnice · ${formatEur(unit.price)} · ${rating}${reviews}</div>
          <div class="unit-meta">${escapeHtml(unit.location || "")} · ${formatKm(unit.resort_km)} od areálu</div>
          <div class="unit-links"><a href="${escapeHtml(unit.url)}" target="_blank" rel="noopener">Otevřít na Airbnb</a></div>
        </div>
      </div>`;
  }

  function detailHtml(pair) {
    if (!pair) {
      return `<h2>Žádná varianta</h2><p class="detail-meta">Pro zvolené filtry není k dispozici žádná dvojice.</p>`;
    }
    const budgetClass = pair.total <= 2400 ? "budget-ok" : pair.total <= 3000 ? "budget-ok" : "budget-over";
    const budgetText = pair.total <= 2400
      ? "pod 5 000 Kč/os."
      : pair.total <= 3000
        ? "pod 3 000 €"
        : "mírně nad 3 000 €";
    return `
      <div class="card-top" style="justify-content:flex-start">
        <span class="badge" style="--resort-color:${colorFor(pair.resort)}">${escapeHtml(pair.resort)}</span>
        <span class="provider-tag">${escapeHtml(pair.provider)}</span>
      </div>
      <h2>${formatEur(pair.total)} celkem</h2>
      <div class="detail-meta">${formatDate(pair.check_in)} → ${formatDate(pair.check_out)} · ${pair.nights} noci · ${escapeHtml(DATA.assumptions.split)}</div>
      <div class="detail-total">
        <div><strong>${formatEur(pair.total)}</strong><span>za obě jednotky</span></div>
        <div class="${budgetClass}">${formatCzk(pair.czk_per_person)} / os.<br><small>${budgetText}</small></div>
      </div>
      <div class="detail-metrics">
        <div class="metric"><span>Mezi ubytováními</span><strong>${formatKm(pair.distance_units_km)}</strong></div>
        <div class="metric"><span>Max. od areálu</span><strong>${formatKm(pair.max_resort_km)}</strong></div>
      </div>
      <div class="detail-units">${pair.units.map(unitRow).join("")}</div>
      <p class="detail-meta" style="margin-top:14px">Vzdálenosti jsou vzdušnou čarou. Ověřit dojezd, daně a simultánní dostupnost.</p>`;
  }

  function cardHtml(pair) {
    const budgetClass = pair.over_budget ? "over-budget" : "";
    return `
      <article class="pair-card ${pair.id === state.selectedId ? "selected" : ""}" data-id="${escapeHtml(pair.id)}" tabindex="0" role="button" aria-label="Vybrat ${escapeHtml(pair.resort)} za ${formatEur(pair.total)}">
        <div class="card-top">
          <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap">
            <span class="badge" style="--resort-color:${colorFor(pair.resort)}">${escapeHtml(pair.resort)}</span>
            <span class="provider-tag">${escapeHtml(pair.provider)}</span>
          </div>
          <span class="card-price ${budgetClass}">${formatEur(pair.total)}</span>
        </div>
        <div class="card-units">
          ${pair.units.map((unit) => `
            <div class="mini-unit">
              ${unitThumb(unit)}
              <h3 title="${escapeHtml(unit.title)}">${escapeHtml(unit.role)} · ${escapeHtml(unit.title)}</h3>
              <p>${unit.bedrooms} ložnice · ${formatEur(unit.price)}</p>
            </div>`).join("")}
        </div>
        <div class="card-foot">
          <span>od sebe <strong>${formatKm(pair.distance_units_km)}</strong></span>
          <span>areál <strong>${formatKm(pair.max_resort_km)}</strong></span>
          <span><strong>${formatCzk(pair.czk_per_person)}</strong> / os.</span>
        </div>
      </article>`;
  }

  function renderCards(list) {
    const cards = $("cards");
    const empty = $("empty");
    cards.innerHTML = list.map(cardHtml).join("");
    if (!list.length) {
      empty.hidden = false;
      const selectedResort = state.resort !== "all" ? resorts[state.resort] : null;
      empty.innerHTML = (selectedResort && selectedResort.data_note)
        ? escapeHtml(selectedResort.data_note)
        : "Pro zvolené filtry není žádná dvojice. Zkus zvýšit rozpočet nebo vzdálenost od areálu.";
    } else {
      empty.hidden = true;
      empty.textContent = "";
    }
    cards.querySelectorAll(".pair-card").forEach((card) => {
      const select = () => selectPair(card.dataset.id);
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

  function distanceLabel(map, a, b, text, color) {
    L.marker(midpoint(a, b), {
      interactive: false,
      icon: L.divIcon({
        className: "distance-label",
        html: escapeHtml(text),
        iconSize: null,
      }),
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
      .map(([name, resort]) => `<span><span class="legend-dot" style="--resort-color:${resort.color};background:${resort.color}"></span>${escapeHtml(name)}</span>`)
      .join("");
  }

  function drawSelection(pair) {
    if (!map || !selectionLayer) return;
    selectionLayer.clearLayers();
    if (!pair) {
      map.setView([47.5, 13.8], 8);
      return;
    }

    const color = colorFor(pair.resort);
    const markers = [];
    const resortPoints = new Set();

    for (const unit of pair.units) {
      const marker = L.marker([unit.lat, unit.lng], {
        icon: L.divIcon({
          className: `unit-marker role-${unit.role}`,
          html: escapeHtml(unit.role),
          iconSize: [34, 34],
          iconAnchor: [17, 17],
        }),
      })
        .bindTooltip(`${escapeHtml(unit.role)} osob · ${escapeHtml(unit.title)}`, { direction: "top", offset: [0, -12] })
        .addTo(selectionLayer);
      markers.push(marker);

      const point = unit.resort_point;
      resortPoints.add(`${point.lat},${point.lng}`);
      L.polyline([[unit.lat, unit.lng], [point.lat, point.lng]], {
        color,
        weight: 2,
        opacity: 0.65,
        dashArray: "7 6",
      }).addTo(selectionLayer);
      distanceLabel(map, unit, point, `areál ${formatKm(unit.resort_km)}`, color);
    }

    const [a, b] = pair.units;
    L.polyline([[a.lat, a.lng], [b.lat, b.lng]], {
      color: "#132238",
      weight: 3,
      opacity: 0.85,
    }).addTo(selectionLayer);
    distanceLabel(map, a, b, `od sebe ${formatKm(pair.distance_units_km)}`, "#132238");

    for (const key of resortPoints) {
      const [lat, lng] = key.split(",").map(Number);
      L.circle([lat, lng], {
        radius: 25000,
        color,
        weight: 1.5,
        opacity: 0.5,
        dashArray: "5 8",
        fillColor: color,
        fillOpacity: 0.025,
      }).addTo(selectionLayer);
    }

    const bounds = L.latLngBounds([a, b].map((unit) => [unit.lat, unit.lng]));
    for (const key of resortPoints) {
      const [lat, lng] = key.split(",").map(Number);
      bounds.extend([lat, lng]);
    }
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
          x: {
            title: { display: true, text: "Max. vzdálenost od areálu (km)" },
            min: 0,
            max: 26,
            grid: { color: "rgba(19,34,56,0.07)" },
          },
          y: {
            title: { display: true, text: "Celková cena (€)" },
            beginAtZero: false,
            suggestedMin: 500,
            grid: { color: "rgba(19,34,56,0.07)" },
          },
        },
        plugins: {
          legend: { position: "bottom", labels: { boxWidth: 10, usePointStyle: true } },
          tooltip: {
            callbacks: {
              label: (context) => {
                const raw = context.raw || {};
                if (raw.budgetLine) return raw.label;
                return `${raw.resort}: ${formatEur(raw.y)} · ${formatKm(raw.x)} · ${raw.pairId}`;
              },
            },
          },
        },
        onClick: (event, elements) => {
          if (!elements.length) return;
          const element = elements[0];
          const dataset = chart.data.datasets[element.datasetIndex];
          if (!dataset || !dataset.pairIds) return;
          const pairId = dataset.pairIds[element.index];
          if (pairId) selectPair(pairId);
        },
      },
    });
  }

  function renderChart(list) {
    if (!chart) return;
    const datasets = [];
    for (const [name, resort] of Object.entries(resorts)) {
      const points = list.filter((pair) => pair.resort === name);
      if (!points.length) continue;
      datasets.push({
        label: name,
        type: "scatter",
        data: points.map((pair) => ({
          x: pair.max_resort_km,
          y: pair.total,
          pairId: pair.id,
          resort: pair.resort,
        })),
        pairIds: points.map((pair) => pair.id),
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
      fill: false,
    });
    datasets.push({
      label: "3 000 €",
      type: "line",
      data: [{ x: 0, y: 3000, budgetLine: true, label: "3 000 €" }, { x: 25, y: 3000, budgetLine: true, label: "3 000 €" }],
      borderColor: "#b45309",
      borderDash: [4, 5],
      borderWidth: 1.5,
      pointRadius: 0,
      fill: false,
    });
    chart.data.datasets = datasets;
    chart.update();
  }

  function renderProvisional() {
    const target = $("provisionalTable");
    let items = DATA.provisional || [];
    if (!target) return;
    if (reviewFilterActive()) {
      items = items.filter((pair) => reviewPass(pair.units));
    }
    if (!items.length) {
      target.innerHTML = "<p class='detail-meta'>Pro zvolený filtr recenzí nejsou orientační data (trivago hodnocení neuvádí).</p>";
      return;
    }
    const rows = items.map((pair) => {
      const seven = pair.units.find((unit) => unit.role === "7");
      const five = pair.units.find((unit) => unit.role === "5");
      const unitLink = (unit) => unit && unit.url
        ? `<a href="${escapeHtml(unit.url)}" target="_blank" rel="noopener">${escapeHtml(unit.name)}</a>`
        : escapeHtml(unit ? unit.name : "—");
      return `<tr>
        <td>${escapeHtml(pair.area)}</td>
        <td>${unitLink(seven)}<br><span class="unit-meta">${seven ? formatEur(seven.price) : "—"}</span></td>
        <td>${unitLink(five)}<br><span class="unit-meta">${five ? formatEur(five.price) : "—"}</span></td>
        <td><strong>${formatEur(pair.total)}</strong><br><span class="unit-meta">${formatCzk(Math.round(pair.total * 25 / 12))} / os.</span></td>
      </tr>`;
    }).join("");
    target.innerHTML = `<table>
      <thead><tr><th>Středisko</th><th>7 osob / orientační</th><th>5 osob / orientační</th><th>Celkem / 4 noci</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>`;
  }

  function renderBest() {
    const target = $("bestTable");
    const items = DATA.best_options || [];
    if (!target) return;
    if (!items.length) {
      target.innerHTML = "<p class='detail-meta'>Nejsou data.</p>";
      return;
    }
    const cell = (option) => {
      if (!option || !reviewPass(option.units)) return "—";
      const units = option.units.map((unit) =>
        `<div class="multi-unit"><strong>${escapeHtml(unit.role)} osob</strong> · ${unit.bedrooms} ložnice · ${formatEur(unit.price)} · <a href="${escapeHtml(unit.url)}" target="_blank" rel="noopener">${escapeHtml(unit.title)}</a></div>`
      ).join("");
      const providers = [...new Set(option.units.map((unit) => unit.provider || "Airbnb"))];
      const providerLabel = providers.length > 1 ? "Mix" : providers[0];
      return `<div class="best-option"><strong>${escapeHtml(option.split)} · ${formatEur(option.total)}</strong> <span class="provider-tag">${escapeHtml(providerLabel)}</span><span class="unit-meta">${formatCzk(option.czk_per_person)} / os. · areál ${formatKm(option.max_resort_km)} · od sebe ${formatKm(option.max_unit_km)}</span><div class="best-units">${units}</div></div>`;
    };
    const rows = items.map((item) => {
      const two = cell(item.best_two);
      const multi = cell(item.best_multi);
      if (two === "—" && multi === "—") return "";
      return `<tr><td><strong>${escapeHtml(item.resort)}</strong></td><td>${two}</td><td>${multi}</td></tr>`;
    }).filter(Boolean).join("");
    target.innerHTML = rows
      ? `<table><thead><tr><th>Středisko</th><th>2 jednotky</th><th>3+ jednotky</th></tr></thead><tbody>${rows}</tbody></table>`
      : "<p class='detail-meta'>Pro zvolený filtr recenzí není žádná nejlepší volba.</p>";
  }

  function renderMulti() {
    const target = $("multiTable");
    const items = DATA.multi_pairs || [];
    if (!target) return;
    const areaSelect = $("multiArea");
    const splitSelect = $("multiSplit");
    const providerSelect = $("multiProvider");
    if (!areaSelect.dataset.ready) {
      const areas = [...new Set(items.map((item) => item.area))].sort();
      const splits = [...new Set(items.map((item) => item.split))].sort();
      areaSelect.innerHTML = `<option value="all">Všechna střediska</option>` + areas.map((area) => `<option value="${escapeHtml(area)}">${escapeHtml(area)}</option>`).join("");
      splitSelect.innerHTML = `<option value="all">Všechna rozdělení</option>` + splits.map((split) => `<option value="${escapeHtml(split)}">${escapeHtml(split)}</option>`).join("");
      areaSelect.dataset.ready = "1";
      areaSelect.addEventListener("change", renderMulti);
      splitSelect.addEventListener("change", renderMulti);
      providerSelect.addEventListener("change", renderMulti);
    }
    const area = areaSelect.value || "all";
    const split = splitSelect.value || "all";
    const provider = providerSelect.value || "all";
    const filtered = items.filter((item) =>
      (area === "all" || item.area === area) &&
      (split === "all" || item.split === split) &&
      (provider === "all" || (item.provider || "Airbnb") === provider) &&
      reviewPass(item.units)
    );
    if (!filtered.length) {
      target.innerHTML = "<p class='detail-meta'>Pro zvolený filtr není varianta.</p>";
      return;
    }
    const rows = filtered.slice(0, 120).map((item) => {
      const units = item.units.map((unit) => `<div class="multi-unit"><strong>${escapeHtml(unit.role)} osob</strong> · ${unit.bedrooms} ložnice · ${formatEur(unit.price)} · ${escapeHtml(ratingLabel(unit))} · <a href="${escapeHtml(unit.url)}" target="_blank" rel="noopener">${escapeHtml(unit.title)}</a></div>`).join("");
      return `<tr>
        <td>${escapeHtml(item.area)}</td>
        <td>${escapeHtml(item.split)}</td>
        <td><span class="provider-tag">${escapeHtml(item.provider || "Airbnb")}</span></td>
        <td><div class="multi-units">${units}</div></td>
        <td><strong>${formatEur(item.total)}</strong><br><span class="unit-meta">${formatCzk(item.czk_per_person)} / os.</span></td>
        <td>${formatKm(item.max_unit_km)}<br><span class="unit-meta">od sebe max.</span></td>
        <td>${formatKm(item.max_resort_km)}<br><span class="unit-meta">od areálu max.</span></td>
      </tr>`;
    }).join("");
    target.innerHTML = `<table>
      <thead><tr><th>Středisko</th><th>Rozdělení</th><th>Zdroj</th><th>Jednotky</th><th>Celkem / 4 noci</th><th>Mezi jednotkami</th><th>Od areálu</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>`;
  }

  function renderBookingLocal() {
    const target = $("bookingLocalTable");
    const items = DATA.booking_local || [];
    if (!target) return;
    if (!items.length) {
      target.innerHTML = "<p class='detail-meta'>Zatím nejsou Booking data.</p>";
      return;
    }
    const rows = items.filter((pair) => reviewPass(pair.units)).map((pair) => {
      const seven = pair.units.find((unit) => unit.role === "7");
      const five = pair.units.find((unit) => unit.role === "5");
      const unitLink = (unit) => unit && unit.url
        ? `<a href="${escapeHtml(unit.url)}" target="_blank" rel="noopener">${escapeHtml(unit.title)}</a>`
        : escapeHtml(unit ? unit.title : "—");
      return `<tr>
        <td>${escapeHtml(pair.area)}</td>
        <td>${unitLink(seven)}<br><span class="unit-meta">${seven ? `${seven.bedrooms} ložnice · ${formatEur(seven.price)} · ${escapeHtml(ratingLabel(seven))} · ${escapeHtml(seven.address || "")}` : "—"}</span></td>
        <td>${unitLink(five)}<br><span class="unit-meta">${five ? `${five.bedrooms} ložnice · ${formatEur(five.price)} · ${escapeHtml(ratingLabel(five))} · ${escapeHtml(five.address || "")}` : "—"}</span></td>
        <td><strong>${formatEur(pair.total)}</strong><br><span class="unit-meta">${formatCzk(Math.round(pair.total * 25 / 12))} / os.</span></td>
      </tr>`;
    }).join("");
    if (!rows) {
      target.innerHTML = "<p class='detail-meta'>Pro zvolený filtr recenzí není žádná Booking varianta.</p>";
      return;
    }
    target.innerHTML = `<table>
      <thead><tr><th>Středisko</th><th>7 osob</th><th>5 osob</th><th>Celkem / 4 noci</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>`;
  }

  function selectPair(id) {
    if (!pairById.has(id)) return;
    state.selectedId = id;
    const pair = pairById.get(id);
    $("detailPanel").innerHTML = detailHtml(pair);
    document.querySelectorAll(".pair-card").forEach((card) => {
      card.classList.toggle("selected", card.dataset.id === id);
    });
    drawSelection(pair);
    if (window.matchMedia("(max-width: 1050px)").matches) {
      $("map").scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }

  function render() {
    const list = filteredPairs();
    if (!state.selectedId || !list.some((pair) => pair.id === state.selectedId)) {
      state.selectedId = list.length ? list[0].id : null;
    }
    const selected = state.selectedId ? pairById.get(state.selectedId) : null;
    $("detailPanel").innerHTML = detailHtml(selected);
    const airbnbCount = list.filter((pair) => pair.provider === "Airbnb").length;
    const bookingCount = list.filter((pair) => pair.provider === "Booking").length;
    const mixCount = list.filter((pair) => pair.provider === "Mix").length;
    $("resultCount").textContent = `Zobrazeno ${list.length} z ${pairs.length} dvojic (Airbnb ${airbnbCount}, Booking ${bookingCount}, Mix ${mixCount}). Cíl 3 000 € celkem / 5 000 Kč na osobu.`;
    renderCards(list);
    renderChart(list);
    drawSelection(selected);
    renderBest();
    renderProvisional();
    renderMulti();
    renderBookingLocal();
  }

  function initControls() {
    const resortSelect = $("resort");
    resortSelect.innerHTML = `<option value="all">Všechna střediska</option>` +
      resortNames.map((name) => `<option value="${escapeHtml(name)}">${escapeHtml(name)}</option>`).join("");
    resortSelect.addEventListener("change", () => {
      state.resort = resortSelect.value;
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

    $("sort").addEventListener("change", (event) => {
      state.sort = event.target.value;
      render();
    });

    $("only5k").addEventListener("change", (event) => {
      state.only5k = event.target.checked;
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
      state.budget = 3500;
      state.maxResort = 25;
      state.maxUnits = 60;
      state.only5k = false;
      state.minRating = 0;
      state.minReviews = 0;
      state.requireReviews = false;
      state.sort = "price";
      resortSelect.value = "all";
      $("provider").value = "all";
      budget.value = "3500";
      budgetOut.textContent = formatEur(3500);
      maxResort.value = "25";
      maxResortOut.textContent = formatKm(25);
      maxUnits.value = "60";
      maxUnitsOut.textContent = formatKm(60);
      $("only5k").checked = false;
      minRating.value = "0";
      minRatingOut.textContent = "0 / 5";
      minReviews.value = "0";
      minReviewsOut.textContent = "0";
      $("requireReviews").checked = false;
      $("sort").value = "price";
      render();
    });
  }

  initControls();
  initMap();
  initChart();
  render();
})();
