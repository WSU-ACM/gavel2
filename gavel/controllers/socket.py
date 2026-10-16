from gavel import app
from gavel import celery
from gavel import socketio
from flask_socketio import emit
from gavel.constants import *
from gavel.models import *
from gavel.schemas import ItemSchema, AnnotatorSchema, FlagSchema, SettingSchema
import gavel.settings as settings
import gavel.utils as utils
from sqlalchemy import event
from sqlalchemy import (or_, not_)
from sqlalchemy.orm import object_session
from flask import has_request_context, json, request
import asyncio

loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

item_schema = ItemSchema()
annotator_schema = AnnotatorSchema()
flag_schema = FlagSchema()
setting_schema = SettingSchema()


def skip_model_event(target):
  if not has_request_context():
    return True
  auth = request.authorization
  if not auth or not utils.check_auth(auth.username, auth.password):
    return True
  session = object_session(target)
  return session is not None and session.info.get('suppress_socket_events')

def standardize(target):
  try:
    name = target.__tablename__
    if str(name) == 'annotator':
      return {
        'type': name,
        'target': json.dumps(injectAnnotator(target, annotator_schema.dump(target)))
      }
    elif str(name) == 'flag':
      return {
        'type': name,
        'target': json.dumps(injectFlag(target, flag_schema.dump(target)))
      }
    elif str(name) == 'item':
      return {
        'type': name,
        'target': json.dumps(injectItem(target, item_schema.dump(target)))
      }
    elif str(name) == 'setting':
      settings = Setting.query.all()
      return {
        'type': name,
        'target': json.dumps([setting_schema.dump(it) for it in settings])
      }
    else:
      # Legacy to_dict() due to schema ambiguity
      return {
        'type': name,
        'target': json.dumps(target.to_dict())
      }
  except Exception as e:
    print(str(e))
    return {
      'type': "ERROR",
      'target': json.dumps({'error': 'true'})
    }

def injectAnnotator(target, target_dumped):
  count = Decision.query.filter(Decision.annotator_id == target.id).count()
  target_dumped.update({
    'active': target.effectively_active,
    'roster_active': target.roster_active,
    'votes': count
  })

  return target_dumped

def injectFlag(target, target_dumped):
  target_dumped.update({
    'item_name': target.item.name,
    'item_location': target.item.location,
    'annotator_name': target.annotator.name
  })
  return target_dumped

@celery.task
def injectItem(target, target_dumped):
  assigned = Annotator.query.filter(Annotator.next == target).all()
  viewed_ids = {i.id for i in target.viewed}
  if viewed_ids:
    skipped = Annotator.query.filter(
      Annotator.ignore.contains(target) & ~Annotator.id.in_(viewed_ids)
    ).count()
  else:
    skipped = Annotator.query.filter(Annotator.ignore.contains(target)).count()

  viewed = len(target.viewed)

  target_dumped.update({
    'active': target.effectively_active,
    'roster_active': target.roster_active,
    'viewed': viewed,
    'votes': Decision.query.filter(or_(Decision.winner_id == target.id, Decision.loser_id == target.id)).distinct(Decision.id).count(),
    'skipped': skipped
  })
  return target_dumped

@socketio.on('connect', namespace='/admin')
def admin_socket_connect():
  auth = request.authorization
  if not auth or not utils.check_auth(auth.username, auth.password):
    return False


@socketio.on('user.connected', namespace='/admin')
def test_connect(data):
  emit(CONNECT, data, namespace='/admin')

@socketio.on('annotator.updated.confirmed', namespace='/admin')
@utils.requires_auth
def runRelatedItemUpdates(data):
  triggerRelatedItemUpdates.apply_async(args=[data])

@celery.task(name='socket.triggerRelatedItemUpdates')
def triggerRelatedItemUpdates(data):
  try:
    ignore_ids = {i['id'] for i in data['ignore']}
    items = Item.query.filter(Item.id.in_(ignore_ids))
    for i in items:
      socketio.emit(ITEM_UPDATED, {'type': "item", 'target': json.dumps(injectItem.delay(i, item_schema.dump(i)))}, namespace='/admin')
  except Exception as e:
    return

@event.listens_for(Annotator, 'after_insert')
def annotator_listen_insert(mapper, connection, target):
  if skip_model_event(target):
    return
  socketio.emit(ANNOTATOR_INSERTED, standardize(target), namespace='/admin')

@event.listens_for(Annotator, 'after_update')
def annotator_listen_modify(mapper, connection, target):
  if skip_model_event(target):
    return
  socketio.emit(ANNOTATOR_UPDATED, standardize(target), namespace='/admin')

@event.listens_for(Annotator, 'after_delete')
def annotator_listen_delete(mapper, connection, target):
  if skip_model_event(target):
    return
  print(str(target), str(mapper))
  socketio.emit(ANNOTATOR_DELETED, {"target": json.dumps(annotator_schema.dump(target))}, namespace='/admin')

@event.listens_for(Item, 'after_insert')
def item_listen_insert(mapper, connection, target):
  if skip_model_event(target):
    return
  socketio.emit(ITEM_INSERTED, standardize(target), namespace='/admin')

@event.listens_for(Item, 'after_update')
def item_listen_modify(mapper, connection, target):
  if skip_model_event(target):
    return
  socketio.emit(ITEM_UPDATED, standardize(target), namespace='/admin')

@event.listens_for(Item, 'after_delete')
def item_listen_delete(mapper, connection, target):
  if skip_model_event(target):
    return
  print(str(target), str(mapper))
  socketio.emit(ITEM_DELETED, {"target": item_schema.dump(target)}, namespace='/admin')

@event.listens_for(Flag, 'after_insert')
def flag_listen_insert(mapper, connection, target):
  if skip_model_event(target):
    return
  socketio.emit(FLAG_INSERTED, standardize(target), namespace='/admin')

@event.listens_for(Flag, 'after_update')
def flag_listen_update(mapper, connection, target):
  if skip_model_event(target):
    return
  socketio.emit(FLAG_UPDATED, standardize(target), namespace='/admin')

@event.listens_for(Flag, 'after_delete')
def flag_listen_delete(mapper, connection, target):
  if skip_model_event(target):
    return
  print(str(target), str(mapper))
  socketio.emit(FLAG_DELETED, {"target": json.dumps(flag_schema.dump(target))}, namespace='/admin')

@event.listens_for(Setting, 'after_insert')
def setting_listen_insert(mapper, connection, target):
  if skip_model_event(target):
    return
  socketio.emit(SETTING_INSERTED, standardize(target), namespace='/admin')

@event.listens_for(Setting, 'after_update')
def setting_listen_update(mapper, connection, target):
  if skip_model_event(target):
    return
  socketio.emit(SETTING_UPDATED, standardize(target), namespace='/admin')
