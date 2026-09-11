# Franchise Mode Master Roadmap

This roadmap preserves the long-term direction for the NBA Roster Optimization
Engine. New systems should use durable league state, transactional mutations,
explainable AI, configurable realism, and a shared decision inbox.

## Foundation and usability

- Persistent multi-season franchises and durable checkpoints
- Color-coded workspace navigation, breadcrumbs, contextual explanations, and
  direct links from alerts to the correct screen
- Shared league event queue and decision inbox
- Simulation interruption settings and event expiration rules
- League news, transaction history, milestones, records, and narrative summaries

## Health, fatigue, and medical operations

- League-wide injury audit at 10, 20, 40, and 82-game checkpoints
- Body-part injuries, severity, recurrence, chronic conditions, and reinjury risk
- Fatigue, schedule density, travel, overtime, workload, and back-to-back effects
- Return-to-play stages, minutes restrictions, rehabilitation, and medical clearance
- Medical, training, and strength staff quality

## AI front offices and trade ecosystem

- Persistent AI general-manager identities, timelines, needs, and risk tolerance
- Incoming user trade offers that can pause simulation
- Counteroffers, negotiation memory, leverage, walk-away logic, and trade difficulty
- CPU-to-CPU trades with Off, Conservative, Realistic, Active, and Chaos settings
- Optional commissioner approval or veto of AI trades
- Trade deadline behavior, buyers, sellers, injuries, standings, and owner pressure
- Explainable valuation gaps, roster fit, salary effects, and future-value tradeoffs

## Draft classes and scouting

- Persistent generated names, backgrounds, ages, measurements, positions, and archetypes
- Hidden true ability, potential, floor, ceiling, development curve, and bust probability
- Domestic, international, developmental-league, and alternate pathways
- Class-strength and positional-depth variation
- Weekly scouting-resource allocation
- Film, analytics, live games, interviews, medical reviews, combine, and workouts
- Scout specialties, uncertainty ranges, confidence, and fallible evaluations
- Prospect relationships, promises, interviews, personality, and team fit
- User draft board, staff board, tiers, expected availability, and trade recommendations
- Thirty independent AI scouting boards and intelligent pick logic
- Pick-by-pick draft night, trade-up/down negotiation, reaches, slides, and position runs
- Rookie contracts, summer league, training camp, mentorship, and development plans

## Contracts and offseason

- Rookie-scale contracts, extensions, options, qualifying offers, and restricted free agency
- Unrestricted free agency, agents, market preferences, negotiations, exceptions, and sign-and-trades
- Waivers, roster limits, two-way contracts, and salary-cap/apron consequences
- Player and team goals, role promises, and contract priorities

## Coaches, staff, and organizational identity

- Head coach hiring, firing, extensions, buyouts, job security, and coaching carousel
- Offensive and defensive coordinators, lead assistants, development coaches, and specialists
- Scouts, trainers, medical staff, strength staff, GM, and assistant GM roles
- Coach systems: pace, shot profile, play types, rotations, defensive coverages, and development
- Staff contracts, reputation, relationships, compatibility, poaching, and coaching trees
- Owner expectations, budgets, front-office control, and context-aware performance reviews
- AI hiring based on roster, timeline, owner preferences, weaknesses, and candidate fit

## Player world

- Morale, expected role, minutes, loyalty, ambition, patience, competitiveness, and work ethic
- Chemistry, leadership, mentorship, agent relationships, trade requests, and role complaints
- Scheme fit, position changes, development variance, decline, and career arcs

## Interactive Coach Mode

- Possession-by-possession simulation without requiring graphical player control
- Game clock, score, substitutions, fatigue, fouls, turnovers, rebounds, and lineup tracking
- Shot location, shot quality, defender, contest, play type, and assist opportunity
- Live shot charts, heat maps, play-by-play, win probability, runs, and lineup plus-minus
- Timeouts and user decisions for pace, shot profile, matchups, coverages, doubles, rebounding,
  rotation length, substitutions, intentional fouling, and star usage
- Quick simulation, broadcast simulation, coach-decision mode, and sandbox what-if mode

## Design principles

1. AI difficulty improves decision quality and information asymmetry instead of cheating.
2. AI teams do not receive hidden perfect knowledge of prospects or players.
3. Every major AI decision should expose a concise explanation.
4. User-facing previews must be clearly separated from committed franchise outcomes.
5. Long-running simulation actions must report progress and remain checkpoint-safe.
6. Every new system requires focused self-tests, integration validation, and unified validation.
