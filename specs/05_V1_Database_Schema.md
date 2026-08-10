# V1 Database Schema (D2)

> Sprint 2026 design deliverable. Target: **SQLite for MVP**, via SQLAlchemy 2.0
> declarative models. This spec defines the ER diagram and the ORM column set
> that Phase 3 ("Opportunity Database") will implement. It intentionally maps
> 1:1 onto the V1 Data Contracts (`specs/01_V1_Data_Contracts.md`) and onto the
> existing record schema (`OUTPUT_FIELDS` in `core/records.py`) so backfilling
> the current JSON output is a mechanical insert.

---

## 1. Conventions (SQLAlchemy 2.0)

- Declarative style: `Base = DeclarativeBase()`; each model a `Mapped[...]`
  dataclass-style class using `Mapped[type]` + `mapped_column()`.
- SQLite for the MVP: `sqlite:///phd_data.db` (gitignored). No server needed;
  a SQLAlchemy `Event`/`PRAGMA` enables `foreign_keys=ON` per connection.
- `DateTime`/`Date` fields stored naive UTC via `default=func.now` / explicit
  `datetime.utcnow()` in rows set by app code. `timestamps=True` equivalent
  helpers (`created_at`, `updated_at`) on every table.
- **Every score/confidence column keeps the full precision float** — ranking is
  deterministic and read out raw; do not pre-round for display.
- JSON sub-fields are stored as `JSON` type (SQLite text) when they are
  record-only (skills/methods/topics), NOT expanded to separate rows in MVP —
  they stay faithful to the data-contract lists.

---

## 2. ER diagram (as text)

```
user_profiles 1------n matches n------1 opportunities
                    \------n supervisors
user_profiles 1------n applications n----1 opportunities
user_profiles 1------n bookmarks   n----1 opportunities
user_profiles 1------1 digest_preferences
```

- `matches` links profile ↔ opportunity **and** profile ↔ supervisor (a
  `target_type` discriminator + `target_id`).
- `opportunities` reuses the source id (`source_unique`) for idempotent
  de-duplication with the crawler.

---

## 3. Models

### 3.1 user_profiles

| Column | SQL type | Notes |
|---|---|---|
| id | INTEGER PK | autoincrement |
| raw_text | TEXT | original CV/bio |
| domain | TEXT | profile domain (astronomy) |
| subfield | TEXT | nullable |
| skills / methods / tools / target_roles / countries_preferred / constraints | JSON (TEXT) | from `UserProfile` lists |
| experience_level | TEXT | |
| funding_requirement | TEXT | nullable |
| _confidence | FLOAT | 0–1 |
| active | BOOLEAN | default True; "current profile" singleton |
| created_at / updated_at | DATETIME | UTC |

```python
class UserProfile(Base):
    __tablename__ = "user_profiles"
    id: Mapped[int] = mapped_column(primary_key=True)
    raw_text: Mapped[Optional[str]]
    domain: Mapped[Optional[str]]
    subfield: Mapped[Optional[str]]
    skills: Mapped[Optional[str]]            # JSON list
    methods: Mapped[Optional[str]]           # JSON join
    tools: Mapped[Optional[str]]
    target_roles: Mapped[Optional[str]]
    countries_preferred: Mapped[Optional[str]]
    funding_requirement: Mapped[Optional[str]]
    constraints: Mapped[Optional[str]]
    confidence: Mapped[Optional[float]]
    active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
```

### 3.2 opportunities

Maps 1:1 onto the `OUTPUT_FIELDS` schema from `core/records.py`
(title, institution, country, deadline, posted_date, effective_date, age_days,
freshness, url, source, relevance_score, matched_anchors, matched_keywords,
short_description, position_type, is_new) plus contract fields.

```python
class Opportunity(Base):
    __tablename__ = "opportunities"
    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(index=True)
    source_raw: Mapped[str]                 # raw source id / URL for re-import
    title: Mapped[str]
    institution: Mapped[Optional[str]]
    department: Mapped[Optional[str]]
    country: Mapped[Optional[str]] = mapped_column(index=True)
    city: Mapped[Optional[str]]
    url: Mapped[Optional[str]] = mapped_column(index=True)
    type: Mapped[Optional[str]]             # phd/postdoc/faculty/staff
    field: Mapped[Optional[str]]
    subfield: Mapped[Optional[str]]
    topics: Mapped[Optional[str]]           # JSON list
    skills_required: Mapped[Optional[str]]
    methods_required: Mapped[Optional[str]]
    funding_status: Mapped[Optional[str]]
    deadline: Mapped[Optional[datetime]]
    posted_date: Mapped[Optional[datetime]]
    effective_date: Mapped[Optional[datetime]]
    age_days: Mapped[Optional[int]]
    freshness: Mapped[Optional[str]]
    relevance_score: Mapped[Optional[float]]
    matched_anchors: Mapped[Optional[str]]  # JSON list
    matched_keywords: Mapped[Optional[str]]
    short_description: Mapped[Optional[str]]
    position_type: Mapped[Optional[str]]
    is_new: Mapped[bool] = mapped_column(default=True)
    confidence: Mapped[Optional[float]]
    created_at / updated_at: DATETIME
```

### 3.3 supervisors

```python
class Supervisor(Base):
    __tablename__ = "supervisors"
    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[Optional[str]]                    # ads | openalex | arxiv
    name: Mapped[str] = mapped_column(index=True)
    institution: Mapped[Optional[str]]
    department: Mapped[Optional[str]]
    country: Mapped[Optional[str]] = mapped_column(index=True)
    profile_url: Mapped[Optional[str]]
    email: Mapped[Optional[str]]
    topics: Mapped[Optional[str]]                    # JSON
    methods: Mapped[Optional[str]]
    recent_papers: Mapped[Optional[str]]             # JSON list
    fit_score: Mapped[Optional[float]]
    confidence: Mapped[Optional[float]]
    created_at / updated_at
```

### 3.4 matches (credits: profile ↔ opportunity or supervisor)

Polymorphic target using two nullable FKs + a type discriminator (simple, no
single-table inheritance complexity for MVP). `relevance_*` fields keep the raw
component scores the deterministic matcher produced, so the UI can drill down
without re-running.

| Column | type | Notes |
|---|---|---|
| profile_id | FK → user_profiles | NOT NULL |
| target_type | VARCHAR | 'opportunity' \| 'supervisor' |
| opportunity_id | FK → opportunities | nullable, set when type=opportunity |
| supervisor_id | FK → supervisors | nullable, set when type=supervisor |
| overall_score / topic_score / method_score / skill_score / location_score / funding_score / competitiveness_score | FLOAT | |
| explanation | TEXT | deterministic generated string |
| confidence | FLOAT | |
| created_at | DATETIME | |

```python
class Match(Base):
    __tablename__ = "matches"
    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("user_profiles.id"))
    target_type: Mapped[str]                       # opportunity | supervisor
    opportunity_id: Mapped[Optional[int]] = mapped_column(ForeignKey("opportunities.id"), nullable=True)
    supervisor_id: Mapped[Optional[int]] = mapped_column(ForeignKey("supervisors.id"), nullable=True)
    overall_score: Mapped[Optional[float]]
    topic_score: Mapped[Optional[float]]
    method_score: Mapped[Optional[float]]
    skill_score: Mapped[Optional[float]]
    location_score: Mapped[Optional[float]]
    funding_score: Mapped[Optional[float]]
    competitiveness_score: Mapped[Optional[float]]
    explanation: Mapped[Optional[str]]
    confidence: Mapped[Optional[float]]
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
```

### 3.5 applications (per-user action tracking)

```python
class Application(Base):
    __tablename__ = "applications"
    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id FK, opportunity_id FK
    status: Mapped[str] = mapped_column(default="draft")  # draft|interview|offer|withdrawn
    cover_letter: Mapped[Optional[str]]
    applied_at: Mapped[Optional[datetime]]
    outcome: Mapped[Optional[str]]
    created_at / updated_at
```

### 3.6 bookmarks

```python
class Bookmark(Base):
    __tablename__ = "bookmarks"
    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id FK, opportunity_id FK
    created_at
    UniqueConstraint(profile_id, opportunity_id)
```

### 3.7 digest_preferences

```python
class DigestPreference(Base):
    __tablename__ = "digest_preferences"
    profile_id: Mapped[int] = mapped_column(ForeignKey("user_profiles.id"), primary_key=True)
    email: Mapped[Optional[str]]
    frequency: Mapped[str] = mapped_column(default="weekly")  # daily|weekly|monthly|off
    include_matches: Mapped[int] = mapped_column(default=5)   # top-N matching positions
    include_supervisors: Mapped[bool] = mapped_column(default=False)
    quiet_days: Mapped[Optional[str]]       # JSON list, e.g. ["Fri","Sat"]
    timezone: Mapped[Optional[str]]
    updated_at
```

---

## 4. Relationships & lifetime

- **Freshness/age_days:** these are derivations written by the crawler.
  `created_at` on `opportunities` is the insertion time, distinct from
  `effective_date` (pipeline's freshness date). Do not conflate.
- **Re-import / dedupe:** `Opportunity.url` + `source` is `unique` indexed, and
  `source_raw` keeps the upstream id. Insert uses `insert ... on_conflict` to
  make repeated crawls idempotent.
- **Matching:** `Match` never recomputes scores at read time; it snapshots the
  deterministic engine output.

---

## 5. MVP scope & next dependencies

- Covered now: schema + ER + FK relationships, SQLite target.
- Not in this spec: events/logs audit trail, full-text search (SQLite FTS5 as a
  later add-on), migration tool selection (Alembic is assumed when the schema
  leaves MVP).
- Depends on: Phase 2 `UserProfile` (Pydantic) — same columns; Phase 1
  `records.py` `OUTPUT_FIELDS` — same columns.

---

## 6. Open questions for review

1. Polymorphic `Match.target_type` vs a dedicated `supervisor_matches` table —
   MVP uses polymorphic for a single table; weigh expandability later.
2. JSON-as-text vs normalized child tables for `skills/topics/recent_papers`:
   MVP chooses JSON text to stay faithful and simple; revisit only when
   $filtering by skill becomes a query hotpath.