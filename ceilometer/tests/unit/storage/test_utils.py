#
# Copyright 2016 Mirantis Inc
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

import datetime

from oslotest import base as testbase

from ceilometer import storage
from ceilometer.storage.es import utils as es_utils
from ceilometer.storage.influx import utils as influx_utils
from ceilometer.storage import models


class ElasticUtilsTest(testbase.BaseTestCase):

    results = {
        'hits': {'hits': [
            {
                '_id': 'fake_id',
                '_source': {
                    'first_sample_timestamp': '2016-04-01T16:16:41',
                    'last_sample_timestamp': '2016-04-02T16:16:41',
                    'source': 'test_source',
                    'project_id': 'fake_project',
                    'user_id': 'fake_user',
                    'metadata': {'doc.item': 'fake_value'},
                    'meters': {
                        'meter1': {'type': 'gauge', 'unit': 'B'},
                        'meter.2': {'type': 'cumulative', 'unit': '%'}
                    }
                }
            },
            {
                '_id': 'fake_id_2',
                '_source': {
                    'first_sample_timestamp': '2016-04-01T16:16:41',
                    'last_sample_timestamp': '2016-04-02T16:16:41',
                    'source': 'test_source',
                    'project_id': 'fake_project',
                    'user_id': 'fake_user',
                    'metadata': {'doc.item_1': 'fake_value_1'},
                    'meters': {
                        'meter1': {'type': 'gauge', 'unit': 'B'},
                        'meter.2': {'type': 'cumulative', 'unit': '%'}
                    }
                }
            }
        ]}
    }

    def test_make_query(self):
        query = es_utils.make_query(
            'index', user='test_user', project='test_project',
            source='test_source', start_timestamp='2016-04-01T16:16:41',
            start_timestamp_op='gt', end_timestamp='2016-04-02T16:16:41',
            end_timestamp_op='le', metaquery={'doc.item': 'test_value'},
            resource='fake_resource', limit=10
        )
        expected_query = {
            'index': 'index',
            'body': {
                'query': {
                    'filtered': {
                        'filter': {
                            'bool': {
                                'must': [
                                    {'term': {'source': 'test_source'}},
                                    {'term': {'_id': 'fake_resource'}},
                                    {'term': {'user_id': 'test_user'}},
                                    {'term': {'project_id': 'test_project'}},
                                    {'range': {
                                        'last_sample_timestamp':
                                            {'gt': '2016-04-01T16:16:41',
                                             'le': '2016-04-02T16:16:41'}}},
                                    {'term': {'doc.item': 'test_value'}}]}}}}},
            'size': 10}
        self.assertEqual(expected_query, query)

    def test_search_results_to_resource(self):
        resources = list(es_utils.search_results_to_resources(self.results))
        self.assertEqual(2, len(resources))
        self.assertIsInstance(resources[0], models.Resource)
        self.assertEqual(
            datetime.datetime(2016, 4, 2, 16, 16, 41),
            resources[0].last_sample_timestamp)
        self.assertEqual('fake_id', resources[0].resource_id)
        self.assertIsInstance(resources[0].metadata, dict)

    def test_search_results_to_meters(self):
        meters = list(es_utils.search_results_to_meters(self.results))
        self.assertEqual(4, len(meters))
        self.assertIsInstance(meters[0], models.Meter)

        self.assertEqual(set(('%', 'B')), set(meter.unit for meter in meters))
        self.assertEqual(set(('cumulative', 'gauge')),
                         set(meter.type for meter in meters))
        self.assertEqual(set(('fake_id', 'fake_id_2')),
                         set(meter.resource_id for meter in meters))

    def test_search_results_to_meters_unique(self):
        meters = list(es_utils.search_results_to_meters(self.results,
                                                        unique=True))
        self.assertEqual(2, len(meters))
        self.assertIsInstance(meters[0], models.Meter)
        self.assertEqual(set(('%', 'B')), set(meter.unit for meter in meters))
        self.assertEqual(set(('cumulative', 'gauge')),
                         set(meter.type for meter in meters))
        self.assertIsNone(meters[0].resource_id)
        self.assertIsNone(meters[0].user_id)
        self.assertIsNone(meters[0].project_id)
        self.assertIsNone(meters[0].source)


class InfluxUtilsTest(testbase.BaseTestCase):
    filter = storage.SampleFilter(
        'user_id', 'project_id', datetime.datetime(2016, 4, 1, 16, 16, 41),
        '>', datetime.datetime(2016, 4, 2, 16, 16, 41), '<=', 'resource_id'
    )

    point = {
        "meter": "counter_name",
        "user_id": "user_id",
        "project_id": "project_id",
        "resource_id": "resource_id",
        "source": "source",
        "metadata.field": "resource_metadata.field",
        "type": "counter_type",
        "unit": "counter_unit",
        "value": "41.5",
        "message_id": "message_id",
        "timestamp": "2016-04-01T18:36:41",
    }

    def test_escape_value(self):
        value_date = influx_utils.escape_value(
            datetime.datetime(2016, 4, 2, 16, 16, 41))
        self.assertIsInstance(value_date, str)
        value_bool = influx_utils.escape_value(True)
        self.assertEqual("'True'", value_bool)
        value = influx_utils.escape_value('string')
        self.assertEqual("'string'", value)

    def test_make_simple_filter_query(self):
        query = influx_utils.make_simple_filter_query(self.filter)
        expected = ('"user_id"=\'user_id\' and "project_id"=\'project_id\' and'
                    ' "time">\'2016-04-01T16:16:41Z\' and '
                    '"time"<=\'2016-04-02T16:16:41Z\' and '
                    '"resource_id"=\'resource_id\'')
        self.assertEqual(expected, query)

    def test_point_to_sample(self):
        sample = influx_utils.point_to_sample(self.point)
        self.assertIsInstance(sample, models.Sample)
        self.assertEqual(
            datetime.datetime(2016, 4, 1, 18, 36, 41), sample.timestamp
        )
        self.assertEqual('resource_id', sample.resource_id)
        self.assertIsInstance(sample.counter_volume, float)
