/**
 * A ref that trails another one.
 *
 * Search boxes fire a request per keystroke otherwise. The delay is applied on the
 * way out, so the input stays fully responsive while the query settles.
 */

import { onScopeDispose, ref, watch, type Ref } from "vue";

export function useDebouncedRef<T>(source: Ref<T>, delay = 300): Ref<T> {
  const debounced = ref(source.value) as Ref<T>;
  let timer: ReturnType<typeof setTimeout> | null = null;

  watch(source, (value) => {
    if (timer !== null) clearTimeout(timer);
    timer = setTimeout(() => {
      debounced.value = value;
      timer = null;
    }, delay);
  });

  onScopeDispose(() => {
    if (timer !== null) clearTimeout(timer);
  });

  return debounced;
}
