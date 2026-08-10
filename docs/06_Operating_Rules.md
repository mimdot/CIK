# Operating Rules for Agents

## First principles
- preserve behavior unless a change is explicitly requested
- keep ranking deterministic
- use the LLM only where it adds value
- keep every task independently testable
- avoid redesigning the entire system at once

## When to stop and ask
If a requirement is ambiguous:
1. state the ambiguity
2. show the options
3. recommend one
4. wait for approval

## What not to do
- do not silently invent features
- do not change architecture without notice
- do not optimize before correctness
- do not couple unrelated modules
- do not make the system dependent on one model provider

## Definition of a good change
A good change is small, testable, and moves the platform one step closer to reliable match quality.
