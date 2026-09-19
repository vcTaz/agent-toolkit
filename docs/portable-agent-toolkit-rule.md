> **Copy for reference.** The live rule is installed at
> `${CLAUDE_CONFIG_DIR:-~/.claude}/rules/portable-agent-toolkit.md`. This copy exists so the
> rule travels with the toolkit; machine-specific absolute paths have been generalised.

# Portable Agent Toolkit

The Portable Agent Toolkit located at:

the toolkit checkout (this repository)

is **one of the agent toolkits available in this environment**.

It provides reusable roles, skills, workflows, and reliability patterns that may be useful for substantial software-engineering, research, debugging, architecture, validation, and review tasks.

It is not the exclusive source of agents, skills, workflows, or instructions.

Other globally installed or project-specific:

- agents
- skills
- toolkits
- plugins
- MCP tools
- repository instructions
- workflows

may also be available and may be more appropriate for a particular task.

## Available roles from this toolkit

- Explorer
- Specialist
- Implementer
- Critic
- Validator
- Synthesizer
- Final Reviewer

## Core reliability principles

When this toolkit is relevant:

- the producer of an important artifact should not be its only reviewer;
- Critic and Validator are distinct responsibilities;
- agreement is not verification;
- only the assigned Implementer should modify an owned artifact unless the workflow explicitly allows otherwise;
- validated blocking findings prevent successful completion until resolved;
- use independent final review for substantial completed deliverables;
- use parallel agents only when work is genuinely independent;
- do not create extra agents merely to increase agent count.

## Toolkit selection

Before using this toolkit, consider the task and the other agents, skills, and toolkits available in the environment.

Use the Portable Agent Toolkit when its roles, skills, workflows, or reliability mechanisms materially improve the task.

Do not force this toolkit onto simple tasks or tasks better served by another specialized toolkit.

When multiple toolkits are relevant, they may be combined where their instructions are compatible.

## Authority and precedence

Explicit user instructions and applicable project-specific instructions take precedence over generic toolkit guidance.

Platform-level safety, permission, sandbox, and security constraints always remain in force.

Using this toolkit does not override:

- repository-specific `CLAUDE.md` or other applicable project instructions;
- explicit user requirements;
- platform permissions or sandbox restrictions;
- stronger specialized instructions from another applicable toolkit.

## Source

Canonical toolkit definitions are maintained in:

the toolkit checkout (this repository)

Consult the canonical role, skill, or workflow definition when using this toolkit rather than relying on memory alone.
