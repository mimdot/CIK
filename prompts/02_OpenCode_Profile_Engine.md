# OpenCode Prompt — Profile Engine

We are building a career intelligence platform.

Create a module named `profile_engine`.

Purpose:
Convert a user's CV or biography into structured JSON.

Input:
- plain text

Output:
- Python dataclass `UserProfile`

Fields:
- education
- experience
- skills
- methods
- programming_languages
- research_topics
- publications
- countries
- career_goals
- preferred_regions
- funding_requirement
- target_roles
- confidence_score

Requirements:
- no LLM assumptions
- every extracted field must include confidence
- unknown fields must remain null
- use Pydantic models

Output:
- project structure
- interfaces
- classes
- tests
- no implementation yet
