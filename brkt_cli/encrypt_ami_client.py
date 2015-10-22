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

import argparse
import json
import logging
import sys
import time
import uuid

import boto.dynamodb2
import boto.dynamodb2.exceptions
import boto.sqs
import boto.sqs.jsonmessage
from boto.dynamodb2.table import Table

from brkt_cli import encrypt_ami_args
from brkt_cli import encrypt_ami_client_args


def encrypt(values):
    sqs = boto.sqs.connect_to_region(values.region)

    queue = sqs.lookup(values.queue_name)
    if not queue:
        queue = sqs.create_queue(values.queue_name)
    queue.set_message_class(boto.sqs.jsonmessage.JSONMessage)
    queue.set_attribute('VisibilityTimeout', 14400)

    job = {
        'encrypt_id': uuid.uuid4().hex,
        'region': values.region,
        'ami': values.ami,
        'encryptor_ami': values.encryptor_ami,
        'encrypted_ami_name': values.encrypted_ami_name,
        'role': None
    }
    queue.write(boto.sqs.jsonmessage.JSONMessage(body=job))
    print json.dumps(job, indent=4)


def poll(values):
    db_conn = boto.dynamodb2.connect_to_region(values.region)

    job = Table(values.table_name, connection=db_conn)

    try:
        job = job.get_item(encrypt_id=values.encrypt_id)
    except boto.dynamodb2.exceptions.ItemNotFound:
        print('job not found (not ready yet), try again later')
        sys.exit(1)
    print json.dumps({
            'encrypt_id': job['encrypt_id'],
            'region': job['region'],
            'ami': job['ami'],
            'encryptor_ami': job['encryptor_ami'],
            'encrypted_ami_name': job['encrypted_ami_name'],
            'role': job['role'],
            'status': job['status'],
            'start_time': time.ctime(job['start_time']),
            'complete_time': (
                time.ctime(job['complete_time'])
                if job['complete_time'] else None),
            'log': job['log']
        }, indent=4)


def main():
    logging.basicConfig(format='%(asctime)s %(message)s', datefmt='%H:%M:%S')

    parser = argparse.ArgumentParser()
    encrypt_ami_client_args.setup_client_args(parser)
    subparsers = parser.add_subparsers()
    encrypt_parser = subparsers.add_parser('encrypt_ami')
    encrypt_ami_args.setup_encrypt_ami_args(encrypt_parser)
    encrypt_parser.set_defaults(func=encrypt)

    poll_parser = subparsers.add_parser('poll')
    encrypt_ami_client_args.setup_poll_args(poll_parser)
    poll_parser.set_defaults(func=poll)

    argv = sys.argv[1:]
    values = parser.parse_args(argv)
    values.func(values)

if __name__ == '__main__':
    main()
