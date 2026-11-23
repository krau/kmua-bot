<script setup lang="ts">
import KmuaMark from "@/components/KmuaMark.vue";
import { Sparkles } from "@lucide/vue";

defineProps<{
  title: string;
  subtitle?: string;
}>();
</script>

<template>
  <header class="page-header">
    <div class="page-header__mark"><KmuaMark /></div>
    <div class="min-w-0">
      <h1>
        {{ title
        }}<Sparkles class="page-header__spark" :size="16" :stroke-width="1.5" aria-hidden="true" />
      </h1>
      <p v-if="subtitle">{{ subtitle }}</p>
    </div>
  </header>
</template>
