function submitForm() {
  const year = document.getElementById("Year").value;
  const weatherYear = document.getElementById("weatherYear").value;
  const scenario = document.getElementById("scenario").value;
  const state = document.getElementById("stateInput").value.trim().toLowerCase() || "__ALL_STATES__";
  const custom_values = {};
  const fallback_scenarios = {};

  document.querySelectorAll(".percentInput").forEach(input => {
    const subsector = input.dataset.subsector;
    const value = parseFloat(input.value);
    if (!isNaN(value) && value > 0) {
      custom_values[[state, subsector]] = value;
    }
  });

  document.querySelectorAll(".scenarioInput").forEach(input => {
    const subsector = input.dataset.subsector;
    const value = input.value.trim().toLowerCase();
    fallback_scenarios[subsector] = value || "baseline";
  });

  const payload = {
    year,
    scenario,
    weather_year: weatherYear,
    custom_values,
    fallback_scenarios,
  };

  fetch("http://localhost:5000/process", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  }).then(async res => {
    if (res.ok) {
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "custom_output.csv";
      a.click();
    } else {
      const err = await res.json();
      alert("Error: " + err.error);
    }
  });
}

const subsectors = [
  'commercial air conditioning', 'commercial cooking', 'commercial lighting',
  'commercial other', 'commercial refrigeration', 'commercial space heating',
  'commercial ventilation', 'commercial water heating', 'data center cooling',
  'data center it', 'district services', 'office equipment (non-p.c.)',
  'office equipment (p.c.)', 'streetlights', 'agriculture-crops',
  'agriculture-other', 'aluminum industry', 'balance of manufacturing other',
  'bulk chemicals', 'cement', 'coal mining', 'computer and electronic products',
  'construction', 'electrical equip., appliances, and components',
  'fabricated metal products', 'food and kindred products',
  'glass and glass products', 'machinery', 'metal and other non-metallic mining',
  'oil & gas mining', 'paper and allied products', 'petroleum refining',
  'plastic and rubber products', 'transportation equipment', 'wood products',
  'residential air conditioning', 'residential ceiling fans',
  'residential clothes drying', 'residential clothes washing',
  'residential cooking', 'residential cooking - secondary',
  'residential dehumidifiers', 'residential dishwashing', 'residential freezing',
  'residential furnace fans and boiler pumps', 'residential hot tubs',
  'residential humidifiers', 'residential lighting', 'residential microwaves',
  'residential other', 'residential pool pumps', 'residential refrigeration',
  'residential secondary heating', 'residential space heating',
  'residential tv and peripherals', 'residential water heating',
  'combination long-haul truck', 'combination short-haul truck',
  'light-commercial truck', 'motor home', 'other bus', 'passenger car',
  'passenger rail', 'passenger truck', 'refuse truck', 'school bus',
  'single unit long-haul truck', 'single unit short-haul truck', 'transit bus'
];

window.onload = () => {
  const container = document.getElementById("subsectorInputs");

  subsectors.forEach(subsector => {
    const div = document.createElement("div");
    div.style.display = "flex";
    div.style.gap = "10px";
    div.style.alignItems = "center";
    div.style.marginBottom = "4px";

    const label = document.createElement("label");
    label.textContent = subsector;
    label.style.width = "300px";

    const percentInput = document.createElement("input");
    percentInput.type = "number";
    percentInput.min = "0";
    percentInput.max = "10";
    percentInput.step = "0.01";
    percentInput.placeholder = "0.0";
    percentInput.style.width = "60px";
    percentInput.dataset.subsector = subsector;
    percentInput.className = "percentInput";

    const scenarioInput = document.createElement("input");
    scenarioInput.type = "text";
    scenarioInput.placeholder = "baseline";
    scenarioInput.style.width = "100px";
    scenarioInput.dataset.subsector = subsector;
    scenarioInput.className = "scenarioInput";

    div.appendChild(label);
    div.appendChild(percentInput);
    div.appendChild(scenarioInput);
    container.appendChild(div);
  });
};
