<template>
  <RouterView v-slot="{ Component, route }">
    <Transition name="route" mode="out-in">
      <div :key="route.path" class="route-frame">
        <component :is="Component" />
      </div>
    </Transition>
  </RouterView>
</template>
