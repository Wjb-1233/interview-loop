import { createApp } from 'vue'

import App from './App.vue'
import router from './router'
import './assets/main.css'
import { installErrorReporting, reportClientError } from './lib/errorReporting'
import { clearRetiredBrowserCache } from './lib/browserCache'

installErrorReporting()

const app = createApp(App)
app.config.errorHandler = (error, _instance, info) => {
  reportClientError(error, `vue.${info}: `)
  console.error(error)
}
app.use(router)
// Do not expose logout until the initial authenticated route is known.
void router.isReady().then(() => app.mount('#app'))

// 刷新令牌失效时统一回到登录页，避免每个页面各自弹「缺少刷新令牌」
window.addEventListener('auth:expired', () => {
  if (router.currentRoute.value.name === 'login') return
  void router.replace({ name: 'login', query: { redirect: router.currentRoute.value.fullPath } })
})

void clearRetiredBrowserCache()
