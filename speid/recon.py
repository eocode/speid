import json
import os
import re
from typing.io import TextIO

import boto3
from clabe import BANKS
from sentry_sdk import capture_exception

from speid import db
from speid.helpers import callback_helper
from speid.models import Event, Transaction
from speid.tables.types import Estado, State

BUCKET_NAME = os.environ['RECON_BUCKET_S3']
FILEPATH = '/tmp/report.txt'
KEY = 'reports/report.txt'
STP_PREFIJO = os.environ['STP_PREFIJO']


def serialize(string: str) -> dict:
    double_quote = string.replace("'", '"')
    data = json.loads(double_quote)
    for key, value in data.items():
        if value == 'None':
            if key == 'rfc_curp_beneficiario':
                data[key] = ''
            else:
                data[key] = None
    return data


def stp_to_spei_bank_code(stp_code: str) -> str:
    try:
        return BANKS[stp_code]
    except (ValueError, KeyError, TypeError):
        return None


def get_account_type(account: str) -> str:
    if account:
        account_type = stp_to_spei_bank_code(account[:3])
        if account_type:
            account_type = account_type[:2]
        return account_type
    return None


def reconciliate_received_stp(transactions: list):
    try:
        for trans in transactions:
            # Make sure the transaction does not exist in speid
            transaction = (
                db.session.query(Transaction)
                .filter_by(
                    orden_id=trans['id'], clave_rastreo=trans['rastreo']
                )
                .first()
            )
            beneficiario = trans['cuenta_beneficiario']
            if not transaction and beneficiario[:6] == STP_PREFIJO:
                del trans['estado_orden']
                del trans['institucion']
                del trans['contraparte']

                trans['clave'] = trans.pop('id')
                trans['clave_rastreo'] = trans.pop('rastreo')
                trans['institucion_ordenante'] = trans['cuenta_ordenante'][:3]

                trans['institucion_beneficiaria'] = trans[
                    'cuenta_beneficiario'
                ][:3]

                trans['nombre_ordenante'] = trans.pop('ordenante')

                trans['nombre_beneficiario'] = trans.pop('beneficiario')

                trans['tipo_cuenta_ordenante'] = get_account_type(
                    trans['cuenta_ordenante']
                )

                trans['tipo_cuenta_beneficiario'] = get_account_type(
                    beneficiario
                )

                trans['monto'] = trans['monto'] / 100

                transaction = Transaction.transform(trans)
                db.session.add(transaction)
                db.session.commit()

                event_created = Event(
                    transaction_id=transaction.id,
                    type=State.created,
                    meta=f'Created by recon: {str(trans)}',
                )
                db.session.add(event_created)
                db.session.commit()

                response = callback_helper.send_transaction(transaction)
                if response['status'] == 'failed':
                    transaction = (
                        db.session.query(Transaction)
                        .filter_by(orden_id=trans['clave'])
                        .first()
                    )
                    transaction.estado = Estado.failed
                    event_created = Event(
                        transaction_id=transaction.id,
                        type=State.error,
                        meta=f'{str(response)}',
                    )
                    db.session.add(event_created)
                    db.session.commit()

    except Exception as exc:
        capture_exception(exc)


def get_transactions(file: TextIO) -> int:
    head = file.readline()
    n = int(re.search(r'\((.*?)\)', head).group(1))
    transactions = ''
    for x in range(0, n):
        transactions += file.readline()
    length = len(transactions)
    if length > 0:
        transactions = transactions.split('\n')
        transactions.remove('')
        if transactions:
            transactions = list(map(lambda x: serialize(x), transactions))
    file.readline()
    return transactions


def download_report():
    s3 = boto3.client(
        's3',
        region_name='us-east-1',
        aws_access_key_id=os.environ['RECON_AWS_ACCESS_KEY_ID'],
        aws_secret_access_key=os.environ['RECON_AWS_SECRET_ACCESS_KEY'],
    )
    body = (
        s3.get_object(
            Bucket='aws-glue-recon.cuenca.io', Key='reports/report.txt'
        )['Body']
        .read()
        .decode('utf-8')
    )

    with open(FILEPATH, 'w') as f:
        f.write(body)


def recon_transactions():
    with open(FILEPATH) as f:
        # STP received successfully
        transactions = get_transactions(f)
        reconciliate_received_stp(transactions)

        # STP sent successfully
        transactions = get_transactions(f)

        # STP others
        transactions = get_transactions(f)

        # SPEID submitted
        transactions = get_transactions(f)

        # SPEID success
        transactions = get_transactions(f)

        # SPEID others
        transactions = get_transactions(f)

        # CUENCA created
        transactions = get_transactions(f)

        # CUENCA submitted
        transactions = get_transactions(f)

        # CUENCA succeeded
        transactions = get_transactions(f)

        # CUENCA others
        transactions = get_transactions(f)

        # STP/CUENCA
        transactions = get_transactions(f)

        # STP/SPEID same status
        transactions = get_transactions(f)

        # STP/SPEID different status
        transactions = get_transactions(f)

        # SPEID/CUENCA submitted
        transactions = get_transactions(f)


def reconciliate():
    download_report()
    recon_transactions()