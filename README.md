<img src="https://cdn.weareasterisk.com/product-assets/gavel/banner.png" width="450" height="150" alt="Gavel banner">

**Gavel** is a project expo voting system. This fork supports participant voting, project-team exclusions, an admin-only live leaderboard, and an audience-voted elimination bracket.

## Participant voting workflow

1. Add projects through the admin dashboard. Each project requires its OrganizerHQ URL.
2. Add participants, then edit each participant to select their project. Participants are never assigned their own project.
3. Run the initial pairwise voting round as usual.
4. Open **Leaderboard / Bracket** from the admin dashboard and create a power-of-two bracket from the top projects.
5. Open one matchup at a time. Members of either presenting team cannot vote. Close the matchup to advance its winner; tied matchups require an administrator-selected winner.

For a fresh database, `python initialize.py` creates the complete schema. For an existing database, apply `migrations/001_participant_bracket.sql` before starting the updated application.

[Click here to create a Heroku instance](https://dashboard.heroku.com/new?template=https%3A%2F%2Fgithub.com%2Fweareasterisk%2Fgavel2%2Ftree%2Fmaster)

[Gavel Documentation](https://gavel.weareasterisk.com/)
