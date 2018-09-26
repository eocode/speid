from speid import db
from speid.models import Transaction, Event
from speid.models.helpers import snake_to_camel
from speid.rabbit.base import ConfirmModeClient, NEW_ORDER_QUEUE
from .celery_app import app
from .celery_app import stpmex


@app.task
def send_order(order_dict):
    # Save transaction
    transaction = Transaction(order_dict)
    db.session.add(transaction)
    db.session.commit()
    event_created = Event(
        transaction_id=transaction.id,
        type='CREATE',
        meta=str(order_dict)
    )

    # Send order to STP
    order_dict = {snake_to_camel(k): v for k, v in order_dict.items()}
    order = stpmex.Orden(**order_dict)
    res = order.registra()

    event_complete = Event(
        transaction_id=transaction.id,
        type='COMPLETE',
        meta=str(res)
    )
    if res.id > 0:
        transaction.orden_id = res.id
    else:
        event_complete.type = 'ERROR'
        client = ConfirmModeClient(NEW_ORDER_QUEUE)
        client.call(order_dict)

    db.session.add(event_created)
    db.session.add(event_complete)
    db.session.commit()