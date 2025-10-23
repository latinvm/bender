# Bitvavo Rate Limit Fix

## Problem

The `python-bitvavo-api` library (version 1.4.3 and earlier) has a bug in its rate limiting thread that causes the following error:

```
Exception in thread Thread-1:
Traceback (most recent call last):
  File "/usr/lib/python3.12/threading.py", line 1073, in _bootstrap_inner
    self.run()
  File ".../python_bitvavo_api/bitvavo.py", line 112, in run
    self.waitForReset(self.timeToWait)
  File ".../python_bitvavo_api/bitvavo.py", line 102, in waitForReset
    time.sleep(waitTime)
ValueError: sleep length must be non-negative
```

### Root Cause

The bug occurs in the `rateLimitThread.waitForReset()` method when calculating the wait time:

```python
timeToWait = (self.bitvavo.rateLimitReset / 1000) - time.time()
```

If the current time is already past the `rateLimitReset` timestamp (meaning the rate limit ban has already expired), this calculation produces a **negative value**, which causes `time.sleep()` to raise a `ValueError`.

This typically happens when:
- System time jumps forward (clock sync, timezone change)
- Network delays cause the rate limit check to occur after the ban expired
- High system load causes thread scheduling delays

## Solution

We've implemented a **monkey patch** in [`src/trader/bitvavo.py`](../src/trader/bitvavo.py) that fixes this issue by:

1. **Checking for negative wait times** before calling `time.sleep()`
2. **Converting negative values to zero** (no wait needed if ban already expired)
3. **Adding comprehensive logging** to monitor rate limit events
4. **Handling recursive calls** to ensure all paths are protected

### Implementation

The patch is automatically applied when the `BitvavoClient` is imported:

```python
def _patch_bitvavo_rate_limit():
    """Monkey patch the Bitvavo library to fix the negative sleep bug."""
    from python_bitvavo_api.bitvavo import rateLimitThread

    def patched_wait_for_reset(self, waitTime):
        # Ensure non-negative wait time
        if waitTime < 0:
            logger.warning(f"Negative wait time detected ({waitTime:.2f}s). Setting to 0.")
            waitTime = 0

        time.sleep(waitTime)

        # Handle recursive calls with negative time protection
        if time.time() >= self.bitvavo.rateLimitReset:
            timeToWait = max(0, (self.bitvavo.rateLimitReset / 1000) - time.time())
            if timeToWait > 0:
                self.waitForReset(timeToWait)

    rateLimitThread.waitForReset = patched_wait_for_reset

# Apply patch on import
_patch_bitvavo_rate_limit()
```

### Logging

The patch adds detailed logging at the `trader.bitvavo` logger level:

- **INFO**: Rate limit waits and resets
- **WARNING**: Negative wait times detected
- **ERROR**: Patch application failures

Example log output:
```
INFO - BitvavoClient initialized with rate limit protection
WARNING - Bitvavo rate limit: Negative wait time detected (-5.23s). Ban likely already expired. Setting to 0.
INFO - Bitvavo rate limit: Waiting 45.2s for rate limit reset
INFO - Bitvavo rate limit: Ban lifted, reset to 1000 requests
```

## Testing

Comprehensive unit tests are available in [`tests/test_bitvavo_patch.py`](../tests/test_bitvavo_patch.py):

```bash
pytest tests/test_bitvavo_patch.py -v
```

Test coverage includes:
- ✅ Negative wait time handling
- ✅ Positive wait time (unchanged behavior)
- ✅ Zero wait time
- ✅ Recursive calls with negative times
- ✅ Client initialization with patch
- ✅ Patch application verification

## Status

✅ **FIXED** - The issue is resolved in Bender's codebase

### Version Information
- **Library**: `python-bitvavo-api` version 1.4.3 (latest as of 2025-10-23)
- **Bug Status**: Still present in upstream library
- **Our Fix**: Monkey patch applied automatically on import
- **Alternative**: Wait for upstream fix (may not happen)

## Upstream Issue

This is a bug in the external `python-bitvavo-api` library, not in Bender's code. Consider:

1. **Reporting to maintainers**: Create an issue at https://github.com/bitvavo/python-bitvavo-api
2. **Pull request**: Submit a fix to the upstream repository
3. **Monitor for updates**: Check if future versions fix this issue

## Migration Path

If the upstream library fixes this bug in a future version:

1. Update `python-bitvavo-api` to the fixed version
2. Test with `pytest tests/test_bitvavo_patch.py`
3. The patch will remain safe even if the library is fixed (it just becomes redundant)
4. Optionally remove the patch if no longer needed

## Impact

**Before Fix:**
- ❌ Random crashes in rate limit thread
- ❌ No visibility into rate limit events
- ❌ Potential trading interruptions

**After Fix:**
- ✅ No more `ValueError: sleep length must be non-negative`
- ✅ Comprehensive logging of rate limit events
- ✅ Graceful handling of expired bans
- ✅ Stable 24/7 operation

## Additional Notes

- The patch is **non-invasive** and doesn't affect normal operation
- Performance impact is **negligible** (just an `if` check and `max()` call)
- The fix is **backward compatible** with older `python-bitvavo-api` versions
- No configuration changes needed - works automatically

---

**Last Updated**: 2025-10-23
**Tested With**: `python-bitvavo-api` 1.4.3
