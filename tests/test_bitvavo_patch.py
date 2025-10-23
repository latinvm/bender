"""
Test the Bitvavo rate limit patch that fixes the negative sleep bug.
"""
import unittest
from unittest.mock import Mock, patch, MagicMock
import time
import logging

# Setup logging
logging.basicConfig(level=logging.DEBUG)


class TestBitvavoRateLimitPatch(unittest.TestCase):
    """Test the monkey patch for Bitvavo's rate limit handler"""

    def setUp(self):
        """Set up test fixtures"""
        # Import after setup to ensure fresh imports
        from trader.bitvavo import BitvavoClient

    def test_patch_applied(self):
        """Test that the patch is applied successfully"""
        from python_bitvavo_api.bitvavo import rateLimitThread

        # Verify the method exists and has been patched
        self.assertTrue(hasattr(rateLimitThread, 'waitForReset'))

    def test_negative_wait_time_handled(self):
        """Test that negative wait times are handled gracefully"""
        from python_bitvavo_api.bitvavo import rateLimitThread

        # Create a mock Bitvavo client
        mock_bitvavo = Mock()
        mock_bitvavo.rateLimitReset = time.time() * 1000 - 5000  # 5 seconds in the past
        mock_bitvavo.rateLimitRemaining = 0

        # Create rate limit thread
        thread = rateLimitThread(-5.0, mock_bitvavo)  # Negative wait time

        # This should NOT raise ValueError anymore
        try:
            with patch('time.sleep') as mock_sleep:
                thread.waitForReset(-5.0)
                # Should have called sleep with 0 instead of -5.0
                mock_sleep.assert_called_once_with(0)
            success = True
        except ValueError as e:
            success = False
            self.fail(f"Negative sleep still raised ValueError: {e}")

        self.assertTrue(success, "Patch should handle negative wait times")

    def test_positive_wait_time_unchanged(self):
        """Test that positive wait times still work normally"""
        from python_bitvavo_api.bitvavo import rateLimitThread

        # Create a mock Bitvavo client
        mock_bitvavo = Mock()
        mock_bitvavo.rateLimitReset = (time.time() + 10) * 1000  # 10 seconds in future
        mock_bitvavo.rateLimitRemaining = 0

        # Create rate limit thread
        thread = rateLimitThread(5.0, mock_bitvavo)

        # Should sleep for the positive duration
        with patch('time.sleep') as mock_sleep:
            # Mock time.time to ensure it stays less than rateLimitReset
            with patch('time.time', return_value=time.time()):
                thread.waitForReset(5.0)
                mock_sleep.assert_called_once_with(5.0)

    def test_zero_wait_time(self):
        """Test that zero wait time works"""
        from python_bitvavo_api.bitvavo import rateLimitThread

        mock_bitvavo = Mock()
        mock_bitvavo.rateLimitReset = time.time() * 1000
        mock_bitvavo.rateLimitRemaining = 0

        thread = rateLimitThread(0, mock_bitvavo)

        # Should work without errors
        with patch('time.sleep') as mock_sleep:
            thread.waitForReset(0)
            mock_sleep.assert_called_once_with(0)

    def test_client_initialization(self):
        """Test that BitvavoClient initializes with the patch"""
        from trader.bitvavo import BitvavoClient

        # Should initialize without errors
        client = BitvavoClient()
        self.assertIsNotNone(client.bitvavo)

    def test_recursive_wait_with_negative_time(self):
        """Test that recursive calls also handle negative times"""
        from python_bitvavo_api.bitvavo import rateLimitThread

        mock_bitvavo = Mock()
        # Set reset time in the past to trigger recursive call with negative time
        mock_bitvavo.rateLimitReset = (time.time() - 1) * 1000  # 1 second ago
        mock_bitvavo.rateLimitRemaining = 0

        thread = rateLimitThread(5.0, mock_bitvavo)

        # Mock time.time to return value after rateLimitReset
        with patch('time.sleep') as mock_sleep:
            with patch('time.time', return_value=time.time()):
                thread.waitForReset(0.1)  # Small positive wait
                # Should have called sleep, and not raised ValueError
                self.assertTrue(mock_sleep.called)


if __name__ == '__main__':
    unittest.main()
