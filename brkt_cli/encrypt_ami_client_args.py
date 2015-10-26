from brkt_cli import VERSION


def setup_client_args(parser):
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
        '-q',
        '--queue',
        metavar='QUEUE_NAME',
        dest='queue_name',
        help='Specify the name of the SQS job queue',
        default='brkt_encryptor_queue'
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
        '--region',
        metavar='NAME',
        help='AWS region (e.g. us-west-2)',
        dest='region',
        required=True
    )


def setup_poll_args(parser):
    parser.add_argument(
        'encrypt_id',
        metavar='ENCRYPT_ID',
        help='Specify the encrypt_id of the encrypt AMI session'
    )
