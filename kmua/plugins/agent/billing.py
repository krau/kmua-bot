"""Convert provider token usage into quota credits.

Model tokens and quota credits are deliberately separate:

- The raw counters describe what the provider actually processed.
- Credits describe what the run costs against an allowance.

This lets accounting keep every input/output/cache token while a later pricing
model can weight them without changing the usage history.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from kmua.config import app_config
from kmua.consts import token_units_to_credits
from kmua.plugins.agent.cache_stats import cache_stats_from_usage


@dataclass(frozen=True)
class BillingUsage:
    """One run's raw token counts and the credits metered for it."""

    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    credits: int


def _int_field(usage: Any, name: str) -> int:
    return max(0, int(getattr(usage, name, 0) or 0))


def _scaled_tokens(tokens: int, percent: int) -> int:
    """Scale integer tokens by a percentage, rounded half up."""
    if tokens <= 0 or percent <= 0:
        return 0
    if percent >= 100:
        return tokens
    return (tokens * percent + 50) // 100


def from_run_usage(
    usage: Any,
    *,
    cache_read_billing_percent: int | None = None,
) -> BillingUsage:
    """Meter a completed run using the configured cache-read rate.

    ``RunUsage.input_tokens`` includes cache reads and writes. Cache reads are
    removed from the full-price input bucket and re-added at the configured
    rate; cache writes stay in the full-price bucket for now.
    """
    input_tokens, cache_read_tokens, cache_write_tokens = cache_stats_from_usage(usage)
    input_tokens = max(0, int(input_tokens or 0))
    cache_read_tokens = max(0, int(cache_read_tokens or 0))
    cache_write_tokens = max(0, int(cache_write_tokens or 0))
    output_tokens = _int_field(usage, "output_tokens")
    percent = (
        app_config.agent_quota_cache_read_billing_percent
        if cache_read_billing_percent is None
        else cache_read_billing_percent
    )
    percent = min(100, max(0, int(percent)))
    billed_cache_read = min(input_tokens, cache_read_tokens)
    uncached_input = input_tokens - billed_cache_read
    billable_tokens = (
        uncached_input + _scaled_tokens(billed_cache_read, percent) + output_tokens
    )
    return BillingUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=cache_read_tokens,
        cache_write_tokens=cache_write_tokens,
        credits=token_units_to_credits(billable_tokens),
    )


def split_billing_usage(meter: BillingUsage, count: int) -> list[BillingUsage]:
    """Split one metered run across recipients without changing its total cost.

    Raw counters and credits are split independently. Division remainders go to the
    first recipients, so both the token counts and the rounded credit total remain
    exact even when the run costs fewer credits than there are recipients.
    """
    if count <= 0:
        raise ValueError("count must be positive")

    def shares(total: int) -> list[int]:
        base, remainder = divmod(total, count)
        return [base + (index < remainder) for index in range(count)]

    input_shares = shares(meter.input_tokens)
    output_shares = shares(meter.output_tokens)
    cache_read_shares = shares(meter.cache_read_tokens)
    cache_write_shares = shares(meter.cache_write_tokens)
    credit_shares = shares(meter.credits)
    return [
        BillingUsage(
            input_tokens=input_shares[index],
            output_tokens=output_shares[index],
            cache_read_tokens=cache_read_shares[index],
            cache_write_tokens=cache_write_shares[index],
            credits=credit_shares[index],
        )
        for index in range(count)
    ]


__all__ = ["BillingUsage", "from_run_usage", "split_billing_usage"]
