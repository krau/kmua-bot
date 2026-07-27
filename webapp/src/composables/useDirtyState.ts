/**
 * Change tracking for an editable page.
 *
 * A form is a draft over a baseline. This composable owns the comparison so every
 * page reports "3 changes" the same way, and so the native main button and the
 * close-confirmation prompt are driven by one source of truth rather than each
 * page remembering to wire them up.
 */

import { computed, ref, watch, type Ref } from "vue";

import { setClosingConfirmation } from "@/telegram";

export interface DirtyState<T extends Record<string, unknown>> {
  /** The editable copy bound to inputs. */
  draft: Ref<T>;
  /** Field names that differ from the baseline. */
  changedFields: Ref<string[]>;
  isDirty: Ref<boolean>;
  /** Replace the baseline, e.g. after a successful save. */
  commit: (value: T) => void;
  /** Throw the draft away and return to the baseline. */
  reset: () => void;
}

/**
 * Deep-copy a form value.
 *
 * A JSON round-trip rather than `structuredClone`: the values held here are already
 * reactive proxies, and `structuredClone` throws `DataCloneError` on a Proxy. Every
 * form value in this app is JSON-shaped (booleans, numbers, strings, null, and flat
 * maps of those), which is exactly what a JSON round-trip preserves.
 */
function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

function differs(a: unknown, b: unknown): boolean {
  // Values here are JSON-shaped (booleans, numbers, strings, flat maps), so a
  // serialised comparison is both correct and cheap.
  if (typeof a === "object" && a !== null) {
    return JSON.stringify(a) !== JSON.stringify(b);
  }
  return a !== b;
}

export function useDirtyState<T extends Record<string, unknown>>(initial: T): DirtyState<T> {
  const baseline = ref(clone(initial)) as Ref<T>;
  const draft = ref(clone(initial)) as Ref<T>;

  const changedFields = computed(() =>
    Object.keys(draft.value).filter((key) =>
      differs(draft.value[key as keyof T], baseline.value[key as keyof T]),
    ),
  );
  const isDirty = computed(() => changedFields.value.length > 0);

  // Telegram asks the user to confirm closing only while there is something to
  // lose; leaving it always on trains people to dismiss it.
  watch(isDirty, (dirty) => setClosingConfirmation(dirty), { immediate: false });

  function commit(value: T): void {
    baseline.value = clone(value);
    draft.value = clone(value);
    setClosingConfirmation(false);
  }

  function reset(): void {
    draft.value = clone(baseline.value);
  }

  return {
    draft,
    changedFields: changedFields as unknown as Ref<string[]>,
    isDirty: isDirty as unknown as Ref<boolean>,
    commit,
    reset,
  };
}
