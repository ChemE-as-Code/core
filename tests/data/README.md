# Test data

`reference_pid.xml` is the reference P&ID of the DEXPI Specification 2.0.1, (c) 2026 DEXPI e.V., CC BY 4.0, unchanged.

`layout_nozzles.xml` is a small P&ID for the 3D-layout nozzle tests: a vertical vessel V-101
with nozzles on every side of its symbol (two drawn at the same spot) and a pump P-101 with
suction and discharge, joined by line 80-P-101. It was drafted with
`layout_nozzles_draft.py` (`cheme sheet new P-01`, then
`cheme run layout_nozzles_draft.py pid/P-01.xml`), the catalogue shapes it does not use
removed, and formatted with `cheme fmt`.

`layout_cabling.xml` is the same plant for the cable tray tests, with a discharge line 50-P-102
through a flow control valve FV-104 to the battery limit and four instruments: PT-101 (pump
discharge nozzle), LT-102 (vessel tapping), PI-103 (a local gauge, `Field`) and FIC-104
(measuring the discharge segment, signal to FV-104). Drafted the same way with
`layout_cabling_draft.py`, unused catalogue shapes removed.

`api-layout-asu.json` is `GET /api/layout` of the ASU example (the process-library repository,
subfolder `processes/asu-1`), with the generated model under `model`, frozen as the contract the
viewer is built against. Regenerate it with
`uv run --extra serve python scripts/build_layout_fixture.py <plant root>`, the plant root being
the folder with `plant.yaml`, e.g. `~/Developer/repos/plantcode-asu/processes/asu-1`; `tests/test_layout_model.py` checks it against the `layout_model` schema.

`tests/test_scripts.py` clones the process-library repository (`CHEME_PROCESS_LIBRARY`, default
`~/Developer/repos/plantcode-asu`) for the ASU regen evidence: revisions before the move have the
plant at the repository's top, later ones in `processes/asu-1`.

`datasheets-asu/` holds six datasheets of the ASU example (process-library repository,
`processes/asu-1/equipment/datasheets/`, as of its commit a295c75), unchanged: written before
the typed `dimensions`, `weights` and nozzle schedule fields, they pin that those fields stay
optional. `tests/test_datasheet_outline.py` also validates every datasheet of a local checkout
of the library (`CHEME_PROCESS_LIBRARY`, default `~/Developer/repos/plantcode-asu`) when there
is one.

`vle_ethanol_water.yaml` holds measured vapour-liquid equilibrium of ethanol + water at 101.3
kPa, the reference of the DWSIM NRTL benchmark
(`tests/test_process_simulate_property_package_nrtl.py`): two isobaric data sets (Kamihama et
al., J. Chem. Eng. Data 57 (2012) 339; Lai et al., J. Chem. Thermodyn. 68 (2014) 13) with the
combined expanded uncertainties, copied unchanged from the NIST TRC ThermoML files named in it.

`process-hda-1/` is the toluene hydrodealkylation plant of the ChemE-as-Code process library
(`processes/hda-1`, CC BY 4.0, (c) 2026 Artur Schweidtmann), cut to what `cheme process pinch`
reads: `plant.yaml` and `process/{flowsheet,materials,reactions,simulation}.yaml` unchanged, and
its recorded DWSIM 9.0.5 run `process/simulation-run.json` (simulated from library commit
4385a2d, written by cheme-as-code 1.2.1), so the end-to-end pinch tests
(`tests/test_process_pinch.py`) need no DWSIM. The sheets `plant.yaml` names are not copied.
While core translates these inputs to the recorded model fingerprint the record is current; a
change to the translation that alters the fingerprint makes the tests fail with
`pinch-run-stale`: copy a run simulated with the new core from the library then.
