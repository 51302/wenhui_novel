import { createRouter, createWebHistory } from 'vue-router'
import Home from '../views/Home.vue'
import Login from '../views/Login.vue'
import Register from '../views/Register.vue'
import Creation from '../views/Creation.vue'
import WorkCircle from '../views/WorkCircle.vue'
import Reader from '../views/Reader.vue'
import VIP from '../views/VIP.vue'
import Bookshelf from '../views/Bookshelf.vue'
import MyProfile from '../views/MyProfile.vue'
import Settings from '../views/Settings.vue'
import Logs from '../views/Logs.vue'

const routes = [
  { path: '/', name: 'Home', component: Home, meta: { title: '首页' } },
  { path: '/login', name: 'Login', component: Login, meta: { title: '登录' } },
  { path: '/register', name: 'Register', component: Register, meta: { title: '注册' } },
  { path: '/creation', name: 'Creation', component: Creation, meta: { title: '创作中心', requiresAuth: true } },
  { path: '/circle', name: 'WorkCircle', component: WorkCircle, meta: { title: '作品圈' } },
  { path: '/vip', name: 'VIP', component: VIP, meta: { title: 'VIP' } },
  { path: '/reader/:novel_unique_id', name: 'Reader', component: Reader, meta: { title: '阅读' } },
  { path: '/bookshelf', name: 'Bookshelf', component: Bookshelf, meta: { title: '书架', requiresAuth: true } },
  { path: '/my', name: 'MyProfile', component: MyProfile, meta: { title: '我的', requiresAuth: true } },
  { path: '/settings', name: 'Settings', component: Settings, meta: { title: '设置' } },
  { path: '/logs', name: 'Logs', component: Logs, meta: { title: '系统日志' } },
  { path: '/:pathMatch(.*)*', redirect: '/' }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

export default router
