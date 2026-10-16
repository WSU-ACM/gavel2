import smtplib
import uuid
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests
from gavel import celery
import gavel.settings as settings
import gavel.utils as utils
from gavel.models import InvitationDelivery, db


class InvitationSendError(Exception):
    pass


STALE_CLAIM_AFTER = timedelta(minutes=15)


def enqueue_invitations(delivery_ids):
    failed = 0
    for delivery_id in delivery_ids:
        try:
            deliver_invitation.apply_async(args=[delivery_id])
        except Exception:
            db.session.rollback()
            delivery = InvitationDelivery.query.filter_by(id=delivery_id).with_for_update().first()
            if delivery is not None and delivery.status == 'pending':
                delivery.status = 'failed'
                delivery.failure_code = 'queue_failed'
                db.session.commit()
            failed += 1
    return failed


def queue_invitation(delivery, allow_resend=False):
    if delivery.status == 'sent' and not allow_resend:
        return False
    if delivery.status == 'sending' and not _claim_is_stale(delivery):
        return False
    delivery.status = 'pending'
    delivery.failure_code = None
    delivery.claim_token = None
    delivery.claimed_at = None
    db.session.commit()
    return enqueue_invitations([delivery.id]) == 0


def invitation_can_retry(delivery):
    return delivery.status == 'failed' or (
        delivery.status == 'sending' and _claim_is_stale(delivery)
    )


@celery.task(
    bind=True,
    name='membership.deliver_invitation',
    max_retries=3,
    default_retry_delay=30,
)
def deliver_invitation(self, delivery_id):
    delivery = InvitationDelivery.query.filter_by(id=delivery_id).with_for_update().first()
    if delivery is None or delivery.status == 'sent':
        return
    if delivery.status == 'sending' and not _claim_is_stale(delivery):
        return
    if delivery.status not in ('pending', 'retrying', 'failed', 'sending'):
        return

    claim_token = uuid.uuid4().hex
    delivery.status = 'sending'
    delivery.attempts += 1
    delivery.failure_code = None
    delivery.claim_token = claim_token
    delivery.claimed_at = datetime.utcnow()
    db.session.commit()

    if settings.DISABLE_EMAIL:
        delivery = InvitationDelivery.query.get(delivery_id)
        delivery.status = 'failed'
        delivery.failure_code = 'email_disabled'
        delivery.claim_token = None
        delivery.claimed_at = None
        db.session.commit()
        return

    try:
        annotator = delivery.annotator
        link = settings.BASE_URL.rstrip('/') + '/login/' + annotator.secret + '/'
        raw_body = settings.EMAIL_BODY.format(name=annotator.name, link=link)
        body = '\n\n'.join(utils.get_paragraphs(raw_body))
        _send_email(annotator.email, settings.EMAIL_SUBJECT, body)
    except Exception:
        db.session.rollback()
        delivery = InvitationDelivery.query.get(delivery_id)
        should_retry = self.request.retries < self.max_retries
        delivery.status = 'retrying' if should_retry else 'failed'
        delivery.failure_code = 'delivery_failed'
        delivery.claim_token = None
        delivery.claimed_at = None
        db.session.commit()
        if should_retry:
            raise self.retry(exc=InvitationSendError('delivery_failed'))
        return

    delivery = InvitationDelivery.query.filter_by(
        id=delivery_id,
        claim_token=claim_token,
    ).with_for_update().first()
    if delivery is None:
        return
    delivery.status = 'sent'
    delivery.failure_code = None
    delivery.claim_token = None
    delivery.claimed_at = None
    delivery.sent_at = datetime.utcnow()
    db.session.commit()


def _claim_is_stale(delivery):
    return (
        delivery.claimed_at is None
        or delivery.claimed_at < datetime.utcnow() - STALE_CLAIM_AFTER
    )


def _send_email(to_address, subject, body):
    if settings.EMAIL_PROVIDER == 'smtp':
        _send_smtp(to_address, subject, body)
        return
    if settings.EMAIL_PROVIDER == 'sendgrid':
        response = requests.post(
            'https://api.sendgrid.com/v3/mail/send',
            json={
                'personalizations': [{'to': [{'email': to_address}]}],
                'from': {'email': settings.EMAIL_FROM},
                'subject': subject,
                'content': [{'type': 'text/plain', 'value': body}],
            },
            headers={
                'authorization': 'Bearer ' + settings.SENDGRID_API_KEY,
                'content-type': 'application/json',
            },
            timeout=15,
        )
    elif settings.EMAIL_PROVIDER == 'mailgun':
        response = requests.post(
            'https://api.mailgun.net/v3/' + settings.MAILGUN_DOMAIN + '/messages',
            auth=('api', settings.MAILGUN_API_KEY),
            data={
                'from': settings.EMAIL_FROM,
                'to': [to_address],
                'subject': subject,
                'text': body,
            },
            timeout=15,
        )
    else:
        raise InvitationSendError('invalid_provider')
    if response.status_code not in (requests.codes.ok, requests.codes.accepted):
        raise InvitationSendError('provider_rejected')


def _send_smtp(to_address, subject, body):
    if settings.EMAIL_AUTH_MODE == 'tls':
        server = smtplib.SMTP(settings.EMAIL_HOST, settings.EMAIL_PORT, timeout=15)
        server.ehlo()
        server.starttls()
        server.ehlo()
    elif settings.EMAIL_AUTH_MODE == 'ssl':
        server = smtplib.SMTP_SSL(settings.EMAIL_HOST, settings.EMAIL_PORT, timeout=15)
    else:
        raise InvitationSendError('invalid_auth_mode')

    try:
        server.login(settings.EMAIL_USER, settings.EMAIL_PASSWORD)
        message = MIMEMultipart()
        message['From'] = settings.EMAIL_FROM
        message['To'] = to_address
        message['Subject'] = subject
        recipients = [to_address]
        if settings.EMAIL_CC:
            message['Cc'] = ', '.join(settings.EMAIL_CC)
            recipients.extend(settings.EMAIL_CC)
        message.attach(MIMEText(body, 'plain'))
        refused = server.sendmail(settings.EMAIL_FROM, recipients, message.as_string())
        if to_address in refused:
            raise InvitationSendError('recipient_refused')
    finally:
        try:
            server.quit()
        except Exception:
            pass
