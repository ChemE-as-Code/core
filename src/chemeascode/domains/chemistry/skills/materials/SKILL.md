---
name: materials
description: Define the components and material templates of a process in process/materials.yaml (identity, CAS, ChEBI, molar mass, normal boiling point) and give streams their material and composition in process/flowsheet.yaml, by editing the YAML files. Use when components are added, identified or changed, or a stream needs a material.
---

# Materials

## Purpose and when to use

Materials are written as YAML, never through editor commands: `process/materials.yaml` holds
the components and the templates, and each stream in `process/flowsheet.yaml` names a template
and gives its composition. `cheme process build` turns them into the DEXPI material
components, templates and states of the BFD/PFD sheets. Use this skill whenever components are
added or identified, or a stream gets its material.

## Required inputs and missing inputs

- Each component's name and, to identify it, its CAS number (and ChEBI id where one exists).
- Which components each stream can carry (its template) and, where known, its composition with
  its basis (`mole_fraction` or `mass_fraction`).

If a component cannot be identified unambiguously (isomers, mixtures, trade names), ask. A
pseudocomponent or mixture without a CAS number keeps an empty `cas` and says what it is in
`name`.

## Workflow and tools

1. Look up identifiers and data with `property-retrieval`, e.g.
   `cheme chemistry props 64-17-5 -p name -p formula -p molecular_weight -p temperature_boil`.
2. Edit `process/materials.yaml` (schema: `cheme schema process-materials`):

   ```yaml
   components:
     - {id: ETOH, name: Ethanol, formula: C2H6O, cas: 64-17-5, chebi: "CHEBI:16236",
        molar_mass: 46.069, normal_boiling_point: 351.44}   # kg/kmol, K at 101.325 kPa
   templates:
     - {id: aqueous, title: Ethanol and water, components: [ETOH, H2O]}
   ```

   A template is an ordered component list. The order defines the order of every composition
   vector of the streams that name it, so append new components at the end of a template that
   streams already use, or update those compositions in the same change.
3. In `process/flowsheet.yaml`, give the stream its template and composition (see
   `process-design` for the stream fields); fractions of one composition sum to one on the
   stated basis.
4. Run `cheme validate` and `cheme process build`.

## Validation and failure handling

`cheme validate` checks the schema, unknown component ids in templates and compositions,
and the balances; fix every finding before building. A component used by no template is
harmless but usually a leftover. Do not change a component's `id` that streams use without
changing them in the same edit.

## Expected outputs and provenance

The edited YAML files, reviewed in the diff. Write where each identifier and value came from
(source and, for a value at a condition, the condition) as a YAML comment next to it, or in the
commit message.

## Required human judgments

- The component list itself: which species are carried, which are lumped or neglected.
- Pseudocomponents and their representative properties.
- The basis (mole or mass) a given composition was measured or specified on.

## References

- `process-design` (the flowsheet and stream table), `property-retrieval` (identifiers and data).
- `cheme schema process-materials`, `cheme schema process-flowsheet`.
