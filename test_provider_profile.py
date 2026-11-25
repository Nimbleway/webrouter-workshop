import os
import contextlib
import io
import harness
import unittest
from unittest.mock import patch

from harness import KEYLESS_CREDENTIALS, provider_settings
from web_router.providers.auto import AutoProvider, AutoExtractProvider
from web_router.providers.max import MaxExtractProvider


class ProviderProfileTests(unittest.TestCase):
    def test_keyless_profile_rejects_inherited_credentials(self):
        for name in KEYLESS_CREDENTIALS:
            with self.subTest(name=name), patch.dict(os.environ, {name: 'test-value'}, clear=True):
                with self.assertRaises(ValueError):
                    provider_settings('keyless')

    def test_both_extract_policies_use_the_same_explicit_chain(self):
        with patch.dict(os.environ, {}, clear=True):
            settings = provider_settings('keyless')
            self.assertEqual(AutoProvider(**settings['auto']).members,
                             ('nimble', 'tavily', 'you-mcp', 'exa-mcp', 'parallel-mcp', 'keenable'))
            expected = ('nimble', 'tavily', 'jina', 'firecrawl', 'keenable')
            self.assertEqual(AutoExtractProvider(**settings['auto']).members, expected)
            self.assertEqual(MaxExtractProvider(**settings['max']).members, expected)

    def test_keyless_profile_rejects_provider_overrides_before_client_creation(self):
        for option in ['--search-provider', '--extract-provider']:
            with self.subTest(option=option), patch.dict(os.environ, {}, clear=True), \
                 patch('sys.argv', ['harness.py', '--web', 'webrouter', '--provider-profile', 'keyless', option, 'other']), \
                 patch.object(harness.anthropic, 'Anthropic') as client, contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    harness.main()
                client.assert_not_called()
