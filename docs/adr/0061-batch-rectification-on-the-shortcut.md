# 0061. Batch rectification: a column on the batch still, on the Fenske-Underwood-Gilliland shortcut

- **Status:** Proposed
- **Date:** 2026-11-06
- **Amended:** 2026-11-13, the qualification deferred to core#195 (see "Amendment" below)

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
    Just above the minimum reflux (X below about 5e-6) Molokanov's `1 - Y` underflows: the
    stages are then infinite, as at the minimum.
  - C1 is never below 1: the distillate is never leaner than the still's own vapour (Gilliland
    underpredicts at low reflux). One stage is the still itself: C1 = 1 at any reflux.
  - The keys. A named `heavy_key` (with the next more volatile component of the charge for
    the light key), or the distillate's key with the next less volatile component of the
    charge, are fixed for the batch. Without either (`reflux: constant`) the keys are taken at
    each point: the light key is the most volatile component that is at least 1 % of the
    still's vapour (`TRACE`; never the least volatile, so a binary keeps its pair), and the
    heavy key is the next less volatile one. After a forerun has taken the lightest component
    down to traces, the column separates the next pair; a note says where the light key moved.
  - A component more volatile than the light key takes no more of the distillate than the
    still's vapour brings up: `x_D,i <= (R + 1) y_i`. This is the column's balance, `D x_D,i =
    V y_i - L x_i` with `L x_i >= 0`. The other components share the rest as Hengstebeck-Geddes
    gives them. One index C1 for all components would gather a light trace at the top, as at
    total reflux: at x_A = 1e-3 (alpha 4/2/1, 10 stages, R 3) it gives 0.139 of A in the
    distillate, where the rigorous column gives 0.006 and the bound 0.009.
  - The relative volatilities are the K-values `P_i(T)/P` at the still's bubble point (raoult),
    or the constant ones, for the whole column.
  - The still's balance is ADR 0055's with the distillate for the vapour, `dN_i/dD = -x_D,i`,
    integrated over the moles distilled with the same Dormand-Prince stepper, ends and cuts.
    `(R + 1)` moles boil up per mole distilled: `dt/dD = (R + 1)/V`, `dE/dD = (R + 1)
    lambda(x_D)` (heat_of_vaporization of the distillate's composition; constant molar
    overflow). The `boilup` is the reboiler's: a vapour rate or its heat input.
- **Duties (ADR 0059 extended).** The reboiler's duty is the still's (now `(R + 1) D lambda`,
  plus ADR 0063's `charge heat-up` and `vessel metal` where `still.heat_up` or the recipe
  vessel's `metal_heat_capacity` is given) on its `energy_port`, or, with a column, its one
  heat stream in. The condenser's is the latent heat of the vapour boiled up, `(R + 1) D
  lambda`, out (total condenser, no subcooling; the heat-up and the metal stay in the pot and
  are never the condenser's) on `still.condenser_port`, or, with a column, its one heat stream
  out (to a cooling utility). Both are written `calculated` (source `still
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
  non-ideal pair; it was not run (deferred, core#195).
- Positive: against a rigorous ternary column (plate to plate, alpha 4/2/1, 10 stages, R 3,
  Newton on the still's composition), once A is a trace of the still (x_A 3e-3 to 0) the
  shortcut's B is never purer than the rigorous one and lies within 0.01 of it. Its C lies within 1e-3:
  B 0.9946 against 0.9948 at x_A = 1e-4, where one A/B key pair for the batch gave 0.916.
  A forerun until x_A = 1e-3, then a main cut until x_B = 0.3 (charge A 5, B 65, C 30), against
  a batch integrated on the rigorous column: the main cut's B is 0.9465 against 0.9476
  (the A/B keys gave 0.746).
- Positive: a constant distillate that is not held anywhere along the path is noted, with
  where (the share of the charge distilled), not only where it ends at the maximum reflux. So
  is a distillate key that is not the most volatile component of the charge (the search for
  C1 assumes the key's share of the distillate rises with it).
- Negative: the issue's qualification against Diwekar's published worked examples and against
  a DWSIM steady-state column is deferred to core#195. No published example's numbers were at
  hand to check, and they are not quoted from memory. The rigorous plate-to-plate columns above
  stand in for both, for ideal mixtures only.
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
  one Underwood root at each point. The keys change at a threshold, so the distillate steps
  where a light component falls below 1 % of the still's vapour. While the light key is
  above the threshold, one C1 overpredicts the heavier components: the forerun above carries
  0.080 of C, where the rigorous batch carries 0.008, which is conservative. Further
  limitations: the relative volatilities of the still's temperature for the whole column,
  constant molar overflow, and an ideal liquid (ADR 0055: no azeotropes).
- Negative: one reflux policy for all cuts of a still (a forerun at a higher reflux is a
  separate still step). A constant distillate's key should be the column's most volatile
  component while it is held; when it is not, the solve says so in a note.
- Limitations: the column, its condenser and the vacuum system are not sized; no reflux drum
  or decanter; no total-reflux start-up time (the charge's heat-up is `still.heat_up`, ADR
  0063, or a `heat` operation of the recipe); the
  condenser's duty has no subcooling; `process simulate` does not couple it.

## Evidence

- core#173; this ADR's PR (core#193); the deferred qualification core#195. Follow-up of ADR 0055 (its Limitations) and ADR 0059 (its
  follow-up "per-cut condenser duties of a still").
- `src/chemeascode/domains/process/batch_still.py` (`_Column`, `hengstebeck`,
  `underwood_root`, `underwood_min_reflux`, `gilliland_stages`, `gilliland_reflux`, the purity
  end), `schema.py` (`Column`, `ColumnDistillate`, `PurityEnd`, `Still.column`,
  `Still.condenser_port`), `duties.py` (`still_condenser_target`, `still_condenser_duty`),
  `propagate.py` (`_duty`, `_candidate`), `model_basis.py` (`batch-shortcut`).
- `tests/test_batch_rectification.py`, `examples/process-batch-rectification`.
- U. M. Diwekar, K. P. Madhavan (1991) Multicomponent batch distillation column design, Ind.
  Eng. Chem. Res. 30, 713-721; U. M. Diwekar (2012) Batch Distillation: Simulation, Optimal
  Design and Control, 2nd ed., CRC Press (the shortcut method, with the Hengstebeck-Geddes
  equation); J. D. Seader, E. J. Henley, D. K. Roper (2011) Separation Process Principles, 3rd ed., Wiley,
  chapters 9 and 13; the Fenske, Underwood, Gilliland and Molokanov references of
  `separations/shortcut.py`.
- process-library `acetyl-chloride-1` and `benzoyl-chloride-1` DESIGN.md D-007, D-008, L-1
  (scratch copies, not committed).

## Amendment (2026-11-13): qualification against published examples and DWSIM (core#195)

The qualification this record deferred, done in `tests/test_batch_rectification.py`. Nothing in
the model, the schema or the commands changes (no new ADR; 0076 was left unused). The papers
are the authors' copies on https://www.vri-custom.org/pdfs/ (paper94, paper59); only single
facts of their worked examples (stages, reflux, charge, relative volatilities, reported
amounts and compositions) are used, with their table in the tests.

- **Diwekar, Malik and Madhavan (1987)**, Comput. Chem. Eng. 11, 629-637, Tables 1 to 4: a
  binary at alpha 2.0, N = 4 (3 plates and the reboiler), 110 mol/h boiled up for 1 h; J, the
  moles distilled, sets R = V T / J - 1. At the printed J the shortcut's cut holds the paper's
  short-cut mean (x_D*) within 1.2e-3 (cases 1 to 6; case 1 at N = 4, 6, 10 and 20 of Table 4),
  and `constant_distillate` at x_D* distils the printed variable-reflux J within 0.6 %. The
  tests' plate-to-plate column gives the paper's rigorous means within 2.3e-3 (0.9579, 0.9059,
  0.9382, 0.9325, 0.9573, 0.9440 against 0.958, 0.906, 0.938, 0.932, 0.957, 0.942), so the
  reference of the bound tests is the paper's rigorous column too; the shortcut is never purer
  than it.
- **Lotter and Diwekar (1997)**, Ind. Eng. Chem. Res. 36, 760-770, Table 4 (the rectifier):
  alpha 1.7, R 4, 8 plates above the still, 50 mol/h for 3 h from an equimolar charge (100 mol
  by the printed balance); MultiBatchDS's 0.9194 mean distillate and 0.3202 still are the
  plate-to-plate column's 0.9195 and 0.3202. The shortcut gives 0.9023.
- **Not reproducible from the printed inputs**, and so no qualification: 1987 case 7 (at its
  printed J of 36.283 the shortcut gives 0.916 and the rigorous column 0.933, against 0.900
  and 0.919; both are met at J = 42.6, and holding 0.90 distils 42.7 against the printed
  36.762); 1987 Table 5, a quaternary at alpha 2.0/1.5/1.0/0.5 (at the printed J the rigorous
  column gives 0.677 and 0.741 of component 1 at 8 and 10 stages, not 0.90; a test keeps the
  reason checked). Diwekar and Madhavan (1991), Ind. Eng. Chem. Res. 30, 713-721, print no
  relative volatilities or stages for their BATCHFRAC quaternary (Table III) and no charge for
  their constant-reflux cases (Table II); Narváez-García et al. (Rev. Mex. Ing. Quím. 12 (2013)
  621-637; InTech 2017, doi 10.5772/66830) give their results in figures only. No published
  multicomponent example with complete inputs and tabulated results was found: the
  multicomponent qualification stays the rigorous ternary columns above.
- **DWSIM** (9.0.5, the `cheme-dwsim` image, behind `CHEME_DWSIM_TESTS=1`): a continuous column
  of the still's stages and a total condenser, fed at the reboiler with the still's saturated
  liquid (1 % of it distilled, the shortcut evaluated at the bottoms' composition), NRTL at
  101.325 kPa(a), at x_B of about 0.1, 0.3 and 0.5 with 5 stages at R 2, 8 at R 1 and 10 at
  R 3, the shortcut at the relative volatility of DWSIM's incipient vapour at the still:
  - benzene and toluene (nearly ideal, alpha 2.40 to 2.50 at the still, 2.46 to 2.59 at the
    top): the shortcut is not purer (to 1.5e-3, at 8 stages and R 1, near the minimum reflux;
    DWSIM's molar overflow is not constant) and within 0.053;
  - methanol and water (non-ideal, no azeotrope: alpha 3.7 to 6.7 at the still, 2.4 to 3.0 at
    the top): the shortcut is purer than DWSIM at most points, by up to 0.020 (0.718 against
    0.698 at x_B 0.09, 8 stages, R 1; 0.981 against 0.962 at x_B 0.29, 5 stages, R 2). It is no
    bound for a liquid whose relative volatility falls towards the top. At the top's relative
    volatility (the column's smallest) it is never purer, often far leaner (0.38 against 0.89).
    Raoult's law (the still's `raoult`, thermo's vapour pressures; not in the tests) is no
    bound either: at x_B 0.5 it gives up to 0.017 more than DWSIM, at 0.09 up to 0.35 less.
- Consequence: "the shortcut is conservative" holds for a constant relative volatility and a
  nearly ideal liquid. For a non-ideal liquid give `volatility: constant` at the smallest
  relative volatility along the column (at the distillate's composition) for a bound, or check
  the column with `cheme process simulate` (a rigorous column at the still's composition); the
  skills `process-design` and `unit-ops-distillation` say so.
