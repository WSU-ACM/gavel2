# Discord bot Gavel login-link integration

This document is the implementation handoff for delivering Gavel participant
login links through Discord. Gavel exposes the links; the Discord membership
bot retrieves them and maps them to Discord users through the same participant
external IDs used in `participants.csv`.

## Gavel API

Request:

```http
GET /api/membership-login-links HTTP/1.1
Host: gavel.example.com
Authorization: Bearer <membership-link-export-token>
Accept: application/json
```

The Gavel deployment must set `MEMBERSHIP_LINK_EXPORT_TOKEN`. The bot should
store the same value as a secret. Send the token only in the `Authorization`
header, never in the URL.

Successful response:

```json
{
  "participants": [
    {
      "external_id": "15281-hacktoberfest-hack-day-pullman:mlh:98765",
      "login_url": "https://gavel.example.com/login/example-secret/"
    }
  ]
}
```

The response contains only participants that:

- were imported with `managed_source=membership_bot`;
- have a non-null external ID;
- are currently active in both Gavel and the imported roster.

Rows are ordered by `external_id`. Gavel login secrets are stable, so repeated
requests return the same URL unless an administrator separately changes the
participant credential. The endpoint sends `Cache-Control: no-store`.

Error responses:

| Status | Meaning |
|---|---|
| `401` | The bearer token is missing or incorrect. |
| `503` | Gavel has no `MEMBERSHIP_LINK_EXPORT_TOKEN` configured. |
| `503` | Gavel's `BASE_URL` is not configured as an HTTP or HTTPS origin. |

## Bot changes

Add bot configuration for:

- `GAVEL_BASE_URL`, such as `https://gavel.example.com`;
- `GAVEL_MEMBERSHIP_LINK_EXPORT_TOKEN`, matching Gavel's
  `MEMBERSHIP_LINK_EXPORT_TOKEN`.

Implement an administrator-only bot operation that performs these steps:

1. Fetch `GET {GAVEL_BASE_URL}/api/membership-login-links` over HTTPS with the
   bearer token.
2. Parse the JSON response and reject malformed entries or duplicate
   `external_id` values.
3. Resolve each external ID to the event-specific MLH registration and its
   assigned Discord account. Use the external ID directly; do not match by
   participant name, email address, or project name.
4. DM the corresponding Discord user their `login_url` and a short explanation
   that the link signs them into Gavel.
5. Record delivery status by external ID so an interrupted run can be resumed
   without messaging successful recipients again.
6. Report aggregate sent, skipped, unresolved, and failed counts to the bot
   administrator. Do not include login URLs in the report.

The operation should support an explicit resend for one participant and a
retry of failed deliveries. A normal rerun should skip participants already
recorded as successfully notified unless the administrator requests a resend.

## Suggested bot-side interface

The exact command names depend on the existing bot, but a useful split is:

- `gavel links preview`: fetch and report counts without sending DMs;
- `gavel links send`: send links not previously delivered;
- `gavel links retry`: retry unresolved or failed deliveries;
- `gavel links resend <participant>`: explicitly resend one link.

Before a bulk send, compare the API's external IDs with the locked membership
roster. Treat IDs unknown to the bot as unresolved rather than guessing a
recipient.

## Operational sequence

1. Lock the membership roster in the bot.
2. Export and import `projects.csv` and `participants.csv` into Gavel.
3. Run the bot's preview operation and resolve any missing Discord assignments.
4. Run the bot's send operation.
5. Review aggregate delivery results and retry failures without reimporting the
   Gavel roster.

## Handling credentials

The threat model is intentionally lightweight, but login URLs grant access as
the participant. The bot should not log the API response, bearer token, or DM
body. Avoid storing login URLs when an external ID plus delivery status is
sufficient. If a deployment uses plain HTTP for local testing, use only
non-production participants and credentials.

## Bot acceptance checks

1. A valid token retrieves active imported participants and their links.
2. A missing or incorrect token is reported without retrying indefinitely.
3. Every returned external ID maps to the expected Discord user.
4. A participant receives only their own Gavel link.
5. A normal rerun does not resend successful DMs.
6. Failed DMs can be retried without reimporting the roster.
7. Participants omitted from a later roster snapshot are not messaged.
8. Manual Gavel participants are not returned or messaged.
9. Logs and administrator reports do not contain bearer tokens, login URLs, or
   participant secrets.
