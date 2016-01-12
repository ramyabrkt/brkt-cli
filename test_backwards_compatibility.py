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
#
"""
  DO NOT MODIFY!
  Other brkt services use the brkt_cli as an unofficial library.
  This test module verifies that the brkt_cli is compatible with current 3rd
  party usage.
  Modify only if you're updating to sync with 3rd party usage.
"""

import inspect
import unittest

from brkt_cli import (
    encrypt_ami,
    aws_service
)

class TestBackwardsCompatibility():
    """ DO NOT MODIFY! see module level comments """

    MODULE = None
    REQUIRED_ATTRIBUTES = ()
    REQUIRED_METHOD_SIGNATURES = ()
    def test_attributes(self):
        """ DO NOT MODIFY! see module level comments """
        for attr in self.REQUIRED_ATTRIBUTES:
            self.assertTrue(
                hasattr(self.MODULE, attr),
                'Expected attribute %s.%s' % (self.MODULE.__name__, attr)
            )

    def test_method_signatures(self):
        """ DO NOT MODIFY! see module level comments """
        count = 0
        for mthd, arguments in self.REQUIRED_METHOD_SIGNATURES:
            self.assertTrue(
                hasattr(self.MODULE, mthd),
                'Expected method %s.%s' % (self.MODULE.__name__, mthd)
            )
            method_ref = self.MODULE.__dict__[mthd]
            # If the method is decorated, get the inner method
            if hasattr(method_ref, '_undecorated'):
                method_ref = method_ref._undecorated
            method_args = inspect.getargspec(method_ref)[0]
            for arg in arguments:
                self.assertIn(arg, method_args,
                    'Expected argument "%s" for method %s.%s' % (
                        arg, self.MODULE.__name__, mthd)
                )


class TestEncryptAMIBackwardsCompatibility(
        unittest.TestCase, TestBackwardsCompatibility):
    """ DO NOT MODIFY! see module level comments """

    MODULE = encrypt_ami
    REQUIRED_ATTRIBUTES = (
        'AMI_NAME_MAX_LENGTH',
        'DESCRIPTION_SNAPSHOT',
        'NAME_ENCRYPTOR',
        'NAME_METAVISOR_ROOT_VOLUME',
        'NAME_METAVISOR_GRUB_VOLUME',
        'NAME_METAVISOR_LOG_VOLUME'
    )
    REQUIRED_METHOD_SIGNATURES = (
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
        ('wait_for_instance', ['aws_svc', 'instance_id']),
        ('create_encryptor_security_group', ['aws_svc', 'vpc_id'])
    )


class TestAWSServiceBackwardsCompatibility(
        unittest.TestCase, TestBackwardsCompatibility):
    """ DO NOT MODIFY! see module level comments """

    MODULE = aws_service.AWSService
    REQUIRED_METHOD_SIGNATURES = (
        ('connect', ['region', 'key_name']),
        ('get_key_pair', ['keyname']),
        ('validate_encryptor_ami', ['ami_id']),
        ('run_instance',
            ['image_id', 'instance_type', 'security_group_ids',
             'block_device_map', 'user_data', 'instance_profile_name',
             'subnet_id']),
        ('create_tags',
            ['resource_id', 'name', 'description']),
        ('get_subnet', ['subnet_id']),
        ('get_image', ['image_id'])
    )
