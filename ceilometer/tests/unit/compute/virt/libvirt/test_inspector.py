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
"""Tests for libvirt inspector.
"""

try:
    import contextlib2 as contextlib   # for Python < 3.3
except ImportError:
    import contextlib

import fixtures
import mock
from oslo_utils import units
from oslotest import base

from ceilometer.compute.virt import inspector as virt_inspector
from ceilometer.compute.virt.libvirt import inspector as libvirt_inspector


class TestLibvirtInspection(base.BaseTestCase):

    class fakeLibvirtError(Exception):
        pass

    def setUp(self):
        super(TestLibvirtInspection, self).setUp()

        class VMInstance(object):
            id = 'ff58e738-12f4-4c58-acde-77617b68da56'
            name = 'instance-00000001'
        self.instance = VMInstance
        self.inspector = libvirt_inspector.LibvirtInspector()
        self.inspector.connection = mock.Mock()
        libvirt_inspector.libvirt = mock.Mock()
        libvirt_inspector.libvirt.VIR_DOMAIN_SHUTOFF = 5
        libvirt_inspector.libvirt.libvirtError = self.fakeLibvirtError
        self.domain = mock.Mock()
        self.addCleanup(mock.patch.stopall)

        self.dom_xml = """
             <domain type='kvm'>
                 <devices>
                    <!-- NOTE(dprince): interface with no target -->
                    <interface type='bridge'>
                       <mac address='fa:16:3e:93:31:5a'/>
                       <source bridge='br100'/>
                       <model type='virtio'/>
                       <address type='pci' domain='0x0000' bus='0x00' \
                       slot='0x03' function='0x0'/>
                    </interface>
                    <!-- NOTE(dprince): interface with no mac -->
                    <interface type='bridge'>
                       <source bridge='br100'/>
                       <target dev='foo'/>
                       <model type='virtio'/>
                       <address type='pci' domain='0x0000' bus='0x00' \
                       slot='0x03' function='0x0'/>
                    </interface>
                    <interface type='bridge'>
                       <mac address='fa:16:3e:71:ec:6d'/>
                       <source bridge='br100'/>
                       <target dev='vnet0'/>
                       <filterref filter=
                        'nova-instance-00000001-fa163e71ec6d'>
                         <parameter name='DHCPSERVER' value='10.0.0.1'/>
                         <parameter name='IP' value='10.0.0.2'/>
                         <parameter name='PROJMASK' value='255.255.255.0'/>
                         <parameter name='PROJNET' value='10.0.0.0'/>
                       </filterref>
                       <alias name='net0'/>
                     </interface>
                     <interface type='bridge'>
                       <mac address='fa:16:3e:71:ec:6e'/>
                       <source bridge='br100'/>
                       <target dev='vnet1'/>
                       <filterref filter=
                        'nova-instance-00000001-fa163e71ec6e'>
                         <parameter name='DHCPSERVER' value='192.168.0.1'/>
                         <parameter name='IP' value='192.168.0.2'/>
                         <parameter name='PROJMASK' value='255.255.255.0'/>
                         <parameter name='PROJNET' value='192.168.0.0'/>
                       </filterref>
                       <alias name='net1'/>
                     </interface>
                     <interface type='bridge'>
                       <mac address='fa:16:3e:96:33:f0'/>
                       <source bridge='qbr420008b3-7c'/>
                       <target dev='vnet2'/>
                       <model type='virtio'/>
                       <address type='pci' domain='0x0000' bus='0x00' \
                       slot='0x03' function='0x0'/>
                    </interface>
                 </devices>
             </domain>
        """

    def test_inspect_cpus(self):
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(self.inspector.connection,
                                                  'lookupByUUIDString',
                                                  return_value=self.domain))
            stack.enter_context(mock.patch.object(self.domain, 'info',
                                                  return_value=(0, 0, 0,
                                                                2, 999999)))
            cpu_info = self.inspector.inspect_cpus(self.instance)
            self.assertEqual(2, cpu_info.number)
            self.assertEqual(999999, cpu_info.time)

    def test_inspect_cpus_with_domain_shutoff(self):
        connection = self.inspector.connection
        with mock.patch.object(connection, 'lookupByUUIDString',
                               return_value=self.domain):
            with mock.patch.object(self.domain, 'info',
                                   return_value=(5, 0, 0,
                                                 2, 999999)):
                self.assertRaises(virt_inspector.InstanceShutOffException,
                                  self.inspector.inspect_cpus,
                                  self.instance)

    def test_inspect_vnics(self):
        interface_stats = {
            'vnet0': (1, 2, 0, 0, 3, 4, 0, 0),
            'vnet1': (5, 6, 0, 0, 7, 8, 0, 0),
            'vnet2': (9, 10, 0, 0, 11, 12, 0, 0),
        }
        interfaceStats = interface_stats.__getitem__

        connection = self.inspector.connection
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(connection,
                                                  'lookupByUUIDString',
                                                  return_value=self.domain))
            stack.enter_context(mock.patch.object(self.domain, 'XMLDesc',
                                                  return_value=self.dom_xml))
            stack.enter_context(mock.patch.object(self.domain,
                                                  'interfaceStats',
                                                  side_effect=interfaceStats))
            stack.enter_context(mock.patch.object(self.domain, 'info',
                                                  return_value=(0, 0, 0,
                                                                2, 999999)))
            interfaces = list(self.inspector.inspect_vnics(self.instance))

            self.assertEqual(3, len(interfaces))
            vnic0, info0 = interfaces[0]
            self.assertEqual('vnet0', vnic0.name)
            self.assertEqual('fa:16:3e:71:ec:6d', vnic0.mac)
            self.assertEqual('nova-instance-00000001-fa163e71ec6d', vnic0.fref)
            self.assertEqual('255.255.255.0', vnic0.parameters.get('projmask'))
            self.assertEqual('10.0.0.2', vnic0.parameters.get('ip'))
            self.assertEqual('10.0.0.0', vnic0.parameters.get('projnet'))
            self.assertEqual('10.0.0.1', vnic0.parameters.get('dhcpserver'))
            self.assertEqual(1, info0.rx_bytes)
            self.assertEqual(2, info0.rx_packets)
            self.assertEqual(3, info0.tx_bytes)
            self.assertEqual(4, info0.tx_packets)

            vnic1, info1 = interfaces[1]
            self.assertEqual('vnet1', vnic1.name)
            self.assertEqual('fa:16:3e:71:ec:6e', vnic1.mac)
            self.assertEqual('nova-instance-00000001-fa163e71ec6e', vnic1.fref)
            self.assertEqual('255.255.255.0', vnic1.parameters.get('projmask'))
            self.assertEqual('192.168.0.2', vnic1.parameters.get('ip'))
            self.assertEqual('192.168.0.0', vnic1.parameters.get('projnet'))
            self.assertEqual('192.168.0.1', vnic1.parameters.get('dhcpserver'))
            self.assertEqual(5, info1.rx_bytes)
            self.assertEqual(6, info1.rx_packets)
            self.assertEqual(7, info1.tx_bytes)
            self.assertEqual(8, info1.tx_packets)

            vnic2, info2 = interfaces[2]
            self.assertEqual('vnet2', vnic2.name)
            self.assertEqual('fa:16:3e:96:33:f0', vnic2.mac)
            self.assertIsNone(vnic2.fref)
            self.assertEqual(dict(), vnic2.parameters)
            self.assertEqual(9, info2.rx_bytes)
            self.assertEqual(10, info2.rx_packets)
            self.assertEqual(11, info2.tx_bytes)
            self.assertEqual(12, info2.tx_packets)

    def test_inspect_vnics_with_domain_shutoff(self):
        connection = self.inspector.connection
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(connection,
                                                  'lookupByUUIDString',
                                                  return_value=self.domain))
            stack.enter_context(mock.patch.object(self.domain, 'info',
                                                  return_value=(5, 0, 0,
                                                                2, 999999)))
            inspect = self.inspector.inspect_vnics
            self.assertRaises(virt_inspector.InstanceShutOffException,
                              list, inspect(self.instance))

    def test_inspect_disks(self):
        dom_xml = """
             <domain type='kvm'>
                 <devices>
                     <disk type='file' device='disk'>
                         <driver name='qemu' type='qcow2' cache='none'/>
                         <source file='/path/instance-00000001/disk'/>
                         <target dev='vda' bus='virtio'/>
                         <alias name='virtio-disk0'/>
                         <address type='pci' domain='0x0000' bus='0x00'
                                  slot='0x04' function='0x0'/>
                     </disk>
                 </devices>
             </domain>
        """

        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(self.inspector.connection,
                                                  'lookupByUUIDString',
                                                  return_value=self.domain))
            stack.enter_context(mock.patch.object(self.domain, 'XMLDesc',
                                                  return_value=dom_xml))
            stack.enter_context(mock.patch.object(self.domain, 'blockStats',
                                                  return_value=(1, 2, 3,
                                                                4, -1)))
            stack.enter_context(mock.patch.object(self.domain, 'info',
                                                  return_value=(0, 0, 0,
                                                                2, 999999)))
            disks = list(self.inspector.inspect_disks(self.instance))

            self.assertEqual(1, len(disks))
            disk0, info0 = disks[0]
            self.assertEqual('vda', disk0.device)
            self.assertEqual(1, info0.read_requests)
            self.assertEqual(2, info0.read_bytes)
            self.assertEqual(3, info0.write_requests)
            self.assertEqual(4, info0.write_bytes)

    def test_inspect_disks_with_domain_shutoff(self):
        connection = self.inspector.connection
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(connection,
                                                  'lookupByUUIDString',
                                                  return_value=self.domain))
            stack.enter_context(mock.patch.object(self.domain, 'info',
                                                  return_value=(5, 0, 0,
                                                                2, 999999)))
            inspect = self.inspector.inspect_disks
            self.assertRaises(virt_inspector.InstanceShutOffException,
                              list, inspect(self.instance))

    def test_inspect_memory_usage(self):
        fake_memory_stats = {'available': 51200, 'unused': 25600}
        connection = self.inspector.connection
        with mock.patch.object(connection, 'lookupByUUIDString',
                               return_value=self.domain):
            with mock.patch.object(self.domain, 'info',
                                   return_value=(0, 0, 51200,
                                                 2, 999999)):
                with mock.patch.object(self.domain, 'memoryStats',
                                       return_value=fake_memory_stats):
                    memory = self.inspector.inspect_memory_usage(
                        self.instance)
                    self.assertEqual(25600 / units.Ki, memory.usage)

    def test_inspect_disk_info(self):
        dom_xml = """
             <domain type='kvm'>
                 <devices>
                     <disk type='file' device='disk'>
                         <driver name='qemu' type='qcow2' cache='none'/>
                         <source file='/path/instance-00000001/disk'/>
                         <target dev='vda' bus='virtio'/>
                         <alias name='virtio-disk0'/>
                         <address type='pci' domain='0x0000' bus='0x00'
                                  slot='0x04' function='0x0'/>
                     </disk>
                 </devices>
             </domain>
        """

        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(self.inspector.connection,
                                                  'lookupByUUIDString',
                                                  return_value=self.domain))
            stack.enter_context(mock.patch.object(self.domain, 'XMLDesc',
                                                  return_value=dom_xml))
            stack.enter_context(mock.patch.object(self.domain, 'blockInfo',
                                                  return_value=(1, 2, 3,
                                                                -1)))
            stack.enter_context(mock.patch.object(self.domain, 'info',
                                                  return_value=(0, 0, 0,
                                                                2, 999999)))
            disks = list(self.inspector.inspect_disk_info(self.instance))

            self.assertEqual(1, len(disks))
            disk0, info0 = disks[0]
            self.assertEqual('vda', disk0.device)
            self.assertEqual(1, info0.capacity)
            self.assertEqual(2, info0.allocation)
            self.assertEqual(3, info0.physical)

    def test_inspect_memory_usage_with_domain_shutoff(self):
        connection = self.inspector.connection
        with mock.patch.object(connection, 'lookupByUUIDString',
                               return_value=self.domain):
            with mock.patch.object(self.domain, 'info',
                                   return_value=(5, 0, 0,
                                                 2, 999999)):
                self.assertRaises(virt_inspector.InstanceShutOffException,
                                  self.inspector.inspect_memory_usage,
                                  self.instance)

    def test_inspect_memory_usage_with_empty_stats(self):
        connection = self.inspector.connection
        with mock.patch.object(connection, 'lookupByUUIDString',
                               return_value=self.domain):
            with mock.patch.object(self.domain, 'info',
                                   return_value=(0, 0, 51200,
                                                 2, 999999)):
                with mock.patch.object(self.domain, 'memoryStats',
                                       return_value={}):
                    self.assertRaises(virt_inspector.NoDataException,
                                      self.inspector.inspect_memory_usage,
                                      self.instance)

    def test_inspect_cpu_util(self):
        with mock.patch.object(self.inspector.connection, 'lookupByUUIDString',
                               return_value=self.domain):
            with mock.patch.object(self.domain, 'info',
                                   return_value=(0, 0, 0, 2, 1 * 10 ** 9)):
                self.assertEqual(
                    None, self.inspector.inspect_cpu_util(self.instance, 1))
            with mock.patch.object(self.domain, 'info',
                                   return_value=(0, 0, 0, 2, 2 * 10 ** 9)):
                cpu_info = self.inspector.inspect_cpu_util(self.instance, 1)
                self.assertEqual(50., cpu_info.util)

    def test_inspect_disk_rates(self):
        dom_xml = """
             <domain type='kvm'>
                 <devices>
                     <disk type='file' device='disk'>
                         <driver name='qemu' type='qcow2' cache='none'/>
                         <source file='/path/instance-00000001/disk'/>
                         <target dev='vda' bus='virtio'/>
                         <alias name='virtio-disk0'/>
                         <address type='pci' domain='0x0000' bus='0x00'
                                  slot='0x04' function='0x0'/>
                     </disk>
                      <disk type='file' device='disk'>
                         <driver name='qemu' type='qcow2' cache='none'/>
                         <source file='/path/instance-00000001/disk'/>
                         <target dev='vdb' bus='virtio'/>
                         <alias name='virtio-disk0'/>
                         <address type='pci' domain='0x0000' bus='0x00'
                                  slot='0x04' function='0x0'/>
                     </disk>
                 </devices>
             </domain>
        """

        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(self.inspector.connection,
                                                  'lookupByUUIDString',
                                                  return_value=self.domain))
            stack.enter_context(mock.patch.object(self.domain, 'XMLDesc',
                                                  return_value=dom_xml))
            stack.enter_context(mock.patch.object(self.domain, 'info',
                                                  return_value=(0, 0, 0,
                                                                2, 999999)))
            with mock.patch.object(self.domain, 'blockStats',
                                   return_value=(0, 1, 2, 3, -1)):
                self.assertEqual(
                    [], self.inspector.inspect_disk_rates(self.instance, 1))

            with mock.patch.object(self.domain, 'blockStats',
                                   return_value=(1, 3, 5, 7, -1)):
                disk_stats = self.inspector.inspect_disk_rates(
                    self.instance, 1)
                self.assertEqual(2, len(disk_stats))
                disk0, info0 = disk_stats[0]
                self.assertEqual('vda', disk0.device)
                self.assertEqual(1, info0.read_requests_rate)
                self.assertEqual(2, info0.read_bytes_rate)
                self.assertEqual(3, info0.write_requests_rate)
                self.assertEqual(4, info0.write_bytes_rate)
                disk1, info1 = disk_stats[1]
                self.assertEqual('vdb', disk1.device)
                self.assertEqual(1, info1.read_requests_rate)
                self.assertEqual(2, info1.read_bytes_rate)
                self.assertEqual(3, info1.write_requests_rate)
                self.assertEqual(4, info1.write_bytes_rate)

    def test_inspect_vnic_stats(self):
        interface_stats = {
            'vnet0': (1, 2, 0, 0, 3, 4, 0, 0),
            'vnet1': (5, 6, 0, 0, 7, 8, 0, 0),
            'vnet2': (9, 10, 0, 0, 11, 12, 0, 0),
        }
        interfaceStats = interface_stats.__getitem__

        connection = self.inspector.connection
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(connection,
                                                  'lookupByUUIDString',
                                                  return_value=self.domain))
            stack.enter_context(mock.patch.object(self.domain, 'XMLDesc',
                                                  return_value=self.dom_xml))
            stack.enter_context(mock.patch.object(self.domain, 'info',
                                                  return_value=(0, 0, 0,
                                                                2,
                                                                999999)))
            with mock.patch.object(self.domain, 'interfaceStats',
                                   side_effect=interfaceStats):

                self.assertEqual(
                    [], self.inspector.inspect_vnic_rates(self.instance, 1))

            interface_stats = {
                'vnet0': (3, 4, 0, 0, 5, 6, 0, 0),
                'vnet1': (10, 11, 0, 0, 16, 18, 0, 0),
                'vnet2': (29, 30, 0, 0, 31, 32, 0, 0),
            }
            interfaceStats = interface_stats.__getitem__

            with mock.patch.object(self.domain, 'interfaceStats',
                                   side_effect=interfaceStats):
                stats = self.inspector.inspect_vnic_rates(self.instance, 1)

                self.assertEqual(3, len(stats))
                vnic0, stats0 = stats[0]
                self.assertEqual('vnet0', vnic0.name)
                self.assertEqual(2, stats0.rx_bytes_rate)
                self.assertEqual(2, stats0.tx_bytes_rate)

                vnic1, stats1 = stats[1]
                self.assertEqual('vnet1', vnic1.name)
                self.assertEqual(5, stats1.rx_bytes_rate)
                self.assertEqual(9, stats1.tx_bytes_rate)

                vnic2, stats2 = stats[2]
                self.assertEqual('vnet2', vnic2.name)
                self.assertEqual(20, stats2.rx_bytes_rate)
                self.assertEqual(20, stats2.tx_bytes_rate)


class TestLibvirtInspectionWithError(base.BaseTestCase):

    class fakeLibvirtError(Exception):
        pass

    def setUp(self):
        super(TestLibvirtInspectionWithError, self).setUp()
        self.inspector = libvirt_inspector.LibvirtInspector()
        self.useFixture(fixtures.MonkeyPatch(
            'ceilometer.compute.virt.libvirt.inspector.'
            'LibvirtInspector._get_connection',
            self._dummy_get_connection))
        libvirt_inspector.libvirt = mock.Mock()
        libvirt_inspector.libvirt.libvirtError = self.fakeLibvirtError

    @staticmethod
    def _dummy_get_connection(*args, **kwargs):
        raise Exception('dummy')

    def test_inspect_unknown_error(self):
        self.assertRaises(virt_inspector.InspectorException,
                          self.inspector.inspect_cpus, 'foo')
