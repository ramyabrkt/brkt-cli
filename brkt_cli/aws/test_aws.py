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
import inspect
import unittest

from boto.ec2.blockdevicemapping import BlockDeviceType, BlockDeviceMapping
from boto.ec2.image import Image
from boto.vpc import Subnet

import brkt_cli
import brkt_cli.aws
import brkt_cli.util
from brkt_cli.aws import (
    encrypt_ami, test_aws_service
)
from brkt_cli.aws.test_aws_service import build_aws_service, new_id
from brkt_cli.validation import ValidationError


class DummyValues(object):

    def __init__(self):
        self.encrypted_ami_name = None
        self.region = 'us-west-2'
        self.key_name = None
        self.subnet_id = None
        self.security_group_ids = []
        self.validate = True
        self.ami = None
        self.encryptor_ami = None
        self.proxies = []
        self.proxy_config_file = None
        self.status_port = None


class TestValidation(unittest.TestCase):

    def test_validate_subnet_and_security_groups(self):
        aws_svc, encryptor_image, guest_image = build_aws_service()

        # Subnet, no security groups.
        subnet = Subnet()
        subnet.id = 'subnet-1'
        subnet.vpc_id = 'vpc-1'
        aws_svc.subnets[subnet.id] = subnet

        brkt_cli.aws._validate_subnet_and_security_groups(
            aws_svc, subnet_id=subnet.id)

        # Security groups, no subnet.
        sg1 = aws_svc.create_security_group('test1', 'test')
        sg2 = aws_svc.create_security_group('test2', 'test')
        brkt_cli.aws._validate_subnet_and_security_groups(
            aws_svc, security_group_ids=[sg1.id, sg2.id]
        )

        # Security group and subnet.
        sg3 = aws_svc.create_security_group(
            'test3', 'test', vpc_id=subnet.vpc_id)
        brkt_cli.aws._validate_subnet_and_security_groups(
            aws_svc, subnet_id=subnet.id, security_group_ids=[sg3.id])

        # Security groups in different VPCs.
        with self.assertRaises(ValidationError):
            brkt_cli.aws._validate_subnet_and_security_groups(
                aws_svc, security_group_ids=[sg1.id, sg2.id, sg3.id])

        # Security group not in default subnet.
        with self.assertRaises(ValidationError):
            brkt_cli.aws._validate_subnet_and_security_groups(
                aws_svc, security_group_ids=[sg3.id])

        # Security group and subnet in different VPCs.
        sg4 = aws_svc.create_security_group(
            'test4', 'test', vpc_id='vpc-2')
        with self.assertRaises(ValidationError):
            brkt_cli.aws._validate_subnet_and_security_groups(
                aws_svc, subnet_id=subnet.id, security_group_ids=[sg4.id])

        # We don't validate security groups that have no vpc_id.
        sg5 = aws_svc.create_security_group('test5', 'test', vpc_id='vpc-2')
        sg5.vpc_id = None
        brkt_cli.aws._validate_subnet_and_security_groups(
            aws_svc, security_group_ids=[sg5.id])

    def test_duplicate_image_name(self):
        """ Test that we detect name collisions with the encrypted image.
        """
        aws_svc, encryptor_image, guest_image = build_aws_service()

        # No name.
        values = DummyValues()
        values.ami = guest_image.id
        brkt_cli.aws._validate(aws_svc, values, encryptor_image.id)

        # Unique name.
        guest_image.name = 'My image'
        values.encrypted_ami_name = 'Proposed name'
        brkt_cli.aws._validate(aws_svc, values, encryptor_image.id)

        # Name collision.
        values.encrypted_ami_name = guest_image.name
        with self.assertRaises(ValidationError):
            brkt_cli.aws._validate(aws_svc, values, encryptor_image.id)

    def test_detect_double_encryption(self):
        """ Test that we disallow encryption of an already encrypted AMI.
        """
        aws_svc = test_aws_service.DummyAWSService()

        # Register guest image
        bdm = BlockDeviceMapping()
        bdm['/dev/sda1'] = BlockDeviceType()
        id = aws_svc.register_image(
            name='Guest image', block_device_map=bdm)
        guest_image = aws_svc.get_image(id)

        # Make the guest image look like it was already encrypted and
        # make sure that validation fails.
        guest_image.tags[encrypt_ami.TAG_ENCRYPTOR] = 'ami-' + new_id()
        with self.assertRaises(ValidationError):
            brkt_cli.aws._validate_guest_ami(aws_svc, id)

    def test_validate_guest_image(self):
        """ Test validation of an encrypted guest image.
        """
        image = Image()
        image.id = new_id()
        old_encryptor_id = new_id()
        new_encryptor_id = new_id()
        image.tags[encrypt_ami.TAG_ENCRYPTOR] = 'True'
        image.tags[encrypt_ami.TAG_ENCRYPTOR_AMI] = old_encryptor_id

        aws_svc = test_aws_service.DummyAWSService()
        aws_svc.images[image.id] = image

        # Missing tag.
        with self.assertRaises(ValidationError):
            brkt_cli.aws._validate_guest_encrypted_ami(
                aws_svc, image.id, new_encryptor_id)

        # No missing tag.
        image.tags[encrypt_ami.TAG_ENCRYPTOR_SESSION_ID] = new_id()
        result = brkt_cli.aws._validate_guest_encrypted_ami(
            aws_svc, image.id, new_encryptor_id)
        self.assertEquals(image, result)

        # Attempting to encrypt with the same encryptor AMI.
        with self.assertRaises(ValidationError):
            brkt_cli.aws._validate_guest_encrypted_ami(
                aws_svc, image.id, old_encryptor_id)

        # Invalid image ID.
        with self.assertRaises(ValidationError):
            brkt_cli.aws._validate_guest_encrypted_ami(
                aws_svc, 'ami-123456', new_encryptor_id
            )

    def test_validate_encryptor_ami(self):
        """ Test validation of the encryptor AMI.
        """
        aws_svc = test_aws_service.DummyAWSService()
        image = Image()
        image.id = new_id()
        image.name = 'brkt-avatar'
        aws_svc.images[image.id] = image

        # Valid image.
        brkt_cli.aws._validate_encryptor_ami(aws_svc, image.id)

        # Unexpected name.
        image.name = 'foobar'
        with self.assertRaises(ValidationError):
            brkt_cli.aws._validate_encryptor_ami(aws_svc, image.id)

        # Invalid id.
        id = new_id()
        with self.assertRaises(ValidationError):
            brkt_cli.aws._validate_encryptor_ami(aws_svc, id)

        # Service returned None.  Apparently this can happen when the account
        # does not have access to the image.
        aws_svc.images[id] = None
        with self.assertRaises(ValidationError):
            brkt_cli.aws._validate_encryptor_ami(aws_svc, id)

    def test_detect_valid_ntp_server(self):
        """ Test that we allow only valid host names or IPv4 addresses to
            to be configured as ntp servers.
        """

        # first test a valid collection of host names/IPv4 addresses
        ntp_servers = ["0.netbsd.pool.ntp.org", "10.10.10.1",
                       "ec2-52-36-60-215.us-west-2.compute.amazonaws.com",
                       "abc.com."]
        brkt_cli.validate_ntp_servers(ntp_servers)

        # test invalid host name is rejected
        ntp_servers = ["ec2_52_36_60_215.us-west-2.compute.amazonaws.com"]
        with self.assertRaises(ValidationError):
            brkt_cli.validate_ntp_servers(ntp_servers)

        # test IPv6 address is rejected
        ntp_servers = ["2001:db8:a0b:12f0::1"]
        with self.assertRaises(ValidationError):
            brkt_cli.validate_ntp_servers(ntp_servers)
        ntp_servers = ["2001:0db8:0a0b:12f0:0001:0001:0001:0001"]
        with self.assertRaises(ValidationError):
            brkt_cli.validate_ntp_servers(ntp_servers)

    def test_updated_image_name(self):
        """ Test updating the name of an encrypted image.
        """
        # Existing image name contains the session id.
        self.assertEquals(
            'abc (encrypted 456)',
            brkt_cli.aws._get_updated_image_name('abc (encrypted 123)', '456')
        )

        # Long name, contains session id.
        existing = 'x' * 112 + ' (encrypted 123)'
        self.assertEquals(
            'x' * 109 + ' (encrypted 123456)',
            brkt_cli.aws._get_updated_image_name(existing, '123456')
        )

        # Existing image name doesn't contain the session id.
        self.assertEquals(
            'abc (encrypted 123)',
            brkt_cli.aws._get_updated_image_name('abc', '123')
        )

        # Long name, does not contain session id.
        self.assertEquals(
            'x' * 112 + ' (encrypted 123)',
            brkt_cli.aws._get_updated_image_name('x' * 128, '123')
        )

    def test_validate_region(self):
        aws_svc = test_aws_service.DummyAWSService()

        # Valid region.
        for region in aws_svc.get_regions():
            brkt_cli.aws._validate_region(aws_svc, region.name)

        # Bogus region.
        with self.assertRaises(ValidationError):
            brkt_cli.aws._validate_region(aws_svc, 'foobar')


class TestEncryptAMIBackwardsCompatibility(unittest.TestCase):

    def test_attributes(self):
        required_attributes = (
            'AMI_NAME_MAX_LENGTH',
            'DESCRIPTION_SNAPSHOT',
            'NAME_ENCRYPTOR',
            'NAME_METAVISOR_ROOT_VOLUME'
        )
        for attr in required_attributes:
            self.assertTrue(
                hasattr(encrypt_ami, attr),
                'Did not find attribute encrypt_ami.%s' % attr
            )

    def test_method_signatures(self):
        required_method_signatures = (
            ('append_suffix',
             ['name', 'suffix', 'max_length']),
            ('clean_up',
             ['aws_svc', 'instance_ids', 'security_group_ids']),
            ('get_encrypted_suffix', []),
            ('snapshot_encrypted_instance',
             ['aws_svc', 'enc_svc_cls', 'encryptor_instance',
              'encryptor_image', 'legacy']),
            ('register_ami',
             ['aws_svc', 'encryptor_instance', 'encryptor_image', 'name',
              'description', 'mv_bdm', 'legacy', 'mv_root_id']),
            ('wait_for_instance',
             ['aws_svc', 'instance_id']),
            ('create_encryptor_security_group', ['aws_svc'])
        )
        for mthd, args in required_method_signatures:
            self.assertTrue(
                hasattr(encrypt_ami, mthd),
                'Did not find method encrypt_ami.%s' % mthd
            )
            method_ref = encrypt_ami.__dict__[mthd]
            method_args = inspect.getargspec(method_ref)[0]
            for arg in args:
                self.assertIn(
                    arg, method_args,
                    'Did not find argument "%s" for method encrypt_ami.%s' % (
                        arg, mthd)
                )
