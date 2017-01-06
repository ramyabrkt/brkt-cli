import brkt_cli
import logging

from brkt_cli.subcommand import Subcommand

from brkt_cli import encryptor_service, util
from brkt_cli.instance_config import (
    INSTANCE_CREATOR_MODE,
    INSTANCE_METAVISOR_MODE,
    INSTANCE_UPDATER_MODE
)
from brkt_cli.instance_config_args import (
    instance_config_from_values,
    setup_instance_config_args
)
from brkt_cli.gce import (
    encrypt_gce_image,
    encrypt_gce_image_args,
    gce_service,
    launch_gce_image,
    launch_gce_image_args,
    update_gce_image,
    update_encrypted_gce_image_args,
)
from brkt_cli.validation import ValidationError

log = logging.getLogger(__name__)


def run_encrypt(values, config):
    session_id = util.make_nonce()
    gce_svc = gce_service.GCEService(values.project, session_id, log)
    check_args(values, gce_svc, config)

    instance_config = instance_config_from_values(
            values, mode=INSTANCE_CREATOR_MODE, cli_config=config)
    if instance_config.brkt_config and
       'crypto_policy_type' in instance_config.brkt_config:
	crypto_policy = values.crypto
    else:
	crypto_policy = 'gcm'

    encrypted_image_name = gce_service.get_image_name(
        values.encrypted_image_name, values.image)
    gce_service.validate_image_name(encrypted_image_name)
    if values.validate:
        gce_service.validate_images(gce_svc,
                                    encrypted_image_name,
                                    values.encryptor_image,
                                    values.image,
                                    values.image_project)
    if not values.verbose:
        logging.getLogger('googleapiclient').setLevel(logging.ERROR)

    log.info('Starting encryptor session %s', gce_svc.get_session_id())

    if crypto_policy is None:
	crypto_policy = 'gcm'

    encrypted_image_id = encrypt_gce_image.encrypt(
        gce_svc=gce_svc,
        enc_svc_cls=encryptor_service.EncryptorService,
        image_id=values.image,
        encryptor_image=values.encryptor_image,
        encrypted_image_name=encrypted_image_name,
        zone=values.zone,
        instance_config=instance_config_from_values(
            values, mode=INSTANCE_CREATOR_MODE, cli_config=config),
        image_project=values.image_project,
        keep_encryptor=values.keep_encryptor,
        image_file=values.image_file,
        image_bucket=values.bucket,
        network=values.network,
        subnetwork=values.subnetwork,
        status_port=values.status_port,
        cleanup=values.cleanup,
        crypto_policy=crypto_policy
    )

    # Print the image name to stdout, in case the caller wants to process
    # the output.  Log messages go to stderr.
    print(encrypted_image_id)
    return 0


def run_update(values, config):
    session_id = util.make_nonce()
    gce_svc = gce_service.GCEService(values.project, session_id, log)
    check_args(values, gce_svc, config)

    encrypted_image_name = gce_service.get_image_name(
        values.encrypted_image_name, values.image)
    gce_service.validate_image_name(encrypted_image_name)
    if values.validate:
        gce_service.validate_images(gce_svc,
                                    encrypted_image_name,
                                    values.encryptor_image,
                                    values.image)
    if not values.verbose:
        logging.getLogger('googleapiclient').setLevel(logging.ERROR)

    log.info('Starting updater session %s', gce_svc.get_session_id())

    updated_image_id = update_gce_image.update_gce_image(
        gce_svc=gce_svc,
        enc_svc_cls=encryptor_service.EncryptorService,
        image_id=values.image,
        encryptor_image=values.encryptor_image,
        encrypted_image_name=encrypted_image_name,
        zone=values.zone,
        instance_config=instance_config_from_values(
            values, mode=INSTANCE_UPDATER_MODE,
            cli_config=config),
        keep_encryptor=values.keep_encryptor,
        image_file=values.image_file,
        image_bucket=values.bucket,
        network=values.network,
        subnetwork=values.subnetwork,
        status_port=values.status_port,
        cleanup=values.cleanup
    )

    print(updated_image_id)
    return 0


def run_launch(values, config):
    gce_svc = gce_service.GCEService(values.project, None, log)
    if values.ssd_scratch_disks > 8:
        raise ValidationError("Maximum of 8 SSD scratch disks are supported")
    instance_config = instance_config_from_values(
        values, mode=INSTANCE_METAVISOR_MODE, cli_config=config)
    if values.startup_script:
        extra_items = [{
            'key': 'startup-script',
            'value': values.startup_script
        }]
    else:
        extra_items = None
    brkt_userdata = instance_config.make_userdata()
    metadata = gce_service.gce_metadata_from_userdata(
        brkt_userdata, extra_items=extra_items)
    if not values.verbose:
        logging.getLogger('googleapiclient').setLevel(logging.ERROR)

    if values.instance_name:
        gce_service.validate_image_name(values.instance_name)

    encrypted_instance_id = launch_gce_image.launch(log,
                            gce_svc,
                            values.image,
                            values.instance_name,
                            values.zone,
                            values.delete_boot,
                            values.instance_type,
                            values.network,
                            values.subnetwork,
                            metadata,
                            values.ssd_scratch_disks)
    print(encrypted_instance_id)
    return 0


class GCESubcommand(Subcommand):

    def name(self):
        return 'gce'

    def setup_config(self, config):
        config.register_option(
            '%s.project' % (self.name(),),
            'The GCE project metavisors will be launched into')
        config.register_option(
            '%s.network' % (self.name(),),
            'The GCE network metavisors will be launched into')
        config.register_option(
            '%s.subnetwork' % (self.name(),),
            'The GCE subnetwork metavisors will be launched into')
        config.register_option(
            '%s.zone' % (self.name(),),
            'The GCE zone metavisors will be launched into')

    def register(self, subparsers, parsed_config):
        self.config = parsed_config

        gce_parser = subparsers.add_parser(
            self.name(),
            description='GCE Operations',
            help='GCE Operations'
        )

        gce_subparsers = gce_parser.add_subparsers(
            dest='gce_subcommand'
        )

        encrypt_gce_image_parser = gce_subparsers.add_parser(
            'encrypt',
            description='Create an encrypted GCE image from an existing image',
            help='Encrypt a GCE image',
            formatter_class=brkt_cli.SortingHelpFormatter
        )
        encrypt_gce_image_args.setup_encrypt_gce_image_args(
            encrypt_gce_image_parser, parsed_config)
        setup_instance_config_args(encrypt_gce_image_parser, parsed_config)

        update_gce_image_parser = gce_subparsers.add_parser(
            'update',
            description=(
                'Update an encrypted GCE image with the latest Metavisor '
                'release'),
            help='Update an encrypted GCE image',
            formatter_class=brkt_cli.SortingHelpFormatter
        )
        update_encrypted_gce_image_args.setup_update_gce_image_args(
            update_gce_image_parser, parsed_config)
        setup_instance_config_args(update_gce_image_parser, parsed_config)

        launch_gce_image_parser = gce_subparsers.add_parser(
            'launch',
            description='Launch a GCE image',
            help='Launch a GCE image',
            formatter_class=brkt_cli.SortingHelpFormatter
        )
        launch_gce_image_args.setup_launch_gce_image_args(
            launch_gce_image_parser)
        setup_instance_config_args(launch_gce_image_parser, parsed_config,
                                   mode=INSTANCE_METAVISOR_MODE)

    def debug_log_to_temp_file(self, values):
        return True

    def run(self, values):
        if values.gce_subcommand == 'encrypt':
            return run_encrypt(values, self.config)
        if values.gce_subcommand == 'update':
            return run_update(values, self.config)
        if values.gce_subcommand == 'launch':
            return run_launch(values, self.config)


class EncryptGCEImageSubcommand(Subcommand):

    def name(self):
        return 'encrypt-gce-image'

    def setup_config(self, config):
        config.register_option(
            '%s.project' % (self.name(),),
            'The GCE project metavisors will be launched into')
        config.register_option(
            '%s.network' % (self.name(),),
            'The GCE network metavisors will be launched into')
        config.register_option(
            '%s.subnetwork' % (self.name(),),
            'The GCE subnetwork metavisors will be launched into')
        config.register_option(
            '%s.zone' % (self.name(),),
            'The GCE zone metavisors will be launched into')
        config.register_option(
            '%s.crypto' % (self.name(),),
            'The GCE crypto metavisors will be launched into')


    def register(self, subparsers, parsed_config):
        self.config = parsed_config
        encrypt_gce_image_parser = subparsers.add_parser(
            'encrypt-gce-image',
            description='Create an encrypted GCE image from an existing image',
            formatter_class=brkt_cli.SortingHelpFormatter
        )

        # Migrate any config options if there were set
        project = parsed_config.get_option('%s.project' % (self.name(),))
        if project:
            parsed_config.set_option('gce.project', project)
            parsed_config.unset_option('%s.project' % (self.name(),))

        network = parsed_config.get_option('%s.network' % (self.name(),))
        if network:
            parsed_config.set_option('gce.network', network)
            parsed_config.unset_option('%s.network' % (self.name(),))

        subnetwork = parsed_config.get_option('%s.subnetwork' % (self.name(),))
        if subnetwork:
            parsed_config.set_option('gce.subnetwork', subnetwork)
            parsed_config.unset_option('%s.subnetwork' % (self.name(),))

        zone = parsed_config.get_option('%s.zone' % (self.name(),))
        if zone:
            parsed_config.set_option('gce.zone', zone)
            parsed_config.unset_option('%s.zone' % (self.name(),))

        crypto = parsed_config.get_option('%s.crypto' % (self.name(),))
        if crypto:
            parsed_config.set_option('gce.crypto', crypto)
            parsed_config.unset_option('%s.crypto' % (self.name(),))

        if project or network or subnetwork or zone or crypto:
            parsed_config.save_config()

        encrypt_gce_image_args.setup_encrypt_gce_image_args(
            encrypt_gce_image_parser, parsed_config)
        setup_instance_config_args(encrypt_gce_image_parser, parsed_config)

    def debug_log_to_temp_file(self, values):
        return True

    def exposed(self):
        return False

    def run(self, values):
        log.warn(
            'This command syntax has been deprecated.  Please use brkt gce '
            'encrypt instead'
        )
        return run_encrypt(values, self.config)


class UpdateGCEImageSubcommand(Subcommand):

    def name(self):
        return 'update-gce-image'

    def register(self, subparsers, parsed_config):
        self.config = parsed_config
        update_gce_image_parser = subparsers.add_parser(
            'update-gce-image',
            description=(
                'Update an encrypted GCE image with the latest Metavisor '
                'release'),
            formatter_class=brkt_cli.SortingHelpFormatter
        )
        update_encrypted_gce_image_args.setup_update_gce_image_args(
            update_gce_image_parser, parsed_config)
        setup_instance_config_args(update_gce_image_parser, parsed_config)

    def debug_log_to_temp_file(self, values):
        return True

    def exposed(self):
        return False

    def run(self, values):
        log.warn(
            'This command syntax has been deprecated.  Please use brkt gce '
            'update instead'
            )
        return run_update(values, self.config)


class LaunchGCEImageSubcommand(Subcommand):

    def name(self):
        return 'launch-gce-image'

    def register(self, subparsers, parsed_config):
        self.config = parsed_config
        launch_gce_image_parser = subparsers.add_parser(
            'launch-gce-image',
            formatter_class=brkt_cli.SortingHelpFormatter,
            description='Launch a GCE image',
        )
        launch_gce_image_args.setup_launch_gce_image_args(
            launch_gce_image_parser)
        setup_instance_config_args(launch_gce_image_parser, parsed_config,
                                   mode=INSTANCE_METAVISOR_MODE)

    def exposed(self):
        return False

    def run(self, values):
        log.warn(
            'This command syntax has been deprecated.  Please use brkt gce '
            'launch instead'
        )
        return run_launch(values, self.config)


def get_subcommands():
    return [GCESubcommand(),
            EncryptGCEImageSubcommand(),
            UpdateGCEImageSubcommand(),
            LaunchGCEImageSubcommand()]


def check_args(values, gce_svc, cli_config):
    if values.encryptor_image:
        if values.bucket != 'prod':
            raise ValidationError("Please provided either an encryptor image or an image bucket")
    if not values.token:
        raise ValidationError('Must provide a token')

    if values.validate:
        if not gce_svc.project_exists(values.project):
            raise ValidationError("Project provider either does not exist or you do not have access to it")
        if not gce_svc.network_exists(values.network):
            raise ValidationError("Network provided does not exist")
        brkt_env = brkt_cli.brkt_env_from_values(values)
        if brkt_env is None:
            _, brkt_env = cli_config.get_current_env()
        brkt_cli.check_jwt_auth(brkt_env, values.token)
