import commands
import os

from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import timeutils

from ceilometer.compute import server_pollsters
from ceilometer import sample

LOG = logging.getLogger(__name__)

COMPUTE_OPTS = [
    cfg.StrOpt('storage_server_address',
               default='',
               help='Some storage address used to check storage-connectivity.'),
    cfg.IntOpt('ping_count',
               default=4,
               help='Count of ping storage gateway.'),
    cfg.FloatOpt('ping_loss_ratio',
                 default=0.5,
                 help='Ping loss ratio that can be accepted.'),
]

CONF = cfg.CONF
CONF.register_opts(COMPUTE_OPTS, group='compute')


def check_ping_status(ip_address, ping_count=4, ping_loss_ratio=0.5):
    ok_count = 0
    for i in range(1, ping_count+1):
        result = os.system(u'ping -c 1 -W 1 %s > /dev/null 2>&1' % ip_address)
        if result == 0:
            ok_count += 1
    return True if ok_count / float(ping_count) >= ping_loss_ratio else False


class StorageConnectivityPollster(server_pollsters.ServerPollster):

    def get_samples(self, manager, cache, resources):
        for host in resources:
            storage_server_addresses = CONF.compute.storage_server_address
            if ',' in storage_server_addresses:
                storage_server_addresses = storage_server_addresses.split(',')
            else:
                storage_server_addresses = [storage_server_addresses]

            result = any(
                [check_ping_status(ip, CONF.compute.ping_count, CONF.compute.ping_loss_ratio) for ip in storage_server_addresses])
            connectivity_status = 1 if result else 0

            host_name = commands.getoutput('hostname').strip()
            yield sample.Sample(
                name='storage_connectivity',
                type=sample.TYPE_GAUGE,
                unit='',
                volume=connectivity_status,
                resource_id=host_name,
                user_id=None,
                project_id=None,
                timestamp=timeutils.utcnow().isoformat(),
                resource_metadata={'node': host_name},
            )
