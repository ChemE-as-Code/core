# 0033. The DWSIM worker iterates the tear streams itself

- **Status:** Accepted
- **Date:** 2026-10-29

## Context

`cheme process simulate` tore each recycle loop at a stream and left the iteration to DWSIM's
Recycle block. It required 1e-7 kg/s (summed over the compounds), 1e-4 K and 1e-2 Pa, with no
acceleration and a limit of 500 iterations. An ammonia synthesis loop with a 0.737 % purge
(process-library, ammonia-1, D-024; core#57) never converged that way:

- DWSIM 9.0.5's Recycle (`LegacyMode`) only copies the tear into its copy. Its GlobalBroyden
  option accelerates temperature, pressure, total flow and enthalpy, but not the composition.
  A loop with a small purge closes only about its purge fraction of the gap per circuit. In the
  ammonia loop the flow fell from 85.13 to 84.26 kg/s over 400 passes and was still falling, at
  0.9978 per pass, so 1e-7 kg/s would have taken about 6000 passes.
- With several tears in series around one loop, each copy is fed by the tear before it. The
  slow mode then has complex eigenvalues, and the residual moves from tear to tear.
- When one Recycle hits its limit, DWSIM stops the pass, so the Recycle blocks after it are not
  calculated in that pass. The saved flowsheet then shows their copies at an earlier value, as
  if they "never left their guess".
- With acceleration (Anderson), the same loop stalls at 3e-5 to 6e-4 kg/s, which is 0.4 to
  8 × 10^-6 of its 85 kg/s. That is how far DWSIM's unit models (flashes, exchangers,
  equilibrium reactors) reproduce their outputs. Tightening the equilibrium reactor's tolerance
  lowered the floor only to 3e-5 to 1.3e-4 kg/s. A review reproduction with the criterion kept
  at 1e-7 kg/s (same loop, tears S4, S9, S27, S44, S46, S48) located the floor: S46 and S48
  reached 1e-12 kg/s, but S44, fed through the equilibrium converter R501, wandered between
  1e-5 and 3e-4 kg/s. The first solve ended unconverged after 500 passes. The worker's re-solve
  for the compressor trains met 1e-7 kg/s only when S44 dipped by chance, after 887 passes in
  all. The test fixture (two loops, no reactor or flash) reaches 1e-16 kg/s in 4 passes under
  either criterion. So 1e-7 kg/s on a large stream cannot be reached reliably once an
  equilibrium reactor is inside the loop.

## Decision

- The worker (`integrations/dwsim_worker.py`, `_Flowsheet`) iterates the tears itself:
  - each step is one DWSIM pass (`CalculateFlowsheet4`) with the copies as given streams;
  - all copies are then set at once, from each tear's temperature, pressure and compound mass
    flows, with Anderson acceleration over all tears together (depth 5; Walker and Ni,
    SIAM J. Numer. Anal. 49 (2011) 1715). After a failed accelerated pass it falls back to
    plain substitution.
- A tear has converged when its copy is within `max(1e-7 kg/s, 1e-5 × the tear's mass flow)`,
  1e-4 K and 1e-2 Pa. The limit stays at 500 passes per solve.
- Afterwards the worker connects DWSIM's Recycle blocks with the same tolerances, and DWSIM
  runs its own recycle test on the converged flowsheet. The saved `.dwxmz` shows the loops as
  before.
- A tear that does not converge is reported by name, with how far its copy is off in each
  quantity and the tolerance.

## Consequences

- Positive: multi-recycle loops with a small purge converge (ammonia-1 in 51 passes). Each pass
  computes every recycle, and the report says which tear failed and by how much.
- Kept from the old criterion: streams below 0.01 kg/s keep the 1e-7 kg/s bound. A tear's
  mismatch (at most 1e-5 of its flow) stays 500 times inside the default flowsheet balance
  tolerance (`rel` 0.005) and 10 times inside the energy closure's 1e-4 of the enthalpy flow.
  DWSIM's own Recycle test runs on every converged result and must pass. It measures the
  errors itself, but against the same `max(1e-7 kg/s, 1e-5 × flow)`, not 1e-7 kg/s.
- Not kept: the absolute 1e-7 kg/s bound on streams above 0.01 kg/s. A flowsheet that sets its
  balance `tolerance.rel` below 1e-5, with an `abs` smaller than 1e-5 of a tear's flow, can
  see a tear's mismatch in its balance check.
- Negative: on a large stream the mass criterion is looser than before (up to 1e-5 of the flow
  instead of 1e-7 kg/s). Copies of a loop torn several times can differ by a few 1e-5 of the
  flow.
- Limitation: DWSIM's equilibrium reactor keeps its own default tolerance (1e-3 on its scaled
  extents). Tightening it changed the ammonia converter's outlet by about 0.3 % of the flow;
  that is a separate accuracy question.

## Evidence

- core#57; `src/chemeascode/integrations/dwsim_worker.py` (`_Flowsheet`, `_anderson`,
  `TEAR_TOLERANCE`, `TEAR_RELATIVE`).
- `tests/test_process_simulate.py`: `test_dwsim_converges_two_recycles_with_a_small_purge`
  (fails with the v1.0.0 worker), `test_tear_acceleration_follows_a_slow_loop_torn_three_times`,
  `test_tear_tolerance_is_absolute_for_small_streams_and_relative_for_large`.
