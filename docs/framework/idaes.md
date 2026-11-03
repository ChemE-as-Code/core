# IDAES simulation backend

`cheme process simulate` solves a flowsheet in DWSIM by default. A flowsheet within a bounded
scope can instead be solved by [IDAES](https://idaes.org) (idaes-pse, on Pyomo, solved with
IPOPT), an optional second backend ([ADR 0039](../adr/0039-idaes-as-an-optional-second-simulation-backend.md)).
Both backends take the same simulator model and write results through the same `--fill` and
`--check` path, run record and provenance.

## Choosing the backend

The backend is a field of `process/simulation.yaml`, not a command-line option, because it is
an input of every simulated value (its fingerprint) and of the run record:

```yaml
schema: cheme/simulation/v1
kind: simulation
simulator: idaes            # dwsim (the default) or idaes
property_package: IDAES ideal VLE
specs:
  H1: {outlet_temperature: {value: 600, provenance: assumed, source: ASSUMED}}
  R1: {mode: adiabatic}
  F1: {temperature: {value: 325, provenance: assumed, source: ASSUMED}}
```

Switching `simulator` changes the model's fingerprint, so values filled by the other backend
become `cheme.process-sim-stale` until `--fill` runs again.

## Installing IDAES

cheme-as-code never imports IDAES or Pyomo. The worker
(`src/chemeascode/integrations/idaes_worker.py`) runs in a separate Python environment:

```sh
python -m venv idaes-env
idaes-env/bin/pip install idaes-pse
idaes-env/bin/idaes get-extensions      # IPOPT and the other solver binaries
export CHEME_IDAES_PYTHON=$PWD/idaes-env/bin/python
cheme process simulate --fill
```

`CHEME_IDAES_COMMAND` takes a full command instead (a container or a remote host), which must
run a copy of the worker with the request on its stdin. Without either variable the run stops
with `cheme.process-sim-unavailable`. The worker was written against idaes-pse 2.13 and
Pyomo 6.10.

## What the backend runs

The scope is what the toluene hydrodealkylation loop needs
(`examples/process-hda-idaes`). Everything outside it is refused at translation, before any
solver runs, with `cheme.process-sim-backend-unsupported` (error) naming the step:

| Kind | IDAES model | Notes |
| --- | --- | --- |
| heater, cooler | `Heater` | outlet temperature or duty; one outlet (no condensate outlet) |
| valve | `PressureChanger`, adiabatic | |
| pump | `PressureChanger`, pump | efficiency |
| compressor, expander | `PressureChanger`, isentropic | `IDAES Peng-Robinson` only; no intercooled stages |
| mixer | `Mixer` | outlet at the lowest inlet pressure |
| splitter | `Separator`, total flow | fractions from the step's `split:` |
| flash | `Flash` | temperature or adiabatic; pressure or no pressure drop; one inlet |
| conversion reactor | `StoichiometricReactor` | one outlet; conversion reactions in the vapour or the liquid phase; adiabatic, isothermal or outlet temperature |
| recycle | tear streams | two sequential-decomposition passes initialize the units, then one simultaneous IPOPT solve closes the loop |

Not supported (use `simulator: dwsim`): heat exchangers with two sides, shortcut and rigorous
columns, component separators, equilibrium, Gibbs and kinetic (fixed-bed) reactors,
compressors with intercoolers, saturation feeds (vapour fraction instead of temperature),
interaction parameters, `--save`.

## Property packages and what they claim

| `property_package` | Method | Built from |
| --- | --- | --- |
| `IDAES ideal VLE` | Raoult's law and ideal gas (methods.yml `IDEAL`) | IDAES's `BT_ideal` (benzene, toluene) and `HC_PR` (hydrogen, methane) component data |
| `IDAES Peng-Robinson` | Peng-Robinson, every kij 0 (methods.yml `PR`) | IDAES's `BT_PR` and `HC_PR` component data |

Both use IDAES's generic (modular) property framework; the worker reads the component data from
the IDAES installation at run time. Two deviations from that data and IDAES's defaults:

- `IDAES ideal VLE` takes its vapour-liquid equilibrium in the complementarity form of
  Dabadghao et al., doi:10.1002/aic.18029, which IDAES ships for cubic equations of state
  only, without the cubic-root terms. IDAES's smooth VLE has no solution for a subcooled
  near-pure liquid (pure toluene, benzene at its trace), or one with a free vapour fraction:
  the bubble and dew points are closer than its smoothing. `IDAES Peng-Robinson` keeps smooth
  VLE and does not converge on such a stream (neither does IDAES's cubic complementarity form
  reliably in idaes-pse 2.13).
- `BT_ideal`'s Perry's liquid heat-capacity coefficients are read in kJ/kmol/K: IDAES labels
  them J/kmol/K, a thousand times below its own `BTX_activity_coeff_VLE` values for the same
  correlation, which leaves a liquid's enthalpy almost independent of temperature.

Compounds: benzene (71-43-2), toluene
(108-88-3), hydrogen (1333-74-0) and methane (74-82-8), hydrogen and methane in the vapour
only. Enthalpies include the formation enthalpies at 298.15 K (IDAES's example data, not
verified by cheme-as-code), so a reactor needs no separate heat of reaction.

**No IDAES package is benchmarked by cheme-as-code.** Translation always reports
`cheme.process-sim-method-unbenchmarked` (info); `methods.yml` claims no application range for
the IDAES route, and simulated values are not predictive. A recorded `method_selection` is
compared by method (`IDEAL`, `PR`) as for DWSIM. Agreement with a DWSIM run of the same
flowsheet is a consistency check, not a validation.

## Results and provenance

As with DWSIM, every simulated stream value gets provenance `calculated`, origin `simulated`,
the model fingerprint and the source

```text
cheme process simulate: IDAES <idaes-pse version>, <property package>
```

and `process/simulation-run.json` records the run. With IDAES its `simulator` entry also names
the numerical solver (`solver: ipopt <version>`), `iterations` is the IPOPT iteration count of
the final solve, and `notes` keeps an initialization that did not finish (the simultaneous
solve may still converge; `converged` is what counts). A run that does not converge writes no
stream value. The conversion and energy checks of a DWSIM run apply, except that a
reactor's energy closure is reported as unsupported: the IDAES packages' enthalpies include
the formation enthalpies and they report none separately, and a closure on them (no formation
term added) is not yet verified by cheme-as-code. The plant closure's `basis` is then
`simulator`. The
record's `energy.reference` (and `energy.formation`, with a reactor) states IDAES's basis:
`formation_enthalpy_included: true`, no formation term added.

## Tests

`tests/test_process_simulate_idaes.py` checks the translation, the refusals and a fill and
check from a recorded worker response without IDAES. With `CHEME_IDAES_TESTS=1` and
`CHEME_IDAES_PYTHON` set it also runs the HDA example in IDAES and checks the material balance,
the declared conversion and the flash outlets.
