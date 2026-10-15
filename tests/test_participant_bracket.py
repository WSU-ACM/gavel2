import os
import base64
import unittest


os.environ['IGNORE_CONFIG_FILE'] = 'true'
os.environ['DATABASE_URL'] = 'sqlite:////tmp/opencode/gavel2-tests.db'
os.environ['REDIS_URL'] = 'redis://localhost:6379/15'
os.environ['BASE_URL'] = 'http://localhost'
os.environ['ADMIN_PASSWORD'] = 'admin'
os.environ['SECRET_KEY'] = 'test-secret'
os.environ['EMAIL_FROM'] = ''
os.environ['EMAIL_USER'] = ''
os.environ['EMAIL_PASSWORD'] = ''
os.environ['DISABLE_EMAIL'] = 'true'
os.environ['SEND_STATS'] = 'false'

from gavel import app
import gavel.bracket as bracket
from gavel.constants import PHASE_INITIAL, SETTING_PHASE
from gavel.controllers.judge import preferred_items
from gavel.models import Annotator, BracketMatch, BracketVote, Item, Setting, db


class ParticipantBracketTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app_context = app.app_context()
        cls.app_context.push()

    @classmethod
    def tearDownClass(cls):
        db.session.remove()
        db.drop_all()
        cls.app_context.pop()

    def setUp(self):
        self.request_context = app.test_request_context('/')
        self.request_context.push()
        db.session.remove()
        db.drop_all()
        db.create_all()
        Setting.set(SETTING_PHASE, PHASE_INITIAL)
        db.session.commit()

    def tearDown(self):
        db.session.rollback()
        self.request_context.pop()

    def make_item(self, name, mu=0):
        item = Item(
            name,
            'table',
            'description',
            submission_reference='https://organizer.example/' + name.lower(),
        )
        item.mu = mu
        db.session.add(item)
        return item

    def test_owned_project_is_not_assigned(self):
        owned = self.make_item('Owned')
        other = self.make_item('Other')
        participant = Annotator('Participant', 'p@example.com', '')
        participant.project = owned
        db.session.add(participant)
        db.session.commit()

        candidates = preferred_items(participant)

        self.assertEqual([other.id], [item.id for item in candidates])

    def test_seed_order_is_standard(self):
        self.assertEqual([1, 4, 2, 3], bracket.seed_order(4))
        self.assertEqual([1, 8, 4, 5, 2, 7, 3, 6], bracket.seed_order(8))
        with self.assertRaises(ValueError):
            bracket.seed_order(6)

    def test_tournament_snapshots_ranking_and_seeds_matches(self):
        items = [self.make_item('Project%d' % seed, 10 - seed) for seed in range(1, 5)]
        db.session.commit()

        tournament = bracket.create_tournament(4)
        db.session.commit()

        self.assertEqual([item.id for item in items], [entry.item_id for entry in tournament.entries])
        first_round = BracketMatch.query.filter_by(round_number=1).order_by(BracketMatch.position).all()
        self.assertEqual((items[0].id, items[3].id), (first_round[0].item_a_id, first_round[0].item_b_id))
        self.assertEqual((items[1].id, items[2].id), (first_round[1].item_a_id, first_round[1].item_b_id))

    def test_team_members_cannot_vote_and_ballots_are_unique(self):
        items = [self.make_item('Project%d' % seed, 10 - seed) for seed in range(1, 4)]
        member = Annotator('Member', 'member@example.com', '')
        member.project = items[0]
        voter = Annotator('Voter', 'voter@example.com', '')
        voter.project = items[2]
        db.session.add_all([member, voter])
        db.session.commit()
        tournament = bracket.create_tournament(2)
        db.session.commit()
        match = tournament.matches[0]
        bracket.open_match(match.id)
        db.session.commit()

        with self.assertRaises(ValueError):
            bracket.cast_vote(match.id, member.id, items[0].id)
        bracket.cast_vote(match.id, voter.id, items[0].id)
        db.session.commit()
        with self.assertRaises(ValueError):
            bracket.cast_vote(match.id, voter.id, items[1].id)
        self.assertEqual(1, BracketVote.query.count())

    def test_tie_requires_an_admin_winner_and_completes_final(self):
        items = [self.make_item('Project%d' % seed, 10 - seed) for seed in range(1, 3)]
        db.session.commit()
        tournament = bracket.create_tournament(2)
        db.session.commit()
        match = tournament.matches[0]
        bracket.open_match(match.id)
        db.session.commit()

        with self.assertRaises(ValueError):
            bracket.close_match(match.id)
        bracket.close_match(match.id, items[0].id)
        db.session.commit()

        self.assertEqual('complete', tournament.status)
        self.assertEqual(items[0].id, tournament.champion_id)

    def test_audience_and_admin_bracket_pages_render(self):
        items = [self.make_item('Project%d' % seed, 10 - seed) for seed in range(1, 4)]
        voter = Annotator('Voter', 'voter@example.com', '')
        voter.read_welcome = True
        voter.project = items[2]
        db.session.add(voter)
        db.session.commit()
        tournament = bracket.create_tournament(2)
        db.session.commit()
        match_id = tournament.matches[0].id
        winner_id = items[0].id
        bracket.open_match(match_id)
        db.session.commit()

        client = app.test_client()
        with client.session_transaction() as client_session:
            client_session['annotator_id'] = voter.id
        audience_response = client.get('/')
        credentials = base64.b64encode(b'admin:admin').decode('ascii')
        admin_response = client.get(
            '/admin/bracket/',
            headers={'Authorization': 'Basic ' + credentials},
        )

        self.assertEqual(200, audience_response.status_code)
        self.assertIn(b'Vote for Project', audience_response.data)
        self.assertEqual(200, admin_response.status_code)
        self.assertIn(b'Leaderboard and bracket', admin_response.data)

        bracket.close_match(match_id, winner_id)
        db.session.commit()
        champion_response = client.get('/')
        self.assertEqual(200, champion_response.status_code)
        self.assertIn(b'Project1 wins!', champion_response.data)

    def test_bracket_requires_every_active_participant_to_have_a_project(self):
        self.make_item('Project1', 2)
        self.make_item('Project2', 1)
        db.session.add(Annotator('Unassigned', 'unassigned@example.com', ''))
        db.session.commit()

        with self.assertRaises(ValueError):
            bracket.create_tournament(2)


if __name__ == '__main__':
    unittest.main()
