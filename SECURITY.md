# Security policy

## Supported versions

The project is currently developed from `main` and has not declared a stable
release support window.

| Version | Supported |
|---|---:|
| Current `main` | Yes |
| Older commits and unmaintained forks | No guaranteed support |

When versioned releases are introduced, this table will identify supported
release lines and security-fix backport policy.

## Reporting a vulnerability

Do not report vulnerabilities in a public issue, discussion, pull request, log
attachment, or chat channel.

If the repository host supports private security advisories, open one for this
repository. Otherwise, contact the maintainer privately using the contact
method on the repository owner's profile and request a secure reporting
channel. Do not send credentials, exploit code, or production evidence until a
private channel is confirmed.

Include, where possible:

- affected commit or version;
- deployment assumptions;
- a concise impact statement;
- reproduction steps using non-production targets;
- whether credentials, remote command execution, model data exposure, alert
  spoofing, or denial of service are involved; and
- suggested mitigations or patches.

## Response expectations

The maintainer should acknowledge a complete private report, assess severity,
coordinate a fix and disclosure date, and credit the reporter if requested.
Exact response times are not guaranteed until a formal support policy is
published.

Please allow time for a coordinated fix before public disclosure, especially
when the issue affects Salt credentials, command validation, Alertmanager
identity, or sensitive data sent to external providers.

## Security scope

Reports are especially valuable for:

- command, unit-name, target, SQL, path, or shell injection;
- bypass of bounded read-only tool behavior;
- unauthorized Salt target access;
- credentials or authorization headers in logs, metrics, alerts, images, or
  traces;
- raw SQL, process arguments, or unrelated evidence sent to the LLM;
- prompt injection that expands tool capability or bypasses output validation;
- unsupported evidence accepted as a confirmed RCA;
- destructive remediation bypassing the safety filter;
- unauthenticated observability exposure beyond the documented network scope;
- alert identity errors that prevent resolution or spoof another incident;
- SQLite state corruption or unsafe migration; and
- dependency or queue behavior that creates an exploitable denial of service.

General hardening suggestions without a concrete impact can be filed as normal
issues after removing environment-specific or sensitive information.

The implemented trust boundaries and deployment expectations are described in
[docs/security.md](docs/security.md).
