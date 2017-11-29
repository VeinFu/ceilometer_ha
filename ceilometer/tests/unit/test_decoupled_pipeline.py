#
# Copyright 2014 Red Hat, Inc
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

from ceilometer import pipeline
from ceilometer import sample
from ceilometer.tests import pipeline_base


class TestDecoupledPipeline(pipeline_base.BasePipelineTestCase):
    def _setup_pipeline_cfg(self):
        source = {'name': 'test_source',
                  'interval': 5,
                  'counters': ['a'],
                  'resources': [],
                  'sinks': ['test_sink']}
        sink = {'name': 'test_sink',
                'transformers': [{'name': 'update', 'parameters': {}}],
                'publishers': ['test://']}
        self.pipeline_cfg = {'sources': [source], 'sinks': [sink]}

    def _augment_pipeline_cfg(self):
        self.pipeline_cfg['sources'].append({
            'name': 'second_source',
            'interval': 5,
            'counters': ['b'],
            'resources': [],
            'sinks': ['second_sink']
        })
        self.pipeline_cfg['sinks'].append({
            'name': 'second_sink',
            'transformers': [{
                'name': 'update',
                'parameters':
                {
                    'append_name': '_new',
                }
            }],
            'publishers': ['new'],
        })

    def _break_pipeline_cfg(self):
        self.pipeline_cfg['sources'].append({
            'name': 'second_source',
            'interval': 5,
            'counters': ['b'],
            'resources': [],
            'sinks': ['second_sink']
        })
        self.pipeline_cfg['sinks'].append({
            'name': 'second_sink',
            'transformers': [{
                'name': 'update',
                'parameters':
                {
                    'append_name': '_new',
                }
            }],
            'publishers': ['except'],
        })

    def _dup_pipeline_name_cfg(self):
        self.pipeline_cfg['sources'].append({
            'name': 'test_source',
            'interval': 5,
            'counters': ['b'],
            'resources': [],
            'sinks': ['test_sink']
        })

    def _set_pipeline_cfg(self, field, value):
        if field in self.pipeline_cfg['sources'][0]:
            self.pipeline_cfg['sources'][0][field] = value
        else:
            self.pipeline_cfg['sinks'][0][field] = value

    def _extend_pipeline_cfg(self, field, value):
        if field in self.pipeline_cfg['sources'][0]:
            self.pipeline_cfg['sources'][0][field].extend(value)
        else:
            self.pipeline_cfg['sinks'][0][field].extend(value)

    def _unset_pipeline_cfg(self, field):
        if field in self.pipeline_cfg['sources'][0]:
            del self.pipeline_cfg['sources'][0][field]
        else:
            del self.pipeline_cfg['sinks'][0][field]

    def test_source_no_sink(self):
        del self.pipeline_cfg['sinks']
        self._exception_create_pipelinemanager()

    def test_source_no_meters_or_counters(self):
        del self.pipeline_cfg['sources'][0]['counters']
        self._exception_create_pipelinemanager()

    def test_source_dangling_sink(self):
        self.pipeline_cfg['sources'].append({
            'name': 'second_source',
            'interval': 5,
            'counters': ['b'],
            'resources': [],
            'sinks': ['second_sink']
        })
        self._exception_create_pipelinemanager()

    def test_sink_no_source(self):
        del self.pipeline_cfg['sources']
        self._exception_create_pipelinemanager()

    def test_source_with_multiple_sinks(self):
        counter_cfg = ['a', 'b']
        self._set_pipeline_cfg('counters', counter_cfg)
        self.pipeline_cfg['sinks'].append({
            'name': 'second_sink',
            'transformers': [{
                'name': 'update',
                'parameters':
                {
                    'append_name': '_new',
                }
            }],
            'publishers': ['new'],
        })
        self.pipeline_cfg['sources'][0]['sinks'].append('second_sink')

        pipeline_manager = pipeline.PipelineManager(self.pipeline_cfg,
                                                    self.transformer_manager)
        with pipeline_manager.publisher(None) as p:
            p([self.test_counter])

        self.test_counter = sample.Sample(
            name='b',
            type=self.test_counter.type,
            volume=self.test_counter.volume,
            unit=self.test_counter.unit,
            user_id=self.test_counter.user_id,
            project_id=self.test_counter.project_id,
            resource_id=self.test_counter.resource_id,
            timestamp=self.test_counter.timestamp,
            resource_metadata=self.test_counter.resource_metadata,
        )

        with pipeline_manager.publisher(None) as p:
            p([self.test_counter])

        self.assertEqual(2, len(pipeline_manager.pipelines))
        self.assertEqual('test_source:test_sink',
                         str(pipeline_manager.pipelines[0]))
        self.assertEqual('test_source:second_sink',
                         str(pipeline_manager.pipelines[1]))
        test_publisher = pipeline_manager.pipelines[0].publishers[0]
        new_publisher = pipeline_manager.pipelines[1].publishers[0]
        for publisher, sfx in [(test_publisher, '_update'),
                               (new_publisher, '_new')]:
            self.assertEqual(2, len(publisher.samples))
            self.assertEqual(2, publisher.calls)
            self.assertEqual('a' + sfx, getattr(publisher.samples[0], "name"))
            self.assertEqual('b' + sfx, getattr(publisher.samples[1], "name"))

    def test_multiple_sources_with_single_sink(self):
        self.pipeline_cfg['sources'].append({
            'name': 'second_source',
            'interval': 5,
            'counters': ['b'],
            'resources': [],
            'sinks': ['test_sink']
        })

        pipeline_manager = pipeline.PipelineManager(self.pipeline_cfg,
                                                    self.transformer_manager)
        with pipeline_manager.publisher(None) as p:
            p([self.test_counter])

        self.test_counter = sample.Sample(
            name='b',
            type=self.test_counter.type,
            volume=self.test_counter.volume,
            unit=self.test_counter.unit,
            user_id=self.test_counter.user_id,
            project_id=self.test_counter.project_id,
            resource_id=self.test_counter.resource_id,
            timestamp=self.test_counter.timestamp,
            resource_metadata=self.test_counter.resource_metadata,
        )

        with pipeline_manager.publisher(None) as p:
            p([self.test_counter])

        self.assertEqual(2, len(pipeline_manager.pipelines))
        self.assertEqual('test_source:test_sink',
                         str(pipeline_manager.pipelines[0]))
        self.assertEqual('second_source:test_sink',
                         str(pipeline_manager.pipelines[1]))
        test_publisher = pipeline_manager.pipelines[0].publishers[0]
        another_publisher = pipeline_manager.pipelines[1].publishers[0]
        for publisher in [test_publisher, another_publisher]:
            self.assertEqual(2, len(publisher.samples))
            self.assertEqual(2, publisher.calls)
            self.assertEqual('a_update', getattr(publisher.samples[0], "name"))
            self.assertEqual('b_update', getattr(publisher.samples[1], "name"))

        transformed_samples = self.TransformerClass.samples
        self.assertEqual(2, len(transformed_samples))
        self.assertEqual(['a', 'b'],
                         [getattr(s, 'name') for s in transformed_samples])

    def test_duplicated_sinks_names(self):
        self.pipeline_cfg['sinks'].append({
            'name': 'test_sink',
            'publishers': ['except'],
        })
        self.assertRaises(pipeline.PipelineException,
                          pipeline.PipelineManager,
                          self.pipeline_cfg,
                          self.transformer_manager)

    def test_duplicated_source_names(self):
        self.pipeline_cfg['sources'].append({
            'name': 'test_source',
            'interval': 5,
            'counters': ['a'],
            'resources': [],
            'sinks': ['test_sink']
        })
        self.assertRaises(pipeline.PipelineException,
                          pipeline.PipelineManager,
                          self.pipeline_cfg,
                          self.transformer_manager)
