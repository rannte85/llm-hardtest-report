# Security Policy

Security fixes are applied to the latest release and the default branch. Older
benchmark snapshots may remain available for reproducibility but are not guaranteed
to receive fixes.

## Reporting a vulnerability

Use GitHub's **Report a vulnerability** private security advisory for this repository.
Do not open a public issue for command injection, credential exposure, sandbox escape,
unsafe archive handling, or another vulnerability that could put users at risk.

Include the affected commit, operating system, minimal reproduction, impact, and any
suggested mitigation. Remove API keys, private output, and personal data. Maintainers
will acknowledge a usable report as soon as practical and coordinate disclosure after
a fix is available.

## Operational boundary

Round 4 runs an external coding-agent process. The harness isolates task artifacts but
is not a hardened security sandbox. Run untrusted agents in a container or disposable
account with least privilege, no production credentials, and no access to unrelated
files. The project cannot guarantee third-party servers, models, or Codex versions.
