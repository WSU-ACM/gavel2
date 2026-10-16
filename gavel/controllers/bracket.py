from sqlalchemy.exc import IntegrityError

from flask import json, redirect, render_template, request, session, url_for

from gavel import app
import gavel.bracket as bracket
import gavel.utils as utils
from gavel.constants import ANNOTATOR_ID, PHASE_BRACKET
from gavel.models import (
    Annotator,
    BracketMatch,
    BracketVote,
    Tournament,
    db,
    with_retries,
)


def _json(data):
    return app.response_class(
        response=json.dumps(data),
        status=200,
        mimetype='application/json',
    )


def _match_data(match):
    counts = {match.item_a_id: 0, match.item_b_id: 0}
    for vote in match.votes:
        counts[vote.item_id] += 1
    eligible_voters = 0
    if match.ready:
        eligible_voters = sum(
            1 for annotator in Annotator.query.filter(Annotator.effectively_active).all()
            if annotator.project_id not in (match.item_a_id, match.item_b_id)
        )
    return {
        'id': match.id,
        'round': match.round_number,
        'position': match.position,
        'status': match.status,
        'ready': match.ready,
        'item_a': {
            'id': match.item_a_id,
            'name': match.item_a.name if match.item_a else None,
            'votes': counts.get(match.item_a_id, 0),
        },
        'item_b': {
            'id': match.item_b_id,
            'name': match.item_b.name if match.item_b else None,
            'votes': counts.get(match.item_b_id, 0),
        },
        'winner_id': match.winner_id,
        'ballots': len(match.votes),
        'eligible_voters': eligible_voters,
    }


@app.route('/bracket/vote', methods=['POST'])
def bracket_vote():
    if bracket.current_phase() != PHASE_BRACKET:
        return redirect(url_for('index'))
    annotator_id = session.get(ANNOTATOR_ID)
    if annotator_id is None:
        return redirect(url_for('index'))
    try:
        match_id = int(request.form.get('match_id', ''))
        item_id = int(request.form.get('item_id', ''))
    except ValueError:
        return utils.user_error('This ballot could not be submitted. Return to the bracket and vote in the current matchup.')

    try:
        def tx():
            bracket.cast_vote(match_id, annotator_id, item_id)
            db.session.commit()
        with_retries(tx)
    except (ValueError, IntegrityError) as error:
        db.session.rollback()
        return utils.user_error(str(error))
    return redirect(url_for('index'))


@app.route('/bracket/status')
def bracket_status():
    annotator = Annotator.query.get(session.get(ANNOTATOR_ID))
    tournament = bracket.active_tournament()
    current_match = None
    if tournament is not None:
        current_match = BracketMatch.query.filter_by(
            tournament_id=tournament.id,
            status='open',
        ).first()
    voted = False
    eligible = False
    if annotator is not None and current_match is not None:
        voted = BracketVote.query.filter_by(
            match_id=current_match.id,
            annotator_id=annotator.id,
        ).first() is not None
        eligible = annotator.effectively_active and annotator.project_id not in (
            current_match.item_a_id,
            current_match.item_b_id,
        )
    return _json({
        'phase': bracket.current_phase(),
        'match_id': current_match.id if current_match else None,
        'voted': voted,
        'eligible': eligible,
    })


@app.route('/admin/bracket/')
@utils.requires_auth
def admin_bracket():
    return render_template('admin_bracket.html')


@app.route('/admin/bracket/state')
@utils.requires_auth
def admin_bracket_state():
    tournament = bracket.active_tournament()
    if tournament is None:
        tournament = Tournament.query.order_by(Tournament.id.desc()).first()
    ranking = [{
        'rank': row['rank'],
        'id': row['item'].id,
        'name': row['item'].name,
        'mu': row['item'].mu,
        'sigma_sq': row['item'].sigma_sq,
        'comparisons': row['comparisons'],
    } for row in bracket.ranked_items()]
    return _json({
        'phase': bracket.current_phase(),
        'ranking': ranking,
        'tournament': None if tournament is None else {
            'id': tournament.id,
            'size': tournament.size,
            'status': tournament.status,
            'champion': tournament.champion.name if tournament.champion else None,
            'matches': [_match_data(match) for match in tournament.matches],
        },
    })


@app.route('/admin/bracket/action', methods=['POST'])
@utils.requires_auth
def admin_bracket_action():
    action = request.form.get('action')
    try:
        if action == 'create':
            size = int(request.form.get('size', ''))

            def tx():
                bracket.create_tournament(size)
                db.session.commit()
        elif action == 'open':
            match_id = int(request.form.get('match_id', ''))

            def tx():
                bracket.open_match(match_id)
                db.session.commit()
        elif action == 'close':
            match_id = int(request.form.get('match_id', ''))
            tie_winner = request.form.get('tie_winner_id')
            tie_winner_id = int(tie_winner) if tie_winner else None

            def tx():
                bracket.close_match(match_id, tie_winner_id)
                db.session.commit()
        else:
            return utils.user_error('Unknown bracket action.')
        with_retries(tx)
    except (ValueError, IntegrityError) as error:
        db.session.rollback()
        return utils.user_error(str(error))
    return redirect(url_for('admin_bracket'))
