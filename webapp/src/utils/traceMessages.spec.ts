/**
 * Trace conversation rendering.
 *
 * The panel reads message history in pydantic-ai's serialized shape, which is
 * versioned by that library rather than by us. What these tests pin down is what
 * the panel promises the operator: every part of a request or response is shown,
 * a tool call and its return are attributable to their tool, media is named
 * instead of silently vanishing, and an unknown part is still visible.
 */

import { describe, expect, it } from "vitest";

import { traceBlocks } from "./traceMessages";

function partsOf(...parts: object[]): unknown[] {
  return [{ kind: "request", parts }];
}

describe("traceBlocks", () => {
  it("separates user prompts from model text", () => {
    const blocks = traceBlocks([
      { kind: "request", parts: [{ part_kind: "user-prompt", content: "hello" }] },
      { kind: "response", parts: [{ part_kind: "text", content: "hi there" }] },
    ]);

    expect(blocks).toEqual([
      { role: "user", kind: "text", text: "hello" },
      { role: "assistant", kind: "text", text: "hi there" },
    ]);
  });

  it("labels a tool call with its name and args", () => {
    const blocks = traceBlocks(
      partsOf({ part_kind: "tool-call", tool_name: "read", args: { path: "a" } }),
    );

    expect(blocks).toHaveLength(1);
    expect(blocks[0]?.role).toBe("assistant");
    expect(blocks[0]?.kind).toBe("tool-call");
    expect(blocks[0]?.toolName).toBe("read");
    expect(blocks[0]?.text).toContain('"path": "a"');
  });

  it("attributes a tool return to its tool", () => {
    const blocks = traceBlocks(
      partsOf({ part_kind: "tool-return", tool_name: "read", content: "file contents" }),
    );

    expect(blocks[0]?.role).toBe("tool");
    expect(blocks[0]?.kind).toBe("tool-return");
    expect(blocks[0]?.toolName).toBe("read");
    expect(blocks[0]?.text).toBe("file contents");
  });

  it("renders a list content part element by element", () => {
    const blocks = traceBlocks(
      partsOf({
        part_kind: "user-prompt",
        content: ["look at this", { kind: "binary", media_type: "image/png", size: 2048 }],
      }),
    );

    expect(blocks[0]?.text).toBe("look at this\n[media: image/png, 2048 bytes]");
  });

  it("names the role of a system prompt", () => {
    const blocks = traceBlocks(partsOf({ part_kind: "system-prompt", content: "be brief" }));
    expect(blocks[0]?.role).toBe("system");
    expect(blocks[0]?.text).toBe("be brief");
  });

  it("shows an unrecognised part instead of dropping it", () => {
    const blocks = traceBlocks(partsOf({ part_kind: "thinking", content: "hmm" }));

    expect(blocks).toHaveLength(1);
    expect(blocks[0]?.kind).toBe("raw");
    expect(blocks[0]?.text).toContain("hmm");
  });

  it("keeps a tool return distinguishable from a retry prompt", () => {
    const blocks = traceBlocks(
      partsOf({ part_kind: "retry-prompt", tool_name: "read", content: "bad args" }),
    );
    expect(blocks[0]?.kind).toBe("tool-return");
    expect(blocks[0]?.text).toBe("bad args");
  });

  it("survives a message shape it does not know", () => {
    expect(traceBlocks([{ kind: "request" }])).toEqual([]);
    expect(traceBlocks([42])).toEqual([{ role: "user", kind: "raw", text: "42" }]);
  });
});
