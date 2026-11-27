<script setup lang="ts">
import { computed, inject, shallowRef, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { Moon, Sun, Bookmark, History, LayoutDashboard, MessageSquareText, MessagesSquare, Settings, TrendingUp, UserRound } from 'lucide-vue-next'

import AtmosphereBackdrop from '@/components/layout/AtmosphereBackdrop.vue'
import { useAuth } from '@/composables/useAuth'
import { useTheme } from '@/composables/useTheme'
import { activeTrainingAttemptKey, trainingAttemptId } from '@/lib/activeTrainingAttempt'

const route = useRoute()
const router = useRouter()
const auth = useAuth()
const activeAttempt = inject(activeTrainingAttemptKey)!

const studentNavItems = [
  { to: '/', label: '成长看板', icon: LayoutDashboard },
  { to: '/scenes', label: '场景训练', icon: MessagesSquare },
  { to: '/plans', label: '能力提升', icon: TrendingUp },
  { to: '/scripts', label: '话术优化', icon: MessageSquareText },
  { to: '/scripts/saved', label: '话术库', icon: Bookmark },
  { to: '/history', label: '训练记录', icon: History },
  { to: '/profile', label: '个人资料', icon: UserRound },
]
const adminNavItems = [
  { to: '/admin', label: '管理工作台', icon: Settings },
  { to: '/profile', label: '个人资料', icon: UserRound },
]
const navItems = computed(() => auth.user.value?.role === 'ADMIN' ? adminNavItems : studentNavItems)

const home = computed(() => auth.user.value?.role === 'ADMIN' ? '/admin' : '/')
const { theme, toggle: toggleTheme, applyScope } = useTheme()
const sidebarCollapsed = shallowRef(false)
const roleLabel = computed(() => auth.user.value?.role === 'ADMIN' ? '管理员' : '训练学员')

// 学员与管理员各自记住自己的主题偏好
watch(() => auth.user.value?.role ?? null, (role) => {
  if (role) applyScope(role as 'STUDENT' | 'ADMIN')
}, { immediate: true })



function toggleNavigation(): void {
  sidebarCollapsed.value = !sidebarCollapsed.value
}

async function signOut() {
  try {
    await activeAttempt.discardBeforeLogout(trainingAttemptId(route))
    await auth.logout()
  } catch { return }
  await router.replace('/login')
}
</script>

<template>
  <div class="shell" :class="{ collapsed: sidebarCollapsed }">
    <div class="app-bg" aria-hidden="true"><AtmosphereBackdrop /></div>
    <header class="topbar">
      <div class="topbar-start">
        <button class="menu-toggle" type="button" aria-label="切换导航" :aria-expanded="!sidebarCollapsed" @click="toggleNavigation">
          <svg width="15" height="10" viewBox="0 0 15 10" fill="none" aria-hidden="true">
            <path d="M0 1h15M0 5h15M0 9h15" stroke="currentColor" stroke-width="1.1" />
          </svg>
        </button>
        <RouterLink class="topbar-brand" :to="home">
          <i class="brand-mark" aria-hidden="true">言</i>
          <strong>言阶</strong>
          <span>InterviewLoop</span>
        </RouterLink>
      </div>
      <div class="topbar-account">
        <button class="theme-toggle" type="button" :aria-label="theme === 'dark' ? '切换到日间模式' : '切换到夜间模式'" @click="toggleTheme">
          <Sun v-if="theme === 'dark'" :size="15" :stroke-width="1.7" aria-hidden="true" />
          <Moon v-else :size="15" :stroke-width="1.7" aria-hidden="true" />
        </button>
        <span class="role">{{ roleLabel }}</span>
        <strong>{{ auth.user.value?.displayName }}</strong>
        <button class="signout" type="button" @click="signOut">退出</button>
      </div>
    </header>

    <aside class="sidebar">
      <nav class="nav" :aria-label="auth.user.value?.role === 'ADMIN' ? '管理导航' : '学员导航'">
        <RouterLink
          v-for="item in navItems"
          :key="item.to"
          :to="item.to"
          class="nav-link"
          :class="{ active: route.path === item.to || (item.to !== '/' && route.path.startsWith(item.to)) }"
        >
          <component :is="item.icon" :size="17" :stroke-width="1.7" aria-hidden="true" />
          <span>{{ item.label }}</span>
        </RouterLink>
      </nav>

      <div class="sidebar-foot">
        <div class="side-account">
          <img v-if="auth.user.value?.avatar" class="side-avatar-img" :src="auth.user.value.avatar" alt="">
          <span v-else class="side-avatar">{{ auth.user.value?.displayName?.slice(0, 1) }}</span>
          <span class="side-copy">
            <strong>{{ auth.user.value?.displayName }}</strong>
            <small>{{ roleLabel }}</small>
          </span>
        </div>
      </div>
    </aside>

    <main class="content"><slot /></main>
  </div>
</template>

<style scoped>
.app-bg { position: fixed; inset: 0; z-index: 0; pointer-events: none; }

.shell {
  position: relative;
  display: grid;
  grid-template-columns: 224px minmax(0, 1fr);
  grid-template-rows: 60px minmax(0, 1fr);
  min-height: 100vh;
  transition: grid-template-columns .22s var(--ease);
}
.shell.collapsed { grid-template-columns: 0 minmax(0, 1fr); }

/* ---------- 顶栏 ---------- */
.topbar {
  position: sticky;
  z-index: 30;
  top: 0;
  grid-column: 1 / -1;
  grid-row: 1;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 0 28px;
  border-bottom: 1px solid var(--border);
  background: color-mix(in srgb, var(--card) 80%, transparent);
  backdrop-filter: blur(18px) saturate(140%);
  -webkit-backdrop-filter: blur(18px) saturate(140%);
}
.topbar-start { display: flex; align-items: center; gap: 14px; }
.menu-toggle {
  display: grid;
  width: 34px;
  height: 34px;
  padding: 0;
  place-items: center;
  border: 0;
  border-radius: 9px;
  background: none;
  color: var(--text-3);
  cursor: pointer;
  transition: color .16s var(--ease), background .16s var(--ease);
}
.menu-toggle:hover { color: var(--text); background: var(--overlay-2); }
.topbar-brand { display: flex; align-items: center; gap: 10px; white-space: nowrap; }
.brand-mark {
  display: grid;
  width: 30px;
  height: 30px;
  place-items: center;
  border-radius: 9px;
  background: var(--grad-brand);
  color: #fff;
  font-size: 15px;
  font-style: normal;
  font-weight: 700;
  box-shadow: 0 6px 14px -6px var(--accent);
}
.topbar-brand strong { font-size: 17px; font-weight: 700; letter-spacing: .08em; }
.topbar-brand span { color: var(--text-3); font-size: 12px; letter-spacing: .06em; }
.topbar-account { display: flex; align-items: center; gap: 12px; color: var(--text-3); font-size: 13px; }
.topbar-account .role {
  padding: 3px 10px;
  border-radius: 999px;
  background: var(--accent-soft);
  color: var(--accent-strong);
  font-size: 12px;
  font-weight: 600;
}
.topbar-account strong { color: var(--text); font-size: 13.5px; font-weight: 600; }
.theme-toggle {
  display: grid;
  place-items: center;
  width: 34px;
  height: 34px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--card);
  color: var(--text-2);
  cursor: pointer;
  transition: border-color .16s var(--ease), color .16s var(--ease), background .16s var(--ease);
}
.theme-toggle:hover { border-color: var(--border-bright); color: var(--text); background: var(--card-2); }
.signout {
  padding: 6px 12px;
  border: 1px solid var(--border);
  border-radius: 9px;
  background: transparent;
  color: var(--text-2);
  cursor: pointer;
  font-size: 13px;
  transition: color .16s var(--ease), border-color .16s var(--ease), background .16s var(--ease);
}
.signout:hover { color: var(--danger); border-color: var(--danger); background: transparent; }

/* ---------- 侧栏 ---------- */
.sidebar {
  grid-column: 1;
  grid-row: 2;
  position: sticky;
  top: 60px;
  align-self: start;
  height: calc(100vh - 60px);
  display: flex;
  flex-direction: column;
  overflow-y: auto;
  padding: 20px 12px 16px;
  border-right: 1px solid var(--border);
  background: var(--card);
}
.nav { display: flex; flex-direction: column; gap: 4px; }
.nav-link {
  position: relative;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 14px;
  border-radius: 10px;
  color: var(--text-2);
  font-size: 14px;
  font-weight: 500;
  white-space: nowrap;
  transition: color .16s var(--ease), background .16s var(--ease);
}
.nav-link:hover { color: var(--text); background: var(--overlay-2); }
.nav-link.active { color: var(--accent-strong); background: var(--accent-soft); font-weight: 600; }
.nav-link.active::before {
  content: '';
  position: absolute;
  top: 50%;
  left: -12px;
  width: 4px;
  height: 20px;
  border-radius: 0 4px 4px 0;
  transform: translateY(-50%);
  background: var(--grad-brand);
}
.sidebar-foot {
  margin-top: auto;
  padding: 14px 6px 0;
  border-top: 1px solid var(--divider);
  white-space: nowrap;
}
.side-account { display: flex; align-items: center; gap: 10px; padding: 8px; border-radius: 12px; background: var(--card-2); }
.side-avatar-img { width: 34px; height: 34px; border-radius: 50%; object-fit: cover; }
.side-avatar {
  display: grid;
  width: 34px;
  height: 34px;
  flex: none;
  place-items: center;
  border-radius: 50%;
  background: var(--grad-brand);
  color: #fff;
  font-size: 13px;
  font-weight: 600;
}
.side-copy strong { display: block; color: var(--text); font-size: 13px; font-weight: 600; }
.side-copy small { display: block; margin-top: 2px; color: var(--text-3); font-size: 12px; }

.collapsed .nav-link { padding-inline: 0; opacity: 0; pointer-events: none; }
.collapsed .sidebar { padding-inline: 0; border-right: 0; }
.collapsed .sidebar-foot { opacity: 0; pointer-events: none; }

.content { grid-column: 2; grid-row: 2; min-width: 0; background: transparent; position: relative; z-index: 1; }
</style>
