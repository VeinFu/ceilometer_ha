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
import copy
import six
import urllib

from ceilometer.storage import models
from ceilometer.storage.mongo import utils as pymongo_utils
from ceilometer import utils


def make_query(index, user=None, project=None, source=None,
               start_timestamp=None, start_timestamp_op=None,
               end_timestamp=None, end_timestamp_op=None,
               metaquery=None, resource=None, limit=None):
    """Make filter query for the resource-list and meter-list requests."""

    q_args = {}
    filters = []
    if limit is not None:
        q_args['size'] = limit
    q_args['index'] = index
    if source is not None:
        filters.append({'term': {'source': source}})
    if resource is not None:
        filters.append({'term': {'_id': resource}})
    if user is not None:
        filters.append({'term': {'user_id': user}})
    if project is not None:
        filters.append({'term': {'project_id': project}})
    if start_timestamp or end_timestamp:
        ts_filter = {}
        st_op = start_timestamp_op or 'gte'
        et_op = end_timestamp_op or 'lt'
        if start_timestamp:
            ts_filter[st_op] = start_timestamp
        if end_timestamp:
            ts_filter[et_op] = end_timestamp
        filters.append({'range': {'last_sample_timestamp': ts_filter}})
    if metaquery is not None:
        metaquery = pymongo_utils.improve_keys(metaquery, metaquery=True)
        for key, value in six.iteritems(metaquery):
            filters.append({'term': {key: value}})
    q_args['body'] = {
        'query': {
            'filtered': {
                'filter': {
                    'bool': {'must': filters}
                }
            }
        }
    }
    return q_args


def search_results_to_resources(results):
    """Transforms results of the search to the Resource instances."""

    for record in results['hits']['hits']:
        yield models.Resource(
            resource_id=record['_id'],
            first_sample_timestamp=utils.sanitize_timestamp(
                record['_source'].get('first_sample_timestamp')),
            last_sample_timestamp=utils.sanitize_timestamp(
                record['_source']['last_sample_timestamp']),
            source=record['_source'].get('source'),
            project_id=record['_source'].get('project_id'),
            user_id=record['_source'].get('user_id'),
            metadata=record['_source'].get('metadata', {})
        )


def search_results_to_meters(results, limit=None, unique=False):
    """Transforms results of the search to the Meter instances."""

    if unique:
        meter_names = set()
    count = 0

    for record in results['hits']['hits']:
        for meter_name, specials in six.iteritems(record['_source']['meters']):
            meter_name = urllib.unquote(meter_name)
            if limit and count >= limit:
                return
            else:
                count += 1
            if unique:
                if meter_name in meter_names:
                    continue
                else:
                    meter_names.add(meter_name)
                    yield models.Meter(
                        name=unquote(meter_name),
                        type=specials['type'],
                        unit=specials.get('unit', ''),
                        resource_id=None,
                        project_id=None,
                        source=None,
                        user_id=None)
            else:
                yield models.Meter(
                    name=unquote(meter_name),
                    type=specials['type'],
                    unit=specials.get('unit', ''),
                    resource_id=record['_id'],
                    source=record['_source']["source"],
                    project_id=record['_source'].get('project_id'),
                    user_id=record['_source'].get('user_id'),
                )


def sample_to_resource(data):
    data = copy.deepcopy(data)
    data['counter_name'] = quote(data['counter_name'])
    data['resource_metadata'] = pymongo_utils.improve_keys(
        data.pop('resource_metadata'))
    return {'script': ('ctx._source.meters += meter;'
                       'ctx._source.user_id = user_id;'
                       'ctx._source.project_id = project_id;'
                       'ctx._source.source = source;'
                       'ctx._source.metadata = '
                       'ctx._source.last_sample_timestamp <= timestamp ? '
                       'metadata : ctx._source.metadata;'
                       'ctx._source.last_sample_timestamp = '
                       'ctx._source.last_sample_timestamp < timestamp ?'
                       'timestamp : ctx._source.last_sample_timestamp;'
                       'ctx._source.first_sample_timestamp = '
                       'ctx._source.first_sample_timestamp > timestamp ?'
                       'timestamp : ctx._source.first_sample_timestamp;'),
            'params': {
                'meter': {data['counter_name']: {
                    'type': data['counter_type'],
                    'unit': data['counter_unit']
                }},
                'metadata': data['resource_metadata'],
                'timestamp': data['timestamp'],
                'user_id': data.get('user_id', ''),
                'project_id': data.get('project_id', ''),
                'source': data.get('source', ''),
                },
            'upsert': {
                "first_sample_timestamp": data['timestamp'],
                "last_sample_timestamp": data['timestamp'],
                "project_id": data['project_id'],
                "user_id": data['user_id'],
                "source": data.get('source', ''),
                "metadata": data['resource_metadata'],
                "meters": {data['counter_name']: {
                    'type': data['counter_type'],
                    'unit': data['counter_unit']
                }}}
            }


def quote(name):
    return name.replace(".", "\\")


def unquote(name):
    return name.replace("\\", ".")
