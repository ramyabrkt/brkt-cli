import argparse
import collections
import os

import boto.iam

Role = collections.namedtuple(
    'Policy', ['name', 'policy_doc', 'assume_role_doc'])

ROLES = {
    'encryptor': Role(
        'Encryptor',
        'iam_encryptor_policy.json',
        'assume_role_policy.json')
}

BRKT_ACCOUNT_IDS = {
    'jenkins+dev': '423624396392'
}


def setup_iam_args(parser):
    parser.add_argument(
        '--brkt-assume-role',
        choices=BRKT_ACCOUNT_IDS.keys(),
        help='Allow Bracket to assume this role (required for '
             'off-line image encryption)')
    parser.add_argument(
        '--region',
        metavar='NAME',
        help='AWS region (e.g. us-west-2)',
        dest='region',
        required=True
    )
    parser.add_argument(
        'role',
        metavar='ROLE',
        choices=ROLES.keys())


def setup_iam(args):
    role = ROLES[args.role]
    policy_path = os.path.join(
        os.path.dirname(__file__), 'assets', role.policy_doc)
    assume_role_path = os.path.join(
        os.path.dirname(__file__), 'assets', role.assume_role_doc)
    policy_doc = open(policy_path).read()
    assume_role_doc = open(assume_role_path).read()
    assume_role_doc %= {'account_id': BRKT_ACCOUNT_IDS[args.brkt_assume_role]}
    conn = boto.iam.connect_to_region(args.region)
    conn.create_role(role.name, assume_role_doc)
    conn.put_role_policy(role.name, role.name, policy_doc)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    setup_iam_args(parser)
    args = parser.parse_args()
    setup_iam(args)
