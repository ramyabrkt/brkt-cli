# Copyright 2015 Bracket Computing, Inc. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License").
# You may not use this file except in compliance with the License.
# A copy of the License is located at
#
# https://github.com/brkt/brkt-cli/blob/master/LICENSE
#
# or in the "license" file accompanying this file. This file is
# distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR
# CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and
# limitations under the License.
import json
import logging
import re
import tempfile
import urllib2

import boto
from boto.exception import EC2ResponseError, NoAuthHandlerFound

import brkt_cli
from brkt_cli import encryptor_service, util
from brkt_cli.aws import (
    aws_service,
    diag,
    diag_args,
    encrypt_ami,
    encrypt_ami_args,
    share_logs,
    share_logs_args,
    update_encrypted_ami_args
)
from brkt_cli.aws.encrypt_ami import (
    TAG_ENCRYPTOR,
    TAG_ENCRYPTOR_AMI,
    TAG_ENCRYPTOR_SESSION_ID)
from brkt_cli.aws.update_ami import update_ami
from brkt_cli.instance_config import (
    INSTANCE_CREATOR_MODE,
    INSTANCE_UPDATER_MODE
)
from brkt_cli.instance_config_args import (
    instance_config_from_values,
    setup_instance_config_args
)
from brkt_cli.subcommand import Subcommand
from brkt_cli.util import BracketError
from brkt_cli.validation import ValidationError

log = logging.getLogger(__name__)


ENCRYPTOR_AMIS_URL = \
    "https://solo-brkt-prod-net.s3.amazonaws.com/hvm_amis.json"


def _handle_aws_errors(func):
    """Provides common error handling to subcommands that interact with AWS
    APIs.
    """
    def _do_handle_aws_errors(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except NoAuthHandlerFound:
            msg = (
                'Unable to connect to AWS.  Are your AWS_ACCESS_KEY_ID and '
                'AWS_SECRET_ACCESS_KEY environment variables set?'
            )
            log.debug('', exc_info=1)
            log.error(msg)
        except EC2ResponseError as e:
            if e.error_code == 'AuthFailure':
                msg = 'Check your AWS login credentials and permissions'
                log.debug('', exc_info=1)
                log.error(msg + ': ' + e.error_message)
            elif e.error_code in (
                    'InvalidKeyPair.NotFound',
                    'InvalidSubnetID.NotFound',
                    'InvalidGroup.NotFound'
            ):
                log.debug('', exc_info=1)
                log.error(e.error_message)
            elif e.error_code == 'UnauthorizedOperation':
                log.debug('', exc_info=1)
                log.error(e.error_message)
                log.error(
                    'Unauthorized operation.  Check the IAM policy for your '
                    'AWS account.'
                )
            else:
                raise
        return 1
    return _do_handle_aws_errors


@_handle_aws_errors
def run_diag(values):
    nonce = util.make_nonce()

    aws_svc = aws_service.AWSService(
        nonce,
        retry_timeout=values.retry_timeout,
        retry_initial_sleep_seconds=values.retry_initial_sleep_seconds
    )
    log.debug(
        'Retry timeout=%.02f, initial sleep seconds=%.02f',
        aws_svc.retry_timeout, aws_svc.retry_initial_sleep_seconds)

    if values.snapshot_id and values.instance_id:
        raise ValidationError("Only one of --instance-id or --snapshot-id "
                              "may be specified")

    if not values.snapshot_id and not values.instance_id:
        raise ValidationError("--instance-id or --snapshot-id "
                              "must be specified")

    if values.validate:
        # Validate the region before connecting.
        region_names = [r.name for r in aws_svc.get_regions()]
        if values.region not in region_names:
            raise ValidationError(
                'Invalid region %s.  Supported regions: %s.' %
                (values.region, ', '.join(region_names)))

    aws_svc.connect(values.region, key_name=values.key_name)
    default_tags = {}
    default_tags.update(brkt_cli.parse_tags(values.tags))
    aws_svc.default_tags = default_tags

    if values.validate:
        if values.key_name:
            aws_svc.get_key_pair(values.key_name)
        _validate_subnet_and_security_groups(
            aws_svc, values.subnet_id, values.security_group_ids)
    else:
        log.info('Skipping validation.')

    diag.diag(
        aws_svc,
        instance_id=values.instance_id,
        snapshot_id=values.snapshot_id,
        ssh_keypair=values.key_name
    )
    return 0


@_handle_aws_errors
def run_share_logs(values):
    nonce = util.make_nonce()

    aws_svc = aws_service.AWSService(
        nonce,
        retry_timeout=values.retry_timeout,
        retry_initial_sleep_seconds=values.retry_initial_sleep_seconds
    )
    log.debug(
        'Retry timeout=%.02f, initial sleep seconds=%.02f',
        aws_svc.retry_timeout, aws_svc.retry_initial_sleep_seconds)

    if values.snapshot_id and values.instance_id:
        raise ValidationError("Only one of --instance-id or --snapshot-id "
                              "may be specified")

    if not values.snapshot_id and not values.instance_id:
        raise ValidationError("--instance-id or --snapshot-id "
                              "must be specified")

    if values.validate:
        # Validate the region before connecting.
        region_names = [r.name for r in aws_svc.get_regions()]
        if values.region not in region_names:
            raise ValidationError(
                'Invalid region %s.  Supported regions: %s.' %
                (values.region, ', '.join(region_names)))

    aws_svc.connect(values.region)

    share_logs.share(
        aws_svc,
        instance_id=values.instance_id,
        snapshot_id=values.snapshot_id,
        bracket_aws_account=values.bracket_aws_account
    )
    return 0


@_handle_aws_errors
def run_encrypt(values, config, verbose=False):
    session_id = util.make_nonce()

    aws_svc = aws_service.AWSService(
        session_id,
        retry_timeout=values.retry_timeout,
        retry_initial_sleep_seconds=values.retry_initial_sleep_seconds
    )
    log.debug(
        'Retry timeout=%.02f, initial sleep seconds=%.02f',
        aws_svc.retry_timeout, aws_svc.retry_initial_sleep_seconds)

    brkt_env = (
        brkt_cli.brkt_env_from_values(values) or
        brkt_cli.get_prod_brkt_env()
    )

    if values is not None and values.crypto:
        crypto_policy = values.crypto
    else:
        crypto_policy = 'gcm'

    if values.validate:
        # Validate the region before connecting.
        _validate_region(aws_svc, values.region)

        if values.token:
            brkt_cli.check_jwt_auth(brkt_env, values.token)

    aws_svc.connect(values.region, key_name=values.key_name)

    if values.validate:
        guest_image = _validate_guest_ami(aws_svc, values.ami)
    else:
        guest_image = aws_svc.get_image(values.ami)

    encryptor_ami = values.encryptor_ami or _get_encryptor_ami(values.region)
    default_tags = encrypt_ami.get_default_tags(session_id, encryptor_ami)
    default_tags.update(brkt_cli.parse_tags(values.tags))
    aws_svc.default_tags = default_tags

    if values.validate:
        _validate(aws_svc, values, encryptor_ami)
        brkt_cli.validate_ntp_servers(values.ntp_servers)

    instance_config = instance_config_from_values(
        values, mode=INSTANCE_CREATOR_MODE, cli_config=config)
    if verbose:
        with tempfile.NamedTemporaryFile(
            prefix='user-data-',
            delete=False
        ) as f:
            log.debug('Writing instance user data to %s', f.name)
            f.write(instance_config.make_userdata())

    encrypted_image_id = encrypt_ami.encrypt(
        aws_svc=aws_svc,
        enc_svc_cls=encryptor_service.EncryptorService,
        image_id=guest_image.id,
        encryptor_ami=encryptor_ami,
        crypto_policy=crypto_policy,
        encrypted_ami_name=values.encrypted_ami_name,
        subnet_id=values.subnet_id,
        security_group_ids=values.security_group_ids,
        guest_instance_type=values.guest_instance_type,
        instance_config=instance_config,
        status_port=values.status_port,
        save_encryptor_logs=values.save_encryptor_logs,
        terminate_encryptor_on_failure=(
            values.terminate_encryptor_on_failure)
    )
    # Print the AMI ID to stdout, in case the caller wants to process
    # the output.  Log messages go to stderr.
    print(encrypted_image_id)
    return 0


@_handle_aws_errors
def run_update(values, config, verbose=False):
    nonce = util.make_nonce()

    aws_svc = aws_service.AWSService(
        nonce,
        retry_timeout=values.retry_timeout,
        retry_initial_sleep_seconds=values.retry_initial_sleep_seconds
    )
    log.debug(
        'Retry timeout=%.02f, initial sleep seconds=%.02f',
        aws_svc.retry_timeout, aws_svc.retry_initial_sleep_seconds)

    brkt_env = (
        brkt_cli.brkt_env_from_values(values) or
        brkt_cli.get_prod_brkt_env()
    )

    if values.validate:
        # Validate the region before connecting.
        _validate_region(aws_svc, values.region)

        if values.token:
            brkt_cli.check_jwt_auth(brkt_env, values.token)

    aws_svc.connect(values.region, key_name=values.key_name)
    encrypted_image = _validate_ami(aws_svc, values.ami)
    encryptor_ami = values.encryptor_ami or _get_encryptor_ami(values.region)
    default_tags = encrypt_ami.get_default_tags(nonce, encryptor_ami)
    default_tags.update(brkt_cli.parse_tags(values.tags))
    aws_svc.default_tags = default_tags

    if values.validate:
        _validate_guest_encrypted_ami(
            aws_svc, encrypted_image.id, encryptor_ami)
        brkt_cli.validate_ntp_servers(values.ntp_servers)
        _validate(aws_svc, values, encryptor_ami)
        _validate_guest_encrypted_ami(
            aws_svc, encrypted_image.id, encryptor_ami)
    else:
        log.info('Skipping AMI validation.')

    mv_image = aws_svc.get_image(encryptor_ami)
    if (encrypted_image.virtualization_type != mv_image.virtualization_type):
        log.error(
            'Virtualization type mismatch.  %s is %s, but encryptor %s is '
            '%s.',
            encrypted_image.id,
            encrypted_image.virtualization_type,
            mv_image.id,
            mv_image.virtualization_type
        )
        return 1

    encrypted_ami_name = values.encrypted_ami_name
    if encrypted_ami_name:
        # Check for name collision.
        filters = {'name': encrypted_ami_name}
        if aws_svc.get_images(filters=filters, owners=['self']):
            raise ValidationError(
                'You already own image named %s' % encrypted_ami_name)
    else:
        encrypted_ami_name = _get_updated_image_name(
            encrypted_image.name, nonce)
        log.debug('Image name: %s', encrypted_ami_name)
        aws_service.validate_image_name(encrypted_ami_name)

    # Initial validation done
    log.info(
        'Updating %s with new metavisor %s',
        encrypted_image.id, encryptor_ami
    )

    instance_config = instance_config_from_values(
        values, mode=INSTANCE_UPDATER_MODE, cli_config=config)
    if verbose:
        with tempfile.NamedTemporaryFile(
            prefix='user-data-',
            delete=False
        ) as f:
            log.debug('Writing instance user data to %s', f.name)
            f.write(instance_config.make_userdata())

    updated_ami_id = update_ami(
        aws_svc, encrypted_image.id, encryptor_ami, encrypted_ami_name,
        subnet_id=values.subnet_id,
        security_group_ids=values.security_group_ids,
        guest_instance_type=values.guest_instance_type,
        updater_instance_type=values.updater_instance_type,
        instance_config=instance_config,
        status_port=values.status_port,
    )
    print(updated_ami_id)
    return 0


class AWSSubcommand(Subcommand):
    def __init__(self):
        self.config = None

    def name(self):
        return 'aws'

    def init_logging(self, verbose):
        # Set boto logging to FATAL, since boto logs auth errors and 401s
        # at ERROR level.
        boto.log.setLevel(logging.FATAL)

    def verbose(self, values):
        return values.aws_verbose

    def register(self, subparsers, parsed_config):
        self.config = parsed_config

        aws_parser = subparsers.add_parser(
            self.name(),
            description='AWS operations',
            help='AWS operations'
        )

        aws_subparsers = aws_parser.add_subparsers(
            dest='aws_subcommand'
        )

        diag_parser = aws_subparsers.add_parser(
            'diag',
            description=(
                'Create instance to diagnose an existing encrypted instance.'
            ),
            help='Diagnose an encrypted instance',
            formatter_class=brkt_cli.SortingHelpFormatter
        )
        diag_args.setup_diag_args(diag_parser)
        diag_parser.set_defaults(aws_subcommand='diag')

        encrypt_ami_parser = aws_subparsers.add_parser(
            'encrypt',
            description='Create an encrypted AMI from an existing AMI.',
            help='Encrypt an AWS image',
            formatter_class=brkt_cli.SortingHelpFormatter
        )
        encrypt_ami_args.setup_encrypt_ami_args(encrypt_ami_parser)
        setup_instance_config_args(encrypt_ami_parser, parsed_config,
                                   mode=INSTANCE_CREATOR_MODE)
        encrypt_ami_parser.set_defaults(aws_subcommand='encrypt')

        share_logs_parser = aws_subparsers.add_parser(
            'share-logs',
            description='Share logs from an existing encrypted instance.',
            help='Share logs',
            formatter_class=brkt_cli.SortingHelpFormatter
        )
        share_logs_args.setup_share_logs_args(share_logs_parser)
        share_logs_parser.set_defaults(aws_subcommand='share-logs')

        update_encrypted_ami_parser = aws_subparsers.add_parser(
            'update',
            description=(
                'Update an encrypted AMI with the latest Metavisor '
                'release.'
            ),
            help='Update an encrypted AWS image',
            formatter_class=brkt_cli.SortingHelpFormatter
        )
        update_encrypted_ami_args.setup_update_encrypted_ami(
            update_encrypted_ami_parser)
        setup_instance_config_args(update_encrypted_ami_parser,
                                   parsed_config,
                                   mode=INSTANCE_UPDATER_MODE)
        update_encrypted_ami_parser.set_defaults(aws_subcommand='update')

    def debug_log_to_temp_file(self, values):
        return values.aws_subcommand in ('encrypt', 'update')

    def run(self, values):
        if values.aws_subcommand == 'encrypt':
            verbose = brkt_cli.is_verbose(values, self)
            return run_encrypt(values, self.config, verbose=verbose)
        if values.aws_subcommand == 'update':
            verbose = brkt_cli.is_verbose(values, self)
            return run_update(values, self.config, verbose=verbose)
        if values.aws_subcommand == 'diag':
            return run_diag(values)
        if values.aws_subcommand == 'share-logs':
            return run_share_logs(values)


class DiagSubcommand(Subcommand):
    def name(self):
        return 'diag'

    def init_logging(self, verbose):
        # Set boto logging to FATAL, since boto logs auth errors and 401s
        # at ERROR level.
        boto.log.setLevel(logging.FATAL)

    def verbose(self, values):
        return values.aws_verbose

    def register(self, subparsers, parsed_config):
        diag_parser = subparsers.add_parser(
            'diag',
            description=(
                'Create instance to diagnose an existing encrypted instance.'
            ),
            formatter_class=brkt_cli.SortingHelpFormatter
        )
        diag_args.setup_diag_args(diag_parser)

    def exposed(self):
        return False

    def run(self, values):
        log.warn(
            'This command syntax has been deprecated.  Please use brkt aws '
            'diag instead.'
        )
        return run_diag(values)


class ShareLogsSubcommand(Subcommand):

    def name(self):
        return 'share-logs'

    def init_logging(self, verbose):
        # Set boto logging to FATAL, since boto logs auth errors and 401s
        # at ERROR level.
        boto.log.setLevel(logging.FATAL)

    def verbose(self, values):
        return values.aws_verbose

    def register(self, subparsers, parsed_config):
        share_logs_parser = subparsers.add_parser(
            'share-logs',
            description='Share logs from an existing encrypted instance.',
            formatter_class=brkt_cli.SortingHelpFormatter
        )
        share_logs_args.setup_share_logs_args(share_logs_parser)

    def exposed(self):
        return False

    def run(self, values):
        log.warn(
            'This command syntax has been deprecated.  Please use '
            'brkt aws share-logs instead.'
        )
        return run_share_logs(values)


class EncryptAMISubcommand(Subcommand):

    def name(self):
        return 'encrypt-ami'

    def init_logging(self, verbose):
        # Set boto logging to FATAL, since boto logs auth errors and 401s
        # at ERROR level.
        boto.log.setLevel(logging.FATAL)

    def verbose(self, values):
        return values.aws_verbose

    def register(self, subparsers, parsed_config):
        self.config = parsed_config
        encrypt_ami_parser = subparsers.add_parser(
            'encrypt-ami',
            description='Create an encrypted AMI from an existing AMI.',
            formatter_class=brkt_cli.SortingHelpFormatter
        )
        encrypt_ami_args.setup_encrypt_ami_args(encrypt_ami_parser)
        setup_instance_config_args(encrypt_ami_parser, parsed_config,
                                   mode=INSTANCE_CREATOR_MODE)

    def debug_log_to_temp_file(self, values):
        return True

    def run(self, values):
        log.warn(
            'This command syntax has been deprecated.  Please use '
            'brkt aws encrypt instead.'
        )
        verbose = brkt_cli.is_verbose(values, self)
        return run_encrypt(values, self.config, verbose=verbose)

    def exposed(self):
        return False


class UpdateAMISubcommand(Subcommand):

    def name(self):
        return 'update-encrypted-ami'

    def init_logging(self, verbose):
        # Set boto logging to FATAL, since boto logs auth errors and 401s
        # at ERROR level.
        boto.log.setLevel(logging.FATAL)

    def verbose(self, values):
        return values.aws_verbose

    def register(self, subparsers, parsed_config):
        self.config = parsed_config
        update_encrypted_ami_parser = subparsers.add_parser(
            'update-encrypted-ami',
            description=(
                'Update an encrypted AMI with the latest Metavisor '
                'release.'
            ),
            formatter_class=brkt_cli.SortingHelpFormatter
        )
        update_encrypted_ami_args.setup_update_encrypted_ami(
            update_encrypted_ami_parser)
        setup_instance_config_args(update_encrypted_ami_parser,
                                   parsed_config,
                                   mode=INSTANCE_UPDATER_MODE)

    def debug_log_to_temp_file(self, values):
        return True

    def exposed(self):
        return False

    def run(self, values):
        log.warn(
            'This command syntax has been deprecated.  Please use brkt aws '
            'update instead.'
        )
        verbose = brkt_cli.is_verbose(values, self)
        return run_update(values, self.config, verbose=verbose)


def get_subcommands():
    return [
        AWSSubcommand(),
        DiagSubcommand(),
        EncryptAMISubcommand(),
        ShareLogsSubcommand(),
        UpdateAMISubcommand()]


def _validate_subnet_and_security_groups(aws_svc,
                                         subnet_id=None,
                                         security_group_ids=None):
    """ Verify that the given subnet and security groups all exist and are
    in the same subnet.

    :return True if all of the ids are valid and in the same VPC
    :raise EC2ResponseError or ValidationError if any of the ids are invalid
    """
    vpc_ids = set()
    if subnet_id:
        # Validate the subnet.
        subnet = aws_svc.get_subnet(subnet_id)
        vpc_ids.add(subnet.vpc_id)

    if security_group_ids:
        # Validate the security groups.
        for id in security_group_ids:
            sg = aws_svc.get_security_group(id, retry=False)
            vpc_ids.add(sg.vpc_id)

    if len(vpc_ids) > 1:
        raise ValidationError(
            'Subnet and security groups must be in the same VPC.')

    if not subnet_id and vpc_ids:
        # Security groups were specified but subnet wasn't.  Make sure that
        # the security groups are in the default VPC.
        (vpc_id,) = vpc_ids
        default_vpc = aws_svc.get_default_vpc()
        log.debug(
            'Default VPC: %s, security group VPC IDs: %s',
            default_vpc,
            vpc_ids
        )

        # Perform the check as long as there's a default VPC.  In
        # EC2-Classic, there is no default VPC and the vpc_id field is null.
        if vpc_id and default_vpc:
            if vpc_id != default_vpc.id:
                raise ValidationError(
                    'Security groups must be in the default VPC when '
                    'a subnet is not specified.'
                )


def _validate_ami(aws_svc, ami_id):
    """
    :return the Image object
    :raise ValidationError if the image doesn't exist
    """
    try:
        image = aws_svc.get_image(ami_id)
    except EC2ResponseError, e:
        if e.error_code.startswith('InvalidAMIID'):
            raise ValidationError(
                'Could not find ' + ami_id + ': ' + e.error_code)
        else:
            raise ValidationError(e.error_message)
    if not image:
        raise ValidationError('Could not find ' + ami_id)
    return image


def _validate_guest_ami(aws_svc, ami_id):
    """ Validate that we are able to encrypt this image.

    :return: the Image object
    :raise: ValidationError if the AMI id is invalid
    """
    image = _validate_ami(aws_svc, ami_id)
    if TAG_ENCRYPTOR in image.tags:
        raise ValidationError('%s is already an encrypted image' % ami_id)

    # Amazon's API only returns 'windows' or nothing.  We're not currently
    # able to detect individual Linux distros.
    if image.platform == 'windows':
        raise ValidationError('Windows is not a supported platform')

    if image.root_device_type != 'ebs':
        raise ValidationError('%s does not use EBS storage.' % ami_id)
    if image.hypervisor != 'xen':
        raise ValidationError(
            '%s uses hypervisor %s.  Only xen is supported' % (
                ami_id, image.hypervisor)
        )
    return image


def _validate_guest_encrypted_ami(aws_svc, ami_id, encryptor_ami_id):
    """ Validate that this image was encrypted by Bracket by checking
        tags.

    :raise: ValidationError if validation fails
    :return: the Image object
    """
    ami = _validate_ami(aws_svc, ami_id)

    # Is this encrypted by Bracket?
    tags = ami.tags
    expected_tags = (TAG_ENCRYPTOR,
                     TAG_ENCRYPTOR_SESSION_ID,
                     TAG_ENCRYPTOR_AMI)
    missing_tags = set(expected_tags) - set(tags.keys())
    if missing_tags:
        raise ValidationError(
            '%s is missing tags: %s' % (ami.id, ', '.join(missing_tags)))

    # See if this image was already encrypted by the given encryptor AMI.
    original_encryptor_id = tags.get(TAG_ENCRYPTOR_AMI)
    if original_encryptor_id == encryptor_ami_id:
        msg = '%s was already encrypted with Bracket Encryptor %s' % (
            ami.id,
            encryptor_ami_id
        )
        raise ValidationError(msg)

    return ami


def _validate_encryptor_ami(aws_svc, ami_id):
    """ Validate that the image exists and is a Bracket encryptor image.

    :raise ValidationError if validation fails
    """
    image = _validate_ami(aws_svc, ami_id)
    if 'brkt-avatar' not in image.name:
        raise ValidationError(
            '%s (%s) is not a Bracket Encryptor image' % (ami_id, image.name)
        )
    return None


def _validate(aws_svc, values, encryptor_ami_id):
    """ Validate command-line options

    :param aws_svc: the BaseAWSService implementation
    :param values: object that was generated by argparse
    """
    if values.encrypted_ami_name:
        aws_service.validate_image_name(values.encrypted_ami_name)

    try:
        if values.key_name:
            aws_svc.get_key_pair(values.key_name)

        _validate_subnet_and_security_groups(
            aws_svc, values.subnet_id, values.security_group_ids)
        _validate_encryptor_ami(aws_svc, encryptor_ami_id)

        if values.encrypted_ami_name:
            filters = {'name': values.encrypted_ami_name}
            if aws_svc.get_images(filters=filters, owners=['self']):
                raise ValidationError(
                    'You already own an image named %s' %
                    values.encrypted_ami_name
                )
    except EC2ResponseError as e:
        raise ValidationError(e.message)


def _validate_region(aws_svc, region_name):
    """ Check that the specified region is a valid AWS region.

    :raise ValidationError if the region is invalid
    """
    region_names = [r.name for r in aws_svc.get_regions()]
    if region_name not in region_names:
        raise ValidationError(
            '%s does not exist.  AWS regions are %s' %
            (region_name, ', '.join(region_names))
        )


def _get_encryptor_ami(region_name):
    """ Read the list of AMIs from the AMI endpoint and return the AMI ID
    for the given region.

    :raise ValidationError if the region is not supported
    :raise BracketError if the list of AMIs cannot be read
    """
    bucket_url = ENCRYPTOR_AMIS_URL

    log.debug('Getting encryptor AMI list from %s', bucket_url)
    r = urllib2.urlopen(bucket_url)
    if r.getcode() not in (200, 201):
        raise BracketError(
            'Getting %s gave response: %s' % (bucket_url, r.text))
    resp_json = json.loads(r.read())
    ami = resp_json.get(region_name)

    if not ami:
        regions = resp_json.keys()
        raise ValidationError(
            'Encryptor AMI is only available in %s' % ', '.join(regions))
    return ami


def _get_updated_image_name(image_name, session_id):
    """ Generate a new name, based on the existing name of the encrypted
    image and the session id.

    :return the new name
    """
    # Replace session id in the image name.
    m = re.match('(.+) \(encrypted (\S+)\)', image_name)
    suffix = ' (encrypted %s)' % session_id
    if m:
        encrypted_ami_name = util.append_suffix(
            m.group(1), suffix, max_length=128)
    else:
        encrypted_ami_name = util.append_suffix(
            image_name, suffix, max_length=128)
    return encrypted_ami_name
