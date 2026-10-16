import base64
import io
import os
import unittest
from unittest import mock


os.environ['IGNORE_CONFIG_FILE'] = 'true'
os.environ['DATABASE_URL'] = 'sqlite:////tmp/opencode/gavel2-membership-tests.db'
os.environ['REDIS_URL'] = 'redis://localhost:6379/15'
os.environ['BASE_URL'] = 'http://localhost'
os.environ['ADMIN_PASSWORD'] = 'admin'
os.environ['MEMBERSHIP_LINK_EXPORT_TOKEN'] = 'test-membership-token'
os.environ['SECRET_KEY'] = 'test-secret'
os.environ['EMAIL_FROM'] = ''
os.environ['EMAIL_USER'] = ''
os.environ['EMAIL_PASSWORD'] = ''
os.environ['DISABLE_EMAIL'] = 'true'
os.environ['SEND_STATS'] = 'false'

from gavel import app
from gavel.constants import SETTING_FALSE, SETTING_TRUE, SETTING_VOTING_STARTED
from gavel.models import (
    Annotator,
    InvitationDelivery,
    Item,
    MembershipRosterImport,
    Setting,
    db,
)
from gavel.services.membership_roster import (
    MAX_ROWS,
    RosterValidationError,
    import_snapshot,
    parse_snapshot,
    read_upload,
)
from gavel.services.invitation_delivery import deliver_invitation


PROJECT_HEADER = 'external_id,name,description,submission_url\n'
PARTICIPANT_HEADER = 'external_id,name,email,description,project_external_id\n'


class MembershipRosterTest(unittest.TestCase):
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
        Setting.set(SETTING_VOTING_STARTED, SETTING_FALSE)
        db.session.commit()

    def tearDown(self):
        db.session.rollback()
        self.request_context.pop()

    def snapshot(self, projects=None, participants=None):
        if projects is None:
            projects = (
                PROJECT_HEADER
                + 'event:team:1,Project One,First project,https://example.com/projects/1\n'
            )
        if participants is None:
            participants = (
                PARTICIPANT_HEADER
                + 'event:mlh:1,Alice,alice@example.edu,Project One member,event:team:1\n'
            )
        return parse_snapshot(projects.encode('utf-8'), participants.encode('utf-8'))

    def test_create_and_exact_replay_preserve_identity_and_secret(self):
        first = import_snapshot(self.snapshot())
        project = Item.query.one()
        participant = Annotator.query.one()
        original = (
            project.id,
            project.mu,
            project.sigma_sq,
            participant.id,
            participant.secret,
            participant.alpha,
            participant.beta,
            participant.project_id,
        )

        second = import_snapshot(self.snapshot())
        project = Item.query.one()
        participant = Annotator.query.one()

        self.assertEqual(1, first['projects_created'])
        self.assertEqual(1, first['participants_created'])
        self.assertEqual(1, second['projects_unchanged'])
        self.assertEqual(1, second['participants_unchanged'])
        self.assertEqual(original, (
            project.id,
            project.mu,
            project.sigma_sq,
            participant.id,
            participant.secret,
            participant.alpha,
            participant.beta,
            participant.project_id,
        ))
        self.assertEqual(1, InvitationDelivery.query.count())
        self.assertEqual(2, MembershipRosterImport.query.count())

    def test_metadata_updates_existing_records(self):
        import_snapshot(self.snapshot())
        project_id = Item.query.one().id
        participant = Annotator.query.one()
        participant_id = participant.id
        secret = participant.secret

        changed = self.snapshot(
            projects=(
                PROJECT_HEADER
                + 'event:team:1,Renamed Project,Updated,https://example.com/projects/updated\n'
            ),
            participants=(
                PARTICIPANT_HEADER
                + 'event:mlh:1,Alice Updated,new@example.edu,Updated member,event:team:1\n'
            ),
        )
        result = import_snapshot(changed)

        self.assertEqual(1, result['projects_updated'])
        self.assertEqual(1, result['participants_updated'])
        self.assertEqual(project_id, Item.query.one().id)
        self.assertEqual(participant_id, Annotator.query.one().id)
        self.assertEqual(secret, Annotator.query.one().secret)

    def test_pre_voting_project_reassignment_updates_existing_participant(self):
        projects = (
            PROJECT_HEADER
            + 'event:team:1,Project One,First,https://example.com/1\n'
            + 'event:team:2,Project Two,Second,https://example.com/2\n'
        )
        import_snapshot(self.snapshot(projects=projects))
        participant = Annotator.query.one()
        participant_id = participant.id
        secret = participant.secret

        participants = (
            PARTICIPANT_HEADER
            + 'event:mlh:1,Alice,alice@example.edu,Project Two member,event:team:2\n'
        )
        result = import_snapshot(self.snapshot(projects, participants))

        participant = Annotator.query.one()
        self.assertEqual(1, result['participants_updated'])
        self.assertEqual(participant_id, participant.id)
        self.assertEqual(secret, participant.secret)
        self.assertEqual('event:team:2', participant.project.external_id)

    def test_missing_rows_deactivate_only_managed_records(self):
        import_snapshot(self.snapshot())
        manual_item = Item('Manual', 'table', 'manual')
        manual_annotator = Annotator('Manual', 'manual@example.edu', 'manual')
        manual_annotator.project = manual_item
        db.session.add_all([manual_item, manual_annotator])
        db.session.commit()

        result = import_snapshot(self.snapshot(PROJECT_HEADER, PARTICIPANT_HEADER))

        self.assertEqual(1, result['projects_deactivated'])
        self.assertEqual(1, result['participants_deactivated'])
        self.assertFalse(Item.query.filter_by(external_id='event:team:1').one().roster_active)
        self.assertFalse(Annotator.query.filter_by(external_id='event:mlh:1').one().roster_active)
        self.assertTrue(manual_item.effectively_active)
        self.assertTrue(manual_annotator.effectively_active)

    def test_reactivation_preserves_secret_and_manual_disable(self):
        import_snapshot(self.snapshot())
        participant = Annotator.query.one()
        participant.active = False
        secret = participant.secret
        db.session.commit()
        import_snapshot(self.snapshot(PROJECT_HEADER, PARTICIPANT_HEADER))
        result = import_snapshot(self.snapshot())

        participant = Annotator.query.one()
        self.assertEqual(1, result['participants_updated'])
        self.assertTrue(participant.roster_active)
        self.assertFalse(participant.active)
        self.assertFalse(participant.effectively_active)
        self.assertEqual(secret, participant.secret)

    def test_vote_lock_rejects_roster_changes_but_allows_metadata(self):
        import_snapshot(self.snapshot())
        Setting.set(SETTING_VOTING_STARTED, SETTING_TRUE)
        db.session.commit()

        with self.assertRaises(RosterValidationError) as raised:
            import_snapshot(self.snapshot(PROJECT_HEADER, PARTICIPANT_HEADER))
        self.assertEqual('roster_locked_after_voting', raised.exception.code)
        self.assertTrue(Item.query.one().roster_active)
        self.assertTrue(Annotator.query.one().roster_active)

        metadata = self.snapshot(
            projects=(
                PROJECT_HEADER
                + 'event:team:1,Project One Updated,Updated,https://example.com/projects/1\n'
            ),
        )
        result = import_snapshot(metadata)
        self.assertEqual(1, result['projects_updated'])

    def test_vote_lock_rejects_reassignment_and_new_records(self):
        projects = (
            PROJECT_HEADER
            + 'event:team:1,Project One,First,https://example.com/1\n'
            + 'event:team:2,Project Two,Second,https://example.com/2\n'
        )
        import_snapshot(self.snapshot(projects=projects))
        original_project_id = Annotator.query.one().project_id
        Setting.set(SETTING_VOTING_STARTED, SETTING_TRUE)
        db.session.commit()

        reassigned = (
            PARTICIPANT_HEADER
            + 'event:mlh:1,Alice,alice@example.edu,Member,event:team:2\n'
        )
        with self.assertRaises(RosterValidationError) as raised:
            import_snapshot(self.snapshot(projects, reassigned))
        self.assertEqual('roster_locked_after_voting', raised.exception.code)
        self.assertEqual(original_project_id, Annotator.query.one().project_id)

        added_project = projects + 'event:team:3,Project Three,Third,https://example.com/3\n'
        with self.assertRaises(RosterValidationError) as raised:
            import_snapshot(self.snapshot(added_project))
        self.assertEqual('roster_locked_after_voting', raised.exception.code)
        self.assertEqual(2, Item.query.count())

    def test_cross_resource_conflict_is_rejected_without_changes(self):
        with self.assertRaises(RosterValidationError) as raised:
            self.snapshot(
                participants=(
                    PARTICIPANT_HEADER
                    + 'event:team:1,Alice,alice@example.edu,Member,event:team:1\n'
                ),
            )
        self.assertEqual('resource_type_conflict', raised.exception.code)
        self.assertEqual(0, Item.query.count())
        self.assertEqual(0, Annotator.query.count())

    def test_validation_rejects_duplicate_normalized_values(self):
        projects = (
            PROJECT_HEADER
            + 'one,Same Name,Description,https://example.com/1\n'
            + 'two, same name ,Description,https://example.com/2\n'
        )
        with self.assertRaises(RosterValidationError) as raised:
            self.snapshot(projects=projects)
        self.assertEqual('duplicate_project_name', raised.exception.code)

        duplicate_emails = (
            PARTICIPANT_HEADER
            + 'one,Alice,Same@Example.edu,Member,event:team:1\n'
            + 'two,Bob, same@example.edu ,Member,event:team:1\n'
        )
        with self.assertRaises(RosterValidationError) as raised:
            self.snapshot(participants=duplicate_emails)
        self.assertEqual('duplicate_email', raised.exception.code)

    def test_structural_validation_reason_codes(self):
        cases = [
            (b'', PARTICIPANT_HEADER.encode(), 'missing_header'),
            (b'name,external_id,description,submission_url\n', PARTICIPANT_HEADER.encode(), 'invalid_header'),
            (b'\xff', PARTICIPANT_HEADER.encode(), 'invalid_utf8'),
            ((PROJECT_HEADER + '\n').encode(), PARTICIPANT_HEADER.encode(), 'blank_row'),
            ((PROJECT_HEADER + 'id,name,description\n').encode(), PARTICIPANT_HEADER.encode(), 'missing_cell'),
            ((PROJECT_HEADER + 'id,name,description,https://example.com,extra\n').encode(), PARTICIPANT_HEADER.encode(), 'extra_cell'),
            ((PROJECT_HEADER + 'id,name,description,ftp://example.com\n').encode(), PARTICIPANT_HEADER.encode(), 'invalid_url'),
            (
                (PROJECT_HEADER + 'id,' + ('x' * 256) + ',description,https://example.com\n').encode(),
                PARTICIPANT_HEADER.encode(),
                'field_too_long',
            ),
            (
                (PROJECT_HEADER + 'id,name,description,https://example.com\n').encode(),
                (PARTICIPANT_HEADER + 'person,Alice,alice@example.edu,Member,missing\n').encode(),
                'unknown_project_external_id',
            ),
        ]
        for projects, participants, code in cases:
            with self.subTest(code=code):
                with self.assertRaises(RosterValidationError) as raised:
                    parse_snapshot(projects, participants)
                self.assertEqual(code, raised.exception.code)

        oversized_rows = PROJECT_HEADER + ''.join(
            'id%d,Name %d,Description,https://example.com/%d\n' % (index, index, index)
            for index in range(MAX_ROWS + 1)
        )
        with self.assertRaises(RosterValidationError) as raised:
            parse_snapshot(oversized_rows.encode(), PARTICIPANT_HEADER.encode())
        self.assertEqual('too_many_rows', raised.exception.code)

        upload = type('Upload', (), {'stream': io.BytesIO(b'x' * (2 * 1024 * 1024 + 1))})()
        with self.assertRaises(RosterValidationError) as raised:
            read_upload(upload)
        self.assertEqual('file_too_large', raised.exception.code)

    def test_source_conflict_and_database_failure_are_atomic(self):
        conflicting = Item('Existing', 'table', 'existing')
        conflicting.external_id = 'event:team:1'
        conflicting.managed_source = 'another_source'
        db.session.add(conflicting)
        db.session.commit()
        with self.assertRaises(RosterValidationError) as raised:
            import_snapshot(self.snapshot())
        self.assertEqual('source_conflict', raised.exception.code)
        self.assertEqual(0, Annotator.query.count())

        db.session.delete(conflicting)
        db.session.commit()
        import_snapshot(self.snapshot())
        original_name = Item.query.one().name
        changed = self.snapshot(
            projects=(
                PROJECT_HEADER
                + 'event:team:1,Should Roll Back,Changed,https://example.com/changed\n'
            ),
        )
        with mock.patch(
            'gavel.services.membership_roster.db.session.flush',
            side_effect=RuntimeError('injected'),
        ):
            with self.assertRaises(RuntimeError):
                import_snapshot(changed)
        db.session.expire_all()
        self.assertEqual(original_name, Item.query.one().name)
        self.assertEqual(1, Annotator.query.count())

    def test_invitation_task_sends_once_using_internal_id(self):
        result = import_snapshot(self.snapshot())
        delivery = InvitationDelivery.query.get(result['invitation_ids'][0])
        delivery_id = delivery.id

        with mock.patch('gavel.services.invitation_delivery.settings.DISABLE_EMAIL', False), mock.patch(
            'gavel.services.invitation_delivery._send_email'
        ) as send_email:
            deliver_invitation.apply(args=[delivery_id]).get()
            deliver_invitation.apply(args=[delivery_id]).get()

        delivery = InvitationDelivery.query.get(delivery_id)
        self.assertEqual('sent', delivery.status)
        self.assertEqual(1, delivery.attempts)
        self.assertEqual(1, send_email.call_count)

    def test_broker_failure_does_not_roll_back_endpoint_import(self):
        client = app.test_client()
        credentials = base64.b64encode(b'admin:admin').decode('ascii')
        auth = {'Authorization': 'Basic ' + credentials}
        with client.session_transaction() as client_session:
            client_session['_csrf_token'] = 'token'

        with mock.patch(
            'gavel.services.invitation_delivery.deliver_invitation.apply_async',
            side_effect=RuntimeError('broker unavailable'),
        ):
            response = client.post(
                '/admin/membership-roster/import',
                data={
                    '_csrf_token': 'token',
                    'projects_file': (
                        io.BytesIO((PROJECT_HEADER + 'p,Project,Description,https://example.com/p\n').encode()),
                        'projects.csv',
                    ),
                    'participants_file': (
                        io.BytesIO((PARTICIPANT_HEADER + 'a,Alice,alice@example.edu,Member,p\n').encode()),
                        'participants.csv',
                    ),
                },
                headers=auth,
                content_type='multipart/form-data',
            )

        self.assertEqual(302, response.status_code)
        self.assertEqual(1, Item.query.count())
        self.assertEqual(1, Annotator.query.count())
        self.assertEqual('failed', InvitationDelivery.query.one().status)
        self.assertEqual('queue_failed', InvitationDelivery.query.one().failure_code)

    def test_endpoint_requires_auth_and_csrf_and_redacts_values(self):
        client = app.test_client()
        credentials = base64.b64encode(b'admin:admin').decode('ascii')
        auth = {'Authorization': 'Basic ' + credentials}

        missing_csrf = client.post('/admin/membership-roster/import', headers=auth)
        self.assertEqual(403, missing_csrf.status_code)

        with client.session_transaction() as client_session:
            client_session['_csrf_token'] = 'token'
        no_auth = client.post(
            '/admin/membership-roster/import',
            data={'_csrf_token': 'token'},
        )
        self.assertEqual(401, no_auth.status_code)

        sentinel = 'private-person@example.edu'
        with mock.patch('gavel.controllers.admin.enqueue_invitations'):
            response = client.post(
                '/admin/membership-roster/import',
                data={
                    '_csrf_token': 'token',
                    'projects_file': (io.BytesIO(PROJECT_HEADER.encode()), 'projects.csv'),
                    'participants_file': (
                        io.BytesIO((PARTICIPANT_HEADER + 'id,Name,' + sentinel + '\n').encode()),
                        'participants.csv',
                    ),
                },
                headers=auth,
                content_type='multipart/form-data',
            )
        self.assertEqual(400, response.status_code)
        self.assertNotIn(sentinel.encode(), response.data)

    def test_membership_login_link_api_authenticates_and_returns_only_active_managed_participants(self):
        import_snapshot(self.snapshot())
        active_participant = Annotator.query.filter_by(external_id='event:mlh:1').one()

        first_active = Annotator('First Active', 'first@example.edu', 'active')
        first_active.external_id = 'event:mlh:0'
        first_active.managed_source = 'membership_bot'
        first_active.roster_active = True
        roster_inactive = Annotator('Roster Inactive', 'inactive@example.edu', 'inactive')
        roster_inactive.external_id = 'event:mlh:2'
        roster_inactive.managed_source = 'membership_bot'
        roster_inactive.roster_active = False
        manually_inactive = Annotator('Manually Inactive', 'disabled@example.edu', 'inactive')
        manually_inactive.external_id = 'event:mlh:3'
        manually_inactive.managed_source = 'membership_bot'
        manually_inactive.roster_active = True
        manually_inactive.active = False
        manual = Annotator('Manual', 'manual@example.edu', 'manual')
        db.session.add_all([first_active, roster_inactive, manually_inactive, manual])
        db.session.commit()

        client = app.test_client()
        unauthorized = client.get('/api/membership-login-links')
        self.assertEqual(401, unauthorized.status_code)
        self.assertEqual('Bearer', unauthorized.headers['WWW-Authenticate'])
        wrong_token = client.get(
            '/api/membership-login-links',
            headers={'Authorization': 'Bearer wrong-token'},
        )
        self.assertEqual(401, wrong_token.status_code)

        response = client.get(
            '/api/membership-login-links',
            headers={'Authorization': 'Bearer test-membership-token'},
        )

        self.assertEqual(200, response.status_code)
        self.assertEqual('no-store', response.headers['Cache-Control'])
        self.assertEqual({
            'participants': [
                {
                    'external_id': 'event:mlh:0',
                    'login_url': 'http://localhost/login/' + first_active.secret + '/',
                },
                {
                    'external_id': 'event:mlh:1',
                    'login_url': 'http://localhost/login/' + active_participant.secret + '/',
                },
            ],
        }, response.get_json())
        self.assertNotIn(manual.secret.encode(), response.data)
        self.assertNotIn(roster_inactive.secret.encode(), response.data)
        self.assertNotIn(manually_inactive.secret.encode(), response.data)

        with mock.patch('gavel.controllers.api.settings.MEMBERSHIP_LINK_EXPORT_TOKEN', ''):
            unavailable = client.get(
                '/api/membership-login-links',
                headers={'Authorization': 'Bearer test-membership-token'},
            )
        self.assertEqual(503, unavailable.status_code)

        with mock.patch('gavel.controllers.api.settings.BASE_URL', '_unused_'):
            invalid_base_url = client.get(
                '/api/membership-login-links',
                headers={'Authorization': 'Bearer test-membership-token'},
            )
        self.assertEqual(503, invalid_base_url.status_code)


if __name__ == '__main__':
    unittest.main()
