# ChemSep SRK interaction parameters (not shipped)

cheme-as-code no longer ships `srk.ipd` or `srk.json`. Until the ChemSep authors confirm the
licence of the IPD files, a user installs them with

    cheme data fetch chemsep-srk            # downloads ChemSep-LITE
    cheme data fetch chemsep-srk --zip lite.zip   # offline, from a downloaded copy

which reads `ipd/srk.ipd` from ChemSep-LITE (http://www.chemsep.org/downloads/data/lite.zip,
plain HTTP; the sha256 of the 8.50 archive is recorded in
`chemeascode.domains.process.thermodynamics.chemsep_srk` and checked), converts it with
`chemsep_srk.parse_srk_ipd` and writes `srk.ipd`, `srk.json`, ChemSep's
`Artistic_license_2_0.txt` and a `SOURCE.json` (archive, member, sha256, date) to
`<user data dir>/chemsep/` (`$CHEME_DATA_DIR` if set). Without it, the Redlich-Kwong-Soave flash
of `thermodynamics.phase` uses `kij = 0` for every pair and says so in the result's `notes`.

## The file

- `srk.ipd`: the ChemSep interaction parameter file "DECHEMA Soave-Redlich-Kwong Parameters"
  ("This library created by Jennifer A. Clark Spring 2014"). The values are taken from the
  DECHEMA Chemistry Data Series: each row cites a DECHEMA page.
- `srk.json`: the same `kij` keyed by CAS pairs, in the JSON layout that thermo's
  `InteractionParameterDB.load_json` reads (the layout of thermo's ChemSep `pr.json`). The
  conversion is a modified version of the ChemSep file.

## Origin of the copy cheme-as-code used to ship

- Added to LLM4ChemE in commit 59f77d2 (2026-03-18, "added SRK interaction parameter
  retrieval") with `convert_srk_to_json.py`, moved to `src/data/` in aa82234, and moved to
  cheme-as-code byte-identical with LLM4ChemE's phase calculations.
- It came from a ChemSep release earlier than 8.50; the exact version was not recorded. It
  equals the first 315 lines of `ipd/srk.ipd` in ChemSep-LITE 8.50, which adds 11 water pairs
  (Whitson Table 9.3, Pedersen Table 16.1). `cheme data fetch` installs the 8.50 file.
- Its `srk.json` was marked asymmetric, so a `kij` was found only with the components in the
  file's order; `parse_srk_ipd` keys each pair in thermo's sorted CAS order and marks the
  table symmetric (the same 182 pairs and values otherwise).

## Licence: what is stated, and what is not

- **The IPD file** states only "ChemSep, Copyright 2009 Harry Kooijman and Ross Taylor". The
  `ipd/` folder of ChemSep-LITE 8.50 has no licence file, and no `.ipd` file mentions a licence.
  chemsep.org's download pages state no licence terms.
- **The Artistic License 2.0 attribution rests on two things, neither of them a statement for
  the IPD files:**
  - ChemSep's pure-component data (PCD): ChemSep-LITE 8.50 has one licence file,
    `pcd/Artistic_license_2_0.txt`, and the PCD XML header reads "ChemSep v8.49 pure component
    data 1 - Copyright (c) Harry Kooijman and Ross Taylor (2024) -
    http://www.perlfoundation.org/artistic_license_2_0";
  - a second-hand report in thermo issue #9
    (https://github.com/CalebBell/thermo/issues/9#issuecomment-382944911): "As I checked with
    Chemsep authors, these databanks themselves are released under following license terms
    http://www.perlfoundation.org/artistic_license_2_0". thermo ships the Artistic License next
    to its ChemSep `pr`/`nrtl`/`wilson`/`uniquac`/`henry` files, but has no SRK file.
- **DECHEMA**: the values come from the DECHEMA Chemistry Data Series. Neither ChemSep nor
  DECHEMA says anything about rights in the compilation.
- If the IPD files are under the Artistic License 2.0, the data could be shipped in this
  AGPL-3.0-or-later package as part of an aggregate (section 8), with the notice kept and the JSON
  conversion marked as modified.

**Status: awaiting confirmation from the ChemSep authors** that the IPD files, `srk.ipd`
included, are under the Artistic License 2.0. File their answer here.
