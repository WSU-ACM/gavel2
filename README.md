<img src="https://cdn.weareasterisk.com/product-assets/gavel/banner.png" width="450" height="150" alt="Gavel banner">

**Gavel** is a project expo voting system. This fork supports participant voting, project-team exclusions, an admin-only live leaderboard, and an audience-voted elimination bracket.

## Participant voting workflow

1. Add projects through the admin dashboard. Each project requires its OrganizerHQ URL.
2. Add participants, then edit each participant to select their project. Participants are never assigned their own project.
3. Run the initial pairwise voting round as usual.
4. Open **Leaderboard / Bracket** from the admin dashboard and create a power-of-two bracket from the top projects.
5. Open one matchup at a time. Members of either presenting team cannot vote. Close the matchup to advance its winner; tied matchups require an administrator-selected winner.

For a fresh database, `python initialize.py` creates the complete schema. For an existing database, apply `migrations/001_participant_bracket.sql` and then `migrations/002_membership_roster.sql` before starting the updated application.

## Membership roster import

Authenticated administrators can open **Membership Roster** from the dashboard and upload `projects.csv` and `participants.csv` together. The importer validates both complete snapshots before applying project and participant changes in one transaction. Integration-managed rows that disappear from a later snapshot are made roster-inactive rather than deleted.

Invitation records are committed with the roster and delivered asynchronously. Run the Celery worker to process them:

```sh
celery -A gavel:celery worker -E -P eventlet --loglevel=info
```

Failed or stale invitation deliveries can be retried from the import result page without replaying the roster.

### Discord login-link delivery

Set `MEMBERSHIP_LINK_EXPORT_TOKEN` and configure `BASE_URL` with Gavel's public
HTTP or HTTPS origin. The Discord membership bot can then retrieve active
integration-managed participants from `GET /api/membership-login-links` using
`Authorization: Bearer <token>`. The response maps each participant
`external_id` to their stable Gavel `login_url` and is sent with
`Cache-Control: no-store`.

See `DISCORD_BOT_LOGIN_LINKS.md` for the complete API contract and the Discord
bot implementation handoff.

[Click here to create a Heroku instance](https://dashboard.heroku.com/new?template=https%3A%2F%2Fgithub.com%2Fweareasterisk%2Fgavel2%2Ftree%2Fmaster)

[Gavel Documentation](https://gavel.weareasterisk.com/)
