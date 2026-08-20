# BOARD_TAXONOMIES.md — what the boards can actually target

> Harvested live on **2026-08-20** as the prerequisite step for
> `plans/03-expand-fields-taxonomy.md`. The point: a new field in
> `astra/fields/` is only as good as the per-board facet it can be pointed at.
> Inventing a field name we cannot target gets us a profile that rides the
> general boards blind. Pick from THIS list.
>
> Method: `Http(cfg).get_soup()` over 12 pages of the live EURAXESS job search,
> accumulating every `job_research_field:<id>` facet that appeared; plus the
> AcademicJobsOnline `/ajo/fields` discipline counter. Both are live-posting
> views, so they show the facets that currently HAVE listings — the useful
> subset, not the full taxonomy.

## 1. EURAXESS — `job_research_field` facet IDs (82 seen with live postings)

The portal ignores `?keywords=` entirely, so this numeric facet is the only
real filter (see the note in `astra/sources/url_registry.yaml`). Blocks run
parent → children → "Other"; **children are subsets of their parent**, which is
the same relationship already verified for astronomy (`items(35) \ items(34)`
was empty every time).

| ID | Label | Claimed today by |
|----|-------|------------------|
| 13 | Anthropology | — |
| 38 | Biological sciences | `biology` |
| 40 | Biological engineering | (child of 38) |
| 41 | Biology | (child of 38) |
| 47 | Chemistry | `chemistry` |
| 48 | Analytical chemistry | (child of 47) |
| 50 | Biochemistry | (child of 47) |
| 52 | Computational chemistry | (child of 47) |
| 59 | Organic chemistry | (child of 47) |
| 60 | Physical chemistry | (child of 47) |
| 78 | Computer science | `computer_science` |
| 84 | Cybernetics | (child of 78) |
| 85 | Database management | (child of 78) |
| 87 | Informatics | (child of 78) |
| 89 | Programming | (child of 78) |
| 94 | Cultural studies | — |
| 104 | European studies | — |
| 117 | Economics | `economics` |
| 158 | Educational sciences | — |
| 159 | Education | (child of 158) |
| 164 | Engineering | `engineering` |
| 168 | Biomedical engineering | (child of 164) |
| 169 | Chemical engineering | (child of 164) |
| 170 | Civil engineering | (child of 164) |
| 172 | Computer engineering | (child of 164) |
| 175 | Electrical engineering | (child of 164) |
| 181 | Materials engineering | (child of 164) |
| 182 | Mechanical engineering | (child of 164) |
| **195** | **Environmental science** | **— unclaimed** |
| 196 | Earth science | (child of 195) |
| 197 | Ecology | (child of 195) |
| 198 | Global change | (child of 195) |
| 208 | Ethics in social sciences | — |
| 210 | Geography | — |
| 219 | Geosciences | `geology`, `geophysics_hydro` |
| 223 | History | — |
| 243 | Music history | — |
| 251 | Information science | `computer_science` |
| 281 | Language sciences | — |
| 286 | Literature | — |
| 298 | Mathematics | `mathematics` |
| 311 | Statistics | (child of 298 — inferred from ID ordering) |
| **313** | **Medical sciences** | **— unclaimed** |
| 314 | Medicine | (child of 313) |
| **317** | **Neurosciences** | **— unclaimed** |
| 320 | Neuroinformatics | (child of 317) |
| 321 | Neurology | (child of 317) |
| 323 | Neuropsychology | (child of 317) |
| 325 | Pharmacological sciences | — |
| 332 | Philosophy | — |
| 334 | Epistemology | (child of 332) |
| 336 | Logic | (child of 332) |
| 337 | Metaphysics | (child of 332) |
| 341 | Philosophy of science | (child of 332) |
| 345 | Physics | `physics`, `condensed_matter`, `astronomy`(adj), `geophysics_hydro` |
| 352 | Condensed matter properties | (child of 345) |
| 358 | Optics | (child of 345) |
| 361 | Solid state physics | (child of 345) |
| 367 | Political sciences | — |
| 374 | Psychological sciences | — |
| 378 | Psychology | (child of 374) |
| 380 | Religious sciences | — |
| 388 | Sociology | — |
| 401 | Technology | `engineering` |
| 402 | Biotechnology | (child of 401) |
| 403 | Chemical technology | (child of 401) |
| 409 | Energy technology | (child of 401) |
| 424 | Medical technology | (child of 401) |
| 428 | Nanotechnology | (child of 401) |
| **6037** | **Health sciences** | **— unclaimed** |
| 920 | All | (the no-filter sentinel) |

Plus `Other` sentinels at 20, 46, 64, 91, 194, 316, 324, 344, 366, 443, 921 —
per-parent catch-alls, not useful targets.

**Parent/child matters for planning.** A new field whose facet is a CHILD of an
already-claimed parent adds no new EURAXESS postings — it re-slices coverage we
already have, more precisely. Its genuinely new reach comes from the general
boards being queried with its own `search_terms`.

## 2. AcademicJobsOnline — live discipline counts

Top 50 by current postings, read off `/ajo/fields` on 2026-08-20:

> Physics (186) · Computer Science (47) · Biology (44) · Theoretical Physics (36)
> · Engineering (33) · High Energy Physics (28) · Chemistry (26) · Condensed
> Matter Physics (25) · Quantum Information Science (23) · Data Science (22) ·
> Astrophysics (20) · Machine Learning (16) · Mathematical Physics (14) ·
> Particle Physics (14) · Law (13) · Statistics (13) · Artificial Intelligence
> (12) · Biophysics (12) · Quantum Computing (12) · Quantum Condensed Matter
> Theory (12) · Nuclear Physics (11) · Quantum Field Theory (11) · AI/Machine
> Learning (10) · Astronomy (10) · Economics (10) · Mathematics (10) ·
> Psychiatry (10) · Quantum Optics (10) · Biochemistry (9) · Cosmology (9) ·
> Quantum Gravity (9) · Statistical Physics (9) · Electrical and Computer
> Engineering (8) · Gravitational Physics (8) · Mechanical Engineering (8) ·
> Microbiology (8) · Neuroscience (8) · Particle Astrophysics (8) · Veterinary
> Medicine (8) · Atomic Molecular and Optical Physics (7) · Computational
> Science and Engineering (7) · Electrical Engineering (7) · Epidemiology (7) ·
> Social Sciences (7) · Bioinformatics (6) · Computational Science (6)

**AJO is a physics and CS board** by volume: physics plus its subfields is well
over half of everything listed, and the `stat` / Data Science / Machine
Learning / AI cluster (13+22+16+12 = 63) is the second densest thing on it.

But **low volume is not the same as no category**, and the first reading of
this list got that wrong. Every batch-1 field turned out to have a real slug —
they are simply small. The counts above tell you what to *expect back*; the
probe below tells you what to *point at*.

### Verified slugs (probed 2026-08-20)

AJO answers **200 for any path** and serves a generic 6054-character fallback
listing, so "it returned results" proves nothing. Each slug below was fetched
and compared against the fallback fingerprint, and read for the discipline it
names in its own heading.

| Slug | Real? | Names itself | Note |
|------|-------|--------------|------|
| `ES` | ✅ | Environmental Science | shared with geology/geophysics_hydro |
| `stat` | ✅ | Statistics | |
| `DS` | ✅ | Data Science | 3717 chars — the largest of the new ones |
| `neurosci` | ✅ | Neuroscience | |
| `neuro` | ✅ | **Neurology** | a different discipline — do not use for neuroscience |
| `biomed` | ✅ | Biomedical Science | |
| `med`, `MED` | ✅ | Medicine | |
| `health` | ✅ | Health | real but nearly empty (704 chars) |
| `MatSci` | ✅ | Materials Science | |
| `ME` | ✅ | Mechanical Engineering | for a future engineering split |
| `EE` | ✅ | Electrical Engineering | for a future engineering split |
| `MS` | ⚠️ | **Media Studies** | the sharpest trap here — *not* Materials Science |
| `neuroscience` | ❌ | — | fallback |
| `materials`, `mat` | ❌ | — | fallback |
| `medicine` | ❌ | — | fallback |
| `bio` | ❌ | — | fallback |
| `NS`, `MatSE`, `materialscience` | ❌ | — | fallback |

Subcategory paths genuinely filter — measured parent vs child page size:
`physics/Materials Science` 14400 vs `physics` 36554, `biology/Neuroscience`
1605 vs `biology` 5375, `cs/Data Science` 2568 vs `cs` 7649.

### The override trap

A field profile's `source_options.academicjobsonline.categories` **wins over
the registry**. On 2026-08-20 six field files were still carrying pre-fix slugs
there: `economics`, `engineering`, `mathematics`, `geology` and
`geophysics_hydro` were all being served the fallback page, and
`condensed_matter` was silently reusing the entire Physics listing. The
registry had been corrected months earlier; the overrides had not. Those blocks
are now deleted, batch-1 fields carry no `source_options` at all, and
`tests/test_source_field_queries.py` guards both halves.

## 3. Batch 1 as shipped (2026-08-20)

| Field | EURAXESS | New coverage or re-slice? | AJO | FindAPhD |
|-------|----------|---------------------------|-----|----------|
| `neuroscience` | 317 (+320/321/323), adj 38 | **New** — unclaimed parent | `neurosci`, `biology/Neuroscience` | pending |
| `biomedical_sciences` | 313, 314, 6037, adj 38 | **New** — largest unclaimed block | `biomed`, `med` | pending |
| `environmental_science` | 195 (+196/197/198), adj 38 | **New** — distinct from geology's 219 | `ES` | pending |
| `materials_science` | 181, 428, 361 | Re-slice — all children of claimed parents | `MatSci`, `physics/Materials Science` | pending |
| `statistics_data_science` | 311, 251, adj 298 | Re-slice — 311 under maths, 251 under CS | `stat`, `DS` | pending |

**FindAPhD is pending for all five, and cannot be fixed from here yet.** Its
discipline tokens are opaque strings (`chemistry/?10M7c0`) readable only off
the site's own rendered links; a guessed one returns FindAPhD's 404. Every
automated fetch on 2026-08-20 returned **403** — the Cloudflare block
`SOURCE_HEALTH.md` already records. The practical cost is currently nil, since
findaphd returns 0 records for *every* field under that same block. The gap is
tracked as `FINDAPHD_PENDING` in `astra/tests/test_source_field_queries.py`;
empty that set when the tokens become readable.

### Live-run sanity check, same day

Each field run against `--source euraxess --source academicjobsonline
--limit-per-source 25`:

| Field | raw → kept | Sample of what came back |
|-------|-----------|--------------------------|
| `neuroscience` | 8 kept | Peripheral Neuroscience & Neuro-Immune postdoc; Wu Tsai Computation & Neuroscience fellowship |
| `biomedical_sciences` | 27 → 6 | Cardiology postdoc; AI & Precision Medicine fellow |
| `environmental_science` | 29 → 14 | PhD Plant Community Ecology; Butterfly Ecology & Climate Change; three Water Treatment Sustainability fellows |
| `materials_science` | 34 → 17 | Reactive extrusion of polymers; Surface Physics/Thin Films; Ceramic Proton Conductors |
| `statistics_data_science` | 50 → 2 | Statistical Scientist (Cornell); UCD Maths & Statistics |

The thin `statistics_data_science` yield is a genuinely quiet day on those two
boards, not the title gate — verified by re-running with
`require_title_anchor: false`, which returned the same two records.

## 4. Refreshing this

Both harvests are cheap to redo and should be redone before any future batch —
facet IDs are stable but posting volume is not:

```
python3 - <<'PY'
import sys, re, json; sys.path.insert(0, 'astra')
from core.config import build_config
from core.http import Http
h = Http(build_config([])); found = {}
for page in range(12):
    soup = h.get_soup('https://euraxess.ec.europa.eu/jobs/search',
                      params=[('page', str(page))])
    if not soup: break
    for a in soup.find_all('a', href=True):
        m = re.search(r'job_research_field%3A(\d+)', a['href'])
        if m: found[int(m.group(1))] = a.get_text(' ', strip=True)[:50]
print(json.dumps(found, indent=1, sort_keys=True))
PY
```

The parent/child claims above are inferred from ID ordering, not read off an
indented sidebar. Verifying one costs a single fetch each: pull the parent and
the child facet and check the child's URLs are a subset — the same test that
settled astronomy's 34/35/37.
