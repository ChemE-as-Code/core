# 0061. Batch rectification: a column on the batch still, on the Fenske-Underwood-Gilliland shortcut

- **Status:** Proposed
- **Date:** 2026-11-06

## Context

The batch still of ADR 0055 is one equilibrium stage without reflux. It strips and swaps
solvents, but it cannot reach a product's purity: at alpha 4 from x0 = 0.5, Rayleigh gives a
distillate of 0.70 mole fraction at 84 % recovery of the light key. The library's product
distillations work around it (core#173):

- acetyl-chloride-1: one stage gives 97.31 wt% acetyl chloride with 2.61 wt% PCl3 (D-007); the
  column K101 is a specified split in a script (99 % of the acetyl chloride and 6 % of the PCl3
  to the product, from a patent's other crude, D-008);
- benzoyl-chloride-1: the column K101 is a specified split in a script (99.5 % of the benzoyl
  chloride, 2 % of the benzotrichloride, 1 % of the benzoic acid, D-008);
- benzyl bromide, MeI and Boc2O the same (process-library #147, #156, #160, #163).

Both entries also typed the reboiler's share for the reflux by hand (acetyl-chloride-1 Q7,
benzoyl-chloride-1 Q6: the reflux ratio times the latent heat of the distillate), entered the
still's `boilup` as the net distillate rate (half the reboiler), and kept the condenser's duty
(Q4, Q5) in the script: ADR 0059 writes one duty per node and leaves condensers typed.

Options considered:

1. **A rigorous batch column** (stage-by-stage MESH with holdup, as Diwekar's BATCH-DIST or
   PharmaPy's `BatchDistillation`). Stiff, needs tray holdups and hydraulics the library entries
   do not have, and PharmaPy cannot be a dependency (ADR 0055).
2. **DWSIM's steady-state column** at the still's starting composition. One point of the
   path, not the batch; core's DWSIM coupling is steady state (ADR 0014, 0033).
3. **Diwekar's shortcut batch column** (Diwekar and Madhavan 1991) on core's
   Fenske-Underwood-Gilliland (`separations/shortcut.py`), on the
   ADR 0055 still's integrator: pure Python, deterministic, every input already in the still's
   data except the stages and the reflux.

## Decision

cheme-as-code takes option 3, in `domains/process/batch_still.py`.

- **Schema** (`schema.py`, all fields left out of the dump when unset, so a still without them
  fingerprints as in 1.9.0):
  - `still.column: {stages | minimum_reflux_factor, reflux: constant | constant_distillate,
    ratio, distillate: {key, mole_fraction}, maximum_ratio, heavy_key, provenance, source}`.
    `stages` are theoretical stages, the still included. `reflux: constant` takes `ratio`
    (L/D). `constant_distillate` holds the `distillate`'s mole fraction of its key by raising
    the reflux, up to `maximum_ratio`, past which the reflux stays there and the purity falls.
    `minimum_reflux_factor` designs the column at the start instead of `stages`: R = factor x
    Underwood's Rmin for the `distillate`, the stages from Gilliland at that R (not rounded:
    a note says so); with `constant` the reflux stays at that R.
  - a new end `purity: {key, fraction}` (with `basis: mole | mass`): the cut's mean share of
    the key falls to the fraction. A product cut collected to its specification, for any still,
    with or without a column. A key leaner than the fraction when the cut starts reaches its
    end at once (an empty cut and a note).
  - `still.condenser_port`: the energy port (out) whose stream carries the condenser's duty.
- **Model.** At each point of the still's path the column is a continuous one fed with the
  still's liquid x_B as a saturated liquid, in quasi-steady state, at constant molar overflow:
  - the distillate from Hengstebeck-Geddes at the Fenske index C1, `x_D,i = alpha_i^C1 x_B,i /
    sum_j alpha_j^C1 x_B,j`;
  - Underwood's root of `sum_i alpha_i x_B,i / (alpha_i - theta) = 0` between the heavy key and
    the next lighter component the still holds (between the two most volatile left once the
    heavy key is gone), and `Rmin = sum_i alpha_i x_D,i / (alpha_i - theta) - 1`;
  - Gilliland in Molokanov's form between them: at constant reflux, C1 such that Gilliland's
    stages equal the column's (bisection: Gilliland's stages rise with C1); at constant
    distillate, the C1 that gives the key's mole fraction and the reflux Gilliland needs for it.
  - C1 is never below 1: the distillate is never leaner than the still's own vapour (Gilliland
    underpredicts at low reflux). One stage is the still itself: C1 = 1 at any reflux.
  - The heavy key defaults to the next less volatile component of the charge after the
    distillate's key (else after the most volatile); `heavy_key` overrides it.
  - The relative volatilities are the K-values `P_i(T)/P` at the still's bubble point (raoult),
    or the constant ones, for the whole column.
  - The still's balance is ADR 0055's with the distillate for the vapour, `dN_i/dD = -x_D,i`,
    integrated over the moles distilled with the same Dormand-Prince stepper, ends and cuts.
    `(R + 1)` moles boil up per mole distilled: `dt/dD = (R + 1)/V`, `dE/dD = (R + 1)
    lambda(x_D)` (heat_of_vaporization of the distillate's composition; constant molar
    overflow). The `boilup` is the reboiler's: a vapour rate or its heat input.
- **Duties (ADR 0059 extended).** The reboiler's duty is the still's (now `(R + 1) D lambda`) on
  its `energy_port`, or, with a column, its one heat stream in. The condenser's is the same
  heat out (total condenser, no subcooling) on `still.condenser_port`, or, with a column, its
  one heat stream out (to a cooling utility). Both are written `calculated` (source `still
  duty` and `still condenser duty`), compared where given, and go stale like any propagated
  value. A one-stage still gets its condenser's duty only where `condenser_port` names it, so
  a 1.9.0 plant with two heat streams on a still is unchanged. A column without a stream out
  is `cheme.process-duty` (info).
- **Replacing the library's hand streams.** With a column the reflux share has no stream of
  its own: acetyl-chloride-1's Q7 and benzoyl-chloride-1's Q6 go, the still's `boilup` is the
  whole reboiler (150 and 200 kW, not the 75 and 100 kW net), and Q3 and Q4 carry `(R + 1) D
  lambda`. The condenser's stream (Q4, Q5) moves from K101 to the still's `condenser` port and
  is written; the product's subcooling it held stays a stream of its own (a cooler), and K101,
  its split and its return stream go.
- **Report.** `cheme process stills` gives the model `batch rectification`, basis
  `batch-shortcut` (predictive, sourced as the still's volatility data), the column's stages,
  the reflux at the start and the end (and the design at the start), each cut's mass fractions
  and recovery of every component, the reflux along the profile, and the condenser's year
  average. `model_basis` lists the column's assumptions.
- **Rules** (`cheme.process-still`): errors for a column's `distillate` key or `heavy_key` that
  is no component or is non-volatile, a purity end's key that is no component, and a
  `condenser_port` that is no energy port out of the node or is also its `energy_port`.

## Consequences

- Positive: a product's batch distillation is a flowsheet step: the purity, the recovery, the
  reflux, the boil-up time (the recipe's `distil`), the reboiler's and the condenser's duty
  follow from the stages and the reflux. `examples/process-batch-rectification` takes crude
  acetyl chloride (2.9 wt% PCl3) through 10 stages at constant distillate (0.999, reflux 0.80
  to 4): a product cut of 99.8 wt% at 99.40 % recovery, an off-cut and the residue in 2.40 h
  of boil-up at 150 kW, 360.6 kWh a batch on the reboiler and the condenser.
- Positive: it is qualified against closed forms (`tests/test_batch_rectification.py`): one
  stage is Rayleigh's still (1e-8), and a reflux only multiplies its time and energy by
  `R + 1` (1e-9); an infinite reflux (R = 1e9) is the Fenske limit, Rayleigh's closed form at
  `alpha^N` (1e-7, N = 2, 3, 6); Underwood's minimum reflux agrees with the binary's closed form
  `[x_D/x_F - alpha (1 - x_D)/(1 - x_F)]/(alpha - 1)` (1e-9); at constant distillate the cut
  is Bogart's `D = W0 (x0 - x_B)/(x_D - x_B)` (1e-8) and the time the quadrature of `(R + 1)
  dD / V` (1e-6); Gilliland's inverse round-trips (1e-9).
- Positive: against a rigorous binary column (plate to plate at the same constant alpha 2,
  constant molar overflow, no holdup, total condenser), the shortcut's distillate is never
  purer, within 0.1 in mole fraction, and the batch's mean purity from x0 = 0.5 to a residue of
  0.2 is 0.743 against 0.784 (5 stages, R 2), 0.921 against 0.946 (8, R 4), 0.993 against 0.995
  (10, R 10) and 0.951 against 0.954 (20, R 3): Gilliland's correlation is conservative, most at
  few stages and low reflux. A DWSIM column at the same reflux would be the same bound for a
  non-ideal pair; it was not run (the qualification's pair is ideal by construction).
- Positive: on scratch copies (not committed) of the library:
  - acetyl-chloride-1 (ST101 with 10 stages at reflux ratio 1, the 150 kW reboiler, its end
    unchanged at 50 mol% acetyl chloride in the residue, K101 and Q7 removed, Q4 on the still):
    99.43 wt% acetyl chloride with 0.57 wt% PCl3 at 98.19 % recovery, 19.2 % of the PCl3 over
    (the script's split assumed 6 %); 2.07 h of boil-up; Q3 and Q4 53.72 kW each, year average
    (the script's Q3 + Q7 55.17 kW, Q4 57.38 kW with the product's subcooling). Collecting the
    product to 99.84 wt% (the script's product) recovers 68.4 % at reflux 1, 99.0 % at reflux 2
    (81.1 kW) and 99.6 % at constant distillate (0.9995, reflux 1.02 to 4, 70.7 kW).
  - benzoyl-chloride-1 (5 stages at reflux 1, the 200 kW reboiler, end unchanged): 99.94 wt%
    benzoyl chloride at 97.35 % recovery, 60 % of the benzotrichloride over (the script
    assumed 2 %): the script's 99.993 wt% product is out of reach at 5 stages and reflux 1, and
    needs about 10 stages at reflux 3 (99.997 wt%, 4.3 % of the benzotrichloride over, 99.0 kW).
    Q4 and Q5 49.56 kW each, year average (the script's Q4 + Q6 50.20 kW).
  - acetyl-chloride-1, benzoyl-chloride-1, benzyl-bromide-1, benzyl-chloroformate-1,
    methyltriphenylphosphonium-bromide-1 and sodium-azide-1 unchanged: `process stills
    --json`, `propagate --check` and the full `validate` (after `process build`) print the same
    as 1.9.0; the rebuilt sheets differ only in the generator's code hash.
- Negative: a shortcut. No holdup on the stages or in the condenser (no start-up at total
  reflux, no holdup's flywheel effect on the cut's purity), the error of Gilliland's correlation,
  one Underwood root and one heavy key for the whole batch, the relative volatilities of the
  still's temperature for the whole column, constant molar overflow, an ideal liquid (ADR 0055:
  no azeotropes).
- Negative: one reflux policy for all cuts of a still (a forerun at a higher reflux is a
  separate still step); a constant distillate's key is the column's most volatile component
  while it is held.
- Limitations: the column, its condenser and the vacuum system are not sized; no reflux drum
  or decanter; no heat-up or total-reflux start-up time (a `heat` operation of the recipe); the
  condenser's duty has no subcooling; `process simulate` does not couple it.

## Evidence

- core#173; this ADR's PR. Follow-up of ADR 0055 (its Limitations) and ADR 0059 (its
  follow-up "per-cut condenser duties of a still").
- `src/chemeascode/domains/process/batch_still.py` (`_Column`, `hengstebeck`,
  `underwood_root`, `underwood_min_reflux`, `gilliland_stages`, `gilliland_reflux`, the purity
  end), `schema.py` (`Column`, `ColumnDistillate`, `PurityEnd`, `Still.column`,
  `Still.condenser_port`), `duties.py` (`condenser_target`, `condenser_duty`), `propagate.py`
  (`_duty`, `_offer`), `model_basis.py` (`batch-shortcut`).
- `tests/test_batch_rectification.py`, `examples/process-batch-rectification`.
- U. M. Diwekar, K. P. Madhavan (1991) Multicomponent batch distillation column design, Ind.
  Eng. Chem. Res. 30, 713-721; U. M. Diwekar (2012) Batch Distillation: Simulation, Optimal
  Design and Control, 2nd ed., CRC Press (the shortcut method, with the Hengstebeck-Geddes
  equation); J. D. Seader, E. J. Henley, D. K. Roper (2011) Separation Process Principles, 3rd ed., Wiley,
  chapters 9 and 13; the Fenske, Underwood, Gilliland and Molokanov references of
  `separations/shortcut.py`.
- process-library `acetyl-chloride-1` and `benzoyl-chloride-1` DESIGN.md D-007, D-008, L-1
  (scratch copies, not committed).
