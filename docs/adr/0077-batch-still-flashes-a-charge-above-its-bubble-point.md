# 0077. Batch still: a charge above its bubble point flashes to the still's pressure first

- **Status:** Proposed
- **Date:** 2026-11-19

## Context

The batch still (ADR 0055, 0061, 0068) starts its boil-up at the charge's bubble point at the
still's pressure, the first cut's without a feed. A charge that enters hotter than that bubble
point is not flashed. With `heat_up` (ADR 0063) the charge's heat-up is 0 and a note says
"its flash is not modelled". The boil-up then evaporates, and its duty pays for, vapour that the
charge's own sensible heat would flash off as the still is evacuated. Two process-library
entries on core 1.11.0 do this by hand (core#279):

- **oxalyl-chloride-1 L-4:** ST101 is charged from the reactor at 333.15 K and stripped at
  15 kPa(a). The charge's bubble point there is 319.3 K.
- **methanesulfonyl-chloride-1 L-4:** the crude enters C-101 at 368.15 K and is evacuated to
  4 kPa(a), where its bubble point is 301.8 K. Its `scripts/balance.py` runs an adiabatic
  differential flash as a cross-check: 321.1 K, 69.7 % of the thionyl chloride and 4.8 % of the
  methanesulfonyl chloride to E-103, 2.623 kW year average. The duty stays inside the still's
  Q3 (steam) and Q4 (brine), so Q3 is conservative by up to that much. A separate Q10 had
  counted it twice.

The options for the flash:

1. **An equilibrium (closed) flash.** One stage, where the vapour stays with the liquid until
   the end: `H_charge(T_in) = H_L(T) + H_V(T)` at the still's pressure. This suits a throttled
   feed into a drum. A still that is evacuated takes the vapour off as it forms.
2. **A differential (open) flash.** The vapour leaves as it forms, in equilibrium with the
   liquid at its bubble point at the falling pressure, and the liquid's sensible heat
   evaporates it. With `y_i = x_i P_i(T) / sum_j x_j P_j(T)` (Raoult's law at the bubble
   pressure the evacuation passes), the path does not depend on how fast the pressure falls.
   It is an ODE in the temperature that ends where the liquid's bubble pressure reaches the
   still's. This is the Rayleigh still's own picture. It is also the entry's cross-check.

The vapour's destination: (a) the first cut, through the still's condenser and into its
receiver; (b) a vent, which would need a new outlet port on the still and a condenser model
for it (ADR 0062's vent is a batch reactor's).

## Decision

- **`still.flash: true`** (volatility raoult, opt-in, left out of the still's dump when unset).
  A charge above its bubble point at the still's pressure first flashes adiabatically and
  differentially to that pressure (option 2). The pressure is the first cut's without a feed,
  as for the boil-up (ADR 0068), and the still's with a feed. `batch_still.flash_charge`
  integrates `dN_i/dT = y_i C(N) / lambda(y)` with `C = sum_i N_i cp_i` from the charge's
  temperature downwards (Dormand-Prince 5(4) in T, relative tolerance 1e-9). It stops where
  the liquid's bubble pressure falls to the still's (bisected in the step). The flash ends at
  the flashed liquid's bubble point. Its heat is the vapour's latent heat, which equals the
  sensible heat the content gave up. `C` counts all of the content: the liquid, a
  `nonvolatile` solute and a `separate_phase` component, at their `liquid_heat_capacity`, as
  `heat_up` does. A charge at or below its bubble point does not flash: it solves exactly as
  without the field.
- **The vapour goes to the first cut** (option a). The still's condenser is on line while the
  still is evacuated. The first cut's receiver is the only one the still has for vapour, and it
  is where the lightest fraction belongs. A vent would lose a condensable solvent and need a
  port and a vent condenser the still does not have. With a column, the flash's vapour passes
  the column before reflux is set up and is not rectified: it joins the first cut at the
  composition it flashed with. A plant that vents the flash models the vent itself.
- **The boil-up is credited.** The boil-up, its time, its duty and the column's design
  (`minimum_reflux_factor`) start from the flashed liquid at its bubble point. The boil-up no
  longer evaporates the flash's vapour. The first cut holds the flash's vapour plus what it
  boils up. An end at a share distilled counts the flash's vapour (it is distilled), and so does
  a purity end's mean over the first cut. The flash takes no time: the evacuation's time is not
  modelled. With `heat_up` the charge's heat-up is 0, without the "not modelled" note. The
  vessel's metal (ADR 0063) is not in the flash. Its term starts at the flash's end, as it
  started at the bubble point before. The condenser's duty (`condenser_port`, ADR 0061)
  condenses the flash's vapour too: a `flash` term beside `condensation`.
- **Data.** The flash needs the charge's temperature (its stream's state), every charged
  component's `liquid_heat_capacity` and every volatile one's `heat_of_vaporization`. Without
  them the still is not solved (`cheme.process-still-unsolved`, naming what is missing).
  With the field, the outlets' fingerprint takes the charge's temperature and those heats, so
  a change to any of them makes the outlets stale. Without it, nothing changes.
- **Report.** `cheme process stills` gives `flash`: the cut it goes to, the pressure, the
  charge's inlet temperature and bubble point, the temperature after the flash, the vapour
  (kmol and kg per hour of flows and per batch, mole fractions), its heat per batch and year
  average. The text output adds a line for it. The basis adds an assumption that names the flash.

## Consequences

- methanesulfonyl-chloride-1 ST101 with `flash: true` (a scratch copy of process-library main,
  this branch): the charge flashes from 368.15 to 321.12 K and gives 2.562 kmol (302.4 kg) a
  batch to the forerun, 78.76 mol% thionyl chloride, with 25.00 kWh a batch, 2.623 kW year
  average. That is the entry's own cross-check, from an independent Euler integration. The
  boil-up falls from 72.78 to 35.47 kWh a batch (0.607 to 0.296 h). The credit is larger than
  the flash's heat because the column boils up (R + 1) per mole distilled. The condenser's
  year average falls from 7.636 to 6.345 kW (3.722 boil-up plus 2.623 flash). The flash's
  methanesulfonyl chloride is not rectified, so the forerun takes 4.222 kmol at 31.6 mol% MsCl
  instead of 3.716 at 22.3 mol%.
- oxalyl-chloride-1 ST101 with `flash: true`: 333.15 to 320.69 K, 5.686 kmol (809.7 kg) a batch
  to the crude cut, 52.72 kWh. The boil-up falls from 541.8 to 489.6 kWh a batch (12.04 to
  10.88 h); the residue's end is unchanged.
- Without the field every still solves, reports and fingerprints as before. The process
  library's `stills --json`, `recipe --json` and `propagate --check` are unchanged.
- A still's schema changed, and `schema.py` is a generator module (ADR 0067), so every BFD/PFD
  needs `cheme process build` once (only `generator_sha256` changes).
- Not covered: a swap's feed that enters above the still's temperature (its note stays); an
  equilibrium flash (a drum before the still is a separate flash step); the evacuation's time;
  the vessel's metal giving heat to the flash (it would flash a little more); a temperature-
  dependent heat of vaporization or heat capacity (both are constant, as in the boil-up).

## Evidence

- core#279; this pull request.
- `src/chemeascode/domains/process/batch_still.py` (`flash_charge`, `_flashed`, `Flash`,
  the report), `schema.py` (`Still.flash`), `duties.py` (`still_condenser_duty`),
  `model_basis.py` (`FLASH`).
- `tests/test_still_flash.py`: one volatile component against the closed form
  `C = C_0 exp(cp_A (T - T_in) / lambda)` and the boil-up credited by exactly the flash's heat.
  A binary against an independent RK4 in T. A charge below its bubble point solves as without
  the field. The first cut's own pressure. The refusals. The report, propagate's condenser duty
  and the fingerprint.
