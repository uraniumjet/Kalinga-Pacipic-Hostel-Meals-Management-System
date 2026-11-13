# Security

## Reporting a problem
Please do not open a public issue for a security problem. Email the maintainer (see the repository profile) with
the steps to reproduce. You will get a reply within a few days.

## What the app does to protect data
- Every query is limited to the signed-in user's organisation; wardens are further limited to their hostels.
- Student photos are served only to signed-in staff of the same organisation, never from a public folder.
- Student QR codes contain a random token, not the roll number.
- Passwords use Django's hashing and validators; sessions expire after `DJANGO_SESSION_HOURS` (default 12).
- With `DJANGO_HTTPS=1`: https redirect, secure cookies and HSTS. Clickjacking and content-type sniffing protections are always on.
- The production start-up refuses to run without a real `DJANGO_SECRET_KEY`.

## Running it safely
- Use https on any network you do not fully control.
- Keep `DJANGO_DEBUG=0`, keep `.env` out of version control, and back up regularly (see `docs/deployment.md`).
- Switch off public organisation registration (`ALLOW_ORG_SIGNUP=0`) once your organisations exist.
- Keep dependencies current; Dependabot opens pull requests for updates.
