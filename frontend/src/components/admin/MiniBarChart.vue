<script setup lang="ts">
interface BarItem { label: string; value: number; hint?: string }
const props = withDefaults(
  defineProps<{ items: BarItem[]; orientation?: 'vertical' | 'horizontal'; height?: number; unit?: string; max?: number }>(),
  { orientation: 'horizontal', height: 160, unit: '', max: 0 },
)
const peak = () => (props.max > 0 ? props.max : Math.max(1, ...props.items.map((item) => item.value)))
const ratioOf = (value: number) => Math.round((value / peak()) * 100) + '%'
// 值为 0 时不画那 3px 的最小宽度，否则看起来像有一条数据
const barStyle = (value: number) => (value > 0 ? {} : { minWidth: '0px' })
</script>

<template>
  <div class="mini-bar" :class="orientation" :style="{ '--bar-height': typeof height + 'px' }">
    <div v-for="item in items" :key="item.label" class="mini-bar-row">
      <span class="mini-bar-label" :title="item.label">{{ item.label }}</span>
      <div class="mini-bar-track">
        <i :style="orientation === 'vertical' ? { height: ratioOf(item.value), ...barStyle(item.value) } : { width: ratioOf(item.value), ...barStyle(item.value) }" />
      </div>
      <span class="mini-bar-value">{{ item.value }}{{ unit }}<em v-if="item.hint">{{ item.hint }}</em></span>
    </div>
  </div>
</template>

<style scoped>
.mini-bar { display: grid; gap: 12px; }
.mini-bar-row { display: grid; grid-template-columns: 110px minmax(0, 1fr) 82px; align-items: center; gap: 14px; }
.mini-bar-label { color: var(--text-2); font-size: 12.5px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.mini-bar-track { display: flex; align-items: flex-end; height: 14px; border-radius: 7px; background: var(--overlay-1, rgba(0,0,0,.05)); overflow: hidden; }
.mini-bar i { display: block; height: 100%; min-width: 3px; border-radius: 7px; background: linear-gradient(90deg, var(--accent-soft, #e8c9bb), var(--accent)); transition: width .25s ease, height .25s ease; }
.mini-bar-value { color: var(--text); font-size: 13px; font-variant-numeric: tabular-nums; text-align: right; }
.mini-bar-value em { margin-left: 4px; color: var(--text-3); font-style: normal; font-size: 11.5px; }

.mini-bar.vertical { gap: 0; }
.mini-bar.vertical .mini-bar-row { grid-template-columns: 92px minmax(0, 1fr) 76px; }
.mini-bar.vertical .mini-bar-track { height: var(--bar-height, 160px); }
.mini-bar.vertical i { width: 100%; min-width: 0; min-height: 3px; }
</style>
