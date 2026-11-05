# 0055. A batch (Rayleigh) still and solvent swap as a flowsheet step, solved natively

- **Status:** Proposed
- **Date:** 2026-11-05

## Context

Several fine chemicals still missing from the process library end in a batch work-up by
distillation: a solvent strip in TsCl and TBSCl; the methanol strip of sodium azide; and the
vacuum distillation of benzoyl chloride, acetyl chloride and benzyl bromide (core#165,
process-library #142, #139, #147, #156, #163). The strips and swaps are one-stage operations;
the product distillations are fractional (a column with reflux). cheme-as-code had no batch
distillation. A library entry could
only give the still as a specified split or as a continuous column (DWSIM), or work it out in a
balance script. None of these follow a charge as it boils down, and none give the boil-up time
the recipe (ADR 0051) needs for the cycle.

Options considered:

1. **PharmaPy** (Casas-Orozco et al. 2021) as a backend. Its `Evaporator` is a one-stage
   still, batch or semi-batch. It integrates through SUNDIALS via Assimulo. Assimulo is not
   on PyPI beyond 3.0, and PharmaPy pins 3.4.3, which conda-forge builds for Python 3.8 to 3.11
   only. Its requirements also pin `numpy<2`, against core's `numpy>=2`. So it cannot be a uv
   extra on Python 3.12+. The only route would be an out-of-process conda worker, which is a
   heavy stack for a one-stage balance (ADR 0042's reasoning).
2. **DWSIM's batch column**. DWSIM is steady state in core's coupling (ADR 0014, 0033), and
   core's semi-batch is refused there too.
3. **A native shortcut model** on the semi-batch's basis and integrator: Rayleigh's balance
   over one equilibrium stage, with Raoult's law or a constant relative volatility, a constant
   boil-up, and a swap's feed. It is pure Python and deterministic (ADR 0010), and every value
   carries its provenance (ADR 0011).

## Decision

cheme-as-code takes option 3 (`domains/process/batch_still.py`). PharmaPy was reviewed and is
not used: no code is copied from it, and its papers are cited as literature only.

- **Schema** (`domains/process/schema.py`): a block or step may give `still:`. Its fields:
  - `volatility: {model: raoult | constant, alpha}`;
  - `nonvolatile` (solid components always stay in the still);
  - `boilup: {value, unit: kmol/h | kmol/s | kg/h | kW | 1/h}`;
  - `pressure` (kPa(a), default: the charge's);
  - `end` (one of `distilled` share, mole or mass; `residue: {key, mole_fraction}`; `time` s of
    boil-up; `temperature` K, raoult only), or `cuts: [{outlet, end}]` collected in turn;
  - `feed: {stream, mode: constant_level | portions, portions, down_to}` (the solvent swap);
  - `outlets: {distillate, residue}` (with cuts: `residue` only).

  A component may give `vapour_pressure` (Antoine, default in the NIST form `log10(P/bar) = a -
  b/(T/K + c)` that `cheme chemistry props` gives, with `ln`, kPa, Pa, mmHg and °C as options,
  and its `temperature_range`) and `heat_of_vaporization` (kJ/kmol). Every new field is left
  out of the dump when unset (`exclude_if`). So a flowsheet without a still, and a component
  without these data, fingerprint as before.
- **Model**: `dN_i/ds = -y_i (+ z_i at constant level)`, integrated over the moles boiled up
  `s` with the batch's Dormand-Prince 5(4) stepper (`fixed_bed._dopri_step`).
  - The vapour `y` comes from Raoult's law at the still's bubble point (Newton within a
    bracket), or from `alpha_i x_i / sum alpha_j x_j`.
  - The time and the latent heat follow along the path: `dt/ds = 1/V`, `dE/ds = lambda(y)`.
    The path therefore does not depend on the boil-up, and an end at a time is a stop like any
    other.
  - Ends are found by bisecting the step that crosses them. A residue end takes its
    direction from its target: the key falls to a target below its share when the cut starts
    (an intermediate key may first rise, then fall), or rises to one above it while it rises.
    A key that never gets there boils the still dry (`StillError`), never an empty cut. A key
    falling already below its target (a swap's old solvent once the feed is in) has reached
    it: an empty cut and a note.
  - Each cut's energy is its own heat, from the end of the cut before; the cuts' sum to the
    still's.
  - A constant-level swap feeds one mole per mole boiled up. It first distils down to its
    `down_to` share of the charge.
  - Put and take distils down to the level, adds one of the equal portions, and repeats.
  - The ends apply once the feed is in. Without an end the still stops when the feed is in
    (constant level), or is back at the level (portions).
  - The swap reuses the semi-batch's basis: the feed is an inlet stream, its flow the amount
    per hour of charge, as a dose's (ADR 0050). It does not reuse the dose's clock schedule
    (`Dosing`): at constant level the feed follows the boil-up, not a time.
- **Basis and time**: a still's flows are amounts per hour of the flowsheet's flows (ADR
  0050, 0051).
  - One batch is the hours of flows that the recipe's batch size makes (`recipe.hours_per_batch`:
    batch size over the flowsheet's rate of its stream). Without a recipe it is one hour, said
    in a note.
  - A vapour rate or a duty is of the still in one batch, so the boil-up time and the energy
    per batch scale with those hours. A specific boil-up (1/h) does not need them.
  - An outlet's fingerprint takes what its flow and composition depend on: the still's
    specification without its texts (provenance, source) and without the boil-up, the molar
    masses, and (raoult) the pressure and the Antoine parameters without their fitted range.
    The boil-up, the hours, and the heats of vaporization of a boil-up in kW enter only where an
    end at a time makes the compositions depend on them.
  - Such an end needs the recipe's batch: propagate waits for the flow of its batch-size stream
    and solves the still once, and refuses (`StillError`) a batch-size stream that is the
    still's outlet or downstream of it (circular). A still that does not solve writes nothing.
- **Propagate** writes every cut's and the residue's flow and composition. An empty cut gets
  the vapour's composition at its end. A still that does not solve is
  `cheme.process-propagate-still` (warning).
- **Recipe**: a `distil` operation with `from: <still step>` takes its boil-up time.
  `from:` a still on another kind, or a `distil` from a step that is no still, is
  `cheme.recipe-reference`.
- **Report**: `cheme process stills [--case] [--json]` gives the basis (`rayleigh`,
  predictive, sourced when the volatility data carry a source); the charge, the feed, each cut
  and the residue per batch and as kmol/h with mole fractions; the boil-up time, the mean and
  peak duty, the energy per batch and the still's temperatures. Its findings are
  `cheme.process-still-unsolved` (error), `-outlet` (warning: given outlet values differ) and
  `-note` (info).
- **Rules** (`cheme.process-still` in `cheme validate`):
  - errors: a still that is also a reactor or crystallizer; outlets or cuts that do not name
    each material outlet port once; not exactly one charge besides the feed; a feed stream that
    is no inlet; an unknown component in `nonvolatile`, `alpha` or a residue key; a volatile
    component without a vapour pressure (raoult) or an alpha (constant); a boil-up in kW
    without the heats of vaporization;
  - info: no heats of vaporization otherwise (no duty);
  - warning: a `heat_of_vaporization` below 2000 kJ/kmol (`materials.yaml`), which is one in
    kJ/mol, as NIST gives it.
  - The components a still holds are those with a non-zero value in its inlets' compositions;
    a template, often shared by many streams, counts only for an inlet with no composition
    yet.

## Consequences

- Positive: a batch distillation, a cut sequence and a solvent swap are flowsheet steps with
  calculated outlets, a boil-up time for the cycle and a duty per batch. Solvent strips and
  swaps (TsCl, TBSCl, NaN3's methanol strip) need neither a specified split nor a script
  (`examples/process-solvent-swap`).
- Negative: product purification by fractional batch distillation (acetyl chloride, benzoyl
  chloride, benzyl bromide, MeI, Boc2O) still needs a column (`process simulate` or a
  specified split) until the constant-reflux follow-up (core#173). One stage cannot reach a
  product's purity: at alpha 4 from x0 = 0.5 Rayleigh gives a distillate of 0.69 mole
  fraction at 84 % recovery, 0.58 at 99 %.
- Positive: it is qualified against closed forms. Rayleigh's binary at constant relative
  volatility agrees to 1e-8. Raoult's law (benzene-toluene, NIST Antoine) agrees with the
  Rayleigh integral to 1e-6. The constant-level swap's
  `((1 - x_P)/alpha) ln(x0/x) + ((alpha - 1)/alpha)(x0 - x) = fed/N` agrees to 1e-8, and
  one put-and-take portion's `N_A/N_A0 = (N_B/N_B0)^alpha` to 1e-8. The balance closes by
  construction (`tests/test_batch_still.py`).
- Negative: an ideal liquid only. There are no activity coefficients, so no azeotropes. A
  component without Antoine data must be declared non-volatile or given a relative
  volatility.
- Limitations:
  - one stage, no rectification: constant-reflux or constant-distillate operation on core's
    Fenske-Underwood-Gilliland shortcut (Diwekar) is a follow-up (core#173);
  - no heat-up to the bubble point (a `heat` operation of the recipe), no sensible heat, no
    heat losses;
  - constant level in moles, not in volume;
  - the condenser and the vacuum system are not sized;
  - `process simulate` does not couple a still (leave it out of `simulation.yaml`), and
    `datasheets fill` does not size it.

## Evidence

- core#165 (feature F2), this ADR's PR.
- `src/chemeascode/domains/process/batch_still.py`, `schema.py` (`Still`, `VapourPressure`,
  `Component.vapour_pressure`, `heat_of_vaporization`), `propagate.py`, `recipe.py`
  (`distil`, `hours_per_batch`), `model_basis.py` (`still_basis`), `model.py` (rules),
  `interfaces/cli/process.py` (`process stills`).
- `tests/test_batch_still.py`, `examples/process-solvent-swap`.
- Lord Rayleigh (1902) On the distillation of binary mixtures, Phil. Mag. 4, 521-537; J. D.
  Seader, E. J. Henley, D. K. Roper (2011) Separation Process Principles, 3rd ed., Wiley,
  chapter 13 (batch distillation); U. M. Diwekar (2012) Batch Distillation, 2nd ed., CRC Press.
- Reviewed, not used: D. Casas-Orozco et al. (2021) PharmaPy: An object-oriented tool for the
  development of hybrid pharmaceutical flowsheets, Comput. Chem. Eng. 153, 107408
  (github.com/CryPTSys/PharmaPy).
