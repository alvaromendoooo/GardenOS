# Authentication & Registration Workflow

Status: **draft for the MVP**. Covers who can register, how users get tied to a
company, and what each kind of user sees. Design of the token mechanics comes next.

## Decision

Authentication is implemented **inside the backend** (Flask + tokens + roles).
An external identity provider (Keycloak) was considered and **deferred**: it adds
a service to run and operate that the MVP doesn't need. Because identity is kept
behind our own `users` / `auth` tables, it can be introduced later if needed.

Trade-off accepted: we are now responsible for password hashing, token
issuing/expiry/revocation, email verification and password reset.

## Core principles

1. **A person registers, never a company.** A company is created by an
   already-registered person.
2. **Identity, membership and permission are different things.**

   | Concept | Meaning | Where |
   |---|---|---|
   | Identity | who logged in | `users` + `auth` |
   | Membership | works for company X | `employee` (user + company) |
   | Permission | may do Y inside X | access level on `employee` (not yet modeled) |

3. **An employee never chooses a company.** The link to a company always comes
   from someone already inside it (invitation). Otherwise anyone could join any
   company and read its data.
4. **The backend is the authority.** The UI only hides things; every endpoint
   checks authentication, membership, permission and ownership itself.

## Who sees what (driven by state, not by registration choice)

| State | Area | Route |
|---|---|---|
| Not logged in | Public marketing site | `/` |
| Logged in, no membership | Onboarding: create a company, or client portal if linked as a customer | `/onboarding`, `/portal` |
| Logged in, has membership | Management app for company and employees | `/app/*` |

The frontend asks `GET /api/me` and picks the area from the response:

```
memberships:    [ {company, permission} ]    -> management app
customer_links: [ {company, customer} ]      -> client portal (post-MVP)
```

A user with neither is valid (just registered). One user may have both.

## Flows

**A. Register a business (founder)**
```
Sign up -> log in -> POST /api/companies -> company + owner employee (ONE transaction)
```
A failure must never leave a company without an owner.

**B. Join a company (employee) - invitation only**
```
Admin invites email -> one-time link -> person signs up or logs in -> accepts -> employee row created
```
Invitation: `company_id`, `email`, `permission`, `token_hash`, `invited_by`,
`expires_at`, `accepted_at`. Store only a **hash** of the token, make it
single-use with an expiry, and require the accepting account's email to match.

**C. Client portal (post-MVP, model A)**
A company invites a customer by email; accepting sets `customer.user_id`.
Properties stay owned by the company, so tenant isolation is unchanged. A client
can *request* work (new `requested` work-order status the company must accept);
they never create active work orders directly. Clients are scoped by
`customer.user_id`, a second isolation axis that needs its own tests.

## How a request finds its company

```
Token -> verify signature + expiry -> user id -> employee row(s) -> company_id -> check permission
```

- `company_id` is **looked up in the DB on each request**, not trusted from the
  token, so removing an employee takes effect immediately.
- If a user belongs to several companies, the client states which one (for
  example the company's `public_id` in a header) and the backend verifies
  membership.
- No membership -> respond `403` with code `no_company` so the frontend can
  route to onboarding.

## Roles

Start with `owner`, `admin`, `member`. This is separate from the existing
free-text `employee.role`, which is only a job specialization. Code branches on
permission, never on that text. Every company keeps at least one owner.

## Decisions (MVP)

1. **One company per user.** Enforced by `UNIQUE (employee.user_id)`.
2. **Tokens:** short-lived access token + revocable refresh token stored hashed
   (`refresh_token`), rotated on use; `family_id` allows revoking a whole chain
   if a revoked token is replayed.
3. **Invitations:** the company's owner invites. There is a single owner per
   company (partial unique index) and the owner cannot leave or be removed
   (application rule). Nobody can be invited as `owner`.
4. **Email verification and password reset are required**, using single-use
   hashed tokens in `user_token`.

## Schema (implemented)

| Table / column | Purpose |
|---|---|
| `employee.permission` | `owner` / `admin` / `member`, separate from free-text `employee.role` |
| `employee` unique `user_id` | one company per user |
| `employee` unique `company_id` where `permission = 'owner'` | at most one owner |
| `invitation` | tenant-owned; `token_hash`, `expires_at`, `accepted_at`, `invited_by` |
| `refresh_token` | hashed, revocable, rotated; `family_id`, `revoked_at` |
| `user_token` | hashed, single-use; purpose `email_verification` / `password_reset` |
| `auth.email` CHECK lowercase | makes email uniqueness case-insensitive |

Application rules the database does NOT enforce (must be coded and tested):
only the owner invites; the owner can never be removed; a company always keeps
its owner; invitation acceptance requires the accepting account's email to match;
expired/used/revoked tokens are refused.

Later: nullable `customer.user_id` for the client portal.

## Out of scope for the MVP

Client portal, marketplace-style public work posts, social login, MFA, an
external identity provider.
