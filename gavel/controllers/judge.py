from gavel import app
from gavel.models import *
from gavel.constants import *
import gavel.settings as settings
import gavel.utils as utils
import gavel.crowd_bt as crowd_bt
import gavel.bracket as bracket
from gavel.voting_state import lock_voting_state, mark_voting_started
from flask import (
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from numpy.random import choice, random, shuffle
from functools import wraps
from datetime import datetime

def requires_initial_phase(redirect_to):
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if bracket.current_phase() != PHASE_INITIAL:
                return redirect(url_for(redirect_to))
            else:
                return f(*args, **kwargs)
        return decorated
    return decorator

def requires_active_annotator(redirect_to):
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            annotator = get_current_annotator()
            if annotator is None or not annotator.effectively_active:
                return redirect(url_for(redirect_to))
            else:
                return f(*args, **kwargs)
        return decorated
    return decorator


@app.route('/')
def index():
    annotator = get_current_annotator()
    if annotator is None:
        return render_template(
            'logged_out.html',
            content=utils.render_markdown(settings.LOGGED_OUT_MESSAGE)
        )
    else:
        phase = bracket.current_phase()
        if phase == PHASE_CLOSED:
            completed_tournament = Tournament.query.filter_by(
                status='complete'
            ).order_by(Tournament.id.desc()).first()
            if completed_tournament is not None:
                return render_template(
                    'bracket_vote.html',
                    tournament=completed_tournament,
                    match=None,
                    existing_vote=None,
                    eligible=False,
                    phase=phase,
                )
            return render_template(
                'closed.html',
                content=utils.render_markdown(settings.CLOSED_MESSAGE)
            )
        if not annotator.effectively_active and not annotator.stop_next:
            return render_template(
                'disabled.html',
                content=utils.render_markdown(settings.DISABLED_MESSAGE)
            )
        if not annotator.effectively_active and annotator.stop_next:
            return render_template(
                'closed.html',
                content=utils.render_markdown(settings.CLOSING_MESSAGE)
            )
        if annotator.project_id is None:
            return render_template(
                'disabled.html',
                content=utils.render_markdown(
                    'Your account has not been assigned to a project. Please contact an organizer.'
                ),
            )
        if phase == PHASE_BRACKET:
            tournament = bracket.active_tournament()
            current_match = None
            existing_vote = None
            eligible = False
            if tournament is not None:
                current_match = BracketMatch.query.filter_by(
                    tournament_id=tournament.id,
                    status='open',
                ).first()
            if current_match is not None:
                existing_vote = BracketVote.query.filter_by(
                    match_id=current_match.id,
                    annotator_id=annotator.id,
                ).first()
                eligible = annotator.project_id not in (
                    current_match.item_a_id,
                    current_match.item_b_id,
                )
            return render_template(
                'bracket_vote.html',
                tournament=tournament,
                match=current_match,
                existing_vote=existing_vote,
                eligible=eligible,
                phase=phase,
            )
        if not annotator.read_welcome:
            return redirect(url_for('welcome'))
        maybe_init_annotator()
        if annotator.next is None:
            return render_template(
                'wait.html',
                content=utils.render_markdown(settings.WAIT_MESSAGE)
            )
        elif annotator.prev is None:
            return render_template('begin.html', item=annotator.next)
        else:
            return render_template('vote.html', prev=annotator.prev, next=annotator.next)

@app.route('/vote', methods=['POST'])
@requires_initial_phase(redirect_to='index')
@requires_active_annotator(redirect_to='index')
def vote():
    try:
        prev_id = int(request.form.get('prev_id', ''))
        next_id = int(request.form.get('next_id', ''))
    except ValueError:
        return utils.user_error('Invalid voting assignment.')

    def tx():
        voting_setting = None
        if request.form.get('action') in ('Previous', 'Current'):
            voting_setting = lock_voting_state()
        annotator = get_current_annotator()
        if bracket.current_phase() != PHASE_INITIAL:
            return
        if annotator.prev is None or annotator.next is None:
            return
        if annotator.prev.id == prev_id and annotator.next.id == next_id:
            if annotator.project_id in (annotator.prev_id, annotator.next_id):
                annotator.prev = None
                annotator.update_next(None)
                db.session.commit()
                return
            if request.form['action'] in ['Skip', 'SkipAbsent', 'SkipBusy']:
                annotator.ignore.append(annotator.next)

                if request.form['action'] == 'SkipAbsent':
                    flag = Flag(annotator, annotator.next, 'Absent')
                    db.session.add(flag)
            else:
                # ignore things that were deactivated in the middle of judging
                if annotator.prev.effectively_active and annotator.next.effectively_active:
                    if request.form['action'] == 'Previous':
                        mark_voting_started(voting_setting)
                        perform_vote(annotator, next_won=False)
                        decision = Decision(annotator, winner=annotator.prev, loser=annotator.next)
                    elif request.form['action'] == 'Current':
                        mark_voting_started(voting_setting)
                        perform_vote(annotator, next_won=True)
                        decision = Decision(annotator, winner=annotator.next, loser=annotator.prev)
                    else:
                        return
                    db.session.add(decision)
                annotator.next.viewed.append(annotator) # counted as viewed even if deactivated
                annotator.prev = annotator.next
                annotator.ignore.append(annotator.prev)
            if annotator.stop_next:
                annotator.active = False
                annotator.stop_next = False
            annotator.update_next(choose_next(annotator))
            db.session.commit()
    with_retries(tx)
    return redirect(url_for('index'))

@app.route('/report', methods=['POST'])
@requires_initial_phase(redirect_to='index')
@requires_active_annotator(redirect_to='index')
def report():
    try:
        next_id = int(request.form.get('next_id', ''))
    except ValueError:
        return utils.user_error('Invalid project assignment.')

    def tx():
        annotator = get_current_annotator()
        if bracket.current_phase() != PHASE_INITIAL or annotator.next is None:
            return
        reason = request.form['reason']
        if reason in ['Unknown', '']:
            return
        if annotator.next.id == next_id:
            flag = Flag(annotator, annotator.next, reason)
            db.session.add(flag)
            annotator.ignore.append(annotator.next)
            if annotator.prev:
                annotator.update_next(choose_next(annotator))
            else:
                annotator.next = None
            db.session.commit()
    with_retries(tx)
    return redirect(url_for('index'))

@app.route('/begin', methods=['POST'])
@requires_initial_phase(redirect_to='index')
@requires_active_annotator(redirect_to='index')
def begin():
    try:
        item_id = int(request.form.get('item_id', ''))
    except ValueError:
        return utils.user_error('Invalid project assignment.')

    def tx():
        annotator = get_current_annotator()
        if bracket.current_phase() != PHASE_INITIAL or annotator.next is None:
            return
        if annotator.next.id == item_id:
            if annotator.project_id == annotator.next_id:
                annotator.update_next(None)
                db.session.commit()
                return
            annotator.ignore.append(annotator.next)
            if request.form['action'] == 'Done':
                annotator.next.viewed.append(annotator)
                annotator.prev = annotator.next
                annotator.update_next(choose_next(annotator))
            elif request.form['action'] in ['Skip', 'SkipAbsent', 'SkipBusy']:
                if request.form['action'] == 'SkipAbsent':
                    flag = Flag(annotator, annotator.next, 'Absent')
                    db.session.add(flag)
                annotator.next = None # will be reset in index
            if annotator.stop_next:
                annotator.active = False
                annotator.stop_next = False
            db.session.commit()
    with_retries(tx)
    return redirect(url_for('index'))

@app.route('/logout')
def logout():
    session.pop(ANNOTATOR_ID, None)
    return redirect(url_for('index'))

@app.route('/login/<secret>/')
def login(secret):
    annotator = Annotator.by_secret(secret)
    if annotator is None:
        session.pop(ANNOTATOR_ID, None)
        session.modified = True
    else:
        session[ANNOTATOR_ID] = annotator.id
    return redirect(url_for('index'))

@app.route('/welcome/')
@requires_initial_phase(redirect_to='index')
@requires_active_annotator(redirect_to='index')
def welcome():
    return render_template(
        'welcome.html'
    )

@app.route('/welcome/done', methods=['POST'])
@requires_initial_phase(redirect_to='index')
@requires_active_annotator(redirect_to='index')
def welcome_done():
    def tx():
        annotator = get_current_annotator()
        if bracket.current_phase() != PHASE_INITIAL:
            return
        if request.form['action'] == 'Done':
            annotator.read_welcome = True
        db.session.commit()
    with_retries(tx)
    return redirect(url_for('index'))

@app.route('/welcome/instructions/')
@requires_initial_phase(redirect_to='index')
@requires_active_annotator(redirect_to='index')
def welcome_instructions():
    return render_template(
        'instructions.html'
    )

def get_current_annotator():
    return Annotator.by_id(session.get(ANNOTATOR_ID, None))

def preferred_items(annotator):
    '''
    Return a list of preferred items for the given annotator to look at next.

    This method uses a variety of strategies to try to select good candidate
    projects.
    '''
    items = []
    ignored_ids = {i.id for i in annotator.ignore}

    if annotator.project_id is not None:
        ignored_ids.add(annotator.project_id)

    if ignored_ids:
        available_items = Item.query.filter(
            Item.effectively_active & (~Item.id.in_(ignored_ids))
        ).all()
    else:
        available_items = Item.query.filter(Item.effectively_active).all()

    prioritized_items = [i for i in available_items if i.prioritized]

    items = prioritized_items if prioritized_items else available_items

    annotators = Annotator.query.filter(
        Annotator.effectively_active & (Annotator.next != None) & (Annotator.updated != None)
    ).all()
    busy = {i.next.id for i in annotators if \
        (datetime.utcnow() - i.updated).total_seconds() < settings.TIMEOUT * 60}
    nonbusy = [i for i in items if i.id not in busy]
    preferred = nonbusy if nonbusy else items

    less_seen = [i for i in preferred if len(i.viewed) < settings.MIN_VIEWS]

    return less_seen if less_seen else preferred

def maybe_init_annotator():
    def tx():
        annotator = get_current_annotator()
        if annotator.next is None:
            items = preferred_items(annotator)
            if items:
                annotator.update_next(choice(items))
                db.session.commit()
    with_retries(tx)

def choose_next(annotator):
    items = preferred_items(annotator)

    shuffle(items) # useful for argmax case as well in the case of ties
    if items:
        if random() < crowd_bt.EPSILON:
            return items[0]
        else:
            return crowd_bt.argmax(lambda i: crowd_bt.expected_information_gain(
                annotator.alpha,
                annotator.beta,
                annotator.prev.mu,
                annotator.prev.sigma_sq,
                i.mu,
                i.sigma_sq), items)
    else:
        return None

def perform_vote(annotator, next_won):
    if next_won:
        winner = annotator.next
        loser = annotator.prev
    else:
        winner = annotator.prev
        loser = annotator.next
    u_alpha, u_beta, u_winner_mu, u_winner_sigma_sq, u_loser_mu, u_loser_sigma_sq = crowd_bt.update(
        annotator.alpha,
        annotator.beta,
        winner.mu,
        winner.sigma_sq,
        loser.mu,
        loser.sigma_sq
    )
    annotator.alpha = u_alpha
    annotator.beta = u_beta
    winner.mu = u_winner_mu
    winner.sigma_sq = u_winner_sigma_sq
    loser.mu = u_loser_mu
    loser.sigma_sq = u_loser_sigma_sq
