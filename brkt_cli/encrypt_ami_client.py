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
import logging
import sys
import uuid

import requests

from brkt_cli import encrypt_ami_args
from brkt_cli import encrypt_ami_client_args

# Hard-coded "dummy" customer ID used when client and server
# are local.  Brkt auth credentials would replace this.
LOCAL_CUST_ID = 'a0c5eec4-72fc-494f-a3e2-6aaa32bf70a4'


def encrypt(values):
    job = {
        'encrypt_id': uuid.uuid4().hex,
        'region': values.region,
        'ami': values.ami,
        'encryptor_ami': values.encryptor_ami,
        'encrypted_ami_name': values.encrypted_ami_name,
        'role': None
    }
    resp = requests.post(
        '%s/encrypt/%s' % (values.server_url, LOCAL_CUST_ID),
        json=job,
        verify=False)
    print resp.content


def poll(values):
    resp = requests.get(
        '%s/encrypt/%s/%s' % (
            values.server_url, LOCAL_CUST_ID, values.encrypt_id),
        verify=False)
    print resp.content


def jobs(values):
    resp = requests.get(
        '%s/encrypt/%s' % (
            values.server_url, LOCAL_CUST_ID),
        verify=False)
    print resp.content


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

    jobs_parser = subparsers.add_parser('jobs')
    jobs_parser.set_defaults(func=jobs)

    argv = sys.argv[1:]
    values = parser.parse_args(argv)
    values.func(values)

if __name__ == '__main__':
    main()
