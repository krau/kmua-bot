/**
 * Token formatting tests.
 *
 * The panel prints balances the API accepts up to 10**12, so the unit has to be chosen
 * from the rounded value: a count that rounds up to 1000.0 would otherwise be shown as
 * "1000.0k", which reads as both the wrong magnitude and the wrong unit.
 */

import { describe, expect, it } from "vitest";

import { formatTokens } from "./format";

describe("formatTokens", () => {
  it("keeps small counts exact", () => {
    expect(formatTokens(0)).toBe("0");
    expect(formatTokens(999)).toBe("999");
  });

  it("switches unit at a thousand", () => {
    expect(formatTokens(1_000)).toBe("1.0k");
  });

  it("promotes when rounding reaches the next unit", () => {
    expect(formatTokens(999_949)).toBe("999.9k");
    expect(formatTokens(999_950)).toBe("1.0M");
    expect(formatTokens(999_999)).toBe("1.0M");
    expect(formatTokens(999_999_999)).toBe("1.0B");
  });

  it("covers the whole range the API accepts", () => {
    expect(formatTokens(1_000_000)).toBe("1.0M");
    expect(formatTokens(10 ** 12)).toBe("1.0T");
  });

  it("keeps the sign on a debt balance", () => {
    expect(formatTokens(-1_500)).toBe("-1.5k");
    expect(formatTokens(-999_999)).toBe("-1.0M");
  });
});
