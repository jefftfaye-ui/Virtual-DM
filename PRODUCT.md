# Product

## Register

product

## Users

Jeff and Julee: two adults playing D&D together on a shared screen. Colocated, drinks nearby, evening session. Neither needs affordances for newcomers; both are comfortable with modern software. The screen is their table. They lean into it.

## Product Purpose

A virtual game table UI for two players with an AI Dungeon Master. The interface surfaces the DM's narrative prominently, keeps party status (HP, conditions, spell slots, encounter) always visible, and lets both players type or speak their actions. Each session starts by referencing the active campaign — scene, party, active quests — so the world grounds itself before anyone speaks.

The UI is a window into the campaign, not a wrapper for a chatbot.

## Brand Personality

Immersive. Focused. Earned.

Not dramatic. Not decorated. The interface recedes so the story advances. Every element on screen either serves the game or gets cut.

## Anti-references

- 90s and early-2000s RPG UIs: beveled chrome borders, fluorescent green health bars, HUDs with 40 overlapping elements, "GAME OVER" typography, fake LCD readouts
- WoW / FFXIV action bars: icon grids, floating damage numbers, tooltip overload
- Parchment textures, aged paper, Celtic knotwork borders, glowing rune decorations
- Generic SaaS dark mode: the standard Tailwind slate palette with blue accents

## Design Principles

1. **The story is the product.** DM narrative gets the most space, the best typography, the highest contrast. Everything else is secondary.
2. **State at a glance.** Party HP, conditions, and encounter order are always visible without clicks. A downed party member is instantly legible from across the table.
3. **Two voices, one table.** Jeff and Julee are equals. Neither's input area dominates; both are reachable from the same posture.
4. **Session-grounded.** The UI opens with the current campaign scene, party status, and active quests. The world exists before the first message.
5. **Tools, not theater.** Voice input and dice rolls are functional, not animations for their own sake. The sound of a die matters; the particle system does not.

## Accessibility & Inclusion

WCAG AA minimum. High contrast between narrative text and backgrounds — sessions run long, eyes tire. Mic input is supplemental to text, never required. No motion-heavy animations; turns and HP changes update cleanly.
