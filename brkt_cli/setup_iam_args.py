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

import collections

Role = collections.namedtuple(
    'Policy', ['policy_doc', 'assume_role_doc'])

ROLES = {
    'Encryptor': Role(
        'iam_encryptor_policy.json',
        'assume_role_policy.json')
}


def setup_iam_args(parser):
    parser.add_argument(
        '--brkt-account-id',
        help='Bracket AWS account ID to trust (automatically fetched/set '
             'in the future)')
    parser.add_argument(
        '--region',
        metavar='NAME',
        help='AWS region (e.g. us-west-2)',
        dest='region',
        required=True
    )
    parser.add_argument(
        'role',
        choices=ROLES.keys(),
        help='The name of the AWS role to add'
    )
