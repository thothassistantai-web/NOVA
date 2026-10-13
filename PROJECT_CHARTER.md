# NOVA: one coordinator for the computer's AI systems

NOVA is Damian's system-wide voice and text interface for coordinating existing and future AI models, agents, bots and tools. It should know which systems are available, route work according to capabilities, preserve context across routes, show progress and recover gracefully from failures.

## Foundation implemented

The compact/orb interface, continuous voice controller, shared profile and host facts, OpenClaw/Codex/Cursor adapters, managed model catalogs, credential resolution, and behavior monitoring already exist. The integration registry now catalogs installed agent adapters and configured managed model providers without copying credentials. Right-click → NOVA system overview shows that inventory. Installation is distinct from verified tool access or health.

Speech falls back from Groq to local Whisper, and cloud voices to local Piper. Circuit cooldowns skip repeated failing requests. Transient model/network failures can try at most three alternative managed cloud providers followed by local Ollama before any output or action has started. Model selection remains unchanged. Existing agent actions are not automatically replayed after dispatch because execution may already have changed files or external state. Permission failures are not bypassed through another agent.

## Next coordinator layers

1. Shared conversation and memory store: one canonical conversation across model routes; confirmed facts, task results and provenance separate from speculative model text. Existing histories need an explicit migration, rather than merging unrelated sessions.
2. Capability registry: reconcile each backend's actual MCP tools, skills, plugins and authenticated connectors. Record health, last verification and constraints. A product's private features are available only through an exposed supported adapter.
3. Task coordinator: persistent job IDs, capability-based routing, progress, cancellation, resumable handoffs and duplicate-action protection. Preserve each agent's permission and approval boundaries.
4. Unified control center: agents, connectors, conversations, tasks, health and fallback reasons in one organized interface. Keep the orb lightweight.
5. Extension adapters: future bots/agents register declared capabilities and an implementation contract; registration alone does not execute arbitrary commands or grant permissions.

## Definition of completion

NOVA can accept one request, choose an available capable backend, carry relevant verified context through the task, expose tool/action evidence, recover without repeating side effects, and return results through the same voice/text conversation. Adding a new integration does not require rewriting the voice UI. Users can see which backend actually handled the request and why.

Cross-agent memory and complete tool inventories are not yet implemented. The current registry is the foundation, not a claim that all applications' data or features have already been combined.
