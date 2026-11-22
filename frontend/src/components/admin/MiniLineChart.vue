<script setup lang="ts">
import { computed } from 'vue'
interface Point { label: string; value: number }
const props = withDefaults(defineProps<{ points: Point[]; height?: number }>(), { height: 120 })
const width = 480
const pad = 10
const peak = computed(() => Math.max(1, ...props.points.map((p) => p.value)))
const coords = computed(() => props.points.map((p, index) => {
  const x = pad + (index * (width - pad * 2)) / Math.max(1, props.points.length - 1)
  const y = props.height - pad - (p.value / peak.value) * (props.height - pad * 2)
  return { x: Number(x.toFixed(1)), y: Number(y.toFixed(1)), label: p.label }
}))
const path = computed(() => coords.value.map((c, i) => (i === 0 ? 'M' : 'L') + c.x + ' ' + c.y).join(' '))
const area = computed(() => {
  if (!coords.value.length) return ''
  const first = coords.value[0]
  const last = coords.value[coords.value.length - 1]
  return path.value + ' L' + last.x + ' ' + (props.height - pad) + ' L' + first.x + ' ' + (props.height - pad) + ' Z'
})
</script>

<template>
  <div class="mini-line">
    <svg :viewBox="'0 0 ' + width + ' ' + height" :height="height" preserveAspectRatio="none" role="img" aria-label="趋势">
      <path :d="area" class="area" />
      <path :d="path" class="stroke" />
      <circle v-for="c in coords" :key="c.label + c.x" :cx="c.x" :cy="c.y" r="2.6" class="dot" />
    </svg>
    <div class="mini-line-axis"><span v-for="c in coords" :key="'l' + c.x">{{ c.label }}</span></div>
  </div>
</template>

<style scoped>
.mini-line { display: grid; gap: 8px; }
.mini-line svg { width: 100%; display: block; }
.area { fill: var(--accent-soft, #ecd6cb); opacity: .55; }
.stroke { fill: none; stroke: var(--accent); stroke-width: 2; stroke-linejoin: round; }
.dot { fill: var(--accent); }
.mini-line-axis { display: flex; justify-content: space-between; color: var(--text-3); font-size: 11px; }
.mini-line-axis span { flex: 1 1 0; text-align: center; overflow: hidden; white-space: nowrap; }
</style>
