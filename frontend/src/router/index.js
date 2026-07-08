import { createRouter, createWebHistory } from 'vue-router'
import Login from '../views/Login.vue'
import Register from '../views/Register.vue'
import Home from '../views/Home.vue'
import WorkCircle from '../views/WorkCircle.vue'
import Creation from '../views/Creation.vue'
import Reader from '../views/Reader.vue'
import VIP from '../views/VIP.vue'
import Settings from '../views/Settings.vue'

const routes = [
  { path: '/', component: Home },
  { path: '/login', component: Login },
  { path: '/register', component: Register },
  { path: '/circle', component: WorkCircle },
  { path: '/creation', component: Creation },
  { path: '/reader/:novel_unique_id', component: Reader, name: 'Reader' },
  { path: '/reader/:novel_unique_id/:chapter_unique_id', component: Reader, name: 'ReaderChapter' },
  { path: '/vip', component: VIP, name: 'VIP' },
  { path: '/settings', component: Settings, name: 'Settings' },
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

export default router
