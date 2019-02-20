import abc

import six

from ceilometer.agent import plugin_base


@six.add_metaclass(abc.ABCMeta)
class ServerPollster(plugin_base.PollsterBase):

    @property
    def default_discovery(self):
        return 'local_node'
