/**
 * Notice tests.
 *
 * The behaviour worth pinning is the timing and the single-slot rule: a notice clears
 * itself, a second one replaces the first rather than queueing behind it, and posting
 * the same text twice still produces a new identity so the banner re-animates. The
 * failure timeout is longer than the success one, which is the reason `kind` exists
 * at all beyond colour.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { NOTICE_MS, useNotice } from "./useNotice";

const { notice, notify, notifyError, dismiss } = useNotice();

describe("useNotice", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    dismiss();
    vi.useRealTimers();
  });

  it("starts with nothing shown", () => {
    expect(notice.value).toBeNull();
  });

  it("posts a success notice", () => {
    notify("已保存");

    expect(notice.value?.text).toBe("已保存");
    expect(notice.value?.kind).toBe("success");
  });

  it("posts a failure notice", () => {
    notifyError("加载失败");

    expect(notice.value?.kind).toBe("error");
  });

  it("clears a success notice on its own", () => {
    notify("已保存");

    vi.advanceTimersByTime(NOTICE_MS.success);

    expect(notice.value).toBeNull();
  });

  it("keeps a notice up for its full duration", () => {
    notify("已保存");

    vi.advanceTimersByTime(NOTICE_MS.success - 1);

    expect(notice.value?.text).toBe("已保存");
  });

  it("keeps a failure notice on screen longer than a success one", () => {
    expect(NOTICE_MS.error).toBeGreaterThan(NOTICE_MS.success);

    notifyError("加载失败");

    // Past the success timeout, before the error one.
    vi.advanceTimersByTime(NOTICE_MS.success);
    expect(notice.value?.text).toBe("加载失败");

    vi.advanceTimersByTime(NOTICE_MS.error - NOTICE_MS.success);
    expect(notice.value).toBeNull();
  });

  it("replaces the current notice instead of queueing", () => {
    notify("已保存");
    notify("头像已刷新");

    expect(notice.value?.text).toBe("头像已刷新");
  });

  it("restarts the timer when replaced", () => {
    notify("已保存");
    // Most of the way through the first notice, as a second quick save would be.
    vi.advanceTimersByTime(NOTICE_MS.success - 200);
    notify("头像已刷新");

    // The first notice's remaining 200ms must not cut the second one short.
    vi.advanceTimersByTime(200);
    expect(notice.value?.text).toBe("头像已刷新");

    vi.advanceTimersByTime(NOTICE_MS.success);
    expect(notice.value).toBeNull();
  });

  it("gives the same text a new identity so the banner re-animates", () => {
    notify("已保存");
    const first = notice.value?.id;
    notify("已保存");

    expect(notice.value?.id).not.toBe(first);
  });

  it("ignores an empty message", () => {
    notify("");

    expect(notice.value).toBeNull();
  });

  it("dismisses on request", () => {
    notify("已保存");
    dismiss();

    expect(notice.value).toBeNull();
  });
});
