<script setup lang="ts">
import KmuaMark from "@/components/KmuaMark.vue";

defineProps<{
  title: string;
  subtitle?: string;
}>();
</script>

<template>
  <header class="page-header">
    <div class="page-header__mark"><KmuaMark /></div>
    <div class="min-w-0">
      <div class="page-header__eyebrow" aria-hidden="true">KMUA · LITTLE UNIVERSE</div>
      <h1>{{ title }}<span class="page-header__spark" aria-hidden="true">✦</span></h1>
      <p v-if="subtitle">{{ subtitle }}</p>
    </div>
  </header>
</template>
