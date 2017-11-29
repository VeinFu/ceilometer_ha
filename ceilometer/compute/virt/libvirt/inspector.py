#
# Copyright 2012 Red Hat, Inc
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.
"""Implementation of Inspector abstraction for libvirt."""

import time

from lxml import etree
from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import units
import six

from ceilometer.compute.pollsters import util
from ceilometer.compute.virt import inspector as virt_inspector
from ceilometer.i18n import _, _LW

libvirt = None

LOG = logging.getLogger(__name__)

OPTS = [
    cfg.StrOpt('libvirt_type',
               default='kvm',
               choices=['kvm', 'lxc', 'qemu', 'uml', 'xen'],
               help='Libvirt domain type.'),
    cfg.StrOpt('libvirt_uri',
               default='',
               help='Override the default libvirt URI '
                    '(which is dependent on libvirt_type).'),
]

COMPUTE_OPTS = [
    cfg.IntOpt('libvirt_cache_expiration_time',
               default=3600,
               min=60,
               help='Time to expiration cache for inspecting cpu util '
                    'and disk rates.'),
]

CONF = cfg.CONF
CONF.register_opts(OPTS)
CONF.register_opts(COMPUTE_OPTS, group='compute')


def retry_on_disconnect(function):
    def decorator(self, *args, **kwargs):
        try:
            return function(self, *args, **kwargs)
        except libvirt.libvirtError as e:
            if (e.get_error_code() in
                    (libvirt.VIR_ERR_SYSTEM_ERROR,
                     libvirt.VIR_ERR_INTERNAL_ERROR) and
                e.get_error_domain() in
                    (libvirt.VIR_FROM_REMOTE,
                     libvirt.VIR_FROM_RPC)):
                LOG.debug('Connection to libvirt broken')
                self.connection = None
                return function(self, *args, **kwargs)
            else:
                raise

    return decorator


class LibvirtInspector(virt_inspector.Inspector):
    per_type_uris = dict(uml='uml:///system', xen='xen:///', lxc='lxc:///')

    def __init__(self):
        self.uri = self._get_uri()
        self.connection = None
        self._stats_cache = {}
        self._expiration_time = cfg.CONF.compute.libvirt_cache_expiration_time

    def _get_uri(self):
        return CONF.libvirt_uri or self.per_type_uris.get(CONF.libvirt_type,
                                                          'qemu:///system')

    def _get_connection(self):
        if not self.connection:
            global libvirt
            if libvirt is None:
                libvirt = __import__('libvirt')
            LOG.debug('Connecting to libvirt: %s', self.uri)
            self.connection = libvirt.openReadOnly(self.uri)

        return self.connection

    @retry_on_disconnect
    def _lookup_by_uuid(self, instance):
        instance_name = util.instance_name(instance)
        try:
            return self._get_connection().lookupByUUIDString(instance.id)
        except Exception as ex:
            if not libvirt or not isinstance(ex, libvirt.libvirtError):
                raise virt_inspector.InspectorException(six.text_type(ex))
            error_code = ex.get_error_code()
            if (error_code in (libvirt.VIR_ERR_SYSTEM_ERROR,
                               libvirt.VIR_ERR_INTERNAL_ERROR) and
                ex.get_error_domain() in (libvirt.VIR_FROM_REMOTE,
                                          libvirt.VIR_FROM_RPC)):
                raise
            msg = _("Error from libvirt while looking up instance "
                    "<name=%(name)s, id=%(id)s>: "
                    "[Error Code %(error_code)s] "
                    "%(ex)s") % {'name': instance_name,
                                 'id': instance.id,
                                 'error_code': error_code,
                                 'ex': ex}
            raise virt_inspector.InstanceNotFoundException(msg)

    def inspect_cpus(self, instance):
        domain = self._get_domain_not_shut_off_or_raise(instance)
        dom_info = domain.info()
        return virt_inspector.CPUStats(number=dom_info[3], time=dom_info[4])

    def _get_domain_not_shut_off_or_raise(self, instance):
        instance_name = util.instance_name(instance)
        domain = self._lookup_by_uuid(instance)

        state = domain.info()[0]
        if state == libvirt.VIR_DOMAIN_SHUTOFF:
            msg = _('Failed to inspect data of instance '
                    '<name=%(name)s, id=%(id)s>, '
                    'domain state is SHUTOFF.') % {
                'name': instance_name, 'id': instance.id}
            raise virt_inspector.InstanceShutOffException(msg)

        return domain

    def inspect_vnics(self, instance):
        domain = self._get_domain_not_shut_off_or_raise(instance)

        tree = etree.fromstring(domain.XMLDesc(0))
        for iface in tree.findall('devices/interface'):
            target = iface.find('target')
            if target is not None:
                name = target.get('dev')
            else:
                continue
            mac = iface.find('mac')
            if mac is not None:
                mac_address = mac.get('address')
            else:
                continue
            fref = iface.find('filterref')
            if fref is not None:
                fref = fref.get('filter')

            params = dict((p.get('name').lower(), p.get('value'))
                          for p in iface.findall('filterref/parameter'))
            interface = virt_inspector.Interface(name=name, mac=mac_address,
                                                 fref=fref, parameters=params)
            dom_stats = domain.interfaceStats(name)
            stats = virt_inspector.InterfaceStats(rx_bytes=dom_stats[0],
                                                  rx_packets=dom_stats[1],
                                                  tx_bytes=dom_stats[4],
                                                  tx_packets=dom_stats[5])
            yield (interface, stats)

    def inspect_disks(self, instance):
        domain = self._get_domain_not_shut_off_or_raise(instance)

        tree = etree.fromstring(domain.XMLDesc(0))
        for device in filter(
                bool,
                [target.get("dev")
                 for target in tree.findall('devices/disk/target')]):
            disk = virt_inspector.Disk(device=device)
            block_stats = domain.blockStats(device)
            stats = virt_inspector.DiskStats(read_requests=block_stats[0],
                                             read_bytes=block_stats[1],
                                             write_requests=block_stats[2],
                                             write_bytes=block_stats[3],
                                             errors=block_stats[4])
            yield (disk, stats)

    def inspect_memory_usage(self, instance, duration=None):
        instance_name = util.instance_name(instance)
        domain = self._get_domain_not_shut_off_or_raise(instance)

        try:
            memory_stats = domain.memoryStats()
            if (memory_stats and
                    memory_stats.get('available') and
                    memory_stats.get('unused')):
                memory_used = (memory_stats.get('available') -
                               memory_stats.get('unused'))
                # Stat provided from libvirt is in KB, converting it to MB.
                memory_used = memory_used / units.Ki
                return virt_inspector.MemoryUsageStats(usage=memory_used)
            else:
                msg = _('Failed to inspect memory usage of instance '
                        '<name=%(name)s, id=%(id)s>, '
                        'can not get info from libvirt.') % {
                    'name': instance_name, 'id': instance.id}
                raise virt_inspector.NoDataException(msg)
        # memoryStats might launch an exception if the method is not supported
        # by the underlying hypervisor being used by libvirt.
        except libvirt.libvirtError as e:
            msg = _('Failed to inspect memory usage of %(instance_uuid)s, '
                    'can not get info from libvirt: %(error)s') % {
                'instance_uuid': instance.id, 'error': e}
            raise virt_inspector.NoDataException(msg)

    def inspect_disk_info(self, instance):
        domain = self._get_domain_not_shut_off_or_raise(instance)
        tree = etree.fromstring(domain.XMLDesc(0))
        for disk in tree.findall('devices/disk'):
            disk_type = disk.get('type')
            if disk_type:
                if disk_type == 'network':
                    LOG.warning(
                        _LW('Inspection disk usage of network disk '
                            '%(instance_uuid)s unsupported by libvirt') % {
                            'instance_uuid': instance.id})
                    continue
                target = disk.find('target')
                device = target.get('dev')
                if device:
                    dsk = virt_inspector.Disk(device=device)
                    block_info = domain.blockInfo(device)
                    info = virt_inspector.DiskInfo(capacity=block_info[0],
                                                   allocation=block_info[1],
                                                   physical=block_info[2])
                    yield (dsk, info)

    def inspect_memory_resident(self, instance, duration=None):
        domain = self._get_domain_not_shut_off_or_raise(instance)
        memory = domain.memoryStats()['rss'] / units.Ki
        return virt_inspector.MemoryResidentStats(resident=memory)

    def inspect_cpu_util(self, instance, duration=None):
        cpu_stats = self.inspect_cpus(instance)
        last = self._populate_cache('cpu_util', instance.id, cpu_stats)
        result = self._calculate_cpu_util(cpu_stats, last, duration)
        if result and result.util < 0.0:
            LOG.warning(
                _LW('cpu_util for %(instance_uuid)s has incorrect value, '
                    'skip this metric ') % {'instance_uuid': instance.id})
            return None
        return result

    def inspect_disk_rates(self, instance, duration=None):
        results = []
        for disk, current in self.inspect_disks(instance):
            cache_key = "%s-%s" % (instance.id, disk.device)
            last = self._populate_cache('disk_rates', cache_key, current)
            results.append(
                (disk, self._calculate_disk_rates(current, last, duration)))
        return [stat for stat in results if stat[1]]

    def inspect_vnic_rates(self, instance, duration=None):
        results = []
        for interface, current in self.inspect_vnics(instance):
            cache_key = "%s-%s" % (instance.id, interface.mac)
            last = self._populate_cache('vnic_rates', cache_key, current)
            results.append(
                (interface,
                 self._calculate_vnic_rates(current, last, duration)))

        return [stat for stat in results if stat[1]]

    def purge_inspection_cache(self):
        for type, resources in self._stats_cache.items():
            for resource_id, stats in resources.items():
                ts, value = stats
                if time.time() - ts > self._expiration_time:
                    del self._stats_cache[type][resource_id]

    @staticmethod
    def _calculate_cpu_util(current, last, duration):
        if not last or not duration:
            return None
        return virt_inspector.CPUUtilStats(
            (100.0 * (current.time - last.time)) /
            (10 ** 9 * current.number * duration)
        )

    @staticmethod
    def _calculate_disk_rates(current, last, duration):
        if not last or not duration:
            return None
        return virt_inspector.DiskRateStats(
            float(current.read_bytes - last.read_bytes) / duration,
            float(current.read_requests - last.read_requests) / duration,
            float(current.write_bytes - last.write_bytes) / duration,
            float(current.write_requests - last.write_requests) / duration
        )

    @staticmethod
    def _calculate_vnic_rates(current, last, duration):
        if not last or not duration:
            return None
        return virt_inspector.InterfaceRateStats(
            float(current.rx_bytes - last.rx_bytes) / duration,
            float(current.tx_bytes - last.tx_bytes) / duration
        )

    def _populate_cache(self, type, key, value):
        last = self._stats_cache.setdefault(type, {}).get(key)
        self._stats_cache[type][key] = (time.time(), value)
        return last[1] if last else None
