#!/bin/env python

# Copyright 2015 Bracket Computing, Inc. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License").
# You may not use this file except in compliance with the License.
# A copy of the License is located at
#
# https://github.com/brkt/brkt-sdk-java/blob/master/LICENSE
#
# or in the "license" file accompanying this file. This file is
# distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR
# CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and
# limitations under the License.

"""
EXPERIMENTAL, USE AT YOUR OWN RISK.

The encrypt ami server moves the encrypt ami process into
a server container.  This allows one to run the server in
a shared location, and communicate via a client.  This
means that the client does not need to maintain the job.
In other words, if the client is interrupted at any time
(close the terminal, etc.) the encrypt process will
continue.  If however the server process is terminated,
any in-flight jobs will fail.  It's likely this limitation
will be fixed at some time.  This is currently very early
stage.
"""

import argparse
import logging
import os
import sys
import time
import threading

import boto
import boto.dynamodb2
import boto.sqs
import boto.sqs.jsonmessage
from boto.dynamodb2.fields import HashKey
from boto.dynamodb2.table import Table
from boto.exception import EC2ResponseError, NoAuthHandlerFound

from brkt_cli import service
from brkt_cli import util
from brkt_cli import encrypt_ami
from brkt_cli import encrypt_ami_server_args


BLOCK_TIMEOUT = 10
VISIBILITY_TIMEOUT = 5


class DynamoLogHandler(logging.Handler):

    def __init__(self, session):
        super(DynamoLogHandler, self).__init__()
        self.session = session

    def emit(self, record):
        msg = self.format(record)
        if not self.session['log']:
            self.session['log'] = msg + '\n'
        else:
            self.session['log'] += msg + '\n'
        self.session.partial_save()
        print msg


def record_error(session, fatal=True):
    session['complete_time'] = int(time.time())
    session['status'] = 'FAIL'
    session.partial_save()


def update_status(session, status, **kwargs):
    complete = status in ('FAIL', 'SUCCESS')
    session['status'] = status
    for k, v in kwargs.items():
        session[k] = v
    if complete:
        session['complete_time'] = int(time.time())
    session.partial_save()


# event: {
#     "verbose": True/False
#     "encrypted_ami_name": <ami_name>
#     "region": <region>,
#     "encryptor_ami": <ami_of_encryptor>,
#     "key_name": <key_name>,
#     "no_validate_ami": True/False,
#     "ami": <ami_to_encrypt>
# }
def encrypt(region, table_name, session_id,
            verbose=False,
            no_validate_ami=False):
    db = boto.dynamodb2.connect_to_region(region)
    encrypt_session = Table(table_name, connection=db)
    session = encrypt_session.get_item(encrypt_id=session_id)
    update_status(session, 'CONFIGURED')

    encrypted_ami_name = session['encrypted_ami_name']
    encryptor_ami = session['encryptor_ami']
    ami = session['ami']
    role = session['role']
    session_id = session['encrypt_id']

    log = logging.getLogger('encrypt_ami.%s' % session_id)
    logHandler = DynamoLogHandler(session)
    log.addHandler(logHandler)

    # Initialize logging.  Log messages are written to stderr and are
    # prefixed with a compact timestamp, so that the user knows how long
    # each operation took.
    if verbose:
        log_level = logging.DEBUG
    else:
        # Boto logs auth errors and 401s at ERROR level by default.
        boto.log.setLevel(logging.FATAL)
        log_level = logging.INFO
    log.setLevel(log_level)
    service.log.setLevel(log_level)

    if not encryptor_ami:
        try:
            encryptor_ami = encrypt_ami.get_encryptor_ami(region)
        except:
            log.exception('Failed to get encryptor AMI.')
            raise

    log.info('Using encryptor AMI %s', encryptor_ami)
    session['encryptor_ami'] = encryptor_ami
    session.partial_save()

    # session_id = util.make_nonce()
    default_tags = encrypt_ami.get_default_tags(session_id, encryptor_ami)

    try:
        # Connect to AWS.
        aws_svc = service.AWSService(
            session_id, encryptor_ami, default_tags=default_tags)
        if role:
            aws_svc.connect_as(role, region, session_id)
        else:
            role = os.environ.get('AWS_ACCOUNT_ID')
            aws_svc.connect(region)
        log.info('Connected to AWS as %s', role)
    except NoAuthHandlerFound:
        msg = (
            'Unable to connect to AWS.  Are your AWS_ACCESS_KEY_ID and '
            'AWS_SECRET_ACCESS_KEY environment variables set?'
        )
        if verbose:
            log.exception(msg)
        else:
            log.error(msg)
        raise

    try:
        if not no_validate_ami:
            error = aws_svc.validate_guest_ami(ami)
            if error:
                log.error(error)
                raise util.BracketError(error)

            error = aws_svc.validate_encryptor_ami(encryptor_ami)
            if error:
                log.error(error)
                raise util.BracketError(error)

        log.info('Starting encryptor session %s', aws_svc.session_id)
        update_status(session, 'ENCRYPTING')

        encrypted_image_id = encrypt_ami.encrypt(
            aws_svc=aws_svc,
            enc_svc_cls=service.EncryptorService,
            image_id=ami,
            encryptor_ami=encryptor_ami,
            encrypted_ami_name=encrypted_ami_name
        )

        update_status(session, 'SUCCESS', encrypted_ami=encrypted_image_id)
        # Print the AMI ID to stdout, in case the caller wants to process
        # the output.  Log messages go to stderr.
        print(encrypted_image_id)
        return {'encrypted_ami': encrypted_image_id}
    except EC2ResponseError as e:
        if e.error_code == 'AuthFailure':
            msg = 'Check your AWS login credentials and permissions'
            if verbose:
                log.exception(msg)
            else:
                log.error(msg + ': ' + e.error_message)
        elif e.error_code == 'InvalidKeyPair.NotFound':
            if verbose:
                log.exception(e.error_message)
            else:
                log.error(e.error_message)
        elif e.error_code == 'UnauthorizedOperation':
            if verbose:
                log.exception(e.error_message)
            else:
                log.error(e.error_message)
            log.error(
                'Unauthorized operation.  Check the IAM policy for your '
                'AWS account.'
            )
        update_status(session, 'FAIL')
        raise
    except util.BracketError as e:
        if verbose:
            log.exception(e.message)
        else:
            log.error(e.message)
        update_status(session, 'FAIL')
        raise


def create_session(db_conn, table_name, job):
    try:
        table = Table.create(
            table_name,
            schema=[HashKey('encrypt_id')],
            connection=db_conn)
    except:
        table = Table(
            table_name,
            connection=db_conn)
    data = {
        'encrypt_id': job['encrypt_id'],
        'region': job['region'],
        'role': job['role'],
        'encryptor_ami': job['encryptor_ami'],
        'encrypted_ami_name': job['encrypted_ami_name'],
        'ami': job['ami'],
        'status': 'INIT',
        'logs': '',
        'ttl': 3600,
        'start_time': int(time.time()),
        'complete_time': 0,
        'encrypted_ami': None
    }

    @service.retry_boto(r'Requested resource not found')
    def _retry_put(data):
        table.put_item(data=data)

    @service.retry_boto(r'Requested resource not found')
    def _retry_get(job):
        item = (
            table.get_item(encrypt_id=job['encrypt_id']))
        return item

    _retry_put(data)
    item = _retry_get(job)
    return item


def main():
    parser = argparse.ArgumentParser()
    encrypt_ami_server_args.setup_encrypt_ami_server_args(parser)

    argv = sys.argv[1:]
    values = parser.parse_args(argv)
    region = values.region

    logging.basicConfig(format='%(asctime)s %(message)s', datefmt='%H:%M:%S')
    log = logging.getLogger('encrypt_ami')

    if values.verbose:
        log.setLevel(logging.DEBUG)
    else:
        log.setLevel(logging.INFO)

    sqs = boto.sqs.connect_to_region(region)
    db = boto.dynamodb2.connect_to_region(region)
    semaphore = threading.Semaphore(values.jobs)

    queue = sqs.lookup(values.queue_name)
    if not queue:
        queue = sqs.create_queue(values.queue_name)
    queue.set_message_class(boto.sqs.jsonmessage.JSONMessage)
    queue.set_attribute('VisibilityTimeout', VISIBILITY_TIMEOUT)

    def encrypt_worker(session, message):
        try:
            log.info('starting new encryption job %s', session['encrypt_id'])
            out = encrypt(
                session['region'], values.table_name, session['encrypt_id'],
                verbose=values.verbose)
            log.info(
                'finished encryption job %s ami %s',
                session['encrypt_id'], out['encrypted_ami'])
        finally:
            semaphore.release()

    try:
        while True:
            semaphore.acquire()
            job = None
            try:
                job = queue.read(wait_time_seconds=BLOCK_TIMEOUT)
            except boto.exception.SQSError:
                log.exception('Error reading from queue')
            if not job:
                semaphore.release()
                log.debug('No encrypt job available')
                continue
            session = create_session(db, values.table_name, job)
            t = threading.Thread(target=encrypt_worker, args=[session, job])
            t.daemon = True
            t.start()
            # At this point we hand off to encrypt which takes an indeterminate
            # amount of time, therefore we delete the message from the queue.
            # If there is a failure, we will not just automatically retry, the
            # user needs to explicitly create a new encrypt job.
            queue.delete_message(job)
    except KeyboardInterrupt:
        pass

if __name__ == '__main__':
    main()
