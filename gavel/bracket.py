from datetime import datetime
from math import log

from gavel.constants import (
    PHASE_BRACKET,
    PHASE_CLOSED,
    PHASE_INITIAL,
    SETTING_CLOSED,
    SETTING_PHASE,
    SETTING_TRUE,
)
from gavel.models import (
    Annotator,
    BracketMatch,
    BracketVote,
    Decision,
    Item,
    Setting,
    Tournament,
    TournamentEntry,
    db,
)
from gavel.voting_state import lock_voting_state, mark_voting_started


def current_phase():
    phase = Setting.value_of(SETTING_PHASE)
    if phase in (PHASE_INITIAL, PHASE_BRACKET, PHASE_CLOSED):
        return phase
    if Setting.value_of(SETTING_CLOSED) == SETTING_TRUE:
        return PHASE_CLOSED
    return PHASE_INITIAL


def ranked_items():
    counts = {}
    for decision in Decision.query.all():
        counts[decision.winner_id] = counts.get(decision.winner_id, 0) + 1
        counts[decision.loser_id] = counts.get(decision.loser_id, 0) + 1

    items = Item.query.filter(Item.effectively_active).order_by(
        Item.mu.desc(),
        Item.sigma_sq.asc(),
        Item.id.asc(),
    ).all()
    return [
        {
            'rank': rank,
            'item': item,
            'comparisons': counts.get(item.id, 0),
        }
        for rank, item in enumerate(items, 1)
    ]


def seed_order(size):
    if size < 2 or size & (size - 1):
        raise ValueError('Bracket size must be a power of two of at least 2.')
    seeds = [1, 2]
    current_size = 2
    while current_size < size:
        current_size *= 2
        expanded = []
        for seed in seeds:
            expanded.extend((seed, current_size + 1 - seed))
        seeds = expanded
    return seeds


def create_tournament(size):
    if current_phase() not in (PHASE_INITIAL, PHASE_CLOSED):
        raise ValueError('The event is not ready to create a bracket.')
    if Tournament.query.filter_by(status='active').first() is not None:
        raise ValueError('An active bracket already exists.')
    unassigned = Annotator.query.filter(
        Annotator.effectively_active,
        Annotator.project_id.is_(None),
    ).count()
    if unassigned:
        raise ValueError(
            'Assign a project to every active participant before creating the bracket.'
        )

    ranking = ranked_items()
    if size > len(ranking):
        raise ValueError('There are not enough active projects for that bracket size.')
    order = seed_order(size)
    tournament = Tournament(size=size, status='active')
    db.session.add(tournament)
    db.session.flush()

    by_seed = {}
    for row in ranking[:size]:
        item = row['item']
        entry = TournamentEntry(
            tournament=tournament,
            item=item,
            seed=row['rank'],
            initial_mu=item.mu,
            initial_sigma_sq=item.sigma_sq,
        )
        db.session.add(entry)
        by_seed[row['rank']] = item

    first_round_matches = size // 2
    for position in range(first_round_matches):
        db.session.add(BracketMatch(
            tournament=tournament,
            round_number=1,
            position=position,
            item_a=by_seed[order[position * 2]],
            item_b=by_seed[order[position * 2 + 1]],
        ))

    rounds = int(log(size, 2))
    for round_number in range(2, rounds + 1):
        match_count = size // (2 ** round_number)
        for position in range(match_count):
            db.session.add(BracketMatch(
                tournament=tournament,
                round_number=round_number,
                position=position,
            ))

    Setting.set(SETTING_PHASE, PHASE_BRACKET)
    Setting.set(SETTING_CLOSED, SETTING_TRUE)
    return tournament


def active_tournament():
    return Tournament.query.filter_by(status='active').order_by(Tournament.id.desc()).first()


def open_match(match_id):
    if current_phase() != PHASE_BRACKET:
        raise ValueError('Elimination-bracket voting is not open. Return to Gavel for the current voting stage.')
    tournament = active_tournament()
    if tournament is None:
        raise ValueError('There is no active bracket.')
    if BracketMatch.query.filter_by(tournament_id=tournament.id, status='open').first():
        raise ValueError('Close the current matchup before opening another.')
    match = BracketMatch.query.filter_by(id=match_id, tournament_id=tournament.id).with_for_update().first()
    if match is None or match.status != 'pending' or not match.ready:
        raise ValueError('That matchup is not ready to open.')
    match.status = 'open'
    match.opened_at = datetime.utcnow()
    return match


def cast_vote(match_id, annotator_id, item_id):
    if current_phase() != PHASE_BRACKET:
        raise ValueError('Bracket voting is not open.')
    voting_setting = lock_voting_state()
    match = BracketMatch.query.filter_by(id=match_id).with_for_update().first()
    annotator = Annotator.query.filter_by(id=annotator_id).first()
    if match is None or match.status != 'open':
        raise ValueError('Voting for that matchup has closed. Return to the bracket for the current matchup.')
    if annotator is None or not annotator.effectively_active:
        raise ValueError('Your participant account is not eligible to vote in this matchup. Ask a hackathon organizer for help.')
    if item_id not in (match.item_a_id, match.item_b_id):
        raise ValueError('That project is not part of the current matchup. Return to the bracket and try again.')
    if annotator.project_id in (match.item_a_id, match.item_b_id):
        raise ValueError("You cannot vote in this matchup because your team's project is competing.")
    if BracketVote.query.filter_by(match_id=match.id, annotator_id=annotator.id).first():
        raise ValueError('Your vote was already recorded and cannot be changed.')
    vote = BracketVote(match=match, annotator=annotator, item_id=item_id)
    db.session.add(vote)
    mark_voting_started(voting_setting)
    return vote


def close_match(match_id, tie_winner_id=None):
    if current_phase() != PHASE_BRACKET:
        raise ValueError('Bracket voting is not open.')
    match = BracketMatch.query.filter_by(id=match_id).with_for_update().first()
    if match is None or match.status != 'open':
        raise ValueError('That matchup is not open.')

    counts = {match.item_a_id: 0, match.item_b_id: 0}
    for vote in match.votes:
        counts[vote.item_id] += 1
    if counts[match.item_a_id] == counts[match.item_b_id]:
        if tie_winner_id not in counts:
            raise ValueError('Select a winner to resolve the tied matchup.')
        winner_id = tie_winner_id
    else:
        winner_id = max(counts, key=counts.get)

    match.winner_id = winner_id
    match.status = 'closed'
    match.closed_at = datetime.utcnow()

    tournament = match.tournament
    final_round = int(log(tournament.size, 2))
    if match.round_number == final_round:
        tournament.champion_id = winner_id
        tournament.status = 'complete'
        tournament.completed_at = datetime.utcnow()
        Setting.set(SETTING_PHASE, PHASE_CLOSED)
        return match

    next_match = BracketMatch.query.filter_by(
        tournament_id=tournament.id,
        round_number=match.round_number + 1,
        position=match.position // 2,
    ).with_for_update().one()
    if match.position % 2 == 0:
        next_match.item_a_id = winner_id
    else:
        next_match.item_b_id = winner_id
    return match
