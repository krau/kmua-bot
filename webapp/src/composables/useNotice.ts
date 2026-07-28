/**
 * Transient feedback: "已保存", "头像已刷新", and the failures that pair with them.
 *
 * State lives at module scope rather than in a component or a Pinia store, because a
 * notice outlives the action that raised it and belongs to no single page: a save on
 * the profile page and a delete on the quotes page post to the same place, and the
 * banner that renders them is mounted once in the shell.
 *
 * Previously each view kept its own `notice` ref and rendered a line of text under the
 * page title. That had three problems: it was easy to miss, it was invisible once the
 * page was scrolled, and inserting a line into the flow shifted everything below it.
 * A single fixed banner fixes all three, and makes the timing consistent - every
 * notice now clears itself rather than lingering until the next action.
 */

import { onScopeDispose, readonly, ref } from "vue";

export type NoticeKind = "success" | "error";

export interface Notice {
  /** Identity, so re-posting the same text still restarts the animation. */
  id: number;
  text: string;
  kind: NoticeKind;
}

/**
 * How long a notice stays up.
 *
 * Exported so the tests assert against these rather than repeating the numbers: a
 * duration written twice is a test that passes for the wrong reason once it changes.
 *
 * Short, because the banner confirms an action the user just took and already expects
 * to have worked. Failures get roughly double: that text is a reason to read, not an
 * acknowledgement to notice.
 */
export const NOTICE_MS: Record<NoticeKind, number> = {
  success: 1600,
  error: 3200,
};

const current = ref<Notice | null>(null);
let timer: ReturnType<typeof setTimeout> | null = null;
let nextId = 0;

function clearTimer(): void {
  if (timer !== null) {
    clearTimeout(timer);
    timer = null;
  }
}

function post(text: string, kind: NoticeKind): void {
  if (!text) return;
  // A second notice replaces the first outright rather than queueing behind it: the
  // latest outcome is the one worth showing, and a queue would make a burst of saves
  // take longer to clear than it took to cause.
  clearTimer();
  current.value = { id: ++nextId, text, kind };
  timer = setTimeout(() => {
    current.value = null;
    timer = null;
  }, NOTICE_MS[kind]);
}

/** Dismiss immediately, e.g. when the user taps the banner. */
function dismiss(): void {
  clearTimer();
  current.value = null;
}

/**
 * Post and read transient notices.
 *
 * The returned `notice` is read-only: a view raises feedback by calling `notify` or
 * `notifyError`, never by assigning, so there is one code path that also sets the
 * dismiss timer.
 */
export function useNotice() {
  return {
    notice: readonly(current),
    notify: (text: string) => post(text, "success"),
    notifyError: (text: string) => post(text, "error"),
    dismiss,
  };
}

/**
 * Drop any pending notice when the owning scope goes away.
 *
 * Used by the shell so a stale banner cannot outlive a teardown. Views do not need
 * this: a notice raised by a save is still worth showing after a route change.
 */
export function useNoticeCleanup(): void {
  onScopeDispose(() => {
    clearTimer();
    current.value = null;
  });
}
