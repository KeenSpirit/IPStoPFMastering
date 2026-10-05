# Issues log — IPStoPF / ProtectionBatchRunner

Open bugs and performance work for the IPS → PowerFactory pipeline. Add a row when an issue is found; delete the row once the fix is verified on a Citrix run, noting the fix and date in the commit or run notes.

Started from the 3 Oct 2026 run review (Gladstone, Beenleigh, Brendale, South Burnett). Rows 14–18 and 8–9 in the performance table were added from the 4 Oct run.

**Status values:** `Open` · `Fix supplied` (code or mapping change provided, not yet verified on a run) · `Diagnostic supplied` (log-only change to find the cause) · `Decision needed`

## Bugs still open

| # | Issue | Evidence | Needed | Status |
| --- | --- | --- | --- | --- |
| 1 | P123 mapping maps two IPS settings to one PF attribute: 0260/0262 → `I2>/Tpset`, 025E/025F → `I2>/pcharac`; last read wins | 126 relays (Beenleigh 58, Brendale 68). `RIS4_J08` and `RIS1_J08` have 025E = DMT but are written `SI (IEC)` | Mapping file: pick 0260 or 0262 and the curve from 025E (conditional row) | Fix supplied 2026-10-04: rows `I2>,Tpset,…,262` and `I2>,pcharac,…,025E` removed from `P123_Energex_to_P12x.csv`. Confirm 025E = delay type, 0262 = tI2>. DMT stages remain open as #18 |
| 2 | pu-base corruption still happens; the finalisation pass repairs it | 17 elements corrected (Beenleigh 11, Brendale 6) on 3 Oct and again on 4 Oct, all P12x, only `I>>`, `I>>>`, `Therm`, `Undercurrent`, on relays whose values changed in the run (e.g. `RIS1_J08`) | Diagnostic: log `Measure Ph` `Inom` before and after `apply_settings` for one P123 | Open |
| 3 | HRC fuses can never match: `FuseTypeIndex` keys candidates by the last character of the type name | 6 HRC (16/25 A), 3 K 63 A, 1 Tx 63K → `Type Matching Error` | ErgonLibrary TypFuse names for HRC and 63 A K, then the index rule | Open |
| 4 | `Type Matching Error` leaves the fuse in service with its previous type | 22 fuses across 3 projects on 3 Oct; the 11 solid links among them now go out of service (patch 0007) | Decide: keep, or out of service | Decision needed |
| 5 | Ergon IT report carries no IT identity, so a relay's CTs cannot be paired | 7 of 40 Gladstone and 5 of 16 South Burnett relays with CT data have more than one CT | Add the IT name or input to `Report-Cache-ProtectionITSettings-EE` | Open |
| 6 | Fractional CT secondaries are rounded (2.89 → 3), not carried | ~180 EX and ~155 EE setting IDs | Citrix check that TypCt/StaCt take decimals; decide whether `RelMeasure.Inom` should be the relay's rated current | Open |
| 7 | Parameter sets: the latest import wins regardless of set name | 6 relays where an As Applied/As Left set lost; `X399509` As_issued imported 7 min after as_applied | Decide whether field sets outrank later Issued sets | Decision needed |
| 8 | A+B relay names depend on switch order, leaving stale same-setting relays that the orphan sweep takes out of service | `BHL1A+B_J5A` orphaned and updated in the same run; `SPEWSP29_J3` likewise | Tag each relay with its setting ID and find by tag, not name | Open |
| 9 | A relay with no IPS settings is classified as a switch and reported as such | `LHM6_CMGR12` (SEF relay) → `Switch - placed out of service` | Separate result for empty settings | Open |
| 10 | NOJA reclosers with blank pickups in SPA; no trip-count source for some NOJA mapping files | 9 Brendale reclosers blank on 3 and 4 Oct (8 are `RC01ES_Energex`). Not the reclose table: every overcurrent element is out of service after IPStoPF. Suspected: `outserv` mapping rows whose IPS value is missing write outserv = 1 | Run with the diagnostic; upload `RC01ES_Energex_to_Noja Recloser.csv` and the `EQL_RC10_RC20` mapping file | Diagnostic supplied 2026-10-04 |
| 11 | One plant number on several PF objects | `DO-800193` ×77 in KING; `DO-1240320`–`4` ElmRelay at YARR + RelFuse at PROT | Model correction | Open |
| 12 | Dip-switch logic treats any value containing `32`, or the pattern as a substring, as ON | Code review | Exact matching | Open |
| 13 | SPA still assesses devices IPStoPF set out of service | `DO-589200` set OOS, then damage- and coordination-checked | SPA filter on `outserv` | Open |
| 14 | No CT in IPS: a 1/1 placeholder CT in the model was kept, so the relay still reads secondary amps as primary | All 26 Gladstone "model CT kept" relays on 4 Oct had a 1/1 CT (FILASS-FB51/52/55, MOURSS-FA61/FA62, ICIZSS-FB52) | Treat a model CT with primary ≤ secondary as no CT (relay out of service) | Fix supplied 2026-10-04 (`ct_settings._handle_no_ips_ct`) |
| 15 | Tx fuse table key truncates the kVA rating in the single-phase and SWER-isolator branches (`int(strn*1000)`: 10 → 9, 315 → 314) | Keys `112.79`, `119.1314`, `1114` on 4 Oct; no fuse size changed this run (the table gives 3/10K for each) | `round()` instead of `int()` in `utils/pf_utils.tx_fuse_size` | Open |
| 16 | 19.1 kV SWER pole-mount transformers classed as two-phase (single-phase test only accepts `phtech == 6`) | Mount Isa `STD 0.025MVA_19-1/0-250kV SWER Polemt` → key `219.125`, 3/10K instead of 16K | Confirm the HV bus `phtech` value on a SWER pole-mount, then accept it | Open |
| 17 | STNW1001 Tx fuse table has no entry for several transformer sizes | 11 kV single-phase 63–1000 kVA, 12.7 kV 20/200/300/1000 kVA, 19.1 kV 20/315 kVA, 11 kV 3-phase 10 kVA (from the `Tx fuse: no STNW1001 size` warnings) | Sizes from STNW1001 for the missing keys | Open |
| 18 | P123 stages set to definite time in IPS are modelled as IDMT: mapping rows ignore the delay-type setting (0202, 0232, 025E) | `RIS1_J08`, `RIS4_J08` (I2> = DMT) | Code rule: when delay type = `DMT`, use the type's definite-time curve and the DMT delay setting for `Tpset` | Open |

## Further performance work

| # | Lever | Where | Expected effect | Status |
| --- | --- | --- | --- | --- |
| 1 | Incremental runs: skip a project when its master version, the IPS setting IDs and dates for its substations, and the mapping-file hashes are unchanged since its last successful run | Mastering + IPStoPF | Largest: most projects should be unchanged in a given week | Open |
| 2 | Parallel PowerFactory sessions, the fleet split across N engine processes | Mastering | Near-linear; limited by licences and one session per PF user | Open |
| 3 | Mastering overhead: 24 min passed before the first derivation started (old *Ready to Master* folder delete + library searches) and ~3.8 min per derived project (3 Oct). 14.7 min and ~2.1 min per project on 4 Oct | Mastering | Hours at fleet scale; instrument first, then rename the old folder and purge it off-cycle | Open |
| 4 | Skeleton fast path: index existing relays by foreign key in one search, call `setup_relay` only where the expected relay is missing or misplaced | IPStoPF (Ergon) | Most of the pass: 2,398 of 2,508 relays were already present on Gladstone (4 Oct); the pass is still 14.6 min there | Open |
| 5 | `app.GetCalcRelevantObjects('*.StaSwitch,*.ElmCoup')` instead of a recursive search plus 4 checks per switch | IPStoPF (Energex) | Most of the switch gathering (3.1 min Beenleigh on 4 Oct); benchmark for identical results first | Open |
| 6 | First-project type index: copy the 46 DIgSILENT models it resolves into ErgonLibrary | Library admin | ~6–12 min once per run (8.1 min on 4 Oct) | Open |
| 7 | SPA stage | SPA | ~25 h of an 80-project run; needs its own review | Open |
| 8 | 41–46 s per project between "IPS to PF Transfer script started" and "Determined region", after validation was cached; suspected `determine_region`'s `der_baseproject` lookup | IPStoPF | ~1 h per 80 projects; add a timing log line first | Open |
| 9 | CT and VT library folders found by a recursive walk of the project library: ~9 s each on Ergon projects, ~0.7 s on Energex | IPStoPF (`orchestrator.update_pf`) | ~12 min per 80 projects; look up the folders by path | Open |
