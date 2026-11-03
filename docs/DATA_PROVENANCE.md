# Data provenance register

Every data file or table that ships with FormCAD, with where its values come from. Attached to each release next to the SBOM files. A data file not listed here does not ship.

| Data | Location | Source and terms |
| --- | --- | --- |
| Thread and hole sizes | `backend/app/data/hole-sizes.json` | the file's own `sources` block (public standard texts read for the values); user file overrides |
| Materials | `backend/app/data/materials.json` | the file's own `note` and per-row sources; values read from cited sources only |
| Simulation materials | `backend/app/data/sim-materials.json` | the file's own `sources` block (public handbooks, unit converted) |
| Sheet metal bend tables | `backend/app/data/sheetmetal/bend_tables.json` | the file's own source fields; user tables override |
| Plastic materials and rules | `backend/app/data/plastic/` | the files' own source fields |
| Fonts | `backend/app/data/fonts/` | licences in `NOTICE.md` |
| Toolbox sizes | none ships | generators take user sizes; the library and the CSV importer read the user's own tables; proportion defaults (head 1.5 d, hex across flats 1.6 d, nut 0.8 d, washer 2 d and 0.15 d, a 10 x 26 x 8 bearing) are FormCAD decisions for a generic shape, not a standard |
| Structural sections, pipe | none ships | user sizes only (inline weld profiles, toolbox section generators) |
| Emission factors | none ships | the user's own table or CSV; the UK government conversion factors (OGL v3.0, attribution required) may be imported by the user; ICE is not embeddable |
| Cost rates and prices | `backend/app/costing/profile.py` (`DEFAULTS`) | example placeholders, labelled as such in every estimate and report until the user enters a value; structure cited to MTRC (MC2), NIST Design-for-Cost, MDPI Sustainability 13(1) 319 (CC BY 3.0) |
| DFM thresholds | `backend/app/costing/dfm.py` (`RULES`) | each row carries its source, read date and single source flag; vendor design guides (Hubs, Protolabs), not standards |
| Mold shrinkage | none ships | a user value with a stated convention |
