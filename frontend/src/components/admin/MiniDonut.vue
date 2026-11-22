<script setup lang="ts">
import { computed } from 'vue'
const props = withDefaults(
  defineProps<{ value: number; total: number; label?: string; caption?: string; size?: number; tone?: 'accent' | 'warn' }>(),
  { label: '', caption: '', size: 96, tone: 'accent' },
)
const ratio = computed(() => (props.total > 0 ? Math.max(0, Math.min(1, props.value / props.total)) : 0))
const radius = computed(() => props.size / 2 - 8)
const circumference = computed(() => 2 * Math.PI * radius.value)
const dash = computed(() => (ratio.value * circumference.value).toFixed(1) + ' ' + circumference.value.toFixed(1))
const center = computed(() => props.size / 2)
const text = computed(() => props.label || Math.round(ratio.value * 100) + '%')
</script>

<template>
  <div class="mini-donut" :class="tone" :style="{ width: size + 'px' }">
    <svg :width="size" :height="size" :viewBox="'0 0 ' + size + ' ' + size" role="img" :aria-label="text">
      <circle :cx="center" :cy="center" :r="radius" fill="none" stroke="var(--overlay-1, rgba(0,0,0,.06))" stroke-width="8" />
      <circle v-if="ratio > 0" :cx="center" :cy="center" :r="radius" fill="none" stroke="currentColor" stroke-width="8" stroke-linecap="round"
        :stroke-dasharray="dash" :transform="'rotate(-90 ' + center + ' ' + center + ')'" />
      <text :x="center" :y="center + 5" text-anchor="middle" class="donut-text">{{ text }}</text>
    </svg>
    <p v-if="caption" class="donut-caption">{{ caption }}</p>
  </div>
</template>

<style scoped>
.mini-donut { display: grid; justify-items: center; gap: 6px; color: var(--accent); }
.mini-donut.warn { color: var(--danger, #b23b2e); }
.donut-text { fill: var(--text); font-size: 15px; font-weight: 650; }
.donut-caption { margin: 0; color: var(--text-3); font-size: 11.5px; text-align: center; }
</style>
