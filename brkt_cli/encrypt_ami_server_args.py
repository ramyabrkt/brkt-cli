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

from brkt_cli import VERSION


def setup_encrypt_ami_server_args(parser):
    parser.add_argument(
        'region',
        metavar='REGION',
        help='AWS region (e.g. us-west-2)'
    )
    parser.add_argument(
        '-v',
        '--verbose',
        dest='verbose',
        action='store_true',
        help='Print status information to the console'
    )
    parser.add_argument(
        '--version',
        action='version',
        version='brkt-cli version %s' % VERSION
    )
    parser.add_argument(
        '-t',
        '--table',
        metavar='TABLE_NAME',
        dest='table_name',
        help='Specify the name of the Dynamo DB table that tracks state',
        default='brkt_encrypt_ami_session'
    )
    parser.add_argument(
        '-j',
        '--jobs',
        metavar='MAX_JOBS',
        type=int,
        help='Max number of parallel encryption jobs',
        default=4
    )
    parser.add_argument(
        '-p',
        '--port',
        metavar='HTTP_PORT',
        type=int,
        help='HTTP listening port',
        default=8000
    )
    parser.add_argument(
        '-c',
        '--cert',
        metavar='SERVER_CERT',
        help='Server cert file'
    )
    parser.add_argument(
        '-k',
        '--key',
        metavar='SERVER_KEY',
        help='Server key file'
    )
