/**
 * Rendering a recorded request/response as a conversation.
 *
 * The trace stores messages in pydantic-ai's own serialized shape (the shape
 * message history is persisted in), so the panel reads that shape rather than a
 * model-friendly one: a message is a `request` or a `response`, and each holds
 * `parts` tagged by `part_kind`. Anything unrecognised is shown as raw JSON
 * rather than dropped - an operator reading a trace needs to see what is there,
 * including the parts this file does not know about.
 */

/** The fields of a serialized message this renderer reads. */
interface TraceMessage {
  kind?: unknown;
  parts?: unknown;
}

/** The fields of a serialized part this renderer reads. */
interface TracePart {
  part_kind?: unknown;
  content?: unknown;
  args?: unknown;
  tool_name?: unknown;
}

export interface TraceBlock {
  /** Who the line belongs to: a user prompt, model output, or a tool. */
  role: "user" | "assistant" | "tool" | "system";
  kind: "text" | "tool-call" | "tool-return" | "raw";
  /** The text to show; already stringified. */
  text: string;
  /** Tool name, for call and return blocks. */
  toolName?: string;
}

function stringify(value: unknown): string {
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value, null, 2) ?? "";
  } catch {
    return String(value);
  }
}

/** Render one content value: text, a media marker, or a mix of both. */
function contentText(content: unknown): string {
  if (typeof content === "string") return content;
  if (content === null || content === undefined) return "";
  if (Array.isArray(content)) {
    return content.map(contentText).filter(Boolean).join("\n");
  }
  if (typeof content === "object") {
    const marker = content as { kind?: unknown; media_type?: unknown; size?: unknown };
    // Binary content was reduced to its metadata on the way in; name it as media
    // so a reader is not left wondering where the picture went.
    if (marker.kind === "binary") {
      const type = typeof marker.media_type === "string" ? marker.media_type : "?";
      const size = typeof marker.size === "number" ? marker.size : 0;
      return `[media: ${type}, ${size} bytes]`;
    }
    return stringify(content);
  }
  return String(content);
}

function partBlocks(part: TracePart, response: boolean): TraceBlock[] {
  const fallback: TraceBlock = {
    role: response ? "assistant" : "user",
    kind: "raw",
    text: stringify(part),
  };
  const toolName = typeof part.tool_name === "string" ? part.tool_name : undefined;
  switch (part.part_kind) {
    case "system-prompt":
      return [{ role: "system", kind: "text", text: contentText(part.content) }];
    case "user-prompt":
      return [{ role: "user", kind: "text", text: contentText(part.content) }];
    case "text":
      return [{ role: "assistant", kind: "text", text: contentText(part.content) }];
    case "tool-return":
    case "builtin-tool-return":
    case "retry-prompt":
      return [{ role: "tool", kind: "tool-return", toolName, text: contentText(part.content) }];
    case "tool-call":
    case "builtin-tool-call":
      return [{ role: "assistant", kind: "tool-call", toolName, text: stringify(part.args) }];
    default:
      return [fallback];
  }
}

/**
 * Flatten recorded messages into display blocks.
 *
 * Message-level `instructions` are skipped: a request's instructions are shown
 * once, from the event's own `instruction_parts`, instead of repeating on every
 * message of a long turn.
 */
export function traceBlocks(messages: readonly unknown[]): TraceBlock[] {
  const blocks: TraceBlock[] = [];
  for (const raw of messages) {
    if (typeof raw !== "object" || raw === null) {
      blocks.push({ role: "user", kind: "raw", text: stringify(raw) });
      continue;
    }
    const message = raw as TraceMessage;
    const response = message.kind === "response";
    const parts = Array.isArray(message.parts) ? (message.parts as TracePart[]) : [];
    for (const part of parts) {
      blocks.push(...partBlocks(part, response));
    }
  }
  return blocks;
}
