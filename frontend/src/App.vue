<script setup lang="ts">
import { computed, provide } from 'vue'
import { useRoute } from 'vue-router'

import AppShell from '@/components/layout/AppShell.vue'
import NetworkStatusBanner from '@/components/layout/NetworkStatusBanner.vue'
import { useNetworkStatus } from '@/composables/useNetworkStatus'
import { activeTrainingAttemptKey, createActiveTrainingAttempt } from '@/lib/activeTrainingAttempt'

provide(activeTrainingAttemptKey, createActiveTrainingAttempt())

const route = useRoute()
const usesShell = computed(() => route.meta.public !== true)
const viewKey = computed(() => JSON.stringify([route.path, route.query.planId ?? '', route.query.sessionId ?? '']))
const { isOnline } = useNetworkStatus()
</script>

<template>
  <NetworkStatusBanner :is-online="isOnline" />
  <AppShell v-if="usesShell">
    <RouterView :key="viewKey" />
  </AppShell>
  <RouterView v-else :key="viewKey" />
</template>

