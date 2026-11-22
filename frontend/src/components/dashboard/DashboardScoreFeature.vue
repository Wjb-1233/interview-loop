<script setup lang="ts">
import { computed } from 'vue'

import AnimatedNumber from '@/components/report/AnimatedNumber.vue'
import { trainingDate } from '@/lib/dashboard'

const props = defineProps<{
  latestScore: number | null
  latestSessionId: string | null
  recentAverage: number | null
  recentSampleCount: number
  focus: string
  lastTrainedAt?: string | null
}>()

const caption = computed(() => {
  const date = props.lastTrainedAt ? trainingDate(props.lastTrainedAt) : ''
  return date ? `这组条件下最近一次训练 · ${date}` : '这组条件下最近一次正式评分'
})
</script>

<template>
  <section class="hero panel" aria-labelledby="latest-score-title">
    <div class="hero-main">
      <p id="latest-score-title" class="label">最近一次成绩</p>

      <div v-if="latestScore !== null" class="figure">
        <span class="num"><AnimatedNumber v-if="Number.isInteger(latestScore)" :value="latestScore" /><template v-else>{{ latestScore }}</template></span>
        <span class="den">/ 100</span>
      </div>
      <p v-else class="empty-score">还没有评分<span>完成一次对练后生成</span></p>

      <p v-if="latestScore !== null" class="caption">{{ caption }}</p>
      <RouterLink v-if="latestSessionId" class="report-link" :to="`/report/${latestSessionId}`">查看本次报告与评分证据 →</RouterLink>


      <RouterLink class="cta" to="/scenes">
        <span>开始一次训练</span>
        <svg width="15" height="10" viewBox="0 0 15 10" fill="none" aria-hidden="true">
          <path d="M0 5h13M9.4 1.4 13 5l-3.6 3.6" stroke="currentColor" stroke-width="1.1" />
        </svg>
      </RouterLink>
    </div>

    <dl class="hero-facts">
      <div class="fact">
        <dt>近 {{ recentSampleCount }} 次同条件均分</dt>
        <dd><span class="num value">{{ recentAverage ?? '—' }}</span><em>/ 100</em></dd>
      </div>
      <div class="fact">
        <dt>当前提升重点</dt>
        <dd class="focus"><i class="dot" aria-hidden="true" /><span class="focus-name">{{ focus }}</span></dd>
      </div>
    </dl>
  </section>
</template>

<style scoped>
.hero {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 300px;
  border-radius: var(--radius);
}
.hero-main { display: flex; flex-direction: column; padding: 36px 40px 34px; }

.label { margin: 0; color: var(--text-3); font-size: 12.5px; }

.figure { display: flex; align-items: flex-end; gap: 12px; margin: 26px 0 0; }
.figure .num {
  color: var(--text);
  font-family: var(--font-num);
  font-size: clamp(104px, 11.4vw, 156px);
  font-weight: 200;
  font-variant-numeric: tabular-nums;
  letter-spacing: -.055em;
  line-height: .8;
}
.figure .num.dash { color: var(--text-3); letter-spacing: 0; }
.empty-score { margin: 10px 0 0; display: grid; gap: 6px; font-size: 22px; font-weight: 600; letter-spacing: -.01em; }
.empty-score span { color: var(--text-3); font-size: 12.5px; font-weight: 400; letter-spacing: .02em; }
.figure .den { padding-bottom: 12px; color: var(--text-3); font-family: var(--font-num); font-size: 13px; letter-spacing: .06em; }

.caption { margin: 22px 0 0; color: var(--text-3); font-size: 13px; line-height: 1.7; }
.report-link { margin:10px 0 22px;color:var(--accent-strong);font-size:12px; }

.cta {
  align-self: flex-start;
  display: inline-flex;
  align-items: center;
  gap: 14px;
  margin-top: auto;
  padding: 12px 18px 12px 20px;
  border: 1px solid var(--accent);
  border-radius: var(--radius-sm);
  background: var(--accent);
  color: #fff;
  font-size: 13px;
  font-weight: 600;
  letter-spacing: .04em;
  transition: background var(--ease), border-color var(--ease), gap var(--ease);
}
.cta svg { transition: transform var(--ease); }
.cta:hover { background: var(--accent-strong); border-color: var(--accent-strong); color: #fff; gap: 18px; }
.cta:hover svg { transform: translateX(2px); }

.hero-facts { display: flex; flex-direction: column; margin: 0; border-left: 1px solid var(--divider); }
.fact {
  display: flex;
  flex: 1;
  flex-direction: column;
  justify-content: center;
  gap: 9px;
  padding: 18px 26px;
  border-bottom: 1px solid var(--divider);
}
.fact:last-child { border-bottom: 0; }
.fact dt { color: var(--text-3); font-size: 12.5px; }
.fact dd { display: flex; align-items: baseline; gap: 7px; margin: 0; }
.fact dd.tags { flex-wrap: wrap; gap: 6px; align-items: center; }
.fact dd.tags span { padding: 2px 8px; border: 1px solid var(--border); border-radius: 5px; color: var(--text-2); font-size: 10.5px; letter-spacing: .02em; }
.fact dd.tags em { color: var(--text-3); font-style: normal; font-size: 12px; }
.fact .value { color: var(--text); font-family: var(--font-num); font-size: 26px; font-weight: 300; letter-spacing: -.01em; }
.fact em { color: var(--text-3); font-size: 12px; font-style: normal; }
.fact .focus-name { color: var(--text); font-size: 22px; font-weight: 500; }
.fact .dot { display: inline-block; width: 5px; height: 5px; margin-right: 8px; transform: translateY(-3px); background: var(--accent); }
.fact .soft { color: var(--text-2); font-size: 13px; line-height: 1.6; letter-spacing: .02em; }

:root[data-theme='dark'] .hero {
  background: rgba(12, 10, 26, .66);
  border-color: rgba(255, 255, 255, .12);
  backdrop-filter: blur(20px) saturate(120%);
  -webkit-backdrop-filter: blur(20px) saturate(120%);
}
:root[data-theme='dark'] .cta {
  border-color: var(--accent);
  background: var(--accent);
  color: #0b0b0e;
}
:root[data-theme='dark'] .cta:hover {
  background: var(--accent-strong);
  border-color: var(--accent-strong);
  color: #0b0b0e;
}
.hero .figure .num { font-size: clamp(64px, 7vw, 86px); font-weight: 600; letter-spacing: -.045em; }
</style>
