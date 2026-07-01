# Workbook Upload Pipeline Audit Table

Quick reference audit table for all sheets in the pipeline.

## Audit Summary Table

| Workbook Sheet | Source Rows | Parsed Model | Entity Count | Missing Fields | Workbook-Only Fields | Default Values | Status |
|---|---|---|---|---|---|---|---|
| **Project_Info** | 1 | ProjectInfo | 1 | None | None | release_date=None | ✅ PASS |
| **Team** | 10 | Resource | 9 | **Skill 3, Skill 3 Level, daily_capacity_hrs** (from allocation), **sprint_allocation** (S1-S8) | Skill 2 Level, S1-S8 allocation/availability | daily_capacity_hrs=8.0 (hardcoded), notes=None | ⚠ PARTIAL |
| **Sprint_Plan** | 8 | Sprint | 8 | None | None | sprint_id=generated (SPR-N), sprint_number=generated | ✅ PASS |
| **Work_Items** | 71 | WorkItem | 70 | None | None | original_sprint=None, assigned_resource=None, remaining_effort_hrs=calculated | ✅ PASS (1 row filtered) |
| **Dependencies** | 23 | Dependency | 23 | **is_on_critical_path, notes** (both unmapped) | None | is_on_critical_path=False, notes=None | ⚠ PARTIAL |
| **Blockers** | 5 | Blocker | 5 | **sprint_identified** | Sprint Identified column | owner=None, target_resolution_date=None, actual_resolution_date=None | ⚠ PARTIAL |
| **Sprint_Actuals** | 0 | SprintActual | 8 | **scope_change_hours, blocker_impact_hrs** (not calculated) | [SHEET DOESN'T EXIST] | All metrics derived/calculated, scope & blocker fields=0.0 | ⚠ DERIVED |

---

## Detailed Field Mapping Tables

### Sheet 1: PROJECT_INFO

| Workbook Column | Model Field | Type | Mandatory | Status | Notes |
|---|---|---|---|---|---|
| Project Name | project_name | str | ✓ | ✓ Mapped | — |
| Sponsor | sponsor | str | ✓ | ✓ Mapped | — |
| Business Unit | business_unit | str | ✓ | ✓ Mapped | — |
| Project Manager | project_manager | str | ✓ | ✓ Mapped | — |
| Start Date | start_date | datetime | ✓ | ✓ Mapped | — |
| Target End Date | target_end_date | datetime | ✓ | ✓ Mapped | — |
| Sprint Length (Days) | sprint_duration_days | int | ✓ | ✓ Mapped | Must be 1-30 |
| Methodology | methodology | str | ✓ | ✓ Mapped | — |
| Customer | customer | str | ✓ | ✓ Mapped | — |
| Status | status | str | ✓ | ✓ Mapped | — |
| [NOT IN SHEET] | release_date | datetime? | ✗ | ⚠ Default | Optional; defaults to None |

**Result: 10/11 fields (90%)**

---

### Sheet 2: TEAM

| Workbook Column | Model Field | Type | Mandatory | Status | Notes |
|---|---|---|---|---|---|
| Resource Name | name | str | ✓ | ✓ Mapped | — |
| [DERIVED] | resource_id | str | ✓ | ✓ Generated | Derived from name (name.lower().replace(" ", "_")) |
| Role | role | str | ✓ | ✓ Mapped | — |
| Skill 1 | primary_skill | str | ✓ | ✓ Mapped | — |
| Skill 1 Level | skill_level | enum | ✓ | ✓ Mapped | Reads Skill 1 Level column |
| Skill 2 | secondary_skill | str? | ✗ | ✓ Mapped | Optional if blank |
| Skill 2 Level | [NOT USED] | — | — | ✗ LOST | Column ignored; only Skill 1 Level read |
| Skill 3 | [NOT MAPPED] | — | — | ✗ LOST | No tertiary_skill in model |
| Skill 3 Level | [NOT MAPPED] | — | — | ✗ LOST | No tertiary_skill_level in model |
| S1 Alloc % (8 columns: S1-S8) | allocation_pct | float | ✓ | ⚠ AVERAGED | Averages all "% Alloc" columns (loses sprint context) |
| S1 Avail % (8 columns: S1-S8) | availability_pct | float | ✓ | ⚠ AVERAGED | Averages all "% Avail" columns (loses sprint context) |
| [NOT IN SHEET] | daily_capacity_hrs | float | ✓ | ⚠ HARDCODED | Always set to 8.0; not read from workbook |
| [NOT IN SHEET] | notes | str? | ✗ | ⚠ Default | Defaults to None; no workbook source |

**Result: 8/13 fields (62%) — Critical fields missing**

**Issues:**
- ⚠ Skill 3 lost entirely
- ⚠ Sprint-specific allocation/availability averaged, losing per-sprint data
- ⚠ daily_capacity_hrs hardcoded instead of read
- ⚠ Skill 2 Level ignored (only Skill 1 Level used for all skills)

---

### Sheet 3: SPRINT_PLAN

| Workbook Column | Model Field | Type | Mandatory | Status | Notes |
|---|---|---|---|---|---|
| Sprint Name | sprint_name | str | ✓ | ✓ Mapped | — |
| [ROW POSITION] | sprint_id | str | ✓ | ✓ Generated | Format: "SPR-{row_position}" (SPR-1, SPR-2, ...) |
| [ROW POSITION] | sprint_number | int | ✓ | ✓ Generated | Row position in sheet (1-indexed) |
| Start Date | start_date | datetime | ✓ | ✓ Mapped | — |
| End Date | end_date | datetime | ✓ | ✓ Mapped | Must be > start_date |
| Duration (Days) | working_days | int | ✓ | ✓ Mapped | — |
| Sprint Goal | sprint_goal | str | ✓ | ✓ Mapped | — |
| Status | status | enum | ✓ | ✓ Mapped | Values: Not Started, In Progress, Completed |
| Velocity (h) | planned_velocity_hrs | float | ✓ | ✓ Mapped | — |
| Carry-Over Items | carryover_count | int | ✓ | ✓ Mapped | — |

**Result: 10/10 fields (100%)**

---

### Sheet 4: WORK_ITEMS

| Workbook Column | Model Field | Type | Mandatory | Status | Notes |
|---|---|---|---|---|---|
| Task ID | item_id | str | ✓ | ✓ Mapped | Must start with "WI-" |
| Task Name | title | str | ✓ | ✓ Mapped | — |
| Type | work_type | enum | ✓ | ✓ Mapped | Values: Feature, Story, Task, Bug, Spike, Defect |
| Sprint | assigned_sprint | str | ✓ | ✓ Mapped | Sprint name (normalized) |
| Orig. Sprint | original_sprint | str? | ✗ | ✓ Mapped | Optional; defaults to None if blank |
| Owner | assigned_resource | str? | ✗ | ✓ Mapped | Optional; resource name (not ID) |
| Required Skill | required_skill | str | ✓ | ✓ Mapped | — |
| Priority | priority | enum | ✓ | ✓ Mapped | Values: Critical, High, Medium, Low |
| Orig Est (h) | estimated_effort_hrs | float | ✓ | ✓ Mapped | Fallback: uses Curr Est if Orig Est = 0 |
| Curr Est (h) | current_estimate_hrs | float | ✓ | ✓ Mapped | — |
| Actual Hrs | actual_effort_hrs | float | ✓ | ✓ Mapped | Defaults to 0.0 if blank |
| Remaining Hrs | remaining_effort_hrs | float | ✓ | ⚠ CALCULATED | Logic: (1) explicit value, (2) progress-based calc, (3) current est if not-started, (4) 0 if done |
| Progress % | progress_pct | float | ✓ | ✓ Mapped | Converted from 0-100 to 0.0-1.0 |
| Status | status | enum | ✓ | ✓ Mapped | Values: Not Started, In Progress, Done, Completed, Blocked, Spillover |
| Scope Change | is_scope_changed | bool | ✓ | ✓ Mapped | Converted from Yes/No to True/False |
| Scope Reason | scope_change_reason | str? | ✗ | ✓ Mapped | Optional; defaults to None if blank |

**Result: 16/16 fields (100%)**

**Note:** 1 data row filtered (summary/total row at end of sheet)

---

### Sheet 5: DEPENDENCIES

| Workbook Column | Model Field | Type | Mandatory | Status | Notes |
|---|---|---|---|---|---|
| Dep ID | dependency_id | str | ✓ | ✓ Mapped | — |
| Predecessor Task | predecessor_item_id | str | ✓ | ✓ Mapped | Must reference valid WI-XXX |
| Successor Task | successor_item_id | str | ✓ | ✓ Mapped | Must reference valid WI-XXX |
| Dependency Type | dependency_type | enum | ✓ | ✓ Mapped | Values: Finish-To-Start, Start-To-Start |
| Lag Days | lag_days | int | ✓ | ✓ Mapped | — |
| [NOT IN SHEET] | is_on_critical_path | bool | ✓ | ⚠ DEFAULT | Always False; "Critical Path" column not in workbook |
| [NOT IN SHEET] | notes | str? | ✗ | ⚠ DEFAULT | Defaults to None |

**Result: 5/7 fields (71%) — 2 fields with defaults only**

**Concerns:**
- ⚠ is_on_critical_path always False (may be incorrect if data should exist)
- ⚠ notes field not populated

---

### Sheet 6: BLOCKERS

| Workbook Column | Model Field | Type | Mandatory | Status | Notes |
|---|---|---|---|---|---|
| Blocker ID | blocker_id | str | ✓ | ✓ Mapped | — |
| Related Task | related_item_id | str | ✓ | ✓ Mapped | Must reference valid WI-XXX |
| Impacted Task IDs | impacted_item_ids | List[str] | ✓ | ✓ Mapped | Split by comma; all must reference valid WI-XXX |
| Notes / Escalation Path OR Notes | description | str | ✓ | ✓ DERIVED | Constructed from Notes column; fallback: "Blocker {ID}: {Task}" |
| Severity | severity | enum | ✓ | ✓ Mapped | Values: Critical, High, Medium, Low |
| Status | status | enum | ✓ | ✓ Mapped | Values: Open, Resolved |
| Owner | owner | str? | ✗ | ✓ Mapped | Optional; resource name |
| Raised Date | raised_date | datetime | ✓ | ✓ Mapped | — |
| Target Resolution | target_resolution_date | datetime? | ✗ | ✓ Mapped | Optional; defaults to None if blank |
| Actual Resolution | actual_resolution_date | datetime? | ✗ | ✓ Mapped | Optional; defaults to None if blank |
| Category | category | enum | ✓ | ✓ MAPPED+FALLBACK | 22 values mapped; unknown → OTHER |
| Sprint Identified | [NOT MAPPED] | — | — | ✗ LOST | Column exists in workbook but not stored in model |
| Notes | notes | str? | ✗ | ✓ Mapped | Copied from Notes column (or Escalation Path) |

**Result: 11/13 fields (85%) — 1 workbook column lost**

**Issues:**
- ✗ Sprint Identified column in workbook is not captured
- ✓ Category mapping: 22 specific values + fallback to OTHER

---

### Sheet 7: SPRINT_ACTUALS (SYNTHETIC/DERIVED)

| Workbook Column | Model Field | Type | Mandatory | Status | Notes |
|---|---|---|---|---|---|
| [DERIVED FROM SPRINTS] | sprint_id | str | ✓ | ✓ DERIVED | From Sprint_Plan sprint IDs |
| [DERIVED FROM SPRINTS] | sprint_number | int | ✓ | ✓ DERIVED | From Sprint_Plan sprint_number |
| [DERIVED FROM WORK_ITEMS] | planned_effort_hrs | float | ✓ | ✓ DERIVED | Sum of work_items.estimated_effort_hrs in sprint |
| [DERIVED FROM WORK_ITEMS] | actual_effort_hrs | float | ✓ | ✓ DERIVED | Sum of work_items.actual_effort_hrs in sprint |
| [CALCULATED] | variance_hrs | float | ✓ | ✓ CALCULATED | actual - planned |
| [DERIVED FROM WORK_ITEMS] | tasks_planned | int | ✓ | ✓ DERIVED | Count of work_items in original sprint |
| [DERIVED FROM WORK_ITEMS] | tasks_completed | int | ✓ | ✓ DERIVED | Count of work_items with status=DONE/COMPLETED |
| [CALCULATED] | completion_rate | float | ✓ | ✓ CALCULATED | tasks_completed / tasks_planned (0.0-1.0) |
| [DERIVED FROM WORK_ITEMS] | carryover_count | int | ✓ | ✓ DERIVED | Count of items where original_sprint ≠ assigned_sprint |
| [DERIVED FROM WORK_ITEMS] | carry_out_count | int | ✓ | ✓ DERIVED | Same as carryover_count |
| [DERIVED FROM WORK_ITEMS] | carry_in_count | int | ✓ | ✓ DERIVED | Count of items moved INTO this sprint |
| [DERIVED FROM WORK_ITEMS] | carry_out_hours | float | ✓ | ✓ DERIVED | Sum of effort_hrs for items carried out |
| [DERIVED FROM WORK_ITEMS] | carry_in_hours | float | ✓ | ✓ DERIVED | Sum of effort_hrs for items carried in |
| [NOT CALCULATED] | scope_change_hours | float | ✓ | ✗ NOT CALCULATED | Always 0.0 (should be sum of scope changes) |
| [NOT CALCULATED] | blocker_impact_hrs | float | ✓ | ✗ NOT CALCULATED | Always 0.0 (should sum blocker hours) |
| [NOT IN SHEET] | notes | str? | ✗ | ⚠ DEFAULT | Optional; defaults to None |

**Result: 14/16 fields (88%) — 2 fields never populated**

**Critical Issues:**
- ✗ scope_change_hours always 0.0 (not calculated from work items)
- ✗ blocker_impact_hrs always 0.0 (not calculated from blockers)
- ⚠ Entire sheet is synthetic; no source workbook sheet (if one exists with recorded actuals, they are lost)

**Fallback Logic:**
If workbook contains Sprint_Actuals sheet, parser uses values from there instead of derived calculations.

---

## Status Legend

| Symbol | Meaning |
|--------|---------|
| ✅ PASS | All fields correctly parsed and populated |
| ⚠ PARTIAL | Some fields missing or have incomplete mappings |
| ⚠ DERIVED | Data calculated/synthesized rather than from source |
| ✓ Mapped | Field successfully read from workbook column |
| ⚠ AVERAGED | Multiple workbook columns aggregated (data loss) |
| ⚠ CALCULATED | Field computed from other fields (may not match workbook) |
| ⚠ DEFAULT | Field has default value only (not from workbook) |
| ⚠ HARDCODED | Field set to static value (never changes) |
| ✗ LOST | Workbook column exists but not captured in model |
| ✗ NOT MAPPED | Model field has no workbook source |
| ✗ NOT CALCULATED | Field should be calculated but isn't |

---

## Quick Reference: Missing Fields by Entity

### ProjectInfo
- ⚠ release_date (optional; not in workbook)

### Team (CRITICAL GAPS)
- ✗ tertiary_skill
- ✗ tertiary_skill_level
- ✗ sprint_allocation (S1-S8 per-sprint breakdown)
- ⚠ daily_capacity_hrs (hardcoded to 8.0)
- ⚠ notes (not in workbook)
- ⚠ skill_2_level (workbook has it but ignored)

### Sprint
- None (100% complete)

### WorkItem
- None (100% complete)

### Dependency
- ⚠ is_on_critical_path (defaults to False, not in workbook)
- ⚠ notes (not in workbook)

### Blocker
- ✗ sprint_identified (column in workbook but not stored)

### SprintActual
- ✗ scope_change_hours (not calculated; always 0.0)
- ✗ blocker_impact_hrs (not calculated; always 0.0)
- ⚠ notes (defaults to None)

---

## Count Verification

| Entity | Expected from Sheets | Actual Parsed | Match? |
|--------|---------------------|--------------|--------|
| ProjectInfo | 1 | 1 | ✓ Yes |
| Team | 10 (9 data + 1 summary) | 9 | ✓ Yes (summary filtered) |
| Sprint | 8 | 8 | ✓ Yes |
| WorkItem | 71 (70 data + 1 summary) | 70 | ✓ Yes (summary filtered) |
| Dependency | 23 | 23 | ✓ Yes |
| Blocker | 5 | 5 | ✓ Yes |
| SprintActual | 0 (derived) | 8 | ✓ Yes (derived from sprints) |

