/**
 * Async loading state for a view.
 *
 * Every list and detail page needs the same three things: the data, whether it is
 * loading, and a translated error. Doing it here keeps the pages free of
 * try/finally boilerplate and makes in-flight cancellation on route change the
 * default rather than something each page remembers.
 */

import { onScopeDispose, ref, type Ref } from "vue";

import { isAbortError, isApiError } from "@/api/errors";
import { t, tError } from "@/i18n";

export interface AsyncResource<T> {
  data: Ref<T | null>;
  loading: Ref<boolean>;
  error: Ref<string | null>;
  reload: () => Promise<void>;
}

export function useAsyncData<T>(
  loader: (signal: AbortSignal) => Promise<T>,
  options: { immediate?: boolean } = {},
): AsyncResource<T> {
  const data = ref<T | null>(null) as Ref<T | null>;
  const loading = ref(false);
  const error = ref<string | null>(null);

  let controller: AbortController | null = null;

  async function reload(): Promise<void> {
    // Supersede any request still in flight so a slow first response cannot
    // overwrite a newer one.
    controller?.abort();
    controller = new AbortController();
    const signal = controller.signal;

    loading.value = true;
    error.value = null;
    try {
      const result = await loader(signal);
      if (!signal.aborted) data.value = result;
    } catch (e) {
      if (isAbortError(e)) return;
      error.value = isApiError(e) ? tError(e.code) : t("app.loadFailed");
    } finally {
      if (!signal.aborted) loading.value = false;
    }
  }

  onScopeDispose(() => controller?.abort());

  if (options.immediate !== false) void reload();

  return { data, loading, error, reload };
}
