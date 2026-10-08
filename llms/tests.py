import json
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import Client, TestCase, TransactionTestCase, override_settings

from llms.models import (
    AABench,
    AAModel,
    APIKey,
    DataSourceConfig,
    LLMModel,
    ModelBenchmark,
    ModelsDevModel,
    ORBench,
    ORModel,
    Provider,
    RankIndex,
    SyncRun,
)
from llms.services.admin_sync import _execute_sync, enqueue_sync, SyncAlreadyRunning
from llms.services.artificial_analysis_sync import sync_artificial_analysis_data
from llms.services.merge_rankindex import merge_and_build_rankindex, normalize_slug
from llms.services.models_dev_sync import sync_models_dev_catalog
from llms.services.rankllms_calculator import calculate_rankllms_index, normalize_percentage
from llms.services.source_http import UpstreamSourceError, fetch_json, get_rate_limit_snapshot
from llms.services.sync_all import run_master_sync
from llms.services.sync_dedicated_tables import sync_artificial_analysis_tables, sync_openrouter_tables
from llms.seo_context import _fmt_pct, _score_cell, models_rows


class RankingFormulaTests(TestCase):
    def test_missing_components_are_omitted_and_weights_are_renormalized(self):
        self.assertEqual(calculate_rankllms_index(components={'intelligence_index': 50}), 50.0)
        self.assertEqual(calculate_rankllms_index(components={'coding_index': 80, 'tokens_per_second': 1}), 80.0)

    def test_percentage_fractions_and_percent_values_are_normalized(self):
        self.assertEqual(normalize_percentage(0.75), 75.0)
        self.assertEqual(normalize_percentage(75), 75.0)
        self.assertIsNone(normalize_percentage(None))
        self.assertIsNone(normalize_percentage(101))

    def test_composite_uses_documented_weights_and_does_not_infer(self):
        score = calculate_rankllms_index(components={
            'intelligence_index': 80,
            'coding_index': 90,
            'agentic_index': 80,
            'gpqa_diamond': 0.75,
            'terminalbench': 0.40,
        })
        self.assertEqual(score, 78.5)
        self.assertIsNone(calculate_rankllms_index(components={}))


class SourceIngestionTests(TestCase):
    @override_settings(OPENROUTER_API_KEY='test-openrouter-key')
    @patch('llms.services.sync_dedicated_tables.fetch_json')
    def test_openrouter_catalog_prices_are_converted_to_usd_per_million(self, fetch):
        fetch.side_effect = [
            {'data': [{
                'id': 'openai/gpt-4o',
                'name': 'GPT-4o',
                'context_length': 128000,
                'pricing': {'prompt': '0.0000025', 'completion': '0.00001'},
                'architecture': {'modality': 'text+image->text'},
                'top_provider': {},
            }]},
            {'data': [{
                'source': 'openrouter',
                'model_permaslug': 'openai/gpt-4o',
                'benchmark_type': 'gpqa_diamond',
                'accuracy': 0.75,
            }]},
        ]
        result = sync_openrouter_tables()
        row = ORModel.objects.get(openrouter_id='openai/gpt-4o')
        self.assertEqual(row.prompt_price_per_1m, Decimal('2.500000'))
        self.assertEqual(row.completion_price_per_1m, Decimal('10.000000'))
        self.assertEqual(result['models_fetched'], 1)
        self.assertEqual(ORBench.objects.count(), 1)

    @patch('llms.services.sync_dedicated_tables.fetch_json', return_value={'data': []})
    def test_empty_openrouter_snapshot_does_not_delete_existing_rows(self, _fetch):
        ORModel.objects.create(openrouter_id='openai/old', name='Old', raw_json={})
        with self.assertRaises(UpstreamSourceError):
            sync_openrouter_tables()
        self.assertTrue(ORModel.objects.filter(openrouter_id='openai/old').exists())

    @patch('llms.services.artificial_analysis_client.fetch_json')
    def test_artificial_analysis_pagination_and_duplicate_page_rows(self, fetch):
        first = {
            'data': [{'id': 'model-one', 'slug': 'model-one'}],
            'pagination': {'page': 1, 'total_pages': 2},
        }
        second = {
            'data': [{'id': 'model-two', 'slug': 'model-two'}, {'id': 'model-one', 'slug': 'model-one'}],
            'pagination': {'page': 2, 'total_pages': 2},
        }
        fetch.side_effect = [first, second]
        with override_settings(ARTIFICIAL_ANALYSIS_API_KEY='test-aa-key'):
            from llms.services.artificial_analysis_client import fetch_language_models
            models = fetch_language_models()
        self.assertEqual([model['slug'] for model in models], ['model-one', 'model-two'])
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(fetch.call_args_list[0].kwargs['params'], {'page': 1})

    @override_settings(ARTIFICIAL_ANALYSIS_API_KEY='test-aa-key')
    @patch('llms.services.artificial_analysis_client.fetch_json', return_value={'data': []})
    def test_aa_media_client_uses_documented_free_media_routes(self, fetch):
        from llms.services.artificial_analysis_client import MEDIA_ENDPOINTS, fetch_media_models
        datasets = fetch_media_models()
        expected = sum(len(endpoints) for endpoints in MEDIA_ENDPOINTS.values())
        self.assertEqual(fetch.call_count, expected)
        self.assertEqual(len(datasets), expected)
        self.assertIn('media/text-to-image/models/free', datasets)
        self.assertEqual(fetch.call_args.kwargs['headers']['x-api-key'], 'test-aa-key')

    @patch('llms.services.sync_dedicated_tables.fetch_media_models', return_value={})
    @patch('llms.services.sync_dedicated_tables.fetch_language_models')
    def test_artificial_analysis_snapshots_keep_unknown_values_empty(self, fetch, _media_fetch):
        fetch.return_value = [{
            'id': 'gpt-4o',
            'slug': 'gpt-4o',
            'name': 'GPT-4o',
            'release_date': '2024-05-13',
            'model_creator': {'name': 'OpenAI', 'slug': 'openai'},
            'evaluations': {
                'artificial_analysis_intelligence_index': 75.0,
                'artificial_analysis_coding_index': 70.0,
                'artificial_analysis_agentic_index': 68.0,
                'artificial_analysis_finance_and_accounting_index': 71.0,
                'artificial_analysis_strategy_and_ops_index': 72.0,
                'artificial_analysis_legal_index': 73.0,
                'artificial_analysis_healthcare_and_medical_index': 74.0,
                'artificial_analysis_engineering_index': 75.0,
                'artificial_analysis_economics_index': 76.0,
            },
            'performance': {
                'median_output_tokens_per_second': 30.0,
                'median_time_to_first_token_seconds': 0.5,
                'median_time_to_first_answer_token_seconds': 0.7,
                'median_end_to_end_response_time_seconds': 3.5,
            },
            'pricing': {
                'price_1m_input_tokens': 3.0,
                'price_1m_output_tokens': 12.0,
                'price_1m_cache_hit_tokens': 0.3,
                'price_1m_cache_write_tokens': 3.75,
            },
        }]
        result = sync_artificial_analysis_tables()
        row = AAModel.objects.get(slug='gpt-4o')
        self.assertIsNone(row.context_window)
        self.assertEqual(row.release_date.isoformat(), '2024-05-13')
        self.assertEqual(result['models_fetched'], 1)
        benchmark = AABench.objects.get()
        self.assertEqual(benchmark.agentic_index, 68.0)
        self.assertEqual(benchmark.finance_and_accounting_index, 71.0)
        self.assertEqual(benchmark.economics_index, 76.0)
        self.assertEqual(benchmark.time_to_first_answer_token, 0.7)
        self.assertEqual(benchmark.end_to_end_response_time, 3.5)
        model = AAModel.objects.get(slug='gpt-4o')
        self.assertEqual(model.cache_hit_price_per_1m, Decimal('0.3'))
        self.assertEqual(model.cache_write_price_per_1m, Decimal('3.75'))

    @patch('llms.services.sync_dedicated_tables.fetch_media_models', return_value={})
    @patch('llms.services.sync_dedicated_tables.fetch_language_models')
    def test_artificial_analysis_duplicate_slug_variants_preserve_previous_snapshot(self, fetch, _media_fetch):
        AAModel.objects.create(slug='kept', name='Kept', creator_name='OpenAI', raw_json={})
        fetch.return_value = [
            {'id': 'record-1', 'slug': 'same-model', 'name': 'Model (high)', 'model_creator': {'name': 'OpenAI'}},
            {'id': 'record-2', 'slug': 'same-model', 'name': 'Model (low)', 'model_creator': {'name': 'OpenAI'}},
        ]
        with self.assertRaisesRegex(UpstreamSourceError, 'multiple records'):
            sync_artificial_analysis_tables()
        self.assertTrue(AAModel.objects.filter(slug='kept').exists())

    @patch('llms.services.sync_dedicated_tables.fetch_media_models')
    @patch('llms.services.sync_dedicated_tables.fetch_language_models')
    def test_artificial_analysis_media_task_metrics_are_preserved_without_invented_price(self, language_fetch, media_fetch):
        language_fetch.return_value = [{
            'id': 'language-id', 'slug': 'gpt-4o', 'name': 'GPT-4o',
            'model_creator': {'name': 'OpenAI', 'slug': 'openai'},
        }]
        media_fetch.return_value = {
            'media/speech-to-text/models/free': ('audio', [{
                'id': 'speech-uuid', 'name': 'Speech recognition model',
                'model_creator': {'name': 'OpenAI'}, 'aa_wer_index': 82.0,
            }]),
        }
        result = sync_artificial_analysis_tables()
        model = AAModel.objects.get(source_id='speech-uuid')
        benchmark = AABench.objects.get(source_id='speech-uuid')
        self.assertEqual(model.model_type, 'audio')
        self.assertEqual(model.modalities, {'input': ['audio'], 'output': ['text']})
        self.assertIsNone(benchmark.price_per_unit)
        self.assertIsNone(benchmark.samples)
        self.assertEqual(benchmark.raw_json['aa_wer_index'], 82.0)
        self.assertEqual(result['media_models_fetched'], 1)

        from llms.services.sync_dedicated_tables import _media_pricing
        self.assertEqual(
            _media_pricing({'price_per_1m_characters': 4.25}),
            (Decimal('4.25'), '1m characters'),
        )

    @patch('llms.services.sync_dedicated_tables.fetch_media_models', return_value={'media/text-to-image/models/free': ('image', [])})
    @patch('llms.services.sync_dedicated_tables.fetch_language_models')
    def test_empty_media_endpoint_preserves_last_media_records(self, language_fetch, _media_fetch):
        language_fetch.return_value = [{'id': 'language-id', 'slug': 'gpt-4o', 'name': 'GPT-4o'}]
        AAModel.objects.create(
            slug='image-old', source_id='old-id', source_slug='old', source_endpoint='media/text-to-image/models/free',
            name='Old image', creator_name='OpenAI', model_type='image', raw_json={'id': 'old-id'},
        )
        result = sync_artificial_analysis_tables()
        self.assertTrue(AAModel.objects.filter(source_id='old-id').exists())
        self.assertEqual(result['stale_models_preserved'], 1)

    @patch('llms.services.artificial_analysis_sync.fetch_language_models')
    def test_aa_main_catalog_does_not_derive_missing_scores(self, fetch):
        fetch.return_value = [{
            'id': 'gpt-4o',
            'slug': 'gpt-4o',
            'name': 'GPT-4o',
            'model_creator': {'name': 'OpenAI', 'slug': 'openai'},
            'evaluations': {'artificial_analysis_intelligence_index': 75.0},
        }]
        result = sync_artificial_analysis_data()
        model = LLMModel.objects.get(openrouter_id='aa/openai/gpt-4o')
        self.assertEqual(model.is_open_weight, None)
        self.assertEqual(result['models_added'], 1)
        benchmark = ModelBenchmark.objects.get(model=model)
        self.assertEqual(benchmark.intelligence_index, 75.0)
        self.assertIsNone(benchmark.coding_index)
        self.assertIsNone(benchmark.agentic_index)
        self.assertIsNone(benchmark.arena_elo)
        self.assertIsNone(benchmark.swe_bench_score)

    @patch('llms.services.models_dev_sync.fetch_json')
    def test_modelsdev_fields_preserve_nulls_and_price_units(self, fetch):
        fetch.return_value = {
            'openai': {
                'name': 'OpenAI',
                'doc': 'https://platform.openai.com/docs',
                'models': {
                    'gpt-4o': {
                        'id': 'openai/gpt-4o',
                        'name': 'GPT-4o',
                        'cost': {'input': 2.5, 'output': 10},
                        'limit': {'context': 128000, 'output': 16384},
                        'modalities': {'input': ['text', 'image'], 'output': ['text']},
                        'reasoning': True,
                        'tool_call': True,
                        'open_weights': False,
                    },
                    'unknown': {'id': 'openai/unknown', 'name': 'Unknown'},
                },
            },
        }
        summary = sync_models_dev_catalog()
        row = ModelsDevModel.objects.get(modelsdev_id='openai/gpt-4o')
        unknown = ModelsDevModel.objects.get(modelsdev_id='openai/unknown')
        self.assertEqual(row.prompt_price_per_1m, Decimal('2.5'))
        self.assertEqual(row.context_length, 128000)
        self.assertIsNone(unknown.prompt_price_per_1m)
        self.assertIsNone(unknown.context_length)
        self.assertEqual(summary['models_fetched'], 2)

    @patch('llms.services.models_dev_sync.fetch_json', return_value=[])
    def test_malformed_modelsdev_response_keeps_existing_snapshot(self, _fetch):
        ModelsDevModel.objects.create(
            modelsdev_id='openai/kept', provider_slug='openai', name='Kept', raw_json={}
        )
        with self.assertRaises(UpstreamSourceError):
            sync_models_dev_catalog()
        self.assertTrue(ModelsDevModel.objects.filter(modelsdev_id='openai/kept').exists())

    @patch('llms.services.source_http.time.sleep')
    @patch('llms.services.source_http.requests.Session')
    def test_upstream_rate_limit_is_reported_without_response_body(self, session_factory, _sleep):
        session = session_factory.return_value
        session.get.return_value.status_code = 429
        session.get.return_value.headers = {
            'Retry-After': '2',
            'X-AA-Tier': 'free',
            'X-RateLimit-Limit': '100',
            'X-RateLimit-Remaining': '0',
        }
        with self.assertRaisesRegex(UpstreamSourceError, 'HTTP 429'):
            fetch_json('openrouter', 'https://openrouter.ai/api/v1/models')
        self.assertNotIn('response body', str(session.get.return_value))
        retries = session.mount.call_args_list[0].args[1].max_retries
        self.assertEqual(retries.total, 2)
        self.assertEqual(retries.retry_after_cap_seconds, 30)
        self.assertEqual(session.get.call_count, 3)
        self.assertEqual(get_rate_limit_snapshot('openrouter')['tier'], 'free')
        self.assertEqual(get_rate_limit_snapshot('openrouter')['remaining'], '0')


class ConservativeMergeTests(TestCase):
    def make_openrouter(self, model_id, *, canonical_slug='', name='GPT-4o'):
        return ORModel.objects.create(
            openrouter_id=model_id,
            canonical_slug=canonical_slug,
            name=name,
            author=model_id.split('/')[0],
            context_length=128000,
            prompt_price_per_1m=Decimal('2.5'),
            completion_price_per_1m=Decimal('10'),
            raw_json={'pricing': {'prompt': '0.0000025', 'completion': '0.00001'}, 'context_length': 128000},
        )

    def test_same_provider_exact_version_joins_and_conflicts_keep_raw_attribution(self):
        self.make_openrouter('openai/gpt-4o', canonical_slug='gpt-4o')
        AAModel.objects.create(
            slug='gpt-4o', name='GPT-4o', creator_name='OpenAI', creator_slug='openai',
            raw_json={
                'evaluations': {
                    'artificial_analysis_intelligence_index': 75,
                    'artificial_analysis_coding_index': 65,
                    'artificial_analysis_agentic_index': 80,
                    'artificial_analysis_finance_and_accounting_index': 71,
                    'artificial_analysis_strategy_and_ops_index': 72,
                    'artificial_analysis_legal_index': 73,
                    'artificial_analysis_healthcare_and_medical_index': 74,
                    'artificial_analysis_engineering_index': 75,
                    'artificial_analysis_economics_index': 76,
                    'gpqa': 0.75,
                },
                'performance': {
                    'median_output_tokens_per_second': 38.0,
                    'median_time_to_first_token_seconds': 0.5,
                    'median_time_to_first_answer_token_seconds': 0.7,
                    'median_end_to_end_response_time_seconds': 3.5,
                },
                'pricing': {
                    'price_1m_input_tokens': 3,
                    'price_1m_output_tokens': 11,
                    'price_1m_cache_hit_tokens': 0.5,
                    'price_1m_cache_write_tokens': 4,
                },
            },
        )
        AABench.objects.create(
            model_slug='gpt-4o', model_name='GPT-4o', creator_name='OpenAI',
            intelligence_index=75, coding_index=65, agentic_index=80,
            finance_and_accounting_index=71,
            raw_json={'evaluations': {
                'artificial_analysis_intelligence_index': 75,
                'artificial_analysis_coding_index': 65,
                'artificial_analysis_agentic_index': 80,
                'artificial_analysis_finance_and_accounting_index': 71,
                'gpqa': 0.75,
            }},
        )
        ORBench.objects.create(
            model_permaslug='openai/gpt-4o', display_name='GPT-4o', source='openrouter',
            benchmark_type='gpqa_diamond', accuracy=0.75, raw_json={'accuracy': 0.75},
        )
        ModelsDevModel.objects.create(
            modelsdev_id='openai/gpt-4o', provider_slug='openai', provider_name='OpenAI', name='GPT-4o',
            context_length=128000,
            prompt_price_per_1m=Decimal('2.5'), completion_price_per_1m=Decimal('10'),
            raw_json={'cost': {'input': 2.5, 'output': 10}, 'limit': {'context': 128000}, 'open_weights': False},
        )

        report = merge_and_build_rankindex()
        self.assertEqual(RankIndex.objects.count(), 1)
        row = RankIndex.objects.get()
        self.assertEqual(row.sources, ['openrouter', 'artificial-analysis', 'models.dev'])
        self.assertEqual(row.intelligence_index, 75)
        self.assertEqual(row.agentic_index, 80)
        self.assertEqual(row.finance_and_accounting_index, 71)
        self.assertEqual(row.economics_index, 76)
        self.assertEqual(row.time_to_first_answer_token, 0.7)
        self.assertEqual(row.end_to_end_response_time, 3.5)
        self.assertEqual(row.aa_cache_hit_price_per_1m, Decimal('0.5'))
        self.assertEqual(row.aa_cache_write_price_per_1m, Decimal('4'))
        self.assertEqual(row.gpqa_diamond, 75)
        self.assertEqual(row.agentic_index, 80)
        self.assertEqual(row.finance_and_accounting_index, 71)
        self.assertEqual(row.rankllms_index, 72.5)
        self.assertEqual(row.prompt_price_per_1m, Decimal('2.5'))
        self.assertEqual(report['conflicts'], 1)
        self.assertEqual(row.raw_data['openrouter']['pricing']['prompt'], '0.0000025')
        self.assertEqual(row.raw_data['artificial_analysis']['pricing']['price_1m_input_tokens'], 3)
        self.assertIn('openai/gpt-4o', row.aliases)

    def test_versions_and_providers_are_not_collapsed(self):
        self.make_openrouter('openai/gpt-4o-2024-05-13', canonical_slug='gpt-4o-2024-05-13')
        self.make_openrouter('anthropic/gpt-4o', canonical_slug='gpt-4o', name='GPT-4o')
        AAModel.objects.create(
            slug='gpt-4o', name='GPT-4o', creator_name='OpenAI', creator_slug='openai', raw_json={},
        )
        report = merge_and_build_rankindex()
        self.assertEqual(RankIndex.objects.count(), 3)
        self.assertEqual(report['ambiguous_matches'], 0)
        self.assertEqual(normalize_slug('gpt-4o-2024-05-13'), 'gpt-4o-2024-05-13')

    def test_ambiguous_alias_does_not_auto_merge(self):
        self.make_openrouter('openai/gpt.4o', canonical_slug='gpt-4o')
        self.make_openrouter('openai/gpt-4o', canonical_slug='gpt-4o', name='GPT-4o')
        AAModel.objects.create(
            slug='gpt-4o', name='GPT-4o', creator_name='OpenAI', creator_slug='openai', raw_json={},
        )
        report = merge_and_build_rankindex()
        self.assertEqual(report['ambiguous_matches'], 1)
        self.assertEqual(RankIndex.objects.count(), 3)

    def test_repeated_merge_is_idempotent(self):
        self.make_openrouter('openai/gpt-4o', canonical_slug='gpt-4o')
        merge_and_build_rankindex()
        first = list(RankIndex.objects.values('canonical_slug', 'name', 'openrouter_id'))
        merge_and_build_rankindex()
        self.assertEqual(list(RankIndex.objects.values('canonical_slug', 'name', 'openrouter_id')), first)

    def test_modelsdev_explicit_canonical_id_links_a_provider_alias(self):
        self.make_openrouter('openai/gpt-4o', canonical_slug='gpt-4o')
        ModelsDevModel.objects.create(
            modelsdev_id='azure/gpt-4o-deployment',
            canonical_model_id='openai/gpt-4o',
            provider_slug='azure',
            provider_name='Azure',
            name='GPT-4o deployment',
            raw_json={'canonical_model_id': 'openai/gpt-4o', 'cost': {'input': 3, 'output': 12}},
        )
        report = merge_and_build_rankindex()
        self.assertEqual(RankIndex.objects.count(), 1)
        row = RankIndex.objects.get()
        self.assertIn('azure/gpt-4o-deployment', row.aliases)
        self.assertIn('models.dev', row.sources)
        self.assertEqual(report['unmatched_modelsdev'], 0)

    def test_media_task_metrics_are_canonical_without_language_model_scores(self):
        AAModel.objects.create(
            slug='audio-speech-to-text-openai-model', source_id='speech-uuid',
            source_slug='speech-uuid', source_endpoint='media/speech-to-text/models/free',
            name='Speech recognition model', creator_name='OpenAI', creator_slug='openai', model_type='audio',
            modalities={'input': ['audio'], 'output': ['text']}, raw_json={'id': 'speech-uuid'},
        )
        AABench.objects.create(
            model_slug='audio-speech-to-text-openai-model', source_id='speech-uuid',
            source_slug='speech-uuid', source_endpoint='media/speech-to-text/models/free',
            model_name='Speech recognition model', creator_name='OpenAI',
            raw_json={'id': 'speech-uuid', 'aa_wer_index': 82.0},
        )
        merge_and_build_rankindex()
        row = RankIndex.objects.get(category='audio')
        self.assertIsNone(row.rankllms_index)
        self.assertEqual(row.media_metrics['aa_wer_index'], 82.0)
        self.assertIsNone(row.media_metrics['price_per_unit'])


class APIAndAdminSecurityTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user_model = get_user_model()

    def test_api_and_model_errors_use_expected_status_codes(self):
        self.assertEqual(self.client.get('/api/v1/models/unknown-model').status_code, 404)
        self.assertEqual(self.client.get('/api/v1/compare').status_code, 400)
        self.assertEqual(self.client.get('/api/v1/compare?model_a=one&model_b=two').status_code, 404)
        self.assertEqual(self.client.get('/api/v1/models?limit=0').status_code, 400)

    def test_public_catalog_empty_response_and_pagination(self):
        response = self.client.get('/api/v1/models?limit=5&offset=0')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['total'], 0)
        self.assertEqual(response.json()['items'], [])

    def test_server_rendered_catalog_keeps_zero_distinct_from_missing(self):
        self.assertEqual(_fmt_pct(0), '0.0%')
        self.assertEqual(_score_cell(None), '<td class="score">—</td>')
        self.assertEqual(_score_cell(0), '<td class="score">0.0</td>')
        RankIndex.objects.create(
            canonical_slug='sample-zero-score', name='Sample', provider='Example',
            agentic_index=0,
        )
        markup = models_rows(limit=1)
        self.assertEqual(markup.count('<td'), 15)
        self.assertIn('<td class="score">0.0</td>', markup)
        self.assertIn('<td class="num lb-rank">—</td>', markup)

    def test_changed_public_pages_render_with_an_empty_catalog(self):
        for path in (
            '/', '/leaderboard', '/llm-leaderboard', '/rankllms', '/rankllms/models',
            '/aabanch', '/aamodels', '/orbench', '/ormodels', '/modelsdev',
            '/benchmarks', '/compare', '/cards', '/agent-guide',
        ):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
        catalog = self.client.get('/rankllms/models')
        self.assertContains(catalog, 'Sort: Agentic')
        self.assertContains(catalog, 'Agentic')

    def test_aa_and_canonical_endpoints_expose_agentic_capability_and_latency_fields(self):
        RankIndex.objects.create(
            canonical_slug='openai-gpt-4o', name='GPT-4o', provider='OpenAI',
            agentic_index=80, finance_and_accounting_index=71,
            time_to_first_answer_token=0.7, end_to_end_response_time=3.5,
            aa_cache_hit_price_per_1m=Decimal('0.5'), aa_cache_write_price_per_1m=Decimal('4'),
            category='audio', media_metrics={'aa_wer_index': 82.0},
        )
        AABench.objects.create(
            model_slug='openai-gpt-4o', model_name='GPT-4o', creator_name='OpenAI',
            agentic_index=80, finance_and_accounting_index=71,
            time_to_first_answer_token=0.7, end_to_end_response_time=3.5,
        )
        AAModel.objects.create(
            slug='openai-gpt-4o', name='GPT-4o', creator_name='OpenAI',
            cache_hit_price_per_1m=Decimal('0.5'), cache_write_price_per_1m=Decimal('4'),
        )

        canonical = self.client.get('/api/v1/rankindex?sort_by=agentic').json()['items'][0]
        leaderboard = self.client.get('/api/v1/leaderboard/rankindex?sort_by=agentic').json()['rankings'][0]
        aa = self.client.get('/api/v1/aabanch?sort_by=agentic').json()['items'][0]
        for row in (canonical, leaderboard, aa):
            self.assertEqual(row['agentic_index'], 80)
            self.assertEqual(row['finance_and_accounting_index'], 71)
            self.assertEqual(row['time_to_first_answer_token'], 0.7)
            self.assertEqual(row['end_to_end_response_time'], 3.5)
        self.assertEqual(leaderboard['media_metrics']['aa_wer_index'], 82.0)
        aa_model = self.client.get('/api/v1/aamodels').json()['items'][0]
        self.assertEqual(aa_model['cache_hit_price_per_1m'], '0.500000')
        self.assertEqual(aa_model['cache_write_price_per_1m'], '4.000000')

    def test_custom_domain_and_render_host_are_allowed_but_unknown_host_is_rejected(self):
        self.assertEqual(self.client.get('/health', HTTP_HOST='api.rankllms.com').status_code, 200)
        self.assertEqual(self.client.get('/health', HTTP_HOST='rankllms-engine-kqso.onrender.com').status_code, 200)
        self.assertEqual(self.client.get('/health', HTTP_HOST='attacker.invalid').status_code, 400)

    def test_api_key_management_is_staff_only_and_list_masks_secret(self):
        payload = {'name': 'Internal testing key', 'tier': 'free'}
        anonymous = self.client.post('/api/v1/keys/generate', data=json.dumps(payload), content_type='application/json')
        self.assertNotEqual(anonymous.status_code, 200)

        regular_user = self.user_model.objects.create_user(username='reader', password='test-pass')
        self.client.force_login(regular_user)
        denied = self.client.get('/api/v1/keys')
        self.assertEqual(denied.status_code, 403)

        staff = self.user_model.objects.create_user(username='operator', password='test-pass', is_staff=True)
        self.client.force_login(staff)
        created = self.client.post('/api/v1/keys/generate', data=json.dumps(payload), content_type='application/json')
        self.assertEqual(created.status_code, 200)
        raw_key = created.json()['key']
        listed = self.client.get('/api/v1/keys')
        self.assertEqual(listed.status_code, 200)
        self.assertNotIn('key', listed.json()[0])
        self.assertEqual(listed.json()[0]['key_preview'], raw_key[:12] + '…')

    def test_settings_page_requires_staff_authentication(self):
        self.assertEqual(self.client.get('/settings/data-sync/').status_code, 302)
        staff = self.user_model.objects.create_user(username='operator', password='test-pass', is_staff=True)
        self.client.force_login(staff)
        response = self.client.get('/settings/data-sync/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Data sync settings')
        self.assertContains(response, 'Dry run')

    @patch('llms.api.enqueue_sync', return_value=SimpleNamespace(pk=42))
    def test_sync_api_is_staff_only_and_accepted_as_background_job(self, enqueue):
        self.assertNotEqual(self.client.post('/api/v1/sync').status_code, 202)
        staff = self.user_model.objects.create_user(username='operator', password='test-pass', is_staff=True)
        self.client.force_login(staff)
        response = self.client.post('/api/v1/sync')
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()['run_id'], 42)
        enqueue.assert_called_once()

    @patch('llms.api.enqueue_sync', return_value=SimpleNamespace(pk=43))
    def test_staff_sync_api_enforces_session_csrf(self, enqueue):
        client = Client(enforce_csrf_checks=True)
        staff = self.user_model.objects.create_user(
            username='csrf-operator', password='test-pass', is_staff=True
        )
        client.force_login(staff)
        self.assertEqual(client.post('/api/v1/sync').status_code, 403)

        page = client.get('/settings/data-sync/')
        self.assertEqual(page.status_code, 200)
        csrf_token = client.cookies['csrftoken'].value
        response = client.post('/api/v1/sync', HTTP_X_CSRFTOKEN=csrf_token)
        self.assertEqual(response.status_code, 202)
        enqueue.assert_called_once()


class SyncRunTests(TestCase):
    @patch('llms.services.admin_sync.threading.Thread')
    def test_database_active_lock_rejects_a_second_sync(self, thread_class):
        thread_class.return_value.start.return_value = None
        enqueue_sync(source='openrouter')
        with self.assertRaises(SyncAlreadyRunning):
            enqueue_sync(source='all')
        SyncRun.objects.filter(active_key='active').update(active_key=None)

    @patch('llms.services.admin_sync.prepare_source_snapshots', return_value={
        'selected': ('openrouter', 'artificial_analysis', 'models_dev'),
        'enabled': {'openrouter': True, 'artificial_analysis': True, 'models_dev': True},
        'snapshots': {},
        'errors': {},
    })
    @patch('llms.services.admin_sync.run_master_sync')
    def test_dry_run_rolls_back_data_and_persists_report(self, run_master, _prepare):
        run = SyncRun.objects.create(source='all', dry_run=True, status='queued', active_key='active')

        def fake_sync(sources=None, prepared=None):
            Provider.objects.create(slug='preview-only', name='Preview only')
            return {
                'status': 'succeeded', 'sources': [], 'records_received': 4,
                'records_added': 1, 'records_updated': 2, 'records_skipped': 0,
                'elapsed_seconds': 0.1,
            }

        run_master.side_effect = fake_sync
        _execute_sync(run.pk)
        run.refresh_from_db()
        self.assertFalse(Provider.objects.filter(slug='preview-only').exists())
        self.assertEqual(run.status, 'dry_run')
        self.assertEqual(run.records_received, 4)
        self.assertEqual(run.records_added, 1)
        self.assertIsNone(run.active_key)

    @patch('llms.services.admin_sync.run_master_sync')
    def test_successful_run_persists_real_counts(self, run_master):
        run = SyncRun.objects.create(source='models_dev', status='queued', active_key='active')
        run_master.return_value = {
            'status': 'succeeded', 'sources': [], 'records_received': 3,
            'records_added': 2, 'records_updated': 1, 'records_skipped': 0,
        }
        _execute_sync(run.pk)
        run.refresh_from_db()
        self.assertEqual(run.status, 'succeeded')
        self.assertEqual(run.records_received, 3)
        self.assertEqual(run.records_added, 2)
        self.assertIsNotNone(run.finished_at)

    @patch('llms.services.sync_all.fetch_openrouter_snapshot', side_effect=UpstreamSourceError('openrouter', 'HTTP 503'))
    @patch('llms.services.sync_all.merge_and_build_rankindex')
    def test_full_source_failure_preserves_last_source_snapshot(self, merge, _fetch):
        ORModel.objects.create(openrouter_id='openai/kept', name='Kept', raw_json={})
        report = run_master_sync(sources=['openrouter'])
        self.assertEqual(report['status'], 'failed')
        self.assertTrue(ORModel.objects.filter(openrouter_id='openai/kept').exists())
        merge.assert_not_called()

    @patch('llms.services.sync_all.fetch_models_dev_catalog', return_value={'providers': {}})
    @patch('llms.services.sync_all.fetch_openrouter_snapshot', side_effect=UpstreamSourceError('openrouter', 'HTTP 503'))
    @patch('llms.services.sync_all.sync_models_dev_catalog', return_value={'models_fetched': 2, 'created': 1, 'updated': 0})
    @patch('llms.services.sync_all.merge_and_build_rankindex', return_value={'status': 'success', 'total_merged_models': 1})
    def test_partial_source_failure_is_reported_without_blocking_healthy_source(self, merge, modelsdev, _openrouter_fetch, modelsdev_fetch):
        report = run_master_sync(sources=['openrouter', 'models_dev'])
        self.assertEqual(report['status'], 'partial')
        self.assertEqual(report['sources_successful'], 1)
        self.assertEqual(report['sources_failed'], 1)
        self.assertEqual(report['records_received'], 2)
        modelsdev.assert_called_once_with(snapshot={'providers': {}})
        merge.assert_called_once()

    @patch('llms.services.sync_all.sync_models_dev_catalog')
    def test_disabled_source_is_skipped(self, sync):
        DataSourceConfig.objects.create(source='models_dev', enabled=False)
        report = run_master_sync(sources=['models_dev'])
        self.assertEqual(report['status'], 'skipped')
        self.assertEqual(report['sources'][0]['status'], 'disabled')
        sync.assert_not_called()


class SourceTransactionBoundaryTests(TransactionTestCase):
    def test_dry_run_prefetches_before_rollback_transaction(self):
        run = SyncRun.objects.create(
            source='all', dry_run=True, status='queued', active_key='active'
        )

        def prepare(sources=None):
            self.assertFalse(connection.in_atomic_block)
            return {'selected': (), 'enabled': {}, 'snapshots': {}, 'errors': {}}

        def fake_sync(sources=None, prepared=None):
            Provider.objects.create(slug='dry-run-only', name='Preview')
            return {'status': 'succeeded', 'sources': [], 'records_received': 0}

        with patch('llms.services.admin_sync.prepare_source_snapshots', side_effect=prepare):
            with patch('llms.services.admin_sync.run_master_sync', side_effect=fake_sync):
                _execute_sync(run.pk)
        self.assertFalse(Provider.objects.filter(slug='dry-run-only').exists())

    def test_artificial_analysis_language_and_media_fetches_precede_write_transaction(self):
        def fetch_language():
            self.assertFalse(connection.in_atomic_block)
            return [{'id': 'aa-model', 'slug': 'aa-model'}]

        def fetch_media():
            self.assertFalse(connection.in_atomic_block)
            return {}

        with patch('llms.services.sync_all.fetch_language_models', side_effect=fetch_language):
            with patch('llms.services.sync_all.fetch_media_models', side_effect=fetch_media):
                with patch('llms.services.sync_all.sync_artificial_analysis_data', return_value={}):
                    with patch('llms.services.sync_all.sync_artificial_analysis_tables', return_value={}):
                        with patch('llms.services.sync_all.merge_and_build_rankindex', return_value={'status': 'success'}):
                            report = run_master_sync(sources=['artificial_analysis'])
        self.assertEqual(report['status'], 'succeeded')

    def test_openrouter_network_fetch_happens_before_snapshot_transaction(self):
        from llms.services.openrouter_sync import sync_openrouter_models

        def fetch(*_args, **_kwargs):
            self.assertFalse(connection.in_atomic_block)
            return {'data': [{'id': 'openai/gpt-4o'}]}

        with override_settings(OPENROUTER_API_KEY=''):
            with patch('llms.services.openrouter_sync.fetch_json', side_effect=fetch):
                with patch('llms.services.openrouter_sync._sync_openrouter_snapshot', return_value={'status': 'ok'}):
                    self.assertEqual(sync_openrouter_models(), {'status': 'ok'})

    def test_models_dev_network_fetch_happens_before_snapshot_transaction(self):
        from llms.services.models_dev_sync import sync_models_dev_catalog

        def fetch(*_args, **_kwargs):
            self.assertFalse(connection.in_atomic_block)
            return {'openai': {'models': {'gpt-4o': {'id': 'openai/gpt-4o'}}}}

        with patch('llms.services.models_dev_sync.fetch_json', side_effect=fetch):
            with patch('llms.services.models_dev_sync._sync_models_dev_snapshot', return_value={'status': 'ok'}):
                self.assertEqual(sync_models_dev_catalog(), {'status': 'ok'})
