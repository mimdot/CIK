# PRD v1

## Objective
Build a service that reads user information, identifies the user's relevant skills and research direction, and sends a short list of high-fit opportunities and supervisors.

## Target users
- PhD applicants
- Master's applicants in research-heavy fields
- postdoctoral researchers
- research engineers
- specialized professionals in technical fields

## Core jobs to be done
- understand the user accurately
- normalize their background into structured data
- find opportunities that match their line of work
- explain the match in plain language
- send only a small, relevant set of results

## Functional requirements
### User intake
- paste bio/CV text
- optional links: ORCID, Google Scholar, LinkedIn, personal site
- choose field, subfield, region, and funding preference

### Profile extraction
- domain
- subfield
- methods
- tools
- skills
- experience level
- target roles
- preferred regions
- funding requirement
- constraints
- confidence score per field

### Opportunity matching
- positions
- supervisors
- labs
- funded openings
- ranked by fit

### Explainability
Every recommendation must include:
- why it matches
- what is missing
- why it is a good next step
- a confidence indicator

### Email digest
- weekly digest by default
- maximum 5 positions and 5 supervisors
- only high-fit results
- include deadlines and next action

### Tracking
- saved
- contacted
- applied
- interview
- rejected
- accepted

## Non-functional requirements
- low budget
- beginner-friendly maintainability
- deterministic ranking
- modular code
- easy to expand
- LLM-independent core scoring

## Success metrics
- profile completion rate
- email open rate
- click-through rate
- save rate
- user return rate
- positive feedback on recommendation relevance
