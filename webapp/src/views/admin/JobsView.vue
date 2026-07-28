<script setup lang="ts">
/**
 * Scheduled jobs, read-only.
 *
 * Scheduling stays in code; this page exists to answer "did the cleanup job actually
 * run" without shelling into the container. The trigger expression is monospace
 * because it is a literal cron-style string.
 */
import { computed } from "vue";

import { fetchJobs } from "@/api/endpoints/admin";
import PageHeader from "@/components/PageHeader.vue";
import SettingsRow from "@/components/SettingsRow.vue";
import SettingsSection from "@/components/SettingsSection.vue";
import StateBlock from "@/components/StateBlock.vue";
import { useAsyncData } from "@/composables/useAsyncData";
import { t } from "@/i18n";
import { formatDateTime } from "@/utils/format";

const jobs = useAsyncData((signal) => fetchJobs(signal));
const items = computed(() => jobs.data.value ?? []);
</script>

<template>
  <PageHeader :title="t('admin.jobs')" />

  <StateBlock
    :loading="jobs.loading.value && !jobs.data.value"
    :error="jobs.error.value"
    :empty="!jobs.loading.value && items.length === 0"
    @retry="jobs.reload"
  >
    <SettingsSection>
      <SettingsRow
        v-for="job in items"
        :key="job.id"
        :label="job.name ?? job.id"
        :hint="job.trigger"
        :value="job.next_run_time ? formatDateTime(job.next_run_time) : t('app.none')"
      />
    </SettingsSection>
  </StateBlock>
</template>
