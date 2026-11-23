# Security Policy

Because **DQAgent** (`dataquality-agent`) connects to analytical data warehouses and generates SQL remediation proposals, security and operational safety are first-class design requirements.

## Supported versions

Security updates are applied to `master` and the latest released version.

| Version | Supported |
| :--- | :--- |
| `master` (latest) | :white_check_mark: |
| Latest `0.x` release | :white_check_mark: |
| Older snapshots | :x: |

## Built-in guardrails

DQAgent enforces several layers of defense-in-depth to protect production warehouses:

1. **SafeSQL read-only guardrail.** Every runtime inspection and diagnostic query is validated through SafeSQL before reaching an adapter: `SELECT`-only (blocking `INSERT`/`UPDATE`/`DELETE`/`DROP`/`ALTER`/`TRUNCATE` and multi-statement payloads), an explicit table allowlist, and a row cap against unbounded scans.
2. **Propose-only runtime + HITL approval.** At runtime DQAgent only *proposes* remediation plans — it never executes write or schema-mutating SQL against production. High-risk fixes require explicit human approval before anything leaves the agent.
3. **Offline clone verification.** Proposed remediation SQL is verified offline against an isolated clone before surfacing for human sign-off.
4. **Credential & evidence hygiene.** Database connection strings and LLM API keys belong in environment variables or untracked local config — never commit credentials, warehouse dumps, or unredacted PII samples into issues, PRs, or shared case stores.

## Reporting a vulnerability

**Please do not report security vulnerabilities through public GitHub issues, discussions, or PRs.**

If you find a vulnerability — a SafeSQL guardrail bypass, a SQL injection vector in a `WarehouseAdapter`, a credential leak in logs/evidence packages, or prompt-injection escalation in remediation generation — report it privately:

1. **GitHub private vulnerability reporting (preferred):**
   `https://github.com/wanghesong2019/dataquality-agent/security/advisories/new`
2. **Email:** wanghesong2021@gmail.com, subject `[SECURITY] DQAgent: <brief summary>`.

### What to include

- The affected component (SafeSQL parser, a specific adapter, CLI, `RemediationPolicy`, or `CaseStore`).
- DQAgent version, Python version, and target database dialect.
- Minimal reproduction steps or proof-of-concept SQL/config.
- Potential impact (read-only bypass, unauthorized table access, credential exposure).

### Timeline

- **Acknowledgment** within 48 hours.
- **Triage & assessment** within 5 business days.
- **Fix & coordinated disclosure** — once patched and released, we publish an advisory crediting your discovery (unless you prefer anonymity).
