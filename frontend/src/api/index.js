import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  timeout: 180000,
  withCredentials: true  // 发送 cookie
})

// 不需要再手动加 Authorization header，cookie 会自动带上
// 但保留从 localStorage 取 token 的逻辑作为兼容

api.interceptors.response.use(
  response => response.data,
  error => {
    if (error.response?.status === 401) {
      localStorage.removeItem('novel_user')
      // /auth/me 的 401 由 App.vue 自行处理（清空 user 显示登录按钮）
      // 其他 API 的 401 才跳转登录页
      const isAuthCheck = error.config?.url?.includes('/auth/me')
      if (!isAuthCheck && window.location.pathname !== '/login') {
        // 使用 replace 而非 href，避免用户点后退又回到 401 页面
        window.location.replace('/login')
      }
    }
    return Promise.reject(error)
  }
)

export default api
