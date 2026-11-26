<script setup lang="ts">
import { onMounted, shallowRef } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import AuthForm, { type AuthSubmitPayload } from '@/components/auth/AuthForm.vue'
import { useAuth } from '@/composables/useAuth'
import { api, errorMessage } from '@/lib/api'
import type { ApiEnvelope } from '@/lib/types'

const router = useRouter()
const route = useRoute()
const auth = useAuth()
const error = shallowRef('')

// 演示账号由后端下发（生产环境返回空），凭证不写进前端产物
type DemoAccount = { role: string; email: string; password: string }
const demoAccounts = shallowRef<DemoAccount[]>([])
const prefill = shallowRef<{ email: string; password: string; token: number } | null>(null)

onMounted(async () => {
  try {
    const response = await api.get<ApiEnvelope<{ accounts: DemoAccount[] }>>('/auth/demo-accounts')
    demoAccounts.value = response.data.data.accounts ?? []
  } catch {
    // 后端没起来时不显示，登录表单照常可用
    demoAccounts.value = []
  }
})

function useDemoAccount(account: DemoAccount): void {
  prefill.value = { email: account.email, password: account.password, token: Date.now() }
}

const forgotOpen = shallowRef(false)
const forgotEmail = shallowRef('')
const forgotBusy = shallowRef(false)
const forgotNotice = shallowRef('')


async function submit(payload: AuthSubmitPayload) {
  error.value = ''
  try {
    if (payload.mode === 'register') {
      await auth.register(payload.email, payload.password, payload.displayName ?? '')
    } else {
      await auth.login(payload.email, payload.password)
    }
    const redirect = typeof route.query.redirect === 'string' ? route.query.redirect : '/'
    await router.replace(redirect)
  } catch (reason) {
    error.value = errorMessage(reason)
  }
}

async function submitPasswordRequest() {
  const email = forgotEmail.value.trim()
  if (!/^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$/.test(email)) {
    forgotNotice.value = '请输入正确的邮箱地址'
    return
  }
  forgotBusy.value = true
  forgotNotice.value = ''
  try {
    await api.post('/auth/password-reset/request', { email })
    forgotNotice.value = '如果这个邮箱已注册，重置链接会发送到邮箱；未开通邮件服务时会转交管理员处理。'
  } catch (reason) {
    forgotNotice.value = errorMessage(reason)
  } finally {
    forgotBusy.value = false
  }
}
</script>

<template>
  <main class="login-page">
    <section class="login-card">
      <header class="brand">
        <strong>言阶</strong>
        <span>InterviewLoop</span>
      </header>

      <h1>面试，是练出来的。</h1>
      <p class="lead">一场十分钟的模拟面试，换一份能落地的复盘。</p>

      <AuthForm
        :loading="auth.loading.value"
        :error="error"
        :prefill="prefill"
        @submit="submit"
        @clear-error="error = ''"
      />

      <div v-if="demoAccounts.length" class="demo-accounts">
        <p class="demo-title">演示账号</p>
        <ul>
          <li v-for="account in demoAccounts" :key="account.email">
            <span class="demo-role">{{ account.role }}</span>
            <span class="demo-cred"><b>{{ account.email }}</b> · {{ account.password }}</span>
            <button type="button" class="demo-fill" @click="useDemoAccount(account)">填入</button>
          </li>
        </ul>
      </div>

      <div class="forgot">
        <button class="forgot-link" type="button" @click="forgotOpen = !forgotOpen">{{ forgotOpen ? '收起' : '忘记密码？' }}</button>
        <div v-if="forgotOpen" class="forgot-form">
          <p>输入注册邮箱提交申请，管理员重置后会给你一个临时密码。</p>
          <input v-model.trim="forgotEmail" class="field" type="email" maxlength="254" placeholder="你的注册邮箱">
          <button class="button" type="button" :disabled="forgotBusy" @click="submitPasswordRequest">{{ forgotBusy ? '提交中…' : '提交申请' }}</button>
          <p v-if="forgotNotice" class="forgot-note">{{ forgotNotice }}</p>
        </div>
      </div>

    </section>
  </main>
</template>

<style scoped>
.login-page { min-height: 100vh; display: grid; place-items: center; padding: 40px 20px; background: var(--bg); }
.login-page {
  background:
    radial-gradient(1100px 520px at 12% -8%, rgba(153, 15, 250, .16), transparent 62%),
    radial-gradient(900px 460px at 92% 8%, rgba(230, 0, 118, .13), transparent 60%),
    var(--bg);
}
.login-card {
  width: min(440px, 100%);
  display: grid;
  gap: 18px;
  padding: 40px 36px;
  border: 1px solid var(--border);
  border-radius: 20px;
  background: var(--grad-sheen), var(--card);
  box-shadow: 0 1px 2px rgba(24, 20, 43, .04), 0 30px 60px -40px rgba(139, 31, 212, .55);
  position: relative;
  overflow: hidden;
}
.login-card::before {
  content: '';
  position: absolute;
  inset: 0 0 auto;
  height: 3px;
  background: var(--grad-hairline);
}
.brand { display: flex; align-items: baseline; gap: 10px; }
.brand strong {
  font-family: var(--font-ui);
  font-size: 20px;
  font-weight: 700;
  letter-spacing: .14em;
  background: var(--grad-text);
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
}
.brand span { color: var(--text-3); font-size: 12px; }
.login-card h1 { margin: 6px 0 0; font-size: 30px; font-weight: 650; letter-spacing: -.02em; line-height: 1.25; }
.login-card .lead { margin: -6px 0 4px; color: var(--text-3); font-size: 14px; line-height: 1.7; }
.login-card :deep(.form-heading) { display: none; }
.login-card :deep(.privacy-note) { display: none; }
.login-card :deep(.mode-switch) { background: var(--bg-2); }
.login-card :deep(.submit-button) { min-height: 46px; font-size: 14px; }
.forgot { display: grid; gap: 10px; justify-items: center; }
.forgot-link { border: 0; background: transparent; color: var(--text-3); font-size: 13px; cursor: pointer; }
.forgot-link:hover { color: var(--text); }
/* 演示账号：轻量分组，不抢主表单的注意力 */
.demo-accounts { border-top: 1px dashed var(--divider); padding-top: 16px; display: grid; gap: 10px; }
.demo-title { margin: 0; color: var(--text-3); font-size: 11px; letter-spacing: .18em; }
.demo-accounts ul { list-style: none; margin: 0; padding: 0; display: grid; gap: 8px; }
.demo-accounts li { display: grid; grid-template-columns: 46px minmax(0, 1fr) auto; align-items: center; gap: 10px; }
.demo-role { color: var(--text-3); font-size: 12px; }
.demo-cred { color: var(--text-2); font-size: 12px; font-family: var(--font-num); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.demo-cred b { color: var(--text); font-weight: 500; }
.demo-fill { padding: 3px 10px; border: 1px solid var(--border); border-radius: 999px; background: transparent; color: var(--text-2); font-size: 11.5px; cursor: pointer; transition: border-color .16s var(--ease), color .16s var(--ease), background .16s var(--ease); }
.demo-fill:hover { border-color: var(--accent); background: var(--accent-soft); color: var(--accent-strong); }
.forgot-form { width: 100%; display: grid; gap: 10px; padding: 14px; border: 1px solid var(--border); border-radius: 12px; background: var(--bg-2); }
.forgot-form p { margin: 0; color: var(--text-2); font-size: 13px; line-height: 1.7; }
.forgot-note { color: var(--text-3) !important; }
</style>
