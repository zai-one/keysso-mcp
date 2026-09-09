# Keysso MCP maintenance

This repository owns the Keys.so MCP implementation and contract. The central
platform is a consumer, not a required runtime dependency. Follow the workspace
task protocol at `../../AGENTS.md` when that file exists; standalone users do not
need the ZAI workspace.

Use Python for scripts. Preserve existing MCP names/schemas and server-owned
authorization, account boundaries, budgets, approvals and unknown-outcome state.
Do not use live provider accounts or credentials in tests. Keep setup local and explicit.
Run scripts/verify.py and scripts/verify_install.py before releases.
Use Issues for requested changes. Preserve LICENSE, NOTICE and third-party licenses.
Never publish operational handoffs, private extraction refs, credentials or runtime state.
Production deployment is a separate action.
When operating in a workspace with a task/verifier protocol, follow that protocol.
