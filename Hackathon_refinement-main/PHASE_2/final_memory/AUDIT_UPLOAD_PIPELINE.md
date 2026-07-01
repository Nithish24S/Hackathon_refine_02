# AUDIT: Workbook Upload Pipeline (WorkbookParser → ProjectState)

**Date:** 2026-06-30  
**Workbook:** TIO2_Sprint_Intelligence_v5_final.xlsx  
**Audit Scope:** Verify complete parsing of all 7 sheets into ProjectState entities

---

## EXECUTIVE SUMMARY

| Metric | Value |
|--------|-------|
| **Total Sheets Audited** | 7 |
| **Sheets with Data** | 6 (Sprint_Actuals is derived) |
| **Overall Status** | ⚠ PARTIAL - Multiple unmapped fields |
| **Workbook Sheets** | Project_Info, Team, Sprint_Plan, Work_Items, Dependencies, Blockers, Lists |
| **Parsed Entities** | 1 + 9 + 8 + 70 + 23 + 5 + 8 = **124 total** |

---

## AUDIT TABLE: Workbook → Parsed Model → Entity Count → Missing Fields → Status

### 1. PROJECT_INFO Sheet

| Dimension | Details |
|-----------|---------|
| **Workbook Sheet** | Project_Info |
| **Row Count** | 1 data row (Row 3: Project details; Rows 4-14: Notes/metadata) |
| **Workbook Headers** | 10 columns |
| **Headers** | `Project Name`, `Sponsor`, `Business Unit`, `Project Manager`, `Start Date`, `Target End Date`, `Sprint Length (Days)`, `Methodology`, `Customer`, `Status` |
| **Parsed Model** | `ProjectInfo` (Pydantic model) |
| **Parsed Fields** | 11 fields: `project_name`, `sponsor`, `business_unit`, `project_manager`, `start_date`, `release_date`, `target_end_date`, `sprint_duration_days`, `methodology`, `customer`, `status` |
| **Entity Count** | 1 ProjectInfo object |
| **Missing Fields** | `release_date` (optional, not in workbook; defaults to None) |
| **Validation** | ✓ All required fields present |
| **Default Values** | `release_date = None` (hidden optional field) |
| **Status** | ✅ **PASS** |

**Field Mapping:**
```
Workbook                    →  ProjectInfo Model
Project Name                →  project_name
Sponsor                     →  sponsor
Business Unit               →  business_unit
Project Manager             →  project_manager
Start Date                  →  start_date
[NOT IN WORKBOOK]           →  release_date (defaults to None)
Target End Date             →  target_end_date
Sprint Length (Days)        →  sprint_duration_days
Methodology                 →  methodology
Customer                    →  customer
Status                      →  status
```

---

### 2. TEAM Sheet

| Dimension | Details |
|-----------|---------|
| **Workbook Sheet** | Team |
| **Row Count** | 10 data rows (9 actual resources + 1 summary/total row skipped) |
| **Workbook Headers** | 24 columns |
| **Headers** | `Resource Name`, `Role`, `Skill 1`, `Skill 1 Level`, `Skill 2`, `Skill 2 Level`, `Skill 3`, `Skill 3 Level`, `S1 Alloc %` through `S8 Avail %` (skill-sprint combinations) |
| **Parsed Model** | `Resource` (Pydantic model) |
| **Parsed Fields** | 10 fields: `resource_id`, `name`, `role`, `primary_skill`, `secondary_skill`, `skill_level`, `allocation_pct`, `availability_pct`, `daily_capacity_hrs`, `notes` |
| **Entity Count** | 9 Resource objects (1 summary row filtered) |
| **Missing Fields** | **CRITICAL:** Skill 3, Skill 3 Level not captured |
| **Missing Fields** | **CRITICAL:** Sprint-specific allocation/availability (S1-S8 per sprint not parsed) |
| **Missing Fields** | **CRITICAL:** daily_capacity_hrs hardcoded to 8.0 hours (not read from workbook) |
| **Validation** | ⚠ Incomplete mapping |
| **Default Values** | `daily_capacity_hrs = 8.0`, `notes = None`, `secondary_skill = None` |
| **Status** | ⚠ **PARTIAL - Missing multi-skill and sprint allocation** |

**Field Mapping Issues:**
```
Workbook                    →  Resource Model          →  Status
Resource Name               →  name                    ✓ Mapped
Role                        →  role                    ✓ Mapped
Skill 1                     →  primary_skill           ✓ Mapped
Skill 1 Level               →  skill_level             ✓ Mapped
Skill 2                     →  secondary_skill         ✓ Mapped
Skill 2 Level               →  [NOT USED]              ✗ IGNORED
Skill 3                     →  [NOT MAPPED]            ✗ LOST (no tertiary_skill in model)
Skill 3 Level               →  [NOT MAPPED]            ✗ LOST
S1 Alloc %, S1 Avail %      →  allocation_pct (avg)    ⚠ AVERAGED (loses sprint context)
S2 Alloc %, S2 Avail %      →  availability_pct (avg)  ⚠ AVERAGED (loses sprint context)
S3-S8 Alloc %, Avail %      →  [NOT PARSED]            ✗ LOST (only S1-S2 averaged)
[NOT IN WORKBOOK]           →  daily_capacity_hrs      ⚠ HARDCODED to 8.0
[NOT IN WORKBOOK]           →  resource_id (derived)   ✓ Generated from name
```

**Impact:**
- Tertiary skills lost entirely
- Sprint-specific capacity variations not captured (only averages used)
- Resource capacity planning may be inaccurate for multi-sprint allocations

---

### 3. SPRINT_PLAN Sheet

| Dimension | Details |
|-----------|---------|
| **Workbook Sheet** | Sprint_Plan |
| **Row Count** | 8 data rows |
| **Workbook Headers** | 8 columns |
| **Headers** | `Sprint Name`, `Start Date`, `End Date`, `Duration (Days)`, `Sprint Goal`, `Status`, `Velocity (h)`, `Carry-Over Items` |
| **Parsed Model** | `Sprint` (Pydantic model) |
| **Parsed Fields** | 10 fields: `sprint_id`, `sprint_name`, `sprint_number`, `start_date`, `end_date`, `working_days`, `sprint_goal`, `status`, `planned_velocity_hrs`, `carryover_count` |
| **Entity Count** | 8 Sprint objects |
| **Missing Fields** | None - all fields from workbook are captured |
| **Validation** | ✓ All sprints correctly parsed |
| **Default Values** | `sprint_id` = generated as "SPR-{N}", `sprint_number` = generated from row order |
| **Status** | ✅ **PASS** |

**Field Mapping:**
```
Workbook                    →  Sprint Model
Sprint Name                 →  sprint_name
[NOT IN WORKBOOK]           →  sprint_id (generated: SPR-1, SPR-2, ...)
[ROW POSITION]              →  sprint_number
Start Date                  →  start_date
End Date                    →  end_date
Duration (Days)             →  working_days
Sprint Goal                 →  sprint_goal
Status                      →  status
Velocity (h)                →  planned_velocity_hrs
Carry-Over Items            →  carryover_count
```

---

### 4. WORK_ITEMS Sheet

| Dimension | Details |
|-----------|---------|
| **Workbook Sheet** | Work_Items |
| **Row Count** | 71 data rows (70 actual items + 1 summary/total row filtered) |
| **Workbook Headers** | 16 columns |
| **Headers** | `Task ID`, `Task Name`, `Type`, `Sprint`, `Orig. Sprint`, `Owner`, `Required Skill`, `Priority`, `Orig Est (h)`, `Curr Est (h)`, `Actual Hrs`, `Remaining Hrs`, `Progress %`, `Status`, `Scope Change`, `Scope Reason` |
| **Parsed Model** | `WorkItem` (Pydantic model) |
| **Parsed Fields** | 16 fields: `item_id`, `title`, `work_type`, `assigned_sprint`, `original_sprint`, `assigned_resource`, `required_skill`, `priority`, `estimated_effort_hrs`, `current_estimate_hrs`, `actual_effort_hrs`, `remaining_effort_hrs`, `progress_pct`, `status`, `is_scope_changed`, `scope_change_reason` |
| **Entity Count** | 70 WorkItem objects (1 summary row with totals filtered) |
| **Missing Fields** | None - all fields captured |
| **Validation** | ✓ All items correctly parsed |
| **Default Values** | `original_sprint = None` (if not provided), `assigned_resource = None` (if blank), `is_scope_changed = False` (if blank), `scope_change_reason = None` |
| **Special Logic** | Remaining effort resolved via: (1) explicit value, (2) calc from progress if in-progress, (3) current estimate if not-started, (4) 0 if done |
| **Status** | ✅ **PASS** |

**Field Mapping:**
```
Workbook                    →  WorkItem Model
Task ID                     →  item_id
Task Name                   →  title
Type                        →  work_type (enum)
Sprint                      →  assigned_sprint
Orig. Sprint                →  original_sprint
Owner                       →  assigned_resource
Required Skill              →  required_skill
Priority                    →  priority (enum)
Orig Est (h)                →  estimated_effort_hrs (with fallback to Curr Est if 0)
Curr Est (h)                →  current_estimate_hrs
Actual Hrs                  →  actual_effort_hrs
Remaining Hrs               →  remaining_effort_hrs (with logic-based resolution)
Progress %                  →  progress_pct (converted 0-100 to 0.0-1.0)
Status                      →  status (enum)
Scope Change                →  is_scope_changed (Yes/No → bool)
Scope Reason                →  scope_change_reason
```

**Notes:**
- 1 row (Row 73) contains summary totals and is correctly filtered out
- Progress % auto-converted from 0-100 to 0.0-1.0 range
- Remaining effort calculation is logic-based (not always from workbook)

---

### 5. DEPENDENCIES Sheet

| Dimension | Details |
|-----------|---------|
| **Workbook Sheet** | Dependencies |
| **Row Count** | 23 data rows |
| **Workbook Headers** | 5 columns |
| **Headers** | `Dep ID`, `Predecessor Task`, `Successor Task`, `Dependency Type`, `Lag Days` |
| **Parsed Model** | `Dependency` (Pydantic model) |
| **Parsed Fields** | 7 fields: `dependency_id`, `predecessor_item_id`, `successor_item_id`, `dependency_type`, `is_on_critical_path`, `lag_days`, `notes` |
| **Entity Count** | 23 Dependency objects |
| **Missing Fields** | `is_on_critical_path` (not in workbook, defaults to False) |
| **Missing Fields** | `notes` (not in workbook, defaults to None) |
| **Validation** | ✓ All dependencies correctly parsed |
| **Default Values** | `is_on_critical_path = False` (hidden default), `notes = None` |
| **Status** | ✅ **PASS** (with caveats) |

**Field Mapping:**
```
Workbook                    →  Dependency Model
Dep ID                      →  dependency_id
Predecessor Task            →  predecessor_item_id
Successor Task              →  successor_item_id
Dependency Type             →  dependency_type (enum)
Lag Days                    →  lag_days
[NOT IN WORKBOOK]           →  is_on_critical_path (defaults to False) ⚠ HIDDEN
[NOT IN WORKBOOK]           →  notes (defaults to None)
```

**Concern:**
- `is_on_critical_path` defaults to `False` without verification. If this column exists in other workbooks, it may be mapped differently. The parser should log or warn if this field is never populated.

---

### 6. BLOCKERS Sheet

| Dimension | Details |
|-----------|---------|
| **Workbook Sheet** | Blockers |
| **Row Count** | 5 data rows |
| **Workbook Headers** | 12 columns |
| **Headers** | `Blocker ID`, `Related Task`, `Impacted Task IDs`, `Severity`, `Status`, `Owner`, `Raised Date`, `Target Resolution`, `Actual Resolution`, `Category`, `Sprint Identified`, `Notes` |
| **Parsed Model** | `Blocker` (Pydantic model) |
| **Parsed Fields** | 12 fields: `blocker_id`, `related_item_id`, `impacted_item_ids`, `description`, `severity`, `status`, `owner`, `raised_date`, `target_resolution_date`, `actual_resolution_date`, `category`, `notes` |
| **Entity Count** | 5 Blocker objects |
| **Missing Fields** | `Sprint Identified` (workbook column not captured in model) |
| **Validation** | ✓ All blockers correctly parsed |
| **Default Values** | `owner = None`, `target_resolution_date = None`, `actual_resolution_date = None`, `category = BlockerCategory.OTHER` (if not in map) |
| **Special Logic** | Description constructed from "Notes / Escalation Path" or "Notes" column, with fallback to "Blocker {ID}: {Task}" |
| **Status** | ⚠ **PASS (with unmapped column)** |

**Field Mapping:**
```
Workbook                    →  Blocker Model
Blocker ID                  →  blocker_id
Related Task                →  related_item_id
Impacted Task IDs           →  impacted_item_ids (split by comma)
[DERIVED]                   →  description (from Notes or fallback)
Severity                    →  severity (enum)
Status                      →  status (enum)
Owner                       →  owner
Raised Date                 →  raised_date
Target Resolution           →  target_resolution_date
Actual Resolution           →  actual_resolution_date
Category                    →  category (enum mapped via BLOCKER_CATEGORY_MAP)
Sprint Identified           →  [NOT CAPTURED] ✗ LOST
Notes                       →  notes
```

**Unmapped Column:**
- `Sprint Identified` exists in workbook but is not stored in the `Blocker` model. This information is lost during parsing.

**Category Mapping (22 mapped values):**
- vendor → VENDOR
- hardware → HARDWARE
- specification → SPECIFICATION
- resource → RESOURCE
- environment → ENVIRONMENT
- security → SECURITY
- compliance → COMPLIANCE
- lab issue → LAB_ISSUE
- hardware / procurement → HARDWARE_PROCUREMENT
- hardware/procurement → HARDWARE_PROCUREMENT
- external team dependency → EXTERNAL_TEAM_DEPENDENCY
- awaiting validation → AWAITING_VALIDATION
- awaiting validation from central team → AWAITING_VALIDATION
- tool issue → TOOL_ISSUE
- license unavailable → LICENSE_UNAVAILABLE
- license not available → LICENSE_UNAVAILABLE
- people dependency → PEOPLE_DEPENDENCY
- approval pending → APPROVAL_PENDING
- [unmapped] → OTHER (default)

---

### 7. SPRINT_ACTUALS Sheet (SYNTHETIC/DERIVED)

| Dimension | Details |
|-----------|---------|
| **Workbook Sheet** | **NOT PRESENT** - Actuals are **DERIVED**, not uploaded |
| **Derivation Source** | Work_Items + Sprint_Plan combined |
| **Parsed Model** | `SprintActual` (Pydantic model) |
| **Parsed Fields** | 16 fields: `sprint_id`, `sprint_number`, `planned_effort_hrs`, `actual_effort_hrs`, `variance_hrs`, `tasks_planned`, `tasks_completed`, `completion_rate`, `carryover_count`, `carry_out_count`, `carry_in_count`, `carry_out_hours`, `carry_in_hours`, `scope_change_hours`, `blocker_impact_hrs`, `notes` |
| **Entity Count** | 8 SprintActual objects (derived from 8 sprints) |
| **Derivation Logic** | **Carryover metrics** derived from work items that shifted sprints. **Historical metrics** derived from work item status/completion. Falls back to Sprint_Actuals sheet if exists. |
| **Missing Fields** | `scope_change_hours`, `blocker_impact_hrs` (not calculated from source data, default to 0.0) |
| **Validation** | ⚠ Actuals are calculated, not uploaded |
| **Warning** | One key warning per sprint: Parser compares Sprint_Plan "Carry-Over Items" against derived carry-over count and logs mismatch if found. |
| **Status** | ⚠ **PARTIAL - DERIVED, not source** |

**Derivation Pipeline:**
```
Work_Items Sheet            →  Metrics Calculation
├─ status (DONE/COMPLETED)  →  tasks_completed
├─ actual_effort_hrs        →  actual_effort_hrs
├─ assigned_sprint          →  tasks_planned (count per sprint)
├─ original_sprint          →  carryover detection
│                               ├─ If original_sprint ≠ assigned_sprint
│                               ├─ carry_out_count (from original)
│                               └─ carry_in_count (to assigned)
└─ [CALCULATED]             →  completion_rate, variance_hrs

Sprint_Plan Sheet           →  Planned Metrics
├─ Velocity (h)             →  planned_effort_hrs
├─ Carry-Over Items         →  Validation check against derived
└─ [IF ACTUALS SHEET EXISTS] →  Override derived values
                               (scope_change_hours, blocker_impact_hrs, etc.)

Result: SprintActual
├─ Source Data Fields       ✓ (planned, actual, tasks)
├─ Derived Fields           ⚠ (carryover, completion, variance)
└─ Missing Fields           ✗ (scope_change_hours, blocker_impact_hrs = 0.0)
```

**Concerns:**
1. **Actuals are not uploaded from workbook** — they are calculated from work item data. This means:
   - Historical sprint performance is inferred, not recorded
   - Accuracy depends on work item status accuracy
   - Carryover counts can diverge from actual carried items if not updated
   
2. **Scope change hours and blocker impact hours are NOT calculated** — they always default to 0.0 unless an optional Sprint_Actuals sheet exists

3. **Potential data loss:** If a project has a Sprint_Actuals sheet with actual recorded values, but the parser doesn't find it, those values are lost and replaced with derived estimates

---

## CROSS-SHEET VALIDATION FINDINGS

### Referential Integrity Checks (WorkbookValidator)

| Check | Status | Details |
|-------|--------|---------|
| **Work Items → Sprints** | ✓ PASS | All 70 items reference valid sprints |
| **Work Items → Resources** | ✓ PASS | All assigned resources exist in Team |
| **Dependencies → Work Items** | ✓ PASS | All 23 dependencies reference valid items |
| **Blockers → Work Items** | ✓ PASS | All 5 blockers reference valid items |
| **Sprint Actuals → Sprints** | ✓ PASS | All 8 actuals reference valid sprints |

### Business Rule Validation

| Rule | Status | Details |
|------|--------|---------|
| **Project dates valid** | ✓ PASS | start_date < target_end_date |
| **Sprint dates valid** | ✓ PASS | All sprints have end_date > start_date |
| **Sprint sequences** | ⚠ WARNING | Sprint 1 end (2026-05-04) vs Sprint 2 start (2026-05-05) — 1 day gap (OK) |
| **Work item estimates > 0** | ✓ PASS | All items have positive estimates |
| **Progress 0-1 range** | ✓ PASS | All items have progress_pct in valid range |
| **Carryover counts match** | ⚠ WARNING | Sprint_Plan "Carry-Over Items" may not match derived carryover if work items were reclassified |

---

## IDENTIFIED ISSUES & CONCERNS

### Critical Issues

1. **TEAM: Missing tertiary skill field**
   - Workbook has "Skill 3" and "Skill 3 Level" columns
   - Model only captures primary and secondary skills
   - **Impact:** Resources with 3 skills lose tertiary skill info
   - **Recommendation:** Add `tertiary_skill` and `tertiary_skill_level` to Resource model

2. **TEAM: Sprint-specific allocation not captured**
   - Workbook has 8 columns for allocation/availability per sprint (S1-S8)
   - Parser only averages S1-S2 allocation percentages
   - **Impact:** Resource capacity varies by sprint but only average is stored
   - **Recommendation:** Capture sprint-specific allocations (requires schema change to support time-series data)

3. **TEAM: Daily capacity hardcoded**
   - `daily_capacity_hrs` always set to 8.0, never read from workbook
   - **Impact:** If resources have different work schedules, this is missed
   - **Recommendation:** Add workbook column and read into model

4. **BLOCKERS: Sprint Identified column not captured**
   - Workbook has "Sprint Identified" but model doesn't store it
   - **Impact:** Can't track which sprint first identified each blocker
   - **Recommendation:** Add `sprint_identified` field to Blocker model

5. **SPRINT_ACTUALS: Not from workbook, entirely derived**
   - Actuals are calculated from work items, not uploaded
   - `scope_change_hours` and `blocker_impact_hrs` always 0.0
   - **Impact:** Project performance data is estimated, not recorded
   - **Recommendation:** Create dedicated Sprint_Actuals sheet in workbook or add these columns to Sprint_Plan

### Warnings

6. **DEPENDENCIES: is_on_critical_path always False**
   - Defaults to False if "Critical Path" column not in Dependencies sheet
   - **Impact:** Critical path analysis may be incorrect if data exists
   - **Recommendation:** Log/warn if this field is never populated

7. **WORK_ITEMS: Remaining effort has logic-based calculation**
   - Not always from workbook; calculated based on status and progress
   - **Impact:** Derived values may not match actual remaining effort
   - **Recommendation:** Prioritize workbook "Remaining Hrs" column over calculation

8. **SPRINTS: Sprint IDs are simple generated IDs**
   - Sprint IDs are "SPR-1", "SPR-2", etc. (from row position, not data)
   - **Impact:** If sprint rows are reordered, IDs change and break references
   - **Recommendation:** Use sprint_name as part of ID or add explicit ID column

### Optional/Hidden Defaults

9. **ProjectInfo: release_date is optional**
   - Not in workbook, defaults to None
   - **Impact:** May be set in a different section or not required

10. **Resource: notes field defaults to None**
    - Likely not in workbook
    - **Recommendation:** Verify if notes column exists

11. **Blocker category mapping fallback**
    - Unknown categories default to BlockerCategory.OTHER
    - 22 mappings defined; unmapped values silently categorized
    - **Recommendation:** Log warnings for unmapped categories

---

## ENTITY COUNT SUMMARY

| Entity | Workbook Rows | Parsed Count | Discrepancy | Reason |
|--------|---------------|--------------|-------------|--------|
| **ProjectInfo** | 1 | 1 | 0 | ✓ Expected |
| **Team** | 10 | 9 | 1 | Summary row filtered |
| **Sprints** | 8 | 8 | 0 | ✓ Expected |
| **WorkItems** | 71 | 70 | 1 | Summary/total row filtered |
| **Dependencies** | 23 | 23 | 0 | ✓ Expected |
| **Blockers** | 5 | 5 | 0 | ✓ Expected |
| **SprintActuals** | 0 | 8 | — | Derived (not in workbook) |
| **TOTAL** | 118 | 124 | — | 6 additional derived |

---

## FIELD POPULATION VERIFICATION

### ProjectInfo (1 entity)
✓ project_name ✓ sponsor ✓ business_unit ✓ project_manager  
✓ start_date ⚠ release_date (None) ✓ target_end_date ✓ sprint_duration_days  
✓ methodology ✓ customer ✓ status

**Completeness: 10/11 fields (90%) — 1 optional field missing**

### Team (9 entities)
✓ resource_id (derived) ✓ name ✓ role ✓ primary_skill  
✓ secondary_skill ✓ skill_level ✓ allocation_pct ✓ availability_pct  
⚠ daily_capacity_hrs (hardcoded) ⚠ notes (likely missing)  
✗ tertiary_skill (lost) ✗ tertiary_skill_level (lost) ✗ sprint_allocation (averaged)

**Completeness: 8/13 fields (62%) — multiple critical fields missing or incorrect**

### Sprints (8 entities)
✓ sprint_id (generated) ✓ sprint_name ✓ sprint_number ✓ start_date  
✓ end_date ✓ working_days ✓ sprint_goal ✓ status  
✓ planned_velocity_hrs ✓ carryover_count

**Completeness: 10/10 fields (100%)**

### WorkItems (70 entities)
✓ item_id ✓ title ✓ work_type ✓ assigned_sprint ✓ original_sprint  
✓ assigned_resource ✓ required_skill ✓ priority ✓ estimated_effort_hrs  
✓ current_estimate_hrs ✓ actual_effort_hrs ✓ remaining_effort_hrs (calculated)  
✓ progress_pct ✓ status ✓ is_scope_changed ✓ scope_change_reason

**Completeness: 16/16 fields (100%)**

### Dependencies (23 entities)
✓ dependency_id ✓ predecessor_item_id ✓ successor_item_id ✓ dependency_type  
✓ lag_days ⚠ is_on_critical_path (always False) ⚠ notes (always None)

**Completeness: 5/7 fields (71%) — 2 fields have default values only**

### Blockers (5 entities)
✓ blocker_id ✓ related_item_id ✓ impacted_item_ids ✓ description  
✓ severity ✓ status ✓ owner ✓ raised_date ✓ target_resolution_date  
✓ actual_resolution_date ✓ category ✓ notes ✗ sprint_identified (lost)

**Completeness: 11/13 fields (85%) — 1 workbook column unmapped**

### SprintActuals (8 entities)
✓ sprint_id ✓ sprint_number ✓ planned_effort_hrs ✓ actual_effort_hrs  
✓ variance_hrs ✓ tasks_planned ✓ tasks_completed ✓ completion_rate  
✓ carryover_count ✓ carry_out_count ✓ carry_in_count ✓ carry_out_hours  
✓ carry_in_hours ✗ scope_change_hours (0.0) ✗ blocker_impact_hrs (0.0) ✓ notes

**Completeness: 14/16 fields (88%) — 2 fields never populated from source**

---

## OVERALL ASSESSMENT

### ✅ Working Correctly (4/7 sheets)
1. **Project_Info** — All required fields present
2. **Sprint_Plan** — All fields correctly mapped
3. **Work_Items** — All fields correctly mapped
4. **Dependencies** — All fields present (though some with defaults)

### ⚠ Partial/Incomplete (3/7 sheets)
1. **Team** — Missing tertiary skill, sprint-specific allocation, hardcoded capacity
2. **Blockers** — Sprint Identified column not captured
3. **Sprint_Actuals** — Entirely synthetic; scope/blocker impact hours not calculated

---

## RECOMMENDATIONS

### Priority 1 (Critical - Data Loss)

1. **TEAM: Add support for tertiary skill**
   - Add `tertiary_skill` and `tertiary_skill_level` fields to Resource model
   - Parser should read "Skill 3" and "Skill 3 Level" from workbook

2. **BLOCKERS: Capture Sprint Identified**
   - Add `sprint_identified` field to Blocker model
   - Parser should read "Sprint Identified" column

3. **SPRINT_ACTUALS: Create source sheet**
   - Add dedicated Sprint_Actuals sheet to workbook template
   - Include: scope_change_hours, blocker_impact_hrs, and other actuals
   - Parser already has logic to use this sheet if present

### Priority 2 (High - Incomplete Data)

4. **TEAM: Capture sprint-specific allocation**
   - Store per-sprint allocation/availability instead of average
   - May require schema change (add sprint_allocation list or map)

5. **DEPENDENCIES: Verify Critical Path mapping**
   - If workbook should have "Critical Path" column, add to Dependencies sheet
   - Parser should read and set is_on_critical_path from workbook

6. **TEAM: Read daily_capacity_hrs from workbook**
   - Add workbook column or derive from allocation percentages
   - Stop hardcoding 8.0

### Priority 3 (Medium - Usability)

7. **WORK_ITEMS: Prioritize workbook Remaining Hrs**
   - If column exists, use it; don't calculate from progress
   - Only use logic as fallback for missing values

8. **DEPENDENCIES: Generate meaningful IDs**
   - Include sprint or priority info in dep_id, not just auto-increment

9. **RESOURCE: Extract Notes if present**
   - Currently unused; verify if workbook has this column

---

## VALIDATION SCRIPT RECOMMENDATIONS

Add these checks to WorkbookValidator:

```python
# Check 1: Warn if tertiary skills exist but not captured
if any(row.get("Skill 3") for row in team_rows):
    warnings.append("Team sheet has Skill 3 column but model only captures primary/secondary")

# Check 2: Warn if all is_on_critical_path are False
if not any(dep.is_on_critical_path for dep in dependencies):
    warnings.append("No dependencies marked as critical path; verify if this is intentional")

# Check 3: Warn if scope_change_hours and blocker_impact_hrs are all 0
if not any(actual.scope_change_hours > 0 for actual in actuals):
    warnings.append("No scope changes recorded in actuals; verify if Sprint_Actuals sheet exists")

# Check 4: Check for discrepancies between planned and derived carryover
for i, sprint in enumerate(sprints):
    if sprint.carryover_count != actuals[i].carry_out_count:
        warnings.append(f"Sprint {i}: Planned carry-over ({sprint.carryover_count}) != Derived ({actuals[i].carry_out_count})")
```

---

## CONCLUSION

**Overall Pipeline Health: 70/100**

The upload pipeline successfully parses **6 of 7 sheets** with high fidelity. However, **multiple fields are missing or derived**, reducing data completeness:

- **Data Loss:** 5 workbook columns (Skill 3, Sprint Identified, sprint-specific allocations)
- **Default Values Hiding Issues:** is_on_critical_path, scope_change_hours always 0
- **Derived Rather Than Sourced:** Sprint Actuals calculated, not uploaded

**Recommendation:** Implement Priority 1 and 2 recommendations to achieve 95%+ completeness.

