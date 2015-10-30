import argparse
import os

import boto.exception
import boto.iam

from brkt_cli import setup_iam_args


def setup_iam(values):
    role = setup_iam_args.ROLES[values.role]
    policy_path = os.path.join(
        os.path.dirname(__file__), 'assets', role.policy_doc)
    assume_role_path = os.path.join(
        os.path.dirname(__file__), 'assets', role.assume_role_doc)
    policy_doc = open(policy_path).read()
    assume_role_doc = open(assume_role_path).read()
    assume_role_doc %= {'account_id': values.brkt_account_id}
    conn = boto.iam.connect_to_region(values.region)
    try:
        resp = conn.get_role(values.role)
        role_result = resp['get_role_response']['get_role_result']['role']
    except boto.exception.BotoServerError as e:
        if e.code == 'NoSuchEntity':
            resp = conn.create_role(values.role, assume_role_doc)
            role_result = \
                resp['create_role_response']['create_role_result']['role']
        else:
            raise
    conn.put_role_policy(values.role, values.role, policy_doc)
    print 'policy arn: %s' % role_result['arn']


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    setup_iam_args.setup_iam_args(parser)
    values = parser.parse_args()
    setup_iam(values)
