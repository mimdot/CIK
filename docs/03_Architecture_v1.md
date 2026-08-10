# Architecture v1

## Main subsystems
### 1. Knowledge Engine
Continuously discovers and normalizes opportunities, supervisors, institutions, and topics from sources such as university pages and OpenAlex.

### 2. Identity Engine
Converts a user's raw text, CV, and links into a structured profile.

### 3. Intelligence Engine
Computes explainable matches between user profile and opportunities.

## Data flow
1. ingest raw source data
2. normalize records
3. build structured user profile
4. compute scores
5. generate explanations
6. send digest
7. store feedback

## Core principle
The LLM should support the system, not define the system.

Use the model for:
- extraction
- summarization
- explanation
- drafting

Do not use the model as the only ranking mechanism.

## Recommended stack
- Python
- FastAPI
- SQLite first
- SQLAlchemy
- Next.js
- Tailwind
- shadcn/ui

## Early modules
- crawler
- parser
- deduplicator
- profile
- matching
- ranking
- explainability
- email
- scheduler
- api
- db

## Data model summary
- UserProfile
- Opportunity
- Supervisor
- Match
- Application
- Bookmark
- DigestPreference

## Matching dimensions
- topic fit
- method fit
- skill fit
- experience fit
- location fit
- funding fit
- competitiveness fit

## Launch sequence
1. clean up the existing script base
2. add structured profile extraction
3. add deterministic ranking
4. add email digest
5. add dashboard
6. expand later
