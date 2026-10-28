# Provenance

Every engineering value says where it comes from, and every generated artifact says what it was
generated from:

- **Values.** In the process YAML each value carries `provenance: given | assumed | calculated`
  and, when given, a `source`; datasheet values are marked `assumed` and carry their basis.
  `cheme process streams` shows the provenance in the stream table.
- **Generated artifacts.** The BFD and PFD carry a provenance comment with the generator
  version and the fingerprints of their inputs; `layout/plant-model.yaml` records the fingerprints of the
  inputs it was built from; generated P&ID sheets name their `generator:` in `plant.yaml`. `cheme validate`
  reports artifacts edited by hand or out of date.
- **Reviews.** Review records in `reviews/` name the commit they reviewed
  (`reviewed_commit`), their `scope` and, optionally, a `basis` of files with revisions. `cheme impact` lists the artifacts whose sources changed since they were reviewed or
  generated.

The shared model (relations such as derived-from, represents, analyses and depends-on, and
fingerprints) is described in [Architecture](../framework/architecture.md#identity-relationships-provenance).

<!-- readme: ### impact -->
