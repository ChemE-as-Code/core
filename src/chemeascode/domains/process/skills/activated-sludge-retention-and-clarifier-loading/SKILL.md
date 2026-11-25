---
name: activated-sludge-retention-and-clarifier-loading
description: Review nominal hydraulic retention time, suspended-solids retention time and secondary clarifier hydraulic and solids loading for continuous activated-sludge trains. Use for A2/O or MLE example comparisons, a change of wasting or recycle duty, or a request to judge whether existing data support a loading or capacity decision.
---

# Activated-sludge retention and secondary clarifier loading

## Purpose and when to use

Apply this review after the biological train and recycle routes have been drawn. It covers a continuous suspended-growth waterline with a gravity secondary clarifier. Identify the biological-volume, total-solids and clarifier boundaries on the flowsheet. A per-pass contact time, a nitrifier retention target and a peak clarifier rating each answer a different design question. SBR decant cycles, membrane separation, attached growth and sidestream solids require their own boundaries.

Solids inventory is the mass of solids held in a unit at the time of observation (kg TSS on a TSS basis). In Korean use **고형물 보유량**. Distinguish this mass from concentration (mg/L) and the solids loss rate (kg TSS/day).

## Required inputs and missing inputs

Keep units, flow path, sample location, time basis and source with every input. Distinguish a model setting, model output, site measurement and engineering assumption. Match inventory and losses in time. For variable wasting obtain the actual volume wasted and its solids concentration over the observation period.

| Requested quantity | Minimum inputs | If a required input is missing |
| --- | --- | --- |
| Nominal biological HRT | In-service biological liquid volumes and external influent flow | Report only zones with known volume, or defer the ratio if influent flow is unknown. |
| Reactor-only TSS SRT | Volume and representative mixed-liquor TSS in every biological zone, plus all external solids losses | If either mass or loss is incomplete, defer this SRT. |
| Waterline TSS SRT | Reactor and clarifier solids inventories and all external solids losses | If only the clarifier inventory is missing, report reactor-only SRT with its boundary and mark waterline SRT as deferred. Request a representative depth profile and the volumes it represents, or a separate documented estimate. |
| Hydraulic surface loads | Effective online settling area and the particular flow named in the numerator | Calculate each supported ratio separately. |
| Applied clarifier solids load | Actual clarifier feed flow and its TSS at the same point and time, plus online settling area | Defer the solids load if feed TSS or routing is unknown. |

For parallel units obtain the flow split and online area before assigning individual-unit loads. A combined duty can mask unequal distribution. Ask separately for peak hydrographs, peak solids loads, settling observations and the intended design criterion before judging capacity.

## Workflow and tools

1. Inspect the flowsheet, recorded stream results and reactor/clarifier data. `cheme process streams --json` can identify stream connections and available recorded quantities. Locate reactor and settler inventories in the run evidence; the stream table alone may be insufficient.
2. Sketch the external influent, effluent, waste activated sludge (WAS), return activated sludge (RAS), clarifier feed and internal mixed-liquor recycle. Confirm the waste take-off point. For a single waterline wasting from clarifier underflow with constant water storage, check `Qin = Qeff + Qwas` and `Qfeed = Qeff + Qwas + Qras`. Adjust the balances for any other crossing or change in storage. An internal recycle split upstream of the clarifier contributes only through material that actually reaches its feed.
3. Assemble a JSON snapshot with `tanks` (objects with `id`, `zone`, `volume_m3`,
   `mlss_mg_L`), `clarifier` (`area_m2`, `height_m`, `n_layers`, `layer_tss_mg_L`) and
   `streams` (objects keyed by `INFLUENT`, `EFFLUENT`, `WAS`, `RAS`, and `TO_CLARIFIER`,
   with `flow_m3_d` and `tss_mg_L`). Record time, sources and assumptions alongside the
   snapshot. Omit unknown fields or use null. Run `cheme process activated-sludge-review
   snapshot.json`. It returns `calculated` values and units, `deferred` reasons, and water-balance
   status. Review any unevaluable boundary before using the result for a design decision.
   The command assumes equal-volume clarifier layers and a single underflow wasting location.
4. Nominal biological HRT (h) = 24 × in-service biological volume (m³) / external influent (m³/d). For a zone, replace the numerator by its volume. For a per-pass estimate use the actual throughflow of that zone, including recycles crossing it, and label it accordingly.
5. Inventory (kg TSS) = sum of volume (m³) × representative TSS (mg/L) / 1,000 for each unit or layer. A single stirred tank's outlet may represent its mixed liquor when complete mixing applies. Weight layers by volume; a simple arithmetic mean requires equal-volume layers. External loss (kg TSS/d) = sum of flow (m³/d) × TSS (mg/L) / 1,000 over effluent, WAS and any other solids exits. Pair flow and concentration for each time interval when averaging losses. Divide the chosen inventory by external loss (d). Internal recycle and RAS remaining within the system do not remove solids from the waterline.
6. Label all surface loads by numerator and effective online area A. Report actual effluent overflow Qeff/A, external influent Qin/A when the comparison reference uses influent, and clarifier feed Qfeed/A (m³/m²/d). Applied solids loading = Qfeed × feed TSS / (1,000 × A) (kg TSS/m²/d). Divide a daily flux by 24 for an hourly unit on the same average basis; an hourly peak needs its own observation.

## Worked example with and without a clarifier profile

Consider a hypothetical snapshot. The bioreactor holds 1,000 m³ at 3,000 mg/L MLSS, giving **3,000 kg TSS**. Daily external losses are 280 kg TSS/day via WAS and 20 kg TSS/day via the secondary effluent, for **300 kg TSS/day**. RAS stays inside the waterline boundary.

For the complete data case, assume a constant clarifier plan area of 200 m² and a water depth of 3 m. Divide the water column into four 0.75 m depth bands, each with a volume of 150 m³. The bottom band represents the sludge blanket at 6,000 mg/L TSS. For this example only, assume the solids in the three upper bands are negligible and use 0 mg/L there. Bands represent portions of the water column used to sum solids mass. With these inputs, the clarifier holds **150 m³ × 6 kg TSS/m³ = 900 kg TSS**.

| Data available | Bioreactor solids inventory | Clarifier solids inventory | Reactor-only TSS SRT | Waterline TSS SRT |
| --- | ---: | ---: | ---: | ---: |
| Complete clarifier TSS profile | 3,000 kg TSS | 900 kg TSS | 3,000 / 300 = **10 days** | (3,000 + 900) / 300 = **13 days** |
| Clarifier TSS profile missing | 3,000 kg TSS | **Deferred** | 3,000 / 300 = **10 days** | **Deferred** |

The same loss rate applies in both cases. Including 900 kg TSS in the numerator adds 3 days (30% relative to reactor-only SRT). If only the clarifier area, blanket thickness or RAS concentration is available, request a representative clarifier TSS profile or document the assumptions of any separate estimate. Preserve hydraulic or loading results when their own inputs are complete.

To reproduce the example with `cheme process activated-sludge-review`, use this snapshot. To reproduce the missing-profile case, remove `layer_tss_mg_L` or set it to `null`.

```json
{
  "tanks": [{"id": "BIO", "zone": "aerobic", "volume_m3": 1000, "mlss_mg_L": 3000}],
  "clarifier": {
    "area_m2": 200, "height_m": 3, "n_layers": 4,
    "layer_tss_mg_L": [6000, 0, 0, 0]
  },
  "streams": {
    "INFLUENT": {"flow_m3_d": 2035},
    "EFFLUENT": {"flow_m3_d": 2000, "tss_mg_L": 10},
    "WAS": {"flow_m3_d": 35, "tss_mg_L": 8000},
    "RAS": {"flow_m3_d": 1161, "tss_mg_L": 8000},
    "TO_CLARIFIER": {"flow_m3_d": 3196, "tss_mg_L": 3000}
  }
}
```

## Validation and failure handling

- Verify positive volumes, area and influent, nonnegative finite concentrations and flows, consistent units, matched observation times and the two water balances for the selected layout. Resolve a misrouted feed before interpreting dependent quantities. Check against a hand substitution.
- Unknown loss differs from observed zero loss. With incomplete losses or zero total loss, leave the retention ratio unavailable and keep any independent hydraulic calculation. Check unmeasured waste events.
- Compare each reference equation's numerator, solids basis (TSS/VSS), inventory boundary, time basis and wasting point. The mixed-liquor wasting shortcut V/Qw requires its own assumptions. Record how much inventory or loss an omission would remove when both values are available.
- Evidence missing for peak capacity or biological performance is a separate finding from a missing input to arithmetic. A valid average load can still be reported.

## Outputs and provenance

Return a row per metric with value, unit, boundary, flow basis, time basis, source and assumptions. List unsupported decisions and the specific observation that would resolve each. Preserve the source run and distinguish a day-end model snapshot from a long-term operating estimate. Record comparisons and outstanding design decisions in the plant's design notes.

## Required human judgment

The designer selects the active volume, applicable inventory and time interval and verifies whether sampling represents the process. To judge peak clarification, match the loading convention and local design criteria to service condition, settling/flux data, blanket behaviour and available online area. To judge nitrification, examine cold-season temperature, aerobic conditions (DO, pH/alkalinity), nitrogen load, kinetics and a justified aerobic retention requirement. To judge biological phosphorus removal, examine the model's P processes, anaerobic-zone conditions, available substrate and appropriate P measurements. Record the evidence for each plant-specific conclusion.

## References

- Henze, van Loosdrecht, Ekama and Brdjanovic (eds.), *Biological Wastewater Treatment: Principles, Modelling and Design* (2008), ch. 4, pp. 56–57, Eqs. 4.1–4.3 (waste location, assumed small solids losses, nominal and throughflow residence time); ch. 12, pp. 321–323, especially Eq. 12.8 and Fig. 12.25 (feed solids flux and hydraulic numerator).
- Olsson and Newell, *Wastewater Treatment Systems: Modelling, Diagnosis and Control*, §18.6, pp. 469–471, Eqs. 18.39–18.41 (aerator/settler balance, effluent and wasting, averaging and simplified inventory). Including the measured or modelled settler mass in the reported ratio is the explicit waterline boundary choice.
- Rieger et al., *Guidelines for Using Activated Sludge Models*, pp. 42 and 84 (waste data, sampling and limits on SRT interpretation). A project-specific capacity or performance criterion needs its own source.
