# Repository Structure

## Recommended root
career-intelligence-platform/

## Proposed layout
```text
backend/
  api/
  crawler/
  matching/
  profile/
  ranking/
  explainability/
  scheduler/
  emails/
  auth/
  db/
  utils/
  config/

frontend/

prompts/

docs/
  00_Project_Index.md
  01_Project_Overview.md
  02_PRD_v1.md
  03_Architecture_v1.md
  04_Roadmap_and_Milestones.md
  05_Repo_Structure.md

specs/

tests/

scripts/
```

## Migration rule
The old monolithic script should be broken into modules gradually, not replaced in one risky jump.
