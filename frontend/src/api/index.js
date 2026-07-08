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
      if (window.location.pathname !== '/login') {
        window.location.href = '/login'
      }
    }
    return Promise.reject(error)
  }
)

export default api
