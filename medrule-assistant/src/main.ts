// src/main.ts

import { createApp } from 'vue'
import { createPinia } from 'pinia' // 引入 Pinia 
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css' // 引入 Element Plus 样式
import * as ElementPlusIconsVue from '@element-plus/icons-vue'
import App from './App.vue'
import './assets/main.css' // 引入我们自己的全局样式

const app = createApp(App)
const pinia = createPinia() // 创建 Pinia 实例

// 注册所有 Element Plus 图标
for (const [key, component] of Object.entries(ElementPlusIconsVue)) {
  app.component(key, component)
}

app.use(pinia) // 使用 Pinia
app.use(ElementPlus)
app.mount('#app')